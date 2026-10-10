"""CPython 2.7 parity for the unchanged release suspension law.

Pure copied samples only: this is not embedded physics or frame acceptance.
"""
from __future__ import print_function
import copy, gc, imp, math, os, random, sys, time
sys.platform = 'linux'
sys.dont_write_bytecode = True
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(root, 'src/res/scripts/client'))
import native_simulation_motion_fixture  # Install the CPython 2.7 package seam.
from gui.mods.offline_lan_0922 import native_math, vehicle_physics as physics
backend = imp.load_dynamic('offline_math_batch_native', sys.argv[1])
native_math._backend, native_math._attempted = backend, True
rng = random.Random(213722)
count = [0]


def near(actual, expected):
    assert set(actual) == set(expected)
    for key, value in expected.items():
        if value is None or type(value) in (bool, int):
            assert actual[key] == value, (key, actual[key], value)
            if type(value) is bool:
                assert type(actual[key]) is bool
        else:
            assert abs(actual[key] - value) <= 2.e-9 * max(1., abs(value)), (key, actual[key], value)
        count[0] += 1


def parameters(mass=21000., spacing=1.):
    springs = []
    for side, x in (('left', -1.2), ('right', 1.2)):
        for z in (-2., -1., 0., 1., 2.):
            springs.append(dict(x=x*spacing, y=0., z=z*spacing,
                side=side, stiffness=mass*physics.GRAVITY, damping=mass*.2,
                static_compression=.1, max_compression=.4,
                max_force=mass*physics.GRAVITY*2.))
    pseudo = [dict(x=x*spacing, y=-.5, z=z*spacing, side=side,
                   kind='rigid' if z < 0 else 'body', penetration=.01)
              for side, x in (('left', -1.4), ('right', 1.4))
              for z in (-2.4, 2.4)]
    return dict(mass=mass, pitch_inertia=mass*2., roll_inertia=mass*1.2,
                fixed_step=1./120., constraint_iterations=8,
                springs=tuple(springs), pseudo_contacts=tuple(pseudo))


saved = None
for case in range(3000):
    p = parameters(rng.uniform(500., 190000.), rng.uniform(.4, 2.))
    p['constraint_iterations'] = rng.choice((0, 1, 4, 8, 12))
    if case % 7 == 0:
        p['pseudo_contacts'] = ()
    for point in p['springs']:
        point['y'] = rng.uniform(-.3, .3)
        point['stiffness'] *= rng.uniform(.5, 1.5)
        point['max_compression'] = rng.uniform(.2, .6)
    gradient = rng.uniform(-.5, .5), rng.uniform(-.5, .5)
    heights = tuple(None if rng.random() < .25 else
                    point['x']*gradient[0] + point['z']*gradient[1]
                    for point in p['springs'])
    pseudo = tuple(None if rng.random() < .4 else
                   point['x']*gradient[0] + point['z']*gradient[1]
                   for point in p['pseudo_contacts'])
    if case % 8 == 0:
        heights, pseudo = (None,)*len(heights), (None,)*len(pseudo)
    state = dict(height=rng.uniform(-.4, 2.), vertical_velocity=rng.uniform(-8., 4.),
        pitch=rng.uniform(-3.2, 3.2), roll=rng.uniform(-3.2, 3.2),
        pitch_velocity=rng.uniform(-2., 2.), roll_velocity=rng.uniform(-2., 2.))
    dt, support = rng.choice((0., .008, .016, .05, .15, .2, .3)), rng.uniform(-3., 3.)
    original = copy.deepcopy((p, state, heights, pseudo))
    expected = physics._reference_damper_suspension_step(p, state, heights, dt, pseudo, support)
    actual = physics._native_suspension_step(p, state, heights, dt, pseudo, support)
    assert actual is not None, case
    near(actual, expected)
    assert (p, state, heights, pseudo) == original
    if case == 1:
        saved = p, state, heights, dt, pseudo, support

# Multi-step state transitions include exact contact/airborne flags, not just
# individual forces. Runtime tuning is read fresh on every bridge call.
for case in range(20):
    p = parameters(); states = [dict(height=.1, vertical_velocity=-1., pitch=.1,
              roll=-.1, pitch_velocity=.2, roll_velocity=-.2) for unused in range(2)]
    for tick in range(100):
        ground = tuple(None if tick < 20 or (case%2 and point['x']>0.) else 0.
                       for point in p['springs'])
        pseudo = (None,)*len(p['pseudo_contacts'])
        expected = physics._reference_damper_suspension_step(p, states[0], ground, .016, pseudo)
        actual = physics._native_suspension_step(p, states[1], ground, .016, pseudo, 0.)
        near(actual, expected)
        states = expected, actual
        if tick == 50:
            p['springs'][0]['stiffness'] *= 1.1
            p['mass'] *= 1.01

for changed in ('GRAVITY', 'FREEZE_ACCEL_EPSILON', 'CONTACT_PENETRATION', 'SERVER_PHYSICS_MAX_SUBSTEPS'):
    previous = getattr(physics, changed)
    setattr(physics, changed, 5 if changed == 'SERVER_PHYSICS_MAX_SUBSTEPS' else previous*1.1)
    try:
        p, state, ground, dt, pseudo, support = saved
        near(physics._native_suspension_step(p, state, ground, dt, pseudo, support),
             physics._reference_damper_suspension_step(p, state, ground, dt, pseudo, support))
    finally:
        setattr(physics, changed, previous)

assert backend.release_suspension_step((), (), (), (), (), (), ()) is None
# Typed rejection must neither coerce custom values nor admit a float loop
# count that the current Python range() contract rejects.
wire = []
original_call = native_math.call
def capture(method, *args):
    wire.append(args)
    return original_call(method, *args)
native_math.call = capture
try:
    physics._native_suspension_step(*saved)
finally:
    native_math.call = original_call
args = list(wire[0]); header = list(args[0]); header[4] = float(header[4])
args[0] = tuple(header)
assert backend.release_suspension_step(*args) is None
class Conversion(object):
    def __float__(self):
        raise AssertionError('must not coerce a custom numeric value')
header[0] = Conversion(); args[0] = tuple(header)
assert backend.release_suspension_step(*args) is None
gc.collect(); before = sys.getrefcount(saved[0]), sys.getrefcount(saved[1])
snapshot = copy.deepcopy(saved)
for unused in range(200):
    physics._native_suspension_step(*saved)
gc.collect(); assert before == (sys.getrefcount(saved[0]), sys.getrefcount(saved[1]))
assert saved == snapshot
assert native_math.snapshot()['fallbacks'] == 0

p = parameters(); state = dict(height=.1, vertical_velocity=0., pitch=0.,
    pitch_velocity=0., roll=0., roll_velocity=0.)
ground = (0.,)*10; pseudo = (None,)*4
for label, operation in (('reference', physics._reference_damper_suspension_step),
                         ('native', physics.damper_suspension_step)):
    start = time.clock()
    for unused in range(2000): operation(p, state, ground, .15, pseudo)
    print('suspension', label, 'ms/call', (time.clock()-start)*1000./2000.)
print('Current suspension parity passed:', count[0], 'field comparisons; 5000 solves, mutation, tuning and ownership checks')
