"""Actual CPython 2.7 projectile spatial frontier vs current 0.10.0 laws.

Called by the existing native-driver conformance job with a rebuilt host
extension. Only #1513 Windows gameplay tests establish engine behavior.
"""
from __future__ import print_function
import gc
import math
import random
import struct
import sys


def _bits(value):
    if type(value) is float:
        return struct.pack('<d', value)
    if type(value) in (list, tuple):
        return (type(value), tuple(_bits(item) for item in value))
    return type(value), value


def run(backend):
    from gui.mods.offline_lan_0922 import native_math
    from gui.mods.offline_lan_0922 import projectile_runtime as laws
    old_backend, old_attempted = native_math._backend, native_math._attempted
    old_math = laws._native_math
    native_math._backend = backend
    native_math._attempted = True
    laws._native_math = native_math
    rng = random.Random(20261011)
    checked = [0] * 6
    names = ('point_segment_distance_sq',
             'point_in_expanded_segment_bounds',
             'ideal_reflection_velocity',
             'ricochet_departure_origin',
             'parabolic_chord_error',
             'curvature_limited_substep')

    def compare(op, args, admitted=True):
        expected = actual = None
        error_a = error_b = None
        try:
            expected = getattr(laws, '_reference_' + names[op])(*args)
        except Exception as error:
            error_a = (type(error), str(error))
        before = native_math.snapshot()['projectile_spatial']
        try:
            actual = getattr(laws, names[op])(*args)
        except Exception as error:
            error_b = (type(error), str(error))
        assert _bits(error_a) == _bits(error_b), (names[op], args, error_a, error_b)
        if error_a is None:
            assert _bits(actual) == _bits(expected), (
                names[op], args, expected, actual)
        if admitted:
            assert native_math.snapshot()['projectile_spatial'] == before + 1, (
                'native rejected supported call', names[op], args)
        checked[op] += 1

    try:
        for case in range(5000):
            a, b, c = [tuple(rng.uniform(-200., 200.) for j in range(3))
                       for unused in range(3)]
            if case % 30 == 0:
                a = b
            if case % 91 == 0:
                c = b
            compare(0, (a, b, c))
            compare(1, (a, b, c, rng.uniform(-10., 30.)))
            compare(2, (a, b))
            if case % 40:
                compare(3, (a, b, c))
            gravity = rng.choice((None, 0., -9.81, 9.81, (0., -9.81, 0.),
                                  (1., 2., 3.), [0., 1., 0.]))
            duration = rng.uniform(-.3, 3.)
            compare(4, (gravity, duration))
            compare(5, (gravity, duration, rng.uniform(0., 1.)))

        zero, unit = (0., 0., 0.), (0., 1., 0.)
        for v in (-0., 0., 1.e-320, -1.e-320, 1.e-12, -1.e-12, 1., 1.e150):
            x = (v, v, v)
            compare(0, (x, zero, unit))
            compare(1, (x, zero, unit, abs(v)))
            compare(2, (unit, x))
            # Numerically degenerate normals stay on the reference error path.
            normal_length = math.sqrt(sum(t*t for t in x))
            compare(3, (unit, unit, x), admitted=normal_length > 1.e-12)
        for step in (0., .0001, .001, .05, .2, 2.):
            for error in (0., 1.e-12, 1.e-9, .05, .3):
                compare(5, ((0., -9.81, 0.), step, error))

        for invalid in (None, 'x', (1.,),
                        (0., 0., float('nan')),
                        (0., 0., float('inf'))):
            compare(0, (invalid, zero, unit), admitted=False)
            compare(1, (invalid, zero, unit, 1.), admitted=False)
            compare(2, (zero, invalid), admitted=False)
            compare(3, (zero, zero, invalid), admitted=False)

        class Trap(object):
            def __float__(self):
                raise AssertionError('native invoked user conversion')
            def __iter__(self):
                raise AssertionError('native invoked user iteration')
        assert backend.projectile_spatial(0, ((Trap(), 0., 0.), zero, unit), ()) is None
        assert backend.projectile_spatial(1, (zero, zero, unit), (Trap(),)) is None
        assert backend.projectile_spatial(2, (zero, Trap()), ()) is None
        assert backend.projectile_spatial(3, (zero, zero, (Trap(), 0., 0.)), ()) is None
        assert backend.projectile_spatial(4, (Trap(),), (1.,)) is None
        assert backend.projectile_spatial(5, (unit,), (Trap(), .1, .05, .05)) is None
        assert backend.projectile_spatial(6, (), ()) is None

        # No Python or engine references are stored after a native query.
        source = [2., 3., 4.]
        owned = (source, zero, unit)
        before_ref = sys.getrefcount(source)
        before_data = tuple(source)
        for unused in range(1000):
            laws.point_segment_distance_sq(*owned)
        gc.collect()
        assert before_ref == sys.getrefcount(source)
        assert before_data == tuple(source)

        # A previous shipped binary without the new entry point must remain usable.
        native_math._backend = object()
        assert laws.point_segment_distance_sq(unit, zero, unit) == \
            laws._reference_point_segment_distance_sq(unit, zero, unit)
        assert laws.ideal_reflection_velocity(unit, unit) == \
            laws._reference_ideal_reflection_velocity(unit, unit)
        laws._native_math = None
        assert laws.parabolic_chord_error(unit, .1) == \
            laws._reference_parabolic_chord_error(unit, .1)
        print('Projectile spatial parity:', checked,
              'native admission, reference errors, ownership and fallback passed')
        return checked
    finally:
        laws._native_math = old_math
        native_math._backend, native_math._attempted = old_backend, old_attempted
