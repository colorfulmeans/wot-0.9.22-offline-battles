"""Observable identity, framing, and acknowledgement boundaries for test controls."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

import player_control_transport as transport_schema
from player_control_transport import PlayerControlTransport


class PlayerControlTransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.command_path = os.path.join(self.directory.name, 'commands.jsonl')
        self.result_path = os.path.join(self.directory.name, 'results.jsonl')
        for path in (self.command_path, self.result_path):
            with open(path, 'wb'):
                pass
        self.now = 100.0
        self.wall_now = time.time()
        self.transport = PlayerControlTransport(self.command_path, self.result_path,
            'session-a', clock=lambda: self.now, wall_clock=lambda: self.wall_now)

    @staticmethod
    def client_module(name):
        module_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
            'src', 'res', 'scripts', 'client', 'gui', 'mods', 'offline_lan_0922',
            'player_control', name + '.py'))
        spec = importlib.util.spec_from_file_location('player_control_contract_' + name, module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def status(self, **overrides):
        result = dict(type='status', session_id='session-a', round_id='round-a',
                      player_id=101, live=True, active=False,
                      features=['drive', 'fire'], mission={}, ammo={}, aim={})
        result.update(overrides)
        return result

    def append(self, *records):
        with open(self.result_path, 'ab') as stream:
            for record in records:
                stream.write((json.dumps(record, ensure_ascii=False) + '\n').encode('utf8'))

    def commands(self):
        with open(self.command_path, encoding='utf8') as stream:
            return [json.loads(line) for line in stream]

    def receipt(self, command, status, **overrides):
        result = dict(command, type='command', status=status, reason='')
        result.update(overrides)
        return result

    def shot(self, command, projectile_id, status='committed', event_seq=1, **overrides):
        result = dict(type='shot', session_id=command['session_id'], round_id=command['round_id'],
            player_id=command['player_id'], command_id=command.get('id'), projectile_id=projectile_id,
            status=status, event_seq=event_seq, time=self.now, damage_total=0., hit_count=0,
            penetrated=False, terminal_observed=status == 'terminal', combat_observed=status == 'hit',
            flight_status=status if status != 'hit' else 'committed')
        result.update(overrides)
        return result

    def test_only_current_live_identity_can_submit_and_submission_is_not_completion(self):
        self.assertIsNone(self.transport.send('start'))
        self.append(self.status(session_id='another-session'))
        self.assertIsNone(self.transport.send('start'))
        self.append(self.status(live=False, reason='dead'))
        self.assertIsNone(self.transport.send('start'))
        self.assertEqual([], self.commands())
        self.append(self.status())
        command_id = self.transport.send('drive', {'seconds': 1, 'forward': 1}, 15)
        command = self.commands()[0]
        self.assertEqual(command_id, command['id'])
        self.assertEqual(('session-a', 'round-a', 101),
                         (command['session_id'], command['round_id'], command['player_id']))
        self.assertEqual({'seconds': 1, 'forward': 1}, command['args'])
        self.assertTrue(command['replace'])
        self.assertEqual('submitted', self.transport.last_result['status'])

    def test_next_battle_supplies_a_new_identity_and_unique_request(self):
        self.append(self.status())
        first = self.transport.send('start')
        self.append(self.status(round_id='round-b', player_id=202))
        second = self.transport.send('stop')
        self.assertNotEqual(first, second)
        self.assertEqual(('round-b', 202),
                         (self.commands()[1]['round_id'], self.commands()[1]['player_id']))

    def test_missing_live_flag_or_invalid_identity_cannot_enable_commands(self):
        for overrides in ({'live': 'true'}, {'round_id': None}, {'player_id': 0}, {'player_id': True}):
            with self.subTest(overrides=overrides):
                self.append(self.status(**overrides))
                self.assertIsNone(self.transport.send('fire'))
        self.assertEqual([], self.commands())

    def test_receipts_require_matching_identity_and_terminal_state_never_regresses(self):
        self.append(self.status())
        command_id = self.transport.send('fire')
        command = self.commands()[0]
        self.append(self.receipt(command, 'completed', session_id='foreign'),
                    self.receipt(command, 'completed', round_id='old-round'),
                    self.receipt(command, 'completed', player_id=999))
        self.transport.poll()
        self.assertEqual('submitted', self.transport.last_result['status'])
        self.append(self.receipt(command, 'accepted'))
        self.transport.poll()
        self.assertEqual('accepted', self.transport.results[command_id]['status'])
        completed = self.receipt(command, 'completed', reason='shot_fired')
        self.append(completed, self.receipt(command, 'accepted'))
        self.transport.poll()
        self.assertEqual('completed', self.transport.last_result['status'])
        self.assertEqual('shot_fired', self.transport.last_result['reason'])

    def test_incomplete_utf8_tail_is_retried_without_being_consumed(self):
        record = self.status(mission={'phase': '等待'})
        encoded = json.dumps(record, ensure_ascii=False).encode('utf8')
        split = encoded.index('等待'.encode('utf8')) + 1
        with open(self.result_path, 'ab') as stream:
            stream.write(encoded[:split])
        self.transport.poll()
        self.assertIsNone(self.transport.status)
        self.assertEqual(0, self.transport.offset)
        with open(self.result_path, 'ab') as stream:
            stream.write(encoded[split:] + b'\n')
        self.transport.poll()
        self.assertEqual('等待', self.transport.status['mission']['phase'])
        offset = self.transport.offset
        self.transport.poll()
        self.assertEqual(offset, self.transport.offset)

    def test_overlong_and_malformed_records_do_not_block_the_next_valid_status(self):
        self.append(self.status())
        self.transport.send('start')  # Keep a pending request so the normal reader handles the oversized row.
        with open(self.result_path, 'ab') as stream:
            stream.write(b'x' * (self.transport.MAX_LINE_BYTES * 2 + 1) + b'\n{broken}\n')
        self.append(self.status(round_id='round-b', player_id=202))
        self.transport.poll()
        self.assertEqual('round-b', self.transport.status['round_id'])
        self.assertTrue(self.transport.live)
        self.assertEqual(os.path.getsize(self.result_path), self.transport.offset)

    def test_oversized_unterminated_record_can_finish_later_without_poisoning_reader(self):
        with open(self.result_path, 'ab') as stream:
            stream.write(b'x' * (self.transport.MAX_LINE_BYTES + 2))
        self.transport.poll()
        with open(self.result_path, 'ab') as stream:
            stream.write(b'\n')
        self.append(self.status())
        self.transport.poll()
        self.assertTrue(self.transport.live)

    def test_stale_or_dead_status_blocks_actions_and_new_heartbeat_restores_them(self):
        self.append(self.status())
        self.transport.poll()
        self.now += 6
        self.assertIsNone(self.transport.send('fire'))
        self.assertEqual('status_stale', self.transport.error)
        self.append(self.status())
        self.assertIsNotNone(self.transport.send('fire'))
        self.append(self.status(live=False, reason='dead'))
        self.assertIsNone(self.transport.send('start'))
        self.assertEqual('dead', self.transport.error)

    def test_reading_an_old_file_does_not_make_a_stopped_client_live(self):
        self.append(self.status())
        timestamp = time.time() - 30
        os.utime(self.result_path, (timestamp, timestamp))
        self.transport.poll()
        self.assertFalse(self.transport.live)
        self.assertEqual('status_stale', self.transport.unavailable_reason())

    def test_late_panel_reads_latest_battle_without_replaying_old_commands(self):
        self.append(*(self.status(round_id='old', ammo={'padding': 'x' * 500}) for _ in range(150)))
        self.append(self.status(round_id='current', player_id=202))
        self.transport.poll()
        self.assertTrue(self.transport.live)
        self.assertEqual('current', self.transport.status['round_id'])
        self.assertEqual([], self.commands())

    def test_file_truncation_invalidates_the_old_snapshot(self):
        self.append(self.status())
        self.transport.poll()
        with open(self.result_path, 'wb'):
            pass
        self.transport.poll()
        self.assertFalse(self.transport.live)
        self.append(self.status(round_id='new-round', player_id=202))
        self.assertIsNotNone(self.transport.send('stop'))
        self.assertEqual('new-round', self.commands()[0]['round_id'])

    def test_missing_terminal_receipt_is_unconfirmed_and_late_actual_receipt_can_resolve_it(self):
        self.append(self.status())
        self.transport.send('fire', timeout_seconds=2)
        command = self.commands()[0]
        self.append(self.receipt(command, 'accepted'))
        self.transport.poll()
        self.now += 7
        self.transport.poll()
        self.assertEqual('unconfirmed', self.transport.last_result['status'])
        self.append(self.receipt(command, 'completed'))
        self.transport.poll()
        self.assertEqual('completed', self.transport.last_result['status'])

    def test_status_snapshot_can_recover_a_matching_terminal_receipt(self):
        self.append(self.status())
        command_id = self.transport.send('fire')
        self.append(self.status(last_command=dict(id=command_id, action='fire', status='failed', reason='no_ammo')))
        self.transport.poll()
        self.assertEqual('failed', self.transport.last_result['status'])
        self.assertEqual('no_ammo', self.transport.last_result['reason'])

    def test_write_failure_does_not_create_a_success_or_pending_receipt(self):
        self.append(self.status())
        self.transport.command_path = self.directory.name
        self.assertIsNone(self.transport.send('fire'))
        self.assertEqual('command_write_failed', self.transport.error)
        self.assertIsNone(self.transport.last_result)
        self.assertFalse(self.transport.requests)

    def test_nonfinite_inputs_are_rejected_before_any_write(self):
        self.append(self.status())
        self.assertIsNone(self.transport.send('drive', {'seconds': float('nan')}))
        self.assertIsNone(self.transport.send('fire', timeout_seconds=float('inf')))
        self.assertEqual([], self.commands())

    def test_replaced_result_file_cannot_reuse_a_previous_battle_snapshot(self):
        self.append(self.status())
        self.transport.poll()
        replacement = self.result_path + '.new'
        with open(replacement, 'w', encoding='utf8') as stream:
            stream.write(json.dumps(self.status(round_id='new-round', player_id=202,
                                               ammo={'padding': 'x' * 100})) + '\n')
        os.replace(replacement, self.result_path)
        self.assertIsNotNone(self.transport.send('stop'))
        self.assertEqual('new-round', self.commands()[0]['round_id'])

    def test_snapshot_does_not_smuggle_foreign_session_or_wrong_action_receipts(self):
        self.append(self.status())
        command_id = self.transport.send('fire')
        self.append(self.status(last_command=dict(id=command_id, action='fire', status='completed',
                                                 session_id='another-session')))
        self.append(self.status(last_command=dict(id=command_id, action='drive', status='completed')))
        self.transport.poll()
        self.assertEqual('submitted', self.transport.last_result['status'])

    def test_commands_fit_the_client_line_limit_and_replace_is_a_boolean(self):
        self.append(self.status())
        self.assertIsNone(self.transport.send('drive', {'padding': 'x' * 4096}))
        self.assertEqual('unknown_argument', self.transport.error)
        self.transport.MAX_COMMAND_BYTES = 32
        self.assertIsNone(self.transport.send('fire'))
        self.assertEqual('command_too_large', self.transport.error)
        self.assertIsNone(self.transport.send('fire', replace='false'))
        self.assertEqual('invalid_replace', self.transport.error)
        self.assertEqual([], self.commands())

    def test_launcher_round_trip_with_the_actual_client_gateway(self):
        commands = self.client_module('commands')
        executed = []
        identity = dict(session_id='session-a', round_id='round-a', player_id=101)
        gateway = commands.CommandGateway(lambda: identity,
            lambda row: commands.append_result(self.result_path, row),
            lambda request, now: executed.append(request), lambda request: None,
            lambda request, reason: None, wall_clock=lambda: self.wall_now)
        self.append(self.status())
        request_id = self.transport.send('drive', {'seconds': 1, 'forward': 1})
        commands.JournalReader().poll(self.command_path,
            lambda request: gateway.submit(request, self.now),
            lambda reason, offset: self.fail('Client rejected framing: ' + reason))
        self.transport.poll()
        self.assertEqual('accepted', self.transport.results[request_id]['status'])
        self.assertEqual({'seconds': 1.0, 'forward': 1.0, 'turn': 0.0}, executed[0]['args'])
        gateway.finish(request_id, 'completed', 'drive_finished', self.now + 1)
        self.transport.poll()
        self.assertEqual('completed', self.transport.results[request_id]['status'])
        self.assertEqual('drive_finished', self.transport.last_result['reason'])

    def test_older_terminal_receipt_cannot_hide_the_newest_completed_request(self):
        self.append(self.status())
        old_id = self.transport.send('drive', {'seconds': 1, 'forward': 1})
        self.transport.send('stop')
        old, new = self.commands()
        self.append(self.receipt(new, 'completed', reason='manual_control'),
                    self.receipt(old, 'cancelled', reason='replaced'))
        self.transport.poll()
        self.assertEqual('stop', self.transport.last_result['action'])
        self.assertEqual('completed', self.transport.last_result['status'])
        self.assertEqual('cancelled', self.transport.results[old_id]['status'])

    def test_stalled_client_can_receive_stop_with_last_identity_without_enabling_other_actions(self):
        self.append(self.status())
        self.transport.poll()
        self.now += 10
        for action in ('start', 'halt', 'drive', 'fire', 'attack', 'status'):
            self.assertIsNone(self.transport.send(action))
        request_id = self.transport.send('stop')
        self.assertIsNotNone(request_id)
        request = self.commands()[0]
        self.assertEqual(('session-a', 'round-a', 101, 'stop'),
            (request['session_id'], request['round_id'], request['player_id'], request['action']))
        self.assertEqual('submitted', self.transport.last_result['status'])
        # A delayed client receipt, rather than the write, proves release.
        self.append(self.receipt(request, 'accepted'), self.receipt(request, 'completed', reason='manual_control'))
        self.transport.poll()
        self.assertEqual('completed', self.transport.results[request_id]['status'])

    def test_stop_after_nonlive_status_or_partial_tail_keeps_observed_identity(self):
        self.append(self.status(live=False, reason='battle_not_live'))
        self.assertIsNotNone(self.transport.send('stop'))
        with open(self.result_path, 'ab') as stream:
            stream.write(b'{"type":"status"')
        self.assertIsNotNone(self.transport.send('stop'))
        self.assertEqual('round-a', self.commands()[-1]['round_id'])
        self.assertIsNone(self.transport.send('halt'))

    def test_stop_without_a_valid_current_session_identity_is_never_written(self):
        self.assertIsNone(self.transport.send('stop'))
        self.append(self.status(session_id='another-session'))
        self.assertIsNone(self.transport.send('stop'))
        self.append(self.status(player_id=None))
        self.assertIsNone(self.transport.send('stop'))
        self.assertEqual([], self.commands())

    def test_admission_deadline_and_response_wait_are_separate_from_execution_timeout(self):
        self.append(self.status())
        command_id = self.transport.send('drive', {'seconds': 1}, timeout_seconds=20,
                                         admission_seconds=3)
        command = self.commands()[0]
        self.assertEqual(self.wall_now + 3, command['expires_at'])
        self.assertEqual(20, command['timeout_seconds'])
        self.assertEqual(self.now + 25, self.transport.requests[command_id]['deadline'])
        self.assertIsNone(self.transport.send('fire', admission_seconds=float('nan')))
        self.assertIsNone(self.transport.send('fire', admission_seconds=True))
        self.assertIsNone(self.transport.send('fire', timeout_seconds=.01))
        self.assertEqual(1, len(self.commands()))

    def test_real_journal_rejects_sixty_second_late_admission_without_execution(self):
        commands = self.client_module('commands')
        executed = []
        identity = dict(session_id='session-a', round_id='round-a', player_id=101)
        gateway = commands.CommandGateway(lambda: identity,
            lambda row: commands.append_result(self.result_path, row),
            lambda request, now: executed.append(request), lambda request: None,
            lambda request, reason: self.fail('Unadmitted command cannot be cancelled'),
            wall_clock=lambda: self.wall_now)
        self.append(self.status())
        command_id = self.transport.send('drive', {'seconds': 1, 'forward': 1}, timeout_seconds=2)
        self.wall_now += 60
        self.now += 60
        self.transport.poll()
        self.assertEqual('unconfirmed', self.transport.results[command_id]['status'])
        reader = commands.JournalReader()
        reader.poll(self.command_path, lambda request: gateway.submit(request, self.now),
                    lambda reason, offset: self.fail(reason))
        self.transport.poll()
        self.assertEqual([], executed)
        self.assertEqual(('rejected', 'request_expired'),
            (self.transport.results[command_id]['status'], self.transport.results[command_id]['reason']))
        self.assertEqual(os.path.getsize(self.command_path), reader.offset)

    def test_delayed_stop_has_no_admission_deadline_and_real_gateway_still_releases(self):
        commands = self.client_module('commands')
        executed = []
        identity = dict(session_id='session-a', round_id='round-a', player_id=101)
        def execute(request, now):
            executed.append(request)
            return dict(status='completed', reason='manual_control')
        gateway = commands.CommandGateway(lambda: identity,
            lambda row: commands.append_result(self.result_path, row), execute,
            lambda request: None, lambda request, reason: None, wall_clock=lambda: self.wall_now)
        self.append(self.status(live=False, reason='dead'))
        command_id = self.transport.send('stop')
        self.assertNotIn('expires_at', self.commands()[0])
        self.wall_now += 600
        self.now += 600
        commands.JournalReader().poll(self.command_path,
            lambda request: gateway.submit(request, self.now), lambda reason, offset: self.fail(reason))
        self.transport.poll()
        self.assertEqual('stop', executed[0]['action'])
        self.assertEqual('completed', self.transport.results[command_id]['status'])

    def test_local_commit_receipt_is_immutable_after_late_rejection_and_duplicate_events(self):
        self.append(self.status())
        command_id = self.transport.send('fire')
        command = self.commands()[0]
        receipt = self.receipt(command, 'completed', reason='shot_committed',
            result=dict(projectile_ids=['p1', 'p2'], stage='local_committed'))
        self.append(receipt)
        self.transport.poll()
        original = json.dumps(self.transport.results[command_id], sort_keys=True)
        rejected = self.shot(command, 'p2', 'rejected', 3, reason='projectile_launch_rejected')
        self.append(rejected, rejected, self.shot(command, 'p2', 'committed', 2),
                    self.shot(command, 'p1', 'terminal', 4))
        self.transport.poll()
        self.assertEqual(original, json.dumps(self.transport.results[command_id], sort_keys=True))
        items = {item['projectile_id']: item for item in self.transport.projectile_results(command_id)}
        self.assertEqual('rejected', items['p2']['flight_status'])
        self.assertTrue(items['p2']['local_committed'])
        self.assertEqual('terminal', items['p1']['flight_status'])
        self.assertFalse(items['p1']['combat_observed'])
        self.assertEqual('completed', self.transport.last_result['status'])

    def test_burst_events_arrive_before_receipt_and_hit_after_terminal_without_double_counting(self):
        self.append(self.status())
        command_id = self.transport.send('fire')
        command = self.commands()[0]
        hit = self.shot(command, 'burst:1', 'hit', 5, damage_total=125., hit_count=2,
                        penetrated=True, terminal_observed=True, flight_status='terminal')
        self.append(hit, self.shot(command, 'burst:2', 'terminal', 4),
            self.shot(command, 'burst:1', 'terminal', 3),
            self.shot(command, 'burst:1', 'hit', 2, damage_total=100., hit_count=1), hit)
        self.transport.poll()
        self.assertEqual('submitted', self.transport.results[command_id]['status'])
        self.append(self.receipt(command, 'completed', reason='shot_committed',
            result=dict(projectile_ids=['burst:1', 'burst:2'], burst_count=2)))
        self.transport.poll()
        items = {item['projectile_id']: item for item in self.transport.projectile_results(command_id)}
        self.assertEqual(2, len(items))
        self.assertEqual((125., 2, True, True), (items['burst:1']['damage_total'],
            items['burst:1']['hit_count'], items['burst:1']['terminal_observed'],
            items['burst:1']['combat_observed']))
        self.assertEqual(5, items['burst:1']['events']['hit']['event_seq'])
        self.assertFalse(items['burst:2']['combat_observed'])

    def test_multiple_bursts_do_not_steal_each_others_identity_or_latest_command(self):
        self.append(self.status())
        first_id = self.transport.send('fire')
        second_id = self.transport.send('fire')
        first, second = self.commands()
        self.append(self.receipt(second, 'completed', reason='shot_committed',
            result={'projectile_ids': ['second:1', 'second:2']}),
            self.receipt(first, 'completed', reason='shot_committed', result={'projectile_ids': ['first:1']}),
            self.shot(first, 'first:1', 'hit', 5, damage_total=25., hit_count=1),
            self.shot(second, 'first:1', 'rejected', 6))
        self.transport.poll()
        self.assertEqual(second_id, self.transport.last_result['id'])
        self.assertEqual(second_id, self.transport.last_shot_command_id)
        self.assertEqual(2, len(self.transport.projectile_results(second_id)))
        first_result = self.transport.projectile_results(first_id)[0]
        self.assertEqual(25., first_result['damage_total'])
        self.assertNotIn('rejected', first_result['events'])

    def test_identity_fences_drop_old_round_session_player_and_wrong_command_events(self):
        self.append(self.status())
        command_id = self.transport.send('fire')
        command = self.commands()[0]
        self.append(self.receipt(command, 'completed', reason='shot_committed',
                                 result={'projectile_ids': ['p']}))
        for overrides in ({'session_id': 'foreign'}, {'round_id': 'old'}, {'player_id': 999},
                          {'player_id': True}, {'player_id': 101.0}, {'command_id': True},
                          {'command_id': 'different-command'}, {'event_seq': True}):
            self.append(dict(self.shot(command, 'p', 'rejected', 2), **overrides))
        self.transport.poll()
        self.assertEqual({}, self.transport.projectile_results(command_id)[0]['events'])
        self.append(self.status(round_id='new-round'), self.shot(command, 'p', 'terminal', 3), self.status())
        self.transport.poll()
        self.assertEqual('new-round', self.transport.status['round_id'])
        self.assertEqual([], self.transport.projectile_results())

    def test_snapshot_inherits_outer_identity_and_repairs_missing_commit_terminal_and_combat_rows(self):
        identity = self.status()
        command = dict(identity, id='late-panel', action='fire')
        snapshot = self.shot(command, 'p', 'hit', 9, damage_total=40., hit_count=1,
                             flight_status='terminal', terminal_observed=True)
        for key in ('session_id', 'round_id', 'player_id'):
            snapshot.pop(key)
        self.append(self.status(last_command=dict(id='late-panel', action='fire', status='completed',
            reason='shot_committed', result={'projectile_ids': ['p']}), shot_results=[snapshot]))
        self.transport.poll()
        self.assertEqual('completed', self.transport.results['late-panel']['status'])
        item = self.transport.projectile_results('late-panel')[0]
        self.assertTrue(item['local_committed'])
        self.assertTrue(item['terminal_observed'])
        self.assertTrue(item['combat_observed'])
        self.assertEqual(40., item['damage_total'])
        self.append(self.status(shot_results=[dict(snapshot, session_id='foreign', status='rejected'),
                                             dict(snapshot, round_id='old', status='rejected')]))
        self.transport.poll()
        self.assertEqual('terminal', self.transport.projectile_results('late-panel')[0]['flight_status'])

    def test_commandless_projectile_event_links_only_through_matching_commit_projectile_id(self):
        self.append(self.status())
        command_id = self.transport.send('fire')
        command = self.commands()[0]
        self.append(self.shot(command, 'p', 'terminal', 2, command_id=None),
            self.shot(command, 'unrelated', 'terminal', 3, command_id=None),
            self.receipt(command, 'completed', reason='shot_committed', result={'projectile_ids': ['p']}))
        self.transport.poll()
        self.assertEqual(['p'], [item['projectile_id'] for item in self.transport.projectile_results(command_id)])
        self.assertTrue(self.transport.projectile_results(command_id)[0]['terminal_observed'])

    def test_shot_tracking_is_bounded_without_modifying_local_receipts(self):
        self.transport.MAX_TRACKED = 3
        self.transport.MAX_PROJECTILES = 4
        self.append(self.status())
        command_id = self.transport.send('fire')
        command = self.commands()[0]
        self.append(self.receipt(command, 'completed', reason='shot_committed',
            result={'projectile_ids': ['p%s' % index for index in range(10)]}))
        self.transport.poll()
        self.assertEqual(4, len(self.transport.projectiles))
        self.assertEqual(4, len(self.transport.projectile_results(command_id)))
        self.assertEqual(10, len(self.transport.results[command_id]['result']['projectile_ids']))

    def test_pending_projectile_prevents_tail_seek_past_its_late_terminal(self):
        self.append(self.status())
        command_id = self.transport.send('fire')
        command = self.commands()[0]
        self.append(self.receipt(command, 'completed', reason='shot_committed', result={'projectile_ids': ['p']}))
        self.transport.poll()
        self.append(self.shot(command, 'p', 'terminal', 2),
            *(self.status(ammo={'padding': 'x' * 500}) for _ in range(150)))
        self.transport.poll()
        self.assertTrue(self.transport.projectile_results(command_id)[0]['terminal_observed'])

    def test_actual_projectile_ledger_and_gateway_round_trip_through_result_journal(self):
        commands = self.client_module('commands')
        shots = self.client_module('shot_receipts').ShotReceipts()
        identity = dict(session_id='session-a', round_id='round-a', player_id=101)
        def publish(row):
            return commands.append_result(self.result_path, dict(row, **identity))
        def execute(request, now):
            event = shots.committed({'projectile_id': 'real:p', 'shell_index': 0},
                {'burst_group_seq': 1, 'burst_count': 1}, {'command': request['id'], 'target': 202}, now, 1)
            publish(event)
            return dict(status='completed', reason='shot_committed', result=dict(
                stage='local_committed', projectile_ids=['real:p']))
        gateway = commands.CommandGateway(lambda: identity, publish, execute,
            lambda request: None, lambda request, reason: None, wall_clock=lambda: self.wall_now)
        self.append(self.status())
        command_id = self.transport.send('fire')
        commands.JournalReader().poll(self.command_path,
            lambda request: gateway.submit(request, self.now), lambda reason, offset: self.fail(reason))
        self.transport.poll()
        local_receipt = dict(self.transport.results[command_id])
        publish(shots.terminal({'projectile_id': 'real:p', 'hit_vehicle': True}, self.now + 1))
        hit = shots.hit({'projectile_id': 'real:p', 'event_id': 'damage-1', 'damage': 95., 'shot_result': 2}, self.now + 2)
        publish(hit)
        publish(hit)
        self.append(self.status(shot_results=shots.snapshot()))
        self.transport.poll()
        item = self.transport.projectile_results(command_id)[0]
        self.assertEqual((95., 1, True, True),
            (item['damage_total'], item['hit_count'], item['penetrated'], item['terminal_observed']))
        self.assertEqual(local_receipt, self.transport.results[command_id])

    def test_terminal_without_combat_has_bounded_grace_and_late_he_snapshot_still_repairs(self):
        self.append(self.status())
        command_id = self.transport.send('fire')
        command = self.commands()[0]
        self.append(self.receipt(command, 'completed', reason='shot_committed', result={'projectile_ids': ['p']}),
                    self.shot(command, 'p', 'terminal', 2, hit_vehicle=False))
        self.transport.poll()
        self.assertTrue(self.transport._has_pending())
        self.now += self.transport.PROJECTILE_GRACE_SECONDS + 1
        self.assertFalse(self.transport._has_pending())
        self.assertFalse(self.transport.projectile_results(command_id)[0]['combat_observed'])
        hit = self.shot(command, 'p', 'hit', 3, damage_total=20., hit_count=1,
                        flight_status='terminal', terminal_observed=True)
        self.append(hit, *(self.status(ammo={'padding': 'x' * 500}) for _ in range(150)))
        # Root snapshots retain recently updated projectiles, not only newly
        # launched ones. The direct hit row lies before the tail seek here.
        self.append(self.status(shot_results=[hit]))
        self.transport.poll()
        item = self.transport.projectile_results(command_id)[0]
        self.assertEqual((20., 1, True), (item['damage_total'], item['hit_count'], item['combat_observed']))
        self.assertFalse(self.transport._has_pending())

    def test_full_projectile_snapshot_fits_bounded_reader_when_opened_late(self):
        client_path = str(Path(__file__).resolve().parents[2] / 'src/res/scripts/client')
        with mock.patch.object(sys, 'path', [client_path] + sys.path):
            from gui.mods.offline_lan_0922.player_control import PlayerControl
        entity = types.SimpleNamespace(isAlive=lambda: True)
        owner = types.SimpleNamespace(state='running', _battle_live=True, _battle_result=None,
            _server=types.SimpleNamespace(vehicle_id=101), _server_entity=lambda unused: entity,
            _sender=object(), _worker_mode=False, _replay_mode=False,
            _start_message={'round_id': 'round-a'}, client=types.SimpleNamespace(player_id=101),
            local_pose=lambda: ((1.25, 0., 4.5), 1.), _local_speed=3.25)
        control = PlayerControl(owner, ())
        ledger = control.shot_receipts
        for index in range(32):
            projectile_id = 'player-flight:' + 'p' * 180 + str(index)
            ledger.committed({'projectile_id': projectile_id, 'shell_index': 0},
                {'burst_group_seq': index, 'burst_count': 1},
                {'command': 'command-' + 'c' * 120, 'target': 202}, self.now, 1)
            ledger.terminal({'projectile_id': projectile_id, 'hit_vehicle': True}, self.now + 1)
            ledger.hit({'projectile_id': projectile_id, 'event_id': 'effect-' + str(index),
                        'damage': 95., 'shot_result': 2, 'target': 202}, self.now + 2)
        self.assertGreater(len(json.dumps(ledger.snapshot()).encode('ascii')), self.transport.MAX_LINE_BYTES)
        self.append(*(self.status(round_id='old', ammo={'padding': 'x' * 500}) for _ in range(150)))
        with mock.patch.dict(os.environ, {'WOT_OFFLINE_TEST_CONTROL_SESSION': 'session-a',
                'WOT_OFFLINE_TEST_CONTROL_RESULT_FILE': self.result_path}):
            control.publish_status(self.now + 3, force=True)
        with open(self.result_path, 'rb') as stream:
            latest_line = stream.readlines()[-1]
        self.assertLessEqual(len(latest_line), self.transport.MAX_LINE_BYTES)
        row = json.loads(latest_line)
        snapshots = row['shot_results']
        self.assertTrue(0 < len(snapshots) < 32)
        self.assertEqual(32 - len(snapshots), row['shot_snapshot_omitted'])
        self.transport.poll()
        self.assertTrue(self.transport.live)
        self.assertEqual(len(snapshots), len(self.transport.projectiles))
        self.assertIn(projectile_id, [item['projectile_id'] for item in self.transport.projectiles.values()])
        self.assertTrue(all(item['damage_total'] == 95. and item['terminal_observed']
                            for item in self.transport.projectiles.values()))

    def test_recent_automatic_shots_remain_visible_after_an_older_manual_fire_command(self):
        self.append(self.status())
        command_id = self.transport.send('fire')
        command = self.commands()[0]
        self.append(self.receipt(command, 'completed', reason='shot_committed', result={'projectile_ids': ['manual:p']}))
        self.transport.poll()
        self.transport.send('start')
        self.append(self.shot(command, 'auto:p', 'committed', 5, command_id=None),
                    self.shot(command, 'auto:p', 'terminal', 6, command_id=None))
        self.transport.poll()
        self.assertEqual({'manual:p', 'auto:p'}, {item['projectile_id'] for item in self.transport.projectile_results()})
        self.assertEqual(['manual:p'], [item['projectile_id'] for item in self.transport.projectile_results(command_id)])

    def test_malformed_result_shapes_are_contained_without_blocking_following_receipts(self):
        self.append(self.status())
        command_id = self.transport.send('fire')
        command = self.commands()[0]
        self.append(self.receipt(command, []), self.receipt(command, 'accepted', action={}),
                    self.shot(command, 'invalid:status', status=[]),
                    self.shot(command, 'invalid:total', damage_total=10 ** 1000),
                    self.shot(command, 'invalid:null:total', damage_total=None),
                    self.shot(command, 'invalid:null:time', time=None),
                    self.shot(command, 'invalid:null:count', hit_count=None),
                    self.receipt(command, 'completed', reason='shot_committed', result={'projectile_ids': ['valid:p']}))
        self.transport.poll()
        self.assertEqual('completed', self.transport.results[command_id]['status'])
        self.assertEqual(['valid:p'], [item['projectile_id'] for item in self.transport.projectile_results(command_id)])

    def test_weapon_and_observation_schema_matches_the_actual_client(self):
        client = self.client_module('commands')
        for name in ('ACTIONS', 'READ_ONLY_ACTIONS', 'STATE_CONDITIONS', 'MISSION_STATUS_VALUES', 'MISSION_PHASE_VALUES'):
            self.assertEqual(getattr(client, name), getattr(transport_schema, name))
        cases = [('select_shell', {'compact_descr': 2147483647}), ('reload', {})]
        predicates = [{'condition': condition} for condition in ('ammo_ready', 'ammo_empty', 'halted')]
        predicates += [{'condition': 'active', 'value': value} for value in (True, False)]
        predicates += [{'condition': 'mission_status', 'value': value, 'command_id': 'mission-one'}
                       for value in client.MISSION_STATUS_VALUES]
        predicates += [{'condition': 'mission_phase', 'value': value} for value in client.MISSION_PHASE_VALUES]
        predicates += [dict(condition=condition, **{field: value})
                       for condition in ('shot_terminal', 'shot_effect')
                       for field, value in (('projectile_id', 'p' * 256), ('command_id', 'c' * 128))]
        predicates.append({'condition': 'shot_effect', 'projectile_id': 'p', 'damage_min': 1.5})
        cases += [(action, args) for action in ('wait_state', 'assert_state') for args in predicates]
        for action, args in cases:
            with self.subTest(action=action, args=args):
                self.assertEqual(client.validate_action(action, args), transport_schema.validate_arguments(action, args))

    def test_invalid_weapon_or_observation_args_never_reach_the_request_journal(self):
        self.append(self.status())
        invalid = [('select_shell', {'compact_descr': value}) for value in (True, 0, -1, '7', 7., 2147483648)]
        invalid += [('select_shell', {}), ('reload', {'force': True}),
                    ('wait_state', {'condition': 'active', 'value': 1}),
                    ('assert_state', {'condition': 'ammo_ready', 'path': 'ammo.can_fire'}),
                    ('wait_state', {'condition': 'ammo.total'}),
                    ('wait_state', {'condition': []}),
                    ('wait_state', {'condition': 'mission_status', 'value': 'unknown'}),
                    ('wait_state', {'condition': 'mission_phase', 'value': 'holding', 'command_id': ''}),
                    ('wait_state', {'condition': 'shot_terminal'}),
                    ('wait_state', {'condition': 'shot_terminal', 'projectile_id': 'p', 'command_id': 'c'}),
                    ('assert_state', {'condition': 'shot_effect', 'command_id': 'c' * 129})]
        invalid += [('wait_state', {'condition': 'shot_effect', 'projectile_id': 'p', 'damage_min': value})
                    for value in (True, -1, '1', float('nan'), float('inf'), 10 ** 1000)]
        client = self.client_module('commands')
        for action, args in invalid:
            with self.subTest(action=action, args=args):
                with self.assertRaises(ValueError):
                    client.validate_action(action, args)
                self.assertIsNone(self.transport.send(action, args))
        self.assertEqual([], self.commands())

    def test_read_only_requests_allow_fresh_nonlive_identity_but_never_stale_status(self):
        self.append(self.status(live=False, reason='dead', active=False))
        self.transport.poll()
        for action, args in (('status', {}), ('wait_state', {'condition': 'active', 'value': False}),
                             ('assert_state', {'condition': 'ammo_empty'})):
            self.assertTrue(self.transport.can_submit(action))
            self.assertIsNotNone(self.transport.send(action, args))
        for action in ('fire', 'start', 'drive', 'reload', 'select_shell'):
            self.assertFalse(self.transport.can_submit(action))
            self.assertIsNone(self.transport.send(action))
        self.assertEqual(3, len(self.commands()))
        self.now += self.transport.stale_seconds + 1.
        for action in ('status', 'wait_state', 'assert_state'):
            self.assertFalse(self.transport.can_submit(action))
            self.assertIsNone(self.transport.send(action, {'condition': 'ammo_ready'} if action != 'status' else {}))
            self.assertEqual('status_stale', self.transport.error)
        self.assertTrue(self.transport.can_submit('stop'))
        self.assertIsNotNone(self.transport.send('stop'))
        self.assertEqual(4, len(self.commands()))

    def test_weapon_wait_defaults_and_real_journal_validation_preserve_fixed_schema(self):
        client = self.client_module('commands')
        identity = dict(session_id='session-a', round_id='round-a', player_id=101)
        executed = []
        def execute(command, now):
            executed.append(command)
            return dict(reason='observed', result=dict(args=command['args']))
        gateway = client.CommandGateway(lambda: identity,
            lambda row: client.append_result(self.result_path, row), execute,
            lambda command: None, lambda command, reason: None, wall_clock=lambda: self.wall_now)
        self.append(self.status())
        for action, args, timeout in (('select_shell', {'compact_descr': 7}, 180.), ('reload', {}, 180.),
                                     ('wait_state', {'condition': 'ammo_ready'}, 30.)):
            self.assertIsNotNone(self.transport.send(action, args))
            self.assertEqual(timeout, self.commands()[-1]['timeout_seconds'])
            self.assertEqual(self.wall_now + 2., self.commands()[-1]['expires_at'])
        client.JournalReader().poll(self.command_path,
            lambda command: gateway.submit(command, self.now), lambda reason, offset: self.fail(reason))
        self.transport.poll()
        self.assertEqual(['select_shell', 'reload', 'wait_state'], [command['action'] for command in executed])
        self.assertEqual([{'compact_descr': 7}, {}, {'condition': 'ammo_ready'}], [command['args'] for command in executed])
        self.assertTrue(all(self.transport.results[command['id']]['status'] == 'completed' for command in self.commands()))


if __name__ == '__main__':
    unittest.main()
