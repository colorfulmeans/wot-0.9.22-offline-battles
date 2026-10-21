"""The upstream city bridge is additive, bidirectional and still rejects water."""
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src/res/scripts/client')]
from verify_windstorm_middle_mesh import CASES
from gui.mods.offline_lan_0922 import prebaked_navigation as pn
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid


class MiddleBridgeTests(unittest.TestCase):
    def test_clearance_weight_uses_the_vertices_actual_metres(self):
        graph = pn.with_shore_hazards(json.loads((ROOT/'navgraphs/84_winter.json').read_bytes()))
        grid = TerrainGrid(lambda *a: None, baked_graph=graph)
        for number, patch in enumerate(graph['local_meshes']):
            for i, key in enumerate(grid._local_meshes.keys[number]):
                if key[0] < 0 and patch['heights_mm'][i] is not None:
                    missing = 8-grid._baked_link_count(key)
                    self.assertAlmostEqual(missing*patch['cell_size']*.2, grid._baked_clearance_penalty(key))
        for key in ((125, 125), (161, 88)):
            if grid._baked_index(key) is not None:
                self.assertAlmostEqual((8-grid._baked_link_count(key))*4.*.2, grid._baked_clearance_penalty(key))

    def test_reverse_shortcut_cannot_skip_a_fine_shore_corner(self):
        graph = pn.with_shore_hazards(json.loads((ROOT/'navgraphs/84_winter.json').read_bytes()))
        grid = TerrainGrid(lambda *a: None, baked_graph=graph)
        first, last = (134., -8.765, -158.), (128., -8.673, -163.)
        self.assertTrue(grid.segment_has_motion_hazard(first, last, 9))
        self.assertFalse(grid.segment_clear(first, last))
        # Two rays with the same nearest endpoint cells must not share the
        # coarse corridor cache when their sub-cell boundary crossings differ.
        for offset in (.01, .21, -.21):
            a = (first[0]+offset, first[1], first[2])
            b = (last[0], last[1], last[2]+offset)
            if grid.segment_has_motion_hazard(a, b, 9):
                self.assertFalse(grid.segment_clear(a, b))

    def test_bridge_mouths_are_bidirectional_and_retain_shore_guards(self):
        graph = pn.with_shore_hazards(json.loads((ROOT/'navgraphs/84_winter.json').read_bytes()))
        self.assertEqual(3, len(graph['local_meshes']))
        grid = TerrainGrid(lambda *a: None, baked_graph=graph)
        for a, b in CASES:
            for start, end in ((a, b), (b, a)):
                path = grid.plan(start, end, max_expansions=20000)
                self.assertTrue(path)
                self.assertLess(math.hypot(path[-1][0]-end[0], path[-1][2]-end[2]), 2.)
                for first, last in zip(path, path[1:]):
                    self.assertTrue(grid.segment_clear(first, last))
                    self.assertFalse(grid.segment_has_motion_hazard(first, last, 13))
        patch = graph['local_meshes'][2]
        for i, mask in enumerate(patch['hazards']):
            if mask & 9:
                point = (patch['origin'][0]+i%patch['width']*patch['cell_size'], 0., patch['origin'][1]+i//patch['width']*patch['cell_size'])
                self.assertFalse(pn.pose_is_safe(graph, point, hazard_mask=9))
