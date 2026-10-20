"""Reported Steyr exit: planning, admission and final pose share the fine mesh."""
import copy
import json
import math
from pathlib import Path
import unittest

from gui.mods.offline_lan_0922 import prebaked_navigation as pn
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = (126.7290046558638, -8.950407028198242, -276.07781896536494)
YAW = 1.654004054630426
DISTANCE = 3.1200008771171768
END = (ORIGIN[0]+math.sin(YAW)*DISTANCE, ORIGIN[1],
       ORIGIN[2]+math.cos(YAW)*DISTANCE)


class WindstormBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads((ROOT/'navgraphs/84_winter.json').read_bytes())
        cls.graph = pn.with_shore_hazards(cls.raw)

    def grid(self):
        return TerrainGrid(lambda *args: None, baked_graph=self.graph)

    def test_recorded_steyr_exit_is_connected_and_admitted(self):
        grid = self.grid()
        self.assertTrue(grid.segment_clear(ORIGIN, END))
        self.assertFalse(grid.segment_has_motion_hazard(ORIGIN, END, 1|4|8))
        for point in (ORIGIN, END):
            self.assertTrue(pn.pose_is_safe(self.graph, point, hazard_mask=1|8))
            self.assertTrue(pn.pose_is_safe(self.graph, point))
        coarse = dict(self.graph, local_meshes=[])
        self.assertFalse(pn.pose_is_safe(coarse, END, hazard_mask=1|8))

    def test_both_mouths_and_bridge_are_bidirectionally_reachable(self):
        grid = self.grid()
        a, b = (120., -9., -280.), (200., -9., -244.)
        c, d = (126., -9., -278.), (194., -9., -250.)
        for start, end in ((a, b), (b, a), (c, d), (d, c)):
            path = grid.plan(start, end, max_expansions=20000)
            self.assertTrue(path)
            self.assertLess(math.hypot(path[-1][0]-end[0], path[-1][2]-end[2]), 2.)
            for first, last in zip(path, path[1:]):
                self.assertFalse(grid.segment_has_motion_hazard(first, last, 1|4|8))
                steps = max(1, int(math.ceil(math.hypot(last[0]-first[0], last[2]-first[2])/.25)))
                for n in range(steps+1):
                    point = tuple(first[k]+(last[k]-first[k])*n/steps for k in range(3))
                    self.assertTrue(pn.pose_is_safe(self.graph, point, hazard_mask=1|8))

    def test_bridge_hull_widths_both_directions(self):
        grid = self.grid()
        yaw = math.atan2(68., 28.)
        for width in (1.2, 1.8, 2.15):
            for heading in (yaw, yaw+math.pi):
                for x in range(136, 187):
                    point = (x, -9., -278.+(x-126)*28./68.)
                    self.assertTrue(grid.hull_pose_clear(point, heading, 3.2, width),
                                    (point, heading, width))

    def test_fine_water_and_wet_edges_remain_rejected(self):
        patch = self.graph['local_meshes'][0]
        for flag in (1, 8):
            count = 0
            for i, value in enumerate(patch['hazards']):
                if not value & flag:
                    continue
                point = (patch['origin'][0]+i%patch['width'], 0.,
                         patch['origin'][1]+i//patch['width'])
                self.assertFalse(pn.pose_is_safe(self.graph, point, hazard_mask=1|8))
                count += 1
            self.assertGreater(count, 0)

    def test_no_fine_alias_can_discard_its_own_hazard(self):
        grid = self.grid()
        for i, key in enumerate(grid._local_meshes.keys[0]):
            value = grid._baked_hazards[grid._baked_flat_index(key)]
            self.assertEqual(self.graph['local_meshes'][0]['hazards'][i], value)

    def test_unknown_legacy_patch_cannot_clear_parent_water(self):
        graph = copy.deepcopy(self.graph)
        local = pn.local_cell_at(graph, END)
        patch, index = local
        patch['heights_mm'][index] = None
        hazards = list(patch['hazards']); hazards[index] = 0; patch['hazards'] = hazards
        self.assertIsNone(pn.local_cell_at(graph, END))
        self.assertFalse(pn.pose_is_safe(graph, END, hazard_mask=1|8))

    def test_runtime_shore_classification_does_not_mutate_catalog(self):
        self.assertFalse(any(v & 8 for p in self.raw['local_meshes'] for v in p['hazards']))
        self.assertTrue(any(v & 8 for p in self.graph['local_meshes'] for v in p['hazards']))


class WindstormRuntimeAdmissionTests(unittest.TestCase):
    def test_recorded_exit_uses_actual_runtime_precheck(self):
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
            self.assertIs(True, runtime._planner_corridor_clear(
                ORIGIN, YAW, 0., maximum_distance=DISTANCE))
            coarse = dict(graph, local_meshes=[])
            runtime.baked_graph = coarse
            runtime.navigator.grid = RuntimeGrid(lambda *a: None, baked_graph=coarse)
            self.assertIs(False, runtime._planner_corridor_clear(
                ORIGIN, YAW, 0., maximum_distance=DISTANCE))
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
