"""Rejection receipts observe existing checks without adding probes or policy."""
import unittest
from gui.mods.offline_lan_0922.ai.driver import LocalDriver


class DriverBlockEvidenceTests(unittest.TestCase):
    def test_every_queried_candidate_records_its_actual_short_circuit_stage(self):
        driver = LocalDriver()
        state = driver._state(24, 0, (0., 0., 0.))
        state['clock'] = 12.
        driver._rank_yaw_candidates = lambda *args: [(0., .1), (1., .2), (2., .3), (3., .4)]
        calls = []
        def pose(yaw):
            calls.append(('pose', yaw))
            return yaw != .1
        def clear(yaw):
            calls.append(('direction', yaw))
            return yaw != .2
        def occupied(position, yaw, *args, **kwargs):
            calls.append(('vehicle', yaw))
            return yaw == .3
        driver._static_hull_ahead = occupied
        self.assertEqual(.4, driver._choose_yaw(state, .4, clear,
            (0., 0., 0.), [], pose_clear=pose))
        self.assertEqual([('pose', .1), ('pose', .2), ('direction', .2),
                          ('pose', .3), ('direction', .3), ('vehicle', .3),
                          ('pose', .4), ('direction', .4), ('vehicle', .4)], calls)
        trace = state['heading_selection']
        self.assertEqual(12., trace['at'])
        self.assertEqual(['pose_rejected', 'world_rejected', 'static_hull_rejected', 'selected'],
                         [row['outcome'] for row in trace['candidates']])
        self.assertEqual(.4, trace['selected'])
        # A later selection replaces the receipt, including an all-pose denial.
        state['clock'] = 13.
        self.assertIsNone(driver._choose_yaw(state, .4, clear,
            (1., 0., 0.), [], pose_clear=lambda yaw: False))
        self.assertEqual(13., state['heading_selection']['at'])
        self.assertIsNone(state['heading_selection']['selected'])
        self.assertTrue(all(row['outcome'] == 'pose_rejected'
                            for row in state['heading_selection']['candidates']))

    def test_hold_clears_a_previous_block_without_changing_its_command(self):
        driver = LocalDriver()
        state = driver._state(24, 0, (0., 0., 0.))
        state['blocked_observation'] = dict(reason='old_block', at=0.)
        command = driver.drive(24, 0, (0., 0., 0.), 0., 0., .1,
            (0., 0., 0.), [], lambda *args: True, movement_intent=False)
        self.assertEqual(0., command['throttle'])
        self.assertEqual('not_blocked', state['blocked_observation']['reason'])
        self.assertEqual(state['clock'], state['blocked_observation']['at'])


if __name__ == '__main__':
    unittest.main()
