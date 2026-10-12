"""Current traffic braking loops through the actual native driver frontier.

The existing CPython 2.7 driver conformance entry point calls run(backend).
Pure calculation parity does not establish embedded-client frame timing.
"""
from __future__ import print_function

import copy
import gc
import math
import random
import struct
import sys


def run(backend):
    from gui.mods.offline_lan_0922 import native_math
    from gui.mods.offline_lan_0922.ai import traffic
    old_backend, old_attempted = native_math._backend, native_math._attempted
    native_math._backend, native_math._attempted = backend, True
    rng = random.Random(1513141309)
    checks = {'roster': 0, 'blocker': 0, 'controls': 0}

    def admitted():
        return native_math.snapshot()['driver_geometry']

    def body(actor):
        width, length = rng.uniform(.8, 2.7), rng.uniform(1., 6.)
        row = dict(id=actor, team=rng.choice((None, 1, 2)), alive=True,
                   position=(rng.uniform(-25., 25.), rng.uniform(-7., 7.),
                             rng.uniform(-25., 25.)),
                   yaw=rng.uniform(-math.pi * 2., math.pi * 2.),
                   pitch=rng.uniform(-.7, .7), roll=rng.uniform(-.5, .5),
                   velocity=(rng.uniform(-12., 12.), 0., rng.uniform(-12., 12.)),
                   half_width=width, half_length=length)
        if rng.randrange(5):
            row['shape'] = [width, length, rng.uniform(-1.5, -.1),
                            rng.uniform(.4, 3.)]
        return row

    def check_roster(own, peers, throttle):
        expected = traffic._reference_braking_roster(own, peers, throttle)
        before = admitted()
        actual = traffic._braking_roster(own, peers, throttle)
        assert admitted() == before + 1, ('roster fallback', own, peers, throttle)
        expected_values = expected[:2] + expected[2] + expected[3]
        actual_values = actual[:2] + actual[2] + actual[3]
        assert struct.pack('<6d', *expected_values) == struct.pack('<6d', *actual_values), (
            'roster values', expected_values, actual_values)
        for a, b in zip(expected[4:], actual[4:]):
            assert len(a) == len(b) and all(x is y for x, y in zip(a, b)), (
                'roster order or ownership', a, b)
        checks['roster'] += 1
        return actual

    def check_blocker(own, peers, throttle, step, brake):
        roster = check_roster(own, peers, throttle)
        speed, unused_sign, position, axis, unused_peers, candidates = roster
        # An empty sweep is not called by the runtime. Directly test it too.
        args = (own, candidates, position, axis, speed, step, brake)
        expected = traffic._reference_braking_blocker(*args)
        before = admitted()
        actual = traffic._braking_blocker(*args)
        assert admitted() == before + 1, ('blocker fallback', args)
        assert actual == expected, ('blocker', args, actual, expected)
        checks['blocker'] += 1

    def controls(own, peers, command, step, brake, mutation=None, fail=False,
                 use_reference=False):
        own, peers, command = copy.deepcopy((own, peers, command))
        coordinator = traffic.TrafficCoordinator()
        coordinator._orders[own['id']] = (2., dict(command))
        calls = []

        def stopping_distance():
            calls.append('stop')
            if mutation is not None:
                mutation(own, peers)
            if fail:
                raise ValueError('stopping sentinel')
            return brake

        saved = traffic._braking_roster, traffic._braking_blocker
        try:
            if use_reference:
                traffic._braking_roster = traffic._reference_braking_roster
                traffic._braking_blocker = traffic._reference_braking_blocker
            try:
                result = coordinator.safe_controls(
                    own, command, peers, 3., stopping_distance, step)
                outcome = ('ok', result)
            except (ValueError, TypeError) as error:
                # Missing-height rows intentionally test the geometry phases.
                # The complete driver can reject those rows during backing;
                # compare that original exception as well as successful output.
                outcome = ('error', type(error).__name__, str(error))
            return outcome, coordinator._orders, calls, own, peers, command
        finally:
            traffic._braking_roster, traffic._braking_blocker = saved

    def check_controls(own, peers, command, step, brake, mutation=None, fail=False):
        args = (own, peers, command, step, brake, mutation, fail)
        expected = controls(*args, **{'use_reference': True})
        actual = controls(*args)
        assert actual == expected, ('controls or side effects', args, actual, expected)
        assert len(actual[2]) <= 1, 'stopping callback replayed'
        checks['controls'] += 1
        return actual

    try:
        for case in range(3000):
            own = body(1)
            peers = [body(index + 2) for index in range(30)]
            for index, peer in enumerate(peers):
                if index % 11 == 0:
                    peer['alive'] = False
                if index % 7 == 0:
                    peer.pop('team', None)
            if case % 3 == 0:
                own['position'] = (own['position'][0], None, own['position'][2])
            if case % 13 == 0:
                peers[0]['id'] = own['id']
            throttle = rng.choice((-1., -.01, 0., .01, 1.))
            for revision in range(2):
                check_blocker(own, peers, throttle,
                              rng.choice((1./30., .1, .2, .53)),
                              float('inf') if case % 7 == 0 else rng.uniform(0., 110.))
                # Do not cache positions, inclinations or mutable fitted shapes.
                own['yaw'] += .03
                peers[1]['position'] = (own['position'][0], own['position'][1],
                                        own['position'][2] + 5.)
                if 'shape' in peers[1]:
                    peers[1]['shape'][1] += .1
            if case < 400:
                command = dict(throttle=throttle, turn=rng.choice((0., -.8, .8)),
                               movement_intent=True,
                               recovery_mode=rng.choice(('drive', 'blocked', 'reverse_turn')),
                               forward_blocked_by=peers[1]['id'], custom=['unchanged'])
                check_controls(own, peers, command, .1, 8.)

        # Boundaries for intended gear, existing side contacts and bridge/grade
        # separation. Do not change the strict >0 vertical overlap or >= SAT gates.
        own = dict(id=1, team=1, alive=True, position=(0., 0., 0.), yaw=0.,
                   pitch=0., roll=0., shape=[1.7, 3.5, -.8, 2.],
                   half_width=1.7, half_length=3.5, velocity=(0., 0., 4.))
        peer = dict(own, id=2, position=(0., 0., 8.), velocity=(0., 0., 0.))
        for z in (-8., 0., 6.999999999, 7., 7.000000001, 8., 24.):
            for x in (0., 3.4, 3.400000001):
                for throttle in (-.010000000001, -.01, 0., .01, .010000000001):
                    p = dict(peer, position=(x, 0., z))
                    check_blocker(own, [p], throttle, .1, 1.)
                    check_controls(own, [p], dict(throttle=throttle, turn=0.,
                        movement_intent=True, recovery_mode='drive'), .1, 1.)
        for height in (2.799999999, 2.8, 2.800000001, 5., 10.):
            for pitch in (0., .43, -.43):
                for roll in (0., -.2, .2):
                    a = dict(own, pitch=pitch, roll=roll)
                    p = dict(peer, pitch=-pitch, roll=-roll,
                             position=(0., height, 8.))
                    check_blocker(a, [p], 1., .1, 8.)
        # Duplicate IDs must not reorder or collapse an ordered candidate list.
        check_blocker(own, [dict(peer, id=0), dict(peer, id=0)], 1., .1, 8.)
        check_blocker(own, [], 1., .1, 8.)
        for throttle in (0., -0., 1., -1.):
            check_blocker(dict(own, velocity=(-0., 0., -0.)), [peer], throttle, .1, 0.)

        command = dict(throttle=1., turn=.5, movement_intent=True,
                       recovery_mode='blocked', forward_blocked_by=2)
        check_controls(own, [peer], command, .1, 8., fail=True)

        def change_pose(a, rows):
            a['position'] = (1., 0., -1.)
            a['yaw'] = .25
            rows[0]['position'] = (0., 0., 7.5)
            rows[0]['velocity'] = (1., 0., 0.)
        check_controls(own, [peer], command, .1, 8., mutation=change_pose)

        class Scalar(float):
            pass
        def reject_after_callback(a, rows):
            rows[0]['yaw'] = Scalar(.15)
        result = check_controls(own, [peer], command, .1, 8.,
                                mutation=reject_after_callback)
        assert result[2] == ['stop']

        saved_tuning = traffic.PREDICTION_SECONDS, traffic._EPSILON
        try:
            for prediction in (0., .5, 2.):
                for epsilon in (0., 1.e-5):
                    traffic.PREDICTION_SECONDS, traffic._EPSILON = prediction, epsilon
                    check_blocker(own, [peer], 1., .1, 8.)
        finally:
            traffic.PREDICTION_SECONDS, traffic._EPSILON = saved_tuning

        # Replaced Python laws remain authoritative rather than being bypassed.
        original_level = traffic._same_level
        try:
            traffic._same_level = lambda a, b: False
            before = admitted()
            actual = traffic._braking_roster(own, [peer], 1.)
            assert admitted() == before and actual[4:] == ([], [])
        finally:
            traffic._same_level = original_level
        original_time = traffic._contact_time
        try:
            traffic._contact_time = lambda a, b: None
            before = admitted()
            assert traffic._braking_blocker(own, [peer], (0., 0.),
                                            (0., 1.), 4., .1, 8.) is None
            assert admitted() == before
        finally:
            traffic._contact_time = original_time

        class Trap(dict):
            def get(self, *args):
                raise AssertionError('native invoked mapping code')
        class NumberTrap(object):
            def __float__(self):
                raise AssertionError('native invoked conversion code')
        class SequenceTrap(list):
            def __len__(self):
                raise AssertionError('native invoked sequence code')
        for raw in ([Trap(peer)], SequenceTrap([peer])):
            assert backend.driver_geometry(3, own, raw, (1.,)) is None
        assert backend.driver_geometry(3, dict(own, yaw=NumberTrap()), [peer], (1.,)) is None
        assert backend.driver_geometry(3, own, [dict(peer, position=NumberTrap())], (1.,)) is None
        # Excluded actors are not required to carry unused valid geometry.
        ignored = [dict(id=1), dict(id=8, alive=False), dict(id=9, team=2)]
        check_roster(own, ignored, 1.)
        assert backend.driver_geometry(4, own, [peer], (0.,)*8) is None
        assert backend.driver_geometry(4, own, [peer], (0.,)*8+(float('nan'),)) is None

        yielded = []
        def generated():
            yielded.append(peer)
            yield peer
        assert traffic._braking_roster(own, generated(), 1.) == \
            traffic._reference_braking_roster(own, [peer], 1.)
        assert yielded == [peer], 'native consumed a reference iterator'

        saved = copy.deepcopy((own, peer))
        refs = [sys.getrefcount(row) for row in (own, peer)]
        for unused in range(1000):
            traffic._braking_roster(own, [peer], 1.)
            traffic._braking_blocker(own, [peer], (0., 0.), (0., 1.), 4., .1, 8.)
        gc.collect()
        assert [sys.getrefcount(row) for row in (own, peer)] == refs
        assert (own, peer) == saved

        class OldBinary(object):
            def driver_geometry(self, *args):
                return None
        native_math._backend = OldBinary()
        assert traffic._braking_roster(own, [peer], 1.) == \
            traffic._reference_braking_roster(own, [peer], 1.)
        assert traffic._braking_blocker(own, [peer], (0., 0.), (0., 1.), 4., .1, 8.) == \
            traffic._reference_braking_blocker(own, [peer], (0., 0.), (0., 1.), 4., .1, 8.)
        native_math._backend = None
        assert traffic._braking_roster(own, [peer], 1.) == \
            traffic._reference_braking_roster(own, [peer], 1.)
        print('Traffic geometry parity:', checks,
              '; supported phases used native; callback/ownership/fallback checks passed')
        return checks
    finally:
        native_math._backend, native_math._attempted = old_backend, old_attempted


if __name__ == '__main__':
    import os
    import imp
    sys.dont_write_bytecode = True
    sys.platform = 'linux'
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:0] = [os.path.join(root, 'tools'),
                   os.path.join(root, 'src/res/scripts/client')]
    import native_simulation_motion_fixture
    if len(sys.argv) != 2:
        raise SystemExit('usage: check_native_traffic_geometry.py HOST_EXTENSION')
    run(imp.load_dynamic('offline_math_batch_native', sys.argv[1]))
