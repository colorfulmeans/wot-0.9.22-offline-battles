"""CPython 2.7 parity for current turn sweeps and passive ground contacts.

These analytic fixtures establish numerical laws and lazy witness ordering,
not embedded BigWorld performance or gameplay acceptance.
"""
from __future__ import print_function
import sys, os, imp, random, math, time, gc
sys.platform = 'linux'
sys.dont_write_bytecode = True
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(root, 'tools'), os.path.join(root, 'src/res/scripts/client')]
import native_simulation_motion_fixture as fixture
from gui.mods.offline_lan_0922 import native_math, vehicle_physics as physics, battle_runtime as battle
backend = imp.load_dynamic('offline_math_batch_native', sys.argv[1])
native_math._backend, native_math._attempted = backend, True
rng = random.Random(1010)
checks = [0]

def near(a, b):
    if isinstance(b, (tuple, list)):
        assert len(a) == len(b), (a, b)
        for x, y in zip(a, b):
            near(x, y)
    else:
        assert abs(a-b) <= 2.e-10*max(1., abs(b)), (a, b)
    checks[0] += 1

params = dict(mass=45000., specificFriction=.6867, terrainResist=(.8, 1., 1.5))
for case in range(3000):
    p = dict(params, mass=rng.uniform(.1, 180000.), specificFriction=rng.uniform(.01, 2.))
    yaw = rng.uniform(-math.pi, math.pi)
    dt = rng.choice((0., -.01, .005, 1./30., .2))
    normal = rng.uniform(-.2, 1.2)
    velocity = (rng.uniform(-20., 20.), rng.uniform(-20., 20.))
    shape = (rng.uniform(.2, 3.), rng.uniform(.3, 6.))
    rolling = bool(case % 2)
    terrain = rng.choice((-3, -1, 0, 1, 2))
    omega = rng.uniform(-2., 2.)
    native_math._backend = None
    expected = (physics.contact_push_decel(p, rolling, terrain, normal),
                physics.contact_push_step(p, velocity[0], velocity[1], yaw, dt, rolling, terrain, normal),
                physics.wreck_contact_step(p, velocity[0], velocity[1], omega, yaw, shape, dt, normal))
    native_math._backend = backend
    actual = (physics.contact_push_decel(p, rolling, terrain, normal),
              physics.contact_push_step(p, velocity[0], velocity[1], yaw, dt, rolling, terrain, normal),
              physics.wreck_contact_step(p, velocity[0], velocity[1], omega, yaw, shape, dt, normal))
    near(actual, expected)

vector = fixture.Vec
for case in range(4000):
    low = (-rng.uniform(.1, 3.), -rng.uniform(.1, 2.), -rng.uniform(.1, 6.))
    high = (rng.uniform(.1, 3.), rng.uniform(.1, 3.), rng.uniform(.1, 6.))
    bbox = low, high
    pivot = rng.uniform(-2., 2.)
    angle = rng.uniform(0., math.pi)
    expected = battle._reference_rotation_interval_bbox(bbox, angle, pivot)
    actual = backend.rotation_envelope(bbox, angle, pivot)
    assert actual is not None
    near(actual, expected)
    position = tuple(rng.uniform(-200., 200.) for unused in range(3))
    start = rng.uniform(-math.pi, math.pi)
    end = start + rng.uniform(-.5, .5)
    pitch, roll = rng.uniform(-1.5, 1.5), rng.uniform(-1.5, 1.5)
    travel = rng.uniform(-1., 1.), rng.uniform(-1., 1.)
    point = vector(*(position[i]+rng.uniform(-6., 6.) for i in range(3)))
    normal = vector(*(rng.uniform(-1., 1.) for unused in range(3)))
    previous = [(point, normal)] if case % 2 else []
    calls = []
    def witness():
        calls.append(case)
        return previous
    reference = battle._reference_rotation_departing_contact(
        position, bbox, start, end, pitch, roll, witness, travel, pivot)
    expected = reference((point, normal))
    expected_calls = list(calls)
    calls[:] = []
    current = battle._rotation_departing_contact(
        position, bbox, start, end, pitch, roll, witness, travel, pivot)
    assert current((point, normal)) == expected, case
    assert calls == expected_calls, (case, calls, expected_calls)
    checks[0] += 1

# The held/airborne paths must preserve the source's early-return contract.
assert physics.wreck_contact_step({}, 1., 2., .5, 0., (), .1, airborne=True) == (1., 2., .5)
assert physics.contact_push_step({}, 1., 2., 0., 0.) == (1., 2.)
assert backend.rotation_envelope((low, high), float('nan'), 0.) is None
assert backend.rotation_envelope((high, low), .1, 0.) is None
assert physics._native_contact_ground(1, params, (float('nan'), 0., 0., .1, False, 0, 1.)) is None
assert physics._native_contact_ground(0, params, (False, 3, 1.)) is None

# Mutable tuning is read at every call, including the constraint iteration count.
for key, value in [('GRAVITY', 7.3), ('SLIDE_HOLD_TAN', .34),
                   ('SLOPE_GRIP_SDW_MIN', .08), ('SERVER_PHYSICS_CONSTRAINT_ITERATIONS', 3)]:
    old = getattr(physics, key)
    try:
        setattr(physics, key, value)
        native_math._backend = None
        expected = physics.wreck_contact_step(params, 1., -2., .5, .7, (1.5, 3.5), .1, .7)
        native_math._backend = backend
        near(physics.wreck_contact_step(params, 1., -2., .5, .7, (1.5, 3.5), .1, .7), expected)
    finally:
        setattr(physics, key, old)

gc.collect()
references = sys.getrefcount(params), sys.getrefcount(bbox)
for unused in range(100):
    physics.wreck_contact_step(params, 1., -2., .5, .7, (1.5, 3.5), .1, .7)
    backend.rotation_envelope(bbox, .1, .3)
gc.collect()
assert references == (sys.getrefcount(params), sys.getrefcount(bbox))

def bench(function, selected):
    native_math._backend = selected
    start = time.clock()
    for unused in range(2000):
        function()
    return (time.clock()-start)*1000./2000.

hit = vector(0., 1., 0.), vector(0., 0., -1.)
turn_reference = battle._reference_rotation_departing_contact(
    (0., 0., 0.), ((-1.5, -.8, -3.5), (1.5, 2., 3.5)), 0., .1)
turn_native = battle._rotation_departing_contact(
    (0., 0., 0.), ((-1.5, -.8, -3.5), (1.5, 2., 3.5)), 0., .1)
assert turn_native(hit) == turn_reference(hit)
print('rotation_departure reference/native ms per hit',
      bench(lambda: turn_reference(hit), None), bench(lambda: turn_native(hit), backend))
for name, operation in [
        ('wreck', lambda: physics.wreck_contact_step(params, 1., -2., .5, .7, (1.5, 3.5), .1, .7)),
        ('rotation_envelope', lambda: battle._destructible_rotation_interval_bbox(bbox, .1, .3))]:
    print(name, 'reference/native ms per call', bench(operation, None), bench(operation, backend))
print('Current ground and turn laws passed:', checks[0], 'comparisons; lazy witnesses, tuning, guards and owned refs')
