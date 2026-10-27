"""Report 140346: height resolution must not acquire a steering lease."""
import contextlib
import io
import json
import struct
import unittest
from unittest import mock

import test_port_0922_bot_runtime as fixture
from test_port_0922_server_bot_ai import BotPlanner, _bot, _route, _state


class HeightOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixture.BotRuntimeTests()
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)
        from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator
        self.runtime = self.fx.module.BotRuntime(1)
        graph = json.loads((fixture.ROOT/'navgraphs/86_himmelsdorf_winter.json').read_text())
        self.nav = TerrainNavigator(lambda *a: 1.1000006198883057,
                                    lambda *a: False, baked_graph=graph)
        self.runtime.navigator = self.nav
        self.runtime.baked_graph = graph
        self.runtime.states[20] = dict(id=20, team=2)
        self.runtime._occupied_route_target = lambda *a: None
        self.runtime._route_lane_target = lambda bot,pos,goal,target,*a: target
        def f32(value):
            return struct.unpack('f', struct.pack('f', value))[0]
        self.runtime._navigation_height_columns = lambda x,z,low,high: dict(
            status='complete', surfaces=[dict(point=(f32(x),1.1000006198883057,f32(z)),
                                           normal=(0.,1.,0.))])
        self.position = (-40.06524306439272, 1.1000003814697266, 325.3738171049585)
        self.goal = (-94., 0., 318.)
        self.order = dict(combat_mode='route', route_id='rail', route_index=2,
                          route_anchor=dict(x=-40.,y=1.1,z=325.), route_join=True)

    def select(self, point, now, status='safe'):
        def choose(bot,current,goal,path_key,*args,**kwargs):
            state = self.nav.bot_states.setdefault(bot, {})
            state.update(request_path_key=tuple(path_key), planned_goal=tuple(goal),
                         navigation_status=status, last_target=tuple(point))
            return tuple(point)
        with mock.patch.object(self.nav, 'next_target', side_effect=choose) as query,              mock.patch.object(self.nav.grid, 'dry_segment_clear', return_value=True),              contextlib.redirect_stdout(io.StringIO()):
            target = self.runtime._navigation_target(20,self.position,self.goal,
                self.order,dict(now=now,yaw=-1.47,speed=0.))
        return target, query.call_count

    def test_recorded_height_only_correction_does_not_capture_next_path_corner(self):
        first, count = self.select((-42.,1.1,322.),1.)
        self.assertEqual((-42.,1.1000006198883057,322.),first)
        self.assertEqual(1,count)
        self.assertNotIn('local_fallback_target',self.nav.bot_states[20])
        handoff=self.runtime.states[20]['_navigation_target_receipt']['runtime_leg_handoff']
        self.assertEqual('same_horizontal_endpoint',handoff['reason'])
        self.assertEqual(1.,handoff['sampled_at'])
        self.assertTrue(handoff['unconsumed'])
        # A ready path may advance its lookahead; resolving Y must not turn
        # the old ordinary A* corner into an uncompleted local escape owner.
        onward, count = self.select((-54.,1.1,322.),1.2)
        self.assertEqual(1,count)
        self.assertEqual((-54.,1.1,322.),onward)

    def test_float32_pending_hold_is_not_a_new_leg_to_chase_after_coasting(self):
        target, count = self.select(self.position,1.,status='pending')
        self.assertEqual(1,count)
        self.assertNotEqual(self.position,target)  # exact native rounding is exercised
        self.assertNotIn('local_fallback_target',self.nav.bot_states[20])
        self.position = (self.position[0]-3.,self.position[1],self.position[2])
        onward, count = self.select((-54.,1.1,322.),1.2)
        self.assertEqual(1,count)
        self.assertEqual((-54.,1.1,322.),onward)

    def test_handoff_receipt_reaches_structured_route_connection_log(self):
        self.select((-42.,1.1,322.),1.)
        state=self.runtime.states[20]
        state.update(x=self.position[0],y=self.position[1],z=self.position[2])
        self.runtime._server_orders[20]=dict(self.order)
        with mock.patch('gui.mods.offline_lan_0922.native_input_diagnostics.write_json_record') as log:
            self.runtime._log_route_connection(state,{},1.2)
        row=next(call.args[1] for call in log.call_args_list
                 if call.args[0]=='BOT ROUTE CONNECTION')
        self.assertEqual('same_horizontal_endpoint',row['target']['runtime_leg_handoff']['reason'])
        self.assertEqual(1.,row['target']['runtime_leg_handoff']['sampled_at'])
        self.assertIsNone(row['gun_orientation']['hull_yaw'])
        self.assertIsNone(row['gun_orientation']['turret_yaw'])
        state.update(yaw=.7, turret_yaw=.2, gun_pitch=-.1,
                     _diagnostic_aim_intent=dict(owner='hull_forward_rest', time_us=1200000))
        with mock.patch('gui.mods.offline_lan_0922.native_input_diagnostics.write_json_record') as log:
            self.runtime._log_route_connection(state,{},4.3)
        row=next(call.args[1] for call in log.call_args_list
                 if call.args[0]=='BOT ROUTE CONNECTION')
        self.assertEqual(.7,row['gun_orientation']['hull_yaw'])
        self.assertEqual(.2,row['gun_orientation']['turret_yaw'])
        self.assertEqual(1200000,row['gun_orientation']['previous_aim']['time_us'])
        self.assertEqual('previous_executed_aim_before_current_control',
                         row['gun_orientation']['freshness'])

    def test_real_horizontal_bypass_still_owns_steering_until_consumed(self):
        self.position = (-40.,1.1,325.)
        bypass = (-43.,1.1,320.)
        with mock.patch.object(self.runtime,'_occupied_route_target',
                side_effect=lambda bot,pos,target,now,*rest: bypass if rest else None):
            actual,count = self.select((-42.,1.1,322.),1.)
        self.assertEqual(1,count)
        self.assertEqual(bypass[::2],actual[::2])
        self.assertEqual(actual,self.nav.bot_states[20]['local_fallback_target'])
        same,count = self.select((-54.,1.1,322.),1.2)
        self.assertEqual(0,count)
        self.assertEqual(actual,same)
        self.position=actual
        onward,count=self.select((-54.,1.1,322.),1.4)
        self.assertEqual(1,count)
        self.assertEqual((-54.,1.1,322.),onward)


class RouteTransferTests(unittest.TestCase):
    def scene(self, first=1.4, second=1.5):
        p=BotPlanner()
        left=_route('left',[(-100.,0.,False),(-100.,500.,False)],capacity=8)
        right=_route('right',[(100.,0.,False),(100.,500.,False)],capacity=8)
        manifest=[_bot(i,1,i-41,left if i<43 else right,'mediumTank',
                       {'support':1. if i==41 else .1}) for i in range(41,45)]
        bots=p._alive_bots(manifest,[_state(i,1,-100. if i<43 else 100.,0.)
                                    for i in range(41,45)])
        contacts=[dict(position=dict(x=x,y=0.,z=z),health=weight/2.,max_health=1.)
                  for x,weight in ((-100.,first),(100.,second)) for z in (200.,300.)]
        return p,bots,contacts

    def test_stable_nearly_balanced_pressure_cannot_generate_four_second_ping_pong(self):
        p,bots,contacts=self.scene()
        for now in range(1,182,60):
            p._rebalance_routes(1,bots,contacts,float(now))
        self.assertEqual({},p._route_assignment_receipts)
        receipt=p._route_balance_receipts[1]
        self.assertEqual(181.,receipt['sampled_at'])
        self.assertEqual('no_improving_donor',receipt['outcome'])
        self.assertTrue(any(row['outcome']=='no_pressure_improvement'
                            for row in receipt['candidates']))
        self.assertEqual(['left','left','right','right'],
            [(p._route_assignments.get(b['id']) or {}).get('route',b['route'])['id']
             for b in bots])

    def test_recorded_jagdtiger_transfer_would_worsen_pressure_after_departure(self):
        p,bots,unused=self.scene()
        left=bots[0]['route']
        p._route_assignments[43]=dict(route=left,until=0.)
        bots.extend(p._alive_bots([_bot(45,1,4,left,'mediumTank',{'support':.1})],
                                 [_state(45,1,-100.,0.)]))
        contacts=[dict(position=dict(x=-100.,y=0.,z=z),health=1.,max_health=1.)
                  for z in (200.,300.)]
        contacts.append(dict(position=dict(x=100.,y=0.,z=250.),
                             health=.7905238095238095,max_health=1.))
        p._rebalance_routes(1,bots,contacts,1.)
        self.assertEqual({},p._route_assignment_receipts)
        balance=p._route_balance_receipts[1]
        check=next(row for row in balance['candidates'] if row['bot']==41)
        self.assertEqual('no_pressure_improvement',check['outcome'])
        self.assertAlmostEqual(.3405238095238095,check['before_transfer'])
        self.assertAlmostEqual(.65,check['after_transfer'])

    def test_balance_evidence_survives_same_revision_worker_transport(self):
        p,bots,contacts=self.scene()
        p._rebalance_routes(1,bots,contacts,1.)
        states=[bot['state'] for bot in bots]
        first=p.build_orders(bots,states,[],2.)
        order=next(row for row in first['orders'] if row['id']==41)
        balance=order['route_assignment']['balance']
        self.assertEqual('no_pressure_improvement',balance['candidate']['outcome'])
        self.assertEqual(1.,balance['sampled_at'])
        self.assertEqual(2.,balance['observed_at'])
        fx=fixture.BotRuntimeTests();fx.setUp()
        try:
            runtime=fx.module.BotRuntime(1)
            runtime._apply_orders(dict(bot_order_revision=first['revision'],
                                       bot_orders=first['orders']))
            second=p.build_orders(bots,states,[],2.5)
            self.assertEqual(first['revision'],second['revision'])
            runtime._apply_orders(dict(bot_order_revision=second['revision'],
                                       bot_orders=second['orders']))
            received=runtime._server_orders[41]['route_assignment']['balance']
            self.assertEqual(1.,received['sampled_at'])
            self.assertEqual(2.5,received['observed_at'])
            self.assertEqual(balance['candidate'],received['candidate'])
        finally:
            fx.tearDown()

    def test_cached_balance_receipt_keeps_evaluation_time_and_reset_clears_it(self):
        p,bots,contacts=self.scene()
        p._rebalance_routes(1,bots,contacts,1.)
        receipt=json.loads(json.dumps(p._route_balance_receipts[1]))
        p._rebalance_routes(1,bots,contacts,2.)
        self.assertEqual(receipt,json.loads(json.dumps(p._route_balance_receipts[1])))
        p.reset()
        self.assertEqual({},p._route_balance_receipts)

    def test_pressure_shift_returns_via_start_and_later_reverse_transfer_is_ordered(self):
        p,bots,contacts=self.scene(.6,3.)
        p._rebalance_routes(1,bots,contacts,1.)
        task=p._travel_tasks[41];donor=next(b for b in bots if b['id']==41)
        self.assertEqual('left',p._route_assignments[41]['route']['id'])
        order=dict(combat_mode='route',target_id=None)
        for index,point in enumerate(task['points']):
            donor['state'].update(point);p._task_publish(order,donor,task,2.+index)
        self.assertEqual('right',p._route_assignments[41]['route']['id'])
        shifted=[dict(position=dict(x=-100.,y=0.,z=z),health=1.,max_health=1.) for z in (150.,200.,250.,300.)]
        p._rebalance_routes(1,bots,shifted,181.)
        self.assertEqual('right',p._route_assignments[41]['route']['id'])
        self.assertEqual('left',p._travel_tasks[41]['target_route']['id'])
        self.assertEqual(2,p._route_assignment_receipts[41]['sequence'])


if __name__=='__main__':
    unittest.main()
