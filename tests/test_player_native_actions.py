"""Foreground native requests with real wire, authority and snapshot receipts.

Native body presentation is an explicit boundary fixture. These tests do not
claim Windows timing or physics acceptance.
"""
import copy
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/res/scripts/client'), str(ROOT / 'server')]

from gui.mods.offline_lan_0922 import lan_client, siege_mechanics
from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime
from gui.mods.offline_lan_0922.player_control.commands import CommandGateway
from gui.mods.offline_lan_0922.player_control.native_actions import NativeActions
import test_port_0922_consumable_audit as equipment_fixture


class NativeActionHarness(unittest.TestCase):
    def setUp(self):
        self.now, self.alive, self.receipts = [30.], [True], []
        self.identity = dict(session_id='native-test', round_id=1, player_id=1)

    def bind(self, owner):
        self.owner = owner
        owner._clock = lambda: self.now[0]
        self.control = types.SimpleNamespace(owner=owner, active=False, closed=False,
            override=None, features=frozenset(), halted=False, record=mock.Mock(),
            release_pending=[], next_release=0.,
            identity=lambda: dict(self.identity), live=lambda: self.alive[0])
        self.control.owns_automatic_drive = lambda: self.control.active and 'drive' in self.control.features
        self.actions = NativeActions(self.control)
        self.control.native_actions = self.actions
        self.control.gateway = CommandGateway(self.control.identity,
            lambda row: self.receipts.append(copy.deepcopy(row)) or True,
            self.actions.execute, self.actions.preflight, self.actions.cancel,
            wall_clock=lambda: 1000.)
        owner._player_control = self.control
        return owner

    def submit(self, action, args, command_id='one', timeout=30.):
        request = dict(self.identity, action=action, args=args, id=command_id,
                       expires_at=1005., timeout_seconds=timeout)
        return self.control.gateway.submit(request, self.now[0])

    def receipt(self, command_id='one'):
        return self.control.gateway.requests[command_id]['receipt']

    def observe(self, seconds=0.):
        self.now[0] += seconds
        self.actions.update(self.now[0])

    def interrupt_selection(self, action, change, getter_call=1):
        original = self.owner._server_entity
        entered = [0]
        def resolve(vehicle_id):
            entity = original(vehicle_id)
            operation = (self.actions.equipment_pending if action == 'use_equipment'
                         else self.actions.siege_pending)
            if operation is not None and operation['phase'] == 'preparing':
                entered[0] += 1
                if entered[0] == getter_call:
                    if change == 'timeout':
                        self.now[0] += 2.
                    elif change == 'stop':
                        self.actions.stop('manual', self.now[0])
                    elif change == 'round':
                        self.identity['round_id'] = 2
                        self.owner.client.round_id = 2
                    elif change == 'owner':
                        self.control.owner = types.SimpleNamespace()
                    elif change == 'entity':
                        replacement = types.SimpleNamespace(typeDescriptor=entity.typeDescriptor)
                        self.owner._server_entity = lambda unused: replacement
                    elif change == 'death':
                        self.alive[0] = False
            return entity
        self.owner._server_entity = resolve
        return entered

    def equipment(self, mounted):
        battle, player = equipment_fixture.battle_state(mounted)
        descriptor = types.SimpleNamespace(extras={
            82: types.SimpleNamespace(name='engineHealth'),
            78: types.SimpleNamespace(name='loader1Health'),
            10: types.SimpleNamespace(name='commanderHealth')})
        self.entity = types.SimpleNamespace(typeDescriptor=descriptor, health=100,
                                           isAlive=lambda: self.alive[0])
        client = lan_client.LANClient('127.0.0.1', 28782, 'NativeAction', player.vehicle)
        client.ready, client.phase, client.player_id, client.round_id = True, 'battle', 1, 1
        client.is_bot_authority = lambda: False
        self.sent = []
        def send(message):
            self.sent.append(copy.deepcopy(message))
            return battle.submit_equipment_intent(1, message)
        client._send = send
        owner = types.SimpleNamespace(client=client, _server=types.SimpleNamespace(vehicle_id=10),
            _server_entity=lambda unused: self.entity, _equipment_state=None, _equipment_revision=-1,
            _records={'player:1': {'critical_state': {}, 'state': {}}},
            _critical_extra_index=BattleRuntime._critical_extra_index,
            _critical_name_from_extra_index=BattleRuntime._critical_name_from_extra_index,
            _report_critical_presentation=mock.Mock())
        self.bind(owner)
        owner._activate_equipment_intent = lambda code: BattleRuntime._activate_equipment_intent(owner, code)
        self.battle, self.player = battle, player
        player.effective_params['critical']['activation_targets'] = [
            {'index': 82, 'name': 'engineHealth'}, {'index': 78, 'name': 'loader1'},
            {'index': 10, 'name': 'commander'}]
        self.restore_equipment()
        return owner

    def restore_equipment(self):
        player = self.player
        local = self.battle._public_player(player)
        self.owner._last_snapshot = dict(round_id=1, players=[local])
        self.owner.client._equipment_intent_seq = max(self.owner.client._equipment_intent_seq,
                                                      player.equipment_intent_seq)
        return BattleRuntime._restore_local_equipment_snapshot(self.owner, self.owner._last_snapshot)


class EquipmentCommandTests(NativeActionHarness):
    def test_every_manual_equipment_kind_uses_native_code_and_exact_canonical_result(self):
        cases = (
            ('largeRepairkit', 5, 'repairkit', True, 'engineHealth', 1),
            ('largeMedkit', 6, 'medkit', True, 'loader1', 1),
            ('handExtinguishers', 3, 'extinguisher', False, None, 1),
            ('smallRepairkit', 4, 'repairkit', False, 'engineHealth', 82),
            ('smallMedkit', 2, 'medkit', False, 'loader1', 78))
        for name, item_id, kind, repair_all, target, extra in cases:
            with self.subTest(kind=name):
                mounted = equipment_fixture.item(name, item_id, tags=(kind,),
                    repairAll=repair_all, reuseCount=-1, cooldownSeconds=90)
                self.equipment([mounted])
                self.player.critical = {
                    'devices': [{'name': 'engineHealth', 'hp': 0, 'state': 'destroyed'}]
                        if kind == 'repairkit' else [],
                    'destroyed': ['engineHealth'] if kind == 'repairkit' else [],
                    'crew_ko': ['loader1'] if kind == 'medkit' else [],
                    'fire': kind == 'extinguisher'}
                args = dict(equipment_id=item_id)
                if target and not repair_all:
                    args['target'] = target
                self.assertEqual('accepted', self.submit('use_equipment', args)['status'])
                self.assertEqual(1, len(self.sent))
                self.assertEqual(item_id | (extra << 16), self.sent[0]['activation_code'])
                self.assertEqual(None if repair_all else target, self.sent[0]['selected'])
                self.assertTrue(self.player.equipment_intent_result['accepted'])
                self.assertFalse(self.player.critical.get('destroyed'))
                self.assertFalse(self.player.critical.get('crew_ko'))
                self.assertFalse(self.player.critical.get('fire'))
                # Authority committed, but the foreground has not observed it.
                self.observe()
                self.assertEqual('accepted', self.receipt()['status'])
                previous = self.owner._equipment_state[0]
                self.restore_equipment()
                self.assertIsNot(previous, self.owner._equipment_state[0])
                self.observe()
                self.assertEqual(('completed', 'equipment_applied'),
                    (self.receipt()['status'], self.receipt()['reason']))
                self.assertEqual(1, self.receipt()['result']['intent_seq'])
                self.assertFalse(self.owner._equipment_state[0].ready(self.now[0]))

    def test_stunned_healthy_crew_uses_the_real_medkit_target_and_commits_stun_clear(self):
        self.equipment([equipment_fixture.medkit()])
        self.player.stun_end_server_time_ms = self.battle._server_time_ms() + 20000
        self.assertEqual('accepted', self.submit('use_equipment',
            {'equipment_id': 2, 'target': 'commander'})['status'])
        self.assertEqual(0, self.player.stun_end_server_time_ms)
        self.restore_equipment()
        self.observe()
        self.assertEqual('completed', self.receipt()['status'])

    def test_authoritative_rejection_is_terminal_and_never_claimed_as_setter_success(self):
        self.equipment([equipment_fixture.medkit()])
        self.assertEqual('accepted', self.submit('use_equipment',
            {'equipment_id': 2, 'target': 'commander'})['status'])
        self.assertFalse(self.player.equipment_intent_result['accepted'])
        self.restore_equipment()
        self.observe()
        self.assertEqual(('failed', 'equipment_ineligible'),
                         (self.receipt()['status'], self.receipt()['reason']))

    def test_passive_automatic_and_mismatched_arguments_never_reach_native_setter(self):
        cases = (
            (equipment_fixture.food(), {'equipment_id': 10}, 'equipment_not_activatable'),
            (equipment_fixture.item('autoExtinguishers', 1, autoactivate=True),
                {'equipment_id': 1}, 'automatic_equipment_only'),
            (equipment_fixture.medkit(), {'equipment_id': 2}, 'equipment_target_required'),
            (equipment_fixture.medkit(), {'equipment_id': 2, 'target': 'engineHealth'}, 'equipment_target_unavailable'),
            (equipment_fixture.medkit(), {'equipment_id': 2, 'target': 'driver'}, 'equipment_target_unavailable'),
            (equipment_fixture.medkit(), {'equipment_id': 2, 'target': 'commander', 'active': True},
                'unexpected_equipment_active'),
            (equipment_fixture.governor(), {'equipment_id': 12}, 'equipment_active_required'),
            (equipment_fixture.governor(), {'equipment_id': 12, 'active': True, 'target': 'commander'},
                'unexpected_equipment_target'),
            (equipment_fixture.item('largeMedkit', 6, tags=('medkit',), repairAll=True),
                {'equipment_id': 6, 'target': 'commander'}, 'unexpected_equipment_target'))
        for mounted, args, reason in cases:
            with self.subTest(args=args, reason=reason):
                self.equipment([mounted])
                receipt = self.submit('use_equipment', args)
                self.assertEqual(('rejected', reason), (receipt['status'], receipt['reason']))
                self.assertEqual([], self.sent)

    def test_governor_already_set_is_canonical_noop_and_never_adopts_manual_pending(self):
        self.equipment([equipment_fixture.governor()])
        receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': False})
        self.assertEqual(('completed', 'equipment_already_set'), (receipt['status'], receipt['reason']))
        self.assertEqual([], self.sent)
        self.owner._activate_equipment_intent((1 << 16) | 12)
        receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': False}, 'two')
        self.assertEqual(('rejected', 'equipment_native_busy'), (receipt['status'], receipt['reason']))
        self.restore_equipment()
        receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': True}, 'three')
        self.assertEqual('equipment_already_set', receipt['reason'])
        self.assertEqual(1, len(self.sent))

    def test_cooldown_change_without_exact_receipt_never_completes_the_command(self):
        self.equipment([equipment_fixture.governor()])
        self.submit('use_equipment', {'equipment_id': 12, 'active': True})
        self.owner._equipment_state[0].active = True
        self.owner._equipment_state[0].ready_at = 120.
        self.observe()
        self.assertEqual('accepted', self.receipt()['status'])
        # A later real manual activation overwrote the only canonical result.
        self.owner._activate_equipment_intent(12)
        self.restore_equipment()
        self.observe()
        self.assertEqual(('failed', 'equipment_receipt_superseded'),
                         (self.receipt()['status'], self.receipt()['reason']))
        self.assertEqual(2, self.receipt()['result']['canonical_result']['intent_seq'])

    def test_unrestored_or_old_round_ledger_is_not_observation(self):
        self.equipment([equipment_fixture.governor()])
        self.submit('use_equipment', {'equipment_id': 12, 'active': True})
        self.restore_equipment()
        self.owner._equipment_revision = -1
        self.observe()
        self.assertEqual('accepted', self.receipt()['status'])
        self.owner._equipment_revision = self.player.equipment_revision
        self.owner._last_snapshot['round_id'] = '1'
        self.observe()
        self.assertEqual('accepted', self.receipt()['status'])
        self.owner._last_snapshot['round_id'] = 1
        self.observe()
        self.assertEqual('completed', self.receipt()['status'])

    def test_cancellation_preserves_committed_equipment_and_deduplicates_retries(self):
        self.equipment([equipment_fixture.governor()])
        self.submit('use_equipment', {'equipment_id': 12, 'active': True})
        self.actions.stop('manual', self.now[0])
        self.assertTrue(self.player.equipment_states[0].active)
        self.restore_equipment()
        self.observe()
        self.assertEqual('cancelled', self.receipt()['status'])
        self.assertEqual('cancelled', self.submit('use_equipment', {'equipment_id': 12, 'active': True})['status'])
        self.assertEqual(1, len(self.sent))

    def test_synchronous_restore_needs_submission_identity_and_respects_deadline(self):
        for elapsed in (0., 1.):
            with self.subTest(elapsed=elapsed):
                self.now[0] = 30.
                self.equipment([equipment_fixture.governor()])
                original = self.owner._report_critical_presentation
                def report(*args):
                    self.restore_equipment()
                    self.now[0] += elapsed
                    self.actions.update(self.now[0])
                    original(*args)
                self.owner._report_critical_presentation = report
                receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': True}, timeout=1.)
                self.assertEqual('completed' if elapsed == 0. else 'failed', receipt['status'])
                self.assertEqual('equipment_applied' if elapsed == 0. else 'command_timeout', receipt['reason'])
                self.assertTrue(self.player.equipment_states[0].active)
                self.assertEqual(30. + elapsed, receipt['time'])

    def test_synchronous_stop_cannot_turn_a_committed_effect_into_success(self):
        self.equipment([equipment_fixture.governor()])
        self.owner._report_critical_presentation = lambda *unused: self.actions.stop('manual', self.now[0])
        receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': True})
        self.assertEqual(('cancelled', 'manual'), (receipt['status'], receipt['reason']))
        self.assertTrue(self.player.equipment_states[0].active)
        self.assertIsNone(self.actions.equipment_pending)

    def test_reentrant_manual_equipment_does_not_replace_the_returned_intent_identity(self):
        self.equipment([equipment_fixture.governor()])
        entered = [False]
        def report(*unused):
            if not entered[0]:
                entered[0] = True
                self.owner._activate_equipment_intent(12)
                self.restore_equipment()
        self.owner._report_critical_presentation = report
        receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': True})
        self.assertEqual(('failed', 'equipment_receipt_superseded'), (receipt['status'], receipt['reason']))
        self.assertEqual(1, receipt['result']['intent_seq'])
        self.assertEqual(2, self.owner.client._equipment_intent_seq)
        self.assertEqual(2, receipt['result']['canonical_result']['intent_seq'])

    def test_sequence_boolean_or_submission_failure_cannot_impersonate_a_receipt(self):
        for sequence in (True, False, None, 0):
            with self.subTest(sequence=sequence):
                self.equipment([equipment_fixture.governor()])
                self.owner._activate_equipment_intent = lambda unused: sequence
                receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': True})
                self.assertEqual(('failed', 'equipment_submission_failed'), (receipt['status'], receipt['reason']))

    def test_automatic_consumables_conflict_and_no_command_id_mutation_are_rejected(self):
        self.equipment([equipment_fixture.governor()])
        self.control.active, self.control.features = True, frozenset(('consumables',))
        receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': True})
        self.assertEqual('automatic_consumables_active', receipt['reason'])
        self.control.active = False
        self.assertEqual('command_id_required', self.actions.preflight(
            {'id': None, 'action': 'use_equipment', 'args': {'equipment_id': 12, 'active': True}}))
        self.assertEqual([], self.sent)

    def test_identity_change_and_timeout_have_bounded_terminal_results(self):
        for change in ('identity', 'deadline', 'dead', 'close'):
            with self.subTest(change=change):
                self.identity['round_id'], self.alive[0], self.now[0] = 1, True, 30.
                self.equipment([equipment_fixture.governor()])
                self.submit('use_equipment', {'equipment_id': 12, 'active': True}, timeout=1.)
                if change == 'identity':
                    self.identity['round_id'] = '1'
                elif change == 'dead':
                    self.alive[0] = False
                elif change == 'close':
                    self.actions.close()
                self.observe(1. if change == 'deadline' else 0.)
                self.assertIn(self.receipt()['status'], ('failed', 'cancelled'))
                self.assertIsNone(self.actions.equipment_pending)
                self.assertTrue(self.player.equipment_states[0].active)

    def test_gateway_timeout_status_is_not_relabelled_as_cancellation_in_snapshot(self):
        self.equipment([equipment_fixture.governor()])
        self.submit('use_equipment', {'equipment_id': 12, 'active': True}, timeout=1.)
        self.now[0] += 1.
        self.control.gateway.tick(self.now[0])
        self.assertEqual('failed', self.receipt()['status'])
        self.assertEqual('failed', self.actions.snapshot()['equipment']['last']['status'])

    def test_status_lists_only_real_descriptor_targets_and_is_json_bounded(self):
        self.equipment([equipment_fixture.medkit(), equipment_fixture.governor(),
                        equipment_fixture.item('smallRepairkit', 4, tags=('repairkit',))])
        status = self.actions.snapshot()
        stock = {row['equipment_id']: row for row in status['equipment']['stock']}
        self.assertEqual(['commander', 'loader1'], stock[2]['targets'])
        self.assertEqual(['engineHealth'], stock[4]['targets'])
        self.assertEqual([], stock[12]['targets'])
        self.assertTrue(status['equipment']['available'])
        self.assertLess(len(json.dumps(status)), 2048)

    def test_partial_startup_snapshot_does_not_need_entity_resolver_or_clock(self):
        self.bind(types.SimpleNamespace(_server=types.SimpleNamespace(vehicle_id=10),
            _equipment_state=[], _records={}, _last_snapshot=None))
        del self.owner._clock
        status = self.actions.snapshot()
        self.assertFalse(status['equipment']['available'])
        self.assertFalse(status['siege']['available'])
        self.assertEqual([], status['equipment']['stock'])

    def test_equipment_selection_reentry_is_fenced_before_any_real_activation(self):
        for change in ('timeout', 'stop', 'round', 'owner', 'entity', 'death'):
            for getter_call in (1, 2):
                with self.subTest(change=change, getter_call=getter_call):
                    self.identity['round_id'], self.now[0], self.alive[0] = 1, 30., True
                    self.equipment([equipment_fixture.governor()])
                    entered = self.interrupt_selection('use_equipment', change, getter_call)
                    receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': True}, timeout=1.)
                    self.assertGreaterEqual(entered[0], getter_call)
                    self.assertIn(receipt['status'], ('failed', 'cancelled'))
                    self.assertEqual([], self.sent)
                    self.assertFalse(self.player.equipment_states[0].active)
                    self.assertIsNone(self.actions.equipment_pending)

    def test_equipment_preflight_native_lookup_cannot_survive_stop_round_or_timeout(self):
        for change, reason in (('stop', 'controller_stopped'), ('round', 'identity_changed'),
                               ('timeout', 'command_timeout')):
            with self.subTest(change=change):
                self.identity['round_id'], self.now[0] = 1, 30.
                self.equipment([equipment_fixture.governor()])
                original = self.owner._server_entity
                def resolve(vehicle_id):
                    entity = original(vehicle_id)
                    if change == 'stop':
                        self.actions.stop('manual', self.now[0])
                    elif change == 'round':
                        self.identity['round_id'] = 2
                    else:
                        self.now[0] += 2.
                    return entity
                self.owner._server_entity = resolve
                receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': True}, timeout=1.)
                self.assertEqual(('rejected', reason), (receipt['status'], receipt['reason']))
                self.assertEqual([], self.sent)

    def test_acceptance_publication_cannot_rebind_equipment_to_a_new_round_or_after_stop(self):
        for change in ('round', 'stop', 'timeout', 'owner'):
            with self.subTest(change=change):
                self.identity['round_id'], self.now[0] = 1, 30.
                self.equipment([equipment_fixture.governor()])
                original = self.control.gateway.emit
                def emit(row):
                    if row['status'] == 'accepted':
                        if change == 'round':
                            self.identity['round_id'] = self.owner.client.round_id = self.battle.round_id = 2
                            self.owner._last_snapshot['round_id'] = 2
                        elif change == 'stop':
                            self.actions.stop('manual', self.now[0])
                        elif change == 'owner':
                            self.control.owner = types.SimpleNamespace(_clock=lambda: self.now[0])
                        else:
                            self.now[0] += 2.
                    return original(row)
                self.control.gateway.emit = emit
                receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': True}, timeout=1.)
                self.assertIn(receipt['status'], ('failed', 'cancelled'))
                self.assertEqual(1, receipt['round_id'])
                self.assertEqual([], self.sent)
                self.assertFalse(self.player.equipment_states[0].active)

    def test_equipment_preparation_is_visible_to_stop_and_same_channel_reentry(self):
        self.equipment([equipment_fixture.governor()])
        original = self.owner._server_entity
        observations = []
        def resolve(vehicle_id):
            operation = self.actions.equipment_pending
            if operation is not None and operation['phase'] == 'preparing' and not observations:
                observations.append('entered')
                self.actions.update(self.now[0])
                observations.append(self.actions.snapshot()['equipment']['pending']['phase'])
                observations.append(self.submit('use_equipment',
                    {'equipment_id': 12, 'active': True}, 'nested')['reason'])
            return original(vehicle_id)
        self.owner._server_entity = resolve
        self.assertEqual('accepted', self.submit('use_equipment', {'equipment_id': 12, 'active': True})['status'])
        self.assertEqual(['entered', 'preparing', 'equipment_operation_busy'], observations)
        self.assertEqual(1, len(self.sent))

    def test_unicode_native_error_is_a_bounded_failure_not_an_error_in_error_handling(self):
        self.equipment([equipment_fixture.governor()])
        self.owner._activate_equipment_intent = mock.Mock(side_effect=RuntimeError('\u539f\u751f\u9519\u8bef'))
        receipt = self.submit('use_equipment', {'equipment_id': 12, 'active': True})
        self.assertEqual(('failed', 'native_setting_error'), (receipt['status'], receipt['reason']))
        self.assertLessEqual(len(receipt['result']['error']), 160)
        self.assertEqual([], self.sent)


class SiegeCommandTests(NativeActionHarness):
    def siege(self, current=0, speed=0., turn=0., vehicle='sweden:S22_Strv_S1'):
        import test_port_0922_siege_braking as fixture
        import test_port_0922_server_projectiles as server_fixture
        owner, entity = fixture.local_battle(vehicle, current, speed, turn)
        authority = server_fixture._state(players=1)
        player = authority.players[1]
        player.vehicle, player.participating, player.siege_state = vehicle, True, current
        authority._freeze_round_participants([player])
        player.speed = speed
        client = lan_client.LANClient('127.0.0.1', 28782, 'SiegeAction', vehicle)
        client.ready, client.phase, client.player_id, client.round_id = True, 'battle', 1, 1
        client.team, client.server_capabilities = 1, server_fixture.SERVER_CAPABILITIES
        client.capabilities = player.capabilities
        self.sent = []
        def send(message):
            self.sent.append(copy.deepcopy(message))
            return authority.update_input(1, message)
        client._send = send
        owner.client = client
        owner._estimated_motion_time_us = lambda unused: authority._logical_motion_time_us()
        owner._gun_state = types.SimpleNamespace(shot_index=0, pending_index=None,
            reload_time=0., reload_duration=5., clip=1, clip_size=1, dispersion=.02,
            adopt_descriptor=mock.Mock(return_value=True))
        owner._records = {'player:1': dict(local=True, engine_id=10, state={}, presented_siege_state=current)}
        # The boundary fixture records actual callback delivery. Body rendering
        # remains native-only, while the request, transition and echo are real.
        owner._binding = types.SimpleNamespace(update_vehicle_siege_state=mock.Mock(
            side_effect=lambda unused_id, state, unused_time: setattr(entity, 'siegeState', state)))
        owner._report_local_siege_edge = mock.Mock()
        self.entity, self.authority, self.player = entity, authority, player
        self.bind(owner)
        self.restore_siege()
        return owner

    def restore_siege(self, present=True):
        row = self.authority._public_player(self.player)
        self.owner._last_snapshot = dict(round_id=1, players=[row])
        record = self.owner._records['player:1']
        record['state'] = copy.deepcopy(row)
        if present:
            self.owner._apply_siege_state(record, row)

    def settle_siege(self):
        for unused in range(self.player.siege_transition_ticks):
            self.authority._advance_siege_states()

    def test_real_native_sender_authority_transition_and_stable_echo_complete_both_modes(self):
        for current in (siege_mechanics.DISABLED, siege_mechanics.ENABLED):
            with self.subTest(current=current):
                self.siege(current=current)
                enabled = current == siege_mechanics.DISABLED
                self.assertEqual('accepted', self.submit('set_siege', {'enabled': enabled})['status'])
                sequence = self.actions.siege_pending['request_seq']
                self.assertEqual(1, sequence)
                self.assertEqual(enabled, self.sent[0]['siege_enabled'])
                self.assertEqual((0., 0., 0.), (self.sent[0]['forward'], self.sent[0]['turn'], self.sent[0]['speed']))
                self.assertEqual(siege_mechanics.SWITCHING_ON if enabled else siege_mechanics.SWITCHING_OFF,
                                 self.player.siege_state)
                self.restore_siege()
                self.observe()
                self.assertEqual('accepted', self.receipt()['status'])
                self.assertIsNotNone(self.owner._local_siege_pending)
                self.settle_siege()
                self.restore_siege(present=False)
                self.observe()
                self.assertEqual('accepted', self.receipt()['status'])
                self.restore_siege()
                self.observe()
                self.assertEqual(('completed', 'siege_stable'), (self.receipt()['status'], self.receipt()['reason']))
                self.assertEqual(sequence, self.receipt()['result']['request_seq'])
                self.assertEqual(self.player.siege_state, self.entity.siegeState)
                self.assertIsNone(self.owner._local_siege_pending)

    def test_real_braking_requests_only_after_body_motion_stops(self):
        self.siege(speed=8., turn=.5)
        self.assertEqual('accepted', self.submit('set_siege', {'enabled': True})['status'])
        self.assertEqual('braking', self.actions.siege_pending['phase'])
        self.assertIsNone(self.actions.siege_pending['request_seq'])
        self.assertEqual([], self.sent)
        self.assertEqual(8., self.owner._local_speed)
        for unused in range(120):
            self.now[0] += .04
            self.authority.tick += 1
            self.owner._drive_local(.04)
            self.observe()
            if self.actions.siege_pending['request_seq'] is not None:
                break
        self.assertEqual(0., self.owner._local_speed)
        self.assertIsNotNone(self.actions.siege_pending['request_seq'])
        self.assertEqual(1, sum('siege_enabled' in row for row in self.sent))
        self.settle_siege()
        self.restore_siege()
        self.observe()
        self.assertEqual('completed', self.receipt()['status'])

    def test_cancelling_unsent_braking_only_retires_its_own_token(self):
        self.siege(speed=8.)
        self.submit('set_siege', {'enabled': True})
        callback = self.actions.siege_pending['on_submitted']
        self.assertFalse(self.owner._cancel_player_control_siege(lambda *unused: None))
        self.assertIsNotNone(self.owner._local_siege_braking)
        self.actions.stop('manual', self.now[0])
        self.assertIsNone(self.owner._local_siege_braking)
        self.assertIsNone(self.owner._local_siege_pending)
        self.assertEqual(8., self.owner._local_speed)
        callback(1, True)
        self.assertEqual('cancelled', self.receipt()['status'])
        self.assertEqual([], self.sent)

    def test_cancel_failure_retains_a_bounded_release_obligation_and_blocks_new_mode(self):
        self.siege(speed=8.)
        self.submit('set_siege', {'enabled': True})
        original = self.owner._cancel_player_control_siege
        self.owner._cancel_player_control_siege = mock.Mock(side_effect=RuntimeError('native busy'))
        self.actions.stop('manual', self.now[0])
        self.assertEqual('cancelled', self.receipt()['status'])
        self.assertTrue(self.owner._local_siege_braking)
        self.assertEqual('releasing', self.actions.siege_pending['phase'])
        self.assertTrue(self.actions.busy)
        self.assertEqual(1, len(self.control.release_pending))
        self.assertEqual('native_siege_release', self.control.release_pending[0][0])
        for unused in range(5):
            self.actions.stop('manual', self.now[0])
            self.observe()
        self.assertEqual(1, self.owner._cancel_player_control_siege.call_count)
        self.assertEqual('siege_operation_busy', self.submit('set_siege', {'enabled': False}, 'two')['reason'])
        self.owner._cancel_player_control_siege = original
        self.control.release_pending[0][1]()
        self.assertIsNone(self.actions.siege_pending)
        self.assertIsNone(self.owner._local_siege_braking)
        self.assertFalse(self.actions.busy)
        self.assertEqual([], self.control.release_pending)

    def test_cancel_retry_cannot_undo_new_manual_owner_or_a_committed_transition(self):
        for replace in (False, True):
            with self.subTest(replace=replace):
                self.siege(speed=8. if replace else 0.)
                self.submit('set_siege', {'enabled': True})
                native_pending = self.owner._local_siege_pending
                original = self.owner._cancel_player_control_siege
                self.owner._cancel_player_control_siege = mock.Mock(side_effect=RuntimeError('busy'))
                self.actions.stop('manual', self.now[0])
                if replace:
                    self.owner.change_vehicle_setting(
                        self.owner._runtime.constants.VEHICLE_SETTING.SIEGE_MODE_ENABLED, 1)
                self.owner._cancel_player_control_siege = original
                self.actions.release_siege()
                if replace:
                    self.assertTrue(self.owner._local_siege_braking)
                else:
                    self.assertEqual(native_pending, self.owner._local_siege_pending)
                    self.assertEqual(siege_mechanics.SWITCHING_ON, self.player.siege_state)
                self.assertIsNone(self.actions.siege_pending)

    def test_cancel_after_submission_preserves_the_real_transition_and_native_pending(self):
        self.siege()
        self.submit('set_siege', {'enabled': True})
        pending = self.owner._local_siege_pending
        self.actions.stop('manual', self.now[0])
        self.assertEqual(pending, self.owner._local_siege_pending)
        self.assertEqual(siege_mechanics.SWITCHING_ON, self.player.siege_state)
        self.settle_siege()
        self.restore_siege()
        self.observe()
        self.assertEqual('cancelled', self.receipt()['status'])
        self.assertEqual(siege_mechanics.ENABLED, self.entity.siegeState)

    def test_synchronous_stop_during_send_does_not_cancel_the_committed_transition(self):
        self.siege()
        original = self.owner.client._send
        def send(message):
            accepted = original(message)
            self.actions.stop('manual', self.now[0])
            return accepted
        self.owner.client._send = send
        self.assertEqual('cancelled', self.submit('set_siege', {'enabled': True})['status'])
        self.assertEqual((True, 1), self.owner._local_siege_pending)
        self.assertEqual(siege_mechanics.SWITCHING_ON, self.player.siege_state)

    def test_sender_post_send_reentry_keeps_exact_siege_request_sequence(self):
        self.siege()
        original = self.owner._ram_contacts_enqueued
        entered = [False]
        def enqueued():
            original()
            if not entered[0]:
                entered[0] = True
                self.assertTrue(self.owner._sender.send_current())
        self.owner._ram_contacts_enqueued = enqueued
        receipt = self.submit('set_siege', {'enabled': True})
        self.assertEqual('accepted', receipt['status'])
        self.assertEqual([1, 2], [row['input_seq'] for row in self.sent])
        self.assertEqual(2, self.owner.client._input_seq)
        self.assertEqual(1, self.actions.siege_pending['request_seq'])
        self.assertEqual((True, 1), self.owner._local_siege_pending)
        self.settle_siege()
        self.restore_siege()
        self.observe()
        self.assertEqual('completed', self.receipt()['status'])
        self.assertEqual(1, self.receipt()['result']['request_seq'])
        self.assertEqual(2, self.receipt()['result']['input_seq'])

    def test_server_rejection_requires_our_input_echo_and_reports_failure(self):
        self.siege()
        # Not yet visible in the foreground entity, so this tests the actual
        # server verdict rather than only an admission guard.
        self.player.critical = {'destroyed': ['engineHealth']}
        self.submit('set_siege', {'enabled': True})
        self.observe()
        self.assertEqual('accepted', self.receipt()['status'])
        self.restore_siege()
        self.observe()
        self.assertEqual(('failed', 'siege_rejected'), (self.receipt()['status'], self.receipt()['reason']))
        self.assertEqual(1, self.receipt()['result']['request_seq'])

    def test_already_set_is_noop_only_with_a_current_stable_presented_canonical_state(self):
        self.siege()
        receipt = self.submit('set_siege', {'enabled': False})
        self.assertEqual(('completed', 'siege_already_set'), (receipt['status'], receipt['reason']))
        self.assertEqual([], self.sent)
        self.owner._last_snapshot['round_id'] = 2
        receipt = self.submit('set_siege', {'enabled': False}, 'stale')
        self.assertEqual(('rejected', 'siege_state_unavailable'), (receipt['status'], receipt['reason']))

    def test_existing_manual_brake_pending_or_transition_is_never_adopted(self):
        for current in ('brake', 'pending', 'transition'):
            with self.subTest(current=current):
                self.siege()
                if current == 'brake':
                    self.owner._local_siege_braking = True
                elif current == 'pending':
                    self.owner._local_siege_pending = (True, 4)
                else:
                    self.entity.siegeState = siege_mechanics.SWITCHING_ON
                receipt = self.submit('set_siege', {'enabled': True})
                self.assertEqual(('rejected', 'siege_native_busy'), (receipt['status'], receipt['reason']))
                self.assertEqual([], self.sent)

    def test_manual_siege_is_blocked_only_while_automatic_drive_owns_it(self):
        self.siege()
        setting = self.owner._runtime.constants.VEHICLE_SETTING.SIEGE_MODE_ENABLED
        self.control.features = frozenset(('drive',))
        self.control.active = True
        self.assertFalse(self.owner.change_vehicle_setting(setting, 1))
        self.assertEqual([], self.sent)
        self.control.active = False
        self.assertTrue(self.owner.change_vehicle_setting(setting, 1))
        self.assertEqual(1, len(self.sent))

    def test_manual_replacement_cancels_previous_observer_without_cancelling_new_brake(self):
        self.siege(speed=8.)
        self.submit('set_siege', {'enabled': True})
        old_callback = self.actions.siege_pending['on_submitted']
        # Identical bool state is still a different native request owner.
        setting = self.owner._runtime.constants.VEHICLE_SETTING.SIEGE_MODE_ENABLED
        self.assertTrue(self.owner.change_vehicle_setting(setting, 1))
        self.assertEqual(('cancelled', 'siege_replaced'), (self.receipt()['status'], self.receipt()['reason']))
        self.assertTrue(self.owner._local_siege_braking)
        old_callback(1, True)
        self.assertEqual('cancelled', self.receipt()['status'])
        self.assertTrue(self.owner._local_siege_braking)

    def test_siege_conflicts_with_automatic_drive_or_timed_drive_but_allows_halt(self):
        for mode in ('automatic', 'timed', 'halt'):
            with self.subTest(mode=mode):
                self.siege()
                self.control.active = mode == 'automatic'
                self.control.features = frozenset(('drive',))
                self.control.override = {'id': 'drive'} if mode == 'timed' else None
                self.control.halted = mode == 'halt'
                receipt = self.submit('set_siege', {'enabled': True})
                self.assertEqual('accepted' if mode == 'halt' else 'rejected', receipt['status'])
                if mode != 'halt':
                    self.assertEqual([], self.sent)

    def test_deadline_during_synchronous_completion_never_becomes_success(self):
        self.siege()
        original = self.owner.client._send
        def send(message):
            accepted = original(message)
            self.settle_siege()
            self.restore_siege()
            self.now[0] += 1.
            return accepted
        self.owner.client._send = send
        receipt = self.submit('set_siege', {'enabled': True}, timeout=1.)
        self.assertEqual(('failed', 'command_timeout'), (receipt['status'], receipt['reason']))
        self.assertEqual(siege_mechanics.ENABLED, self.player.siege_state)
        self.assertEqual(31., receipt['time'])

    def test_synchronous_stable_echo_completes_only_after_exact_submission_is_known(self):
        self.siege()
        original = self.owner.client._send
        observations = []
        def send(message):
            accepted = original(message)
            self.settle_siege()
            self.restore_siege()
            self.actions.update(self.now[0])
            observations.append(self.receipt()['status'])
            return accepted
        self.owner.client._send = send
        receipt = self.submit('set_siege', {'enabled': True})
        self.assertEqual(['accepted'], observations)
        self.assertEqual(('completed', 'siege_stable'), (receipt['status'], receipt['reason']))
        self.assertEqual(1, receipt['result']['request_seq'])

    def test_descriptor_adoption_reentry_cannot_finish_before_native_transaction_returns(self):
        self.siege()
        self.submit('set_siege', {'enabled': True})
        self.restore_siege()
        self.settle_siege()
        observations = []
        def adopt(unused_descriptor):
            self.actions.update(self.now[0])
            observations.append(self.receipt()['status'])
            return True
        self.owner._gun_state.adopt_descriptor.side_effect = adopt
        self.restore_siege()
        self.assertEqual(['accepted'], observations)
        self.observe()
        self.assertEqual('completed', self.receipt()['status'])

    def test_failed_descriptor_adoption_is_not_presented_as_stable_completion(self):
        self.siege()
        self.submit('set_siege', {'enabled': True})
        self.restore_siege()
        self.settle_siege()
        self.owner._gun_state.adopt_descriptor.side_effect = RuntimeError('descriptor failed')
        with self.assertRaisesRegex(RuntimeError, 'descriptor failed'):
            self.restore_siege()
        self.observe()
        self.assertEqual('accepted', self.receipt()['status'])
        self.assertFalse(self.actions.snapshot()['siege']['presented'])
        self.owner._gun_state.adopt_descriptor.side_effect = None
        self.restore_siege()
        self.observe()
        self.assertEqual('completed', self.receipt()['status'])

    def test_rejected_or_mismatched_submission_callbacks_are_terminal(self):
        for sequence, enabled, reason, expected in (
                (None, True, 'siege_not_submitted', 'siege_not_submitted'),
                (True, True, None, 'siege_request_sequence_invalid'),
                (1, False, None, 'siege_request_sequence_invalid')):
            with self.subTest(sequence=sequence, enabled=enabled, reason=reason):
                self.siege(speed=8.)
                self.submit('set_siege', {'enabled': True})
                callback = self.actions.siege_pending['on_submitted']
                callback(sequence, enabled, reason)
                self.assertEqual(('failed', expected), (self.receipt()['status'], self.receipt()['reason']))
                self.assertIsNone(self.owner._local_siege_braking)
                self.assertEqual([], self.sent)

    def test_braking_timeout_releases_only_owned_unsent_request(self):
        self.siege(speed=8.)
        self.submit('set_siege', {'enabled': True}, timeout=1.)
        self.observe(1.)
        self.assertEqual(('failed', 'command_timeout'), (self.receipt()['status'], self.receipt()['reason']))
        self.assertIsNone(self.owner._local_siege_braking)
        self.assertEqual(8., self.owner._local_speed)
        self.assertEqual([], self.sent)

    def test_snapshot_is_not_completion_without_the_submitted_input_frontier(self):
        self.siege()
        self.submit('set_siege', {'enabled': True})
        self.settle_siege()
        self.restore_siege()
        self.owner._last_snapshot['players'][0]['input_seq'] = 0
        self.observe()
        self.assertEqual('accepted', self.receipt()['status'])
        self.owner._last_snapshot['players'][0]['input_seq'] = 1
        self.observe()
        self.assertEqual('completed', self.receipt()['status'])

    def test_siege_selection_reentry_cannot_install_a_brake_or_send_after_cancellation(self):
        for change in ('timeout', 'stop', 'round', 'owner', 'entity', 'death'):
            for getter_call in (1, 2, 3):
                with self.subTest(change=change, getter_call=getter_call):
                    self.identity['round_id'], self.now[0], self.alive[0] = 1, 30., True
                    self.siege()
                    entered = self.interrupt_selection('set_siege', change, getter_call)
                    receipt = self.submit('set_siege', {'enabled': True}, timeout=1.)
                    self.assertGreaterEqual(entered[0], getter_call)
                    self.assertIn(receipt['status'], ('failed', 'cancelled'))
                    self.assertEqual([], self.sent)
                    self.assertIsNone(self.owner._local_siege_braking)
                    self.assertIsNone(self.owner._local_siege_pending)
                    self.assertEqual(siege_mechanics.DISABLED, self.player.siege_state)
                    self.assertIsNone(self.actions.siege_pending)

    def test_siege_acceptance_publication_respects_stop_and_original_round_identity(self):
        for change in ('stop', 'round'):
            with self.subTest(change=change):
                self.identity['round_id'], self.now[0] = 1, 30.
                self.siege(speed=8.)
                original = self.control.gateway.emit
                def emit(row):
                    if row['status'] == 'accepted':
                        if change == 'stop':
                            self.actions.stop('manual', self.now[0])
                        else:
                            self.identity['round_id'] = self.owner.client.round_id = self.authority.round_id = 2
                            self.owner._last_snapshot['round_id'] = 2
                    return original(row)
                self.control.gateway.emit = emit
                receipt = self.submit('set_siege', {'enabled': True})
                self.assertEqual('cancelled', receipt['status'])
                self.assertEqual([], self.sent)
                self.assertIsNone(self.owner._local_siege_braking)
                self.assertIsNone(self.owner._local_siege_pending)
                self.assertEqual(8., self.owner._local_speed)

    def test_unicode_cleanup_error_keeps_retry_obligation(self):
        self.siege(speed=8.)
        self.submit('set_siege', {'enabled': True})
        self.owner._cancel_player_control_siege = mock.Mock(side_effect=RuntimeError('\u539f\u751f\u6e05\u7406\u5931\u8d25'))
        self.actions.stop('manual', self.now[0])
        self.assertEqual('releasing', self.actions.siege_pending['phase'])
        self.assertEqual(1, len(self.control.release_pending))
        self.assertEqual('cancelled', self.receipt()['status'])


if __name__ == '__main__':
    unittest.main()
