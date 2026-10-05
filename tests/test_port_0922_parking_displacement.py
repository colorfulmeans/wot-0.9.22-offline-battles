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
