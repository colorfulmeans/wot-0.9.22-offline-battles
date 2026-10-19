"""Report 153057: a completed macro lane must stop owning hull travel."""
import math
import copy
import unittest

from test_port_0922_server_bot_ai import BotPlanner, _bot, _bot_contact, _route, _state
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter


class TerminalRouteHandoffTests(unittest.TestCase):
    def scene(self, position=(3.895151847505288, -248.40366079137343)):
        planner = BotPlanner()
        route = _route('banana', [(70.,346.,False),(84.523,-194.48,False),(2.,-250.,False)])
        own = _bot(17,2,1,route,'heavyTank',{'brawler':1.})
        own['profile'].update(dominant_role='brawler',armor=190.,desired_range=180.,fire_range=340.)
        enemy = _bot(8,1,7,_route('enemy',[(200.,300.,False),(200.,-300.,False)]),'mediumTank')
        states = [_state(17,2,*position),_state(8,1,202.09239721122165,-95.63260189747022)]
        states[0].update(y=1.1,yaw=-.5280365478097515)
        defense = dict(capture_bases={'1':[dict(id='1:0',x=2.505,y=0.,z=-252.6)],'2':[]})
        return planner,[own,enemy],states,defense

    def order(self, scene, now=1., lane=True, contact=True):
        planner,manifest,states,defense=scene
        if contact:
            enemy=states[1]
            report=_bot_contact(enemy['id'],enemy['x'],enemy['z'],[17] if lane else [])
            report.update(observing_team=2,target_team=1)
            self.assertEqual(1,planner.report_contacts([report],planner.known_targets(states,[]),now))
        return next(o for o in planner.build_orders(manifest,states,[],now,defense)['orders'] if o['id']==17)

    def test_reported_endpoint_hands_hull_to_enemy_without_changing_target(self):
        scene=self.scene(); order=self.order(scene)
        self.assertEqual('engage',order['combat_mode'])
        self.assertEqual(('bot',8),(order['target_kind'],order['target_id']))
        self.assertTrue(order['fire_allowed'])
        self.assertEqual(0.,order['throttle_override'])
        self.assertEqual('engage',order['tactical_evidence']['route_terminal']['outcome'])
        pose=scene[2][0]
        command=BotAdapter('86_himmelsdorf_winter',1).decide_with_order(dict(
            id=17,slot=1,team=2,position=(pose['x'],pose['y'],pose['z']),
            yaw=pose['yaw'],speed=0.,dt=.1),order,lambda *a:True)
        self.assertFalse(command['movement_intent'])
        self.assertTrue(command['control_trace']['face_override'])
        face=order['face_position']
        expected=math.atan2(face['x']-pose['x'],face['z']-pose['z'])
        self.assertAlmostEqual(expected,command['target_yaw'])

    def test_enemy_lane_loss_keeps_target_but_does_not_authorize_fire(self):
        scene=self.scene(); self.order(scene)
        order=self.order(scene,2.,lane=False)
        self.assertEqual(8,order['target_id'])
        self.assertFalse(order['fire_allowed'])
        self.assertEqual(0.,order['throttle_override'])
        self.assertEqual('engage',order['combat_mode'])

    def test_contact_free_capture_finishes_with_a_stable_hold(self):
        scene=self.scene()
        first=self.order(scene,contact=False)
        self.assertEqual('base_capture',first['combat_mode'])
        self.assertEqual('1:0',first['capture_base_id'])
        self.assertEqual(0.,first['throttle_override'])
        scene[2][0]['x']+=1.
        second=self.order(scene,2.,contact=False)
        self.assertEqual(first['move_position'],second['move_position'])
        self.assertEqual(0.,second['throttle_override'])
        self.assertFalse(second['fire_allowed'])

    def test_reloading_at_terminal_keeps_engagement_and_existing_fire_gate(self):
        scene=self.scene();first=self.order(scene)
        scene[2][0].update(clip=0,reload_time=8.,ammo_reload_pending=True,fire_seq=1)
        order=self.order(scene,2.)
        self.assertEqual('engage',order['combat_mode'])
        self.assertEqual(8,order['target_id'])
        self.assertFalse(order['fire_allowed'])
        self.assertEqual(first['move_position'],order['move_position'])
        self.assertEqual(0.,order['throttle_override'])

    def test_enemy_death_hands_completed_route_back_to_capture(self):
        scene=self.scene();self.order(scene)
        scene[2][1].update(alive=False,health=0)
        order=self.order(scene,2.,contact=False)
        self.assertIsNone(order['target_id'])
        self.assertEqual('base_capture',order['combat_mode'])
        self.assertEqual(0.,order['throttle_override'])
        self.assertFalse(order['fire_allowed'])

    def test_push_outside_terminal_radius_resumes_original_route(self):
        scene=self.scene(); self.order(scene)
        scene[2][0].update(x=25.,z=-245.)
        order=self.order(scene,2.)
        self.assertEqual('advance',order['combat_mode'])
        self.assertEqual(1.,order['throttle_override'])
        self.assertEqual(dict(x=2.,y=0.,z=-250.),order['move_position'])
        self.assertEqual('outside_arrival',order['tactical_evidence']['route_terminal']['outcome'])

    def test_intermediate_point_and_distant_final_point_keep_travel(self):
        for pose in ((84.523,-194.48),(30.,-220.)):
            with self.subTest(pose=pose):
                scene=self.scene(pose); order=self.order(scene,contact=False)
                self.assertNotEqual(0.,order['throttle_override'])
                self.assertIn(order['combat_mode'],('advance','base_capture','route'))
                self.assertNotIn(order['tactical_evidence']['route_terminal']['outcome'],('hold','base_capture'))

    def test_low_health_and_empty_magazine_retain_withdrawal_ownership(self):
        for state in (dict(health=10),dict(clip=0,clip_size=4,fire_seq=1,reload_time=25.)):
            with self.subTest(state=state):
                scene=self.scene();scene[2][0].update(state)
                order=self.order(scene)
                self.assertIn(order['combat_mode'],('low_health_retreat','low_health_defend',
                                                   'magazine_reload_retreat','magazine_reload_hold'))

    def test_single_point_automatic_goal_keeps_existing_precise_arrival(self):
        scene=self.scene((8.,-250.))
        scene[1][0]['route']=_route('automatic',[(2.,-250.,False)])
        order=self.order(scene)
        self.assertNotEqual(0.,order['throttle_override'])
        self.assertEqual('outside_arrival',order['tactical_evidence']['route_terminal']['outcome'])

    def test_completed_lane_without_capture_objective_holds_without_a_hull_turn(self):
        scene=self.scene();scene[3].clear()
        order=self.order(scene,contact=False)
        self.assertEqual('hold',order['combat_mode'])
        self.assertEqual(0.,order['throttle_override'])
        self.assertEqual(order['move_position'],order['face_position'])
        self.assertIsNone(order['target_id'])

    def test_actual_circle_not_authored_terminal_controls_capture_arrival(self):
        scene=self.scene();scene[3]['capture_bases']['1'][0].update(x=100.,z=-250.)
        order=self.order(scene,contact=False)
        self.assertEqual('base_capture',order['combat_mode'])
        self.assertIsNone(order['throttle_override'])
        self.assertEqual(100.,order['move_position']['x'])
        self.assertFalse(order['tactical_evidence']['route_terminal']['inside_capture'])

    def test_native_physical_refusal_is_not_consumed_as_completed_travel(self):
        scene=self.scene();scene[2][0]['route_wreck_blocked']=True
        order=self.order(scene)
        self.assertEqual('advance',order['combat_mode'])
        self.assertEqual('physical_or_capture_not_arrived',
                         order['tactical_evidence']['route_terminal']['outcome'])

    def test_parked_or_tactical_orders_and_separate_repositioning_are_untouched(self):
        scene=self.scene();original=self.order(scene);planner,manifest,states,defense=scene
        bot=planner._alive_bots(manifest,states)[0]
        # _alive_bots retains the manifest order (own Bot 17 first).
        target=planner._capture_target(defense,2)
        for change,outcome in ((dict(combat_mode='cover_peek'),'tactical_owner'),
                (dict(team_command='attack'),'tactical_owner'),
                (dict(parking_phase='approach'),'tactical_owner'),
                (dict(move_position=dict(x=84.523,y=0.,z=-194.48)), 'different_destination')):
            with self.subTest(change=change):
                order=copy.deepcopy(original)
                order.update(combat_mode='advance',move_position=dict(x=2.,y=0.,z=-250.),
                             throttle_override=1.)
                order.update(change)
                expected={k:copy.deepcopy(v) for k,v in order.items() if k!='tactical_evidence'}
                planner._handoff_route_terminal(order,bot,target,3.)
                self.assertEqual(expected,{k:v for k,v in order.items() if k!='tactical_evidence'})
                self.assertEqual(outcome,order['tactical_evidence']['route_terminal']['outcome'])

    def test_hold_releases_on_goal_change_and_reset_clears_arrival(self):
        scene=self.scene();self.order(scene)
        planner=scene[0]
        self.assertIn('terminal_hold',planner._route_states[17])
        scene[1][0]['route']['waypoints'][-1].update(x=100.,z=-250.)
        order=self.order(scene,2.)
        receipt=order['tactical_evidence']['route_terminal']
        self.assertEqual('goal_changed',receipt['released'])
        self.assertNotIn('terminal_hold',planner._route_states[17])
        planner.reset(2)
        self.assertEqual({},planner._route_states)


if __name__=='__main__':
    unittest.main()
