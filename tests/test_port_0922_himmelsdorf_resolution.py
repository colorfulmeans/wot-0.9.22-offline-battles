"""Resolution migration retains tactics and exposes geometry in final receipts."""
import copy
import io
import json
from pathlib import Path
import sys
import unittest
import types
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import bake_navigation_0922 as baker
from read_native_evidence import parse_lines
from gui.mods.offline_lan_0922 import bot_tactics, prebaked_navigation


class ResolutionTests(unittest.TestCase):
    def test_first_run_and_reset_profile_uses_current_identities(self):
        profile=bot_tactics.default_profile()
        self.assertEqual(profile,bot_tactics.canonical(profile))
        for name in ('04_himmelsdorf','86_himmelsdorf_winter'):
            self.assertEqual(bot_tactics.MAPS[name]['resource_sha256'],
                             profile['maps'][name]['resource_sha256'])

    def test_preserved_eroded_rail_goal_uses_existing_bounded_grid_snap(self):
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        graph=json.loads((ROOT/'navgraphs/04_himmelsdorf.json').read_bytes())
        grid=TerrainGrid(lambda *args:None,baked_graph=graph)
        raw=grid.cell_for((-218.,1.1,-158.))
        safe=grid._nearest_baked_cell(raw,3)
        self.assertIsNotNone(safe)
        self.assertIsNone(grid._baked_cell_height(raw))
        self.assertLessEqual(sum((a-b)**2 for a,b in zip(raw,safe)),4)
        self.assertIsNotNone(grid._baked_cell_height(safe))
        path=grid.plan((-226.,1.1,-170.),(-218.,1.1,-158.),max_expansions=4096)
        self.assertTrue(path)
        self.assertLessEqual((path[-1][0]+218.)**2+(path[-1][2]+158.)**2,16.)
        self.assertIsNotNone(grid._baked_cell_height(grid.cell_for(path[-1])))

    def test_separate_icicles_do_not_fill_air_and_real_walls_still_block(self):
        import test_port_0922_navigation_collision_bake as fixture
        field=baker.compiled_navigation_obstacles(
            fixture.compiled([]),fixture.VFS([]),baker._legacy_baker())
        field._mark_cell(0,0,.78,.97)
        field._mark_cell(0,0,9.97,10.13)
        self.assertFalse(field.blocked(.5,.5,1.1,margin=0.))
        self.assertEqual(2,len(field.height_intervals[(0,0)]))
        field._mark_cell(0,0,1.8,2.5)
        self.assertTrue(field.blocked(.5,.5,1.1,margin=0.))
        field._mark_cell(0,0,2.3,4.)
        self.assertEqual((1.8,4.),field.height_intervals[(0,0)][1])

    def test_resolution_edges_check_interior_without_weakening_collision(self):
        legacy=types.SimpleNamespace(_ground_height=lambda *args: 1.1)
        calls=[]
        def original(terrain,obstacles,start,end):
            calls.append((start,end))
            return not (.2 < end[0] < .3)
        self.assertFalse(baker._resolution_segment_clear(
            None,None,(0.,1.1,0.),(2.,1.1,0.),legacy,original))
        self.assertEqual(.25,calls[-1][1][0])
        self.assertTrue(baker._resolution_segment_clear(
            None,None,(0.,1.1,0.),(0.,1.1,2.),legacy,original))

    def test_northern_narrow_is_short_and_reversible_without_opening_side_cells(self):
        legacy = baker._legacy_baker()
        for name in ('04_himmelsdorf', '86_himmelsdorf_winter'):
            graph = json.loads((ROOT/'navgraphs'/(name+'.json')).read_bytes())
            self.assertEqual(2., graph['cell_size'])
            self.assertEqual((350, 350), (graph['width'], graph['height']))
            a, _ = legacy._nearest_node(graph, (175.887, 87.135))
            b, _ = legacy._nearest_node(graph, (180.55, 116.688))
            for start, end in ((a,b), (b,a)):
                path, distance = legacy._graph_path(graph, start, end)
                self.assertTrue(path)
                self.assertLess(distance, 40.)
            self.assertEqual([-300.,-300.], graph['origin'])
            a, _ = legacy._nearest_node(graph, (182.606,43.685))
            b, _ = legacy._nearest_node(graph, (175.887,87.135))
            for start,end in ((a,b),(b,a)):
                path,distance=legacy._graph_path(graph,start,end)
                self.assertTrue(path)
                self.assertLess(distance,60.)
            self.assertEqual([[2.,-250.],[70.,346.]], graph['bases'])

    def test_previous_profile_identity_preserves_custom_waypoints(self):
        for name in ('04_himmelsdorf', '86_himmelsdorf_winter'):
            meta = bot_tactics.MAPS[name]
            profile = bot_tactics.empty('retained authored route')
            route = dict(id='banana', team=2, symmetric=False,
                         points=[[70.,346.,0],[180.55,116.688,0],
                                 [175.887,87.135,0],[2.,-250.,0]])
            profile['maps'][name] = dict(mode='regular',
                resource_sha256=meta['navigation_previous_sha256'],
                routes=[], positions=[], default_routes=[route])
            result = bot_tactics.canonical(profile)['maps'][name]
            self.assertEqual(meta['resource_sha256'], result['resource_sha256'])
            self.assertEqual(route['points'], result['default_routes'][0]['points'])

    def test_grid_identity_reaches_serialized_final_motion_and_cached_state(self):
        import test_port_0922_complete_navigation_receipts as fixture
        f = fixture.RuntimeReceiptTests(); f.setUp()
        try:
            runtime = f.runtime
            graph = json.loads((ROOT/'navgraphs/04_himmelsdorf.json').read_bytes())
            runtime.baked_graph = graph
            state = runtime.states[11]
            state['_motion_stall_log'] = ((state['x'],state['y'],state['z']),-10.)
            out=io.StringIO()
            with redirect_stdout(out):
                runtime._log_motion_stall(state, {}, 0.,0.,False,{},3.)
                runtime._finish_motion_stall(state,False,False,
                    (state['x'],state['y'],state['z']),3.)
            rows = parse_lines(out.getvalue().splitlines())
            self.assertFalse(rows['issues'])
            row=next(r['data'] for r in rows['records'] if r['label']=='BOT MOTION')
            self.assertEqual(prebaked_navigation.graph_summary(graph),row['navigation']['grid'])
            self.assertEqual(2.,row['navigation']['grid']['cell_size'])
            self.assertEqual('after_contacts_and_support',row['execution_receipt']['phase'])
        finally:
            f.tearDown()


if __name__ == '__main__':
    unittest.main()
