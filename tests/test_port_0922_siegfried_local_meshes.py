"""Town precision keeps the reviewed anchor and every wall restriction."""
import json
import math
from pathlib import Path
import unittest
from gui.mods.offline_lan_0922 import prebaked_navigation as pn,bot_tactics
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid

ROOT=Path(__file__).resolve().parents[1]


class SiegfriedLocalMeshesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph=pn.with_shore_hazards(json.loads((ROOT/'navgraphs/14_siegfried_line.json').read_text()))

    def test_bounded_town_sampling_keeps_coarse_base_and_only_one_tiny_fine_pocket(self):
        self.assertEqual(4.,self.graph['cell_size'])
        patches=self.graph['local_meshes']
        self.assertEqual([1.,2.,2.,2.,2.],[p['cell_size'] for p in patches])
        self.assertLess(patches[0]['width']*patches[0]['height'],400)
        self.assertLess(sum(p['width']*p['height'] for p in patches),25000)

    def test_original_authored_corner_is_supported_without_moving_it(self):
        point=(80.8441,-67.0406)
        grid=TerrainGrid(lambda *args:None,baked_graph=self.graph)
        cell=grid._local_meshes.cell((point[0],0.,point[1]))
        self.assertIsNotNone(grid._baked_index(cell))
        rows=bot_tactics.default_profile()['maps']['14_siegfried_line']['default_routes']
        for team in (1,2):
            selected=[next(r for r in rows if r['team']==team and r['id']=='fortification_line' and r.get('class_tag')==tag) for tag in ('heavyTank','AT-SPG')]
            self.assertEqual(selected[0]['points'],selected[1]['points'])
            self.assertIn(list(point),[p[:2] for p in selected[0]['points']])

    def test_corner_approaches_complete_both_directions_without_a_detour(self):
        grid=TerrainGrid(lambda *args:None,baked_graph=self.graph)
        for row in self.graph['bake']['local_meshes']['corner_validation']:
            a,b=row['start'],row['end']
            path=grid.plan((a[0],0.,a[1]),(b[0],0.,b[1]),max_expansions=100000)
            self.assertLess(math.hypot(path[-1][0]-b[0],path[-1][2]-b[1]),4.)
            cost=sum(math.hypot(y[0]-x[0],y[2]-x[2]) for x,y in zip(path,path[1:]))
            self.assertLess(cost,math.dist(a,b)*1.8+12.)


if __name__=='__main__':unittest.main()
