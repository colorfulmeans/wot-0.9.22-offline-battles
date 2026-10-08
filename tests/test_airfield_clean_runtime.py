"""Cold navigation uses the immutable current graph, including original holes."""
import copy
import json
import math
from pathlib import Path
import unittest
from test_port_0922_navigation import TerrainGrid
from gui.mods.offline_lan_0922.navigation_graph_schema import validate_graph
ROOT=Path(__file__).resolve().parents[1]
NEW=json.loads((ROOT/'navgraphs/31_airfield.json').read_text())
OLD=json.loads((ROOT/'tests/fixtures/31_airfield-before.json').read_text())

class CleanGraphIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        def no_native(*args):
            self.calls.append(args)
            raise AssertionError('Cold baked planning must not reconstruct terrain')
        self.graph=copy.deepcopy(NEW)
        self.grid=TerrainGrid(no_native,no_native,baked_graph=self.graph)
    def test_current_graph_is_not_rewritten_by_initialization(self):
        self.assertEqual(NEW,self.graph)
        self.assertEqual(NEW['heights_mm'],self.grid._baked_heights)
        self.assertEqual(NEW['links'],self.grid._baked_links)
    def test_all_30_spawn_to_enemy_base_paths_work_cold_without_native_queries(self):
        for team in (1,2):
            gx,gz=NEW['spawn_anchors'][2-team]
            for slot,pose in enumerate(NEW['spawn_formations'][str(team)]):
                path=self.grid.plan(tuple(pose[:3]),(gx,0.,gz),max_expansions=20000)
                self.assertTrue(path,(team,slot))
                self.assertLess(math.hypot(path[-1][0]-gx,path[-1][2]-gz),4.1)
        self.assertEqual([],self.calls)
        self.assertEqual(NEW,self.graph)
    def test_remaining_holes_stay_missing_without_native_reconstruction(self):
        index=next(i for i,h in enumerate(NEW['heights_mm']) if h is None)
        cell=(index%NEW['width'],index//NEW['width'])
        self.assertIsNone(self.grid._baked_cell_height(cell))
        self.assertEqual([],self.calls)
    def test_old_graph_is_also_loaded_without_mutating_its_terrain(self):
        graph=copy.deepcopy(OLD)
        grid=TerrainGrid(lambda *a:0.,lambda *a:False,baked_graph=graph)
        self.assertEqual(OLD,graph)
        self.assertEqual(OLD['heights_mm'],grid._baked_heights)
    def test_new_graph_passes_current_loader_schema(self):
        self.assertIsNotNone(validate_graph(copy.deepcopy(NEW),'31_airfield'))
