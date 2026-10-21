"""Retained spawn identities and exact-client ground evidence, not live physics."""
import importlib.util
import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('serene_spawns', ROOT/'tools/repair_serene_coast_spawns_0922.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class SereneCoastSpawnTests(unittest.TestCase):
    def test_entire_retained_formation_has_level_maximum_chassis_evidence(self):
        graph = json.loads((ROOT/'navgraphs/47_canada_a.json').read_text())
        rows = json.loads((ROOT/'tests/fixtures/serene_coast_spawn_ground_232823.json').read_text())
        self.assertEqual(30, len(rows))
        self.assertEqual({('1', 8), ('1', 9), ('2', 6), ('2', 8), ('2', 15)},
                         {(r['team'], r['slot']) for r in rows if r['shift']})
        for row in rows:
            with self.subTest(team=row['team'], slot=row['slot']):
                pose = graph['spawn_formations'][row['team']][row['slot']-1]
                self.assertEqual(row['after'], pose)
                self.assertEqual(row['before'][3], pose[3])
                self.assertLessEqual(row['shift'], 16.)
                if row['ground_before']['clear']:
                    self.assertEqual(row['before'], pose)
                evidence = row['ground_after']
                self.assertTrue(evidence['clear'])
                self.assertLessEqual(evidence['centre_slope_degrees'], 6.)
                self.assertLessEqual(evidence['footprint_slope_degrees'], 8.)
                values = [y for line in evidence['samples'] for y in line]
                self.assertEqual(15, len(values))
                self.assertLessEqual(max(values)-min(values), .9)
        v = graph['validation']['spawn_level_ground_revalidation']
        self.assertTrue(v['hard_and_soft_clearance'])
        self.assertTrue(v['pairwise_clearance'])
        self.assertTrue(v['directed_home_connection'])
        hw, hl = v['vehicle_envelope']['half_width'], v['vehicle_envelope']['half_length']
        poses = [p for team in graph['spawn_formations'].values() for p in team]
        for i, first in enumerate(poses):
            for second in poses[i+1:]:
                self.assertGreaterEqual(math.hypot(first[0]-second[0], first[2]-second[2]),
                                        repair.baker.SPAWN_MINIMUM_SPACING)
                self.assertFalse(repair.baker.spawn_obbs_overlap(first, second, hw, hl))

    def test_published_editor_and_saved_profiles_keep_route_edits_after_spawn_only_update(self):
        import copy
        import hashlib
        from gui.mods.offline_lan_0922 import bot_tactics as cfg
        raw = (ROOT/'navgraphs/47_canada_a.json').read_bytes()
        graph = json.loads(raw)
        identity = hashlib.sha256(raw).hexdigest()
        self.assertEqual(identity, cfg.MAPS['47_canada_a']['resource_sha256'])
        profile = cfg.default_profile()
        self.assertEqual(identity, profile['maps']['47_canada_a']['resource_sha256'])
        for old in graph['navigation_previous_sha256s']:
            saved = copy.deepcopy(profile)
            entry = saved['maps']['47_canada_a']
            entry['resource_sha256'] = old
            entry['default_routes'][0]['disabled'] = True
            expected = copy.deepcopy(entry)
            expected['resource_sha256'] = identity
            self.assertEqual(expected, cfg.canonical(saved)['maps']['47_canada_a'])

    def test_flat_centre_does_not_hide_long_hull_on_bank(self):
        def ground(x, z):
            return max(0., z-3.)
        result = repair.footprint([0., 0., 0., 0.], 2.42, 6.41, ground)
        self.assertEqual(0., result['centre_slope_degrees'])
        self.assertFalse(result['clear'])
        self.assertTrue(repair.footprint([0., 0., -5., 0.], 2.42, 6.41, ground)['clear'])

    def test_small_natural_ground_variation_remains_admitted(self):
        self.assertTrue(repair.footprint([0., 0., 0., .49], 2.42, 6.41,
                                        lambda x, z: .015*x+.02*z)['clear'])
        self.assertFalse(repair.footprint([0., 0., 0., .49], 2.42, 6.41,
                                         lambda x, z: .4*x)['clear'])
        self.assertFalse(repair.footprint([0., 0., 0., .49], 2.42, 6.41,
                                         lambda x, z: None)['clear'])


if __name__ == '__main__':
    unittest.main()
