"""One admitted clock for player and Bot low-speed governor wear."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922.equipment_mechanics import governor_wear


class GovernorClockTests(unittest.TestCase):
    def test_split_ticks_equal_one_slow_frame(self):
        elapsed, loss = 0, 0
        for unused in range(25):
            elapsed, delta = governor_wear(elapsed, .1, 2, 2, 10)
            loss += delta
        self.assertAlmostEqual(.5, elapsed)
        self.assertEqual(4, loss)
        self.assertEqual((.5, 4), governor_wear(0, 2.5, 2, 2, 10))

    def test_disabling_and_half_speed_clear_fractional_wear(self):
        for rate, speed in ((0, 2), (2, 5), (2, -5)):
            self.assertEqual((0, 0), governor_wear(.9, .2, rate, speed, 10))


if __name__ == '__main__': unittest.main()
