import math
import unittest

from test_port_0922_turret_obstacles import descriptor, pose
from gui.mods.offline_lan_0922 import rigid_turret as physics
from gui.mods.offline_lan_0922.entities import turret_obstacles as geometry


def components():
    td = descriptor()
    td.turret.weight = 4000.0
    td.gun.weight = 1000.0
    return geometry.turret_components(td)


def body(position=(0, 1, 0), velocity=(0, 0, 0), angular=(0, 0, 0)):
    return physics.Body(components(), dict(position=position, attitude=(0, 0, 0),
                         velocity=velocity, angular_velocity=angular))


def floor(start, end):
    if start[1] >= 0 and end[1] <= 0 and start[1] != end[1]:
        f = start[1]/(start[1]-end[1])
        return (tuple(start[i]+(end[i]-start[i])*f for i in range(3)), (0, 1, 0))
    return None


class RigidTurretTests(unittest.TestCase):
    def test_mass_and_inertia_use_both_actual_components(self):
        props = physics.properties(components())
        self.assertEqual(5000, props['mass'])
        self.assertAlmostEqual(.9, props['centre'][2])
        for i in range(3):
            self.assertGreater(props['inertia'][4*i], 0)

    def test_missing_weight_has_no_generic_light_turret_fallback(self):
        with self.assertRaises((TypeError, ValueError)):
            physics.properties(geometry.turret_components(descriptor()))

    def test_flat_floor_drop_cannot_stop_in_mid_air(self):
        value = body((0, 8, 0))
        for _ in range(400):
            physics.scenery_step(value, .01, floor)
        # A long offset gun can prop the assembly at an angle. Its lowest
        # real component must touch, rather than forcing the root to Y=1.
        self.assertLess(value.position[1], 2.0)
        self.assertLess(min(p[1] for p in value.points()), .025)
        self.assertGreater(min(p[1] for p in value.points()), -.025)
        self.assertLess(physics.length(value.velocity), .05)

    def test_missing_ground_keeps_falling_after_the_old_flight_window(self):
        value = body((0, 20, 0))
        for _ in range(900):
            physics.scenery_step(value, .01, lambda a, b: None)
        self.assertLess(value.position[1], -300)
        self.assertFalse(value.grounded)

    def test_side_collision_does_not_lift_a_grounded_turret_onto_roof(self):
        value = body()
        boxes = geometry.vehicle_support_boxes(descriptor(), pose(x=-1.4), attached=False)
        result = physics.vehicle_contact(value, boxes, 50000, (5, 0, 0))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(0, result['momentum'][1])
        self.assertAlmostEqual(0, result['body_correction'][1])
        self.assertGreater(result['momentum'][0], 0)

    def test_reciprocal_momentum_is_conserved_and_impact_adds_no_energy(self):
        for vehicle_mass in (1000., 5000., 100000.):
            value = body()
            boxes = geometry.vehicle_support_boxes(descriptor(), pose(x=-1.4), attached=False)
            velocity = (5, 0, 0)
            result = physics.vehicle_contact(value, boxes, vehicle_mass, velocity)
            initial_energy = .5*vehicle_mass*25
            value.momentum(result['momentum'], result['angular_momentum'])
            final_vehicle = physics.add(velocity, result['delta'])
            self.assertAlmostEqual(vehicle_mass*5, vehicle_mass*final_vehicle[0]+value.props['mass']*value.velocity[0])
            self.assertLessEqual(.5*vehicle_mass*physics.dot(final_vehicle, final_vehicle)+value.kinetic_energy(), initial_energy+1e-5)

    def test_off_centre_impact_turns_body_instead_of_translating_it_up(self):
        value = body()
        boxes = geometry.vehicle_support_boxes(descriptor(), pose(x=-1.4, z=.7), attached=False)
        hit = physics.vehicle_contact(value, boxes, 50000, (5, 0, 0))
        self.assertIsNotNone(hit)
        value.momentum(hit['momentum'], hit['angular_momentum'])
        self.assertGreater(abs(value.angular[1]), 0)
        self.assertEqual(0, value.velocity[1])

    def test_rotation_roundtrips_pitch_roll_and_half_turns(self):
        for attitude in ((1, .4, -.6), (2, math.pi, 0), (0, 0, math.pi)):
            original = physics.matrix(attitude)
            restored = physics.matrix(physics.angles(original))
            for a, b in zip(original, restored):
                self.assertAlmostEqual(a, b)

    def test_wall_contact_separates_horizontally(self):
        def wall(start, end):
            if start[0] <= 0 <= end[0] and end[0] != start[0]:
                f = -start[0]/(end[0]-start[0])
                return (tuple(start[i]+(end[i]-start[i])*f for i in range(3)), (-1, 0, 0))
        value = body((-1.01, 5, 0), (5, 0, 0))
        physics.scenery_step(value, .01, wall)
        self.assertLessEqual(max(p[0] for p in value.points()), 1e-5)
        self.assertLess(value.position[1], 5.001)


class RigidTurretLifecycleTests(unittest.TestCase):
    def vehicle(self):
        return dict(boxes=geometry.vehicle_support_boxes(descriptor(), pose(), attached=False),
                    mass=50000., velocity=(0., 0., 0.), human=True, alive=True)

    def test_landing_on_vehicle_then_driving_away_releases_gravity(self):
        value = body((0, 4, 0), angular=(0, 0, 0))
        vehicle = self.vehicle()
        physics.advance(value, 1., [vehicle], floor)
        supported = value.position[1]
        self.assertGreater(supported, 1.5)
        self.assertTrue(value.grounded)
        self.assertIsNotNone(value.impact)
        serial = value.impact_serial
        physics.advance(value, .1, [vehicle], floor)
        self.assertEqual(serial, value.impact_serial)
        physics.advance(value, .3, [], floor)
        self.assertLess(value.position[1], supported-.1)
        self.assertFalse(value.sleeping)

    def test_deep_side_overlap_uses_horizontal_entry_not_roof_axis(self):
        value = body((0, 1, 0))
        value.grounded = True
        vehicle = self.vehicle()
        for x in (-1.4, -.7, -.1):
            vehicle['boxes'] = geometry.vehicle_support_boxes(descriptor(), pose(x=x), attached=False)
            result = physics.vehicle_contact(value, vehicle['boxes'], vehicle['mass'], (5, 0, 0))
            self.assertIsNotNone(result)
            self.assertAlmostEqual(0, result['body_correction'][1])
            self.assertAlmostEqual(0, result['momentum'][1])

    def test_dynamic_obstacle_cannot_restore_old_immovable_wall_gate(self):
        from test_port_0922_turret_obstacles import row, _Math
        value = body()
        accepted = physics.revision(row(), value, 4000)
        obstacles = geometry.DetachedTurretObstacles(_Math())
        self.assertTrue(obstacles.add('bot:17', accepted, descriptor()))
        for x in (-.01, .01):
            self.assertFalse(obstacles.sweep_blocks(pose(), pose(x=x), descriptor(), 4000))
        self.assertEqual([], list(obstacles.navigation_hulls(4000)))
        newer = physics.revision(accepted, value, 4040)
        self.assertTrue(obstacles.add('bot:17', newer, descriptor()))
        self.assertFalse(obstacles.add('bot:17', accepted, descriptor()))
        self.assertEqual(1, obstacles.active())

    def test_velocity_impact_and_receipt_are_one_owned_wire_revision(self):
        import json
        from test_port_0922_turret_obstacles import row
        from gui.mods.offline_lan_0922 import turret_obstacle_schema as wire
        value = body((0, 4, 0))
        value.acks = [['player:1', 8, 123., 0., 0., 0., 0., 90.]]
        accepted = physics.revision(row(), value, 4000)
        decoded = wire.normalize_proposal(json.loads(json.dumps(accepted)))
        self.assertIsNotNone(decoded)
        self.assertEqual(accepted['flight']['body']['acks'], decoded['flight']['body']['acks'])
        self.assertEqual(list(value.velocity), decoded['flight']['body']['velocity'])
        self.assertFalse(decoded['flight']['landed'])
        invalid = json.loads(json.dumps(accepted))
        invalid['flight']['body']['velocity'][1] = float('nan')
        self.assertIsNone(wire.normalize_proposal(invalid))
