"""Occupied authoring places and external shoves through production orders."""
import copy
import unittest
from unittest import mock
import test_port_0922_wait_parking as waits
import test_port_0922_spg_initial_positions as spgs
import test_port_0922_withdrawal_runtime as withdrawal
import test_port_0922_bot_runtime as harness
from test_port_0922_server_bot_ai import _state, _bot, _route, _contact
from server_bot_ai import BotPlanner


class WaitDisplacementTests(unittest.TestCase):
    def setUp(self):
        self.fixture = waits.WaitParkingTests()
        self.planner, self.manifest = self.fixture.setup_parking()
        self.manifest = self.manifest[:1]
        self.states = [_state(11, 1, -40, 0)]

    def orders(self, now, players=()):
        return self.planner.build_orders(self.manifest, self.states, players, now)['orders'][0]

    def human(self, x=0, player_id=11):
        return dict(_state(player_id, 1, x, 0), collision_shape=(1.7, 3.5, -.8, 2.))

    def test_human_identity_can_equal_bot_identity_and_occupy_first_slot(self):
        order = self.orders(1, [self.human()])
        self.assertEqual(1, order['parking_slot'])
        self.assertEqual(20, order['move_position']['x'])

    def test_player_entering_a_leased_destination_reassigns_before_arrival(self):
        self.assertEqual(0, self.orders(1)['parking_slot'])
        self.assertEqual(1, self.orders(2, [self.human()])['parking_slot'])

    def test_wreck_entering_lease_reassigns_and_full_group_uses_parent(self):
        self.assertEqual(0, self.orders(1)['parking_slot'])
        wreck = dict(self.human(), alive=False, health=0)
        self.assertEqual(1, self.orders(2, [wreck])['parking_slot'])
        wrecks = [dict(wreck, id=i, x=x) for i, x in enumerate((0, 20, 40), 1)]
        full = self.orders(3, wrecks)
        self.assertNotIn('parking_phase', full)
        self.assertEqual(0, full['move_position']['x'])
        self.assertIsNone(full['throttle_override'])
        self.assertNotIn('parking_slot', self.orders(4, wrecks[::2]))

    def test_all_occupied_uses_parent_without_later_reacquiring_slot(self):
        players = [self.human(x, i) for i, x in enumerate((0, 20, 40), 1)]
        order = self.orders(1, players)
        self.assertNotIn('parking_phase', order)
        self.assertEqual(0, order['move_position']['x'])
        self.assertIsNone(order['throttle_override'])
        self.assertNotIn('parking_slot', self.orders(2, players[::2]))
        self.states[0]['x']=0
        self.assertEqual(1,self.orders(3,players[::2])['route_index'])

    def test_chassis_size_and_separate_floor_affect_occupancy(self):
        human = self.human(-10)
        human['collision_shape'] = (2, 8, -.8, 2.)
        self.assertEqual(1, self.orders(1, [human])['parking_slot'])
        human['y'] = 20
        self.setUp()
        self.assertEqual(0, self.orders(2, [human])['parking_slot'])

    def test_small_shove_keeps_clock_holds_current_pose_and_can_aim(self):
        self.states[0]['x'] = 0
        self.orders(1)
        self.states[0]['x'] = 4
        contact = _contact(2, 100, 0, [11])
        players = [dict(self.human(), id=2, team=2, x=100)]
        self.planner.report_contacts([contact], self.planner.known_targets(self.states, players), 6)
        order = self.orders(6, players)
        self.assertEqual('waiting', order['parking_phase'])
        self.assertEqual(4, order['move_position']['x'])
        self.assertEqual(0, order['throttle_override'])
        self.assertEqual(2, order['target_id'])
        self.assertTrue(order['fire_allowed'])
        self.assertEqual(1, self.orders(11)['route_index'])

    def test_large_or_vertical_shove_redeploys_without_resetting_wait_clock(self):
        for pose in (dict(x=12), dict(x=4, y=-12), dict(x=4, airborne=True)):
            with self.subTest(pose=pose):
                self.setUp()
                self.states[0]['x'] = 0
                self.orders(1)
                self.states[0].update(pose)
                self.assertEqual('approach', self.orders(6)['parking_phase'])
                self.assertEqual(1, self.planner._route_states[11]['parking_arrived'][0])
                self.assertEqual(1, self.orders(11)['route_index'])


class SPGDisplacementTests(unittest.TestCase):
    setUp = spgs.InitialPositionIntegrationTests.setUp
    tearDown = spgs.InitialPositionIntegrationTests.tearDown
    _runtime = spgs.InitialPositionIntegrationTests._runtime
    _fixture_bot = spgs.InitialPositionIntegrationTests._fixture_bot
    def test_occupied_manual_zone_tries_same_zone_before_another(self):
        runtime = self._runtime()
        runtime.baked_graph = spgs._graph()
        cfg, planning = self.module.bot_tactics, self.module.bot_tactics_runtime
        raw = cfg.empty('Occupied parking')
        raw['maps']['08_ruinberg'] = dict(mode='regular',
            resource_sha256=cfg.MAPS['08_ruinberg']['resource_sha256'], routes=[], positions=[
                dict(id='home', label='Home', team=1, point=[-106, 346], radius=36, heading=180, priority=1),
                dict(id='other', label='Other', team=1, point=[-170, 346], radius=24, heading=180, priority=9)])
        runtime._bot_tactics = cfg.canonical(raw)
        state = spgs._states(runtime.baked_graph, 1)[0]
        plans, unused = planning.assign_manual_positions(runtime._bot_tactics, '08_ruinberg', runtime.baked_graph, [state], preferred_zone='home')
        state['_spg_initial'] = plans[state['id']]
        self.assertEqual('home', state['_spg_initial']['zone'])
        runtime.states = {state['id']: state}
        old = copy.deepcopy(state['_spg_initial'])
        human = dict(id=1, team=2, world_pose=True, alive=True, **old['point'])
        runtime._contact_players = [human]
        with mock.patch.object(runtime, '_player_collision_profile', return_value={'shape': (1.7, 3.5, -.8, 2.)}):
            order = runtime._artillery_position_order(state, {'combat_mode': 'artillery_deploy'}, {}, 1)
        self.assertEqual('home', state['_spg_initial']['zone'])
        self.assertNotEqual(old['point'], state['_spg_initial']['point'])
        self.assertIsNone(order['throttle_override'])

    def test_no_free_parking_holds_and_rechecks_when_body_leaves(self):
        runtime = self._runtime()
        plan, bot, state = self._fixture_bot(40)
        state.update(_spg_initial=plan, profile={'class_tag': 'SPG'})
        runtime.states = {11: state}
        runtime._contact_players = [dict(id=1, alive=True, world_pose=True, **plan['point'])]
        with mock.patch.object(runtime, '_player_collision_profile', return_value={'shape': (1.7, 3.5, -.8, 2.)}), \
                mock.patch.object(self.module.spg_positions, 'assign_initial_positions', return_value=({}, {})) as select:
            order = runtime._artillery_position_order(state, {'combat_mode': 'artillery_deploy', 'fire_allowed': True}, {}, 1)
            self.assertEqual('artillery_hold', order['combat_mode'])
            self.assertEqual(0, order['throttle_override'])
            self.assertTrue(order['fire_allowed'])
            runtime._artillery_position_order(state, {'combat_mode': 'artillery_deploy'}, {}, 1.2)
            self.assertEqual(1, select.call_count)
            runtime._contact_players = []
            order = runtime._artillery_position_order(state, {'combat_mode': 'artillery_deploy'}, {}, 2.1)
            self.assertEqual('artillery_deploy', order['combat_mode'])
        self.assertEqual(plan, state['_spg_initial'])

    def test_arrived_spg_shoved_inside_safe_area_keeps_firing_pose(self):
        runtime = self._runtime()
        runtime.baked_graph = spgs._graph()
        plan, bot, state = self._fixture_bot(0)
        state.update(_spg_initial=plan, profile={'class_tag': 'SPG'}, y=plan['point']['y'])
        runtime.states = {11: state}
        order = dict(combat_mode='artillery_hold', target_id=2, fire_allowed=True)
        runtime._artillery_position_order(state, order, {}, 1)
        state['x'] += 4
        result = runtime._artillery_position_order(state, order, {}, 2.1)
        self.assertEqual('artillery_hold', result['combat_mode'])
        self.assertEqual(tuple(state[k] for k in ('x', 'y', 'z')), result['move_position'])
        self.assertTrue(result['fire_allowed'])
        self.assertEqual(plan, state['_spg_initial'])
        state['y'] -= 10
        self.assertEqual('artillery_deploy', runtime._artillery_position_order(state, order, {}, 3.2)['combat_mode'])


class RetreatEndpointTests(unittest.TestCase):
    def test_hit_memory_expiry_keeps_endpoint_then_arrival_and_pause_release_it(self):
        planner = BotPlanner()
        state = _state(11, 1, 0, 100)
        bot = _bot(11, 1, 0, _route('road', [(0, 0, False), (0, 100, False), (0, 200, False)]), 'AT-SPG')
        planner._route_states[11] = dict(route_id='road', index=1)
        actor = dict(bot, state=state)
        planner._apply_retreat_order({}, actor, dict(x=0, y=0, z=0), dict(x=0, y=0, z=200), 1, 'under_fire_withdraw', 'under_fire_hold')
        order = planner.build_orders([bot], [state], [], 8)['orders'][0]
        self.assertEqual('under_fire_withdraw', order['combat_mode'])
        self.assertEqual(0, order['move_position']['z'])
        state['z'] = 4
        order = planner.build_orders([bot], [state], [], 9)['orders'][0]
        self.assertEqual('under_fire_hold', order['tactical_phase'])
        self.assertEqual(0, order['throttle_override'])
        self.assertEqual('route', planner.build_orders([bot], [state], [], 25)['orders'][0]['combat_mode'])


class OccupiedTravelPointTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.runtime = self.fixture.module.BotRuntime(1, baked_graph=harness._flat_open_graph())
        from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator
        self.runtime.navigator = TerrainNavigator(lambda *args: 0., baked_graph=harness._flat_open_graph())
        self.runtime.states = {11: dict(id=11, team=1, x=0, y=0, z=0,
            half_length=3.5, half_width=1.7, profile={'class_tag': 'AT-SPG'},
            collision_shape=(1.7, 3.5, -.8, 2.), alive=True)}
        self.runtime.adapter = self.fixture.module.BotAdapter('01_karelia', 1)
        self.goal = (0, 0, 20)
        self.order = dict(combat_mode='route', move_position=self.goal, route_anchor=(0, 0, 0),
            route_id='road', route_index=1, route_join=False, throttle_override=None)

    def tearDown(self):self.fixture.tearDown()

    def test_player_on_waypoint_uses_safe_temporary_goal_and_leaving_restores_it(self):
        self.runtime._contact_players = [dict(id=1, team=1, world_pose=True, x=0, y=0, z=20)]
        with mock.patch.object(self.runtime, '_player_collision_profile', return_value={'shape': (1.7, 3.5, -.8, 2.)}):
            selected = self.runtime._navigation_target(11, (0, 0, 0), self.goal, self.order, dict(now=1, speed=0))
        self.assertNotEqual(self.goal, selected)
        self.assertGreater(abs(selected[0]), 8)
        self.assertTrue(self.runtime.states[11]['route_wreck_blocked'])
        self.assertEqual(self.goal, self.order['move_position'])
        self.runtime._contact_players = []
        selected = self.runtime._navigation_target(11, (0, 0, 0), self.goal, self.order, dict(now=2.1, speed=0))
        self.assertEqual(self.goal, selected)
        self.assertFalse(self.runtime.states[11]['route_wreck_blocked'])

    def test_wreck_on_waypoint_bypasses_without_mutating_authored_goal(self):
        self.runtime.states[12] = dict(id=12, team=1, alive=False, x=0, y=0, z=20,
            collision_shape=(1.7, 3.5, -.8, 2.), half_length=3.5, half_width=1.7)
        self.runtime._publish_static_hulls([])
        selected = self.runtime._navigation_target(11, (0, 0, 0), self.goal, self.order, dict(now=1, speed=0))
        self.assertNotEqual(self.goal, selected)
        self.assertTrue(self.runtime.navigator.grid.dry_segment_clear((0, 0, 0), selected, 1))
        self.assertEqual(self.goal, self.order['move_position'])

    def test_wait_approach_never_uses_travel_point_bypass(self):
        self.runtime._contact_players = [dict(id=1, team=1, world_pose=True, x=0, y=0, z=20)]
        with mock.patch.object(self.runtime, '_player_collision_profile', side_effect=AssertionError('travel bypass invoked')):
            self.runtime._navigation_target(11, (0, 0, 0), self.goal,
                dict(self.order, combat_mode='parking_approach'), dict(now=1, speed=0))


class ShortRetreatRuntimeTests(unittest.TestCase):
    setUp = withdrawal.RuntimeWithdrawalTests.setUp
    tearDown = withdrawal.RuntimeWithdrawalTests.tearDown
    contact_runtime = withdrawal.RuntimeWithdrawalTests.contact_runtime

    def test_long_retreat_recovery_and_wide_target_keep_movement_ownership(self):
        aim = self.fixture.module.ai_driver.combat_hull_aim
        for mode, allow, yaw in (('reverse_withdraw', False, .2),
                ('reverse_withdraw', True, 1.), ('blocked', True, .2)):
            self.assertEqual((-.2, -.72, False), aim(
                0, yaw, -.1, .1, -.2, -.72, mode, True,
                combat_mode='under_fire_withdraw', movement_intent=True,
                withdrawal_aim=allow))

    def test_fixed_gun_lays_and_fires_while_short_reverse_escape_progresses(self):
        runtime = self.contact_runtime((100, 0, 100), 'route')
        runtime.visibility_probe = lambda *args: True
        runtime.firing_lane_probe = lambda *args: True
        runtime._apply_orders(dict(bot_order_revision=2, bot_orders=[dict(
            id=11, team=2, combat_mode='under_fire_withdraw', target_kind='human', target_id=2,
            move_position=(0, 0, -20), aim_position=(20, 0, 100), face_position=(20, 0, 100),
            fire_range=500, fire_allowed=True, throttle_override=None)]))
        player = harness._admit_player(dict(id=2, team=1, alive=True, x=20, y=0, z=100))
        import contextlib
        import io
        aimed = False
        with contextlib.redirect_stdout(io.StringIO()):
            for frame in range(1, 91):
                runtime.update(.05, frame*.05, players=[player])
                aimed = aimed or runtime.states[11]['hull_aiming']
        self.assertTrue(aimed)
        self.assertLess(runtime.states[11]['z'], -5)
        self.assertGreater(runtime.states[11]['fire_seq'], 0)
        self.assertLess(abs(runtime.states[11]['yaw']), .5)


class SPGFirePositionTests(unittest.TestCase):
    setUp = spgs.InitialPositionIntegrationTests.setUp
    tearDown = spgs.InitialPositionIntegrationTests.tearDown
    _runtime = spgs.InitialPositionIntegrationTests._runtime

    def fixture(self, radius=36, alternate=True):
        import types
        runtime = self._runtime()
        runtime.baked_graph = spgs._graph()
        cfg, planning = self.module.bot_tactics, self.module.bot_tactics_runtime
        raw = cfg.empty('Blocked fire parking')
        zones = [dict(id='home', label='Home', team=1, point=[-106,346],
                      radius=radius, heading=180, priority=1)]
        if alternate:
            zones.append(dict(id='other', label='Other', team=1, point=[-170,346],
                              radius=24, heading=180, priority=9))
        raw['maps']['08_ruinberg'] = dict(mode='regular',
            resource_sha256=cfg.MAPS['08_ruinberg']['resource_sha256'], routes=[], positions=zones)
        runtime._bot_tactics = cfg.canonical(raw)
        state = spgs._states(runtime.baked_graph, 1)[0]
        plans, unused = planning.assign_manual_positions(runtime._bot_tactics,
            '08_ruinberg', runtime.baked_graph, [state], preferred_zone='home')
        state['_spg_initial'] = plans[state['id']]
        state.update(state['_spg_initial']['point'])
        state.update(fire_seq=0, airborne=False, _overturned=False)
        runtime.states = {state['id']:state}
        target = dict(id=99, network_id=99, kind='human', alive=True)
        order = dict(combat_mode='artillery_hold', fire_allowed=True, target_id=99,
                     move_position=tuple(state[k] for k in ('x','y','z')))
        gun = types.SimpleNamespace(ready=lambda factor: True)
        ammo = types.SimpleNamespace(can_fire=lambda: True)
        return runtime,state,target,order,gun,ammo

    def observe(self, fixture, now, planning=None, **changes):
        runtime,state,target,order,gun,ammo = fixture
        runtime._observe_spg_fire_position(state, dict(order,**changes), target,
            planning or dict(state='failed',reason='world_blocked',local_blockage=False,completed=now),
            gun,ammo,1.0,now)

    def fail_for_30_seconds(self, fixture):
        for now in range(31):self.observe(fixture,float(now))

    def test_far_blockage_relocates_inside_same_authored_zone_first(self):
        fixture = self.fixture(); runtime,state,target,order,gun,ammo=fixture
        original=copy.deepcopy(state['_spg_initial']); pose=tuple(state[k] for k in ('x','y','z'))
        self.fail_for_30_seconds(fixture)
        result=runtime._artillery_position_order(state,order,{99:target},30.0)
        self.assertEqual('home',state['_spg_initial']['zone'])
        self.assertNotEqual(original['point'],state['_spg_initial']['point'])
        self.assertEqual('artillery_deploy',result['combat_mode'])
        self.assertEqual('fire_position_same_zone',state['_spg_position_event'])
        self.assertEqual(pose,tuple(state[k] for k in ('x','y','z')))
        self.assertFalse(result['fire_allowed'])
        self.assertIsNone(result['target_id'])
        state.update(state['_spg_initial']['point'])
        arrived=runtime._artillery_position_order(state,order,{99:target},31.0)
        self.assertEqual('artillery_hold',arrived['combat_mode'])
        self.assertTrue(arrived['fire_allowed'])
        self.assertEqual(99,arrived['target_id'])
        self.assertFalse(runtime._artillery_intents)

    def test_exhausted_small_zone_selects_another_authored_position(self):
        fixture=self.fixture(radius=12);runtime,state,target,order,gun,ammo=fixture
        self.fail_for_30_seconds(fixture)
        runtime._artillery_position_order(state,order,{99:target},30.0)
        self.assertEqual('other',state['_spg_initial']['zone'])
        self.assertEqual('fire_position_other_zone',state['_spg_position_event'])

    def test_no_safe_alternate_keeps_attack_permission_and_bounded_retry(self):
        fixture=self.fixture(radius=12,alternate=False);runtime,state,target,order,gun,ammo=fixture
        original=state['_spg_initial'];self.fail_for_30_seconds(fixture)
        result=runtime._artillery_position_order(state,order,{99:target},30.0)
        self.assertIs(original,state['_spg_initial'])
        self.assertEqual('artillery_hold',result['combat_mode'])
        self.assertTrue(result['fire_allowed'])
        self.assertEqual('fire_position_no_safe_alternate',state['_spg_position_event'])
        with mock.patch.object(self.module.bot_tactics_runtime,'assign_manual_positions') as select:
            runtime._artillery_position_order(state,order,{99:target},31.0)
        select.assert_not_called()

    def test_reload_no_target_no_permission_and_pending_do_not_count(self):
        fixture=self.fixture();runtime,state,target,order,gun,ammo=fixture
        self.observe(fixture,0.0)
        for now in range(1,61):
            self.observe(fixture,float(now),dict(state='pending'))
        self.assertNotIn('_spg_fire_position_failure',state)
        self.observe(fixture,61.0,fire_allowed=False)
        self.assertNotIn('_spg_fire_position_failure',state)
        gun.ready=lambda factor:False
        self.observe(fixture,62.0)
        self.assertNotIn('_spg_fire_position_failure',state)
        gun.ready=lambda factor:True;fixture=(runtime,state,None,order,gun,ammo)
        self.observe(fixture,63.0)
        self.assertNotIn('_spg_fire_position_failure',state)

    def test_nominal_clear_success_and_new_position_retire_failed_episode(self):
        fixture=self.fixture();runtime,state,target,order,gun,ammo=fixture
        for now in range(10):self.observe(fixture,float(now))
        runtime._observe_spg_fire_position(state,order,target,dict(state='clear'),
            gun,ammo,1.0,10.0,dict(state='clear'))
        self.assertNotIn('_spg_fire_position_failure',state)
        self.observe(fixture,11.0);state['fire_seq']=1
        self.observe(fixture,12.0)
        self.assertEqual(0.0,state['_spg_fire_position_failure']['elapsed'])
        state['x']+=3
        self.observe(fixture,13.0)
        self.assertEqual(0.0,state['_spg_fire_position_failure']['elapsed'])

    def test_single_random_launch_failure_cannot_relocate(self):
        fixture=self.fixture();runtime,state,target,order,gun,ammo=fixture
        state['_spg_launch_failure']=dict(reason='world_blocked',launch_failed=True,completed=0.0)
        state['_spg_launch_failure_target']=runtime._observer_target_key(target)
        for now in range(3):self.observe(fixture,float(now),dict(state='clear'))
        episode=state['_spg_fire_position_failure']
        self.assertEqual(1,len(episode['proofs']))
        for now in range(3,60):self.observe(fixture,float(now),dict(state='clear'))
        self.assertNotIn('_spg_fire_position_failure',state)
        original=state['_spg_initial']
        self.assertIs(original,runtime._retry_spg_fire_position(state,original,59.0))
        self.assertNotIn('_spg_fire_failed_parking',state)

    def test_repeated_failures_across_pending_proofs_reach_bounded_switch(self):
        fixture=self.fixture();runtime,state,target,order,gun,ammo=fixture
        for now in range(41):
            proof=(dict(state='failed',reason='world_blocked',completed=float(now))
                   if now in (0,20,40) else dict(state='pending'))
            self.observe(fixture,float(now),proof)
        self.assertEqual(40.0,state['_spg_fire_position_failure']['elapsed'])
        self.assertEqual(3,len(state['_spg_fire_position_failure']['proofs']))
        result=runtime._artillery_position_order(state,order,{99:target},40.0)
        self.assertEqual('artillery_deploy',result['combat_mode'])

    def test_stale_target_failure_cannot_start_a_position_episode(self):
        fixture=self.fixture();runtime,state,target,order,gun,ammo=fixture
        state['_spg_launch_failure']=dict(reason='world_blocked',launch_failed=True,completed=10.0)
        state['_spg_launch_failure_target']=('human',88)
        self.observe(fixture,10.0,dict(state='clear'))
        self.assertNotIn('_spg_fire_position_failure',state)

    def test_missing_current_fire_permission_cannot_trigger_position_selection(self):
        fixture=self.fixture();runtime,state,target,order,gun,ammo=fixture
        self.fail_for_30_seconds(fixture)
        original=state['_spg_initial']
        result=runtime._artillery_position_order(state,dict(order,fire_allowed=False),{99:target},30.0)
        self.assertIs(original,state['_spg_initial'])
        self.assertFalse(result['fire_allowed'])


    def test_wreck_occupied_alternate_is_not_selected(self):
        fixture=self.fixture(radius=12);runtime,state,target,order,gun,ammo=fixture
        runtime.states[91]=dict(id=91,team=1,x=-170.0,y=3.406,z=346.0,
                               alive=False,collision_shape=(20,20,0,2))
        original=state['_spg_initial'];self.fail_for_30_seconds(fixture)
        runtime._artillery_position_order(state,order,{99:target},30.0)
        self.assertIs(original,state['_spg_initial'])
        self.assertEqual('fire_position_no_safe_alternate',state['_spg_position_event'])


    def test_relocation_does_not_override_base_defense(self):
        fixture=self.fixture();runtime,state,target,order,gun,ammo=fixture
        original=state['_spg_initial'];self.fail_for_30_seconds(fixture)
        defense=dict(order,combat_mode='base_defense')
        self.assertEqual(defense,runtime._artillery_position_order(state,defense,{99:target},30.0))
        self.assertIs(original,state['_spg_initial'])
