"""Active hydraulic aim/finite-TD proofs, never prospective mode admission.

Native observation fixtures feed production policy, source inversion,
stationary collision certificates and hydraulic actuation. These tests do
not establish physical Windows client timing/rendering acceptance.
"""
import math
import unittest
from unittest import mock

from test_player_siege_engagement import SiegeScene
from test_player_stationary_plan import install_plan_observations, NativePlanScene
from gui.mods.offline_lan_0922 import shot_geometry, siege_mechanics
from gui.mods.offline_lan_0922.vehicle_control import siege_planning
from gui.mods.offline_lan_0922.vehicle_control.native_aim import (
    active_hydraulic_pose, hydraulic_body, hydraulic_reach, mechanical_reach)


class ActualHydraulicScene(SiegeScene):
    def configure_plan(self, **kwargs):
        self.configure(**kwargs)
        enabled = self.entity.siegeState
        self.position = (0., 0., 0.)
        self.plan_receipts = []
        install_plan_observations(self)
        self.entity.siegeState = enabled
        self.observe()
        return self

    plan_frame = NativePlanScene.plan_frame
    plan = NativePlanScene.plan

    def evaluated_row(self, sample=0, mode='penetration'):
        policy = self.runtime.attack_policy
        self.observe()
        policy.frame = policy.evaluator.snapshot(self.now)
        job = next(job for job in policy._jobs(mode, self.runtime.gun.shot_index)
                   if job[2]['entity'] is self.target and job[3] == sample)
        return policy._evaluate(job, self.now, 'foreground')


class ActualSiegeAimTests(unittest.TestCase):
    def scene(self, **kwargs):
        scene = ActualHydraulicScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        return scene.configure_plan(**kwargs)

    def test_future_mode_precheck_api_is_removed(self):
        for name in ('SiegePrecheck', 'project_solution', 'PRECHECK_CANDIDATES'):
            self.assertFalse(hasattr(siege_planning, name))

    def test_disabled_mode_never_inspects_targets_or_native_sources(self):
        scene = self.scene(enabled=False)
        frame = scene.runtime.attack_policy.evaluator.snapshot(scene.now)
        with mock.patch.object(scene.battle._runtime, 'get_shot_angles') as angles:
            self.assertIsNone(scene.runtime.siege_aim.candidate(frame, scene.now))
        angles.assert_not_called()
        self.assertEqual('inactive', scene.runtime.siege_aim.status()['status'])

    def test_actual_selected_point_is_motion_only_and_adds_no_world_armour_work(self):
        scene = self.scene(enabled_pitch=(0., 0.), hydraulic_center=1.5)
        row = scene.evaluated_row()
        policy = scene.runtime.attack_policy
        before_rows, before_world = dict(policy.rows), len(scene.world_queries)
        with mock.patch.object(policy.evaluator, 'evaluate', side_effect=AssertionError('second evaluator')):
            result = scene.runtime.siege_aim.candidate(policy.frame, scene.now, row)
        self.assertIsNotNone(result, scene.runtime.siege_aim.status())
        self.assertEqual(before_rows, policy.rows)
        self.assertEqual(before_world, len(scene.world_queries))
        self.assertTrue(result['solution']['needs_hydraulic'])
        self.assertTrue(result['solution']['siege_aim'])
        self.assertFalse(result['solution']['reachable'])
        self.assertFalse(result['solution']['source_verified'])
        self.assertFalse(policy._executable(result))
        self.assertLessEqual(scene.runtime.siege_aim.status()['native_calls'], siege_planning.NATIVE_SOURCE_CALLS)

    def test_matching_flat_input_inverts_exact_native_actuator_contract(self):
        scene = self.scene(enabled_pitch=(0., 0.), hydraulic_center=-1.5)
        row = scene.evaluated_row()
        helper = scene.runtime.siege_aim
        candidate = helper.candidate(scene.runtime.attack_policy.frame, scene.now, row)
        self.assertIsNotNone(candidate, helper.status())
        source = helper.hydraulic_point(candidate, candidate['solution']['point'])
        self.assertIsNotNone(source)
        self.assertTrue(scene.runtime.weapon.preaim(candidate))
        # Exercise the actual native sender and body-pitch consumer.
        scene.runtime._siege_aim_candidate = candidate
        scene.runtime.attack_policy.decision = dict(action='firing_position', candidate=row,
                                                     reason='native_firing_position')
        for unused in range(15):
            scene.actuate_native_source(.1)
        self.assertAlmostEqual(candidate['solution']['hydraulic_pitch'],
                               scene.battle._local_siege_aim_pitch, places=6)
        self.assertFalse(scene.battle._projectile_meta)

    def test_source_is_revoked_on_target_motion_shell_change_or_mode_exit(self):
        for change in ('target', 'shell', 'mode'):
            with self.subTest(change=change):
                scene = self.scene()
                row = scene.evaluated_row()
                helper = scene.runtime.siege_aim
                result = helper.candidate(scene.runtime.attack_policy.frame, scene.now, row)
                self.assertIsNotNone(result, helper.status())
                if change == 'target':
                    scene.pose(scene.target, (2., 12., 100.))
                elif change == 'shell':
                    scene.runtime.gun.shot_index = 1
                else:
                    scene.entity.siegeState = siege_mechanics.DISABLED
                self.assertIsNone(helper.hydraulic_point(result, result['solution']['point']))

    def test_mismatched_raw_policy_observation_cannot_publish_a_motion_source(self):
        scene = self.scene()
        row = scene.evaluated_row()
        row = dict(row, pose_stamp=('forged',))
        helper = scene.runtime.siege_aim
        self.assertIsNone(helper.candidate(scene.runtime.attack_policy.frame, scene.now, row))
        self.assertEqual(0, helper.status()['native_calls'])

    def test_target_change_during_native_inverse_revokes_motion_result(self):
        scene = self.scene()
        row = scene.evaluated_row()
        getter = scene.battle._runtime.get_shot_angles

        def changed(*args):
            result = getter(*args)
            scene.pose(scene.target, (4., 12., 100.))
            return result

        with mock.patch.object(scene.battle._runtime, 'get_shot_angles', changed):
            helper = scene.runtime.siege_aim
            self.assertIsNone(helper.candidate(scene.runtime.attack_policy.frame, scene.now, row))
        self.assertEqual('actual_hydraulic_observation_changed', helper.status()['reason'])

    def test_all_point_certificate_progress_does_not_start_point_by_point_hydraulic_motion(self):
        scene = self.scene()
        row = scene.evaluated_row()
        policy = scene.runtime.attack_policy
        policy.selected = row['key']
        policy.decision = dict(action='wait', reason='stationary_domain_review_pending')
        self.assertIsNone(scene.runtime.siege_aim.candidate(policy.frame, scene.now))

    def test_hydraulic_compose_is_exact_on_rolled_ground_with_nonzero_pivot(self):
        position, flat, correction, center = (1., 2., 3.), (.4, .13, -.17), -.12, 1.5
        mounted, actual = hydraulic_body(position, flat, correction, center)
        local = (.2, .8, 1.3)
        expected = shot_geometry.transform_vehicle_point(
            shot_geometry.transform_vehicle_point(local, (0., center * math.sin(correction),
                center * (1. - math.cos(correction))), 0., correction, 0.), position, *flat)
        observed = shot_geometry.transform_vehicle_point(local, mounted, *actual)
        for left, right in zip(expected, observed):
            self.assertAlmostEqual(left, right, places=10)

    def test_hydraulic_reach_uses_local_composition_not_euler_pitch_addition(self):
        scene = self.scene(enabled_pitch=(0., 0.))
        frame = scene.runtime.attack_policy.evaluator.snapshot(scene.now)
        hydraulic = active_hydraulic_pose(scene.runtime, frame)
        flat, correction = (.3, .1, .2), -.15
        unused, actual = hydraulic_body((0., 0., 0.), flat, correction, 0.)
        direction = shot_geometry.transform_vehicle_vector((0., 0., 1.), *actual)
        result = hydraulic_reach(frame['descriptor'], direction, flat, hydraulic)
        self.assertTrue(result['reachable'], result)
        self.assertAlmostEqual(correction, result['hydraulic_pitch'], places=6)
        capability = mechanical_reach(frame['descriptor'], direction, flat, dict(hydraulic, body=flat))
        self.assertTrue(capability['reachable'], capability)


class ActualHydraulicStationaryTests(unittest.TestCase):
    scene = ActualSiegeAimTests.scene
    # Separate current-mode point projections share the existing stationary
    # frontier/budgets; they are not an additional mode-entry search.
    def test_zero_pitch_hydraulic_samples_close_independently_without_moving_actor(self):
        scene = self.scene(enabled_pitch=(0., 0.), hydraulic_center=1.5)
        original = scene.body.yaw, scene.body.pitch, tuple(scene.body.translation)
        corrections = []
        for sample in (0, 1, 2, 3):
            frame, plan = scene.plan(sample=sample)
            self.assertEqual('proved', plan['status'], plan)
            self.assertFalse(plan['proof']['fire_permission'])
            self.assertIsNotNone(plan['proof']['hydraulic'])
            solution = plan['prediction']['solution']
            self.assertTrue(solution['needs_hydraulic'])
            self.assertFalse(solution['source_verified'])
            corrections.append(solution['hydraulic_pitch'])
            self.assertTrue(scene.planner.current(frame, plan['proof']))
            scene.fixture.now += .11
        self.assertGreater(len(set(round(v, 5) for v in corrections)), 1)
        self.assertEqual(original, (scene.body.yaw, scene.body.pitch, tuple(scene.body.translation)))

    def test_hydraulic_contact_blocked_is_pending_not_armour_failure(self):
        scene = self.scene(enabled_pitch=(0., 0.), hydraulic_center=1.5)
        with mock.patch.object(scene.runtime.geometry, '_turret_motion_is_clear', return_value=False):
            frame, plan = scene.plan()
            row = scene.evaluated_row()
        self.assertEqual('pending', plan['status'])
        self.assertEqual('stationary_hydraulic_sweep_blocked', plan['reason'])
        self.assertEqual('unknown', row['armor'])
        self.assertNotEqual('excluded', row.get('scope'))

    def test_outside_hydraulic_range_stays_explicitly_unreachable(self):
        scene = self.scene(enabled_pitch=(0., 0.))
        scene.pose(scene.target, (0., 80., 100.))
        unused, plan = scene.plan()
        self.assertEqual('pending', plan['status'])
        self.assertEqual('stationary_hydraulic_pitch_unreachable', plan['reason'])

    def test_actual_pitch_change_retires_old_stationary_receipt(self):
        scene = self.scene(enabled_pitch=(0., 0.))
        frame, plan = scene.plan()
        self.assertEqual('proved', plan['status'], plan)
        scene.battle._local_siege_aim_pitch = -.1
        self.assertFalse(scene.planner.current(frame, plan['proof']))

    def test_active_hydraulic_yaw_uses_existing_shortest_arc_and_flat_support(self):
        scene = self.scene(enabled_pitch=(0., 0.), hydraulic_center=-1.5)
        scene.pose(scene.target, (math.sin(.6) * 100., 12., math.cos(.6) * 100.))
        frame, plan = scene.plan()
        self.assertEqual('proved', plan['status'], plan)
        self.assertTrue(plan['proof']['arc'])
        self.assertGreater(plan['prediction']['solution']['hull_yaw'], .5)
        self.assertTrue(plan['prediction']['solution']['needs_hydraulic'])
        self.assertTrue(all(receipt['hydraulic']['native_clear'] for receipt in plan['proof']['arc']))
        self.assertAlmostEqual(0., plan['proof']['source_support']['pitch'])
        self.assertLess(sum(abs(receipt['end_yaw'] - receipt['start_yaw'])
                            for receipt in plan['proof']['arc']), math.pi)

    def test_blocked_shortest_active_arc_never_retries_reverse_long_arc(self):
        scene = self.scene(enabled_pitch=(0., 0.))
        scene.pose(scene.target, (math.sin(.6) * 100., 12., math.cos(.6) * 100.))
        scene.catalog_status = 'hard'
        unused, plan = scene.plan()
        self.assertEqual('pending', plan['status'], plan)
        self.assertEqual('stationary_native_rotation_blocked', plan['reason'])
        self.assertFalse(plan['proved'])
        self.assertTrue(scene.catalog_calls)

    def test_all_known_nonpenetrating_he_points_can_close_then_fallback(self):
        scene = self.scene(enabled_pitch=(0., 0.), clip=3)
        scene.set_he(piercing=0.)
        scene.runtime.gun.ammo[1] = 0
        for name in ('chassis', 'hull', 'turret', 'gun'):
            getattr(scene.target.typeDescriptor, name).materials[0].armor = 10000.
        policy = scene.runtime.attack_policy
        policy.evaluator.atomic_clock = lambda: 0.
        for unused in range(160):
            scene.observe()
            decision = policy.update(scene.now)
            policy.background(scene.now)
            if decision.get('mode') == 'he_fallback' or (
                    decision.get('candidate') or {}).get('mode') == 'he_fallback':
                break
            scene.fixture.now += .11
        else:
            self.fail('actual hydraulic finite domain never closed: %r' % policy.status())
        counts = policy._failure_domain((0,))
        self.assertTrue(counts['all_failed'], counts)
        self.assertGreater(counts['projected_failed'], 0)
        self.assertEqual(0., scene.battle._local_siege_aim_pitch)


if __name__ == '__main__':
    unittest.main()
