"""Replay the complete-arc/refusal mismatch captured for WZ-111 5A."""
import copy
import json
from pathlib import Path
import unittest
from unittest import mock

from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator
import test_port_0922_bot_combat_manoeuvre as feedback_fixture


class CompletePivotHandoffTests(unittest.TestCase):
    def setUp(self):
        feedback_fixture.LocalActionFeedbackTests.setUp(self)
        root = Path(__file__).resolve().parents[1]
        self.capture = json.loads((root / 'tests/fixtures/thepit_1115a_blocked_20261024.json').read_bytes())
        self.position = tuple(self.capture['position'])
        self.goal = tuple(self.capture['target'])
        self.nav = TerrainNavigator(lambda *unused: 0.26,
            baked_graph=json.loads((root / 'navgraphs/100_thepit.json').read_bytes()))
        self.runtime.navigator = self.nav
        self.nav.bot_states[19] = {}
        self.state = dict(id=19, yaw=self.capture['yaw'])
        self.command = dict(move_position=self.goal, movement_intent=True,
                            recovery_mode='blocked')

    def search(self, rows):
        rotations = [r for r in rows if r['kind'] == 'rotation']
        calls = []
        def pose(yaw):
            matches = [r for r in rotations if abs(r['yaw'] - yaw) < 1e-6]
            self.assertTrue(matches, 'replay requested an uncaptured native query')
            calls.append(matches[-1])
            return matches[-1]['clear']
        driver = LocalDriver()
        result = driver._partial_pivot(pose, self.capture['yaw'],
                                      self.capture['recovery_side'], 1., 1.)
        return result, driver._last_partial_pivot_search, calls

    def rows_at(self, now):
        rows = copy.deepcopy(self.capture['verdicts'])
        for row in rows:
            row['sampled_at'] = now
            if 'native_sweep' in row:
                row['native_sweep']['at'] = now
        return rows

    def test_full_arc_failure_retires_private_connector_despite_clear_sample(self):
        result, search, calls = self.search(self.capture['verdicts'])
        self.assertIsNone(result)
        self.assertEqual(7, len(calls))
        self.assertEqual(1, sum(row['clear'] for row in calls))
        self.assertEqual(6, len(search['candidates']))
        self.command['partial_pivot_search'] = search
        for now in (10., 10.3, 10.6, 10.9, 11.2):
            self.runtime._report_blocked_planner(self.position, self.command,
                {}, self.state, now, self.rows_at(now))
        handoff = self.state['_planner_blocked_handoff']
        self.assertTrue(handoff.get('complete_pivot_arcs_exhausted', False))
        self.assertEqual('local_actions_exhausted', handoff['reason'])
        self.assertEqual(1, self.nav.bot_states[19]['blocked_step_replans'])
        self.assertEqual({}, self.nav.grid._failed_edges)
        self.assertTrue(self.nav.bot_segment_penalized(19, self.position, self.goal, 11.3))
        self.assertFalse(self.nav.bot_segment_penalized(18, self.position, self.goal, 11.3))
        # An ordinary replan/route switch must retain the failed near connector.
        self.nav.request_replan(19, self.position, 11.4)
        self.assertIn(self.goal, self.nav._active_local_target_refusals(19, 11.4))
        self.assertFalse(self.nav.bot_segment_penalized(19, self.position, self.goal, 30.))

    def test_unknown_stale_traffic_only_or_incomplete_proof_cannot_retire(self):
        unused, search, unused_calls = self.search(self.capture['verdicts'])
        for kind in ('unknown', 'stale', 'other_decision', 'traffic_only', 'incomplete', 'old_yaw'):
            with self.subTest(kind=kind):
                rows = self.rows_at(10.)
                proof = copy.deepcopy(search)
                if kind == 'unknown':
                    for row in rows:
                        if row['kind'] == 'rotation' and row['clear'] is False:
                            row['reason'] = 'rotation_callback_exception'
                elif kind == 'stale':
                    for row in rows:
                        row['sampled_at'] = 9.
                elif kind == 'other_decision':
                    for row in rows:
                        if row['kind'] == 'rotation':
                            row['decision_id'] = ['previous_decision']
                elif kind == 'traffic_only':
                    rows = [r for r in rows if r['kind'] != 'local_sweep']
                elif kind == 'incomplete':
                    proof['candidates'].pop()
                else:
                    proof['yaw'] += 0.1
                command = dict(self.command, partial_pivot_search=proof)
                self.runtime._report_blocked_planner(self.position, command,
                    {}, self.state, 10., rows)
                self.assertFalse(self.state['_planner_blocked_handoff'].get('complete_pivot_arcs_exhausted', False))
                self.assertFalse(self.nav.bot_failed_edges)

    def test_far_camera_cadence_accumulates_fresh_failures_and_stale_gap_resets(self):
        unused, proof, unused_calls = self.search(self.capture['verdicts'])
        command = dict(self.command, partial_pivot_search=proof)
        for now in (10., 10.6, 11.2, 11.8, 12.4):
            self.runtime._report_blocked_planner(self.position, command,
                {}, self.state, now, self.rows_at(now), observation_interval=0.6)
        self.assertEqual(1, self.nav.bot_states[19]['blocked_step_replans'])
        self.nav.clear_blocked_contact(19)
        self.nav.bot_states[19]['blocked_step_escalated_until'] = 0.
        for now in (30., 32., 34., 36.):
            self.runtime._report_blocked_planner(self.position, command,
                {}, self.state, now, self.rows_at(now), observation_interval=0.6)
        self.assertEqual(1, self.nav.bot_states[19]['blocked_step_tracker']['count'])
        self.assertEqual(1, self.nav.bot_states[19]['blocked_step_replans'])

    def test_usable_complete_arc_is_preserved_without_extra_probes(self):
        driver = LocalDriver()
        calls = []
        result = driver._partial_pivot(lambda yaw: calls.append(yaw) or True,
                                      0., 1., 2., 0.15)
        self.assertEqual('partial_pivot_recovery', result['recovery_mode'])
        self.assertEqual(4, len(calls))
        self.assertEqual('selected', driver._last_partial_pivot_search['reason'])

    def test_unavailable_pivot_does_not_reuse_previous_exhaustion(self):
        driver = LocalDriver()
        driver._partial_pivot(lambda yaw: False, 0., 1., 1., 1.)
        self.assertIsNone(driver._partial_pivot(None, None, 1., None, 1.))
        self.assertEqual('unavailable', driver._last_partial_pivot_search['reason'])
        self.assertEqual([], driver._last_partial_pivot_search['candidates'])

    def test_adapter_preserves_the_complete_action_proof(self):
        unused, proof, unused_calls = self.search(self.capture['verdicts'])
        adapter = BotAdapter('100_thepit', 1)
        local = dict(throttle=0., turn=0., target_yaw=self.capture['yaw'],
                     recovery_mode='blocked', partial_pivot_search=proof)
        state = dict(self.state, slot=0, team=2, speed=0., dt=0.1)
        with mock.patch.object(adapter.driver, 'drive', return_value=local):
            command = adapter._drive_order_controls(19, state,
                self.position, dict(combat_mode='route', move_position=self.goal),
                lambda *unused: True)
        self.assertIs(proof, command['partial_pivot_search'])


if __name__ == '__main__':
    unittest.main()
