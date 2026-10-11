"""Current 0.10.0 pair-crossing and peer-roster C++ conformance.

Run against the actual CPython 2.7 extension from check_native_driver_geometry.
The original numeric owner remains the oracle, including mutable inputs,
prioritization, pair state and Python descriptor fallback.
"""
from __future__ import print_function

import math
import random
import struct


def _match(expected, actual):
    if isinstance(expected, float):
        return (type(actual) is float and
                (struct.pack('<d', expected) == struct.pack('<d', actual) or
                 abs(expected - actual) <= 1.e-12))
    if isinstance(expected, dict):
        return (isinstance(actual, dict) and set(expected) == set(actual) and
                all(_match(expected[key], actual[key]) for key in expected))
    if isinstance(expected, (tuple, list)):
        return (type(actual) is type(expected) and len(expected) == len(actual) and
                all(_match(a,b) for a,b in zip(expected, actual)))
    return type(actual) is type(expected) and actual == expected


def run(backend):
    from gui.mods.offline_lan_0922 import native_math
    from gui.mods.offline_lan_0922.ai import traffic
    old_backend, old_attempted = native_math._backend, native_math._attempted
    native_math._backend, native_math._attempted = backend, True
    rng = random.Random(16110922)
    counts = dict(begin=0, cleared=0, separation=0, roster=0)

    def sample(actor):
        width, length = rng.uniform(.9, 2.8), rng.uniform(2., 6.)
        row = dict(id=actor, team=rng.choice((None,1,2)), alive=rng.choice((True,True,False)),
                   position=(rng.uniform(-20.,20.),rng.uniform(-4.,4.),rng.uniform(-20.,20.)),
                   yaw=rng.uniform(-math.pi,math.pi),
                   pitch=rng.uniform(-.7,.7),roll=rng.uniform(-.5,.5),
                   velocity=(rng.uniform(-10.,10.),0.,rng.uniform(-10.,10.)),
                   half_width=width,half_length=length)
        if rng.randrange(5):
            row['shape'] = (width,length,-.8,2.)
        if rng.randrange(6) == 0:
            row['position'] = (row['position'][0],None,row['position'][2])
        return row

    def admitted():
        return native_math.snapshot()['driver_geometry']

    def assert_used(before, label):
        assert admitted() == before + 1, ('native fallback',label)

    try:
        for case in range(2200):
            first, second = sample(1), sample(2)
            if case % 11 == 0:
                first.update(position=(0.,0.,0.),yaw=0.,velocity=(0.,0.,5.))
                second.update(position=(rng.uniform(-3.,3.),0.,rng.uniform(4.,15.)),
                              yaw=math.pi,velocity=(0.,0.,-5.))
            if case % 7 == 0:
                first.update(position=(0.,0.,0.),yaw=0.,velocity=(0.,0.,5.))
                second.update(position=(rng.uniform(-3.,3.),0.,rng.uniform(2.,9.)),
                              yaw=math.pi*.5,velocity=(5.,0.,0.))
            coordinator = traffic.TrafficCoordinator()
            now = rng.uniform(0.,100.)
            if case % 3 == 0:
                coordinator._held[first['id']] = now - rng.uniform(0.,2.)
            if case % 4 == 0:
                coordinator._held[second['id']] = now - rng.uniform(0.,2.)
            old = coordinator._reference_begin(first,second,now)
            before = admitted()
            new = coordinator._begin(first,second,now)
            assert_used(before,'begin')
            assert _match(old,new),('begin',case,old,new)
            counts['begin'] += 1
            if old is not None:
                expected = traffic.TrafficCoordinator._reference_cleared(old,first,second)
                before = admitted()
                actual = traffic.TrafficCoordinator._cleared(old,first,second)
                assert_used(before,'cleared')
                assert expected is actual,('cleared',case,expected,actual)
                counts['cleared'] += 1
            expected = traffic._reference_separation(first,second)
            before = admitted()
            actual = traffic._separation(first,second)
            assert_used(before,'separation')
            assert _match(expected,actual),('separation',case,expected,actual)
            counts['separation'] += 1
            # All supported calls reread mutable positions, yaw and dimensions.
            second['yaw'] += .07
            second['position'] = (second['position'][0]+.03,
                                  second['position'][1],second['position'][2]-.02)
            expected = traffic._reference_separation(first,second)
            before = admitted()
            actual = traffic._separation(first,second)
            assert_used(before,'mutable separation')
            assert _match(expected,actual)
            counts['separation'] += 1
            if case < 1000:
                neighbours = [sample(i+3) for i in range(29)]
                if case % 10 == 0: neighbours[3]['id'] = neighbours[2]['id']
                expected = traffic._reference_adjust_roster(first['id'],first,neighbours)
                before = admitted()
                actual = traffic._adjust_roster(first['id'],first,neighbours)
                assert_used(before,'adjust roster')
                assert tuple(expected) == tuple(actual),('roster keys',case)
                assert all(expected[k] is actual[k] for k in expected),('roster identity',case)
                counts['roster'] += 1

        # Runtime modifications to timing laws cannot be concealed in native defaults.
        first = dict(id=1,position=(0.,0.,0.),yaw=0.,velocity=(0.,0.,5.),
                     shape=(1.6,3.5,-.8,2.))
        second = dict(first,id=2,position=(0.,0.,5.),yaw=math.pi,
                      velocity=(0.,0.,-5.))
        previous = (traffic.PREDICTION_SECONDS,traffic.YIELD_SECONDS,
                    traffic.HEAD_ON_OFFSET,traffic._EPSILON)
        try:
            for prediction in (.1,1.,2.):
                for yield_seconds in (.1,1.5,3.):
                    traffic.PREDICTION_SECONDS = prediction
                    traffic.YIELD_SECONDS = yield_seconds
                    traffic.HEAD_ON_OFFSET = .37
                    traffic._EPSILON = 1.e-8
                    coordinator = traffic.TrafficCoordinator()
                    old = coordinator._reference_begin(first,second,8.)
                    before=admitted()
                    new = coordinator._begin(first,second,8.)
                    assert_used(before,'mutable tuning')
                    assert _match(old,new),('mutable tuning',old,new)
                    counts['begin'] += 1
        finally:
            (traffic.PREDICTION_SECONDS,traffic.YIELD_SECONDS,
             traffic.HEAD_ON_OFFSET,traffic._EPSILON) = previous

        # Never call Python conversion/equality/iteration inside native code.
        class Trap(dict):
            def get(self,*args):
                raise AssertionError('native called custom mapping')
        class FloatTrap(float):
            pass
        assert backend.driver_geometry(5,(first,Trap(second)),(0,0),
                                       (1.,1.,1.5,.42,1.e-9)) is None
        assert backend.driver_geometry(5,(dict(first,yaw=FloatTrap(0.)),second),
                                       (0,0),(1.,1.,1.5,.42,1.e-9)) is None
        assert backend.driver_geometry(7,(first,Trap(second)),(),()) is None
        assert backend.driver_geometry(8,first,[Trap(second)],()) is None

        # Unsupported input/older shipping binary stays on the current rule.
        class OldBinary(object):
            def driver_geometry(self,*args):
                return None
        native_math._backend = OldBinary()
        coordinator = traffic.TrafficCoordinator()
        assert coordinator._begin(first,second,8.) == coordinator._reference_begin(first,second,8.)
        assert traffic._separation(first,second) == traffic._reference_separation(first,second)
        assert traffic._adjust_roster(1,first,[second]) == traffic._reference_adjust_roster(1,first,[second])
        print('Traffic crossing native parity:',counts)
        return counts
    finally:
        native_math._backend, native_math._attempted = old_backend, old_attempted
