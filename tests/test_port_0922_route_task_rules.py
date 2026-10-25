"""Confirmed task ownership, soft lane capacity and command admission."""
import copy
import unittest
from unittest import mock

from test_port_0922_server_bot_ai import BotPlanner, _bot, _route, _state
import test_port_0922_team_commands as command_fixture
TICK_HZ=command_fixture.TICK_HZ
from gui.mods.offline_lan_0922 import bot_tactics as contract, route_network


class CommandCooldownTests(unittest.TestCase):
    def setUp(self):
        self.fixture = command_fixture.TeamCommandTests();self.fixture.setUp()
        self.server = self.fixture.state

    def send(self, command, sequence):
        return self.server.submit_team_command(1, self.fixture._message(command, sequence=sequence))

    def test_shared_cooldown_refuses_once_and_does_not_queue(self):
        first = self.send('HELPME', 1)
        self.assertEqual([11,12], first['recipient_bot_ids'])
        expiry = first['expires_tick']
        denied = self.send('BACKTOBASE', 2)
        self.assertFalse(denied['accepted']);self.assertEqual('cooldown', denied['code'])
        self.assertEqual([11,12], denied['recipient_bot_ids'])
        self.assertEqual([], self.send('ATTACK', 3)['recipient_bot_ids'])
        self.assertEqual(expiry, self.server._active_team_commands_locked()[0]['expires_tick'])
        self.server.tick += int(10*TICK_HZ)
        self.assertEqual('HELPME', self.server._active_team_commands_locked()[0]['command'])
        accepted = self.send('ATTACK', 4)
        self.assertTrue(accepted['accepted']);self.assertEqual([11,12], accepted['recipient_bot_ids'])
        self.assertEqual(['ATTACK'], [o['command'] for o in self.server._active_team_commands_locked()])

    def test_no_recipient_does_not_consume_cooldown(self):
        self.server.bot_states[11]['alive'] = False;self.server.bot_states[12]['alive'] = False
        self.assertEqual([], self.send('HELPME',1)['recipient_bot_ids'])
        self.server.bot_states[11]['alive'] = True
        self.assertEqual([11], self.send('ATTACK',2)['recipient_bot_ids'])

    def test_retransmit_keeps_the_original_admission(self):
        first = self.send('HELPME',1)
        self.server.tick += 10
        self.assertEqual(first,self.send('HELPME',1))
        self.assertEqual(1,len(self.server.team_commands))

    def test_auto_defender_and_combat_bot_do_not_reply(self):
        self.server.bot_orders={'orders':[dict(id=11,combat_mode='base_defense'),dict(id=12,combat_mode='engage')]}
        self.assertEqual([],self.send('HELPME',1)['recipient_bot_ids'])
        self.assertEqual([],self.send('BACKTOBASE',2)['recipient_bot_ids'])

    def test_guard_has_one_way_arrival_and_continuous_safe_time(self):
        self.send('BACKTOBASE',1)
        context=dict(capture_bases={'1':[dict(id='own',x=0.,y=0.,z=-200.,radius=30.)]},states={'1':dict(invaders=1)},contributors={'1':[]})
        with mock.patch.object(self.server,'_bot_defense_context',return_value=context):
            self.server.tick+=int(80*TICK_HZ)
            self.assertTrue(self.server._active_team_commands_locked())
            for actor in (11,12):self.server.bot_states[actor].update(x=0,z=-200,world_pose=True)
            self.assertTrue(self.server._active_team_commands_locked())
            self.server.tick+=int(20*TICK_HZ)
            self.assertTrue(self.server._active_team_commands_locked())
            context['states']['1']['invaders']=0
            self.assertTrue(self.server._active_team_commands_locked())
            # Leaving the edge cannot restart the expired travel clock.
            for actor in (11,12):self.server.bot_states[actor]['z']=-160
            self.server.tick+=int(29*TICK_HZ)
            self.assertTrue(self.server._active_team_commands_locked())
            context['states']['1']['invaders']=1
            self.assertTrue(self.server._active_team_commands_locked())
            context['states']['1']['invaders']=0
            self.assertTrue(self.server._active_team_commands_locked())
            self.server.tick+=int(30*TICK_HZ)
            self.assertFalse(self.server._active_team_commands_locked())

    def test_guard_travel_expires_without_arrival_and_dead_issuer_ends_guard(self):
        self.send('BACKTOBASE',1)
        self.server.tick+=int(90*TICK_HZ)
        self.assertFalse(self.server._active_team_commands_locked())

    def test_safe_base_uses_canonical_circle_for_arrival_and_thirty_second_release(self):
        self.send('BACKTOBASE',1)
        context=dict(bases={'1':[]},capture_bases={'1':[dict(id='own',x=0.,z=-200.,radius=30.)]},
                     states={'1':dict(invaders=0)},contributors={'1':[]})
        with mock.patch.object(self.server,'_bot_defense_context',return_value=context):
            self.server.tick+=int(80*TICK_HZ)
            for actor in (11,12):self.server.bot_states[actor].update(x=0,z=-200,world_pose=True)
            self.assertTrue(self.server._active_team_commands_locked())
            self.server.tick+=int(29*TICK_HZ)
            self.assertTrue(self.server._active_team_commands_locked())
            self.server.tick+=int(TICK_HZ)
            self.assertFalse(self.server._active_team_commands_locked())
        self.server.tick+=int(10*TICK_HZ);self.send('BACKTOBASE',2)
        self.fixture.sender.alive=False
        self.assertFalse(self.server._active_team_commands_locked())

    def test_rejection_history_remains_bounded(self):
        self.send('HELPME',1)
        for seq in range(2,150):self.send('ATTACK',seq)
        self.assertLessEqual(len(self.fixture.sender.team_command_acks),64)
        self.assertLessEqual(len(self.fixture.sender.team_command_fingerprints),64)


class RouteTaskTests(unittest.TestCase):
    def scene(self):
        p=BotPlanner();route=_route('old',[(0,0,False),(0,100,False),(0,200,False),(0,300,False)])
        manifest=[_bot(11,1,0,route,'mediumTank')]
        state=_state(11,1,0,250);state['world_pose']=True
        bot=p._alive_bots(manifest,[state])[0]
        p._route_states[11]=dict(route_id='old',index=3)
        return p,bot

    def order(self):return dict(combat_mode='route',target_id=None)

    def test_pressure_cannot_commit_before_old_and_new_start(self):
        p,b=self.scene();other=_route('new',[(10,0,False),(50,100,False)])
        task=p._task_begin(b,'pressure',target_route=other,now=0.)
        o=self.order();p._task_publish(o,b,task,0.)
        self.assertEqual((0.,200.),(o['move_position']['x'],o['move_position']['z']))
        for now,z in ((1,200),(2,100),(3,0)):
            b['state'].update(x=0,z=z);p._task_publish(o,b,task,now)
        self.assertNotIn(11,p._route_assignments)
        self.assertEqual('route_transfer',o['combat_mode'])
        b['state'].update(x=10,z=0);p._task_publish(o,b,task,4)
        self.assertEqual('new',p._route_assignments[11]['route']['id'])
        self.assertNotIn(11,p._travel_tasks)

    def test_blocked_root_is_not_skipped_into_new_lane(self):
        p,b=self.scene();other=_route('new',[(10,0,False),(50,100,False)])
        task=p._task_begin(b,'pressure',target_route=other,now=0.)
        o=self.order()
        for now in range(0,161,20):p._task_publish(o,b,task,now)
        self.assertEqual(task['root_index'],task['index'])
        self.assertNotIn(11,p._route_assignments)

    def test_defense_skips_waits_then_uses_direct_base_after_two_failures(self):
        p,b=self.scene();base=dict(base_id='1:0',point=dict(x=-100,y=0,z=0),radius=30)
        task=p._task_begin(b,'defense',base=base,now=0.)
        o=self.order()
        for now in (0,20,40):p._task_publish(o,b,task,now)
        self.assertEqual(base['point'],o['move_position'])
        self.assertEqual('base_defense',o['combat_mode'])

    def test_rejected_default_edit_cannot_attach_its_branch_to_fallback_geometry(self):
        p,b=self.scene();route=p._task_route(b);route['id']='central_streets'
        p.tactics_map='08_ruinberg'
        raw=dict(id='central_streets',team=1,points=[[0,0,0],[50,50,0],[0,300,0]],node_ids=['a','b','c'],
            defense=dict(junction='b',points=[[50,50,0],[-80,80,0],[-100,0,0]]))
        p.tactics={'maps':{'08_ruinberg':dict(default_routes=[raw])}}
        base=dict(base_id='own',point=dict(x=-100,y=0,z=0),radius=30)
        task=p._task_begin(b,'defense',base,now=0.)
        self.assertNotIn(dict(x=-80.,y=0.,z=80.),task['points'])
        self.assertEqual(base['point'],task['points'][-1])

    def test_defense_branch_has_stable_identity_after_insertion(self):
        route=dict(points=[[0,0,0],[0,100,0],[0,200,0]],node_ids=['a','b','c'],
                   defense=dict(junction='b',points=[[0,100,0],[-100,0,0]]))
        route_network.insert_node(route,1,[10,50,0])
        self.assertEqual('b',route['defense']['junction'])
        self.assertEqual(2,route_network.nodes(route).index('b'))
        route_network.delete_node(route,2)
        self.assertNotIn('defense',route)

    def test_clone_rebinds_branch_to_new_nodes(self):
        route=dict(points=[[0,0,0],[0,100,0],[0,200,0]],node_ids=['a','b','c'],
                   defense=dict(junction='b',points=[[0,100,0],[-100,0,0]]))
        cloned=route_network.clone_route(route)
        self.assertNotEqual(route['node_ids'],cloned['node_ids'])
        self.assertEqual(cloned['node_ids'][1],cloned['defense']['junction'])

    def test_wait_and_defense_are_mutually_exclusive(self):
        raw=dict(points=[[0,0,0],[0,100,1,0,[[0,100,60]]],[0,200,0]],node_ids=['a','b','c'],
                 defense=dict(junction='b',points=[[0,100,0],[-100,0,0]]))
        with self.assertRaises(contract.TacticsError):route_network.copy_fields(raw,dict(points=raw['points']),contract,[-1000,-1000,1000,1000])

    def test_pressure_combat_pause_preserves_gate_and_actual_reentry(self):
        p,b=self.scene();other=_route('new',[(10,0,False),(50,100,False)])
        task=p._task_begin(b,'pressure',target_route=other,now=0.)
        order=dict(combat_mode='engage',target_id=3)
        p._task_apply(order,b,10.)
        self.assertEqual('engage',order['combat_mode']);self.assertEqual(0,task['index'])
        b['state'].update(x=30,z=220)
        order=self.order();p._task_apply(order,b,50.)
        self.assertEqual(220.,order['route_anchor']['z'])
        self.assertEqual(180.,task['until']);self.assertEqual(0,task['index'])

    def test_pressure_expiry_returns_to_last_passed_old_node(self):
        p,b=self.scene();other=_route('new',[(10,0,False),(50,100,False)])
        task=p._task_begin(b,'pressure',target_route=other,now=0.)
        b['state']['z']=200;p._task_publish(self.order(),b,task,1.)
        b['state']['z']=160;order=self.order();p._task_publish(order,b,task,180.)
        self.assertNotIn(11,p._travel_tasks);self.assertEqual('old',order['route_id'])
        self.assertEqual(200.,order['move_position']['z'])

    def test_combat_cancels_player_without_changing_combat_movement(self):
        p,b=self.scene();request=dict(command_id='one',command='STOP')
        order=dict(self.order(),move_position=dict(x=0,y=0,z=250))
        p._task_apply(order,b,0.,player_order=request)
        combat=dict(combat_mode='engage',target_id=3,move_position=dict(x=20,y=0,z=230))
        before=copy.deepcopy(combat);p._task_apply(combat,b,1.)
        self.assertEqual(before,combat);self.assertNotIn(11,p._previous_player)

    def test_turnback_has_one_frozen_goal_and_then_ends(self):
        p,b=self.scene();request=dict(command_id='one',command='TURNBACK')
        order=dict(self.order(),move_position=dict(x=0,y=0,z=100))
        p._task_apply(order,b,0.,player_order=request)
        changed=dict(self.order(),move_position=dict(x=0,y=0,z=0))
        p._task_apply(changed,b,1.,player_order=request)
        self.assertEqual(100,changed['move_position']['z'])
        b['state']['z']=100;p._task_apply(changed,b,2.,player_order=request)
        self.assertTrue(changed['player_command_cancelled']);self.assertEqual('route',changed['combat_mode'])

    def test_authored_terminal_uses_enemy_circle_and_spawn_skips_first_node(self):
        p,b=self.scene();route=p._task_route(b);route['id']='user_lane'
        raw=dict(id='lane',team=1,classes=['mediumTank'],slots=[],policy='preferred',points=[[0,0,0],[0,100,0],[0,200,0],[0,300,0]])
        p.tactics={'maps':{'08_ruinberg':dict(routes=[raw])}};p.tactics_map='08_ruinberg'
        p._route_states.clear();b['state']['z']=0
        identity,index,unused,unused2,unused3=p._route(b,0.)
        self.assertEqual(1,index)
        p._route_states[11]['index']=3
        target=dict(id='enemy',point=dict(x=10,y=0,z=350),radius=50)
        order=dict(self.order(),move_position=dict(x=0,y=0,z=300))
        p._task_capture_handoff(order,b,target)
        self.assertEqual('base_capture',order['combat_mode']);self.assertEqual(target['point'],order['move_position'])

    def test_pressure_aggregates_class_variants_as_one_road(self):
        p,b=self.scene()
        configs=[dict(id='one_lt',family='one',team=1,classes=['lightTank'],slots=[],policy='preferred',points=[[0,0,0],[0,100,0]]),
                 dict(id='one_ht',family='one',team=1,classes=['heavyTank'],slots=[],policy='preferred',points=[[0,0,0],[0,100,0]])]
        p.tactics={'maps':{'08_ruinberg':dict(routes=configs)}};p.tactics_map='08_ruinberg'
        left=_route('user_one_lt',[(0,0,False),(0,100,False)])
        heavy=_route('user_one_ht',[(0,0,False),(0,100,False)])
        right=_route('other',[(200,0,False),(200,100,False)])
        manifest=[_bot(11,1,0,left,'lightTank'),_bot(12,1,1,heavy,'heavyTank'),_bot(13,1,2,right,'mediumTank')]
        bots=p._alive_bots(manifest,[_state(11,1,0,0),_state(12,1,0,0),_state(13,1,200,0)])
        p._rebalance_routes(1,bots,[dict(position=dict(x=200,y=0,z=100),health=100,max_health=100)],0.)
        counts=p._route_balance_receipts[1]['contributors']
        self.assertEqual(2,counts['user_one_lt']);self.assertEqual(2,counts['user_one_ht'])
        destination=p._task_class_route(left,bots[1],{r['id']:r for r in (left,heavy,right)})
        self.assertEqual('user_one_ht',destination['id'])

    def test_directed_join_ignores_unreachable_nearest_node(self):
        class Graph:
            width=3;height=1;directions=[(1,0)];links=[1,1,0]
            def closest(self,p):return int(round(p[0]))
            def point(self,c):return (c,0,0)
            def usable(self,c):return True
        # Node zero is closer in the plane but cannot be reached backwards.
        self.assertEqual(1,route_network.reachable_join(Graph(),(1,0,0),[[0,0,0],[2,0,0]]))


class AuthoredArtilleryTravelTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from gui.mods.offline_lan_0922 import spg_route_travel
        self.travel=spg_route_travel
        self.zone=dict(id='a',team=1,point=[0,100],radius=16,travel=[[0,0,0],[30,50,0],[0,100,0]])
        self.peer=dict(id='b',team=1,point=[100,100],radius=16,travel=[[0,0,0],[100,0,0],[100,100,0]])
        self.settings=dict(positions=[self.zone,self.peer],routes=[])
        self.state=dict(id=11,team=1,x=0.,y=0.,z=0.,profile={'class_tag':'SPG'},_spg_initial={'zone':'a'},alive=True)
        self.regular=dict(id=12,team=1,profile={'class_tag':'heavyTank'},alive=True)
        self.states=[self.state,self.regular]
        self.runtime=SimpleNamespace(_bot_tactics={'maps':{'08_ruinberg':self.settings}},_navigation_map_name='08_ruinberg',
            _ordered_states=lambda:self.states,baked_graph=dict(objective_bases=[[0,0],[0,300]],objective_base_radii=[30,30]))
        self.join=mock.patch.object(self.travel,'_join',return_value=0).start();self.addCleanup(mock.patch.stopall)

    def apply(self,mode='artillery_deploy',**extra):
        order=dict(combat_mode=mode,target_id=None,move_position=(0,0,100),fire_allowed=False)
        order.update(extra)
        return self.travel.apply(self.runtime,self.state,order,1.)

    def test_deploy_keeps_authored_detour_and_fire_fields(self):
        result=self.apply(target_id=9,fire_allowed=True)
        self.assertEqual((30,0.,50),result['move_position'])
        self.assertEqual(9,result['target_id']);self.assertTrue(result['fire_allowed'])
        self.state.update(x=30,z=50)
        self.assertEqual((0,0.,100),self.apply()['move_position'])

    def test_parking_region_hands_off_to_actual_off_center_native_goal(self):
        self.apply();self.state.update(x=30,z=50);self.apply()
        self.state.update(x=0,z=90)
        native=(10,0,100)
        result=self.apply(move_position=native)
        self.assertEqual(native,result['move_position']);self.assertNotIn('authored_spg_connection',result)
        self.state.update(x=10,z=100)
        result=self.apply(move_position=native)
        self.assertEqual(native,result['move_position']);self.assertNotIn('authored_spg_connection',result)

    def test_arrived_parking_does_not_copy_static_network_every_control_frame(self):
        self.state.update(x=0,z=100);self.apply('artillery_hold')
        original=self.travel.copy.deepcopy
        with mock.patch.object(self.travel.copy,'deepcopy',wraps=original) as copies:
            for unused in range(30):self.apply('artillery_hold')
        self.assertEqual(0,copies.call_count)

    def test_restored_arrived_parking_does_not_deploy_from_base_again(self):
        self.state.update(x=5,z=100)
        result=self.apply('artillery_hold',move_position=(5,0,100),throttle_override=0.)
        self.assertEqual('artillery_hold',result['combat_mode'])
        self.assertEqual(0.,result['throttle_override'])

    def test_relocation_uses_authored_parking_link(self):
        self.apply();self.state.update(x=0,z=100)
        self.zone['links']={'b':[[0,100,0],[50,150,0],[100,100,0]]}
        self.state['_authored_spg_zone']=copy.deepcopy(self.zone)
        self.state['_spg_initial']['zone']='b'
        result=self.apply('artillery_relocate')
        self.assertEqual((50,0.,150),result['move_position'])

    def test_missing_link_uses_automatic_goal_not_invented_trip_via_base(self):
        self.state.update(x=0,z=100)
        self.state['_authored_spg_zone']=copy.deepcopy(self.zone)
        self.state['_spg_initial']['zone']='b'
        result=self.apply('artillery_relocate',move_position=(100,0,100))
        self.assertEqual((100,0,100),result['move_position'])
        self.assertNotIn('authored_spg_connection',result)
        self.state.update(x=100,z=100);self.apply('artillery_hold')
        self.assertEqual('b',self.state['_authored_spg_zone']['id'])

    def test_present_relocation_link_does_not_require_destination_deployment(self):
        self.peer.pop('travel')
        self.zone['links']={'b':[[0,100,0],[50,150,0],[100,100,0]]}
        self.state.update(x=0,z=100)
        self.state['_authored_spg_zone']=copy.deepcopy(self.zone)
        self.state['_spg_initial']['zone']='b'
        self.assertEqual((50,0.,150),self.apply('artillery_relocate')['move_position'])

    def test_missing_deployment_keeps_native_goal_and_drops_stale_connection(self):
        self.apply()
        self.zone.pop('travel')
        result=self.apply(move_position=(5,0,105))
        self.assertEqual((5,0,105),result['move_position'])
        self.assertNotIn('authored_spg_connection',result)
        self.assertNotIn('_authored_spg_travel',self.state)

    def test_missing_sortie_does_not_resume_cached_deployment(self):
        self.apply();self.regular['alive']=False
        result=self.apply('base_capture',move_position=(0,0,300))
        self.assertEqual((0,0,300),result['move_position'])
        self.assertEqual('base_capture',result['combat_mode'])
        self.assertNotIn('_authored_spg_travel',self.state)

    def test_missing_defense_connection_keeps_automatic_base_destination(self):
        self.zone.pop('travel')
        result=self.apply('base_defense',move_position=(0,0,0))
        self.assertEqual((0,0,0),result['move_position'])
        self.assertNotIn('authored_spg_connection',result)

    def test_missing_attack_route_keeps_present_deployment_for_regular_team(self):
        self.assertEqual((30,0.,50),self.apply()['move_position'])

    def test_unproved_join_retains_existing_connection_and_retries(self):
        self.join.return_value=None
        self.state.update(x=90,z=100)
        result=self.apply('base_defense',move_position=(0,0,-300))
        self.assertEqual('defense',result['authored_spg_connection'])
        self.assertEqual((0,0.,100),result['move_position'])
        self.assertNotEqual((0,0,-300),result['move_position'])
        for now in (2.,100.,300.):
            result=self.travel.apply(self.runtime,self.state,
                dict(combat_mode='base_defense',move_position=(0,0,-300)),now)
            self.assertEqual('defense',result['authored_spg_connection'])
            self.assertIsNone(result['throttle_override'])

    def test_defense_preserves_actual_parking_and_resumes_deployment(self):
        self.apply();self.state.update(x=30,z=50);self.apply();self.state.update(x=0,z=100)
        result=self.apply('base_defense')
        self.assertEqual((30,0.,50),result['move_position'])
        self.assertEqual('a',self.state['_authored_spg_return_zone']['id'])
        self.state.update(x=0,z=0);self.apply('base_defense')
        resumed=self.apply()
        self.assertEqual('deploy',self.state['_authored_spg_travel']['kind'])
        self.assertEqual((30,0.,50),resumed['move_position'])

    def test_defense_during_relocation_returns_to_last_arrived_parking(self):
        self.apply();self.state.update(x=30,z=50);self.apply();self.state.update(x=0,z=100);self.apply()
        self.assertEqual('a',self.state['_authored_spg_zone']['id'])
        self.state['_spg_initial']['zone']='b';self.apply('artillery_relocate')
        self.assertEqual('a',self.state['_authored_spg_zone']['id'])
        self.apply('base_defense');self.state.update(x=0,z=0)
        self.apply('artillery_hold')
        self.assertEqual('a',self.state['_spg_initial']['zone'])
        self.assertEqual(('deploy','a'),self.state['_authored_spg_travel']['identity'])

    def test_sortie_returns_home_before_starting_authored_attack_and_holds_circle(self):
        self.apply();self.state.update(x=30,z=50);self.apply();self.state.update(x=0,z=100);self.regular['alive']=False
        self.settings['routes']=[dict(id='attack',team=1,purpose='spg_attack',points=[[0,0,0],[100,200,0],[0,300,0]])]
        self.assertEqual('sortie_return',self.apply()['authored_spg_connection'])
        self.state.update(x=30,z=50);self.apply()
        self.state.update(x=0,z=0);self.apply()
        self.assertEqual('attack',self.state['_authored_spg_travel']['kind'])
        self.state.update(x=100,z=200);self.apply()
        self.state.update(x=0,z=280)
        self.assertEqual('base_capture',self.apply()['combat_mode'])

    def test_sortie_defense_reverses_its_own_attack_nodes(self):
        self.regular['alive']=False
        self.settings['routes']=[dict(id='attack',team=1,purpose='spg_attack',points=[[0,0,0],[100,200,0],[0,300,0]])]
        self.state['_authored_spg_attack']=copy.deepcopy(self.settings['routes'][0])
        self.state['_authored_spg_travel']=dict(kind='attack',identity=('attack','attack'),points=self.settings['routes'][0]['points'],index=2)
        self.state.update(x=100,z=220)
        self.apply('base_defense')
        self.assertEqual([[100,200,0],[0,0,0]],self.state['_authored_spg_travel']['points'])
        self.apply('artillery_hold')
        self.assertEqual('attack',self.state['_authored_spg_travel']['kind'])

    def test_live_non_artillery_player_prevents_premature_sortie(self):
        self.regular['alive']=False
        self.settings['routes']=[dict(id='attack',team=1,purpose='spg_attack',points=[[0,0,0],[0,300,0]])]
        human=dict(team=1,alive=True,class_tag='heavyTank')
        self.runtime._contact_players=[human]
        self.assertNotIn('_authored_spg_attack',self.state)
        self.apply();self.assertNotIn('_authored_spg_attack',self.state)
        human['alive']=False;self.apply()
        self.assertIn('_authored_spg_attack',self.state)

    def test_combat_keeps_existing_order_and_non_artillery_unchanged(self):
        self.apply();self.state.update(x=30,z=50)
        result=self.apply('engage',target_id=9,fire_allowed=True)
        self.assertEqual('engage',result['combat_mode'])
        self.assertNotIn('authored_spg_connection',result)
        self.state['profile']['class_tag']='heavyTank'
        self.assertNotIn('authored_spg_connection',self.apply())


if __name__=='__main__':unittest.main()
