"""Current local-driver steering candidates through the actual Python 2 frontier."""
from __future__ import print_function
import copy
import math
import os
import random
import struct
import sys

def _bits(value):
    if type(value) is float:
        return struct.pack('<d', value)
    if type(value) in (tuple, list):
        return tuple(_bits(x) for x in value)
    return value

def run(backend):
    from gui.mods.offline_lan_0922 import native_math
    from gui.mods.offline_lan_0922.ai.driver import LocalDriver
    old_backend, old_attempted = native_math._backend, native_math._attempted
    native_math._backend, native_math._attempted = backend, True
    rng = random.Random(202610112)
    driver = LocalDriver()
    comparisons = 0
    callbacks = 0
    def admissions():
        return native_math.snapshot()['driver_geometry']
    try:
        for case in range(2200):
            now = rng.uniform(0., 20.)
            state = dict(clock=now, escape_side_until=now+rng.uniform(-2.,2.),
                         escape_side=rng.choice((-1.,0.,1.)),
                         failed_yaws={})
            yaw = rng.uniform(-9.*math.pi,9.*math.pi)
            for i in range(rng.randrange(25)):
                key=rng.randrange(24)
                state['failed_yaws'][key] = now + rng.uniform(-3.,5.)
            expected_state=copy.deepcopy(state)
            expected=driver._reference_rank_yaw_candidates(expected_state,yaw)
            before=admissions()
            actual=driver._rank_yaw_candidates(state,yaw)
            assert admissions()==before+1, ('native candidate admission',case)
            assert _bits(actual)==_bits(expected), ('candidate score/order',case,actual,expected)
            assert state==expected_state, ('expired failure mutations',case)
            comparisons+=1
        for case in range(200):
            yaw = rng.uniform(-math.pi, math.pi)
            state = dict(clock=10.,failed_yaws={},
                         escape_side_until=0.,escape_side=0.)
            calls=[]
            def direction_clear(a):
                calls.append(('direction',a))
                return a < yaw + .9
            def pose_clear(a):
                calls.append(('pose',a))
                return a > yaw - .45
            # Two independent fresh states; no engine calls in native ranking.
            a=copy.deepcopy(state)
            b=copy.deepcopy(state)
            expected=driver._reference_rank_yaw_candidates(b,yaw)
            previous=driver._rank_yaw_candidates(a,yaw)
            assert _bits(previous)==_bits(expected) and a==b
            # Compare original callback order after the same candidate ranking.
            def select(items):
                result=None
                for score,candidate in items:
                    if pose_clear(candidate) and direction_clear(candidate):
                        result=candidate
                        break
                return result
            left=select(expected); reference_calls=list(calls); calls[:]=[]
            right=select(previous)
            assert left==right and calls==reference_calls
            callbacks+=1
        original=driver._failure_penalty
        try:
            driver._failure_penalty=lambda state,yaw: 9.
            state=dict(clock=5.,failed_yaws={},escape_side_until=0.,escape_side=0.)
            before=admissions()
            assert driver._rank_yaw_candidates(state,0.)==driver._reference_rank_yaw_candidates(state,0.)
            assert admissions()==before
        finally:
            del driver._failure_penalty

        class InputTrap(object):
            def __float__(self):
                raise AssertionError('native invoked conversion')
        invalid=backend.driver_geometry(9,(0.,0.,2.,0.,0.,math.pi,24),
                                        (InputTrap(),),())
        assert invalid is None
        invalid=backend.driver_geometry(9,(0.,0.,2.,0.,0.,math.pi,24),
                                        (.0,),((0,InputTrap()),))
        assert invalid is None

        class OldBinary(object):
            pass
        native_math._backend=OldBinary()
        state=dict(clock=5.,failed_yaws={},escape_side_until=0.,escape_side=0.)
        assert driver._rank_yaw_candidates(state,0.)==driver._reference_rank_yaw_candidates(state,0.)
        print('Local driver native candidate parity: %d comparisons, %d probe traces and fallback checks.' % (comparisons, callbacks))
    finally:
        native_math._backend, native_math._attempted=old_backend,old_attempted

if __name__=='__main__':
    import imp
    sys.dont_write_bytecode=True;sys.platform='linux'
    root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:0]=[os.path.join(root,'tools'),os.path.join(root,'src/res/scripts/client')]
    import native_simulation_motion_fixture
    run(imp.load_dynamic('offline_math_batch_native',sys.argv[1]))
