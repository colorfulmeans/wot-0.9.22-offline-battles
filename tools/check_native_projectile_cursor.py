"""Conformance for remaining projectile numeric helpers, not the game ABI.

Usage: python tools/check_native_projectile_cursor.py HOST_EXTENSION [PRIOR_SOURCE]
The driver conformance runner calls run(backend) on the actual Python 2.7 host.
Optional isolated-harness controls exercise allocation and diagnostic cleanup.
"""
from __future__ import print_function
import gc
import itertools
import json
import os
import random
import struct
import sys


def load(name, path):
    if sys.version_info[0] < 3:
        import imp
        return imp.load_dynamic(name, path) if path.endswith(('.so', '.pyd')) else imp.load_source(name, path)
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bits(value):
    if isinstance(value, float):
        return ('float', struct.pack('<d', value))
    if isinstance(value, (tuple, list)):
        return (type(value).__name__, tuple(bits(v) for v in value))
    return (type(value).__name__, value)


def outcome(function, args, generator=False):
    try:
        value = function(*args)
        return ('ok', list(value) if generator else value)
    except (TypeError, ValueError, OverflowError, IndexError, KeyError) as error:
        return ('error', type(error).__name__, str(error))


def run(backend, reference_path=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = os.path.join(root, 'src/res/scripts/client/gui/mods/offline_lan_0922')
    adapter = load('_cursor_adapter', os.path.join(source, 'native_math.py'))
    module = load('_cursor_under_test', os.path.join(source, 'projectile_runtime.py'))
    reference = load('_cursor_reference', reference_path) if reference_path else module
    adapter._backend, adapter._attempted = backend, True
    module._native_math = adapter
    if reference_path:
        reference._native_math = None
    rng = random.Random(15133235)
    counts = dict(numeric=0, chords=0, moving=0, intervals=0, boundaries=0,
                  fallback=0, allocations=0)

    def admitted():
        return adapter.snapshot()['projectile_math']

    def check(name, args, generator=False, supported=True):
        prior = getattr(reference, name if reference_path else '_reference_' + name)
        before = admitted()
        expected = outcome(prior, args, generator)
        assert admitted() == before, 'reference unexpectedly dispatched native'
        actual = outcome(getattr(module, name), args, generator)
        assert bits(actual) == bits(expected), (name, args, actual, expected)
        if supported:
            calls = (len(actual[1]) + 63) // 64 if generator else 1
            assert admitted() == before + calls, ('silent native fallback', name)
        if generator:
            counts['intervals'] += 1
            counts['boundaries'] += len(actual[1]) if actual[0] == 'ok' else 0
        else:
            counts['numeric' if supported else 'fallback'] += 1

    for case in range(10000):
        a,b,c,d = [tuple(rng.uniform(-2500.,2500.) for unused in range(3)) for j in range(4)]
        t,u = rng.uniform(-1.,10.),rng.uniform(-1.,2.)
        check('projectile_range_distance', ({'start':a, 'payload':{'range_origin':b}},c))
        check('trajectory_position', (a,b,c,t))
        check('lerp3', (a,b,u))
        if case < 250:
            check('substep_boundaries', (u,t,rng.choice((.001,.013,.05,.2))), True)
        chord = (a,b,c,0.,max(0.,u),max(0.,u)+.05,100.,rng.uniform(0.,110.))
        expected=module._reference_prepare_chord(*chord)
        before=admitted(); actual=module.prepare_chord(*chord)
        assert bits(actual)==bits(expected) and admitted()==before+1
        counts['chords']+=1
        args=(a,b,c,d,u,t)
        expected=module._reference_compensate_segment_for_moving_target(*args)
        before=admitted();actual=module.compensate_segment_for_moving_target(*args)
        assert bits(actual)==bits(expected) and admitted()==before+1
        counts['moving']+=1

    zero,unit=(0.,0.,0.),(0.,1.,0.)
    for value in (-0.,0.,1.e-320,-1.e-320,1.e-12,-1.e-12,None,False,True):
        check('trajectory_position',(zero,unit,zero,value))
        check('lerp3',(zero,unit,value))
    for point in ((-0.,0.,-0.),(1.e-320,0.,0.),(1.e-12,-1.e-12,0.)):
        check('projectile_range_distance',({'start':zero},point))
    for end in (0.,1.e-9,1.e-9+1.e-20,.01,.05,3.2,3.25,10.,50.):
        check('substep_boundaries',(0.,end,.05),True)
    for step in (None,False,-1.,0.,.0001,.001,.05,.2):
        check('substep_boundaries',(-1.,4.,step),True)
    for value in (None,(),(1.,),(1.,2.),'xyz',(0.,float('nan'),1.),(0.,float('inf'),1.)):
        check('trajectory_position',(value,unit,zero,.2),supported=False)
        check('lerp3',(value,unit,.2),supported=False)
    for elapsed in ('not a number',float('nan'),float('inf')):
        check('trajectory_position',(zero,unit,zero,elapsed),supported=False)
    check('projectile_range_distance',({'payload':{'range_origin':None}},unit),supported=False)
    class Trap(object):
        def __float__(self): raise AssertionError('native invoked conversion')
        def __iter__(self): raise AssertionError('native invoked iteration')
    class SequenceTrap(list):
        def __len__(self): raise AssertionError('native invoked length')
        def __getitem__(self,key): raise AssertionError('native invoked indexing')
    assert backend.projectile_math(32,(Trap(),unit),()) is None
    assert backend.projectile_math(33,(zero,unit,zero),(Trap(),)) is None
    assert backend.projectile_math(34,(SequenceTrap(unit),zero),(.2,)) is None
    assert backend.projectile_math(35,(),(1.e20,1.e20+1.e10,.05)) is None
    for op in (-1,31,36,1.e100,Trap()):
        assert backend.projectile_math(op,(),()) is None
    conversions=[]
    class Number(object):
        def __float__(self): conversions.append(1); return 2.
    class State(dict):
        def get(self,key,*rest): conversions.append(key); return dict.get(self,key,*rest)
    assert module.projectile_range_distance(State(start=(Number(),0.,0.)),zero)==2.
    assert conversions==['payload',1]
    conversions[:]=[]
    gen=module.substep_boundaries(Number(),6.,0.)
    assert not conversions and next(gen)==(2.,2.05)
    module.PROJECTILE_MAX_SUBSTEP_SECONDS=.001
    tail=list(gen);module.PROJECTILE_MAX_SUBSTEP_SECONDS=.05
    prior=getattr(reference,'substep_boundaries' if reference_path else '_reference_substep_boundaries')
    assert conversions==[1] and bits(tail)==bits(list(prior(2.05,6.,.05)))
    gen=module.substep_boundaries(0.,100.,.001);next(gen);before=admitted();gen.close()
    assert admitted()==before
    gen=module.substep_boundaries(0.,5.,.05)
    head=list(itertools.islice(gen,64));adapter._backend=None
    try: tail=list(gen)
    finally: adapter._backend=backend
    assert bits(head+tail)==bits(list(prior(0.,5.,.05)))
    # Preserve custom dependent laws and the explicit Python owner seam.
    saved=module.trajectory_position
    try:
        module.trajectory_position=lambda *args:(1.,2.,3.)
        before=admitted();args=(zero,unit,zero,0.,0.,.1,10.,0.)
        assert module.prepare_chord(*args)==module._reference_prepare_chord(*args)
        assert admitted()==before
    finally: module.trajectory_position=saved
    saved=module.lerp3;trace=[]
    def custom(*args): trace.append(args[2]);return (7.,8.,9.)
    module.lerp3=custom
    try:
        result=module.compensate_segment_for_moving_target(zero,unit,unit,zero,.1,.9)
        assert trace==[.1,.9] and result==((-7.,-8.,-9.),(-7.,-7.,-9.))
    finally: module.lerp3=saved
    a,b=[2.,3.,4.],[10.,12.,14.];first=module.lerp3(a,b,.5);a[0]=6.
    assert module.lerp3(a,b,.5)!=first
    saved=tuple(a),tuple(b),sys.getrefcount(a),sys.getrefcount(b)
    for unused in range(10000): module.lerp3(a,b,.5)
    gc.collect();assert saved==(tuple(a),tuple(b),sys.getrefcount(a),sys.getrefcount(b))
    if hasattr(backend,'test_allocation_budget'):
        for op,vectors,scalars,n in ((32,(zero,unit),(),1),(33,(zero,unit,zero),(.1,),4),
                                     (34,(zero,unit),(.1,),4),(35,(),(0.,.05,.05),4),
                                     (35,(),(0.,3.2,.05),193)):
            for budget in range(n):
                backend.test_allocation_budget(budget)
                try: backend.projectile_math(op,vectors,scalars)
                except MemoryError: counts['allocations']+=1
                else: raise AssertionError(('allocation failure missing',op,budget))
                finally: backend.test_allocation_budget(-1)
        backend.test_diag_begin()
        backend.projectile_math(33,(zero,unit,zero),(.1,))
        backend.projectile_math(35,(),(0.,1.,.05))
        rows=backend.test_diag_end()
        assert set(row[0] for row in rows)=={33,35}
        assert all(row[1:3]==(1,0) and all(x>=0. for x in row[3:]) for row in rows)
    class Reject(object):
        def projectile_math(self,*args):return None
    for older in (None,object(),Reject()):
        adapter._backend=older
        assert module.trajectory_position(zero,unit,zero,.1)==(0.,.1,0.)
        assert list(module.substep_boundaries(0.,.1,.05))==[(0.,.05),(.05,.1)]
    adapter._backend=backend;module._native_math=None
    assert module.trajectory_position(zero,unit,zero,.1)==(0.,.1,0.)
    module._native_math=adapter
    print('Projectile cursor conformance:',json.dumps(counts,sort_keys=True))
    return counts


if __name__=='__main__':
    sys.dont_write_bytecode=True
    if len(sys.argv) not in (2,3):
        raise SystemExit('usage: check_native_projectile_cursor.py HOST_EXTENSION [PRIOR_SOURCE]')
    run(load('offline_math_batch_native',sys.argv[1]),sys.argv[2] if len(sys.argv)==3 else None)
