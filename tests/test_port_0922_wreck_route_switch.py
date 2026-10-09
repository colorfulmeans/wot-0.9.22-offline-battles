"""A blocked macro lane must be abandoned, rather than locally retried forever."""
import unittest

from test_port_0922_server_bot_ai import BotPlanner, _bot, _route, _state
from test_port_0922_bot_state_codec import codec, _bot_state, STATIC
import test_port_0922_bot_runtime as runtime_fixture


class WreckRouteSwitchTests(unittest.TestCase):
    def setUp(self):
        self.planner = BotPlanner()
        self.lane = _route('banana', [(190, 74, False), (190, -74, False),
                                      (0, -280, False)])
        self.bypass = _route('rail', [(100, 100, False), (0, 0, False),
                                     (0, -280, False)])
        self.manifest = [_bot(17, 1, 0, self.lane, 'heavyTank'),
                         _bot(24, 1, 1, self.lane, 'AT-SPG'),
                         _bot(25, 1, 2, self.bypass, 'mediumTank')]
        self.states = [_state(17, 1, 120, -28),
                       _state(24, 1, 176, -9), _state(25, 1, 0, 0)]
        for state in self.states:
            state.update(world_pose=True, route_wreck_blocked=True)

    def orders(self, now):
        return {o['id']: o for o in self.planner.build_orders(
            self.manifest, self.states, [], now)['orders']}

    def return_home(self, now):
        home=self.lane['waypoints'][0]
        for state in self.states[:2]:
            state.update(x=home['x'],z=home['z'],route_wreck_blocked=False)
        return self.orders(now)

    def test_skip_blocked_gate_then_change_route_after_next_attempt(self):
        first=self.orders(0)
        self.orders(29.9)
        skipped=self.orders(30)
        for bot_id in (17,24):
            self.assertEqual('banana',skipped[bot_id]['route_id'])
            self.assertEqual(first[bot_id]['route_index']+1,skipped[bot_id]['route_index'])
            self.assertEqual('blocked_timeout',skipped[bot_id]['route_point_skip_reason'])
            self.assertEqual(dict(x=self.states[0 if bot_id==17 else 1]['x'],y=0.,
                                  z=self.states[0 if bot_id==17 else 1]['z']),
                             skipped[bot_id]['route_anchor'])
            self.assertTrue(skipped[bot_id]['route_join'])
        self.assertEqual('banana',self.orders(89.9)[17]['route_id'])
        returning=self.orders(90)
        self.assertEqual('returning',returning[17]['route_retreat_phase'])
        self.assertEqual('banana',returning[17]['route_id'])
        changed=self.return_home(91)
        for bot_id in (17,24):
            self.assertEqual('rail',changed[bot_id]['route_id'])
            self.assertEqual('returned_home',changed[bot_id]['route_switch_reason'])

    def test_recovery_orbits_do_not_extend_attempt_budget(self):
        self.orders(0)
        for now in range(1,31):
            self.states[0]['x']=111 if now%2 else 120
            self.states[0]['yaw']=now*.3
            orders=self.orders(now)
        self.assertEqual(2,orders[17]['route_index'])
        self.assertEqual('banana',orders[17]['route_id'])
        self.assertEqual('returning',self.orders(90)[17]['route_retreat_phase'])
        self.assertEqual('rail',self.return_home(91)[17]['route_id'])

    def test_actual_progress_past_next_gate_resets_skip_sequence(self):
        self.lane['waypoints'].append(dict(x=-200,y=0,z=-280))
        self.orders(0);self.orders(40)
        self.states[0].update(x=0,z=-280,route_wreck_blocked=False)
        self.assertEqual(3,self.orders(31)[17]['route_index'])
        self.assertNotIn('blocked_skip_to',self.planner._route_states[17])

    def test_second_blocked_gate_changes_route_instead_of_skipping_again(self):
        self.lane['waypoints'].append(dict(x=-200,y=0,z=-280))
        self.orders(0);self.orders(30)
        self.assertEqual('returning',self.orders(90)[17]['route_retreat_phase'])
        self.assertEqual('rail',self.return_home(91)[17]['route_id'])

    def test_reaching_next_gate_allows_a_fresh_skip_on_later_obstruction(self):
        self.lane['waypoints'].extend([dict(x=-200,y=0,z=-280),dict(x=-400,y=0,z=-280)])
        self.orders(0);self.orders(40)
        self.states[0].update(x=0,z=-280,route_wreck_blocked=False)
        self.orders(31)
        self.states[0]['route_wreck_blocked']=True
        self.orders(32)
        skipped=self.orders(62)[17]
        self.assertEqual(('banana',4),(skipped['route_id'],skipped['route_index']))
        self.assertEqual('blocked_timeout',skipped['route_point_skip_reason'])

    def test_cleared_blocker_resets_next_gate_attempt_clock(self):
        self.orders(0);self.orders(40)
        self.states[0]['route_wreck_blocked']=False
        self.orders(40)
        self.states[0]['route_wreck_blocked']=True
        self.orders(90)
        self.assertEqual('banana',self.orders(149.9)[17]['route_id'])
        self.assertEqual('returning',self.orders(150)[17]['route_retreat_phase'])
        self.assertEqual('rail',self.return_home(151)[17]['route_id'])

    def test_proved_obstruction_close_to_gate_skips_without_returning(self):
        self.states[0].update(x=190,z=-64)
        self.planner._route_states[17]=dict(route_id='banana',index=1)
        bot=self.planner._alive_bots(self.manifest,self.states)[0]
        order=dict(route_id='banana',route_index=1,combat_mode='route',
                   move_position=self.lane['waypoints'][1])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,0)
        self.planner._reroute_wreck_stall(order,bot,self.manifest,30)
        self.assertEqual(('banana',2),(order['route_id'],order['route_index']))
        self.assertEqual(-64,order['route_anchor']['z'])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,90)
        self.assertEqual('returning',order['route_retreat_phase'])
        bot['state'].update(x=190,z=74,route_wreck_blocked=False)
        self.planner._reroute_wreck_stall(order,bot,self.manifest,91)
        self.assertEqual('rail',order['route_id'])

    def test_missing_owned_pose_or_immobilization_never_switches(self):
        self.states[0]['route_wreck_blocked'] = False
        self.states[0]['world_pose'] = False
        self.states[1]['critical'] = {'destroyed': ['leftTrackHealth']}
        self.orders(0)
        self.assertEqual('banana', self.orders(100)[17]['route_id'])
        self.assertEqual('banana', self.orders(100)[24]['route_id'])

    def test_native_stall_without_wreck_skips_then_switches(self):
        for state in self.states:state['route_wreck_blocked']=False
        first=self.orders(0)[17]
        skipped=self.orders(30)[17]
        self.assertEqual(first['route_index']+1,skipped['route_index'])
        self.assertEqual('returning',self.orders(90)[17]['route_retreat_phase'])
        self.assertEqual('rail',self.return_home(91)[17]['route_id'])

    def test_capture_and_route_transitions_keep_the_failed_gate_budget(self):
        self.states[0]['route_wreck_blocked']=False
        bot=self.planner._alive_bots(self.manifest,self.states)[0]
        self.planner._route_states[17]=dict(route_id='banana',index=1)
        order=dict(route_id='banana',route_index=1,combat_mode='route',
                   move_position=self.lane['waypoints'][1])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,0)
        order.update(combat_mode='base_capture',move_position=dict(x=0,y=0,z=-280))
        self.planner._reroute_wreck_stall(order,bot,self.manifest,30)
        self.assertEqual(2,order['route_index'])
        order['combat_mode']='base_capture'
        self.planner._reroute_wreck_stall(order,bot,self.manifest,90)
        self.assertEqual('returning',order['route_retreat_phase'])
        self.assertNotIn('route_switch_reason',order)

    def test_forward_progress_refreshes_timer_but_local_orbit_does_not(self):
        self.states[0]['route_wreck_blocked']=False
        bot=self.planner._alive_bots(self.manifest,self.states)[0]
        order=dict(route_id='banana',route_index=1,combat_mode='route',
                   move_position=dict(x=220,y=0,z=-28))
        self.planner._reroute_wreck_stall(order,bot,self.manifest,0)
        bot['state']['x']+=10
        self.planner._reroute_wreck_stall(order,bot,self.manifest,19)
        self.assertEqual(19,self.planner._wreck_route_progress[17]['since'])
        bot['state']['z']+=8
        self.planner._reroute_wreck_stall(order,bot,self.manifest,30)
        self.assertEqual(19,self.planner._wreck_route_progress[17]['since'])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,49)
        self.assertEqual('blocked_timeout',order['route_point_skip_reason'])

    def test_arrived_capture_and_intentional_hold_do_not_reroute(self):
        self.states[0]['route_wreck_blocked']=False
        bot=self.planner._alive_bots(self.manifest,self.states)[0]
        order=dict(route_id='banana',route_index=1,combat_mode='base_capture',
                   move_position=dict(x=120,y=0,z=-28),throttle_override=0)
        for now in (0,100):self.planner._reroute_wreck_stall(order,bot,self.manifest,now)
        self.assertNotIn(17,self.planner._wreck_route_progress)

    def test_route_alias_with_same_failed_next_gate_is_not_an_exit(self):
        bot=self.planner._alive_bots(self.manifest,self.states)[0]
        self.planner._route_states[17]=dict(route_id='banana',index=2,blocked_skip_to=2)
        self.bypass['waypoints']=[dict(x=120,y=0,z=-28),dict(x=0,y=0,z=-280)]
        order=dict(route_id='banana',route_index=2,combat_mode='route',
                   move_position=self.lane['waypoints'][2])
        for now in (0,20):self.planner._reroute_wreck_stall(order,bot,self.manifest,now)
        self.assertNotIn('route_switch_reason',order)

    def test_switch_joins_current_entry_instead_of_restoring_old_failed_cursor(self):
        self.planner._route_history[17]={'rail':dict(index=2,parking_completed={0})}
        self.orders(0);self.orders(30)
        self.assertEqual('returning',self.orders(90)[17]['route_retreat_phase'])
        order=self.return_home(91)[17]
        self.assertEqual('rail',order['route_id'])
        self.assertEqual(0,order['route_index'])
        self.assertTrue(order['route_join'])
        self.assertEqual({0},self.planner._route_states[17]['parking_completed'])

    def test_artillery_only_capturer_does_not_wait_for_a_stationary_route_cursor(self):
        bot=self.planner._alive_bots(self.manifest,self.states)[0]
        bot['profile']['class_tag']='SPG'
        target=dict(id='enemy',point=dict(x=0,y=0,z=-280),radius=50)
        order=self.planner._order_for(bot,0,1,None,[],0,team_bots=[bot],
            capture_target=target,no_known_enemies=True)
        self.assertEqual('base_capture',order['combat_mode'])
        self.assertEqual(target['point'],order['move_position'])

    def long_return(self):
        self.lane['waypoints']=[dict(x=x,y=0,z=z) for x,z in
            ((0,0),(0,100),(100,100),(200,100),(300,100))]
        self.states[0].update(x=180,z=100)
        bot=self.planner._alive_bots(self.manifest,self.states)[0]
        self.planner._route_states[17]=dict(route_id='banana',index=3)
        order=dict(route_id='banana',route_index=3,combat_mode='route',
                   move_position=self.lane['waypoints'][3])
        home=dict(point=dict(x=-100,y=0,z=0))
        for now in (0,30,90):
            self.planner._reroute_wreck_stall(order,bot,self.manifest,now,home)
        return bot,order

    def test_reverse_nodes_then_own_base_before_starting_another_route(self):
        bot,order=self.long_return()
        self.assertEqual(dict(x=100,y=0,z=100),order['move_position'])
        for now,pose,next_goal in ((91,(100,100),(0,100)),
                                  (92,(0,100),(0,0)),(93,(0,0),(-100,0))):
            bot['state'].update(x=pose[0],z=pose[1])
            self.planner._reroute_wreck_stall(order,bot,self.manifest,now)
            self.assertEqual('banana',order['route_id'])
            self.assertEqual(next_goal,(order['move_position']['x'],order['move_position']['z']))
        bot['state'].update(x=-100,z=0,route_wreck_blocked=False)
        self.planner._reroute_wreck_stall(order,bot,self.manifest,94)
        self.assertEqual('rail',order['route_id'])
        self.assertEqual('returned_home',order['route_switch_reason'])

    def test_two_failed_return_gates_resume_forward_instead_of_changing_route(self):
        bot,order=self.long_return()
        self.planner._reroute_wreck_stall(order,bot,self.manifest,119.9)
        self.assertEqual(2,order['route_retreat_index'])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,120)
        self.assertEqual(1,order['route_retreat_index'])
        self.assertEqual(dict(x=0,y=0,z=100),order['move_position'])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,179.9)
        self.assertIn(17,self.planner._route_retreats)
        self.planner._reroute_wreck_stall(order,bot,self.manifest,180)
        self.assertNotIn(17,self.planner._route_retreats)
        self.assertEqual('banana',order['route_id'])
        self.assertEqual(dict(x=200,y=0,z=100),order['move_position'])
        self.assertEqual('second_return_gate_failed',order['route_retreat_aborted'])

    def test_aborted_return_restarts_full_forward_attempt_sequence(self):
        bot,order=self.long_return()
        for now in (120,180):
            self.planner._reroute_wreck_stall(order,bot,self.manifest,now)
        self.assertEqual(3,order['route_index'])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,181)
        self.planner._reroute_wreck_stall(order,bot,self.manifest,210.9)
        self.assertEqual(3,order['route_index'])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,211)
        self.assertEqual(4,order['route_index'])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,270.9)
        self.assertNotIn(17,self.planner._route_retreats)
        self.planner._reroute_wreck_stall(order,bot,self.manifest,271)
        self.assertIn(17,self.planner._route_retreats)

    def test_new_route_repeats_skip_and_return_policy(self):
        self.orders(0);self.orders(30);self.orders(90)
        order=self.return_home(91)[17]
        self.assertEqual('rail',order['route_id'])
        self.states[0]['route_wreck_blocked']=True
        self.orders(92)
        self.assertEqual(0,self.orders(121.9)[17]['route_index'])
        self.assertEqual(1,self.orders(122)[17]['route_index'])
        self.orders(181.9)
        self.assertNotIn(17,self.planner._route_retreats)
        self.assertEqual('returning',self.orders(182)[17]['route_retreat_phase'])

    def test_reaching_an_earlier_gate_resets_consecutive_return_failures(self):
        bot,order=self.long_return()
        self.planner._reroute_wreck_stall(order,bot,self.manifest,120)
        bot['state'].update(x=0,z=100)
        self.planner._reroute_wreck_stall(order,bot,self.manifest,121)
        self.assertEqual(0,self.planner._route_retreats[17]['failures'])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,181)
        self.assertIn(17,self.planner._route_retreats)

    def test_waiting_places_are_not_revisited_during_return(self):
        bot,order=self.long_return()
        from unittest import mock
        with mock.patch.object(self.planner,'_wait_parking',side_effect=AssertionError('return must not park')):
            route_id,index,point,anchor,join=self.planner._route(bot,45)
        self.assertEqual(('banana',2), (route_id,index))
        self.assertTrue(join)

    def test_explicit_stay_pauses_return_timeout(self):
        bot,order=self.long_return()
        held=dict(order,team_command='STAY',throttle_override=0)
        self.planner._reroute_wreck_stall(held,bot,self.manifest,100)
        self.assertEqual(0,held['throttle_override'])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,101)
        self.assertEqual(2,order['route_retreat_index'])

    def test_artillery_with_living_regulars_retains_its_staging_policy(self):
        bots=self.planner._alive_bots(self.manifest,self.states)
        bot=bots[0];bot['profile']['class_tag']='SPG'
        target=dict(id='enemy',point=dict(x=0,y=0,z=-280),radius=50)
        order=self.planner._order_for(bot,0,len(bots),None,[],0,team_bots=bots,
            capture_target=target,no_known_enemies=True)
        self.assertNotEqual('base_capture',order['combat_mode'])

    def test_no_suitable_route_holds_and_does_not_oscillate(self):
        self.bypass['class_weights'] = {'heavyTank': 0, 'AT-SPG': 0}
        self.orders(0)
        self.orders(30)
        self.assertEqual('banana', self.orders(100)[17]['route_id'])
        self.bypass['class_weights'] = {'heavyTank': 1, 'AT-SPG': 1}
        orders = self.return_home(120)
        self.assertEqual('rail', orders[17]['route_id'])
        self.assertEqual('rail', self.orders(140)[17]['route_id'])
        self.assertNotIn('route_switch_reason', self.orders(141)[17])

    def test_combat_hold_and_explicit_command_reset_stall_clock(self):
        bot = self.planner._alive_bots(self.manifest, self.states)[0]
        for extra in ({'combat_mode': 'engage'}, {'throttle_override': 0},
                      {'team_command': 'STAY'}):
            order = dict(route_id='banana', route_index=1, combat_mode='route',
                         move_position=self.lane['waypoints'][1])
            self.planner._reroute_wreck_stall(order, bot, self.manifest, 0)
            held = dict(order, **extra)
            self.planner._reroute_wreck_stall(held, bot, self.manifest, 25)
            self.assertNotIn(17, self.planner._wreck_route_progress)
            self.assertEqual('banana', held['route_id'])

    def test_round_reset_clears_stall_and_rejected_routes(self):
        self.orders(0)
        self.orders(30)
        self.planner.reset(2)
        self.assertEqual({}, self.planner._wreck_route_progress)
        self.assertEqual({}, self.planner._wreck_route_avoid)
        self.assertEqual({}, self.planner._route_retreats)
        self.assertEqual('banana', self.orders(100)[17]['route_id'])

    def test_exact_wreck_evidence_survives_compact_checkpoint(self):
        for blocked in (True, False):
            state = _bot_state(route_wreck_blocked=blocked)
            self.assertEqual(blocked, codec.decode_row(
                codec.encode_row(state), STATIC)['route_wreck_blocked'])


class WreckRouteEvidenceTests(unittest.TestCase):
    def setUp(self):
        fixture = runtime_fixture.BotRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.runtime = fixture.runtime
        self.runtime.battle_start(fixture.start)
        self.runtime.states[11].update(x=0, y=0, z=0)
        from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator
        self.runtime.navigator = TerrainNavigator(lambda *unused: 0.0,
                                                  cell_size=2.0)
        self.grid = self.runtime.navigator.grid
        self.grid.set_static_hulls([(2, 0, 40, 0, 5, 2)])

    def prove(self, mode='route', now=0):
        strategic = dict(combat_mode=mode, route_id='banana', route_index=1,
                         route_anchor=(0, 0, 0), route_join=False,
                         move_position=(0, 0, 100))
        self.runtime._navigation_target(11, (0, 0, 0), (0, 0, 100),
                                        strategic, dict(now=now, speed=0))
        return self.runtime.states[11]['route_wreck_blocked']

    def test_actual_grid_hull_receipt_clears_when_wreck_moves_or_bot_holds(self):
        self.assertTrue(self.prove())
        self.assertFalse(self.prove('artillery_hold', 0.1))
        self.grid.set_static_hulls([(2, 60, 40, 0, 5, 2)])
        self.assertFalse(self.prove(now=0.2))

    def test_parking_approach_reports_wrecks_but_arrived_wait_does_not(self):
        self.assertTrue(self.prove('parking_approach'))
        self.assertFalse(self.prove('hold', .1))
        self.grid.set_static_hulls([])
        self.assertFalse(self.prove('parking_approach', 1.1))

    def test_corner_lane_detects_wreck_outside_straight_goal_ray(self):
        self.assertFalse(self.grid.path_crosses_static_hull(
            [(60, 0, 0), (0, 0, 100)]))
        strategic = dict(combat_mode='route', route_id='banana', route_index=1,
                         route_anchor=(0, 0, 0), route_join=False)
        self.runtime._navigation_target(11, (60, 0, 0), (0, 0, 100),
                                        strategic, dict(now=0, speed=0))
        self.assertTrue(self.runtime.states[11]['route_wreck_blocked'])


if __name__ == '__main__':
    unittest.main()
