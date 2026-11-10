"""Finite policy work survives native pose refresh, never firing evidence.

These are deterministic observation/scheduler regressions for report 184606.
The production-shaped pose and simulated query cost are not native Windows
timing evidence; the real evaluator/trigger chain is covered separately.
"""
import unittest

from test_player_rebuilt_attack_policy import Observations
import test_shared_physical_review_coverage as physical_review
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import (
    _planning_pose, ATOMIC_CANDIDATES, ATOMIC_WALL_SECONDS)


def native_pose(scene, revision):
    height = revision * 1.e-8
    position = (0., height, 0.)
    pose = (position, (3.07, -.0197 + height, .0065),
            (0., 1.75 + height, 0.), (-.128, .043), 101, 102, position)
    scene.frame.update(position=position, pose=pose,
                       planning_pose=_planning_pose(pose))


class CurrentHESchedulingTests(unittest.TestCase):
    def scene(self, targets, qualified, completed_hints=False):
        scene = Observations(clips=10, targets=targets, points=9,
                             he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(24, 40, 40))
        native_pose(scene, 0)
        for target in range(1, targets + 1):
            if target in qualified:
                scene.value(2, target=target, armor='failed', line='clear',
                            mechanical='reachable')
            else:
                scene.value(2, target=target, armor='unknown', line='clear',
                            mechanical='hull_laying', reason='yaw_limit')
            scene.value(2, target=target, mode='he_fallback', armor='unknown',
                        line='unknown', mechanical='unknown', contact=None)
        if completed_hints:
            scene.prime('penetration', 2)
            scene.prime('he_fallback', 2)
            policy = scene.policy
            policy._collect_current_he_observations(
                policy._jobs('he_fallback', 2), policy._current_he_observations,
                policy._current_he_deferred)
        scene.he(20., target=qualified[0])
        clock = [0.]
        scene.policy.atomic_clock = lambda: clock[0]

        def cost(channel):
            if channel == 'atomic':
                clock[0] += .001

        scene.on_evaluate = cost
        return scene

    def acquire(self, scene, target):
        for step in range(40):
            native_pose(scene, step + 1)
            decision = scene.tick(step * .1)
            self.assertLessEqual(scene.policy._used['foreground'], 2)
            self.assertLessEqual(scene.policy._used['background'], 2)
            self.assertLessEqual(scene.policy._used['atomic'], ATOMIC_CANDIDATES)
            self.assertEqual(ATOMIC_WALL_SECONDS, scene.policy.atomic_time_budget)
            self.assertIsNone(scene.policy.reload_authority)
            self.assertEqual(2, scene.frame['loaded'])
            if decision['action'] == 'aim':
                break
        self.assertEqual('aim', decision['action'], scene.policy.status())
        candidate = decision['candidate']
        self.assertEqual((2, ('bot', target), 0, 'he_fallback'), candidate['key'])
        self.assertIsNotNone(scene.policy.current_row(candidate, require_line=True))
        self.assertEqual(scene.frame['pose'], candidate['solution']['source_pose'])
        self.assertEqual(20., candidate['expected_damage'])
        self.assertEqual({0}, {call[4] for call in scene.calls if call[2] == 2})
        self.assertFalse(scene.policy._all_failed((0, 1)))
        return candidate

    def test_local_negative_he_attempt_receives_contact_work_before_unknown_enemies(self):
        scene = self.scene(15, (10,))
        first = self.acquire(scene, 10)
        self.assertTrue(any(call[1] in ('foreground', 'atomic') and call[5] == 'he_fallback'
                            for call in scene.calls))
        native_pose(scene, 41)
        current = scene.tick(4.1)
        self.assertEqual(('aim', first['key']),
                         (current['action'], current['candidate']['key']))
        self.assertNotEqual(first['pose_stamp'], current['candidate']['pose_stamp'])
        self.assertGreater(scene.policy.proof_revocations['source'], 0)

    def test_completed_unavailable_comparison_rechecks_new_contact_under_source_drift(self):
        scene = self.scene(14, (5, 12), completed_hints=True)
        self.assertEqual(14, len(scene.policy._current_he_observations))
        self.assertFalse(any(row['damage'] is not None
                             for row in scene.policy._current_he_observations.values()))
        self.acquire(scene, 5)

    def test_completed_higher_damage_hint_is_rechecked_before_a_lower_ready_contact(self):
        scene = self.scene(14, (5, 12), completed_hints=True)
        scene.he(50., target=12)
        scene.prime('he_fallback', 2)
        scene.policy._collect_current_he_observations(
            scene.policy._jobs('he_fallback', 2), scene.policy._current_he_observations,
            scene.policy._current_he_deferred)
        native_pose(scene, 1)
        decision = scene.tick(.1)
        self.assertEqual('aim', decision['action'], scene.policy.status())
        self.assertEqual(('bot', 12), decision['candidate']['target_key'])
        self.assertEqual(50., decision['candidate']['expected_damage'])
        self.assertEqual(scene.frame['pose'], decision['candidate']['solution']['source_pose'])

    def test_pending_old_high_hint_yields_to_a_current_contact_before_global_coverage(self):
        scene = self.scene(15, (5, 10))
        scene.prime('penetration', 2)
        scene.he(200., target=10)
        high = next(job for job in scene.policy._jobs('he_fallback', 2)
                    if job[0][1] == ('bot', 10))
        scene.policy._evaluate(high, 0., 'background')
        scene.policy._collect_current_he_observations(
            (high,), scene.policy._current_he_observations, scene.policy._current_he_deferred)
        for target in range(1, 16):
            if target != 5:
                scene.value(2, target=target, mode='he_fallback', armor='unknown',
                    line='pending', mechanical='unknown', review_pending=True)
        self.acquire(scene, 5)
        self.assertEqual(200., scene.policy._current_he_observations[high[0]]['damage'])
        self.assertGreater(scene.policy.he_comparison['pending'], 0)

    def test_newly_verified_current_he_penetration_precedes_uncommitted_contact(self):
        scene = Observations(targets=3, points=1, he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(0, 0, 30))
        scene.policy.atomic_clock = lambda: 0.
        scene.he(20., target=1)
        scene.he(30., target=2)
        scene.passed(2, target=3)
        decision = scene.tick(0., background=False)
        self.assertEqual('aim', decision['action'])
        self.assertEqual((2, ('bot', 3), 0, 'penetration'), decision['candidate']['key'])
        self.assertIsNone(scene.policy.reload_authority)


class PhysicalInspectionSchedulingTests(unittest.TestCase):
    def test_native_source_micro_motion_preserves_coverage_only(self):
        scene = physical_review.PhysicalReviewCoverageTests.scene(points=9)
        native_pose(scene, 0)
        for step in range(80):
            native_pose(scene, step + 1)
            result = scene.tick(step * .05)
            self.assertLessEqual(scene.policy._used['foreground'], 2)
            self.assertLessEqual(scene.policy._used['background'], 2)
            self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
            if result['action'] == 'firing_position':
                break
        self.assertEqual('firing_position', result['action'], scene.policy.status())
        self.assertGreater(scene.policy.proof_revocations['source'], 0)
        self.assertFalse(scene.policy._all_failed((0,)))
        fresh = [scene.policy._current(job, require_line=True)
                 for job in scene.policy._jobs(shell_index=0)]
        self.assertLess(sum(row is not None for row in fresh), len(fresh))


class RetainedLayIntentionTests(unittest.TestCase):
    def scene(self):
        scene = Observations(targets=2, points=1, he=False)
        native_pose(scene, 0)
        scene.value(0, armor='unknown', line='clear', mechanical='hull_laying')
        scene.policy.frame = scene.snapshot(0.)
        job = scene.policy._jobs(shell_index=0)[0]
        return scene, job

    def test_current_mechanical_point_does_not_require_other_armour_domains(self):
        scene, job = self.scene()
        receipt = scene.policy.retained_lay_candidate(job[0], 0.)
        self.assertEqual(('clear', 'hull_laying'),
                         (receipt['status'], receipt['mechanical']))
        self.assertEqual([('bot', 1)], [call[3] for call in scene.calls])
        self.assertEqual(1, scene.policy._used['foreground'])
        self.assertFalse(scene.policy._executable(receipt['candidate']))
        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])

    def test_source_drift_with_spent_budget_refreshes_geometry_without_reusing_row(self):
        scene, job = self.scene()
        old = scene.policy._evaluate(job, 0., 'foreground')
        native_pose(scene, 1)
        scene.policy.frame = scene.snapshot(.1)
        scene.policy._used['foreground'] = 2
        calls = len(scene.calls)
        refreshed = dict(point=(3., 1., 50.), source_pose=scene.frame['pose'],
                         reachable=False, needs_hull=True)
        scene.refresh_trigger_solution = lambda candidate, now: refreshed
        receipt = scene.policy.retained_lay_candidate(job[0], .1)
        self.assertEqual(('pending', 'hull_laying'),
                         (receipt['status'], receipt['mechanical']))
        self.assertIs(refreshed, receipt['solution'])
        self.assertEqual(('pending', 'unknown'),
            (receipt['candidate']['line'], receipt['candidate']['armor']))
        self.assertEqual(calls, len(scene.calls))
        self.assertIs(old, scene.policy.rows[job[0]])
        self.assertIsNone(scene.policy.current_row(old))
        self.assertFalse(scene.policy._executable(receipt['candidate']))

    def test_current_obstacle_or_pitch_refusal_cannot_be_replayed_as_clear(self):
        for line, mechanical in (('friendly_blocked', 'hull_laying'),
                                 ('clear', 'mechanical_limited')):
            with self.subTest(line=line, mechanical=mechanical):
                scene, job = self.scene()
                scene.value(0, line=line, mechanical=mechanical)
                receipt = scene.policy.retained_lay_candidate(job[0], 0.)
                self.assertEqual('blocked', receipt['status'])
                self.assertFalse(scene.policy._executable(receipt['candidate']))

    def test_pending_without_current_geometry_does_not_return_old_solution(self):
        scene, job = self.scene()
        scene.policy._evaluate(job, 0., 'foreground')
        native_pose(scene, 1)
        scene.policy.frame = scene.snapshot(.1)
        scene.policy._used['foreground'] = 2
        scene.refresh_trigger_solution = lambda candidate, now: None
        receipt = scene.policy.retained_lay_candidate(job[0], .1)
        self.assertEqual('pending', receipt['status'])
        self.assertIsNone(receipt['candidate'])
        self.assertIsNone(receipt['solution'])

    def test_changed_target_or_loaded_shell_retires_the_same_point_intention(self):
        for change in ('target', 'shell'):
            with self.subTest(change=change):
                scene, job = self.scene()
                if change == 'target':
                    scene.policy.frame['targets'] = scene.policy.frame['targets'][1:]
                else:
                    scene.policy.frame['loaded'] = 1
                scene.policy._job_lists = {}
                receipt = scene.policy.retained_lay_candidate(job[0], .1)
                self.assertEqual('invalid', receipt['status'])
                self.assertEqual([], scene.calls)

    def test_current_stationary_turn_is_retained_but_expired_plan_is_not(self):
        scene, job = self.scene()
        solution = dict(point=(8., 1., 100.), needs_hull=True,
                        source_pose=scene.frame['pose'])
        scene.value(0, line='world_blocked', mechanical='hull_laying',
            stationary_plan=dict(status='proved', proof=dict(proved=True),
                armor='passed', line='clear', mechanical='reachable', solution=solution))
        scene.stationary_plan_current = lambda frame, proof: True
        receipt = scene.policy.retained_lay_candidate(job[0], 0.)
        self.assertEqual(('clear', 'hull_laying'),
                         (receipt['status'], receipt['mechanical']))
        self.assertEqual(solution, receipt['solution'])
        self.assertEqual('world_blocked', receipt['candidate']['line'])
        self.assertFalse(scene.policy._executable(receipt['candidate']))
        scene.stationary_plan_current = lambda frame, proof: False
        scene.policy._used['foreground'] = 2
        expired = scene.policy.retained_lay_candidate(job[0], .1)
        self.assertEqual('pending', expired['status'])
        self.assertIsNone(expired['solution'])

    def test_reentrant_pose_change_during_recheck_never_publishes_clear(self):
        scene, job = self.scene()
        scene.on_evaluate = lambda channel: native_pose(scene, 1)
        receipt = scene.policy.retained_lay_candidate(job[0], 0.)
        self.assertEqual('pending', receipt['status'])
        self.assertIsNone(receipt['solution'])

    def test_invalidated_observation_keeps_the_task_pending_without_old_geometry(self):
        scene, job = self.scene()
        scene.policy._evaluate(job, 0., 'foreground')
        scene.policy._frame_invalid = True
        calls = len(scene.calls)
        receipt = scene.policy.retained_lay_candidate(job[0], .1)
        self.assertEqual('pending', receipt['status'])
        self.assertIsNone(receipt['candidate'])
        self.assertIsNone(receipt['solution'])
        self.assertEqual(calls, len(scene.calls))


class NextLoadOrderingTests(unittest.TestCase):
    def test_current_high_penetration_clip_does_not_pin_the_next_load_rank(self):
        for he_passed, expected in ((True, 2), (False, 0)):
            with self.subTest(he_passed=he_passed):
                scene = Observations(clips=6, targets=1, points=9,
                                     he_validation='single_point')
                scene.frame.update(loaded=1, ammo=(30, 30, 30))
                scene.passed(0)
                scene.passed(1)
                if he_passed:
                    scene.passed(2)
                for step in range(20):
                    native_pose(scene, step + 1)
                    decision = scene.tick(step * .1)
                    self.assertEqual(('aim', 1), (decision['action'],
                        decision['candidate']['shell_index']))
                    self.assertEqual((1, 6), (scene.frame['loaded'], scene.frame['clip']))
                    self.assertIsNone(scene.policy.reload_authority)
                    plan, unused_reason = scene.policy.next_at_edge()
                    if plan is not None and plan['shell_index'] == expected:
                        break
                self.assertIsNotNone(plan, scene.policy.status())
                self.assertEqual(expected, plan['shell_index'])
                self.assertLessEqual(scene.policy._used['background'], 2)

    def test_unresolved_higher_rank_is_not_fabricated_as_a_negative_for_next(self):
        scene = Observations(clips=6, targets=2, points=1,
                             he_validation='single_point')
        scene.frame['loaded'] = 1
        scene.passed(1)
        scene.passed(0)
        scene.value(2, target=2, armor='unknown', line='pending', review_pending=True)
        for step in range(20):
            native_pose(scene, step + 1)
            decision = scene.tick(step * .1)
            self.assertEqual('aim', decision['action'])
            self.assertEqual(1, decision['candidate']['shell_index'])
            self.assertIsNone(scene.policy.next_at_edge()[0])
            self.assertIsNone(scene.policy.reload_authority)


if __name__ == '__main__':
    unittest.main()
