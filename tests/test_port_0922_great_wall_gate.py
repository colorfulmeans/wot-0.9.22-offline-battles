"""Bots on the Default ``valley`` route drive through Great Wall's gatehouse.

The map's only east crossing is a gatehouse whose baked corridor is one cell
wide at its north mouth and two cells inside. Both teams' Default ``valley``
routes run through it, and team 2 reaches it about 230 m after its spawn.
The scene is flat: four-metre heights are zeroed as in the departure
fixtures, and the navigation grid stands in for collision.
"""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest import mock
from server_bot_ai import BotPlanner

import test_port_0922_bot_runtime as runtime_fixtures
from effective_params_fixture import bot_default_crew_factors
from test_port_0922_fjord_departure import _bots


ROOT = Path(__file__).resolve().parents[1]
MAP_NAME = '59_asia_great_wall'
# The gatehouse passage, from the bake's grid-phase record and passage rows.
PASSAGE_X = 404.0
PASSAGE_SOUTH = -158.0
PASSAGE_NORTH = -140.0
SECONDS = 120.0
FPS = 15


def _flat_graph():
    path = ROOT / 'navgraphs' / ('%s.json' % MAP_NAME)
    graph = copy.deepcopy(json.loads(path.read_text()))
    graph['heights_mm'] = [
        0 if value is not None else None for value in graph['heights_mm']]
    return graph


def _valley(route):
    identity = (route or {}).get('id') or ''
    return identity == 'valley' or identity.endswith('_valley')


def _segment_distance(point, first, second):
    dx, dz = second[0] - first[0], second[1] - first[1]
    length = dx * dx + dz * dz
    t = 0.0 if not length else max(0.0, min(1.0, (
        (point[0] - first[0]) * dx + (point[1] - first[1]) * dz) / length))
    return math.hypot(first[0] + t * dx - point[0], first[1] + t * dz - point[1])


class GreatWallGateTests(unittest.TestCase):
    def setUp(self):
        self._gui_modules = dict(
            (key, value) for key, value in sys.modules.items()
            if key == 'gui' or key.startswith('gui.'))

    def tearDown(self):
        for key in list(sys.modules):
            if key == 'gui' or key.startswith('gui.'):
                sys.modules.pop(key, None)
        sys.modules.update(self._gui_modules)

    def run_scene(self, seconds=SECONDS):
        """Drive the Default round; report team 2's valley Bots at the gatehouse.

        Returns the runtime, the valley Bot ids, when each crossed north of
        the gatehouse and how many seconds each spent inside it.
        """
        module = runtime_fixtures._load()
        original_factors = module.loadout.attribute_factors
        module.loadout.attribute_factors = bot_default_crew_factors
        self.addCleanup(
            setattr, module.loadout, 'attribute_factors', original_factors)
        graph = _flat_graph()
        runtime_box = {}

        def spawn(team, slot):
            point = graph['spawn_formations'][str(team)][slot]
            return ((point[0], 0.0, point[2]), point[3])

        def ground(unused_x, unused_z, unused_hint=0.0):
            return 0.0

        def baked_direction(position, yaw, speed, unused_descriptor,
                            maximum_distance):
            grid = runtime_box['runtime'].navigator.grid
            distance = 20.0 if abs(float(speed)) > 5.0 else 15.0
            if maximum_distance is not None:
                distance = min(distance, max(0.5, float(maximum_distance)))
            end = (float(position[0]) + math.sin(float(yaw)) * distance,
                   float(position[1]),
                   float(position[2]) + math.cos(float(yaw)) * distance)
            clear = grid.segment_clear(position, end)
            return {'clear': clear, 'collision': not clear,
                    'water': False, 'slope': 0.0}

        def baked_receipt(position, yaw, speed, descriptor, maximum_distance):
            if not baked_direction(position, yaw, speed, descriptor,
                                   maximum_distance)['clear']:
                return False
            distance = 15.0 if maximum_distance is None else min(
                15.0, max(0.5, float(maximum_distance)))
            return {'distance': distance, 'half_width': 1.6, 'leading': 3.5,
                    'origin': tuple(position), 'yaw': float(yaw),
                    'direction': -1 if float(speed) < 0.0 else 1}

        runtime = module.BotRuntime(
            1,
            descriptor_resolver=runtime_fixtures._class_descriptor,
            direction_probe=baked_direction,
            world_receipt_probe=baked_receipt,
            spawn_resolver=spawn,
            ground_probe=ground, physics_ground_probe=ground,
            baked_graph=graph,
            visibility_probe=lambda *unused: False,
            firing_lane_probe=lambda *unused: False)
        runtime_box['runtime'] = runtime
        # A fixed allocation seed replays the same Default lane draw.
        with mock.patch.object(module.random.SystemRandom, 'getrandbits', return_value=0x0922):
            published = runtime.battle_start({
                'map': MAP_NAME, 'round_id': 7, 'bot_authority_id': 1, 'bots': _bots(),
                'bot_tactics': module.bot_tactics.for_round(
                    module.bot_tactics.default_profile(), MAP_NAME)})[0]
        planner = BotPlanner()
        planner.tactics = runtime._bot_tactics
        planner.tactics_map = MAP_NAME
        valley = sorted(bot['id'] for bot in published['bots']
                        if bot['team'] == 2 and _valley(bot.get('route')))
        crossed = {}
        inside = dict((bot_id, 0.0) for bot_id in valley)
        for frame in range(1, int(FPS * seconds) + 1):
            now = frame / float(FPS)
            # Bots move only on server orders, as in the worker.
            orders = planner.build_orders(
                published['bots'], list(runtime.states.values()), [], now)
            runtime._apply_orders(dict(bot_order_revision=orders['revision'],
                                       bot_orders=orders['orders']))
            runtime.update(1.0 / float(FPS), now)
            for bot_id in valley:
                state = runtime.states[bot_id]
                if (abs(state['x'] - PASSAGE_X) < 8.0 and
                        PASSAGE_SOUTH <= state['z'] <= PASSAGE_NORTH):
                    inside[bot_id] += 1.0 / FPS
                if (bot_id not in crossed and state['z'] > PASSAGE_NORTH + 4.0 and
                        abs(state['x'] - PASSAGE_X) < 40.0):
                    crossed[bot_id] = now
        return runtime, valley, crossed, inside

    def test_both_default_valley_routes_cross_the_gatehouse(self):
        from gui.mods.offline_lan_0922 import bot_tactics, bot_tactics_runtime
        graph = json.loads((ROOT / 'navgraphs' / ('%s.json' % MAP_NAME)).read_text())
        document = bot_tactics.for_round(bot_tactics.default_profile(), MAP_NAME)
        routes, outcomes = bot_tactics_runtime.default_routes(document, MAP_NAME, graph)
        centre = (PASSAGE_X, (PASSAGE_SOUTH + PASSAGE_NORTH) / 2.0)
        for team in ('1', '2'):
            rows = [route for route in routes[team] if _valley(route)]
            self.assertTrue(rows, team)
            for route in rows:
                points = route['waypoints']
                self.assertLess(min(_segment_distance(centre, first, second)
                                    for first, second in zip(points, points[1:])),
                                4.0, (team, route['id']))
        self.assertTrue(all(status == 'baked_route_connected'
                            for key, status in outcomes.items() if _valley(dict(id=key.split(':', 1)[1]))))

    def test_default_valley_bots_drive_through_the_gatehouse(self):
        runtime, valley, crossed, inside = self.run_scene()
        self.assertGreaterEqual(len(valley), 2)
        # Every team-2 valley Bot gets through, and none sits in the passage.
        self.assertEqual([], [
            (bot_id, round(runtime.states[bot_id]['x'], 1), round(runtime.states[bot_id]['z'], 1))
            for bot_id in valley if bot_id not in crossed])
        self.assertLessEqual(max(inside.values()), 10.0)


if __name__ == '__main__':
    unittest.main()
