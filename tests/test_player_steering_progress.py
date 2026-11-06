"""Distant route steering preserves forward travel through player consumers.

The opening pose and target are from report 133716, 13:19:52.876. Clear-world
and installed-physics inputs are explicit seams. The Bot driver is used only
as an independent test reference; player runtime never calls it. These tests
do not claim to replay the client's native suspension or steering dynamics.
"""
import math
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from gui.mods.offline_lan_0922.player_control.driving import Driver, angle


POSITION = (-38.782702541859024, .25004818172341164, -106.43755713094941)
TARGET = (-78.8077, .25, -98.9527)
YAW = -.927706572266834
SPEED = 4.012412739670818
SHAPE = (1.5080519914627075, 2.9235379695892334,
         .0026149998884648085, 1.6808550357818604)


def goal(distance, bearing, height=0.):
    return (distance * math.sin(bearing), height, distance * math.cos(bearing))


class PlayerSteeringProgressTests(unittest.TestCase):
    def test_captured_far_clear_point_keeps_forward_like_actual_bot_driver(self):
        reference = LocalDriver()
        bot = reference.drive(1, 0, POSITION, YAW, SPEED, .1, TARGET, (),
            lambda *args: True, half_length=SHAPE[1], turn_speed_limit=.55)
        self.assertEqual([], reference.states[1]['pedal_observation']['gates'])
        self.assertEqual(1., bot['throttle'])
        driver = Driver()
        # Keep this call usable against the old driver as a behavioral
        # countercheck, independently of the newly exposed optional inputs.
        player = driver.drive(POSITION, YAW, SPEED, TARGET, 0., lambda *args: True)
        self.assertAlmostEqual(40.718834803993545, driver.receipt['distance'])
        self.assertAlmostEqual(-.45822045895848396, driver.receipt['delta'])
        self.assertEqual(1., player['throttle'])
        self.assertFalse(player['brake'])
        self.assertAlmostEqual(bot['turn'], player['turn'])

    def test_distant_moderate_correction_drives_from_rest_and_at_speed(self):
        for speed in (0., 4.):
            for bearing in (-.8, -.458, .458, .8):
                with self.subTest(speed=speed, bearing=bearing):
                    command = Driver().drive((0., 0., 0.), 0., speed,
                        goal(40.7, bearing), 0., lambda *args: True,
                        half_length=3., turn_speed_limit=.55)
                    self.assertEqual(1., command['throttle'])
                    self.assertFalse(command['brake'])
                    self.assertGreater(command['turn'] * bearing, 0.)

    def test_near_corner_rear_goal_and_steep_entry_still_align(self):
        for label, target in (('near_corner', goal(6., .5)),
                              ('rear', goal(40., 2.)),
                              ('uphill', goal(40., 1., 20.)),
                              ('downhill', goal(40., -1., -20.))):
            for speed in (0., 4.):
                with self.subTest(label=label, speed=speed):
                    command = Driver().drive((0., 0., 0.), 0., speed,
                        target, 0., lambda *args: True, half_length=3.)
                    self.assertEqual(0., command['throttle'])
                    if speed:
                        self.assertTrue(command['brake'])
                    else:
                        self.assertNotEqual(0., command['turn'])

    def test_long_hull_retains_near_corner_gate_beyond_eight_metres(self):
        short = Driver().drive((0., 0., 0.), 0., 0., goal(10., .5), 0.,
                               lambda *args: True, half_length=3.)
        long = Driver().drive((0., 0., 0.), 0., 0., goal(10., .5), 0.,
                              lambda *args: True, half_length=6.)
        self.assertGreater(short['throttle'], 0.)
        self.assertEqual(0., long['throttle'])

    def test_installed_turn_radius_alignment_survives_braking_to_rest(self):
        driver = Driver()
        target = goal(15., .35)
        # At 4 m/s and .4 rad/s, the 10 m radius admits the near-point
        # alignment. At rest the geometric radius shrinks, but its owner stays.
        first = driver.drive((0., 0., 0.), 0., 4., target, 0.,
                             lambda *args: True, turn_speed_limit=.4)
        self.assertEqual(0., first['throttle'])
        self.assertTrue(first['brake'])
        for now, remaining in ((.1, .35), (.2, .20), (.3, .121)):
            command = driver.drive((0., 0., 0.), .35 - remaining, 0., target, now,
                                   lambda *args: True, turn_speed_limit=.4)
            self.assertEqual(0., command['throttle'])
        aligned = driver.drive((0., 0., 0.), .35 - .119, 0., target, .4,
                               lambda *args: True, turn_speed_limit=.4)
        self.assertGreater(aligned['throttle'], 0.)
        self.assertFalse(aligned['brake'])

    def test_nearby_rebased_tip_cannot_move_the_alignment_heading(self):
        driver = Driver()
        first = goal(7., .6)
        driver.drive((0., 0., 0.), 0., 0., first, 0., lambda *args: True,
                     turn_speed_limit=.5)
        second = (first[0] + 1., first[1], first[2])
        command = driver.drive((0., 0., 0.), .6 - .119, 0., second, .1,
                               lambda *args: True, turn_speed_limit=.5)
        self.assertGreater(command['throttle'], 0.)
        self.assertAlmostEqual(.119 / .58, command['turn'])

    def test_new_far_leg_releases_near_point_alignment(self):
        driver = Driver()
        driver.drive((0., 0., 0.), 0., 0., goal(6., .6), 0., lambda *args: True,
                     turn_speed_limit=.5)
        command = driver.drive((0., 0., 0.), 0., 0., goal(40., .458), .1,
                               lambda *args: True, turn_speed_limit=.5)
        self.assertGreater(command['throttle'], 0.)
        self.assertFalse(command['brake'])

    def test_closed_forward_corridor_cannot_gain_throttle_from_far_point_rule(self):
        queries = []
        def clear(heading, reach):
            queries.append((heading, reach))
            return abs(angle(heading)) > .7
        command = Driver().drive((0., 0., 0.), 0., 0., goal(40., .458), 0., clear)
        self.assertEqual(0., command['throttle'])
        self.assertTrue(any(abs(heading) < 1.e-9 for heading, unused in queries))

    def test_cover_fixed_gears_retain_their_alignment_and_steering_signs(self):
        for direction, base in ((1., 0.), (-1., math.pi)):
            for delta in (.2, .458):
                with self.subTest(direction=direction, delta=delta):
                    command = Driver().drive((0., 0., 0.), 0., 0.,
                        goal(40., base + delta), 0., lambda *args: True,
                        terminal=True, travel_direction=direction,
                        motion_key=('player_cover', direction),
                        half_length=3., turn_speed_limit=.55)
                    if delta > .30:
                        self.assertEqual(0., command['throttle'])
                        self.assertGreater(command['turn'], 0.)
                    else:
                        self.assertGreater(command['throttle'] * direction, 0.)
                        self.assertAlmostEqual(delta * direction, command['turn'])

    def test_cover_reverse_brakes_opposing_motion_before_changing_gear(self):
        command = Driver().drive((0., 0., 0.), 0., 4., goal(8., math.pi), 0.,
            lambda *args: True, terminal=True, travel_direction=-1.,
            motion_key=('player_cover', 'return'), turn_speed_limit=.55)
        self.assertEqual((0., 0., True),
                         (command['throttle'], command['turn'], command['brake']))

    def test_real_control_passes_installed_traverse_and_keeps_clear_route_forward(self):
        from test_player_control import PlayerRegressionTests
        from test_player_navigation_migration import controller
        control, unused = PlayerRegressionTests().aim_controller()
        owner = control.owner
        entity = owner._server_entity(1)
        entity.typeDescriptor.type = types.SimpleNamespace(tags=('mediumTank',))
        control.features = {'drive'}
        control.navigation = controller('mediumTank')
        self.addCleanup(control.navigation.close)
        route = dict(id='captured_clear_route', waypoints=[
            (POSITION[0], POSITION[2]), (TARGET[0], TARGET[2])])
        control.navigation.routes = control.navigation.selection = [route]
        control.navigation.route, control.navigation.index = route, 1
        control.publish_status = mock.Mock()
        owner.local_pose = lambda: (POSITION, YAW)
        owner._clock = lambda: 1.
        owner._local_speed = SPEED
        owner._local_physics = dict(rotSpd=.55)
        owner._collision_shape = lambda unused: SHAPE
        control.direction_clear = mock.Mock(return_value=True)
        # The live ally is well behind the swept driving corridor; merely
        # observing a teammate must not reinstate the old far-angle brake.
        neighbour = dict(id=37, actor_key=('bot', 7), alive=True, team=1,
            position=(-20., .25, -180.), yaw=0., collision_shape=SHAPE,
            health=1000, max_health=1000, class_tag='heavyTank', speed=0.)
        control._contacts = lambda unused: ([], [neighbour], {})
        with mock.patch.object(control.navigation.driver, 'drive',
                               wraps=control.navigation.driver.drive) as drive, \
             mock.patch('gui.mods.offline_lan_0922.player_control.traffic_laws.traffic_stopping_distance',
                        return_value=.9):
            control.update(.1, 1.)
        self.assertAlmostEqual(.55, drive.call_args.kwargs['turn_speed_limit'])
        self.assertAlmostEqual(SHAPE[1], drive.call_args.kwargs['half_length'])
        self.assertEqual('route', control.last_order['combat_mode'])
        self.assertGreater(owner._sender.forward, 0.)
        self.assertLess(owner._sender.turn, 0.)
        self.assertFalse(owner._sender.handbrake)
        control.direction_clear.assert_called()
        owner._sender.send_current.assert_called()


if __name__ == '__main__':
    unittest.main()
