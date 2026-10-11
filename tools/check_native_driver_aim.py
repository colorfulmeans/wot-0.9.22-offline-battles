"""Actual CPython 2.7 aiming frontier parity against current-release laws."""
from __future__ import print_function
import os, sys, imp, random, math, time
sys.platform = 'linux'
sys.dont_write_bytecode = True
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(root, 'tools'), os.path.join(root, 'src/res/scripts/client')]
import native_simulation_motion_fixture
from gui.mods.offline_lan_0922 import native_math
from gui.mods.offline_lan_0922.ai import driver
backend = imp.load_dynamic('offline_math_batch_native', sys.argv[1])
native_math._backend = backend
native_math._attempted = True
rng = random.Random(141309)
modes = [None, 'engage', 'reverse_withdraw', 'avoid', 'blocked', 'reverse_turn',
         'pivot_recovery', 'forward_escape', 'short_forward_escape',
         'short_reverse_escape', 'contact_escape', 'wreck_push', 'friendly_yield',
         'nav_wait', 'physical_hold']
checks = 0

def check(name, args):
    global checks
    expected = getattr(driver, '_reference_' + name)(*args)
    before = native_math.snapshot()['driver_aim']
    actual = getattr(driver, name)(*args)
    assert native_math.snapshot()['driver_aim'] == before + 1, ('fallback', name, args)
    assert actual == expected, (name, args, actual, expected)
    assert type(actual) is type(expected), (name, type(actual), type(expected))
    if isinstance(actual, tuple):
        assert [type(x) for x in actual] == [type(x) for x in expected]
    checks += 1

for case in range(6000):
    hull, target = [rng.uniform(-math.pi * 4, math.pi * 4) for unused in range(2)]
    minimum, maximum = rng.choice([(-math.pi, math.pi), (-1.57, 1.57),
        (0., 0.), (-.1, .4), (-.4, .1), (-math.pi + .1, math.pi - .1)])
    turn, throttle = [rng.uniform(-1., 1.) for unused in range(2)]
    rear = rng.choice((-1., 0., 1.))
    check('combat_hull_aim', (hull, target, minimum, maximum, turn, throttle,
        rng.choice(modes), rng.choice((False, True)), rng.choice((None, 'engage', 'withdraw')),
        rng.choice((False, True)), rng.choice((False, True)), rear, rng.choice((False, True))))
    relative = driver._angle_delta(target, hull)
    check('limited_traverse_target', (relative, minimum, maximum, rear))
    desired, pitch = [rng.uniform(-1., 1.) for unused in range(2)]
    check('gun_aligned', (target, hull, relative, desired, pitch, .06, .04))
    check('barrel_direction', (target, pitch))

# Exact inequality edges, +/-pi seam, fixed and asymmetric traverse, held modes.
for minimum, maximum in [(-math.pi, math.pi), (0., 0.), (-.1, .4), (-1.57, 1.57)]:
    margin = min(.04, max(0., maximum - minimum) * .25)
    for relative in [minimum, maximum, minimum + margin, maximum - margin,
                     -math.pi, math.pi, -math.pi/2, math.pi/2, -.35, .35]:
        for epsilon in [-1.e-12, 0., 1.e-12]:
            for mode in modes:
                for rear in [-1., 0., 1.]:
                    check('combat_hull_aim', (0., relative + epsilon, minimum, maximum,
                        .5, -.5, mode, True, 'engage', False, True, rear, True))
            check('limited_traverse_target', (relative + epsilon, minimum, maximum, 1.))
for yaw_error in [.06-1.e-12, .06, .06+1.e-12, -.06, math.pi, -math.pi]:
    for pitch_error in [.04-1.e-12, .04, .04+1.e-12, -.04]:
        check('gun_aligned', (yaw_error, 0., 0., pitch_error, 0., .06, .04))
assert backend.driver_aim(3, (float('inf'), 0.), ()) is None
assert backend.driver_aim(0, (0.,)*7, (0, 2, 0, 0, 0, 0)) is None
assert backend.driver_aim(4, (), ()) is None
# Unsupported numeric objects never invoke Python conversion inside C++.
class Trap(object):
    def __float__(self):
        raise AssertionError('native invoked user conversion')
assert backend.driver_aim(3, (Trap(), 0.), ()) is None
# Old binaries fall back to the exact current policy while source-only work proceeds.
native_math._backend = None
args = (0., math.pi, -1.57, 1.57, .5, -.5, None)
assert driver.combat_hull_aim(*args) == driver._reference_combat_hull_aim(*args)
print('Driver aim exact parity:', checks, 'comparisons; all supported calls used native')
from check_native_gun_pitch_limits import run as check_pitch_limits
check_pitch_limits(backend)
