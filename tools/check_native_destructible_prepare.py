"""Full CPython 2.7 streamed-chunk preparation parity and lifecycle checks."""
from __future__ import print_function
import copy
import gc
import imp
import json
import math
import os
import random
import struct
import sys
import types


class Spy(object):
    def __init__(self, backend, old=False):
        self.backend, self.old = backend, old
        self.attempted = self.accepted = 0
    def __getattr__(self, name):
        return getattr(self.backend, name)
    def destr_query(self, handle, op, payload):
        if op != 8:
            return self.backend.destr_query(handle, op, payload)
        self.attempted += 1
        result = None if self.old else self.backend.destr_query(handle, op, payload)
        if result is not None:
            self.accepted += 1
        return result


def environment():
    from gui.mods.offline_lan_0922 import destructibles_sensor as real
    from gui.mods.offline_lan_0922 import native_destructibles as module
    sensor = types.ModuleType('_chunk_preparation_sensor')
    sensor._normalized_filename = real._normalized_filename
    sensor._STRING_TYPES = real._STRING_TYPES
    sensor._NATIVE_FILENAME_LAW = (sensor._normalized_filename, sensor._STRING_TYPES)
    sensor._destructible_catalog = None
    sensor._destructible_isolated_1513 = lambda *args: False
    area = types.ModuleType('AreaDestructibles')
    area.DESTR_TYPE_TREE, area.DESTR_TYPE_FALLING_ATOM = 1, 2
    area.DESTR_TYPE_FRAGILE, area.DESTR_TYPE_STRUCTURE = 3, 4
    return module, sensor, area


def registry(count, seed=7, fanout=4):
    rng = random.Random(seed)
    origins, extended = {}, {}
    rows = []
    for i in range(count):
        x, y, z = [rng.uniform(-25., 25.) for unused in range(3)]
        name = (None, '', ' \t\r\n', 'TREE\\Oak.MODEL', '/b.model', 'x')[i % 6]
        boxes = (((x, y, z), ((1.,0.,0.),(0.,1.,0.),(0.,0.,1.)), None),) if i % 3 else ()
        row = (i * 65537, x, y, z, (1,2,3,4,5,None)[i % 6], name,
               25., 100., boxes, rng.uniform(0., 4.))
        rows.append(row)
        cell = (int(math.floor(x / 8.)), int(math.floor(z / 8.)))
        origins.setdefault(cell, []).append(row)
        for part in range(fanout):
            extended.setdefault((cell[0] + part % 2, cell[1] + part // 2), []).append(row)
    return {'bins': origins, 'extended_bins': extended, 'count': count,
            'native_count': count, 'max_radius': 4., 'tree_health': {},
            'slot_diagnostics': {}}, rows


def responses(owner, chunk=22):
    pose = ((0.,0.,0.), .23, 0., 0., 0., None, (-2.,-1.,-4.), (2.,1.,4.))
    sweep = ((0.,0.,0.), ((32.,0.,0.),(0.,30.,0.),(0.,0.,32.)))
    return (owner.query(2, (float(chunk), (sweep,), 0.)),
            owner.query(1, (float(chunk), pose, 0., sweep)),
            owner.query(1, (float(chunk), pose, 2., sweep)),
            owner.query(1, (float(chunk), pose, -2., sweep)))


def outcome(function):
    try:
        return ('ok', function())
    except Exception as error:
        return ('error', type(error).__name__, str(error))


def run(backend):
    module, sensor, area = environment()
    previous_area = sys.modules.get('AreaDestructibles')
    sys.modules['AreaDestructibles'] = area
    spy = Spy(backend)
    baseline = module.Geometry(backend, sensor)
    current = module.Geometry(spy, sensor)
    counts = dict(registrations=0, cached=0, queries=0, fallbacks=0,
                  rejected=0, byte_names=0, ownership=0)
    def compare(value, chunk=22, admitted=True):
        before = spy.accepted
        left = baseline._reference_chunk(sensor, chunk, value)
        right = current.chunk(sensor, chunk, value)
        assert list(left) == list(right), ('dictionary order', list(left), list(right))
        assert set(left) == set(right)
        assert all(left[k] is right[k] for k in left), 'original row identity changed'
        a, b = responses(baseline, chunk), responses(current, chunk)
        assert a == b, ('native query parity', chunk, a, b)
        if admitted:
            assert spy.accepted == before + 1, ('native registration fallback', chunk)
        else:
            assert spy.accepted == before
        counts['registrations'] += 1
        counts['queries'] += len(a)
        before = spy.attempted
        assert current.chunk(sensor, chunk, value) is right
        assert spy.attempted == before, 'cached registration called C++ again'
        counts['cached'] += 1
        return right
    try:
        for case in range(300):
            value, unused = registry(case % 97, case, case % 7)
            compare(value, 22 if case % 2 else 4294967000)
            replacement, unused = registry(case % 53, case + 10000, case % 5)
            compare(replacement, 22 if case % 2 else 4294967000)
        # Test bytes.strip truth value exhaustively, including embedded NUL.
        for byte in range(256):
            row = (byte, 0.,0.,0.,1, chr(byte), 1.,1.,(),0.)
            value = {'bins': {(0,0): [row]}, 'extended_bins': {}}
            compare(value)
            counts['byte_names'] += 1
        counts['unicode_names'] = 0
        # Exhaust the UCS2 code-unit domain, including whitespace, NUL and
        # surrogates, against the original filename normalization owner.
        for codepoint in range(65536):
            row = (codepoint, 0.,0.,0.,1, unichr(codepoint), 1.,1.,(),0.)
            compare({'bins': {(0,0): [row]}, 'extended_bins': {}})
            counts['unicode_names'] += 1
        for filename in (u'', u'\u00a0', u'\u6811.model', u'  trees\\Oak.MODEL ',
                         u'\ud83c\udf33.model'):
            row = (1, 0.,0.,0.,1, filename, 1.,1.,(),0.)
            compare({'bins': {(0,0): [row]}, 'extended_bins': {}})
        class UnicodeSubclass(unicode):
            pass
        for filename in (7, UnicodeSubclass(u'tree.model')):
            row = (1, 0.,0.,0.,1, filename, 1.,1.,(),0.)
            compare({'bins': {(0,0): [row]}, 'extended_bins': {}}, admitted=False)
            counts['fallbacks'] += 1
        # Equal but distinct rows require original equality and last-row ownership.
        row = (2, 0.,0.,0.,1, 'a', 1.,1.,(),0.)
        other = tuple(list(row))
        assert other is not row and other == row
        mapping = compare({'bins': {(0,0): [row, other]}, 'extended_bins': {}}, admitted=False)
        assert mapping[2] is other
        counts['fallbacks'] += 1
        # Opaque fields which the original projection never reads stay opaque.
        class Trap(object):
            def __float__(self):
                raise AssertionError('native invoked numeric conversion')
            def __iter__(self):
                raise AssertionError('native invoked iteration')
            def __nonzero__(self):
                raise AssertionError('native invoked truth conversion')
        opaque = Trap()
        row = (3, 0.,0.,0.,1, 'a', opaque, opaque, (opaque,), 0.)
        compare({'bins': {(0,0): [row, row]}, 'extended_bins': {(0,0): [row]}})
        # Direct rejection must not modify the previously registered chunk.
        stable, rows = registry(8)
        compare(stable)
        saved = responses(current)
        good = rows[0]
        bad_rows = [list(good) for unused in range(5)]
        bad_rows[0][1] = opaque
        bad_rows[1][5] = opaque
        bad_rows[2][8] = opaque
        bad_rows[3][9] = float('nan')
        bad_rows[4][0] = opaque
        for bad in bad_rows:
            assert backend.destr_query(current.handle,8,
                (22., (((0,0), (bad,)),), (), (1,3,4,2))) is None
            assert responses(current) == saved
            counts['rejected'] += 1
        broken = {'bins': {(0,0): [good, tuple(list(good[:1]) + [99.] + list(good[2:]))]},
                  'extended_bins': {}}
        a = outcome(lambda: baseline._reference_chunk(sensor, 22, broken))
        b = outcome(lambda: current.chunk(sensor, 22, broken))
        assert a == b and a[0] == 'error' and a[1] == 'RuntimeError', (a,b)
        assert responses(current) == saved
        counts['fallbacks'] += 1
        # A generator is rejected without consuming it, then used exactly once.
        events = []
        def generate():
            for row in rows:
                events.append(row[0])
                yield row
        expected = baseline._reference_chunk(sensor, 22,
            {'bins': {(0,0): list(rows)}, 'extended_bins': {}})
        actual = current.chunk(sensor, 22,
            {'bins': {(0,0): generate()}, 'extended_bins': {}})
        assert actual == expected and events == [r[0] for r in rows]
        counts['fallbacks'] += 1
        # Custom filename policies remain authoritative.
        saved_normalizer = sensor._normalized_filename
        try:
            sensor._normalized_filename = lambda value: ''
            compare(registry(12)[0], admitted=False)
            counts['fallbacks'] += 1
        finally:
            sensor._normalized_filename = saved_normalizer
        # Older binaries do not know query 8 and still register via update 2.
        legacy_spy = Spy(backend, old=True)
        legacy = module.Geometry(legacy_spy, sensor)
        try:
            value, unused = registry(20)
            assert legacy.chunk(sensor,22,value) == baseline._reference_chunk(sensor,22,value)
            assert responses(legacy) == responses(baseline)
            assert legacy_spy.attempted == 1 and legacy_spy.accepted == 0
            counts['fallbacks'] += 1
        finally:
            legacy.close()
        # Replacement removes old numeric entries. Cache hits do not re-read
        # mutated registries; retirement and registry replacement own that law.
        populated, rows = registry(20)
        mapping = compare(populated)
        frozen = responses(current)
        populated['bins'].clear()
        assert current.chunk(sensor,22,populated) is mapping
        assert responses(current) == frozen
        compare({'bins': {}, 'extended_bins': {}})
        assert current.query(2, (22., (((0.,0.,0.), ((32.,0.,0.),(0.,30.,0.),(0.,0.,32.))),), 0.)) == ()
        row = (1, 0.,0.,0.,1, 'tree', 1.,1.,(),0.)
        payload = (22., (((0,0), (row,)),), (), (1,3,4,2))
        refs = sys.getrefcount(row)
        for unused in range(1000):
            result = backend.destr_query(current.handle, 8, payload)
            assert result[0][1] is row
            del result
        gc.collect()
        assert sys.getrefcount(row) == refs, 'native Store retained Python rows'
        counts['ownership'] += 1000
        handle = backend.destr_open()
        assert backend.destr_close(handle) == 1
        assert backend.destr_query(handle,8,payload) is None
        counts['rejected'] += 1
        print('Destructible preparation conformance:', json.dumps(counts, sort_keys=True))
        return counts
    finally:
        baseline.close()
        current.close()
        if previous_area is None:
            sys.modules.pop('AreaDestructibles', None)
        else:
            sys.modules['AreaDestructibles'] = previous_area


if __name__ == '__main__':
    assert len(sys.argv) == 2, 'usage: check_native_destructible_prepare.py HOST_EXTENSION'
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:0] = [os.path.join(root,'tools'), os.path.join(root,'src/res/scripts/client')]
    sys.dont_write_bytecode = True
    import native_simulation_motion_fixture
    run(imp.load_dynamic('offline_math_batch_native', sys.argv[1]))
