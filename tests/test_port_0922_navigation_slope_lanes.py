"""Report 211816: a supported high shoulder is not a vertical obstacle."""
import math
import types
import unittest
import test_port_0922_battle_runtime as fixtures
from test_port_0922_world_collision import _Vector


class NavigationSlopeLaneTests(unittest.TestCase):
    def scene(self, sx=1., sz=1., obstacle=None):
        runtime=fixtures._runtime();runtime.math=types.SimpleNamespace(Vector3=_Vector)
        battle=fixtures.BattleRuntime(runtime);battle._avatar=runtime.bigworld.avatar
        calls=[]
        grade=.6 if obstacle=='steep' else .15
        def ground(x,z):return grade*z+(.25+.05*sz*z)*sx*x
        def collide(a,b,trace=None):
            calls.append((a,b))
            hits=[];dx,dy,dz=b.x-a.x,b.y-a.y,b.z-a.z
            # All three corridor lanes have constant X; vertical samples do too.
            self.assertAlmostEqual(0.,dx,places=8)
            delta_ground=(grade+.05*sz*sx*a.x)*dz
            denominator=dy-delta_ground
            if abs(denominator)>1.e-10:
                t=(ground(a.x,a.z)-a.y)/denominator
                if 0.<=t<=1. and not (obstacle=='gap' and abs(dz)<1.e-9 and 1.8<abs(a.z)<3.):
                    normal=_Vector(-sx*(.25+.05*sz*a.z),1.,-grade-.05*sz*sx*a.x)
                    hits.append((t,normal))
            if obstacle in ('wall','beam') and abs(dz)>1.e-10:
                t=(sz*3.7-a.z)/dz
                if 0.<=t<=1.:
                    y=a.y+dy*t;g=ground(a.x,sz*3.7)
                    low,high=(1.4,1.8) if obstacle=='beam' else (0.,2.)
                    if g+low<=y<=g+high:hits.append((t,_Vector(0.,0.,-sz)))
            if not hits:return None
            t,normal=min(hits,key=lambda row:row[0])
            return (a+(b-a).scale(t),normal,0)
        battle._collide_navigation=collide
        battle._water_depth=lambda unused:-1.
        return battle,calls,grade

    def test_all_four_bank_directions_recast_above_proved_support(self):
        for sx in (-1.,1.):
            for sz in (-1.,1.):
                with self.subTest(sx=sx,sz=sz):
                    battle,calls,grade=self.scene(sx,sz)
                    trace={}
                    self.assertFalse(battle._navigation_obstacle((0.,0.,0.),(0.,grade*sz*4.,sz*4.),2.15,trace=trace))
                    self.assertEqual('clear',trace['classification'])
                    self.assertTrue(any(p['verdict']=='continuous_support_lane_clear'
                                        for p in trace['slope_lane_proofs']))

    def test_wall_beam_gap_and_excess_grade_are_not_hidden_by_the_first_terrain_hit(self):
        for obstacle in ('wall','beam','gap','steep'):
            with self.subTest(obstacle=obstacle):
                battle,calls,grade=self.scene(obstacle=obstacle)
                self.assertTrue(battle._navigation_obstacle((0.,0.,0.),(0.,grade*4.,4.),2.15))

    def test_empty_original_corridor_does_not_spend_support_queries(self):
        battle,calls,grade=self.scene()
        battle._collide_navigation=lambda a,b,trace=None:calls.append((a,b))
        self.assertFalse(battle._navigation_obstacle((0.,0.,0.),(0.,0.,4.),2.15))
        self.assertEqual(6,len(calls))


if __name__=='__main__':unittest.main()
