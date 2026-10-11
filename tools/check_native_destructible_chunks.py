"""Current swept-hull chunk planning through the complete CPython 2.7 host.

The tiny separately loaded Vector3 model provides only the reviewed float32
constructor/index contract. This cannot establish #1513 in-game admission.
"""
from __future__ import print_function
import gc
import math
import os
import random
import struct
import sys
import types

MAPPER_SOURCE = '''
_INV_CHUNK_RANGE = .01
def chunkIDFromPosition(position):
    return chunkIDFromChunkIndexes(*chunkIndexesFromPosition(position))
def chunkIndexesFromPosition(position):
    return (int(math.floor(position[0] * _INV_CHUNK_RANGE)),
            int(math.floor(position[2] * _INV_CHUNK_RANGE)))
def chunkIDFromChunkIndexes(x, z):
    return ((x + 127) << 8) | (z + 127)
'''


def load_extension(name, path):
    if sys.version_info[0] < 3:
        import imp
        return imp.load_dynamic(name, path)
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture():
    path = os.environ.get('WOT_NATIVE_CHUNK_VECTOR')
    if not path:
        raise RuntimeError('WOT_NATIVE_CHUNK_VECTOR must name the test Vector3 extension')
    module = load_extension('native_chunk_vector', path)
    cache, area, engine_math = [types.ModuleType(n) for n in
                              ('DestructiblesCache', 'AreaDestructibles', 'Math')]
    cache.math = math
    eval(compile(MAPPER_SOURCE, '<reviewed-chunk-mapper>', 'exec'), cache.__dict__)
    area.chunkIDFromPosition = cache.chunkIDFromPosition
    engine_math.Vector3 = module.Vector3
    return cache, area, engine_math


def box(x, z, length=3.5, width=1.7, yaw=0., y=0., fourth=None):
    sy, cy = math.sin(yaw), math.cos(yaw)
    axes = [(cy * width, 0., -sy * width), (0., 1.3, 0.),
            (sy * length, 0., cy * length)]
    if fourth is not None:
        axes.append(fourth)
    return ((x, y, z), tuple(axes))


def run(backend):
    from gui.mods.offline_lan_0922 import native_math
    from gui.mods.offline_lan_0922 import native_destructibles as adapter
    from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
    previous_backend, previous_attempted = native_math._backend, native_math._attempted
    names = ('DestructiblesCache', 'AreaDestructibles', 'Math')
    previous_modules = dict((name, sys.modules.get(name)) for name in names)
    previous_radius = sensor._SOLID_CONTACT_RADIUS_1513
    previous_chunk = sensor._DESTRUCTIBLE_CHUNK_METRES_1513
    counters = dict(queries=0, fallback=0, callback_traces=0, rejections=0)
    cache, area, engine_math = fixture()
    for name, module in zip(names, (cache, area, engine_math)):
        sys.modules[name] = module
    native_math._backend, native_math._attempted = backend, True
    rng = random.Random(151310112)
    try:
        assert adapter._chunk_mapper_1513(area), 'fixture did not satisfy the existing mapper contract'
        assert adapter._chunk_vector_1513(engine_math), 'test native Vector3 gate did not admit'

        def compare(values, admitted=True):
            before = native_math.snapshot()['destr_required_chunks']
            expected = sensor._reference_tree_motion_required_chunks_1513(values)
            actual = sensor._tree_motion_required_chunks_1513(values)
            assert actual == expected, (values, actual, expected)
            assert native_math.snapshot()['destr_required_chunks'] == before + int(admitted), (
                'unexpected native admission', values, admitted)
            counters['queries' if admitted else 'fallback'] += 1
            return actual

        for case in range(3000):
            values = []
            x, z = rng.uniform(-1900., 1900.), rng.uniform(-1900., 1900.)
            for i in range(rng.randrange(1, 9)):
                values.append(box(x + i * .9, z + i * .7,
                    rng.uniform(.1, 15.), rng.uniform(.1, 8.),
                    rng.uniform(-math.pi, math.pi), rng.uniform(-50., 50.),
                    (rng.uniform(-4., 4.), rng.uniform(-2., 2.), rng.uniform(-4., 4.))))
            compare(values)
            if case < 100:
                values[0] = box(100., -100., rng.uniform(1., 15.), 4.)
                compare(values)
        for boundary in (-1200., -200., -100., 0., 100., 200., 1200.):
            bits = struct.unpack('<I', struct.pack('<f', boundary))[0]
            around = [boundary - 1.e-5, boundary, boundary + 1.e-5]
            if boundary:
                around += [struct.unpack('<f', struct.pack('<I', bits + d))[0]
                           for d in (-1, 1)]
            for x in around:
                for z in around:
                    for yaw in (0., .3, -1.2):
                        compare([box(x, z, .5, .5, yaw)])
        compare([], admitted=False)
        for length in (799.499999, 799.5, 799.500001, 1600.):
            compare([box(0., 0., length, .5)])
        for radius in (-.1, 0., .5, 1.25):
            for chunk_size in (25., 100., 150., -100.):
                sensor._SOLID_CONTACT_RADIUS_1513 = radius
                sensor._DESTRUCTIBLE_CHUNK_METRES_1513 = chunk_size
                compare([box(99.5, -100.5, 9., 3., .12)])
        sensor._SOLID_CONTACT_RADIUS_1513 = previous_radius
        sensor._DESTRUCTIBLE_CHUNK_METRES_1513 = previous_chunk

        # The original helper body is independent, not a modified native oracle.
        from collections import defaultdict
        traces = defaultdict(list)
        probe = [box(0., 0., 4., 2.)]
        original = area.chunkIDFromPosition
        for failure in (False, True):
            def mapper(position):
                values = tuple(position[i] for i in range(3))
                traces['active'].append(values)
                if failure:
                    raise ValueError('mapper failure remains pending')
                return 17
            area.chunkIDFromPosition = mapper
            for call in (sensor._reference_tree_motion_required_chunks_1513,
                         sensor._tree_motion_required_chunks_1513):
                traces['active'] = []
                result = call(probe)
                traces['runs'].append((result, tuple(traces['active'])))
            assert traces['runs'][-1] == traces['runs'][-2]
            counters['callback_traces'] += 1
        area.chunkIDFromPosition = original

        # A custom constructor is never bypassed even with the pinned mapper.
        original_vector = engine_math.Vector3
        vector_calls = []
        def vector(x, y, z):
            vector_calls.append((x, y, z))
            return original_vector(x, y, z)
        engine_math.Vector3 = vector
        before = native_math.snapshot()['destr_required_chunks']
        actual = sensor._tree_motion_required_chunks_1513(probe)
        first = list(vector_calls)
        vector_calls[:] = []
        expected = sensor._reference_tree_motion_required_chunks_1513(probe)
        assert actual == expected and vector_calls == first and first
        assert native_math.snapshot()['destr_required_chunks'] == before
        engine_math.Vector3 = original_vector
        counters['callback_traces'] += 1

        old_bounds = sensor._box_xz_bounds
        try:
            sensor._box_xz_bounds = lambda b: (-2., 2., -3., 3.)
            compare(probe, admitted=False)
        finally:
            sensor._box_xz_bounds = old_bounds
        old_samples = sensor._tree_motion_axis_samples_1513
        try:
            sensor._tree_motion_axis_samples_1513 = lambda low, high: None
            compare(probe, admitted=False)
        finally:
            sensor._tree_motion_axis_samples_1513 = old_samples
        area.chunkIDFromPosition = None
        compare(probe, admitted=False)
        area.chunkIDFromPosition = original
        for x in (-13000., 13000.):
            compare([box(x, 0.)], admitted=False)

        cache.int = lambda value: int(value) + 1
        compare(probe, admitted=False)
        del cache.int
        old_floor = math.floor
        try:
            math.floor = lambda value: old_floor(value)
            compare(probe, admitted=False)
        finally:
            math.floor = old_floor
        cache._INV_CHUNK_RANGE = .02
        compare(probe, admitted=False)
        cache._INV_CHUNK_RANGE = .01

        class Trap(object):
            def __float__(self): raise AssertionError('native called conversion')
            def __abs__(self): raise AssertionError('native called absolute value')
            def __iter__(self): raise AssertionError('native called iteration')
        class SequenceTrap(list):
            def __iter__(self): raise AssertionError('native iterated custom sequence')
            def __len__(self): raise AssertionError('native measured custom sequence')
        bad = [Trap(), SequenceTrap(probe), [((Trap(), 0., 0.), ())],
               [((0., 0., 0.), ((0., 0., Trap()),))]]
        for value in bad:
            assert backend.destr_required_chunks(value, (.5, 100.)) is None
            counters['rejections'] += 1
        for tuning in ((.5, 0.), (float('nan'), 100.), (.5, float('inf')),
                       (.5, Trap())):
            assert backend.destr_required_chunks(probe, tuning) is None
            counters['rejections'] += 1
        # Over-budget geometry does not read a later malformed entry.
        assert backend.destr_required_chunks([box(0., 0., 1700.), Trap()], (.5,100.)) == (2,())
        seen = []
        def generated():
            seen.append(1)
            yield probe[0]
        assert sensor._tree_motion_required_chunks_1513(generated()) == \
            sensor._reference_tree_motion_required_chunks_1513(probe)
        assert seen == [1]
        counters['fallback'] += 1
        references = sys.getrefcount(probe[0])
        saved = repr(probe)
        for unused in range(1000):
            assert backend.destr_required_chunks(probe, (.5,100.))[0] == 0
        gc.collect()
        assert sys.getrefcount(probe[0]) == references and repr(probe) == saved
        native_math._backend = object()
        compare(probe, admitted=False)
        print('Destructible required-chunk conformance:', counters)
        return counters
    finally:
        native_math._backend, native_math._attempted = previous_backend, previous_attempted
        sensor._SOLID_CONTACT_RADIUS_1513 = previous_radius
        sensor._DESTRUCTIBLE_CHUNK_METRES_1513 = previous_chunk
        for name, previous in previous_modules.items():
            if previous is None: sys.modules.pop(name, None)
            else: sys.modules[name] = previous


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:0] = [os.path.join(root, 'tools'), os.path.join(root, 'src/res/scripts/client')]
    if len(sys.argv) != 2:
        raise SystemExit('usage: check_native_destructible_chunks.py FULL_HOST_EXTENSION')
    run(load_extension('offline_math_batch_native', sys.argv[1]))
