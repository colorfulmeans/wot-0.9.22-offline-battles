"""Ordered macro recovery, independent from native motor/collision policy."""
import copy
import unittest

from test_port_0922_server_bot_ai import BotPlanner, _bot, _route, _state, _order_signature


class RecoveryScene:
    def __init__(self, failed=2, alternatives=True, physical=True):
        self.planner = BotPlanner()
        self.main = _route('main', [(0, 0, False), (0, 100, False), (0, 200, False),
                                    (100, 200, False), (200, 200, False)])
        self.other = _route('other', [(0, 0, False), (-100, 100, False), (-100, 200, False)])
        self.manifest = [_bot(17, 1, 0, self.main, 'heavyTank')]
        if alternatives:
            self.manifest.append(_bot(24, 1, 1, self.other, 'mediumTank'))
        state = dict(_state(17, 1, 30, 100), world_pose=True, route_wreck_blocked=physical)
        self.bot = self.planner._alive_bots(self.manifest, [state])[0]
        self.planner._route_assignments[17] = dict(route=self.main, until=0.)
        self.planner._route_states[17] = dict(route_id='main', index=failed)

    def step(self, now, position=None, mode='route', **values):
        if position is not None:
            self.bot['state'].update(x=position[0], z=position[1])
        identity, index, goal, anchor, join = self.planner._route(self.bot, now)
        order = dict(id=17, route_id=identity, route_index=index, move_position=goal,
                     route_anchor=anchor, route_join=join, combat_mode=mode, **values)
        self.planner._apply_authored_route_order(order, self.bot, goal, now)
        self.planner._reroute_wreck_stall(order, self.bot, self.manifest, now)
        return order

    @property
    def recovery(self):
        return self.planner._route_recoveries.get(17)


class RouteRecoveryCycleTests(unittest.TestCase):
    def test_aiming_during_route_advance_does_not_pause_any_recovery_leg(self):
        s = RecoveryScene()
        expected = [('forward', 2), ('skip', 3), ('return', 1), ('return_skip', 0)]
        for tick in range(46):
            order = s.step(tick * 20, mode='advance', target_id=26 + tick % 2,
                           target_kind='bot', throttle_override=1., fire_allowed=False)
            self.assertEqual(expected[tick % 4],
                             (s.recovery['phase'], order['route_index']))
            self.assertNotEqual('pause_advance', order['route_attempt']['action'])
            self.assertEqual(26 + tick % 2, order['target_id'])
            self.assertFalse(order['fire_allowed'])

    def test_c_d_b_a_retry_c_for_the_entire_fifteen_minutes(self):
        s = RecoveryScene()
        original = copy.deepcopy(s.main)
        expected = [('forward', 2), ('skip', 3), ('return', 1), ('return_skip', 0)]
        for tick in range(46):
            order = s.step(tick*20)
            self.assertEqual(expected[tick % 4], (s.recovery['phase'], order['route_index']))
            self.assertEqual('main', order['route_id'])
            self.assertEqual('route', order['combat_mode'])
            self.assertIsNone(order['throttle_override'])
        self.assertEqual(original, s.main)
        self.assertGreaterEqual(s.recovery['round'], 11)

    def test_return_b_success_then_a_to_start_before_switching(self):
        s = RecoveryScene()
        for now in (0, 20, 40):
            order = s.step(now)
        self.assertEqual(('return', 1), (s.recovery['phase'], order['route_index']))
        order = s.step(41, (0, 100))
        self.assertEqual(('main', 0), (order['route_id'], order['route_index']))
        self.assertIsNotNone(s.recovery)
        order = s.step(42, (0, 0))
        self.assertEqual(('other', 1), (order['route_id'], order['route_index']))
        self.assertEqual('recovery_at_start', order['route_switch_reason'])
        self.assertIsNone(s.recovery)

    def test_success_at_c_or_d_returns_to_normal_forward_travel(self):
        for skipped in (False, True):
            s = RecoveryScene()
            s.step(0)
            if skipped:
                s.step(20)
            index = 3 if skipped else 2
            goal = s.main['waypoints'][index]
            order = s.step(21 if skipped else 1, (goal['x'], goal['z']))
            self.assertIsNone(s.recovery)
            self.assertEqual(index+1, order['route_index'])
            self.assertEqual('recovery_complete', order['route_attempt']['action'])

    def test_return_skip_success_continues_every_earlier_point(self):
        s = RecoveryScene(failed=4)
        s.step(0)
        self.assertEqual(3, s.step(20)['route_index'])  # terminal C has no D
        self.assertEqual(2, s.step(40)['route_index'])  # B failed: try A
        self.assertEqual(1, s.step(41, (0, 200))['route_index'])
        self.assertEqual(0, s.step(42, (0, 100))['route_index'])
        self.assertIsNotNone(s.recovery)
        self.assertEqual('other', s.step(43, (0, 0))['route_id'])
        self.assertIsNone(s.recovery)

    def test_b_is_first_point_and_failure_does_not_stop_retries(self):
        s = RecoveryScene(failed=1)
        s.bot['state'].update(x=50, z=50)
        s.step(0); s.step(20)
        self.assertEqual(0, s.step(40)['route_index'])
        self.assertEqual(1, s.step(60)['route_index'])
        self.assertEqual('forward', s.recovery['phase'])

    def test_transfer_remains_recovery_until_new_first_point_is_reached(self):
        s = RecoveryScene()
        s.other['waypoints'][0].update(x=-40, z=-40)
        s.planner._route_history[17] = {'other': dict(index=2, parking_completed={0, 1})}
        for now in (0, 20, 40):s.step(now)
        s.step(41, (0, 100))
        order = s.step(42, (0, 0))
        self.assertEqual(('other', 0), (order['route_id'], order['route_index']))
        self.assertEqual('transfer', s.recovery['phase'])
        self.assertEqual('retry_transfer', s.step(62)['route_attempt']['action'])
        self.assertEqual(0, s.recovery['index'])
        order = s.step(63, (-40, -40))
        self.assertIsNone(s.recovery)
        self.assertEqual(1, order['route_index'])
        self.assertNotIn(1, s.planner._route_states[17].get('parking_completed', ()))

    def test_no_eligible_alternative_retries_same_route_without_cooldown(self):
        s = RecoveryScene(alternatives=False)
        for now in (0, 20, 40):s.step(now)
        s.step(41, (0, 100))
        order = s.step(42, (0, 0))
        self.assertEqual(('main', 2), (order['route_id'], order['route_index']))
        self.assertEqual('retry_no_alternative', order['route_attempt']['action'])
        self.assertEqual('forward', s.recovery['phase'])
        self.assertEqual(3, s.step(62)['route_index'])

    def test_combat_pauses_all_phases_and_rejoins_from_actual_pose(self):
        for target in (None, 55):
            s = RecoveryScene()
            s.step(0); s.step(20); s.step(40)
            before = copy.deepcopy(s.recovery)
            paused = s.step(45, mode='engage', target_id=target)
            self.assertEqual('pause_engage', paused['route_attempt']['action'])
            s.step(300, (30, 80), mode='engage', target_id=target)
            self.assertEqual(before, s.recovery)
            order = s.step(301)
            self.assertEqual('return', s.recovery['phase'])
            self.assertEqual(5., order['route_attempt']['elapsed'])
            self.assertEqual(dict(x=30., y=0., z=80.), order['route_anchor'])
            self.assertEqual(0, s.step(316)['route_index'])

    def test_combat_movement_cannot_refresh_the_recovery_budget(self):
        s = RecoveryScene()
        s.step(0); s.step(5, mode='engage', target_id=55)
        s.step(90, (0, 180), mode='engage', target_id=55)
        order = s.step(100)
        self.assertEqual(5., order['route_attempt']['elapsed'])
        self.assertNotEqual('physical_progress_renewed', order['route_attempt']['action'])
        self.assertEqual(3, s.step(115)['route_index'])

    def test_explicit_stop_and_track_damage_pause_without_erasing_progress(self):
        for kind in ('command', 'immobile', 'airborne', 'unowned'):
            s = RecoveryScene(); s.step(0); s.step(20)
            kwargs = {'team_command': 'STOP'} if kind == 'command' else {}
            if kind == 'immobile':s.bot['state']['critical'] = {'destroyed': ['leftTrackHealth']}
            if kind == 'airborne':s.bot['state']['airborne'] = True
            if kind == 'unowned':s.bot['state']['world_pose'] = False
            s.step(25, **kwargs); s.step(200, **kwargs)
            self.assertEqual(('skip', 3), (s.recovery['phase'], s.recovery['index']))

    def test_arrival_circle_accepts_a_crossing_without_requiring_the_center(self):
        s = RecoveryScene()
        s.step(0); s.step(1, (-10, 200))
        order = s.step(2, (10, 200))
        self.assertIsNone(s.recovery)
        self.assertEqual('recovery_complete', order['route_attempt']['action'])

    def test_return_does_not_call_wait_owner_and_new_route_starts_fresh(self):
        from unittest import mock
        s = RecoveryScene()
        points=[[p['x'],p['z'],0] for p in s.main['waypoints']]
        points[1][2:]=[1,0,[[0,100,60]]]
        s.planner.tactics_map='08_ruinberg'
        s.planner.tactics['maps']['08_ruinberg']=dict(default_routes=[dict(id='main',team=1,points=points)])
        s.step(0); s.step(20); s.step(40)
        s.planner._wait_claims[(1, 'main', 1, 0)] = dict(bot_id=17)
        with mock.patch.object(s.planner, '_wait_parking', side_effect=AssertionError('return cannot wait')):
            s.step(41, (0, 100))
            s.step(42, (0, 0))
        self.assertFalse(s.planner._wait_claims)

    def test_pressure_cannot_invalidate_or_reassign_recovery_routes(self):
        import test_port_0922_navigation_handoff_140346 as fixture
        p, bots, contacts = fixture.RouteTransferTests().scene(.6, 3.)
        for bot in bots:
            p._route_recoveries[bot['id']] = dict(phase='return')
            p._route_assignments[bot['id']] = dict(route=bot['route'], until=1., radio_scoped=True)
        before = copy.deepcopy(p._route_assignments)
        p._rebalance_routes(1, bots, contacts, 100)
        self.assertEqual(before, p._route_assignments)
        self.assertTrue(all(r['outcome']=='route_recovery_in_progress'
                            for r in p._route_balance_receipts[1]['candidates']))
        p._route_recoveries.clear()
        p._next_route_rebalance[1] = 0
        p._rebalance_routes(1, bots, contacts, 101)
        self.assertTrue(any(r['outcome']!='route_recovery_in_progress'
                            for r in p._route_balance_receipts[1]['candidates']))

    def test_attempt_telemetry_does_not_churn_order_revisions(self):
        s = RecoveryScene()
        first = _order_signature(s.step(0))
        self.assertEqual(first, _order_signature(s.step(9)))

    def test_stale_pose_gap_cannot_consume_a_gate_via_projection(self):
        s = RecoveryScene()
        s.step(0); s.step(1, (-10,200))
        order=s.step(10, (10,200))
        self.assertIsNotNone(s.recovery)
        self.assertEqual(2,order['route_index'])

    def test_new_lane_wait_is_normal_after_recovery_completion(self):
        s=RecoveryScene()
        s.other['id']='user_new'
        s.planner.tactics_map='08_ruinberg'
        s.planner.tactics['maps']['08_ruinberg']=dict(routes=[dict(
            id='new',team=1,classes=['heavyTank'],slots=[],policy='preferred',
            points=[[0,0,0],[-100,100,1,0,[[-100,100,60]]],[-100,200,0]])])
        for now in (0,20,40):s.step(now)
        s.step(41,(0,100))
        order=s.step(42,(0,0))
        self.assertIsNone(s.recovery)
        self.assertEqual('parking_approach',order['combat_mode'])
        order=s.step(43,(-100,100))
        self.assertEqual('hold',order['combat_mode'])
        self.assertEqual(43,s.planner._route_states[17]['parking_arrived'][1])
        self.assertEqual('hold',s.step(102)['combat_mode'])
        self.assertEqual(2,s.step(103)['route_index'])

    def test_completion_at_terminal_hands_back_to_capture_in_same_order(self):
        import test_port_0922_terminal_route_handoff as fixture
        helper=fixture.TerminalRouteHandoffTests();scene=helper.scene()
        planner,manifest,states,defense=scene
        planner._route_assignments[17]=dict(route=manifest[0]['route'],until=0.)
        planner._route_states[17]=dict(route_id='banana',index=2)
        planner._route_recoveries[17]=dict(route_id='banana',index=2,failed=1,
            phase='skip',anchor=dict(x=84.523,y=0.,z=-194.48),round=0)
        order=helper.order(scene,contact=False)
        self.assertNotIn(17,planner._route_recoveries)
        self.assertEqual(0.,order['throttle_override'])
        self.assertNotEqual('route_recovery_in_progress',order['tactical_evidence']['route_terminal']['outcome'])

    def test_completed_start_transfer_does_not_starve_the_third_lane(self):
        s=RecoveryScene()
        third=_route('zzz',[(0,0,False),(100,100,False),(100,200,False)])
        s.manifest.append(_bot(25,1,2,third,'mediumTank'))
        selected=[]
        s.bot['state'].update(x=0,z=0)
        for now in range(3):
            route=s.planner._cycle_route(s.bot)
            recovery=dict(route_id=route['id'],phase='return',index=0,failed=1,
                          anchor=dict(x=0,y=0,z=0),round=0)
            s.planner._route_recoveries[17]=recovery
            s.planner._cycle_change_route({},s.bot,s.manifest,recovery,now)
            self.assertIsNone(s.recovery)
            selected.append(s.planner._cycle_route(s.bot)['id'])
        self.assertEqual(['other','zzz','main'],selected)

    def test_death_prunes_cycle_and_route_selection_memory(self):
        s=RecoveryScene();s.step(0);s.step(20)
        s.planner._recovery_route_visits[17]={'main':1}
        s.bot['state'].update(alive=False,health=0)
        s.planner.build_orders(s.manifest,[s.bot['state']],[],30)
        self.assertNotIn(17,s.planner._route_recoveries)
        self.assertNotIn(17,s.planner._recovery_route_visits)
        self.assertNotIn(17,s.planner._wreck_route_progress)

    def test_class_exclusion_cannot_be_bypassed_when_returning_to_start(self):
        for key,value in (('class_weights',{'heavyTank':0}),
                          ('_editor_disabled_classes',['heavyTank'])):
            s=RecoveryScene();s.other[key]=value
            for now in (0,20,40):s.step(now)
            s.step(41,(0,100))
            order=s.step(42,(0,0))
            self.assertEqual('main',order['route_id'])
            self.assertEqual('retry_no_alternative',order['route_attempt']['action'])
            self.assertIsNotNone(s.recovery)

    def test_combat_resume_and_completed_gate_wait_keep_actual_connector(self):
        s=RecoveryScene()
        points=[[p['x'],p['z'],0] for p in s.main['waypoints']]
        points[3][2:]=[1,0,[[110,200,60]]]
        s.planner.tactics_map='08_ruinberg'
        s.planner.tactics['maps']['08_ruinberg']=dict(default_routes=[dict(
            id='main',team=1,class_tag='heavyTank',points=points)])
        # Use the class-specific identity so the real authored wait owner sees it.
        s.main['id']='class_ht_main'
        s.planner._route_states[17]['route_id']=s.main['id']
        s.step(0);s.step(20);s.step(25,mode='engage',target_id=55)
        s.step(50,(20,150),mode='engage',target_id=55)
        order=s.step(51)
        self.assertEqual(dict(x=20.,y=0.,z=150.),s.planner._route_states[17]['join_anchor'])
        order=s.step(52,(100,200))
        self.assertIsNone(s.recovery)
        self.assertEqual('parking_approach',order['combat_mode'])
        self.assertEqual(dict(x=100.,y=0.,z=200.),order['route_anchor'])
        self.assertEqual(110.,order['move_position']['x'])

    def test_reset_clears_cycles_and_gate_clocks(self):
        s = RecoveryScene(); s.step(0); s.step(20)
        s.planner.reset(3)
        self.assertEqual({}, s.planner._route_recoveries)
        self.assertEqual({}, s.planner._wreck_route_progress)
        self.assertEqual({}, s.planner._recovery_route_visits)


if __name__ == '__main__':
    unittest.main()
