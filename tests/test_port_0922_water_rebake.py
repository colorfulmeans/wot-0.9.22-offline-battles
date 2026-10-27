"""Real water measurements, preserved geometry and consistent motion gates."""
import copy
import importlib.util
import json
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('water_rebake', ROOT/'tools/rebake_navigation_water.py')
rebake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rebake)


class WaterRebakeTests(unittest.TestCase):
    def layer(self):
        return dict(width=4,height=1,origin=[0.,0.],cell_size=4.,
            heights_mm=[-500,-500,None,None],hazards=[0,0,1,1],links=[2,1,0,0],
            directions=[[-1,0],[1,0]])

    def context(self):
        terrain=types.SimpleNamespace(height=lambda x,z:-1.,
            water_depth=lambda x,z,y: (1.05 if x < 10. else 1.8))
        obstacles=types.SimpleNamespace(surface_height=lambda x,z:None,
            blocked=lambda *a,**k:False)
        legacy=types.SimpleNamespace(WATER_DEPTH_LIMIT=1.2,VEHICLE_HALF_WIDTH=2.15,
            SHALLOW_WATER_THRESHOLD=1.2,BRIDGE_OBSTACLE_MARGIN=1.,
            VEHICLE_GROUND_CLEARANCE=.65,HAZARD_WATER=1,HAZARD_EDGE=2,
            HAZARD_SHALLOW_WATER=4,DIRECTIONS=((-1,0),(1,0)),
            _ground_height=lambda t,o,x,z:-1.,
            _has_safe_edge_clearance=lambda t,o,x,z,y:t.water_depth(x,z,y)<=legacy.WATER_DEPTH_LIMIT,
            _segment_clear=lambda t,o,a,b: True)
        return terrain,obstacles,legacy

    def test_remeasures_every_cell_revives_shallow_and_keeps_real_deep_water(self):
        layer=self.layer();original=copy.deepcopy(layer)
        terrain,obstacles,legacy=self.context()
        result,proof=rebake.rebake_layer(layer,terrain,obstacles,legacy)
        self.assertEqual(original,layer)
        self.assertEqual(4,proof['cells_measured'])
        self.assertEqual(-1000,result['heights_mm'][2])
        self.assertEqual(0,result['hazards'][2])
        self.assertTrue(result['links'][1]&2)
        self.assertTrue(result['links'][2]&1)
        self.assertIsNone(result['heights_mm'][3])
        self.assertEqual(1,result['hazards'][3])
        self.assertEqual(1.2,legacy.WATER_DEPTH_LIMIT)

    def test_obstacle_and_already_reviewed_1_2_support_guards_are_not_overridden(self):
        layer=self.layer();terrain,obstacles,legacy=self.context()
        obstacles.blocked=lambda *a,**k:True
        result,unused=rebake.rebake_layer(layer,terrain,obstacles,legacy)
        self.assertIsNone(result['heights_mm'][2])
        self.assertTrue(result['hazards'][2]&2)
        result,unused=rebake.rebake_layer(layer,terrain,obstacles,legacy,previous_limit=1.2)
        self.assertEqual(layer['heights_mm'],result['heights_mm'])

    def test_missing_ground_is_not_water_and_isolated_new_pocket_is_not_published(self):
        layer=self.layer();terrain,obstacles,legacy=self.context()
        layer['heights_mm'][:2]=[None,None];layer['links'][:2]=[0,0]
        legacy._ground_height=lambda t,o,x,z:None if x<8 else -1.
        result,proof=rebake.rebake_layer(layer,terrain,obstacles,legacy)
        self.assertEqual(2,proof['missing_ground'])
        self.assertEqual(0,result['hazards'][0])
        self.assertIsNone(result['heights_mm'][2])
        self.assertEqual(0,proof['revived_cells'])

    def test_shipped_main_and_local_grids_have_completed_measurement_receipts(self):
        count=0
        for path in (ROOT/'navgraphs').glob('*.json'):
            graph=json.loads(path.read_bytes())
            if 'heights_mm' not in graph:continue
            count+=1
            with self.subTest(map=graph['map']):
                self.assertEqual(1.2,graph['bake']['water_depth_limit'])
                self.assertEqual(1.2,graph['bake']['shallow_water_threshold'])
                proof=graph['bake']['water_policy_rebake']
                self.assertTrue(proof['all_cells_measured'])
                self.assertFalse(proof['navigation_strategy_changed'])
                for layer,receipt in zip([graph]+graph.get('local_meshes',[]),[proof['base']]+proof['local_layers']):
                    self.assertEqual(layer['width']*layer['height'],receipt['cells_measured'])
                    self.assertEqual(1.2,receipt['water_depth_limit'])
        self.assertEqual(41,count)

    def test_recorded_tiger_and_a44_prefixes_no_longer_hit_the_old_shore_apron(self):
        from gui.mods.offline_lan_0922 import prebaked_navigation as pn
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        graph=pn.with_shore_hazards(json.loads((ROOT/'navgraphs/45_north_america.json').read_bytes()))
        grid=TerrainGrid(lambda *a:None,baked_graph=graph)
        pairs=(
            ((-160.925659,-13.3449,367.823266),(-159.3755,-13.3449,367.3527)),
            ((-168.65004,-12.20996,366.75073),(-167.38298,-12.20996,370.54475)))
        for a,b in pairs:
            evidence={}
            self.assertFalse(grid.segment_has_motion_hazard(a,b,13,evidence),evidence)
            self.assertTrue(pn.pose_is_safe(graph,b,hazard_mask=9))
        # Exact measured river depression remains deep for navigation.
        cell=grid.cell_for((-114.,-14.30136,304.))
        index=grid._baked_flat_index(cell)
        self.assertTrue(grid._baked_hazards[index]&1)


if __name__=='__main__':
    unittest.main()
