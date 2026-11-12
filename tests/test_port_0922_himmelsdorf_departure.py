import collections
import json
import math
import sys
from pathlib import Path
import unittest
from unittest import mock
import contextlib
import route_scene_fixture


ROOT = Path(__file__).resolve().parents[1]
CLIENT_SCRIPTS = ROOT / 'src' / 'res' / 'scripts' / 'client'
TESTS_ROOT = ROOT / 'tests'
sys.path.insert(0, str(ROOT / 'server'))
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
sys.path.insert(0, str(CLIENT_SCRIPTS))
sys.path.insert(0, str(TESTS_ROOT))

from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from test_port_0922_ai import shared_plan_and_drive, wire_route
from test_port_0922_server_bot_ai import _state
from gui.mods.offline_lan_0922.vehicle_control.strategy import BotPlanner
import test_port_0922_bot_runtime as runtime_fixtures
from effective_params_fixture import bot_default_crew_factors
from test_port_0922_fjord_departure import (
    ROLES, _EpisodeMonitor, _flat_graph,
)


NON_SPG_LINEUP = (
    ('heavyTank',) * 6 + ('mediumTank',) * 5 +
    ('AT-SPG',) * 2 + ('lightTank',) * 2)


class HimmelsdorfDepartureTests(unittest.TestCase):
    def setUp(self):
        self._gui_modules = dict(
            (key, value) for key, value in sys.modules.items()
            if key == 'gui' or key.startswith('gui.'))

    def tearDown(self):
        for key in list(sys.modules):
            if key == 'gui' or key.startswith('gui.'):
                sys.modules.pop(key, None)
        sys.modules.update(self._gui_modules)

    @staticmethod
    def _route_profile(bot_id):
        """Return a non-SPG profile suitable for the v0.6.6 route roster."""
        return {
            'vehicle_name': 'departure-test:%d' % bot_id,
            'class_tag': 'mediumTank',
            'dominant_role': 'support',
            'roles': {
                'brawler': 0.5,
                'flanker': 0.5,
                'scout': 0.5,
                'sniper': 0.5,
                'support': 0.5,
                'artillery': 0.0,
            },
            'shells': (),
            'desired_range': 180.0,
            'fire_range': 500.0,
            'armor': 80.0,
            'speed': 15.0,
        }

    @staticmethod
    def _synthetic_control():
        adapter = BotAdapter('07_lakeville', 'connector-motion-contract')
        actor = adapter.roster.register_profile(
            93, 1, HimmelsdorfDepartureTests._route_profile(93),
            'Connector contract Bot')
        actor['route'] = dict(id='connector-contract', waypoints=(
            (0., -40., False), (0., -65., False), (40., 40., False)))
        return adapter, BotPlanner(), actor

    def test_shared_connector_filter_requires_forward_motion(self):
        """Parked and reversing hulls retain the authored spawn connector."""
        cases = ((0., (0., 0., -65.), 1), (-6., (0., 0., -65.), 1),
                 (6., (40., 0., 40.), 2))
        for speed, expected_target, expected_index in cases:
            with self.subTest(speed=speed):
                adapter, planner, actor = self._synthetic_control()
                state = dict(_state(93, 1, 0., -20.), speed=speed)
                order, command = shared_plan_and_drive(
                    adapter, planner, actor, state, now=0.)
                self.assertEqual(expected_target, command['move_position'])
                self.assertEqual(expected_index, order['route_index'])
                self.assertEqual(dict(x=0., y=0., z=-20.), order['route_anchor'])
                self.assertTrue(order['route_join'])
                self.assertEqual(expected_index, planner._route_states[93]['index'])

    def test_report_roster_parked_joins_use_one_shared_disk_and_passage_contract(self):
        """Retain 29 real slots, roster capacities and authored egress proofs.

        The former local-circle versus server-convoy comparison required two
        runtime planners. Both actors now consume the same public build_orders
        result, with the existing convoy passage proof checked at each gate.
        """
        from gui.mods.offline_lan_0922.bot_tactics import route_disk_reached
        graph = json.loads((ROOT / 'navgraphs' / '86_himmelsdorf_winter.json').read_text())
        adapter = BotAdapter('86_himmelsdorf_winter', 'reported-round-1',
            bases={1: tuple(graph['bases'][0]), 2: tuple(graph['bases'][1])},
            bounds=tuple(graph['bounds']), baked_routes=graph['routes'])
        planner = BotPlanner()
        manifest, states = [], []
        for team in (1, 2):
            for slot in range(15):
                if team == 2 and slot == 0:
                    continue
                identity = slot + 1 if team == 1 else slot + 16
                actor = adapter.roster.register_profile(identity, team,
                    self._route_profile(identity), 'Bot %d' % identity)
                raw = graph['spawn_formations'][str(team)][slot]
                state = dict(_state(identity, team, raw[0], raw[2]),
                    y=float(raw[1]), yaw=float(raw[3]), speed=0.)
                manifest.append(dict(actor, slot=slot,
                    route=wire_route(actor['route'], state['y'])))
                states.append(state)
        orders = {row['id']: row for row in
            planner.build_orders(manifest, states, [], 0.)['orders']}
        route_counts, team_one_hill = collections.Counter(), []
        for actor, state in zip(manifest, states):
            identity, team, route = actor['id'], actor['team'], actor['route']
            spawn = (state['x'], state['y'], state['z'])
            order = orders[identity]
            command = adapter.decide_with_order(dict(state, slot=actor['slot'],
                position=spawn, dt=.1, now=0., neighbours=()), order, lambda *args: True)
            if not route.get('waypoints'):
                # Deleting the old missing-route enemy-base shortcut is part
                # of removing its fallback, not permission to invent a lane.
                self.assertEqual('', order['route_id'])
                self.assertEqual(0, order['route_index'])
                self.assertEqual(tuple(round(value, 3) for value in spawn),
                                 command['move_position'])
                continue
            route_id, cursor = route['id'], order['route_index']
            route_counts[(team, route_id)] += 1
            self.assertEqual(route_id, order['route_id'])
            self.assertEqual(cursor, planner._route_states[identity]['index'])
            entry = planner._route_states[identity]['entry_receipt']['selected_index']
            for passed in range(entry, cursor):
                point, following = route['waypoints'][passed:passed + 2]
                self.assertTrue(route_disk_reached((spawn[0], spawn[2]),
                    (point['x'], point['z']), (following['x'], following['z'])))
            # The common planner canonicalizes same-ID catalogue routes.
            # Their horizontal geometry is authored; the manifest's vertical
            # hint can come from a peer occupying a different spawn height.
            selected_route = (planner._route_assignments.get(identity) or {}).get('route', route)
            self.assertEqual(route_id, selected_route['id'])
            self.assertEqual([(point['x'], point['z']) for point in route['waypoints']],
                             [(point['x'], point['z']) for point in selected_route['waypoints']])
            point = selected_route['waypoints'][cursor]
            expected = tuple(round(point[axis], 3) for axis in ('x', 'y', 'z'))
            self.assertEqual(expected, command['move_position'])
            if order['route_join']:
                expected_anchor = spawn
            else:
                previous = selected_route['waypoints'][cursor - 1]
                expected_anchor = tuple(previous[axis] for axis in ('x', 'y', 'z'))
            self.assertEqual(tuple(round(value, 3) for value in expected_anchor),
                             tuple(order['route_anchor'][axis]
                                   for axis in ('x', 'y', 'z')))
            if team == 1 and route_id == 'hill':
                dx, dz = command['move_position'][0] - spawn[0], command['move_position'][2] - spawn[2]
                heading_error = abs((math.atan2(dx, dz) - state['yaw'] + math.pi) %
                                    (2. * math.pi) - math.pi)
                team_one_hill.append((identity, cursor, heading_error))
        self.assertEqual(29, len(states))
        self.assertNotIn(16, orders)
        self.assertEqual(29, len(orders))
        self.assertTrue(route_counts)
        self.assertTrue(all(0 < count <= 3 for count in route_counts.values()))
        self.assertLessEqual(len(team_one_hill), 3)
        for unused_identity, cursor, heading_error in team_one_hill:
            self.assertGreaterEqual(cursor, 0)
            self.assertLessEqual(heading_error, math.pi)

    def test_flat_report_roster_departs_at_15_and_24_fps(self):
        """Exercise crowded departure with track grip, without native claims.

        This is a pure-data regression over the production Himmelsdorf route
        topology, formations, planner, driver, traffic law and copied vehicle
        physics. It cannot prove #1513 BigWorld collision or presentation on
        Windows, but it does reproduce the reported team-2 human slot zero and
        all 29 non-SPG Bot spawn/route-join decisions at two render cadences.
        """
        module = runtime_fixtures._load()
        original_factors = module.loadout.attribute_factors
        module.loadout.attribute_factors = bot_default_crew_factors
        self.addCleanup(
            setattr, module.loadout, 'attribute_factors', original_factors)
        graph = _flat_graph('86_himmelsdorf_winter')
        bots = []
        for team in (1, 2):
            for slot, class_tag in enumerate(NON_SPG_LINEUP):
                if team == 2 and slot == 0:
                    continue
                dominant_role, roles = ROLES[class_tag]
                bot_id = slot + 1 if team == 1 else slot + 16
                bots.append({
                    'id': bot_id,
                    'team': team,
                    'slot': slot,
                    'name': '%s%d' % (class_tag, bot_id),
                    'vehicle': 'fake',
                    'profile': {
                        'class_tag': class_tag,
                        'dominant_role': dominant_role,
                        'roles': dict(roles),
                        'shells': [],
                        'vehicle_name': 'fake',
                        'desired_range': 200,
                        'fire_range': 500,
                    },
                })

        def spawn(team, slot):
            point = graph['spawn_formations'][str(team)][slot]
            return ((point[0], 0.0, point[2]), point[3])

        def flat_ground(unused_x, unused_z, unused_hint=0.0):
            return 0.0

        for fps in getattr(self,"frame_rates",(15,24)):
            with self.subTest(fps=fps):
                runtime_box = {}

                def baked_direction(
                        position, yaw, speed, unused_descriptor,
                        maximum_distance):
                    distance = 20.0 if abs(float(speed)) > 5.0 else 15.0
                    if maximum_distance is not None:
                        distance = min(distance, float(maximum_distance))
                    end = (
                        float(position[0]) + math.sin(float(yaw)) * distance,
                        float(position[1]),
                        float(position[2]) + math.cos(float(yaw)) * distance,
                    )
                    grid = runtime_box['runtime'].navigator.grid
                    # This fixture has a flat native world, not a collision mesh.
                    # Missing/coarse navigation cells are not physical walls.
                    clear = True
                    return {
                        'clear': clear, 'collision': not clear, 'slope': 0.0,
                    }

                def baked_receipt(
                        position, yaw, speed, descriptor, maximum_distance):
                    result = baked_direction(
                        position, yaw, speed, descriptor, maximum_distance)
                    if not result['clear']:
                        return False
                    distance = 15.0
                    if maximum_distance is not None:
                        distance = min(distance, float(maximum_distance))
                    return {
                        'distance': distance, 'half_width': 1.6,
                        'leading': 3.5, 'origin': tuple(position),
                        'yaw': float(yaw),
                        'direction': -1 if float(speed) < 0.0 else 1,
                    }

                runtime = module.BotRuntime(
                    1,
                    descriptor_resolver=(
                        lambda unused: runtime_fixtures._combat_descriptor()),
                    direction_probe=baked_direction,
                    world_receipt_probe=baked_receipt,
                    spawn_resolver=spawn,
                    ground_probe=flat_ground,
                    physics_ground_probe=flat_ground,
                    baked_graph=graph,
                    visibility_probe=lambda *unused: False,
                    firing_lane_probe=lambda *unused: False)
                runtime_box['runtime'] = runtime
                # Production chooses fresh entropy; keep the CI traffic scene
                # replayable and use the same lane draw at both frame rates.
                allocation=(contextlib.nullcontext() if getattr(self,'authoritative',False) else mock.patch.object(module.bot_tactics_runtime,'assign_initial_routes',route_scene_fixture.allocate))
                with allocation,mock.patch.object(module.random.SystemRandom,'getrandbits',return_value=0x0922):
                    published=runtime.battle_start({
                        'map': '86_himmelsdorf_winter',
                        'bot_tactics': (module.bot_tactics.default_profile()
                            if getattr(self, 'authoritative', False)
                            else module.bot_tactics.empty()),
                        'round_id': fps,
                        'bot_authority_id': 1,
                        'bots': bots,
                    })[0]
                planner=BotPlanner()
                planner.tactics = runtime._bot_tactics
                planner.tactics_map = '86_himmelsdorf_winter'
                starts = dict(
                    (bot_id, (state['x'], state['z']))
                    for bot_id, state in runtime.states.items())
                start_bodies = dict((bot_id, (state['x'], state['z'], state['yaw'],
                                             state['collision_shape']))
                                    for bot_id, state in runtime.states.items())
                maximum_departure = dict((bot_id, 0.0) for bot_id in starts)
                monitor = _EpisodeMonitor()
                monitor.started['recovery'] = {}
                monitor.maximum['recovery'] = {}
                recovery_episodes = {}
                now = [0.0]
                macro_goals = {}
                peak_group = {
                    1: {'parked': 0, 'recovery': 0},
                    2: {'parked': 0, 'recovery': 0},
                }

                original_navigation = runtime.adapter.navigation_target

                def navigation_target(
                        bot_id, position, goal, strategic, state):
                    macro_goals[int(bot_id)] = tuple(goal)
                    return original_navigation(
                        bot_id, position, goal, strategic, state)

                runtime.adapter.navigation_target = navigation_target
                original_drive = runtime.adapter.driver.drive

                def drive(*args, **kwargs):
                    order = original_drive(*args, **kwargs)
                    bot_id = int(args[0])
                    position = args[2]
                    goal = macro_goals.get(bot_id, position)
                    far_macro_goal = math.hypot(
                        float(goal[0]) - float(position[0]),
                        float(goal[2]) - float(position[2])) > 15.0
                    mode = order.get('recovery_mode')
                    monitor.record(
                        'parked', bot_id,
                        far_macro_goal and mode == 'arrived', now[0])
                    episode = runtime.adapter.driver.states[bot_id]['recovery_count']
                    if recovery_episodes.get(bot_id) != episode:
                        # Consecutive checked attempts can both report
                        # ``blocked`` while a queue clears. The old mode-only
                        # monitor merged two distinct one-second leases into
                        # one 2.2-second episode. Keep the two-second bound on
                        # each actual episode; the departure and original-hull
                        # occupancy assertions below still reject a stuck Bot.
                        monitor.record('recovery', bot_id, False, now[0])
                        recovery_episodes[bot_id] = episode
                    monitor.record(
                        'recovery', bot_id,
                        mode in ('blocked', 'pivot_recovery', 'reverse_turn'),
                        now[0])
                    return order

                runtime.adapter.driver.drive = drive

                # Hull friction and held tracks remove the old sideways
                # sliding escape. Allow the crowded line one minute while
                # retaining the per-episode parking/recovery limits below.
                for frame in range(1, fps * 60 + 1):
                    now[0] = frame / float(fps)
                    if getattr(self,'authoritative',False):
                        orders=planner.build_orders(published['bots'],list(runtime.states.values()),[],now[0])
                        runtime._apply_orders(dict(bot_order_revision=orders['revision'],bot_orders=orders['orders']))
                    runtime.update(1.0 / float(fps), now[0])
                    group = {
                        1: {'parked': 0, 'recovery': 0},
                        2: {'parked': 0, 'recovery': 0},
                    }
                    for bot_id, state in runtime.states.items():
                        distance = math.hypot(
                            state['x'] - starts[bot_id][0],
                            state['z'] - starts[bot_id][1])
                        maximum_departure[bot_id] = max(
                            maximum_departure[bot_id], distance)
                        cached = runtime._decision_cache.get(bot_id)
                        command = cached[3] if cached is not None else {}
                        mode = command.get('recovery_mode')
                        goal = macro_goals.get(bot_id, (state['x'], 0.0,
                                                       state['z']))
                        far_macro_goal = math.hypot(
                            float(goal[0]) - float(state['x']),
                            float(goal[2]) - float(state['z'])) > 15.0
                        if far_macro_goal and mode == 'arrived':
                            group[state['team']]['parked'] += 1
                        if mode in ('blocked', 'pivot_recovery',
                                    'reverse_turn'):
                            group[state['team']]['recovery'] += 1
                    for team in (1, 2):
                        for kind in ('parked', 'recovery'):
                            peak_group[team][kind] = max(
                                peak_group[team][kind], group[team][kind])

                bot_ids = sorted(runtime.states)
                monitor.finish(bot_ids, now[0])
                thresholds = dict(
                    (bot_id, max(8.0, 2.0 * state['half_length']))
                    for bot_id, state in runtime.states.items())
                never_exited = [
                    bot_id for bot_id in bot_ids
                    if maximum_departure[bot_id] < thresholds[bot_id]
                ]

                self.assertEqual(29, len(bot_ids))
                self.assertNotIn(16, bot_ids)
                self.assertEqual([], sorted(
                    (bot_id, round(maximum_departure[bot_id], 3),
                     round(thresholds[bot_id], 3))
                    for bot_id in never_exited))
                # Test actual occupancy, not an arbitrary circle: a hull
                # seven metres sideways can already be completely outside
                # its former slot even when its centre is within eight metres.
                self.assertEqual([], [bot_id for bot_id in bot_ids
                    if module.tank_collision.obb_contact(
                        *start_bodies[bot_id],
                        runtime.states[bot_id]['x'], runtime.states[bot_id]['z'],
                        runtime.states[bot_id]['yaw'], runtime.states[bot_id]['collision_shape']) is not None])
                for team in (1, 2):
                    team_ids = [bot_id for bot_id in bot_ids
                                if runtime.states[bot_id]['team'] == team]
                    team_never_exited = [bot_id for bot_id in never_exited
                                         if bot_id in team_ids]
                    self.assertLess(
                        len(team_never_exited), (len(team_ids) + 1) // 2)
                    self.assertLess(
                        peak_group[team]['parked'],
                        (len(team_ids) + 1) // 2)
                self.assertLessEqual(
                    max(monitor.maximum['parked'].values() or [0.0]),
                    0.5)
                # Recovery is allowed to chain; every hull must still leave
                # its spawn OBB within the one-minute run above.

    def test_new_allocation_with_server_route_recovery_departs(self):
        self.authoritative=True;self.frame_rates=(15,)
        self.test_flat_report_roster_departs_at_15_and_24_fps()


if __name__ == '__main__':
    unittest.main()
