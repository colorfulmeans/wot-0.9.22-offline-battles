"""Distance owns routing; slope ranks legal choices at equal progress."""
import math
import unittest
from unittest import mock
from test_port_0922_navigation import TerrainGrid, StaticHullNavigationTests


class DistanceGradeTests(unittest.TestCase):
    def grid(self):
        return TerrainGrid(lambda x,z,h: .1*x,
            lambda *args: False, baked_graph=StaticHullNavigationTests._flat_graph())

    def test_local_distance_beats_flatness(self):
        grid=self.grid()
        grid._ground=lambda x,z,h: .1*x
        grid.segment_penalty=lambda *args:0.
        grid.segment_has_baked_hazard=lambda *args:False
        grid.segment_clear=lambda *args:True
        # The shortest progress candidate is on a legal slope. A flatter
        # angled candidate must not override progress toward the route point.
        grid._terrain_grade=lambda p: 1. if abs(p[0])<.01 else 0.
        receipt={}
        target=grid.safe_local_target((20.,0.,20.),(20.,0.,80.),0.,diagnostic=receipt)
        self.assertAlmostEqual(20.,target[0])
        self.assertGreater(target[2],22.)
        self.assertEqual(3,len(receipt['distance_then_grade']))

    def test_baked_grade_reads_transverse_slope_without_native_query(self):
        graph=StaticHullNavigationTests._flat_graph()
        graph['heights_mm']=[100*x for z in range(21) for x in range(21)]
        probe=mock.Mock(side_effect=AssertionError('no engine query needed'))
        grid=TerrainGrid(probe,lambda *args:False,baked_graph=graph)
        self.assertAlmostEqual(.025,grid._terrain_grade((40.,1.,40.)))
        probe.assert_not_called()

    def test_unavoidable_legal_slope_remains_routable(self):
        graph=StaticHullNavigationTests._flat_graph()
        graph['heights_mm']=[200*z for z in range(21) for x in range(21)]
        grid=TerrainGrid(lambda *args:0.,lambda *args:False,baked_graph=graph)
        path=grid.plan((4.,.2,4.),(68.,3.4,68.),max_expansions=4096)
        self.assertTrue(path)
        self.assertLess(math.hypot(path[-1][0]-68.,path[-1][2]-68.),1.)

    def test_equal_length_forks_prefer_the_flatter_side(self):
        for flat_z in (5,15):
            graph=StaticHullNavigationTests._flat_graph()
            graph['heights_mm']=[None if x==10 and z not in (5,15)
                else int(150*abs(z-flat_z)) for z in range(21) for x in range(21)]
            grid=TerrainGrid(lambda *args:0.,lambda *args:False,baked_graph=graph)
            path=grid.plan((4.,.75,40.),(76.,.75,40.),prefer_clearance=False,max_expansions=4096)
            self.assertTrue(path)
            self.assertTrue(any(abs(p[0]-40.)<.01 and abs(p[2]-flat_z*4.)<.01 for p in path))


if __name__=='__main__':unittest.main()
