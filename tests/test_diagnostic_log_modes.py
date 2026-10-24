"""Normal play stays small; test diagnostics have explicit byte bounds."""
import io
import json
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import native_input_diagnostics as logs


class LogModeTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(logs.os.environ, {logs.DETAIL_ENV:'0'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.output = io.StringIO()
        self.stream = mock.patch.object(logs.sys, 'stdout', self.output)
        self.stream.start()
        self.addCleanup(self.stream.stop)
        self.budget = mock.patch.object(logs, '_detail_budget', dict(
            start=None, window=0, session=0, dropped=0, notice=False))
        self.budget.start()
        self.addCleanup(self.budget.stop)

    def test_basic_skips_serialization_of_bulk_histories_but_keeps_key_events(self):
        with mock.patch.object(logs.json, 'dumps', side_effect=AssertionError('bulk encoded')):
            logs.write_json_record('BOT MOTION', {'history':object()})
        logs.write_json_record('BOT CONSUMABLE', {'id':6, 'event':'repair'})
        logs.write_json_record('BOT MOTION BASIC', {'id':6, 'recovery':'blocked'})
        self.assertIn('BOT CONSUMABLE', self.output.getvalue())
        self.assertIn('BOT MOTION BASIC', self.output.getvalue())

    def test_test_mode_preserves_complete_fragmented_record(self):
        logs.os.environ[logs.DETAIL_ENV] = '1'
        payload = dict(id=6, history='x'*18000)
        logs.write_json_record('BOT MOTION', payload)
        parts = [json.loads(line.split(' PART ',1)[1]) for line in self.output.getvalue().splitlines()]
        self.assertEqual(payload, json.loads(''.join(p['data'] for p in parts)))
        self.assertTrue(all(len(line)<8192 for line in self.output.getvalue().splitlines()))

    def test_budget_never_suppresses_key_event_and_has_session_ceiling(self):
        logs.os.environ[logs.DETAIL_ENV] = '1'
        with mock.patch.object(logs, 'DETAIL_WINDOW_BYTES', 20000), mock.patch.object(
                logs, 'DETAIL_SESSION_BYTES', 30000), mock.patch.object(logs.time, 'time') as clock:
            for minute in range(5):
                clock.return_value = minute*60.0
                for unused in range(20):
                    logs.write_json_record('BOT MOTION', dict(history='x'*4000))
                logs.write_json_record('BOT CONSUMABLE', dict(event='repair'))
        self.assertLessEqual(logs._detail_budget['session'], 30000)
        self.assertEqual(5, self.output.getvalue().count('BOT CONSUMABLE'))
        self.assertIn('DIAGNOSTIC LIMIT', self.output.getvalue())

    def test_oversize_detail_is_explicitly_suppressed(self):
        logs.os.environ[logs.DETAIL_ENV] = '1'
        with mock.patch.object(logs, 'DETAIL_RECORD_BYTES', 1024):
            logs.write_json_record('BOT MOTION', dict(history='x'*2000))
        self.assertIn('DIAGNOSTIC LIMIT', self.output.getvalue())
        self.assertNotIn(' PART ', self.output.getvalue())

    def test_closed_window_skips_encoding_and_reopens_next_minute(self):
        logs.os.environ[logs.DETAIL_ENV] = '1'
        with mock.patch.object(logs, 'DETAIL_WINDOW_BYTES', 1000), \
                mock.patch.object(logs.time, 'time', return_value=1.) as clock:
            logs.write_json_record('BOT SLOPE', dict(history='x'*600))
            with mock.patch.object(logs.json, 'dumps', side_effect=AssertionError('closed budget encoded')):
                for unused in range(100):
                    logs.write_json_record('BOT SLOPE', dict(history=object()))
            clock.return_value = 61.
            logs.write_json_record('BOT SLOPE', dict(id=1))
        self.assertIn('BOT SLOPE {"id":1}', self.output.getvalue())

    def test_closed_session_skips_encoding_across_window_rollover(self):
        logs.os.environ[logs.DETAIL_ENV] = '1'
        with mock.patch.object(logs, 'DETAIL_SESSION_BYTES', 1000), \
                mock.patch.object(logs.time, 'time', return_value=1.) as clock:
            logs.write_json_record('BOT SLOPE', dict(history='x'*600))
            clock.return_value = 61.
            with mock.patch.object(logs.json, 'dumps', side_effect=AssertionError('closed session encoded')):
                logs.write_json_record('BOT SLOPE', dict(history=object()))
            logs.write_json_record('BOT CONSUMABLE', dict(event='repair'))
        self.assertIn('BOT CONSUMABLE', self.output.getvalue())

    def test_oversize_record_does_not_block_following_small_record(self):
        logs.os.environ[logs.DETAIL_ENV] = '1'
        with mock.patch.object(logs, 'DETAIL_RECORD_BYTES', 100):
            logs.write_json_record('BOT SLOPE', dict(history='x'*200))
            logs.write_json_record('BOT SLOPE', dict(id=1))
        self.assertIn('BOT SLOPE {"id":1}', self.output.getvalue())

    def test_closed_budget_skips_nested_runtime_history_construction(self):
        from test_port_0922_bot_runtime import _load
        runtime = _load().BotRuntime(1)
        logs.os.environ[logs.DETAIL_ENV] = '1'
        logs._detail_budget['session'] = logs.DETAIL_SESSION_BYTES
        with mock.patch.object(runtime, '_record_execution_window',
                side_effect=AssertionError('closed budget built history')):
            runtime._log_motion_stall(dict(id=1,x=0.,y=0.,z=0.), {},
                                      0.,0.,False,{},1.)

    def test_basic_runtime_never_builds_nested_motion_history(self):
        from test_port_0922_bot_runtime import _load
        runtime = _load().BotRuntime(1)
        runtime.round_id = 1
        state = dict(id=6, vehicle='sweden:S23_Strv_81', x=-297.97,
                     y=18.55, z=-290.21, speed=0.0)
        command = dict(movement_intent=True, recovery_mode='blocked',
                       combat_mode='route', move_position=(-301.07,18.86,-289.70))
        with mock.patch.object(runtime, '_record_execution_window',
                side_effect=AssertionError('basic entry built motion history')):
            for tick in range(600):
                runtime._log_motion_stall(state, command, 0., 0., False,
                                         dict(clear=False, collision=True), tick*0.1)
        self.assertEqual(2, self.output.getvalue().count('BOT MOTION BASIC'))
        self.assertLess(len(self.output.getvalue()), 2000)
        self.assertNotIn('_execution_window', state)

    def test_new_round_reopens_budget_but_duplicate_start_does_not(self):
        with mock.patch.object(logs, '_detail_round', None):
            logs.log_summary('round_start', 1)
            logs._detail_budget.update(session=logs.DETAIL_SESSION_BYTES, session_closed=True)
            logs.log_summary('round_start', 1)
            self.assertTrue(logs._detail_budget['session_closed'])
            logs.log_summary('round_end', 1)
            self.assertTrue(logs._detail_budget['session_closed'])
            logs.log_summary('round_start', 2)
            self.assertEqual(0, logs._detail_budget['session'])
            self.assertNotIn('session_closed', logs._detail_budget)

    def test_fire_gate_uses_detail_budget_and_basic_entry_skips_encoder(self):
        with mock.patch.object(logs.json, 'dumps', side_effect=AssertionError('encoded')):
            logs.write_json_record('SPG FIRE GATE', dict(history=object()))
        logs.os.environ[logs.DETAIL_ENV] = '1'
        logs._detail_budget['session_closed'] = True
        with mock.patch.object(logs.json, 'dumps', side_effect=AssertionError('encoded')):
            logs.write_json_record('SPG FIRE GATE', dict(history=object()))

    def test_long_stall_keeps_compact_outcome_after_bulk_budget_closed(self):
        from test_port_0922_bot_runtime import _load
        runtime = _load().BotRuntime(1)
        logs.os.environ[logs.DETAIL_ENV] = '1'
        logs._detail_budget['session_closed'] = True
        state = dict(id=4, vehicle='uk:GB91_Super_Conqueror', x=135., y=-8., z=-154.)
        runtime.states[4] = state
        runtime.states[5] = dict(id=5, x=138., y=-8., z=-154., alive=False)
        command = dict(movement_intent=True, recovery_mode='avoid', combat_mode='route')
        for now in (0., 16., 17., 46.):
            runtime._log_motion_stall(state, command, 1., .2, True, {}, now)
            runtime._finish_motion_stall(state, False, False, (135.,-8.,-154.), now)
        rows = [json.loads(line.split('BOT RECOVERY SUMMARY ',1)[1])
                for line in self.output.getvalue().splitlines() if 'BOT RECOVERY SUMMARY ' in line]
        self.assertEqual(2, len(rows))
        self.assertEqual(5, rows[0]['nearby'][0]['id'])
        self.assertFalse(rows[0]['nearby'][0]['alive'])
        self.assertEqual(1., rows[0]['command']['throttle'])
        self.assertNotIn('BOT MOTION PART', self.output.getvalue())


if __name__ == '__main__':
    unittest.main()
