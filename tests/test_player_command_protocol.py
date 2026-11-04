"""Exercise the real journals and admission/terminal command boundaries."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control.commands import (
    CommandGateway, JournalReader, append_result)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'commands.jsonl'
        self.reader = JournalReader()
        self.accepted, self.rejected = [], []

    def poll(self):
        self.reader.poll(str(self.path), self.accepted.append,
                         lambda reason, offset: self.rejected.append((reason, offset)))

    def test_oversized_record_does_not_pin_following_stop(self):
        self.path.write_bytes(b'x' * 5000 + b'\n{"action":"stop"}\n')
        self.poll()
        self.assertEqual([{'action': 'stop'}], self.accepted)
        self.assertEqual([('oversize', 0)], self.rejected)
        self.assertEqual(self.path.stat().st_size, self.reader.offset)

    def test_growing_oversize_tail_is_rejected_once_and_drained_boundedly(self):
        self.path.write_bytes(b'x' * 200000)
        self.poll()
        self.assertLessEqual(self.reader.offset, 65536)
        self.assertEqual([('oversize', 0)], self.rejected)
        self.assertTrue(self.reader.discarding)
        with self.path.open('ab') as stream:
            stream.write(b'\n{"action":"stop"}\n')
        for unused in range(4):
            self.poll()
        self.assertEqual([{'action': 'stop'}], self.accepted)
        self.assertEqual(1, len(self.rejected))

    def test_partial_record_and_split_utf8_remain_unconsumed(self):
        record = json.dumps({'action': 'status', 'label': '\u8fd4\u56de'}, ensure_ascii=False).encode('utf8')
        self.path.write_bytes(record[:-3])
        self.poll()
        self.assertEqual(0, self.reader.offset)
        self.assertEqual([], self.accepted)
        with self.path.open('ab') as stream:
            stream.write(record[-3:] + b'\n')
        self.poll()
        self.assertEqual('返回', self.accepted[0]['label'])
        self.assertEqual([], self.rejected)

    def test_malformed_record_does_not_consume_valid_next_request(self):
        self.path.write_bytes(b'{bad}\n\xff\n{"action":"stop"}\n')
        self.poll()
        self.assertEqual([{'action': 'stop'}], self.accepted)
        self.assertEqual(['invalid_json', 'invalid_json'], [r[0] for r in self.rejected])

    def test_truncation_clears_oversize_drain(self):
        self.path.write_bytes(b'x' * 5000)
        self.poll()
        self.path.write_bytes(b'{"action":"stop"}\n')
        self.poll()
        self.assertEqual([{'action': 'stop'}], self.accepted)

    def test_result_is_complete_jsonl_and_nonfinite_values_are_rejected(self):
        self.assertTrue(append_result(str(self.path), {'status': 'completed', 'id': 'one'}))
        self.assertTrue(self.path.read_bytes().endswith(b'\n'))
        self.assertEqual('completed', json.loads(self.path.read_text())['status'])
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            append_result(str(self.path), {'bad': float('nan')})
        self.assertEqual(before, self.path.read_bytes())


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(session_id='launch-A', round_id='round-B', player_id=4)
        self.rows = []
        self.execute = mock.Mock(return_value=None)
        self.cancel = mock.Mock()
        self.preflight = mock.Mock(return_value=None)
        self.gateway = CommandGateway(lambda: self.identity,
            lambda row: self.rows.append(dict(row)) or True,
            self.execute, self.preflight, self.cancel)

    def request(self, **kwargs):
        return dict(self.identity, **dict(dict(id='one', action='drive',
                    args=dict(seconds=1., forward=1.), replace=True), **kwargs))

    def test_identity_rejects_stale_launch_round_and_player_before_execution(self):
        for field in ('session_id', 'round_id', 'player_id'):
            request = self.request()
            request[field] = 'old'
            row = self.gateway.submit(request, 0.)
            self.assertEqual('rejected', row['status'])
            self.assertEqual('stale_' + field, row['reason'])
        self.execute.assert_not_called()
        self.preflight.assert_not_called()

    def test_invalid_drive_or_timeout_never_preempts_running_command(self):
        self.gateway.submit(self.request(), 0.)
        for args in ({'seconds': -1}, {'seconds': float('nan')},
                     {'turn': 1.01}, {'forward': True}, {'unknown': 1}):
            self.assertEqual('rejected', self.gateway.submit(
                self.request(id='bad', args=args), .1)['status'])
        self.assertEqual('accepted', self.gateway.requests['one']['receipt']['status'])
        self.execute.assert_called_once()
        self.cancel.assert_not_called()

    def test_identical_retry_is_not_reexecuted_and_returns_final_receipt(self):
        request = self.request(action='fire', args={})
        self.gateway.submit(request, 0.)
        self.gateway.submit(request, .1)
        self.gateway.finish('one', 'completed', 'shot_committed', .2, {'projectile_id': 'p'})
        receipt = self.gateway.submit(request, .3)
        self.assertEqual('completed', receipt['status'])
        self.assertEqual('p', receipt['result']['projectile_id'])
        self.execute.assert_called_once()

    def test_same_id_with_different_payload_does_not_replace_original(self):
        self.gateway.submit(self.request(), 0.)
        result = self.gateway.submit(self.request(args={'forward': -1}), .1)
        self.assertEqual('id_conflict', result['reason'])
        self.assertEqual('accepted', self.gateway.requests['one']['receipt']['status'])
        self.execute.assert_called_once()

    def test_receipt_write_failure_prevents_action(self):
        self.gateway.emit = mock.Mock(return_value=False)
        result = self.gateway.submit(self.request(), 0.)
        self.assertEqual('result_unavailable', result['reason'])
        self.execute.assert_not_called()

    def test_timeout_reports_failure_even_if_cleanup_cancels_all_commands(self):
        def cancel(command, reason):
            self.gateway.finish(command['id'], 'cancelled', reason, 2.)
        self.cancel.side_effect = cancel
        self.gateway.submit(self.request(timeout_seconds=1.), 0.)
        self.gateway.tick(1.)
        self.gateway.tick(2.)
        self.assertEqual('failed', self.gateway.requests['one']['receipt']['status'])
        self.assertEqual('command_timeout', self.rows[-1]['reason'])
        self.cancel.assert_called_once()

    def test_synchronous_commit_is_not_overwritten_by_execute_return(self):
        def execute(command, now):
            self.gateway.finish(command['id'], 'completed', 'shot_committed', now,
                                {'projectile_id': 'actual'})
            return None
        self.execute.side_effect = execute
        receipt = self.gateway.submit(self.request(action='fire', args={}), 4.)
        self.assertEqual(['accepted', 'completed'], [r['status'] for r in self.rows])
        self.assertEqual('actual', receipt['result']['projectile_id'])

    def test_preflight_rejects_without_acceptance_or_execution(self):
        self.preflight.return_value = 'drive_disabled'
        receipt = self.gateway.submit(self.request(action='return_base', args={}), 0.)
        self.assertEqual('rejected', receipt['status'])
        self.assertEqual('drive_disabled', receipt['reason'])
        self.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
