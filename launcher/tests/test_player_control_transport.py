"""Observable identity, framing, and acknowledgement boundaries for test controls."""
import importlib.util
import json
import os
import tempfile
import time
import unittest

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
        self.transport = PlayerControlTransport(self.command_path, self.result_path,
                                                'session-a', clock=lambda: self.now)

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
        self.now += 5
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
        self.assertEqual('command_too_large', self.transport.error)
        self.assertIsNone(self.transport.send('fire', replace='false'))
        self.assertEqual('invalid_replace', self.transport.error)
        self.assertEqual([], self.commands())

    def test_launcher_round_trip_with_the_actual_client_gateway(self):
        module_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
            'src', 'res', 'scripts', 'client', 'gui', 'mods', 'offline_lan_0922',
            'player_control', 'commands.py'))
        spec = importlib.util.spec_from_file_location('player_command_gateway_contract', module_path)
        commands = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(commands)
        executed = []
        identity = dict(session_id='session-a', round_id='round-a', player_id=101)
        gateway = commands.CommandGateway(lambda: identity,
            lambda row: commands.append_result(self.result_path, row),
            lambda request, now: executed.append(request), lambda request: None,
            lambda request, reason: None)
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


if __name__ == '__main__':
    unittest.main()
