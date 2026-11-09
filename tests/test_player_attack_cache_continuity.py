"""Native cache work is reusable only below exact current-pose admission.

The real snapshot, trajectory, collision and armour resolver run here. The
float32 vector fixture models storage at the native Vector3 boundary, rather
than rounding planning poses or manufacturing an already-passed evaluation.
These counts describe deterministic work, not native-client wall-clock time.
"""
import struct
from types import SimpleNamespace
import unittest
from unittest import mock

import test_player_fire_admission_complete as native_fire
from test_player_rebuilt_attack_policy import Observations
from gui.mods.offline_lan_0922 import combat_rules
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import (
    AttackPolicy, NativeAttackEvaluator)
from gui.mods.offline_lan_0922.vehicle_control import ammunition_validation


class NativeFloatVector(native_fire.f._Vector):
    def __init__(self, *args):
        super().__init__(*args)
        self.x, self.y, self.z = tuple(struct.unpack('f', struct.pack('f', value))[0]
                                     for value in (self.x, self.y, self.z))


class NativeCacheContinuityTests(native_fire.AutomaticFireScene):
    def setUp(self):
        super().setUp()
        self.battle._runtime.math.Vector3 = NativeFloatVector
        self.native_hits = 0
        self.targets = list(self.runtime.visible_targets())
        self.observed_runtime = SimpleNamespace(owner=self.battle, gun=self.runtime.gun,
            geometry=self.runtime.geometry, now=self.now,
            current_source=self.runtime.current_source,
            target_entity=self.runtime.target_entity,
            attack_search_drive_available=self.runtime.attack_search_drive_available,
            combat_targets=lambda: self.targets,
            combat_stop=SimpleNamespace(signature=('admitted', 1)))
        self.evaluator = NativeAttackEvaluator(self.observed_runtime)
        self.policy = AttackPolicy(self.observed_runtime, self.evaluator,
                                   atomic_time_budget=.25)
        for name in ('chassis', 'hull', 'turret', 'gun'):
            getattr(self.target.typeDescriptor, name).hitTester.on_hit = self.count_hit

    def count_hit(self):
        self.native_hits += 1

    def snapshot(self, seconds=.1):
        self.fixture.now += seconds
        self.observed_runtime.now = self.now
        self.policy.frame = self.evaluator.snapshot(self.now)
        return self.policy.frame

    def evaluate_point(self):
        for unused in range(30):
            self.snapshot()
            job = next(job for job in self.policy._jobs(shell_index=0)
                       if job[2]['entity'] is self.target and job[3] == 0)
            row = self.policy._evaluate(job, self.now, 'foreground')
            if row['line'] != 'pending':
                self.assertEqual('clear', row['line'], row)
                self.assertIn(row['armor'], ('passed', 'failed'), row)
                return row
        self.fail('real native frontier did not finish the selected point')

    def harden(self):
        for name in ('chassis', 'hull', 'turret', 'gun'):
            for material in getattr(self.target.typeDescriptor, name).materials.values():
                material.armor = 10000.

    def test_sub_native_ray_jitter_recomputes_proof_without_recurring_collision(self):
        self.harden()
        with mock.patch.object(combat_rules, 'resolve_armor_contact',
                               wraps=combat_rules.resolve_armor_contact) as resolve:
            previous = self.evaluate_point()
            self.assertEqual('failed', previous['armor'])
            calls, batches = self.native_hits, self.evaluator.cache_observations['armour_batches']
            self.assertGreater(calls, 0)
            previous_job = self.evaluator.jobs[previous['key'][:3]]
            distances = [resolve.call_args.args[1]]
            for index in range(1, 9):
                # This value changes the physical/policy source observation.
                # The native collider still receives exactly the same floats.
                self.origin = (0., 2., index * 1.e-9)
                fresh = self.snapshot()
                self.assertNotEqual(previous['pose_stamp'][1], fresh['planning_pose'])
                self.assertIsNone(self.policy.current_row(previous))
                current = self.evaluate_point()
                self.assertEqual('failed', current['armor'])
                current_job = self.evaluator.jobs[current['key'][:3]]
                self.assertIsNot(previous_job, current_job)
                self.assertIsNot(previous, current)
                distances.append(resolve.call_args.args[1])
                previous, previous_job = current, current_job
            self.assertEqual(calls, self.native_hits)
            self.assertEqual(batches, self.evaluator.cache_observations['armour_batches'])
            self.assertEqual(8, self.evaluator.cache_observations['armour_ray_reuses'])
            self.assertEqual(9, resolve.call_count)
            self.assertGreater(len(set(distances)), 1,
                               'range must be resolved again, not reused with the hit list')

    def test_real_source_ray_change_requeries_collision_and_retires_negative(self):
        self.harden()
        old = self.evaluate_point()
        calls = self.native_hits
        self.origin = (5., 2., 0.)
        self.snapshot()
        self.assertIsNone(self.policy.current_row(old))
        current = self.evaluate_point()
        self.assertEqual('failed', current['armor'])
        self.assertGreater(self.native_hits, calls)
        self.assertNotEqual(old['pose_stamp'], current['pose_stamp'])
        self.assertEqual(0, self.evaluator.cache_observations['armour_ray_reuses'])

    def test_native_target_turret_change_requeries_collision(self):
        self.harden()
        old = self.evaluate_point()
        calls = self.native_hits
        self.target.appearance.turretMatrix.setRotateY(.2)
        self.snapshot()
        self.assertIsNone(self.policy.current_row(old))
        current = self.evaluate_point()
        self.assertEqual('failed', current['armor'])
        self.assertGreater(self.native_hits, calls)
        self.assertNotEqual(old['pose_stamp'][2], current['pose_stamp'][2])

    def test_armor_revision_cannot_retain_a_now_false_negative(self):
        self.harden()
        old = self.evaluate_point()
        self.assertEqual('failed', old['armor'])
        calls = self.native_hits
        for name in ('chassis', 'hull', 'turret', 'gun'):
            for material in getattr(self.target.typeDescriptor, name).materials.values():
                material.armor = 10.
        self.battle._records['bot:%s' % self.target.id]['armor_revision'] = 1
        self.snapshot()
        self.assertIsNone(self.policy.current_row(old))
        current = self.evaluate_point()
        self.assertEqual('passed', current['armor'])
        self.assertGreater(self.native_hits, calls)

    def test_admission_churn_reuses_exact_native_job_but_revokes_old_authority(self):
        old = self.evaluate_point()
        frame = self.policy.frame
        cached = self.evaluator.jobs[old['key'][:3]]
        calls = self.native_hits
        for index in range(2, 10):
            self.observed_runtime.combat_stop.signature = ('admitted', index)
            self.assertFalse(self.evaluator.fence(frame))
            self.snapshot()
            self.assertIsNone(self.policy.current_row(old))
            current = self.evaluate_point()
            self.assertEqual('passed', current['armor'])
            self.assertIs(cached, self.evaluator.jobs[current['key'][:3]])
            self.assertTrue(self.evaluator.fence(self.policy.frame))
        self.assertEqual(calls, self.native_hits)

    def test_departed_domain_is_pruned_and_reentry_requires_native_work(self):
        old = self.evaluate_point()
        calls = self.native_hits
        accepted = list(self.targets)
        self.targets[:] = []
        self.snapshot()
        self.assertIsNone(self.policy.current_row(old))
        self.assertFalse(self.evaluator.jobs)
        self.assertFalse(self.evaluator.predictions)
        self.assertFalse(self.evaluator.armour_rays)
        self.targets[:] = accepted
        self.evaluate_point()
        self.assertGreater(self.native_hits, calls)

    def test_new_generation_clears_all_physical_caches(self):
        old = self.evaluate_point()
        calls = self.native_hits
        self.battle._generation += 1
        self.snapshot()
        self.assertIsNone(self.policy.current_row(old))
        self.assertFalse(self.evaluator.jobs)
        self.assertFalse(self.evaluator.predictions)
        self.assertFalse(self.evaluator.armour_rays)
        self.evaluate_point()
        self.assertGreater(self.native_hits, calls)

    def test_real_snapshot_atomic_interval_survives_admission_churn(self):
        self.harden()
        with mock.patch.object(self.evaluator, 'begin_atomic',
                               wraps=self.evaluator.begin_atomic) as begin:
            self.snapshot()
            self.policy.update(self.now, self.policy.frame)
            self.assertEqual(1, begin.call_count)
            start = self.now
            for index in range(1, 10):
                self.observed_runtime.combat_stop.signature = ('admitted', index + 1)
                self.snapshot(.1)
                self.policy.update(self.now, self.policy.frame)
                self.assertEqual(start, self.policy._atomic_at)
                self.assertEqual(1, begin.call_count)
            self.snapshot(1.11)
            self.policy.update(self.now, self.policy.frame)
            self.assertEqual(2, begin.call_count)
            self.battle._generation += 1
            self.snapshot(.01)
            self.policy.update(self.now, self.policy.frame)
            self.assertEqual(3, begin.call_count)

    def test_snapshot_uses_exact_mounted_identities_for_all_five_hesh_pairs(self):
        self.set_he()
        # Expected pairs come from this installed #1513 client, independently
        # of iterating the product whitelist (which could silently gain rows).
        expected = (
            ('_183mm_L4', '_183mm_HESH'),
            ('_183mm_AT_Gun', '_183mm_HESH'),
            ('_105mm_Gun_L7', '_105mm_HESH_L7'),
            ('_105mm_AT_Gun_L7', '_105mm_HESH_L7'),
            ('_5_5inch_AT_Gun', '_5_5inch_HESH_Mk_1'))
        rejected = (
            ('_105mm_Gun_L7', '_105mm_HE_L7'),
            ('_105mm_AT_Gun_L7', '_105mm_HE_L7'),
            ('_183mm_L4', '_183mm_HE_Mk1'),
            ('_183mm_AT_Gun', '_183mm_HE_Mk1'),
            ('_5_5inch_AT_Gun', '_5_5inch_HE_Mk_1T'),
            ('Gun_FV4202', '_105mm_HESH_L7'))
        descriptor = self.entity.typeDescriptor
        descriptor.type.name = 'uk:GB70_FV4202_105'
        for mode, pairs in ((ammunition_validation.FULL, expected),
                            (ammunition_validation.SINGLE_POINT, rejected)):
            for gun_name, shell_name in pairs:
                with self.subTest(gun=gun_name, shell=shell_name):
                    descriptor.gun.name = gun_name
                    self.runtime.gun.shots[0].shell.name = shell_name
                    shell = self.snapshot()['shells'][0]
                    self.assertEqual('uk:' + gun_name, shell['gun_identity'])
                    self.assertEqual('uk:' + shell_name, shell['shell_identity'])
                    self.assertEqual(mode, shell['validation_mode'])
                    self.assertTrue(shell['is_he'])
        descriptor.type.name = 'ussr:R11_MS-1'
        descriptor.gun.name = '_105mm_Gun_L7'
        self.runtime.gun.shots[0].shell.name = 'uk:_105mm_HESH_L7'
        shell = self.snapshot()['shells'][0]
        self.assertIsNone(shell['shell_identity'])
        self.assertEqual(ammunition_validation.SINGLE_POINT, shell['validation_mode'])


class OrdinaryHEContinuityTests(unittest.TestCase):
    def test_next_trigger_retargeting_does_not_repeat_completed_stationary_trials(self):
        scene = Observations(targets=2, points=1, he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(0, 0, 10))
        selected = set()
        for tick in range(8):
            # Current contact damage can change with the shooter/blast scene
            # while both target armour poses remain exactly the same.
            scene.he(50. if tick % 2 == 0 else 100., target=1)
            scene.he(100. if tick % 2 == 0 else 50., target=2)
            scene.prime('he_fallback', 2)
            decision = scene.tick(tick * .2)
            self.assertEqual('aim', decision['action'])
            self.assertEqual('he_fallback', decision['candidate']['mode'])
            self.assertEqual(('bot', 2 if tick % 2 == 0 else 1),
                             decision['candidate']['target_key'])
            self.assertEqual(100., decision['candidate']['expected_damage'])
            selected.add(decision['candidate']['target_key'])
            self.assertIsNone(scene.policy.search_started)
            # A changed ranking cannot take this already-qualified trigger.
            # The next physical commit opens another complete comparison.
            scene.he(100. if tick % 2 == 0 else 50., target=1)
            scene.he(50. if tick % 2 == 0 else 100., target=2)
            scene.prime('he_fallback', 2)
            current = scene.tick(tick * .2 + .05)
            self.assertEqual(('aim', decision['candidate']['key']),
                             (current['action'], current['candidate']['key']))
            scene.policy.shot_committed(dict(burst_index=0, burst_count=1),
                dict(player_control=dict(candidate=current['candidate'])))
            # GunState's completed single-shot/load observation. Real native
            # commits and debits are covered by shared_current_he_execution.
            scene.frame['ammo'] = (0, 0, 9 - tick)
        self.assertEqual({('bot', 1), ('bot', 2)}, selected)
        probes = [call for call in scene.calls if call[2] == 2 and call[-1] == 'penetration']
        self.assertTrue(probes)
        for target in (('bot', 1), ('bot', 2)):
            self.assertLessEqual(sum(call[3] == target for call in probes), 1,
                'fallback intent must not erase a completed same-target trial')

    def test_next_trigger_sample_ranking_does_not_reopen_same_target_trial(self):
        scene = Observations(targets=1, points=3, he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(0, 0, 10))
        samples = set()
        for tick in range(8):
            scene.he(50. if tick % 2 == 0 else 100., sample=1)
            scene.he(100. if tick % 2 == 0 else 50., sample=2)
            scene.prime('he_fallback', 2)
            decision = scene.tick(tick * .2)
            self.assertEqual('aim', decision['action'])
            self.assertEqual('he_fallback', decision['candidate']['mode'])
            self.assertEqual(2 if tick % 2 == 0 else 1, decision['candidate']['sample'])
            self.assertEqual(100., decision['candidate']['expected_damage'])
            samples.add(decision['candidate']['sample'])
            scene.he(100. if tick % 2 == 0 else 50., sample=1)
            scene.he(50. if tick % 2 == 0 else 100., sample=2)
            scene.prime('he_fallback', 2)
            current = scene.tick(tick * .2 + .05)
            self.assertEqual(('aim', decision['candidate']['key']),
                             (current['action'], current['candidate']['key']))
            scene.policy.shot_committed(dict(burst_index=0, burst_count=1),
                dict(player_control=dict(candidate=current['candidate'])))
            scene.frame['ammo'] = (0, 0, 9 - tick)
        self.assertEqual({1, 2}, samples)
        probes = [call for call in scene.calls if call[2] == 2 and call[-1] == 'penetration']
        self.assertEqual(1, len(probes))

    def test_blocked_unknown_alternative_cannot_veto_loaded_he_or_authorize_next(self):
        for blocker in ('world_blocked', 'friendly_blocked'):
            with self.subTest(blocker=blocker):
                scene = Observations(targets=1, points=1, he_validation='single_point')
                scene.frame.update(loaded=2, ammo=(30, 0, 10))
                scene.value(0, armor='unknown', line=blocker)
                scene.he(100.)
                for tick in range(5):
                    decision = scene.tick(tick * .1)
                    self.assertFalse(scene.policy._all_failed((0,)))
                    self.assertTrue(scene.policy.fallback)
                    self.assertEqual('aim', decision['action'])
                    self.assertEqual('he_fallback',
                        (decision.get('candidate') or {}).get('mode'))
                    self.assertEqual(2, decision['candidate']['shell_index'])
                    self.assertIsNone(scene.policy.next_plan)
                # Once that same alternative is actually checked and fails,
                # NEXT may also rank HE. CURRENT never needed that AP failure.
                scene.value(0, armor='failed', line='clear')
                scene.frame['line_revision'] += 1
                for tick in range(5, 10):
                    decision = scene.tick(tick * .1)
                    if decision['action'] == 'aim':
                        break
                self.assertTrue(scene.policy._all_failed((0,)))
                self.assertEqual('aim', decision['action'])
                self.assertEqual('he_fallback', decision['candidate']['mode'])


if __name__ == '__main__':
    unittest.main()
