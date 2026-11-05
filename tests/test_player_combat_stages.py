"""Regression scenarios for the foreground pivot and staged search owners."""
import math
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control import PlayerControl
from gui.mods.offline_lan_0922.player_control.traffic import Traffic, body
from gui.mods.offline_lan_0922 import vehicle_physics
import test_player_control_integration_review as fixtures


class CombatStageScenarios(unittest.TestCase):
    def test_same_pose_and_input_match_actual_drive_step(self):
        from test_port_0922_battle_runtime import (
            BattleRuntime, _runtime, _Client, _Vehicle, _Descriptor, _Vector)
        for status in ('clear', 'hard'):
            with self.subTest(catalog=status):
                runtime = _runtime()
                battle = BattleRuntime(runtime)
                battle.client = _Client()
                battle._avatar = runtime.bigworld.avatar
                entity = _Vehicle(10, _Descriptor(), _Vector(2, 3, 4),
                                  (0, 0, 0), {'health': 500})
                runtime.bigworld.entities[10] = entity
                battle._server = types.SimpleNamespace(vehicle_id=10)
                battle._sender = types.SimpleNamespace(forward=0., turn=-1.,
                    handbrake=False, send_current=mock.Mock(return_value=True))
                battle._local_position, battle._local_yaw = (2., 3., 4.), 0.
                battle._local_descriptor = entity.typeDescriptor
                battle._attach_local_presentation()
                battle._local_physics = dict(vehicle_physics.derive_params(entity.typeDescriptor),
                    rotSpd=1., rotationIsAroundCenter=False, trackCenter=1.5)
                battle._destructibles = types.SimpleNamespace(
                    _vehicle_hull_bbox=lambda td: td.hull.hitTester.bbox,
                    _catalog_motion_proposal=mock.Mock(return_value=dict(
                        status=status, token=None, kinds='structure', requires_commit=False)),
                    take_ground_skip_count=mock.Mock(return_value=0))
                battle._native_world_rotation_is_clear = mock.Mock(
                    side_effect=lambda *a, **kw: not kw.get('include_static', False))
                battle._smoothed_drive_pitch = mock.Mock(return_value=0.)
                battle._update_vertical_motion = mock.Mock(side_effect=lambda e, p, y, dt: p)
                battle._ground_pitch = mock.Mock(return_value=0.)
                battle._apply_slope_slide = mock.Mock(side_effect=lambda p, y, dt, e=None: p)
                battle._resolve_local_tank_contacts = mock.Mock(side_effect=lambda e, p, y, dt: p)
                control = PlayerControl(battle, ('drive', 'fire'))
                state = dict(position=(2., 3., 4.), yaw=0., speed=0., now=1.,
                             decision_horizon=.5, physics_dt=.1)
                shape = battle._collision_shape(entity.typeDescriptor)
                traffic = Traffic(body(10, state['position'], 0., shape), [])
                with mock.patch('gui.mods.offline_lan_0922.battle_runtime.vehicle_physics.longitudinal_step',
                                return_value=0.):
                    allowed = control.combat_pivot_clear(entity, state, traffic, -1., None)
                    preview = control.pivot_receipt
                    battle._drive_local(.1)
                self.assertEqual(status == 'clear', allowed)
                if allowed:
                    self.assertAlmostEqual(preview['end_yaw'], battle._local_yaw)
                    for expected, actual in zip(preview['end'], battle._local_position):
                        self.assertAlmostEqual(expected, actual)
                else:
                    self.assertEqual(0., battle._local_yaw)
                self.assertTrue(all(not call.kwargs.get('include_static', False)
                    for call in battle._native_world_rotation_is_clear.call_args_list))
                self.assertEqual(status, preview['catalog']['status'])

    def test_report_141316_spotted_unavailable_contacts_keep_route_and_forward_turret(self):
        control, target = fixtures.PlayerControlIntegrationReviewTests().direct_facing_controller()
        owner = control.owner
        from test_player_navigation_migration import controller as navigation_controller
        control.navigation = navigation_controller(tag='mediumTank')
        owner.local_pose = lambda: ((7.2566, .26, -60.0757), -.01724)
        target.position = (6., .32, 94.)  # 154 m: inside the captured 135 * 1.15 threshold.
        other = types.SimpleNamespace(id=target.id+1, position=(15., .32, 82.),
                                      typeDescriptor=target.typeDescriptor)
        control._contacts = lambda unused: ([], [], {target.id: target, other.id: other})
        control.aiming.compare_direct.side_effect = None
        control.aiming.compare_direct.return_value = ('unavailable', None)
        control.navigation.firing_position = mock.Mock()
        control.navigation.ammo_withdrawal = mock.Mock()
        control.navigation.decide = mock.Mock(side_effect=lambda *a, **kw: dict(
            throttle=0. if kw['hold'] else 1., turn=0., brake=kw['hold'],
            holding=kw['hold'], travel_intent=not kw['hold'],
            combat_mode='engage' if kw['hold'] else 'route',
            recovery_mode='hold' if kw['hold'] else 'travel'))
        for now in (1., 1.2, 2., 9.5, 16., 60.):
            control.update(.1, now)
            self.assertEqual(1., owner._sender.forward)
            self.assertFalse(owner._sender.handbrake)
            self.assertIsNone(control.direct_engagement.phase_since)
            self.assertFalse(control.direct_engagement.seek or control.direct_engagement.retreat)
        control.navigation.firing_position.assert_not_called()
        control.navigation.ammo_withdrawal.assert_not_called()
        control.weapon.forward.assert_called()
        self.assertTrue(control.direct_engagement.clear_for_cruise)
        # A new pending contact is not a reason to stop, but is not a completed
        # no-engagement proof for centering the turret either.
        control.weapon.forward.reset_mock()
        third = types.SimpleNamespace(id=target.id+2, position=target.position,
                                      typeDescriptor=target.typeDescriptor)
        control._contacts = lambda unused: ([], [], {third.id: third})
        control.aiming.compare_direct.return_value = ('pending', None)
        for now in (61., 62., 80.):
            control.update(.1, now)
            self.assertEqual(1., owner._sender.forward)
        control.weapon.forward.assert_not_called()
        control.aiming.compare_direct.return_value = ('unknown', None)
        for now in (81., 82., 100.):
            control.update(.1, now)
            self.assertEqual(1., owner._sender.forward)
        control.weapon.forward.assert_not_called()
        self.assertFalse(control.direct_engagement.clear_for_cruise)

    @mock.patch('gui.mods.offline_lan_0922.player_control.weapon.barrel_aligned', return_value=True)
    def test_lost_or_distant_admitted_contact_cannot_lend_its_clock_to_raw_contact(self, unused):
        for keep_distant in (False, True):
            with self.subTest(still_spotted=keep_distant):
                control, target = fixtures.PlayerControlIntegrationReviewTests().direct_facing_controller()
                control.update(.1, 1.)
                self.assertTrue(control.direct_engagement.active_engagement)
                raw = types.SimpleNamespace(id=target.id+1, position=(-70., 0., 20.),
                                            typeDescriptor=target.typeDescriptor)
                target.position = (1000., 0., 1000.)
                records = {raw.id: raw}
                if keep_distant:
                    records[target.id] = target
                control._contacts = lambda unused: ([], [], records)
                control.aiming.compare_direct.side_effect = None
                control.aiming.compare_direct.return_value = ('unavailable', None)
                control.navigation.decide = mock.Mock(side_effect=lambda *a, **kw: dict(
                    throttle=0. if kw['hold'] else 1., turn=0., brake=kw['hold'],
                    holding=kw['hold'], travel_intent=not kw['hold'],
                    combat_mode='engage' if kw['hold'] else 'route',
                    recovery_mode='hold' if kw['hold'] else 'travel'))
                for now in (2., 10., 20.):
                    control.update(.1, now)
                    self.assertEqual(1., control.owner._sender.forward)
                    self.assertIsNone(control.direct_engagement.phase_since)
                    self.assertFalse(control.direct_engagement.active_engagement)

    @mock.patch('gui.mods.offline_lan_0922.player_control.weapon.barrel_aligned', return_value=True)
    def test_barrel_is_commanded_to_next_point_before_chassis_position_search(self, unused):
        control, target = fixtures.PlayerControlIntegrationReviewTests().direct_facing_controller()
        control.aiming.direct_samples = lambda target: 2
        upper = tuple(target.position)
        lower = (upper[0], upper[1] - .5, upper[2])
        def probe(item, index, sample, now, *args, **kwargs):
            solution = dict(created=now, point=upper if sample == 0 else lower,
                clear=True, geometry_clear=True, reachable=True, laying=True, barrel_error=.1)
            if kwargs.get('physical'):
                return ('armor' if sample == 0 and now > 1. else 'laying'), solution
            return 'ready', solution
        control.aiming.compare_direct.side_effect = probe
        control.navigation.firing_position = mock.Mock()
        for now in (1., 1.2, 1.4):
            control.update(.1, now)
            self.assertEqual(0., control.owner._sender.forward)
        commanded = [call.args[1] for call in control.weapon.aim.call_args_list]
        self.assertEqual([upper, lower], commanded)
        control.navigation.firing_position.assert_not_called()
        self.assertEqual('turret', control.direct_engagement.phase)

    @mock.patch('gui.mods.offline_lan_0922.player_control.weapon.barrel_aligned', return_value=True)
    def test_outer_controller_waits_twice_reverses_then_recovers(self, unused):
        control, target = fixtures.PlayerControlIntegrationReviewTests().direct_facing_controller()
        control.update(.1, .8)  # Establish an actual usable engagement first.
        control.aiming.compare_direct.side_effect = None
        control.aiming.compare_direct.return_value = ('pending', None)
        control.navigation.firing_position = mock.Mock(return_value=None)
        for now in (1., 4., 8.9):
            control.update(.1, now)
            self.assertEqual(0., control.owner._sender.forward)
            self.assertEqual('turret', control.direct_engagement.phase)
        control.navigation.firing_position.assert_not_called()
        control.update(.1, 9.)
        self.assertEqual('position', control.direct_engagement.phase)
        control.navigation.firing_position.assert_called_once()
        control.update(.1, 14.9)
        self.assertEqual('position', control.direct_engagement.phase)
        control.update(.1, 15.)
        self.assertEqual('retreat', control.direct_engagement.phase)
        self.assertLess(control.owner._sender.forward, 0.)
        self.assertEqual(0., control.owner._sender.turn)
        control.update(.1, 23.1)
        self.assertEqual('ammo_retreat_hold', control.last_order['combat_mode'])
        control.aiming.compare_direct.return_value = ('ready', dict(created=23.3,
            point=target.position, clear=True, geometry_clear=True, reachable=True))
        control.update(.1, 23.3)
        self.assertEqual('turret', control.direct_engagement.phase)
        self.assertEqual(0., control.owner._sender.forward)
        control.trigger.assert_called()
        reasons = [call.kwargs.get('reason') for call in control.record.call_args_list
                   if call.args[0] == 'engagement_stage']
        self.assertEqual(['turret_timeout', 'position_timeout', 'ray_ready'], reasons)

    @mock.patch('gui.mods.offline_lan_0922.player_control.weapon.barrel_aligned', return_value=True)
    def test_rejected_pivot_rechecks_without_hull_translation(self, unused):
        control, target = fixtures.PlayerControlIntegrationReviewTests().direct_facing_controller()
        owner = control.owner
        owner._destructible_pose_sweep.return_value = dict(status='hard')
        control.update(.1, 1.)
        self.assertEqual('blocked', control.last_order['combat_facing']['state'])
        owner._destructible_pose_sweep.return_value = dict(status='clear')
        control.update(.1, 1.6)
        self.assertEqual('turning', control.last_order['combat_facing']['state'])
        self.assertGreater(owner._sender.turn, 0.)

if __name__ == '__main__':
    unittest.main()
