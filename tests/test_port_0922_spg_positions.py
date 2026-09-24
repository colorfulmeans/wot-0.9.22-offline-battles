"""Forum positions: provenance, all-map graph checks and real order/driver integration.

Native map meshes/firing arcs are not mocked as if verified; existing firing
proof regressions remain in the retained test suite.
"""
import contextlib
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/res/scripts/client'))
sys.path.insert(0, str(ROOT/'server'))
sys.path.insert(0, str(ROOT/'tools'))
from gui.mods.offline_lan_0922.ai import spg_positions as lib
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from server_bot_ai import BotPlanner
from test_port_0922_server_bot_ai import _bot, _state, _route, _contact
import test_port_0922_bot_runtime as harness


def graph(name):
    return json.loads((ROOT/'navgraphs'/(name+'.json')).read_text())


def bot(identity=11, team=1):
    return {'id': identity, 'team': team, 'state': {'collision_shape': (2., 4.5, 0., 2.)}}


def order_for(point, name='08_ruinberg'):
    return {'id': 11, 'team': point['team'], 'spg_position_id': point['id'],
            'spg_position_map': name, 'spg_position_revision': lib.REVISION,
            'move_position': tuple(point['point']), 'route_anchor': tuple(point['point']),
            'combat_mode': 'artillery_deploy', 'target_id': 1000002,
            'target_kind': 'human', 'fire_allowed': True,
            'aim_position': (0., 2., 0.), 'face_position': (0., 2., 0.),
            'route_index': 0, 'fire_range': 1250.}


class HistoricalPositionDataTests(unittest.TestCase):
    def test_coverage_is_exact_and_missing_maps_are_not_fabricated(self):
        maps = lib.DATA['maps']
        self.assertEqual(41, len(maps))
        self.assertEqual(38, sum(bool(m['markers']) for m in maps.values()))
        self.assertEqual(237, sum(len(m['markers']) for m in maps.values()))
        self.assertEqual(666, sum(len(m['positions']) for m in maps.values()))
        self.assertEqual(7, sum(p['slots'] == 0 for m in maps.values() for p in m['markers']))
        self.assertEqual('missing_image', lib.map_status('59_asia_great_wall'))
        for name in ('95_lost_city', '101_dday'):
            self.assertEqual('no_source_markers', lib.map_status(name))
            self.assertIsNone(lib.choose(name, bot(), [], 3))
        self.assertEqual('missing_map', lib.map_status('96_prohorovka_defense'))
        self.assertEqual('unsupported_mode', lib.map_status('08_ruinberg', 'assault'))

    def test_all_graphs_are_pinned_and_every_slot_is_dry_connected_and_bounded(self):
        import build_spg_positions as builder
        for name, entry in lib.DATA['maps'].items():
            with self.subTest(map=name):
                raw = (ROOT/'navgraphs'/(name+'.json')).read_bytes()
                self.assertEqual(entry['nav_sha256'], hashlib.sha256(raw).hexdigest())
                installed = graph(name)
                reachable = [builder.distances(installed, p, entry['bounds'])
                             for p in entry['spawn_anchors']] if entry['positions'] else []
                markers = {p['id']: p for p in entry['markers']}
                for point in entry['positions']:
                    self.assertTrue(lib.graph_accepts(name, point, installed), point['id'])
                    self.assertIn(point['node'], reachable[point['team']-1])
                    self.assertLessEqual(point['projection_metres'], 24.0001)
                    marker = markers[point['marker_id']]
                    self.assertAlmostEqual(point['projection_metres'], math.hypot(
                        point['point'][0]-marker['world'][0],
                        point['point'][2]-marker['world'][1]), places=3)

    def test_world_mapping_uses_offset_bounds_and_north_positive_z(self):
        import build_spg_positions as builder
        self.assertEqual((-300., 400.), builder.pixel_to_world((0., 0.), (512., 512.),
                                                            (-300., -300., 400., 400.)))
        self.assertEqual((400., -300.), builder.pixel_to_world((512., 512.), (512., 512.),
                                                            (-300., -300., 400., 400.)))
        self.assertEqual((50., 50.), builder.pixel_to_world((256., 256.), (512., 512.),
                                                         (-300., -300., 400., 400.)))

    def test_team_one_is_not_assumed_to_be_north(self):
        for name, north_team in (('08_ruinberg', 1), ('35_steppes', 2)):
            for marker in lib.DATA['maps'][name]['markers']:
                if marker['pixel_center'][1] < 100:
                    self.assertEqual(north_team, marker['team'])

    def test_graph_guard_rejects_wrong_map_water_height_and_closed_link(self):
        name = '08_ruinberg'
        point = lib.DATA['maps'][name]['positions'][0]
        for field in ('map', 'game_version', 'hazards', 'heights_mm', 'links'):
            installed = graph(name)
            if field in ('map', 'game_version'):
                installed[field] = 'wrong'
            else:
                installed[field][point['node']] = {'hazards': 1, 'heights_mm': None, 'links': 0}[field]
            self.assertFalse(lib.graph_accepts(name, point, installed), field)

    def test_three_spgs_on_each_side_receive_separated_positions_on_all_38_maps(self):
        for name, entry in lib.DATA['maps'].items():
            if not entry['positions']:
                continue
            occupied = []
            for team in (1, 2):
                for identity in range(team*10, team*10+3):
                    unit = bot(identity, team)
                    selected = lib.choose(name, unit, occupied, 37)
                    self.assertIsNotNone(selected, (name, team, identity))
                    self.assertEqual(team, selected['team'])
                    for previous, radius in occupied:
                        if previous['team'] == team:
                            self.assertGreaterEqual(math.hypot(
                                selected['point'][0]-previous['point'][0],
                                selected['point'][2]-previous['point'][2]), 14.)
                    occupied.append(lib.reservation(unit, selected))

    def test_slot_choice_is_repeatable_without_global_rng_or_enemy_information(self):
        first = lib.choose('08_ruinberg', bot(), [], 88)
        second = lib.choose('08_ruinberg', bot(), [], 88)
        self.assertEqual(first, second)
        self.assertFalse(lib.DATA['policy']['native_arcs_prevalidated'])
        self.assertIn('community', lib.DATA['source']['kind'])

    def test_wire_plan_requires_same_map_side_revision_and_exact_goal(self):
        point = lib.DATA['maps']['08_ruinberg']['positions'][0]
        order = order_for(point)
        self.assertTrue(lib.plan_matches_order(order))
        for field, value in (('spg_position_map', '35_steppes'),
                             ('spg_position_revision', 'invented'), ('team', 3-point['team']),
                             ('move_position', (100., 0., 100.))):
            self.assertFalse(lib.plan_matches_order(dict(order, **{field: value})))
        partial = dict(order)
        partial.pop('spg_position_id')
        self.assertFalse(lib.plan_matches_order(partial))
        self.assertTrue(lib.plan_matches_order({'id': 4, 'combat_mode': 'route'}))


class PlannerPositionTests(unittest.TestCase):
    def setUp(self):
        self.planner = BotPlanner()
        self.planner.reset(77)
        self.route = _route('ordinary_lane', [(0., 0., False), (0., 200., False)])
        self.manifest = [_bot(11, 1, 0, self.route)]
        self.states = [_state(11, 1, -66., 306.)]

    def orders(self, name='08_ruinberg'):
        return self.planner.build_orders(self.manifest, self.states, [], 1., map_name=name)['orders']

    def test_initial_goal_is_library_position_not_ordinary_route_node(self):
        order = self.orders()[0]
        self.assertTrue(lib.plan_matches_order(order))
        self.assertNotIn(order['move_position'], self.route['waypoints'])
        self.assertIn(order['spg_position_id'], lib._INDEX)
        self.assertEqual('artillery_deploy', order['combat_mode'])

    def test_server_does_not_park_fifteen_metres_early(self):
        order = self.orders()[0]
        goal = order['move_position']
        self.states[0].update(x=goal['x']+12., y=goal['y'], z=goal['z'])
        moving = self.orders()[0]
        self.assertIsNone(moving['throttle_override'])
        self.assertEqual('artillery_deploy', moving['combat_mode'])
        self.states[0]['x'] = goal['x']+1.
        parked = self.orders()[0]
        self.assertEqual('artillery_hold', parked['combat_mode'])
        self.assertEqual(0., parked['throttle_override'])

    def test_deployment_survives_route_change_and_target_leases(self):
        first = self.orders()[0]
        self.manifest[0]['route'] = _route('new_route', [(300., 100., False), (200., -300., False)])
        second = self.orders()[0]
        self.assertEqual(first['spg_position_id'], second['spg_position_id'])
        self.assertEqual(first['move_position'], second['move_position'])

    def test_map_change_and_reset_clear_old_reservations(self):
        self.orders()
        self.assertTrue(self.planner._spg_deployments)
        order = self.orders('35_steppes')[0]
        self.assertTrue(order['spg_position_id'].startswith('35_steppes:'))
        self.planner.reset(78)
        self.assertFalse(self.planner._spg_deployments)
        self.assertIsNone(self.planner._spg_map_name)

    def test_missing_source_is_explicit_legacy_fallback(self):
        order = self.orders('59_asia_great_wall')[0]
        self.assertNotIn('spg_position_id', order)
        self.assertEqual('missing_image', order['spg_position_status'])

    def test_non_artillery_and_at_spg_keep_original_goals(self):
        for kind in ('mediumTank', 'AT-SPG'):
            self.manifest[0]['profile']['class_tag'] = kind
            before = self.planner.build_orders(self.manifest, self.states, [], 1.)
            after = self.planner.build_orders(self.manifest, self.states, [], 1., map_name='08_ruinberg')
            self.assertEqual(before['orders'], after['orders'])
            self.assertNotIn('spg_position_id', after['orders'][0])

    def test_manual_move_supersedes_initial_plan_without_contradictory_metadata(self):
        def manual(order, *unused):
            order.update(combat_mode='radio_move', move_position={'x': 0., 'y': 0., 'z': 10.})
        with mock.patch.object(self.planner, '_apply_team_order', side_effect=manual):
            order = self.orders()[0]
        self.assertNotIn('spg_position_id', order)
        self.assertEqual('radio_move', order['combat_mode'])
        self.assertTrue(lib.plan_matches_order(order))

    def test_live_server_supplies_actual_selected_map_to_planner(self):
        text = (ROOT/'server/lan_battle_server.py').read_text()
        self.assertIn('team_orders=team_orders, map_name=self.map_name)', text)


class WorkerPositionTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: v for k, v in sys.modules.items() if k == 'gui' or k.startswith('gui.')}
        self.module = harness._load()
        self.runtime = self.module.BotRuntime(1)
        self.runtime.baked_graph = graph('08_ruinberg')
        self.runtime._navigation_map_name = '08_ruinberg'
        self.point = lib.DATA['maps']['08_ruinberg']['positions'][0]
        x, y, z = self.point['point']
        self.state = {'id': 11, 'team': 1, 'slot': 0, 'x': x+12., 'y': y, 'z': z,
                      'yaw': -math.pi/2, 'speed': 0., 'profile': {'class_tag': 'SPG'},
                      'route': {'waypoints': ((0., 0., False), (0., 300., False))}}
        self.runtime.states[11] = self.state
        self.order = order_for(self.point)

    def tearDown(self):
        for key in list(sys.modules):
            if key == 'gui' or key.startswith('gui.'):
                sys.modules.pop(key, None)
        sys.modules.update(self.saved)

    def position_order(self, order=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.runtime._artillery_position_order(self.state, order or self.order,
                {1000002: {'id': 1000002, 'position': (0., 0., 0.)}}, 5.)

    def test_worker_recomputes_arrival_and_does_not_accept_stale_server_hold(self):
        result = self.position_order(dict(self.order, combat_mode='artillery_hold', throttle_override=0.))
        self.assertEqual('artillery_deploy', result['combat_mode'])
        self.assertIsNone(result['throttle_override'])
        self.assertIsNone(result['target_id'])
        self.assertFalse(result['fire_allowed'])
        self.assertEqual(self.point['point'][0]+12., self.state['x'])  # no teleport

    def test_actual_arrival_restores_target_and_fire_attempt_without_bypass(self):
        self.state['x'] = self.point['point'][0]+1.
        result = self.position_order()
        self.assertEqual('artillery_hold', result['combat_mode'])
        self.assertEqual(1000002, result['target_id'])
        self.assertTrue(result['fire_allowed'])  # existing exact arc gate still owns shell launch
        self.assertEqual(0., result['throttle_override'])

    def test_matching_order_passes_boundary_but_forged_goal_does_not(self):
        message = {'bot_orders': [self.order], 'bot_order_revision': 1}
        self.assertTrue(self.runtime._apply_orders(message))
        bad = dict(self.order, move_position=(0., 0., 0.))
        self.assertFalse(self.runtime._apply_orders(dict(message, bot_orders=[bad], bot_order_revision=2)))
        self.assertEqual(self.point['id'], self.runtime._server_orders[11]['spg_position_id'])

    def test_worker_refuses_library_for_wrong_graph_without_scene_queries(self):
        self.runtime.baked_graph = dict(self.runtime.baked_graph, map='35_steppes')
        result = self.position_order()
        self.assertEqual('spg_invalid_position', result['combat_mode'])
        self.assertFalse(result['fire_allowed'])
        self.assertEqual(0., result['throttle_override'])
        self.assertEqual('library_graph_mismatch', self.state['_spg_position_event'])

    def test_base_defense_preempts_library_parking(self):
        defense = dict(self.order, combat_mode='base_defense')
        self.assertEqual(defense, self.position_order(defense))

    def test_real_driver_continues_through_old_fifteen_metre_stop_zone(self):
        result = self.position_order()
        # Real LocalDriver/adapter, no rewritten driver or fake throttle.
        adapter = object.__new__(BotAdapter)
        adapter.driver = LocalDriver()
        adapter.navigation_target = None
        decision = {'id': 11, 'slot': 0, 'position': (self.state['x'], self.state['y'], self.state['z']),
                    'yaw': -math.pi/2, 'speed': 0., 'dt': .1, 'now': 5.}
        command = adapter.decide_with_order(decision, result, lambda unused: True)
        self.assertGreater(command['throttle'], 0.)
        self.assertIsNone(command['target_id'])
        self.assertFalse(command['fire_allowed'])
        self.assertNotEqual('arrived', command['recovery_mode'])

    def test_deployment_navigation_cache_is_not_keyed_by_enemy(self):
        source = (ROOT/'src/res/scripts/client/gui/mods/offline_lan_0922/bot_runtime.py').read_text()
        self.assertIn("'spg_deployment',\n                        strategic['spg_position_id']", source)

if __name__ == '__main__':
    unittest.main()
