"""Artillery reservations, persistent sortie ownership and shared road entries."""
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import spg_modes, spg_route_travel as travel, spg_route_recovery as recovery


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.states=[dict(id=i,team=1,alive=True,x=0.,y=0.,z=100.,vehicle='test',
                         profile={'class_tag':'SPG'},ammo_remaining=[10,0]) for i in range(1,7)]
        for s in self.states[:3]:s['_spg_initial']=dict(zone=str(s['id']),vehicle='test',point=dict(x=0,y=0,z=100),radius=2)
        self.regular=dict(id=99,team=1,alive=True,profile={'class_tag':'heavyTank'})
        self.states.append(self.regular)
        self.settings=dict(routes=[dict(id='spg',team=1,purpose='spg_attack',points=[[0,0,0],[0,100,0],[0,300,0]])])
        self.runtime=SimpleNamespace(round_id=1,_ordered_states=lambda:self.states,_bot_tactics={'maps':{'08_ruinberg':self.settings}},
            _navigation_map_name='08_ruinberg',baked_graph=dict(objective_bases=[[0,0],[0,300]],objective_base_radii=[30,30]))
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(recovery.bot_tactics_runtime,'graph_view',return_value=object()).start()
        mock.patch.object(recovery.bot_tactics_runtime,'validate_route',return_value=None).start()

    def test_deployment_reserves_one_per_position_and_caps_three(self):
        self.states[3]['_spg_initial']=copy.deepcopy(self.states[0]['_spg_initial'])
        self.states[4]['_spg_initial']=dict(zone='four',point=dict(x=20,y=0,z=100))
        spg_modes.update(self.runtime,0)
        self.assertEqual(3,sum(bool(s.get('_spg_initial')) for s in self.states))
        self.assertEqual(3,len(self.runtime._spg_mode_slots))
        self.assertEqual('automatic',self.states[3]['_spg_deployment'])

    def test_pre_battle_none_round_initializes_without_requiring_any_bots(self):
        self.runtime.round_id=None;self.states[:]=[]
        spg_modes.update(self.runtime,0)
        self.assertEqual({},self.runtime._spg_mode_slots)
        self.assertEqual(set(),self.runtime._spg_endgame_teams)

    def test_dead_parking_owner_has_one_replacement_and_no_duplicate_reservation(self):
        spg_modes.update(self.runtime,0);self.states[0]['alive']=False
        spg_modes.update(self.runtime,1)
        owner=self.runtime._spg_mode_slots[(1,'1')]['owner']
        self.assertIn(owner,(4,5,6))
        for t in range(2,15):spg_modes.update(self.runtime,t)
        self.assertEqual(owner,self.runtime._spg_mode_slots[(1,'1')]['owner'])
        self.assertEqual(1,sum(s.get('_spg_initial',{}).get('zone')=='1' for s in self.states if s['alive']))

    def test_parking_retries_cannot_claim_other_owners_or_closed_regions(self):
        spg_modes.update(self.runtime,0)
        self.runtime._spg_mode_slots[(1,'closed')]=dict(owner=None,disabled=True,plan={})
        self.assertEqual(['2','3','closed'],spg_modes.parking_exclusions(self.runtime,self.states[0]))

    def test_failed_replacement_closes_only_that_slot_until_new_round(self):
        spg_modes.update(self.runtime,0);self.states[0]['alive']=False;spg_modes.update(self.runtime,1)
        slot=self.runtime._spg_mode_slots[(1,'1')];replacement=next(s for s in self.states if s['id']==slot['owner'])
        spg_modes.release_parking(self.runtime,replacement,failed=True);spg_modes.update(self.runtime,2)
        self.assertTrue(slot['disabled']);self.assertIsNone(slot['owner'])
        self.assertEqual('automatic',replacement['_spg_deployment'])
        self.assertFalse(self.runtime._spg_mode_slots[(1,'2')]['disabled'])
        self.runtime.round_id=2;spg_modes.update(self.runtime,3)
        self.assertFalse(any(s['disabled'] for s in self.runtime._spg_mode_slots.values()))

    def test_sortie_prefers_free_vehicles_and_never_replaces_combat_or_recovery(self):
        spg_modes.update(self.runtime,0);self.regular['alive']=False
        self.runtime._contact_players=[dict(team=1,alive=True,class_tag='heavyTank')]
        spg_modes.update(self.runtime,1)
        selected=[s for s in self.states if s.get('_spg_mode')=='sortie']
        self.assertEqual({4,5,6},{s['id'] for s in selected})
        selected[0]['_authored_spg_travel']=dict(kind='attack',recovery_phase='return')
        for t in range(2,8):spg_modes.update(self.runtime,t)
        self.assertEqual({4,5,6},{s['id'] for s in self.states if s.get('_spg_mode')=='sortie'})
        selected[0]['alive']=False;spg_modes.update(self.runtime,9)
        self.assertEqual(3,sum(s.get('_spg_mode')=='sortie' and s['alive'] for s in self.states))
        self.assertTrue(all(s.get('_spg_deployment')=='waiting' for s in self.states[:3] if s['_spg_mode']=='deployment'))

    def test_empty_sortie_frees_normal_slot_and_keeps_unlimited_empty_travel(self):
        self.regular['alive']=False;spg_modes.update(self.runtime,0)
        selected=next(s for s in self.states if s.get('_spg_mode')=='sortie')
        selected['ammo_remaining']=[0,0];spg_modes.update(self.runtime,1)
        self.assertEqual('empty',selected['_spg_mode'])
        self.assertEqual(3,sum(s.get('_spg_mode')=='sortie' for s in self.states))
        for s in self.states[:6]:s['ammo_remaining']=[0,0]
        spg_modes.update(self.runtime,2)
        self.assertEqual(6,sum(s.get('_spg_mode')=='empty' for s in self.states))

    def test_fire_opportunity_holds_actual_position_without_redeploying(self):
        self.regular['alive']=False;state=self.states[3]
        order=dict(combat_mode='artillery_deploy',target_id=None,fire_allowed=False,move_position=(0,0,100))
        result=travel.apply(self.runtime,state,order,0)
        self.assertEqual('sortie_return',result['authored_spg_connection'])
        active=state['_authored_spg_travel']
        result=travel.apply(self.runtime,state,dict(order,target_id=44,fire_allowed=True,aim_position=(50,0,100)),1)
        self.assertEqual('engage',result['combat_mode']);self.assertEqual((0.,0.,100.),result['move_position'])
        self.assertEqual('sortie',result['spg_mode']);self.assertIs(active,state['_authored_spg_travel'])
        state['z']=0.;result=travel.apply(self.runtime,state,order,2)
        self.assertEqual('attack',result['authored_spg_connection']);self.assertEqual('sortie',state['_spg_mode'])

    def test_missing_artillery_route_uses_an_ordinary_reserve_before_automatic(self):
        self.regular['alive']=False;self.settings['routes']=[]
        row=dict(id='reserve',waypoints=[[50,0,0],[50,100,0],[0,300,0]],_route_tier='reserve')
        with mock.patch.object(recovery,'_catalog',return_value=[row]):
            result=travel.apply(self.runtime,self.states[3],dict(combat_mode='artillery_deploy'),0)
        self.assertEqual('sortie_return',result['authored_spg_connection'])
        self.assertEqual('reserve',self.states[3]['_authored_spg_attack']['id'])

    def test_three_artillery_lane_claims_send_fourth_empty_to_least_used_reserve(self):
        for s in self.states[:6]:s['ammo_remaining']=[0,0]
        row=dict(id='reserve',waypoints=[[0,0,0],[100,100,0],[0,300,0]],_route_tier='reserve')
        with mock.patch.object(recovery,'_catalog',return_value=[row]):
            for s in self.states[:4]:travel.apply(self.runtime,s,dict(empty_ammo=True,combat_mode='base_capture'),0)
        self.assertEqual(['spg']*3,[s['_authored_spg_attack']['id'] for s in self.states[:3]])
        self.assertEqual('reserve',self.states[3]['_authored_spg_attack']['id'])

    def test_reverse_defense_connector_joins_stable_node_then_attacks_forward(self):
        row=dict(id='road',waypoints=[[100,0,0],[100,100,0],[100,200,0],[0,300,0]])
        source=dict(points=[list(p) for p in row['waypoints']],node_ids=['a','b','c','d'],
            defense=dict(junction='c',points=[[100,200,0],[50,100,0],[0,0,0]]))
        with mock.patch.object(recovery.bot_tactics,'route_config',return_value=source):
            self.assertEqual([[0,0,0],[50,100,0],[100,200,0],[0,300,0]],recovery._road(self.runtime,self.states[0],row))

    def test_borrowed_road_visits_its_first_node_when_base_is_elsewhere(self):
        self.regular['alive']=False;self.settings['routes']=[]
        state=self.states[3];state['z']=0.
        row=dict(id='offset',waypoints=[[100,0,0],[100,100,0],[0,300,0]])
        with mock.patch.object(recovery,'_catalog',return_value=[row]):
            order=travel.apply(self.runtime,state,dict(combat_mode='artillery_deploy'),0)
        self.assertEqual((100.,0.,0.),order['move_position'])
        self.assertEqual(0,state['_authored_spg_travel']['index'])

    def test_defense_resumes_sortie_without_reinstalling_old_parking(self):
        mock.patch.object(travel,'_join',return_value=0).start()
        self.regular['alive']=False;state=self.states[3]
        incoming=dict(combat_mode='artillery_deploy')
        travel.apply(self.runtime,state,incoming,0)
        state['_authored_spg_return_initial']=dict(zone='old',point=dict(x=500,y=0,z=500))
        travel.apply(self.runtime,state,dict(combat_mode='base_defense',defense_base_id=1),1)
        # Simulate the stale parking record retained by the former implementation.
        state['_authored_spg_return_initial']=dict(zone='old',point=dict(x=500,y=0,z=500))
        result=travel.apply(self.runtime,state,incoming,2)
        self.assertEqual('sortie',state['_spg_mode'])
        self.assertEqual('sortie_return',result['authored_spg_connection'])
        self.assertNotIn('_spg_initial',state)

    def test_round_change_clears_sortie_progress_and_decision_cache(self):
        spg_modes.update(self.runtime,0)
        state=self.states[0]
        state['_authored_spg_travel']=dict(kind='attack',index=4)
        state['_spg_automatic_attack']=True
        self.runtime._decision_cache={state['id']:dict(combat_mode='old')}
        self.runtime.round_id=2;spg_modes.update(self.runtime,1)
        self.assertNotIn('_authored_spg_travel',state)
        self.assertNotIn('_spg_automatic_attack',state)
        self.assertNotIn(state['id'],self.runtime._decision_cache)


if __name__=='__main__':unittest.main()
