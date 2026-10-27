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

    def test_blocked_return_retries_for_the_full_battle_without_route_cooldown(self):
        self.orders(0)
        phases=set()
        for now in range(20,901,20):
            order=self.orders(now)[17]
            phases.add(self.planner._route_recoveries[17]['phase'])
            self.assertEqual('banana',order['route_id'])
            self.assertIsNone(order['throttle_override'])
        self.assertEqual({'forward','skip','return'},phases)

    def test_skip_then_fold_to_start_before_entering_other_lane(self):
        first=self.orders(0);self.orders(19.9);skipped=self.orders(20)
        for bot_id in (17,24):
            self.assertEqual('banana',skipped[bot_id]['route_id'])
            self.assertEqual(first[bot_id]['route_index']+1,skipped[bot_id]['route_index'])
            self.assertEqual('blocked_timeout',skipped[bot_id]['route_point_skip_reason'])
        returned=self.orders(40)
        for bot_id in (17,24):
            self.assertEqual(('banana',0),(returned[bot_id]['route_id'],returned[bot_id]['route_index']))
        for row in self.states[:2]:row.update(x=190,z=74)
        changed=self.orders(41)
        for bot_id in (17,24):
            self.assertEqual(('rail',0),(changed[bot_id]['route_id'],changed[bot_id]['route_index']))
            self.assertEqual('recovery_at_start',changed[bot_id]['route_switch_reason'])
            self.assertEqual('transfer',self.planner._route_recoveries[bot_id]['phase'])

    def test_recovery_orbits_do_not_extend_attempt_budget(self):
        self.orders(0)
        for now in range(1,21):
            self.states[0]['x']=111 if now%2 else 120
            self.states[0]['yaw']=now*.3
            orders=self.orders(now)
        self.assertEqual(2,orders[17]['route_index'])
        self.assertEqual('banana',orders[17]['route_id'])
        self.assertEqual(('banana',0),(self.orders(40)[17]['route_id'],self.orders(40)[17]['route_index']))

    def test_actual_progress_past_next_gate_resets_skip_sequence(self):
        self.lane['waypoints'].append(dict(x=-200,y=0,z=-280))
        self.orders(0);self.orders(20)
        self.states[0].update(x=0,z=-280,route_wreck_blocked=False)
        self.assertEqual(3,self.orders(21)[17]['route_index'])
        self.assertNotIn('blocked_skip_to',self.planner._route_states[17])

    def test_second_blocked_gate_folds_back_instead_of_skipping_again(self):
        self.lane['waypoints'].append(dict(x=-200,y=0,z=-280))
        self.orders(0);self.orders(20)
        self.assertEqual(('banana',0),(self.orders(40)[17]['route_id'],self.orders(40)[17]['route_index']))

    def test_reaching_next_gate_allows_a_fresh_skip_on_later_obstruction(self):
        self.lane['waypoints'].extend([dict(x=-200,y=0,z=-280),dict(x=-400,y=0,z=-280)])
        self.orders(0);self.orders(20)
        self.states[0].update(x=0,z=-280,route_wreck_blocked=False)
        self.orders(21)
        self.states[0]['route_wreck_blocked']=True
        self.orders(22)
        skipped=self.orders(42)[17]
        self.assertEqual(('banana',4),(skipped['route_id'],skipped['route_index']))
        self.assertEqual('blocked_timeout',skipped['route_point_skip_reason'])

    def test_blocker_receipt_changes_keep_the_unfinished_gate_clock(self):
        self.orders(0);self.orders(20)
        self.states[0]['route_wreck_blocked']=False
        self.orders(30)
        self.states[0]['route_wreck_blocked']=True
        self.orders(40)
        self.assertEqual(('banana',0),(self.orders(40)[17]['route_id'],self.orders(40)[17]['route_index']))

    def test_contact_flicker_cannot_renew_an_unmoved_gate(self):
        self.orders(0)
        for now in range(1, 41):
            self.states[0]['route_wreck_blocked'] = bool((now // 7) % 2)
            orders = self.orders(now)
        self.assertEqual(('banana',0),(orders[17]['route_id'],orders[17]['route_index']))

    def test_base_defense_pauses_and_resumes_the_same_gate_budget(self):
        bot = self.planner._alive_bots(self.manifest, self.states)[0]
        self.planner._route_states[17] = dict(route_id='banana', index=1)
        def order(mode):
            return dict(route_id='banana', route_index=1, combat_mode=mode,
                        move_position=self.lane['waypoints'][1])
        self.planner._reroute_wreck_stall(order('route'), bot, self.manifest, 0)
        self.planner._reroute_wreck_stall(order('base_defense'), bot, self.manifest, 12)
        self.planner._reroute_wreck_stall(order('base_defense'), bot, self.manifest, 30)
        resumed = order('route')
        self.planner._reroute_wreck_stall(resumed, bot, self.manifest, 40)
        self.assertEqual(12., resumed['route_attempt']['elapsed'])
        self.planner._reroute_wreck_stall(resumed, bot, self.manifest, 48)
        self.assertEqual('skip_gate', resumed['route_attempt']['action'])

    def test_proved_obstruction_close_to_gate_skips_without_returning(self):
        self.states[0].update(x=190,z=-64)
        self.planner._route_states[17]=dict(route_id='banana',index=1)
        bot=self.planner._alive_bots(self.manifest,self.states)[0]
        order=dict(route_id='banana',route_index=1,combat_mode='route',
                   move_position=self.lane['waypoints'][1])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,0)
        self.planner._reroute_wreck_stall(order,bot,self.manifest,20)
        self.assertEqual(('banana',2),(order['route_id'],order['route_index']))
        self.assertEqual(-64,order['route_anchor']['z'])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,40)
        self.assertEqual(('banana',0),(order['route_id'],order['route_index']))

    def test_missing_owned_pose_or_immobilization_never_switches(self):
        self.states[0]['route_wreck_blocked'] = False
        self.states[0]['world_pose'] = False
        self.states[1]['critical'] = {'destroyed': ['leftTrackHealth']}
        self.orders(0)
        self.assertEqual('banana', self.orders(100)[17]['route_id'])
        self.assertEqual('banana', self.orders(100)[24]['route_id'])

    def test_native_stall_without_wreck_skips_then_returns(self):
        for state in self.states:state['route_wreck_blocked']=False
        first=self.orders(0)[17]
        skipped=self.orders(20)[17]
        self.assertEqual(first['route_index']+1,skipped['route_index'])
        self.assertEqual(('banana',0),(self.orders(40)[17]['route_id'],self.orders(40)[17]['route_index']))

    def test_capture_and_route_transitions_keep_the_failed_gate_budget(self):
        self.states[0]['route_wreck_blocked']=False
        bot=self.planner._alive_bots(self.manifest,self.states)[0]
        self.planner._route_states[17]=dict(route_id='banana',index=1)
        order=dict(route_id='banana',route_index=1,combat_mode='route',
                   move_position=self.lane['waypoints'][1])
        self.planner._reroute_wreck_stall(order,bot,self.manifest,0)
        order.update(combat_mode='base_capture',move_position=dict(x=0,y=0,z=-280))
        self.planner._reroute_wreck_stall(order,bot,self.manifest,20)
        self.assertEqual(2,order['route_index'])
        order['combat_mode']='base_capture'
        self.planner._reroute_wreck_stall(order,bot,self.manifest,40)
        self.assertEqual('return_to_anchor',order['route_attempt']['action'])
        self.assertEqual(0,order['route_index'])

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
        self.planner._reroute_wreck_stall(order,bot,self.manifest,39)
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

    def test_switch_joins_first_point_and_discards_stale_lane_history(self):
        self.planner._route_history[17]={'rail':dict(index=2,parking_completed={0})}
        self.orders(0);self.orders(20);self.orders(40)
        self.states[0].update(x=190,z=74)
        order=self.orders(41)[17]
        self.assertEqual(('rail',0),(order['route_id'],order['route_index']))
        self.states[0].update(x=100,z=100)
        order=self.orders(42)[17]
        self.assertEqual(('rail',1),(order['route_id'],order['route_index']))
        self.assertNotIn(0,self.planner._route_states[17].get('parking_completed',()))

    def test_artillery_only_server_order_cannot_bypass_worker_sortie_reservations(self):
        bot=self.planner._alive_bots(self.manifest,self.states)[0]
        bot['profile']['class_tag']='SPG'
        target=dict(id='enemy',point=dict(x=0,y=0,z=-280),radius=50)
        order=self.planner._order_for(bot,0,1,None,[],0,team_bots=[bot],
            capture_target=target,no_known_enemies=True)
        self.assertEqual('artillery_deploy',order['combat_mode'])
        self.assertNotEqual(target['point'],order['move_position'])

    def test_artillery_with_living_regulars_retains_its_staging_policy(self):
        bots=self.planner._alive_bots(self.manifest,self.states)
        bot=bots[0];bot['profile']['class_tag']='SPG'
        target=dict(id='enemy',point=dict(x=0,y=0,z=-280),radius=50)
        order=self.planner._order_for(bot,0,len(bots),None,[],0,team_bots=bots,
            capture_target=target,no_known_enemies=True)
        self.assertNotEqual('base_capture',order['combat_mode'])

    def test_no_suitable_route_retries_and_newly_eligible_lane_requires_return(self):
        self.bypass['class_weights']={'heavyTank':0,'AT-SPG':0}
        self.orders(0);self.orders(20);self.orders(40)
        self.states[0].update(x=190,z=74)
        order=self.orders(41)[17]
        self.assertEqual('banana',order['route_id'])
        self.assertEqual('retry_no_alternative',order['route_attempt']['action'])
        self.bypass['class_weights']={'heavyTank':1,'AT-SPG':1}
        self.states[0].update(x=120,z=-28)
        self.orders(61);self.orders(81);self.orders(101)
        self.states[0].update(x=190,z=74)
        self.assertEqual('rail',self.orders(102)[17]['route_id'])

    def test_combat_hold_and_explicit_command_pause_the_existing_clock(self):
        for extra in ({'combat_mode':'engage'},{'throttle_override':0},{'team_command':'STAY'}):
            self.planner._route_recoveries.clear();self.planner._wreck_route_progress.clear()
            bot=self.planner._alive_bots(self.manifest,self.states)[0]
            order=dict(route_id='banana',route_index=1,combat_mode='route',move_position=self.lane['waypoints'][1])
            self.planner._reroute_wreck_stall(order,bot,self.manifest,0)
            held=dict(order,**extra)
            self.planner._reroute_wreck_stall(held,bot,self.manifest,10)
            self.assertIn(17,self.planner._wreck_route_progress)
            self.assertEqual(10.,held['route_attempt']['elapsed'])
            self.assertEqual('banana',held['route_id'])

    def test_advance_contact_pauses_instead_of_erasing_unfinished_attempt(self):
        self.orders(0)
        bot=self.planner._alive_bots(self.manifest,self.states)[0]
        held=dict(route_id='banana',route_index=1,combat_mode='advance_contact')
        self.planner._reroute_wreck_stall(held,bot,self.manifest,10)
        self.assertEqual('pause_advance_contact',held['route_attempt']['action'])
        self.assertIn(17,self.planner._wreck_route_progress)
        self.orders(15)
        self.assertEqual('blocked_timeout',self.orders(25)[17]['route_point_skip_reason'])
        self.assertEqual(('banana',0),(self.orders(45)[17]['route_id'],self.orders(45)[17]['route_index']))

    def test_round_reset_clears_stall_and_rejected_routes(self):
        self.orders(0)
        self.orders(20)
        self.planner.reset(2)
        self.assertEqual({}, self.planner._wreck_route_progress)
        self.assertEqual({}, self.planner._wreck_route_avoid)
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
