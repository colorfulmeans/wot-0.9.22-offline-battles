"""Cover movement keeps its gear through the foreground traffic pipeline.

Collision checks use the production hull geometry. Native world predicates
remain explicit seams; these tests do not claim Windows game acceptance.
"""
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))

import test_player_independent_traffic as fixtures
from gui.mods.offline_lan_0922 import vehicle_physics
from gui.mods.offline_lan_0922.player_control.driving import angle
from gui.mods.offline_lan_0922.player_control.navigation import PlayerNavigation
from gui.mods.offline_lan_0922.player_control.traffic import (
    PlayerTraffic, Traffic, TurnClearance, body)
from gui.mods.offline_lan_0922.player_control.wrecks import WreckPush


def cover_order(phase='return', direction=-1, throttle=None, turn=.25, brake=False):
    hull_heading = -.2 if direction < 0 else .2
    travel_heading = angle(hull_heading + (math.pi if direction < 0 else 0.))
    goal = (math.sin(travel_heading) * 6., 0., math.cos(travel_heading) * 6.)
    return dict(throttle=.65 * direction if throttle is None else throttle,
        turn=turn, brake=brake, holding=False, travel_intent=True,
        combat_mode='cover_' + phase, recovery_mode='travel', local_target=goal,
        cover_motion=dict(phase=phase, direction=direction, goal=goal),
        driving=dict(heading=hull_heading, travel_heading=travel_heading))


def traffic_for(own, peers):
    return Traffic(body(own['engine_id'], own['position'], own['yaw'], fixtures.SHAPE), peers)


def cover_hold():
    command = PlayerNavigation._cover_order('cover_hold', (0., 0., 0.))
    command.setdefault('recovery_mode', command['combat_mode'])
    return command


def apply(player, own, peers, command, clear=None, stopping=0., stalled=False, contact=None):
    traffic = traffic_for(own, peers)
    if clear is None:
        clear = lambda heading, reach=6.: traffic.clear(heading, reach)
    player.apply(command, own, traffic, 1, clear, lambda: stopping, 1. / 30.,
                 stalled, None, contact=contact)
    return traffic


class CoverTurnClearanceTests(unittest.TestCase):
    def test_reverse_steering_uses_clear_physical_side_and_retires_old_pivot(self):
        own = fixtures.state()
        traffic = traffic_for(own, [fixtures.peer(2, (2.02, 0., 2.1))])
        self.assertFalse(traffic.can_turn(.25))
        self.assertTrue(traffic.can_turn(-.25))
        clearance = TurnClearance()
        clearance.sign, clearance.heading = 1., 1.4
        clearance.advance_origin = own['position']
        command = cover_order()
        clearance.apply(command, own['yaw'], traffic, own['position'], lambda *args: True)
        self.assertEqual((-.65, .25, False),
                         (command['throttle'], command['turn'], command['brake']))
        self.assertEqual((0., None, None),
                         (clearance.sign, clearance.heading, clearance.advance_origin))
        self.assertNotIn('reverse_only', command)

    def test_blocked_cover_turn_cannot_choose_long_pivot_or_clear_forward_exit(self):
        for phase, direction, x in (('return', -1, -2.02), ('peek', 1, 2.02)):
            with self.subTest(phase=phase):
                own = fixtures.state()
                traffic = traffic_for(own, [fixtures.peer(2, (x, 0., 2.1))])
                self.assertFalse(traffic.can_turn(.25 * direction))
                self.assertTrue(traffic.can_turn(-.25 * direction))
                clearance = TurnClearance()
                command = cover_order(phase, direction)
                clearance.apply(command, own['yaw'], traffic, own['position'],
                                lambda *args: True)
                self.assertEqual((0., 0., True),
                                 (command['throttle'], command['turn'], command['brake']))
                self.assertIsNone(clearance.heading)
                self.assertIsNone(clearance.advance_origin)

    def test_cover_stop_cannot_resume_a_preceding_latched_pivot(self):
        clearance = TurnClearance()
        clearance.sign, clearance.heading = -1., -1.4
        clearance.advance_origin = (0., 0., 0.)
        command = cover_hold()
        own = fixtures.state()
        clearance.apply(command, 0., traffic_for(own, []), own['position'], lambda *args: True)
        self.assertEqual((0., 0., True),
                         (command['throttle'], command['turn'], command['brake']))
        self.assertIsNone(clearance.heading)
        self.assertIsNone(clearance.advance_origin)


class CoverTrafficOwnershipTests(unittest.TestCase):
    def test_cover_releases_an_admitted_forward_escape_without_inheriting_gear(self):
        for held in (False, True):
            with self.subTest(held=held):
                player = PlayerTraffic()
                route = fixtures.order()
                front_only = lambda heading, reach=6.: abs(angle(heading)) < .1
                apply(player, fixtures.state(), [], route, front_only, stalled=True)
                self.assertEqual('short_forward_escape', route['recovery_mode'])
                self.assertGreater(route['throttle'], 0.)
                self.assertIsNotNone(player.escape)
                command = cover_hold() if held else cover_order(turn=0.)
                apply(player, fixtures.state(.1), [], command)
                self.assertEqual((0. if held else -.65, 0., held),
                                 (command['throttle'], command['turn'], command['brake']))
                self.assertIsNone(player.escape)

    def test_blocked_cover_does_not_admit_a_forward_escape_after_wait_or_stall(self):
        player = PlayerTraffic()
        player.wait = 0.
        command = cover_order(throttle=0., turn=0., brake=True)
        apply(player, fixtures.state(2.), [], command,
              lambda heading, reach=6.: abs(angle(heading)) < .1, stalled=True)
        self.assertEqual((0., 0., True),
                         (command['throttle'], command['turn'], command['brake']))
        self.assertIsNone(player.escape)
        self.assertIsNone(player.wait)

    def test_cover_releases_a_previously_admitted_courtesy_translation(self):
        for held in (False, True):
            with self.subTest(held=held):
                player = PlayerTraffic()
                follower = fixtures.peer(2, (0., 0., -4.2), velocity=(0., 0., .3))
                apply(player, fixtures.state(), [follower], fixtures.order('engage', hold=True))
                follower['velocity'] = (0., 0., 0.)
                courtesy = fixtures.order('engage', hold=True)
                apply(player, fixtures.state(1.6), [follower], courtesy)
                self.assertEqual('friendly_yield', courtesy['recovery_mode'])
                self.assertGreater(courtesy['throttle'], 0.)
                command = cover_hold() if held else cover_order(turn=0.)
                apply(player, fixtures.state(1.7), [follower], command)
                self.assertLessEqual(command['throttle'], 0.)
                self.assertNotEqual('friendly_yield', command['recovery_mode'])
                self.assertIsNone(player.parked)

    def test_cover_releases_a_previously_admitted_contact_exit(self):
        for held in (False, True):
            with self.subTest(held=held):
                player = PlayerTraffic()
                rear = fixtures.peer(2, (0., 0., -3.9))
                contact = dict(peer=2, normal=(0., 1.), at=0.)
                route = fixtures.order()
                apply(player, fixtures.state(), [rear], route, contact=contact)
                self.assertEqual('contact_escape', route['recovery_mode'])
                self.assertGreater(route['throttle'], 0.)
                command = cover_hold() if held else cover_order(turn=0.)
                apply(player, fixtures.state(.1), [rear], command,
                      contact=dict(contact, at=.1), stalled=True)
                self.assertLessEqual(command['throttle'], 0.)
                self.assertNotEqual('contact_escape', command['recovery_mode'])
                self.assertIsNone(player.contact_escape)
                self.assertIsNone(player.escape)

    def test_cover_retires_an_existing_head_on_pair_as_a_control_hold(self):
        for held in (False, True):
            with self.subTest(held=held):
                player = PlayerTraffic()
                ahead = fixtures.peer(2, (0., 0., 4.1), math.pi)
                for now in (0., 1.6):
                    apply(player, fixtures.state(now), [ahead], fixtures.order(), lambda *args: False)
                self.assertIn(2, player.pairs)
                self.assertNotEqual('finished', player.pairs[2].get('phase'))
                command = cover_hold() if held else cover_order(turn=0.)
                apply(player, fixtures.state(1.7), [ahead], command)
                self.assertEqual(0. if held else -.65, command['throttle'])
                self.assertNotEqual('head_on_retreat', command['recovery_mode'])
                self.assertEqual('finished', player.pairs[2].get('phase'))
                self.assertEqual('control_hold', player.pairs[2].get('reason'))

    def test_cover_keeps_correct_reverse_steering_at_the_final_vehicle_turn_gate(self):
        player = PlayerTraffic()
        command = cover_order()
        traffic = apply(player, fixtures.state(speed=-2.),
                        [fixtures.peer(2, (2.02, 0., 2.1))], command)
        self.assertFalse(traffic.can_turn(.25))
        self.assertTrue(traffic.can_turn(-.25))
        self.assertEqual((-.65, .25, False),
                         (command['throttle'], command['turn'], command['brake']))

    def test_reverse_vehicle_braking_clears_steering_before_native_sign_changes(self):
        command = cover_order()
        apply(PlayerTraffic(), fixtures.state(speed=-2.),
              [fixtures.peer(2, (0., 0., -5.))], command, stopping=2.)
        self.assertEqual('vehicle_brake', command['traffic_mode'])
        self.assertEqual(2, command['reverse_blocked_by'])
        self.assertEqual((0., 0., True),
                         (command['throttle'], command['turn'], command['brake']))

    def test_cover_rejects_a_previous_wreck_push_for_both_travel_directions(self):
        own = fixtures.state()
        traffic = traffic_for(own, [fixtures.peer(4, (0., 0., 5.), alive=False)])
        for phase, direction in (('return', -1), ('peek', 1), ('hold', 0)):
            with self.subTest(phase=phase):
                push = WreckPush()
                route = fixtures.order()
                self.assertTrue(push.apply(route, own, traffic, lambda *args: True,
                                           pose_clear=lambda *args: True))
                self.assertEqual(4, push.active)
                command = cover_hold() if phase == 'hold' else cover_order(phase, direction)
                expected = dict(command)
                self.assertFalse(push.apply(command, fixtures.state(.1), traffic,
                                            lambda *args: True, pose_clear=lambda *args: True))
                self.assertEqual(expected, command)
                self.assertIsNone(push.active)


class CoverControllerIntegrationTests(unittest.TestCase):
    def controller(self, command):
        controller, nav, unused_entity = (
            fixtures.ForegroundControllerTrafficIntegrationTests().controller())
        nav.decide = lambda state, clear, hold=False: dict(command)
        return controller, nav

    def test_real_update_preserves_steered_reverse_after_route_ownership(self):
        command = cover_order()
        controller, nav = self.controller(command)
        controller.turn_clearance.sign, controller.turn_clearance.heading = 1., 1.4
        controller.turn_clearance.advance_origin = (0., 0., 0.)
        controller.player_traffic.escape = ((0., 0., 0.), 0., 1., 2., 5.)
        nav.driver.replan = True
        controller.update(.1, 1.)
        sender = controller.owner._sender
        self.assertEqual((-.65, .25, False), (sender.forward, sender.turn, sender.handbrake))
        self.assertEqual(command['cover_motion'], controller.last_order['cover_motion'])
        self.assertFalse(controller.last_order.get('reverse_only'))
        self.assertIsNone(controller.turn_clearance.heading)
        self.assertIsNone(controller.player_traffic.escape)
        # Positive measured speed cannot flip steering while the actual
        # emitted pedal requests reverse. This is the copied actuator's law.
        params = dict(speedFwd=20., rotSpd=1., terrainResist=(1., 1., 1.))
        omega = vehicle_physics.traverse_step(params, 0., sender.turn, 2., .1,
                                             drive_intent=sender.forward)
        self.assertLess(omega, 0.)

    def test_real_update_still_rejects_a_blocked_reverse_steering_arc(self):
        command = cover_order()
        controller, unused_nav = self.controller(command)
        controller.owner._local_speed = -2.
        blocker = dict(fixtures.peer(2, (-2.1, 0., -1.7), team=2), visible=True)
        controller._contacts = lambda entity: ([], [blocker], {})
        traffic = Traffic(body(7, (0., 0., 0.), 0., fixtures.SHAPE), [blocker])
        self.assertTrue(traffic.can_turn(-.25))
        self.assertTrue(traffic.clear(math.pi, 2.3))
        self.assertFalse(traffic.can_steer(-.65, .25, -2.))
        controller.update(.1, 1.)
        sender = controller.owner._sender
        self.assertEqual((0., 0., True), (sender.forward, sender.turn, sender.handbrake))
        self.assertEqual(command['cover_motion'], controller.last_order['cover_motion'])

    def test_ordinary_route_keeps_its_admitted_forward_escape(self):
        controller, unused_nav = self.controller(fixtures.order())
        controller.player_traffic.escape = ((0., 0., 0.), 0., 1., 2., 5.)
        controller.update(.1, 1.)
        self.assertEqual('short_forward_escape', controller.last_order['recovery_mode'])
        self.assertEqual((1., 0., False), (controller.owner._sender.forward,
            controller.owner._sender.turn, controller.owner._sender.handbrake))
        self.assertIsNotNone(controller.player_traffic.escape)


if __name__ == '__main__':
    unittest.main()
