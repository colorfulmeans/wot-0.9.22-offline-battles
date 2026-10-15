"""Bit-exact current-release pitch curves through the actual native frontier.

Run with a host extension path, or call run(backend) from the aiming check.
This check does not substitute for the embedded #1513 runtime acceptance.
"""
from __future__ import print_function

import math
import os
import random
import struct
import sys


def _load_source(name, path):
    if sys.version_info[0] < 3:
        import imp
        return imp.load_source(name, path)
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _single(value):
    return struct.unpack('<f', struct.pack('<f', float(value)))[0]


def _reference(yaw, limits):
    yaw = _single(yaw)
    if yaw < 0.0:
        yaw = _single(yaw + _single(2.0 * math.pi))
    result = []
    for name in ('minPitch', 'maxPitch'):
        points = tuple((_single(x), _single(y)) for x, y in limits[name])
        lower, upper = 0, len(points) - 1
        while upper - lower > 1:
            middle = (lower + upper) // 2
            if yaw > points[middle][0]:
                lower = middle
            else:
                upper = middle
        span = _single(points[upper][0] - points[lower][0])
        fraction = _single(_single(yaw - points[lower][0]) / span)
        result.append(_single(
            _single(points[lower][1] * _single(1.0 - fraction)) +
            _single(points[upper][1] * fraction)))
    return tuple(result)


class _NativeCalls(object):
    def __init__(self, backend):
        self.backend = backend
        self.admitted = 0
        self.rejected = 0

    def call(self, name, *args):
        assert name == 'driver_aim' and args[0] == 4
        result = self.backend.driver_aim(*args)
        if result is None:
            self.rejected += 1
        else:
            self.admitted += 1
        return result


def run(backend):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'src', 'res', 'scripts', 'client', 'gui',
                        'mods', 'offline_lan_0922', 'gun_pitch_limits.py')
    module = _load_source('_native_pitch_under_test', path)
    reference = _load_source('_reference_pitch_under_test', path)
    reference._native_math = None
    calls = _NativeCalls(backend)
    module._native_math = calls
    checks = [0]

    def compare(yaw, limits):
        expected = _reference(yaw, limits)
        before = calls.admitted
        actual = module.calc_pitch_limits(yaw, limits)
        assert calls.admitted == before + 1, ('native fallback', yaw, limits)
        assert type(actual) is tuple and all(type(x) is float for x in actual)
        assert struct.pack('<dd', *actual) == struct.pack('<dd', *expected), (
            yaw, limits, actual, expected)
        checks[0] += 1
        return actual

    rng = random.Random(1513141309)
    for unused in range(6000):
        limits = {'absolute': (12.0, 13.0)}
        for name in ('minPitch', 'maxPitch'):
            count = rng.randrange(2, 25)
            # Keep distinct nodes separated after float32 rounding on both
            # Python 2 and 3, whose random selection paths need not coincide.
            nodes = ([0.0] + [(i + rng.uniform(0.1, 0.9)) * 2.0 * math.pi / (count - 1)
                               for i in range(count - 2)] + [2.0 * math.pi])
            limits[name] = [[x, rng.uniform(-0.8, 0.8)] for x in nodes]
        compare(rng.uniform(-4.0 * math.pi, 4.0 * math.pi), limits)

    # Independent knot grids, negative yaw, exact seams and adjacent float32s.
    limits = {'minPitch': [(0.0, -0.785398), (2.1, -0.785398),
                           (2.2, -0.244346), (4.1, -0.244346),
                           (4.2, -0.785398), (2.0 * math.pi, -0.785398)],
              'maxPitch': [(0.0, 0.0349066), (0.87, 0.0349066),
                           (0.96, 0.0872665), (5.32, 0.0872665),
                           (5.41, 0.0349066), (2.0 * math.pi, 0.0349066)]}
    for degrees in range(-720, 721):
        compare(math.radians(degrees), limits)
    for curve in limits.values():
        for yaw, unused in curve:
            bits = struct.unpack('<I', struct.pack('<f', yaw))[0]
            for neighbor in (max(0, bits - 1), bits, bits + 1):
                adjacent = struct.unpack('<f', struct.pack('<I', neighbor))[0]
                compare(adjacent, limits)
                compare(adjacent - 2.0 * math.pi, limits)
    for value in (0.0, -0.0, 1.e-40, -1.e-40):
        flat = {'minPitch': ((0.0, value), (2.0 * math.pi, value)),
                'maxPitch': ((0.0, value), (2.0 * math.pi, value))}
        for yaw in (0.0, -0.0, math.pi, -math.pi, 2.0 * math.pi):
            compare(yaw, flat)

    before = compare(0.5, limits)
    limits['maxPitch'][0] = (0.0, 0.2)
    assert compare(0.5, limits) != before
    saved = repr(limits)
    compare(0.6, limits)
    assert repr(limits) == saved, 'native modified caller curves'

    # Rejection must be callback-free; fallback alone owns conversion/iteration.
    class Trap(object):
        def __float__(self):
            raise AssertionError('native invoked Python conversion')

    class SequenceTrap(list):
        def __len__(self):
            raise AssertionError('native invoked Python sequence protocol')

    good = ((0.0, -0.3), (2.0 * math.pi, -0.3))
    for bad in ((), ((0.0, 0.1),), ((0.0, Trap()), (1.0, 0.1)),
                SequenceTrap(good), ((0.0, float('nan')), (1.0, 0.1)),
                ((0.0, float('inf')), (1.0, 0.1)),
                ((0.0, 1.e100), (1.0, 0.1))):
        assert backend.driver_aim(4, (0.0, bad, good), ()) is None
    for bad in (((1.0, -0.3), (1.0 + 1.e-9, -0.2)),
                ((0.0, float('nan')), (1.0, 0.1)), (),
                ((0.0, 1.e100), (1.0, 0.1))):
        bad_limits = {'minPitch': bad, 'maxPitch': good}
        outcomes = []
        for owner in (reference, module):
            try:
                owner.calc_pitch_limits(1.0, bad_limits)
            except ValueError as error:
                outcomes.append(str(error))
            else:
                raise AssertionError('invalid curve unexpectedly accepted')
        assert outcomes[0] == outcomes[1], outcomes

    # Iterators are not consumed by the failed native admission.
    yielded = []
    def generated():
        for point in good:
            yielded.append(point)
            yield point
    assert module.calc_pitch_limits(0.5, {'minPitch': generated(), 'maxPitch': good}) == \
        reference.calc_pitch_limits(0.5, {'minPitch': good, 'maxPitch': good})
    assert yielded == list(good)

    class OldBinary(object):
        def driver_aim(self, *args):
            return None
    module._native_math = _NativeCalls(OldBinary())
    assert module.calc_pitch_limits(0.5, limits) == reference.calc_pitch_limits(0.5, limits)
    module._native_math = None
    assert module.calc_pitch_limits(0.5, limits) == reference.calc_pitch_limits(0.5, limits)
    print('Gun pitch bit-exact parity:', checks[0],
          'comparisons; supported calls admitted; rejection and fallback passed')
    return checks[0]


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    if len(sys.argv) != 2:
        raise SystemExit('usage: check_native_gun_pitch_limits.py HOST_EXTENSION')
    if sys.version_info[0] < 3:
        import imp
        backend = imp.load_dynamic('offline_math_batch_native', sys.argv[1])
    else:
        backend = _load_source('offline_math_batch_native', sys.argv[1])
    run(backend)
