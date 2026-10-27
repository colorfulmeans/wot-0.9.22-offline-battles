"""Captured failure boundaries, complete serialized receipts and capture toggles.

Analytic columns reproduce the measured Lowe attitude/ray-origin mismatch;
they are not a replay of the Airfield mesh or proof of native escape.
"""
import io
import json
import math
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

import test_port_0922_battle_runtime as battle_fixture
import test_port_0922_server_bot_ai as server_fixture
from gui.mods.offline_lan_0922 import bot_runtime
sys.path.insert(0, str(server_fixture.PORT_ROOT/'tools'))
from read_native_evidence import parse_lines


class CompleteSlopeReceiptTests(unittest.TestCase):
    def case(self):
        runtime = bot_runtime.BotRuntime(1)
        runtime._contact_now = 374.508
        state = dict(id=18, x=-318.5099886192857, y=-2.5671989917755127,
            z=-65.38970915986832, yaw=-1.6139090703837777,
            pitch=.5340974079017251, terrain_pitch=.5340974079017251,
            roll=-.037529514262987215, half_length=3.6737260818481445,
            half_width=2.015000104904175, grounded_once=True, airborne=False,
            pose_sample=(-316.9262717808137,-65.2714206457327,-.9634293369580506),
            _basic_slope_samples=dict(sampled_at=132.48500061035156))
        runtime._suspension_params[18] = None
        runtime._descriptors[18] = {}
        return runtime, state

    def serialized(self, runtime, state, **kwargs):
        out = io.StringIO()
        state.pop('_basic_slope_pose_log_at_sample', None)
        with redirect_stdout(out):
            changed = runtime._update_slope_pose(state, **kwargs)
        parsed = parse_lines(out.getvalue().splitlines(), 'worker')
        self.assertEqual([], parsed['issues'])
        row = next(r['data'] for r in parsed['records'] if r['label']=='BOT SLOPE POSE')
        self.assertEqual(state['_slope_pose_refresh']['reason'],row['refresh']['reason'])
        self.assertEqual(state['pitch'],row['refresh']['applied_pose']['pitch'])
        return changed, row['refresh']

    def test_long_tilted_hull_samples_uphill_end_above_centre_ray_origin(self):
        runtime,state = self.case()
        yaw=state['yaw']; pitch=state['pitch']; roll=state['roll']
        def plane(x,z):
            dx=x-state['x']; dz=z-state['z']
            local_x=math.cos(yaw)*dx-math.sin(yaw)*dz
            local_z=math.sin(yaw)*dx+math.cos(yaw)*dz
            return state['y']+math.tan(roll)/math.cos(pitch)*local_x-math.tan(pitch)*local_z
        def column(x,z,hint):
            ground=plane(x,z)
            return ground if ground <= hint+2.0 else None
        # The old centre datum misses the uphill rear at the captured stance.
        x=state['x']-math.sin(yaw)*state['half_length']
        z=state['z']-math.cos(yaw)*state['half_length']
        self.assertIsNone(column(x,z,state['y']))
        runtime._physics_ground_probe = column
        changed,receipt = self.serialized(runtime,state)
        self.assertTrue(changed)
        self.assertTrue(receipt['attempted_samples']['complete'])
        self.assertEqual(4,len(receipt['queries']))
        self.assertEqual('measurement_accepted',receipt['reason'])
        self.assertTrue(receipt['marker_advanced'])
        self.assertAlmostEqual(pitch,state['pitch'])
        self.assertAlmostEqual(roll,state['roll'])

    def test_missing_point_keeps_all_results_and_old_measurement_in_serialized_log(self):
        runtime,state = self.case()
        marker=state['pose_sample']; old=state['_basic_slope_samples']
        runtime._physics_ground_probe=mock.Mock(side_effect=[-3.,None,-2.,-2.5])
        changed,receipt=self.serialized(runtime,state)
        self.assertFalse(changed)
        self.assertEqual('measurement_unavailable',receipt['reason'])
        self.assertEqual([-3.,None,-2.,-2.5],[q['height'] for q in receipt['queries']])
        self.assertEqual(["front","rear","right","left"],
                         [p['name'] for p in receipt['attempted_samples']['points']])
        self.assertAlmostEqual(242.02299938964846,receipt['accepted_sample_age'])
        self.assertEqual(list(marker),receipt['final_measured_pose'])
        self.assertIs(old,state['_basic_slope_samples'])

    def test_cached_early_returns_and_rejection_replace_old_failure_receipt(self):
        runtime,state=self.case()
        runtime._physics_ground_probe=mock.Mock(return_value=state['y'])
        self.assertTrue(self.serialized(runtime,state)[0])
        self.assertEqual('measurement_reused',self.serialized(runtime,state)[1]['reason'])
        state['_slope_pose_target']=None
        self.assertEqual('cached_target_missing',self.serialized(runtime,state)[1]['reason'])
        state['airborne']=True
        self.assertEqual('airborne',self.serialized(runtime,state)[1]['reason'])
        state['airborne']=False; state['grounded_once']=False
        self.assertEqual('not_grounded',self.serialized(runtime,state)[1]['reason'])
        runtime._suspension_params[18]={}
        self.assertEqual('detailed_solver_owns_pose',self.serialized(runtime,state)[1]['reason'])
        runtime._suspension_params[18]=None;state['grounded_once']=True
        runtime._turret_motion_probe=mock.Mock(return_value=False)
        marker=state['pose_sample']
        changed,receipt=self.serialized(runtime,state,force_sample=True)
        self.assertFalse(changed)
        self.assertEqual('body_pose_rejected',receipt['reason'])
        self.assertEqual('rejected_detached_turret_sweep',receipt['guard'])
        self.assertFalse(receipt['marker_advanced'])
        self.assertEqual(marker,state['pose_sample'])

    def test_all_native_layer_terminals_survive_actual_runtime_query(self):
        battle=battle_fixture.BattleRuntime(battle_fixture._runtime())
        vector=battle._vector
        def hit(y,ny):return (vector((0.,y,0.)),vector((0.,ny,0.)))
        for replies, terminal in (([None],'ray_miss'),
                ([RuntimeError('native failure')],'query_exception'),
                ([hit(8.,1.),hit(3.,1.)],'accepted'),
                ([hit(8.,0.)]*4,'layer_budget_exhausted'),
                ([hit(-1000.,0.)],'column_floor')):
            with self.subTest(terminal=terminal):
                battle._collide_down=mock.Mock(side_effect=replies)
                runtime,state=self.case()
                runtime._physics_ground_limit_probe=battle._bot_support_column
                receipt={}
                runtime._ground_probe_at(0.,0.,10.,maximum_y=5.,receipt=receipt)
                last=receipt['layers'][-1]
                self.assertEqual(terminal,last.get('terminal',last['outcome']))
                self.assertTrue(all('start' in q and 'end' in q for q in receipt['layers']))
                if terminal=='query_exception':self.assertEqual('RuntimeError',last['error_type'])
                if terminal=='accepted':self.assertEqual(3.,receipt['height'])

    def test_native_miss_and_exception_reach_serialized_four_point_failure(self):
        battle=battle_fixture.BattleRuntime(battle_fixture._runtime())
        v=battle._vector
        battle._collide_down=mock.Mock(side_effect=[
            (v((0.,-3.,0.)),v((0.,1.,0.))), None,
            RuntimeError('native failure'), (v((0.,-2.,0.)),v((0.,1.,0.)))])
        runtime,state=self.case()
        runtime._physics_ground_limit_probe=battle._bot_support_column
        changed,receipt=self.serialized(runtime,state)
        self.assertFalse(changed)
        self.assertEqual('measurement_unavailable',receipt['reason'])
        self.assertEqual(['accepted','ray_miss','query_exception','accepted'],
            [q['layers'][0]['outcome'] for q in receipt['queries']])

    def test_cached_blend_commit_and_raised_probe_have_terminal_serialized_receipts(self):
        runtime,state=self.case()
        state['pose_sample']=(state['x'],state['z'],state['yaw'])
        state['_slope_pose_target']=(.2,.1)
        changed,receipt=self.serialized(runtime,state)
        self.assertTrue(changed)
        self.assertEqual('cached_target_applied',receipt['reason'])
        self.assertFalse(receipt['marker_advanced'])
        runtime._physics_ground_probe=mock.Mock(side_effect=ValueError('bad query'))
        out=io.StringIO();state.pop('_basic_slope_pose_log_at_sample',None)
        with redirect_stdout(out),self.assertRaises(ValueError):
            runtime._update_slope_pose(state,force_sample=True)
        parsed=parse_lines(out.getvalue().splitlines(),'worker')
        self.assertEqual([],parsed['issues'])
        receipt=parsed['records'][0]['data']['refresh']
        self.assertEqual('refresh_exception',receipt['reason'])
        self.assertEqual('query_exception',receipt['queries'][0]['outcome'])
        self.assertEqual('ValueError',receipt['queries'][0]['error_type'])


class CaptureProgressTests(unittest.TestCase):
    def test_route_has_no_screen_gate_and_never_rewinds_passed_terminal(self):
        route=server_fixture._route('class_lt_valley',[
            (float(i)*30.,0.,False) for i in range(10)]+
            [(-187.341,398.242,False),(-340.,386.,False)])
        planner=server_fixture.BotPlanner()
        bot=server_fixture._bot(28,2,0,route,'lightTank')
        bot['state']=server_fixture._state(28,2,-340.147,385.804)
        planner._route_states[28]=dict(route_id='class_lt_valley',index=11)
        for now in range(4):
            result=planner._route(bot,float(now))
            self.assertEqual(11,result[1])
            self.assertEqual(-340.,result[2]['x'])
            receipt=planner._route_states[28]['progress_receipt']
            self.assertEqual(11,receipt['effective_limit'])
        # An approaching vehicle passes every intermediate gate, then continues
        # to the terminal rather than being held at a capture screening point.
        planner._route_states[28]=dict(route_id='class_lt_valley',index=9)
        bot['state'].update(x=270.,z=0.)
        result=planner._route(bot,5.)
        self.assertEqual(10,result[1])
        self.assertEqual(-187.341,result[2]['x'])
        bot['state'].update(x=-187.341,z=398.242)
        result=planner._route(bot,6.)
        self.assertEqual(11,result[1])
        self.assertEqual(-340.,result[2]['x'])

    def test_final_order_carries_progress_without_forcing_new_command_revision(self):
        planner=server_fixture.BotPlanner()
        route=server_fixture._route('lane',[(0.,0.,False),(0.,100.,False),(0.,500.,False)])
        bot=server_fixture._bot(11,1,0,route,'heavyTank')
        states=[server_fixture._state(11,1,0.,100.)]
        payload=planner.build_orders([bot],states,[],1.)
        order=payload['orders'][0]
        trace=order['route_assignment']['progress']
        self.assertEqual(order['move_position'],trace['final_order']['move_position'])
        self.assertEqual(order['route_index'],trace['final_order']['route_index'])
        original=server_fixture._order_signature(order)
        order=json.loads(json.dumps(order))
        order['route_assignment']['progress']['at']=999.
        self.assertEqual(original,server_fixture._order_signature(order))
