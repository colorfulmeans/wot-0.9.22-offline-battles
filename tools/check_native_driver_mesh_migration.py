"""Current driver and complete mesh consumers through the real Python 2 C API.

WOT_NATIVE_BASELINE selects an independent pre-integration checkout. Supported
calls must enter native, and callback overrides must retain their original
Python behavior. These contracts do not establish Windows game rendering.
"""
from __future__ import print_function
import copy
import gc
import imp
import math
import os
import random
import struct
import sys
import time


def bits(value):
    if type(value) is float:
        return ('float', struct.pack('<d', value))
    if type(value) in (tuple, list):
        return (type(value).__name__, tuple(bits(item) for item in value))
    if type(value) is dict:
        return dict((key, bits(item)) for key, item in value.items())
    return type(value).__name__, value


def run(backend):
    from gui.mods.offline_lan_0922 import native_math
    from gui.mods.offline_lan_0922 import internal_mesh as mesh
    from gui.mods.offline_lan_0922 import internal_hit_layouts as layouts
    from gui.mods.offline_lan_0922.ai import driver
    old_backend, old_attempted, old_mesh_backend = (
        native_math._backend, native_math._attempted, mesh._native_math)
    native_math._backend, native_math._attempted, mesh._native_math = backend, True, native_math
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    baseline = os.environ.get('WOT_NATIVE_BASELINE', root)
    module_path = os.path.join(baseline, 'src/res/scripts/client/gui/mods/offline_lan_0922/internal_mesh.py')
    oracle = imp.load_source('_driver_mesh_migration_oracle', module_path)
    oracle._native_math = None
    rng = random.Random(2026101109)
    counts = dict(rank=0, probes=0, recovery=0, contains=0, intervals=0,
                  distance=0, cone_depth=0, consumer=0, fallback=0)

    def counter(method):
        return native_math.snapshot()[method]

    def rank_case(state, yaw, offsets=None, admitted=True):
        a, b = driver.LocalDriver(), driver.LocalDriver()
        if offsets is not None:
            a._CANDIDATE_OFFSETS = b._CANDIDATE_OFFSETS = offsets
        x, y = copy.deepcopy(state), copy.deepcopy(state)
        before = counter('driver_geometry')
        expected = a._reference_rank_yaw_candidates(x, yaw)
        actual = b._rank_yaw_candidates(y, yaw)
        assert bits(tuple(actual)) == bits(tuple(expected)), (state, yaw, actual, expected)
        assert bits(x) == bits(y), (x, y)
        if admitted:
            assert counter('driver_geometry') == before + 1, ('rank fallback', state, yaw)
        counts['rank'] += 1

    def mesh_case(name, args, with_stats=False):
        a, b = {'triangles': 7, 'keep': True}, {'triangles': 7, 'keep': True}
        expected = getattr(oracle, name)(*(args + (a,) if with_stats else args))
        before = counter('projectile_math')
        actual = getattr(mesh, name)(*(args + (b,) if with_stats else args))
        assert bits(actual) == bits(expected), (name, args, actual, expected)
        assert a == b, ('triangle counters', name, a, b)
        assert counter('projectile_math') == before + 1, ('consumer fallback', name, args)
        counts[name] += 1
        return actual

    vertices = [(-1.,-1.,-1.), (1.,-1.,-1.), (1.,1.,-1.), (-1.,1.,-1.),
                (-1.,-1.,1.), (1.,-1.,1.), (1.,1.,1.), (-1.,1.,1.)]
    faces = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
             (3,7,6),(3,6,2),(0,4,7),(0,7,3),(1,2,6),(1,6,5)]
    cube = oracle.prepare(vertices, faces)[0]
    plane = oracle.prepare([(-2.,0.,-2.),(2.,0.,-2.),(2.,0.,2.),(-2.,0.,2.)],
                           [(0,1,2),(0,2,3)])[0]
    torus_vertices, torus_faces = [], []
    major, minor = 12, 8
    for i in range(major):
        u = i * 2. * math.pi / major
        for j in range(minor):
            v = j * 2. * math.pi / minor
            torus_vertices.append(((2.+.5*math.cos(v))*math.cos(u),
                                   .5*math.sin(v), (2.+.5*math.cos(v))*math.sin(u)))
    for i in range(major):
        for j in range(minor):
            a, b = i*minor+j, ((i+1)%major)*minor+j
            c, d = ((i+1)%major)*minor+(j+1)%minor, i*minor+(j+1)%minor
            torus_faces.extend(((a,b,c),(a,c,d)))
    torus = oracle.prepare(torus_vertices, torus_faces)[0]
    shapes = (cube, plane, torus)
    try:
        assert oracle.contains((0.,0.,0.), cube)
        assert oracle.intervals((-3.,0.,0.), (3.,0.,0.), cube) == ((1./3.,2./3.),)
        assert not oracle.contains((0.,0.,0.), torus), 'torus hole must remain empty'
        for case in range(3000):
            now = rng.uniform(0., 500.)
            state = {'clock': now, 'failed_yaws': dict(
                (key, rng.choice((None, now, now-rng.random(), now+rng.random()*5.)))
                for key in rng.sample(list(range(24)), rng.randrange(25))),
                'escape_side_until': now+rng.choice((-1.,0.,1.)),
                'escape_side': rng.choice((-1.,0.,1.)), 'keep': ['unchanged']}
            rank_case(state, rng.uniform(-50.*math.pi,50.*math.pi))
        for yaw in (0., -0., math.pi, -math.pi, math.pi/24., -math.pi/24.):
            for delta in (-1.e-12, 0., 1.e-12):
                rank_case({'clock':10., 'failed_yaws':dict((i,10.) for i in range(24))},
                          yaw+delta, (0.,0.,.42,-.42,.78,-.78,2.*math.pi,-2.*math.pi))
        for case in range(100):
            state = {'clock':10.,'failed_yaws':{12:9.,13:11.},
                     'escape_side_until':11.,'escape_side':1.,
                     'collision_body': {'probe_identity': case}}
            yaw, cutoff = rng.uniform(-math.pi,math.pi), rng.randrange(1,16)
            traces = []
            for use_native in (False, True):
                native_math._backend = backend if use_native else None
                obj = driver.LocalDriver(); current = copy.deepcopy(state); trace=[]
                def pose(angle):
                    trace.append(('pose',angle,dict(current['failed_yaws'])))
                    return len(trace)>=cutoff
                def clear(angle):
                    trace.append(('clear',angle,dict(current['failed_yaws'])))
                    return True
                def static_hull_ahead(position, angle, peers, length, width, body=None):
                    assert body is current['collision_body'], 'physical pose lost before hull precheck'
                    return False
                obj._static_hull_ahead = static_hull_ahead
                result = obj._choose_yaw(current,yaw,clear,position=(0.,0.,0.),
                                         neighbours=[],pose_clear=pose)
                traces.append((result,current,trace))
            assert bits(traces[0]) == bits(traces[1]), ('probe order',traces)
            counts['probes'] += 1
        native_math._backend = backend
        for case in range(600):
            obj = driver.LocalDriver()
            position = (rng.uniform(-10.,10.),0.,rng.uniform(-10.,10.))
            yaw = rng.uniform(-math.pi,math.pi)
            peers = [dict(id=i+1, position=(rng.uniform(-20.,20.),
                         rng.uniform(-7.,7.),rng.uniform(-20.,20.)),
                         yaw=rng.uniform(-math.pi,math.pi),half_length=rng.uniform(1.,5.),
                         half_width=rng.uniform(.5,2.5)) for i in range(30)]
            state = obj._state(1,case%15,position)
            negative = obj._reference_recovery_occupancy(position,yaw,-1.,peers,3.5,1.7)
            positive = obj._reference_recovery_occupancy(position,yaw,1.,peers,3.5,1.7)
            expected = (-1. if negative<positive else 1. if positive<negative
                        else obj._fallback_recovery_side(state))
            before = counter('driver_geometry')
            actual = obj._select_recovery_side(state,position,yaw,peers,3.5,1.7)
            assert actual == expected and counter('driver_geometry') == before+1
            counts['recovery'] += 1
        for case in range(1500):
            shape = shapes[case%len(shapes)]
            point = tuple(rng.uniform(-3.,3.) for unused in range(3))
            end = tuple(rng.uniform(-3.,3.) for unused in range(3))
            mesh_case('contains',(point,shape))
            mesh_case('intervals',(point,end,shape),True)
            mesh_case('distance',(point,shape),True)
        for point in ((0.,0.,0.), (1.,1.,1.), (-1.,0.,0.), (1.+1.e-9,0.,0.),
                      (0,0,0), [-0.,0.,0.]):
            mesh_case('contains',(point,cube))
            mesh_case('intervals',(point,point,cube),True)
            mesh_case('distance',(point,cube),True)
        interior = (0.,0.,0.)
        assert mesh.distance(interior,cube)[1] is interior, 'inside tuple identity'
        corner = mesh.distance((9.,9.,9.),cube)[1]
        assert any(corner is point for point in cube['vertices']), 'original nearest vertex identity'
        for case in range(250):
            shape = shapes[case%len(shapes)]
            apex = (-4.,rng.uniform(-2.,2.),rng.uniform(-2.,2.))
            axis, depth, tangent = (1.,0.,0.), rng.uniform(.2,8.), rng.uniform(.05,1.5)
            expected = None
            if oracle.intersects_cone(shape,apex,axis,depth,tangent,apex_inside=False):
                low, high = 0., float(depth)
                for unused in range(14):
                    middle = (low+high)*.5
                    if oracle.intersects_cone(shape,apex,axis,middle,tangent,apex_inside=False):
                        high=middle
                    else: low=middle
                expected=high
            before=counter('projectile_math')
            raw=mesh.cone_entry_depth(shape,apex,axis,depth,tangent)
            assert raw is not None and counter('projectile_math')==before+1
            actual=raw[1] if raw[0] else None
            assert bits(expected)==bits(actual),('cone depth',expected,actual)
            counts['cone_depth']+=1
            record=oracle.distance(apex,shape)
            before=counter('projectile_math')
            actual=layouts._primitive_cone_entry({},shape,apex,axis,depth,tangent,
                                                 distance_record=record)
            assert bits(expected)==bits(actual),('entry consumer',expected,actual)
            assert counter('projectile_math')==before+1, 'consumer did not fuse depth search'
            counts['consumer']+=1
        original_length=layouts._vector_length
        try:
            def failed_length(value):
                raise ValueError('length override sentinel')
            layouts._vector_length=failed_length
            try:
                layouts._primitive_cone_entry({},cube,(-4.,0.,0.),(1.,0.,0.),8.,.5,
                    distance_record=(3.,(-1.,0.,0.)))
            except ValueError as error:
                assert str(error)=='length override sentinel'
            else:raise AssertionError('fused query bypassed a replaced helper')
            counts['fallback']+=1
        finally:layouts._vector_length=original_length
        original=mesh.contains
        try:
            mesh.contains=lambda point, shape:True
            before=counter('projectile_math')
            assert mesh.distance((3.,0.,0.),cube)==(0.,(3.,0.,0.))
            assert counter('projectile_math')==before
            counts['fallback']+=1
        finally:mesh.contains=original
        obj=driver.LocalDriver();events=[]
        def penalty(state,yaw):
            events.append(yaw)
            return .125
        obj._failure_penalty=penalty
        current={'clock':10.,'failed_yaws':{}}
        before=counter('driver_geometry')
        obj._rank_yaw_candidates(current,0.)
        assert len(events)==len(obj._CANDIDATE_OFFSETS)
        assert counter('driver_geometry')==before
        counts['fallback']+=1
        class Trap(object):
            def __float__(self):raise AssertionError('native conversion')
            def __iter__(self):raise AssertionError('native iteration')
        geometry=mesh._volume_geometry(cube)
        assert backend.projectile_math(5,geometry,(Trap(),1.e-8)) is None
        assert backend.projectile_math(6,geometry,((0.,0.,0.),Trap(),1.e-8)) is None
        assert backend.driver_geometry(9,(0.,10.,2.,0.,0.,math.pi,24),(Trap(),),()) is None
        node=[(-1.,-1.,-1.),(1.,1.,1.),None,None,()]
        node[2]=node;node[3]=node
        bad=list(geometry);bad[2]=node
        assert backend.projectile_math(5,tuple(bad),((0.,0.,0.),1.e-8)) is None
        # Preserve 06f4e1c's fix: deepcopy can share immutable vertex tuples.
        # Its legitimate references must exist before measuring native calls.
        frozen=copy.deepcopy(cube)
        gc.collect()
        refs=(sys.getrefcount(cube),sys.getrefcount(cube['vertices']))
        for unused in range(500):mesh.distance((2.,.5,0.),cube)
        gc.collect()
        after=(sys.getrefcount(cube),sys.getrefcount(cube['vertices']))
        assert refs==after,('retained native input reference',refs,after)
        assert cube==frozen
        class OldBinary(object):
            def projectile_math(self,*args):return None
            def driver_geometry(self,*args):return None
        native_math._backend=OldBinary()
        assert mesh.intervals((-3.,0.,0.),(3.,0.,0.),cube)==oracle.intervals((-3.,0.,0.),(3.,0.,0.),cube)
        rank_case({'clock':10.,'failed_yaws':{12:9.}},0.,admitted=False)
        counts['fallback']+=1
        native_math._backend=backend
        clock=getattr(time,'perf_counter',time.time)
        timings={}
        for name,args in (('contains',((.5,0.,0.),cube)),
                          ('intervals',((-3.,0.,0.),(3.,0.,0.),torus)),
                          ('distance',((1.8,.6,.1),torus))):
            samples=[]
            for owner in (oracle,mesh):
                values=[]
                function=getattr(owner,name)
                for trial in range(5):
                    started=clock()
                    for unused in range(250):function(*args)
                    values.append((clock()-started)/250.)
                samples.append(sorted(values)[len(values)//2])
            timings[name]=samples
        print('Current driver/mesh conformance:',counts)
        print('Complete consumer reference/native seconds:',timings)
        return counts
    finally:
        native_math._backend, native_math._attempted, mesh._native_math = (
            old_backend, old_attempted, old_mesh_backend)


if __name__ == '__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: check_native_driver_mesh_migration.py HOST_EXTENSION')
    sys.dont_write_bytecode=True
    sys.platform='linux'
    root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:0]=[os.path.join(root,'tools'),os.path.join(root,'src/res/scripts/client')]
    import native_simulation_motion_fixture
    run(imp.load_dynamic('offline_math_batch_native',sys.argv[1]))
