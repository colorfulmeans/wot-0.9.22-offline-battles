"""Town precision keeps the reviewed anchor and every wall restriction."""
import copy
import json
import math
from pathlib import Path
import unittest
from gui.mods.offline_lan_0922 import prebaked_navigation as pn,bot_tactics,bot_tactics_runtime as runtime
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

    def test_runtime_admission_and_detailed_check_accept_the_same_fine_anchor(self):
        profile=bot_tactics.default_profile();name='14_siegfried_line'
        unused,outcomes=runtime.default_routes(profile,name,self.graph)
        for team in (1,2):
            for tag in ('heavyTank','AT-SPG'):
                row=next(r for r in profile['maps'][name]['default_routes'] if r['team']==team and r['id']=='fortification_line' and r.get('class_tag')==tag)
                self.assertEqual('baked_route_connected',outcomes['%s:%s'%(team,bot_tactics.default_route_id(row))])
                grid=runtime.graph_view(name,self.graph)
                self.assertIsNone(runtime.validate_route(grid,row))
                self.assertEqual([],runtime.route_issues(grid,row))

    def test_local_hazard_or_disconnection_cannot_be_admitted_via_coarse_snapping(self):
        name='14_siegfried_line'
        row=next(r for r in bot_tactics.default_profile()['maps'][name]['default_routes'] if r['team']==1 and r['id']=='fortification_line' and r.get('class_tag')=='AT-SPG')
        for failure in ('hazard','disconnected'):
            graph=copy.deepcopy(self.graph);patch=graph['local_meshes'][0]
            if failure=='hazard':
                patch['hazards']=list(patch['hazards'])
                x=int(math.floor((80.8441-patch['origin'][0])/patch['cell_size']+.5))
                z=int(math.floor((-67.0406-patch['origin'][1])/patch['cell_size']+.5))
                patch['hazards'][z*patch['width']+x]=1
            else:patch['links']=[0]*len(patch['links'])
            grid=runtime.graph_view(name,graph)
            self.assertEqual('waypoint_unusable' if failure=='hazard' else 'waypoints_disconnected',runtime.validate_route(grid,row))
            self.assertTrue(runtime.route_issues(grid,row))

    def test_admission_cannot_connect_two_legal_nodes_by_leaving_arena_bounds(self):
        graph=copy.deepcopy(self.graph)
        graph.update(width=3,height=3,origin=[0.,0.],heights_mm=[1000]*9,
                     hazards=[0]*9,links=[0]*9)
        graph['heights_mm'][4]=None
        for i in range(9):
            if graph['heights_mm'][i] is None:continue
            for bit,(dx,dz) in enumerate(graph['directions']):
                x,z=i%3+dx,i//3+dz
                if 0<=x<3 and 0<=z<3 and graph['heights_mm'][z*3+x] is not None:
                    graph['links'][i]|=1<<bit
        graph['local_meshes']=[dict(origin=[-4.,-4.],cell_size=2.,width=2,height=2,
            heights_mm=[None]*4,hazards=[0]*4,links=[0]*4)]
        grid=runtime.graph_view('14_siegfried_line',graph)
        grid.bounds=(0.,4.,8.,4.)
        route=dict(team=1,points=[[0.,4.,0],[8.,4.,0]])
        self.assertEqual('waypoints_disconnected',runtime.validate_route(grid,route))


if __name__=='__main__':unittest.main()
