"""Recorded El Hallouf target rewrite and private wait-recovery ownership."""
import json
import math
import types
import unittest
from unittest import mock

import test_port_0922_bot_runtime as fixtures


class NavigationWaitLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BotRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.module = self.fixture.module
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid, TerrainNavigator
        self.grid_type, self.navigator_type = TerrainGrid, TerrainNavigator

    def recorded_runtime(self, alive=True):
        graph = json.loads((fixtures.ROOT / 'navgraphs/29_el_hallouf.json').read_text())
        grid = self.grid_type(lambda *args: 0.0, baked_graph=graph)
        grid.ground_probe = lambda x, z, y: grid._baked_cell_height(grid.cell_for((x, y, z)))
        runtime = self.module.BotRuntime.__new__(self.module.BotRuntime)
        runtime.navigator = types.SimpleNamespace(grid=grid)
        runtime._contact_players = []
        runtime._server_orders = {}
        runtime.states = {}
        for identity, pose, shape, living in (
                (22, (213.9065696716982, 13.225835800170898, -69.01506734746917),
                 (1.8550790548324585, 3.461872100830078), True),
                (21, (219.44847325776732, 16.261442184448242, -57.24761416152669),
                 (1.499140977859497, 2.629296064376831), alive),
                (7, (224.7323658488371, 16.404083251953125, -59.47811210063265),
                 (1.819651, 3.382535), False),
                (6, (229.2231835038136, 16.279024124145508, -64.74885919868326),
                 (1.622931, 2.952724), False)):
            runtime.states[identity] = dict(id=identity, x=pose[0], y=pose[1], z=pose[2],
                half_width=shape[0], half_length=shape[1], collision_shape=shape, alive=living)
        return runtime

    def test_recorded_live_bat_does_not_rewrite_e50m_corner(self):
        runtime = self.recorded_runtime()
        own = runtime.states[22]
        pose = (own['x'], own['y'], own['z'])
        target = (214.0, 14.84, -62.0)
        self.assertIsNone(runtime._occupied_route_target(22, pose, target, 0.0, True))
        self.assertFalse(own.get('route_wreck_blocked', False))
        # The same living hull must remain solid for actual parking selection.
        self.assertEqual(3, len(runtime._physical_parking_occupancy(own)))
        self.assertEqual(2, len(runtime._physical_parking_occupancy(own, travel=True)))

    def test_wreck_or_authored_hold_remains_an_occupied_travel_point(self):
        for held in (False, True):
            runtime = self.recorded_runtime(alive=held)
            if held:
                runtime._server_orders[21] = {'parking_phase': 'waiting'}
            own = runtime.states[22]
            pose = (own['x'], own['y'], own['z'])
            result = runtime._occupied_route_target(22, pose, (214.0, 14.84, -62.0), 0.0, True)
            self.assertTrue(own['route_wreck_blocked'])
            if result is not None:
                self.assertGreater(math.hypot(result[0]-pose[0], result[2]-pose[2]), 1.5)

    def test_replan_retires_private_paths_but_keeps_shared_paths_and_failures(self):
        nav = self.navigator_type(lambda *args: 0.0, baked_graph=fixtures._flat_open_graph())
        keys = [(('route', 1, 'lane'), (15, 15)),
                (('recovery', 11, 1), (15, 15)),
                (('recovery', 12, 1), (15, 15))]
        for key in keys:
            nav.paths[key] = [(0.0, 0.0, 0.0), (0.0, 0.0, 12.0)]
            nav.path_times[key] = 0.0
        nav.bot_states[11] = {'last_target': (0.0, 0.0, 10.0)}
        nav.bot_failed_edges[11] = {'retained_evidence': (100.0, 1.0)}
        nav.request_replan(11, (1.0, 0.0, -3.0), 5.0)
        self.assertIn(keys[0], nav.paths)
        self.assertNotIn(keys[1], nav.paths)
        self.assertIn(keys[2], nav.paths)
        self.assertIn('retained_evidence', nav.bot_failed_edges[11])
        self.assertEqual((1.0, 0.0, -3.0), nav.bot_states[11]['recovery_start'])

    def test_escape_target_survives_pose_changes_but_not_a_new_obstacle(self):
        nav = self.navigator_type(lambda *args: 0.0, baked_graph=fixtures._flat_open_graph())
        goal, first = (0.0, 0.0, 30.0), (3.0, 0.0, 5.0)
        state = {}
        with mock.patch.object(nav.grid, 'safe_local_target', side_effect=[first, (-3.0, 0.0, 5.0)]) as choose:
            self.assertEqual(first, nav._safe_fallback_target(11, (0.0, 0.0, 0.0), goal, 1.0, (), state))
            self.assertEqual(first, nav._safe_fallback_target(11, (0.1, 0.0, 0.0), goal, 2.0, (), state))
            self.assertEqual(1, choose.call_count)
            with mock.patch.object(nav.grid, 'dry_segment_clear', return_value=False):
                self.assertEqual((-3.0, 0.0, 5.0), nav._safe_fallback_target(
                    11, (0.1, 0.0, 0.0), goal, 2.1, (), state))

    def test_retired_search_cannot_overwrite_replacement_or_publish_stale_path(self):
        nav = self.navigator_type(lambda *args: 0.0, baked_graph=fixtures._flat_open_graph())
        key = (('recovery', 11, 1), (15, 15))
        old = types.SimpleNamespace(result=[(0.0, 0.0, 12.0)], hull_revision=0)
        replacement = object()
        nav.searches[key] = replacement
        nav.bot_states[11] = {'pending_prefix_search': old}
        nav._finish_search(key, old, 2.0)
        self.assertIs(replacement, nav.searches[key])
        self.assertNotIn(key, nav.paths)
        self.assertIsNone(nav.bot_states[11].get('pending_prefix_search'))

    def issued_exit(self):
        nav = self.navigator_type(lambda *args: 0.0, baked_graph=fixtures._flat_open_graph())
        current, goal, local = (0.0, 0.0, 0.0), (0.0, 0.0, 30.0), (3.0, 0.0, 5.0)
        request = ('local', 11, 'route')
        nav.next_target(11, current, goal, request, 0.0)
        state = nav.bot_states[11]
        nav._remember_local_fallback(local, goal, state, current)
        state['last_target'] = local
        return nav, current, goal, local, request

    def test_complete_path_cannot_steal_unfinished_local_exit(self):
        nav, current, goal, local, request = self.issued_exit()
        for frame in range(1, 21):
            pose = (0.1 * (frame % 2), 0.0, 0.0)
            self.assertEqual(local, nav.next_target(11, pose, goal, request, frame * 0.1))
        # Finishing the fixed leg permits the ready complete path immediately.
        self.assertNotEqual(local, nav.next_target(11, local, goal, request, 2.1))

    def test_safety_veto_and_new_order_retire_local_exit(self):
        nav, current, goal, local, request = self.issued_exit()
        original = nav.grid.dry_segment_clear
        with mock.patch.object(nav.grid, 'dry_segment_clear',
                side_effect=lambda a, b, *args: False if b == local else original(a, b, *args)):
            self.assertNotEqual(local, nav.next_target(11, current, goal, request, 0.1))
        nav, current, goal, local, request = self.issued_exit()
        self.assertNotEqual(local, nav.next_target(
            11, current, (0.0, 0.0, -30.0), ('local', 11, 'retreat'), 0.1))

    def test_stalled_exit_times_out_without_reselecting_that_same_endpoint(self):
        nav, current, goal, local, request = self.issued_exit()
        self.assertEqual(local, nav.next_target(11, current, goal, request, 1.0))
        target = nav.next_target(11, current, goal, request, 13.0)
        self.assertNotEqual(local, target)
        self.assertEqual('timeout', nav.bot_states[11]['local_target_end_reason'])
        self.assertTrue(nav.bot_segment_penalized(11, current, local, 13.1))
        self.assertFalse(nav.bot_segment_penalized(12, current, local, 13.1))
        self.assertFalse(nav.bot_segment_penalized(11, current, local, 26.0))

    def test_tactical_hold_retires_local_exit_and_keeps_motion_disabled(self):
        nav, current, goal, local, request = self.issued_exit()
        nav.next_target(11, current, goal, request, 0.1, movement_intent=False)
        self.assertIsNone(nav.bot_states[11].get('local_fallback_target'))

    def test_slow_real_alignment_renews_lease_but_heading_oscillation_does_not(self):
        nav, current, goal, local, request = self.issued_exit()
        for frame in range(25):
            yaw = -1.0 + frame * 0.04
            self.assertEqual(local, nav.retained_local_target(
                11, current, goal, request, float(frame), yaw=yaw))
        nav, current, goal, local, request = self.issued_exit()
        for frame in range(12):
            nav.retained_local_target(11, current, goal, request, float(frame),
                                      yaw=-1.0 + 0.01 * (frame % 2))
        self.assertIsNone(nav.retained_local_target(
            11, current, goal, request, 13.0, yaw=-1.0))

    def test_runtime_lane_translation_applies_once_to_the_actual_issued_leg(self):
        runtime = self.module.BotRuntime(1)
        nav = self.navigator_type(lambda *args: 0.0, baked_graph=fixtures._flat_open_graph())
        runtime.navigator = nav
        runtime.states = {11: {'id': 11, 'team': 1}}
        goal, local = (0.0, 0.0, 30.0), (3.0, 0.0, 5.0)
        strategic = {'combat_mode': 'route', 'route_id': 'south', 'route_index': 1}
        with mock.patch.object(runtime, '_route_lane_target', return_value=local) as lane:
            for frame in range(20):
                result = runtime._navigation_target(11, (0.1 * (frame % 2), 0.0, 0.0),
                    goal, strategic, {'now': frame * 0.1, 'yaw': 0.0, 'speed': 0.0})
                self.assertEqual(local, result)
            self.assertEqual(1, lane.call_count)

    def test_short_direct_shortcut_cannot_steal_an_issued_exit(self):
        nav, current, goal, local, request = self.issued_exit()
        runtime = self.module.BotRuntime(1)
        runtime.navigator = nav
        runtime.states = {11: {'id': 11, 'team': 1}}
        short_goal = (0.0, 0.0, 14.0)
        nav.next_target(11, current, short_goal, ('local', 11, 'engage', 22), 0.0)
        nav._remember_local_fallback(local, short_goal, nav.bot_states[11], current, 0.0)
        nav.bot_states[11]['last_target'] = local
        self.assertEqual(local, runtime._navigation_target(11, current, short_goal,
            {'combat_mode': 'engage', 'target_id': 22}, {'now': 1.0, 'yaw': 0.0}))

    def test_deferred_native_proof_pauses_without_surrendering_target(self):
        nav, current, goal, local, request = self.issued_exit()
        def defer(*unused):
            nav.grid._native_proof_revision += 1
            return False
        with mock.patch.object(nav.grid, 'dry_segment_clear', side_effect=defer):
            self.assertEqual(current, nav.next_target(11, current, goal, request, 1.0))
            self.assertEqual(local, nav.bot_states[11]['local_fallback_target'])
            self.assertEqual('pending', nav.bot_states[11]['navigation_status'])
        self.assertEqual(local, nav.next_target(11, current, goal, request, 1.1))

    def test_consumed_exit_remains_fixed_origin_for_the_next_short_leg(self):
        nav, current, goal, local, request = self.issued_exit()
        arrived = (2.9, 0.0, 5.0)
        nav._retained_local_fallback(11, arrived, goal, 1.0, nav.bot_states[11])
        self.assertEqual(local, nav._local_fallback_origin(arrived, goal, nav.bot_states[11]))

    def test_occupied_gate_bypass_does_not_rotate_with_refreshing_hull_pose(self):
        runtime = self.module.BotRuntime(1)
        runtime.navigator = self.navigator_type(lambda *args: 0.0,
                                                baked_graph=fixtures._flat_open_graph())
        runtime.states = {11: {'id': 11, 'team': 1, 'half_length': 3.5, 'half_width': 1.7}}
        goal = (0.0, 0.0, 10.0)
        with mock.patch.object(runtime, '_physical_parking_occupancy',
                return_value=[(None, goal, 3.5)]):
            first = runtime._occupied_route_target(11, (0.0, 0.0, 0.0), goal, 0.0, True)
            self.assertIsNotNone(first)
            for frame in range(1, 30):
                self.assertEqual(first, runtime._occupied_route_target(
                    11, (0.2 * (frame % 2), 0.0, 0.0), goal, float(frame), True))
            with mock.patch.object(runtime.navigator.grid, 'dry_segment_clear', return_value=False):
                self.assertIsNone(runtime._occupied_route_target(
                    11, (0.0, 0.0, 0.0), goal, 31.0, True))

    def test_failed_current_pose_fallback_is_pending_not_terminal_arrival(self):
        nav, current, goal, local, request = self.issued_exit()
        state = nav.bot_states[11]
        state.pop('local_fallback_target', None)
        with mock.patch.object(nav, '_safe_fallback_target', return_value=current):
            self.assertEqual(current, nav._fallback_target(11, current, goal, 1.0, None, state))
        self.assertEqual('pending', state['navigation_status'])
        self.assertFalse(state['target_is_terminal'])

    def test_unreachable_completed_origin_is_retired_before_another_exit(self):
        nav, current, goal, local, request = self.issued_exit()
        state = nav.bot_states[11]
        state['local_completed_target'] = local
        with mock.patch.object(nav.grid, 'safe_local_target', return_value=goal), mock.patch.object(nav.grid, 'dry_segment_clear', return_value=False):
            self.assertEqual(current, nav._new_local_fallback(11, current, local, goal, 1.0, None, state))
        self.assertNotIn('local_completed_target', state)


if __name__ == '__main__':
    unittest.main()
