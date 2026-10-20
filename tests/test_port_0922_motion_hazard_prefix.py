"""Physical hazard prefixes and complete handoff evidence from report 214449."""
import json
import contextlib
import io
import runpy
import math
from pathlib import Path
import unittest
from unittest import mock
import test_port_0922_bot_runtime as harness
import test_port_0922_navigation_wait_lifecycle as waits

ROOT = Path(__file__).resolve().parents[1]

class PhysicalHazardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        self.grid_type = TerrainGrid

    def grid(self, name='84_winter'):
        from gui.mods.offline_lan_0922 import prebaked_navigation as pn
        return self.grid_type(lambda *a: None, baked_graph=pn.with_shore_hazards(
            json.loads((ROOT/'navgraphs'/(name+'.json')).read_bytes())))

    def test_recorded_long_precheck_cannot_skip_short_prefix_hazard(self):
        grid=self.grid();start=(155.24067643099974,-13.843542098999023,-12.604771772707448)
        yaw=math.atan2(.3171880441496,.948362665149)
        for distance, blocked in ((.05,False),(.5,False),(1.62,True),(3.90755295753479,True),(4.,True)):
            end=(start[0]+math.sin(yaw)*distance,start[1],start[2]+math.cos(yaw)*distance)
            receipt={}
            self.assertEqual(blocked,grid.segment_has_motion_hazard(start,end,13,receipt),(distance,receipt))
            if blocked:self.assertEqual((163,122),receipt['rejected_cell'])
        self.assertEqual(10,grid._baked_hazards[grid._baked_flat_index((163,122))])

    def test_base_crossings_agree_with_dense_physical_samples_in_all_octants(self):
        grid=self.grid()
        for yaw in (n*.17 for n in range(-18,19)):
            start=(155.24,0.,-12.60)
            end=(start[0]+math.sin(yaw)*9.7,0.,start[2]+math.cos(yaw)*9.7)
            cells=grid._motion_segment_cells(start,end)
            dense={grid.cell_for((start[0]+(end[0]-start[0])*i/4000.,0.,start[2]+(end[2]-start[2])*i/4000.)) for i in range(4001)}
            self.assertEqual(dense,set(cells))
            self.assertEqual(set(cells),set(grid._motion_segment_cells(end,start)))
            for fraction in (.1,.4,.7):
                mid=tuple(start[i]+(end[i]-start[i])*fraction for i in range(3))
                self.assertTrue(set(grid._motion_segment_cells(start,mid)).issubset(set(cells)))

    def test_mixed_local_patch_boundaries_do_not_skip_entered_cells(self):
        grid=self.grid();patch=grid._local_meshes.patches[0]
        ox,oz=patch['origin'];a=(ox-2.,0.,oz+2.31);b=(ox+13.7,0.,oz+5.92)
        expected=[]
        for i in range(10001):
            p=tuple(a[j]+(b[j]-a[j])*i/10000. for j in range(3))
            c=grid._local_meshes.cell(p) or grid.cell_for(p)
            if not expected or c!=expected[-1]:expected.append(c)
        self.assertEqual(tuple(expected),grid._motion_segment_cells(a,b))
        self.assertEqual(set(expected),set(grid._motion_segment_cells(b,a)))

    def test_start_hazard_can_be_left_but_unknown_destination_cannot_be_entered(self):
        graph=self.fixture._ford_graph(size=9)
        graph['hazards']=[0]*len(graph['hazards']);graph['heights_mm']=list(graph['heights_mm'])
        graph['hazards'][1*graph['width']+1]=13
        grid=self.grid_type(lambda *a:None,baked_graph=graph)
        self.assertFalse(grid.segment_has_motion_hazard((4.,0.,4.),(8.,0.,4.),13))
        receipt={}
        self.assertTrue(grid.segment_has_motion_hazard((4.,0.,4.),(1000.,0.,4.),13,receipt))
        self.assertEqual('unknown_cell',receipt['reason'])
        self.assertTrue(grid.segment_has_motion_hazard((-100.,0.,4.),(4.,0.,4.),13))

    def test_mask_height_erosion_and_exact_geometry_cache_are_independent(self):
        graph=self.fixture._ford_graph(size=9)
        graph['hazards']=[0]*len(graph['hazards']);graph['heights_mm']=list(graph['heights_mm'])
        i=1*graph['width']+2;graph['heights_mm'][i]=None;graph['hazards'][i]=1
        grid=self.grid_type(lambda *a:None,baked_graph=graph)
        self.assertTrue(grid.segment_has_motion_hazard((4.,0.,4.),(8.,0.,4.),1))
        self.assertFalse(grid.segment_has_motion_hazard((4.,0.,4.),(8.,0.,4.),12))
        for i in range(550):grid._motion_segment_cells((4.+i*.0001,0.,4.),(8.,0.,4.))
        self.assertLessEqual(len(grid._motion_crossings),512)

    def test_routing_vertex_links_and_native_wall_checks_are_not_replaced(self):
        grid=self.grid();a=(155.24067643099974,0.,-12.604771772707448);b=(156.4801055,0.,-8.8989944)
        self.assertEqual(((163,121),(164,122)),grid._baked_segment_cells(a,b,False))
        runtime=self.fixture._ford_runtime(self.fixture._ford_graph(size=9))
        receipt={}
        runtime._planner_corridor_clear((4.,0.,4.),0.,0.,hazard_only=True,evidence=receipt)
        self.assertEqual('physical_boundaries',receipt['traversal'])

class HandoffEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = waits.NavigationWaitLifecycleTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_reached_unsafe_timeout_and_runtime_intent_record_actual_terminal_cause(self):
        for cause in ('reached','unsafe','timeout','runtime_intent_handoff'):
            nav,current,goal,target,request=self.fixture.issued_exit()
            state=nav.bot_states[11]
            if cause=='reached':nav._retained_local_fallback(11,target,goal,1.,state)
            elif cause=='unsafe':
                with mock.patch.object(nav.grid,'dry_segment_clear',return_value=False):
                    nav._retained_local_fallback(11,current,goal,1.,state)
            elif cause=='timeout':nav._retained_local_fallback(11,current,goal,99.,state)
            else:nav.retained_local_target(11,current,goal,request,1.,False)
            event=state['local_target_events'][-1]
            self.assertEqual(cause,event['reason']);self.assertEqual(target,event['target'])
            self.assertIn('request',event);self.assertIn('progress_at',event)
            trace=nav.bot_search_diagnostics(11,current,100.)
            self.assertEqual(event,trace['local_target_events'][-1])

    def test_immediate_handoff_and_solver_events_roundtrip_without_sampling_loss(self):
        reader=runpy.run_path(str(ROOT/'tools/read_native_evidence.py'))['parse_lines']
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            nav,current,goal,target,request=self.fixture.issued_exit()
            nav._retained_local_fallback(11,target,goal,1.,nav.bot_states[11])
            runtime=self.fixture.module.BotRuntime(1)
            state=dict(id=11,x=0.,y=0.,z=0.,yaw=0.,pitch=0.,roll=0.,profile={})
            runtime._local_ballistic_solution(state,None,None,0)
        parsed=reader(output.getvalue().splitlines())
        self.assertEqual([],parsed['issues'])
        handoff=[r['data'] for r in parsed['records'] if r['label']=='BOT LOCAL HANDOFF']
        self.assertEqual('reached',handoff[-1]['reason']);self.assertEqual(11,handoff[-1]['bot'])
        self.assertEqual('target_missing',[r['data'] for r in parsed['records'] if r['label']=='BOT GUN SOLUTION'][-1]['reason'])

    def test_passed_changed_owner_and_penalty_keep_distinct_causes(self):
        for cause in ('passed','last_target_changed','penalized','intent_changed'):
            nav,current,goal,target,request=self.fixture.issued_exit();state=nav.bot_states[11]
            if cause=='passed':current=(target[0]*2.,0.,target[2]*2.)
            if cause=='last_target_changed':state['last_target']=(12.,0.,12.)
            if cause=='intent_changed':state['local_fallback_intent']=('different',)
            with mock.patch.object(nav,'_bot_edges_penalized',return_value=cause=='penalized'):
                nav._retained_local_fallback(11,current,goal,1.,state)
            self.assertEqual(cause,state['local_target_events'][-1]['reason'])

    def test_request_hold_and_rejected_connector_publish_before_deletion(self):
        for cause in ('request_changed','movement_hold','connector_rejected'):
            nav,current,goal,target,request=self.fixture.issued_exit();state=nav.bot_states[11]
            if cause=='request_changed':nav.next_target(11,current,(20.,0.,-30.),('local',11,'other'),1.)
            elif cause=='movement_hold':nav.next_target(11,current,goal,request,1.,movement_intent=False)
            else:
                with mock.patch.object(nav.grid,'safe_local_target',return_value=(9.,0.,12.)), mock.patch.object(nav.grid,'dry_segment_clear',return_value=False):
                    nav._new_local_fallback(11,current,(1.,0.,0.),goal,1.,(),state)
            matches=[e for e in state['local_target_events'] if e['reason']==cause]
            self.assertEqual(1,len(matches));self.assertEqual(target,matches[0]['target'])

    def test_same_leg_does_not_renew_or_duplicate_transition_history(self):
        nav,current,goal,target,request=self.fixture.issued_exit();state=nav.bot_states[11]
        original=state['local_target_progress_at'];count=len(state['local_target_events'])
        nav._remember_local_fallback(target,goal,state,current,2.)
        self.assertEqual(original,state['local_target_progress_at'])
        self.assertEqual(count,len(state['local_target_events']))

    def test_unavailable_invalid_unsolved_and_range_results_have_distinct_terminal_evidence(self):
        runtime=self.fixture.module.BotRuntime(1)
        state=dict(id=11,x=0.,y=0.,z=0.,yaw=0.,pitch=0.,roll=0.,profile={})
        target=dict(id=28,kind='bot',alive=True,position=(0.,0.,150.))
        descriptor=harness._combat_descriptor()
        runtime._local_ballistic_solution(state,target,None,0)
        self.assertEqual('ballistics_missing',state['_gun_solution_receipt']['reason'])
        runtime.direct_aim_point_probe=lambda *a: {'aim_position':None}
        runtime._local_ballistic_solution(state,target,descriptor,0)
        self.assertEqual('aim_selection_invalid',state['_gun_solution_receipt']['reason'])
        runtime.direct_aim_point_probe=None
        with mock.patch.object(self.fixture.module.ballistics,'ballistic_intercept',return_value=None):
            runtime._local_ballistic_solution(state,target,descriptor,0)
        self.assertEqual('no_intercept',state['_gun_solution_receipt']['reason'])
        with mock.patch.object(self.fixture.module.ballistics,'ballistic_intercept',return_value=((0.,0.,150.),0.,1000.)):
            runtime._local_ballistic_solution(state,target,descriptor,0)
        self.assertEqual('out_of_range',state['_gun_solution_receipt']['reason'])

    def test_every_solver_early_return_explains_refusal_clearing_and_preserves_behavior(self):
        module=self.fixture.module;runtime=module.BotRuntime(1)
        target=dict(id=28,kind='bot',alive=True,position=(0.,0.,150.))
        state=dict(id=11,x=0.,y=0.,z=0.,yaw=0.,pitch=.45,roll=0.,profile={})
        descriptor=harness._combat_descriptor()
        runtime._local_ballistic_solution(state,target,descriptor,0)
        self.assertEqual('mechanical_refusal',state['_gun_solution_receipt']['reason'])
        with mock.patch.object(runtime,'_exact_shot_origin',return_value=None):
            runtime._local_ballistic_solution(state,target,descriptor,0)
        receipt=state['_gun_solution_receipt']
        self.assertEqual('muzzle_missing',receipt['reason']);self.assertEqual(('bot',28),receipt['previous_refusal'])
        self.assertNotIn('_gun_angle_refusal',state)
        runtime.direct_aim_point_probe=lambda *a:None
        runtime._local_ballistic_solution(state,target,descriptor,0)
        self.assertEqual('aim_selection_unavailable',state['_gun_solution_receipt']['reason'])
        runtime.direct_aim_point_probe=None;state['pitch']=0.
        self.assertIsNotNone(runtime._local_ballistic_solution(state,target,descriptor,0))
        self.assertEqual('reachable',state['_gun_solution_receipt']['reason'])
        self.assertEqual(['mechanical_refusal','muzzle_missing','aim_selection_unavailable','reachable'],
                         [r['last']['reason'] for r in state['_gun_solution_history']])

if __name__=='__main__':unittest.main()
