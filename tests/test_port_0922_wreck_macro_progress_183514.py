"""404 report: successful wreck motion must survive the macro gate clock."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from test_port_0922_server_bot_ai import BotPlanner, _bot, _route, _state
import test_port_0922_navigation_handoff_140346 as transfer_fixture
import test_port_0922_wreck_contact_recovery as push_fixture


class PhysicalGateProgressTests(unittest.TestCase):
    def setUp(self):
        self.planner = BotPlanner()
        self.route = _route('road', [(0, 0, False), (0, 100, False), (0, 200, False)])
        self.manifest = [_bot(17, 1, 0, self.route, 'heavyTank')]
        self.state = _state(17, 1, 0, 0)
        self.state.update(world_pose=True, route_wreck_blocked=True)
        self.bot = self.planner._alive_bots(self.manifest, [self.state])[0]
        self.state = self.bot['state']
        self.planner._route_states[17] = dict(route_id='road', index=1)

    def step(self, now, x=0., z=0., goal=None):
        self.state.update(x=x, z=z)
        order = dict(route_id='road', route_index=1, combat_mode='route',
                     move_position=goal or self.route['waypoints'][1])
        self.planner._reroute_wreck_stall(order, self.bot, self.manifest, now)
        return order

    def test_slow_continuing_push_does_not_skip_or_change_gate(self):
        self.step(0)
        renewed = 0
        for now in range(1, 121):
            order = self.step(now, z=now*.1)
            renewed += order['route_attempt']['action'] == 'physical_progress_renewed'
            self.assertEqual(1, order['route_index'])
        self.assertGreater(renewed, 15)
        self.assertLess(order['route_attempt']['elapsed'], 6.)

    def test_real_stop_after_success_keeps_original_twenty_second_skip(self):
        self.step(0)
        self.assertEqual('physical_progress_renewed', self.step(10, z=1.)['route_attempt']['action'])
        self.assertEqual(1, self.step(29.9, z=1.)['route_index'])
        self.assertEqual('skip_gate', self.step(30., z=1.)['route_attempt']['action'])

    def test_reverse_then_return_does_not_renew_twice(self):
        self.step(0)
        self.step(1, z=1.)
        for now in range(2, 21):
            self.step(now, z=0. if now%2 else 1.)
        self.assertEqual('skip_gate', self.step(21., z=1.)['route_attempt']['action'])

    def test_lateral_orbit_and_stationary_contact_flicker_still_expire(self):
        self.step(0)
        for now in range(1, 20):
            self.state['route_wreck_blocked'] = bool(now%2)
            self.step(now, x=9. if now%2 else -9.)
        self.assertEqual('skip_gate', self.step(20.)['route_attempt']['action'])

    def test_changed_local_goal_cannot_fabricate_physical_progress(self):
        self.step(0)
        changed = dict(x=0., y=0., z=90.)
        order = self.step(10, goal=changed)
        self.assertEqual(0., order['route_attempt']['improvement'])
        self.assertEqual('skip_gate', self.step(20, goal=changed)['route_attempt']['action'])

    def test_nonphysical_small_motion_keeps_existing_progress_threshold(self):
        self.state['route_wreck_blocked'] = False
        self.step(0)
        order = self.step(10, z=1.)
        self.assertEqual(10., order['route_attempt']['elapsed'])
        self.assertEqual('skip_gate', self.step(20., z=1.)['route_attempt']['action'])


class RouteEvidenceTests(unittest.TestCase):
    def test_macro_renewal_is_readable_from_plain_server_log(self):
        from read_native_evidence import parse_lines
        result = parse_lines(['[18:31:47] BOT ROUTE ATTEMPT '
            '{"bot":3,"action":"physical_progress_renewed","improvement":0.6}'],
            'server.log')
        self.assertEqual([], result['issues'])
        self.assertEqual('physical_progress_renewed', result['records'][0]['data']['action'])

    def test_pressure_input_sources_survive_assignment_record(self):
        p, bots, contacts = transfer_fixture.RouteTransferTests().scene(.6, 3.)
        for index, contact in enumerate(contacts):
            contact.update(id=index+100, target_kind='bot', visible=True)
        p._rebalance_routes(1, bots, contacts, 1.)
        receipt = p._route_assignment_receipts[41]['selection']
        self.assertEqual(4, len(receipt['contact_inputs']))
        self.assertEqual(4, len(receipt['contributor_inputs']))
        self.assertEqual(100, receipt['contact_inputs'][0]['target_id'])
        self.assertEqual('bot', receipt['contact_inputs'][0]['target_kind'])
        self.assertIn(41, receipt['contact_inputs'][0]['known_by'])

    def test_moving_rejoin_records_each_rear_point_skip(self):
        p = BotPlanner()
        route = _route('road', [(0, 0, False), (0, 50, False), (0, 100, False)])
        bot = p._alive_bots([_bot(17, 1, 0, route, 'heavyTank')],
                           [_state(17, 1, 0, 40)])[0]
        bot['state'].update(speed=2., yaw=3.141592653589793)
        p._route(bot, 10.)
        receipt = p._route_states[17]['progress_receipt']['entry']
        self.assertEqual(10., receipt['sampled_at'])
        self.assertEqual(2, receipt['selected_index'])
        self.assertTrue(receipt['skipped'])


class PushTerminalEvidenceTests(unittest.TestCase):
    def test_world_turn_refusal_reason_survives_next_exhausted_sample(self):
        fixture = push_fixture.WreckContactRecoveryTests()
        fixture.setUp()
        self.state = fixture.state
        self.decide = fixture.decide
        self.state['push_pose_clear'] = lambda yaw: False
        self.state['now'] = 10.
        first = self.decide()
        self.assertEqual('world_turn_refused', first['wreck_push']['terminal']['reason'])
        self.state['now'] = 11.
        later = self.decide()
        self.assertEqual(first['wreck_push']['terminal'], later['wreck_push']['terminal'])
        self.assertEqual(10., later['wreck_push']['terminal']['at'])
        fixture.order.update(combat_mode='hold', parking_phase='waiting', throttle_override=0.)
        parked = fixture.decide()
        self.assertNotIn('wreck_push', parked)
        self.assertEqual('world_turn_refused', parked['wreck_push_last_terminal']['reason'])
        fixture.adapter.forget(1)
        self.assertNotIn(1, fixture.adapter._wreck_last_terminal)

    def test_motor_timeout_keeps_first_reason_and_timestamp(self):
        fixture = push_fixture.WreckContactRecoveryTests()
        fixture.setUp()
        fixture.route()
        for frame in range(145):
            fixture.state['now'] = frame*.1
            command = fixture.decide()
        terminal = command['wreck_push']['terminal']
        self.assertIn(terminal['reason'], ('own_stalled', 'push_stalled'))
        self.assertLess(terminal['at'], 14.4)
        fixture.state['now'] = 50.
        self.assertEqual(terminal, fixture.decide()['wreck_push']['terminal'])


if __name__ == '__main__':
    unittest.main()
