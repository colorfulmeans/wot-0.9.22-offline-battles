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
    def test_all_eight_circled_passages_are_short_reversible_and_collision_proved(self):
        import math
        from check_navigation_resolution import inspect
        from build_local_navigation_meshes import CIRCLED_PASSAGES
        maps=[]
        for name in ('04_himmelsdorf','86_himmelsdorf_winter'):
            graph=json.loads((ROOT/'navgraphs'/(name+'.json')).read_bytes())
            maps.append(graph)
            cases=[(a,b) for first,last in CIRCLED_PASSAGES for a,b in ((first,last),(last,first))]
            records=inspect(graph,cases)
            self.assertEqual(16,len(records))
            for row in records:
                self.assertTrue(row['connected'],row)
                a,b=row['start'],row['end']
                self.assertLess(row['length'],math.hypot(b[0]-a[0],b[1]-a[1])*1.8+12.,row)
            proof=graph['bake']['local_meshes']['circled_passage_validation']
            self.assertEqual(16,len(proof))
            self.assertEqual({.25},{r['collision_sample_metres'] for r in proof})
            self.assertEqual({2.15},{r['half_width'] for r in proof})
        for a,b in zip(maps[0]['local_meshes'],maps[1]['local_meshes']):
            for field in ('origin','cell_size','width','height','links'):
                self.assertEqual(a[field],b[field],field)
        a=bot_tactics.default_map('04_himmelsdorf')['default_routes']
        b=bot_tactics.default_map('86_himmelsdorf_winter')['default_routes']
        # Independent class exclusions may differ; retained enabled travel agrees.
        self.assertEqual([r for r in a if r['id']!='rear_guard' and not r.get('disabled')],
                         [r for r in b if not r.get('disabled')])

    def test_local_exact_collision_keeps_width_and_does_not_inflate_wall_cells(self):
        import test_port_0922_navigation_collision_bake as fixture
        field=baker.compiled_navigation_obstacles(fixture.compiled([]),fixture.VFS([]),
            baker._legacy_baker(),precise_regions=((-10.,-10.,10.,10.),))
        wall=((0.,0.,-10.),(0.,10.,-10.),(0.,0.,10.))
        field._raster_triangle(wall)
        self.assertTrue(field.blocked(2.1,0.,1.1,margin=2.15))
        self.assertFalse(field.blocked(2.2,0.,1.1,margin=2.15))
        roof=((-5.,10.,-5.),(5.,10.,-5.),(0.,10.,5.))
        self.assertFalse(baker.collision_triangle_blocks_disk(roof,0.,0.,1.75,3.5,2.15))
        ground=((-5.,0.,-5.),(5.,0.,-5.),(0.,0.,5.))
        self.assertFalse(baker.collision_triangle_blocks_disk(ground,0.,0.,1.75,3.5,2.15))

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
        self.assertIsNone(grid._baked_cell_height(raw))
        self.assertIn(raw[1]*graph['width']+raw[0],graph['bake']['railway_obstacles']['layers'][0]['removed_node_indices'])
        self.assertNotEqual(raw,safe)
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
        import subprocess, math, copy
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        for name in ('04_himmelsdorf', '86_himmelsdorf_winter'):
            graph=json.loads((ROOT/'navgraphs'/(name+'.json')).read_bytes())
            baseline=json.loads(subprocess.check_output(['git','show','ca22f909:navgraphs/'+name+'.json'],cwd=ROOT))
            for key in ('cell_size','width','height','origin','hazards','routes'):
                self.assertEqual(baseline[key],graph[key],key)
            expected=copy.deepcopy(baseline['spawn_formations'])
            for change in graph['validation']['spawn_railway_revalidation']['changes']:
                self.assertEqual(expected[change['team']][change['slot']],change['before'])
                expected[change['team']][change['slot']]=change['after']
            self.assertEqual(expected,graph['spawn_formations'])
            removed=set(graph['bake']['railway_obstacles']['layers'][0]['removed_node_indices'])
            for index,(old,new) in enumerate(zip(baseline['heights_mm'],graph['heights_mm'])):
                self.assertEqual(None if index in removed else old,new)
            self.assertTrue(all((old&new)==new for old,new in zip(baseline['links'],graph['links'])))
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
            self.assertLess(sum(p['width']*p['height'] for p in graph['local_meshes']),30625)

    def test_local_meshes_do_not_retire_any_original_passage_link(self):
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        for name in ('04_himmelsdorf','86_himmelsdorf_winter'):
            graph=json.loads((ROOT/'navgraphs'/(name+'.json')).read_bytes())
            grid=TerrainGrid(lambda *args:None,lambda *args:True,baked_graph=graph)
            for patch in graph['local_meshes']:
                for i in range(patch['width']*patch['height']):
                    point=(patch['origin'][0]+i%patch['width']*patch['cell_size'],1.1,
                           patch['origin'][1]+i//patch['width']*patch['cell_size'])
                    base=grid._baked_cell_height(grid.cell_for(point))
                    if base is not None:
                        self.assertEqual(base,grid._routing_height(point))
            for first, neighbours in grid._local_meshes.edges.items():
                for last in neighbours:
                    self.assertIn(first,grid._local_meshes.edges[last])
            for index,mask in enumerate(graph['links']):
                cell=(index%graph['width'],index//graph['width'])
                for bit,(dx,dz) in enumerate(graph['directions']):
                    if not mask & (1<<bit):
                        continue
                    first=grid.point_for(cell,grid._baked_cell_height(cell))
                    other=(cell[0]+dx,cell[1]+dz)
                    last=grid.point_for(other,grid._baked_cell_height(other))
                    if grid._local_meshes.touches(first,last):
                        self.assertTrue(grid._baked_corridor(first,last)[0],(name,cell,other))
                        self.assertIn(tuple(sorted((cell,other))),grid._edge_keys_for_segment(first,last))

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
        self.assertEqual(9,len(backend.value[11]))
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

    def test_manifest_editor_and_actual_local_mesh_bytes_have_one_identity(self):
        import hashlib
        rows=json.loads((ROOT/'navgraphs/manifest.json').read_bytes())['maps']
        for name in ('04_himmelsdorf','86_himmelsdorf_winter'):
            raw=(ROOT/'navgraphs'/(name+'.json')).read_bytes()
            identity=hashlib.sha256(raw).hexdigest()
            self.assertNotIn(b'\r\n',raw)
            self.assertEqual(identity,bot_tactics.MAPS[name]['resource_sha256'])
            self.assertEqual(identity,next(row['sha256'] for row in rows if row['map']==name))

    def test_retained_local_mesh_receipt_does_not_keep_previous_round_grid_alive(self):
        import weakref
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        graph=json.loads((ROOT/'navgraphs/04_himmelsdorf.json').read_bytes())
        grid=TerrainGrid(lambda *args:1.1,baked_graph=graph)
        mesh=grid._local_meshes
        previous=weakref.ref(grid)
        del grid
        self.assertIsNone(previous())
        self.assertTrue(mesh.points)

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
            self.assertEqual(9,len(row['navigation']['grid']['local_meshes']))
            self.assertEqual('after_contacts_and_support',row['execution_receipt']['phase'])
        finally:
            f.tearDown()


if __name__ == '__main__':
    unittest.main()
