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
        state=self.contact_state()
        target=dict(id=1000001,network_id=1,kind='human',alive=True,position=(0.,0.,6.))
        self.runtime.states[19]=state
        order=dict(combat_mode='engage',target_id=1000001,move_position=(0.,0.,0.),
                   throttle_override=0.,fire_allowed=True)
        self.runtime._gun_angle_order(state,order,{1000001:target},0.,lambda *a:True)
        self.assertEqual(0.,state['_gun_angle_adjustment']['start'])
        order.update(combat_mode='advance_contact',move_position=target['position'])
        order.pop('throttle_override')
        with mock.patch.object(self.runtime,'_gun_angle_target_fraction',side_effect=(0.,1.)):
            result=self.runtime._gun_angle_order(state,order,{1000001:target},2.1,lambda *a:True)
        self.assertLess(result['move_position'][2],0.)
        self.assertEqual(0.,state['_gun_angle_adjustment']['start'])
        self.assertEqual(3.217203344,state['speed'])
        defended=dict(order,combat_mode='base_defense')
        self.assertIs(defended,self.runtime._gun_angle_order(state,defended,{1000001:target},2.2,lambda *a:True))
        self.assertNotIn('_gun_angle_adjustment',state)

    def test_unblocked_approach_is_not_taken_over(self):
        state=self.contact_state()
        state['_translation_motion_receipt']['fraction']=1.
        order=dict(combat_mode='advance_contact',target_id=1000001,move_position=(0.,0.,6.))
        result=self.runtime._gun_angle_order(state,order,{},1.,lambda *a:True)
        self.assertIs(order,result)
        self.assertNotIn('_gun_angle_adjustment',state)

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
