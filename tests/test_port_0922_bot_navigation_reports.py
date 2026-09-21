"""September 21 navigation report regressions; no native playtest claim."""

import json
import math
import types
import unittest
from pathlib import Path

from test_port_0922_bot_runtime import _load
import test_port_0922_navigation as navigation_tests
from test_port_0922_server_bot_ai import (
    BotPlanner, _bot, _capture_defense, _route, _state)
from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator


ROOT = Path(__file__).resolve().parents[1]


class AirfieldPendingEscapeTests(unittest.TestCase):
    def test_reported_airfield_pockets_have_a_proved_rear_exit(self):
        graph = json.loads((ROOT / 'navgraphs/31_airfield.json').read_text())
        # 090604 hidden-worker: two hulls were outside the forward
        # routing corridor. A queued A* held them without invoking recovery.
        poses = (
            ((80.732559, -11.624972, -295.808058), (34.0, 0.0, -266.0)),
            ((-319.8, -0.18, -95.5), (-334.0, 0.0, -6.0)),
        )
        for current, goal in poses:
            with self.subTest(current=current):
                nav = TerrainNavigator(lambda *unused: None, baked_graph=graph)
                state = {'pending_since': 0.0}
                target = nav._pending_target(2, current, goal, 1.0, state)
                self.assertNotEqual(current, target)
                self.assertTrue(nav.grid.dry_segment_clear(current, target, 1.0))
                bearing = math.atan2(goal[0] - current[0], goal[2] - current[2])
                exit_bearing = math.atan2(target[0] - current[0], target[2] - current[2])
                offset = (exit_bearing - bearing + math.pi) % (2 * math.pi) - math.pi
                self.assertGreater(abs(offset), 1.75)

    def test_known_forward_exit_keeps_precedence_over_rear_candidates(self):
        nav = TerrainNavigator(lambda *unused: 0.0,
            baked_graph=navigation_tests.StaticHullNavigationTests._flat_graph())
        current, goal = (40, 0, 40), (40, 0, 60)
        target = nav.grid.safe_local_target(current, goal, 1.0)
        self.assertGreater(target[2], current[2])

    def test_complete_static_enclosure_still_holds(self):
        nav = TerrainNavigator(lambda *unused: 0.0, lambda *unused: True,
            baked_graph=navigation_tests.StaticHullNavigationTests._flat_graph())
        current, goal = (40, 0, 40), (40, 0, 60)
        nav.grid.review_native_corridor(current, goal)
        self.assertEqual(current, nav._pending_target(
            2, current, goal, 1.0, {'pending_since': 0.0}))


class BlockedPlannerReviewTests(unittest.TestCase):
    def setUp(self):
        self.runtime = object.__new__(_load().BotRuntime)
        self.calls = []
        self.runtime.navigator = types.SimpleNamespace(
            report_blocked_plan=lambda *args: self.calls.append(args) or True)
        self.command = dict(recovery_mode='blocked', movement_intent=True,
                            move_position=(20.0, 0.0, 40.0))

    def test_static_veto_is_reported_without_waiting_for_realised_motion(self):
        self.assertTrue(self.runtime._report_blocked_planner(
            (20, 0, 20), self.command,
            {0: dict(clear=False, collision=True, water=False)}))
        self.assertEqual([((20, 0, 20), (20, 0, 40))], self.calls)

    def test_traffic_holds_and_unavailable_samples_do_not_mark_terrain(self):
        for sample in ({}, dict(clear=False, collision=False),
                       dict(clear=False, collision=True, deferred=True),
                       dict(clear=False, collision=True, probe_failed=True)):
            self.assertFalse(self.runtime._report_blocked_planner(
                (20, 0, 20), self.command, {0: sample}))
        for changes in (dict(recovery_mode='friendly_yield'),
                        dict(movement_intent=False)):
            command = dict(self.command, **changes)
            self.assertFalse(self.runtime._report_blocked_planner(
                (20, 0, 20), command, {0: dict(clear=False, collision=True)}))
        self.assertEqual([], self.calls)

    def test_review_retires_static_shortcut_and_finds_other_route(self):
        def obstacle(start, end, half_width):
            # A wall at z=36 ends at x=36; the previously baked straight
            # corridor is stale, and x>=40 is the measured alternative.
            if abs(end[2] - start[2]) < 1e-9:
                return False
            progress = (36.0 - start[2]) / (end[2] - start[2])
            return (0 <= progress <= 1 and
                    start[0] + progress * (end[0] - start[0]) < 36 + half_width)
        nav = TerrainNavigator(lambda *unused: 0.0, obstacle,
            baked_graph=navigation_tests.StaticHullNavigationTests._flat_graph())
        start, goal = (20, 0, 20), (20, 0, 60)
        self.assertTrue(nav.grid.segment_clear(start, goal))
        self.assertTrue(nav.report_blocked_plan(start, goal))
        self.assertFalse(nav.grid.segment_clear(start, goal))
        path = nav.grid.plan(start, goal)
        self.assertEqual(goal, path[-1])
        self.assertGreaterEqual(max(point[0] for point in path), 40)
        self.assertFalse(any(obstacle(a, b, 2.15) for a, b in zip(path, path[1:])))


class AdvancedCaptureTests(unittest.TestCase):
    def test_contact_loss_after_staging_hands_over_to_actual_circle(self):
        route = _route('lane', [(0, -100, False), (0, 100, False),
                               (0, 300, False)])
        manifest = [_bot(11, 1, 0, route, 'mediumTank')]
        states = [_state(11, 1, 0, 280)]
        planner = BotPlanner()
        order = planner.build_orders(
            manifest, states, [], 1.0, _capture_defense())['orders'][0]
        self.assertEqual('base_capture', order['combat_mode'])
        self.assertEqual((123.5, 456.25),
                         (order['move_position']['x'], order['move_position']['z']))


class ActiveWreckPathTests(unittest.TestCase):
    def test_new_wreck_retires_active_private_join_as_well_as_shared_route(self):
        nav = TerrainNavigator(lambda *unused: 0.0,
            baked_graph=navigation_tests.StaticHullNavigationTests._flat_graph())
        start, goal = (20, 0, 20), (20, 0, 60)
        request = ('route', 1, 'lane', 1)
        nav.next_target(1, start, goal, request, 0.0)
        active = nav._cache_key(('join', 1, (5, 5)) + request, goal)
        nav.paths[active] = (start, (20, 0, 40), goal)
        nav.path_times[active] = 0.0
        nav.path_hull_revisions[active] = nav.grid.static_hull_revision
        nav.bot_states[1].update(path_key=active, index=1,
                                 last_target=(20, 0, 40))
        nav.grid.set_static_hulls(((9, 20, 40, 0, 3.5, 1.7),))
        shared = nav._cache_key(request, goal)
        nav.paths[shared] = (start, (8, 0, 20), (8, 0, 60), goal)
        nav.path_hull_revisions[shared] = nav.grid.static_hull_revision
        target = nav.next_target(1, start, goal, request, 0.1)
        self.assertNotEqual(active, nav.bot_states[1]['path_key'])
        self.assertFalse(nav.grid.path_crosses_static_hull((start, target)))


if __name__ == '__main__':
    unittest.main()
