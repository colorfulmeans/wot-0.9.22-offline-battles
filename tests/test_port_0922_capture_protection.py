"""Report ebb19501b480: contact pursuit must not abandon 69 capture points."""
import copy
import unittest

from gui.mods.offline_lan_0922 import capture_orders
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from test_port_0922_server_bot_ai import BotPlanner, _bot, _state, _route, _bot_contact


class CaptureProtectionTests(unittest.TestCase):
    def scene(self, count=2):
        planner=BotPlanner()
        route=_route('lane',[(198.,-350.,False),(144.845,285.836,False),(198.,354.,False)])
        bots=[_bot(22+i,2,i,route,'mediumTank') for i in range(count)]
        for b in bots:b['profile']['desired_range']=250.
        states=[_state(b['id'],2,172.+i,316.+i) for i,b in enumerate(bots)]
        bots.append(_bot(1,1,0,_route('enemy',[(0.,0.,False)]),'heavyTank'))
        states.append(_state(1,1,-282.287,405.115))
        defense=dict(capture_bases={'1':[dict(id='1:0',x=195.851,z=352.782,radius=50.)]})
        return planner,bots,states,defense

    def orders(self, scene, now=1., shootable=False):
        p,bots,states,defense=scene
        contact=_bot_contact(1,states[-1]['x'],states[-1]['z'],
                             [s['id'] for s in states[:-1]] if shootable else [])
        contact.update(observing_team=2,target_team=1)
        p.report_contacts([contact],p.known_targets(states,[]),now)
        return [o for o in p.build_orders(bots,states,[],now,defense)['orders'] if o['team']==2]

    def test_reported_two_capturers_keep_aim_without_chasing_outside(self):
        scene=self.scene();self.orders(scene,0.,shootable=True)
        for now in (1.,3.,8.,12.,30.):
            for order in self.orders(scene,now):
                if now==1.:self.assertEqual(('bot',1),(order['target_kind'],order['target_id']))
                self.assertFalse(order['fire_allowed'])
                self.assertEqual(0.,order['throttle_override'])
                self.assertTrue(capture_orders.inside(order['move_position'],order['capture_area']))
                self.assertNotEqual(order['aim_position'],order['move_position'])

    def test_more_than_three_arrivals_keep_capture_even_with_three_humans(self):
        scene=self.scene(6)
        scene[3]['contributors']={'1':[dict(kind='human',id=i,points=0) for i in (91,92,93)]}
        orders=self.orders(scene)
        self.assertEqual(6,len(orders))
        self.assertTrue(all('capture_area' in o and o['throttle_override']==0. for o in orders))
        self.assertFalse(hasattr(scene[0],'_base_capture'))

    def test_shot_permission_is_unchanged_and_reload_does_not_authorize_pursuit(self):
        scene=self.scene()
        for s in scene[2][:-1]:s.update(clip=0,clip_size=4,reload_time=20.)
        for order in self.orders(scene,shootable=True):
            self.assertFalse(order['fire_allowed'])
            self.assertEqual(0.,order['throttle_override'])

    def test_shoved_outside_reenters_actual_circle_instead_of_chasing_contact(self):
        scene=self.scene(1);self.orders(scene)
        scene[2][0].update(x=140.3506,z=318.0734)
        order=self.orders(scene,3.,shootable=True)[0]
        self.assertEqual('base_capture',order['combat_mode'])
        self.assertEqual(dict(x=195.851,y=0.,z=352.782),order['move_position'])
        self.assertIsNone(order['throttle_override'])
        self.assertEqual(1,order['target_id'])

    def test_death_and_round_reset_clear_capture_arrival(self):
        scene=self.scene(1);self.orders(scene)
        scene[2][0]['alive']=False;self.orders(scene,2.)
        self.assertNotIn(22,scene[0]._capture_arrivals)
        scene[0].reset(2);self.assertEqual({},scene[0]._capture_arrivals)

    def test_changed_or_missing_capture_circle_releases_old_arrival(self):
        scene=self.scene(1);self.orders(scene)
        scene[3]['capture_bases']['1'][0]['x']=500.
        order=self.orders(scene,2.)[0]
        self.assertNotIn('capture_area',order)
        self.assertNotIn(22,scene[0]._capture_arrivals)
        scene[3]['capture_bases'].clear()
        self.assertNotIn('capture_area',self.orders(scene,3.)[0])

    def test_network_capture_owner_retires_cached_worker_commands(self):
        import test_port_0922_bot_runtime as fixture
        harness=fixture.BotRuntimeTests();harness.setUp()
        self.addCleanup(harness.doCleanups)
        runtime=harness.runtime
        order=self.orders(self.scene(1))[0]
        plain=copy.deepcopy(order);plain.pop('capture_area')
        self.assertTrue(runtime._apply_orders(dict(bot_orders=[plain],bot_order_revision=1)))
        runtime._decision_cache[22]=('old',)
        self.assertTrue(runtime._apply_orders(dict(bot_orders=[order],bot_order_revision=2)))
        self.assertNotIn(22,runtime._decision_cache)
        received=runtime._server_orders[22]
        self.assertEqual(order['capture_area'],received['capture_area'])
        self.assertTrue(capture_orders.inside(received['move_position'],received['capture_area']))

    def test_explicit_route_tasks_do_not_inherit_capture_owner(self):
        scene=self.scene(1);self.orders(scene)
        p=scene[0];bot=p._alive_bots(scene[1],scene[2])[0]
        for kind in ('defense','pressure','guard'):
            p._capture_arrivals[22]=dict(scene[3]['capture_bases']['1'][0])
            p._travel_tasks[22]=dict(kind=kind)
            order=dict(combat_mode='base_defense',move_position=dict(x=0.,y=0.,z=0.),tactical_evidence={})
            p._protect_capture_order(order,bot,p._capture_target(scene[3],2))
            self.assertNotIn('capture_area',order)
            self.assertNotIn(22,p._capture_arrivals)

    def test_worker_reposition_and_live_target_overlay_cannot_bypass_circle(self):
        area=dict(id='1:0',point=dict(x=195.851,y=0.,z=352.782),radius=50.)
        adapter=BotAdapter('45_north_america',1)
        state=dict(id=22,slot=1,team=2,position=(172.7373,9.3916,316.0127),
                   yaw=0.,speed=0.,dt=.1,neighbours=[])
        for mode in ('advance_contact','gun_angle_adjust','cover_peek','withdraw','artillery_deploy'):
            order=dict(combat_mode=mode,target_id=1,target_kind='bot',
                move_position=(-282.287,0.,405.115),aim_position=(-282.287,0.,405.115),
                face_position=(-282.287,0.,405.115),throttle_override=1.,
                capture_area=area,fire_allowed=False)
            original=copy.deepcopy(order)
            command=adapter.decide_with_order(state,order,lambda *a:True)
            self.assertFalse(command['movement_intent'],mode)
            self.assertEqual(1,command['target_id'])
            self.assertFalse(command['fire_allowed'])
            self.assertEqual(original,order)

    def test_no_squad_or_screen_limits_contact_free_route_arrivals(self):
        p=BotPlanner();route=_route('lane',[(0.,0.,False),(0.,100.,False),(0.,300.,False)])
        bots=[_bot(i+1,1,i,route,'mediumTank') for i in range(8)]
        states=[_state(i+1,1,i,100.) for i in range(8)]
        defense=dict(capture_bases={'2':[dict(id='2:0',x=0.,z=300.,radius=50.)]})
        orders=p.build_orders(bots,states,[],1.,defense)['orders']
        self.assertTrue(all(o['combat_mode']=='route' and o['throttle_override'] is None for o in orders))
        for s in states:s.update(z=280.)
        orders=p.build_orders(bots,states,[],2.,defense)['orders']
        self.assertTrue(all(o['throttle_override']==0. and 'capture_area' in o for o in orders))


if __name__=='__main__':unittest.main()
