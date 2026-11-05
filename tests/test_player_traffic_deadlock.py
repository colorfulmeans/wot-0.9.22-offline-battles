"""Expired foreground traffic leases cannot keep ownership of the controls.

The 2026-11-06 report supplies the local pose, retreat deadline and negative
remaining distance below. It does not supply the peer's contemporaneous pose
or the lease's origin. Those two inputs are explicit synthetic fixtures, not
a claim to replay Windows native physics from this diagnostic log.
"""
import math
import unittest

import test_player_independent_traffic as traffic_fixtures
from test_player_independent_traffic import (
    PlayerTraffic, SHAPE, apply, order, peer, state)


CAPTURED_POSITION = (-47.78124038378273, .2594193775348715, -85.6567111915957)
CAPTURED_YAW = 2.9897614516956694
CAPTURED_DEADLINE = 671.676025390625
CAPTURED_REMAINING = -1.0559615813217356
CAPTURED_LOCAL = 2130706479
CAPTURED_PEER = 2130706502


def captured_lease_fixture():
    """Keep the reported local terminal state; declare the unlogged geometry."""
    sine, cosine = math.sin(CAPTURED_YAW), math.cos(CAPTURED_YAW)
    # An allied Bot has canonical priority despite its larger native handle.
    other = peer(CAPTURED_PEER, (CAPTURED_POSITION[0]+8.*sine,
        CAPTURED_POSITION[1], CAPTURED_POSITION[2]+8.*cosine), CAPTURED_YAW-math.pi)
    other['actor_key'] = ('bot', 24)
    distance = SHAPE[1]*3.2-CAPTURED_REMAINING
    origin = (CAPTURED_POSITION[0]+distance*sine, CAPTURED_POSITION[1],
              CAPTURED_POSITION[2]+distance*cosine)
    lease = dict(mode='head_on', axis=(-sine, -cosine), blocked=True,
        until=CAPTURED_DEADLINE-6., priority=CAPTURED_PEER,
        retreat=CAPTURED_LOCAL, origin=origin, targets={
            CAPTURED_LOCAL:CAPTURED_YAW+.42,
            CAPTURED_PEER:CAPTURED_YAW-math.pi+.42})
    return other, lease


class ForegroundTrafficLeaseLivenessTests(unittest.TestCase):
    def start_blocked_pair(self):
        player = PlayerTraffic()
        other = peer(1, (0., 0., 4.3), math.pi)
        for now in (0., 1.6):
            apply(player, state(now, identity=2), [other], order(), lambda *args:False)
        self.assertEqual(2, player.pairs[1]['retreat'])
        return player, other

    def test_captured_expired_retreat_does_not_own_the_410_second_tail(self):
        player = PlayerTraffic()
        other, lease = captured_lease_fixture()
        player.pairs[CAPTURED_PEER] = lease
        for now in (CAPTURED_DEADLINE, 672., 700., 900., 1077.):
            own = state(now, CAPTURED_POSITION, CAPTURED_YAW, identity=CAPTURED_LOCAL)
            own['actor_key'] = ('player', 1)
            command = dict(order(), throttle=0., turn=.6)
            result = apply(player, own, [other], command, lambda *args:True)
            self.assertEqual(.6, result['turn'], now)
            self.assertFalse(result['brake'], now)
            self.assertNotEqual('head_on_retreat', result['recovery_mode'])
            self.assertNotIn('suppress_fire', result)
            self.assertAlmostEqual(CAPTURED_REMAINING, result['traffic_control']['remaining'])
            self.assertEqual('finished', result['traffic_control']['phase'])

    def test_distance_budget_returns_control_before_deadline(self):
        player, other = self.start_blocked_pair()
        result = apply(player, state(2., (0., 0., -6.6), identity=2), [other],
                       dict(order(), throttle=0., turn=.5), lambda *args:True)
        self.assertEqual(.5, result['turn'])
        self.assertFalse(result['brake'])
        self.assertNotIn('suppress_fire', result)
        self.assertEqual('distance_complete', result['traffic_control']['reason'])
        self.assertEqual('finished', result['traffic_control']['phase'])

    def test_stationary_expired_encounter_cannot_restart_from_clock_alone(self):
        player, other = self.start_blocked_pair()
        for now in (7.5, 7.6, 9., 20., 100., 1000.):
            result = apply(player, state(now, identity=2), [other], order(),
                           lambda *args:True)
            self.assertNotEqual('head_on_retreat', result['recovery_mode'], now)
            self.assertNotEqual('head_on', result.get('traffic_mode'), now)
            self.assertNotIn('suppress_fire', result)
            self.assertEqual('finished', player.pairs[1]['phase'])

    def test_expiration_never_bypasses_live_hull_braking(self):
        player, other = self.start_blocked_pair()
        other['position'] = (0., 0., 4.05)
        result = apply(player, state(8., identity=2), [other], order(), lambda *args:True)
        self.assertEqual('vehicle_brake', result['traffic_mode'])
        self.assertTrue(result['brake'])
        self.assertEqual(0., result['throttle'])
        self.assertEqual(1, result['forward_blocked_by'])
        self.assertNotIn('suppress_fire', result)

    def test_finished_encounter_rearms_after_real_separation_and_reentry(self):
        player, other = self.start_blocked_pair()
        apply(player, state(8., identity=2), [other], order(), lambda *args:True)
        other['position'] = (10., 0., 4.3)
        apply(player, state(10., identity=2), [other], order(), lambda *args:True)
        other['position'] = (0., 0., 4.3)
        result = apply(player, state(11., identity=2), [other], order(), lambda *args:False)
        self.assertEqual('head_on_blocked', result['traffic_mode'])
        self.assertAlmostEqual(12.5, player.pairs[1]['until'])

    def test_subpixel_pose_jitter_does_not_rearm_a_finished_pair(self):
        player, other = self.start_blocked_pair()
        apply(player, state(8., identity=2), [other], order(), lambda *args:True)
        for now, offset in ((10., .001), (12., -.001), (100., .002)):
            other['position'] = (offset, offset, 4.3+offset)
            own = state(now, (offset, offset, offset), yaw=offset, identity=2)
            result = apply(player, own, [other], order(), lambda *args:True)
            self.assertNotIn('suppress_fire', result)
            self.assertEqual('finished', player.pairs[1]['phase'])

    def test_longitudinal_departure_can_clear_the_old_lateral_only_envelope(self):
        player, other = self.start_blocked_pair()
        apply(player, state(8., identity=2), [other], order(), lambda *args:True)
        # Retreating straight does not satisfy the old _cleared predicate:
        # centres have not passed and neither actor has left the lateral lane.
        apply(player, state(10., (0., 0., -10.), identity=2), [other], order(),
              lambda *args:True)
        self.assertFalse(player.pairs)
        result = apply(player, state(11., identity=2), [other], order(), lambda *args:False)
        self.assertEqual('head_on_blocked', result['traffic_mode'])

    def test_finished_peer_does_not_mask_a_different_active_encounter(self):
        player, other = self.start_blocked_pair()
        apply(player, state(8., identity=2), [other], order(), lambda *args:True)
        newcomer = peer(3, (0., 0., 4.6), math.pi)
        result = apply(player, state(9., identity=2), [other, newcomer], order(),
                       lambda *args:False)
        self.assertEqual('head_on_blocked', result['traffic_mode'])
        self.assertEqual('blocked', result['traffic_control']['phase'])
        self.assertEqual(3, result['traffic_control']['peer'])
        self.assertNotIn('retreat', result['traffic_control'])

    def test_two_clients_release_both_roles_and_reenter_symmetrically(self):
        first, second = PlayerTraffic(), PlayerTraffic()
        for now in (0., 1.6, 8., 100.):
            commands = []
            for player, identity, z, yaw, other_id, other_z, other_yaw in (
                    (first, 1, 0., 0., 2, 4.3, math.pi),
                    (second, 2, 4.3, math.pi, 1, 0., 0.)):
                result = apply(player, state(now, (0., 0., z), yaw, identity=identity),
                    [peer(other_id, (0., 0., other_z), other_yaw)], order(), lambda *args:False)
                commands.append(result)
            if now >= 8.:
                for command in commands:
                    self.assertEqual('finished', command['traffic_control']['phase'])
                    self.assertNotIn('suppress_fire', command)
        # One public displacement, viewed from opposite local owners, clears
        # both memories. Neither endpoint reads the other's orders or lease.
        for player, identity, position, yaw, other in (
                (first, 1, (0., 0., 0.), 0., peer(2, (10., 0., 4.3), math.pi)),
                (second, 2, (10., 0., 4.3), math.pi, peer(1, (0., 0., 0.)))):
            apply(player, state(101., position, yaw, identity=identity), [other], order())
            self.assertFalse(player.pairs)

    def test_real_reentry_cannot_bypass_finite_backoff(self):
        player, other = self.start_blocked_pair()
        apply(player, state(8., identity=2), [other], order(), lambda *args:True)
        other['position'] = (10., 0., 4.3)
        apply(player, state(8.1, identity=2), [other], order(), lambda *args:True)
        other['position'] = (0., 0., 4.3)
        result = apply(player, state(8.2, identity=2), [other], order(), lambda *args:False)
        self.assertEqual('finished', result['traffic_control']['phase'])
        self.assertNotIn('suppress_fire', result)
        result = apply(player, state(9.6, identity=2), [other], order(), lambda *args:False)
        self.assertEqual('head_on_blocked', result['traffic_mode'])

    def test_reused_native_identity_does_not_inherit_spent_encounter(self):
        player = PlayerTraffic()
        own = state(identity=2)
        own['actor_key'] = ('player', 2)
        other = peer(1, (0., 0., 4.3), math.pi)
        other['actor_key'] = ('player', 1)
        for now in (0., 1.6, 8.):
            own['now'] = now
            apply(player, own, [other], order(), lambda *args:False)
        self.assertEqual('finished', player.pairs[1]['phase'])
        other['actor_key'] = ('player', 3)
        own['now'] = 8.1
        result = apply(player, own, [other], order(), lambda *args:False)
        self.assertEqual('head_on_blocked', result['traffic_mode'])
        self.assertAlmostEqual(9.6, player.pairs[1]['until'])

    def test_peer_disappearance_death_team_change_and_level_change_clear_memory(self):
        for changed in ('missing', 'dead', 'enemy', 'other_level'):
            with self.subTest(changed=changed):
                player, other = self.start_blocked_pair()
                apply(player, state(8., identity=2), [other], order(), lambda *args:True)
                if changed == 'dead':
                    other['alive'] = False
                elif changed == 'enemy':
                    other['team'] = 2
                elif changed == 'other_level':
                    other['position'] = (0., 10., 4.3)
                apply(player, state(9., identity=2), [] if changed == 'missing' else [other],
                      order(), lambda *args:True)
                self.assertFalse(player.pairs)

    def test_expired_crossing_yield_does_not_restart_for_static_observations(self):
        player = PlayerTraffic()
        crossing = peer(1, (-5., 0., 0.), math.pi/2., (5., 0., 0.))
        for now in (0., 2., 20., 200.):
            result = apply(player, state(now, (0., 0., -5.), speed=5., identity=2),
                           [crossing], order(), lambda *args:True)
            if now:
                self.assertNotEqual('yield', result.get('traffic_mode'))
                self.assertEqual('finished', player.pairs[1]['phase'])

    def test_expired_short_escape_hands_back_before_a_fresh_attempt(self):
        player = PlayerTraffic()
        started = apply(player, state(1.), [], order(), lambda *args:True, stalled=True)
        self.assertEqual('short_reverse_escape', started['recovery_mode'])
        for now in (5.1, 5.2, 6.5):
            result = apply(player, state(now), [], dict(order(), throttle=0., turn=.6),
                           lambda *args:True, stalled=True)
            self.assertEqual('travel', result['recovery_mode'])
            self.assertEqual(.6, result['turn'])
            self.assertIsNone(player.escape)
        result = apply(player, state(6.7), [], order(), lambda *args:True, stalled=True)
        self.assertEqual('short_forward_escape', result['recovery_mode'])

    def test_explicit_stop_retires_prior_pair_without_leaking_a_later_retreat(self):
        player, other = self.start_blocked_pair()
        held = order('physical_hold', hold=True)
        result = apply(player, state(2., identity=2), [other], held, lambda *args:True)
        self.assertEqual('hold', result['recovery_mode'])
        result = apply(player, state(2.1, identity=2), [other], order(), lambda *args:True)
        self.assertNotEqual('head_on_retreat', result['recovery_mode'])
        self.assertNotIn('suppress_fire', result)
        self.assertEqual('finished', player.pairs[1]['phase'])


class ForegroundControllerExpiredTrafficTests(unittest.TestCase):
    controller = traffic_fixtures.ForegroundControllerTrafficIntegrationTests.controller

    def test_real_update_and_driver_receive_control_after_captured_retreat(self):
        controller, navigation, entity = self.controller()
        other, lease = captured_lease_fixture()
        owner = controller.owner
        entity.id = owner._server.vehicle_id = CAPTURED_LOCAL
        owner.local_pose = lambda:(CAPTURED_POSITION, CAPTURED_YAW)
        controller._contacts = lambda unused:([], [other], {})
        controller.player_traffic.pairs[CAPTURED_PEER] = lease
        goal = (-50., .26, -90.)
        def decide(current, clear, hold=False):
            result = navigation.driver.drive(current['position'], current['yaw'],
                current['speed'], goal, current['now'], clear)
            return dict(result, travel_intent=True, combat_mode='route', holding=False,
                        local_target=goal, driving=dict(navigation.driver.receipt))
        navigation.decide = decide
        controller.update(.1, 672.)
        self.assertEqual('align', controller.last_order['recovery_mode'])
        self.assertGreater(owner._sender.turn, 0.)
        self.assertFalse(owner._sender.handbrake)
        self.assertNotIn('suppress_fire', controller.last_order)
        # The pose deliberately stays fixed: local recovery must remain live
        # rather than letting the spent traffic lease silence each new plan.
        for now in (676., 680., 700., 900., 1077.):
            controller.update(.1, now)
            self.assertNotEqual('head_on_retreat', controller.last_order['recovery_mode'])
            self.assertTrue(owner._sender.forward or owner._sender.turn, now)
            self.assertNotIn('suppress_fire', controller.last_order)


if __name__ == '__main__':
    unittest.main()
