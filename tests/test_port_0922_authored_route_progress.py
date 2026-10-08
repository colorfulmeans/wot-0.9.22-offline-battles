"""Regression coverage for the native El Halluf report from 2026-10-05."""
import unittest
import test_port_0922_ai as fixtures
from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator, _distance_2d
from gui.mods.offline_lan_0922.prebaked_navigation import load_graph


class AuthoredRouteProgressTests(unittest.TestCase):
    def test_latest_authored_descent_finishes_within_one_bounded_search(self):
        navigator = TerrainNavigator(lambda *unused: None,
            baked_graph=load_graph('29_el_hallouf', str(fixtures.ROOT)))
        start = (-131.5, 58.6, -294.697)
        goal = (29.276, 0.0, -180.313)
        search = navigator.grid.begin_plan(start, goal, max_expansions=4096,
            prefer_clearance=True, route_corridor=(start, goal))
        # Check completed planning, not a temporary forward fallback. The
        # shipped overwritten corridor vector exhausted all 4096 expansions.
        for unused in range(512):
            if search.step(1):
                break
        self.assertTrue(search.done)
        self.assertLess(_distance_2d(search.result[-1], goal), 0.01)
        for first, last in zip(search.result, search.result[1:]):
            self.assertTrue(navigator.grid.dry_segment_clear(first, last, 1.0))

    def test_eligible_slope_does_not_pay_a_comfort_surcharge(self):
        graph = fixtures.BotAiPortTests._baked_graph(12, 3)
        # A legal 0.30-grade bump in the middle lane has a longer flat bypass.
        for x in range(3, 9):
            graph['heights_mm'][12 + x] = 1200
        navigator = TerrainNavigator(lambda *unused: None, baked_graph=graph)
        navigator.grid._smooth = lambda path, *args: path
        for start, goal in [((10.0, 0.0, 24.0), (54.0, 0.0, 24.0)),
                            ((54.0, 0.0, 24.0), (10.0, 0.0, 24.0))]:
            for corridor in [None, (start, goal)]:
                search = navigator.grid.begin_plan(start, goal,
                    prefer_clearance=False, route_corridor=corridor)
                while not search.done:
                    search.step(256)
                self.assertTrue(search.result)
                self.assertTrue(all(point[2] == 24.0 for point in search.result))

    def test_live_ground_planning_does_not_zigzag_across_a_legal_plane(self):
        navigator = TerrainNavigator(lambda x, z, hint: x * 0.30,
            bounds=(0.0, 0.0, 44.0, 8.0), cell_size=4.0)
        navigator.grid._smooth = lambda path, *args: path
        for start, goal in [((0.0, 0.0, 4.0), (44.0, 13.2, 4.0)),
                            ((44.0, 13.2, 4.0), (0.0, 0.0, 4.0))]:
            search = navigator.grid.begin_plan(start, goal)
            while not search.done:
                search.step(256)
            self.assertTrue(search.result)
            self.assertTrue(all(point[2] == 4.0 for point in search.result))

    def test_reported_centurion_pose_selects_a_forward_supported_descent(self):
        navigator = TerrainNavigator(lambda *unused: None,
            baked_graph=load_graph('29_el_hallouf', str(fixtures.ROOT)))
        current = (-129.44, 58.29, -291.0)
        anchor = (-131.5, 0.0, -294.697)
        goal = (53.443, 0.0, -184.263)
        route = ('route', 2, 'class_mt_south_valley', 2)
        for frame in range(100):
            target = navigator.next_target(21, current, goal, route,
                1.0 + frame * 0.1, anchor=anchor)
            state = navigator.bot_states[21]
            if navigator.paths.get(state.get('path_key')):
                break
        self.assertLess(_distance_2d(target, goal), _distance_2d(current, goal))
        self.assertTrue(navigator.grid.dry_segment_clear(current, target, 12.0))
        self.assertGreater(target[0], current[0])
        self.assertGreater(target[2], current[2])

    def test_reacquired_cached_path_does_not_return_to_a_passed_start(self):
        navigator = TerrainNavigator(lambda *unused: None,
            baked_graph=fixtures.BotAiPortTests._baked_graph(12, 3))
        route = ('route', 1, 'lane', 1)
        goal = (54.0, 0.0, 24.0)
        current = (16.0, 0.0, 24.0)
        key = navigator._cache_key(route, goal)
        navigator.paths[key] = ((10.0, 0.0, 24.0),
                                (30.0, 0.0, 24.0), goal)
        navigator.path_times[key] = 1.0
        first = navigator.next_target(7, current, goal, route, 1.0)
        # A combat request resets the active path, but not physical progress.
        navigator.next_target(7, current, (54.0, 0.0, 28.0),
                             ('local', 7, 'engage', 2), 1.1)
        target = navigator.next_target(7, current, goal, route, 1.2)
        self.assertGreater(first[0], current[0])
        self.assertGreater(target[0], current[0])

    def test_corridor_preference_still_bypasses_an_impassable_wall(self):
        graph = fixtures.BotAiPortTests._baked_graph(9, 5,
            blocked=((4, 0), (4, 1), (4, 2), (4, 3)))
        navigator = TerrainNavigator(lambda *unused: None, baked_graph=graph)
        start, goal = (10.0, 0.0, 28.0), (42.0, 0.0, 28.0)
        search = navigator.grid.begin_plan(start, goal,
            prefer_clearance=True, route_corridor=(start, goal))
        while not search.done:
            search.step(256)
        self.assertTrue(search.result)
        self.assertGreater(max(point[2] for point in search.result), 28.0)
        self.assertLess(_distance_2d(search.result[-1], goal), 0.01)
        for first, last in zip(search.result, search.result[1:]):
            self.assertTrue(navigator.grid.dry_segment_clear(first, last, 1.0))


if __name__ == '__main__':
    unittest.main()
