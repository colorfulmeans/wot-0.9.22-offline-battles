"""Observe close-corner refusals and physical crossings without changing decisions."""
import json
import unittest
from unittest import mock
from test_port_0922_navigation import TerrainNavigator
from gui.mods.offline_lan_0922.bot_runtime import BotRuntime


class NearGoalEvidenceTests(unittest.TestCase):
    def test_native_pending_zero_steps_is_not_reported_as_zero_python_work(self):
        import types
        from gui.mods.offline_lan_0922.native_navigation import NativeSearch
        nav=TerrainNavigator(lambda *args:0.,lambda *args:False)
        key=(('route',3),(0,0))
        nav.searches[key]=NativeSearch(7,0,1.)
        nav.search_times[key]=1.
        nav.bot_states[3]=dict(request_key=key)
        nav._native_navigation=types.SimpleNamespace(
            stats=(1,2),queries={7:[(42,(0.,0.,0.),(4.,0.,0.))]})
        result=nav.bot_search_diagnostics(3,(0.,0.,0.),3.)
        row=result['searches'][0]
        self.assertEqual('native',row['backend'])
        self.assertEqual('completion_only',row['progress_accounting'])
        self.assertEqual(1,row['waiting_query_count'])
        self.assertEqual(42,row['waiting_queries'][0][0])
        self.assertEqual(7,row['native_job_id'])
        self.assertEqual((1,2),result['search_scheduler']['native_stats'])
        json.dumps(result)

    def test_corridor_receipt_distinguishes_baked_rejection_and_native_deferral(self):
        nav=TerrainNavigator(lambda *args:0.,lambda *args:False)
        grid=nav.grid
        grid.prebaked=True
        grid.local_height_links=None
        with mock.patch.object(grid,'_routing_height',return_value=0.), \
             mock.patch.object(grid,'_baked_corridor',return_value=(False,0)), \
             mock.patch.object(grid,'_supported_slope_corridor',return_value=False), \
             mock.patch.object(grid,'_baked_cell_height',return_value=0.), \
             mock.patch.object(grid,'_inside',return_value=True):
            evidence={}
            self.assertFalse(grid.segment_clear((0.,0.,0.),(3.,0.,0.),None,evidence))
            self.assertEqual('baked_corridor',evidence['reason'])
            self.assertFalse(evidence['proof_deferred'])
        with mock.patch.object(grid,'_routing_height',return_value=0.), \
             mock.patch.object(grid,'_baked_corridor',return_value=(True,0)), \
             mock.patch.object(grid,'_needs_native_review',return_value=True), \
             mock.patch.object(grid,'_inside',return_value=True), \
             mock.patch.object(grid,'_native_segment_clear',return_value=False) as probe:
            evidence={}
            grid._proof_deferred=True
            self.assertFalse(grid.segment_clear((0.,0.,0.),(3.,0.,0.),None,evidence))
            self.assertEqual('native_review',evidence['reason'])
            self.assertTrue(evidence['proof_deferred'])
            self.assertEqual(1,probe.call_count)

    def test_physics_observation_remembers_crossing_between_control_samples(self):
        state=dict(x=0.,y=0.,z=2.,yaw=0.,speed=4.)
        BotRuntime._observe_near_goal_motion(state,(0.,0.,-2.),(0.,0.,0.),1.)
        row=state['_near_goal_motion']
        self.assertEqual(2.,row['minimum_final_distance'])
        self.assertEqual(0.,row['minimum_segment_distance'])
        self.assertEqual(1.,row['entered_arrival_at'])
        state['z']=3.
        BotRuntime._observe_near_goal_motion(state,(0.,0.,2.),(0.,0.,0.),2.)
        self.assertEqual(1.,row['entered_arrival_at'])
        self.assertEqual(4.,state['speed'])
        BotRuntime._observe_near_goal_motion(state,(0.,0.,3.),(2.,0.,3.),3.)
        row=state['_near_goal_motion']
        self.assertEqual(1.,row['previous_goal']['entered_arrival_at'])
        self.assertNotIn('previous_goal',row['previous_goal'])
        json.dumps(row)
        BotRuntime._observe_near_goal_motion(state,(0.,0.,3.),None,4.)
        self.assertNotIn('_near_goal_motion',state)

    def test_next_edge_refusal_keeps_first_reason_and_original_query_order(self):
        path=[(0.,0.,0.),(0.,0.,10.),(0.,0.,20.)]
        for failure,reason in [('setup','climb_setup_required'),('private','private_edge_penalty'),
                ('penalty','segment_penalty'),('solid','segment_blocked'),(None,'next_dry_edge_clear')]:
            nav=TerrainNavigator(lambda *args:0.,lambda *args:False)
            nav.bot_states[3]={};calls=[]
            with mock.patch.object(nav.grid,'live_shortcut_preserves_climb_approach',
                    side_effect=lambda *args:calls.append('setup') or failure!='setup'), \
                 mock.patch.object(nav,'_bot_edges_penalized',
                    side_effect=lambda *args:calls.append('private') or failure=='private'), \
                 mock.patch.object(nav.grid,'segment_penalty',
                    side_effect=lambda *args:calls.append('penalty') or float(failure=='penalty')), \
                 mock.patch.object(nav.grid,'segment_clear',
                    side_effect=lambda *args:calls.append('solid') or failure!='solid'), \
                 mock.patch.object(nav.grid,'segment_has_baked_hazard',return_value=False):
                clear=nav._planned_next_segment_clear((0.,0.,-2.),path,0,4.,3)
            self.assertEqual(failure is None,clear)
            row=nav.bot_states[3]['corner_selection_receipt']['checks'][0]
            self.assertEqual(reason,row['reason'])
            order=['setup','private','penalty','solid']
            self.assertEqual(order if failure is None else order[:order.index(failure)+1],calls)

    def test_close_sharp_corner_records_lookahead_refusal_without_new_probe(self):
        nav=TerrainNavigator(lambda *args:0.,lambda *args:False)
        nav.bot_states[3]={}
        path=[(178.,1.1,30.),(190.,1.1,30.)]
        with mock.patch.object(nav.grid,'dry_segment_clear',side_effect=AssertionError('extra probe')):
            chosen=nav._lookahead_index((177.82,1.1,28.16),path,0,('route',3),10.,10.,3)
        self.assertEqual(0,chosen)
        row=nav.bot_states[3]['corner_selection_receipt']['checks'][0]
        self.assertEqual('unreached_sharp_corner',row['reason'])
        self.assertGreater(row['corner_distance'],row['driver_arrival_radius'])

    def test_receipt_is_bounded_and_observation_can_be_disabled_without_decision_change(self):
        nav=TerrainNavigator(lambda *args:0.,lambda *args:False)
        path=[(0.,0.,0.),(0.,0.,10.)];nav.bot_states[3]={}
        for unused in range(25):nav._record_corner_check(3,(0.,0.,0.),path,0,1,1.,False,'fixture')
        row=nav.bot_states[3]['corner_selection_receipt']
        self.assertEqual(16,len(row['checks']));self.assertEqual(9,row['dropped'])
        calls=[]
        with mock.patch.object(nav.grid,'segment_clear',side_effect=lambda *a:calls.append(a) or False), \
             mock.patch.object(nav.grid,'segment_penalty',return_value=0.), \
             mock.patch.object(nav,'_bot_edges_penalized',return_value=False):
            a=nav._planned_next_segment_clear(path[0],path,0,2.,3)
            first=list(calls);calls[:]=[]
            with mock.patch.object(nav,'_record_corner_check'):
                b=nav._planned_next_segment_clear(path[0],path,0,2.,3)
        self.assertEqual(a,b);self.assertEqual(first,calls)


if __name__=='__main__':unittest.main()
