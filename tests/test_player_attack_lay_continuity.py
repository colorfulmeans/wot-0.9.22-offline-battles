"""Native lay timing belongs to one continuously executed aiming intent.

OwnershipScene supplies real admitted native candidates and the installed gun
source. These boundary tests feed observed phases/angles into the production
lay observer; the timer and its policy recovery consumer are not mocked.
Finite-rate native tracking and real shots are covered by the separate flow
tests. This file does not establish Windows motion or frame timing.
"""
import math
import unittest
from unittest import mock

from test_player_combat_ownership import OwnershipScene


class AttackLayContinuityTests(unittest.TestCase):
    def scene(self, clip=1):
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(clip=clip, burst=1)
        scene.eligible_enemy(5)
        other = scene.eligible_enemy(6)
        scene.pose(other, (35., 0., 40.))
        self.assertEqual({5: True, 6: True}, scene.sample_original_lanes())
        scene.tick()
        runtime = scene.runtime
        self.assertEqual('aim', runtime.attack_policy.decision['action'])
        self.assertIsNotNone(runtime._attack_lay)
        self.assertTrue(runtime.weapon.owned())
        self.assertIsNotNone(runtime.weapon.source_point)
        return scene

    def observe(self, scene, elapsed, intention=None, target=None):
        runtime = scene.runtime
        candidate = runtime.attack_policy.decision.get('candidate')
        target = target or (candidate or {}).get('target')
        intention = intention or runtime.state['_diagnostic_aim_intent']
        runtime._observe_attack_lay(runtime.state, target, intention, 10.1 + elapsed)

    def select(self, scene, identity=5, sample=0, shell=0):
        runtime, policy = scene.runtime, scene.runtime.attack_policy
        runtime.gun.shot_index = shell
        policy.frame = policy.evaluator.snapshot(scene.now)
        job = next(job for job in policy._jobs(shell_index=shell)
                   if job[0][1] == ('bot', identity) and job[3] == sample)
        row = policy._evaluate(job, scene.now, 'foreground')
        self.assertEqual(('reachable', 'clear', 'passed'),
                         (row['mechanical'], row['line'], row['armor']))
        policy._choose('aim', 'current_shell_verified', row)
        intention = dict(runtime.state['_diagnostic_aim_intent'],
                         target_kind='bot', target_id=identity)
        # A supplied native observation keeps the gun short of the new intent.
        runtime.weapon.target = row['target']
        runtime.weapon.point = tuple(row['solution']['point'])
        runtime.weapon.source_point = runtime.weapon.point
        return row, intention

    def test_non_aim_phases_cannot_age_the_next_executed_aim(self):
        for action in ('wait', 'switch_shell', 'preaim', 'firing_position',
                       'trigger_active', 'unchanged'):
            with self.subTest(action=action):
                scene = self.scene()
                runtime, policy = scene.runtime, scene.runtime.attack_policy
                candidate = policy.decision['candidate']
                self.observe(scene, 4.)
                policy._choose(action, 'ordinary_he_alternative_pending')
                self.observe(scene, 5., target=candidate['target'])
                self.assertIsNone(runtime._attack_lay)
                row, intention = self.select(scene, identity=6)
                self.observe(scene, 12., intention)
                self.assertIsNone(policy._lay_recovery)
                self.assertEqual(22.1, runtime._attack_lay['progressed_at'])
                self.assertEqual(row['key'], policy.decision['candidate']['key'])

    def test_new_target_sample_or_loaded_shell_gets_its_own_six_seconds(self):
        for change in (dict(identity=6), dict(sample=1), dict(shell=1)):
            with self.subTest(change=change):
                scene = self.scene()
                self.observe(scene, 5.9)
                unused_row, intention = self.select(scene, **change)
                self.observe(scene, 6.1, intention)
                self.assertIsNone(scene.runtime.attack_policy._lay_recovery)
                self.assertAlmostEqual(16.2, scene.runtime._attack_lay['progressed_at'])

    def test_same_intent_really_stalls_despite_subthreshold_pose_jitter(self):
        scene = self.scene()
        runtime, policy = scene.runtime, scene.runtime.attack_policy
        candidate = policy.decision['candidate']
        point = candidate['solution']['point']
        for tick in range(1, 61):
            jitter = math.sin(tick) * .0001
            runtime.state['position'] = (jitter, 0., jitter)
            candidate['solution']['point'] = (point[0] + jitter, point[1], point[2])
            self.observe(scene, tick / 10.)
            if tick < 60:
                self.assertIsNone(policy._lay_recovery)
        self.assertIsNone(runtime._attack_lay)
        self.assertIs(candidate, policy._lay_recovery[0])

    def test_missing_source_or_non_enemy_intent_ends_the_observation(self):
        for missing in ('source', 'ownership', 'intention', 'candidate'):
            with self.subTest(missing=missing):
                scene = self.scene()
                runtime, policy = scene.runtime, scene.runtime.attack_policy
                candidate = policy.decision['candidate']
                intention = dict(runtime.state['_diagnostic_aim_intent'])
                if missing == 'source':
                    runtime.weapon.source_point = runtime.weapon.motion_point = None
                elif missing == 'ownership':
                    runtime.weapon.close()
                elif missing == 'intention':
                    intention.update(owner='hull_forward_rest', target_id=None)
                else:
                    policy.rows.pop(candidate['key'])
                self.observe(scene, 7., intention, candidate['target'])
                self.assertIsNone(runtime._attack_lay)
                self.assertIsNone(policy._lay_recovery)

    def test_navigation_motion_does_not_age_a_later_stationary_aim(self):
        scene = self.scene()
        runtime, policy = scene.runtime, scene.runtime.attack_policy
        runtime.combat_stop.stop_allowed = False
        runtime._last_order.update(combat_mode='cover_peek', throttle=1., turn=.5)
        self.observe(scene, 5.)
        self.assertIsNone(runtime._attack_lay)
        runtime.combat_stop.stop_allowed = True
        runtime._last_order.update(combat_mode='engage', throttle=0., turn=0.)
        self.observe(scene, 12.)
        self.assertIsNone(policy._lay_recovery)
        self.assertEqual(22.1, runtime._attack_lay['progressed_at'])

    def test_stationary_protected_navigation_does_not_disable_real_gun_stall(self):
        scene = self.scene()
        runtime, policy = scene.runtime, scene.runtime.attack_policy
        runtime.combat_stop.stop_allowed = False
        runtime._last_order.update(combat_mode='base_defense', throttle=0., turn=0.)
        self.assertTrue(runtime.combat_stop.navigation_owns(runtime._last_order))
        self.assertIsNotNone(runtime.current_attack_candidate(
            runtime.state, policy.decision['candidate']['target'], for_aim=True))
        for tick in range(1, 61):
            self.observe(scene, tick / 10.)
        self.assertIsNotNone(policy._lay_recovery)

    def test_existing_angular_translation_and_inverse_progress_renew_timeout(self):
        for progress in ('angle', 'translation', 'inverse'):
            with self.subTest(progress=progress):
                scene = self.scene()
                runtime, policy = scene.runtime, scene.runtime.attack_policy
                if progress == 'inverse':
                    runtime._attack_lay['verified'] = runtime.weapon.verified = False
                self.observe(scene, 4.)
                if progress == 'angle':
                    runtime.state['turret_yaw'] += .1
                elif progress == 'translation':
                    runtime.state['position'] = (.25, 0., 0.)
                else:
                    runtime.weapon.verified = True
                self.observe(scene, 5.)
                self.observe(scene, 6.1)
                self.assertIsNone(policy._lay_recovery)
                self.assertAlmostEqual(15.1, runtime._attack_lay['progressed_at'])
                self.observe(scene, 11.1)
                self.assertIsNotNone(policy._lay_recovery)

    def test_material_point_motion_restarts_but_alignment_finishes_observation(self):
        scene = self.scene()
        runtime, policy = scene.runtime, scene.runtime.attack_policy
        candidate = policy.decision['candidate']
        point = candidate['solution']['point']
        candidate['solution']['point'] = (point[0] + 1., point[1], point[2])
        self.observe(scene, 6.1)
        self.assertIsNone(policy._lay_recovery)
        self.assertAlmostEqual(16.2, runtime._attack_lay['progressed_at'])
        runtime.state['gun_aligned'] = True
        self.observe(scene, 12.2)
        self.assertIsNone(runtime._attack_lay)
        self.assertIsNone(policy._lay_recovery)

    def test_early_reload_uses_original_contact_for_cover_and_retreat(self):
        for cover in (False, True):
            with self.subTest(cover=cover):
                scene = self.scene(clip=6)
                runtime, policy = scene.runtime, scene.runtime.attack_policy
                planner = runtime.planner
                job = next(job for job in policy._jobs(shell_index=1)
                           if job[0][1] == ('bot', 6) and job[3] == 0)
                future = policy._evaluate(job, scene.now, 'foreground')
                policy._choose('reload_clip', 'proven_early_reload', future,
                               early_reload=True, shell_index=1)
                order = dict(scene.original_order())
                self.assertEqual(5, order['target_id'])
                if cover:
                    contact = planner._contacts[runtime.state['team']][('bot', 5)]
                    planner._affordances[runtime.actor_id] = dict(
                        target=('bot', 5), reported_at=scene.now, candidates=[dict(
                            id='native-cover-for-5', position=dict(x=-8., y=0., z=0.),
                            peek_position=dict(x=-3., y=0., z=0.), travel_distance=8.,
                            route_alignment=1., enemy_occlusion=1., exposure=0.,
                            slope=0., water=0., ally_congestion=0.,
                            escape_feasible=True, peek_feasible=True)])
                    planner._cover_candidate(runtime._planner_bot(), contact,
                        planner._personality(runtime.actor_id), scene.now)
                with mock.patch.object(planner, '_apply_cover_order',
                                       wraps=planner._apply_cover_order) as cover_order:
                    result = runtime._reload_order(order, scene.now)
                if cover:
                    self.assertEqual(5, cover_order.call_args[0][2]['id'])
                    self.assertEqual('take_cover', result['combat_mode'])
                    self.assertEqual(('bot', 5), planner._cover_states[runtime.actor_id]['target'])
                else:
                    self.assertEqual('magazine_reload_retreat', result['combat_mode'])
                    self.assertEqual((20., 0., 40.), tuple(
                        result['face_position'][axis] for axis in ('x', 'y', 'z')))
                self.assertEqual(5, result['target_id'])
                self.assertEqual(0, runtime.gun.shot_index)
                self.assertEqual(6, runtime.gun.clip)

    def test_early_reload_without_original_contact_keeps_original_face(self):
        scene = self.scene(clip=6)
        runtime, policy = scene.runtime, scene.runtime.attack_policy
        job = next(job for job in policy._jobs(shell_index=1)
                   if job[0][1] == ('bot', 6) and job[3] == 0)
        future = policy._evaluate(job, scene.now, 'foreground')
        policy._choose('reload_clip', 'proven_early_reload', future,
                       early_reload=True, shell_index=1)
        order = dict(scene.original_order(), target_kind=None, target_id=None,
                     face_position=(7., 0., -8.))
        result = runtime._reload_order(order, scene.now)
        self.assertEqual((7., 0., -8.), tuple(
            result['face_position'][axis] for axis in ('x', 'y', 'z')))
        self.assertIsNone(result['target_id'])


if __name__ == '__main__':
    unittest.main()
