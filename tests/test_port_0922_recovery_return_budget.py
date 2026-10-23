"""Recovery cannot erase realised forward progress or renew it by oscillation."""
import math
import unittest
from unittest import mock
from gui.mods.offline_lan_0922.ai import recovery_travel
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.ai.driver import short_escape_remaining


class RecoveryReturnBudgetTests(unittest.TestCase):
    def setUp(self):
        self.adapter = BotAdapter('100_thepit', 1)
        self.state = dict(id=7, yaw=0., half_length=3.5)
        self.command = dict(throttle=1., recovery_mode='wreck_push', turn=0.)
        self.core = mock.patch.object(self.adapter, '_unbounded_drive_order_controls',
                                      side_effect=lambda *args: dict(self.command))
        self.core.start()
        self.addCleanup(self.core.stop)

    def sample(self, z, x=0., order=None):
        return self.adapter._drive_order_controls(7, self.state, (x, 0., z),
                                                  order or {}, lambda *args: True)

    def test_four_real_forward_metres_allow_only_two_reverse_metres(self):
        self.sample(0.)
        self.command.update(throttle=-1., recovery_mode='reverse_turn')
        command = self.sample(4.)
        self.assertEqual('short_reverse_escape', command['recovery_mode'])
        self.assertEqual(2., command['recovery_probe_length'])
        # Exercise the shipping runtime's cached-action endpoint contract.
        self.assertAlmostEqual(0., short_escape_remaining(command, (0., 0., 2.)))
        self.assertEqual(1., self.sample(3.)['recovery_probe_length'])
        self.assertEqual(0., self.sample(2.)['throttle'])
        self.assertTrue(self.sample(2.)['brake'])

    def test_return_to_same_forward_endpoint_cannot_buy_another_reverse(self):
        self.sample(0.)
        self.command.update(throttle=-1., recovery_mode='contact_escape')
        self.sample(4.)
        self.sample(2.)
        self.command.update(throttle=1., recovery_mode='wreck_push')
        self.sample(2.)
        self.command.update(throttle=-1., recovery_mode='reverse_turn')
        self.assertEqual(0., self.sample(4., order=dict(route_id='another', route_index=9))['throttle'])

    def test_blocked_forward_only_earns_realised_credit(self):
        self.sample(0.)
        self.command.update(throttle=-1., recovery_mode='short_reverse_escape')
        self.assertAlmostEqual(.125, self.sample(.25)['recovery_probe_length'])

    def test_budget_never_extends_an_already_proved_short_exit(self):
        self.sample(0.)
        self.command.update(throttle=-1., recovery_mode='short_reverse_escape',
            recovery_probe_origin=(0.,0.,4.), recovery_probe_yaw=math.pi,
            recovery_probe_length=1., recovery_probe_distance=1.)
        self.assertAlmostEqual(1., self.sample(4.)['recovery_probe_length'])
        self.assertAlmostEqual(.5, self.sample(3.5)['recovery_probe_length'])

    def test_ordinary_forward_travel_does_not_limit_an_independent_first_recovery(self):
        self.command['recovery_mode']='drive'
        self.sample(0.)
        self.command.update(throttle=-1., recovery_mode='reverse_turn')
        self.assertNotIn('backtrack_budget',self.sample(4.))

    def test_live_traffic_does_not_start_a_wreck_return_budget(self):
        for change in ('moved', 'pivot', 'gone'):
            self.adapter._recovery_travel.clear()
            self.state.update(yaw=0., neighbours=[dict(id=8,alive=True,position=(2.,0.,0.))])
            self.adapter._contact_escapes[7] = dict(peer=8,peer_alive=True)
            self.command.update(throttle=1.,recovery_mode='contact_escape')
            self.sample(0.)
            self.command.update(throttle=-1.,recovery_mode='reverse_turn')
            self.assertNotIn('backtrack_budget',self.sample(4.))
            if change == 'moved':self.state['neighbours'][0]['position']=(4.,0.,0.)
            elif change == 'pivot':self.state['yaw']=.5
            else:self.state['neighbours']=[]
            self.assertNotIn('backtrack_budget',self.sample(4.),change)

    def test_rotation_and_no_forward_motion_do_not_invent_credit(self):
        self.sample(0.)
        self.state['yaw'] = 1.
        self.command.update(throttle=-1., recovery_mode='reverse_turn')
        self.assertNotIn('backtrack_budget', self.sample(0.))

    def test_independent_rear_exit_and_tactical_withdrawal_stay_legal(self):
        self.sample(0.)
        self.command.update(throttle=-1., recovery_mode='reverse_withdraw')
        self.assertNotIn('backtrack_budget', self.sample(4.))
        self.state['yaw'] = math.pi
        self.command['recovery_mode'] = 'reverse_turn'
        self.assertNotIn('backtrack_budget', self.sample(4.))

    def test_departure_releases_pocket_but_route_switch_does_not(self):
        memory = recovery_travel.observe(None, (0., 0., 0.), 0., 8.5)
        memory['throttle'] = 1.
        memory = recovery_travel.observe(memory, (0., 0., 4.), 0., 8.5)
        self.assertEqual(2., recovery_travel.remaining(memory))
        memory = recovery_travel.observe(memory, (9., 0., 4.), 0., 8.5)
        self.assertIsNone(recovery_travel.remaining(memory))

    def test_forget_retires_budget_with_the_bot(self):
        self.sample(0.)
        self.adapter.forget(7)
        self.assertNotIn(7, self.adapter._recovery_travel)


class RecoveryPocketLogTests(unittest.TestCase):
    def test_diagnostic_summary_is_bounded_and_basic_mode_does_not_sample(self):
        import test_port_0922_bot_runtime as fixture
        harness = fixture.BotRuntimeTests()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        runtime = harness.runtime
        state = dict(id=7, x=0., y=0., z=0.)
        command = dict(movement_intent=True, recovery_mode='reverse_turn')
        from gui.mods.offline_lan_0922 import native_input_diagnostics as logs
        with mock.patch.object(harness.module, 'detailed_enabled', return_value=False), \
                mock.patch.object(logs, 'write_json_record') as writer:
            runtime._log_recovery_pocket(state, command, {}, 0.)
            self.assertNotIn('_recovery_pocket_log', state)
            writer.assert_not_called()
        with mock.patch.object(harness.module, 'detailed_enabled', return_value=True), \
                mock.patch.object(logs, 'write_json_record') as writer:
            for now in (0., 14., 15., 16., 29., 30.):
                runtime._log_recovery_pocket(state, command, dict(water=False), now)
            self.assertEqual(2, writer.call_count)
            self.assertEqual('BOT RECOVERY POCKET', writer.call_args.args[0])
            self.assertEqual(30., writer.call_args.args[1]['age'])

