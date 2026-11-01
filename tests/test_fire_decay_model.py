"""Community shape, native skill ratios, interval and injury continuity."""
import unittest
from gui.mods.offline_lan_0922 import fire_model


class FireDecayTests(unittest.TestCase):
    def run_fire(self, factor, step):
        progress = damage = seconds = 0
        while progress < 10 - 1.e-7:
            progress, loss, active, ended = fire_model.advance(progress, step, factor, 10000)
            damage += loss
            seconds += active
        return damage, seconds

    def test_native_skill_ratios_reduce_duration_and_total_damage(self):
        bare, seconds = self.run_fire(.57, .1)
        trained, trained_seconds = self.run_fire(1., .1)
        self.assertEqual(2500, bare)
        self.assertAlmostEqual(10., seconds)
        self.assertEqual(1425, trained)
        self.assertAlmostEqual(5.7, trained_seconds)

    def test_slow_frames_and_30hz_do_not_lose_damage(self):
        for factor in (.57, .785, 1., 1.215):
            self.assertEqual(self.run_fire(factor, 20)[0], self.run_fire(factor, 1./30)[0])

    def test_initial_fire_rate_is_not_reduced_by_skill(self):
        a = fire_model.advance(0, .01, .57, 1000000)[1]
        b = fire_model.advance(0, .01, 1., 1000000)[1]
        self.assertLessEqual(abs(a - b), 1)

    def test_damage_decreases_as_the_fire_ages(self):
        self.assertGreater(fire_model.advance(0, 1, .57, 10000)[1],
                           fire_model.advance(8, 1, .57, 10000)[1])

    def test_crew_injury_changes_future_decay_without_resetting_progress(self):
        p, unused, unused_time, ended = fire_model.advance(0, 2, 1., 10000)
        new, unused, active, ended = fire_model.advance(p, 2, .57, 10000)
        self.assertAlmostEqual(p + 2, new)
        self.assertFalse(ended)

    def test_reignition_starts_from_zero(self):
        end = fire_model.advance(10, 1, .57, 1000)
        fresh = fire_model.advance(0, 1, .57, 1000)
        self.assertEqual(0, end[1])
        self.assertGreater(fresh[1], 0)
        self.assertFalse(fresh[3])

    def test_rejects_invalid_rates(self):
        for factor in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                fire_model.advance(0, 1, factor, 1000)
