"""Foreground player ownership, native seams and captured failure regressions."""
import ast
import itertools
import math
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import player_control
from gui.mods.offline_lan_0922.player_control.ammunition import Ammunition
from gui.mods.offline_lan_0922.player_control.driving import Driver, angle
from gui.mods.offline_lan_0922.player_control.weapon import Weapon
from gui.mods.offline_lan_0922.player_control.weapon import barrel_aligned
from gui.mods.offline_lan_0922.player_control.traffic import Traffic, body
from gui.mods.offline_lan_0922.player_control.strategy import Strategy
from gui.mods.offline_lan_0922.player_control.navigation import PlayerNavigation, route_candidates


class PlayerRegressionTests(unittest.TestCase):
    def policy(self, main=0, loaded=0):
        return Ammunition([dict(index=0,kind='ARMOR_PIERCING'),
                           dict(index=1,kind='HIGH_EXPLOSIVE')],main,loaded)

    def test_terminal_before_penetration_does_not_switch_to_he(self):
        p=self.policy()
        for i in range(1,8):
            p.launch(str(i),0,42,i)
            p.terminal(dict(projectile_id=str(i),hit_vehicle=True),i+.1)
            self.assertEqual([],p.settle([50,5],i+.2))
            p.hit(dict(projectile_id=str(i),damage=250,shot_result=2))
            result=p.settle([50,5],i+.3)
            self.assertTrue(result[0]['known'])
            self.assertEqual(0,p.choose([50,5]))

    def test_two_confirmed_failures_switch_but_penetration_resets_counter(self):
        p=self.policy()
        for i,damage in enumerate((0,200,0,0)):
            p.launch(str(i),0,42,i)
            p.terminal(dict(projectile_id=str(i),hit_vehicle=True),i)
            p.hit(dict(projectile_id=str(i),damage=damage,shot_result=2 if damage else 1))
            p.settle([20,5],i+.1)
            self.assertEqual(1 if i==3 else 0,p.desired)

    def test_full_standard_premium_he_cycle_uses_actual_available_stocks(self):
        p=Ammunition([dict(index=0,kind='ARMOR_PIERCING'),
                      dict(index=1,kind='ARMOR_PIERCING_CR'),
                      dict(index=2,kind='HIGH_EXPLOSIVE')],0,0)
        for i,shell in enumerate((0,0,1,1,2,2)):
            p.launch(str(i),shell,42,i)
            p.hit(dict(projectile_id=str(i),damage=50 if shell==2 else 0,shot_result=2))
            p.terminal(dict(projectile_id=str(i),hit_vehicle=True),i)
            p.settle([20,20,6],i)
            if i in (1,3,5):self.assertEqual({1:1,3:2,5:0}[i],p.choose([20,20,6]))

    def test_missing_effect_is_unknown_never_a_failure(self):
        p=self.policy()
        for i in range(3):
            p.launch(str(i),0,42,i*3)
            p.terminal(dict(projectile_id=str(i),hit_vehicle=True),i*3)
            self.assertFalse(p.settle([20,5],i*3+2.1)[0]['known'])
        self.assertEqual(0,p.failures)
        self.assertEqual(0,p.desired)

    def test_cosmetic_zero_damage_is_a_known_failure(self):
        p=self.policy()
        for i in range(2):
            p.launch(str(i),0,42,i)
            p.hit(dict(projectile_id=str(i),damage=0,shot_result=1,cosmetic_only=True))
            p.terminal(dict(projectile_id=str(i),hit_vehicle=True),i)
            p.settle([20,5],i)
        self.assertEqual(1,p.desired)

    def test_he_returns_after_two_rounds_without_consulting_damage(self):
        p=self.policy();p.protected=False
        for i in range(2):
            p.launch(str(i),1,42,i)
            p.hit(dict(projectile_id=str(i),damage=200,shot_result=2))
            p.terminal(dict(projectile_id=str(i),hit_vehicle=True),i)
            p.settle([20,5],i)
        self.assertEqual(0,p.desired)

    def test_loaded_manual_round_is_protected_once(self):
        p=self.policy(loaded=1)
        self.assertTrue(p.protected)
        self.assertEqual(1,p.choose([20,5]))
        p.launch('p',1,42,0)
        self.assertFalse(p.protected)
        self.assertEqual(0,p.choose([20,5]))

    def test_duplicate_terminal_and_effect_do_not_reapply_after_settlement(self):
        p=self.policy();p.launch('p',0,42,0)
        p.hit(dict(projectile_id='p',damage=0,shot_result=1))
        p.terminal(dict(projectile_id='p',hit_vehicle=True),0)
        p.settle([20,5],0)
        p.terminal(dict(projectile_id='p',hit_vehicle=True),1)
        p.hit(dict(projectile_id='p',damage=0,shot_result=1))
        self.assertEqual([],p.settle([20,5],1))
        self.assertEqual(1,p.failures)

    def test_out_of_order_results_drain_in_launch_order(self):
        p=self.policy()
        p.launch('a',0,42,0);p.launch('b',0,42,0)
        p.hit(dict(projectile_id='b',damage=200,shot_result=2))
        p.terminal(dict(projectile_id='b',hit_vehicle=True),0)
        self.assertEqual([],p.settle([20,5],0))
        p.hit(dict(projectile_id='a',damage=0,shot_result=1))
        p.terminal(dict(projectile_id='a',hit_vehicle=True),0)
        self.assertEqual(['a','b'],[r['id'] for r in p.settle([20,5],0)])
        self.assertEqual(0,p.failures)

    def test_objective_behind_tank_pivots_and_never_reverses(self):
        d=Driver();yaw=0.;position=[0.,0.,0.]
        for i in range(200):
            order=d.drive(position,yaw,0.,(0,0,-40),i*.1,lambda *a:True)
            self.assertGreaterEqual(order['throttle'],0.)
            yaw=angle(yaw+order['turn']*.08)
            position[0]+=math.sin(yaw)*order['throttle']*.6
            position[2]+=math.cos(yaw)*order['throttle']*.6
        self.assertLess(position[2],-25)

    def test_captured_near_tip_does_not_alternate_forward_reverse(self):
        d=Driver();position=[-9.2,.258,33.65];yaw=0.
        target=(-14,.258,30.)
        for i in range(100):
            order=d.drive(position,yaw,0.,target,i*.1,lambda *a:True)
            self.assertGreaterEqual(order['throttle'],0.)
            yaw=angle(yaw+order['turn']*.08)
            position[0]+=math.sin(yaw)*order['throttle']*.3
            position[2]+=math.cos(yaw)*order['throttle']*.3
        self.assertLess(math.hypot(position[0]-target[0],position[2]-target[2]),2.1)

    def test_blocked_all_directions_cannot_reverse_into_mountain(self):
        d=Driver()
        for i in range(100):
            order=d.drive((0,0,0),0,0,(0,0,40),i*.1,lambda *a:False)
            self.assertEqual(0,order['throttle'])

    def test_recovery_direction_is_latched_not_frame_alternation(self):
        d=Driver();d.reverse_until=1.
        for i in range(9):
            order=d.drive((0,0,0),0,0,(10,0,0),i*.1,lambda *a:True)
            self.assertEqual(-1,order['throttle'])
            self.assertEqual(0,order['turn'])

    def test_hold_cancels_reverse_and_releases_progress_anchor(self):
        d=Driver();d.reverse_until=10
        order=d.drive((0,0,0),0,0,(0,0,30),1,lambda *a:True,hold=True)
        self.assertEqual(0,order['throttle']);self.assertTrue(order['brake'])
        self.assertEqual(0,d.reverse_until)

    def test_native_aim_source_is_restored_after_takeover(self):
        source=lambda:'manual'
        class Rotator:
            clientMode=False
            def __init__(self):self._VehicleGunRotator__shotPointSourceFunctor=source
            @property
            def shotPointSourceFunctor(self):return self._VehicleGunRotator__shotPointSourceFunctor
            @shotPointSourceFunctor.setter
            def shotPointSourceFunctor(self,value):self._VehicleGunRotator__shotPointSourceFunctor=value
        rotator=Rotator()
        owner=types.SimpleNamespace(_avatar=types.SimpleNamespace(gunRotator=rotator,autoAim=lambda t:None),
             _mutable_shot_ray=lambda:((0,1,0),(0,0,1)),_vector=tuple)
        w=Weapon(owner);w.aim(42,(5,1,20),1)
        self.assertTrue(rotator.clientMode)
        self.assertEqual((5,1,20),rotator.shotPointSourceFunctor())
        w.close()
        self.assertIs(source,rotator.shotPointSourceFunctor)
        self.assertFalse(rotator.clientMode)

    def test_native_synchronous_commit_counts_as_accepted_without_pending_intent(self):
        owner=types.SimpleNamespace(_local_fire_intent=None)
        w=Weapon(owner)
        def shoot():w.committed+=1
        owner._avatar=types.SimpleNamespace(shoot=shoot,isWaitingForShot=True)
        self.assertTrue(w.trigger())
        self.assertEqual(1,w.trigger_receipt['committed_during_call'])

    def test_firing_alignment_uses_gravity_not_straight_target_ray(self):
        theta=.5*math.asin(10.*400./100.**2)
        self.assertTrue(barrel_aligned((0,0,0),(0,math.sin(theta),math.cos(theta)),100,10,(0,0,400),.1))
        self.assertFalse(barrel_aligned((0,0,0),(0,0,1),100,10,(0,0,400),.1))

    def test_unengaged_barrel_faces_forward_in_world_yaw(self):
        w=Weapon(types.SimpleNamespace());w.bind=lambda:None
        w.forward((10,0,20),math.pi/2,1.)
        self.assertAlmostEqual(110,w.point[0]);self.assertAlmostEqual(20,w.point[2])
        self.assertIsNone(w.target)

    def test_spg_splash_damage_does_not_count_as_failed_penetration(self):
        p=Ammunition([dict(index=0,kind='HIGH_EXPLOSIVE'),dict(index=1,kind='HIGH_EXPLOSIVE')],0,0,artillery=True)
        for i in range(3):
            p.launch(str(i),0,42,i)
            p.hit(dict(projectile_id=str(i),damage=100,shot_result=1))
            p.terminal(dict(projectile_id=str(i),hit_vehicle=True),i)
            p.settle([20,5],i)
        self.assertEqual(0,p.desired);self.assertEqual(0,p.failures)

    def traffic(self,point,alive=True):
        return Traffic(body(1,(0,0,0),0,(1.5,3.5,-.5,2.)),
            [dict(id=2,position=point,yaw=0,collision_shape=(1.5,3.5,-.5,2.),alive=alive)])

    def test_friend_ahead_blocks_forward_but_keeps_a_side_exit(self):
        t=self.traffic((0,0,8))
        self.assertFalse(t.clear(0,6))
        self.assertIn(2,t.receipt['blockers'])
        self.assertTrue(t.clear(math.pi/2,6))
        self.assertEqual([],t.receipt['blockers'])
        self.assertEqual(2,t.receipt['blocked_queries'][0]['actors'][0]['id'])
        self.assertTrue(t.receipt['blocked_queries'][0]['actors'][0]['alive'])

    def test_wreck_uses_the_same_clearance_as_a_live_vehicle(self):
        t=self.traffic((0,0,8),False)
        self.assertFalse(t.clear(0,6))
        self.assertFalse(t.receipt['blocked_queries'][0]['actors'][0]['alive'])

    def test_vehicle_on_overhead_bridge_does_not_block_ground(self):
        self.assertTrue(self.traffic((0,8,8)).clear(0,6))

    def test_initial_overlap_can_escape_backwards(self):
        self.assertTrue(self.traffic((0,0,5)).clear(math.pi,4))

    def test_base_alarm_preempts_front_and_clearance_rejoins_routes(self):
        s=Strategy();routes=[dict(id='main',waypoints=[(0,0),(0,100)])]
        result=s.decide(0,routes,routes[0],[],[],dict(points=10,invaders=1),(0,0),True)
        self.assertEqual('player_base_defence',result[0]['id'])
        self.assertIsNone(s.decide(2,routes,None,[],[],{},(0,0)))
        self.assertEqual(routes,s.decide(6,routes,None,[],[],{},(0,0)))

    def test_front_support_requires_stable_observed_pressure_and_cooldown(self):
        s=Strategy();routes=[dict(id='a',waypoints=[(0,0),(0,400)]),dict(id='b',waypoints=[(300,0),(300,400)])]
        contacts=[dict(position=(300,0,100))]*3
        self.assertIsNone(s.decide(0,routes,routes[0],contacts,[],{},(0,0)))
        self.assertIsNone(s.decide(7,routes,routes[0],contacts,[],{},(0,0)))
        self.assertEqual([routes[1]],s.decide(9,routes,routes[0],contacts,[],{},(0,0)))
        self.assertIsNone(s.decide(10,routes,routes[1],[],[],{},(0,0)))

    def test_blocked_flag_centre_can_join_supported_defence_approach(self):
        s=Strategy()
        routes=s.decide(0,[],None,[],[],dict(points=29,invaders=1),(0,0))
        p=PlayerNavigation.__new__(PlayerNavigation)
        p.routes=routes
        p.route=None;p.index=None;p.candidates=None;p.search=None;p.pending=None;p.retry_at=0.;p.receipt={}
        p._height=lambda point,hint:None if tuple(point)==(0,0) else 0.
        def begin(start,goal,**kw):
            return types.SimpleNamespace(step=lambda budget:None,done=True,result=(start,goal))
        p.navigator=types.SimpleNamespace(grid=types.SimpleNamespace(begin_plan=begin))
        self.assertTrue(p.join((0,0,25),1))
        self.assertNotEqual('player_base_defence',p.route['id'])
        self.assertEqual((0.,20.),p.route['waypoints'][0])

    def test_handover_preserves_admitted_burst_then_cancels_future_subshots(self):
        burst={};events=[]
        owner=types.SimpleNamespace(_local_fire_intent=dict(player_burst=burst),_local_player_burst=burst,
            _sender=types.SimpleNamespace(send_current=lambda:True),_gun_state=object(),
            _cancel_local_player_burst=lambda **kw:events.append('cancel'),
            _rescale_current_reload=lambda *a:events.append('reload'))
        c=player_control.PlayerControl(owner,('fire',));c.active=True;c.live=lambda:False
        c.record=lambda *a,**kw:None
        c.stop()
        self.assertEqual([],events)
        c.shot_committed({},dict(player_burst=burst,reload_factor=1.))
        self.assertEqual(['cancel','reload'],events)

    def test_native_trigger_owns_call_and_releases_authorization_on_error(self):
        owner=types.SimpleNamespace(_local_fire_intent=None)
        w=Weapon(owner)
        def shoot():
            self.assertTrue(w.triggering)
            owner._local_fire_intent={}
        owner._avatar=types.SimpleNamespace(shoot=shoot)
        self.assertTrue(w.trigger());self.assertFalse(w.triggering)
        owner._avatar.shoot=mock.Mock(side_effect=RuntimeError('native'))
        with self.assertRaises(RuntimeError):w.trigger()
        self.assertFalse(w.triggering)

    def test_inactive_panel_fire_records_synchronous_native_commit(self):
        owner=types.SimpleNamespace(_sender=object(),_local_fire_intent=None)
        c=player_control.PlayerControl(owner,())
        owner._player_control=c
        c.live=lambda:True
        c.record=lambda *a,**kw:None
        owner._avatar=types.SimpleNamespace(shoot=lambda:c.shot_committed({},{}))
        self.assertTrue(c.command(dict(action='fire'),0))
        self.assertFalse(c.active)
        self.assertIsNone(c.ammo_policy)
        self.assertEqual(1,c.shot_commits)

    def test_no_runtime_bot_policy_or_driver_dependencies(self):
        denied=('bot_runtime','bot_tactics_runtime','ammo_policy','ai.driver','ai.planner','bot_gunnery')
        for p in (ROOT/'src/res/scripts/client/gui/mods/offline_lan_0922/player_control').glob('*.py'):
            tree=ast.parse(p.read_text(encoding='utf8'))
            imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            self.assertFalse(set(denied).intersection(imports),str(p))
            self.assertNotIn('BotAdapter',p.read_text(encoding='utf8'))

    def test_worker_and_replay_cannot_attach_player_decisions(self):
        with mock.patch.dict(os.environ,{'WOT_OFFLINE_PLAYER_AUTOCONTROL':'drive,fire'}):
            for worker,replay in ((True,False),(False,True),(True,True)):
                owner=types.SimpleNamespace(_worker_mode=worker,_replay_mode=replay)
                self.assertIsNone(player_control.attach(owner))

    def test_mouse_is_consumed_only_for_active_fire_channel(self):
        class Handler:
            def handleKeyEvent(self,event):return 'manual'
        handler=Handler()
        owner=types.SimpleNamespace(_avatar=types.SimpleNamespace(inputHandler=handler))
        c=player_control.PlayerControl(owner,('fire',));c.input_available=lambda:True
        with mock.patch.dict(sys.modules,{'Keys':types.SimpleNamespace(KEY_GRAVE=41,KEY_LEFTMOUSE=256,KEY_RIGHTMOUSE=257),
                'game':types.SimpleNamespace(convertKeyEvent=lambda e:e)}):
            c.bind_input()
            for active,fire in itertools.product((False,True),repeat=2):
                c.active=active;c.features={'fire'} if fire else set()
                for key in (256,257):
                    self.assertEqual(True if active and fire else 'manual',handler.handleKeyEvent((True,key,0,False)))

    def test_main_and_reserve_entry_catalog_is_private(self):
        rows=[dict(id='main',waypoints=[(0,0)]),dict(id='reserve',waypoints=[(5,0)])]
        result=route_candidates({'1':rows},1,'heavyTank')
        self.assertEqual(['main','reserve'],[r['id'] for r in result])
        result[0]['waypoints'].append((1,1));self.assertEqual(1,len(rows[0]['waypoints']))

    def test_eight_feature_masks_claim_only_enabled_mailbox_channels(self):
        from test_port_0922_battle_runtime import _LANInputSender
        for drive,fire,consumables in itertools.product((False,True),repeat=3):
            names={n for n,on in zip(('drive','fire','consumables'),(drive,fire,consumables)) if on}
            owner=types.SimpleNamespace()
            c=player_control.PlayerControl(owner,names);c.active=True
            c.weapon=types.SimpleNamespace(triggering=False)
            owner._player_control=c
            owner.shoot=mock.Mock(return_value=True)
            sender=_LANInputSender(owner)
            sender.send_current=lambda:True
            sender.send_avatar_input(1,'move',dict(flags=1))
            self.assertEqual(0 if drive else 1,sender.forward)
            self.assertEqual(not fire,sender.send_avatar_input(1,'shoot',{}))
            c.weapon.triggering=True
            self.assertTrue(sender.send_avatar_input(1,'shoot',{}))

    def test_countdown_press_cannot_latch_live_key(self):
        c=types.SimpleNamespace(key_down=False,live=lambda:False,input_available=lambda:True,toggle=mock.Mock())
        with mock.patch.object(player_control,'_current',c),mock.patch.dict(sys.modules,{'Keys':types.SimpleNamespace(KEY_GRAVE=41)}):
            self.assertFalse(player_control.handle_key(True,41))
            self.assertFalse(c.key_down)
            c.live=lambda:True
            self.assertTrue(player_control.handle_key(True,41))
            player_control.handle_key(True,41)
            c.toggle.assert_called_once()
            player_control.handle_key(False,41)
            player_control.handle_key(True,41)
            self.assertEqual(2,c.toggle.call_count)

    def test_layer_disconnected_entry_is_rejected_before_ground_route(self):
        p=PlayerNavigation.__new__(PlayerNavigation)
        p.routes=[dict(id='bridge',waypoints=[(0,0)]),dict(id='ground',waypoints=[(20,0)])]
        p.route=None;p.index=None;p.candidates=None;p.search=None;p.pending=None;p.retry_at=0.;p.receipt={}
        p._height=lambda point,hint:8 if point[0]==0 else 0
        def begin(start,goal,**kw):
            path=((0,8,0),goal) if goal[1] else (start,goal)
            return types.SimpleNamespace(step=lambda budget:None,done=True,result=path)
        p.navigator=types.SimpleNamespace(grid=types.SimpleNamespace(begin_plan=begin))
        self.assertFalse(p.join((0,0,0),1));self.assertTrue(p.join((0,0,0),2))
        self.assertEqual('ground',p.route['id'])


if __name__=='__main__':unittest.main()
