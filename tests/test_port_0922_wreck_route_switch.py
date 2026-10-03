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

    def test_reported_vk_and_t95_switch_only_after_twenty_seconds(self):
        self.assertEqual('banana', self.orders(0)[17]['route_id'])
        self.assertEqual('banana', self.orders(19.9)[24]['route_id'])
        orders = self.orders(20)
        for bot_id in (17, 24):
            self.assertEqual('rail', orders[bot_id]['route_id'])
            self.assertEqual('wreck_stall', orders[bot_id]['route_switch_reason'])
            self.assertNotEqual(self.lane['waypoints'][1],
                                orders[bot_id]['move_position'])
        # The alternative remains available even after its original Bot dies.
        self.states[2].update(alive=False, health=0)
        self.assertEqual('rail', self.orders(200)[17]['route_id'])

    def test_real_progress_and_detour_travel_restart_the_wait(self):
        self.orders(0)
        self.states[0]['z'] -= 4
        self.states[1]['x'] -= 9  # A legitimate bypass can initially go away.
        self.orders(19)
        self.assertEqual('banana', self.orders(20)[17]['route_id'])
        self.assertEqual('banana', self.orders(20)[24]['route_id'])
        self.assertEqual('rail', self.orders(39)[17]['route_id'])

    def test_jitter_or_chassis_turn_does_not_count_as_progress(self):
        self.orders(0)
        for now in range(1, 21):
            self.states[0]['x'] = 120 + (0.5 if now % 2 else -0.5)
            self.states[0]['yaw'] = now * 0.3
            orders = self.orders(now)
        self.assertEqual('rail', orders[17]['route_id'])

    def test_missing_wreck_evidence_or_immobilization_never_switches(self):
        self.states[0]['route_wreck_blocked'] = False
        self.states[1]['critical'] = {'destroyed': ['leftTrackHealth']}
        self.orders(0)
        self.assertEqual('banana', self.orders(100)[17]['route_id'])
        self.assertEqual('banana', self.orders(100)[24]['route_id'])

    def test_no_suitable_route_holds_and_does_not_oscillate(self):
        self.bypass['class_weights'] = {'heavyTank': 0, 'AT-SPG': 0}
        self.orders(0)
        self.assertEqual('banana', self.orders(100)[17]['route_id'])
        self.bypass['class_weights'] = {'heavyTank': 1, 'AT-SPG': 1}
        orders = self.orders(120)
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
