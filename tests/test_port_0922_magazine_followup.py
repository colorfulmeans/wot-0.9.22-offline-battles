"""Committed magazine fire keeps aim without renewing idle movement leases."""
import unittest
from unittest import mock
import test_port_0922_bot_runtime as harness


class MagazineFollowupTests(unittest.TestCase):
    def setUp(self):
        self.f = harness.BotRuntimeTests(); self.f.setUp()
        self.rt = self.f.module.BotRuntime(1)
        self.s = dict(id=23, alive=True, health=1000, x=408.25, y=-16.06,
            z=-143.43, yaw=3.02, speed=0., fire_seq=9, clip_size=4, clip=3,
            reload_time=3., profile={'class_tag': 'AT-SPG'},
            ammo_remaining=[20,10,5], shell_index=0)
        self.t = dict(id=7, kind='bot', alive=True, visible=True,
                      position=(405.,3.6,-354.3))
        self.shot = dict(combat_mode='engage', target_id=7, target_kind='bot',
                         throttle=0., fire_allowed=True)
        self.move = dict(self.shot, combat_mode='take_cover',
                         move_position=(416.1,-16.1,-132.3), throttle_override=1.)

    def tearDown(self):
        self.f.tearDown()

    def arm(self, now=10.):
        self.rt._retain_magazine_followup(self.s,self.shot,self.t,now)

    def order(self, now=11., order=None):
        return self.rt._rear_laying_order(self.s,order or self.move,{7:self.t},now)

    def test_actual_runtime_fire_arms_only_committed_nonempty_magazine(self):
        captured=[]
        original=self.f.module.BotRuntime._retain_magazine_followup
        def retain(rt,state,command,target,now):
            original(rt,state,command,target,now)
            captured.append((state['fire_seq'],state['clip'],
                dict(state.get('_magazine_followup') or {})))
        with mock.patch.object(self.f.module.BotRuntime,'_retain_magazine_followup',retain):
            self.f.test_bot_fire_uses_turret_pitch_los_reload_clip_and_barrel_scatter()
        first=next(row for row in captured if row[0]==1)
        second=next(row for row in captured if row[0]==2)
        self.assertEqual(1,first[1])
        self.assertEqual(1,first[2]['fire_seq'])
        self.assertEqual(0,second[1])
        self.assertEqual({},second[2])

    def test_reported_cover_turn_stays_on_same_enemy_after_shot(self):
        self.arm(); result=self.order()
        self.assertEqual('engage',result['combat_mode'])
        self.assertEqual((408.25,-16.06,-143.43),result['move_position'])
        self.assertEqual(self.t['position'],result['face_position'])
        self.assertEqual(7,result['target_id'])
        self.assertTrue(result['fire_allowed'])
        self.assertEqual(0.,result['throttle_override'])
        self.assertEqual('take_cover',self.move['combat_mode'])

    def test_each_real_shot_renews_short_reload_plus_two_not_turns(self):
        self.arm(); deadline=self.s['_magazine_followup']['deadline']
        for now in (11.,12.,14.9):
            self.order(now);self.assertEqual(deadline,self.s['_magazine_followup']['deadline'])
        self.s.update(fire_seq=10,clip=2);self.arm(13.)
        self.assertEqual(18.,self.s['_magazine_followup']['deadline'])
        self.assertEqual('engage',self.order(17.)['combat_mode'])
        self.assertEqual('take_cover',self.order(18.)['combat_mode'])
        self.assertNotIn('_magazine_followup',self.s)
        self.assertEqual('followup_timeout',self.s['_magazine_followup_receipt']['reason'])
        self.assertEqual('take_cover',self.order(19.)['combat_mode'])

    def test_single_shot_moving_and_artillery_do_not_admit(self):
        for change,cmd in (({'clip_size':1},{}),({'speed':2.},{}),({}, {'throttle':1.}),
                ({'profile':{'class_tag':'SPG'}},{}),({'clip':0},{})):
            with self.subTest(change=change,command=cmd):
                s=dict(self.s,**change)
                self.rt._retain_magazine_followup(s,dict(self.shot,**cmd),self.t,10.)
                self.assertNotIn('_magazine_followup',s)

    def test_empty_dead_lost_target_priority_motion_and_mechanical_release(self):
        for cause in ('empty','dead','lost','target_changed','base_defense','parking',
                      'translated','mechanical','actor_dead','blocked','ammo_exhausted'):
            with self.subTest(cause=cause):
                self.s.update(clip=3,x=408.25,health=1000,ammo_remaining=[20,10,5])
                self.s.pop('_gun_angle_refusal',None)
                self.t.update(alive=True,visible=True)
                self.rt._shot_los_cache.clear()
                self.arm();order=dict(self.move)
                if cause=='empty':self.s['clip']=0
                if cause=='ammo_exhausted':self.s['ammo_remaining']=[0,10,5]
                if cause=='dead':self.t['alive']=False
                if cause=='lost':self.t['visible']=False
                if cause=='target_changed':order['target_id']=8
                if cause=='base_defense':order['combat_mode']='base_defense'
                if cause=='parking':order['parking_phase']='approach'
                if cause=='translated':self.s['x']+=2.
                if cause=='mechanical':self.s['_gun_angle_refusal']=('bot',7)
                if cause=='actor_dead':self.s['health']=0
                if cause=='blocked':self.rt._shot_los_cache[self.rt._shot_los_key(self.s,self.t)]=(10.9,False)
                self.rt._magazine_followup_order(self.s,order,{7:self.t},11.)
                self.assertNotIn('_magazine_followup',self.s)
                self.assertFalse(self.s['_magazine_followup_receipt']['active'])

    def test_old_rear_leases_cannot_expire_under_successful_followups(self):
        self.s.update(_rear_aim_episode={'start':0.},_rear_motion_lease={'start':0.},
                      _rear_hull_aim=(('bot',7),1.),_rear_motion_blocked=True)
        self.arm(10.)
        self.assertNotIn('_rear_aim_episode',self.s)
        self.assertNotIn('_rear_motion_lease',self.s)
        self.s.update(fire_seq=10,clip=2);self.arm(14.)
        self.assertEqual('engage',self.order(18.)['combat_mode'])
        self.assertNotIn('_gun_angle_pivot_refusal',self.s)

    def test_existing_stationary_turret_armour_face_is_preserved(self):
        self.s['profile']={'class_tag':'mediumTank'}
        self.arm()
        order=dict(self.move,stable_hull_face=True,face_position=(500.,0.,-350.),
                   hull_angle_degrees=20.)
        result=self.order(order=order)
        self.assertEqual(order['face_position'],result['face_position'])
        self.assertEqual(20.,result['hull_angle_degrees'])

    def test_reload_fire_permission_not_fabricated_and_turret_vehicle_supported(self):
        self.s['profile']={'class_tag':'mediumTank'}
        self.arm();result=self.order(order=dict(self.move,fire_allowed=False))
        self.assertFalse(result['fire_allowed'])
        self.assertEqual(9,self.s['fire_seq'])
        self.assertEqual(3,self.s['clip'])


if __name__=='__main__':
    unittest.main()
