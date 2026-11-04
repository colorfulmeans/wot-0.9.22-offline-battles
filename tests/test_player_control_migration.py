"""Controller integration for ownership, ammo capability and actual receipts.

Deterministic fixtures exercise Python decisions, not Windows playability.
"""
import copy
import itertools
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control import PlayerControl
from gui.mods.offline_lan_0922.player_control.capabilities import ammunition_state, Governor
from gui.mods.offline_lan_0922.player_control.ammunition import Ammunition
import test_player_control as existing


class ControllerMigrationTests(unittest.TestCase):
    def control(self, features=('drive', 'fire')):
        entity = types.SimpleNamespace(id=1, isAlive=lambda: True,
            health=1000, typeDescriptor=types.SimpleNamespace(maxHealth=1000))
        sender = types.SimpleNamespace(forward=1., turn=.3, handbrake=True,
                                       send_current=mock.Mock(return_value=True))
        gun = types.SimpleNamespace(shots=[{}], ammo=[10], clip=1, clip_size=1,
            reload_time=0., shot_index=0, can_fire=lambda unused:True)
        owner = types.SimpleNamespace(_sender=sender, _gun_state=gun,
            _server=types.SimpleNamespace(vehicle_id=1), _server_entity=lambda unused:entity,
            _clock=lambda:1., _local_fire_intent=None, _local_player_burst=None,
            _cancel_local_player_burst=mock.Mock(), _defer_cancel_native_shot_wait=mock.Mock(),
            _start_message=dict(round_id='r'), client=types.SimpleNamespace(player_id=1,team=1),
            _local_speed=0., _local_turn_speed=0., _local_vertical_speed=0.,
            _local_pitch=0., _local_roll=0., _local_suspension_pitch_velocity=0.,
            _local_suspension_roll_velocity=0.,
            _local_air_lateral=(0.,0.), _local_airborne=False,
            _local_support_rise_blocked=False, _overturn_level=0,
            local_pose=lambda:((0.,0.,0.),0.),
            _collision_shape=lambda unused:(1.,3.,0.,2.))
        control = PlayerControl(owner, features, notify=lambda text:None)
        control.active = True
        control.live = lambda:True
        control.record = mock.Mock()
        control.bind_input = lambda:None
        control.poll_commands = lambda now:None
        control.gateway.wall_clock = lambda:1000.
        owner._player_control = control
        return control

    def request(self, control, action, **kwargs):
        return dict(control.identity(), id=action, action=action, args={},
                    expires_at=1005., **kwargs)

    def start_fixture(self, features=('drive', 'fire')):
        from test_player_manual_aim import ObservedRotator
        control = self.control(features)
        control.active = False
        control.notify = mock.Mock()
        control.owner._server_entity(1).typeDescriptor.type = types.SimpleNamespace(tags=())
        source = lambda: (91., 92., 93.)
        rotator = ObservedRotator(source)
        control.owner._avatar = types.SimpleNamespace(gunRotator=rotator,
            autoAim=mock.Mock(), isWaitingForShot=False)
        control.owner._mutable_shot_ray = lambda: ((0., 1., 0.), (0., 0., 1.))
        control.owner._vector = tuple
        patcher = mock.patch('gui.mods.offline_lan_0922.player_control.ammunition.mounted_shells',
                             return_value=[dict(index=0, kind='ARMOR_PIERCING')])
        patcher.start()
        self.addCleanup(patcher.stop)
        return control, rotator, source, mock.Mock()

    def test_start_all_feature_masks_claim_only_enabled_native_channels(self):
        for enabled in itertools.product((False, True), repeat=3):
            names = {name for name, on in zip(('drive', 'fire', 'consumables'), enabled) if on}
            with self.subTest(features=names):
                c, rotator, source, navigation = self.start_fixture(names)
                c.owner._local_player_burst = {'manual': True}
                self.assertEqual(bool(names), c.toggle(navigation))
                self.assertEqual(bool(names), c.active)
                self.assertEqual('drive' in names, c.owns_drive())
                if 'fire' in names:
                    c.owner._avatar.autoAim.assert_called_once_with(None)
                    self.assertIs(c.weapon.bound_source, rotator.shotPointSourceFunctor)
                    self.assertTrue(rotator.clientMode)
                else:
                    c.owner._avatar.autoAim.assert_not_called()
                    self.assertIs(source, rotator.shotPointSourceFunctor)
                    self.assertFalse(rotator.clientMode)
                c.stop()
                self.assertIs(source, rotator.shotPointSourceFunctor)
                self.assertFalse(rotator.clientMode)
                self.assertEqual((0., 0., False) if 'drive' in names else (1., .3, True),
                    (c.owner._sender.forward, c.owner._sender.turn, c.owner._sender.handbrake))
                c.owner._cancel_local_player_burst.assert_not_called()

    def test_native_bind_stop_cannot_revive_start_or_accept_a_nested_start(self):
        for boundary in ('auto_aim', 'source_before', 'source_after', 'mode_before'):
            with self.subTest(boundary=boundary):
                c, rotator, source, navigation = self.start_fixture()
                observed = []
                def stop_once(unused):
                    if boundary == 'auto_aim':
                        c.owner._avatar.autoAim.side_effect = None
                    else:
                        setattr(rotator, boundary, None)
                    observed.append((c.active, c.weapon is not None, c.aiming is not None))
                    c.stop('native_setter_stop')
                    observed.append(c.toggle(navigation))
                if boundary == 'auto_aim':
                    c.owner._avatar.autoAim.side_effect = stop_once
                else:
                    setattr(rotator, boundary, stop_once)
                self.assertFalse(c.toggle(navigation))
                self.assertEqual([(True, True, True), False], observed)
                self.assertFalse(c.active)
                self.assertIsNone(c.weapon)
                self.assertIsNone(c.navigation)
                self.assertIsNone(c.aiming)
                self.assertFalse(c.release_pending)
                self.assertIs(source, rotator.shotPointSourceFunctor)
                self.assertFalse(rotator.clientMode)
                navigation.close.assert_called_once_with()
                self.assertNotIn('enabled', [call.args[0] for call in c.record.call_args_list])

    def test_bind_entity_gun_or_round_replacement_cannot_complete_start(self):
        for changed in ('entity', 'gun', 'rotator', 'round'):
            for boundary in ('source_before', 'source_after', 'mode_before'):
                with self.subTest(changed=changed, boundary=boundary):
                    c, rotator, source, navigation = self.start_fixture()
                    def replace_once(unused):
                        setattr(rotator, boundary, None)
                        if changed == 'entity':
                            replacement = copy.copy(c.owner._server_entity(1))
                            c.owner._server_entity = lambda unused: replacement
                        elif changed == 'gun':
                            c.owner._gun_state = copy.copy(c.owner._gun_state)
                        elif changed == 'rotator':
                            c.owner._avatar.gunRotator = copy.copy(rotator)
                        else:
                            c.owner._start_message = dict(round_id='next-round')
                    setattr(rotator, boundary, replace_once)
                    self.assertFalse(c.toggle(navigation))
                    self.assertFalse(c.active)
                    self.assertIsNone(c.weapon)
                    self.assertIsNone(c.navigation)
                    self.assertIs(source, rotator.shotPointSourceFunctor)
                    self.assertFalse(rotator.clientMode)
                    self.assertFalse(c.release_pending)

    def test_native_bind_failure_cleans_partial_source_and_mode(self):
        for boundary in ('auto_aim', 'source_before', 'source_after', 'mode_before'):
            with self.subTest(boundary=boundary):
                c, rotator, source, navigation = self.start_fixture()
                def fail_once(unused):
                    if boundary == 'auto_aim':
                        c.owner._avatar.autoAim.side_effect = None
                    else:
                        setattr(rotator, boundary, None)
                    raise RuntimeError('native binding failed')
                if boundary == 'auto_aim':
                    c.owner._avatar.autoAim.side_effect = fail_once
                else:
                    setattr(rotator, boundary, fail_once)
                self.assertFalse(c.toggle(navigation))
                self.assertFalse(c.active)
                self.assertIsNone(c.weapon)
                self.assertIs(source, rotator.shotPointSourceFunctor)
                self.assertFalse(rotator.clientMode)
                self.assertFalse(c.release_pending)
                navigation.close.assert_called_once_with()

    def test_cancelled_navigation_constructor_closes_only_its_late_resource(self):
        c, rotator, source, navigation = self.start_fixture()
        def create(*unused):
            c.stop('native_constructor_stop')
            self.assertFalse(c.toggle(navigation))
            return navigation
        with mock.patch('gui.mods.offline_lan_0922.player_control.navigation.PlayerNavigation',
                        side_effect=create):
            self.assertFalse(c.toggle())
        self.assertFalse(c.active)
        self.assertIsNone(c.navigation)
        navigation.close.assert_called_once_with()
        self.assertIs(source, rotator.shotPointSourceFunctor)
        self.assertFalse(rotator.clientMode)
        self.assertFalse(c.release_pending)

    def test_start_cleanup_failure_remains_retryable_without_reviving_owner(self):
        c, rotator, source, navigation = self.start_fixture()
        def stop_once(unused):
            rotator.source_after = None
            c.stop('native_setter_stop')
            def fail_restore_once(value):
                if value is source:
                    rotator.source_after = None
                    raise RuntimeError('restore failed after source write')
            rotator.source_after = fail_restore_once
        rotator.source_after = stop_once
        self.assertFalse(c.toggle(navigation))
        self.assertFalse(c.active)
        self.assertIsNone(c.weapon)
        self.assertIs(source, rotator.shotPointSourceFunctor)
        self.assertTrue(rotator.clientMode)
        self.assertEqual(['aim_release'], [stage for stage, unused in c.release_pending])
        c.retry_releases(2.)
        self.assertFalse(c.release_pending)
        self.assertFalse(rotator.clientMode)
        self.assertFalse(c.active)

    def test_ordinary_stop_retries_mode_after_source_was_already_restored(self):
        for third_party in (False, True):
            with self.subTest(third_party=third_party):
                c, rotator, source, navigation = self.start_fixture()
                self.assertTrue(c.toggle(navigation))
                def fail_mode_once(value):
                    if value is False:
                        rotator.mode_before = None
                        raise RuntimeError('native mode restore failed')
                rotator.mode_before = fail_mode_once
                self.assertFalse(c.stop())
                self.assertIs(source, rotator.shotPointSourceFunctor)
                self.assertTrue(rotator.clientMode)
                self.assertEqual(['aim_release'], [stage for stage, unused in c.release_pending])
                replacement = lambda: (1., 2., 3.)
                if third_party:
                    rotator.shotPointSourceFunctor = replacement
                c.retry_releases(2.)
                self.assertFalse(c.release_pending)
                self.assertIs(replacement if third_party else source, rotator.shotPointSourceFunctor)
                self.assertEqual(third_party, rotator.clientMode)

    def test_start_cleanup_reentry_does_not_overwrite_new_control(self):
        c, rotator, source, navigation = self.start_fixture()
        attempts = []
        def stop_once(unused):
            rotator.mode_before = None
            c.stop('native_setter_stop')
            def during_restore(value):
                if value is source:
                    rotator.source_after = None
                    attempts.append(c.toggle(navigation))
            rotator.source_after = during_restore
        rotator.mode_before = stop_once
        self.assertFalse(c.toggle(navigation))
        self.assertEqual([False], attempts)
        self.assertFalse(c.release_pending)
        replacement = mock.Mock()
        self.assertTrue(c.toggle(replacement))
        current_weapon = c.weapon
        c.retry_releases(10.)
        self.assertTrue(c.active)
        self.assertIs(current_weapon, c.weapon)
        self.assertIs(replacement, c.navigation)
        self.assertIs(current_weapon.bound_source, rotator.shotPointSourceFunctor)
        self.assertTrue(rotator.clientMode)
        replacement.close.assert_not_called()

    def test_start_barrier_precedes_native_input_and_navigation_release(self):
        for boundary in ('input', 'navigation'):
            with self.subTest(boundary=boundary):
                c, rotator, source, navigation = self.start_fixture()
                attempts = []
                def stop_once(unused):
                    rotator.source_before = None
                    c.stop('native_setter_stop')
                def attempt_start():
                    attempts.append(c.toggle(mock.Mock()))
                    return True
                rotator.source_before = stop_once
                if boundary == 'input':
                    c.owner._sender.send_current.side_effect = attempt_start
                else:
                    navigation.close.side_effect = attempt_start
                self.assertFalse(c.toggle(navigation))
                self.assertEqual([False], attempts)
                self.assertFalse(c.active)
                self.assertIsNone(c.weapon)
                self.assertIs(source, rotator.shotPointSourceFunctor)
                self.assertFalse(rotator.clientMode)
                self.assertFalse(c.release_pending)

    def test_all_feature_masks_release_only_owned_channels_and_never_manual_burst(self):
        for enabled in itertools.product((False, True), repeat=3):
            names = {name for name,on in zip(('drive','fire','consumables'),enabled) if on}
            with self.subTest(features=names):
                c = self.control(names)
                c.owner._local_player_burst = {'manual': True}
                c.stop()
                sender = c.owner._sender
                self.assertEqual((0.,0.,False) if 'drive' in names else (1.,.3,True),
                                 (sender.forward,sender.turn,sender.handbrake))
                c.owner._cancel_local_player_burst.assert_not_called()
                c.owner._defer_cancel_native_shot_wait.assert_not_called()

    def test_fire_only_cancels_own_future_burst_without_touching_manual_drive(self):
        c = self.control(('fire',))
        c.owned_burst = c.owner._local_player_burst = dict(committed=1)
        c.stop()
        c.owner._cancel_local_player_burst.assert_called_once_with(apply_settings=True)
        self.assertEqual((1., .3, True), (c.owner._sender.forward,
            c.owner._sender.turn, c.owner._sender.handbrake))
        c.owner._sender.send_current.assert_not_called()

    def test_override_owns_drive_even_when_automatic_drive_feature_is_off(self):
        c = self.control(('fire',))
        c.active = False
        c.override = (3., 1., 0.)
        c.stop()
        self.assertEqual((0.,0.,False), (c.owner._sender.forward,
            c.owner._sender.turn,c.owner._sender.handbrake))
        c.owner._cancel_local_player_burst.assert_not_called()

    def test_grave_takeover_releases_halt_or_timed_drive_before_fire_only_start(self):
        for previous in ('halt', 'drive'):
            c = self.control(('fire',))
            c.active = False
            c.halted = previous == 'halt'
            c.override = (3.,1.,0.) if previous == 'drive' else None
            entity = c.owner._server_entity(1)
            entity.typeDescriptor.type = types.SimpleNamespace(tags=())
            with mock.patch('gui.mods.offline_lan_0922.player_control.ammunition.mounted_shells',
                    return_value=[dict(index=0,kind='ARMOR_PIERCING')]), \
                 mock.patch('gui.mods.offline_lan_0922.player_control.weapon.Weapon'), \
                 mock.patch('gui.mods.offline_lan_0922.player_control.aiming.Aiming'):
                self.assertTrue(c.toggle())
            self.assertIsNone(c.override)
            self.assertFalse(c.halted)
            self.assertEqual((0.,0.,False),(c.owner._sender.forward,
                c.owner._sender.turn,c.owner._sender.handbrake))
            self.assertFalse(c.owns_drive())

    def test_invalid_local_drive_does_not_release_current_automation(self):
        for args in ({'seconds':0}, {'forward':2}, {'turn':float('nan')}):
            c = self.control()
            with self.assertRaises(ValueError):
                c.command(dict(action='drive', **args), 1.)
            self.assertTrue(c.active)
            self.assertEqual(1., c.owner._sender.forward)
            c.owner._sender.send_current.assert_not_called()

    def test_real_empty_inventory_releases_aim_and_combat_hold(self):
        c, target = existing.PlayerRegressionTests().aim_controller()
        c.owner._gun_state.ammo = [0]
        c.owner._gun_state.clip = 0
        c.owner._gun_state.can_fire = lambda unused:False
        c.firing_lane = lambda unused:True
        c.target_engine = target.id
        c.update(.1, 1.)
        self.assertEqual('empty', c.ammo_state['state'])
        self.assertIsNone(c.target_engine)
        c.weapon.trigger.assert_not_called()
        self.assertFalse(c.navigation.decide.call_args.kwargs['hold'])
        self.assertTrue(c.navigation.set_context.call_args.args[0]['empty_ammo'])
        self.assertEqual(1., c.owner._sender.forward)

    def test_empty_clip_and_empty_current_stock_are_distinct_from_total_empty(self):
        c = self.control()
        gun = c.owner._gun_state
        gun.clip, gun.reload_time = 0, 40.
        gun.can_fire = lambda unused:False
        self.assertEqual('reloading', ammunition_state(gun)['state'])
        self.assertFalse(ammunition_state(gun)['empty'])
        gun.shots, gun.ammo = [{},{}], [0,10]
        self.assertEqual('shell_empty', ammunition_state(gun)['state'])
        self.assertFalse(ammunition_state(gun)['empty'])

    def test_unknown_inventory_neither_invents_no_ammo_nor_fires(self):
        c, target = existing.PlayerRegressionTests().aim_controller()
        c.owner._gun_state.ammo = None
        c.firing_lane = lambda unused:True
        c.update(.1, 1.)
        self.assertEqual('unknown', c.ammo_state['state'])
        self.assertFalse(c.navigation.set_context.call_args.args[0]['empty_ammo'])
        c.weapon.trigger.assert_not_called()

    def test_manual_shot_during_takeover_does_not_pollute_automatic_ammo_policy(self):
        c = self.control(('fire',))
        c.ammo_policy = mock.Mock()
        c.shot_committed(dict(projectile_id='manual',shell_index=0), {})
        c.ammo_policy.launch.assert_not_called()
        self.assertEqual(1, c.shot_commits)
        self.assertEqual(0, c.automatic_commits)

    def test_manual_pending_round_exhausting_protected_stock_allows_real_switch(self):
        c = self.control(('fire',))
        c.ammo_policy = Ammunition([dict(index=0,kind='ARMOR_PIERCING'),
                                   dict(index=1,kind='HIGH_EXPLOSIVE')],0,0)
        gun=c.owner._gun_state
        gun.shots=[dict(shell=dict(compactDescr=11)),dict(shell=dict(compactDescr=22))]
        gun.ammo=[0,5]
        gun.clip=0
        gun.pending_index=None
        c.owner._runtime=types.SimpleNamespace(constants=types.SimpleNamespace(
            VEHICLE_SETTING=types.SimpleNamespace(CURRENT_SHELLS=4,NEXT_SHELLS=5)))
        c.owner.change_vehicle_setting=mock.Mock()
        c.select_ammo(1.)
        self.assertFalse(c.ammo_policy.protected)
        c.owner.change_vehicle_setting.assert_called_once_with(4,22)

    def test_trigger_keeps_own_group_and_position_on_actual_commit(self):
        c = self.control(('fire',))
        c.ammo_policy = mock.Mock()
        c.target_engine = 7
        burst = dict(group_seq=12, committed=1)
        c.owner._avatar = types.SimpleNamespace(isWaitingForShot=False)
        def shoot():
            c.owner._local_player_burst = burst
            c.shot_committed(dict(projectile_id='p',shell_index=0),
                dict(player_burst=burst,burst_group_seq=12,burst_count=3,x=2.,y=4.,z=8.))
        c.owner._avatar.shoot = shoot
        from gui.mods.offline_lan_0922.player_control.weapon import Weapon
        self.assertTrue(c.trigger(Weapon(c.owner), 1.))
        self.assertIs(burst, c.owned_burst)
        c.ammo_policy.launch.assert_called_once_with('p',0,7,1.,
            position=(2.,4.,8.),group=12,count=3,clip_remaining=1)
        c.stop()
        c.ammo_policy = None
        c.retired_policies[0].close_group.assert_called_once_with(12,1)

    def test_retired_policy_keeps_admitted_projectile_receipts_after_stop(self):
        c = self.control(('fire',))
        p = Ammunition([dict(index=0,kind='ARMOR_PIERCING')],0,0)
        p.launch('p',0,7,0.)
        c.ammo_policy = p
        c.stop()
        c.shot_hit(dict(projectile_id='p',damage=100,shot_result=2))
        c.shot_terminal(dict(projectile_id='p',hit_vehicle=True))
        self.assertEqual(100., p.rows['p']['damage'])
        p.settle([9], 1.)
        self.assertTrue(p.idle)

    def test_command_halt_completes_only_after_observed_vehicle_stop(self):
        c = self.control()
        rows = []
        c.gateway.emit = lambda row:rows.append(dict(row)) or True
        with mock.patch.dict(os.environ, {'WOT_OFFLINE_TEST_CONTROL_SESSION':'s'}):
            c.owner._local_speed = 4.
            receipt = c.gateway.submit(self.request(c,'halt'),0.)
            self.assertEqual('accepted', receipt['status'])
            c.update(.1,.1)
            self.assertEqual('accepted', c.gateway.requests['halt']['receipt']['status'])
            c.owner._local_speed = 0.
            c.update(.1,1.)
            self.assertEqual('accepted', c.gateway.requests['halt']['receipt']['status'])
            c.update(.1,1.6)
            self.assertEqual('completed', c.gateway.requests['halt']['receipt']['status'])
            self.assertTrue(c.halted)
            self.assertTrue(c.owner._sender.handbrake)
            c.stop()
            self.assertFalse(c.owns_drive())

    def test_movement_timeout_stops_owned_input_and_reports_failed_not_cancelled(self):
        c = self.control()
        c.gateway.emit = lambda row:True
        with mock.patch.dict(os.environ, {'WOT_OFFLINE_TEST_CONTROL_SESSION':'s'}):
            request = self.request(c,'drive',timeout_seconds=.5)
            request['args'] = dict(seconds=2.,forward=1.)
            c.gateway.submit(request,0.)
            self.assertIsNotNone(c.override)
            c.gateway.tick(.5)
            self.assertIsNone(c.override)
            self.assertEqual(0.,c.owner._sender.forward)
            self.assertEqual('failed',c.gateway.requests['drive']['receipt']['status'])

    def test_enveloped_stop_after_oversize_is_executed_and_acknowledged(self):
        c = self.control()
        with tempfile.TemporaryDirectory() as directory:
            request_path, result_path = Path(directory)/'request.jsonl', Path(directory)/'result.jsonl'
            with mock.patch.dict(os.environ, dict(WOT_OFFLINE_TEST_CONTROL_SESSION='s',
                WOT_OFFLINE_TEST_CONTROL_FILE=str(request_path),
                WOT_OFFLINE_TEST_CONTROL_RESULT_FILE=str(result_path))):
                request_path.write_bytes(b'x'*5000+b'\n'+
                    json.dumps(self.request(c,'stop')).encode('utf8')+b'\n')
                PlayerControl.poll_commands(c, 0.)
                self.assertFalse(c.active)
                rows=[json.loads(line) for line in result_path.read_text().splitlines()]
                self.assertEqual(['accepted','completed'],
                    [row['status'] for row in rows if row.get('id')=='stop'])

    def test_player_corridor_uses_actual_bank_pose_for_forward_and_reverse(self):
        from test_port_0922_posed_direction_probe import PosedDirectionProbeTests
        for yaw in (0.,math.pi):
            battle, rays, pose, height = PosedDirectionProbeTests().scene()
            battle.local_pose = lambda:((0.,5.,0.),pose[0])
            battle._local_speed = 0.
            battle._local_pitch, battle._local_roll = pose[1:]
            battle._collide_navigation = lambda a,b,trace:battle._runtime.bigworld.wg_collideSegment(
                battle._avatar.spaceID,a,b,0)
            battle._direction_probe = mock.Mock(wraps=battle._direction_probe)
            control = PlayerControl(battle,('drive',))
            self.assertTrue(control.direction_clear((0.,5.,0.),yaw,object(),(2.2,3.,0.,2.),4.))
            self.assertEqual(pose,battle._direction_probe.call_args.kwargs['body_pose'])

    def test_mission_travel_can_push_but_capture_and_parking_holds_cannot(self):
        from gui.mods.offline_lan_0922.player_control.wrecks import WreckPush
        from gui.mods.offline_lan_0922.player_control.traffic import Traffic, body
        state=dict(position=(0.,0.,0.),yaw=0.,now=0.,half_length=2.,half_width=1.)
        peer=dict(id=4,position=(0.,0.,5.),alive=False,team=1,yaw=0.,collision_shape=(1.,2.,0.,2.))
        for mode in ('return_base','base_capture','base_defence','artillery_deploy'):
            for travelling in (False,True):
                order=dict(combat_mode=mode,travel_intent=travelling,
                    local_target=(0.,0.,30.),recovery_mode='travel' if travelling else 'hold')
                traffic=Traffic(body(1,state['position'],0.,(1.,2.,0.,2.)),[peer])
                self.assertEqual(travelling,WreckPush().apply(order,state,traffic,lambda *a:True))

    def test_supported_mission_holds_allow_siege_but_failed_holds_do_not(self):
        for status in ('running','completed','failed','cancelled'):
            c,entity=existing.PlayerRegressionTests().aim_controller()
            entity.typeDescriptor=types.SimpleNamespace(hasSiegeMode=True)
            entity.siegeState=0
            c.owner._local_siege_pending=c.owner._local_siege_braking=None
            c.owner._runtime=types.SimpleNamespace(constants=types.SimpleNamespace(
                VEHICLE_SIEGE_STATE=types.SimpleNamespace(DISABLED=0,ENABLED=1,SWITCHING_ON=2,SWITCHING_OFF=3),
                VEHICLE_SETTING=types.SimpleNamespace(SIEGE_MODE_ENABLED=10)))
            c.owner.change_vehicle_setting=mock.Mock(return_value=True)
            order=dict(combat_mode='mission_hold',holding=True,mission=dict(status=status))
            c.update_siege(entity,order,True,0.)
            c.update_siege(entity,order,True,1.)
            self.assertEqual(status in ('running','completed'),c.owner.change_vehicle_setting.called)

    def test_final_barrel_proof_follows_mode_changes_and_skips_forbidden_fire(self):
        for mode in ('permitted','failed_mission','deploying'):
            c,target=existing.PlayerRegressionTests().aim_controller()
            c.firing_lane=lambda unused:True
            order=dict(throttle=0.,turn=0.,brake=True)
            if mode=='failed_mission':
                order['mission']=dict(status='failed')
            elif mode=='deploying':
                c.owner._server_entity(1).typeDescriptor.type=types.SimpleNamespace(tags=('SPG',))
                order['artillery']=dict(phase='deploying')
            c.navigation.decide.return_value=order
            events=[]
            actual=[(0.,0.,1.)]
            c.owner._mutable_shot_ray=lambda:((0.,1.,0.),actual[0])
            def changed(*args):
                events.append('mode')
                actual[0]=(1.,0.,0.)
            c.update_siege=changed
            def confirm(target,solution,direction,*args,**kwargs):
                self.assertEqual(['mode'],events)
                self.assertEqual(actual[0],direction)
                events.append('proof')
                return True
            c.aiming.confirm=mock.Mock(side_effect=confirm)
            c.trigger=mock.Mock(side_effect=lambda *a:events.append('fire') or True)
            with mock.patch('gui.mods.offline_lan_0922.player_control.weapon.barrel_aligned',return_value=True):
                c.update(.1,1.)
            self.assertEqual(['mode','proof','fire'] if mode=='permitted' else ['mode'],events)
            self.assertEqual(mode=='permitted',c.aiming.confirm.called)


class DynamicTrajectoryTests(unittest.TestCase):
    def scene(self, position=(10.,0.,2.)):
        from test_port_0922_battle_runtime import _RigidMatrix, _Vector, _Descriptor
        math_module=types.SimpleNamespace(Matrix=_RigidMatrix,Vector3=_Vector)
        body, turret, gun = _RigidMatrix(), _RigidMatrix(), _RigidMatrix()
        body.setTranslate(position)
        other=types.SimpleNamespace(id=2,typeDescriptor=_Descriptor(),matrix=body,
            appearance=types.SimpleNamespace(turretMatrix=turret,gunMatrix=gun),
            isStarted=True,isTurretDetached=False,alive=True)
        other.isAlive=lambda:other.alive
        record=dict(ready=True,engine_id=2,native_remote=True,state=dict(team=1))
        owner=types.SimpleNamespace(_records={'friend':record},
            _server_entity=lambda identity:other,
            client=types.SimpleNamespace(team=1),_runtime=types.SimpleNamespace(math=math_module),
            _projectile_vehicle_matrices=mock.Mock(side_effect=lambda *a:(other.matrix,other.matrix)),
            _tactical_ray_clear=mock.Mock(side_effect=AssertionError('dynamic gate queried world BSP')))
        control=PlayerControl(owner,('fire',))
        return control,other,types.SimpleNamespace(id=99),record

    def test_friend_entering_earlier_chord_is_rechecked_from_current_pose(self):
        c,friend,target,record=self.scene()
        path=((0.,1.,0.),(0.,1.,5.),(0.,1.,40.))
        self.assertTrue(c.dynamic_path_clear(target,path))
        friend.matrix.setTranslate((0.,0.,2.))
        self.assertFalse(c.dynamic_path_clear(target,path))
        self.assertEqual(2,c.owner._projectile_vehicle_matrices.call_count)
        c.owner._tactical_ray_clear.assert_not_called()

    def test_current_full_box_includes_rotated_gun_until_detached(self):
        c,friend,target,record=self.scene((0.,0.,0.))
        path=((1.85,1.5,-10.),(1.85,1.5,10.))
        self.assertTrue(c.dynamic_path_clear(target,path))
        friend.appearance.turretMatrix.setRotateY(math.pi/2.)
        self.assertFalse(c.dynamic_path_clear(target,path))
        friend.isTurretDetached=True
        self.assertTrue(c.dynamic_path_clear(target,path))

    def test_overhead_clearance_enemy_and_wreck_have_distinct_admission(self):
        c,friend,target,record=self.scene((0.,0.,5.))
        self.assertTrue(c.dynamic_path_clear(target,((0.,10.,0.),(0.,10.,20.))))
        low=((0.,1.,0.),(0.,1.,20.))
        self.assertFalse(c.dynamic_path_clear(target,low))
        record['state']['team']=2
        self.assertTrue(c.dynamic_path_clear(target,low))
        friend.alive=False
        self.assertFalse(c.dynamic_path_clear(target,low))

    def test_missing_attached_geometry_and_current_debris_cannot_certify_clear(self):
        c,friend,target,record=self.scene()
        path=((0.,1.,0.),(0.,1.,5.),(0.,1.,40.))
        friend.typeDescriptor.gun.hitTester=None
        self.assertFalse(c.dynamic_path_clear(target,path))
        friend.isTurretDetached=True
        self.assertTrue(c.dynamic_path_clear(target,path))
        c.owner._turret_server_time_ms=mock.Mock(return_value=1234)
        debris=c.owner._detached_turret_obstacles=types.SimpleNamespace(
            active=lambda:True,target_entry_distance=mock.Mock(return_value=0.))
        self.assertFalse(c.dynamic_path_clear(target,path))
        debris.target_entry_distance.assert_called_once_with(path[0],path[1],1234)
        c.owner._tactical_ray_clear.assert_not_called()


class GovernorTests(unittest.TestCase):
    def test_uphill_requires_two_seconds_and_stops_on_level_reverse_or_damage(self):
        governor=Governor()
        self.assertFalse(governor.wanted(0.,3.,-.1,True,False))
        self.assertFalse(governor.wanted(1.9,3.,-.1,True,False))
        self.assertTrue(governor.wanted(2.,3.,-.1,True,False))
        self.assertFalse(governor.wanted(2.1,3.,0.,True,False))
        self.assertFalse(governor.wanted(2.2,-3.,-.1,True,False))
        self.assertFalse(governor.wanted(5.,3.,-.1,True,True))

    def test_airborne_or_unobserved_support_never_enables_governor(self):
        governor=Governor()
        for now in (0.,3.,5.):
            self.assertFalse(governor.wanted(now,3.,None,True,False))
            self.assertFalse(governor.wanted(now,3.,-.2,False,False))

    def test_wreck_attempt_must_keep_its_own_progress(self):
        governor=Governor()
        push=dict(peer=4,phase='pushing',progress=0.)
        self.assertTrue(governor.wanted(0.,0.,0.,True,False,push))
        self.assertFalse(governor.wanted(2.,0.,0.,True,False,push))
        push['progress']=.2
        self.assertTrue(governor.wanted(2.1,.2,0.,True,False,push))


if __name__=='__main__':
    unittest.main()
