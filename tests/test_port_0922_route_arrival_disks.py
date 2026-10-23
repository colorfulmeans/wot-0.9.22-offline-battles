"""Route disks, actual crossing and private blocked-corner handoff."""
import copy
import json
from pathlib import Path
import unittest
from unittest import mock

from test_port_0922_navigation import TerrainNavigator
from test_port_0922_server_bot_ai import BotPlanner, _route, _bot, _state
from server_bot_ai import _route_point_reached, ROUTE_ARRIVAL_RADIUS
from gui.mods.offline_lan_0922 import bot_tactics


class RouteArrivalDiskTests(unittest.TestCase):
    def test_circle_edge_side_bypass_and_fast_crossing(self):
        points = [dict(x=0., z=0.), dict(x=30., z=0.)]
        self.assertEqual(6., ROUTE_ARRIVAL_RADIUS)
        self.assertEqual(bot_tactics.WAIT_AVOIDANCE_RADIUS, ROUTE_ARRIVAL_RADIUS)
        for x, z, expected in ((-6., 0., True), (0., 6., True),
                               (-6.001, 0., False), (0., 6.001, False)):
            self.assertEqual(expected, _route_point_reached(x, z, points, 0, 1))
        self.assertTrue(_route_point_reached(10., 0., points, 1, 1, (50., 0.)))
        self.assertFalse(_route_point_reached(10., 6.01, points, 1, 1, (50., 6.01)))
        # A passed terminal is not an unbounded forward corridor.
        self.assertFalse(_route_point_reached(50., 0., points, 1, 1))

    def test_route_tick_consumes_crossed_disks_without_rewind(self):
        planner = BotPlanner()
        route = _route('crossing', [(0., 0., False), (0., 20., False),
                                   (0., 40., False), (0., 80., False)])
        bot = _bot(23, 1, 0, route, 'AT-SPG')
        bot['state'] = _state(23, 1, 0., 0.)
        self.assertEqual(1, planner._route(bot, 1.)[1])
        bot['state'].update(z=50.)
        self.assertEqual(3, planner._route(bot, 2.)[1])
        bot['state'].update(z=49.)
        self.assertEqual(3, planner._route(bot, 3.)[1])

    def test_initial_join_does_not_skip_an_unreached_gate_twenty_metres_away(self):
        planner = BotPlanner()
        route = _route('entry', [(0., 0., False), (0., 20., False), (0., 100., False)])
        bot = _bot(23, 1, 0, route, 'AT-SPG')
        bot['state'] = _state(23, 1, 0., 0.)
        self.assertEqual(1, planner._route(bot, 1.)[1])

    def test_terminal_crossing_does_not_require_returning_to_circle(self):
        import test_port_0922_terminal_route_handoff as terminal
        helper = terminal.TerminalRouteHandoffTests()
        scene = helper.scene((2., -230.))
        scene[3].clear()
        first = helper.order(scene, now=1., contact=False)
        self.assertNotEqual(0., first['throttle_override'])
        scene[2][0]['z'] = -270.
        second = helper.order(scene, now=2., contact=False)
        self.assertEqual('hold', second['combat_mode'])
        self.assertEqual(0., second['throttle_override'])
        self.assertEqual(second['move_position'], second['face_position'])

    def test_duplicate_or_stale_samples_cannot_create_terminal_crossing(self):
        for second_time, crossed in ((1., False), (2., True), (4., False)):
            planner = BotPlanner()
            route = _route('terminal', [(-100., 0., False), (0., 0., False)])
            bot = _bot(23, 1, 0, route, 'AT-SPG')
            bot['state'] = _state(23, 1, -10., 0.)
            planner._route(bot, 1.)
            bot['state']['x'] = 10.
            planner._route(bot, second_time)
            self.assertEqual(crossed, 'terminal_crossing' in planner._route_states[23])

    def test_every_shipped_route_uses_closed_six_metre_disk(self):
        root = Path(__file__).resolve().parents[1]
        checked = 0
        for source in (root / 'navgraphs').glob('*.json'):
            graph = json.loads(source.read_bytes())
            for routes in graph.get('routes', {}).values():
                for route in routes:
                    points = [dict(x=p[0], z=p[1]) for p in route.get('waypoints', ())]
                    for i, point in enumerate(points):
                        # Terminal mode isolates the circle from forward-pass semantics.
                        self.assertTrue(_route_point_reached(point['x']+6., point['z'], points, i, i))
                        self.assertFalse(_route_point_reached(point['x']+6.01, point['z'], points, i, i))
                        checked += 1
        self.assertGreater(checked, 1000)


class CapturedE3CornerTests(unittest.TestCase):
    def scene(self):
        root = Path(__file__).resolve().parents[1]
        capture = json.loads((root / 'tests/fixtures/thepit_e3_corner_20261024.json').read_bytes())
        nav = TerrainNavigator(lambda *args: .4, lambda *args: False)
        receipt = copy.deepcopy(capture['corner_receipt'])
        nav.grid.static_hull_revision = receipt['checks'][-1]['corridor']['static_hull_revision']
        index = receipt['checks'][0]['index']
        nav.bot_states[23] = dict(corner_selection_receipt=receipt)
        nav.bot_states[24] = dict(index=4)
        return nav, nav.bot_states[23], receipt, capture['path'], index

    def test_captured_static_hull_refusal_retires_only_own_outgoing_leg(self):
        nav, state, receipt, path, index = self.scene()
        origin, now = tuple(receipt['origin']), receipt['at']
        self.assertTrue(nav._handoff_blocked_corner(23, state, origin, path, index, now))
        self.assertTrue(state['replan_active'])
        self.assertTrue(nav.bot_segment_penalized(23, origin, path[index+1], now))
        self.assertFalse(nav.bot_segment_penalized(24, origin, path[index+1], now))
        self.assertEqual(dict(index=4), nav.bot_states[24])
        self.assertEqual({}, nav.grid._failed_edges)
        nav.request_replan(23, origin, now+.1)
        self.assertTrue(nav.bot_segment_penalized(23, origin, path[index+1], now+.1))
        self.assertFalse(nav.bot_segment_penalized(23, origin, path[index+1], now+60.))

    def test_unknown_stale_changed_revision_or_clear_edge_cannot_retire(self):
        for kind in ('stale', 'changed_revision', 'changed_hulls', 'deferred', 'unproved', 'clear', 'far'):
            with self.subTest(kind=kind):
                nav, state, receipt, path, index = self.scene()
                origin, now = tuple(receipt['origin']), receipt['at']
                if kind == 'stale': now += 1.
                elif kind == 'changed_revision': nav.grid._native_proof_revision += 1
                elif kind == 'changed_hulls': nav.grid.static_hull_revision += 1
                elif kind == 'deferred': nav.grid._proof_deferred = True
                elif kind == 'far': origin = (origin[0]+20., origin[1], origin[2])
                else:
                    for row in receipt['checks']:
                        if kind == 'clear': row['clear'] = True
                        else: row.pop('corridor', None)
                self.assertFalse(nav._handoff_blocked_corner(23, state, origin, path, index, now))
                self.assertEqual({}, nav.bot_failed_edges)

    def test_next_target_hands_captured_connector_to_private_planning(self):
        nav, state, receipt, path, index = self.scene()
        origin, now = tuple(receipt['origin']), receipt['at']
        goal = tuple(receipt['goal'])
        route_key = ('route_join', 23, 'captured_e3')
        key = nav._cache_key(route_key, goal)
        state.update(request_key=key, request_path_key=route_key, planned_goal=goal,
                     planned_at=now, path_key=key, index=index, last_position=origin,
                     progress_time=now, last_target=tuple(path[index]), replan_generation=0)
        path = [tuple(point) for point in path]
        nav.paths[key] = path
        def replay_selection(*args):
            # next_target clears old receipts before performing these checks.
            state['corner_selection_receipt'] = copy.deepcopy(receipt)
            return index
        with mock.patch.object(nav, 'tick'), \
             mock.patch.object(nav, '_observe_macro_progress', return_value=False), \
             mock.patch.object(nav, '_path', return_value=(key, path)), \
             mock.patch.object(nav.grid, 'segment_clear', return_value=True), \
             mock.patch.object(nav.grid, 'segment_penalty', return_value=0.), \
             mock.patch.object(nav.grid, 'segment_has_baked_hazard', return_value=False), \
             mock.patch.object(nav, '_planned_next_segment_clear', return_value=False), \
             mock.patch.object(nav, '_lookahead_index', side_effect=replay_selection):
            selected = nav.next_target(23, origin, goal, route_key, now)
        self.assertEqual(origin, selected)
        self.assertTrue(state['replan_active'])
        self.assertIn('near_corner_handoff', state)


if __name__ == '__main__':
    unittest.main()
