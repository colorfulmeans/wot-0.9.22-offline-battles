"""Report 050321: preserve movement ownership and reject unusable aim choices."""
import contextlib
import io
import math
import types
import unittest
from unittest import mock
import test_port_0922_bot_runtime as harness
import test_port_0922_battle_runtime as battle_fixtures
import test_port_0922_contact_support_navigation as support_fixtures


class MechanicalHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.runtime = self.fixture.module.BotRuntime(1)
        self.state = dict(id=7, x=36.352049956, y=-11.056488, z=25.10297947,
            yaw=-2.475119, pitch=0., roll=0., speed=0., fire_seq=5,
            half_length=3.5, collision_shape=(1.5,3.5,-.5,2.), profile={})
        self.target = dict(id=11, kind='bot', alive=True,
                           position=(91.66,-11.2,-22.98))
        self.hold = dict(combat_mode='engage', target_id=11,
            move_position=self.position(), fire_allowed=True, throttle_override=0.)

    def tearDown(self):
        self.fixture.tearDown()

    def position(self):
        return self.state['x'],self.state['y'],self.state['z']

    def lease(self):
        value = dict(start=246.696, origin=self.position(),
                     goal=self.target['position'], fire_seq=5, target_id=11)
        self.state['_rear_motion_lease'] = value
        return value

    def laying(self, order, now):
        return self.runtime._rear_laying_order(self.state, order, {11:self.target}, now)

    def test_reported_zero_travel_engage_does_not_complete_approach(self):
        lease = self.lease()
        self.laying(self.hold,251.742)
        self.assertIs(lease,self.state['_rear_motion_lease'])
        self.assertEqual(246.696,lease['start'])
        self.assertEqual(self.target['position'],lease['goal'])

    def test_hold_approach_alternation_exhausts_absolute_budget_and_resumes_move(self):
        lease = self.lease()
        for t in (247.,249.,251.,253.):
            self.laying(dict(self.hold,combat_mode='advance_contact',
                             move_position=self.target['position']),t)
            self.laying(self.hold,t+.1)
        result = self.laying(self.hold,255.)
        self.assertEqual('advance_contact',result['combat_mode'])
        self.assertEqual(self.target['position'],result['move_position'])
        self.assertNotIn('throttle_override',result)
        self.assertTrue(result['fire_allowed'])
        self.assertTrue(self.state['_rear_motion_blocked'])
        self.assertEqual(246.696,lease['start'])
        retry = lease['retry_until']
        self.assertEqual('engage',self.laying(self.hold,retry)['combat_mode'])
        self.assertNotIn('_rear_motion_lease',self.state)

    def test_real_shot_arrival_travel_and_priority_hold_release(self):
        for cause in ('shot','arrival','travel','parking','base_defense'):
            with self.subTest(cause=cause):
                self.state.update(x=36.352049956,z=25.10297947,fire_seq=5)
                self.lease();order=dict(self.hold)
                if cause=='shot':self.state['fire_seq']=6
                if cause=='arrival':self.state.update(x=91.66,z=-22.98)
                if cause=='travel':self.state['x']+=9.
                if cause=='parking':order['parking_phase']='waiting'
                if cause=='base_defense':order['combat_mode']='base_defense'
                self.laying(order,250.)
                self.assertNotIn('_rear_motion_lease',self.state)

    def test_new_attacker_keeps_budget_but_cannot_resume_previous_enemys_destination(self):
        lease=self.lease()
        new=dict(self.target,id=12,position=(-50.,0.,30.))
        order=dict(self.hold,target_id=12)
        result=self.runtime._rear_laying_order(self.state,order,{12:new},255.)
        self.assertEqual(12,result['target_id'])
        self.assertEqual(new['position'],result['move_position'])
        self.assertEqual(246.696,lease['start'])

    def test_mechanical_relocation_backs_out_of_enemy_contact(self):
        self.state.update(x=0.,y=0.,z=0.,yaw=0.,_gun_angle_refusal=('bot',11))
        peer=dict(self.state,id=11,z=7.,yaw=math.pi)
        self.runtime.states={7:self.state,11:peer}
        self.target['position']=(0.,0.,7.)
        self.hold['move_position']=(0.,0.,0.)
        self.runtime._gun_angle_order(self.state,self.hold,{11:self.target},0.,lambda *a:True)
        result=self.runtime._gun_angle_order(self.state,self.hold,{11:self.target},2.,lambda *a:True)
        self.assertLess(result['move_position'][2],0.)
        self.assertEqual('withdraw',result['combat_mode'])
        checks=self.state['_gun_angle_handoff']['candidate_checks']
        self.assertLess(checks[0]['target_fraction'],1.)
        self.assertEqual(1.,checks[1]['target_fraction'])
        # This precheck neither moves a hull nor changes the contact solver.
        self.assertEqual((0.,0.,0.),self.position())

    def test_real_candidate_pitch_checks_do_not_mutate_refusal_or_fire_state(self):
        descriptor=harness._combat_descriptor()
        self.state.update(x=0.,y=0.,z=0.,yaw=0.,pitch=0.,_gun_angle_refusal=('bot',11))
        origin=(0.,2.5,0.)
        target=dict(self.target,position=(0.,0.,7.))
        self.assertFalse(self.runtime.bot_aim_point_reachable(self.state,target,descriptor,origin,(0.,0.,7.)))
        self.assertTrue(self.runtime.bot_aim_point_reachable(self.state,target,descriptor,origin,(0.,2.5,7.)))
        self.assertEqual(('bot',11),self.state['_gun_angle_refusal'])
        self.assertEqual(5,self.state['fire_seq'])


class CandidateReachabilityTests(unittest.TestCase):
    def scene(self):
        fixture=battle_fixtures.BattleRuntimeContractTests()
        runtime,battle,source,target,descriptor=fixture._bot_lane_scene()
        runtime.bigworld.wg_collideSegment=lambda *a:None
        battle._bot_aim_damage_score=lambda *a:100.
        return runtime,battle,source,target,descriptor

    def test_unreachable_retained_point_yields_to_later_reachable_point_with_budget(self):
        runtime,battle,source,target,descriptor=self.scene()
        checks=[]
        def reachable(s,t,d,origin,point):
            checks.append(point)
            return point[1]>1.8
        battle._bots=types.SimpleNamespace(bot_aim_selection_allowed=lambda *a:True,
                                          bot_aim_point_reachable=reachable)
        for unused in range(12):
            before=len(checks)
            battle._bot_firing_lane(source,target)
            self.assertLessEqual(len(checks)-before,2)
            p=battle._bot_aim_point(source,target)
            if p is not None and p['aim_position'][1]>1.8:break
        else:self.fail('later reachable candidate never selected')
        selected=battle._bot_aim_point(source,target)
        battle._bot_firing_lane(source,target)
        self.assertEqual(selected,battle._bot_aim_point(source,target))
        self.assertTrue(any(c['reachable'] for c in source['_aim_candidate_receipt']['checks']))

    def test_all_unreachable_keeps_exposed_point_for_bounded_relocation(self):
        runtime,battle,source,target,descriptor=self.scene()
        battle._bots=types.SimpleNamespace(bot_aim_selection_allowed=lambda *a:True,
                                          bot_aim_point_reachable=lambda *a:False)
        self.assertTrue(battle._bot_firing_lane(source,target))
        self.assertIsNotNone(battle._bot_aim_point(source,target))
        self.assertTrue(all(not c['reachable'] for c in source['_aim_candidate_receipt']['checks']))

    def test_changed_pose_rechecks_retained_sample_and_keeps_search_cursor(self):
        runtime,battle,source,target,descriptor=self.scene()
        minimum=[0.]
        battle._bots=types.SimpleNamespace(bot_aim_selection_allowed=lambda *a:True,
            bot_aim_point_reachable=lambda s,t,d,o,p:p[1]>=minimum[0])
        self.assertTrue(battle._bot_firing_lane(source,target))
        first=battle._bot_aim_point(source,target)
        minimum[0]=1.8
        target['position']=(1.,0.,100.)
        for unused in range(12):
            battle._bot_firing_lane(source,target)
            selected=battle._bot_aim_point(source,target)
            if selected['aim_position'][1]>=minimum[0]:break
        else:self.fail('unreachable old selection hid later candidates')
        self.assertNotEqual(first['aim_token'],selected['aim_token'])

    def test_wall_still_rejects_reachable_candidates(self):
        runtime,battle,source,target,descriptor=self.scene()
        battle._bots=types.SimpleNamespace(bot_aim_selection_allowed=lambda *a:True,
                                          bot_aim_point_reachable=lambda *a:True)
        runtime.bigworld.wg_collideSegment=lambda *a:(battle_fixtures._Vector(0.,1.,1.),)
        self.assertFalse(battle._bot_firing_lane(source,target))
        self.assertIsNone(battle._bot_aim_point(source,target))
        self.assertEqual('blocked',source['_aim_candidate_receipt']['reason'])
        self.assertTrue(all(c['reason']=='world_blocked' for c in source['_aim_candidate_receipt']['checks']))

    def test_missing_context_replaces_previous_receipt_instead_of_logging_old_success(self):
        runtime,battle,source,target,descriptor=self.scene()
        self.assertTrue(battle._bot_firing_lane(source,target))
        battle._bot_aim_context=lambda *a:None
        self.assertFalse(battle._bot_firing_lane(source,target))
        self.assertEqual('context_unavailable',source['_aim_candidate_receipt']['reason'])
        self.assertEqual([],source['_aim_candidate_receipt']['checks'])


class SupportMotionEvidenceTests(unittest.TestCase):
    def test_projection_and_timed_transition_log_actual_inputs_without_new_casts(self):
        runtime,state=support_fixtures.ContactSupportTests.scene(self,lambda x,z:0.)
        state.update(speed=0.,_edge_support_active=True)
        for step in (0.,.2):
            state['_edge_support_active']=True
            runtime._contact_now=2.+step
            with mock.patch.object(runtime,'_integrate_vertical_motion',return_value=False), contextlib.redirect_stdout(io.StringIO()) as out:
                runtime._update_vertical_motion(state,step,(0.,0.,-.2),0.,(0.,0.,-.1))
            self.assertEqual(step,state['_support_motion_receipt']['step'])
            self.assertEqual((0.,0.,-.2),state['_support_motion_receipt']['tick_pose'])
            self.assertIn('"motion"',out.getvalue())
            self.assertFalse(state.get('_edge_support_active',False))


if __name__=='__main__':unittest.main()
