"""Three recorded rounds: bypass admission, contact laying and proof evidence."""
import contextlib
import io
import math
import types
import unittest
from unittest import mock
import test_port_0922_bot_runtime as harness


class RecordedHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.runtime = self.fixture.module.BotRuntime(1)

    def occupied_emil(self, cache_until=0.):
        runtime=self.runtime
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        grid=TerrainGrid(lambda *args:0.,baked_graph=harness._flat_open_graph())
        # Preserve recorded XZ; height availability/native clearance are supplied
        # separately, rather than claiming this fixture replays native terrain.
        grid._baked_index=lambda cell:0
        grid._baked_cell_height=lambda cell:0.
        grid.point_has_baked_hazard=mock.Mock(return_value=False)
        grid.dry_segment_clear=mock.Mock(return_value=True)
        runtime.navigator=types.SimpleNamespace(grid=grid,bot_states={12:{'replan_generation':1}})
        goal=(26.,-.183,126.)
        target=(35.902488708496094,-.2777712345123291,132.7779541015625)
        key=(grid.cell_for(goal),True)
        runtime.states[12]=dict(id=12,half_length=3.3402910232543945,
            half_width=1.5805059671401978,
            _occupied_route_leg=(key,target,dict(epoch=(0,1),phase='active',
                goal=goal,origin=(33.61885715383492,-.04217660427093506,131.2148822954759))),
            _occupied_route_targets={key:(cache_until,target,True)})
        runtime._physical_parking_occupancy=mock.Mock(return_value=[
            (None,(29.81,0.,119.44),math.hypot(3.17,1.64))])
        return runtime,grid,goal,target

    def test_recorded_completed_bypass_returns_original_corner_even_before_cache_expiry(self):
        arrived=(34.88200447005671,-.12273275852203369,131.94391922028694)
        for until in (0.,400.):
            with self.subTest(cache_until=until):
                runtime,grid,goal,target=self.occupied_emil(until)
                self.assertIsNone(runtime._occupied_route_target(12,arrived,goal,325.367,True))
                self.assertEqual('completed_handoff',runtime.states[12]['_occupied_route_bypass_observations'][-1]['reason'])
                for now in (325.6,326.,330.):
                    self.assertIsNone(runtime._occupied_route_target(12,arrived,goal,now,True))

    def test_completed_bypass_renews_only_on_existing_replan_not_global_geometry(self):
        arrived=(34.88200447005671,-.12273275852203369,131.94391922028694)
        for changed in ('retry','geometry'):
            with self.subTest(changed=changed):
                runtime,grid,goal,target=self.occupied_emil()
                self.assertIsNone(runtime._occupied_route_target(12,arrived,goal,325.,True))
                if changed=='retry':runtime.navigator.bot_states[12]['replan_generation']=2
                else:grid.static_hull_revision+=1
                result=runtime._occupied_route_target(12,arrived,goal,326.,True)
                if changed=='retry':
                    self.assertIsNotNone(result)
                else:
                    self.assertIsNone(result)
                    self.assertEqual('completed_handoff',runtime.states[12]['_occupied_route_bypass_observations'][-1]['reason'])
                    self.assertEqual('geometry_revalidation',runtime.states[12]['_occupied_route_bypass_observations'][-1]['epoch_action'])

    def test_unfinished_bypass_remains_fixed_and_completed_handoff_does_not_claim_clearance(self):
        runtime,grid,goal,target=self.occupied_emil(400.)
        before=(33.61885715383492,-.04217660427093506,131.2148822954759)
        self.assertEqual(target,runtime._occupied_route_target(12,before,goal,320.,True))
        runtime._physical_parking_occupancy.assert_not_called()
        self.assertEqual('cached',runtime.states[12]['_occupied_route_bypass_observations'][-1]['source'])
        arrived=(34.88200447005671,-.12273275852203369,131.94391922028694)
        self.assertIsNone(runtime._occupied_route_target(12,arrived,goal,325.,True))
        self.assertTrue(runtime.states[12]['route_wreck_blocked'])
        grid.dry_segment_clear.return_value=False
        runtime.navigator.bot_states[12]['replan_generation']=2
        self.assertIsNone(runtime._occupied_route_target(12,arrived,goal,326.,True))

    def test_completed_bypass_releases_when_blocker_clears(self):
        runtime,grid,goal,target=self.occupied_emil()
        arrived=(34.88200447005671,-.12273275852203369,131.94391922028694)
        runtime._occupied_route_target(12,arrived,goal,325.,True)
        runtime._physical_parking_occupancy.return_value=[]
        self.assertIsNone(runtime._occupied_route_target(12,arrived,goal,327.,True))
        self.assertNotIn('_occupied_route_leg',runtime.states[12])
        self.assertFalse(runtime.states[12]['_occupied_route_bypass_observations'][-1]['blocked'])

    def test_runtime_completed_bypass_hands_back_to_original_navigation_corner(self):
        runtime,grid,corner,target=self.occupied_emil(400.)
        own=runtime.states[12];own['team']=1
        position=(34.88200447005671,-.12273275852203369,131.94391922028694)
        macro=(10.007,0.,114.068)
        runtime.navigator.next_target=mock.Mock(return_value=corner)
        runtime.navigator.retained_local_target=mock.Mock(return_value=None)
        runtime.navigator.target_is_terminal=mock.Mock(return_value=False)
        runtime.navigator.remember_runtime_target=mock.Mock()
        runtime._navigation_height_columns=None
        runtime._route_lane_target=lambda bot,pos,goal,selected,*args:selected
        grid.dry_segment_clear.return_value=False
        result=runtime._navigation_target_impl(12,position,macro,
            dict(combat_mode='route',route_id='class_td_ice_road',route_index=3),
            dict(now=325.367,speed=0.,yaw=2.97))
        self.assertEqual(corner,result)
        self.assertNotEqual(macro,result)
        runtime.navigator.next_target.assert_called_once()
        runtime.navigator.remember_runtime_target.assert_not_called()
        receipt=own['_navigation_target_receipt']
        self.assertEqual('same_horizontal_endpoint',receipt['runtime_leg_handoff']['reason'])
        self.assertEqual('completed_handoff',receipt['occupied_bypass'][-1]['reason'])
        self.assertTrue(own['route_wreck_blocked'])
        self.assertFalse(receipt['occupied_bypass'][-1]['native_clearance_claimed'])

    def test_amx_bypass_handoff_distinguishes_arrival_from_replan(self):
        corner = (54., .267, 102.)
        bypass = (46.335449569, .323, 104.292305977)
        reached = (45.6, .3, 104.9)
        short_of_arrival = (bypass[0]-1.51, bypass[1], bypass[2])
        after_handoff = (50.251281614, .298, 102.852890882)
        for hold, replan, expect_bypass in (
                (reached, False, False), (short_of_arrival, False, True),
                (reached, True, True)):
            with self.subTest(hold=hold, replan=replan):
                runtime, grid, _, _ = self.occupied_emil()
                key = (grid.cell_for(corner), True)
                own = runtime.states[12]
                own.update(team=2, half_length=3.5196011066, half_width=1.6997820139,
                    _occupied_route_leg=(key, bypass, dict(epoch=(0, 1), phase='active')),
                    _occupied_route_targets={key: (4123., bypass, True)})
                runtime._physical_parking_occupancy.return_value = [
                    (None, (59.306400299, .209700003, 107.579597473), 4.531514173)]
                runtime.navigator.observe_direct_target = mock.Mock(return_value=None)
                runtime.navigator.next_target = mock.Mock(return_value=corner)
                runtime.navigator.remember_runtime_target = mock.Mock()
                runtime._navigation_height_columns = None
                runtime._route_lane_target = lambda bot, pos, goal, selected, *args: selected
                runtime._navigation_target_impl(12, hold, hold,
                    dict(combat_mode='engage', throttle_override=0.),
                    dict(now=4119.962, speed=0., yaw=1.))
                grid.static_hull_revision += 1
                if replan:
                    runtime.navigator.bot_states[12]['replan_generation'] += 1

                result = runtime._navigation_target_impl(
                    12, after_handoff, (108.2138, 0., 122.5995),
                    dict(combat_mode='route', route_id='class_td_rim_east', route_index=2),
                    dict(now=4122.763, speed=0., yaw=1.))
                receipt = own['_navigation_target_receipt']['occupied_bypass'][-1]
                if expect_bypass:
                    self.assertNotEqual(corner, result)
                    self.assertEqual('bypass_issued', receipt['reason'])
                    if not replan:
                        self.assertEqual(bypass, result)
                else:
                    self.assertEqual(corner, result)
                    runtime.navigator.remember_runtime_target.assert_not_called()
                    self.assertEqual('completed_handoff', receipt['reason'])
                    self.assertEqual(4119.962, receipt['completed_at'])
                self.assertFalse(receipt['native_clearance_claimed'])

    def test_reported_cached_bypass_cannot_readmit_retired_target(self):
        runtime = self.runtime
        p=(180.1784,-9.4646,-261.9659)
        a=(185.625,-8.735,-255.3274)
        b=(178.2376,-10.1644,-259.523)
        grid=types.SimpleNamespace(prebaked=True,cell_for=lambda p:(int(p[0]),int(p[2])),
            _baked_index=lambda cell:None)
        runtime.navigator=types.SimpleNamespace(grid=grid,bot_segment_penalized=lambda *args:True)
        state={'id':10,'_occupied_route_targets':{(grid.cell_for(b),True):(400.,a,True)},
               '_occupied_route_leg':((grid.cell_for(b),True),a)}
        runtime.states[10]=state
        self.assertIsNone(runtime._occupied_route_target(10,p,b,317.936,True))
        self.assertEqual('active_private_refusal',state['_occupied_route_refusal']['reason'])
        self.assertNotIn('_occupied_route_leg',state)

    def test_runtime_admission_preserves_retry_clock_and_cooldown_expiry(self):
        from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator
        nav=TerrainNavigator.__new__(TerrainNavigator)
        nav.grid=types.SimpleNamespace(cell_size=4.)
        state={'request_key':('recorded',),'local_replan_generation':24,
               'local_target_progress_at':300.}
        nav.bot_states={10:state}
        nav._bot_edges_penalized=lambda bot,current,target,now:now<320.
        with contextlib.redirect_stdout(io.StringIO()):
            for now in(317.,317.2,317.4):
                self.assertFalse(nav.remember_runtime_target(10,(0.,0.,0.),(0.,0.,50.),(4.,0.,5.),now))
                self.assertEqual(300.,state['local_target_progress_at'])
                self.assertNotIn('local_fallback_target',state)
            self.assertTrue(nav.remember_runtime_target(10,(0.,0.,0.),(0.,0.,50.),(4.,0.,5.),320.))
        self.assertEqual((4.,0.,5.),state['local_fallback_target'])

    def contact_state(self):
        state=dict(id=19,team=2,x=0.,y=0.,z=0.,yaw=0.,pitch=0.,roll=0.,
            speed=3.217203344,profile={},half_length=3.5,
            collision_shape=(1.5,3.5,-.5,2.),_gun_angle_refusal=('human',1))
        state['_translation_motion_receipt']=dict(outcome='velocity_owned_by_remote_player',
            fraction=0.,step=.141,start=(0.,0.,0.),accepted=(0.,0.))
        return state

    def test_remote_impulse_is_preserved_but_not_counted_as_approach(self):
        state=self.contact_state()
        speed,basis=self.runtime._mechanical_approach_speed(state)
        self.assertEqual(0.,speed)
        self.assertEqual('realised_player_contact',basis)
        self.assertEqual(3.217203344,state['speed'])
        state['z']=.4
        self.assertGreater(self.runtime._mechanical_approach_speed(state)[0],1.)

    def test_player_contact_relocation_survives_approach_hold_alternation(self):
        # The old independent gun-angle destination is gone. A current
        # physical point task retains its checked goal through policy waits,
        # while genuine priority travel returns its original route.
        from test_player_recovery_continuity import SelectedPointRecoveryContinuityTests
        scene=SelectedPointRecoveryContinuityTests().scene()
        first=scene.apply(0.)
        self.assertEqual('gun_angle_adjust',first['combat_mode'])
        phase=scene.owner._physical_recovery
        scene.decide('wait',candidate=False,reason='current_lane_pending')
        self.assertEqual(phase['goal'],scene.apply(2.1)['move_position'])
        self.assertEqual(0.,phase['started'])
        scene.raw_order['combat_mode']='base_defense'
        result=scene.apply(2.2)
        self.assertEqual('base_defense',result['combat_mode'])
        self.assertIsNone(scene.owner._physical_recovery)
        self.assertFalse(hasattr(self.runtime,'_gun_angle_order'))

    def test_unblocked_approach_is_not_taken_over(self):
        from test_player_combat_stop import Scene
        scene=Scene(admitted=False)
        scene.raw_order.update(combat_mode='advance_contact',target_id=None,
            move_position=(0.,0.,6.),throttle_override=None,fire_allowed=False)
        scene.candidate.update(line='clear',mechanical='reachable',armor='unknown')
        scene.decide('wait',candidate=False,reason='native_proof_pending')
        self.assertEqual(scene.raw_order,scene.apply(1.))
        self.assertFalse(scene.owner.stop_allowed)
        self.assertFalse(hasattr(self.runtime,'_gun_angle_order'))

    def test_snapshot_lane_producer_receipt_reaches_authority_for_both_targets(self):
        state=dict(id=19,team=2,x=0.,y=0.,z=0.)
        self.runtime.states[19]=state
        def probe(snapshot,target):
            snapshot['_aim_candidate_receipt']=dict(reason='selected',target_kind=target['kind'],
                target_id=target['network_id'],checks=[dict(reachable=True)])
            return True
        self.runtime.firing_lane_probe=probe
        for kind,identity in(('human',1),('bot',5)):
            target=dict(kind=kind,network_id=identity,id=1000001 if kind=='human'else identity,
                        position=(0.,0.,6.))
            snapshot=dict(state)
            self.assertTrue(self.runtime._shot_clear(snapshot,target,10.,force=True))
            receipt=state['_aim_candidate_receipt']
            self.assertEqual(kind,receipt['target_kind'])
            self.assertEqual(identity,receipt['target_id'])
            self.assertTrue(receipt['checks'][0]['reachable'])

    def test_contact_owner_releases_previous_traffic_wait(self):
        from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
        adapter=BotAdapter('04_himmelsdorf',1)
        bot=7
        state=dict(id=bot,slot=1,team=1,x=0.,y=0.,z=0.,yaw=0.,speed=0.,dt=.2)
        driver_state=adapter.driver._state(bot,1,(0.,0.,0.))
        driver_state['traffic_waiting']=True
        order=dict(combat_mode='route',move_position=(0.,0.,20.))
        plan=((0.,0.,8.),dict(throttle=1.,turn=.7,target_yaw=0.,recovery_mode='wreck_push'))
        with mock.patch.object(adapter,'_hull_contact',return_value=None), \
             mock.patch.object(adapter,'_retained_contact_escape',return_value=None), \
             mock.patch.object(adapter,'_wreck_push_plan',return_value=plan):
            result=adapter._drive_order_controls(bot,state,(0.,0.,0.),order,lambda *a:True)
        self.assertEqual('wreck_push',result['recovery_mode'])
        self.assertEqual(1.,result['throttle'])
        self.assertNotIn('traffic_waiting',driver_state)

    def test_early_planner_return_keeps_real_collision_witness(self):
        state=dict(id=7,_rotation_contact_trace=dict(reason='solid_lane',sampled_at=258.53,
            hit=(-83.2652,13.6345,102.1064)),
            _translation_motion_receipt=dict(outcome='unrestricted',fraction=1.))
        with mock.patch.object(self.fixture.module, 'detailed_enabled', return_value=True):
            result=self.runtime._report_blocked_planner((0.,0.,0.),
                dict(move_position=(0.,0.,10.),recovery_mode='drive',movement_intent=True),
                {},state,259.)
        self.assertFalse(result)
        evidence=state['_planner_blocked_handoff']
        self.assertEqual('solid_lane',evidence['realised_rotation']['reason'])
        self.assertEqual(258.53,evidence['realised_rotation']['sampled_at'])
        self.assertEqual('unrestricted',evidence['translation_sweep']['outcome'])

    def test_cached_native_corridor_explains_reuse_without_new_probe(self):
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        grid=TerrainGrid(lambda *a:0.)
        grid.native_query_oracle=types.SimpleNamespace(last_receipt={'reason':'clear'},run=lambda *a:(1,2,0))
        p=(0.,0.,0.);q=(1.,0.,0.)
        self.assertTrue(grid._native_segment_clear(p,q))
        self.assertTrue(grid._native_segment_clear(p,q))
        self.assertEqual('cached',grid._native_review_receipt['reason'])

    def test_unknown_native_proof_retains_specific_oracle_reason(self):
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        grid=TerrainGrid(lambda *a:0.)
        grid.native_query_oracle=types.SimpleNamespace(last_receipt={'reason':'owner_identity_changed'},
            run=lambda *a,**k:(-1,0,0))
        self.assertFalse(grid._native_segment_clear((0.,0.,0.),(1.,0.,0.)))
        self.assertTrue(grid._proof_deferred)
        self.assertEqual('oracle_unknown',grid._native_review_receipt['reason'])
        self.assertEqual('owner_identity_changed',grid._native_review_receipt['oracle']['reason'])


if __name__=='__main__':
    unittest.main()
