"""Windows319 failures at partial tips, repeated exits and adjacent roofs."""
import unittest
import types
from unittest import mock

from test_port_0922_navigation import TerrainNavigator
from gui.mods.offline_lan_0922 import vehicle_stack
from gui.mods.offline_lan_0922 import tank_collision
import test_port_0922_battle_runtime as battle_fixture


class IncompleteEndpointTests(unittest.TestCase):
    def scene(self):
        nav = TerrainNavigator(lambda *args: -14.73, lambda *args: False)
        nav.grid.segment_clear = lambda *args: True
        nav.grid.segment_penalty = lambda *args: 0.
        return nav

    def test_report_bot10_same_partial_tip_is_blocked_not_arrived(self):
        nav = self.scene()
        current = (-10.28, -14.73, 18.20)
        endpoint = (-10., -14.681, 18.)
        goal = (0., 0., 18.)
        nav._path = lambda key, *args: (key, (endpoint,))
        for now in (1., 1.5):
            target = nav.next_target(10,current,goal,('route',10),now)
            self.assertEqual(goal,target)
            self.assertEqual('blocked',nav.bot_states[10]['navigation_status'])
            self.assertFalse(nav.target_is_terminal(10))
        self.assertEqual(2,nav.bot_states[10]['local_retry_progress']['failures'])
        self.assertEqual('no_onward_leg',nav.bot_states[10]['path_endpoint_refusal']['reason'])

    def test_nearby_incomplete_tip_is_not_an_arrival_either(self):
        nav = self.scene()
        current = (-2.,-14.,18.)
        goal = (0.,0.,18.)
        nav._path = lambda key,*args:(key,(current,))
        self.assertEqual(goal,nav.next_target(10,current,goal,('route',10),1.))
        self.assertEqual('incomplete_endpoint',nav.bot_states[10]['path_endpoint_refusal']['reason'])
        self.assertFalse(nav.target_is_terminal(10))

    def test_actual_arrival_keeps_terminal_output(self):
        nav = self.scene()
        goal = (0.,0.,18.)
        nav._path = lambda key,*args:(key,(goal,))
        nav.next_target(10,goal,goal,('route',10),1.)
        self.assertTrue(nav.target_is_terminal(10))
        self.assertNotIn('path_endpoint_refusal',nav.bot_states[10])

    def test_report_bot28_repeated_tip_without_search_keeps_bounded_retry(self):
        nav = self.scene()
        current = (-30.4237,1.2487,-168.3943)
        candidate = (-28.34897,.616,-168.2463)
        goal = (0.,0.,-18.)
        state = dict(request_key=(('local',28),(0,0)),temporary_stalled=True,
                     temporary_visited_cells={nav.grid.cell_for(candidate)})
        nav.bot_states[28] = state
        with mock.patch.object(nav.grid,'safe_local_target',return_value=candidate):
            target = nav._pending_target(28,current,goal,50.,state,allow_last_target=False,
                                         immediate_safe_local=True)
        self.assertEqual(current,target)
        self.assertEqual('pending',state['navigation_status'])
        self.assertEqual(1,state['local_retry_progress']['failures'])
        self.assertEqual('temporary_path_repeats',state['local_selection']['outcome'])
        nav._record_local_retry_refusal(state,current,goal,50.5)
        self.assertFalse(nav._local_retry_stalled(state,current,goal,50.5,True))
        self.assertTrue(nav._local_retry_stalled(state,current,goal,63.,True))

    def test_real_pending_search_still_waits_for_its_own_proof(self):
        nav = self.scene()
        current,goal=(0.,0.,0.),(30.,0.,0.)
        key=('search',)
        state=dict(path_key=key,pending_since=0.)
        nav.searches[key]=mock.Mock(done=False,progress={})
        with mock.patch.object(nav,'_pending_search_target',return_value=None), \
                mock.patch.object(nav,'_safe_fallback_target',return_value=None):
            self.assertEqual(current,nav._pending_target(1,current,goal,5.,state))
        self.assertEqual('pending',state['navigation_status'])


class RoofPairTests(unittest.TestCase):
    def test_first_landing_contact_does_not_reenable_secondary_roof_push(self):
        runtime=battle_fixture._runtime()
        battle=battle_fixture.BattleRuntime(runtime)
        battle.client=types.SimpleNamespace(player_id=1)
        battle._collision_shape=lambda desc:(1.5,3.,0.,2.)
        battle._local_pitch=battle._local_roll=0.
        battle._local_vertical_speed=-17.2662
        battle._local_airborne=False
        entity=types.SimpleNamespace(typeDescriptor=object())
        candidates=[(('bot',number),dict(y=0.),entity) for number in (9,12,13)]
        def context(actor):
            previous=getattr(battle,'_stack_context',None)
            battle._stack_context=dict(actor=actor,candidates=candidates,hits=[])
            return previous
        battle._stack_support_context=context
        def hit(start,end,unused):
            key,state,unused_entity=battle._stack_context['candidates'][0]
            if key[1]!=13:
                battle._stack_context['hits'].append((key,state,(start.x,start.y-.03,start.z)))
        battle._stack_ground_hit=hit
        peers=[dict(kind='bot',network_id=n) for n in (9,12,13)]
        self.assertEqual({('bot',9),('bot',12)},
            battle._falling_roof_approaches(entity,(0.,2.,0.),0.,peers))
        # A previous contact only permits a fresh query; it cannot suppress a side hit.
        battle._local_vertical_speed=.1
        battle._local_roof_contact_pairs=[('bot',9)]
        battle._stack_ground_hit=lambda *args:None
        self.assertEqual(set(),battle._falling_roof_approaches(entity,(0.,2.,0.),0.,peers))

    def test_secondary_native_roof_is_not_a_planar_push_or_ram(self):
        upper=dict(id=1,kind='player',network_id=1,x=0.,y=1.,z=0.,yaw=0.,
            mass=36000.,vx=0.,vz=0.,shape=(1.5,3.,0.,2.),alive=True,
            stack_carrier=['bot',9],roof_contact_pairs=[('bot',9),('bot',12)])
        first=dict(upper,id=9,kind='bot',network_id=9,y=0.,stack_carrier=None,roof_contact_pairs=())
        second=dict(first,id=12,network_id=12,x=.5)
        solved=tank_collision.resolve_pairs([upper,first,second],.1,anchor=1)
        self.assertEqual((0.,0.),solved[1]['correction'])
        self.assertFalse(tank_collision.resolve_tank(upper,[first,second],now=1.,dt=.1)['ram_events'])
        self.assertEqual(1.,tank_collision.translation_fraction(upper,(0.,1.),[first,second]))
        # A neighbouring side contact still reaches the physical resolver.
        wall=dict(second,id=13,network_id=13)
        self.assertTrue(vehicle_stack.planar_pair(upper,wall))
        self.assertNotEqual((0.,0.),tank_collision.resolve_pairs([upper,wall],.1,anchor=1)[1]['correction'])

    def test_both_fresh_roofs_survive_single_primary_carrier(self):
        params=dict(springs=(dict(x=-1.,y=0.,z=0.,static_compression=.1),
                             dict(x=1.,y=0.,z=0.,static_compression=.1)),pseudo_contacts=())
        solved=dict(height=.11447,pitch=0.,roll=0.)
        hits=[(('bot',9),{},(-1.,0.,0.)),(('bot',12),{},(1.,0.,0.))]
        self.assertEqual([('bot',9),('bot',12)],vehicle_stack.roof_contact_pairs(
            params,[0.,0.],[],solved,(0.,.11447,0.),0.,0.,0.,hits))
        self.assertIsNone(vehicle_stack.settled_carrier(params,[0.,0.],[],solved,
            (0.,.11447,0.),0.,0.,0.,hits))
        # A detached hull, stale sample, missing support or wrong XZ is not a roof pair.
        self.assertEqual([],vehicle_stack.roof_contact_pairs(params,[0.,0.],[],
            dict(height=.3,pitch=0.,roll=0.),(0.,.3,0.),0.,0.,0.,hits))
        self.assertEqual([],vehicle_stack.roof_contact_pairs(params,[None,None],[],
            solved,(0.,.11447,0.),0.,0.,0.,hits))


if __name__ == '__main__':
    unittest.main()
