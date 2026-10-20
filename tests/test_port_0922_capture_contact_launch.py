"""Complete capture, contact-laying and queued-launch regressions from 163803.

Controlled collision/arc oracles prove ownership, not native map acceptance.
"""
import math
import unittest
from unittest import mock
import test_port_0922_bot_runtime as runtime_fixture
import test_port_0922_server_bot_ai as server_fixture
from gui.mods.offline_lan_0922.ai import driver
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922 import tank_collision


class CaptureReloadTests(unittest.TestCase):
    def test_canonical_membership_holds_empty_magazine_then_releases(self):
        h = server_fixture
        planner = h.BotPlanner()
        route = h._route('capture', [(0, 0, False), (0, 450, False)])
        manifest = [h._bot(3, 1, 0, route, 'heavyTank')]
        state = h._weapon_state(h._state(3, 1, 0, 440), clip=0,
            clip_size=4, reload_time=27., fire_seq=18)
        players = [dict(id=7, team=2, alive=True)]
        contact = h._contact(7, 0, 460, [3])
        defense = dict(bases={'1':[dict(id='1:0', x=0.,y=0.,z=0.)],
                              '2':[dict(id='2:0', x=0.,y=0.,z=450.)]},
            states={'1':dict(points=30, time_left=60., invaders=1, stopped=False)},
            contributors={'1':[dict(kind='human',id=7)],
                          '2':[dict(kind='bot',id=3,points=0)]})
        for now in (1., 4., 10., 25.):
            planner.report_contacts([contact], planner.known_targets([state], players), now)
            order = planner.build_orders(manifest, [state], players, now, defense)['orders'][0]
            self.assertEqual('magazine_reload_hold', order['combat_mode'])
            self.assertEqual(0., order['throttle_override'])
            self.assertEqual(7, order['target_id'])
            self.assertFalse(order['fire_allowed'])
            self.assertTrue(order['tactical_evidence']['withdrawal']['active_capture'])
            self.assertNotIn(3, planner._retreat_states)
        # A completed reload returns to combat without needing to leave capture.
        state.update(clip=4, reload_time=0.)
        planner.report_contacts([contact], planner.known_targets([state], players), 28.)
        ready = planner.build_orders(manifest, [state], players, 28., defense)['orders'][0]
        self.assertTrue(ready['fire_allowed'])
        self.assertNotEqual('base_defense', ready['combat_mode'])
        # Actual capture exit releases only this guard and normal defense applies.
        defense['contributors']['2'] = []
        state.update(z=380., clip=0, reload_time=27.)
        out = planner.build_orders(manifest,[state],players,31.,defense)['orders'][0]
        self.assertEqual('base_defense', out['combat_mode'])
        self.assertFalse(out['tactical_evidence']['withdrawal']['active_capture'])

    def test_reload_guard_is_membership_not_route_label_or_old_points(self):
        h=server_fixture; p=h.BotPlanner()
        bot=h._bot(3,1,0,h._route('capture',[(0,0,False),(0,450,False)]),'heavyTank')
        bot['state']=h._weapon_state(h._state(3,1,0,440),clip=0,clip_size=4,reload_time=27.,fire_seq=18)
        focus=dict(id=7,target_kind='human',visible=True,shootable_by_bot_ids=[3],position=dict(x=0.,y=0.,z=460.))
        order=p._order_for(bot,0,1,focus,[focus],1.,active_capture=False)
        self.assertIn(order['combat_mode'], ('magazine_reload_retreat','magazine_reload_hold'))
        self.assertFalse(order['tactical_evidence']['withdrawal']['active_capture'])
        self.assertIn(3,p._retreat_states)
        held=p._order_for(bot,0,1,focus,[focus],2.,active_capture=True)
        self.assertEqual('magazine_reload_hold',held['combat_mode'])
        self.assertNotIn(3,p._retreat_states)
        self.assertEqual('active_capture_reload',held['tactical_evidence']['withdrawal']['released'])


class MausPhysicalCorridorTests(unittest.TestCase):
    def setUp(self):
        self.state=dict(id=18,team=1,position=(-10.190999231392443,-2.627039670944214,113.44262431702671),
            yaw=.07226989197644697,pitch=-.07769934467862143,roll=.02776846321142524,
            collision_shape=(1.7309390306472778,4.409120082855225,0.,2.3498300313949585),
            half_width=1.7309390306472778,half_length=4.409120082855225,dt=.1,speed=0.)
        self.peer=dict(id=7,team=1,alive=False,position=(-6.145095053265735,-2.347686290740967,114.14252058486774),
            yaw=2.9198859220866322,pitch=-.016258197125277048,roll=-.116294727579601,
            shape=(1.631669044494629,1.8438169956207275,-.012354999780654907,2.1293100118637085))
        self.state['neighbours']=[self.peer]
        self.adapter=BotAdapter('22_slough',1)

    def test_recorded_contact_admits_actual_forward_escape_without_shrinking_body(self):
        s=self.state; d=self.adapter.driver; p=s['position']; body=d.collision_body(s)
        self.assertIsNotNone(self.adapter._hull_contact(18,s,p))
        for distance in (1.,3.,5.,7.):
            self.assertEqual(1.,tank_collision.translation_fraction(body,
                (math.sin(s['yaw'])*distance,math.cos(s['yaw'])*distance),[d.collision_body(self.peer)]))
            self.assertIsNone(d._reverse_blocked_by_vehicle(p,s['yaw']+math.pi,
                [self.peer],s['half_length'],s['half_width'],distance,body))
        self.assertFalse(d._static_hull_ahead(p,s['yaw'],[self.peer],s['half_length'],s['half_width'],body))
        contact=self.adapter._hull_contact(18,s,p)
        # Exercise the real local contact-plan producer, then its retained check.
        plan=self.adapter._contact_escape_plan(s,p,lambda *args:True,contact)
        self.assertIsNotNone(plan)
        self.assertEqual('contact_escape',plan[1]['recovery_mode'])
        self.assertNotEqual(0.,plan[1]['throttle'])
        self.assertEqual(s['collision_shape'],body['shape'])

    def test_real_intervening_hull_and_world_veto_remain(self):
        s=self.state;d=self.adapter.driver;p=s['position'];b=d.collision_body(s)
        rear=dict(self.peer,id=99,position=(p[0]-math.sin(s['yaw'])*8,p[1],p[2]-math.cos(s['yaw'])*8),yaw=s['yaw'],pitch=0.,roll=0.,shape=s['collision_shape'])
        self.assertEqual(99,d._reverse_blocked_by_vehicle(p,s['yaw'],[rear],s['half_length'],s['half_width'],10.,b))
        c=self.adapter._hull_contact(18,s,p)
        self.assertIsNone(self.adapter._contact_escape_plan(s,p,lambda *args:False,c))


class TortoiseHandoffTests(unittest.TestCase):
    def setUp(self):
        self.f=runtime_fixture.BotRuntimeTests();self.f.setUp()
    def tearDown(self):
        self.f.tearDown()
    def test_real_runtime_contact_receipt_survives_contact_response_and_releases_laying(self):
        h=runtime_fixture
        descriptor=h._combat_descriptor(turret_yaw_limits=(-.349,.349),turret_speed=1.)
        rt=self.f.module.BotRuntime(1,descriptor_resolver=lambda unused:descriptor,
            direction_probe=lambda *args:dict(clear=True,slope=0.),
            ground_probe=lambda *args:0.,physics_ground_probe=lambda *args:0.,
            rotation_resolver=lambda *args:True,spawn_resolver=lambda *args:((0.,0.,0.),0.),
            visibility_probe=lambda *args:True,firing_lane_probe=lambda *args:True,
            baked_graph=h._flat_open_graph())
        rt.battle_start(self.f.start)
        point=(10.,0.,-100.)
        rt._apply_orders(dict(bot_order_revision=1,bot_orders=[dict(id=11,team=2,
            combat_mode='cover_hold',target_kind='human',target_id=2,
            move_position=(0.,0.,0.),aim_position=point,face_position=point,
            fire_range=500.,fire_allowed=False,throttle_override=0.)]))
        player=h._admit_player(dict(id=2,team=1,alive=True,x=10.,y=0.,z=-100.))
        with mock.patch.object(rt,'_rotation_fraction_for',return_value=0.):
            rt.update(.05,.05,players=[player])
            state=rt.states[11]
            self.assertIn('_rear_aim_episode',state)
            self.assertIn('_rear_contact_refusal',state)
            # Contact processing consumes this independent traffic flag.
            state.pop('_rotation_contact_blocked',None)
            released=False
            for frame in range(2,81):
                rt.update(.05,frame*.05,players=[player])
                if '_rear_aim_episode' not in state:
                    released=True
                if released:
                    self.assertNotIn('_rear_aim_episode',state)
            self.assertTrue(released)
            self.assertIn('_gun_angle_adjustment',state)
            self.assertIsNotNone(state['_gun_angle_adjustment']['destination'])
            self.assertEqual(0,state['fire_seq'])

    def test_stationary_contact_expiry_cannot_recreate_rear_episode_and_relocates(self):
        rt=self.f.module.BotRuntime(1)
        state=dict(id=23,slot=1,team=2,x=-3.158,y=-7.225,z=41.474,yaw=2.057431014,
            pitch=0.,roll=0.,speed=0.,fire_seq=8,half_length=4.,profile={'class_tag':'AT-SPG'},
            _rear_aim_episode=dict(identity=('bot',8),target_id=8,fire_seq=8,start=1.),
            _rear_contact_refusal=dict(identity=('bot',8),position=(-3.158,-7.225,41.474),yaw=2.057431014,fraction=0.))
        target=dict(kind='bot',id=8,alive=True,position=(1.,-7.225,160.))
        order=dict(combat_mode='cover_hold',target_id=8,target_kind='bot',fire_allowed=False,
            move_position=(-3.158,-7.225,41.474),throttle_override=0.)
        out=rt._rear_laying_order(state,order,{8:target},2.)
        self.assertNotIn('_rear_aim_episode',state)
        self.assertEqual(('bot',8),state['_gun_angle_pivot_refusal'])
        self.assertEqual('contact_blocked',state['_rear_motion_observation']['laying_terminal'])
        bearing=math.atan2(target['position'][0]-state['x'],target['position'][2]-state['z'])
        for backend in (None,(1.,0.,1)):
            with mock.patch.object(driver.native_math,'call',return_value=backend) as native:
                self.assertEqual((0.,0.,False),driver.combat_hull_aim(state['yaw'],bearing,-.349,.349,
                    0.,0.,'arrived',True,combat_mode='cover_hold',movement_intent=False,allow_rear_start=False))
                native.assert_not_called()
        rt._gun_angle_order(state,out,{8:target},2.,lambda *args:True)
        moved=rt._gun_angle_order(state,out,{8:target},4.,lambda *args:True)
        self.assertIn(moved['combat_mode'],('gun_angle_adjust','withdraw'))
        self.assertNotEqual(order['move_position'],moved['move_position'])
        self.assertNotEqual(0.,moved['throttle_override'])
        self.assertEqual(8,moved['target_id'])
        # Neither the cooldown nor contact receipt suppresses normal forward aim.
        self.assertTrue(driver.combat_hull_aim(0.,.5,-.349,.349,0.,0.,'arrived',True,
            combat_mode='cover_hold',movement_intent=False,allow_rear_start=False)[2])
        self.assertTrue(driver.combat_hull_aim(0.,2.,-.349,.349,0.,0.,'arrived',True,
            combat_mode='cover_hold',movement_intent=False,allow_rear_start=True)[2])


    def test_pivot_handoff_cleans_up_on_completion_failure_target_and_priority_change(self):
        for terminal in ('arrived','stalled','blocked','new_target','front_arc','base_defense'):
            with self.subTest(terminal=terminal):
                rt=self.f.module.BotRuntime(1)
                state=dict(id=23,x=0.,y=0.,z=0.,yaw=0.,speed=0.,
                    profile={'class_tag':'AT-SPG'},_gun_angle_pivot_refusal=('bot',8))
                target=dict(kind='bot',id=8,alive=True,position=(10.,0.,-100.))
                targets={8:target,9:dict(target,id=9)}
                order=dict(target_id=8,target_kind='bot',combat_mode='cover_hold',
                    move_position=(0.,0.,0.),aim_position=target['position'],
                    face_position=target['position'],throttle_override=0.)
                rt._gun_yaw_limits[23]=(-.349,.349,True)
                clear=lambda *args:terminal!='blocked'
                rt._gun_angle_order(state,order,targets,1.,clear)
                rt._gun_angle_order(state,order,targets,3.,clear)
                if terminal=='arrived':state['z']=8.
                elif terminal=='new_target':order['target_id']=9
                elif terminal=='front_arc':target['position']=(0.,0.,100.)
                elif terminal=='base_defense':order['combat_mode']='base_defense'
                result=rt._gun_angle_order(state,order,targets,10.,clear)
                self.assertNotIn('_gun_angle_pivot_refusal',state)
                self.assertNotIn('_gun_angle_adjustment',state)
                if terminal in ('stalled','blocked'):
                    self.assertEqual('advance_contact',result['combat_mode'])
                    self.assertEqual(8,result['target_id'])
                    self.assertTrue(rt._gun_angle_rejected(state,('bot',8),10.))



class SpgFrozenPivotTests(unittest.TestCase):
    def setUp(self):
        self.f=runtime_fixture.BotRuntimeTests();self.f.setUp()
    def tearDown(self):
        self.f.tearDown()
    def test_support_float_jitter_preserves_bounded_proof_until_one_committed_shot(self):
        from gui.mods.offline_lan_0922.artillery_controller import ArtilleryController
        descriptor=runtime_fixture._combat_descriptor(dispersion=.03)
        descriptor.gun.shots=({'shell':{'effectsIndex':0},'speed':425.,'gravity':143.,'maxDistance':10000.},)
        controller=ArtilleryController(maximum_step=.12)
        keys=[];origins=[]
        def launch(source,target,installed,shell,seq,yaw,pitch,flight,now):
            origin=(source['x'],source['y']+1.7,source['z'])
            ready,receipt=controller.request_launch(source,target,installed,shell,seq,origin,yaw,pitch,flight,now)
            keys.append(controller._launch_keys[source['id']]);origins.append(origin)
            return receipt
        rt=self.f.module.BotRuntime(1,artillery_launch_probe=launch,artillery_launch_cancel=controller.cancel_launch)
        rt.round_id=7
        state=dict(id=30,x=0.,y=-4.334611415863037,z=0.,yaw=0.,pitch=0.,roll=0.,turret_yaw=0.,
            aim_yaw=0.,gun_pitch=-.1,gun_aligned=True,speed=0.,fire_seq=0,critical={},profile={'class_tag':'SPG'})
        target=dict(kind='bot',id=8,alive=True,position=(0.,0.,100.))
        solution=dict(yaw=0.,pitch=-.1,flight_time=.5,aim_position=(0.,1.,100.))
        gun=self.f.module._BotGunState(descriptor);gun.elapsed=100.
        receipt=None
        for frame in range(1,61):
            now=frame*.04
            state['y']=(-4.334611415863037 if frame%2 else -4.334610939025879)
            receipt=rt._artillery_launch_receipt(state,target,descriptor,0,gun,solution,now)
            if receipt is not None:break
            self.assertLessEqual(controller.advance(now,4,lambda *args:None),4)
            self.assertEqual(0,state['fire_seq'])
        self.assertIsNotNone(receipt)
        self.assertGreater(frame,1)
        self.assertEqual(1,len(set(keys)))
        self.assertEqual(1,len(set(origins)))
        self.assertEqual(origins[0],receipt['origin'])
        self.assertTrue(rt._fire(state,gun,1.,descriptor,launch_receipt=receipt))
        self.assertEqual(1,state['fire_seq'])
        self.assertEqual(receipt['origin'],state['shot_origin'])
        self.assertIsNone(rt._active_artillery_intent(state,target,descriptor,0,now))

    def test_real_motion_and_turret_change_cancel_frozen_intent(self):
        descriptor=runtime_fixture._combat_descriptor()
        for field,delta in (('x',.06),('yaw',.002),('turret_yaw',.002),('gun_pitch',.002)):
            rt=self.f.module.BotRuntime(1,artillery_launch_probe=lambda *args:None)
            state=dict(id=30,x=0.,y=0.,z=0.,yaw=0.,turret_yaw=0.,gun_pitch=-.1,aim_yaw=0.,gun_aligned=True,fire_seq=0)
            target=dict(kind='bot',id=8,alive=True,position=(0.,0.,100.))
            solution=dict(yaw=0.,pitch=-.1,flight_time=.5,aim_position=(0.,1.,100.))
            gun=self.f.module._BotGunState(descriptor)
            self.assertIsNotNone(rt._create_artillery_intent(state,target,descriptor,0,gun,solution,1.))
            state[field]+=delta
            self.assertIsNone(rt._active_artillery_intent(state,target,descriptor,0,1.1))
            self.assertNotIn(30,rt._artillery_intents)

if __name__=='__main__':unittest.main()
