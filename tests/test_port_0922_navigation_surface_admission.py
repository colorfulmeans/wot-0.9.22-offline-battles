"""Real travel normals and support-layer continuity without changing route retries."""
import ast
import math
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_port_0922_navigation import TerrainGrid, StaticHullNavigationTests


class DirectionPreferenceTests(unittest.TestCase):
    def grid(self, probe):
        grid = TerrainGrid(lambda *args: 0., lambda *args: False,
            baked_graph=StaticHullNavigationTests._flat_graph())
        grid.directional_surface_probe = probe
        return grid

    def test_nearby_direction_can_prefer_a_gentler_normal_with_old_cost_retained(self):
        calls = []
        def probe(position, yaw, distance):
            calls.append((yaw, distance))
            return dict(status='hit', grade=.35 if abs(yaw) < .1 else .02)
        grid = self.grid(probe)
        receipt = {}
        target = grid.safe_local_target((20.,0.,20.), (20.,0.,70.), 0., diagnostic=receipt)
        self.assertNotEqual(receipt['legacy_selected'], target)
        self.assertAlmostEqual(.45, abs(math.atan2(target[0]-20., target[2]-20.)))
        self.assertLessEqual(len(calls), 3)
        eligible = [r for r in receipt['candidates'] if r['rejected'] is None]
        original = min(eligible, key=lambda r: (r['D']+r['C'],abs(r['theta'])))
        chosen = next(r for r in eligible if r['point'] == target)
        self.assertLessEqual(chosen['score']-original['score'], 2.)
        self.assertAlmostEqual(3.5*abs(chosen['theta']), chosen['C'])

    def test_unavoidable_admitted_slope_still_advances_toward_the_goal(self):
        grid = self.grid(lambda *args: dict(status='hit',grade=.4))
        receipt = {}
        target = grid.safe_local_target((20.,0.,20.), (20.,0.,70.), 0.,diagnostic=receipt)
        self.assertEqual(receipt['legacy_selected'],target)
        self.assertGreater(target[2],20.)

    def test_missing_normal_is_not_flat_and_keeps_legacy_choice(self):
        grid = self.grid(lambda *args: dict(status='missing'))
        receipt = {}
        target = grid.safe_local_target((20.,0.,20.), (20.,0.,70.), 0.,diagnostic=receipt)
        self.assertEqual(receipt['legacy_selected'],target)

    def test_tiny_normal_noise_does_not_start_side_to_side_steering(self):
        grid=self.grid(lambda position,yaw,distance:dict(status='hit',
            grade=.003 if abs(yaw)<.1 else .001))
        receipt={}
        target=grid.safe_local_target((20.,0.,20.),(20.,0.,70.),0.,diagnostic=receipt)
        self.assertEqual(receipt['legacy_selected'],target)

    def test_unknown_old_direction_cannot_be_ranked_as_a_steep_surface(self):
        def probe(position,yaw,distance):
            return dict(status='missing') if abs(yaw)<.1 else dict(status='hit',grade=0.)
        grid=self.grid(probe);receipt={}
        target=grid.safe_local_target((20.,0.,20.),(20.,0.,70.),0.,diagnostic=receipt)
        self.assertEqual(receipt['legacy_selected'],target)

    def test_avoidance_penalty_cannot_be_erased_by_a_flat_surface(self):
        grid = self.grid(lambda position,yaw,distance:dict(status='hit',grade=0.))
        receipt = {}
        target = grid.safe_local_target((20.,0.,20.), (20.,0.,70.), 0.,
            avoid_points=[(20.,0.,24.)],diagnostic=receipt)
        self.assertEqual(receipt['legacy_selected'],target)
        for row in receipt['candidates']:
            if row['rejected'] is None:
                self.assertAlmostEqual(row['C'],abs(row['theta'])*3.5+
                    grid._penalty(grid.cell_for(row['point']),[(20.,0.,24.)],False)*2.)

    def test_other_side_of_map_cannot_win_just_because_it_is_flat(self):
        calls = []
        def probe(position,yaw,distance):
            calls.append(yaw)
            return dict(status='hit',grade=.3 if abs(yaw)<.5 else 0.)
        grid=self.grid(probe); receipt={}
        target=grid.safe_local_target((20.,0.,20.),(20.,0.,70.),0.,diagnostic=receipt)
        self.assertEqual(receipt['legacy_selected'],target)
        self.assertTrue(all(abs(yaw)<=.45+1e-8 for yaw in calls))


class NativeSurfaceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[1]/'src/res/scripts/client/gui/mods/offline_lan_0922/battle_runtime.py'
        node=next(n for n in ast.parse(path.read_text(encoding='utf8')).body
                  if isinstance(n,ast.ClassDef) and n.name=='BattleRuntime')
        method=next(n for n in node.body if isinstance(n,ast.FunctionDef)
                    and n.name=='_navigation_direction_surface')
        method.decorator_list=[]
        namespace=dict(math=math,_xyz=lambda p:(p.x,p.y,p.z) if hasattr(p,'x') else tuple(p))
        exec(compile(ast.Module(body=[method],type_ignores=[]),'surface_contract','exec'),namespace)
        cls.probe=staticmethod(namespace['_navigation_direction_surface'])
        method=next(n for n in node.body if isinstance(n,ast.FunctionDef)
                    and n.name=='_direction_probe')
        namespace.update(NAVIGATION_MAX_GRADE=math.tan(math.radians(26.)),
            BOT_WATER_AVOID_DEPTH=1.2,BOT_WATER_ESCAPE_DEEPEN_EPSILON=.05)
        exec(compile(ast.Module(body=[method],type_ignores=[]),'direction_contract','exec'),namespace)
        cls.direction=staticmethod(namespace['_direction_probe'])

    def runtime(self, normal=(0.,1.,-.4)):
        calls=[]
        def collide(start,end,trace):
            calls.append((start,end))
            return (SimpleNamespace(y=0.),normal)
        runtime=SimpleNamespace(_vector=lambda p:p,_collide_navigation=collide,
            _record_navigation_hit=lambda *args:None)
        return runtime,calls

    def test_reverse_travel_samples_the_rear_and_keeps_signed_grade(self):
        runtime,calls=self.runtime()
        front=self.probe(runtime,(0.,0.,0.),0.,3.)
        rear=self.probe(runtime,(0.,0.,0.),math.pi,3.)
        self.assertAlmostEqual(.4,front['grade'])
        self.assertAlmostEqual(-.4,rear['grade'])
        self.assertGreater(calls[0][0][2],0.)
        self.assertLess(calls[1][0][2],0.)

    def test_missing_and_malformed_normals_stay_unknown(self):
        runtime,calls=self.runtime((0.,float('nan'),0.))
        self.assertEqual('invalid_surface',self.probe(runtime,(0.,0.,0.),0.,3.)['status'])
        runtime._collide_navigation=lambda *args:None
        self.assertEqual('missing',self.probe(runtime,(0.,0.,0.),0.,3.)['status'])

    def test_captured_34_degree_near_bank_is_not_a_flat_distant_chord(self):
        runtime=SimpleNamespace(_water_depth=lambda *args:0.,
            _navigation_direction_surface=lambda *args:dict(status='hit',
                grade=math.tan(math.radians(34.))))
        result=self.direction(runtime,(0.,0.,0.),0.,descriptor=object(),corridor_half_width=2.)
        self.assertFalse(result['clear'])
        self.assertEqual('planning_surface_grade',result['reason'])

    def test_admitted_large_slope_is_not_rejected_for_being_nonflat(self):
        def vector(point):return SimpleNamespace(x=point[0],y=point[1],z=point[2])
        def collide(start,end,trace):
            return (vector((start.x,.35*start.z,start.z)),(0.,1.,-.35)) if start.z==end.z else None
        runtime=SimpleNamespace(_water_depth=lambda *args:0.,_vector=vector,
            _collide_navigation=collide,
            _navigation_direction_surface=lambda *args:dict(status='hit',grade=.35))
        result=self.direction(runtime,(0.,0.,0.),0.,descriptor=object(),corridor_half_width=2.)
        self.assertTrue(result['clear'])
        self.assertAlmostEqual(.35,result['slope'])

    def test_missing_ground_records_exact_query_band(self):
        def vector(point):return SimpleNamespace(x=point[0],y=point[1],z=point[2])
        runtime=SimpleNamespace(_water_depth=lambda *args:0.,_vector=vector,
            _collide_navigation=lambda *args:None,
            _navigation_direction_surface=lambda *args:dict(status='missing'))
        result=self.direction(runtime,(47.,-1.,-266.),0.,descriptor=object(),corridor_half_width=2.)
        self.assertEqual('planning_ground_missing',result['reason'])
        self.assertEqual((47.,3.5,-258.),result['native_trace']['ray_start'])
        self.assertEqual((47.,-6.,-258.),result['native_trace']['ray_end'])


if __name__=='__main__':
    unittest.main()
