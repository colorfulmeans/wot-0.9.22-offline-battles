"""Recovery keeps physical exit proofs without cumulative travel quotas."""
import unittest
from unittest import mock
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter


class RecoveryReturnBudgetTests(unittest.TestCase):
    def test_sti_centimetre_push_does_not_revoke_a_proved_reverse_exit(self):
        adapter = BotAdapter('34_redshire', 1)
        state = dict(id=17, slot=1, team=1, yaw=0., half_length=3.28, dt=.1,
                     speed=0., neighbours=[])
        strategic = dict(combat_mode='route', move_position=(0.,0.,-20.))
        for cycle in range(4):
            for z in (0., .0798, .21955, .1404, -1., -2.):
                state['position'] = (0.,0.,z)
                with mock.patch.object(adapter.driver, 'drive', return_value=dict(
                        throttle=-1., turn=0., target_yaw=0., recovery_mode='reverse_turn')):
                    command = adapter._drive_order_controls(17,state,state['position'],
                                                           strategic,lambda *a: True)
                self.assertEqual(-1.,command['throttle'], (cycle,z))
                self.assertNotIn('backtrack_budget',command)
                self.assertNotIn('navigation_replan',command)

    def test_short_exit_still_uses_real_collision_proofs(self):
        adapter=BotAdapter('34_redshire',1)
        memory=adapter.driver._state(17,0,(0.,0.,0.))
        blocked=adapter.driver._short_escape(memory,(0.,0.,0.),0.,0.,.1,0.,0.,[],
                                             lambda *a:False,3.28,1.61)
        self.assertIsNone(blocked)
        admitted=adapter.driver._short_escape(memory,(0.,0.,0.),0.,0.,.1,0.,0.,[],
            lambda heading,*a: __import__('math').cos(heading)<-.5,3.28,1.61)
        self.assertIsNotNone(admitted)
        self.assertLess(admitted['throttle'],0.)


class RecoveryPocketLogTests(unittest.TestCase):
    def test_diagnostic_summary_is_bounded_and_basic_mode_does_not_sample(self):
        import test_port_0922_bot_runtime as fixture
        harness = fixture.BotRuntimeTests()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        runtime = harness.runtime
        state = dict(id=7, x=0., y=0., z=0., yaw=1., speed=2.,
            _execution_window={'actions': [{'outcome': {
                'at': 29., 'yaw': 0.5, 'final': [0., 0., 1.],
                'unbounded_history': list(range(10000))}}]})
        command = dict(movement_intent=True, recovery_mode='reverse_turn',
                       throttle=-1., turn=1., forward_blocked_by=19)
        from gui.mods.offline_lan_0922 import native_input_diagnostics as logs
        with mock.patch.object(harness.module, 'detailed_enabled', return_value=False), \
                mock.patch.object(logs, 'write_json_record') as writer:
            runtime._log_recovery_pocket(state, command, {}, 0.)
            self.assertNotIn('_recovery_pocket_log', state)
            writer.assert_not_called()
        with mock.patch.object(harness.module, 'detailed_enabled', return_value=True), \
                mock.patch.object(logs, 'write_json_record') as writer:
            for now in (0., 14., 15., 16., 29., 30.):
                runtime._log_recovery_pocket(state, command, dict(water=False), now, [0., 0.])
            self.assertEqual(2, writer.call_count)
            self.assertEqual('BOT RECOVERY POCKET', writer.call_args.args[0])
            self.assertEqual(30., writer.call_args.args[1]['age'])
            row = writer.call_args.args[1]
            self.assertEqual([-1., 1.], row['requested_controls'])
            self.assertEqual([0., 0.], row['applied_controls'])
            self.assertEqual([19, None], row['blockers'])
            self.assertEqual(0.5, row['last_execution']['yaw'])
            self.assertNotIn('unbounded_history', row['last_execution'])

