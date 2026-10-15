"""Incremental complete-call CPython 2.7 chunk preparation benchmark.

The reference already commits to the existing native geometry Store. Fixtures
are synthetic registration/reload work, not per-frame or gameplay timings.
"""
from __future__ import print_function
import gc
import imp
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT,'tools'), os.path.join(ROOT,'src/res/scripts/client')]
sys.dont_write_bytecode = True
import native_simulation_motion_fixture
from check_native_destructible_prepare import environment, registry, responses


def median(function, loops):
    results = []
    for unused in range(7):
        gc.collect()
        started = time.clock()
        for iteration in range(loops):
            function()
        results.append((time.clock() - started) * 1.e6 / loops)
    return sorted(results)[len(results) // 2]


def run(backend):
    module, sensor, area = environment()
    previous = sys.modules.get('AreaDestructibles')
    sys.modules['AreaDestructibles'] = area
    reference, native = module.Geometry(backend,sensor), module.Geometry(backend,sensor)
    rows = []
    try:
        for count, fanout, loops in ((1,0,1000),(32,4,250),(256,6,80),(1024,8,20)):
            source, unused = registry(count, seed=count, fanout=fanout)
            def old():
                reference.chunks.clear()
                return reference._reference_chunk(sensor,22,source)
            def new():
                native.chunks.clear()
                return native.chunk(sensor,22,source)
            a, b = old(), new()
            assert list(a) == list(b) and all(a[k] is b[k] for k in a)
            assert responses(reference) == responses(native)
            before, after = median(old,loops), median(new,loops)
            row = dict(scene='registration', items=count, extended_fanout=fanout,
                       previous_us=before, current_us=after, ratio=before/after)
            rows.append(row)
            print(json.dumps(row,sort_keys=True))
        # Cached calls are the per-frame path. No large admission scan may be
        # moved above their existing identity-cache return.
        source, unused = registry(1024)
        reference._reference_chunk(sensor,22,source)
        native.chunk(sensor,22,source)
        a = median(lambda: reference._reference_chunk(sensor,22,source), 20000)
        b = median(lambda: native.chunk(sensor,22,source), 20000)
        row = dict(scene='cached',items=1024,previous_us=a,current_us=b,ratio=a/b)
        rows.append(row)
        print(json.dumps(row,sort_keys=True))
        return rows
    finally:
        reference.close()
        native.close()
        if previous is None:
            sys.modules.pop('AreaDestructibles',None)
        else:
            sys.modules['AreaDestructibles'] = previous


if __name__ == '__main__':
    assert len(sys.argv) == 3, 'usage: benchmark_native_destructible_prepare.py HOST_EXTENSION OUTPUT_JSON'
    backend = imp.load_dynamic('offline_math_batch_native',sys.argv[1])
    rows = run(backend)
    with open(sys.argv[2],'w') as output:
        json.dump({'units':'microseconds','samples':7,'rows':rows,
                   'gameplay_measurement':False},output,indent=2,sort_keys=True)
        output.write('\n')
