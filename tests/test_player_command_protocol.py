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
    CommandGateway, JournalReader, append_result, validate_action,
    MISSION_PHASE_VALUES, MISSION_STATUS_VALUES, STATE_CONDITIONS)


class ActionSchemaTests(unittest.TestCase):
    def test_selected_shell_requires_exact_positive_integer_descriptor(self):
        for value in (1, 65537, 2147483647):
            self.assertEqual({'compact_descr': value}, validate_action('select_shell', {'compact_descr': value}))
        for value in (None, False, True, 0, -1, 2147483648, '7', 7., {}, float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_action('select_shell', {'compact_descr': value})
        with self.assertRaises(ValueError):
            validate_action('select_shell', {})

    def test_reload_and_boolean_state_predicates_do_not_accept_extra_fields(self):
        self.assertEqual({}, validate_action('reload', {}))
        for action in ('wait_state', 'assert_state'):
            for condition in ('ammo_ready', 'ammo_empty', 'halted'):
                args = {'condition': condition}
                self.assertEqual(args, validate_action(action, args))
                with self.assertRaises(ValueError):
                    validate_action(action, dict(args, value=True))
        with self.assertRaises(ValueError):
            validate_action('reload', {'force': True})

    def test_active_condition_requires_boolean_and_missions_use_explicit_enums(self):
        for action in ('wait_state', 'assert_state'):
            for value in (True, False):
                self.assertEqual({'condition': 'active', 'value': value},
                    validate_action(action, {'condition': 'active', 'value': value}))
            for value in (None, 0, 1, 'true', []):
                with self.subTest(action=action, value=value), self.assertRaises(ValueError):
                    validate_action(action, {'condition': 'active', 'value': value})
            for condition, values in (('mission_status', MISSION_STATUS_VALUES), ('mission_phase', MISSION_PHASE_VALUES)):
                for value in values:
                    self.assertEqual(value, validate_action(action, {'condition': condition, 'value': value})['value'])
                for value in (None, 'arbitrary', True, {}, 'mission.phase'):
                    with self.subTest(condition=condition, value=value), self.assertRaises(ValueError):
                        validate_action(action, {'condition': condition, 'value': value})
                self.assertEqual('mission-one', validate_action(action, dict(condition=condition,
                    value='idle', command_id='mission-one'))['command_id'])
                for command_id in ('', 'c' * 129, 7, None):
                    with self.subTest(command_id=command_id), self.assertRaises(ValueError):
                        validate_action(action, dict(condition=condition, value='idle', command_id=command_id))

    def test_shot_predicates_require_exactly_one_bounded_reference(self):
        for action in ('wait_state', 'assert_state'):
            for condition in ('shot_terminal', 'shot_effect'):
                for field, maximum in (('projectile_id', 256), ('command_id', 128)):
                    for value in ('one', 'x' * maximum):
                        args = dict(condition=condition, **{field: value})
                        expected = dict(args, damage_min=0.) if condition == 'shot_effect' else args
                        self.assertEqual(expected, validate_action(action, args))
                    for value in ('', 'x' * (maximum + 1), 1, True, None):
                        with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                            validate_action(action, dict(condition=condition, **{field: value}))
                for references in ({}, {'projectile_id': 'p', 'command_id': 'c'}):
                    with self.assertRaises(ValueError):
                        validate_action(action, dict(condition=condition, **references))

    def test_damage_min_is_finite_numeric_nonnegative_and_only_for_effects(self):
        args = dict(condition='shot_effect', projectile_id='p')
        for value in (0, .1, 1000, 1e300):
            self.assertEqual(float(value), validate_action('wait_state', dict(args, damage_min=value))['damage_min'])
        for value in (None, True, '1', -1, float('nan'), float('inf'), 10 ** 1000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_action('wait_state', dict(args, damage_min=value))
        with self.assertRaises(ValueError):
            validate_action('assert_state', dict(condition='shot_terminal', projectile_id='p', damage_min=0.))

    def test_predicates_are_a_fixed_schema_not_arbitrary_paths_or_code(self):
        self.assertEqual(8, len(STATE_CONDITIONS))
        for action in ('wait_state', 'assert_state'):
            for args in ({}, {'condition': 'ammo.total'}, {'condition': '__import__'},
                         {'condition': []}, {'condition': 'ammo_ready', 'path': 'ammo.total'},
                         {'condition': 'ammo_empty', 'expression': 'True'}):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    validate_action(action, args)


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
        self.wall_now = 1000.
        self.gateway = CommandGateway(lambda: self.identity,
            lambda row: self.rows.append(dict(row)) or True,
            self.execute, self.preflight, self.cancel, wall_clock=lambda: self.wall_now)

    def request(self, **kwargs):
        return dict(self.identity, **dict(dict(id='one', action='drive',
                    args=dict(seconds=1., forward=1.), replace=True,
                    expires_at=1002.), **kwargs))

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

    def test_expired_admission_rejects_before_preflight_or_execution(self):
        self.wall_now = 1060.
        receipt = self.gateway.submit(self.request(timeout_seconds=2.), 60.)
        self.assertEqual(('rejected', 'request_expired'), (receipt['status'], receipt['reason']))
        self.preflight.assert_not_called()
        self.execute.assert_not_called()
        self.cancel.assert_not_called()
        self.assertNotIn('deadline', self.gateway.requests['one'])

    def test_admission_deadline_is_required_finite_numeric_and_not_a_boolean(self):
        for index, value in enumerate((None, True, '1002', {}, -1, float('nan'), float('inf'))):
            with self.subTest(value=value):
                request = self.request(id='bad-%s' % index, expires_at=value)
                receipt = self.gateway.submit(request, 0.)
                self.assertEqual('rejected', receipt['status'])
        request = self.request(id='missing')
        request.pop('expires_at')
        self.assertEqual('invalid_expires_at', self.gateway.submit(request, 0.)['reason'])
        self.execute.assert_not_called()
        self.preflight.assert_not_called()

    def test_deadline_boundary_is_expired_and_preflight_cannot_cross_it(self):
        self.wall_now = 1002.
        self.assertEqual('request_expired', self.gateway.submit(self.request(), 0.)['reason'])
        self.wall_now = 1001.
        self.preflight.side_effect = lambda command: setattr(self, 'wall_now', 1002.)
        self.assertEqual('request_expired', self.gateway.submit(self.request(id='crossing'), 0.)['reason'])
        self.execute.assert_not_called()

    def test_admitted_retries_keep_the_same_outcome_after_admission_expiry(self):
        request = self.request()
        self.gateway.submit(request, 500.)
        self.wall_now = 9000.
        self.assertEqual('accepted', self.gateway.submit(request, 501.)['status'])
        self.gateway.finish('one', 'completed', 'drive_finished', 502.)
        self.assertEqual('completed', self.gateway.submit(request, 503.)['status'])
        self.execute.assert_called_once()
        self.assertEqual(503., self.gateway.requests['one']['deadline'])

    def test_expired_request_does_not_replay_after_wall_clock_rewinds(self):
        request = self.request()
        self.wall_now = 1003.
        receipt = self.gateway.submit(request, 0.)
        self.wall_now = 1000.
        self.assertEqual(receipt, self.gateway.submit(request, 1.))
        self.execute.assert_not_called()

    def test_stop_has_no_admission_expiry_but_still_requires_current_identity(self):
        self.wall_now = 10000.
        request = self.request(action='stop', args={})
        self.assertEqual('accepted', self.gateway.submit(request, 0.)['status'])
        request = self.request(id='stop-without-deadline', action='stop', args={})
        request.pop('expires_at')
        self.assertEqual('accepted', self.gateway.submit(request, 1.)['status'])
        request = self.request(id='stale-stop', action='stop', args={})
        request['round_id'] = 'old'
        self.assertEqual('stale_round_id', self.gateway.submit(request, 2.)['reason'])
        self.assertEqual(2, self.execute.call_count)

    def test_a_supplied_stop_deadline_must_still_have_a_valid_shape(self):
        receipt = self.gateway.submit(self.request(action='stop', args={}, expires_at=True), 0.)
        self.assertEqual('invalid_expires_at', receipt['reason'])
        self.execute.assert_not_called()

    def test_execution_timeout_uses_client_time_after_admission_not_wall_expiry(self):
        self.gateway.submit(self.request(timeout_seconds=2.), 100.)
        self.wall_now = 5000.
        self.gateway.tick(101.9)
        self.assertEqual('accepted', self.gateway.requests['one']['receipt']['status'])
        self.gateway.tick(102.)
        self.assertEqual('command_timeout', self.gateway.requests['one']['receipt']['reason'])

    def test_stale_identity_is_rejected_before_an_expired_id_can_replay(self):
        request = self.request()
        self.gateway.submit(request, 0.)
        self.identity = dict(self.identity, round_id='next-round')
        self.wall_now = 5000.
        self.assertEqual('stale_round_id', self.gateway.submit(request, 1.)['reason'])
        self.execute.assert_called_once()

    def test_new_action_execution_deadlines_are_separate_from_admission(self):
        for action, args, timeout in (('select_shell', {'compact_descr': 7}, 180.),
                                     ('reload', {}, 180.),
                                     ('wait_state', {'condition': 'ammo_ready'}, 30.)):
            row = self.gateway.submit(self.request(id=action, action=action, args=args), 100.)
            self.assertEqual('accepted', row['status'])
            self.assertEqual(100. + timeout, self.gateway.requests[action]['deadline'])
        self.wall_now = 1003.
        row = self.gateway.submit(self.request(id='late-assert', action='assert_state',
            args={'condition': 'ammo_empty'}), 100.)
        self.assertEqual('request_expired', row['reason'])

    def test_invalid_weapon_or_watch_schema_rejects_before_preflight_or_mutation(self):
        for index, (action, args) in enumerate((('select_shell', {'compact_descr': True}),
            ('reload', {'force': True}), ('wait_state', {'condition': 'shot_effect', 'command_id': 'c', 'damage_min': -1}),
            ('assert_state', {'condition': 'active', 'value': 1}))):
            row = self.gateway.submit(self.request(id=str(index), action=action, args=args), 0.)
            self.assertEqual('rejected', row['status'])
        self.execute.assert_not_called()
        self.preflight.assert_not_called()
        self.cancel.assert_not_called()


if __name__ == '__main__':
    unittest.main()
