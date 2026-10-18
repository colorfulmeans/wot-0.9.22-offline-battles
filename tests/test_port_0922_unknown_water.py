"""Unknown support cannot impersonate water or bypass a physical refusal."""
import json
from pathlib import Path
import unittest
from unittest import mock

from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid, TerrainNavigator

ROOT = Path(__file__).resolve().parents[1]


def grid_with_gap(water=None):
    width, height = 9, 3
    heights = [0] * (width * height)
    hazards = [0] * len(heights)
    heights[width+4] = None
    if water is not None:
        hazards[width+water] = 4
    return TerrainGrid(lambda *args: 0., lambda *args: False, baked_graph=dict(
        format='offline-lan-0922-navgraph', version=2, width=width, height=height,
        origin=(0.,0.), cell_size=4., heights_mm=heights, hazards=hazards,
        links=[255]*len(heights), bounds=(-2.,-2.,34.,10.)))


class UnknownWaterTests(unittest.TestCase):
    def test_gap_is_not_water_but_still_requires_the_segment_proof(self):
        grid=grid_with_gap();a,b=(8.,0.,4.),(24.,0.,4.)
        self.assertEqual((False,None),grid._baked_corridor(a,b))
        self.assertFalse(grid.segment_has_baked_hazard(a,b,4))
        self.assertTrue(grid.segment_has_baked_hazard(a,b,3))
        self.assertFalse(grid.dry_segment_clear(a,b,1.))
        self.assertFalse(grid.segment_clear(a,(100.,0.,4.)))

    def test_real_water_before_or_after_unknown_support_still_blocks(self):
        for water in (3,5):
            grid=grid_with_gap(water);a,b=(8.,0.,4.),(24.,0.,4.)
            self.assertTrue(grid.segment_has_baked_hazard(a,b,4))
            self.assertTrue(grid.segment_has_baked_hazard(b,a,4))
            with mock.patch.object(grid,'segment_clear',side_effect=AssertionError('water bypass')):
                self.assertFalse(grid.dry_segment_clear(a,b,1.))

    def test_a_ford_can_be_left_but_not_entered_as_a_dry_shortcut(self):
        grid=grid_with_gap(2)
        self.assertFalse(grid.segment_has_baked_hazard((8.,0.,4.),(24.,0.,4.),4))
        self.assertTrue(grid.segment_has_baked_hazard((24.,0.,4.),(8.,0.,4.),4))

    def test_recorded_vk3001h_native_clear_exit_is_not_vetoed_as_water(self):
        graph=json.loads((ROOT/'navgraphs/86_himmelsdorf_winter.json').read_bytes())
        nav=TerrainNavigator(lambda *args:1.1,baked_graph=graph)
        nav.bot_states[18]={}
        origin=(185.59560574348657,1.1171762347221375,45.49895911248732)
        path=[(184.,1.12,46.),(184.,1.114,44.)]
        # 015957: this existing physical gate returned clear, then the old
        # water-only gate incorrectly vetoed it. No additional ray is implied.
        with mock.patch.object(nav.grid,'segment_clear',return_value=True) as proof, \
                mock.patch.object(nav.grid,'segment_penalty',return_value=0.), \
                mock.patch.object(nav,'_bot_edges_penalized',return_value=False), \
                mock.patch.object(nav.grid,'live_shortcut_preserves_climb_approach',return_value=True):
            self.assertTrue(nav._planned_next_segment_clear(origin,path,0,1.,18))
            self.assertEqual(1,proof.call_count)
            proof.return_value=False
            self.assertFalse(nav._planned_next_segment_clear(origin,path,0,2.,18))

    def test_reused_edge_geometry_keeps_live_penalties_and_expiry(self):
        grid=grid_with_gap();a,b=(8.,0.,4.),(24.,0.,4.)
        edges=grid._edge_keys_for_segment(a,b)
        self.assertIs(edges,grid._edge_keys_for_segment(a,b))
        self.assertEqual(0.,grid.segment_penalty(a,b,0.))
        grid._failed_edges[edges[0]]=(5.,240.)
        self.assertEqual(240.,grid.segment_penalty(a,b,1.))
        self.assertEqual(0.,grid.segment_penalty(a,b,5.))
        grid._static_hull_edges[edges[0]]=240.
        self.assertEqual(240.,grid.segment_penalty(a,b,10.))
        grid._edge_keys_for_segment(a,(2000.,0.,4.))
        self.assertTrue(all(len(row)<=8 for row in grid._segment_edge_keys.values()))

    def test_mixed_mesh_hazard_cache_keeps_exact_subcell_endpoints(self):
        import types
        grid=grid_with_gap(5)
        grid._local_meshes=types.SimpleNamespace(touches=lambda *args:True,indices={})
        with mock.patch.object(grid,'_baked_corridor',return_value=(False,None)), \
                mock.patch.object(grid,'_baked_segment_cells',side_effect=[((2,1),(3,1)),((2,1),(5,1))]) as scan:
            self.assertFalse(grid.segment_has_baked_hazard((8.,0.,4.),(24.,0.,4.),4))
            self.assertTrue(grid.segment_has_baked_hazard((8.1,0.,4.),(24.,0.,4.),4))
            self.assertFalse(grid.segment_has_baked_hazard((8.,0.,4.),(24.,0.,4.),4))
            self.assertEqual(2,scan.call_count)


if __name__=='__main__':unittest.main()
