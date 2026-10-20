"""Recorded wreck exits: advisory geometry must not replace physical contact."""
import json
import math
from pathlib import Path
import unittest
from gui.mods.offline_lan_0922.ai.navigation import (
    TerrainGrid, STATIC_HULL_PLANNING_INSET)
from gui.mods.offline_lan_0922 import tank_collision as collision

ROOT = Path(__file__).resolve().parents[1]


class WreckEdgeAvoidanceTests(unittest.TestCase):
    def grid(self, hulls, clearance=0.):
        grid = TerrainGrid(lambda *a: 0., obstacle_probe=lambda *a: False)
        grid.set_static_hulls(hulls,clearance=clearance)
        return grid

    def test_recorded_t28_nameless_jagdpanther_exits_are_not_coarse_wreck_vetoes(self):
        data = json.loads((ROOT/'tests/fixtures/wreck_edge_20261020.json').read_text())
        for case in data['cases']:
            with self.subTest(actor=case['actor']):
                own, peers, end = case['own'], case['peers'], case['end']
                start = own['x'], own['y'], own['z']
                hulls = [(p['id'], p['x'], p['z'], p['yaw'], p['shape'][1], p['shape'][0]) for p in peers]
                grid = self.grid(hulls,clearance=1.981354)
                self.assertEqual(0., grid.segment_penalty(start, end, case['at']))
                self.assertFalse(grid.path_crosses_static_hull((start, end)))
                self.assertEqual(1., collision.translation_fraction(own,
                    (end[0]-start[0], end[2]-start[2]), peers))
                self.assertEqual(tuple(hulls), grid._static_hulls)

    def test_only_fifteen_centimetre_planning_border_is_released(self):
        hull = (7, 0., 0., 0., 3.5, 1.7)
        grid = self.grid((hull,))
        self.assertEqual(.15, STATIC_HULL_PLANNING_INSET)
        for x, crossing in ((0., True), (1.54, True), (1.56, False), (1.69, False), (1.71, False)):
            a, b = (x, 0., -6.), (x, 0., 6.)
            self.assertEqual(crossing, grid.path_crosses_static_hull((a,b)))
            self.assertEqual(crossing, grid.segment_penalty(a,b,0.) > 0.)
            self.assertEqual(crossing, grid.path_crosses_static_hull((b,a)))
        # Planning admission cannot shrink or bypass physical contact.
        own = dict(id=1,x=1.6, y=0., z=-7., yaw=0., shape=(1.,2.,0.,2.))
        peer = dict(id=7,x=0.,y=0.,z=0.,yaw=0.,shape=(1.7,3.5,0.,2.))
        self.assertLess(collision.translation_fraction(own,(0.,14.),[peer]),1.)
        self.assertEqual((1.7,3.5,0.,2.),peer['shape'])

    def test_rotated_subcell_crossings_and_cache_move_clear_are_consistent(self):
        grid = self.grid(((7, 2., 2., math.pi/4, 3.5, 1.7),))
        a,b = (1.,0.,1.), (3.,0.,3.)
        self.assertGreater(grid.segment_penalty(a,b,0.),0.)
        self.assertTrue(grid.path_crosses_static_hull((a,b)))
        self.assertTrue(grid.set_static_hulls(((7,40.,40.,math.pi/4,3.5,1.7),)))
        self.assertEqual(0.,grid.segment_penalty(a,b,0.))
        grid.set_static_hulls(())
        self.assertFalse(grid.path_crosses_static_hull((a,b)))

    def test_timed_failure_and_real_terrain_veto_remain(self):
        grid = self.grid(((7,0.,0.,0.,3.5,1.7),))
        a,b = (8.,0.,-8.), (8.,0.,8.)
        grid._edge_keys_for_segment = lambda *a: (((0,0),(0,1)),)
        key = ((0,0),(0,1))
        grid._failed_edges[key] = (10.,240.)
        proof = {}
        self.assertFalse(grid.dry_segment_clear(a,b,0.,proof))
        self.assertEqual('timed_failed_edge',proof['egress_reason'])
        self.assertTrue(proof['timed_failure'])
        self.assertFalse(proof['static_hull_crossing'])
        grid._failed_edges.clear()
        grid.segment_clear = lambda *a: False
        self.assertFalse(grid.dry_segment_clear(a,b,11.,proof))
        self.assertEqual('terrain_or_native_rejected',proof['egress_reason'])


if __name__ == '__main__':
    unittest.main()
