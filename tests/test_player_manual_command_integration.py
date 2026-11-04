"""Independent explicit command channels through the actual foreground owner.

Point-source/native angle observations are fixtures; no test here claims a
Windows battle run. LAN sequence tests exercise the actual encoder.
"""
import copy
import types
import unittest
from unittest import mock

from test_player_manual_aim import ManualAimHarness, SOURCE_ATTRIBUTE
from gui.mods.offline_lan_0922 import lan_client


class ExplicitChannelIntegrationTests(ManualAimHarness, unittest.TestCase):
    def setUp(self):
        super(ExplicitChannelIntegrationTests, self).setUp()
        self.control.gateway.execute = self.control.execute_command
        self.control.gateway.preflight = self.control.command_preflight
        self.control.gateway.cancel = self.control.cancel_command

    def tick(self, now):
        self.fixture.now[0] = now
        self.control.update(.1, now)

    def test_held_aim_survives_drive_completion_and_halt_until_explicit_release(self):
        self.complete()
        source = getattr(self.rotator, SOURCE_ATTRIBUTE)
        self.assertEqual('accepted', self.submit('drive',
            dict(forward=1., seconds=.5), identity='drive')['status'])
        self.tick(.7)
        self.assertEqual('completed', self.receipt('drive')['status'])
        self.assertTrue(self.aim.held)
        self.assertIs(source, getattr(self.rotator, SOURCE_ATTRIBUTE))
        self.assertEqual('accepted', self.submit('halt', {}, identity='halt')['status'])
        self.tick(.8)
        self.tick(1.5)
        self.assertEqual('completed', self.receipt('halt')['status'])
        self.assertTrue(self.control.halted)
        self.assertTrue(self.aim.held)
        self.assertEqual('completed', self.submit('release_aim',
            dict(command_id='aim-one'), identity='release')['status'])
        self.assertFalse(self.aim.held)
        self.assertTrue(self.control.halted)
        self.assertIs(self.old_source, getattr(self.rotator, SOURCE_ATTRIBUTE))

    def test_drive_timeout_releases_only_movement(self):
        self.complete()
        self.submit('drive', dict(forward=1., seconds=5.), identity='drive', timeout=.25)
        self.tick(.5)
        self.assertEqual(('failed', 'command_timeout'),
                         (self.receipt('drive')['status'], self.receipt('drive')['reason']))
        self.assertFalse(self.control.owns_drive())
        self.assertEqual((0., 0., False), (self.owner._sender.forward,
            self.owner._sender.turn, self.owner._sender.handbrake))
        self.assertTrue(self.aim.held)
        self.assertEqual('completed', self.receipt('aim-one')['status'])

    def test_auto_fire_takeover_cannot_silently_replace_held_aim(self):
        self.complete()
        source = getattr(self.rotator, SOURCE_ATTRIBUTE)
        self.control.features.update(('drive', 'fire'))
        row = self.submit('start', {}, identity='start')
        self.assertEqual(('rejected', 'aim_busy'), (row['status'], row['reason']))
        self.assertFalse(self.control.toggle())
        self.assertIs(source, getattr(self.rotator, SOURCE_ATTRIBUTE))
        self.assertFalse(self.control.active)

    def test_held_aim_and_siege_descriptor_switch_are_explicitly_mutually_exclusive(self):
        self.complete()
        self.entities[1].typeDescriptor.hasSiegeMode = True
        row = self.submit('set_siege', dict(enabled=True), identity='mode')
        self.assertEqual(('rejected', 'aim_busy'), (row['status'], row['reason']))
        self.assertTrue(self.aim.held)
        self.assertIsNone(self.control.native_actions.siege_pending)

    def test_pending_mode_blocks_both_drive_and_gun_consumers_before_any_mutation(self):
        self.control.native_actions.siege_pending = object()
        self.control.features.update(('drive', 'fire'))
        actions = [('start', {}), ('attack', {}),
                   ('drive', dict(forward=1., seconds=1.)), ('fire', {}),
                   ('select_shell', dict(compact_descr=102)), ('reload', {}),
                   ('aim_point', dict(position=(20., 1., 100.))),
                   ('aim_target', dict(target_id=42))]
        for index, (action, args) in enumerate(actions):
            row = self.submit(action, args, identity='blocked-%s' % index)
            self.assertEqual(('rejected', 'siege_operation_busy'),
                             (row['status'], row['reason']), action)
        self.assertFalse(self.control.toggle())
        self.assertFalse(self.control.active)
        self.assertIsNone(self.control.override)
        self.assertEqual([], self.rotator.writes)
        self.owner._sender.send_current.assert_not_called()

    def test_pending_equipment_blocks_automatic_consumable_takeover(self):
        self.control.native_actions.equipment_pending = object()
        self.control.features.add('consumables')
        row = self.submit('start', {}, identity='start')
        self.assertEqual(('rejected', 'equipment_operation_busy'), (row['status'], row['reason']))
        self.assertFalse(self.control.toggle())
        self.assertFalse(self.control.active)

    def test_mode_command_cannot_replace_active_auto_fire_without_stop(self):
        self.control.features.add('fire')
        self.control.active = True
        row = self.submit('set_siege', dict(enabled=True), identity='mode')
        self.assertEqual(('rejected', 'automatic_fire_active'), (row['status'], row['reason']))
        self.assertTrue(self.control.active)

    def test_explicit_fire_uses_held_target_and_not_automatic_navigation_target(self):
        self.complete('aim_target')
        self.control.target_engine = 999
        contexts = []
        def attempt():
            contexts.append(copy.copy(self.control.trigger_context))
            return False
        with mock.patch('gui.mods.offline_lan_0922.player_control.weapon.Weapon.trigger',
                        side_effect=attempt):
            row = self.submit('fire', {}, identity='shot')
        self.assertEqual('failed', row['status'])
        self.assertEqual(42, contexts[0]['target'])
        self.assertEqual('shot', contexts[0]['command'])
        self.assertTrue(self.aim.held)
        self.assertEqual([], self.control.shot_receipts.snapshot())

    def test_new_fire_does_not_trust_historical_aim_completion(self):
        self.complete('aim_target')
        self.target.position = (-20., 0., 100.)
        with mock.patch('gui.mods.offline_lan_0922.player_control.weapon.Weapon.trigger') as trigger:
            row = self.submit('fire', {}, identity='shot')
        self.assertEqual(('rejected', 'aim_not_aligned'), (row['status'], row['reason']))
        trigger.assert_not_called()
        self.assertEqual('completed', self.receipt('aim-one')['status'])
        self.assertTrue(self.aim.held)

    def test_native_actions_route_once_through_the_common_idempotency_gateway(self):
        action = self.control.native_actions
        with mock.patch.object(action, 'preflight', return_value=None), \
                mock.patch.object(action, 'execute', return_value=None) as execute:
            first = self.submit('use_equipment', dict(equipment_id=12, active=True), identity='kit')
            duplicate = self.submit('use_equipment', dict(equipment_id=12, active=True), identity='kit')
        self.assertEqual(first, duplicate)
        self.assertEqual('accepted', first['status'])
        self.assertEqual(1, execute.call_count)

    def test_failed_aim_release_retries_after_nonlive_updates_without_starvation(self):
        self.complete()
        attempts = []
        def release(value):
            if value is self.old_source:
                attempts.append(self.fixture.now[0])
                if len(attempts) == 1:
                    raise RuntimeError('native source still busy')
        self.rotator.source_before = release
        row = self.submit('stop', {}, identity='stop')
        self.assertEqual(('failed', 'release_pending'), (row['status'], row['reason']))
        self.assertEqual([.1], attempts)
        self.fixture.alive[0] = False
        for now in (.2, .4, .6, .8, 1.):
            self.tick(now)
            self.assertEqual([.1], attempts)
        self.tick(1.2)
        self.assertEqual([.1, 1.2], attempts)
        self.assertFalse(self.control.release_pending)
        self.assertFalse(self.aim.held)
        self.assertIs(self.old_source, getattr(self.rotator, SOURCE_ATTRIBUTE))

    def test_movement_does_not_cancel_an_existing_explicit_fire_receipt(self):
        request = self.fixture.request(self.control, 'fire', identity='shot')
        self.control.gateway.requests['shot'] = dict(command=request,
            receipt=dict(status='accepted', id='shot'), deadline=10.)
        burst = dict(player_control=dict(command='shot', policy=None))
        self.control.owned_burst = burst
        self.control.fire_command = 'shot'
        with mock.patch.object(self.control, 'release_burst') as release:
            self.submit('drive', dict(forward=1., seconds=.5), identity='drive')
            self.tick(.6)
        release.assert_not_called()
        self.assertIs(burst, self.control.owned_burst)
        self.assertEqual('shot', self.control.fire_command)
        self.assertEqual('accepted', self.receipt('shot')['status'])

    def test_native_liveness_query_stop_cannot_be_rebased_into_a_new_drive(self):
        original, stopped = self.control.live, []
        def live():
            if not stopped:
                stopped.append(True)
                self.control.stop('native_query_stop')
            return original()
        self.control.live = live
        row = self.submit('drive', dict(forward=1., seconds=1.), identity='drive')
        self.assertEqual(('rejected', 'control_changed'), (row['status'], row['reason']))
        self.assertIsNone(self.control.override)
        self.owner._sender.send_current.assert_not_called()

    def test_accepted_publication_stop_cannot_execute_a_previously_valid_drive(self):
        original = self.control.gateway.emit
        def emit(row):
            if row.get('id') == 'drive' and row.get('status') == 'accepted':
                self.control.stop('receipt_stop')
            return original(row)
        self.control.gateway.emit = emit
        row = self.submit('drive', dict(forward=1., seconds=1.), identity='drive')
        self.assertEqual(('cancelled', 'control_changed'), (row['status'], row['reason']))
        self.assertIsNone(self.control.override)
        self.owner._sender.send_current.assert_not_called()


class InputSequenceReturnTests(unittest.TestCase):
    def client(self):
        client = lan_client.LANClient('127.0.0.1', 28782, 'Sequence', 'ussr:R11_MS-1')
        client.ready, client.phase, client.round_id = True, 'battle', 7
        client.capabilities = client.server_capabilities = (lan_client.HUMAN_RAM_TIMELINE_CAPABILITY,)
        rows = []
        client._send = lambda message: rows.append(copy.deepcopy(message)) or True
        return client, rows

    def test_exact_return_survives_landing_retry_reentry_and_legacy_bool_stays_bool(self):
        client, rows = self.client()
        client._landing_observation_round = 7
        client._landing_observation_pending = dict(retry_on_input=True, sent=False)
        def retry(**unused):
            client._landing_observation_pending = None
            self.assertIs(True, client.send_input(0., 0.))
            return True
        client._send_pending_landing_observation = retry
        self.assertEqual(1, client.send_input_sequence(0., 0., siege_enabled=True))
        self.assertEqual(2, client._input_seq)
        self.assertEqual([1, 2], [row['input_seq'] for row in rows])
        self.assertIs(True, client.send_input(0., 0.))
        self.assertEqual(3, client._input_seq)

    def test_unavailable_echo_and_failed_enqueue_never_return_a_local_guess(self):
        client, rows = self.client()
        client.server_capabilities = ()
        self.assertIsNone(client.send_input_sequence(0., 0.))
        self.assertEqual([], rows)
        self.assertEqual(0, client._input_seq)
        client.server_capabilities = client.capabilities
        client._send = lambda unused: False
        self.assertIsNone(client.send_input_sequence(0., 0.))
        self.assertIs(False, client.send_input(0., 0.))
        self.assertEqual(0, client._input_seq)


class NativeFireAuthorizationTests(unittest.TestCase):
    """Real Weapon, shot freezing, LAN launch and ammunition commit paths."""
    def setUp(self):
        import os
        import math
        import test_port_0922_battle_runtime as runtime_fixture
        from test_player_manual_aim import ObservedRotator
        from gui.mods.offline_lan_0922 import ballistics
        from gui.mods.offline_lan_0922.gun_mechanics import _field
        from gui.mods.offline_lan_0922.player_control import PlayerControl

        self.native = runtime_fixture
        fixture = runtime_fixture.BattleRuntimeContractTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        env = mock.patch.dict(os.environ, {'WOT_OFFLINE_TEST_CONTROL_SESSION': 'native-fire'})
        env.start()
        self.addCleanup(env.stop)
        self.battle, self.gun, self.settings, self.client, self.record = fixture._pending_fire_shell_change_battle()
        self.now = [30.]
        self.battle._clock = lambda: self.now[0]
        self.battle._projectile_server_local_time = self.now[0]
        self.control = PlayerControl(self.battle, (), notify=lambda text: None)
        self.battle._player_control = self.control
        self.rows = []
        self.control.record = mock.Mock()
        self.control.emit_result = lambda row: self.rows.append(copy.deepcopy(row)) or True
        self.control.gateway.emit = self.control.emit_result
        self.control.gateway.wall_clock = lambda: 1000.
        self.entity = self.battle._server_entity(10)
        self.entity.typeDescriptor.gun.pitchLimits.update(
            minPitch=((0., -.4), (2.*math.pi, -.4)),
            maxPitch=((0., .4), (2.*math.pi, .4)))
        self.body = runtime_fixture._Matrix()
        self.battle._local_stabilised_pose = lambda: self.body
        self.rotator = ObservedRotator(lambda: (0., 2., 100.), mode=True)
        self.rotator.dispersionAngle = .0037

        def ray():
            return (runtime_fixture._Vector(0., 2., 0.), runtime_fixture._Vector(
                math.sin(self.rotator.turretYaw)*math.cos(self.rotator.gunPitch),
                -math.sin(self.rotator.gunPitch),
                math.cos(self.rotator.turretYaw)*math.cos(self.rotator.gunPitch)))

        def angles(desc, matrix, current, point):
            shot = self.gun.shots[self.gun.shot_index]
            roots = ballistics.ballistic_solutions((0., 2., 0.), tuple(point),
                _field(shot, 'speed'), _field(shot, 'gravity'))
            return math.atan2(point[0], point[2]), roots[0][0]

        self.rotator.getCurShotPosition = ray
        self.battle._runtime.get_shot_angles = angles
        self.battle._avatar.gunRotator = self.rotator
        self.battle._avatar.isWaitingForShot = False
        # The mailbox body is real. Only the stock Avatar entrance is the
        # explicitly modelled native boundary, as in the pinned-contract tests.
        self.battle._avatar.shoot = lambda: self.battle.shoot(0., 0.)

    def submit(self, action='fire', args=None, identity='fire', timeout=5.):
        request = dict(self.control.identity(), id=identity, action=action,
            args=args or {}, timeout_seconds=timeout, expires_at=1005.)
        return self.control.gateway.submit(request, self.now[0])

    def launches(self):
        return [row for row in self.client.sent if row[0] == 'projectile_launch']

    def align(self):
        self.rotator.turretYaw, self.rotator.gunPitch = self.battle._runtime.get_shot_angles(
            self.entity.typeDescriptor, self.body, (0., 0.), self.rotator.shotPointSourceFunctor())

    def hold(self, target=False):
        if target:
            self.target = self.native._Vehicle(42, self.native._Descriptor(),
                self.native._Vector(20., 0., 100.), (0., 0., 0.), {'health': 500})
            self.battle._runtime.bigworld.entities[42] = self.target
            self.battle._records['enemy'] = dict(ready=True, engine_id=42, state=dict(team=2),
                                                spot_visible=True)
        row = self.submit('aim_target' if target else 'aim_point',
            dict(target_id=42) if target else dict(position=(20., 2., 100.)), identity='aim')
        self.assertEqual('accepted', row['status'])
        self.align()
        self.control.manual_aim.update(self.now[0])
        self.assertEqual('completed', self.control.gateway.requests['aim']['receipt']['status'])

    def hud(self, callback, after_commit=False):
        original = self.battle._avatar.updateVehicleAmmo
        called = [False]

        def update(*args):
            if not called[0] and (not after_commit or self.gun.ammo[0] < 20):
                called[0] = True
                callback()
            return original(*args)

        self.battle._avatar.updateVehicleAmmo = update

    def burst(self):
        descriptor = self.entity.typeDescriptor.gun
        descriptor.burst, descriptor.clip = (3, .1), (3, 1.)
        self.gun.clip_size = self.gun.clip = 3
        self.gun.burst_count, self.gun.burst_interval = 3, .1

    def test_native_hud_stop_blocks_real_launch_and_ammunition_debit(self):
        self.hud(lambda: self.control.stop('native_hud_stop'))
        row = self.submit()
        self.assertEqual(('cancelled', 'native_hud_stop'), (row['status'], row['reason']))
        self.assertEqual([20, 10], self.gun.ammo)
        self.assertFalse(self.launches())
        self.assertFalse(self.battle._projectile_meta)

    def test_native_hud_timeout_is_checked_before_the_real_shot_boundary(self):
        self.hud(lambda: self.now.__setitem__(0, self.now[0] + 2.))
        row = self.submit(timeout=1.)
        self.assertEqual(('failed', 'command_timeout'), (row['status'], row['reason']))
        self.assertFalse(self.launches())
        self.assertEqual([20, 10], self.gun.ammo)

    def test_native_hud_entity_replacement_with_same_engine_id_cannot_fire(self):
        self.hud(lambda: self.battle._runtime.bigworld.entities.__setitem__(10, copy.copy(self.entity)))
        row = self.submit()
        self.assertEqual(('failed', 'vehicle_changed'), (row['status'], row['reason']))
        self.assertFalse(self.launches())
        self.assertEqual([20, 10], self.gun.ammo)

    def test_native_hud_round_change_cannot_authorize_the_old_request(self):
        self.hud(lambda: self.battle._start_message.update(round_id=8))
        row = self.submit()
        self.assertEqual(('failed', 'identity_changed'), (row['status'], row['reason']))
        self.assertFalse(self.launches())

    def test_real_loaded_shell_setting_in_native_hud_cannot_use_old_aim_permission(self):
        self.hold()
        self.hud(lambda: self.battle.change_vehicle_setting(self.settings.CURRENT_SHELLS, 102))
        row = self.submit()
        self.assertEqual(('failed', 'shell_changed'), (row['status'], row['reason']))
        self.assertEqual(1, self.gun.shot_index)
        self.assertEqual([20, 10], self.gun.ammo)
        self.assertFalse(self.launches())

    def test_native_hud_aim_release_or_foreign_source_does_not_fire(self):
        self.hold()
        self.hud(lambda: self.control.manual_aim.stop('native_release', self.now[0]))
        row = self.submit()
        self.assertEqual(('failed', 'aim_owner_changed'), (row['status'], row['reason']))
        self.assertFalse(self.launches())

    def test_native_hud_foreign_source_cannot_reuse_completed_aim_receipt(self):
        self.hold()
        self.hud(lambda: setattr(self.rotator, 'shotPointSourceFunctor', lambda: (0., 0., -100.)))
        row = self.submit()
        self.assertEqual(('failed', 'aim_source_lost'), (row['status'], row['reason']))
        self.assertFalse(self.launches())

    def test_native_hud_angle_change_cannot_fire_on_historical_alignment(self):
        self.hold()
        self.hud(lambda: setattr(self.rotator, 'turretYaw', self.rotator.turretYaw + .3))
        row = self.submit()
        self.assertEqual(('failed', 'aim_not_aligned'), (row['status'], row['reason']))
        self.assertFalse(self.launches())

    def test_newly_aligned_target_does_not_certify_an_older_frozen_shot_ray(self):
        self.hold(target=True)
        original = self.battle._sender.send_current
        called = [False]

        def move_target(*args, **kwargs):
            result = original(*args, **kwargs)
            if not called[0]:
                called[0] = True
                self.target.position = self.native._Vector(50., 0., 100.)
                self.control.manual_aim.update(self.now[0])
                self.align()
            return result

        self.battle._sender.send_current = move_target
        row = self.submit()
        self.assertEqual(('failed', 'aim_not_aligned'), (row['status'], row['reason']))
        self.assertFalse(self.launches())
        self.assertEqual([20, 10], self.gun.ammo)

    def test_stop_inside_projectile_preinstall_discards_only_uncommitted_shell(self):
        original = self.battle._preinstall_player_projectile

        def preinstall(*args, **kwargs):
            projectile_id = original(*args, **kwargs)
            self.control.stop('preinstall_stop')
            return projectile_id

        self.battle._preinstall_player_projectile = preinstall
        row = self.submit()
        self.assertEqual(('cancelled', 'preinstall_stop'), (row['status'], row['reason']))
        self.assertFalse(self.launches())
        self.assertFalse(self.battle._projectile_meta)
        self.assertEqual([20, 10], self.gun.ammo)

    def test_same_native_trigger_cannot_reenter_a_second_uncommitted_shot(self):
        nested = []
        self.hud(lambda: nested.append(self.battle.shoot(0., 0.)))
        row = self.submit()
        self.assertEqual([False], nested)
        self.assertFalse(self.launches())
        self.assertEqual([20, 10], self.gun.ammo)
        self.assertEqual('failed', row['status'])

    def test_preserved_explicit_fire_survives_movement_channel_stop_in_native_hud(self):
        self.hud(lambda: self.control.stop('drive_completed', preserve_explicit=True))
        row = self.submit()
        self.assertEqual(('completed', 'shot_committed'), (row['status'], row['reason']))
        self.assertEqual(1, len(self.launches()))
        self.assertEqual([19, 10], self.gun.ammo)

    def test_real_script_burst_keeps_authorization_until_its_final_native_round(self):
        self.burst()
        row = self.submit()
        self.assertEqual('accepted', row['status'])
        for now in (30.11, 30.22):
            self.now[0] = now
            self.assertTrue(self.battle._advance_local_player_burst())
        self.assertEqual(3, len(self.launches()))
        self.assertEqual([17, 10], self.gun.ammo)
        self.assertEqual('completed', self.control.gateway.requests['fire']['receipt']['status'])

    def test_stop_before_later_burst_round_preserves_the_already_committed_round(self):
        self.burst()
        self.assertEqual('accepted', self.submit()['status'])
        self.assertEqual([19, 10], self.gun.ammo)
        self.battle._ammo_signature = None
        self.hud(lambda: self.control.stop('tail_stop'))
        self.now[0] = 30.11
        self.assertFalse(self.battle._advance_local_player_burst())
        self.assertEqual(1, len(self.launches()))
        self.assertEqual([19, 10], self.gun.ammo)
        self.assertEqual('cancelled', self.control.gateway.requests['fire']['receipt']['status'])
        self.assertIsNone(self.battle._local_player_burst)
        self.assertIsNone(self.control.owned_burst)

    def test_stop_after_wire_acceptance_keeps_committed_round_but_never_reclaims_tail(self):
        self.burst()
        original = self.client.send_projectile_launch

        def accepted(*args, **kwargs):
            result = original(*args, **kwargs)
            self.control.stop('post_send_stop')
            return result

        self.client.send_projectile_launch = accepted
        row = self.submit()
        self.assertEqual(('cancelled', 'post_send_stop'), (row['status'], row['reason']))
        self.assertEqual(1, len(self.launches()))
        self.assertEqual([19, 10], self.gun.ammo)
        self.assertIsNone(self.battle._local_player_burst)
        self.assertIsNone(self.control.owned_burst)
        self.assertEqual(1, len(self.control.shot_receipts.snapshot()))

    def test_stop_in_postcommit_native_hud_neither_rolls_back_nor_restarts_tail(self):
        self.burst()
        self.hud(lambda: self.control.stop('postcommit_stop'), after_commit=True)
        row = self.submit()
        self.assertEqual(('cancelled', 'postcommit_stop'), (row['status'], row['reason']))
        self.assertEqual(1, len(self.launches()))
        self.assertEqual([19, 10], self.gun.ammo)
        self.assertIsNone(self.battle._local_player_burst)
        self.assertIsNone(self.control.owned_burst)

    def test_ordinary_manual_native_fire_with_no_controller_token_is_unchanged(self):
        self.assertFalse(self.control.manual_aim.held)
        self.assertTrue(self.battle.shoot(0., 0.))
        self.assertEqual(1, len(self.launches()))
        self.assertEqual([19, 10], self.gun.ammo)
        self.assertEqual(0, self.control.automatic_commits)
        self.assertFalse(self.control.gateway.requests)

    def test_source_change_in_last_native_entity_query_is_not_hidden_by_fresh_aim_gate(self):
        self.hold()
        gate = self.control.manual_aim.fire_preflight
        resolve = self.battle._server_entity
        after_proof = [False]

        def observed(*args, **kwargs):
            result = gate(*args, **kwargs)
            if self.control.trigger_context is not None:
                after_proof[0] = True
            return result

        def last_query(identity):
            entity = resolve(identity)
            if after_proof[0]:
                after_proof[0] = False
                self.rotator.shotPointSourceFunctor = lambda: (0., 0., -100.)
            return entity

        self.control.manual_aim.fire_preflight = observed
        self.battle._server_entity = last_query
        row = self.submit()
        self.assertEqual(('failed', 'aim_source_lost'), (row['status'], row['reason']))
        self.assertFalse(self.launches())


if __name__ == '__main__':
    unittest.main()
