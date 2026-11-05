"""Real-map foreground navigation completion and adversarial ownership tests.

The Caucasus column faces replay recorded native evidence; the other native
seams replay map heights. PlayerPathfinder/PlayerTerrainGrid are never replaced.
These contracts do not establish Windows physics, timing or driving feel.
"""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import bot_tactics, prebaked_navigation, native_navigation_query
from gui.mods.offline_lan_0922.player_control.pathfinding import PlayerPathfinder, PlayerTerrainGrid
from gui.mods.offline_lan_0922.player_control.local_height import MAX_COLUMNS
from gui.mods.offline_lan_0922.player_control.navigation import PlayerNavigation
from gui.mods.offline_lan_0922.player_control.strategy import Strategy


ORIGIN = (9.427737630211562, -14.861078262329102, 104.35341621625808)
FLOOR = -14.873424530029297
DECK = .9740817546844482
LOCAL_GATE = (1.9548214691137655, 105.15099152270032)


def pose(now=0., position=ORIGIN, speed=0., yaw=0.):
    return dict(id=17, engine_id=5017, now=now, position=tuple(position),
                speed=speed, yaw=yaw, half_length=2., half_width=1.)


class RealNavigationCase(unittest.TestCase):
    def setUp(self):
        self.config = mock.patch.object(prebaked_navigation, 'CONFIG_PATH', str(ROOT / 'config.json'))
        self.config.start()
        self.addCleanup(self.config.stop)

    def navigation(self, name='37_caucasus', tag='heavyTank', profile=None, ground=None, columns=None):
        graph = prebaked_navigation.load_graph(name)
        holder = {}
        if ground is None:
            ground = lambda x, z, hint: holder['nav'].navigator.grid._ground(x, z, hint)
        owner = SimpleNamespace(_start_message=dict(map=name,
            bot_tactics=profile if profile is not None else bot_tactics.empty()),
            client=SimpleNamespace(team=1), _arena_bounds=graph['bounds'],
            _navigation_ground=ground, _navigation_obstacle=lambda *args: False,
            _navigation_height_columns=columns)
        descriptor = SimpleNamespace(type=SimpleNamespace(tags=[tag]))
        # No native engine exists here; only its optional acceleration factory
        # is disabled. Both real routing/search and local-link code execute.
        with mock.patch.object(native_navigation_query.Oracle, 'create', return_value=None):
            nav = PlayerNavigation(owner, descriptor)
        holder['nav'] = nav
        self.addCleanup(nav.close)
        self.assertIsInstance(nav.navigator, PlayerPathfinder)
        self.assertIsInstance(nav.navigator.grid, PlayerTerrainGrid)
        self.assertTrue(nav.navigator.grid.prebaked)
        return nav

    def columns(self, status='complete', wet=False):
        calls = []
        def probe(x, z, low, high):
            calls.append((x, z, low, high))
            return dict(status=status, surfaces=[dict(point=(x, y, z), normal=(0., 1., 0.),
                navigation_water=wet and y == FLOOR) for y in (FLOOR, DECK) if low <= y <= high])
        return probe, calls

    def terminal_capture(self, empty=False):
        nav = self.navigation('95_lost_city')
        # Exercise the capture handoff from a reachable route endpoint
        # outside the flag, independent of the Default endpoint policy.
        point = prebaked_navigation.load_graph('95_lost_city')['spawn_anchors'][1]
        route = dict(id='capture-approach', waypoints=[point])
        state = pose(0., (point[0], nav._height(point, 0.), point[1]))
        nav.route, nav.index = route, len(route['waypoints']) - 1
        nav.set_context(dict(empty_ammo=empty, supported=True, contacts=[], allies=[], base={}))
        nav.decide(state, lambda *args: True)
        self.assertIsNotNone(nav.mission)
        self.assertFalse(nav.mission.explicit)
        self.assertFalse(nav.mission.arrival['inside'])
        return nav, state

    def td(self):
        nav = self.navigation('02_malinovka', 'AT-SPG', bot_tactics.default_profile())
        route = next(row for row in nav.routes if row['id'] == 'class_td_west_lake_road')
        index = next(i for i, point in enumerate(route['waypoints']) if bot_tactics.waiting_positions(point))
        nav.route, nav.index = route, index
        point = route['waypoints'][index]
        state = pose(0., (point[0], nav._height(point, 0.), point[1]))
        nav.set_context(dict(empty_ammo=False, supported=True, contacts=[], allies=[], base={}))
        return nav, state, index, bot_tactics.waiting_positions(point)

    def native_parking(self, columns):
        nav = self.navigation('37_caucasus', 'AT-SPG',
                              ground=lambda *args: FLOOR, columns=columns)
        nav.route = dict(id='native-parking', waypoints=[
            [ORIGIN[0], ORIGIN[2], 1, 0., [[ORIGIN[0], ORIGIN[2], 60.]]],
            [ORIGIN[0] + 15., ORIGIN[2], 0]])
        nav.index = 0
        nav.set_context(dict(supported=True, empty_ammo=False, contacts=[], allies=[]))
        return nav


class RealSupportCompletionTests(RealNavigationCase):
    def test_recorded_caucasus_lower_floor_completes_hold_on_real_bake(self):
        columns, calls = self.columns()
        nav = self.navigation(ground=lambda *args: FLOOR, columns=columns)
        self.assertAlmostEqual(1.109, nav.navigator.grid._ground(ORIGIN[0], ORIGIN[2], ORIGIN[1]))
        nav.start_mission('hold_position', dict(command_id='recorded-floor'), pose())
        nav.set_context(dict(supported=True, overturned=False))
        for now in (0., 1., 31.):
            nav.movement_policy(pose(now))
        receipt = nav.mission_status()
        self.assertEqual('completed', receipt['status'])
        self.assertEqual('arrived_and_held', receipt['reason'])
        self.assertAlmostEqual(FLOOR, nav._height((ORIGIN[0], ORIGIN[2]), ORIGIN[1]))
        self.assertIs(nav.support.links, nav.navigator.grid.local_height_links)
        self.assertEqual(3, len(calls))
        self.assertAlmostEqual(1.109, nav.navigator.grid._ground(ORIGIN[0], ORIGIN[2], ORIGIN[1]))

    def test_real_grid_joins_and_drives_local_lower_floor_without_deck_snap(self):
        columns, unused = self.columns()
        nav = self.navigation(ground=lambda *args: FLOOR, columns=columns)
        nav.selection = [dict(id='recorded_local_gate', waypoints=[LOCAL_GATE])]
        self.assertTrue(nav.join(ORIGIN, 0.))
        self.assertEqual('joined_native_floor', nav.receipt['status'])
        self.assertAlmostEqual(FLOOR, nav.receipt['goal'][1])
        nav.set_context(dict(supported=True))
        order = nav.decide(pose(), lambda *args: True)
        self.assertAlmostEqual(FLOOR, order['local_target'][1])
        self.assertFalse(order['holding'])
        self.assertLessEqual(order['height_support']['native_queries'], MAX_COLUMNS)

    def test_explicit_upper_point_cannot_borrow_connected_lower_floor(self):
        columns, unused = self.columns()
        nav = self.navigation(ground=lambda *args: FLOOR, columns=columns)
        nav.start_mission('hold_position', dict(position=(LOCAL_GATE[0], DECK, LOCAL_GATE[1])), pose())
        nav.set_context(dict(supported=True))
        order = nav.decide(pose(1.), lambda *args: True)
        self.assertFalse(nav.mission_status()['arrival']['height_matches'])
        self.assertIsNone(nav.route)
        self.assertEqual(ORIGIN, order['local_target'])
        self.assertNotEqual('completed', nav.mission.status)

    def test_missing_incomplete_and_wet_columns_never_fall_back_to_baked_support(self):
        for status, wet in (('deferred', False), ('layer_limit', False), ('complete', True)):
            with self.subTest(status=status, wet=wet):
                columns, unused = self.columns(status, wet)
                nav = self.navigation(ground=lambda *args: FLOOR, columns=columns)
                nav.start_mission('hold_position', {}, pose())
                nav.set_context(dict(supported=True))
                nav.movement_policy(pose(1.))
                self.assertFalse(nav.mission.arrival['supported'])
                self.assertIsNone(nav._height((ORIGIN[0], ORIGIN[2]), ORIGIN[1]))

    def test_live_airborne_and_overturned_flags_still_veto_native_floor(self):
        for context in (dict(supported=False), dict(supported=True, overturned=True)):
            columns, unused = self.columns()
            nav = self.navigation(ground=lambda *args: FLOOR, columns=columns)
            nav.start_mission('hold_position', {}, pose())
            nav.set_context(context)
            nav.movement_policy(pose(1.))
            self.assertFalse(nav.mission.arrival['supported'])

    def test_native_ground_and_columns_share_one_budget_for_same_sample(self):
        columns, calls = self.columns()
        ground_calls = []
        def ground(x, z, hint):
            ground_calls.append((x, z, hint))
            return FLOOR
        nav = self.navigation(ground=ground, columns=columns)
        nav.set_context(dict(supported=True))
        nav.movement_policy(pose())
        for index in range(100):
            nav._height((ORIGIN[0] + .025 * index, ORIGIN[2] + 2.), ORIGIN[1])
        before = len(calls) + len(ground_calls)
        nav.movement_policy(pose())
        nav.support.begin(ORIGIN, 0.)
        nav._height((ORIGIN[0] + 3., ORIGIN[2]), ORIGIN[1])
        self.assertLessEqual(before, MAX_COLUMNS)
        self.assertEqual(before, len(calls) + len(ground_calls))
        self.assertEqual(before, nav.support.native_queries)

    def test_link_scope_and_state_are_private_to_each_live_player(self):
        columns, calls = self.columns()
        first = self.navigation(ground=lambda *args: FLOOR, columns=columns)
        second = self.navigation(ground=lambda *args: FLOOR, columns=columns)
        first.support.begin(ORIGIN, 0.)
        moved = (ORIGIN[0] + 30., ORIGIN[1], ORIGIN[2])
        second.support.begin(moved, 0.)
        self.assertIsNot(first.support.links, second.support.links)
        self.assertEqual(ORIGIN, first.support.links.origin)
        before = len(calls)
        first._height((moved[0], moved[2]), moved[1])
        self.assertEqual(before, len(calls))
        first.support.begin(moved, 1.)
        first._height((moved[0], moved[2]), moved[1])
        self.assertEqual(moved, first.support.links.origin)
        self.assertGreater(len(calls), before)


class AutomaticMissionCompletionTests(RealNavigationCase):
    def test_armed_implicit_capture_travel_can_accept_emergency_defence(self):
        nav, state = self.terminal_capture()
        alarm = dict(points=80, invaders=1)
        nav.set_context(dict(empty_ammo=False, supported=True, base=alarm))
        state['now'] = 1.
        self.assertTrue(nav.movement_policy(state)['allow_strategy'])
        strategy = Strategy()
        routes = strategy.decide(1., nav.routes, nav.route, [], [], alarm, nav.home,
                                 mission=nav.mission_status())
        self.assertTrue(nav.retask(routes, 'defend'))
        self.assertIsNone(nav.mission)
        self.assertTrue(nav.automatic_defence)
        self.assertEqual('automatic_retask_defend', nav.previous_mission['reason'])

    def test_actual_flag_occupancy_retains_capture_even_during_alarm(self):
        nav, state = self.terminal_capture()
        point = nav.enemy_area['point']
        arrived = pose(1., (point[0], nav.navigator.grid._ground(point[0], point[1], 0.), point[1]))
        nav.set_context(dict(empty_ammo=False, supported=True, base=dict(points=80, invaders=1)))
        policy = nav.movement_policy(arrived)
        self.assertTrue(policy['holding'])
        self.assertFalse(policy['allow_strategy'])
        self.assertFalse(nav.retask([dict(id='player_base_defence', waypoints=[nav.home])], 'defend'))
        self.assertEqual('capture_base', nav.mission.objective)

    def test_rejected_artillery_strategy_preserves_automatic_mission_identity(self):
        nav = self.navigation('95_lost_city', 'SPG')
        nav._automatic_capture(pose(), 'route_terminal_capture')
        original = nav.mission
        nav.artillery.mode = 'parking'
        self.assertFalse(nav.retask(nav.routes, 'squad'))
        self.assertIs(original, nav.mission)
        self.assertNotIn(original.status, ('failed', 'cancelled'))
        self.assertIsNone(nav.previous_mission)

    def test_failed_automatic_task_releases_hull_and_fire_owner_with_bounded_retry(self):
        nav, state = self.terminal_capture()
        failed_id = nav.mission.identity
        state['now'] = 31.
        policy = nav.movement_policy(state)
        self.assertTrue(policy['allow_strategy'])
        self.assertFalse(policy['holding'])
        self.assertIsNone(nav.mission)
        recovery = nav.mission_status()['automatic_recovery']
        self.assertEqual('no_navigation_progress', recovery['previous']['result']['reason'])
        self.assertEqual(36., recovery['retry_at'])
        order = nav.decide(state, lambda *args: True)
        self.assertNotIn('mission', order)
        self.assertNotIn((order.get('mission') or {}).get('status'), ('failed', 'cancelled'))
        state['now'] = 35.
        self.assertFalse(nav._capture_handoff(state))
        state['now'] = 36.
        self.assertTrue(nav._capture_handoff(state))
        self.assertNotEqual(failed_id, nav.mission.identity)

    def test_no_ammo_recovery_never_admits_defence_or_combat_withdrawal(self):
        nav, state = self.terminal_capture(empty=True)
        state['now'] = 31.
        policy = nav.movement_policy(state)
        self.assertFalse(policy['allow_strategy'])
        self.assertFalse(policy['allow_withdrawal'])
        self.assertFalse(policy['allow_firing_position'])
        self.assertFalse(nav.retask([dict(id='player_base_defence', waypoints=[nav.home])], 'defend'))
        state['now'] = 36.
        nav.movement_policy(state)
        self.assertIsNotNone(nav.mission)
        self.assertEqual('capture_base', nav.mission.objective)

    def test_explicit_mission_priority_does_not_depend_on_travel_or_failure(self):
        for action in ('attack', 'return_base', 'defend_base', 'hold_position'):
            nav = self.navigation('95_lost_city')
            nav.start_mission(action, dict(timeout=1.), pose())
            nav.set_context(dict(supported=True, base=dict(points=80, invaders=1)))
            nav.movement_policy(pose(2.))
            self.assertIsNotNone(nav.mission)
            self.assertFalse(nav.retask([dict(id='player_base_defence', waypoints=[nav.home])], 'defend'))
            self.assertEqual(action, nav.mission.action)


class AuthoredParkingCompletionTests(RealNavigationCase):
    def test_real_native_footprint_resumes_without_exceeding_one_sample_budget(self):
        columns, calls = self.columns()
        nav = self.native_parking(columns)
        first = nav.decide(pose(), lambda *args: True)
        record = nav.parking.records[('native-parking', 0)]
        self.assertEqual('recheck', first['parking']['phase'])
        self.assertFalse(record['complete'])
        self.assertGreater(record['scans'][0]['verified'], 0)
        self.assertLess(record['scans'][0]['verified'], 8)
        self.assertLessEqual(nav.support.native_queries, MAX_COLUMNS)
        second = nav.decide(pose(.1), lambda *args: True)
        self.assertEqual('waiting', second['parking']['phase'])
        self.assertEqual(.1, second['parking']['arrived_at'])
        self.assertEqual(FLOOR, record['goal'][1])
        self.assertLessEqual(nav.support.native_queries, MAX_COLUMNS)
        self.assertGreater(len(calls), 0)

    def test_partial_footprint_is_discarded_after_geometry_revision_or_expiry(self):
        for changed in ('generation', 'expired', 'moved'):
            with self.subTest(changed=changed):
                columns, calls = self.columns()
                source = dict(revision=1)
                def probe(*args):
                    result = columns(*args)
                    result['generation'] = (123, source['revision'])
                    return result
                nav = self.native_parking(probe)
                nav.decide(pose(), lambda *args: True)
                record = nav.parking.records[('native-parking', 0)]
                now, position = .1, ORIGIN
                if changed == 'generation':
                    source['revision'] = 2
                elif changed == 'expired':
                    now = 1.
                else:
                    position = (ORIGIN[0] + .3, ORIGIN[1], ORIGIN[2])
                nav.decide(pose(now, position), lambda *args: True)
                scan = record['scans'][0]
                self.assertEqual(now, scan['at'])
                self.assertEqual(position, scan['origin'])
                self.assertEqual((123, source['revision']), scan['generation'])
                self.assertLessEqual(nav.support.native_queries, MAX_COLUMNS)

    def test_incomplete_budget_and_temporary_exception_recheck_then_recover(self):
        for unavailable in ('layer_limit', 'query_budget', 'exception'):
            with self.subTest(unavailable=unavailable):
                columns, calls = self.columns()
                source = dict(status=unavailable)
                def probe(*args):
                    if source['status'] == 'exception':
                        raise RuntimeError('space temporarily unavailable')
                    if source['status'] != 'complete':
                        return dict(status=source['status'], surfaces=[])
                    return columns(*args)
                nav = self.native_parking(probe)
                first = nav.decide(pose(), lambda *args: True)
                record = nav.parking.records[('native-parking', 0)]
                self.assertEqual('recheck', first['parking']['phase'])
                self.assertTrue(first['holding'])
                self.assertFalse(record['complete'])
                self.assertIsNone(record['slot'])
                self.assertEqual(0, nav.index)
                source['status'] = 'complete'
                nav.decide(pose(.1), lambda *args: True)
                recovered = nav.decide(pose(.2), lambda *args: True)
                self.assertEqual('waiting', recovered['parking']['phase'])
                self.assertFalse(record['complete'])
                self.assertEqual(0, record['slot'])
                self.assertLessEqual(nav.support.native_queries, MAX_COLUMNS)

    def test_selected_slot_survives_unknown_support_without_inventing_arrival(self):
        columns, calls = self.columns()
        source = dict(ready=True)
        def probe(*args):
            return columns(*args) if source['ready'] else dict(status='layer_limit', surfaces=[])
        nav = self.native_parking(probe)
        nav.decide(pose(), lambda *args: True)
        nav.decide(pose(.1), lambda *args: True)
        source['ready'] = False
        unknown = nav.decide(pose(1.), lambda *args: True)
        record = nav.parking.records[('native-parking', 0)]
        self.assertEqual('recheck', unknown['parking']['phase'])
        self.assertEqual('parking_support_unknown', unknown['parking']['reason'])
        self.assertEqual(0, record['slot'])
        self.assertFalse(record['complete'])
        self.assertEqual(.1, record['arrived_at'])
        source['ready'] = True
        recovered = nav.decide(pose(1.1), lambda *args: True)
        self.assertEqual('waiting', recovered['parking']['phase'])
        self.assertEqual(.1, recovered['parking']['arrived_at'])

    def test_unknown_support_has_finite_failure_without_permanent_gate_owner(self):
        columns, calls = self.columns()
        source = dict(ready=False)
        def probe(*args):
            return columns(*args) if source['ready'] else dict(status='layer_limit', surfaces=[])
        nav = self.native_parking(probe)
        nav.decide(pose(), lambda *args: True)
        nav.decide(pose(30.1), lambda *args: True)
        record = nav.parking.records[('native-parking', 0)]
        self.assertTrue(record['complete'])
        self.assertEqual('parking_evidence_timeout', record['reason'])
        self.assertTrue(nav.movement_policy(pose(30.1))['allow_withdrawal'])
        source['ready'] = True
        nav.decide(pose(30.2), lambda *args: True)
        self.assertEqual(1, nav.index)

    def test_proved_water_is_rejected_instead_of_unknown_retry(self):
        columns, calls = self.columns(wet=True)
        nav = self.native_parking(columns)
        nav.decide(pose(), lambda *args: True)
        record = nav.parking.records[('native-parking', 0)]
        self.assertTrue(record['complete'])
        self.assertEqual('no_supported_unoccupied_parking', record['reason'])
        self.assertIsNone(record.get('evidence_since'))

    def test_default_td_gate_selects_real_place_instead_of_skipping_wait(self):
        nav, state, index, places = self.td()
        order = nav.decide(state, lambda *args: True)
        self.assertEqual(index, nav.index)
        self.assertEqual('parking_approach', order['combat_mode'])
        self.assertEqual(tuple(places[0][:2]), (order['local_target'][0], order['local_target'][2]))
        self.assertEqual(60., order['parking']['duration'])
        self.assertFalse(nav.movement_policy(state)['allow_withdrawal'])

    def test_wait_clock_starts_at_native_arrival_and_finishes_without_return_to_gate(self):
        nav, state, index, places = self.td()
        nav.decide(state, lambda *args: True)
        goal = nav.parking.receipt['goal']
        arrived = pose(10., goal)
        order = nav.decide(arrived, lambda *args: True)
        self.assertEqual('waiting', order['parking']['phase'])
        self.assertTrue(order['holding'])
        self.assertEqual(10., order['parking']['arrived_at'])
        order = nav.decide(pose(69.9, goal), lambda *args: True)
        self.assertTrue(order['holding'])
        completed = nav.decide(pose(70., goal), lambda *args: True)
        self.assertGreater(nav.index, index)
        self.assertEqual('authored_wait_elapsed', nav.parking.records[(nav.route['id'], index)]['reason'])
        self.assertEqual('authored_wait_elapsed', completed['parking']['previous']['reason'])

    def test_occupancy_uses_local_physical_id_height_and_visibility(self):
        for overhead, visible, expected in ((0., True, 1), (20., True, 0), (0., False, 0)):
            nav, state, index, places = self.td()
            place = places[0]
            height = nav._height(place, state['position'][1])
            row = dict(id=17, team=2, visible=visible, position=(place[0], height + overhead, place[1]),
                       collision_shape=(1., 2.))
            nav.set_context(dict(supported=True, neighbours=[row], allies=[dict(id=42, alive=True)]))
            order = nav.decide(state, lambda *args: True)
            self.assertEqual(expected, order['parking']['slot'])

    def test_selected_slot_is_rechecked_when_another_observed_hull_arrives(self):
        nav, state, index, places = self.td()
        nav.decide(state, lambda *args: True)
        goal = nav.parking.receipt['goal']
        nav.set_context(dict(supported=True, allies=[dict(id=8001, position=goal)]))
        state['now'] = 1.
        order = nav.decide(state, lambda *args: True)
        self.assertEqual(1, order['parking']['slot'])
        self.assertEqual(index, nav.index)

    def test_all_occupied_places_skip_once_without_global_reservations_or_queue(self):
        nav, state, index, places = self.td()
        rows = [dict(id=8000 + i, position=(p[0], nav._height(p, state['position'][1]), p[1]))
                for i, p in enumerate(places)]
        nav.set_context(dict(supported=True, allies=rows))
        order = nav.decide(state, lambda *args: True)
        self.assertGreater(nav.index, index)
        record = nav.parking.records[(nav.route['id'], index)]
        self.assertEqual('no_supported_unoccupied_parking', record['reason'])
        self.assertEqual(record['reason'], order['parking']['previous']['reason'])

    def test_empty_ammo_skips_authored_parking_and_preserves_capture_policy(self):
        nav, state, index, places = self.td()
        nav.set_context(dict(supported=True, empty_ammo=True))
        nav.decide(state, lambda *args: True, hold=True)
        self.assertEqual('capture_base', nav.mission.objective)
        self.assertFalse(nav.movement_policy(state)['allow_strategy'])
        self.assertEqual('idle', nav.parking.snapshot()['phase'])

    def test_blocked_approach_has_finite_failure_and_continues_macro_route(self):
        nav, state, index, places = self.td()
        nav.decide(state, lambda *args: True)
        state['now'] = 31.
        nav.decide(state, lambda *args: False)
        self.assertGreater(nav.index, index)
        self.assertEqual('blocked_approach_timeout', nav.parking.records[(nav.route['id'], index)]['reason'])

    def test_small_shove_preserves_clock_and_permanent_wait_remains_explicit_data(self):
        nav, state, index, places = self.td()
        nav.route = copy.deepcopy(nav.route)
        for place in bot_tactics.waiting_positions(nav.route['waypoints'][index]):
            place[2] = -1.
        nav.decide(state, lambda *args: True)
        goal = nav.parking.receipt['goal']
        nav.decide(pose(1., goal), lambda *args: True)
        shove = (goal[0] + 1., goal[1], goal[2])
        order = nav.decide(pose(700., shove), lambda *args: True)
        self.assertEqual(index, nav.index)
        self.assertTrue(order['holding'])
        self.assertEqual(1., order['parking']['arrived_at'])
        self.assertEqual(-1., order['parking']['duration'])

    def test_large_shove_after_long_wait_gets_new_finite_recheck_window(self):
        nav, state, index, places = self.td()
        nav.route = copy.deepcopy(nav.route)
        for place in bot_tactics.waiting_positions(nav.route['waypoints'][index]):
            place[2] = -1.
        nav.decide(state, lambda *args: True)
        goal = nav.parking.receipt['goal']
        nav.decide(pose(1., goal), lambda *args: True)
        shoved = (goal[0] + 9., nav.navigator.grid._ground(goal[0] + 9., goal[2], goal[1]), goal[2])
        order = nav.decide(pose(700., shoved), lambda *args: True)
        record = nav.parking.records[(nav.route['id'], index)]
        self.assertEqual('recheck', order['parking']['phase'])
        self.assertEqual(1., record['arrived_at'])
        self.assertEqual(700., record['progress_at'])
        self.assertFalse(record['complete'])
        nav.decide(pose(731., shoved), lambda *args: False)
        self.assertTrue(record['complete'])
        self.assertEqual('blocked_approach_timeout', record['reason'])


if __name__ == '__main__':
    unittest.main()
