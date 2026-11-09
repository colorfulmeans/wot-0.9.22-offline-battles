"""Retired tactics cannot override retained route and physical movement owners.

This replaces the old tactical-withdrawal and withdrawal-handoff contracts.
Those contracts required an explicitly removed strategy; collision recovery,
gun-angle destination driving and firing holds remain production behavior.
"""
import importlib
import inspect
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'src/res/scripts/client'))


class AdapterTacticalCleanupTests(unittest.TestCase):
    def implementations(self):
        for prefix in ('gui.mods.offline_lan_0922',
                       'gui.mods.offline_lan_0922.player_control.copied'):
            yield (importlib.import_module(prefix + '.ai.adapter'),
                   importlib.import_module(prefix + '.ai.driver'))

    def fixture(self, module):
        adapter = module.BotAdapter('01_karelia', 7)
        state = dict(id=11, slot=0, position=(0., 0., 0.), yaw=0.,
                     speed=0., dt=.1, half_length=3.5, half_width=1.5,
                     neighbours=[], pose_clear=lambda yaw: True)
        order = dict(combat_mode='route', target_id=None,
                     move_position=(0., 0., 20.), fire_range=500.,
                     throttle_override=None, fire_allowed=False)
        return adapter, state, order

    def test_no_retreat_or_flank_state_and_no_compatibility_helpers(self):
        for module, driver in self.implementations():
            adapter, state, order = self.fixture(module)
            for name in ('_reverse_withdrawal', '_withdrawal_attempts',
                         '_flank_arrivals', '_reverse_mechanical_adjustment'):
                self.assertFalse(hasattr(adapter, name), (module.__name__, name))
            for function in (driver.combat_hull_aim,
                             driver._reference_combat_hull_aim):
                self.assertNotIn('withdrawal_aim', inspect.signature(function).parameters)
            result = adapter.decide_with_order(state, order, lambda *a: True)
            self.assertNotIn('withdrawal', result)
            self.assertNotIn('withdrawal_aim', result)
            self.assertNotIn('flank_arrival', result['control_trace'])
            adapter.forget(11)

    def test_route_forward_motion_keeps_ordinary_driver(self):
        for module, unused in self.implementations():
            adapter, state, order = self.fixture(module)
            result = adapter.decide_with_order(state, order, lambda *a: True)
            self.assertEqual('drive', result['recovery_mode'])
            self.assertGreater(result['throttle'], 0.)
            self.assertTrue(result['movement_intent'])

    def test_mechanical_destinations_keep_existing_driver_and_override(self):
        for module, unused in self.implementations():
            for z in (-8., 8.):
                adapter, state, order = self.fixture(module)
                order.update(combat_mode='gun_angle_adjust', target_id=2,
                             move_position=(0., 0., z), throttle_override=1.)
                with mock.patch.object(adapter.driver, 'drive',
                        wraps=adapter.driver.drive) as drive:
                    result = adapter.decide_with_order(state, order, lambda *a: True)
                drive.assert_called_once()
                self.assertEqual((0., 0., z), drive.call_args[0][6])
                self.assertTrue(drive.call_args[1]['movement_intent'])
                self.assertEqual('gun_angle_adjust', result['combat_mode'])
                self.assertNotEqual('reverse_withdraw', result['recovery_mode'])

    def test_explicit_hold_does_not_start_any_motion_strategy(self):
        for module, unused in self.implementations():
            adapter, state, order = self.fixture(module)
            order.update(throttle_override=0.)
            result = adapter.decide_with_order(state, order, lambda *a: True)
            self.assertEqual(0., result['throttle'])
            self.assertTrue(result['brake'])
            self.assertFalse(result['movement_intent'])

    def test_engagement_hold_preserves_target_ammunition_and_fire_intent(self):
        for module, unused in self.implementations():
            adapter, state, order = self.fixture(module)
            order.update(combat_mode='engage', target_id=2,
                         move_position=state['position'],
                         aim_position=(0., 0., 100.), face_position=(0., 0., 100.),
                         fire_allowed=True, shell_index=2, throttle_override=0.)
            result = adapter.decide_with_order(state, order, lambda *a: True)
            self.assertEqual((2, 2, True),
                             (result['target_id'], result['shell_index'], result['fire_allowed']))
            self.assertEqual(0., result['throttle'])
            self.assertEqual('combat_hold', result['control_trace']['action_owner'])

    def test_physical_rejection_still_reaches_checked_driver(self):
        for module, unused in self.implementations():
            adapter, state, order = self.fixture(module)
            result = adapter.decide_with_order(state, order, lambda *a: False)
            self.assertEqual((0., 0.), (result['throttle'], result['turn']))
            self.assertEqual('blocked', result['recovery_mode'])
            self.assertGreater(adapter.driver.states[11]['clock'], 0.)

    def test_pending_navigation_remains_wait_not_tactical_reverse(self):
        for module, unused in self.implementations():
            adapter, state, order = self.fixture(module)
            adapter.navigation_target = lambda *a: state['position']
            result = adapter.decide_with_order(state, order, lambda *a: True)
            self.assertEqual('nav_wait', result['recovery_mode'])
            self.assertEqual(0., result['throttle'])

    def test_physical_reverse_and_unsticking_retain_control_over_aiming(self):
        for unused, driver in self.implementations():
            for mode in ('reverse_turn', 'short_reverse_escape', 'contact_escape',
                         'wreck_push', 'pivot_recovery', 'blocked'):
                self.assertEqual((-.2, -.72, False), driver.combat_hull_aim(
                    0., 2.9, -.1, .1, -.2, -.72, mode, True,
                    combat_mode='route', movement_intent=True))

    def test_native_call_has_no_active_tactical_slot(self):
        for unused, driver in self.implementations():
            with mock.patch.object(driver.native_math, 'call', return_value=None) as call:
                driver.combat_hull_aim(0., 0., -.1, .1, 0., 0., 'arrived', True,
                                       combat_mode='engage')
            self.assertEqual((0, 1, 1, 0, 0, 1), call.call_args[0][3])


if __name__ == '__main__':
    unittest.main()
