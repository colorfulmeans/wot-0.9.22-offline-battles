"""Published 9.6 probability mass, bounded cone and owner parity."""
import random
import unittest
from gui.mods.offline_lan_0922 import shot_dispersion


class ShotDispersionTests(unittest.TestCase):
    def test_published_ten_percent_central_zone_with_seeded_large_sample(self):
        rng = random.Random(9221513)
        values=[shot_dispersion.radius(1.,rng.gauss,rng.uniform) for i in range(100000)]
        self.assertTrue(all(0<=v<=1 for v in values))
        self.assertAlmostEqual(.10,sum(v<.1 for v in values)/len(values),delta=.003)
        self.assertGreater(sum(.1<=v<.2 for v in values)/len(values),.20)

    def test_rejected_central_sample_moves_only_to_adjacent_zone(self):
        values=iter((1.,.5))
        radius=shot_dispersion.radius(1.,lambda a,b:.01,lambda a,b:next(values))
        self.assertAlmostEqual(.15,radius)
