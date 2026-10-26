"""Confirmed zero stock owns travel, without borrowing ordinary combat control."""
import copy
import unittest
from types import SimpleNamespace
from unittest import mock

from test_port_0922_server_bot_ai import BotPlanner, BattleState, _bot, _route, _state, _contact
from gui.mods.offline_lan_0922 import empty_ammo, spg_route_travel, spg_route_recovery


class InventoryProofTests(unittest.TestCase):
    def test_saved_total_limit_is_exact_and_keeps_native_capacity_and_magazine(self):
        from test_bot_shot_ammo_policy import profile
        from gui.mods.offline_lan_0922 import ammo_policy, bot_tactics
        from gui.mods.offline_lan_0922.bot_runtime import _BotAmmoState
        for clip in (1,3):
            p=profile(clip=clip)
            descriptor=dict(gun=dict(shots=[{}, {}, {}],maxAmmo=60,clip=(clip,2.)))
            for limit in (0,1,100):
                p['ammo_limit']=bot_tactics.normalize_values({'ammo_limit':limit})['ammo_limit']
                inventory=_BotAmmoState(descriptor,p)
                self.assertEqual(min(60,limit),sum(inventory.remaining))
                self.assertEqual(min(60,limit),sum(ammo_policy.allocation(p,60,3)))
                if limit==1:
                    self.assertTrue(inventory.consume_loaded())
                    self.assertFalse(inventory.can_fire())
                    self.assertEqual(0,sum(inventory.remaining))
            self.assertEqual((clip,2.),descriptor['gun']['clip'])
        for value in (True,-1,1.5,1801):
            with self.assertRaises(bot_tactics.TacticsError):bot_tactics.normalize_values({'ammo_limit':value})

    def test_only_complete_numeric_zero_inventory_can_trigger(self):
        for values in (None, [], [None], [False], ['0'], [0, 1], [-1], [float('nan')]):
            with self.subTest(values=values):
                self.assertFalse(empty_ammo.confirmed(dict(ammo_remaining=values)))
        self.assertFalse(empty_ammo.confirmed(dict(ammo_remaining=[0]), dict(shells=[{}, {}])))
        self.assertTrue(empty_ammo.confirmed(dict(ammo_remaining=[0, 0, 0])))
        self.assertFalse(empty_ammo.confirmed(dict(clip=0, reload_time=30, ammo_remaining=[0, 2])))

    def test_local_handoff_once_preserves_projectile_ledger_and_new_recovery(self):
        state = dict(id=11, _rear_motion_lease={}, _authored_spg_travel={'kind':'defense'})
        adapter = SimpleNamespace(driver=SimpleNamespace(states={11:{'paused':True}}), _withdrawal_attempts={11:{}})
        cancel = mock.Mock()
        runtime = SimpleNamespace(adapter=adapter, _cancel_artillery_intent=cancel,
                                  _launched_projectiles={42:'in-flight'})
        empty_ammo.handoff(runtime, state, {'empty_ammo':True})
        self.assertNotIn('_rear_motion_lease', state)
        self.assertNotIn('_authored_spg_travel', state)
        adapter.driver.states[11] = {'recovery':'new'}
        empty_ammo.handoff(runtime, state, {'empty_ammo':True})
        self.assertEqual({'recovery':'new'}, adapter.driver.states[11])
        self.assertEqual({42:'in-flight'}, runtime._launched_projectiles)
        cancel.assert_called_once_with(11)


class EmptyTravelTests(unittest.TestCase):
    def setUp(self):
        self.planner = BotPlanner()
        self.route = _route('road', [(0,0,False), (0,100,False), (0,200,False), (0,300,False), (0,400,False)])
        self.manifest = [_bot(11,1,0,self.route,'heavyTank')]
        self.state = _state(11,1,0,100)
        self.state.update(ammo_remaining=[0],clip=0)
        self.defense = dict(capture_bases={'1':[dict(id='home',x=0,z=0,radius=30)],
                                          '2':[dict(id='enemy',x=0,z=400,radius=30)]})
        self.planner._task_graph = lambda:None

    def tick(self, now=1., commands=None):
        return self.planner.build_orders(self.manifest,[self.state],[],now,
            defense=self.defense,team_orders=commands)['orders'][0]

    def test_first_trigger_drops_old_tasks_but_later_ticks_keep_recovery(self):
        p = self.planner
        p._travel_tasks[11] = dict(kind='guard', route=self.route)
        p._previous_combat.add(11)
        p._previous_player[11] = dict(id='old')
        p._retreat_states[11] = dict(moving_mode='magazine_reload_retreat')
        order = self.tick()
        self.assertTrue(order['empty_ammo'])
        self.assertNotIn(11,p._travel_tasks)
        self.assertNotIn(11,p._previous_combat)
        self.assertNotIn(11,p._previous_player)
        self.assertNotIn(11,p._retreat_states)
        self.state.update(z=150,route_wreck_blocked=True)
        self.tick(2); self.tick(23)
        self.assertIn(11,p._route_recoveries)
        recovery = p._route_recoveries[11]
        self.tick(24)
        self.assertIs(recovery,p._route_recoveries[11])

    def test_external_commands_are_excluded_but_own_recovery_remains_mobile(self):
        self.tick()
        bot = self.planner._alive_bots(self.manifest,[self.state])[0]
        self.assertFalse(self.planner._base_defense_eligible(bot))
        self.assertFalse(self.planner._route_donor_eligible(bot))
        self.assertTrue(self.planner._route_mobile(bot))
        order = self.tick(2,[dict(command='STOP',command_id='stop',team=1,
                                 issued_tick=1,expires_tick=100,recipient_bot_ids=[11])])
        self.assertNotEqual('team_stop',order['combat_mode'])
        self.assertIsNone(order['throttle_override'])
        self.assertFalse(BattleState._team_command_bot_can_respond(self.state,order,'BACKTOBASE'))

    def test_known_enemy_and_hit_do_not_steal_hull_but_aim_is_retained(self):
        enemy = dict(id=2,team=2,alive=True,x=50.,y=0.,z=150.,health=1000,max_health=1000)
        contact = _contact(2,50,150,[11])
        p = self.planner
        p.report_contacts([contact],p.known_targets([self.state],[enemy]),1.)
        order = p.build_orders(self.manifest,[self.state],[enemy],1.,defense=self.defense)['orders'][0]
        self.assertEqual(2,order['target_id'])
        self.assertEqual('route',order['combat_mode'])
        self.assertEqual(order['move_position'],order['face_position'])
        self.assertFalse(order['fire_allowed'])
        self.assertIsNone(order['throttle_override'])

    def test_skip_gate_return_and_repeat_is_not_blocked_by_donor_exclusion(self):
        self.tick(0)
        self.state.update(z=150,route_wreck_blocked=True)
        self.planner._route_states[11].update(index=2)
        a = self.tick(1); b = self.tick(22); c = self.tick(43)
        self.assertEqual('skip_gate',b['route_attempt']['action'])
        self.assertEqual('return_to_anchor',c['route_attempt']['action'])
        self.assertEqual(1,c['route_index'])
        self.tick(64)
        d = self.tick(85)
        self.assertEqual('retry_cycle',d['route_attempt']['action'])
        self.assertTrue(d['empty_ammo'])

    def test_capture_is_held_and_push_out_reenters_without_old_cycle(self):
        self.tick(0)
        self.state['z'] = 390.
        order = self.tick(1)
        self.assertEqual(0.,order['throttle_override'])
        self.assertIn('capture_area',order)
        self.state['z'] = 350.
        order = self.tick(100)
        self.assertEqual('base_capture',order['combat_mode'])
        self.assertIsNone(order['throttle_override'])
        self.assertEqual(400.,order['move_position']['z'])

    def test_unknown_does_not_trigger_and_round_reset_releases_latch(self):
        self.state.pop('ammo_remaining')
        self.assertNotIn('empty_ammo',self.tick())
        self.state['ammo_remaining'] = [0]
        self.assertTrue(self.tick(2)['empty_ammo'])
        self.state.pop('ammo_remaining')
        self.assertTrue(self.tick(3)['empty_ammo'])
        self.planner.reset(2)
        self.assertNotIn('empty_ammo',self.tick(4))

    def test_unconfigured_ordinary_route_uses_enemy_base_automatic_navigation(self):
        self.manifest[0]['route'] = {}
        self.assertEqual(400.,self.tick()['move_position']['z'])

    def test_timed_and_permanent_waits_are_skipped_without_moving_authored_nodes(self):
        from test_port_0922_authored_route_waits import AuthoredRouteWaitTests
        p, manifest = AuthoredRouteWaitTests().setup_route(seconds=60)
        p._task_graph = lambda:None
        original = copy.deepcopy(p.tactics)
        state = _state(11,1,0,0)
        state['ammo_remaining'] = [0]
        order = p.build_orders(manifest,[state],[],1.)['orders'][0]
        self.assertEqual(1,order['route_index'])
        self.assertIsNone(order['throttle_override'])
        self.assertIsNone(order.get('parking_phase'))
        self.assertEqual(original,p.tactics)

    def test_worker_adapter_keeps_navigation_face_separate_from_aim(self):
        from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
        adapter = BotAdapter('08_ruinberg',1)
        order = self.tick()
        order.update(target_id=9,aim_position={'x':200.,'y':0.,'z':0.},
                     face_position={'x':200.,'y':0.,'z':0.})
        result = adapter.decide_with_order(dict(id=11,slot=0,team=1,position=(0.,0.,100.),
            yaw=0.,speed=0.,dt=.1,neighbours=[],half_width=1.5,half_length=3.5,
            pose_clear=lambda yaw:True),order,lambda *args:True)
        self.assertTrue(result['empty_ammo'])
        self.assertEqual((200.,0.,0.),result['aim_position'])
        self.assertEqual((0.,0.,200.),result['face_position'])
        self.assertTrue(result['movement_intent'])


class EmptyArtilleryTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(id=19,team=1,alive=True,x=0.,y=0.,z=100.,profile={'class_tag':'SPG'})
        self.routes = [dict(id='attack',team=1,purpose='spg_attack',points=[[0,0,0],[0,200,0],[0,400,0]])]
        others = [dict(id=i,team=1,alive=True,profile={'class_tag':'SPG'}) for i in (11,12,13)]
        others.append(dict(id=14,team=1,alive=True,profile={'class_tag':'heavyTank'}))
        self.runtime = SimpleNamespace(_bot_tactics={'maps':{'08_ruinberg':{'routes':self.routes}}},
            _navigation_map_name='08_ruinberg', _ordered_states=lambda:[self.state]+others,
            baked_graph=dict(objective_bases=[[0,0],[0,400]],objective_base_radii=[30,30]))

    def tick(self, now=0):
        return spg_route_travel.apply(self.runtime,self.state,
            dict(empty_ammo=True,combat_mode='base_capture',target_id=9,fire_allowed=False,
                 aim_position=(50,0,100),move_position=(0,0,400)),now)

    def test_empty_fourth_spg_leaves_mixed_team_returns_home_and_reuses_recovery(self):
        self.assertEqual('sortie_return',self.tick()['authored_spg_connection'])
        self.state['z'] = 0.
        self.assertEqual('attack',self.tick(1)['authored_spg_connection'])
        self.state['z'] = 100.
        self.tick(2)
        self.assertEqual('skip',self.tick(23)['authored_spg_recovery']['phase'])
        self.tick(24)
        self.assertEqual('return',self.tick(45)['authored_spg_recovery']['phase'])

    def test_missing_sortie_uses_automatic_enemy_goal(self):
        self.routes[:] = []
        result = self.tick()
        self.assertEqual((0,0.,0),result['move_position'])
        self.assertEqual('sortie_return',result['authored_spg_connection'])
        self.state['z']=0.
        result=self.tick(1)
        self.assertEqual((0,0,400),result['move_position'])
        self.assertNotIn('authored_spg_connection',result)
        self.state['z']=100.
        self.assertEqual((0,0,400),self.tick(2)['move_position'])


if __name__ == '__main__':unittest.main()
