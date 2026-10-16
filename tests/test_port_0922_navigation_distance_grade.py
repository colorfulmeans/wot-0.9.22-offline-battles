"""Legacy selection and observational slope receipts must not change driving."""
import contextlib
import copy
import io
import math
import unittest
from test_port_0922_navigation import TerrainGrid, StaticHullNavigationTests
import test_port_0922_bot_runtime as bots

class NavigationObservationTests(unittest.TestCase):
    def grid(self):
        grid = TerrainGrid(lambda x,z,h: .1*x, lambda *args: False,
            baked_graph=StaticHullNavigationTests._flat_graph())
        grid._ground = lambda x,z,h: .1*x
        grid.segment_penalty = lambda *args: 0.
        grid.segment_has_baked_hazard = lambda *args: False
        grid.segment_clear = lambda *args: True
        return grid

    def test_receipt_replays_legacy_distance_turn_and_avoidance_order(self):
        for avoid in (None, [(20.,0.,23.)]):
            grid = self.grid(); receipt = {}
            result = grid.safe_local_target((20.,2.,20.), (10.,0.,80.), 1.,
                avoid_points=avoid, diagnostic=receipt)
            rows = [r for r in receipt['candidates'] if r['rejected'] is None]
            expected = min(rows, key=lambda r:(r['D']+r['C'], abs(r['theta'])))
            self.assertEqual(expected['point'], result)
            for row in rows:
                penalty = grid._penalty(grid.cell_for(row['point']), avoid, False)
                self.assertAlmostEqual(abs(row['theta'])*3.5+penalty*2.,row['C'])
            self.assertEqual(result, grid.safe_local_target(
                (20.,2.,20.), (10.,0.,80.), 1., avoid_points=avoid))
            self.assertNotIn('distance_then_grade', receipt)

    def test_recorded_airfield_choice_retains_turn_cost(self):
        grid=self.grid(); grid._ground=lambda *args:0.; grid._penalty=lambda *args:0.
        # Replay two captured eligible endpoints, not an invented flat-world
        # collision result. The full traffic fixture covers end-to-end behavior.
        eligible=((-300.7803088521,0.,-192.5842730889),
                  (-299.3396826721,0.,-192.4088839332))
        grid.segment_clear=lambda start,end:any(math.hypot(end[0]-p[0],end[2]-p[2])<1e-6 for p in eligible)
        receipt={}
        target=grid.safe_local_target((-298.,0.,-194.),
            (-313.0806504495,0.,-134.894427191),.7333333333,diagnostic=receipt)
        self.assertAlmostEqual(-299.3396826721,target[0])
        self.assertAlmostEqual(-192.4088839332,target[2])
        rows=[r for r in receipt['candidates'] if r['rejected'] is None]
        shortest=min(rows,key=lambda r:r['D'])
        self.assertNotEqual(shortest['point'],target)

    def test_bad_ground_is_unknown_not_zero_slope(self):
        grid=self.grid(); grid._ground=lambda *args:None; grid.obstacle_probe=None; receipt={}
        self.assertIsNone(grid.safe_local_target((20.,0.,20.),(20.,0.,80.),1.,
            diagnostic=receipt))
        self.assertTrue(receipt['candidates'])
        self.assertTrue(all(r['rejected']=='missing_ground' for r in receipt['candidates']))

class SurfaceObservationTests(unittest.TestCase):
    setUp = bots.ShovedWreckTests.setUp
    tearDown = bots.ShovedWreckTests.tearDown
    _runtime = bots.ShovedWreckTests._runtime
    _wreck = bots.ShovedWreckTests._wreck

    def test_reverse_direction_budget_and_unchanged_authority(self):
        runtime=self._runtime(); state=self._wreck(runtime)
        state.update(yaw=0., _navigation_target_receipt=dict(final_target=(0.,0.,10.)))
        before=copy.deepcopy(state); calls=[]
        runtime._navigation_surface_probe=lambda point,yaw:calls.append((point,yaw)) or dict(status='missing')
        runtime._queue_navigation_surface_trace(state, dict(controls=dict(motion=(-1.,0.))), 0.)
        with contextlib.redirect_stdout(io.StringIO()):
            runtime._drain_navigation_surface_trace(0.)
            runtime._drain_navigation_surface_trace(.01)
        self.assertEqual(1,len(calls))
        self.assertLess(calls[0][0][2],state['z'])
        self.assertAlmostEqual(math.pi,calls[0][1])
        self.assertEqual(before,state)
        with contextlib.redirect_stdout(io.StringIO()):runtime._drain_navigation_surface_trace(.11)
        self.assertEqual(2,len(calls))
        self.assertGreater(calls[1][0][2],state['z'])

    def test_probe_failure_cannot_change_driving_state(self):
        runtime=self._runtime();state=self._wreck(runtime);before=copy.deepcopy(state)
        def failed(*args):raise ValueError('native surface unavailable')
        runtime._navigation_surface_probe=failed
        runtime._queue_navigation_surface_trace(state,{},0.)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runtime._drain_navigation_surface_trace(0.)
        self.assertIn('ValueError',output.getvalue())
        self.assertEqual(before,state)

    def test_new_round_discards_queued_old_positions(self):
        runtime=self._runtime(); state=self._wreck(runtime)
        runtime._navigation_surface_probe=lambda *args:dict(status='missing')
        runtime._queue_navigation_surface_trace(state,{},1.)
        self.assertTrue(runtime._navigation_surface_queue)
        message=dict(self.start);message['round_id']=runtime.round_id+1
        runtime.battle_start(message)
        self.assertEqual([],runtime._navigation_surface_queue)

class RawSurfaceContractTests(unittest.TestCase):
    def test_signed_normal_is_directional_and_missing_stays_unknown(self):
        import ast
        from pathlib import Path
        from types import SimpleNamespace
        source=(Path(__file__).resolve().parents[1]/'src/res/scripts/client/gui/mods/offline_lan_0922/battle_runtime.py').read_text(encoding='utf-8')
        cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='BattleRuntime')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_navigation_surface_observation')
        namespace=dict(math=math,VEHICLE_SKIP_FLAGS=128)
        exec(compile(ast.Module(body=[method],type_ignores=[]),'surface_probe','exec'),namespace)
        calls=[];hits=[((0.,0.,4.),(0.,1.,-.5)),None]
        def collide(*args):calls.append(args);return hits.pop(0)
        runtime=SimpleNamespace(_avatar=SimpleNamespace(spaceID=7),_vector=lambda p:p,
            _runtime=SimpleNamespace(bigworld=SimpleNamespace(wg_collideSegment=collide)))
        first=namespace['_navigation_surface_observation'](runtime,(0.,0.,4.),0.)
        self.assertAlmostEqual(math.degrees(math.atan(.5)),first['directional_angle_degrees'])
        self.assertEqual((7,(0.,8.,4.),(0.,-30.,4.),128),calls[0])
        missing=namespace['_navigation_surface_observation'](runtime,(0.,0.,4.),math.pi)
        self.assertEqual('missing',missing['status'])
        self.assertNotIn('directional_angle_degrees',missing)

if __name__=='__main__':unittest.main()
