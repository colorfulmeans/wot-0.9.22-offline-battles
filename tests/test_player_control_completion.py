"""Adversarial foreground lifecycle and canonical equipment/shot regressions.

The real journal, encoder, server and snapshot consumers are exercised where
available. Native motion observations are explicit fixtures, not gameplay proof.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/res/scripts/client'), str(ROOT / 'launcher')]
from gui.mods.offline_lan_0922.player_control import PlayerControl
from gui.mods.offline_lan_0922.player_control.shot_receipts import ShotReceipts
from gui.mods.offline_lan_0922.player_control.settling import HaltObservation
from player_control_transport import PlayerControlTransport


class ForegroundCompletionTests(unittest.TestCase):
    def setUp(self):
        self.now, self.alive, self.rows = [0.], [True], []
        patch = mock.patch.dict(os.environ, {'WOT_OFFLINE_TEST_CONTROL_SESSION': 'completion'})
        patch.start()
        self.addCleanup(patch.stop)

    def control(self, features=('drive', 'fire')):
        entity = types.SimpleNamespace(id=1, isAlive=lambda: self.alive[0], health=1000,
            typeDescriptor=types.SimpleNamespace(maxHealth=1000))
        sender = types.SimpleNamespace(forward=1., turn=.3, handbrake=False,
                                      send_current=mock.Mock(return_value=True))
        gun = types.SimpleNamespace(shots=[{}], ammo=[10], clip=1, clip_size=1,
                                   reload_time=0., shot_index=0)
        gun.can_fire = lambda unused: gun.clip > 0 and gun.ammo[0] > 0 and gun.reload_time <= 0.
        owner = types.SimpleNamespace(_server=types.SimpleNamespace(vehicle_id=1),
            _server_entity=lambda unused: entity, _sender=sender, _gun_state=gun,
            state='running', _battle_live=True, _battle_result=None,
            _worker_mode=False, _replay_mode=False, _clock=lambda: self.now[0],
            _start_message={'round_id': 'round-a'},
            client=types.SimpleNamespace(player_id=1, team=1),
            _avatar=types.SimpleNamespace(isWaitingForShot=False),
            _local_fire_intent=None, _local_player_burst=None,
            _cancel_local_player_burst=mock.Mock(), _local_speed=0., _local_turn_speed=0.,
            _local_pitch=0., _local_roll=0., _local_suspension_pitch_velocity=0.,
            _local_suspension_roll_velocity=0.,
            _local_vertical_speed=0., _local_air_lateral=(0., 0.), _local_airborne=False,
            _local_support_rise_blocked=False, _overturn_level=0,
            local_pose=lambda: ((0., 0., 0.), 0.),
            _collision_shape=lambda unused: (1., 3., 0., 2.))
        control = PlayerControl(owner, features, notify=lambda text: None)
        owner._player_control = control
        control.bind_input = lambda: None
        control.record = mock.Mock()
        control.emit_result = lambda row: self.rows.append(copy.deepcopy(row)) or True
        control.gateway.emit = control.emit_result
        control.gateway.wall_clock = lambda: 1000.
        return control

    def request(self, control, action, identity='one', **values):
        request = dict(control.identity(), id=identity, action=action, args={},
                       timeout_seconds=15., replace=True, expires_at=1005.)
        request.update(values)
        return request

    def update(self, control, now):
        self.now[0] = now
        control.update(.1, now)

    def test_halt_retries_retired_resources_without_cancelling_brake_owner(self):
        control = self.control()
        control.active = True
        release = mock.Mock(side_effect=[RuntimeError('first'), RuntimeError('second'), None])
        control.weapon = types.SimpleNamespace(close=release)
        receipt = control.gateway.submit(self.request(control, 'halt'), 0.)
        self.assertEqual('accepted', receipt['status'])
        for now in (.1, 1.1):
            self.update(control, now)
            self.assertTrue(control.release_pending)
            self.assertEqual('accepted', control.gateway.requests['one']['receipt']['status'])
            self.assertTrue(control.halted)
        self.update(control, 2.2)
        self.assertEqual(3, release.call_count)
        self.assertFalse(control.release_pending)
        self.assertEqual('accepted', control.gateway.requests['one']['receipt']['status'])
        self.update(control, 2.8)
        self.assertEqual('completed', control.gateway.requests['one']['receipt']['status'])
        self.assertTrue(control.halted)
        self.assertEqual((0., 0., True), (control.owner._sender.forward,
            control.owner._sender.turn, control.owner._sender.handbrake))

    def test_halt_requires_full_supported_body_rest_and_settle_time(self):
        blocked = ({'_local_turn_speed': 1.}, {'_local_vertical_speed': -8.},
                   {'_local_air_lateral': (1., 0.)}, {'_local_airborne': True},
                   {'_local_support_rise_blocked': True}, {'_overturn_level': 2},
                   {'_local_suspension_pitch_velocity': .15}, {'_local_suspension_roll_velocity': .12})
        for fields in blocked:
            with self.subTest(fields=fields):
                control = self.control()
                previous = {key: getattr(control.owner, key) for key in fields}
                for key, value in fields.items():
                    setattr(control.owner, key, value)
                self.now[0] = 0.
                control.gateway.submit(self.request(control, 'halt'), 0.)
                for now in (.1, 1., 2.):
                    self.update(control, now)
                    self.assertEqual('accepted', control.gateway.requests['one']['receipt']['status'])
                for key, value in previous.items():
                    setattr(control.owner, key, value)
                self.update(control, 3.)
                self.assertEqual('accepted', control.gateway.requests['one']['receipt']['status'])
                self.update(control, 3.6)
                self.assertEqual('completed', control.gateway.requests['one']['receipt']['status'])

    def test_unknown_motion_is_not_reported_as_stopped(self):
        control = self.control()
        del control.owner._local_turn_speed
        control.gateway.submit(self.request(control, 'halt'), 0.)
        self.update(control, 2.)
        self.assertEqual('accepted', control.gateway.requests['one']['receipt']['status'])
        self.assertEqual('motion_unavailable', control.halt_observation.receipt['reason'])

    def test_observed_displacement_and_clock_regression_restart_settling(self):
        control = self.control()
        rest = HaltObservation()
        self.assertFalse(rest.observe(control.owner, 0.))
        control.owner.local_pose = lambda: ((0., 0., 1.), 0.)
        self.assertFalse(rest.observe(control.owner, .6))
        self.assertFalse(rest.observe(control.owner, .2))
        self.assertFalse(rest.observe(control.owner, .6))
        self.assertTrue(rest.observe(control.owner, .8))

    def test_halt_timeout_releases_brake_and_never_claims_completion(self):
        control = self.control()
        control.owner._local_turn_speed = 2.
        control.gateway.submit(self.request(control, 'halt', timeout_seconds=.5), 0.)
        self.update(control, .1)
        self.update(control, .6)
        receipt = control.gateway.requests['one']['receipt']
        self.assertEqual(('failed', 'command_timeout'), (receipt['status'], receipt['reason']))
        self.assertFalse(control.owns_drive())
        self.assertFalse(control.owner._sender.handbrake)

    def test_pitch_and_roll_displacement_restart_halt_settling(self):
        control = self.control()
        rest = HaltObservation()
        self.assertFalse(rest.observe(control.owner, 0.))
        control.owner._local_pitch, control.owner._local_roll = .15, .12
        self.assertFalse(rest.observe(control.owner, .6))
        self.assertFalse(rest.observe(control.owner, 1.))
        self.assertTrue(rest.observe(control.owner, 1.2))

    def test_nonreplacing_movement_respects_default_and_completed_anchor_ownership(self):
        for anchored in (False, True):
            for action in ('drive', 'attack', 'return_base', 'defend_base', 'hold_position'):
                with self.subTest(anchored=anchored, action=action):
                    control = self.control()
                    control.active = True
                    control.navigation = types.SimpleNamespace(mission_status=lambda:
                        {'status': 'completed'} if anchored else None)
                    command = self.request(control, action, replace=False)
                    if action == 'drive':
                        command['args'] = {'seconds': 1., 'forward': 1.}
                    receipt = control.gateway.submit(command, 0.)
                    self.assertEqual(('rejected', 'movement_busy'), (receipt['status'], receipt['reason']))
                    self.assertTrue(control.active)
                    self.assertIsNone(control.override)

    def test_fire_only_owner_does_not_block_nonreplacing_drive(self):
        control = self.control(('fire',))
        control.active = True
        receipt = control.gateway.submit(self.request(control, 'drive', replace=False,
            args={'seconds': 1., 'forward': 1.}), 0.)
        self.assertEqual('accepted', receipt['status'])
        self.assertIsNotNone(control.override)

    def test_failed_cleanup_does_not_install_new_timed_drive(self):
        control = self.control()
        control.active = True
        control.weapon = types.SimpleNamespace(close=mock.Mock(side_effect=RuntimeError('busy')))
        receipt = control.gateway.submit(self.request(control, 'drive',
            args={'seconds': 1., 'forward': 1.}), 0.)
        self.assertEqual(('failed', 'release_pending'), (receipt['status'], receipt['reason']))
        self.assertIsNone(control.override)
        self.assertFalse(control.owner._sender.forward)

    def test_failed_input_release_submission_is_retried_before_halt_completion(self):
        control = self.control()
        control.active = True
        control.owner._sender.send_current.side_effect = [False, True, True, True, True, True]
        control.gateway.submit(self.request(control, 'halt'), 0.)
        self.assertEqual(['input_release'], [stage for stage, unused in control.release_pending])
        self.update(control, .1)
        self.assertEqual('accepted', control.gateway.requests['one']['receipt']['status'])
        self.update(control, 1.1)
        self.assertFalse(control.release_pending)
        self.update(control, 1.7)
        self.assertEqual('completed', control.gateway.requests['one']['receipt']['status'])

    def test_nonlive_client_consumes_stop_and_rejects_gameplay_with_real_journal(self):
        for end in ('death', 'result'):
            with self.subTest(end=end), tempfile.TemporaryDirectory() as directory:
                command_path, result_path = Path(directory) / 'commands.jsonl', Path(directory) / 'results.jsonl'
                with mock.patch.dict(os.environ, {
                    'WOT_OFFLINE_TEST_CONTROL_FILE': str(command_path),
                    'WOT_OFFLINE_TEST_CONTROL_RESULT_FILE': str(result_path)}):
                    self.alive[0], self.now[0] = True, 0.
                    control = self.control()
                    control.emit_result = lambda row: PlayerControl.emit_result(control, row)
                    control.gateway.emit = control.emit_result
                    control.active = True
                    if end == 'death':
                        self.alive[0] = False
                    else:
                        control.owner._battle_result = {'reason': 'captured'}
                    self.update(control, 1.)
                    transport = PlayerControlTransport(str(command_path), str(result_path),
                        'completion', clock=lambda: self.now[0], wall_clock=lambda: 1000.)
                    transport.poll()
                    self.assertFalse(transport.live)
                    identity = transport.send('stop')
                    self.assertIsNotNone(identity)
                    with command_path.open('a', encoding='utf8') as output:
                        output.write(json.dumps(self.request(control, 'drive', identity='late',
                            args={'seconds': 1., 'forward': 1.})) + '\n')
                    self.update(control, 1.3)
                    transport.poll()
                    self.assertEqual('completed', transport.results[identity]['status'])
                    self.assertEqual('battle_not_live', control.gateway.requests['late']['receipt']['reason'])
                    self.assertIsNone(control.override)
                    self.assertEqual(command_path.stat().st_size, control.command_offset)

    def test_old_rejection_retains_shot_receipt_without_poisoning_new_generation(self):
        control = self.control()
        context = {'command': 'old', 'target': 7, 'policy': None,
                   'generation': control.control_generation}
        control.trigger_context = context
        control.shot_committed({'projectile_id': 'old-shot', 'shell_index': 0}, {})
        control.trigger_context = None
        control.stop()
        control.active = True
        control.control_generation += 1
        control.fire_command = 'new'
        control.fire_rejected('late_rejection', 'old-shot')
        self.assertIsNone(control.last_fire_failure)
        self.assertEqual('new', control.fire_command)
        rejected = [row for row in self.rows if row.get('status') == 'rejected']
        self.assertEqual(1, len(rejected))
        self.assertEqual('old', rejected[0]['command_id'])

    def test_inactive_committed_shot_survives_stop_and_reports_late_effect_once(self):
        control = self.control()
        control.trigger_context = {'command': 'shot-command', 'target': 7, 'policy': None}
        control.shot_committed({'projectile_id': 'shot', 'shell_index': 0}, {})
        control.trigger_context = None
        control.stop()
        control.shot_terminal({'projectile_id': 'shot', 'hit_vehicle': True})
        event = {'projectile_id': 'shot', 'event_id': 30, 'damage': 140, 'shot_result': 2}
        control.shot_hit(event)
        control.shot_hit(event)
        control.shot_terminal({'projectile_id': 'foreign', 'hit_vehicle': True})
        control.shot_hit(dict(event, projectile_id='foreign'))
        shots = [row for row in self.rows if row.get('type') == 'shot']
        self.assertEqual(['committed', 'terminal', 'hit'], [row['status'] for row in shots])
        self.assertEqual(140, shots[-1]['damage_total'])
        self.assertEqual('terminal', shots[-1]['flight_status'])
        control.publish_status(1., force=True)
        self.assertEqual(shots[-1]['event_seq'], self.rows[-1]['shot_results'][0]['event_seq'])

    def test_delayed_rejection_of_earlier_trigger_does_not_poison_current_fire(self):
        control = self.control()
        from gui.mods.offline_lan_0922.player_control.weapon import Weapon
        for identity in ('first', 'second'):
            control.owner._avatar.shoot = lambda identity=identity: control.shot_committed(
                {'projectile_id': identity, 'shell_index': 0}, {})
            self.assertTrue(control.trigger(Weapon(control.owner), self.now[0]))
        control.fire_rejected('earlier_rejection', 'first')
        self.assertIsNone(control.last_fire_failure)
        control.fire_rejected('current_rejection', 'second')
        self.assertEqual('current_rejection', control.last_fire_failure)

    def test_status_repair_window_respects_actual_receiver_line_budget(self):
        control = self.control()
        for index in range(32):
            pid = 'projectile-' + str(index) + '-' + 'p' * 230
            control.trigger_context = {'command': 'c' * 128, 'target': 7, 'policy': None}
            control.shot_committed({'projectile_id': pid, 'shell_index': 0}, {})
            control.shot_terminal({'projectile_id': pid, 'hit_vehicle': True})
            control.shot_hit({'projectile_id': pid, 'event_id': index, 'damage': 100, 'shot_result': 2})
        control.trigger_context = None
        control.publish_status(1., force=True)
        status = self.rows[-1]
        encoded = json.dumps(status, ensure_ascii=True, separators=(',', ':')).encode('ascii') + b'\n'
        self.assertLessEqual(len(encoded), PlayerControlTransport.MAX_LINE_BYTES)
        self.assertGreater(status['shot_snapshot_omitted'], 0)
        self.assertEqual(pid, status['shot_results'][-1]['projectile_id'])
        self.assertEqual(96, len([row for row in self.rows if row.get('type') == 'shot']))


class ShotReceiptObservationTests(unittest.TestCase):
    def ledger(self):
        result = ShotReceipts()
        result.committed({'projectile_id': 'p', 'shell_index': 0}, {},
                         {'command': 'fire'}, 0., 1)
        return result

    def test_terminal_does_not_invent_a_combat_outcome_and_he_effects_accumulate(self):
        ledger = self.ledger()
        terminal = ledger.terminal({'projectile_id': 'p', 'hit_vehicle': True}, 1.)
        self.assertTrue(terminal['terminal_observed'])
        self.assertFalse(terminal['combat_observed'])
        self.assertNotIn('outcome_known', terminal)
        for event_id, damage in ((1, 50), (2, 25)):
            event = {'projectile_id': 'p', 'event_id': event_id, 'damage': damage, 'shot_result': 2}
            row = ledger.hit(event, 1.1)
            self.assertIsNone(ledger.hit(event, 1.2))
        self.assertEqual((75., 2, True), (row['damage_total'], row['hit_count'], row['penetrated']))
        self.assertTrue(row['terminal_observed'])
        self.assertIsNone(ledger.terminal({'projectile_id': 'p'}, 2.))

    def test_rejected_launch_ignores_later_cosmetic_terminal_and_combat_duplicates(self):
        ledger = self.ledger()
        self.assertIsNotNone(ledger.rejected('p', 'rejected', 1.))
        self.assertIsNone(ledger.rejected('p', 'rejected', 2.))
        self.assertIsNone(ledger.terminal({'projectile_id': 'p'}, 2.))
        self.assertIsNone(ledger.hit({'projectile_id': 'p', 'event_id': 1, 'damage': 100}, 2.))
        self.assertEqual(0., ledger.snapshot()[0]['damage_total'])

    def test_nonfinite_and_cosmetic_effects_cannot_consume_an_event_identity(self):
        ledger = self.ledger()
        event = {'projectile_id': 'p', 'event_id': 1, 'damage': 20}
        for damage in (float('nan'), float('inf'), 'bad'):
            self.assertIsNone(ledger.hit(dict(event, damage=damage), 1.))
        self.assertIsNone(ledger.hit(dict(event, cosmetic_only=True), 1.))
        self.assertEqual(20., ledger.hit(event, 1.)['damage_total'])

    def test_unicode_ids_are_preserved_without_coercing_to_ascii(self):
        ledger = self.ledger()
        self.assertIsNone(ledger.get(u'\u4e2d'))
        ledger.committed({'projectile_id': u'\u4e2d'}, {}, {}, 1., 1)
        self.assertEqual(u'\u4e2d', ledger.get(u'\u4e2d')['projectile_id'])
        event = {'projectile_id': u'\u4e2d', 'event_id': u'\u6548\u679c', 'damage': 10}
        self.assertEqual(10., ledger.hit(event, 2.)['damage_total'])
        self.assertIsNone(ledger.hit(event, 2.))
        self.assertEqual(u'\u62d2\u7edd', ledger.rejected(u'\u4e2d', u'\u62d2\u7edd', 3.)['reason'])

    def test_snapshot_retains_recent_observation_of_older_live_projectile(self):
        ledger = self.ledger()
        for index in range(40):
            ledger.committed({'projectile_id': 'next-%s' % index}, {}, {}, 1., 1)
        ledger.hit({'projectile_id': 'p', 'event_id': 1, 'damage': 10}, 2.)
        rows = ledger.snapshot()
        self.assertEqual(32, len(rows))
        self.assertEqual('p', rows[-1]['projectile_id'])

    def test_history_is_bounded_without_dropping_live_projectiles(self):
        ledger = self.ledger()
        for index in range(300):
            identity = 'done-%s' % index
            ledger.committed({'projectile_id': identity}, {}, {}, 1., 1)
            ledger.terminal({'projectile_id': identity, 'hit_vehicle': False}, 1.)
        ledger.hit({'projectile_id': 'p', 'event_id': 1, 'damage': 10}, 10.)
        self.assertEqual(257, len(ledger.rows))
        self.assertIsNotNone(ledger.get('p'))

    def test_late_effect_is_not_pruned_during_its_own_observation(self):
        ledger = self.ledger()
        ledger.terminal({'projectile_id': 'p', 'hit_vehicle': True}, 1.)
        for index in range(256):
            identity = 'later-%s' % index
            ledger.committed({'projectile_id': identity}, {}, {}, 2., 1)
            ledger.terminal({'projectile_id': identity, 'hit_vehicle': False}, 2.)
        row = ledger.hit({'projectile_id': 'p', 'event_id': 1000, 'damage': 140}, 10.)
        self.assertIsNotNone(ledger.get('p'))
        self.assertEqual(256, len(ledger.rows))
        self.assertEqual(row, ledger.snapshot()[-1])
        self.assertIsNone(ledger.get('later-0'))


class CanonicalConsumableCompletionTests(unittest.TestCase):
    def setup_equipment(self, mounted):
        import test_port_0922_consumable_audit as fixture
        from gui.mods.offline_lan_0922 import lan_client
        from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime
        battle, player = fixture.battle_state([mounted])
        descriptor = types.SimpleNamespace(extras={10: types.SimpleNamespace(name='commanderHealth')})
        entity = types.SimpleNamespace(typeDescriptor=descriptor)
        client = lan_client.LANClient('127.0.0.1', 28782, 'Completion', player.vehicle)
        client.ready, client.phase, client.player_id, client.round_id = True, 'battle', 1, 1
        client.is_bot_authority = lambda: False
        sent = []
        def send(message):
            sent.append(copy.deepcopy(message))
            return battle.submit_equipment_intent(1, message)
        client._send = send
        owner = types.SimpleNamespace(client=client, _server=types.SimpleNamespace(vehicle_id=10),
            _records={'player:1': {'critical_state': {}, 'state': {}}},
            _equipment_state=None, _equipment_revision=-1,
            _clock=lambda: float(battle.tick) / fixture.server.TICK_HZ,
            _server_entity=lambda unused: entity,
            _critical_extra_index=BattleRuntime._critical_extra_index,
            _critical_name_from_extra_index=BattleRuntime._critical_name_from_extra_index,
            _report_critical_presentation=mock.Mock(), _local_speed=3., _local_airborne=False,
            _local_support_rise_blocked=False,
            _local_ground_plane={'gradient_x': 0., 'gradient_z': .1},
            local_pose=lambda: ((0., 0., 0.), 0.),
            _projectile_estimated_server_time=lambda now: battle._server_time_ms())
        owner._activate_equipment = lambda code: BattleRuntime._activate_equipment(owner, code)
        def restore():
            local = dict(id=1, equipment_revision=player.equipment_revision,
                equipment_intent_result=player.equipment_intent_result,
                equipment_states=[value.snapshot(owner._clock()) for value in player.equipment_states])
            return BattleRuntime._restore_local_equipment_snapshot(owner, {'players': [local]})
        restore()
        control = PlayerControl(owner, ('consumables',), notify=lambda text: None)
        control.record = mock.Mock()
        return fixture, battle, player, entity, owner, control, sent, restore

    def test_governor_off_survives_real_snapshot_reconstruction_on_all_exit_conditions(self):
        import test_port_0922_consumable_audit as fixture
        for exit_condition in ('flat', 'downhill', 'engine_destroyed', 'airborne'):
            with self.subTest(exit_condition=exit_condition):
                f, battle, player, entity, owner, control, sent, restore = self.setup_equipment(fixture.governor())
                control.consumables(entity)
                battle.tick += 2 * f.server.TICK_HZ
                control.consumables(entity)
                self.assertEqual([True], [row['requested_active'] for row in sent])
                previous = owner._equipment_state[0]
                restore()
                self.assertIsNot(previous, owner._equipment_state[0])
                if exit_condition == 'flat':
                    owner._local_ground_plane['gradient_z'] = 0.
                elif exit_condition == 'downhill':
                    owner._local_ground_plane['gradient_z'] = -.1
                elif exit_condition == 'engine_destroyed':
                    owner._records['player:1']['critical_state']['destroyed'] = ['engineHealth']
                else:
                    owner._local_airborne = True
                # A changed intent cancels on even before the retry throttle.
                control.consumables(entity)
                self.assertEqual([True, False], [row['requested_active'] for row in sent])
                self.assertFalse(player.equipment_states[0].active)

    def test_governor_cancels_pending_on_without_waiting_for_old_echo(self):
        import test_port_0922_consumable_audit as fixture
        f, battle, player, entity, owner, control, sent, restore = self.setup_equipment(fixture.governor())
        control.consumables(entity)
        battle.tick += 2 * f.server.TICK_HZ
        control.consumables(entity)
        self.assertFalse(owner._equipment_state[0].active)
        self.assertTrue(player.equipment_states[0].active)
        owner._local_ground_plane['gradient_z'] = 0.
        control.consumables(entity)
        self.assertEqual([True, False], [row['requested_active'] for row in sent])
        self.assertFalse(player.equipment_states[0].active)

    def test_governor_enabled_manually_is_never_adopted_or_disabled(self):
        import test_port_0922_consumable_audit as fixture
        f, battle, player, entity, owner, control, sent, restore = self.setup_equipment(fixture.governor())
        self.assertTrue(owner._activate_equipment((1 << 16) | 12))
        restore()
        control.consumables(entity)
        battle.tick += 3 * f.server.TICK_HZ
        control.consumables(entity)
        owner._local_ground_plane['gradient_z'] = 0.
        control.consumables(entity)
        control.release_governor()
        self.assertEqual([True], [row['requested_active'] for row in sent])
        self.assertTrue(player.equipment_states[0].active)

    def test_failed_governor_release_preserves_ownership_for_retry(self):
        import test_port_0922_consumable_audit as fixture
        f, battle, player, entity, owner, control, sent, restore = self.setup_equipment(fixture.governor())
        control.consumables(entity)
        battle.tick += 2 * f.server.TICK_HZ
        control.consumables(entity)
        actual = owner._activate_equipment
        owner._activate_equipment = lambda code: False
        with self.assertRaisesRegex(RuntimeError, 'governor_release_not_submitted'):
            control.release_governor()
        self.assertIsNotNone(control.owned_governor)
        owner._activate_equipment = actual
        control.release_governor()
        self.assertIsNone(control.owned_governor)
        self.assertFalse(player.equipment_states[0].active)

    def test_small_medkit_clears_pure_stun_through_native_encoding_and_server(self):
        import test_port_0922_consumable_audit as fixture
        f, battle, player, entity, owner, control, sent, restore = self.setup_equipment(fixture.medkit())
        player.stun_end_server_time_ms = battle._server_time_ms() + 20000
        owner._records['player:1']['state']['stun_end_server_time_ms'] = player.stun_end_server_time_ms
        control.consumables(entity)
        self.assertEqual(1, len(sent))
        self.assertEqual((10, 'commander'), (sent[0]['activation_code'] >> 16, sent[0]['selected']))
        self.assertTrue(player.equipment_intent_result['accepted'])
        self.assertEqual(0, player.stun_end_server_time_ms)
        restore()
        battle.tick += 3 * f.server.TICK_HZ
        control.consumables(entity)
        self.assertEqual(1, len(sent))

    def test_stun_without_any_real_crew_extra_is_contained_not_fabricated(self):
        import test_port_0922_consumable_audit as fixture
        f, battle, player, entity, owner, control, sent, restore = self.setup_equipment(fixture.medkit())
        entity.typeDescriptor.extras = {}
        player.stun_end_server_time_ms = battle._server_time_ms() + 20000
        owner._records['player:1']['state']['stun_end_server_time_ms'] = player.stun_end_server_time_ms
        control.consumables(entity)
        self.assertFalse(sent)
        self.assertGreater(player.stun_end_server_time_ms, 0)
        self.assertEqual('consumable_unavailable', control.record.call_args.args[0])

    def test_small_repair_prioritizes_destroyed_engine_before_critical_gun(self):
        import test_port_0922_consumable_audit as fixture
        mounted = fixture.item('smallRepairkit', 4, tags=('repairkit',), reuseCount=-1, cooldownSeconds=90)
        f, battle, player, entity, owner, control, sent, restore = self.setup_equipment(mounted)
        player.effective_params['critical']['devices'].append(
            {'name': 'gunHealth', 'max_hp': 100, 'regen_hp': 50})
        player.effective_params['critical']['activation_targets'] = [
            {'index': 82, 'name': 'engineHealth'}, {'index': 83, 'name': 'gunHealth'}]
        player.critical = {'devices': [
            {'name': 'engineHealth', 'hp': 0, 'state': 'destroyed'},
            {'name': 'gunHealth', 'hp': 20, 'state': 'critical'}], 'destroyed': ['engineHealth']}
        owner._records['player:1']['critical_state'] = copy.deepcopy(player.critical)
        entity.typeDescriptor.extras = {82: types.SimpleNamespace(name='engineHealth'),
                                       83: types.SimpleNamespace(name='gunHealth')}
        control.consumables(entity)
        self.assertEqual('engineHealth', sent[0]['selected'])
        self.assertTrue(player.equipment_intent_result['accepted'])
        self.assertNotIn('engineHealth', player.critical['destroyed'])
        gun = next(row for row in player.critical['devices'] if row['name'] == 'gunHealth')
        self.assertEqual(20, gun['hp'])


class NativeShotCompletionTests(unittest.TestCase):
    def setUp(self):
        import test_port_0922_battle_runtime as fixture
        self.fixture = fixture.BattleRuntimeContractTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.command_path = Path(self.directory.name) / 'commands.jsonl'
        self.result_path = Path(self.directory.name) / 'results.jsonl'
        patch = mock.patch.dict(os.environ, {
            'WOT_OFFLINE_TEST_CONTROL_SESSION': 'completion',
            'WOT_OFFLINE_TEST_CONTROL_FILE': str(self.command_path),
            'WOT_OFFLINE_TEST_CONTROL_RESULT_FILE': str(self.result_path)})
        patch.start()
        self.addCleanup(patch.stop)

    def fire(self):
        battle, gun, unused, client, record = self.fixture._pending_fire_shell_change_battle()
        control = PlayerControl(battle, ('drive', 'fire'), notify=lambda text: None)
        control.record = mock.Mock()
        control.gateway.wall_clock = lambda: 1000.
        battle._player_control = control
        battle._avatar.shoot = lambda: battle.shoot(0., 0.)
        control.publish_status(battle._clock(), force=True)
        transport = PlayerControlTransport(str(self.command_path), str(self.result_path),
            'completion', clock=battle._clock, wall_clock=lambda: 1000.)
        identity = transport.send('fire')
        self.assertIsNotNone(identity)
        control.poll_commands(battle._clock())
        transport.poll()
        self.assertEqual('completed', transport.results[identity]['status'])
        return battle, gun, control, transport, identity, self.fixture._local_launch(battle)

    def test_inactive_panel_shot_reports_real_terminal_without_ammo_policy(self):
        battle, gun, control, transport, identity, launch = self.fire()
        self.assertIsNone(control.ammo_policy)
        pid = launch['projectile_id']
        self.assertTrue(battle._apply_projectile_terminal_event({'projectile_id': pid,
            'hit_vehicle': False, 'resolved_time_ms': 1000, 'round_id': 7}))
        self.assertNotIn(pid, battle._projectile_meta)
        rows = [json.loads(line) for line in self.result_path.read_text().splitlines()]
        shots = [row for row in rows if row.get('type') == 'shot']
        self.assertEqual(['committed', 'terminal'], [row['status'] for row in shots])
        self.assertTrue(all(row['command_id'] == identity for row in shots))
        transport.poll()
        observed = transport.projectile_results(identity)
        self.assertEqual(1, len(observed))
        self.assertIn('terminal', observed[0]['events'])

    def test_delayed_native_rejection_keeps_debit_reload_and_separate_command_result(self):
        battle, gun, control, transport, identity, launch = self.fire()
        before = list(gun.ammo), gun.reload_time, gun.clip
        self.assertTrue(self.fixture._reject_local_launch(battle, launch))
        self.assertFalse(self.fixture._reject_local_launch(battle, launch))
        self.assertEqual(before, (list(gun.ammo), gun.reload_time, gun.clip))
        transport.poll()
        self.assertEqual('completed', transport.results[identity]['status'])
        observed = transport.projectile_results(identity)
        self.assertEqual(1, len(observed))
        self.assertEqual('projectile_launch_rejected', observed[0]['events']['rejected']['reason'])


if __name__ == '__main__':
    unittest.main()
