"""A worker's adopted firing position must not look like stale deployment."""
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import native_input_diagnostics as logs
import test_port_0922_bot_runtime as fixture


class SPGPositionDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        harness = fixture.BotRuntimeTests()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        self.runtime, self.module = harness.runtime, harness.module
        self.state = dict(id=29, x=-346.0144, y=-9.6313, z=-275.794,
            _spg_initial=dict(zone='replacement', radius=2.,
                point=dict(x=-346., y=-9.564, z=-274.)),
            _spg_position_event='fire_position_other_zone')
        self.runtime._server_orders[29] = dict(combat_mode='artillery_deploy',
            move_position=(-302., -9.671, -354.))
        self.command = dict(combat_mode='artillery_hold',
            movement_intent=False, move_position=(-346.0144, -9.6313, -275.794))

    def test_normal_entry_never_builds_or_emits(self):
        with mock.patch.object(self.module, 'detailed_enabled', return_value=False), \
                mock.patch.object(logs, 'write_json_record') as writer:
            self.runtime._log_spg_position_state(self.state, self.command, 0.)
        writer.assert_not_called()
        self.assertNotIn('_spg_position_state_log_at', self.state)

    def test_compact_state_survives_bulk_budget_without_changing_command(self):
        original = dict(self.command)
        with mock.patch.object(self.module, 'detailed_enabled', return_value=True), \
                mock.patch.object(logs, '_detail_budget', dict(
                    start=0., session=logs.DETAIL_SESSION_BYTES, window=0,
                    dropped=0, notice=False)), \
                mock.patch.object(logs, 'write_json_record') as writer:
            for now in (0., 1., 29., 30., 31.):
                self.runtime._log_spg_position_state(self.state, self.command, now)
        self.assertEqual(2, writer.call_count)
        label, row = writer.call_args.args
        self.assertEqual('SPG POSITION STATE', label)
        self.assertNotIn(label, logs.DETAIL_LABELS)
        self.assertEqual('artillery_deploy', row['received_mode'])
        self.assertEqual('artillery_hold', row['final_mode'])
        self.assertEqual('replacement', row['zone'])
        self.assertEqual(2., row['radius'])
        self.assertEqual(original, self.command)
