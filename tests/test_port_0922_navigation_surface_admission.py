"""Withdraw Windows350 surface policy without deleting legacy safety checks."""
import ast
import math
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_port_0922_navigation import TerrainGrid, StaticHullNavigationTests
from gui.mods.offline_lan_0922.ai.driver import NAVIGATION_MAX_GRADE


class LegacyLocalChoiceTests(unittest.TestCase):
    def test_complete_old_distance_turn_avoidance_order_is_restored(self):
        grid=TerrainGrid(lambda *args:0., lambda *args:False,
            baked_graph=StaticHullNavigationTests._flat_graph())
        calls=[]
        # A leftover/externally injected surface seam must not affect ranking.
        grid.directional_surface_probe=lambda *args:calls.append(args) or dict(status='hit',grade=1.)
        for avoid in (None,[(20.,0.,24.)]):
            receipt={}
            target=grid.safe_local_target((20.,0.,20.),(20.,0.,70.),0.,
                avoid_points=avoid,diagnostic=receipt)
            rows=[r for r in receipt['candidates'] if r['rejected'] is None]
            expected=min(rows,key=lambda row:(row['D']+row['C'],abs(row['theta'])))
            self.assertEqual(expected['point'],target)
            for row in rows:
                self.assertAlmostEqual(row['C'],abs(row['theta'])*3.5+
                    grid._penalty(grid.cell_for(row['point']),avoid,False)*2.)
            self.assertNotIn('surface_choices',receipt)
        self.assertEqual([],calls)


class LegacyMovementAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[1]/'src/res/scripts/client/gui/mods/offline_lan_0922/battle_runtime.py'
        node=next(n for n in ast.parse(path.read_text(encoding='utf8')).body
                  if isinstance(n,ast.ClassDef) and n.name=='BattleRuntime')
        method=next(n for n in node.body if isinstance(n,ast.FunctionDef)
                    and n.name=='_direction_probe')
        namespace=dict(math=math,_xyz=lambda p:(p.x,p.y,p.z) if hasattr(p,'x') else tuple(p),
            NAVIGATION_MAX_GRADE=NAVIGATION_MAX_GRADE,
            BOT_WATER_AVOID_DEPTH=1.2,BOT_WATER_ESCAPE_DEEPEN_EPSILON=.05)
        exec(compile(ast.Module(body=[method],type_ignores=[]),'legacy_direction','exec'),namespace)
        cls.direction=staticmethod(namespace['_direction_probe'])

    def runtime(self, grade=0., normal_angle=34., wall=False):
        calls=[]
        def vector(point):return SimpleNamespace(x=point[0],y=point[1],z=point[2])
        def collide(start,end,trace):
            if start.x==end.x and start.z==end.z:
                return (vector((start.x,grade*start.z,start.z)),
                    (0.,1.,-math.tan(math.radians(normal_angle))))
            return (vector((0.,0.,0.)),(0.,0.,1.)) if wall else None
        runtime=SimpleNamespace(_water_depth=lambda *args:0.,_vector=vector,
            _collide_navigation=collide,_record_navigation_hit=lambda *args:None,
            _navigation_direction_surface=lambda *args:calls.append(args) or dict(status='hit',grade=1.))
        return runtime,calls

    def test_single_steep_normal_cannot_veto_forward_or_reverse(self):
        for yaw in (0.,math.pi):
            for normal_angle in (29.5,34.,50.):
                with self.subTest(yaw=yaw,normal_angle=normal_angle):
                    runtime,calls=self.runtime(normal_angle=normal_angle)
                    result=self.direction(runtime,(0.,0.,0.),yaw,
                        descriptor=object(),corridor_half_width=2.)
                    self.assertTrue(result['clear'])
                    self.assertEqual([],calls)

    def test_mandatory_admitted_climb_and_descent_keep_legacy_admission(self):
        runtime,calls=self.runtime(grade=.35)
        for yaw in (0.,math.pi):
            result=self.direction(runtime,(0.,0.,0.),yaw,
                descriptor=object(),corridor_half_width=2.)
            self.assertTrue(result['clear'])
            self.assertAlmostEqual(.35 if yaw==0. else -.35,result['slope'])

    def test_legacy_continuous_grade_and_real_wall_protection_remain(self):
        for grade,wall,reason in ((.8,False,'planning_grade'),(0.,True,'planning_collision')):
            runtime,calls=self.runtime(grade=grade,wall=wall)
            result=self.direction(runtime,(0.,0.,0.),0.,
                descriptor=object(),corridor_half_width=2.)
            self.assertFalse(result['clear'])
            self.assertEqual(reason,result['reason'])

    def test_missing_ground_keeps_the_new_diagnostic_ray_evidence(self):
        runtime,calls=self.runtime()
        runtime._collide_navigation=lambda *args:None
        result=self.direction(runtime,(47.,-1.,-266.),0.,
            descriptor=object(),corridor_half_width=2.)
        self.assertEqual('planning_ground_missing',result['reason'])
        self.assertEqual((47.,3.5,-258.),result['native_trace']['ray_start'])
        self.assertEqual((47.,-6.,-258.),result['native_trace']['ray_end'])


if __name__=='__main__':unittest.main()
