"""Current mesh ray and closest-surface frontiers through a native extension.

The regular entry point takes a CPython 2.7 host backend. Optional modules let
scratch host tests also compare against an independently pinned prior source.
No engine objects or invented client resource geometry are used here.
"""
from __future__ import print_function
import copy
import gc
import math
import random
import struct
import sys


def _ordered_sum(values, start=0):
    for value in values:
        start += value
    return start


def _bits(value):
    if type(value) is float:
        return ('float', struct.pack('<d', value))
    if isinstance(value, (tuple, list)):
        return (type(value).__name__, tuple(_bits(x) for x in value))
    if isinstance(value, dict):
        return ('dict', tuple(sorted((key, _bits(v)) for key, v in value.items())))
    if isinstance(value, set):
        return ('set', tuple(sorted(value)))
    return (type(value).__name__, value)


def fixtures(mesh):
    vertices = ((-1.,-1.,-1.),(1.,-1.,-1.),(1.,1.,-1.),(-1.,1.,-1.),
                (-1.,-1.,1.),(1.,-1.,1.),(1.,1.,1.),(-1.,1.,1.))
    faces = ((0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
             (3,7,6),(3,6,2),(0,4,7),(0,7,3),(1,2,6),(1,6,5))
    cube = mesh.prepare(vertices, faces)[0]
    tetra = mesh.prepare(((0.,0.,0.),(2.,0.,0.),(0.,2.,0.),(0.,0.,2.)),
                         ((0,2,1),(0,1,3),(0,3,2),(1,2,3)))[0]
    plane_vertices = []
    n = 12
    for y in range(n+1):
        for x in range(n+1):
            plane_vertices.append((x/3.-2., y/3.-2., .07*math.sin(x)*math.cos(y)))
    plane_faces = []
    for y in range(n):
        for x in range(n):
            i=y*(n+1)+x
            plane_faces.extend(((i,i+1,i+n+2),(i,i+n+2,i+n+1)))
    plane = mesh.prepare(plane_vertices, plane_faces)[0]
    open_cube = mesh.prepare(vertices, faces[:-2])[0]
    # Two disjoint closed solids, one combined diagnostic BVH: the space
    # between them must not become a fabricated occupied interval.
    joined_vertices = tuple((x+offset,y,z) for offset in (-2.,2.) for x,y,z in vertices)
    joined_faces = faces + tuple(tuple(i+8 for i in f) for f in faces)
    joined = dict(cube, vertices=joined_vertices, triangles=joined_faces,
                  orientations=cube['orientations']*2,
                  minimum=(-3.,-1.,-1.), maximum=(3.,1.,1.),
                  bvh=mesh._tree(joined_vertices, joined_faces, list(range(24))))
    return [cube, tetra, plane, open_cube, joined]


def run(backend, module=None, native=None, reference=None):
    if module is None:
        from gui.mods.offline_lan_0922 import internal_mesh as module
    if native is None:
        from gui.mods.offline_lan_0922 import native_math as native
    if reference is None:
        reference = module
    saved = (native._backend, native._attempted, module._native_math,
             reference._native_math)
    sum_owners = []
    for owner in (module,) if reference is module else (module, reference):
        sum_owners.append((owner, 'sum' in owner.__dict__, owner.__dict__.get('sum')))
        # 3.12+ compensated sum is not the supported game's ordered 2.7 sum.
        if sys.version_info >= (3, 12):
            owner.sum = _ordered_sum
    class Admission(object):
        def __init__(self):
            self.accepted = {}
        def projectile_math(self, op, *args):
            result = backend.projectile_math(op, *args)
            if result is not None:
                self.accepted[op] = self.accepted.get(op, 0) + 1
            return result
    admission = Admission()
    native._backend, native._attempted = admission, True
    reference._native_math = None
    module._native_math = native
    rng = random.Random(1513101134)
    counts = dict(ray=0, distance=0, intervals=0, contains=0, cone=0, special=0)

    def compare(name, args, stats=False, required=False):
        opcode = 3 if name == '_line_hits' else 4
        before = admission.accepted.get(opcode, 0)
        a = {'triangles': 5} if stats else None
        b = copy.deepcopy(a)
        kwargs = {'stats': a} if stats else {}
        error_a = error_b = None
        old_ref = reference._native_math
        reference._native_math = None
        expected = actual = None
        try:
            expected = getattr(reference, name)(*args, **kwargs)
        except Exception as error:
            error_a = type(error).__name__, str(error)
        finally:
            reference._native_math = old_ref
        module._native_math = native
        try:
            actual = getattr(module, name)(*args, **({'stats': b} if stats else {}))
        except Exception as error:
            error_b = type(error).__name__, str(error)
        assert error_a == error_b, (name, 'exceptions', args, error_a, error_b)
        if error_a is None:
            assert _bits(expected) == _bits(actual), (name, 'values', args, expected, actual)
        assert a == b, (name, 'triangle counts', a, b)
        if required:
            assert admission.accepted.get(opcode, 0) == before + 1, (name, 'native fallback', args)
        if name == 'distance' and error_a is None and expected[1] is not None:
            for vertex in args[1]['vertices']:
                if expected[1] is vertex:
                    assert actual[1] is vertex, ('vertex identity', expected, actual)
        return actual

    try:
        meshes = fixtures(module)
        for case in range(1800):
            mesh = meshes[case % len(meshes)]
            start = tuple(rng.uniform(-4.,4.) for unused in range(3))
            end = tuple(rng.uniform(-4.,4.) for unused in range(3))
            delta = module._sub(end, start)
            first, last = ((0.,1.) if case % 2 else (-float('inf'),float('inf')))
            compare('_line_hits', (mesh,start,delta,first,last), stats=True, required=True)
            counts['ray'] += 1
            # Force some inside samples as well as outside closest-surface walks.
            p = start if case % 3 else tuple(v*.2 for v in start)
            was_inside = reference.contains(p,mesh)
            compare('distance', (p,mesh), stats=True, required=not was_inside)
            counts['distance'] += 1
            compare('intervals', (start,end,mesh), stats=True)
            counts['intervals'] += 1
            compare('contains', (p,mesh))
            counts['contains'] += 1
            if case < 100:
                compare('intersects_cone', (mesh,p,(1.,0.,0.),2.,.6), stats=True)
                counts['cone'] += 1

        # Vertex/edge/coplanar/zero-ray and +/-epsilon seams; exact face order
        # and grouping also apply to the joined solids' empty middle interval.
        for mesh in meshes:
            for vertex in mesh['vertices'][:8]:
                for epsilon in (-1.e-8, -1.e-12, -0., 0., 1.e-12, 1.e-8):
                    p = (vertex[0]+epsilon, vertex[1], vertex[2])
                    for delta in ((0.,0.,0.),(1.,0.,0.),(1.e-15,0.,0.),(0.,0.,-1.)):
                        compare('_line_hits', (mesh,p,delta,-float('inf'),float('inf')),
                                stats=True, required=True)
                        counts['ray'] += 1
                    compare('distance', (p,mesh), stats=True)
                    counts['distance'] += 1
                    compare('intervals', (p,p,mesh), stats=True)
                    counts['intervals'] += 1
        cube = meshes[0]
        joined = meshes[-1]
        assert compare('intervals', ((-5.,0.,0.),(5.,0.,0.),joined)) == ((.2,.4),(.6,.8))
        moved = copy.deepcopy(cube)
        moved['closed'] = False
        moved['vertices'] = [list(v) for v in moved['vertices']]
        for unused in range(120):
            # Change the same live mesh's lists and rebuild only the test BVH.
            shift = rng.uniform(-1.,1.)
            for v in moved['vertices']:
                v[0] += shift
            moved['bvh'] = module._tree(moved['vertices'],moved['triangles'],list(range(12)))
            p = (3.,3.,3.)
            compare('distance', (p,moved), stats=True, required=True)
            counts['distance'] += 1
            compare('_line_hits', (moved,(-4.,0.,0.),(8.,0.,0.),0.,1.),stats=True,required=True)
            counts['ray'] += 1

        # Equidistant leaves must keep heap serial tie order and vertex objects.
        v = ((-1.,0.,0.),(-1.,1.,0.),(-1.,0.,1.),(1.,0.,0.),(1.,1.,0.),(1.,0.,1.))
        f = ((0,1,2),(3,4,5))
        l = ((-1.,0.,0.),(-1.,1.,1.),None,None,(0,))
        r = ((1.,0.,0.),(1.,1.,1.),None,None,(1,))
        equal = dict(cube, vertices=v, triangles=f, closed=False, orientations=None,
                     bvh=((-1.,0.,0.),(1.,1.,1.),l,r,()))
        out = compare('distance', ((0.,-1.,-1.),equal), stats=True, required=True)
        assert out[1] is v[0]
        equal['bvh'] = ((-1.,0.,0.),(1.,1.,1.),r,l,())
        out = compare('distance', ((0.,-1.,-1.),equal), stats=True, required=True)
        assert out[1] is v[3]
        counts['special'] += 2

        # Native rejection must replay neither partial counter mutations nor
        # custom conversions. The unchanged reference owns malformed errors.
        for bad_faces in (((99999,0,1),), ((0,1),), ((-1,0,1),)):
            bad = dict(cube, closed=False, triangles=bad_faces,
                       bvh=((-2.,-2.,-2.),(2.,2.,2.),None,None,(0,)))
            compare('_line_hits', (bad,(-4.,0.,0.),(8.,0.,0.),0.,1.),stats=True)
            compare('distance', ((3.,3.,3.),bad),stats=True)
            counts['special'] += 2
        for orientations in ((), (0,)*12, None):
            bad = dict(cube, orientations=orientations)
            compare('_line_hits', (bad,(-4.,.2,.1),(8.,0.,0.),0.,1.),stats=True)
            counts['special'] += 1
        empty = dict(cube, closed=False, triangles=(), vertices=(),
                     bvh=((0.,0.,0.),(0.,0.,0.),None,None,()))
        assert compare('distance', ((3.,3.,3.),empty),stats=True,required=True) == (float('inf'),None)
        counts['special'] += 1

        class Trap(list):
            def __len__(self):
                raise AssertionError('native invoked custom sequence')
            def __getitem__(self,key):
                raise AssertionError('native invoked custom sequence')
        raw = (cube['vertices'],cube['triangles'],cube['bvh'])
        assert backend.projectile_math(3,raw+(cube['orientations'],),(Trap(),(1.,0.,0.),0.,1.,1.e-8)) is None
        assert backend.projectile_math(4,(Trap(),raw[1],raw[2]),((3.,3.,3.),)) is None
        cycle = [(-2.,-2.,-2.),(2.,2.,2.),None,None,()]
        cycle[2] = cycle[3] = cycle
        cyclic = (cube['vertices'],cube['triangles'],cycle)
        assert backend.projectile_math(3,cyclic+(cube['orientations'],),((-4.,0.,0.),(8.,0.,0.),0.,1.,1.e-8)) is None
        assert backend.projectile_math(4,cyclic,((3.,3.,3.),)) is None
        counts['special'] += 4

        class Stats(dict):
            def __init__(self):
                dict.__init__(self); self.writes=[]
            def __setitem__(self,key,value):
                self.writes.append((key,value)); dict.__setitem__(self,key,value)
        for name, args in (('_line_hits',(cube,(-4.,.2,.1),(8.,0.,0.),0.,1.)),
                           ('distance',((3.,3.,3.),cube))):
            a,b = Stats(),Stats()
            reference._native_math = None
            expected=getattr(reference,name)(*args,**{'stats':a})
            module._native_math=native
            actual=getattr(module,name)(*args,**{'stats':b})
            assert _bits(expected)==_bits(actual) and a.writes==b.writes
            counts['special'] += 1

        # A caller-replaced containment decision is still consulted exactly once.
        old_contains=module.contains; calls=[]
        module.contains=lambda *args: calls.append(args) or False
        try:
            module.distance((3.,3.,3.),cube)
            assert len(calls)==1
        finally:
            module.contains=old_contains
        # Replaced numerical helpers cannot be bypassed by the C++ implementation.
        old_triangle=module._triangle_line
        module._triangle_line=lambda *args: None
        try:
            assert module._line_hits(cube,(-4.,0.,0.),(8.,0.,0.),0.,1.) == []
        finally:
            module._triangle_line=old_triangle
        counts['special'] += 2
        for epsilon in (0.,1.e-7,-1.e-10):
            olda,oldb=reference._EPS,module._EPS
            reference._EPS=module._EPS=epsilon
            try:
                compare('_line_hits',(cube,(-4.,.2,.1),(8.,0.,0.),0.,1.),stats=True,required=True)
            finally:
                reference._EPS,module._EPS=olda,oldb
            counts['special'] += 1

        held=(cube['vertices'],cube['triangles'],cube['bvh'],cube['vertices'][0])
        before=copy.deepcopy(cube)
        gc.collect()
        refs=tuple(sys.getrefcount(x) for x in held)
        for unused in range(1000):
            module._line_hits(cube,(-4.,.2,.1),(8.,0.,0.),0.,1.)
            module.distance((3.,3.,3.),cube)
        gc.collect()
        assert refs==tuple(sys.getrefcount(x) for x in held), (refs, tuple(sys.getrefcount(x) for x in held))
        assert _bits(before)==_bits(cube)
        native._backend=object()
        compare('_line_hits',(cube,(-4.,.2,.1),(8.,0.,0.),0.,1.),stats=True)
        compare('distance',((3.,3.,3.),cube),stats=True)
        counts['special'] += 3
        print('Mesh query conformance:', counts, 'bitwise results and counters passed')
        return counts
    finally:
        native._backend,native._attempted,module._native_math,reference._native_math=saved
        for owner,existed,value in sum_owners:
            if existed: owner.sum=value
            else: owner.__dict__.pop('sum',None)


if __name__ == '__main__':
    import os
    import imp
    if len(sys.argv) != 2:
        raise SystemExit('usage: check_native_internal_mesh_queries.py HOST_EXTENSION')
    root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:0]=[os.path.join(root,'tools'),os.path.join(root,'src/res/scripts/client')]
    sys.dont_write_bytecode=True
    import native_simulation_motion_fixture
    run(imp.load_dynamic('offline_math_batch_native',sys.argv[1]))
