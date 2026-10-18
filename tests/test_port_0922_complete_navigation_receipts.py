"""Decision witnesses survive reuse and reach the final motion publication."""
import copy
import io
import json
import math
import unittest
import sys
from contextlib import redirect_stdout

import test_port_0922_bot_runtime as runtime_fixture
import test_port_0922_withdraw_receipts as lease_fixture
import test_port_0922_wreck_route_switch as route_fixture
sys.path.insert(0, str(runtime_fixture.ROOT / 'tools'))
from read_native_evidence import parse_lines


class RuntimeReceiptTests(unittest.TestCase):
    def setUp(self):
        self.fixture = runtime_fixture.BotRuntimeTests()
        self.fixture.setUp()
        self.runtime = self.fixture.runtime
        self.runtime.battle_start(self.fixture.start)

    def tearDown(self):
        self.fixture.tearDown()

    def test_cached_command_keeps_exact_nonempty_probe_and_original_time(self):
        self.runtime.update(.04, 1.)
        first = copy.deepcopy(self.runtime._decision_cache[11][3]['planning_receipt'])
        self.assertGreater(first['query_count'], 0)
        self.assertTrue(all(r['reason'] for r in first['queries']))
        self.runtime.update(.04, 1.04)
        self.assertEqual(1, len(self.fixture.adapters[0].calls))
        self.assertEqual(first['queries'], self.runtime.states[11]['_planning_verdicts'])
        command = self.runtime._decision_cache[11][3]
        observation = self.runtime._planning_observation(command, 1.04, 'cache_reused')
        self.assertEqual(first, observation['receipt'])
        self.assertAlmostEqual(.04, observation['age_seconds'])
        self.assertEqual('cache_reused', self.runtime.states[11]['_planning_disposition'])

    def test_refresh_creates_new_identity_without_mutating_old_witness(self):
        self.runtime.update(.04, 1.)
        old = self.runtime._decision_cache[11][3]['planning_receipt']
        saved = copy.deepcopy(old)
        self.runtime.update(.04, 1.30)
        new = self.runtime._decision_cache[11][3]['planning_receipt']
        self.assertNotEqual(old['id'], new['id'])
        self.assertEqual(saved, old)
        self.assertEqual(1.30, new['sampled_at'])

    def test_final_serialized_motion_links_cached_proof_and_actual_rollback(self):
        self.runtime.update(.04, 1.)
        command = self.runtime._decision_cache[11][3]
        state = self.runtime.states[11]
        state['_motion_stall_log'] = ((state['x'], state['y'], state['z']), -10.)
        state['_planning_disposition'] = 'cache_reused'
        output = io.StringIO()
        with redirect_stdout(output):
            self.runtime._log_motion_stall(state, command, 0., 0., False,
                                          dict(collision=True, slope=99.), 1.04)
            state['_motion_stall_pending'].update(dt=.04,world_speed=10.)
            state['speed']=10.
            origin=(state['x'],state['y'],state['z'])
            self.runtime._observe_near_goal_motion(state,origin,origin,1.04)
            self.runtime._finish_motion_stall(state, True, True,
                (state['x'], state['y'], state['z']), 1.04)
        parsed = parse_lines(output.getvalue().splitlines(), 'worker')
        self.assertEqual([], parsed['issues'])
        row = next(r['data'] for r in parsed['records'] if r['label'] == 'BOT MOTION')
        self.assertTrue(row['planning_verdicts'])
        self.assertEqual('cache_reused', row['planning_observation']['disposition'])
        execution = row['execution_receipt']
        self.assertEqual(row['planning_observation']['decision_id'], execution['decision_id'])
        self.assertEqual('after_contacts_and_support', execution['phase'])
        self.assertTrue(execution['pose_rollback'])
        self.assertTrue(execution['support_rollback'])
        self.assertFalse(execution['path_clear'])
        self.assertEqual(0., execution['horizontal_displacement'])
        velocity=execution['velocity_receipt']
        self.assertEqual(10.,velocity['scalar_speed'])
        self.assertEqual(10.,velocity['pre_contact_speed'])
        self.assertEqual([0.,0.],velocity['realized_velocity'])
        self.assertEqual(.04,velocity['dt'])
        self.assertEqual(1.04,row['near_goal_motion']['entered_arrival_at'])
        self.assertEqual(0.,row['near_goal_motion']['minimum_segment_distance'])

    def test_bounded_query_history_preserves_all_rejection_counts(self):
        receipt = dict(id=[5, 11, 1, 1.], sampled_at=1., query_count=0,
                       dropped_queries=0, queries=[], reason_counts={})
        for i in range(90):
            self.runtime._record_planning_verdict(receipt,
                dict(clear=False, reason='terrain_contact', distance=i))
        self.assertEqual(90, receipt['query_count'])
        self.assertEqual(42, receipt['dropped_queries'])
        self.assertEqual({'terrain_contact': 90}, receipt['reason_counts'])
        self.assertEqual(list(range(43, 91)), [r['query_index'] for r in receipt['queries']])

    def test_no_probe_and_same_callback_hold_are_explicit(self):
        self.fixture.adapters[0].decide = lambda *args: dict(throttle=0., turn=0., fire_allowed=False)
        self.runtime.update(.04, 1.)
        receipt = self.runtime._decision_cache[11][3]['planning_receipt']
        self.assertEqual(0, receipt['query_count'])
        self.assertEqual('planner_and_traffic_returned_without_world_query', receipt['not_queried_reason'])
        self.runtime._decision_cache.pop(11)
        self.runtime._refresh_control_this_step = False
        self.runtime._update_once(.04, 1.04, [])
        self.assertEqual('physical_hold', self.runtime.states[11]['_planning_disposition'])

    def test_direction_early_returns_retain_actual_query_or_nonquery_reason(self):
        cases = [
            (False, None, None, 'baked_motion_hazard'),
            (True, None, None, 'baked_corridor_clear'),
            (None, None, .5, 'native_probe_unavailable'),
            (None, dict(deferred=True), .5, 'native_probe_deferred'),
            (None, dict(clear=False, collision=True), .5, 'native_probe_rejected'),
            (None, dict(clear=False, reason='water'), .5, 'water'),
            (None, dict(clear=True), .5, 'native_probe_clear')]
        for index, (advisory, sample, distance, expected) in enumerate(cases):
            with self.subTest(reason=expected):
                self.runtime.battle_start(self.fixture.start)
                self.runtime._planner_corridor_clear = lambda *a, **kw: advisory
                self.runtime._probe_direction = lambda *a, **kw: sample
                def decide(state, clear):
                    clear(state['yaw'], distance)
                    return dict(throttle=0., turn=0., fire_allowed=False)
                self.runtime.adapter.decide = decide
                self.runtime.update(.04, float(index + 1))
                receipt = self.runtime._decision_cache[11][3]['planning_receipt']
                self.assertEqual(expected, receipt['queries'][0]['reason'])
                if sample is not None and advisory is None:
                    self.assertEqual(sample, receipt['queries'][0]['native_probe'])

    def test_moving_join_records_actual_path_at_bounded_cadence_without_probes(self):
        state = self.runtime.states[11]
        self.runtime._server_orders[11] = dict(route_join=True, route_id='west',
            route_index=2, move_position=(140., 0., -223.), combat_mode='route')
        key = ('west', 2)
        self.runtime.navigator.bot_states[11] = dict(path_key=key, index=1,
            planned_goal=(140., 0., -223.), navigation_status='safe')
        path = ((320., -14., 75.), (364., -13., -151.), (338., 6., -318.), (140., 0., -223.))
        self.runtime.navigator.paths[key] = path
        self.runtime._navigation_height_columns = lambda *args: self.fail('diagnostic recast')
        output = io.StringIO()
        with redirect_stdout(output):
            for now in (1., 1.04, 3., 4.):
                self.runtime._log_route_connection(state, {}, now)
        parsed = parse_lines(output.getvalue().splitlines(), 'worker')
        self.assertEqual([], parsed['issues'])
        rows = [r['data'] for r in parsed['records'] if r['label'] == 'BOT ROUTE CONNECTION']
        self.assertEqual(2, len(rows))
        self.assertEqual([list(p) for p in path], rows[0]['path_points'])
        self.assertEqual('west', rows[0]['order']['route_id'])
        self.assertEqual('existing_receipts_only', rows[0]['query_policy'])


class EscapeTerminalReceiptTests(unittest.TestCase):
    def setUp(self):
        self.fixture = lease_fixture.ShortEscapeReceiptTests()
        self.fixture.setUp()
        self.driver, self.state = self.fixture.driver, self.fixture.state

    def test_fresh_rejection_carries_actual_probe_reason(self):
        def reject(yaw, distance):
            reject.last_receipt = dict(reason='native_probe_rejected',
                native_probe=dict(collision=True, slope=99.), decision_id=[5, 25, 1, 1.])
            return False
        self.driver._short_escape(self.state, (0., 0., 0.), 0., 0., .1, .1, 0., [], reject, 3.5, 1.7)
        rows = self.state['short_escape_probes']
        self.assertEqual(6, len(rows))
        self.assertTrue(all(r['reason'] == 'native_probe_rejected' for r in rows))
        self.assertTrue(all(r['probe_receipt']['native_probe']['collision'] for r in rows))

    def test_each_non_query_release_has_reason_and_does_not_cast(self):
        for reason in ('distance_completed', 'lease_expired', 'heading_changed', 'realized_failure'):
            with self.subTest(reason=reason):
                self.setUp()
                self.fixture.select()
                position, yaw = (0., 0., 0.), 0.
                if reason == 'distance_completed': position = (0., 0., -2.)
                if reason == 'lease_expired': self.state['clock'] = 5.
                if reason == 'heading_changed': yaw = 1.
                if reason == 'realized_failure':
                    self.driver._short_failure_applies = lambda *args: True
                before = len(self.fixture.calls)
                self.assertIsNone(self.driver._retained_short_escape(self.state,
                    position, yaw, [], self.fixture.clear, 3.5, 1.7))
                self.assertEqual(before, len(self.fixture.calls))
                self.assertEqual(reason, self.state['short_escape_validation']['reason'])

    def test_retained_probe_rejection_and_vehicle_release_are_distinct(self):
        for blocked in (False, True):
            with self.subTest(vehicle=blocked):
                self.setUp(); self.fixture.select()
                def clear(yaw, distance):
                    clear.last_receipt = dict(reason='water' if not blocked else 'native_probe_clear')
                    return blocked
                self.driver._reverse_blocked_by_vehicle = lambda *args, **kwargs: 19
                self.assertIsNone(self.driver._retained_short_escape(self.state,
                    (0., 0., 0.), 0., [], clear, 3.5, 1.7))
                validation = self.state['short_escape_validation']
                self.assertEqual('vehicle_occupied' if blocked else 'water', validation['reason'])
                self.assertEqual(clear.last_receipt, validation['probe_receipt'])

    def test_callback_exception_does_not_reuse_previous_success_reason(self):
        def broken(yaw, distance):
            raise ValueError('native query failure')
        broken.last_receipt = dict(reason='clear_from_old_query')
        self.driver._short_escape(self.state, (0., 0., 0.), 0., 0., .1, .1, 0., [], broken, 3.5, 1.7)
        self.assertTrue(all(r['reason'] == 'direction_callback_exception'
                            for r in self.state['short_escape_probes']))
        self.assertTrue(all(r['probe_receipt']['exception_type'] == 'ValueError'
                            for r in self.state['short_escape_probes']))

    def test_diagnostic_metadata_failure_does_not_change_successful_probe(self):
        class Probe:
            def __call__(self, *args): return True
            @property
            def last_receipt(self): raise ValueError('diagnostic unavailable')
        self.assertTrue(self.driver._clear(Probe(), 0., 1.))
        self.assertEqual('callback_receipt_unavailable', self.driver._last_direction_receipt['reason'])


class LeaseAndEntryReceiptTests(unittest.TestCase):
    def test_covered_pressure_exit_updates_evidence_without_extending_deadline(self):
        f = lease_fixture.RouteLeaseEvidenceTests(); f.setUp()
        p = f.planner
        p._route_line_contributor = lambda *args: True
        contacts = [dict(position=dict(x=100., y=0., z=250.), health=1., max_health=1000.)]
        p._rebalance_routes(1, f.bots, contacts, 5.)
        lease = p._route_assignments[f.donor['id']]
        self.assertEqual(7., lease['until'])
        self.assertEqual('pressure_already_covered', lease['_lease_observation']['outcome'])
        p._rebalance_routes(1, f.bots, contacts, 5.5)
        self.assertEqual('rebalance_not_due', lease['_lease_check']['outcome'])
        self.assertEqual(5., lease['_lease_observation']['evaluated_at'])
        p._rebalance_routes(1, f.bots, contacts, 7.)
        previous = p._route_assignment_receipts[f.donor['id']]['previous_lease']
        self.assertEqual('pressure_already_covered', previous['observation']['outcome'])
        self.assertEqual('rebalance_not_due', previous['check']['outcome'])

    def test_route_switch_serializes_selected_entry_without_changing_existing_choice(self):
        f = route_fixture.WreckRouteSwitchTests(); f.setUp()
        f.orders(0.); f.orders(20.); orders = f.orders(40.)
        order = orders[17]
        self.assertEqual('rail', order['route_id'])
        receipt = order['route_assignment']['entry_selection']
        self.assertEqual('rail', receipt['selected_route'])
        self.assertEqual(order['route_index'], receipt['selected_index'])
        self.assertEqual(order['move_position'], receipt['selected_point'])
        self.assertTrue(receipt['candidates'])
        eligible = next(r for r in receipt['candidates'] if r['outcome'] == 'eligible')
        self.assertGreaterEqual(eligible['entry_distance'], 0.)
        self.assertEqual(receipt, json.loads(json.dumps(receipt)))


if __name__ == '__main__':
    unittest.main()
