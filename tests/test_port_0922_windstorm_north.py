"""North bridge and bank: reported Emil short/long execution must agree."""
import json
import math
from pathlib import Path
import sys
import unittest

from gui.mods.offline_lan_0922 import prebaked_navigation as pn
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = (280.3538467765204, -14.974234580993652, 219.5717056753799)
YAW = -1.2797609560299639
DISTANCE = 3.4308600425720215


class NorthBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads((ROOT/'navgraphs/84_winter.json').read_bytes())
        cls.graph = pn.with_shore_hazards(cls.source)

    def test_exact_emil_exit_and_every_short_prefix_share_safe_cells(self):
        grid = TerrainGrid(lambda *a: None, baked_graph=self.graph)
        for distance in [.05, .25, .5, 1., 1.5, 2., 2.5, 3., DISTANCE]:
            end = (ORIGIN[0]+math.sin(YAW)*distance, ORIGIN[1], ORIGIN[2]+math.cos(YAW)*distance)
            self.assertTrue(grid.segment_clear(ORIGIN, end), distance)
            self.assertFalse(grid.segment_has_motion_hazard(ORIGIN, end, 1|4|8), distance)
            self.assertTrue(pn.pose_is_safe(self.graph, end, hazard_mask=1|8), distance)

    def test_north_bridge_and_bank_are_bidirectionally_connected(self):
        grid = TerrainGrid(lambda *a: None, baked_graph=self.graph)
        for a, b in (((282., -12., 250.), (216., -11., 210.)),
                     ((282., -15., 220.), (272., -15., 220.)),
                     (ORIGIN, (217.724, -11., 216.479)),
                     (ORIGIN, (276., -12., 244.))):
            for start, end in ((a, b), (b, a)):
                path = grid.plan(start, end, max_expansions=20000)
                self.assertTrue(path)
                self.assertLess(math.hypot(path[-1][0]-end[0], path[-1][2]-end[2]), 2.)
                length = sum(math.hypot(last[0]-first[0], last[2]-first[2])
                             for first, last in zip(path, path[1:]))
                self.assertLess(length, math.hypot(end[0]-start[0], end[2]-start[2])*1.8+12.)
                self.assertTrue(all(198 <= p[0] <= 326 and 166 <= p[2] <= 278 for p in path))
                for first, last in zip(path, path[1:]):
                    self.assertFalse(grid.segment_has_motion_hazard(first, last, 1|4|8), (first, last))

    def test_deep_water_and_unsafe_bank_remain_rejected(self):
        patch = self.graph['local_meshes'][1]
        counts = {1: 0, 8: 0}
        for i, hazard in enumerate(patch['hazards']):
            if not hazard & 9:
                continue
            point = (patch['origin'][0]+i%patch['width'], 0., patch['origin'][1]+i//patch['width'])
            self.assertFalse(pn.pose_is_safe(self.graph, point, hazard_mask=9))
            for flag in counts:
                counts[flag] += bool(hazard & flag)
        self.assertTrue(all(counts.values()))
        # This bank's full width exceeded .9 m but is inside the newly
        # measured 1.2 m envelope. Other deep/edge samples above stay vetoed.
        self.assertTrue(pn.pose_is_safe(self.graph, (262., -15., 226.), hazard_mask=9))

    def test_surveyed_shallow_bank_has_support_and_fine_links(self):
        grid = TerrainGrid(lambda *a: None, baked_graph=self.graph)
        for point in ((278., -15., 218.), (274., -15., 218.), (270., -15., 218.)):
            local = pn.local_cell_at(self.graph, point)
            self.assertIsNotNone(local)
            patch, i = local
            self.assertIsNotNone(patch['heights_mm'][i])
            self.assertTrue(patch['links'][i])
            self.assertEqual(0, patch['hazards'][i])
        self.assertTrue(grid.segment_clear((282., -15., 220.), (272., -15., 220.)))

    def test_every_fine_sample_retains_its_own_hazard_in_search(self):
        grid = TerrainGrid(lambda *a: None, baked_graph=self.graph)
        for number, patch in enumerate(self.graph['local_meshes']):
            for i, key in enumerate(grid._local_meshes.keys[number]):
                self.assertEqual(patch['hazards'][i], grid._baked_hazards[grid._baked_flat_index(key)])

    def test_north_geometry_carries_full_width_water_and_drop_proof(self):
        proof = self.source['bake']['local_meshes']['north_bridge']
        self.assertEqual(2.15, proof['bank_support_half_width'])
        self.assertEqual(1.2, proof['water_depth_limit'])
        self.assertEqual(.25, proof['support_sample_metres'])
        self.assertGreater(len(proof['measured_bank_nodes']), 0)


class NorthRuntimeTests(unittest.TestCase):
    def test_bake_support_uses_surface_sample_basis_but_keeps_cliff_and_water_veto(self):
        import types
        sys.path.insert(0, str(ROOT/'tools'))
        from build_windstorm_north_mesh import footprint_support
        terrain = types.SimpleNamespace(water_depth=lambda x, z, y: 0.)
        obstacles = types.SimpleNamespace(raster_size=1.,
            surface_height=lambda x, z: math.floor(x)*.13)
        legacy = types.SimpleNamespace(VEHICLE_HALF_WIDTH=2.15, WATER_DEPTH_LIMIT=.9,
            MAX_GRADE=.38, _ground_height=lambda t, o, x, z: o.surface_height(x, z))
        self.assertTrue(footprint_support(terrain, obstacles, legacy, 269., 243., 269*.13))
        obstacles.surface_height = lambda x, z: -3. if x < 269. else 0.
        self.assertFalse(footprint_support(terrain, obstacles, legacy, 269., 243., 0.))
        obstacles.surface_height = lambda x, z: 0.
        terrain.water_depth = lambda x, z, y: 1. if x < 268. else 0.
        self.assertFalse(footprint_support(terrain, obstacles, legacy, 269., 243., 0.))

    def test_actual_runtime_accepts_both_planner_and_committed_emil_lengths(self):
        import types
        import test_port_0922_bot_runtime as harness
        fixture = harness.BotRuntimeTests()
        fixture.setUp()
        try:
            module = fixture.module
            graph = module.prebaked_navigation.with_shore_hazards(json.loads(
                (ROOT/'navgraphs/84_winter.json').read_bytes()))
            from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid as RuntimeGrid
            runtime = module.BotRuntime(1, baked_graph=graph)
            runtime.baked_graph = graph
            runtime.navigator = types.SimpleNamespace(grid=RuntimeGrid(lambda *a: None, baked_graph=graph))
            for distance in (.5, DISTANCE):
                self.assertIs(True, runtime._planner_corridor_clear(
                    ORIGIN, YAW, 0., hazard_only=True, maximum_distance=distance))
            coarse = dict(graph, local_meshes=graph['local_meshes'][:1])
            runtime.baked_graph = coarse
            runtime.navigator.grid = RuntimeGrid(lambda *a: None, baked_graph=coarse)
            self.assertIs(False, runtime._planner_corridor_clear(
                ORIGIN, YAW, 0., hazard_only=True, maximum_distance=.5))
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
