"""Measure public helper overhead, including regressions; not game latency.

Usage: python tools/benchmark_native_projectile_cursor.py EXTENSION PRIOR_SOURCE OUTPUT_JSON
Seven alternating-order samples; units are microseconds per full public call.
"""
from __future__ import print_function
import json
import os
import sys
import time
from check_native_projectile_cursor import load


def main(extension, prior_path, output):
    root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source=os.path.join(root,'src/res/scripts/client/gui/mods/offline_lan_0922')
    prior=load('_cursor_benchmark_prior',prior_path);prior._native_math=None
    current=load('_cursor_benchmark_current',os.path.join(source,'projectile_runtime.py'))
    adapter=load('_cursor_benchmark_adapter',os.path.join(source,'native_math.py'))
    adapter._backend=load('offline_math_batch_native',extension);adapter._attempted=True
    current._native_math=adapter
    clock=getattr(time,'perf_counter',time.time)
    results=[]
    def measure(name,first,second,iterations):
        assert first()==second(),name
        samples=[[],[]];functions=(first,second)
        for sample in range(7):
            for index in ((0,1) if sample%2==0 else (1,0)):
                start=clock()
                for unused in range(iterations):functions[index]()
                samples[index].append((clock()-start)*1.e6/iterations)
        a,b=sorted(samples[0])[3],sorted(samples[1])[3]
        results.append(dict(operation=name,prior_us=a,native_us=b,ratio=a/b,
                            prior_samples_us=samples[0],native_samples_us=samples[1]))
    for name,args in (
        ('projectile_range_distance',({'start':(1.,2.,3.)},(40.,50.,100.))),
        ('trajectory_position',((1.,2.,3.),(1200.,10.,0.),(0.,-9.81,0.),.1)),
        ('lerp3',((1.,2.,3.),(100.,2.,80.),.2))):
        first,second=getattr(prior,name),getattr(current,name)
        measure(name,lambda:first(*args),lambda:second(*args),20000)
    for n in (1,4,64,640):
        measure('substeps_'+str(n),
                lambda:list(prior.substep_boundaries(0.,n*.05,.05)),
                lambda:list(current.substep_boundaries(0.,n*.05,.05)),1000)
    report=dict(python=sys.version,samples=7,results=results,
                scope='Isolated helpers, not the state manager, engine or game latency.')
    with open(output,'w') as stream:json.dump(report,stream,indent=2,sort_keys=True)
    for row in results:
        print('%s: %.5f -> %.5f us; %.3fx' % (
            row['operation'],row['prior_us'],row['native_us'],row['ratio']))


if __name__=='__main__':
    sys.dont_write_bytecode=True
    if len(sys.argv)!=4:raise SystemExit('usage: benchmark_native_projectile_cursor.py EXTENSION PRIOR_SOURCE OUTPUT_JSON')
    main(*sys.argv[1:])
