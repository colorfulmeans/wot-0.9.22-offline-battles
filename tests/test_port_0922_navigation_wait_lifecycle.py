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


if __name__ == '__main__':
    unittest.main()
