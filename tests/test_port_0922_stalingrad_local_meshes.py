"""Circled city gaps use a bounded local mesh, preserving authored roads."""
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build_stalingrad_local_meshes as builder
from gui.mods.offline_lan_0922 import bot_tactics, prebaked_navigation as pn
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid


class StalingradLocalMeshesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=json.loads((ROOT/'navgraphs/92_stalingrad.json').read_text())
        cls.graph=pn.with_shore_hazards(cls.raw)

    def test_fourteen_bounded_two_metre_patches_keep_the_coarse_base(self):
        self.assertEqual(4.,self.raw['cell_size'])
        patches=self.raw['local_meshes']
        self.assertEqual(14,len(patches))
        self.assertTrue(all(p['cell_size']==2. for p in patches))
        self.assertLess(sum(p['width']*p['height'] for p in patches),20000)
        self.assertEqual([list(r) for r in builder.REGIONS],self.raw['bake']['local_meshes']['regions'])

    def test_owner_authored_points_waits_and_defense_are_unchanged(self):
        entry=bot_tactics.default_profile()['maps']['92_stalingrad']
        entry.pop('resource_sha256')
        digest=hashlib.sha256(json.dumps(entry,sort_keys=True,separators=(',',':')).encode('ascii')).hexdigest()
        self.assertEqual('81cc0b9346f29ba36d1654a88cb557fe5c06d525739657ce42f9797e3c3de12a',digest)

    def test_every_local_link_is_supported_reversible_and_inside_its_patch(self):
        directions=self.raw['directions']
        for p in self.raw['local_meshes']:
            for i,mask in enumerate(p['links']):
                if mask:self.assertIsNotNone(p['heights_mm'][i])
                for bit,(dx,dz) in enumerate(directions):
                    if not mask & (1<<bit):continue
                    nx,nz=i%p['width']+dx,i//p['width']+dz
                    self.assertTrue(0<=nx<p['width'] and 0<=nz<p['height'])
                    j=nz*p['width']+nx
                    self.assertIsNotNone(p['heights_mm'][j])
                    self.assertTrue(p['links'][j] & (1<<directions.index([-dx,-dz])))
                    if dx and dz:
                        self.assertIsNotNone(p['heights_mm'][(i//p['width'])*p['width']+nx])
                        self.assertIsNotNone(p['heights_mm'][nz*p['width']+i%p['width']])

    def test_all_circled_passages_reach_both_ends_without_remote_detours(self):
        rows=builder.prove(self.graph)
        self.assertEqual(28,len(rows))
        for row in rows:
            self.assertLess(row['length'],math.dist(row['start'],row['end'])*1.8+12.)

    def test_previous_problem_edges_are_local_and_do_not_gain_a_height_layer(self):
        grid=TerrainGrid(lambda *args:None,baked_graph=self.graph)
        for a,b,limit in (((-168.7496,-210.6374),(-167.4814,-245.493),50.),
                          ((-375.8577,-294.8617),(-293.8373,-315.8436),110.)):
            for start,end in ((a,b),(b,a)):
                path=grid.plan((start[0],0.,start[1]),(end[0],0.,end[1]),max_expansions=100000)
                distance=sum(math.hypot(y[0]-x[0],y[2]-x[2]) for x,y in zip(path,path[1:]))
                self.assertLess(distance,limit)
                self.assertLess(max(p[1] for p in path)-min(p[1] for p in path),1.)

    def test_wall_and_missing_support_samples_are_still_closed(self):
        rejected=0
        grid=TerrainGrid(lambda *args:None,baked_graph=self.graph)
        for number,p in enumerate(self.raw['local_meshes']):
            for i,y in enumerate(p['heights_mm']):
                if y is not None:continue
                rejected+=1
                self.assertEqual(0,p['links'][i])
                key=grid._local_meshes.keys[number][i]
                self.assertIsNone(grid._baked_index(key))
        self.assertGreater(rejected,1000)


if __name__=='__main__':unittest.main()
