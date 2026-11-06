"""A refused turn may retain a fully proved straight waypoint approach.

The pose is the 24.42 s settled frame of the report-144204 opening replay,
not a claimed native pose. Its fourteen collision bodies are the captured
report roster. Native world replies are explicit seams. The preceding frame
still had angular velocity, so a zero-turn command was not yet a straight
physical trajectory.
"""
import copy
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control.driving import Driver
from gui.mods.offline_lan_0922.player_control.traffic import Traffic, body, steering_reach
from test_player_stationary_waypoint import PLAYER_SHAPE, captured_pit_neighbours


POSITION = (-63.55030459826099, .25, -117.46075994169222)
YAW = -.6080466905610693
TARGET = (-64.09645830609244, .279, -116.00317478873046)


class PlayerCornerClearanceTests(unittest.TestCase):
    def scene(self, speed=0., neighbours=None):
        traffic = Traffic(body(2130706436, POSITION, YAW, PLAYER_SHAPE),
                          captured_pit_neighbours() if neighbours is None else neighbours)
        driver = Driver()
        command = driver.drive(POSITION, YAW, speed, TARGET, 59.441,
            traffic.clear, half_length=PLAYER_SHAPE[1], turn_speed_limit=.7783950319281508,
            request_key=('player_route', 1, 'captured_opening'))
        command.update(local_target=TARGET, combat_mode='route', travel_intent=True,
                       holding=False, driving=driver.receipt)
        return traffic, command

    def test_captured_arc_refusal_can_consume_corner_with_same_full_straight_sweep(self):
        traffic, command = self.scene()
        self.assertEqual('travel', command['recovery_mode'])
        self.assertAlmostEqual(.4302433359334852, command['turn'])
        self.assertFalse(traffic.can_steer(command['throttle'], command['turn'], 0.))
        self.assertTrue(traffic.can_steer(command['throttle'], 0., 0.))
        before = copy.deepcopy(command)
        calls = []
        proof = traffic.corner_straight_proof(command, 0., 0.,
            lambda heading, reach: calls.append((heading, reach)) or True)
        self.assertIsNotNone(proof)
        self.assertEqual(before, command)
        self.assertEqual('corner_straight', proof['kind'])
        self.assertEqual([(YAW, 1.)], calls)
        self.assertEqual(1., proof['reach'])
        self.assertEqual(1.5, proof['arrival_radius'])
        self.assertEqual(1., proof['fraction'])
        self.assertAlmostEqual(.05842602745519021, proof['entry_distance'])
        self.assertLess(proof['closest_distance'], proof['arrival_radius'])
        # Arrival remains the ordinary Driver/pathfinder 1.5 m threshold;
        # the approach does not consume or move the waypoint on its behalf.
        step = proof['entry_distance'] + .001
        reached = (POSITION[0] + math.sin(YAW) * step, POSITION[1],
                   POSITION[2] + math.cos(YAW) * step)
        arrived = Driver().drive(reached, YAW, .45, TARGET, 59.551,
                                 lambda *args: True)
        self.assertEqual('hold', arrived['recovery_mode'])

    def test_nonzero_native_rotation_waits_even_when_a_new_zero_turn_would_fit(self):
        traffic, command = self.scene()
        for omega in (.377165001, -.377165001, .000000001, None, float('nan')):
            with self.subTest(omega=omega):
                calls = []
                self.assertIsNone(traffic.corner_straight_proof(command, 0., omega,
                    lambda *args: calls.append(args) or True))
                self.assertEqual([], calls)

    def test_reverse_or_opposing_motion_cannot_borrow_forward_proof(self):
        traffic, original = self.scene()
        for throttle, speed in ((.45, -.001), (-.45, 0.), (-.45, -1.), (0., 0.)):
            with self.subTest(throttle=throttle, speed=speed):
                command = dict(original, throttle=throttle)
                self.assertIsNone(traffic.corner_straight_proof(
                    command, speed, 0., lambda *args: True))

    def test_hold_terminal_cover_and_recovery_owners_keep_their_commands(self):
        traffic, original = self.scene()
        changes = (
            ('terminal', {}, {'terminal': True}),
            ('unknown_terminal', {}, {'terminal': None}),
            ('held', {'holding': True}, {}),
            ('protected_hold', {'traffic_hold_protected': True}, {}),
            ('braking', {'brake': True}, {}),
            ('cover', {'cover_motion': {'phase': 'peek', 'direction': 1.}}, {}),
            ('no_travel', {'travel_intent': False}, {}),
            ('reverse_lease', {'recovery_mode': 'reverse_clearance'}, {}),
            ('forward_lease', {'recovery_mode': 'forward_clearance'}, {}),
            ('short_escape', {'recovery_mode': 'short_reverse_escape'}, {}),
            ('traffic_turn', {'recovery_mode': 'vehicle_turn_clearance_latched'}, {}),
            ('detour', {}, {'recovery_heading': YAW}),
            ('driver_alignment', {}, {'mode': 'align'}),
        )
        for label, order_fields, driver_fields in changes:
            with self.subTest(owner=label):
                command = copy.deepcopy(original)
                command.update(order_fields)
                command['driving'].update(driver_fields)
                before = copy.deepcopy(command)
                self.assertIsNone(traffic.corner_straight_proof(
                    command, 0., 0., lambda *args: True))
                self.assertEqual(before, command)
        without_receipt = dict(original)
        without_receipt.pop('driving')
        self.assertIsNone(traffic.corner_straight_proof(
            without_receipt, 0., 0., lambda *args: True))

    def test_ray_must_enter_the_existing_arrival_disc_within_original_reach(self):
        traffic, original = self.scene()
        for label, along, lateral in (
                ('miss', .5, 1.5001), ('tangent', 1., 1.5),
                ('behind', -2., 0.), ('too_far', 2.5001, 0.),
                ('already_arrived', 1., .1)):
            with self.subTest(reason=label):
                point = (POSITION[0] + math.sin(YAW) * along + math.cos(YAW) * lateral,
                         POSITION[1],
                         POSITION[2] + math.cos(YAW) * along - math.sin(YAW) * lateral)
                command = dict(original, local_target=point)
                self.assertIsNone(traffic.corner_straight_proof(
                    command, 0., 0., lambda *args: True))

    def test_full_world_sweep_cannot_be_replaced_by_the_short_arrival_segment(self):
        traffic, command = self.scene()
        calls = []
        def world(heading, reach):
            calls.append((heading, reach))
            return reach < .1
        self.assertIsNone(traffic.corner_straight_proof(command, 0., 0., world))
        self.assertEqual([(YAW, 1.)], calls)

    def test_hull_after_the_arrival_disc_still_blocks_the_full_speed_horizon(self):
        neighbours = captured_pit_neighbours()
        # The extra test body is beyond the short arrival segment and the
        # one-metre rest horizon, but lies inside the speed-dependent sweep.
        neighbours.append(dict(id=999, alive=True, team=1, yaw=YAW,
            position=(POSITION[0]+math.sin(YAW)*5.6, .25,
                      POSITION[2]+math.cos(YAW)*5.6),
            collision_shape=(.3, .3, 0., 2.)))
        unused_traffic, command = self.scene()
        traffic = Traffic(body(2130706436, POSITION, YAW, PLAYER_SHAPE), neighbours)
        self.assertEqual('travel', command['recovery_mode'])
        self.assertTrue(traffic.clear(YAW, 1.))
        self.assertFalse(traffic.clear(YAW, steering_reach(4.)))
        self.assertIsNone(traffic.corner_straight_proof(
            command, 4., 0., lambda *args: True))

    def test_new_close_hull_rejects_straight_even_when_old_command_was_travel(self):
        unused_traffic, command = self.scene()
        neighbours = captured_pit_neighbours()
        neighbours.append(dict(id=999, alive=True, team=1, yaw=YAW,
            position=(POSITION[0]+math.sin(YAW)*3.6, .25,
                      POSITION[2]+math.cos(YAW)*3.6),
            collision_shape=(.3, .3, 0., 2.)))
        traffic = Traffic(body(2130706436, POSITION, YAW, PLAYER_SHAPE), neighbours)
        self.assertEqual('travel', command['recovery_mode'])
        self.assertFalse(traffic.can_steer(command['throttle'], command['turn'], 0.))
        self.assertFalse(traffic.clear(YAW, 1.))
        self.assertIsNone(traffic.corner_straight_proof(
            command, 0., 0., lambda *args: True))

    def test_moving_straight_positive_uses_the_same_unshortened_horizon(self):
        traffic, command = self.scene(speed=.37114712759247204)
        self.assertFalse(traffic.can_steer(command['throttle'], command['turn'], .37114712759247204))
        calls = []
        proof = traffic.corner_straight_proof(command, .37114712759247204, 0.,
            lambda heading, reach: calls.append((heading, reach)) or True)
        self.assertIsNotNone(proof)
        self.assertAlmostEqual(1.2412456329351068, proof['reach'])
        self.assertEqual([(YAW, proof['reach'])], calls)


if __name__ == '__main__':
    unittest.main()
