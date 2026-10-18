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
    def test_sloping_face_keeps_local_height_and_vertical_wall_still_blocks(self):
        import test_port_0922_navigation_collision_bake as fixture
        field=baker.compiled_navigation_obstacles(
            fixture.compiled([]),fixture.VFS([]),baker._legacy_baker())
        field._raster_triangle(((0.,0.,0.),(20.,10.,0.),(0.,0.,20.)))
        self.assertFalse(field.blocked(.5,.5,1.1,margin=0.))
        self.assertTrue(field.blocked(4.5,.5,1.1,margin=0.))
        field._raster_triangle(((.5,0.,0.),(.5,8.,0.),(.5,8.,1.)))
        self.assertTrue(field.blocked(.5,.5,1.1,margin=0.))

    def test_first_run_and_reset_profile_uses_current_identities(self):
        profile=bot_tactics.default_profile()
        self.assertEqual(profile,bot_tactics.canonical(profile))
        for name in ('04_himmelsdorf','86_himmelsdorf_winter'):
            self.assertEqual(bot_tactics.MAPS[name]['resource_sha256'],
                             profile['maps'][name]['resource_sha256'])

    def test_preserved_rail_goal_uses_original_four_metre_support(self):
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        graph=json.loads((ROOT/'navgraphs/04_himmelsdorf.json').read_bytes())
        grid=TerrainGrid(lambda *args:None,baked_graph=graph)
        raw=grid.cell_for((-218.,1.1,-158.))
        safe=grid._nearest_baked_cell(raw,3)
        self.assertIsNotNone(safe)
        self.assertIsNotNone(grid._baked_cell_height(raw))
        self.assertEqual(raw,safe)
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

    def test_local_meshes_keep_original_base_and_short_bidirectional_passages(self):
        import subprocess, math
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        for name in ('04_himmelsdorf', '86_himmelsdorf_winter'):
            graph=json.loads((ROOT/'navgraphs'/(name+'.json')).read_bytes())
            baseline=json.loads(subprocess.check_output(['git','show','ca22f909:navgraphs/'+name+'.json'],cwd=ROOT))
            for key in ('cell_size','width','height','origin','heights_mm','links','hazards','routes','spawn_formations'):
                self.assertEqual(baseline[key],graph[key],key)
            grid=TerrainGrid(lambda *args:1.1,lambda *args:False,baked_graph=graph)
            self.assertEqual(4.,grid.cell_size)
            self.assertEqual([3.12,2.08],[grid.cell_size*.78,grid.cell_size*.52])
            for a,b,limit in (((182.606,43.685),(175.887,87.135),60.),
                              ((175.887,87.135),(180.55,116.688),45.),
                              ((190.536,151.486),(216.694,216.882),100.)):
                for first,last in ((a,b),(b,a)):
                    path=grid.plan((first[0],1.1,first[1]),(last[0],1.1,last[1]),max_expansions=4096)
                    self.assertTrue(path)
                    self.assertLess(sum(math.hypot(y[0]-x[0],y[2]-x[2]) for x,y in zip(path,path[1:])),limit)
                    for x,y in zip(path,path[1:]):
                        self.assertTrue(grid.segment_clear(x,y))
            self.assertLess(sum(p['width']*p['height'] for p in graph['local_meshes']),2200)

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

    def test_local_mesh_wire_keeps_base_arrays_and_adds_only_scoped_meshes(self):
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        from gui.mods.offline_lan_0922.native_navigation import NativeNavigation
        graph=json.loads((ROOT/'navgraphs/04_himmelsdorf.json').read_bytes())
        grid=TerrainGrid(lambda *args:1.1,lambda *args:False,baked_graph=graph)
        class Backend:
            def nav_open(self, value):
                self.value=value
                return 9
            def nav_close(self, context):
                pass
        backend=Backend();owner=NativeNavigation(grid,backend)
        self.addCleanup(owner.close)
        self.assertEqual(12,len(backend.value))
        self.assertEqual(4.,backend.value[2])
        self.assertEqual(30625,len(backend.value[5]))
        self.assertEqual(tuple(graph['links']),backend.value[6])
        self.assertEqual(2,len(backend.value[11]))
        from gui.mods.offline_lan_0922.navigation_graph_schema import validate_graph
        damaged=copy.deepcopy(graph);damaged['local_meshes'][0]['links'][0]=255
        with self.assertRaises(ValueError):
            validate_graph(damaged,'04_himmelsdorf')

    def test_original_and_test_build_profile_identities_both_migrate(self):
        for name in ('04_himmelsdorf','86_himmelsdorf_winter'):
            meta=bot_tactics.MAPS[name]
            for old in [meta['navigation_previous_sha256']]+meta['navigation_previous_sha256s']:
                profile=bot_tactics.default_profile()
                profile['maps'][name]['resource_sha256']=old
                result=bot_tactics.canonical(profile)
                self.assertEqual(meta['resource_sha256'],result['maps'][name]['resource_sha256'])

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
            self.assertEqual(4.,row['navigation']['grid']['cell_size'])
            self.assertEqual(2,len(row['navigation']['grid']['local_meshes']))
            self.assertEqual('after_contacts_and_support',row['execution_receipt']['phase'])
        finally:
            f.tearDown()


if __name__ == '__main__':
    unittest.main()
