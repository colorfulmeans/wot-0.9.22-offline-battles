"""Ordinary engagement ownership over real copied manoeuvre laws.

The fixture supplies native observations and task/path receipts.  Mechanical
and friendly candidate/lifetime decisions execute the copied production laws;
the full-runtime consumer tests separately exercise final native arbitration.
These tests do not claim Windows physics or frame-time acceptance.
"""
import copy
import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import siege_mechanics
from gui.mods.offline_lan_0922.player_control.attack_policy import AttackPolicy
from gui.mods.offline_lan_0922.player_control.engagement_position import (
    EngagementPosition, MECHANICAL_STALL_SECONDS)
from gui.mods.offline_lan_0922.player_control.copied import bot_runtime
from gui.mods.offline_lan_0922.player_control.copied.ai.driver import WAYPOINT_ARRIVAL_RADIUS


class Scene:
    def __init__(self, siege=None):
        self.now = 0.
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
        engine._friendly_repositions = {}
        engine._decision_cache = {}
        engine._gun_yaw_limits = {1: (-.2, .2, True)}
        engine._server_orders = {}
        engine._physics_params_for = lambda actor: dict(rotSpd=1.)
        engine._gun_angle_target_fraction = lambda *args: None
        engine.navigator = SimpleNamespace(bot_states={}, paths={}, grid=SimpleNamespace(_proof_deferred=False))
        self.policy = SimpleNamespace(decision={}, rows={}, search_started=None,
            _executable=AttackPolicy._executable, _planned_evidence=AttackPolicy._planned_evidence,
            _plannable=AttackPolicy._plannable, receipts=[])
        self.policy.navigation_result = self.policy.receipts.append
        self.policy.stationary_review_wait = lambda: AttackPolicy.stationary_review_wait(self.policy)
        self.policy._stationary_review_order = lambda order: AttackPolicy._stationary_review_order(
            self.policy, order)
        self.policy.frame = None
        self.policy.current_row = lambda candidate, require_line=True: (
            candidate if candidate.get('fresh', True) else None)
        self.runtime = SimpleNamespace(engine=engine, state=self.state,
            gun=SimpleNamespace(shot_index=0, clip_size=3, clip=3), actor_id=1,
            owner=SimpleNamespace(_local_siege_aim_pitch=0., _local_siege_pending=None,
                                  _local_siege_braking=None),
            entity=SimpleNamespace(siegeState=siege,
                typeDescriptor=SimpleNamespace(hasSiegeMode=has_siege)), features={'drive', 'fire'},
            _targets=(self.target,), _mission=None, _siege_pending=None,
            _siege_aim_candidate=None, _last_navigation={}, generation=7, now=0.,
            attack_policy=self.policy, _native_hull_laying=None,
            _mission_brakes=lambda: False, _planner_bot=lambda: dict(id=1))
        self.route = (17., 0., 31.)
        self.route_calls = []
        self.runtime.planner = SimpleNamespace(_route=self.original_route,
            _apply_authored_route_order=lambda *args: None)
        self.owner = EngagementPosition(self.runtime)
        self.runtime.firing_position = self.owner
        self.runtime.siege_capable = lambda: has_siege
        self.runtime.siege_aim_candidate = lambda: (self.runtime._siege_aim_candidate
            if self.runtime.entity.siegeState == siege_mechanics.ENABLED and
            not self.owner._mode_switch_pending() else None)
        self.raw_order = dict(id=1, target_id=2, target_kind='bot',
            combat_mode='engage', move_position=(0., 0., 0.),
            face_position=self.target['position'], aim_position=self.target['position'],
            throttle_override=0., fire_range=500., fire_allowed=True, shell_index=0)
        self.owner.remember_task(self.raw_order)
        self.candidate = dict(target=self.target, shell_index=0, mechanical='reachable',
            line='world_blocked', armor='passed', mode='penetration', key=('point', 0),
            solution=dict(point=(0., 1., 80.), yaw=0., mechanical_reason='world_blocked'))
        self.decide('firing_position')

    def original_route(self, bot, now):
        self.route_calls.append((bot, now))
        return 'route-a', 3, self.route, (12., 0., 20.), False

    def decide(self, action, candidate=True):
        self.policy.decision = dict(action=action, reason='observed_point',
                                    candidate=self.candidate if candidate else None)

    def apply(self, now):
        self.now = now
        result = self.owner.apply_order(dict(self.raw_order), now)
        if result is not None:
            self.runtime.engine._server_orders[1] = dict(result)
        return result

    def position(self, point):
        self.state['position'] = tuple(point)
        self.state.update(zip(('x', 'y', 'z'), point))

    def native_mode(self, mode):
        self.state['siege_state'] = self.runtime.entity.siegeState = mode

    def fail(self, now=1.):
        self.apply(0.)
        self.owner._fail('navigation_local_timeout', dict(at=now, reason='timeout'), now)


class OrdinaryOwnershipTests(unittest.TestCase):
    def test_safe_stationary_plan_can_lay_from_an_actual_blocked_muzzle(self):
        scene = Scene()
        planned = dict(status='proved', proof=dict(proved=True), line='clear',
            mechanical='reachable', armor='passed',
            solution=dict(point=(25., 1., 80.), yaw=.7, hull_yaw=.5, needs_hull=True))
        scene.candidate.update(mechanical='hull_laying', armor='unknown',
                               stationary_plan=planned)
        actual = copy.deepcopy(scene.candidate)
        with mock.patch.object(scene.policy, 'current_row', wraps=scene.policy.current_row) as current:
            result = scene.apply(0.)
        current.assert_called_once_with(scene.candidate, require_line=True)
        self.assertEqual('native_lay', result['_player_position_phase'])
        self.assertEqual('copied_combat_hull_aim', scene.owner.receipt['owner'])
        self.assertEqual(scene.state['position'], result['move_position'])
        self.assertEqual(planned['solution']['point'], result['face_position'])
        self.assertAlmostEqual(.5, scene.owner.pivot['best_error'])
        self.assertFalse(scene.owner.pivot['hydraulic'])
        self.assertFalse(result['fire_allowed'])
        self.assertEqual(actual, scene.candidate)
        self.assertFalse(AttackPolicy._executable(scene.candidate))
        self.assertIsNone(scene.policy.search_started)

    def test_stationary_motion_requires_current_proved_loaded_shell_plan(self):
        cases = ('stale', 'pending', 'not_proved', 'blocked', 'armor_failed', 'no_hull', 'other_shell')
        for case in cases:
            with self.subTest(case=case):
                scene = Scene()
                planned = dict(status='proved', proof=dict(proved=True), line='clear',
                    mechanical='reachable', armor='passed',
                    solution=dict(point=(25., 1., 80.), yaw=.7, hull_yaw=.5, needs_hull=True))
                scene.candidate.update(mechanical='hull_laying', armor='unknown',
                                       stationary_plan=planned)
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
                self.assertEqual('mechanical', result['_player_position_phase'])
                self.assertIsNone(scene.owner.pivot)
                self.assertFalse(result['fire_allowed'])

    def test_stationary_he_contact_plan_can_lay_without_claiming_penetration(self):
        scene = Scene()
        scene.candidate.update(mechanical='hull_laying', mode='he_fallback', armor='unknown',
            stationary_plan=dict(status='proved', proof=dict(proved=True), line='clear',
                mechanical='reachable', armor='failed', contact=True, expected_damage=0.,
                solution=dict(point=(25., 1., 80.), yaw=.7, needs_hull=True)))
        result = scene.apply(0.)
        self.assertEqual('native_lay', result['_player_position_phase'])
        self.assertFalse(result['fire_allowed'])
        self.assertFalse(AttackPolicy._executable(scene.candidate, 'he_fallback'))
        self.assertEqual('unknown', scene.candidate['armor'])

    def test_stationary_motion_consumer_requires_the_owner_and_never_admits_fire(self):
        from gui.mods.offline_lan_0922.player_control.full_runtime import FullPlayerRuntime
        scene = Scene()
        scene.runtime._live = lambda: True
        scene.policy.frame = dict(loaded=0)
        scene.candidate.update(mechanical='hull_laying', armor='unknown',
            pose_stamp='fixed-source-pose', line_stamp='current-native-lane',
            stationary_plan=dict(status='proved', proof=dict(proved=True), line='clear',
                mechanical='reachable', armor='passed',
                solution=dict(point=(25., 1., 80.), yaw=.7, hull_yaw=.5, needs_hull=True)))
        actual = copy.deepcopy(scene.candidate)

        def consumer(for_aim):
            return FullPlayerRuntime.current_attack_candidate(
                scene.runtime, scene.state, scene.target, for_aim=for_aim)

        self.assertIsNone(consumer(True))  # no admitted native-lay owner yet
        scene.apply(0.)
        motion = consumer(True)
        self.assertTrue(motion['_player_stationary_motion'])
        self.assertTrue(motion['solution']['_player_motion_only'])
        self.assertEqual((25., 1., 80.), motion['solution']['point'])
        self.assertEqual('world_blocked', motion['line'])
        self.assertEqual('unknown', motion['armor'])
        self.assertEqual('hull_laying', motion['mechanical'])
        self.assertIsNone(consumer(False))
        scene.policy.decision['action'] = 'aim'
        self.assertIsNone(consumer(False))  # an action alone cannot grant fire
        self.assertEqual(actual, scene.candidate)

    def test_stationary_safe_turn_can_repair_actual_pitch_limit_without_promoting_it(self):
        from gui.mods.offline_lan_0922.player_control.full_runtime import FullPlayerRuntime
        scene = Scene()
        scene.runtime._live = lambda: True
        scene.policy.frame = dict(loaded=0)
        scene.candidate.update(mechanical='mechanical_limited', armor='unknown',
            line='clear', pose_stamp='uniform-native-slope', line_stamp='current-lane',
            stationary_plan=dict(status='proved', proof=dict(proved=True), line='clear',
                mechanical='reachable', armor='passed',
                solution=dict(point=(25., 1., 80.), yaw=.7, hull_yaw=.5, needs_hull=True)))
        scene.candidate['solution']['mechanical_reason'] = 'pitch_limit'
        actual = copy.deepcopy(scene.candidate)
        result = scene.apply(0.)
        self.assertEqual('native_lay', result['_player_position_phase'])
        motion = FullPlayerRuntime.current_attack_candidate(
            scene.runtime, scene.state, scene.target, for_aim=True)
        self.assertTrue(motion['_player_stationary_motion'])
        self.assertTrue(motion['solution']['_player_motion_only'])
        self.assertEqual('mechanical_limited', motion['mechanical'])
        self.assertFalse(AttackPolicy._executable(motion))
        self.assertFalse(result['fire_allowed'])
        self.assertEqual(actual, scene.candidate)

    def test_stationary_review_wait_has_no_new_episode_and_fences_late_motion(self):
        scene = Scene()
        scene.policy.frame = dict(loaded=0, position=scene.state['position'])
        scene.policy.decision = dict(action='wait', reason='stationary_domain_review_pending',
                                     candidate=None)
        order = AttackPolicy.apply_order(scene.policy, scene.raw_order, 0.)
        self.assertIsNone(scene.owner.apply_order(order, 0.))
        self.assertEqual(0, scene.owner.sequence)
        with mock.patch.object(bot_runtime.BotRuntime, '_gun_angle_order', side_effect=AssertionError('gun moved')), \
                mock.patch.object(bot_runtime.BotRuntime, '_friendly_reposition_order', side_effect=AssertionError('lane moved')), \
                mock.patch.object(bot_runtime.BotRuntime, '_rear_laying_order', side_effect=AssertionError('rear moved')):
            self.assertIs(order, scene.owner.gun_angle_order(scene.state, order, {}, .5, None))
            self.assertEqual((None, False), scene.owner.friendly_reposition_order(scene.state, {}, .5))
            self.assertIs(order, scene.owner.rear_laying_order(scene.state, order, {}, .5))
        self.assertTrue(scene.state['_rear_motion_blocked'])
        late, target = AttackPolicy.select_command(scene.policy, scene.state,
            dict(order, throttle=1., turn=1.), scene.target, .5)
        self.assertEqual((0., 0., True, False),
                         (late['throttle'], late['turn'], late['brake'], late['fire_allowed']))
        self.assertIsNone(target)
        self.assertIsNone(late['aim_position'])
        self.assertIsNone(scene.policy.search_started)

    def test_stationary_review_suspends_existing_mechanical_clock_without_renewal(self):
        scene = Scene()
        scene.candidate.update(mechanical='mechanical_limited', line='clear')
        order = scene.apply(0.)
        order = scene.owner.gun_angle_order(scene.state, order, {2: scene.target}, 0., lambda *args: False)
        episode = scene.owner.episode
        marker = scene.state['_gun_angle_adjustment']
        scene.policy.frame = dict(loaded=0, position=scene.state['position'])
        scene.policy.decision = dict(action='wait', reason='stationary_domain_review_pending',
                                     candidate=None)
        stopped = AttackPolicy.apply_order(scene.policy, order, .5)
        paused = scene.owner.apply_order(stopped, .5)
        self.assertEqual('stationary_review', paused['_player_position_phase'])
        self.assertIs(episode, scene.owner.episode)
        self.assertIs(marker, scene.state['_gun_angle_adjustment'])
        with mock.patch.object(bot_runtime.BotRuntime, '_gun_angle_order', side_effect=AssertionError('clock advanced')):
            self.assertIs(paused, scene.owner.gun_angle_order(scene.state, paused, {}, 1., None))
        # The original two-second review window now expires. The same reason
        # with firing_position is not a fresh pause or a new manoeuvre clock.
        scene.decide('firing_position')
        scene.policy.decision['reason'] = 'stationary_domain_review_pending'
        resumed = scene.apply(2.)
        self.assertEqual('mechanical', resumed['_player_position_phase'])
        self.assertEqual(0., marker['start'])
        self.assertIs(episode, scene.owner.episode)
        scene.owner.gun_angle_order(scene.state, resumed, {2: scene.target}, 2., lambda *args: False)
        self.assertTrue(scene.owner.suppressed)
        self.assertEqual('bounded_attempt_complete', scene.owner.terminal['reason'])

    def test_stationary_review_retains_native_pivot_age_without_false_handoff(self):
        scene = Scene()
        scene.candidate.update(mechanical='hull_laying', line='clear')
        scene.candidate['solution']['yaw'] = .5
        scene.apply(0.)
        pivot = scene.owner.pivot
        scene.policy.frame = dict(loaded=0, position=scene.state['position'])
        scene.policy.decision = dict(action='wait', reason='stationary_domain_review_pending',
                                     candidate=None)
        stopped = AttackPolicy.apply_order(scene.policy, scene.raw_order, 1.)
        self.assertEqual('stationary_review', scene.owner.apply_order(stopped, 1.)['_player_position_phase'])
        self.assertIs(pivot, scene.owner.pivot)
        self.assertNotIn('handoff', pivot)
        self.assertEqual(0., pivot['progress_at'])
        scene.decide('firing_position')
        self.assertEqual('native_lay', scene.apply(1.5)['_player_position_phase'])
        self.assertIs(pivot, scene.owner.pivot)
        self.assertEqual(0., pivot['progress_at'])

    def test_real_mechanical_law_terminal_hands_back_original_route(self):
        scene = Scene()
        scene.candidate.update(mechanical='mechanical_limited', line='clear')
        probes = []

        def rejected(yaw, distance):
            probes.append((yaw, distance))
            return False

        order = scene.apply(0.)
        self.assertEqual('mechanical', scene.owner.episode['phase'])
        order = scene.owner.gun_angle_order(scene.state, order, {2: scene.target}, 0., rejected)
        self.assertEqual(0., scene.state['_gun_angle_adjustment']['start'])
        self.assertFalse(probes)
        result = scene.owner.gun_angle_order(scene.state, order, {2: scene.target}, 2., rejected)
        self.assertEqual(2, len(probes))
        self.assertEqual('bounded_attempt_complete', scene.owner.terminal['reason'])
        self.assertEqual(scene.route, result['move_position'])
        self.assertEqual('route', result['combat_mode'])
        self.assertIsNone(result['target_id'])
        self.assertIsNone(scene.policy.search_started)
        self.assertEqual(3, scene.runtime.gun.clip)

    def test_target_or_point_change_does_not_restart_native_stall_clock(self):
        scene = Scene()
        scene.candidate.update(mechanical='hull_laying', line='clear')
        scene.candidate['solution']['yaw'] = .7
        self.assertEqual('native_lay', scene.apply(0.)['_player_position_phase'])
        other = dict(scene.target, id=3, network_id=3)
        scene.candidate['target'] = other
        scene.runtime._targets = (scene.target, other)
        scene.candidate['solution']['yaw'] = -.7
        scene.apply(5.)
        self.assertEqual(0., scene.owner.pivot['progress_at'])
        result = scene.apply(MECHANICAL_STALL_SECONDS)
        self.assertEqual('native_pivot_stalled', scene.owner.pivot['handoff']['reason'])
        self.assertEqual('ordinary', result['_player_position_phase'])
        self.assertEqual(scene.target['position'], result['move_position'])
        self.assertIsNone(scene.policy.search_started)

    def test_actual_native_progress_renews_only_the_existing_stall_allowance(self):
        scene = Scene()
        scene.candidate.update(mechanical='hull_laying', line='clear')
        scene.candidate['solution']['yaw'] = .7
        scene.apply(0.)
        scene.state['yaw'] = .2
        scene.apply(5.)
        self.assertEqual(5., scene.owner.pivot['progress_at'])
        scene.apply(7.)
        self.assertNotIn('handoff', scene.owner.pivot)
        scene.apply(11.)
        self.assertIn('handoff', scene.owner.pivot)

    def test_failed_native_pivot_handoff_survives_flickering_proof(self):
        scene = Scene()
        scene.candidate.update(mechanical='hull_laying', line='clear')
        scene.candidate['solution']['yaw'] = .7
        scene.apply(0.)
        scene.decide('wait')
        scene.apply(.1)
        scene.decide('firing_position')
        for index in range(1, 20):
            scene.state['yaw'] = index * .001
            result = scene.apply(index + .2)
            self.assertEqual('ordinary', result['_player_position_phase'])
            self.assertEqual(.1, scene.owner.pivot['handoff']['at'])
        scene.position((WAYPOINT_ARRIVAL_RADIUS - .01, 0., 0.))
        self.assertEqual('ordinary', scene.apply(25.)['_player_position_phase'])
        scene.position((WAYPOINT_ARRIVAL_RADIUS, 0., 0.))
        self.assertEqual('native_lay', scene.apply(26.)['_player_position_phase'])

    def test_pending_navigation_is_not_a_conclusive_position_failure(self):
        scene = Scene()
        scene.apply(0.)
        nav = dict(navigation_status='pending', path_key=('search', 1),
            local_selection=dict(at=20., outcome='no_candidate'),
            local_fallback=dict(attempted=18))
        scene.runtime.engine.navigator.bot_states[1] = nav
        scene.owner.observe(30.)
        self.assertTrue(scene.owner.active)
        self.assertIsNone(scene.owner.terminal)
        nav['navigation_status'] = 'blocked'
        scene.owner.observe(31.)
        self.assertTrue(scene.owner.active)
        scene.runtime.engine.navigator.paths[('search', 1)] = []
        nav['local_fallback']['missing_ground'] = 1
        scene.owner.observe(32.)
        self.assertTrue(scene.owner.active)
        nav['local_fallback']['missing_ground'] = 0
        scene.owner.observe(33.)
        self.assertEqual('navigation_no_firing_route', scene.owner.terminal['reason'])
        self.assertIsNone(scene.policy.search_started)

    def test_real_navigation_timeout_and_stale_receipt_are_distinct(self):
        scene = Scene()
        scene.apply(10.)
        scene.runtime.engine.navigator.bot_states[1] = dict(local_target_events=[
            dict(at=5., reason='timeout', request='old')])
        scene.owner.observe(12.)
        self.assertIsNone(scene.owner.terminal)
        scene.runtime.engine.navigator.bot_states[1]['local_target_events'].append(
            dict(at=13., reason='timeout', request='current'))
        scene.owner.observe(13.)
        self.assertEqual('current', scene.owner.terminal['evidence']['request'])
        self.assertEqual('navigation_local_timeout', scene.owner.terminal['reason'])

    def test_existing_driver_timeout_finishes_its_recovery_before_route_handoff(self):
        scene = Scene()
        driver = dict(recovery_time=0., recovery_count=0, clock=0.)
        scene.runtime.engine.adapter = SimpleNamespace(driver=SimpleNamespace(states={1: driver}))
        scene.apply(0.)
        driver.update(recovery_time=2., clock=8., recovery_trigger=dict(
            at=8., reason='objective_timeout', origin=(0., 0., 0.),
            goal=(0., 0., 80.), clock_basis='driver_elapsed_seconds'))
        scene.owner.observe(9.)
        self.assertTrue(scene.owner.active)
        driver.update(recovery_time=1., clock=9.)
        scene.owner.observe(10.)
        self.assertTrue(scene.owner.active)
        driver.update(recovery_time=0., recovery_count=1, clock=10.)
        scene.owner.observe(11.)
        self.assertEqual('navigation_recovery_stalled', scene.owner.terminal['reason'])
        self.assertEqual('driver_elapsed_seconds', scene.owner.terminal['evidence']['clock_basis'])
        self.assertIsNone(scene.policy.search_started)

    def test_existing_local_stuck_receipt_requires_completed_nonprogressing_recovery(self):
        scene = Scene()
        driver = dict(recovery_time=0., recovery_count=0, clock=0.)
        scene.runtime.engine.adapter = SimpleNamespace(driver=SimpleNamespace(states={1: driver}))
        scene.apply(0.)
        # Count alone is not evidence of a relevant completed recovery.
        driver.update(recovery_count=1, clock=2.)
        scene.owner.observe(2.)
        self.assertTrue(scene.owner.active)
        driver.update(recovery_time=2., clock=3., recovery_trigger=dict(
            at=3., reason='local_stuck', origin=(0., 0., 0.), goal=(0., 0., 80.),
            clock_basis='driver_elapsed_seconds'))
        scene.owner.observe(3.)
        self.assertTrue(scene.owner.active)
        driver.update(recovery_time=.1, clock=4.)
        scene.owner.observe(4.)
        self.assertTrue(scene.owner.active)
        driver.update(recovery_time=0., recovery_count=2, clock=5.)
        scene.owner.observe(5.)
        self.assertEqual('navigation_recovery_stalled', scene.owner.terminal['reason'])
        self.assertEqual('local_stuck', scene.owner.terminal['evidence']['reason'])
        self.assertFalse(scene.owner.terminal['navigation_owned'])
        scene.apply(5.1)
        self.assertTrue(scene.owner.terminal['navigation_owned'])

    def test_local_stuck_with_actual_translation_keeps_original_recovery_authority(self):
        scene = Scene()
        driver = dict(recovery_time=0., recovery_count=0, clock=0.)
        scene.runtime.engine.adapter = SimpleNamespace(driver=SimpleNamespace(states={1: driver}))
        scene.apply(0.)
        driver.update(recovery_time=2., clock=3., recovery_trigger=dict(
            at=3., reason='local_stuck', origin=(0., 0., 0.), goal=(0., 0., 80.)))
        scene.owner.observe(3.)
        scene.position((WAYPOINT_ARRIVAL_RADIUS, 0., 0.))
        driver.update(recovery_time=0., recovery_count=1, clock=5.)
        scene.owner.observe(5.)
        self.assertTrue(scene.owner.active)
        self.assertIsNone(scene.owner.terminal)

    def test_driver_recovery_real_progress_or_preexisting_event_is_not_new_failure(self):
        scene = Scene()
        driver = dict(recovery_time=0., recovery_count=2, clock=12., recovery_trigger=dict(
            at=10., reason='objective_timeout', origin=(0., 0., 0.), goal=(0., 0., 80.)))
        scene.runtime.engine.adapter = SimpleNamespace(driver=SimpleNamespace(states={1: driver}))
        scene.apply(20.)
        scene.owner.observe(21.)
        self.assertIsNone(scene.owner.terminal)
        driver.update(recovery_time=2., clock=24., recovery_trigger=dict(
            at=24., reason='native_translation_timeout', origin=(0., 0., 0.), goal=(0., 0., 80.)))
        scene.owner.observe(25.)
        scene.position((WAYPOINT_ARRIVAL_RADIUS, 0., 0.))
        driver.update(recovery_time=0., recovery_count=3, clock=26.)
        scene.owner.observe(27.)
        self.assertTrue(scene.owner.active)
        self.assertIsNone(scene.owner.terminal)

    def test_actual_friendly_lease_expires_without_remarking_or_ammo_mutation(self):
        scene = Scene()
        scene.candidate['line'] = 'friendly_blocked'
        scene.candidate['blocker'] = dict(blocker_kind='bot', blocker_id=5,
            blocker_team=1, blocker_position=(0., 0., 12.), blocker_radius=2.)
        scene.apply(0.)
        marker = scene.runtime.engine._friendly_repositions[1]
        deadline = marker['deadline']
        first = scene.owner.episode['id']
        for moment in (1., 2., deadline - .01):
            scene.apply(moment)
            self.assertIs(marker, scene.runtime.engine._friendly_repositions[1])
            result, expired = scene.owner.friendly_reposition_order(
                scene.state, {2: scene.target}, moment)
            self.assertFalse(expired)
            self.assertEqual(marker['destination'], result['move_position'])
        scene.apply(deadline)
        result, unused = scene.owner.friendly_reposition_order(scene.state, {2: scene.target}, deadline)
        self.assertEqual('friendly_position_timeout', scene.owner.terminal['reason'])
        self.assertEqual(first, scene.owner.terminal['episode_id'])
        self.assertEqual(scene.route, result['move_position'])
        self.assertNotIn(1, scene.runtime.engine._friendly_repositions)
        self.assertEqual(3, scene.runtime.gun.clip)
        scene.apply(deadline + 20.)
        self.assertNotIn(1, scene.runtime.engine._friendly_repositions)

    def test_target_changed_friendly_leg_keeps_first_real_deadline(self):
        scene = Scene()
        scene.candidate['line'] = 'friendly_blocked'
        scene.candidate['blocker'] = dict(blocker_kind='bot', blocker_id=5,
            blocker_team=1, blocker_position=(0., 0., 12.), blocker_radius=2.)
        scene.apply(0.)
        deadline = scene.runtime.engine._friendly_repositions[1]['deadline']
        scene.target.update(id=3, network_id=3)
        scene.raw_order['target_id'] = 3
        scene.apply(1.)
        scene.owner.friendly_reposition_order(scene.state, {3: scene.target}, 1.)
        self.assertNotIn(1, scene.runtime.engine._friendly_repositions)
        scene.apply(2.)
        self.assertEqual(deadline, scene.runtime.engine._friendly_repositions[1]['deadline'])

    def test_late_original_tactical_owners_cannot_recreate_terminated_attempt(self):
        scene = Scene()
        scene.fail()
        with mock.patch.object(bot_runtime.BotRuntime, '_gun_angle_order', side_effect=AssertionError('late gun owner')), \
                mock.patch.object(bot_runtime.BotRuntime, '_friendly_reposition_order', side_effect=AssertionError('late lane owner')), \
                mock.patch.object(bot_runtime.BotRuntime, '_rear_laying_order', side_effect=AssertionError('late rear owner')):
            self.assertIs(scene.raw_order, scene.owner.gun_angle_order(
                scene.state, scene.raw_order, {2: scene.target}, 2., lambda *args: True))
            self.assertEqual((None, False), scene.owner.friendly_reposition_order(scene.state, {2: scene.target}, 2.))
            scene.state['_rear_aim_episode'] = dict(start=1.)
            self.assertIs(scene.raw_order, scene.owner.rear_laying_order(
                scene.state, scene.raw_order, {2: scene.target}, 2.))
        self.assertNotIn('_rear_aim_episode', scene.state)
        self.assertTrue(scene.state['_rear_motion_blocked'])

    def test_unchanged_domain_does_not_rearm_but_real_translation_does(self):
        scene = Scene()
        scene.fail()
        for now in (2., 10., 30.):
            scene.state['yaw'] += .001
            scene.runtime.owner._local_siege_aim_pitch += .02
            result = scene.apply(now)
            self.assertEqual('route', result['_player_position_phase'])
            self.assertTrue(scene.owner.suppressed)
        scene.position((WAYPOINT_ARRIVAL_RADIUS, 0., 0.))
        result = scene.apply(31.)
        self.assertFalse(scene.owner.suppressed)
        self.assertTrue(scene.owner.active)
        self.assertEqual(2, scene.owner.episode['id'])

    def test_fresh_independent_executable_point_can_end_route_suppression(self):
        scene = Scene()
        scene.fail()
        scene.candidate.update(line='clear', mechanical='reachable', fresh=False)
        scene.decide('aim')
        self.assertEqual('route', scene.apply(2.)['_player_position_phase'])
        scene.candidate['fresh'] = True
        self.assertIsNone(scene.apply(3.))
        self.assertFalse(scene.owner.suppressed)

    def test_world_revision_rearms_stationary_travel_mode_without_actual_aim(self):
        scene = Scene()
        scene.policy.frame = dict(scene=('avatar', 1, 3), lane_missing=(), blockers=(), debris=None)
        scene.fail()
        scene.candidate.update(mechanical='mechanical_limited', line='world_blocked')
        for now in (2., 3., 20.):
            scene.policy.frame['observed_at'] = now
            scene.policy.frame['debris'] = now  # unavailable provider's unknown stamp
            self.assertEqual('route', scene.apply(now)['_player_position_phase'])
        scene.policy.frame['scene'] = ('avatar', 1, 4)  # real demolished-wall revision
        result = scene.apply(21.)
        self.assertFalse(scene.owner.suppressed)
        self.assertTrue(scene.owner.active)
        self.assertEqual('mechanical', result['_player_position_phase'])
        self.assertIsNone(scene.policy.search_started)

    def test_only_related_native_blocker_change_rearms_failed_lane(self):
        scene = Scene()

        def blocker(identity, point):
            matrix = (tuple(point), 0., 0., 0.)
            pose = (identity, 'descriptor', matrix, matrix, matrix, matrix,
                    False, ('hit-testers',), 0, 0)
            return (0, 0, identity, 'bot', identity, True, 1, tuple(point), pose)

        scene.policy.frame = dict(scene=('avatar', 1, 3), lane_missing=(), debris=None,
            blockers=(blocker(5, (0., 0., 20.)), blocker(6, (200., 0., 200.))))
        scene.fail()
        scene.policy.frame['blockers'] = (
            blocker(5, (.001, 0., 20.)), blocker(6, (210., 0., 200.)))
        self.assertEqual('route', scene.apply(2.)['_player_position_phase'])
        scene.policy.frame['blockers'] = (
            blocker(5, (.5, 0., 20.)), blocker(6, (210., 0., 200.)))
        result = scene.apply(3.)
        self.assertFalse(scene.owner.suppressed)
        self.assertEqual('ordinary', result['_player_position_phase'])

    def test_late_guard_preserves_processed_driver_controls_after_handoff(self):
        scene = Scene()
        scene.fail()
        scene.apply(1.5)
        processed = dict(scene.raw_order, throttle=.8, turn=-.2, brake=False,
                         _player_attack_solution=dict(point=(0., 2., 80.)))
        result, target = scene.owner.guard_command(processed, scene.target, 2.)
        self.assertIsNone(target)
        self.assertEqual((.8, -.2, False), (result['throttle'], result['turn'], result['brake']))
        self.assertIsNone(result['target_id'])
        self.assertIsNone(result['aim_position'])
        self.assertNotIn('_player_attack_solution', result)

    def test_new_terminal_after_drive_solve_does_not_reuse_abandoned_controls(self):
        scene = Scene()
        scene.fail()
        processed = dict(scene.raw_order, throttle=.8, turn=-.2, brake=False)
        result, target = scene.owner.guard_command(processed, scene.target, 2.)
        self.assertIsNone(target)
        self.assertEqual((0., 0., True), (result['throttle'], result['turn'], result['brake']))
        self.assertFalse(result['movement_intent'])
        self.assertEqual(scene.route, result['move_position'])
        self.assertEqual('navigation', result['_player_position_owner'])
        self.assertTrue(scene.owner.terminal['navigation_owned'])

    def test_explicit_task_cancels_old_local_episode_not_native_transaction(self):
        scene = Scene()
        scene.apply(0.)
        pending = scene.runtime._siege_pending = dict(enabled=True, sequence=18)
        scene.runtime._mission = dict(id='return-3', explicit=True, destination=(10., 0., 0.))
        scene.owner.remember_task(dict(scene.raw_order, combat_mode='team_return_base'))
        self.assertFalse(scene.owner.active)
        self.assertFalse(scene.owner.suppressed)
        self.assertIs(pending, scene.runtime._siege_pending)
        self.assertIsNone(scene.apply(1.))

    def test_verified_nonordinary_action_is_not_trapped_by_old_position_failure(self):
        for action in ('search_penetration', 'reload_clip', 'switch_shell', 'retreat'):
            with self.subTest(action=action):
                scene = Scene()
                scene.fail()
                scene.decide(action)
                self.assertIsNone(scene.apply(2.))
                self.assertFalse(scene.owner.suppressed)


class SiegeModeOwnershipTests(unittest.TestCase):
    def desired(self, scene, command=None, target=None):
        from gui.mods.offline_lan_0922.player_control.full_runtime import FullPlayerRuntime
        return FullPlayerRuntime.siege_desired(scene.runtime, scene.state,
            scene.raw_order if command is None else command, target)

    def test_selected_visible_contact_enters_without_point_or_penetration_proof(self):
        for clip in (1, 3):
            with self.subTest(clip=clip):
                scene = Scene(siege=siege_mechanics.DISABLED)
                scene.runtime.gun.clip_size = scene.runtime.gun.clip = clip
                scene.decide('wait', candidate=False)
                self.assertEqual({}, scene.policy.rows)
                self.assertIsNone(scene.runtime._siege_aim_candidate)
                self.assertTrue(self.desired(scene))
                result = scene.apply(0.)
                self.assertEqual('siege_transition', result['_player_position_phase'])
                self.assertFalse(result['fire_allowed'])
                self.assertEqual(clip, scene.runtime.gun.clip)
                self.assertIsNone(scene.owner.episode)

    def test_stationary_review_clears_fire_target_but_not_selected_mode_contact(self):
        scene = Scene(siege=siege_mechanics.DISABLED)
        scene.policy.frame = dict(loaded=0, position=scene.state['position'])
        scene.policy.decision = dict(action='wait', candidate=None,
            reason='stationary_domain_review_pending')
        order = AttackPolicy.apply_order(scene.policy, scene.raw_order, 0.)
        command, target = AttackPolicy.select_command(scene.policy, scene.state,
            order, scene.target, 0.)
        self.assertIsNone(command['target_id'])
        self.assertIsNone(target)
        self.assertTrue(self.desired(scene, command, target))
        self.assertEqual('siege_transition', scene.owner.apply_order(command, 0.)[
            '_player_position_phase'])

    def test_mode_does_not_select_an_arbitrary_visible_target(self):
        scene = Scene(siege=siege_mechanics.DISABLED)
        order = dict(scene.raw_order, target_id=None, target_kind=None,
                     combat_mode='route')
        scene.owner.remember_task(order)
        self.assertFalse(self.desired(scene, order))
        # An upstream native loop-selected contact is legitimate; presence
        # in the roster without that selection was not enough.
        self.assertTrue(self.desired(scene, order, scene.target))

    def test_disappearance_and_reappearance_follow_current_visible_selection(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        self.assertTrue(self.desired(scene))
        scene.runtime._targets = ()
        self.assertFalse(self.desired(scene, target=scene.target))
        scene.runtime._targets = (dict(scene.target, visible=False),)
        self.assertFalse(self.desired(scene, target=scene.target))
        scene.runtime._targets = (dict(scene.target, alive=False),)
        self.assertFalse(self.desired(scene, target=scene.target))
        scene.runtime._targets = (scene.target,)
        self.assertTrue(self.desired(scene))

    def test_combat_local_travel_does_not_inherit_strategic_distance_exit(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        for mode in ('engage', 'advance_contact', 'gun_angle_adjust',
                     'friendly_lane_reposition', 'cover_hide', 'cover_hold'):
            with self.subTest(mode=mode):
                order = dict(scene.raw_order, combat_mode=mode, throttle=1.,
                    movement_intent=True, move_position=(0., 0., 120.),
                    control_trace=dict(strategic_move_position=(0., 0., 500.)))
                scene.owner.remember_task(order)
                self.assertFalse(scene.owner.navigation_owns(order))
                self.assertTrue(self.desired(scene, order, scene.target))

    def test_original_attack_radio_without_destination_retains_combat_priority(self):
        from gui.mods.offline_lan_0922.player_control.copied.server_bot_ai import BotPlanner
        scene = Scene(siege=siege_mechanics.DISABLED)
        scene.runtime._mission = dict(id='attack', explicit=True, action='attack')
        order = dict(scene.raw_order, move_position=dict(x=0., y=0., z=40.))
        order = BotPlanner._apply_team_order(order, dict(state=scene.state),
            dict(command='ATTACK', command_id='attack'), (), {},
            route_point=dict(x=0., y=0., z=500.))
        self.assertEqual('team_attack', order['combat_mode'])
        self.assertEqual(2, order['target_id'])
        scene.owner.remember_task(order)
        self.assertFalse(scene.owner.navigation_owns(order))
        self.assertTrue(self.desired(scene, order))

    def test_raw_protected_navigation_survives_rewritten_combat_mode_and_old_contact(self):
        for mode in ('base_defense', 'magazine_reload_retreat', 'withdraw',
                     'under_fire_withdraw', 'crossfire_withdraw', 'team_back_to_base'):
            with self.subTest(mode=mode):
                scene = Scene(siege=siege_mechanics.ENABLED)
                scene.apply(0.)
                self.assertTrue(scene.owner.active)
                raw = dict(scene.raw_order, combat_mode=mode, move_position=(40., 0., 40.),
                           throttle_override=None)
                scene.owner.remember_task(raw)
                overwritten = dict(raw, combat_mode='engage', move_position=(0., 0., 0.),
                                   throttle_override=0.)
                self.assertTrue(scene.owner.navigation_owns(overwritten, task_only=True))
                self.assertFalse(self.desired(scene, overwritten, scene.target))
                self.assertIsNone(scene.owner.apply_order(raw, 1.))
                self.assertFalse(scene.owner.active)
                self.assertIsNone(scene.owner.pivot)

    def test_explicit_destination_owns_travel_but_at_destination_combat_can_enter(self):
        scene = Scene(siege=siege_mechanics.DISABLED)
        scene.runtime._mission = dict(id='go-hold', explicit=True, action='hold_position',
                                      destination=(10., 0., 0.), radius=2.)
        self.assertFalse(self.desired(scene))
        scene.position((9., 0., 0.))
        self.assertTrue(self.desired(scene))

    def test_reload_cover_receipt_not_generic_cover_label_owns_navigation(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        order = dict(scene.raw_order, combat_mode='cover_hide')
        scene.owner.remember_task(order)
        self.assertTrue(self.desired(scene, order))
        scene.policy.decision = dict(action='reload_clip', early_reload=True)
        scene.runtime._reload_retreat = dict(started=1., ready=False)
        self.assertTrue(self.desired(scene, order))  # not yet admitted to a route
        scene.runtime._reload_retreat['navigation_owned'] = True
        self.assertFalse(scene.owner.navigation_owns(order, task_only=True))
        self.assertTrue(scene.owner.navigation_owns(order))
        self.assertFalse(self.desired(scene, order))
        scene.runtime._reload_retreat.update(ready=True, reason='copied_cover_attempt_complete')
        self.assertFalse(self.desired(scene, order))
        scene.policy.decision = dict(action='wait')
        self.assertTrue(self.desired(scene, order))  # old receipt cannot claim a new action
        scene.policy.decision = dict(action='reload_clip', early_reload=True)
        scene.runtime._reload_retreat = dict(ready=True, reason='native_stationary_reload')
        self.assertTrue(self.desired(scene, order))

    def test_native_request_direction_is_atomic_across_contact_and_owner_changes(self):
        scene = Scene(siege=siege_mechanics.DISABLED)
        scene.runtime._siege_pending = dict(enabled=True, sequence=1)
        scene.runtime._targets = ()
        scene.owner.remember_task(dict(scene.raw_order, combat_mode='base_defense'))
        self.assertTrue(self.desired(scene))
        scene.runtime._siege_pending = dict(enabled=False, sequence=2)
        scene.runtime._targets = (scene.target,)
        scene.owner.remember_task(scene.raw_order)
        self.assertFalse(self.desired(scene))
        scene.runtime._siege_pending = None
        scene.native_mode(siege_mechanics.SWITCHING_ON)
        self.assertTrue(self.desired(scene))
        scene.native_mode(siege_mechanics.SWITCHING_OFF)
        self.assertFalse(self.desired(scene))

    def test_auto_drive_only_retains_original_bot_distance_rule(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        scene.runtime.features = {'drive'}
        near = dict(scene.raw_order, movement_intent=True, move_position=(0., 0., 1.))
        self.assertTrue(self.desired(scene, near, scene.target))
        far = dict(near, control_trace=dict(strategic_move_position=(0., 0., 500.)))
        self.assertFalse(self.desired(scene, far, scene.target))


class SiegeOrdinaryLifetimeTests(unittest.TestCase):
    def motion(self, scene, pitch=-.1, yaw=0.):
        scene.runtime._siege_aim_candidate = dict(target=scene.target, mode='penetration',
            mechanical='hydraulic_laying', shell_index=0,
            solution=dict(point=(0., 10., 80.), yaw=yaw, hull_yaw=yaw,
                          siege_correction=pitch, hydraulic_pitch=pitch,
                          needs_hydraulic=True, siege_aim=True,
                          source_verified=False, reachable=False))

    def test_mode_wait_has_no_preview_or_position_clock_then_actual_lay_is_bounded(self):
        scene = Scene(siege=siege_mechanics.DISABLED)
        scene.decide('wait', candidate=False)
        original = copy.deepcopy(scene.policy.rows)
        order = scene.apply(0.)
        self.assertEqual('siege_transition', order['_player_position_phase'])
        self.assertFalse(order['fire_allowed'])
        self.assertIsNone(scene.owner.episode)
        self.assertIsNone(scene.owner.pivot)
        self.assertEqual(0, scene.owner.sequence)
        scene.native_mode(siege_mechanics.SWITCHING_ON)
        scene.apply(1.)
        scene.apply(10.)
        self.assertIsNone(scene.owner.episode)
        self.assertIsNone(scene.owner.pivot)
        scene.native_mode(siege_mechanics.ENABLED)
        self.motion(scene)
        order = scene.apply(11.)
        self.assertEqual('native_lay', order['_player_position_phase'])
        self.assertEqual(11., scene.owner.pivot['progress_at'])
        scene.runtime.owner._local_siege_aim_pitch = -.05
        scene.apply(16.)
        self.assertEqual(16., scene.owner.pivot['progress_at'])
        scene.apply(20.)
        self.assertNotIn('handoff', scene.owner.pivot)
        scene.apply(22.)
        self.assertEqual('native_pivot_stalled', scene.owner.pivot['handoff']['reason'])
        self.assertEqual(original, scene.policy.rows)
        self.assertIsNone(scene.policy.search_started)

    def test_failure_reports_first_route_handoff_owns_exit_and_waits_stable_ack(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        scene.fail()
        self.assertFalse(scene.owner.exit_required)
        self.assertFalse(scene.owner.terminal['navigation_owned'])
        self.assertEqual('handoff', scene.owner.terminal['phase'])
        receipt = scene.owner.navigation_result(dict(action='firing_position'), 1.1)
        self.assertEqual('handoff', receipt['phase'])
        self.assertFalse(scene.owner.terminal['navigation_owned'])
        first = scene.apply(2.)
        self.assertTrue(scene.owner.terminal['navigation_owned'])
        self.assertEqual('navigation', first['_player_position_owner'])
        self.assertTrue(scene.owner.exit_required)
        self.assertEqual('exit', first['_player_position_phase'])
        self.assertEqual((0., 0., 0.), first['move_position'])
        scene.runtime._siege_pending = dict(enabled=False, sequence=4)
        scene.native_mode(siege_mechanics.SWITCHING_OFF)
        self.assertEqual('exit', scene.apply(3.)['_player_position_phase'])
        scene.native_mode(siege_mechanics.DISABLED)
        self.assertEqual('exit', scene.apply(4.)['_player_position_phase'])
        scene.runtime._siege_pending = None
        result = scene.apply(5.)
        self.assertFalse(scene.owner.exit_required)
        self.assertTrue(scene.owner.suppressed)
        self.assertEqual('route', result['_player_position_phase'])
        self.assertEqual(scene.route, result['move_position'])
        self.assertIsNone(scene.policy.search_started)

    def test_native_enable_requires_no_point_and_spends_no_ordinary_timeout(self):
        scene = Scene(siege=siege_mechanics.DISABLED)
        scene.decide('wait', candidate=False)
        scene.apply(0.)
        self.assertIsNone(scene.owner.episode)
        scene.native_mode(siege_mechanics.SWITCHING_ON)
        scene.runtime._siege_pending = dict(enabled=True, sequence=3)
        for now in (1., 3., 7.):
            result = scene.apply(now)
            self.assertEqual('siege_transition', result['_player_position_phase'])
            self.assertIsNone(scene.owner.pivot)
            self.assertIsNone(scene.owner.episode)
            self.assertEqual(0, scene.owner.sequence)
        scene.native_mode(siege_mechanics.ENABLED)
        scene.runtime._siege_pending = None
        # Point evidence now starts against the actual enabled descriptor.
        # No abandoned prospective-pose owner may park it in siege_verify.
        for now in (9., 10., 12.):
            self.assertIsNone(scene.apply(now))
            self.assertIsNone(scene.owner.episode)
            self.assertIsNone(scene.owner.pivot)
        scene.decide('firing_position')
        scene.candidate.update(mechanical='hull_laying', line='clear')
        scene.candidate['solution']['yaw'] = .5
        result = scene.apply(14.)
        self.assertEqual('native_lay', result['_player_position_phase'])
        self.assertEqual(14., scene.owner.pivot['progress_at'])
        self.assertEqual(14., scene.owner.episode['started_at'])
        self.assertEqual(1, scene.owner.sequence)
        self.assertIsNone(scene.policy.search_started)

    def test_new_point_cannot_reverse_an_already_pending_exit(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        scene.fail()
        self.assertEqual('exit', scene.apply(1.1)['_player_position_phase'])
        scene.runtime._siege_pending = dict(enabled=False, sequence=9)
        scene.candidate.update(line='clear', mechanical='reachable')
        scene.decide('aim')
        self.assertEqual('exit', scene.apply(2.)['_player_position_phase'])
        scene.native_mode(siege_mechanics.DISABLED)
        scene.runtime._siege_pending = None
        scene.runtime.owner._local_siege_pending = dict(sequence=9)
        self.assertEqual('exit', scene.apply(3.)['_player_position_phase'])
        scene.runtime.owner._local_siege_pending = None
        result = scene.apply(4.)
        self.assertEqual('siege_transition', result['_player_position_phase'])
        self.assertFalse(result['fire_allowed'])
        self.assertFalse(scene.owner.suppressed)

    def test_fresh_shot_before_mode_request_can_retain_enabled_combat(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        scene.fail()
        scene.candidate.update(line='clear', mechanical='reachable')
        scene.decide('aim')
        self.assertIsNone(scene.apply(2.))
        self.assertFalse(scene.owner.suppressed)
        self.assertFalse(scene.owner.exit_required)
        self.assertEqual(siege_mechanics.ENABLED, scene.state['siege_state'])

    def test_siege_exit_guard_cannot_donate_hull_to_late_combat_pivot(self):
        scene = Scene(siege=siege_mechanics.ENABLED)
        scene.fail()
        command = dict(scene.raw_order, throttle=1., turn=1., brake=False)
        guarded, target = scene.owner.guard_command(command, scene.target, 2.)
        self.assertIsNone(target)
        self.assertEqual((0., 0., True), (guarded['throttle'], guarded['turn'], guarded['brake']))
        self.assertFalse(guarded['movement_intent'])
        self.assertFalse(scene.state['hull_aiming'])

    def test_actual_siege_lay_never_steals_independent_reload_or_armour_search(self):
        for action in ('trigger_active', 'search_penetration', 'reload_clip', 'switch_shell', 'retreat'):
            with self.subTest(action=action):
                scene = Scene(siege=siege_mechanics.ENABLED)
                self.motion(scene)
                scene.decide(action)
                self.assertIsNone(scene.apply(0.))
                self.assertFalse(scene.owner.active)
                self.assertIsNone(scene.policy.search_started)


class EnemyContactHandoffTests(unittest.TestCase):
    def witness(self, **changes):
        result = dict(source='foreground_enemy_translation', enemy_blocking=True,
            peer=2, peer_kind='bot', peer_id=2, team=2, peer_position=(0., 0., 6.),
            fraction=.4, attempted_heading=0., position=(0., 0., 0.), at=0.)
        result.update(changes)
        return result

    def test_only_real_enemy_translation_veto_holds_initial_scan(self):
        scene = Scene()
        scene.decide('wait', candidate=False)
        self.assertFalse(scene.owner.contact(self.witness(source='world_collision')))
        self.assertIsNone(scene.apply(0.))
        for fields in (dict(team=1), dict(enemy_blocking=False), dict(fraction=1.),
                       dict(attempted_heading=None)):
            self.assertFalse(scene.owner.contact(self.witness(**fields)))
        self.assertTrue(scene.owner.contact(self.witness()))
        order = scene.apply(.1)
        self.assertEqual('contact_verify', order['_player_position_phase'])
        self.assertEqual(0., order['throttle_override'])
        scene.decide('firing_position')
        next_order = scene.apply(2.1)
        self.assertEqual('ordinary', next_order['_player_position_phase'])
        self.assertNotEqual((0., 0., 0.), next_order['move_position'])
        self.assertEqual({}, scene.runtime.engine.navigator.bot_states)
        self.assertIsNone(scene.policy.search_started)

    def test_repeat_contact_cannot_reopen_terminal_attempt(self):
        scene = Scene()
        scene.fail()
        self.assertFalse(scene.owner.contact(self.witness(at=2.)))
        scene.decide('wait', candidate=False)
        self.assertEqual('route', scene.apply(2.)['_player_position_phase'])
        self.assertTrue(scene.owner.suppressed)


if __name__ == '__main__':
    unittest.main()
