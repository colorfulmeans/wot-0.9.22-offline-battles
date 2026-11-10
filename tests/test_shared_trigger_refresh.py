"""Final physical poses refresh one intention before the real trigger proof.

Native transforms are observation fixtures. Both binding fire entrances,
ballistics, exact armour/HE admission, scatter and ammunition debits are real.
The selected sample is established before motion; no policy row is rewritten
to make its old geometry match a later physical pose.
"""
import contextlib
import io
import math
import unittest
from unittest import mock

import test_player_fire_admission_complete as native
import test_port_0922_actor_binding as actors
from gui.mods.offline_lan_0922 import ballistics, shot_geometry
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import native_source_pose


class FinalPoseTriggerTests(unittest.TestCase):
    def player(self):
        scene = native.AutomaticFireScene('runTest')
        with contextlib.redirect_stdout(io.StringIO()):
            scene.setUp()
        self.addCleanup(scene.doCleanups)
        return scene

    def worker(self):
        fixture = actors.WorkerFirstEdgeAdmissionTests('runTest')
        with contextlib.redirect_stdout(io.StringIO()):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    @staticmethod
    def turn_worker(fixture, angle=-.02):
        # The native turret compensates the body's turn, retaining the same
        # world ray. The policy candidate still owns the pre-turn pose.
        fixture.state['yaw'] += angle
        fixture.state['turret_yaw'] -= angle

    @staticmethod
    def turn_player(scene, angle=-.02):
        scene.body.setRotateYPR((angle, 0., 0.))
        scene.battle._local_yaw = angle
        scene.battle._avatar.gunRotator.turretYaw -= angle

    def test_player_final_hull_turn_refreshes_same_sample_and_commits(self):
        scene = self.player()
        candidate, solution = scene.candidate, scene.candidate['solution']
        self.turn_player(scene)
        self.assertNotEqual(solution['source_pose'], native_source_pose(scene.runtime))
        with contextlib.redirect_stdout(io.StringIO()):
            accepted = scene.fire()
        self.assertTrue(accepted, scene.admission.receipt)
        self.assertEqual([19, 10], scene.runtime.gun.ammo)
        self.assertEqual(1, len(scene.launches()))
        self.assertIs(candidate['solution'], solution)

    def test_worker_final_hull_turn_refreshes_same_sample_and_commits(self):
        fixture = self.worker()
        solution = fixture.candidate['solution']
        self.turn_worker(fixture)
        self.assertNotEqual(solution['source_pose'], fixture.binding.source_pose())
        self.assertTrue(fixture.fire(), fixture.binding._admission().receipt)
        self.assertEqual([19, 10], fixture.binding.gun.ammo)
        self.assertEqual(1, len(fixture.engine._pending_launches))
        self.assertEqual([], fixture.observer_reads)
        self.assertIs(fixture.candidate['solution'], solution)

    def test_translation_and_target_motion_recompute_the_same_intercept(self):
        fixture = self.worker()
        binding, scene = fixture.binding, fixture.scene
        old_solution = fixture.candidate['solution']
        fixture.state.update(x=3., y=0., z=-5., yaw=-.04)
        scene.pose(scene.target, (8., 0., 110.))
        velocity = (2., 0., .5)
        scene.battle._records['bot:42']['state']['velocity'] = velocity
        observed = dict(fixture.target, velocity=velocity, position=(8., 0., 110.))
        binding.observe(scene.now, [observed])
        sample = shot_geometry.ordered_vehicle_aim_samples(scene.target.typeDescriptor)[
            fixture.candidate['sample']]
        sample_point = shot_geometry.vehicle_aim_point(sample,
            dict(position=tuple(scene.target.position)))
        shot = binding.gun.shots[binding.gun.shot_index]
        origin = (3., 2., -5.)
        point, pitch, flight = ballistics.ballistic_intercept(
            origin, sample_point, velocity, shot.speed, shot.gravity)
        yaw = math.atan2(point[0] - origin[0], point[2] - origin[2])
        fixture.state.update(aim_yaw=yaw, turret_yaw=yaw-fixture.state['yaw'],
                             gun_pitch=pitch)
        context = binding.prepare_trigger_context(fixture.state, observed,
                                                   binding.weapon.solution)
        self.assertIsNotNone(context)
        solution = context['solution']
        self.assertEqual(tuple(point), solution['point'])
        self.assertEqual(origin, solution['origin'])
        self.assertEqual(velocity, solution['velocity'])
        self.assertEqual(flight, solution['flight_time'])
        self.assertEqual(binding.source_pose(), solution['source_pose'])
        self.assertNotEqual(old_solution['point'], solution['point'])
        self.assertNotEqual(old_solution['target_pose'], solution['target_pose'])
        self.assertIs(context['candidate'], fixture.candidate)
        self.assertTrue(fixture.fire(), binding._admission().receipt)
        self.assertEqual([19, 10], binding.gun.ammo)

    def test_changed_armour_is_reproved_instead_of_relabeling_old_success(self):
        fixture = self.worker()
        self.turn_worker(fixture)
        self.assertEqual('passed', fixture.candidate['armor'])
        for name in ('chassis', 'hull', 'turret', 'gun'):
            component = getattr(fixture.scene.target.typeDescriptor, name)
            for material in component.materials.values():
                material.armor = 5000.
        fixture.battle._records['bot:42']['armor_revision'] = 1
        self.assertFalse(fixture.fire())
        self.assertEqual('auto_actual_barrel_armour', fixture.binding._last_fire_failure)
        self.assertEqual([20, 10], fixture.binding.gun.ammo)
        self.assertFalse(fixture.engine._pending_launches)
        self.assertFalse(fixture.engine._burst_states[11].active)

    def test_refresh_cannot_make_an_unlaid_native_barrel_fire(self):
        fixture = self.worker()
        # This time the turret has not compensated the body's movement.
        # The old readiness bit cannot replace the actual barrel proof.
        fixture.state['yaw'] += .15
        self.assertTrue(fixture.state['gun_aligned'])
        self.assertFalse(fixture.fire())
        self.assertEqual('auto_gun_laying', fixture.binding._last_fire_failure)
        self.assertEqual([20, 10], fixture.binding.gun.ammo)
        self.assertFalse(fixture.engine._pending_launches)

    def test_worker_native_begin_reentry_still_revokes_refreshed_proof(self):
        fixture = self.worker()
        self.turn_worker(fixture)
        begin = fixture.binding.gun.native.begin_burst
        calls = []
        def move_after_begin(count, factor):
            calls.append((count, factor))
            accepted = begin(count, factor)
            fixture.state['x'] += .25
            return accepted
        with mock.patch.object(fixture.binding.gun.native, 'begin_burst', move_after_begin):
            self.assertFalse(fixture.fire())
        self.assertEqual(1, len(calls))
        self.assertEqual([20, 10], fixture.binding.gun.ammo)
        self.assertFalse(fixture.engine._pending_launches)
        self.assertFalse(fixture.engine._control_launch_proofs)
        self.assertFalse(fixture.engine._burst_states[11].active)

    def test_player_preinstall_reentry_still_revokes_refreshed_proof(self):
        scene = self.player()
        self.turn_player(scene)
        install = scene.battle._preinstall_player_projectile
        calls = []
        def move_after_install(*args):
            calls.append(True)
            value = install(*args)
            scene.body.setRotateYPR((-.02, -.1, 0.))
            return value
        with mock.patch.object(scene.battle, '_preinstall_player_projectile', move_after_install):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(scene.fire())
        self.assertEqual(1, len(calls))
        self.assertEqual('auto_source_pose_changed', scene.control.last_fire_failure)
        scene.assert_unspent()

    def test_refresh_has_one_prediction_and_preserves_policy_frontiers(self):
        fixture = self.worker()
        binding = fixture.binding
        policy, candidate = binding.attack_policy, fixture.candidate
        evaluator = policy.evaluator
        self.turn_worker(fixture, -1.e-12)
        before = (policy.selected, policy._move_episode, policy._physical_review,
                  policy.background_cursor, policy.next_shell, policy.next_plan,
                  policy.loading_plan, policy.frame)
        world_before = len(fixture.scene.world_queries)
        with mock.patch.object(policy, 'update', side_effect=AssertionError('reranked')), \
                mock.patch.object(policy, 'background', side_effect=AssertionError('rescanned')), \
                mock.patch.object(evaluator, 'evaluate', side_effect=AssertionError('extra proof')), \
                mock.patch.object(evaluator, '_prediction', wraps=evaluator._prediction) as predict:
            context = binding.prepare_trigger_context(fixture.state, fixture.target,
                                                       binding.weapon.solution)
        self.assertIsNotNone(context)
        self.assertEqual(binding.source_pose(), context['solution']['source_pose'])
        self.assertEqual(1, predict.call_count)
        self.assertEqual(before, (policy.selected, policy._move_episode,
            policy._physical_review, policy.background_cursor, policy.next_shell,
            policy.next_plan, policy.loading_plan, policy.frame))
        self.assertIs(context['candidate'], candidate)
        self.assertEqual(world_before, len(fixture.scene.world_queries))
        self.assertEqual(dict(predictions=1, world_chords=0, armour_batches=0),
                         evaluator.trigger_refresh_receipt['work'])

    def test_same_slice_refresh_preserves_measured_target_velocity(self):
        fixture = self.worker()
        binding, scene = fixture.binding, fixture.scene
        evaluator = binding.attack_policy.evaluator
        evaluator.snapshot(scene.now)
        scene.fixture.now += .1
        scene.pose(scene.target, (.3, 0., 100.))
        binding.observe(scene.now, [fixture.target])
        frame = evaluator.snapshot(scene.now)
        expected = frame['targets'][0]['velocity']
        self.assertGreater(expected[0], 2.9)
        observed = dict(evaluator.observations)
        context = binding.prepare_trigger_context(fixture.state, fixture.target,
                                                   binding.weapon.solution)
        self.assertIsNotNone(context)
        self.assertEqual(expected, context['solution']['velocity'])
        self.assertEqual(observed, evaluator.observations)

    def test_native_reentry_during_refresh_cannot_relabel_a_changed_source(self):
        fixture = self.worker()
        self.turn_worker(fixture)
        evaluator = fixture.binding.attack_policy.evaluator
        prediction = evaluator._prediction
        def move_during_prediction(*args):
            value = prediction(*args)
            fixture.state['x'] += .25
            return value
        with mock.patch.object(evaluator, '_prediction', move_during_prediction):
            context = fixture.binding.prepare_trigger_context(
                fixture.state, fixture.target, fixture.binding.weapon.solution)
        self.assertIsNone(context)
        self.assertEqual('observation_changed', evaluator.trigger_refresh_receipt['reason'])
        self.assertEqual([20, 10], fixture.binding.gun.ammo)
        self.assertFalse(fixture.engine._pending_launches)


if __name__ == '__main__':
    unittest.main()
