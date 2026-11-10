"""Immediate fallback keeps ammunition proof separate from geometric recovery.

The observations are finite plate/line facts, never substituted policy
decisions. These regressions intentionally fail the pre-change search policy.
"""
import contextlib
import io
import unittest
from unittest.mock import patch

from test_player_rebuilt_attack_policy import Observations
import test_player_fire_admission_complete as native_fire
from gui.mods.offline_lan_0922 import battle_runtime


class ImmediateHEPolicyTests(unittest.TestCase):
    def test_complete_negative_domain_uses_he_without_navigation_or_elapsed_time(self):
        for clips in (1, 6):
            for validation in ('single_point', 'full'):
                with self.subTest(clips=clips, validation=validation):
                    scene = Observations(clips=clips, targets=1, points=3,
                                         he_validation=validation)
                    scene.frame['search_drive'] = False
                    scene.he(25.)
                    scene.prime()
                    scene.prime('he_fallback')
                    decision = scene.tick(0., background=False, navigation=None)
                    self.assertEqual('reload_clip' if clips > 1 else 'switch_shell',
                                     decision['action'], decision)
                    self.assertEqual(2, decision['shell_index'])
                    self.assertEqual('he_fallback', decision['candidate']['mode'])
                    self.assertNotIn('move_request', decision)
                    self.assertFalse(hasattr(scene.policy, 'search_started'))
                    self.assertFalse(hasattr(scene.policy, 'search_authority'))
                    self.assertEqual((clips, (30, 30, 30)),
                                     (scene.frame['clip'], scene.frame['ammo']))

    def test_complete_negative_domain_without_he_exits_immediately(self):
        scene = Observations(targets=1, points=2, he=False)
        scene.prime()
        decision = scene.tick(0., background=False, navigation=None)
        self.assertEqual(('navigate', 'no_he_or_verified_penetration'),
                         (decision['action'], decision['reason']))
        self.assertNotIn('move_request', decision)

    def test_unknown_or_blocked_alternative_cannot_become_negative_certificate(self):
        for line, armor in (('pending', 'unknown'), ('unknown', 'unknown'),
                            ('world_blocked', 'failed'), ('clear', 'unknown')):
            with self.subTest(line=line, armor=armor):
                scene = Observations(targets=1, points=2,
                                     he_validation='single_point')
                scene.value(1, sample=1, line=line, armor=armor)
                scene.he(30.)
                scene.prime()
                scene.prime('he_fallback')
                decision = scene.tick(0., background=False)
                self.assertNotIn(decision['action'], ('switch_shell', 'reload_clip', 'aim'))
                self.assertFalse(scene.policy.fallback)
                self.assertFalse(scene.policy._fallback_qualified((0, 1, 2)))

    def test_known_stationary_exclusion_does_not_manufacture_empty_negative_domain(self):
        scene = Observations(targets=1, points=1, he_validation='single_point')
        for index in (0, 1):
            scene.value(index, line='unknown', armor='unknown',
                        mechanical='mechanical_limited', scope='excluded',
                        scope_proof=dict(scope='excluded'))
        scene.he(30.)
        scene.prime()
        scene.prime('he_fallback')
        decision = scene.tick(0., background=False)
        self.assertFalse(scene.policy._fallback_qualified((0, 1, 2)))
        self.assertFalse(scene.policy.fallback)
        self.assertNotIn(decision['action'], ('switch_shell', 'reload_clip', 'aim'))

    def test_ordinary_he_has_one_same_point_for_penetration_and_fallback_per_enemy(self):
        scene = Observations(targets=2, points=9, he_validation='single_point')
        scene.policy.selected = (2, ('bot', 1), 4, 'penetration')
        scene.policy.frame = scene.snapshot(0.)
        penetration = scene.policy._jobs('penetration', 2)
        fallback = scene.policy._jobs('he_fallback', 2)
        expected = [(('bot', 1), 4), (('bot', 2), 0)]
        self.assertEqual(expected, [(job[0][1], job[3]) for job in penetration])
        self.assertEqual(expected, [(job[0][1], job[3]) for job in fallback])
        for job in penetration:
            scene.policy._evaluate(job, 0., 'foreground')
        self.assertEqual((), scene.policy._jobs('penetration', 2))
        self.assertEqual(expected, [(job[0][1], job[3])
                                   for job in scene.policy._jobs('he_fallback', 2)])

    def test_whitelisted_he_keeps_the_full_point_domain_in_both_modes(self):
        scene = Observations(targets=2, points=9, he_validation='full')
        scene.policy.frame = scene.snapshot(0.)
        for mode in ('penetration', 'he_fallback'):
            jobs = scene.policy._jobs(mode, 2)
            self.assertEqual(18, len(jobs))
            self.assertEqual(set(range(9)), {job[3] for job in jobs})

    def test_current_ordinary_he_uses_one_point_and_is_not_replaced_by_next_ap(self):
        for clips in (1, 6):
            with self.subTest(clips=clips):
                scene = Observations(clips=clips, targets=2, points=9,
                                     he_validation='single_point')
                scene.frame['loaded'] = 2
                scene.policy.atomic_time_budget = 0.
                scene.passed(0)
                scene.he(20., target=1)
                scene.he(40., target=2)
                scene.he(2000., target=1, sample=8)
                scene.prime()
                aimed = None
                for step in range(6):
                    decision = scene.tick(step * .1)
                    self.assertNotIn(decision['action'], ('switch_shell', 'reload_clip'))
                    if decision['action'] == 'aim':
                        aimed = decision
                        break
                self.assertIsNotNone(aimed, scene.policy.status())
                candidate = aimed['candidate']
                self.assertEqual((2, ('bot', 2), 0, 40.),
                    (candidate['shell_index'], candidate['target_key'],
                     candidate['sample'], candidate['expected_damage']))
                self.assertEqual(0, scene.policy.next_shell)
                self.assertTrue(all(call[4] == 0 for call in scene.calls if call[2] == 2))
                self.assertEqual(2, scene.policy.he_comparison['total'])

    def test_current_ordinary_he_uses_qualified_penetration_immediately(self):
        scene = Observations(targets=2, points=9, he_validation='single_point')
        scene.frame['loaded'] = 2
        scene.passed(2)
        decision = scene.tick(0., background=False)
        self.assertEqual(('aim', 2, 'penetration', 0),
            (decision['action'], decision['candidate']['shell_index'],
             decision['candidate']['mode'], decision['candidate']['sample']))
        self.assertEqual(1, len(scene.calls))

    def test_complete_blocked_he_comparison_does_not_restart_before_geometry_handoff(self):
        scene = Observations(targets=6, points=1, he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(0, 0, 30))
        scene.policy.atomic_time_budget = 0.
        for target in range(1, 7):
            scene.value(2, target=target, mode='he_fallback', armor='unknown',
                        line='world_blocked')
        scene.prime()
        scene.prime('he_fallback')
        # A finite completed comparison is a coverage record, not a positive
        # shot, zero-damage measurement, or a negative armour certificate.
        jobs = scene.policy._jobs('he_fallback', 2)
        scene.policy._collect_current_he_observations(
            jobs, scene.policy._current_he_observations,
            scene.policy._current_he_deferred)
        scene.frame['pose'] = ('source', 1)
        before = len(scene.calls)
        decision = scene.tick(.1, background=False)
        self.assertEqual('firing_position', decision['action'], decision)
        self.assertEqual((6, 6, 0), tuple(scene.policy.he_comparison[name]
                         for name in ('total', 'observed', 'pending')))
        self.assertLessEqual(len(scene.calls) - before, 2)
        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
        self.assertFalse(scene.policy._all_failed((2,)))
        candidate = decision['candidate']
        self.assertEqual(('source', 1), candidate['pose_stamp'][1])
        self.assertEqual('world_blocked', candidate['line'])
        self.assertTrue(all(row['damage'] is None
                            for row in scene.policy._current_he_observations.values()))

    def test_pending_he_queries_are_not_completed_coverage_or_failure(self):
        scene = Observations(targets=2, points=1, he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(0, 0, 30))
        scene.policy.atomic_time_budget = 0.
        for target in (1, 2):
            scene.value(2, target=target, mode='he_fallback', armor='unknown',
                        line='pending', review_pending=True)
        scene.prime()
        for step in range(4):
            decision = scene.tick(step * .1, background=False)
            self.assertNotIn(decision['action'], ('aim', 'navigate', 'firing_position'))
            self.assertEqual(0, scene.policy.he_comparison['observed'])
            self.assertFalse(scene.policy._current_he_observations)
            self.assertFalse(scene.policy.apply_order({})['fire_allowed'])

    def test_unknown_he_does_not_turn_elapsed_time_into_a_contact_failure(self):
        scene = Observations(targets=1, points=1, he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(0, 0, 30))
        scene.value(2, mode='he_fallback', armor='unknown', line='unknown')
        scene.prime()
        for now in (0., 1., 8., 40.):
            decision = scene.tick(now, background=False)
            self.assertNotIn(decision['action'], ('aim', 'navigate', 'firing_position'))
            self.assertFalse(scene.policy.apply_order({})['fire_allowed'])

    def test_geometry_request_is_bound_to_the_exact_shell_target_point_and_mode(self):
        scene = Observations(targets=1, points=1)
        scene.value(0, armor='passed', line='world_blocked')
        decision = scene.tick(0., background=False)
        self.assertEqual('firing_position', decision['action'])
        candidate, request = decision['candidate'], decision['move_request']
        self.assertEqual(candidate['key'], request['key'])
        self.assertEqual(candidate['shell_index'], request['shell_index'])
        self.assertEqual(candidate['mode'], request['mode'])
        self.assertEqual(candidate['sample'], request['sample'])
        self.assertNotIn('deadline', request)

    def test_explicit_complete_no_contact_exits_but_none_remains_unknown(self):
        for contact, expected_action in ((False, 'navigate'), (None, 'wait')):
            with self.subTest(contact=contact):
                scene = Observations(targets=1, points=1, he_validation='single_point')
                scene.frame.update(loaded=2, ammo=(0, 0, 30))
                scene.value(2, mode='he_fallback', contact=contact)
                scene.prime()
                scene.prime('he_fallback')
                decision = scene.tick(0., background=False)
                self.assertEqual(expected_action, decision['action'], decision)
                self.assertFalse(scene.policy.apply_order({})['fire_allowed'])


class NativeHECompletionTests(native_fire.AutomaticFireScene):
    def setUp(self):
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)
        super().setUp()

    def contact(self, receipt, impact=(1000., 1000., 1000.)):
        self.set_he(piercing=1.)
        record = next(row for row in self.battle._records.values()
                      if row.get('engine_id') == self.target.id)
        return self.battle._projectile_he_blast_contact(
            {}, record, self.target, self.battle._gun_state.shots[0], impact,
            60., receipt=receipt)

    def test_native_complete_scan_separates_no_contact_from_missing_geometry(self):
        receipt = {}
        self.assertIsNone(self.contact(receipt))
        self.assertEqual('complete_no_contact', receipt['status'])
        self.assertTrue(receipt['complete'])
        self.target.typeDescriptor.hull.hitTester = None
        receipt = {}
        self.assertIsNone(self.contact(receipt))
        self.assertEqual('incomplete', receipt['status'])
        self.assertFalse(receipt['complete'])

    def test_native_failed_surface_query_cannot_publish_no_contact(self):
        receipt = {}
        with patch.object(battle_runtime, 'collide_vehicle_at_matrix',
                          side_effect=RuntimeError('native query unavailable')):
            self.assertIsNone(self.contact(receipt, impact=(0., .5, 100.)))
        self.assertFalse(receipt['complete'], receipt)
        self.assertEqual('incomplete', receipt['status'])

    def test_native_evaluator_records_completed_no_contact_but_preserves_unknown(self):
        self.set_he(piercing=1.)
        for name in ('chassis', 'hull', 'turret', 'gun'):
            for material in getattr(self.target.typeDescriptor, name).materials.values():
                material.armor = 10000.
        evaluator = self.runtime.attack_policy.evaluator
        frame = evaluator.snapshot(self.now)
        shell, target = frame['shells'][0], frame['targets'][0]
        predicted = evaluator._prediction(frame, shell, target, target['samples'][0])
        geometry = evaluator._armour_geometry(frame, shell, target,
            predicted['sample_point'], predicted['direction'], predicted['flight'])
        self.assertIsNotNone(geometry)
        # A fully observed occluding wall is a known failed blast contact.
        self.battle._projectile_he_world_visible = lambda *args, **kwargs: False
        failed = evaluator._he_damage(shell, target, geometry)
        self.assertIs(failed['contact'], False)
        self.assertIsNone(failed['expected_damage'])
        # Native occlusion failure is unknown, never the same terminal fact.
        def unavailable(*args, **kwargs):
            raise RuntimeError('native occlusion unavailable')
        self.battle._projectile_he_world_visible = unavailable
        unknown = evaluator._he_damage(shell, target, geometry)
        self.assertIsNone(unknown['contact'])
        self.assertIsNone(unknown['expected_damage'])

    def test_geometry_recovery_reuses_half_the_existing_foreground_world_budget(self):
        evaluator = self.runtime.attack_policy.evaluator
        self.runtime.combat_stop.physical_recovery_active = lambda: True
        evaluator.snapshot(self.now + .1)
        self.assertEqual((6, 6, 12), tuple(evaluator._budgets[name]
                         for name in ('foreground', 'recovery', 'background')))
        self.runtime.combat_stop.physical_recovery_active = lambda: False
        evaluator.snapshot(self.now + .2)
        self.assertEqual((12, 0, 12), tuple(evaluator._budgets[name]
                         for name in ('foreground', 'recovery', 'background')))


if __name__ == '__main__':
    unittest.main()
