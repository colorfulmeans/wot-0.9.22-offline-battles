"""Replay real narrow-gateway turns and preserve existing query decisions."""
import json
from pathlib import Path
import unittest
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
from gui.mods.offline_lan_0922 import bot_tactics

ROOT = Path(__file__).resolve().parents[1]


class LocalMeshPoseTests(unittest.TestCase):
    def grid(self):
        return TerrainGrid(lambda *a: None, baked_graph=json.loads(
            (ROOT/'navgraphs/86_himmelsdorf_winter.json').read_bytes()))

    def test_recorded_jagdpz_and_t95_turns_use_fine_support(self):
        grid = self.grid()
        for point, yaw, width, length in (
            ((105.12158372134759,1.1,151.16519557093042),2.025630695940001,2.047271966934204,4.054581165313721),
            ((206.71414726557165,1.1,179.79109147828575),-1.5383362118961221,2.1738998889923096,3.6082069873809814)):
            self.assertTrue(grid.hull_pose_clear(point,yaw,length,width))
            mesh = grid._local_meshes
            grid._local_meshes = None
            self.assertFalse(grid.hull_pose_clear(point,yaw,length,width))
            grid._local_meshes = mesh

    def test_real_walls_still_refuse_hull_pose(self):
        grid = self.grid()
        self.assertFalse(grid.hull_pose_clear((0.,1.1,180.),0.,4.,2.))

    def test_all_recorded_queries_match_before_optimization_and_after_cache_reuse(self):
        grid = self.grid()
        mesh = grid._local_meshes
        cases = json.loads((ROOT/'tests/fixtures/himmelsdorf-200200-local-queries.json').read_bytes())
        for repeat in range(2):
            for row in cases:
                a,b = row['start'],row['end']
                self.assertEqual(row['touches'],mesh.touches(a,b))
                for flag,expected in zip((False,True),row['crossed']):
                    self.assertEqual(expected,[list(c) for c in mesh.crossed(a,b,flag)])
        self.assertLessEqual(len(mesh._crossings),256)
        self.assertLessEqual(len(mesh._segments),256)

    def test_spatial_index_keeps_inclusive_patch_boundaries_and_priority(self):
        grid = self.grid()
        mesh = grid._local_meshes
        for patch in mesh.patches:
            for z in range(patch['height']):
                for x in range(patch['width']):
                    point = (patch['origin'][0]+x*patch['cell_size'],0.,patch['origin'][1]+z*patch['cell_size'])
                    expected = None
                    for i,p in enumerate(mesh.patches):
                        px=(point[0]-p['origin'][0])/p['cell_size']
                        pz=(point[2]-p['origin'][1])/p['cell_size']
                        if 0<=px<=p['width']-1 and 0<=pz<=p['height']-1:
                            expected=mesh.keys[i][int(pz+.5)*p['width']+int(px+.5)]
                            break
                    self.assertEqual(expected,mesh.cell(point))

    def test_el_halluf_saved_light_valley_is_packaged_for_both_teams(self):
        rows=bot_tactics.default_map('29_el_hallouf')['default_routes']
        routes=[r for r in rows if r.get('class_tag')=='lightTank' and r['id']=='south_valley']
        self.assertEqual({1,2},{r['team'] for r in routes})
        for r in routes:
            # The adopted owner baseline removes a collinear valley sample;
            # retain both ends of that valley leg and its exact reverse route.
            self.assertIn([159.894,60.0291,0],r['points'])
            self.assertIn([-5.2176,-55.4219,0],r['points'])
        self.assertEqual(routes[0]['points'],list(reversed(routes[1]['points'])))


if __name__ == '__main__':
    unittest.main()
