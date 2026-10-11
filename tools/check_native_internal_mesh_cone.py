"""Current internal-mesh cone traversal through an actual native extension.

Run standalone with a CPython 2.7 host extension or call run(backend) from the
existing native conformance job. No BigWorld runtime is faked by this checker.
"""
from __future__ import print_function

import copy
import gc
import math
import os
import random
import sys


def _source(name, path):
    if sys.version_info[0] < 3:
        import imp
        return imp.load_source(name, path)
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Calls(object):
    def __init__(self, backend):
        self.backend = backend
        self.admitted = 0
        self.rejected = 0

    def call(self, name, *args):
        assert name == 'projectile_math' and args[0] in (2, 3)
        # Containment now uses the ray frontier. Exercise it without counting
        # those calls as cone admission; cone-specific override gates still
        # assert that opcode 2 was not invoked.
        if args[0] == 3:
            return self.backend.projectile_math(*args)
        result = self.backend.projectile_math(*args)
        if result is None:
            self.rejected += 1
        else:
            self.admitted += 1
        return result


def _unit(values):
    length = math.sqrt(sum(v * v for v in values))
    return tuple(v / length for v in values)


def run(backend):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'src/res/scripts/client/gui/mods/offline_lan_0922/internal_mesh.py')
    mesh = _source('_native_cone_mesh', path)
    reference = _source('_reference_cone_mesh', path)
    reference._native_math = None
    calls = _Calls(backend)
    mesh._native_math = calls
    rng = random.Random(151310112)
    counts = {'triangle': 0, 'bvh': 0, 'boundary': 0, 'depth_search': 0,
              'mutable': 0, 'fallback': 0}

    def compare(primitive, apex, axis, depth, tangent, category, epsilon=None):
        old_epsilon = mesh._EPS, reference._EPS
        if epsilon is not None:
            mesh._EPS = reference._EPS = epsilon
        stats, expected_stats = {'triangles': 7}, {'triangles': 7}
        try:
            expected = reference.intersects_cone(
                primitive, apex, axis, depth, tangent, expected_stats, False)
            before = calls.admitted
            actual = mesh.intersects_cone(
                primitive, apex, axis, depth, tangent, stats, False)
            assert calls.admitted == before + 1, ('native fallback', category)
            assert type(actual) is bool and actual is expected, (
                category, primitive, apex, axis, depth, tangent, actual, expected)
            assert stats == expected_stats, ('traversal order/count', stats, expected_stats)
            counts[category] += 1
            return actual
        finally:
            mesh._EPS, reference._EPS = old_epsilon

    # Random isolated surfaces exercise clipping and stationary-point tests.
    for unused in range(5000):
        vertices = [tuple(rng.uniform(-5., 5.) for i in range(3)) for j in range(3)]
        primitive = mesh.prepare(vertices, [(0, 1, 2)])[0]
        apex = tuple(rng.uniform(-6., 6.) for i in range(3))
        axis = _unit(tuple(rng.uniform(-1., 1.) for i in range(3)))
        compare(primitive, apex, axis, rng.uniform(0., 15.),
                rng.uniform(0., 3.), 'triangle')

    cube_vertices = [(x, y, z) for x in (-1., 1.) for y in (-1., 1.) for z in (-1., 1.)]
    cube_faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5),
                  (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6),
                  (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    cube = mesh.prepare(cube_vertices, cube_faces)[0]
    assert cube['closed']
    n = 13
    grid_vertices = [(i * .3 - 1.8, j * .3 - 1.8, .25 * math.sin(i) * math.cos(j))
                     for i in range(n) for j in range(n)]
    grid_faces = []
    for i in range(n - 1):
        for j in range(n - 1):
            a = i * n + j
            grid_faces.extend(((a, a + n, a + 1), (a + 1, a + n, a + n + 1)))
    grid = mesh.prepare(grid_vertices, grid_faces)[0]
    assert not grid['closed'] and len(grid['triangles']) == 288
    for case in range(3000):
        primitive = cube if case % 2 else grid
        apex = tuple(rng.uniform(-6., 6.) for i in range(3))
        axis = _unit(tuple(rng.uniform(-1., 1.) for i in range(3)))
        compare(primitive, apex, axis, rng.uniform(0., 15.),
                rng.uniform(-.2, 2.), 'bvh')

    # The cone can cross the face interior when every vertex is outside.
    surface = mesh.prepare([(-4., -3., 2.), (4., -3., 2.), (0., 4., 2.)], [(0, 1, 2)])[0]
    assert compare(surface, (0., 0., 0.), (0., 0., 1.), 2., .01, 'boundary')
    for depth in (0., -0., 1.999999999, 2., 2.000000001, 5., -1.):
        for tangent in (0., 1.e-6, .1, 1., -1.):
            for epsilon in (0., 1.e-10, 1.e-8, 1.e-5):
                compare(surface, (0., 0., 0.), (0., 0., 1.), depth,
                        tangent, 'boundary', epsilon)
    for axis in ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.),
                 (0., 0., 0.), (.2, .3, .4), (1., 1., 1.)):
        compare(grid, (0., 0., -1.), axis, 3., .4, 'boundary')

    # Repeated minimum-depth queries use the same predicate and node order.
    for case in range(100):
        lo, hi = 0., 10.
        apex = (rng.uniform(-1., 1.), rng.uniform(-1., 1.), -3.)
        for unused in range(14):
            middle = (lo + hi) * .5
            hit = compare(grid, apex, (0., 0., 1.), middle, .4, 'depth_search')
            if hit:
                hi = middle
            else:
                lo = middle

    # Mutable geometry is read fresh. No id-based geometry cache is allowed.
    mutable = dict(surface)
    mutable['vertices'] = [list(v) for v in surface['vertices']]
    mutable['triangles'] = [list(f) for f in surface['triangles']]
    for i in range(100):
        mutable['vertices'][0][0] += .01
        mutable['triangles'][0][:] = list(reversed(mutable['triangles'][0]))
        mutable['bvh'] = mesh._tree(mutable['vertices'], mutable['triangles'], [0])
        compare(mutable, (0., 0., 0.), (0., 0., 1.), 3., .05, 'mutable')

    # Containment remains a separate, single call and can bypass all surfaces.
    for primitive, apex in ((cube, (0., 0., 0.)), (cube, (0., 0., -3.)),
                             (grid, (0., 0., 0.))):
        for known in (None, True, False):
            stats, expected_stats = {}, {}
            expected = reference.intersects_cone(primitive, apex, (0., 0., 1.), 4., .5, expected_stats, known)
            actual = mesh.intersects_cone(primitive, apex, (0., 0., 1.), 4., .5, stats, known)
            assert actual is expected and stats == expected_stats

    class FloatTrap(float):
        def __float__(self):
            raise AssertionError('native invoked conversion')
    class ListTrap(list):
        def __iter__(self):
            raise AssertionError('native invoked iteration')
    geometry = (surface['vertices'], surface['triangles'], surface['bvh'])
    query = ((0., 0., 0.), (0., 0., 1.), 3., .1, mesh._EPS)
    def invoke(owner, primitive, stats=None):
        return owner.intersects_cone(primitive, query[0], query[1], query[2],
                                     query[3], stats, False)

    invalid = [ListTrap(geometry), (ListTrap(geometry[0]), geometry[1], geometry[2])]
    for value in invalid:
        assert backend.projectile_math(2, value, query) is None
    for value in (FloatTrap(1.), float('nan'), float('inf'), 1.e100):
        assert backend.projectile_math(2, geometry, ((value, 0., 0.),) + query[1:]) is None
    # Invalid indices and cycles are rejected without unsafe pointer reads.
    invalid_faces = (((999, 1, 2),), ((-1, 1, 2),))
    for faces in invalid_faces:
        assert backend.projectile_math(2, (geometry[0], faces, geometry[2]), query) is None
    cyclic = [(-4., -4., 0.), (4., 4., 4.), None, None, ()]
    cyclic[2] = cyclic[3] = cyclic
    assert backend.projectile_math(2, (geometry[0], geometry[1], cyclic), query) is None

    # Rejection has not consumed a generator or incremented observable stats.
    generated = []
    def vertices():
        for v in geometry[0]:
            generated.append(v)
            yield v
    assert backend.projectile_math(2, (vertices(), geometry[1], geometry[2]), query) is None
    assert generated == []
    malformed = dict(surface, triangles=((999, 1, 2),))
    for owner in (reference, mesh):
        stats = {'triangles': 9}
        try:
            invoke(owner, malformed, stats)
        except IndexError:
            assert stats == {'triangles': 10}
        else:
            raise AssertionError('invalid index accepted')

    # Exact user-provided overrides and per-triangle counter side effects stay Python.
    original = mesh.triangle_intersects_cone
    try:
        mesh.triangle_intersects_cone = lambda *args: False
        before = calls.admitted
        assert not invoke(mesh, surface)
        assert calls.admitted == before
    finally:
        mesh.triangle_intersects_cone = original
    class Stats(dict):
        def __setitem__(self, key, value):
            self.writes.append((key, value))
            dict.__setitem__(self, key, value)
    stats = Stats(); stats.writes = []
    expected_stats = Stats(); expected_stats.writes = []
    before = calls.admitted
    assert invoke(mesh, grid, stats) is \
        invoke(reference, grid, expected_stats)
    assert stats == expected_stats and stats.writes == expected_stats.writes
    assert calls.admitted == before
    for initial in ({}, {'triangles': True}, {'triangles': 10 ** 30}):
        actual, expected = dict(initial), dict(initial)
        assert invoke(mesh, surface, actual) is \
            invoke(reference, surface, expected)
        assert actual == expected

    saved = copy.deepcopy(geometry)
    refs = [sys.getrefcount(v) for v in geometry]
    for unused in range(1000):
        assert backend.projectile_math(2, geometry, query) is not None
    gc.collect()
    assert refs == [sys.getrefcount(v) for v in geometry] and geometry == saved

    class OldBinary(object):
        def projectile_math(self, *args):
            return None
    for old in (None, _Calls(OldBinary())):
        mesh._native_math = old
        actual, expected = {}, {}
        assert invoke(mesh, grid, actual) is \
            invoke(reference, grid, expected)
        assert actual == expected
        counts['fallback'] += 1
    print('Native internal-mesh cone:', counts, 'admitted:', calls.admitted)
    return counts


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: check_native_internal_mesh_cone.py HOST_EXTENSION')
    sys.dont_write_bytecode = True
    if sys.version_info[0] < 3:
        import imp
        backend = imp.load_dynamic('offline_math_batch_native', sys.argv[1])
    else:
        backend = _source('offline_math_batch_native', sys.argv[1])
    run(backend)
