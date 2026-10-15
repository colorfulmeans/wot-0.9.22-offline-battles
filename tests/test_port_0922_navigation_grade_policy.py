"""The requested 25-degree route policy is independent of physical grip."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.ai import driver
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
from gui.mods.offline_lan_0922 import vehicle_physics


class NavigationGradePolicyTests(unittest.TestCase):
    def test_uphill_and_downhill_have_one_25_degree_limit(self):
        grid = TerrainGrid(lambda x, z, hint: 0.)
        self.assertAlmostEqual(math.tan(math.radians(25.)), grid.max_grade_up)
        self.assertEqual(grid.max_grade_up, grid.max_grade_down)

    def test_straight_segments_reject_both_steep_directions(self):
        for degrees, admitted in ((22.5, True), (24.99, True),
                                  (25.01, False), (26., False), (27.5, False)):
            for sign in (-1., 1.):
                with self.subTest(degrees=degrees, sign=sign):
                    grade = sign * math.tan(math.radians(degrees))
                    grid = TerrainGrid(lambda x, z, hint: grade * z,
                                       cell_size=4.)
                    self.assertEqual(admitted, grid.segment_clear(
                        (0., 0., 0.), (0., grade * 20., 20.)))

    def test_alignment_still_starts_at_22_point_5_and_45_degree_bend(self):
        self.assertAlmostEqual(math.tan(math.radians(22.5)), driver.SLOPE_ALIGNMENT_GRADE)
        self.assertAlmostEqual(math.radians(45.), driver.SLOPE_ALIGNMENT_TURN)
        for degrees, brake in ((22., False), (23., True), (24.9, True)):
            for sign in (-1., 1.):
                height = sign * 100. * math.tan(math.radians(degrees))
                command = driver.LocalDriver().drive(
                    11, 0, (0., 0., 0.), -math.radians(50.), 0., .1,
                    (0., height, 100.), (), lambda *unused: True)
                self.assertEqual(brake, command['brake'])
                self.assertEqual(0. if brake else 1., command['throttle'])

    def test_grip_and_slip_calibration_are_not_changed_by_route_policy(self):
        self.assertAlmostEqual(math.cos(math.radians(27.5)),
                               vehicle_physics.SLOPE_GRIP_LNG_FULL_Y)
        self.assertAlmostEqual(math.tan(math.radians(27.5)),
                               vehicle_physics.SLIP_THRESHOLD_TAN)
        self.assertEqual(1., vehicle_physics.longitudinal_slope_grip(math.radians(26.)))
        self.assertLess(driver.NAVIGATION_MAX_GRADE, vehicle_physics.SLIP_THRESHOLD_TAN)


if __name__ == '__main__':
    unittest.main()
