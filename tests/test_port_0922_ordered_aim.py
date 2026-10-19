"""Ordered aim preference, retained points, bounded work and moving evidence."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.aim_search import OrderedSearch, stale_reason


class OrderedAimTests(unittest.TestCase):
    def setUp(self):
        self.search = OrderedSearch(9)
        self.origin = (0., 2., 0.)
        self.points = [('hull' if i < 5 else 'turret', (float(i), 2., 100.))
                       for i in range(9)]
        self.pose = dict(yaw=0., pitch=0., roll=0., turret_yaw=0.)
        self.calls = []
        self.good = {0, 1}

    def step(self, now=0., selected=None):
        def probe(i, point):
            self.calls.append(i)
            return dict(clear=True, score=100. if i in self.good else 0.)
        return self.search.step(self.origin, self.points, self.pose, 0,
                                now, selected, probe)

    def test_lower_hull_is_first_and_current_positive_is_retained(self):
        index, receipt = self.step()
        self.assertEqual(0, index)
        self.assertLessEqual(len(self.calls), 2)
        self.calls[:] = []
        self.assertEqual(1, self.step(.1, selected=1)[0])
        self.assertEqual([1], self.calls)

    def test_nine_points_finish_without_restarting_first_pair(self):
        self.good = {8}
        for now in (0., .01, .02, .03, .04, .05):
            before = len(self.calls)
            index, receipt = self.step(now)
            self.assertLessEqual(len(self.calls)-before, 2)
            if index is not None:
                break
        self.assertEqual(8, index)
        self.assertEqual(set(range(9)), set(self.calls))

    def test_continuous_movement_does_not_starve_unvisited_candidates(self):
        self.good = set()
        for n in range(12):
            self.origin = (n * 1., 2., 0.)
            self.step(n * .2)
        self.assertEqual(set(range(9)), set(self.calls))

    def test_slow_worker_can_finish_before_negative_evidence_expires(self):
        self.good = {8}
        for n in range(12):
            index, receipt = self.step(n * .2)
            if index is not None: break
        self.assertEqual(8, index)
        self.assertLessEqual(n, 6)

    def test_a_new_obstacle_cannot_reuse_an_unchecked_positive_neighbour(self):
        self.assertEqual(0, self.step()[0])
        self.assertGreater(self.search.rows[1]['score'], 0.)
        selected, receipt = self.search.step(self.origin, self.points, self.pose,
            0, .1, 0, lambda i,p: dict(clear=False, score=None))
        self.assertIsNone(selected)

    def test_partial_search_is_not_a_completed_wall_verdict(self):
        search = OrderedSearch(9)
        for n in range(5):
            unused, receipt = search.step(self.origin, self.points, self.pose,
                0, n*.01, None, lambda i,p: dict(clear=False, score=None))
            self.assertEqual('searching' if n < 4 else 'blocked', receipt['outcome'])

    def test_a_and_b_have_independent_progress(self):
        self.good = set()
        self.step()
        other = OrderedSearch(9)
        self.assertEqual(0, other.cursor)
        self.assertEqual(2, self.search.cursor)

    def test_moving_target_reopens_earlier_failed_point(self):
        self.good = {8}
        for n in range(4): self.step(n * .01)
        self.points = [(part, (p[0]+1., p[1], p[2])) for part, p in self.points]
        self.good = {0, 8}
        for n in range(5):
            index, receipt = self.step(.1+n*.01)
            if index is not None: break
        self.assertEqual(0, index)

    def test_unknown_armour_is_exposed_fallback_not_positive_proof(self):
        for n in range(5):
            index, receipt = self.search.step(self.origin, self.points, self.pose,
                0, n*.01, None, lambda i,p: dict(clear=True, score=None))
        self.assertEqual(0, index)
        self.assertEqual('exposed_fallback', receipt['outcome'])

    def test_cumulative_movement_angle_shell_and_age_invalidate_evidence(self):
        self.step()
        row = self.search.rows[0]
        args = (self.points[0][1], self.pose, 'hull', .1, 0)
        self.assertIsNone(stale_reason(row, (.4, 2., 0.), *args))
        self.assertEqual('source_moved', stale_reason(row, (.6, 2., 0.), *args))
        for key in ('yaw', 'pitch', 'roll'):
            pose = dict(self.pose, **{key: math.radians(4.)})
            self.assertEqual('pose_changed', stale_reason(row, self.origin,
                self.points[0][1], pose, 'hull', .1, 0))
        self.assertEqual('age', stale_reason(row, self.origin,
            self.points[0][1], self.pose, 'hull', .5, 0))
        self.assertEqual('shell_changed', stale_reason(row, self.origin,
            self.points[0][1], self.pose, 'hull', .1, 1))


if __name__ == '__main__':
    unittest.main()
