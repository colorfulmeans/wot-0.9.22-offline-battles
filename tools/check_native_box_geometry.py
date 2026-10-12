"""CPython 2.7 host-bridge conformance against the retained reference laws."""
from __future__ import print_function
import imp
import math
import random
import sys
import os
import time
import types

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(root, 'src', 'res', 'scripts', 'client'))
for name in ('gui', 'gui.mods', 'gui.mods.offline_lan_0922'):
    module = types.ModuleType(name)
    module.__path__ = [os.path.join(root, 'src', 'res', 'scripts', 'client', *name.split('.'))]
    sys.modules[name] = module
from gui.mods.offline_lan_0922 import destructibles_sensor as ref
ref._native_geometry.box_probe = lambda *args, **kwargs: None
ref._native_geometry.box_envelope = lambda *args, **kwargs: None
b = imp.load_dynamic('offline_math_batch_native', sys.argv[1])


class Vector(object):
    def __init__(self, values):
        self.x, self.y, self.z = values


def close(actual, expected):
    if expected is None:
        assert actual is None, (actual, expected)
    elif isinstance(expected, (tuple, list)):
        assert len(actual) == len(expected), (actual, expected)
        for a, e in zip(actual, expected):
            close(a, e)
    elif isinstance(expected, bool):
        assert bool(actual) == expected, (actual, expected)
    else:
        assert abs(actual - expected) <= 2.e-10 * (1. + abs(expected)), (actual, expected)


rng = random.Random(132223)
epsilon = ref._CATALOG_POINT_EPSILON
cases = []
for index in range(1500):
    center = tuple(rng.uniform(-50., 50.) for unused in range(3))
    scale = [rng.uniform(.1, 8.) for unused in range(3)]
    yaw = rng.uniform(-math.pi, math.pi)
    cy, sy = math.cos(yaw), math.sin(yaw)
    local = ((scale[0], 0., 0.),
             (rng.uniform(-.7, .7) * scale[0], scale[1], 0.),
             (rng.uniform(-.7, .7) * scale[0], rng.uniform(-.7, .7) * scale[1], scale[2]))
    axes = tuple((cy*x + sy*z, y, -sy*x + cy*z) for x, y, z in local)
    if index % 11 == 0:
        axes += ((.1, .2, .3),)
    box = center, axes, None
    point = tuple(center[i] + rng.uniform(-10., 10.) for i in range(3))
    start = tuple(center[i] + rng.uniform(-20., 20.) for i in range(3))
    end = tuple(center[i] + rng.uniform(-20., 20.) for i in range(3))
    cases.append((box, point, start, end))
unit = ((0., 0., 0.), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), None)
for point in ((0., 0., 0.), (1. + epsilon, 0., 0.), (1. + epsilon + 1.e-7, 0., 0.)):
    cases.append((unit, point, (-2., 0., 0.), (2., 0., 0.)))
cases.append((((0., 0., 0.), ((0., 0., 0.),) * 3, None), (0.,) * 3, (0.,) * 3, (1.,) * 3))

for box, point, start, end in cases:
    expected = (ref._point_in_world_box(Vector(point), box),
                ref._segment_world_box_interval(Vector(start), Vector(end), box),
                ref._projected_box_interval_1513(Vector(start), Vector(end), box))
    for flags in range(1, 8):
        output = b.destr_box_geometry(0, ((box,), point, start, end, epsilon, flags))
        assert output is not None
        close(output[0], (expected[0] if flags & 1 else False,
                          expected[1] if flags & 2 else None,
                          expected[2] if flags & 4 else None))
    for padding in (0., -.01, .1):
        close(b.destr_box_geometry(0, ((box,), None, start, end, padding, 2))[0][1],
              ref._segment_world_box_interval(Vector(start), Vector(end), box, padding))

for index in range(0, len(cases), 3):
    boxes = tuple(row[0] for row in cases[index:index+3])
    expected = ref._instance_motion_envelope_1513({'boxes': boxes})
    result = b.destr_box_geometry(1, boxes)
    close(None if result[0] is None else result[0] + (None,), expected)
assert b.destr_box_geometry(1, ()) == (None,)
assert b.destr_box_geometry(0, ((unit,), (0.,) * 3, None, None, epsilon, 0)) is None
assert b.destr_box_geometry(0, ((unit,), ('wrong', 0., 0.), None, None, epsilon, 1)) is None

# Compare batch work with the unchanged reference, without any engine timings.
boxes = tuple(row[0] for row in cases[:16])
point, start, end = cases[0][1:]
stamp = time.clock()
for unused in range(1000):
    for box in boxes:
        ref._point_in_world_box(Vector(point), box)
        ref._segment_world_box_interval(Vector(start), Vector(end), box)
reference_ms = (time.clock() - stamp) * 1000.
stamp = time.clock()
for unused in range(1000):
    b.destr_box_geometry(0, (boxes, point, start, end, epsilon, 3))
native_ms = (time.clock() - stamp) * 1000.
print('Box conformance passed: %d probes, 502 envelopes, degeneracy and rejection' % (len(cases) * 10))
print('16-box batch only: reference %.3f ms, native %.3f ms; excludes engine/adapter work' % (reference_ms, native_ms))
