"""Continuous hills must not become cliff hazards during offline baking."""
import math
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from bake_navigation_0922 import continuous_terrain_edge_clearance, refine_terrain_edges


class TerrainEdgeTests(unittest.TestCase):
    def check(self, height, water=0, bridge=False):
        terrain = types.SimpleNamespace(height=height,
                                        water_depth=lambda x, z, y: water)
        obstacles = types.SimpleNamespace(surface_height=lambda x, z: 10 if bridge else None)
        legacy = types.SimpleNamespace(
            _ground_height=lambda t, o, x, z: t.height(x, z),
            WATER_DEPTH_LIMIT=.9, VEHICLE_GROUND_CLEARANCE=.65)
        return continuous_terrain_edge_clearance(
            terrain, obstacles, 0, 0, height(0, 0), legacy,
            lambda *args: False)

    def test_continuous_slopes_survive_all_headings(self):
        for angle in range(0, 360, 15):
            dx, dz = math.sin(math.radians(angle)), math.cos(math.radians(angle))
            with self.subTest(angle=angle):
                self.assertTrue(self.check(lambda x, z: 50 + .44 * (dx*x + dz*z)))

    def test_abrupt_cliff_is_rejected_at_near_and_far_shoulders(self):
        for edge in (.5, 2, 5):
            with self.subTest(edge=edge):
                self.assertFalse(self.check(lambda x, z: 50 if x < edge else 47))

    def test_deep_water_missing_ground_and_bridge_lips_stay_rejected(self):
        self.assertFalse(self.check(lambda x, z: 50, water=1))
        self.assertFalse(self.check(lambda x, z: None if x > 2 else 50))
        self.assertFalse(self.check(lambda x, z: 50, bridge=True))

    def test_slope_turning_into_a_cliff_is_rejected(self):
        self.assertFalse(self.check(lambda x, z: 50 - .44*x - max(0, x-2)**2))

    def test_existing_safe_nodes_are_unchanged(self):
        self.assertTrue(continuous_terrain_edge_clearance(
            None, None, 0, 0, 50, None, lambda *args: True))

    def test_refinement_preserves_water_buildings_and_authored_geometry(self):
        import copy
        graph = dict(width=3, height=3, origin=[0, 0], cell_size=4,
                     directions=[[1,0],[0,1],[-1,0],[0,-1]],
                     heights_mm=[None,None,None,None,50000,None,None,None,None],
                     hazards=[1,2,0,2,0,2,0,2,1], links=[0]*9,
                     bake={}, routes={}, spawn_formations={'1':[[4,50,4]]})
        original = copy.deepcopy(graph)
        terrain = types.SimpleNamespace(height=lambda x,z:50,water_depth=lambda *a:0)
        obstacles = types.SimpleNamespace(surface_height=lambda *a:None,blocked=lambda *a,**k:False)
        legacy = types.SimpleNamespace(HAZARD_EDGE=2,WATER_DEPTH_LIMIT=.9,
            VEHICLE_HALF_WIDTH=2.15,VEHICLE_GROUND_CLEARANCE=.65,
            _ground_height=lambda t,o,x,z:50,_has_safe_edge_clearance=lambda *a:True,
            _segment_clear=lambda *a:True)
        result = refine_terrain_edges(graph,terrain,obstacles,legacy)
        self.assertEqual(original,graph)
        self.assertEqual(4,result['bake']['continuous_terrain_nodes_added'])
        self.assertEqual(original['spawn_formations'],result['spawn_formations'])
        for index in (0,2,6,8):
            self.assertIsNone(result['heights_mm'][index])
            self.assertEqual(original['hazards'][index],result['hazards'][index])
        self.assertTrue(result['links'][4])
        legacy._segment_clear=lambda *a:False
        isolated=refine_terrain_edges(graph,terrain,obstacles,legacy)
        self.assertEqual(0,isolated['bake']['continuous_terrain_nodes_added'])
        self.assertEqual(original['heights_mm'],isolated['heights_mm'])
