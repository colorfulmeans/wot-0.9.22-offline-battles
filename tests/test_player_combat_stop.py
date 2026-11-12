"""Shared combat stops preserve task ownership and current native evidence.

The small fixture supplies an isolated, already established combat task and
current-row evidence stubs. It enters that task through accept/resolve, never
by giving a macro engage label movement permission. Cold admission is explicit
with admitted=False; it is not a native-proof integration claim.
Cold-start, lane checks, routes and final native controls belong to separate
full-runtime tests. Every living observed enemy participates in armour review;
retired priority metadata cannot filter or reorder that domain. Recovery
consumers here are the actual common engine laws, not a second player copy.
"""
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import siege_mechanics
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import AttackPolicy
from gui.mods.offline_lan_0922.vehicle_control.combat_stop import (
    CombatStop, MECHANICAL_STALL_SECONDS)
from gui.mods.offline_lan_0922.vehicle_control.target_selection import ordinary_initial_key
from gui.mods.offline_lan_0922 import bot_runtime
from gui.mods.offline_lan_0922.ai.driver import WAYPOINT_ARRIVAL_RADIUS
from gui.mods.offline_lan_0922.vehicle_control.full_runtime import (
    FullPlayerRuntime, _PlayerBehaviorEngine)


class Scene:
    def __init__(self, siege=None, admitted=True):
        has_siege = siege is not None
        siege = siege if has_siege else siege_mechanics.DISABLED
        self.state = dict(id=1, team=1, position=(0., 0., 0.), x=0., y=0., z=0.,
            yaw=0., speed=0., aim_yaw=0., siege_state=siege, fire_seq=0,
            shell_index=0, half_width=1.7, half_length=3.5,
            profile=dict(class_tag='AT-SPG'))
        self.target = dict(kind='bot', network_id=2, id=2, team=2, alive=True,
            health=1000, position=(0., 0., 80.), x=0., y=0., z=80., yaw=0.)
        engine = bot_runtime.BotRuntime.__new__(bot_runtime.BotRuntime)
        engine.states = {1: self.state}
        engine._decision_cache = {}
        engine._gun_yaw_limits = {1: (-.2, .2, True)}
        engine._server_orders = {}
        engine._shot_los_cache = {}
        engine._physics_params_for = lambda actor: dict(rotSpd=1.)
        engine._gun_angle_target_fraction = lambda *args: None
        engine.navigator = SimpleNamespace(bot_states={}, paths={},
            grid=SimpleNamespace(_proof_deferred=False))
        self.policy = SimpleNamespace(decision={}, rows={}, selected=None,
            _executable=AttackPolicy._executable,
            _attack_result=AttackPolicy._attack_result,
            _needs_firing_position=AttackPolicy._needs_firing_position,
            _planned_evidence=AttackPolicy._planned_evidence,
            _plannable=AttackPolicy._plannable,
            frame=dict(loaded=0, reloading=False), receipts=[])
        self.policy.current_target_key = lambda: AttackPolicy.current_target_key(self.policy)
        self.policy.navigation_result = self.policy.receipts.append
        self.policy.stationary_review_wait = lambda: AttackPolicy.stationary_review_wait(self.policy)
        self.policy._stationary_review_order = lambda order: AttackPolicy._stationary_review_order(
            self.policy, order)
        self.policy.intent_solution = lambda candidate: AttackPolicy.intent_solution(
            self.policy, candidate)
        self.policy.current_row = lambda candidate, require_line=True: (
            candidate if candidate.get('fresh', True) else None)
        self.policy._rows_for = lambda mode, shell, fresh_line: [
            row for row in self.policy.rows.values() if row.get('mode') == mode and
            row.get('shell_index') == shell and self.policy.current_row(row) is not None]
        self.runtime = SimpleNamespace(engine=engine, state=self.state,
            gun=SimpleNamespace(shot_index=0, clip_size=3, clip=3), actor_id=1,
            owner=SimpleNamespace(_local_siege_aim_pitch=0., _local_siege_pending=None,
                                  _local_siege_braking=None),
            entity=SimpleNamespace(siegeState=siege,
                typeDescriptor=SimpleNamespace(hasSiegeMode=has_siege)),
            features={'drive', 'fire'}, _targets=(self.target,), _mission=None,
            _siege_pending=None, _siege_aim_candidate=None, _last_navigation={},
            generation=7, now=0., attack_policy=self.policy, _native_hull_laying=None,
            _mission_brakes=lambda: False, _planner_bot=lambda: dict(id=1), _live=lambda: True)
        self.runtime.visible_targets = lambda: self.runtime._targets
        self.policy.runtime = self.runtime
        self.runtime.planner = SimpleNamespace(_target_decisions={},
            _route=mock.Mock(side_effect=AssertionError('combat stop cannot choose a route')))
        self.owner = CombatStop(self.runtime)
        self.runtime.combat_stop = self.owner
        engine._actor_controls = {1: self.runtime}
        self.runtime.siege_capable = lambda: has_siege
        self.runtime._stationary_review_wait = self.policy.stationary_review_wait
        self.runtime.siege_aim_candidate = lambda target=None: (
            FullPlayerRuntime.siege_aim_candidate(self.runtime, target))
        self.raw_order = dict(id=1, target_id=2, target_kind='bot',
            combat_mode='engage', move_position=(0., 0., 0.),
            face_position=self.target['position'], aim_position=self.target['position'],
            throttle_override=0., fire_range=500., fire_allowed=True, shell_index=0,
            tactical_evidence=dict(selection=dict(selected=('bot', 2), outcome='assigned',
                candidates=[dict(target=('bot', 2), reason='eligible', score=0.)])))
        self.candidate = dict(target=self.target, shell_index=0, mechanical='reachable',
            line='world_blocked', armor='passed', mode='penetration', key=('point', 0),
            solution=dict(point=(0., 1., 80.), yaw=0., mechanical_reason='world_blocked'))
        self.decide('firing_position')
        self.owner.accept(self.raw_order)
        if admitted:
            # Establish this fixture's existing task through a real current
            # executable-point admission. A blocked point now only queues
            # inspection and must not grant movement by itself.
            previous = dict(self.candidate)
            self.candidate.update(line='clear', mechanical='reachable')
            self.decide('aim')
            self.owner.finish(self.owner.resolve(self.raw_order, 0.))
            self.candidate.clear()
            self.candidate.update(previous)
            self.decide('firing_position')

    def decide(self, action, candidate=True, **fields):
        self.policy.decision = dict(action=action, reason='observed_point',
                                    candidate=self.candidate if candidate else None)
        self.policy.decision.update(fields)

    def apply(self, now):
        self.runtime.now = now
        self.owner.accept(self.raw_order)
        result = self.owner.resolve(dict(self.raw_order), now)
        if self.owner.active:
            result = AttackPolicy.apply_order(self.policy, result, now)
        result = self.owner.apply_order(result, now)
        result = self.owner.finish(result)
        self.runtime.engine._server_orders[1] = dict(result)
        return result

    def position(self, point):
        self.state['position'] = tuple(point)
        self.state.update(zip(('x', 'y', 'z'), point))

    def native_mode(self, mode):
        self.state['siege_state'] = self.runtime.entity.siegeState = mode

    def stationary(self, **changes):
        planned = dict(status='proved', proof=dict(proved=True), line='clear',
            mechanical='reachable', armor='passed',
            solution=dict(point=(25., 1., 80.), yaw=.7, hull_yaw=.5, needs_hull=True))
        self.candidate.update(mechanical='hull_laying', armor='unknown',
                               stationary_plan=planned, **changes)
        return planned


class OriginalOwnershipBoundaryTests(unittest.TestCase):
    def test_departed_target_transfers_existing_engagement_without_route_confirmation(self):
        scene = Scene()
        previous = scene.owner._episode
        target = dict(scene.target, id=3, network_id=3, position=(0., 0., 70.), z=70.)
        scene.runtime._targets = (target,)
        scene.raw_order.update(combat_mode='route', move_position=(20., 0., 40.))
        scene.candidate.update(target=target, line='clear', target_key=('bot', 3))
        scene.decide('aim')
        result = scene.apply(.1)
        self.assertTrue(scene.owner.combat_owned)
        self.assertEqual(previous, scene.owner._episode)
        self.assertEqual(3, result['target_id'])
        self.assertIsNone(scene.owner._route_confirmation)

    def test_siege_review_without_completed_work_releases_original_route(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        scene.raw_order.update(combat_mode='route', move_position=(0., 0., 60.))
        scene.decide('wait', candidate=False, reason='stationary_alternatives_pending')
        scene.policy.rows['pending'] = dict(stationary_progress_token=(1, 0, 0, 0))
        scene.apply(1.)
        scene.policy.rows['pending']['stationary_progress_token'] = (100, 0, 0, 0)
        result = scene.apply(1. + MECHANICAL_STALL_SECONDS)
        self.assertFalse(scene.owner.combat_owned)
        self.assertEqual('siege_stationary_review_stalled', scene.owner.receipt['reason'])
        self.assertEqual((0., 0., 60.), result['move_position'])
    def test_visible_contact_without_native_task_proposal_preserves_route(self):
        scene = Scene(admitted=False)
        scene.raw_order.update(target_id=None, target_kind=None, combat_mode='route',
            move_position=(17., 0., 31.), throttle_override=None,
            aim_position=None, fire_allowed=False)
        scene.candidate.update(line='world_blocked', armor='unknown')
        scene.decide('firing_position')
        before = copy.deepcopy(scene.raw_order)
        result = scene.apply(0.)
        self.assertEqual(before, result)
        self.assertTrue(scene.owner.active)
        self.assertFalse(scene.owner.combat_owned)
        self.assertFalse(scene.owner.stop_allowed)
        self.assertEqual((scene.target,), scene.owner.targets)
        self.assertTrue(scene.owner.contains(scene.target))
        scene.runtime.planner._route.assert_not_called()

    def test_protected_navigation_keeps_destinations(self):
        cases = ('base_defense',
                 'team_attack', 'team_return_base', 'team_defend_base', 'team_follow',
                 'team_attention_cell', 'team_hold_position')
        for mode in cases:
            for action in ('aim', 'firing_position', 'search_penetration'):
                with self.subTest(mode=mode, action=action):
                    scene = Scene()
                    scene.raw_order.update(combat_mode=mode, move_position=(17., 0., 31.),
                                           throttle_override=None, route_index=3)
                    if mode == 'team_attack':
                        scene.runtime._mission = dict(explicit=True, action='attack',
                            destination=(17., 0., 31.), radius=2.)
                    scene.candidate.update(line='clear')
                    scene.decide(action)
                    before = copy.deepcopy(scene.raw_order)
                    self.assertEqual(before, scene.apply(0.))
                    self.assertFalse(scene.owner.stop_allowed)
                    scene.runtime.planner._route.assert_not_called()

    def test_capture_and_parking_stops_are_not_donated_to_combat(self):
        for fields in (dict(parking_phase='waiting'), dict(capture_area=True)):
            with self.subTest(fields=fields):
                scene = Scene()
                scene.raw_order.update(fields)
                before = copy.deepcopy(scene.raw_order)
                self.assertEqual(dict(before, aim_position=scene.candidate['solution']['point'],
                                      fire_allowed=False), scene.apply(0.))
                self.assertFalse(scene.owner.stop_allowed)
        scene = Scene()
        scene.runtime._mission = dict(capture_started=True)
        self.assertEqual(dict(scene.raw_order, aim_position=scene.candidate['solution']['point'],
                              fire_allowed=False), scene.apply(0.))
        self.assertFalse(scene.owner.stop_allowed)

    def test_retired_tactical_modes_cannot_supply_combat_stop(self):
        for mode in ('flank', 'take_cover', 'cover_hold', 'cover_peek', 'cover_return',
                     'magazine_reload_retreat', 'low_health_retreat', 'withdraw'):
            with self.subTest(mode=mode):
                scene = Scene()
                scene.raw_order.update(combat_mode=mode, throttle_override=0.)
                scene.candidate.update(line='clear')
                scene.decide('aim')
                before = copy.deepcopy(scene.raw_order)
                self.assertEqual(before, scene.apply(0.))
                self.assertFalse(scene.owner.stop_allowed)
                self.assertFalse(scene.owner.combat_owned)

    def test_selected_target_then_full_live_domain_ignores_old_scores_and_refusals(self):
        scene = Scene(admitted=False)
        extra = [dict(scene.target, id=i, network_id=i) for i in range(3, 8)]
        scene.runtime._targets = (scene.target,) + tuple(extra)
        selection = scene.raw_order['tactical_evidence']['selection']
        selection.update(outcome='movement_lease', candidates=[
            dict(target=('bot', 5), reason='no_local_lane', score=-100.),
            dict(target=('bot', 4), reason='eligible', score=20.),
            dict(target=('bot', 2), reason='no_local_lane', score=100.),
            dict(target=('bot', 3), reason='eligible', score=5.),
            dict(target=('bot', 6), reason='eligible', score=1.),
            dict(target=('bot', 7), reason='outside_engagement_range', score=-100.)],
            focus_refusals=[dict(target=('bot', 6))])
        scene.owner.accept(scene.raw_order)
        self.assertEqual((2, 3, 4, 5, 6, 7), tuple(row['id'] for row in scene.owner.targets))
        self.assertTrue(scene.owner.contains(scene.target))
        self.assertTrue(all(scene.owner.contains(row) for row in extra))
        self.assertEqual((), scene.owner.receipt['excluded'])
        self.assertEqual('candidate_evaluation_only', scene.owner.receipt['reason'])

    def test_initial_key_selects_nearest_before_lower_armor(self):
        scene = Scene()
        source = (10., 0., 20.)
        near = dict(scene.target, id=3, network_id=3,
                    position=(10., 0., 25.), armor=300.)
        soft = dict(scene.target, id=4, network_id=4,
                    position=(10., 0., 26.), armor=10.)
        selected = min((soft, near),
                       key=lambda target: ordinary_initial_key(source, target))
        self.assertIs(near, selected)
        self.assertEqual(5., ordinary_initial_key(source, near)[0])
        self.assertEqual(6., ordinary_initial_key(source, soft)[0])

    def test_equal_distance_initial_key_prefers_lower_armor_and_orders_domain(self):
        scene = Scene()
        armored = dict(scene.target, id=3, network_id=3,
                       position=(3., 0., 4.), armor=180.)
        soft = dict(scene.target, id=4, network_id=4,
                    position=(-3., 0., -4.), profile=dict(armor=25.))
        selected = min((armored, soft), key=lambda target:
                       ordinary_initial_key(scene.state['position'], target))
        self.assertIs(soft, selected)
        scene.runtime._targets = (armored, scene.target, soft)
        scene.owner.accept(scene.raw_order)
        self.assertEqual((4, 3, 2), tuple(row['id'] for row in scene.owner.targets))

    def test_distances_are_not_binned_to_invent_an_armor_tie(self):
        scene = Scene()
        near = dict(scene.target, id=3, network_id=3,
                    position=(0., 0., 50.), armor=300.)
        soft = dict(scene.target, id=4, network_id=4,
                    position=(0., 0., 50.001), armor=10.)
        self.assertLess(ordinary_initial_key(scene.state['position'], near),
                        ordinary_initial_key(scene.state['position'], soft))

    def test_macro_target_is_only_a_hint_before_policy_acquires_an_intention(self):
        scene = Scene(admitted=False)
        near = dict(scene.target, id=3, network_id=3,
                    position=(0., 0., 20.), armor=300.)
        farther = dict(scene.target, id=4, network_id=4,
                       position=(0., 0., 30.), armor=10.)
        scene.runtime._targets = (farther, near, scene.target)
        scene.owner.accept(scene.raw_order)
        self.assertEqual((3, 4, 2), tuple(row['id'] for row in scene.owner.targets))
        self.assertIs(scene.target, scene.owner.engagement_target(scene.raw_order))
        self.assertEqual(('bot', 3), scene.owner.receipt['selected'])
        self.assertEqual(('bot', 2), scene.owner.receipt['initial_hint'])

    def test_dead_and_zero_health_contacts_are_not_armour_review_candidates(self):
        scene = Scene()
        living = dict(scene.target, id=3, network_id=3, health=1.)
        invalid = [dict(scene.target, id=4, network_id=4, alive=False),
                   dict(scene.target, id=5, network_id=5, alive=True, health=0.),
                   dict(scene.target, id=6, network_id=6, health=-1.),
                   dict(scene.target, id=7, network_id=7, health=float('nan'))]
        scene.runtime._targets = (scene.target, living) + tuple(invalid)
        scene.owner.accept(scene.raw_order)
        self.assertEqual((2, 3), tuple(row['id'] for row in scene.owner.targets))
        self.assertTrue(scene.owner.contains(living))
        self.assertTrue(all(not scene.owner.contains(row) for row in invalid))
        self.assertEqual((True, (('bot', 2), ('bot', 3))), scene.owner.signature)

    def test_retired_priority_metadata_cannot_change_target_or_domain_signature(self):
        scene = Scene()
        other = dict(scene.target, id=3, network_id=3, kind='human')
        scene.runtime._targets += (other,)
        scene.owner.accept(scene.raw_order)
        signature = scene.owner.signature
        targets = scene.owner.targets
        scene.state['recent_hit'] = dict(attacker_kind='human', attacker_id=3, at=1.)
        selection = scene.raw_order['tactical_evidence']['selection']
        selection.update(selected=('human', 3), outcome='retaliation',
            candidates=[dict(target=('human', 3), reason='eligible', score=-1000.),
                        dict(target=('bot', 2), reason='no_local_lane', score=1000.)],
            focus_refusals=[dict(target=('bot', 2))])
        scene.owner.accept(scene.raw_order)
        self.assertEqual(targets, scene.owner.targets)
        self.assertEqual(signature, scene.owner.signature)
        self.assertEqual(('bot', 2), scene.owner.receipt['selected'])
        self.assertEqual((), scene.owner.receipt['excluded'])

    def test_ordinary_advance_admits_full_native_review_and_current_shot_stop(self):
        scene = Scene(admitted=False)
        scene.runtime.actor_kind = 'human'
        other = dict(scene.target, id=3, network_id=3)
        scene.runtime._targets += (other,)
        scene.raw_order.update(combat_mode='advance', move_position=(17., 0., 31.),
                               throttle_override=None)
        scene.raw_order['tactical_evidence']['selection']['candidates'].append(
            dict(target=('bot', 3), reason='eligible', score=10.))
        scene.owner.accept(scene.raw_order)
        self.assertTrue(scene.owner.active)
        self.assertFalse(scene.owner.stop_allowed)
        self.assertEqual((2, 3), tuple(row['id'] for row in scene.owner.targets))
        scene.candidate.update(line='clear')
        scene.decide('aim')
        for step in range(16):
            result = scene.apply(step * .125)
            self.assertEqual('advance', result['combat_mode'])
            self.assertFalse(scene.owner.stop_allowed)
        result = scene.apply(2.)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertEqual('engage', result['combat_mode'])
        self.assertEqual(scene.state['position'], result['move_position'])
        self.assertEqual(0., result['throttle_override'])

    def test_target_gone_or_fire_disabled_cannot_reuse_a_previous_stop(self):
        for condition in ('hidden', 'dead', 'no_fire', 'empty', 'brake'):
            with self.subTest(condition=condition):
                scene = Scene()
                scene.candidate.update(mechanical='hull_laying', line='clear')
                scene.candidate['solution']['yaw'] = .7
                scene.apply(0.)
                self.assertIsNotNone(scene.owner.pivot)
                if condition == 'hidden':
                    scene.target['visible'] = False
                elif condition == 'dead':
                    scene.target['alive'] = False
                elif condition == 'no_fire':
                    scene.runtime.features = {'drive'}
                elif condition == 'empty':
                    scene.raw_order['empty_ammo'] = True
                else:
                    scene.runtime._mission_brakes = lambda: True
                self.assertEqual(scene.raw_order, scene.apply(1.))
                self.assertFalse(scene.owner.active)
                self.assertIsNone(scene.owner.pivot)

    def test_foreign_candidate_cannot_donate_pivot_or_blocker_evidence(self):
        for evidence in ('stationary_plan', 'friendly_blocker', 'move_request'):
            with self.subTest(evidence=evidence):
                scene = Scene()
                foreign = dict(scene.target, id=99, network_id=99)
                scene.candidate['target'] = foreign
                if evidence == 'stationary_plan':
                    scene.stationary()
                elif evidence == 'friendly_blocker':
                    scene.candidate.update(line='friendly_blocked', blocker=dict(
                        blocker_kind='bot', blocker_id=5, blocker_team=1,
                        blocker_position=(0., 0., 12.), blocker_radius=2.))
                else:
                    scene.decide('firing_position', candidate=False,
                        move_request=dict(target=foreign, solution=dict(point=(25., 1., 80.))))
                result = scene.apply(0.)
                self.assertIsNone(scene.owner.pivot)
                self.assertNotEqual((25., 1., 80.), result.get('face_position'))
                self.assertFalse(hasattr(scene.runtime.engine, '_friendly_repositions'))
                self.assertIsNone(scene.state.get('_gun_angle_refusal'))
                scene.runtime.planner._route.assert_not_called()

    def test_reset_only_retires_own_observation_not_original_recovery(self):
        scene = Scene()
        scene.state['_rear_motion_lease'] = dict(start=0., goal=(0., 0., 80.))
        scene.runtime.engine.navigator.bot_states[1] = dict(path_key=('route', 1))
        before = copy.deepcopy(scene.state)
        before.pop('_combat_movement_owner')
        scene.owner.reset()
        self.assertEqual(before, scene.state)
        self.assertEqual((0., 0., 80.), scene.state['_rear_motion_lease']['goal'])
        self.assertEqual(('route', 1), scene.runtime.engine.navigator.bot_states[1]['path_key'])


class NativePlanningInputTests(unittest.TestCase):
    def test_safe_stationary_plan_lays_without_promoting_the_blocked_actual_muzzle(self):
        scene = Scene()
        planned = scene.stationary()
        actual = copy.deepcopy(scene.candidate)
        with mock.patch.object(scene.policy, 'current_row', wraps=scene.policy.current_row) as current:
            result = scene.apply(0.)
        self.assertGreaterEqual(current.call_count, 2)
        current.assert_any_call(scene.candidate, require_line=True)
        self.assertEqual(mock.call(scene.candidate, require_line=True),
                         current.call_args_list[-1])
        self.assertEqual('native_lay', scene.owner.receipt['reason'])
        self.assertEqual('copied_combat_hull_aim', scene.runtime._last_navigation['owner'])
        self.assertEqual(scene.state['position'], result['move_position'])
        self.assertEqual(planned['solution']['point'], result['face_position'])
        self.assertAlmostEqual(.5, scene.owner.pivot['best_error'])
        self.assertFalse(result['fire_allowed'])
        self.assertEqual(actual, scene.candidate)
        self.assertFalse(AttackPolicy._executable(scene.candidate))
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_stationary_motion_requires_current_proved_loaded_shell_plan(self):
        for case in ('stale', 'pending', 'not_proved', 'blocked', 'armor_failed', 'no_hull', 'other_shell'):
            with self.subTest(case=case):
                scene = Scene()
                planned = scene.stationary()
                if case == 'stale':
                    scene.candidate['fresh'] = False
                elif case == 'pending':
                    planned['status'] = 'pending'
                elif case == 'not_proved':
                    planned['proof']['proved'] = False
                elif case == 'blocked':
                    planned['line'] = 'world_blocked'
                elif case == 'armor_failed':
                    planned['armor'] = 'failed'
                elif case == 'no_hull':
                    planned['solution']['needs_hull'] = False
                else:
                    scene.candidate['shell_index'] = 1
                result = scene.apply(0.)
                self.assertIsNone(scene.owner.pivot)
                self.assertFalse(result['fire_allowed'])
                self.assertEqual('same_point_recovery', scene.runtime._last_navigation['owner'])

    def test_stationary_he_contact_plan_is_motion_only_not_penetration_proof(self):
        scene = Scene()
        planned = scene.stationary(mode='he_fallback')
        planned.update(armor='failed', contact=True, expected_damage=0.)
        result = scene.apply(0.)
        self.assertEqual('native_lay', scene.owner.receipt['reason'])
        self.assertFalse(result['fire_allowed'])
        self.assertFalse(AttackPolicy._executable(scene.candidate, 'he_fallback'))
        self.assertEqual('unknown', scene.candidate['armor'])

    def test_stationary_motion_consumer_requires_admitted_lay_and_never_authorizes_fire(self):
        for mechanical, actual_line in (('hull_laying', 'world_blocked'),
                                        ('mechanical_limited', 'clear')):
            with self.subTest(mechanical=mechanical):
                scene = Scene()
                scene.stationary()
                scene.candidate.update(mechanical=mechanical, line=actual_line,
                    pose_stamp='actual-native-pose', line_stamp='current-native-lane')
                actual = copy.deepcopy(scene.candidate)
                consumer = lambda aim: FullPlayerRuntime.current_attack_candidate(
                    scene.runtime, scene.state, scene.target, for_aim=aim)
                self.assertIsNone(consumer(True))
                scene.apply(0.)
                motion = consumer(True)
                self.assertTrue(motion['_player_stationary_motion'])
                self.assertTrue(motion['solution']['_player_motion_only'])
                self.assertEqual((25., 1., 80.), motion['solution']['point'])
                self.assertEqual(actual_line, motion['line'])
                self.assertEqual('unknown', motion['armor'])
                self.assertEqual(mechanical, motion['mechanical'])
                self.assertIsNone(consumer(False))
                scene.policy.decision['action'] = 'aim'
                self.assertIsNone(consumer(False))
                self.assertEqual(actual, scene.candidate)

    def test_aim_label_without_current_executable_evidence_cannot_stop(self):
        for case in ('stale', 'blocked', 'limited', 'unknown'):
            with self.subTest(case=case):
                scene = Scene()
                scene.candidate.update(line='clear')
                if case == 'stale':
                    scene.candidate['fresh'] = False
                elif case == 'blocked':
                    scene.candidate['line'] = 'world_blocked'
                elif case == 'limited':
                    scene.candidate['mechanical'] = 'mechanical_limited'
                else:
                    scene.candidate['armor'] = 'unknown'
                scene.raw_order.update(combat_mode='advance_contact',
                    move_position=(0., 0., 80.), throttle_override=None)
                # This boundary begins with an accepted approach, not a new
                # macro request that is allowed to replace an existing stop.
                scene.owner.finish(scene.raw_order)
                scene.decide('aim')
                result = scene.apply(0.)
                self.assertEqual((0., 0., 80.), result['move_position'])
                self.assertNotEqual('stopped', scene.owner.receipt['status'])
                self.assertFalse(result['fire_allowed'])

    def test_target_or_point_change_does_not_restart_six_second_native_stall_clock(self):
        scene = Scene()
        scene.candidate.update(mechanical='hull_laying', line='clear')
        scene.candidate['solution']['yaw'] = .7
        scene.apply(0.)
        other = dict(scene.target, id=3, network_id=3)
        scene.runtime._targets += (other,)
        scene.raw_order['tactical_evidence']['selection']['candidates'].append(
            dict(target=('bot', 3), reason='eligible', score=1.))
        scene.candidate['target'] = other
        scene.candidate['solution']['yaw'] = -.7
        scene.apply(5.)
        self.assertEqual(0., scene.owner.pivot['progress_at'])
        result = scene.apply(MECHANICAL_STALL_SECONDS)
        self.assertIsNone(scene.owner.pivot)
        self.assertEqual('native_pivot_stalled', scene.owner._failed_recovery['reason'])
        self.assertFalse(scene.owner.stop_allowed)
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        scene.runtime.planner._route.assert_not_called()

    def test_actual_native_progress_renews_only_the_existing_stall_allowance(self):
        scene = Scene()
        scene.candidate.update(mechanical='hull_laying', line='clear')
        scene.candidate['solution']['yaw'] = .7
        scene.apply(0.)
        pivot = scene.owner.pivot
        scene.state['yaw'] = .2
        scene.apply(5.)
        self.assertIs(pivot, scene.owner.pivot)
        self.assertEqual(5., pivot['progress_at'])
        scene.apply(7.)
        self.assertNotIn('handoff', pivot)
        scene.apply(11.)
        self.assertIn('handoff', pivot)

    def test_failed_pivot_rechecks_same_point_before_route_reacquisition(self):
        scene = Scene()
        scene.candidate.update(mechanical='hull_laying', line='clear')
        scene.candidate['solution']['yaw'] = .7
        scene.runtime.point_recovery_probe = lambda *args: dict(status='pending')
        scene.apply(0.)
        scene.apply(MECHANICAL_STALL_SECONDS)
        self.assertIsNone(scene.owner.pivot)
        self.assertFalse(scene.owner.stop_allowed)
        scene.apply(7.)
        self.assertFalse(scene.owner.stop_allowed)
        scene.runtime.point_recovery_probe = lambda *args: dict(status='clear')
        scene.apply(8.)
        phase = scene.owner._physical_recovery
        self.assertIsNotNone(phase)
        self.assertEqual(scene.candidate['key'], phase['key'])
        goal = phase['goal']
        self.assertIsNotNone(goal)
        scene.position((goal[0] - .01, goal[1], goal[2]))
        scene.apply(8.3)
        self.assertIsNone(scene.owner.pivot)
        scene.apply(8.4)
        self.assertIs(phase, scene.owner._physical_recovery)
        self.assertEqual(phase['key'], scene.candidate['key'])
        self.assertIsNotNone(scene.owner.pivot)
        self.assertFalse(scene.owner._motion_order.get('fire_allowed', False))


class UnchangedRecoveryConsumerTests(unittest.TestCase):
    def test_player_keeps_original_rear_law_without_independent_position_finders(self):
        for name in ('_rear_laying_order',):
            with self.subTest(name=name):
                self.assertIs(getattr(bot_runtime.BotRuntime, name),
                              getattr(_PlayerBehaviorEngine, name))
        self.assertFalse(hasattr(bot_runtime.BotRuntime, '_gun_angle_order'))
        self.assertFalse(hasattr(_PlayerBehaviorEngine, '_gun_angle_order'))
        self.assertFalse(hasattr(bot_runtime.BotRuntime, '_friendly_reposition_order'))
        self.assertFalse(hasattr(_PlayerBehaviorEngine, '_friendly_reposition_order'))

    def test_mechanical_failure_ends_the_bounded_move_without_starting_a_pursuit(self):
        scene = Scene()
        scene.candidate.update(mechanical='mechanical_limited', line='clear')
        scene.raw_order.update(combat_mode='route', target_id=None, target_kind=None,
            move_position=(20., 0., -30.), throttle_override=None,
            aim_position=None, fire_allowed=False)
        order = scene.apply(0.)
        self.assertTrue(scene.owner.physical_recovery_active())
        scene.runtime.point_recovery_probe = lambda *args: dict(status='blocked')
        result = order
        for tick in range(1, 15):
            result = scene.apply(tick * .1)
            if not scene.owner.combat_owned:
                break
        self.assertEqual('point_recovery_no_checked_position',
                         scene.owner._failed_recovery['reason'])
        self.assertEqual('route', result['combat_mode'])
        self.assertEqual((20., 0., -30.), result['move_position'])
        self.assertIsNone(result['target_id'])
        self.assertFalse(scene.owner.stop_allowed)
        self.assertEqual(3, scene.runtime.gun.clip)
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        scene.runtime.planner._route.assert_not_called()

    def test_stationary_review_does_not_restart_same_point_mechanical_recovery(self):
        scene = Scene()
        scene.candidate.update(mechanical='mechanical_limited', line='clear')
        scene.raw_order.update(combat_mode='route', target_id=None, target_kind=None,
            move_position=(20., 0., -30.), throttle_override=None,
            aim_position=None, fire_allowed=False)
        order = scene.apply(0.)
        phase = scene.owner._physical_recovery
        scene.decide('wait', candidate=False, reason='stationary_domain_review_pending')
        scene.owner.accept(scene.raw_order)
        result = scene.owner.apply_order(order, 1.)
        self.assertIs(phase, scene.owner._physical_recovery)
        self.assertEqual(0., phase['started'])
        self.assertFalse(result['fire_allowed'])
        scene.runtime.point_recovery_probe = lambda *args: dict(status='blocked')
        result = scene.apply(MECHANICAL_STALL_SECONDS)
        self.assertEqual('route', result['combat_mode'])
        self.assertFalse(scene.owner.stop_allowed)
        self.assertEqual('point_recovery_exhausted',
                         scene.owner._failed_recovery['reason'])

    def test_stationary_review_keeps_pivot_age_without_creating_new_recovery(self):
        scene = Scene()
        scene.candidate.update(mechanical='hull_laying', line='clear')
        scene.candidate['solution']['yaw'] = .5
        scene.apply(0.)
        pivot = scene.owner.pivot
        scene.decide('wait', candidate=False, reason='stationary_domain_review_pending')
        scene.apply(1.)
        self.assertIs(pivot, scene.owner.pivot)
        self.assertNotIn('handoff', pivot)
        self.assertEqual(0., pivot['progress_at'])
        scene.decide('firing_position')
        scene.apply(1.5)
        self.assertIs(pivot, scene.owner.pivot)
        self.assertEqual(0., pivot['progress_at'])

    def test_friendly_same_point_move_cannot_renew_its_stall_clock_each_policy_tick(self):
        scene = Scene()
        scene.candidate.update(line='friendly_blocked', blocker=dict(blocker_kind='bot',
            blocker_id=5, blocker_team=1, blocker_position=(0., 0., 12.), blocker_radius=2.))
        scene.runtime.point_recovery_probe = lambda *args: dict(status='clear')
        scene.apply(0.)
        phase = scene.owner._physical_recovery
        deadline = MECHANICAL_STALL_SECONDS
        for moment in (1., 2., deadline - .01):
            order = scene.apply(moment)
            self.assertIs(phase, scene.owner._physical_recovery)
            self.assertEqual(phase['goal'], order['move_position'])
            self.assertEqual(0., phase['progress_at'])
        scene.apply(deadline)
        self.assertIsNone(scene.owner._physical_recovery)
        self.assertFalse(scene.owner.stop_allowed)
        self.assertEqual('point_recovery_drive_stalled', scene.owner._failed_recovery['reason'])
        scene.apply(deadline + .1)
        self.assertIsNone(scene.owner._physical_recovery)
        self.assertEqual(3, scene.runtime.gun.clip)
        scene.runtime.planner._route.assert_not_called()

    def test_valid_reopened_native_point_completes_only_matching_recovery(self):
        scene = Scene()
        scene.candidate.update(line='friendly_blocked', blocker=dict(blocker_kind='bot',
            blocker_id=5, blocker_team=1, blocker_position=(0., 0., 12.), blocker_radius=2.))
        scene.runtime.point_recovery_probe = lambda *args: dict(status='clear')
        scene.apply(0.)
        phase = scene.owner._physical_recovery
        self.assertIsNotNone(phase)
        scene.candidate['line'] = 'clear'
        scene.decide('aim')
        result = scene.apply(1.)
        self.assertTrue(phase['ready'])
        scene.apply(1.1)
        self.assertIsNone(scene.owner._physical_recovery)
        self.assertEqual(0., result['throttle_override'])
        self.assertEqual('verified_shot', scene.owner.receipt['reason'])

    def test_stationary_review_preserves_the_checked_friendly_same_point_goal(self):
        scene = Scene()
        scene.candidate.update(line='friendly_blocked', blocker=dict(blocker_kind='bot',
            blocker_id=5, blocker_team=1, blocker_position=(0., 0., 12.), blocker_radius=2.))
        scene.runtime.point_recovery_probe = lambda *args: dict(status='clear')
        scene.apply(0.)
        phase = scene.owner._physical_recovery
        scene.decide('wait', candidate=False, reason='stationary_domain_review_pending')
        result = scene.apply(1.)
        self.assertIs(phase, scene.owner._physical_recovery)
        self.assertEqual(phase['goal'], result['move_position'])
        self.assertFalse(result['fire_allowed'])
        scene.apply(MECHANICAL_STALL_SECONDS)
        self.assertIsNone(scene.owner._physical_recovery)
        self.assertFalse(scene.owner.stop_allowed)

    def test_shared_combat_retires_the_old_rear_pursuit_without_choosing_a_route(self):
        scene = Scene()
        original_goal = (13., 0., 37.)
        scene.state['_rear_motion_lease'] = dict(start=0., origin=scene.state['position'],
            goal=original_goal, fire_seq=0, target_id=2)
        scene.decide('wait', candidate=False, reason='stationary_domain_review_pending')
        order = scene.apply(7.9)
        result = scene.runtime.engine._rear_laying_order(
            scene.state, order, {2: scene.target}, 8.)
        self.assertIs(order, result)
        self.assertEqual('engage', result['combat_mode'])
        self.assertNotEqual(original_goal, result['move_position'])
        self.assertEqual(0., result['throttle_override'])
        self.assertEqual(2, result['target_id'])
        self.assertNotIn('_rear_motion_lease', scene.state)
        self.assertFalse(scene.state['_rear_motion_blocked'])
        scene.runtime.planner._route.assert_not_called()

    def test_explicit_mission_handoff_retires_only_combat_stop_leases(self):
        scene = Scene()
        state = scene.state
        state['_magazine_followup'] = dict(identity=('bot', 2), fire_seq=1,
            target_id=2, origin=state['position'], fired_at=0., deadline=3.)
        state['_rear_aim_episode'] = dict(identity=('bot', 2), target_id=2, start=0., fire_seq=1)
        state['_rear_hull_aim'] = (('bot', 2), 1.)
        state['_rear_motion_lease'] = dict(start=0., goal=(13., 0., 37.))
        state['_rear_contact_refusal'] = dict(identity=('bot', 2))
        state['_rear_motion_blocked'] = True
        state['ammo_remaining'], state['reload_time'] = [17, 10], .1
        original_navigation = dict(path_key=('authored_route', 3), recovery_time=1.)
        scene.runtime.engine.navigator.bot_states[1] = original_navigation
        physical_tail = dict(next_index=1, count=3)
        scene.runtime.owner._local_player_burst = physical_tail
        gun_before = dict(vars(scene.runtime.gun))
        scene.owner.mission_handoff(1.)
        for name in ('_magazine_followup', '_rear_aim_episode', '_rear_hull_aim',
                     '_rear_motion_lease', '_rear_contact_refusal'):
            self.assertNotIn(name, state)
        self.assertFalse(state['_rear_motion_blocked'])
        self.assertEqual('priority_handoff', state['_magazine_followup_terminal']['reason'])
        self.assertEqual('player_mission_priority_handoff', state['_rear_motion_observation']['reason'])
        self.assertIs(original_navigation, scene.runtime.engine.navigator.bot_states[1])
        self.assertIs(physical_tail, scene.runtime.owner._local_player_burst)
        self.assertEqual(gun_before, vars(scene.runtime.gun))
        self.assertEqual(([17, 10], .1), (state['ammo_remaining'], state['reload_time']))
        scene.runtime.planner._route.assert_not_called()

    def test_ordinary_combat_wait_does_not_retire_committed_magazine_followup(self):
        scene = Scene()
        scene.state.update(clip_size=3, clip=2, reload_time=.5)
        hold = scene.state['_magazine_followup'] = dict(identity=('bot', 2), fire_seq=1,
            target_id=2, origin=scene.state['position'], fired_at=0., deadline=2.5)
        scene.decide('wait', candidate=False, reason='ordinary_evidence_pending')
        order = scene.apply(1.)
        self.assertIs(hold, scene.state['_magazine_followup'])
        result = scene.runtime.engine._rear_laying_order(scene.state, order, {2: scene.target}, 1.)
        self.assertIs(hold, scene.state['_magazine_followup'])
        self.assertEqual('engage', result['combat_mode'])
        self.assertEqual(0., result['throttle_override'])
        # The shot/load transaction is retained; the retired rear planner is
        # not allowed to become a second movement owner for that transaction.
        self.assertIs(order, result)
        self.assertNotIn('_magazine_followup_receipt', scene.state)
        self.assertEqual(2.5, hold['deadline'])


class EarlyStopNotLateControlRewriteTests(unittest.TestCase):
    def test_policy_order_overlay_preserves_all_original_movement_fields(self):
        scene = Scene()
        scene.candidate.update(line='clear')
        scene.decide('aim')
        order = dict(scene.raw_order, combat_mode='advance', move_position=(17., 0., 31.),
                     throttle_override=None, route_index=3, arrival_radius=4.)
        scene.owner.accept(order)
        result = AttackPolicy.apply_order(scene.policy, order, 0.)
        for name in ('combat_mode', 'move_position', 'throttle_override', 'route_index', 'arrival_radius'):
            self.assertEqual(order[name], result[name])

    def test_travel_refines_only_original_target_point_and_retains_its_hull_facing(self):
        for mode in ('team_attack', 'base_defense'):
            with self.subTest(mode=mode):
                scene = Scene()
                scene.candidate.update(line='clear')
                scene.decide('aim')
                order = dict(scene.raw_order, combat_mode=mode,
                    move_position=(17., 0., 31.), throttle_override=None,
                    face_position=(-9., 0., 22.))
                if mode == 'team_attack':
                    scene.runtime._mission = dict(explicit=True, action='attack',
                        destination=order['move_position'], radius=2.)
                scene.owner.accept(order)
                result = AttackPolicy.apply_order(scene.policy, order, 0.)
                for name in ('target_id', 'target_kind', 'face_position',
                             'move_position', 'combat_mode', 'throttle_override'):
                    self.assertEqual(order[name], result[name])
                self.assertEqual(scene.candidate['solution']['point'], result['aim_position'])
                self.assertTrue(result['fire_allowed'])

    def test_other_eligible_policy_target_cannot_replace_original_travel_target_or_face(self):
        for mode in ('team_attack', 'base_defense'):
            with self.subTest(mode=mode):
                scene = Scene()
                other = dict(scene.target, id=3, network_id=3, position=(25., 0., 70.))
                scene.runtime._targets += (other,)
                scene.raw_order['tactical_evidence']['selection']['candidates'].append(
                    dict(target=('bot', 3), reason='eligible', score=10.))
                scene.candidate.update(line='clear', target=other)
                scene.candidate['solution']['point'] = (25., 1., 70.)
                scene.decide('aim')
                order = dict(scene.raw_order, combat_mode=mode,
                    move_position=(17., 0., 31.), throttle_override=None,
                    face_position=(-9., 0., 22.))
                if mode == 'team_attack':
                    scene.runtime._mission = dict(explicit=True, action='attack',
                        destination=order['move_position'], radius=2.)
                scene.owner.accept(order)
                result = AttackPolicy.apply_order(scene.policy, order, 0.)
                expected = dict(order, fire_allowed=False)
                self.assertEqual(expected, result)

    def test_combat_owned_stop_still_accepts_a_different_eligible_policy_target(self):
        scene = Scene()
        other = dict(scene.target, id=3, network_id=3, position=(25., 0., 70.))
        scene.runtime._targets += (other,)
        scene.raw_order['tactical_evidence']['selection']['candidates'].append(
            dict(target=('bot', 3), reason='eligible', score=10.))
        scene.owner.accept(scene.raw_order)
        scene.candidate.update(line='clear', target=other)
        scene.candidate['solution']['point'] = (25., 1., 70.)
        scene.decide('aim')
        result = AttackPolicy.apply_order(scene.policy, scene.raw_order, 0.)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertEqual(3, result['target_id'])
        self.assertEqual(other['position'], result['face_position'])
        self.assertEqual((25., 1., 70.), result['aim_position'])
        self.assertEqual(scene.raw_order['move_position'], result['move_position'])

    def test_combat_stop_is_supplied_before_driver_not_by_late_shooting_callback(self):
        scene = Scene()
        scene.decide('wait', candidate=False, reason='stationary_domain_review_pending')
        before_driver = scene.apply(0.)
        self.assertEqual(0., before_driver['throttle_override'])
        self.assertFalse(before_driver['fire_allowed'])
        self.assertTrue(before_driver['stable_hull_face'])
        self.assertEqual(scene.state['position'], before_driver['face_position'])
        command = dict(before_driver, throttle=.8, turn=-.4, brake=False,
                       movement_intent=True, move_position=(4., 0., 8.))
        result, target = AttackPolicy.select_command(
            scene.policy, scene.state, command, scene.target, .5)
        for name in ('throttle', 'turn', 'brake', 'movement_intent', 'move_position', 'target_id'):
            self.assertEqual(command[name], result[name])
        self.assertIs(scene.target, target)
        self.assertFalse(result['fire_allowed'])
        self.assertIsNone(result['aim_position'])

    def test_late_candidate_cannot_retarget_the_already_solved_driver(self):
        scene = Scene()
        scene.candidate.update(line='clear', target=dict(scene.target, id=99, network_id=99))
        scene.decide('aim')
        command = dict(scene.raw_order, throttle=.5, turn=.2, brake=False)
        result, target = AttackPolicy.select_command(
            scene.policy, scene.state, command, scene.target, 0.)
        self.assertEqual((.5, .2, False), (result['throttle'], result['turn'], result['brake']))
        self.assertEqual(2, result['target_id'])
        self.assertIs(scene.target, target)
        self.assertFalse(result['fire_allowed'])


class SiegeOriginalOwnershipTests(unittest.TestCase):
    @staticmethod
    def desired(scene, command=None, target=None):
        return FullPlayerRuntime.siege_desired(
            scene.runtime, scene.state, command or scene.raw_order, target)

    @staticmethod
    def motion(scene, pitch=-.1, yaw=0.):
        scene.runtime._siege_aim_candidate = dict(target=scene.target, mode='penetration',
            mechanical='hydraulic_laying', shell_index=0,
            solution=dict(point=(0., 10., 80.), yaw=yaw, hull_yaw=yaw,
                siege_correction=pitch, hydraulic_pitch=pitch, needs_hydraulic=True,
                siege_aim=True, source_verified=False, reachable=False))

    def test_route_release_needs_a_new_clear_point_and_two_seconds(self):
        scene = Scene(siege=siege_mechanics.DISABLED, admitted=False)
        scene.raw_order.update(combat_mode='route', move_position=(0., 0., 60.),
                               target_id=None, target_kind=None, face_position=(0., 0., 60.),
                               throttle_override=None, aim_position=None, fire_allowed=False)
        scene.candidate.update(key=(0, ('bot', 2), 0, 'penetration'),
                               line='clear', mechanical='mechanical_limited')
        scene.decide('firing_position')
        for moment in (0., .5, 1., 1.5):
            self.assertEqual(scene.raw_order, scene.apply(moment))
        scene.apply(2.)
        self.assertTrue(scene.owner.waiting_for_siege())
        scene.native_mode(siege_mechanics.ENABLED)
        scene.decide('wait', candidate=False, reason='stationary_alternatives_pending')
        scene.apply(3.)
        result = scene.apply(3. + MECHANICAL_STALL_SECONDS)
        self.assertEqual(scene.raw_order['move_position'], result['move_position'])
        self.assertFalse(scene.owner.combat_owned)
        self.assertFalse(result['fire_allowed'])
        scene.native_mode(siege_mechanics.SWITCHING_OFF)
        scene.decide('firing_position')
        self.assertEqual(scene.raw_order, scene.apply(9.5))
        scene.native_mode(siege_mechanics.DISABLED)
        for moment in (10., 10.5, 11., 11.5, 12.):
            self.assertEqual(scene.raw_order, scene.apply(moment))
        self.assertIsNone(scene.owner._route_confirmation)
        other = dict(scene.candidate, key=(0, ('bot', 2), 1, 'penetration'))
        scene.policy.rows[other['key']] = other
        for moment in (12.5, 13., 13.5, 14.):
            self.assertEqual(scene.raw_order, scene.apply(moment))
        scene.apply(14.5)
        self.assertTrue(scene.owner.waiting_for_siege())
        self.assertEqual(other['key'], scene.owner._siege_point['key'])

    def test_blocked_laying_point_keeps_the_same_siege_engagement(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        scene.candidate.update(key=(0, ('bot', 2), 0, 'penetration'), line='clear')
        self.motion(scene)
        scene.runtime._siege_aim_candidate['key'] = scene.candidate['key']
        scene.apply(0.)
        self.assertIsNotNone(scene.owner.pivot)
        episode = scene.owner._episode
        scene.runtime._siege_aim_candidate = None
        scene.candidate.update(line='friendly_blocked')
        scene.policy.retained_lay_candidate = lambda key, now: dict(
            status='blocked', candidate=scene.candidate)
        result = scene.apply(.2)
        self.assertFalse(result['fire_allowed'])
        self.assertIsNone(scene.owner.pivot)
        self.assertTrue(scene.owner.combat_owned)
        self.assertTrue(self.desired(scene, result))
        self.assertEqual(episode, scene.owner._episode)
        self.assertEqual('siege_point_review', scene.owner.receipt['reason'])

    def test_siege_pivot_tracks_a_clear_point_whose_bearing_outpaces_the_hull(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        key = (0, ('bot', 2), 0, 'penetration')
        scene.candidate.update(key=key, line='clear', mechanical='hull_laying')
        self.motion(scene, pitch=0., yaw=-.05)
        motion = scene.runtime._siege_aim_candidate
        motion.update(key=key, line='clear')
        motion['solution'].update(needs_hull=True, needs_hydraulic=False)
        scene.apply(0.)
        pivot, episode = scene.owner.pivot, scene.owner._episode
        for now, hull, bearing in ((1., -.02, -.15), (3., -.09, -.34),
                                   (5., -.14, -.62), (7., -.19, -.9)):
            scene.state['yaw'] = hull
            motion['solution']['hull_yaw'] = bearing
            command = scene.apply(now)
            self.assertIs(pivot, scene.owner.pivot)
            self.assertEqual(now, pivot['progress_at'])
            self.assertEqual(episode, scene.owner._episode)
            self.assertFalse(command['fire_allowed'])
        self.assertTrue(scene.owner.combat_owned)

        motion['solution']['hull_yaw'] = -1.1
        scene.apply(10.)
        self.assertEqual(7., pivot['progress_at'])
        motion['solution']['hull_yaw'] = -1.3
        command = scene.apply(7. + MECHANICAL_STALL_SECONDS)
        self.assertFalse(command['fire_allowed'])
        self.assertFalse(scene.owner.combat_owned)
        self.assertEqual('native_pivot_stalled', scene.owner._failed_recovery['reason'])

    def test_siege_pivot_does_not_renew_for_hull_jitter_away_from_a_clear_point(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        key = (0, ('bot', 2), 0, 'penetration')
        scene.candidate.update(key=key, line='clear', mechanical='hull_laying')
        self.motion(scene, pitch=0., yaw=-.2)
        motion = scene.runtime._siege_aim_candidate
        motion.update(key=key, line='clear')
        motion['solution'].update(needs_hull=True, needs_hydraulic=False)
        scene.apply(0.)
        pivot = scene.owner.pivot
        for now, hull, bearing in ((3., .02, -.3), (5., .01, -.4), (6., .015, -.5)):
            scene.state['yaw'] = hull
            motion['solution']['hull_yaw'] = bearing
            self.assertFalse(scene.apply(now)['fire_allowed'])
        self.assertEqual(0., pivot['progress_at'])
        self.assertFalse(scene.owner.combat_owned)
        self.assertEqual('native_pivot_stalled', scene.owner._failed_recovery['reason'])

    def test_siege_review_does_not_release_on_an_old_clock_during_reload(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        scene.decide('wait', candidate=False, reason='stationary_alternatives_pending')
        scene.apply(1.)
        scene.candidate.update(line='clear')
        scene.decide('aim')
        scene.apply(5.)
        scene.decide('wait', candidate=False, reason='stationary_alternatives_pending')
        scene.apply(8.)
        self.assertTrue(scene.owner.combat_owned)
        scene.policy.frame['reloading'] = True
        scene.apply(15.)
        self.assertTrue(scene.owner.combat_owned)
        scene.policy.frame['reloading'] = False
        scene.apply(22.)
        self.assertFalse(scene.owner.combat_owned)

    def test_temporary_siege_inverse_loss_waits_during_reload(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        scene.candidate.update(key=(0, ('bot', 2), 0, 'penetration'), line='clear')
        self.motion(scene)
        scene.runtime._siege_aim_candidate['key'] = scene.candidate['key']
        scene.apply(0.)
        self.assertIsNotNone(scene.owner.pivot)
        scene.runtime._siege_aim_candidate = None
        scene.candidate.update(mechanical='mechanical_limited')
        scene.policy.retained_lay_candidate = lambda key, now: dict(
            status='blocked', candidate=scene.candidate, mechanical='mechanical_limited')
        scene.policy.frame['reloading'] = True
        scene.apply(8.)
        self.assertTrue(scene.owner.combat_owned)
        self.assertEqual('native_pivot_geometry_pending', scene.owner.receipt['reason'])
        scene.policy.frame['reloading'] = False
        scene.apply(8.1)
        self.assertTrue(scene.owner.combat_owned)
        scene.apply(14.)
        self.assertFalse(scene.owner.combat_owned)
        self.assertEqual('native_pivot_geometry_stalled', scene.owner.receipt['reason'])

    def test_established_combat_enters_siege_without_requiring_another_point_proof(self):
        for clip in (1, 3, 6):
            with self.subTest(clip=clip):
                scene = Scene(siege=siege_mechanics.DISABLED)
                scene.runtime.gun.clip = scene.runtime.gun.clip_size = clip
                scene.decide('wait', candidate=False)
                self.assertTrue(self.desired(scene))
                result = scene.apply(0.)
                self.assertFalse(result['fire_allowed'])
                self.assertEqual('engagement_waits_native_siege', scene.owner.receipt['reason'])
                self.assertIsNone(scene.owner.pivot)
                self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_unselected_visible_enemy_cannot_start_siege_even_as_late_callback_target(self):
        scene = Scene(siege=siege_mechanics.DISABLED, admitted=False)
        scene.raw_order.update(target_id=None, target_kind=None, combat_mode='route',
            move_position=(0., 0., 40.), throttle_override=None,
            aim_position=None, fire_allowed=False)
        scene.candidate.update(armor='unknown')
        scene.decide('wait', candidate=False)
        scene.owner.accept(scene.raw_order)
        self.assertFalse(self.desired(scene, target=scene.target))
        self.assertEqual(scene.raw_order, scene.apply(0.))

    def test_native_visibility_loss_and_reacquisition_follow_original_order(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        self.assertTrue(self.desired(scene))
        selected = dict(scene.raw_order)
        scene.runtime._targets = ()
        scene.raw_order.update(target_id=None, target_kind=None, combat_mode='route',
                               move_position=(0., 0., 40.), throttle_override=None)
        scene.owner.accept(scene.raw_order)
        self.assertFalse(self.desired(scene))
        scene.runtime._targets = (scene.target,)
        scene.raw_order = selected
        scene.candidate.update(line='clear', mechanical='reachable')
        scene.decide('aim')
        scene.owner.accept(scene.raw_order)
        scene.owner.resolve(scene.raw_order, 0.)
        self.assertTrue(self.desired(scene))

    def test_local_recovery_does_not_exit_siege_because_of_travel_distance(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        for mode in ('engage', 'advance_contact', 'gun_angle_adjust',
                     'friendly_lane_reposition'):
            with self.subTest(mode=mode):
                # These are derived local commands, not replacement raw
                # planner admission. The accepted original owner stays put.
                command = dict(scene.raw_order, combat_mode=mode, throttle=1.,
                    movement_intent=True, move_position=(0., 0., 120.),
                    control_trace=dict(strategic_move_position=(0., 0., 500.)))
                self.assertTrue(self.desired(scene, command, scene.target))

    def test_protected_raw_navigation_cannot_be_overridden_by_a_stale_engage_label(self):
        for mode in ('base_defense', 'team_attack', 'team_back_to_base'):
            with self.subTest(mode=mode):
                scene = Scene(siege=siege_mechanics.ENABLED)
                scene.raw_order.update(combat_mode=mode, move_position=(40., 0., 40.),
                                       throttle_override=None)
                if mode == 'team_attack':
                    scene.runtime._mission = dict(explicit=True, action='attack',
                        destination=scene.raw_order['move_position'], radius=2.)
                scene.owner.accept(scene.raw_order)
                overwritten = dict(scene.raw_order, combat_mode='engage',
                    move_position=(0., 0., 0.), throttle_override=0.)
                self.assertTrue(scene.owner.navigation_owns(overwritten, task_only=True))
                self.assertFalse(self.desired(scene, overwritten, scene.target))
                self.assertEqual(scene.raw_order, scene.apply(1.))

    def test_explicit_destination_keeps_travel_until_original_combat_at_arrival(self):
        scene = Scene(siege=siege_mechanics.DISABLED)
        scene.runtime._mission = dict(id='go-hold', explicit=True, action='hold_position',
                                     destination=(10., 0., 0.), radius=2.)
        scene.owner.accept(scene.raw_order)
        self.assertFalse(self.desired(scene))
        scene.position((9., 0., 0.))
        scene.candidate.update(line='clear', mechanical='reachable')
        scene.decide('aim')
        scene.owner.accept(scene.raw_order)
        scene.owner.resolve(scene.raw_order, 0.)
        self.assertTrue(self.desired(scene))

    def test_native_transition_direction_is_atomic_across_owner_changes(self):
        scene = Scene(siege=siege_mechanics.DISABLED)
        scene.runtime._siege_pending = dict(enabled=True, sequence=1)
        scene.runtime._targets = ()
        scene.owner.accept(dict(scene.raw_order, combat_mode='base_defense'))
        self.assertTrue(self.desired(scene))
        scene.runtime._siege_pending = dict(enabled=False, sequence=2)
        scene.runtime._targets = (scene.target,)
        scene.owner.accept(scene.raw_order)
        self.assertFalse(self.desired(scene))
        scene.runtime._siege_pending = None
        scene.native_mode(siege_mechanics.SWITCHING_ON)
        self.assertTrue(self.desired(scene))
        scene.native_mode(siege_mechanics.SWITCHING_OFF)
        self.assertFalse(self.desired(scene))

    def test_drive_only_retains_original_bot_distance_rule(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        scene.runtime.features = {'drive'}
        near = dict(scene.raw_order, movement_intent=True, move_position=(0., 0., 1.))
        self.assertTrue(self.desired(scene, near, scene.target))
        far = dict(near, control_trace=dict(strategic_move_position=(0., 0., 500.)))
        self.assertFalse(self.desired(scene, far, scene.target))

    def test_mode_wait_has_no_preview_clock_then_native_lay_is_bounded(self):
        scene = Scene(siege=siege_mechanics.DISABLED)
        scene.decide('wait', candidate=False)
        original_rows = copy.deepcopy(scene.policy.rows)
        for moment, mode in ((0., siege_mechanics.DISABLED),
                             (1., siege_mechanics.SWITCHING_ON),
                             (10., siege_mechanics.SWITCHING_ON)):
            scene.native_mode(mode)
            self.assertFalse(scene.apply(moment)['fire_allowed'])
            self.assertIsNone(scene.owner.pivot)
        scene.native_mode(siege_mechanics.ENABLED)
        self.motion(scene)
        scene.apply(11.)
        self.assertEqual(11., scene.owner.pivot['progress_at'])
        scene.runtime.owner._local_siege_aim_pitch = -.05
        scene.apply(16.)
        self.assertEqual(16., scene.owner.pivot['progress_at'])
        scene.apply(20.)
        self.assertNotIn('handoff', scene.owner.pivot)
        scene.apply(22.)
        self.assertIsNone(scene.owner.pivot)
        self.assertEqual('native_pivot_stalled', scene.owner._failed_recovery['reason'])
        self.assertFalse(self.desired(scene))
        self.assertEqual(original_rows, scene.policy.rows)
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        scene.runtime.planner._route.assert_not_called()

    def test_actual_siege_preaim_never_steals_reload_trigger_or_armor_search(self):
        for action in ('trigger_active', 'search_penetration', 'reload_clip', 'switch_shell', 'navigate'):
            with self.subTest(action=action):
                scene = Scene(siege=siege_mechanics.ENABLED)
                self.motion(scene)
                scene.decide(action)
                result = scene.apply(0.)
                for name in ('target_id', 'combat_mode', 'move_position',
                             'face_position', 'throttle_override', 'shell_index'):
                    self.assertEqual(scene.raw_order[name], result[name])
                self.assertFalse(result['fire_allowed'])
                self.assertNotEqual(scene.runtime._siege_aim_candidate['solution']['point'],
                                    result['aim_position'])
                self.assertTrue(scene.owner.active)
                self.assertIsNone(scene.owner.pivot)
                self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_hydraulic_motion_cannot_retarget_an_already_resolved_contact(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        other = dict(scene.target, id=3, network_id=3, position=(25., 0., 70.))
        scene.runtime._targets += (other,)
        scene.raw_order['tactical_evidence']['selection']['candidates'].append(
            dict(target=('bot', 3), reason='eligible', score=10.))
        scene.decide('wait', candidate=False)
        self.motion(scene)
        motion = scene.runtime._siege_aim_candidate
        motion['target'] = other
        self.assertEqual(dict(scene.raw_order, aim_position=None, fire_allowed=False), scene.apply(0.))
        self.assertTrue(scene.owner.contains(other))
        self.assertIsNone(scene.owner.pivot)
        self.assertIsNone(scene.runtime.siege_aim_candidate(scene.target))

        # Execute the actual shared actor-bound lane callback; only native
        # I/O is represented by this fixture.
        runtime = scene.runtime
        runtime.engine._actor_controls = {scene.state['id']: runtime}
        runtime.engine._control_factory = None
        runtime.current_attack_candidate = lambda source, target, for_aim=False: (
            FullPlayerRuntime.current_attack_candidate(runtime, source, target, for_aim))
        runtime._siege_fire_ready = lambda: FullPlayerRuntime._siege_fire_ready(runtime)
        runtime.consume_gun_handoff = lambda source, command, target, now: (
            FullPlayerRuntime.consume_gun_handoff(runtime, source, command, target, now))
        scene.policy.select_command = lambda source, command, target, now: (
            AttackPolicy.select_command(scene.policy, source, command, target, now))
        command = dict(scene.raw_order, throttle=.5, turn=.2, brake=False,
                       movement_intent=True, move_position=(4., 0., 8.))
        result, target = _PlayerBehaviorEngine._apply_blocked_direct_aim(
            runtime.engine, scene.state, command, scene.target, 0.)
        self.assertIsNone(target)
        self.assertNotIn('_player_motion_only', result)
        self.assertIsNone(result['aim_position'])
        self.assertFalse(result['fire_allowed'])
        for name in ('throttle', 'turn', 'brake', 'movement_intent',
                     'move_position', 'face_position', 'target_id', 'target_kind'):
            self.assertEqual(command[name], result[name])

        # A current preaim for that same solved contact remains usable, but
        # cannot turn its motion-only source into firing permission either.
        motion['target'] = scene.target
        result, target = _PlayerBehaviorEngine._apply_blocked_direct_aim(
            runtime.engine, scene.state, command, scene.target, .1)
        self.assertIs(scene.target, target)
        self.assertTrue(result['_player_motion_only'])
        self.assertFalse(result['fire_allowed'])
        for name in ('throttle', 'turn', 'brake', 'movement_intent',
                     'move_position', 'face_position', 'target_id', 'target_kind'):
            self.assertEqual(command[name], result[name])


if __name__ == '__main__':
    unittest.main()
