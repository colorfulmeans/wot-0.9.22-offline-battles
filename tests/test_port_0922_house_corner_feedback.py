"""Strv 81 mixed pivot/translation refusal from the 032606 report."""
import math
import unittest
from test_port_0922_bot_combat_manoeuvre import LocalActionFeedbackTests


class HouseCornerTests(unittest.TestCase):
    setUp = LocalActionFeedbackTests.setUp

    def rows(self):
        # The one permitted pivot is at -1.4093, while its forward hull lane
        # hits the house. The other headings have hard native sweep refusals.
        heading = -1.4092995727111672
        return [dict(self.proof, yaw=heading+0.42),
            dict(kind='rotation', yaw=heading+0.42, clear=False,
                 reason='local_sweep_blocked'),
            dict(kind='rotation', yaw=heading, clear=True, reason='local_sweep_clear'),
            dict(kind='direction', yaw=heading, clear=False,
                 reason='planning_collision', native_probe=dict(collision=True))]

    def test_clear_pivot_blocked_translation_retires_only_this_bots_connector(self):
        for now in (10., 10.3, 10.6, 10.9, 11.2):
            self.runtime._report_blocked_planner(self.position, self.command,
                {}, self.state, now, self.rows())
        self.assertTrue(self.state['_planner_blocked_handoff']['local_actions_exhausted'])
        self.assertEqual(1, self.nav.bot_states[20]['blocked_step_replans'])
        self.assertEqual({}, self.nav.grid._failed_edges)
        self.assertTrue(self.nav.bot_segment_penalized(20, self.position, self.goal, 11.3))
        self.assertFalse(self.nav.bot_segment_penalized(21, self.position, self.goal, 11.3))
        self.assertFalse(self.nav.bot_segment_penalized(20, self.position, self.goal, 30.))

    def test_available_unknown_or_other_heading_does_not_exhaust(self):
        for change in (dict(clear=True), dict(clear=None), dict(yaw=0.2),
                       dict(decision_id=('stale',)), dict(sampled_at=-1.0),
                       dict(native_probe=dict(collision=True, deferred=True)),
                       dict(native_probe=dict(collision=True, probe_failed=True))):
            rows = self.rows()
            rows[-1].update(change)
            self.runtime._report_blocked_planner(self.position, self.command,
                {}, self.state, 10., rows)
            self.assertFalse(self.state['_planner_blocked_handoff']['local_actions_exhausted'])
        self.assertFalse(self.nav.bot_failed_edges)


if __name__ == '__main__':
    unittest.main()
