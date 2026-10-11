"""Compare the current projectile manager's complete chord math with native.

Requires an actual CPython 2.7 host extension path passed by the existing
native driver conformance entrypoint. Does not prove embedded #1513 latency.
"""
from __future__ import print_function

import math
import os
import random
import struct
import sys


def _bits(value):
    if isinstance(value, float):
        return struct.pack('<d', value)
    if isinstance(value, (tuple, list)):
        return tuple(_bits(item) for item in value)
    if isinstance(value, bool):
        return bool(value)
    return value


def run(backend):
    from gui.mods.offline_lan_0922 import native_math
    from gui.mods.offline_lan_0922 import projectile_runtime as runtime
    from gui.mods.offline_lan_0922 import projectile_manager
    previous_backend, previous_attempted = (
        native_math._backend, native_math._attempted)
    previous_owner = runtime._native_math
    rng = random.Random(15131011)
    checks = [0, 0, 0]

    def admitted():
        return native_math.snapshot()['projectile_math']

    def compare_chord(vectors, scalars):
        before = admitted()
        expected = runtime._reference_prepare_chord(*(vectors + scalars))
        actual = runtime.prepare_chord(*(vectors + scalars))
        assert admitted() == before + 1, ('native chord rejected', vectors, scalars)
        assert _bits(actual) == _bits(expected), ('chord', vectors, scalars, actual, expected)
        checks[0] += 1

    def compare_moving(vectors, scalars):
        before = admitted()
        expected = runtime._reference_compensate_segment_for_moving_target(
            *(vectors + scalars))
        actual = runtime.compensate_segment_for_moving_target(
            *(vectors + scalars))
        assert admitted() == before + 1, ('native motion rejected', vectors, scalars)
        assert _bits(actual) == _bits(expected), ('moving', vectors, scalars, actual, expected)
        checks[1] += 1

    def manager_trace(native):
        runtime._native_math = native_math if native else None
        manager = projectile_manager.InFlightProjectiles(
            initial_time=0., maximum_substep=.035)
        for index in range(9):
            assert manager.launch('shot-%d' % index,
                (index * 3., 1., 0.), (70. + index * 17., index * 3., 7.),
                (0., -9.81, 0.), 0., 1.25, 20. + index * 24.,
                {'index': index})
        events = []
        terminals = []

        def chord(state, start, end, beginning, ending):
            events.append((state['key'], state['cursor_time'], start, end,
                           beginning, ending, state['distance']))
            if state['key'] == 'shot-7' and beginning >= .07:
                return {'reason': 'hit', 'fraction': .37}
            if state['key'] == 'shot-8' and beginning >= .04:
                return {'reason': 'hit', 'fraction': 0.}
            return None

        def terminal(state, record):
            terminals.append((state, record))

        for interval in (.04, .12, .20, .28, .44, .61, .87, 1.25):
            assert manager.advance(interval, chord, terminal, maximum_chords=18)
        assert manager.advance(1.25, chord, terminal)
        return events, terminals, manager.snapshot(), manager.last_advance_metrics()

    try:
        native_math._backend, native_math._attempted = backend, True
        runtime._native_math = native_math
        for unused in range(15000):
            vectors = tuple(tuple(rng.uniform(-400., 400.) for i in range(3))
                            for j in range(3))
            launch = rng.uniform(0., 500.)
            start = launch + rng.uniform(0., 15.)
            end = start + rng.choice((0., .001, .01, .05, .2))
            limit = rng.choice((0., 10., 400., rng.uniform(0., 15000.)))
            travelled = rng.choice((0., limit, max(0., limit - rng.uniform(0., 5.))))
            compare_chord(vectors, (launch, start, end, limit, travelled))
            vectors = tuple(tuple(rng.uniform(-250., 250.) for i in range(3))
                            for j in range(4))
            compare_moving(vectors, (rng.uniform(-.5, 1.5), rng.uniform(-.5, 1.5)))

        # Direct native admission must not invoke a custom numeric converter.
        class Trap(object):
            def __float__(self):
                raise AssertionError('native called user conversion')
        assert backend.projectile_math(0,
            ((0., 0., 0.), (1., Trap(), 1.), (0., -9.81, 0.)),
            (0., 0., .05, 100., 0.)) is None
        assert backend.projectile_math(0,
            ((0., 0., 0.), (1., 1., 1.), (0., -9.81, 0.)),
            (0., 0., float('inf'), 100., 0.)) is None
        assert backend.projectile_math(1,
            ((0., 0., 0.),) * 4, (float('nan'), 1.)) is None
        assert backend.projectile_math(9, (), ()) is None

        # Frozen Python laws remain authoritative for overridden functions.
        old_trajectory = runtime.trajectory_position
        try:
            runtime.trajectory_position = lambda *args: (1., 2., 3.)
            before = admitted()
            data = runtime.prepare_chord((0.,) * 3, (1.,) * 3,
                                         (0.,) * 3, 0., 0., .01, 10., 0.)
            assert admitted() == before
            assert data == runtime._reference_prepare_chord(
                (0.,) * 3, (1.,) * 3, (0.,) * 3, 0., 0., .01, 10., 0.)
        finally:
            runtime.trajectory_position = old_trajectory

        reference = manager_trace(False)
        actual = manager_trace(True)
        assert _bits(actual) == _bits(reference), 'manager callback/ledger parity'
        checks[2] += 1

        # The old shipping extension has no new method. Keep reference math.
        class OldBinary(object):
            pass
        native_math._backend = OldBinary()
        runtime._native_math = native_math
        vectors = ((0.,) * 3, (1., 2., 3.), (0., -9.81, 0.))
        scalars = (0., 0., .01, 10., 0.)
        assert runtime.prepare_chord(*(vectors + scalars)) == \
               runtime._reference_prepare_chord(*(vectors + scalars))
        runtime._native_math = None
        assert runtime.prepare_chord(*(vectors + scalars)) == \
               runtime._reference_prepare_chord(*(vectors + scalars))
        print('Projectile math exact parity:', checks,
              '; native admitted; manager callback/ledger and fallback passed')
        return checks
    finally:
        runtime._native_math = previous_owner
        native_math._backend, native_math._attempted = (
            previous_backend, previous_attempted)


if __name__ == '__main__':
    import imp
    if len(sys.argv) != 2:
        raise SystemExit('usage: check_native_projectile_math.py HOST_EXTENSION')
    sys.dont_write_bytecode = True
    sys.platform = 'linux'
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:0] = [os.path.join(root, 'tools'),
                   os.path.join(root, 'src/res/scripts/client')]
    import native_simulation_motion_fixture
    run(imp.load_dynamic('offline_math_batch_native', sys.argv[1]))
