"""Withdrawal orders through the real adapter and local safety probes."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'src/res/scripts/client'))
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.ai.driver import combat_hull_aim


class WithdrawalTests(unittest.TestCase):
    def setUp(self):
        self.adapter = BotAdapter('01_karelia', 7)
        self.state = dict(id=11, slot=0, position=(0., 0., 0.), yaw=0.,
                          speed=0., dt=.1, half_length=3.5, half_width=1.5,
                          neighbours=[], pose_clear=lambda yaw: True)
        self.order = dict(combat_mode='low_health_retreat', target_id=2,
                          aim_position=(0., 0., 100.), face_position=(0., 0., 100.),
                          move_position=(0., 0., -20.), fire_range=500.,
                          throttle_override=None, fire_allowed=True)

    def decide(self, clear=lambda *args: True):
        return self.adapter.decide_with_order(self.state, self.order, clear)

    def test_every_withdrawal_mode_backs_without_exposing_rear(self):
        for mode in ('withdraw', 'low_health_retreat', 'under_fire_withdraw',
                     'crossfire_withdraw'):
            self.order['combat_mode'] = mode
            result = self.decide()
            self.assertLess(result['throttle'], 0.)
            self.assertAlmostEqual(0., result['turn'])
            self.assertAlmostEqual(0., math.sin(result['target_yaw']))
            self.assertGreater(math.cos(result['target_yaw']), .99)
            self.assertEqual(self.order['aim_position'], result['aim_position'])
            self.assertTrue(result['fire_allowed'])

    def test_shallow_diagonal_backs_with_correct_reverse_steering_sign(self):
        self.order['move_position'] = (-5., 0., -20.)
        result = self.decide()
        self.assertLess(result['throttle'], 0.)
        self.assertLess(result['turn'], 0.)
        self.assertLess(abs(result['turn']), .5)
        self.assertGreater(math.cos(result['target_yaw']), .9)

    def test_reverse_sweep_rejects_rear_hulls_of_every_team_and_wrecks(self):
        for team, alive in ((1, True), (2, True), (2, False)):
            self.state['neighbours'] = [dict(id=22, team=team, alive=alive,
                position=(0., 0., -8.), yaw=0., half_length=3.5, half_width=1.5)]
            result = self.decide()
            self.assertEqual((0., 0.), (result['throttle'], result['turn']))

    def test_water_cliff_or_static_probe_denial_holds_instead_of_turning(self):
        result = self.decide(lambda *args: False)
        self.assertEqual((0., 0.), (result['throttle'], result['turn']))
        self.assertEqual('blocked', result['recovery_mode'])

    def test_intermediate_rotation_is_checked_not_only_end_heading(self):
        self.order['move_position'] = (-5., 0., -20.)
        self.state['pose_clear'] = lambda yaw: not .05 < yaw < .2
        self.assertEqual(0., self.decide()['throttle'])

    def test_stopping_distance_brakes_before_withdrawal_endpoint(self):
        self.state.update(speed=-5., stopping_distance=12.)
        self.order['move_position'] = (0., 0., -10.)
        self.assertEqual((0., 0.), (self.decide()['throttle'], self.decide()['turn']))

    def test_arrival_and_explicit_defensive_hold_remain_stationary(self):
        self.order['move_position'] = self.state['position']
        self.assertEqual(0., self.decide()['throttle'])
        self.order.update(move_position=(0., 0., -20.), throttle_override=0.)
        self.assertEqual(0., self.decide()['throttle'])

    def test_long_withdrawal_backs_until_in_range_contact_is_lost(self):
        self.order['move_position'] = (0., 0., -100.)
        self.assertLess(self.decide()['throttle'], 0.)
        self.order['target_id'] = None
        self.assertNotEqual('reverse_withdraw', self.decide()['recovery_mode'])

    def test_short_navigation_corner_does_not_reclassify_long_safe_travel(self):
        self.order.update(move_position=(0., 0., -100.), target_id=None)
        self.adapter.navigation_target = lambda *args: (0., 0., -10.)
        self.assertNotEqual('reverse_withdraw', self.decide()['recovery_mode'])

    def test_pending_navigation_stays_pending_and_does_not_reverse(self):
        self.order['move_position'] = (0., 0., -100.)
        self.adapter.navigation_target = lambda *args: self.state['position']
        result = self.decide()
        self.assertEqual('nav_wait', result['recovery_mode'])
        self.assertEqual(0., result['throttle'])

    def test_ordinary_route_and_forward_destination_keep_normal_driver(self):
        self.order['combat_mode'] = 'route'
        self.assertNotEqual('reverse_withdraw', self.decide()['recovery_mode'])
        self.order.update(combat_mode='low_health_retreat', move_position=(0., 0., 20.))
        self.assertGreater(self.decide()['throttle'], 0.)

    def test_fixed_gun_aiming_cannot_steal_reverse_withdrawal_controls(self):
        self.assertEqual((-.2, -.72, False), combat_hull_aim(
            0., 1., -.1, .1, -.2, -.72, 'reverse_withdraw', True,
            combat_mode='low_health_retreat', movement_intent=True))

    def test_denied_reverse_expires_and_local_recovery_keeps_ownership(self):
        for mode in ('withdraw', 'low_health_retreat', 'under_fire_withdraw',
                     'crossfire_withdraw'):
            with self.subTest(mode=mode):
                self.setUp()
                self.order['combat_mode'] = mode
                rear_denied = lambda yaw, *unused: math.cos(yaw) > .1
                self.assertEqual('blocked', self.decide(rear_denied)['recovery_mode'])
                for unused in range(85):
                    result = self.decide(rear_denied)
                self.assertNotEqual('blocked', result['recovery_mode'])
                self.assertTrue(self.adapter._withdrawal_attempts[11]['fallback'])
                # A transient clear rear ray must not restart the failed owner.
                self.assertNotEqual('reverse_withdraw', self.decide()['recovery_mode'])
                self.state['position'] = (0., 0., 3.)
                self.assertNotEqual('reverse_withdraw', self.decide()['recovery_mode'])
                self.state['position'] = (0., 0., -2.1)
                self.assertEqual('reverse_withdraw', self.decide()['recovery_mode'])

    def test_clear_reverse_without_actual_translation_also_expires(self):
        for unused in range(85):
            result = self.decide()
        self.assertNotEqual('reverse_withdraw', result['recovery_mode'])
        self.adapter.forget(11)
        self.assertNotIn(11, self.adapter._withdrawal_attempts)

    def test_real_reverse_progress_and_explicit_hold_reset_attempt(self):
        for unused in range(150):
            self.state['position'] = (0., 0., self.state['position'][2] - .1)
            self.assertEqual('reverse_withdraw', self.decide()['recovery_mode'])
        self.order['throttle_override'] = 0.
        self.decide()
        self.assertNotIn(11, self.adapter._withdrawal_attempts)


if __name__ == '__main__':
    unittest.main()
