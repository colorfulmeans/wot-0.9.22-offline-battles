"""Direction admission regressions from El Halluf build 101 report 220536.

Finite planar collision fixtures exercise the production probe's existing ray
budget and grade gate; they do not prove native Windows terrain behaviour.
"""
import unittest
from test_port_0922_battle_runtime import _runtime, _Vector, BattleRuntime


class DownhillDirectionTests(unittest.TestCase):
    def test_direction_probe_matches_navigation_grade_without_extra_samples(self):
        from gui.mods.offline_lan_0922 import vehicle_physics
        from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
        limit = vehicle_physics.SLIP_THRESHOLD_TAN
        # Report 220536: Patton/Skorpion's otherwise clear descending rays.
        for grade in (-0.412402153015, -0.426597595215, -0.50, 0.50):
            for distance in (4.0, 15.0, 20.0):
                with self.subTest(grade=grade, distance=distance):
                    runtime = _runtime()
                    samples, lanes = [], []
                    def collide(unused_space, start, end, unused_mask):
                        if start.x == end.x and start.z == end.z:
                            samples.append((start, end))
                            height = 40.0 + grade * start.z
                            if min(start.y, end.y) <= height <= max(start.y, end.y):
                                return (_Vector(start.x, height, start.z),)
                            return None
                        lanes.append((start, end))
                        return None
                    runtime.bigworld.wg_collideSegment = collide
                    battle = BattleRuntime(runtime)
                    battle._avatar = runtime.bigworld.avatar
                    result = battle._direction_probe(
                        (0.0, 40.0, 0.0), 0.0, 6.0, None, distance)
                    self.assertTrue(result['clear'], result)
                    self.assertTrue(BotRuntime._probe_is_clear(result))
                    self.assertAlmostEqual(grade, result['slope'])
                    self.assertLess(abs(grade), limit)
                    self.assertEqual(1 if distance <= 8.0 else 2, len(samples))
                    self.assertEqual(6, len(lanes))

    def test_direction_probe_keeps_cliff_missing_ground_wall_and_water_vetoes(self):
        for obstacle in ('steep_up', 'steep_down', 'missing', 'wall', 'water'):
            with self.subTest(obstacle=obstacle):
                runtime = _runtime()
                grade = (0.53 if obstacle == 'steep_up' else
                         -0.53 if obstacle == 'steep_down' else -0.42)
                def collide(unused_space, start, end, unused_mask):
                    if start.x == end.x and start.z == end.z:
                        if obstacle == 'missing':
                            return None
                        height = 40.0 + grade * start.z
                        return (_Vector(start.x, height, start.z),)
                    if obstacle == 'wall':
                        return (end,)
                    return None
                runtime.bigworld.wg_collideSegment = collide
                battle = BattleRuntime(runtime)
                battle._avatar = runtime.bigworld.avatar
                if obstacle == 'water':
                    battle._water_depth = lambda p: 2.0 if p[2] > 0.0 else -1.0
                result = battle._direction_probe(
                    (0.0, 40.0, 0.0), 0.0, 0.0, None, 4.0)
                self.assertFalse(result['clear'], result)
                if obstacle.startswith('steep'):
                    self.assertEqual('planning_grade', result['reason'])
                elif obstacle == 'missing':
                    self.assertEqual('planning_ground_missing', result['reason'])
                elif obstacle == 'wall':
                    self.assertTrue(result['collision'])
                else:
                    self.assertTrue(result['water'])
