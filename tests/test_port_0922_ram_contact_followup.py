from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'src' / 'res' / 'scripts' / 'client'
sys.path.insert(0, str(CLIENT))

from gui.mods.offline_lan_0922 import tank_collision
from test_port_0922_battle_runtime import BattleRuntime


class RamContactFollowupTests(unittest.TestCase):

    def test_shared_contact_width_recovers_a_native_plate_beside_a_track_gap(self):
        runtime = object.__new__(BattleRuntime)
        runtime._vector = lambda value: tuple(value)
        first = {'x': 0.0, 'z': 0.0, 'yaw': 0.0,
                 'shape': (1.5, 3.5, -0.8, 2.0)}
        second = {'x': 0.0, 'z': 6.5, 'yaw': 0.0,
                  'shape': (1.5, 3.5, -0.8, 2.0)}
        samples = runtime._ram_contact_xz_samples(
            first, second, (0.0, -1.0))
        self.assertEqual(3, len(samples))
        self.assertTrue(all(abs(x) < 1.5 and 3.0 < z < 3.5
                            for x, z in samples))

        def armor(self, vehicle, matrix, point, normal,
                  chassis_matrix=None):
            if vehicle == 'bot' and abs(point[0]) < 0.3:
                return None
            return {'armor': 40.0 if vehicle == 'player' else 20.0,
                    'screened': False}

        runtime._native_ram_vehicle_armor = types.MethodType(armor, runtime)
        proof = {'hit_point': (0.0, 1.0, 3.25),
                 'contact_y_span': (0.0, 2.0),
                 'contact_xz_candidates': samples,
                 'contact_normal': (0.0, -1.0),
                 'local_vehicle': 'player', 'bot_vehicle': 'bot',
                 'local_matrix': object(), 'bot_matrix': object()}
        matched, unused_first, unused_second = (
            runtime._native_ram_contact_plate_pair(proof))
        self.assertEqual((40.0, 20.0),
                         (matched[0]['armor'], matched[1]['armor']))
        self.assertGreater(abs(matched[3]), 0.3)
        self.assertTrue(3.0 < matched[4] < 3.5)

    def test_contact_height_candidates_stay_inside_shared_span_and_near_observation_first(self):
        values = tank_collision.ram_contact_sample_heights(2.0, (0.0, 4.0))
        self.assertEqual(2.0, values[0])
        self.assertTrue(all(0.0 <= value <= 4.0 for value in values))
        self.assertGreaterEqual(len(values), 5)
        self.assertEqual(len(values), len(set(round(v, 6) for v in values)))

    def test_native_pair_can_recover_structural_plates_away_from_chassis_midpoint(self):
        runtime = object.__new__(BattleRuntime)
        runtime._vector = lambda value: tuple(value)
        calls = []

        def armor(self, vehicle, matrix, hit, normal, chassis_matrix=None):
            calls.append((vehicle, float(hit[1])))
            if float(hit[1]) < 2.5:
                return None
            return {
                'armor': 150.0 if vehicle == 'player' else 76.2,
                'screened': False,
            }

        runtime._native_ram_vehicle_armor = types.MethodType(armor, runtime)
        proof = {
            'contact_normal': (1.0, 0.0),
            'hit_point': (10.0, 2.0, 20.0),
            'contact_y_span': (0.0, 4.0),
            'local_vehicle': 'player',
            'bot_vehicle': 'bot',
            'local_matrix': object(),
            'bot_matrix': object(),
        }

        matched, seen_player, seen_bot = runtime._native_ram_contact_plate_pair(
            proof)

        self.assertIsNotNone(matched)
        self.assertAlmostEqual(150.0, matched[0]['armor'])
        self.assertAlmostEqual(76.2, matched[1]['armor'], places=3)
        self.assertGreaterEqual(matched[2], 2.5)
        self.assertIsNotNone(seen_player)
        self.assertIsNotNone(seen_bot)
        self.assertIn(('player', 2.0), calls)

    def test_native_pair_never_mixes_plates_from_different_heights(self):
        runtime = object.__new__(BattleRuntime)
        runtime._vector = lambda value: tuple(value)

        def armor(self, vehicle, matrix, hit, normal, chassis_matrix=None):
            y = float(hit[1])
            if vehicle == 'player' and y < 2.0:
                return {'armor': 150.0, 'screened': False}
            if vehicle == 'bot' and y > 2.0:
                return {'armor': 76.2, 'screened': False}
            return None

        runtime._native_ram_vehicle_armor = types.MethodType(armor, runtime)
        proof = {
            'contact_normal': (1.0, 0.0),
            'hit_point': (10.0, 2.0, 20.0),
            'contact_y_span': (0.0, 4.0),
            'local_vehicle': 'player',
            'bot_vehicle': 'bot',
            'local_matrix': object(),
            'bot_matrix': object(),
        }

        matched, seen_player, seen_bot = runtime._native_ram_contact_plate_pair(
            proof)

        self.assertIsNone(matched)
        self.assertIsNotNone(seen_player)
        self.assertIsNotNone(seen_bot)

    def test_second_constraint_reads_normal_contact_velocity(self):
        tanks = [
            {'id': 1, 'vx': 10.0, 'vz': 1.0},
            {'id': 2, 'vx': -2.0, 'vz': 3.0},
        ]
        results = {
            1: {'delta_velocity': (-4.0, 2.0)},
            2: {'delta_velocity': (7.0, -1.0)},
        }

        updated = tank_collision.post_contact_velocity_bodies(tanks, results)

        self.assertEqual((6.0, 3.0), (updated[0]['vx'], updated[0]['vz']))
        self.assertEqual((5.0, 2.0), (updated[1]['vx'], updated[1]['vz']))
        self.assertEqual((10.0, 1.0), (tanks[0]['vx'], tanks[0]['vz']))

    def test_existing_ram_curve_is_not_retuned_by_this_fix(self):
        # Protect the accepted T-44/AT 7/T71-style cases: this follow-up fixes
        # contact-point proof and duplicated physical impulses, not the global
        # damage coefficient.
        self.assertAlmostEqual(0.25, tank_collision.RAM_DAMAGE_COEFFICIENT)
        damage_other, damage_self = tank_collision.ram_damage(
            5.72386, 55883.0, 100175.0, 50.8, 180.0)
        self.assertEqual((64, 191), (damage_other, damage_self))


if __name__ == '__main__':
    unittest.main()
