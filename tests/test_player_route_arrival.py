"""Foreground corner arrival uses the pathfinder's actual consumption disk.

The captured pose is from report 133716 on the exact Windows client. The
pathfinder seam supplies a checked path and explicit geometry responses; it
does not replay native physics or establish in-client driving feel.
"""
import math
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control.driving import Driver
from gui.mods.offline_lan_0922.player_control.pathfinding import PlayerPathfinder


class PlayerRouteArrivalTests(unittest.TestCase):
    def test_captured_unconsumed_corner_keeps_forward_command(self):
        # 13:25:57.288: route, holding=False, terminal=False, clear terrain
        # and no traffic refusal, yet the old two-metre driver disk held here.
        position = (-66.52325277655783, .25130920962248315, -92.41978981475219)
        target = (-68.42960357666016, .2499995231628418, -92.92816162109375)
        driver = Driver()
        order = driver.drive(position, -1.955978891407381, 0., target, 407.288,
                             lambda *args: True)
        self.assertAlmostEqual(1.9729711773195713, driver.receipt['distance'])
        self.assertEqual('travel', order['recovery_mode'])
        self.assertGreater(order['throttle'], 0.)
        self.assertFalse(order['brake'])

    def test_real_pathfinder_corner_is_approached_before_checked_handoff(self):
        nav = PlayerPathfinder(lambda *args: 0., lambda *args: False, cell_size=4.)
        self.addCleanup(nav.close)
        corner, following, goal = (0., 0., 0.), (12., 0., 12.), (12., 0., 30.)
        path = [corner, following, goal]
        request = ('route', 1, 'arrival_contract')
        key = nav._cache_key(request, goal)
        position = (0., 0., -1.9729711773195713)
        nav.paths[key] = path
        nav.player_states[1] = dict(request_key=key, request_path_key=request,
            planned_goal=goal, planned_at=0., path_key=key, index=0,
            last_position=position, progress_time=0., last_target=corner,
            replan_generation=0)
        driver = Driver()
        # An unreached bend is necessary for the outgoing climb. Its adjacent
        # edge is clear after arrival; widening the corner disk would skip it.
        with mock.patch.object(nav, '_path', return_value=(key, path)), \
             mock.patch.object(nav.grid, 'live_shortcut_preserves_climb_approach',
                               return_value=False):
            for now, remaining in ((0., 1.9729711773195713), (.1, 1.501)):
                position = (0., 0., -remaining)
                selected = nav.next_target(1, position, goal, request, now)
                self.assertEqual(corner, selected)
                self.assertFalse(nav.target_is_terminal(1))
                order = driver.drive(position, 0., 0., selected, now,
                                     lambda *args: True,
                                     terminal=nav.target_is_terminal(1))
                self.assertGreater(order['throttle'], 0.)
                self.assertFalse(order['brake'])
            position = (0., 0., -1.5)
            selected = nav.next_target(1, position, goal, request, .2)
            self.assertEqual(following, selected)
            self.assertEqual(1, nav.player_states[1]['index'])
            yaw = math.atan2(selected[0] - position[0], selected[2] - position[2])
            order = driver.drive(position, yaw, 0., selected, .2,
                                 lambda *args: True)
            self.assertGreater(order['throttle'], 0.)
            self.assertFalse(order['brake'])

    def test_nonterminal_disk_closes_at_one_and_a_half_metres(self):
        for remaining, expected_hold in ((1.5, True), (1.500001, False),
                                         (1.75, False), (2., False)):
            with self.subTest(remaining=remaining):
                order = Driver().drive((0., 0., 0.), 0., 0.,
                    (0., 0., remaining), 0., lambda *args: True)
                self.assertEqual(expected_hold, order['brake'])
                self.assertEqual(expected_hold, order['throttle'] == 0.)

    def test_terminal_radius_remains_owned_by_its_mission(self):
        for radius, remaining, expected_hold in ((0., 0., True),
                (0., 1.75, False), (1.5, 1.75, False), (6., 1.75, True)):
            with self.subTest(radius=radius, remaining=remaining):
                driver = Driver()
                order = driver.drive((0., 0., 0.), 0., 0.,
                    (0., 0., remaining), 0., lambda *args: True,
                    terminal=True, arrival_radius=radius)
                self.assertEqual(radius, driver.receipt['arrival_radius'])
                self.assertEqual(expected_hold, order['brake'])

    def test_stopping_envelope_does_not_stop_before_a_nonterminal_corner(self):
        for terminal in (False, True):
            with self.subTest(terminal=terminal):
                order = Driver().drive((0., 0., 0.), 0., 3., (0., 0., 2.), 0.,
                    lambda *args: True, terminal=terminal, arrival_radius=1.5,
                    stopping_distance=.3, decision_horizon=.1)
                self.assertEqual(terminal, order['brake'])
                self.assertEqual('arrival_brake' if terminal else 'travel',
                                 order['recovery_mode'])

    def test_explicit_hold_still_stops_an_unconsumed_corner(self):
        order = Driver().drive((0., 0., 0.), 0., 0., (0., 0., 1.75), 0.,
                               lambda *args: True, hold=True)
        self.assertEqual((0., 0., True),
                         (order['throttle'], order['turn'], order['brake']))


if __name__ == '__main__':
    unittest.main()
