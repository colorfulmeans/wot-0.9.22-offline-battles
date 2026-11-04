"""Foreground mission/parking regressions with observed poses and native seams.

These tests exercise Python ownership and terminal evidence. They do not claim
that an authored point is physically reachable in the Windows game client.
"""
import ast
import copy
import math
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control import navigation
from gui.mods.offline_lan_0922.player_control.artillery import Artillery
from gui.mods.offline_lan_0922.player_control.missions import Mission, base_areas
from gui.mods.offline_lan_0922.player_control.strategy import CombatPolicy, Strategy
from gui.mods.offline_lan_0922 import native_navigation_query


def state(now=0., position=(0., 0., 0.), speed=0., yaw=0.):
    return dict(id=17, now=now, position=position, speed=speed, yaw=yaw,
                half_length=2., half_width=1.)


HOME = dict(point=(-100., 0.), radius=20., team=1)
ENEMY = dict(point=(0., 100.), radius=15., team=2)
ALIVE_ALLY = dict(id=3, alive=True, health=500, max_health=500,
                  position=(-100., 0., -100.), class_tag='heavyTank')


class NativeNavigationSeam(object):
    def __init__(self):
        self.player_states = {}
        self.ground = lambda x, z, hint: 0.
        self.grid = types.SimpleNamespace(_ground=lambda x, z, hint: self.ground(x, z, hint),
                                          begin_plan=self.begin)
        self.path_calls = []

    def begin(self, start, goal, **unused):
        return types.SimpleNamespace(done=True, result=(start, goal), step=lambda budget: None)

    def set_boundary_body(self, *args):
        pass

    def next_target(self, identity, start, goal, key, now):
        self.path_calls.append((identity, start, goal, key, now))
        return goal

    def close(self):
        pass


def controller(tag='heavyTank', positions=(), active=None, route_end=70.):
    graph = dict(bounds=(-200., -200., 200., 200.),
                 objective_bases=[HOME['point'], ENEMY['point']],
                 objective_base_radii=[HOME['radius'], ENEMY['radius']],
                 routes={'1': [dict(id='main', waypoints=[(0., 0.), (0., route_end)])], '2': []})
    settings = dict(positions=list(positions), routes=[])
    if tag == 'SPG':
        settings['routes'] = [dict(id='sortie', purpose='spg_attack', team=1,
                                  points=[(-100., 0.), (-50., 50.), (0., 100.)])]
    owner = types.SimpleNamespace(_start_message=dict(map='04_himmelsdorf',
        bot_tactics=dict(maps={'04_himmelsdorf': settings})),
        client=types.SimpleNamespace(team=1), _arena_bounds=graph['bounds'],
        _navigation_ground=None, _navigation_obstacle=None)
    if active is not None:
        owner._spawn_planner = types.SimpleNamespace(capture_bases=active)
    descriptor = types.SimpleNamespace(type=types.SimpleNamespace(tags=(tag,)))
    seam = NativeNavigationSeam()
    with mock.patch.object(navigation.prebaked_navigation, 'load_graph', return_value=graph), \
         mock.patch.object(navigation.prebaked_navigation, 'clip_graph_to_arena'), \
         mock.patch.object(navigation.prebaked_navigation, 'with_shore_hazards', side_effect=lambda g: g), \
         mock.patch.object(navigation, 'PlayerPathfinder', return_value=seam), \
         mock.patch.object(native_navigation_query.Oracle, 'create', return_value=None):
        result = navigation.PlayerNavigation(owner, descriptor)
    return result


class MissionMigrationTests(unittest.TestCase):
    def test_active_capture_circles_override_baked_coordinates_and_radius(self):
        nav = controller(active={1: [dict(x=-80., z=-60., radius=9.)],
                                 2: [dict(x=30., z=120., radius=7.)]})
        self.assertEqual((-80., -60.), nav.home)
        receipt = nav.start_mission('return_base', dict(command_id='return-1', radius=100.), state())
        self.assertEqual((-80., -60.), receipt['goal'])
        self.assertEqual(9., receipt['radius'])
        nav.start_mission('capture_base', {}, state())
        self.assertEqual((30., 120.), nav.mission_status()['goal'])
        self.assertEqual(7., nav.mission_status()['radius'])

    def test_legacy_active_points_use_server_wire_default_instead_of_baked_radius(self):
        graph = dict(objective_bases=[(-100., 0.), (0., 100.)], objective_base_radii=[20., 15.])
        home, enemy = base_areas(graph, 1, {1: [(-80., 0.)], 2: [(0., 100.)]})
        self.assertEqual((-80., 0.), home['point'])
        self.assertEqual(50., home['radius'])
        self.assertEqual(50., enemy['radius'])
        nav = controller(active={1: [(-80., 0.)], 2: [(0., 100.)]})
        self.assertEqual(50., nav.start_mission('return_base', {}, state())['radius'])

    def test_return_brakes_on_entry_and_completes_only_after_supported_stop(self):
        nav = controller()
        nav.start_mission('return_base', dict(command_id='return'), state())
        nav.set_context({})
        moving = state(1., (-85., 0., 0.), speed=4.)
        order = nav.decide(moving, lambda *args: True, hold=True)
        self.assertTrue(order['brake'])
        self.assertEqual('running', nav.mission_status()['status'])
        stopped = state(2., (-85., 0., 0.))
        nav.decide(stopped, lambda *args: True)
        self.assertFalse(nav.mission_status()['arrival']['settled'])
        nav.decide(state(2.6, stopped['position']), lambda *args: True)
        self.assertEqual('completed', nav.mission_status()['status'])
        self.assertEqual('arrived_and_held', nav.mission_status()['result']['reason'])
        self.assertFalse(nav.retask([dict(id='front', waypoints=[(100., 100.)])]))
        self.assertTrue(nav.decide(state(30., stopped['position']), lambda *args: True)['brake'])

    def test_bridge_layer_airborne_and_overturn_cannot_count_as_arrival(self):
        for pose, context in (((0., 8., 100.), {}), ((0., 0., 100.), {'supported': False}),
                              ((0., 0., 100.), {'overturned': True})):
            nav = controller()
            nav.start_mission('capture_base', {}, state())
            nav.set_context(context)
            nav.decide(state(1., pose), lambda *args: True)
            nav.decide(state(2., pose), lambda *args: True)
            receipt = nav.mission_status()
            self.assertFalse(receipt['arrival']['supported'])
            self.assertNotEqual('capturing', receipt['phase'])

    def test_hilly_circle_support_is_measured_at_occupied_position(self):
        nav = controller()
        nav.navigator.ground = lambda x, z, hint: 4. if z < 100. else 0.
        nav.start_mission('capture_base', {}, state())
        nav.set_context({})
        nav.decide(state(1., (0., 4., 90.)), lambda *args: True)
        nav.decide(state(2., (0., 4., 90.)), lambda *args: True)
        self.assertEqual('capturing', nav.mission_status()['phase'])

    def test_unsupported_flag_centre_can_join_a_supported_point_inside_actual_circle(self):
        nav = controller()
        nav.navigator.ground = lambda x, z, hint: None if (x, z) == ENEMY['point'] else 0.
        nav.start_mission('capture_base', {}, state())
        nav.set_context({})
        order = nav.decide(state(1.), lambda *args: True)
        self.assertNotEqual((0., 0., 100.), order['local_target'])
        self.assertLess(math.hypot(order['local_target'][0], order['local_target'][2] - 100.), 15.)
        self.assertGreater(order['throttle'], 0.)

    def test_capture_uses_real_circle_holds_without_clip_retreat_and_reenters(self):
        nav = controller()
        nav.start_mission('capture_base', dict(command_id='cap'), state())
        nav.set_context(dict(fire_clear=True, target=dict(id=8, position=(0., 0., 140.))))
        policy = nav.movement_policy(state(1., (0., 0., 84.)))
        self.assertTrue(policy['force_move'])
        self.assertFalse(policy['allow_withdrawal'])
        self.assertFalse(policy['allow_strategy'])
        nav.decide(state(2., (0., 0., 90.)), lambda *args: True, hold=True)
        nav.decide(state(3., (0., 0., 90.)), lambda *args: True, hold=True)
        self.assertEqual('capturing', nav.mission_status()['phase'])
        self.assertTrue(nav.movement_policy(state(3., (0., 0., 90.)))['holding'])
        shoved = state(4., (0., 0., 80.))
        self.assertTrue(nav.movement_policy(shoved)['force_move'])
        order = nav.decide(shoved, lambda *args: True, hold=True)
        self.assertGreater(order['throttle'], 0.)
        self.assertEqual('capture_travel', nav.mission_status()['phase'])

    def test_capture_completion_needs_public_capture_result_not_just_entry(self):
        nav = controller()
        nav.start_mission('capture_base', {}, state())
        nav.set_context({})
        nav.decide(state(1., (0., 0., 100.)), lambda *args: True)
        nav.decide(state(3., (0., 0., 100.)), lambda *args: True)
        self.assertEqual('running', nav.mission_status()['status'])
        nav.set_context(dict(enemy_base=dict(points=100)))
        nav.decide(state(4., (0., 0., 100.)), lambda *args: True)
        self.assertEqual('base_captured', nav.mission_status()['result']['reason'])

    def test_small_shove_after_long_capture_hold_starts_reentry_not_stall_failure(self):
        nav = controller()
        nav.start_mission('capture_base', {}, state())
        nav.set_context({})
        nav.decide(state(1., (0., 0., 85.1)), lambda *args: True)
        nav.decide(state(2., (0., 0., 85.1)), lambda *args: True)
        nav.decide(state(100., (0., 0., 85.1)), lambda *args: True)
        order = nav.decide(state(101., (0., 0., 84.9)), lambda *args: True, hold=True)
        self.assertEqual('running', nav.mission_status()['status'])
        self.assertEqual('capture_travel', nav.mission_status()['phase'])
        self.assertGreater(order['throttle'], 0.)

    def test_point_mission_preserves_requested_vertical_layer(self):
        nav = controller()
        nav.start_mission('hold_position', dict(position=(0., 8., 0.)), state())
        nav.set_context({})
        nav.movement_policy(state(1.))
        nav.movement_policy(state(2.))
        self.assertFalse(nav.mission_status()['arrival']['height_matches'])
        self.assertEqual('running', nav.mission_status()['status'])
        self.assertEqual(8., nav.mission_status()['goal_height'])

    def test_entry_path_cannot_finish_on_another_layer_under_the_goal(self):
        nav = controller()
        nav.navigator.ground = lambda x, z, hint: 8. if z == 70. else 0.
        nav._reset_travel([dict(id='bridge', waypoints=[(0., 70.)])])
        def under_bridge(start, goal, **unused):
            return types.SimpleNamespace(done=True, result=(start, (goal[0], 0., goal[2])),
                                         step=lambda budget: None)
        nav.navigator.grid.begin_plan = under_bridge
        self.assertFalse(nav.join((0., 0., 0.), 1.))
        self.assertEqual('rejected_layer_or_path', nav.receipt['status'])

    def test_battle_end_without_capture_does_not_claim_capture_success(self):
        nav = controller()
        nav.start_mission('capture_base', {}, state())
        nav.set_context(dict(battle_finished=True))
        nav.movement_policy(state(1.))
        self.assertEqual('cancelled', nav.mission_status()['status'])

    def test_canonical_capture_result_settles_before_teardown_but_other_results_do_not(self):
        results = [(dict(winner=1, reason='base captured', base_team=2), 'completed'),
                   (dict(winner=1, reason='team_eliminated', base_team=0), 'cancelled'),
                   (dict(winner=2, reason='base captured', base_team=1), 'cancelled'),
                   (dict(winner=0, reason='timeout', base_team=0), 'cancelled')]
        for result, status in results:
            nav = controller()
            nav.start_mission('capture_base', dict(command_id='cap'), state())
            receipt = nav.finish_battle(result, 20.)
            self.assertEqual(status, receipt['status'])
            self.assertEqual('cap', receipt['id'])
            self.assertEqual(result, receipt['result']['battle'])
            nav.close()
            self.assertEqual(status, nav.mission_status()['status'])

    def test_route_terminal_outside_circle_hands_off_instead_of_parking_there(self):
        nav = controller(route_end=70.)
        nav.set_context({})
        nav.decide(state(1., (0., 0., 70.)), lambda *args: True, hold=True)
        self.assertEqual('capture_base', nav.mission_status()['action'])
        self.assertFalse(nav.mission_status()['arrival']['inside'])
        self.assertEqual((0., 100.), nav.mission_status()['goal'])

    def test_empty_ammo_breaks_hold_and_keeps_explicit_attack_identity(self):
        nav = controller()
        nav.start_mission('attack', dict(command_id='attack-9'), state())
        nav.cover_move = {'stale': True}
        nav.firing_move = ('stale',)
        nav.driver.reverse_until = 100.
        nav.set_context(dict(empty_ammo=True, fire_clear=True,
                             target=dict(id=4, position=(0., 0., 20.))))
        order = nav.decide(state(1.), lambda *args: True, hold=True)
        self.assertGreater(order['throttle'], 0.)
        self.assertIsNone(nav.cover_move)
        self.assertIsNone(nav.firing_move)
        self.assertEqual(0., nav.driver.reverse_until)
        self.assertEqual('attack-9', nav.mission_status()['id'])
        self.assertEqual('attack', nav.mission_status()['action'])
        self.assertEqual('capture_base', nav.mission_status()['objective'])

    def test_empty_ammo_preserves_explicit_return_defend_and_hold(self):
        for action in ('return_base', 'defend_base', 'hold_position'):
            nav = controller()
            nav.start_mission(action, {}, state())
            nav.set_context(dict(empty_ammo=True))
            nav.movement_policy(state(1.))
            self.assertEqual(action, nav.mission_status()['objective'])

    def test_completed_hold_returns_to_its_anchor_after_shove(self):
        nav = controller()
        nav.start_mission('hold_position', {}, state())
        nav.set_context({})
        nav.decide(state(1.), lambda *args: True)
        nav.decide(state(2.), lambda *args: True)
        self.assertEqual('completed', nav.mission_status()['status'])
        order = nav.decide(state(3., (0., 0., -8.)), lambda *args: True, hold=True)
        self.assertGreater(order['throttle'], 0.)
        self.assertEqual((0., 0.), nav.mission_status()['goal'])

    def test_defend_waits_for_public_alarm_and_visible_attackers_to_clear(self):
        nav = controller()
        nav.start_mission('defend_base', {}, state())
        nav.set_context(dict(base=dict(points=10, invaders=1)))
        nav.decide(state(1., (-100., 0., 0.)), lambda *args: True)
        nav.decide(state(2., (-100., 0., 0.)), lambda *args: True)
        self.assertEqual('defending', nav.mission_status()['phase'])
        nav.set_context(dict(base={}, contacts=[dict(position=(-110., 0., 0.))]))
        nav.decide(state(10., (-100., 0., 0.)), lambda *args: True)
        self.assertEqual('running', nav.mission_status()['status'])
        nav.set_context(dict(base={}, contacts=[]))
        nav.decide(state(11., (-100., 0., 0.)), lambda *args: True)
        nav.decide(state(15., (-100., 0., 0.)), lambda *args: True)
        self.assertEqual('running', nav.mission_status()['status'])
        nav.decide(state(16., (-100., 0., 0.)), lambda *args: True)
        self.assertEqual('base_clear_and_held', nav.mission_status()['result']['reason'])

    def test_explicit_command_blocks_automatic_front_and_defence(self):
        nav = controller()
        nav.start_mission('attack', {}, state())
        self.assertFalse(nav.retask([dict(id='player_base_defence', waypoints=[(-100., 0.)])], 'defend'))
        strategy = Strategy()
        suggestion = strategy.decide(0., nav.routes, None, [], [],
            dict(points=70, invaders=1), nav.home, mission=nav.mission_status())
        self.assertIsNone(suggestion)
        self.assertEqual('mission_owned', strategy.receipt['mode'])

    def test_rejected_replacement_keeps_accepted_task_and_motion_owner(self):
        nav = controller()
        nav.start_mission('attack', dict(command_id='keep'), state())
        original, driver = nav.mission, nav.driver
        rejected = nav.start_mission('hold_position',
            dict(command_id='bad', position=(5000., 0., 5000.)), state(1.))
        self.assertEqual('failed', rejected['status'])
        self.assertEqual('objective_outside_arena', rejected['reason'])
        self.assertIs(original, nav.mission)
        self.assertIs(driver, nav.driver)
        self.assertEqual('keep', nav.mission_status()['id'])

    def test_validation_does_not_allocate_or_replace_a_mission(self):
        nav = controller()
        nav.start_mission('attack', dict(command_id='keep'), state())
        original, driver, sequence = nav.mission, nav.driver, nav.mission_sequence
        receipt = nav.validate_mission('return_base', dict(command_id='next'), state(1.))
        self.assertEqual('pending', receipt['status'])
        self.assertEqual('next', receipt['id'])
        self.assertIs(original, nav.mission)
        self.assertIs(driver, nav.driver)
        self.assertEqual(sequence, nav.mission_sequence)

    def test_root_policy_then_decide_observes_each_sample_once(self):
        nav = controller()
        nav.start_mission('return_base', {}, state())
        nav.set_context({})
        with mock.patch.object(nav.mission, 'observe', wraps=nav.mission.observe) as observe, \
             mock.patch.object(nav.combat, 'update', wraps=nav.combat.update) as combat:
            pose = state(1.)
            nav.movement_policy(pose)
            nav.decide(pose, lambda *args: True)
            self.assertEqual(1, observe.call_count)
            self.assertEqual(1, combat.call_count)

    def test_mission_timeout_and_stall_produce_terminal_results(self):
        for args, when, reason in ((dict(timeout=5.), 5., 'mission_timeout'),
                                   ({}, 30., 'no_navigation_progress')):
            nav = controller()
            nav.start_mission('return_base', args, state())
            nav.set_context({})
            nav.movement_policy(state(0.))
            nav.movement_policy(state(when))
            self.assertEqual('failed', nav.mission_status()['status'])
            self.assertEqual(reason, nav.mission_status()['result']['reason'])
            self.assertTrue(nav.decide(state(when), lambda *args: True)['brake'])


class WithdrawalMigrationTests(unittest.TestCase):
    def setUp(self):
        self.nav = controller()
        self.entity = types.SimpleNamespace(typeDescriptor=types.SimpleNamespace(maxHealth=1000), health=1000)
        self.target = types.SimpleNamespace(id=5, position=(0., 0., 30.))
        self.gun = types.SimpleNamespace(clip_size=3, clip=0, reload_time=40.)
        # This suite owns the withdrawal state machine, not native cover
        # geometry. The complete candidate sampler is tested separately using
        # real descriptors in test_player_cover_independence.
        self.nav._cover_candidate = lambda pose, target, entity, clear, ray: dict(
            target=target.id, goal=(0., 0., -5.), peek=(0., 0., 0.))
        self.nav.cover_search.current_exposure = lambda *args: 0.
        self.nav.cover_search.peek_clear = lambda pose, context, target, entity, point, ground, ray: ray(
            (0., 1.7, 30.), (point[0], point[1]+1.5, point[2]))

    def apply(self, pose, target=None, ray=lambda *args: False):
        return self.nav.withdrawal(pose, target, self.entity, self.gun,
                                   lambda *args: True, ray)

    def test_long_reload_and_final_two_seconds_keep_arrived_cover(self):
        self.apply(state(1.), self.target)
        self.apply(state(2., (0., 0., -5.)))
        for now, remaining in ((9.1, 31.9), (25., 16.), (39.5, 1.5), (40.5, .5)):
            self.gun.reload_time = remaining
            order = self.apply(state(now, (0., 0., -5.)))
            self.assertEqual('cover_hold', order['combat_mode'])
            self.assertTrue(order['brake'])
        self.gun.reload_time = 0.
        self.gun.clip = 3
        self.assertIsNone(self.apply(state(41., (0., 0., -5.))))

    def test_stalled_cover_movement_has_its_own_deadline(self):
        self.apply(state(1.), self.target)
        self.assertIsNone(self.apply(state(9.1)))
        self.assertIsNone(self.nav.cover_move)
        self.assertEqual('cover_movement_timeout', self.nav.receipt['status'])

    def test_real_progress_renews_approach_but_shove_starts_fresh_return(self):
        self.apply(state(1.), self.target)
        self.apply(state(7., (0., 0., -2.)))
        self.assertIsNotNone(self.apply(state(10., (0., 0., -2.))))
        self.apply(state(11., (0., 0., -5.)))
        order = self.apply(state(30., (0., 0., -1.)))
        self.assertEqual('cover_return', order['combat_mode'])
        self.assertLess(order['throttle'], 0.)

    def test_critical_cover_peek_returns_after_actual_shot(self):
        self.entity.health = 200
        self.gun.clip_size, self.gun.clip, self.gun.reload_time = 1, 1, 0.
        self.nav.set_context(dict(gun_ready=True, fire_seq=0))
        ray = lambda origin, end: end[2] >= 0.
        self.apply(state(1.), self.target, ray)
        self.apply(state(2., (0., 0., -5.)), self.target, ray)
        peek = self.apply(state(3.1, (0., 0., -5.)), self.target, ray)
        self.assertEqual('cover_peek', peek['combat_mode'])
        self.assertGreater(peek['throttle'], 0.)
        self.apply(state(4.), self.target, ray)
        self.nav.set_context(dict(gun_ready=False, fire_seq=1))
        returning = self.apply(state(4.2), self.target, ray)
        self.assertEqual('cover_return', returning['combat_mode'])
        self.assertLess(returning['throttle'], 0.)


class CombatRecoveryTests(unittest.TestCase):
    def test_class_ranges_are_distinct_and_match_live_profile_catalogue(self):
        path = ROOT / 'src/res/scripts/client/gui/mods/offline_lan_0922/ai/planner.py'
        tree = ast.parse(path.read_text(encoding='utf8'))
        declaration = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'desired_ranges' for target in node.targets))
        expected = ast.literal_eval(declaration.value)
        for tag, ranges in expected.items():
            policy = CombatPolicy(tag)
            self.assertEqual(ranges, (policy.desired_range, policy.fire_range))
        nav = controller('AT-SPG')
        self.assertAlmostEqual(255. * 1.15, nav.movement_policy(state())['engage_range'])

    def test_ready_hold_without_shot_releases_for_bounded_proved_motion(self):
        nav = controller()
        nav.set_context(dict(target=dict(id=8, position=(0., 0., 40.)),
                             fire_clear=True, aligned=False, gun_ready=True, fire_seq=0))
        self.assertFalse(nav.movement_policy(state(0.))['force_move'])
        self.assertTrue(nav.movement_policy(state(8.))['force_move'])
        order = nav.decide(state(8.), lambda *args: True, hold=True)
        self.assertEqual('combat_recovery', order['combat_mode'])
        self.assertGreater(order['throttle'], 0.)
        self.assertFalse(nav.movement_policy(state(12.))['force_move'])

    def test_committed_shot_ends_an_active_unproductive_shot_recovery(self):
        policy = CombatPolicy('heavyTank')
        context = dict(target=dict(id=8, position=(0., 0., 40.)),
                       fire_clear=True, gun_ready=True, fire_seq=0)
        policy.update(state(0.), context)
        policy.update(state(8.), context)
        self.assertIsNotNone(policy.recovery)
        context['fire_seq'] = 1
        policy.update(state(9.), context)
        self.assertIsNone(policy.recovery)

    def test_real_aim_progress_reload_and_accepted_shots_reset_idle_budget(self):
        for field, value in (('aim_progress', True), ('gun_ready', False), ('fire_seq', 1)):
            policy = CombatPolicy('heavyTank')
            context = dict(target=dict(id=8, position=(0., 0., 40.)),
                           fire_clear=True, aligned=False, gun_ready=True, fire_seq=0)
            policy.update(state(0.), context)
            context[field] = value
            self.assertTrue(policy.update(state(9.), context))
            self.assertIsNone(policy.recovery)

    def test_unproved_recovery_does_not_drive_and_still_expires(self):
        nav = controller()
        nav.set_context(dict(target=dict(id=8, position=(0., 0., 40.)),
                             fire_clear=True, gun_ready=True, fire_seq=0))
        nav.movement_policy(state(0.))
        blocked = nav.decide(state(8.), lambda *args: False, hold=True)
        self.assertTrue(blocked['brake'])
        self.assertEqual(0., blocked['throttle'])
        self.assertIsNotNone(nav.combat.recovery)
        nav.movement_policy(state(12.))
        self.assertIsNone(nav.combat.recovery)


class ArtilleryMigrationTests(unittest.TestCase):
    POSITIONS = [dict(id='battery_a', team=1, point=(20., 0.), radius=2., priority=5),
                 dict(id='battery_b', team=1, point=(-40., 0.), radius=2., priority=4)]

    def parked(self):
        nav = controller('SPG', self.POSITIONS)
        context = dict(allies=[ALIVE_ALLY], fire_seq=0, gun_ready=True,
                       target=dict(id=8, position=(0., 0., 100.)), fire_clear=False, aligned=False)
        nav.set_context(context)
        nav.decide(state(0.), lambda *args: True, hold=True)
        nav.decide(state(1., (20., 0., 0.)), lambda *args: True)
        nav.decide(state(2., (20., 0., 0.)), lambda *args: True)
        self.assertEqual('holding', nav.artillery.mode)
        return nav, context

    def test_spg_deploys_to_own_position_before_attack_route_and_then_holds(self):
        nav, context = self.parked()
        self.assertEqual('battery_a:0', nav.artillery.current['id'])
        self.assertFalse(nav.sortie_started)
        self.assertTrue(nav.decide(state(10., (20., 0., 0.)), lambda *args: True)['brake'])
        self.assertFalse(nav.movement_policy(state(10., (20., 0., 0.)))['allow_withdrawal'])

    def test_occupied_parking_is_excluded_without_reserving_bot_slots(self):
        nav = controller('SPG', self.POSITIONS)
        nav.set_context(dict(allies=[dict(ALIVE_ALLY, position=(20., 0., 0.))]))
        nav.movement_policy(state())
        self.assertEqual('battery_b:0', nav.artillery.current['id'])
        self.assertEqual((20., 0.), self.POSITIONS[0]['point'])

    def test_parking_rejects_a_steep_or_partly_unsupported_footprint(self):
        for first_height in (lambda x, z: (x - 20.) * .4,
                             lambda x, z: None if x > 22. else 0.):
            nav = controller('SPG', self.POSITIONS)
            nav.navigator.ground = lambda x, z, hint: first_height(x, z) if x > 10. else 0.
            nav.set_context(dict(allies=[ALIVE_ALLY]))
            nav.movement_policy(state())
            self.assertEqual('battery_b:0', nav.artillery.current['id'])

    def test_continuous_ready_firing_failure_relocates_and_success_resets(self):
        nav, context = self.parked()
        nav.movement_policy(state(20., (20., 0., 0.)))
        self.assertEqual('battery_a:0', nav.artillery.current['id'])
        context['fire_seq'] = 1
        nav.set_context(context)
        nav.movement_policy(state(29., (20., 0., 0.)))
        nav.movement_policy(state(40., (20., 0., 0.)))
        self.assertEqual('battery_a:0', nav.artillery.current['id'])
        nav.movement_policy(state(60., (20., 0., 0.)))
        self.assertEqual('battery_b:0', nav.artillery.current['id'])
        self.assertEqual('relocating', nav.artillery.mode)
        self.assertEqual('persistent_firing_failure', nav.artillery.receipt['relocation_reason'])

    def test_reload_and_absence_of_visible_targets_do_not_relocate(self):
        for changes in (dict(gun_ready=False), dict(target=None, contacts=[])):
            nav, context = self.parked()
            context.update(changes)
            nav.set_context(context)
            nav.movement_policy(state(90., (20., 0., 0.)))
            self.assertEqual('holding', nav.artillery.mode)
            self.assertEqual('battery_a:0', nav.artillery.current['id'])

    def test_ready_aligned_lane_without_any_committed_shot_is_also_bounded(self):
        nav, context = self.parked()
        context.update(fire_clear=True, aligned=True)
        nav.set_context(context)
        nav.movement_policy(state(33., (20., 0., 0.)))
        self.assertEqual('battery_b:0', nav.artillery.current['id'])

    def test_movement_timeout_tries_another_parking_candidate(self):
        nav = controller('SPG', self.POSITIONS)
        nav.set_context(dict(allies=[ALIVE_ALLY]))
        nav.movement_policy(state(0.))
        nav.movement_policy(state(30.))
        self.assertEqual('battery_b:0', nav.artillery.current['id'])
        self.assertEqual('parking_movement_timeout', nav.artillery.receipt['relocation_reason'])

    def test_base_defence_resumes_own_parking_without_lost_state(self):
        nav, context = self.parked()
        previous = copy.deepcopy(nav.artillery.current)
        nav.retask([dict(id='player_base_defence', waypoints=[(-100., 0.)])], 'defend')
        self.assertEqual('defending', nav.artillery.mode)
        nav.set_context(dict(allies=[ALIVE_ALLY], now=50.))
        nav.retask(nav.routes, 'rejoin_after_defence')
        self.assertEqual(previous, nav.artillery.current)
        nav.decide(state(50., (-100., 0., 0.)), lambda *args: True)
        self.assertEqual('deploying', nav.artillery.mode)
        self.assertFalse(nav.automatic_defence)

    def test_public_survivors_drive_endgame_and_sortie_resumes_after_defence(self):
        nav = controller('SPG', self.POSITIONS)
        nav.set_context(dict(allies=[dict(id=17, class_tag='SPG', alive=True),
                                     dict(id=3, class_tag='mediumTank', alive=False)]))
        nav.movement_policy(state(0.))
        nav.movement_policy(state(5.))
        self.assertEqual('sortie_return', nav.artillery.mode)
        nav.decide(state(6., (-100., 0., 0.)), lambda *args: True)
        self.assertEqual('sortie', nav.artillery.mode)
        self.assertTrue(nav.sortie_started)
        self.assertEqual('user_sortie', nav.route['id'])
        previous = nav.route, nav.index
        nav.retask([dict(id='player_base_defence', waypoints=[(-100., 0.)])], 'defend')
        nav.retask(nav.routes, 'rejoin_after_defence')
        self.assertEqual('sortie', nav.artillery.mode)
        self.assertEqual(previous, (nav.route, nav.index))

    def test_endgame_return_can_use_a_supported_point_beside_blocked_home_centre(self):
        nav = controller('SPG', self.POSITIONS)
        nav.navigator.ground = lambda x, z, hint: None if (x, z) == HOME['point'] else 0.
        nav.set_context(dict(allies=[]))
        nav.movement_policy(state(0.))
        order = nav.decide(state(5., yaw=-math.pi / 2.), lambda *args: True)
        self.assertEqual('sortie_return', nav.artillery.mode)
        target = order['local_target']
        self.assertNotEqual((-100., 0., 0.), target)
        self.assertLess(math.hypot(target[0] + 100., target[2]), 20.)
        self.assertGreater(order['throttle'], 0.)

    def test_stalled_endgame_return_releases_to_connected_attack_entry(self):
        nav = controller('SPG', self.POSITIONS)
        nav.set_context(dict(allies=[]))
        nav.movement_policy(state(0.))
        nav.movement_policy(state(5.))
        nav.decide(state(35.), lambda *args: False)
        self.assertEqual('sortie', nav.artillery.mode)
        self.assertTrue(nav.artillery.sortie_home_failed)
        self.assertFalse(nav.selection[0]['player_start_at_first'])

    def test_unknown_surviving_class_does_not_trigger_endgame(self):
        nav = controller('SPG', self.POSITIONS)
        nav.set_context(dict(allies=[dict(id=3, alive=True)]))
        nav.movement_policy(state(0.))
        nav.movement_policy(state(10.))
        self.assertNotIn(nav.artillery.mode, ('sortie_return', 'sortie'))

    def test_incomplete_roster_and_native_identity_do_not_create_false_endgame_or_occupancy(self):
        nav = controller('SPG', self.POSITIONS)
        own = dict(id=5017, class_tag='SPG', alive=True, position=(20., 0., 0.))
        nav.set_context(dict(allies=[own], allies_complete=False))
        pose = dict(state(0., (20., 0., 0.)), engine_id=5017)
        nav.movement_policy(pose)
        self.assertEqual('battery_a:0', nav.artillery.current['id'])
        pose['now'] = 10.
        nav.movement_policy(pose)
        self.assertNotIn(nav.artillery.mode, ('sortie_return', 'sortie'))
        nav.set_context(dict(allies=[own], allies_complete=True))
        nav.movement_policy(pose)
        pose['now'] = 15.
        nav.movement_policy(pose)
        self.assertEqual('sortie_return', nav.artillery.mode)

    def test_empty_spg_skips_parking_and_uses_capture(self):
        nav = controller('SPG', self.POSITIONS)
        nav.set_context(dict(empty_ammo=True, allies=[ALIVE_ALLY], fire_clear=True))
        order = nav.decide(state(1.), lambda *args: True, hold=True)
        self.assertEqual('capture_base', nav.mission_status()['objective'])
        self.assertGreater(order['throttle'], 0.)
        self.assertIsNone(nav.artillery.current)


if __name__ == '__main__':
    unittest.main()
