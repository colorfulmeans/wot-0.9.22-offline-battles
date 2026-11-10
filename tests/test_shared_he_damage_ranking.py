"""Shared NEXT HE plans require a completed, current damage comparison.

These fixtures provide native observations, not decisions. An observed unknown
is neither a zero-damage contact nor an armour-failure proof. Unvisited and
unfinished points cannot certify that the first returned contact is maximal.
"""
import copy
import unittest

from test_player_rebuilt_attack_policy import (
    Observations, ATOMIC_ARMOUR_BATCHES, ATOMIC_CANDIDATES)
import test_player_fire_admission_complete as native_fire
from gui.mods.offline_lan_0922.vehicle_control.evaluation_budget import EvaluationBudget


class SharedHEDamageRankingTests(unittest.TestCase):
    @staticmethod
    def scene(targets=3, points=2):
        scene = Observations(clips=6, targets=targets, points=points)
        # The current AP cassette is valid for this trigger, but exhausted for
        # NEXT. Every replacement penetration candidate really fails.
        scene.frame['ammo'] = (6, 30, 30)
        scene.passed(0)
        for target in range(1, targets + 1):
            for sample in range(points):
                scene.he(0., target=target, sample=sample)
        scene.he(140., target=targets, sample=points - 1)
        scene.prime()
        return scene

    def test_next_waits_for_later_he_damage_instead_of_committing_first_zero(self):
        scene = self.scene()
        scene.policy.background_budget = 1
        for step in range(5):
            decision = scene.tick(step * .1)
            self.assertEqual('aim', decision['action'])
            self.assertEqual(0, decision['candidate']['shell_index'])
            self.assertLessEqual(scene.policy._used['background'], 1)
            plan, reason = scene.policy.next_at_edge()
            self.assertIsNone(plan)
            self.assertEqual('he_damage_comparison_pending', reason)
        scene.tick(.5)
        plan, reason = scene.policy.next_at_edge()
        self.assertEqual('verified', reason)
        self.assertEqual((2, ('bot', 3), 1, 140.),
            (plan['shell_index'], plan['target_key'], plan['sample'],
             plan['expected_damage']))

    def test_next_proof_contains_every_compared_he_point(self):
        scene = self.scene()
        scene.prime('he_fallback')
        scene.tick(0.)
        plan, reason = scene.policy.next_at_edge()
        self.assertEqual('verified', reason)
        self.assertEqual(140., plan['expected_damage'])
        expected = set(job[0] for job in scene.policy._jobs('he_fallback'))
        actual = set(row['key'] for row in scene.policy.next_proofs
                     if row['mode'] == 'he_fallback')
        self.assertEqual(expected, actual)

    def test_foreground_he_compare_rejects_competitor_pose_change_during_last_probe(self):
        scene = Observations(targets=2, points=1, he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(0, 0, 30))
        scene.he(80., target=1)
        scene.he(40., target=2)
        scene.prime()
        changed = []

        def change_competitor(channel):
            if (channel == 'foreground' and scene.calls[-1][3] == ('bot', 2) and
                    scene.calls[-1][-1] == 'he_fallback'):
                # A synchronous observation callback changes a losing target
                # before the completed comparison can publish its winner.
                scene.move_target(2, 1)
                scene.he(200., target=2)
                changed.append(True)

        scene.on_evaluate = change_competitor
        decision = scene.tick(0., background=False)
        self.assertEqual([True], changed)
        self.assertEqual(2, sum(call[1] == 'foreground' for call in scene.calls))
        self.assertEqual(0, scene.atomic_calls,
                         'completion fencing must not open another work budget')
        self.assertNotEqual('aim', decision['action'])
        self.assertIsNone(decision.get('candidate'))
        self.assertTrue(scene.policy._frame_invalid)
        self.assertEqual({}, scene.policy.rows)
        self.assertIsNone(scene.policy.selected)

        # The fresh frame may rank and use the newly exposed best contact;
        # fencing a stale comparison is not a permanent target exclusion.
        scene.on_evaluate = None
        decision = scene.tick(.1, background=False)
        self.assertEqual('aim', decision['action'])
        self.assertEqual((('bot', 1), 80.),
            (decision['candidate']['target_key'], decision['candidate']['expected_damage']))

    def test_moving_he_domain_larger_than_atomic_slice_eventually_aims_current_best(self):
        for targets, moving in ((6, True), (5, True), (6, False)):
            with self.subTest(targets=targets, points=9, moving=moving):
                scene = Observations(targets=targets, points=9,
                                     he_validation='single_point')
                scene.frame.update(loaded=2, ammo=(0, 0, 60))
                # Zero query cost isolates candidate-budget starvation from
                # wall-clock cost. The existing work limits remain unchanged.
                scene.policy.atomic_clock = lambda: 0.
                self.assertEqual((2, 2), (scene.policy.foreground_budget,
                                          scene.policy.background_budget))
                self.assertEqual(48, ATOMIC_CANDIDATES)
                for target in range(1, targets + 1):
                    for sample in range(9):
                        scene.he(80. + target + sample, target=target, sample=sample)
                first_aim, actions, maximum_observed = None, {}, 0
                for step in range(601):
                    if moving:
                        for index, target in enumerate(scene.frame['targets'], 1):
                            scene.move_target(index, step)
                            target['velocity'] = (1., 0., 0.)
                            target['value']['position'] = (step * .1, 0., 100. + index)
                    before = len(scene.calls)
                    decision = scene.tick(step * .1)
                    if step == 0:
                        self.assertEqual(targets, len(scene.policy._jobs('he_fallback', 2)),
                            'ordinary HE must not validate eight redundant samples per enemy')
                    actions[decision['action']] = actions.get(decision['action'], 0) + 1
                    maximum_observed = max(maximum_observed,
                                           scene.policy.he_comparison['observed'])
                    calls = scene.calls[before:]
                    for channel, limit in (('foreground', 2), ('background', 2),
                                           ('atomic', ATOMIC_CANDIDATES)):
                        self.assertLessEqual(sum(call[1] == channel for call in calls), limit)
                    self.assertEqual(('source', 0), scene.frame['pose'])
                    if decision['action'] != 'aim':
                        continue
                    candidate = decision['candidate']
                    current = scene.policy.current_row(candidate)
                    self.assertIsNotNone(current)
                    self.assertEqual('he_fallback', candidate['mode'])
                    self.assertEqual(current['pose_stamp'], candidate['pose_stamp'])
                    self.assertTrue(scene.policy._executable_current(current, 'he_fallback'))
                    self.assertEqual((2, ('bot', targets), 0, 80. + targets),
                        (candidate['shell_index'], candidate['target_key'],
                         candidate['sample'], candidate['expected_damage']))
                    expected_pose = ('enemy', targets, step if moving else 0)
                    self.assertEqual(expected_pose, current['pose_stamp'][2])
                    self.assertTrue(scene.policy.apply_order({})['fire_allowed'])
                    first_aim = step * .1
                    break
                self.assertIsNotNone(first_aim, dict(
                    seconds=60., candidates=targets * 9, moving=moving,
                    actions=actions, maximum_observed=maximum_observed,
                    last_comparison=scene.policy.he_comparison))

    def test_changed_losing_candidate_invalidates_the_old_maximum_proof(self):
        scene = self.scene()
        scene.prime('he_fallback')
        scene.tick(0.)
        previous, reason = scene.policy.next_at_edge()
        self.assertEqual('verified', reason)
        self.assertEqual(('bot', 3), previous['target_key'])
        # The winner did not move. A formerly inferior target now exposes a
        # better contact; its old observation cannot certify the old winner.
        scene.move_target(2, 1)
        scene.he(200., target=2, sample=1)
        scene.tick(.1, background=False)
        self.assertIsNotNone(scene.policy.current_row(previous))
        self.assertIsNone(scene.policy.next_at_edge()[0])
        for step in range(2, 30):
            scene.tick(step * .1)
            current, unused_reason = scene.policy.next_at_edge()
            if current is not None:
                break
        self.assertIsNotNone(current)
        self.assertEqual((('bot', 2), 1, 200.),
            (current['target_key'], current['sample'], current['expected_damage']))

    def test_new_candidate_invalidates_a_plan_even_if_old_rows_are_current(self):
        scene = self.scene(targets=2, points=1)
        scene.prime('he_fallback')
        scene.tick(0.)
        previous, reason = scene.policy.next_at_edge()
        self.assertEqual('verified', reason)
        new = copy.deepcopy(scene.frame['targets'][-1])
        new.update(key=('bot', 3), pose=('enemy', 3, 0))
        new['value'].update(id=103, network_id=3, position=(0., 0., 103.))
        scene.frame['targets'] += (new,)
        scene.he(220., target=3)
        scene.tick(.1, background=False)
        self.assertIsNotNone(scene.policy.current_row(previous))
        self.assertIsNone(scene.policy.next_at_edge()[0])
        for step in range(2, 30):
            scene.tick(step * .1)
            current, unused_reason = scene.policy.next_at_edge()
            if current is not None:
                break
        self.assertIsNotNone(current)
        self.assertEqual((('bot', 3), 220.),
                         (current['target_key'], current['expected_damage']))

    def test_observed_unknown_finishes_comparison_without_becoming_zero_damage(self):
        scene = self.scene(targets=2, points=1)
        scene.he(20., target=1)
        scene.value(2, target=2, mode='he_fallback', armor='unknown',
                    line='unknown', contact=None, expected_damage=None,
                    reason='native_armour_unknown')
        scene.prime('he_fallback')
        scene.tick(0.)
        plan, reason = scene.policy.next_at_edge()
        self.assertEqual('verified', reason)
        self.assertEqual((('bot', 1), 20.),
                         (plan['target_key'], plan['expected_damage']))
        unknown = [row for row in scene.policy.next_proofs
                   if row['mode'] == 'he_fallback' and row['target_key'] == ('bot', 2)]
        self.assertEqual(1, len(unknown))
        self.assertIsNone(unknown[0]['contact'])
        self.assertIsNone(unknown[0]['expected_damage'])

    def test_next_he_domain_excludes_the_last_current_he_cassette(self):
        scene = Observations(clips=6, targets=1, points=1)
        alternate = dict(scene.frame['shells'][2], index=3, signature=('he', 2))
        scene.frame.update(shells=scene.frame['shells'] + (alternate,),
                           loaded=2, ammo=(0, 0, 6, 30))
        scene.passed(2)
        scene.he(80., index=3)
        scene.prime()
        scene.prime('he_fallback', 3)
        # A frame with no optional-work allowance cannot rebuild NEXT from
        # cached facts. CURRENT still uses the loaded cassette immediately;
        # the completed NEXT comparison belongs to a later serviced frame.
        scene.policy.background_budget = 0
        before = len(scene.calls)
        decision = scene.tick(0.)
        self.assertEqual(('aim', 2),
                         (decision['action'], decision['candidate']['shell_index']))
        self.assertEqual((None, 'not_observed'), scene.policy.next_at_edge())
        self.assertEqual(before, len(scene.calls))
        self.assertEqual(0, scene.atomic_calls)
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        scene.policy.background_budget = 2
        scene.tick(.1)
        self.assertTrue(any(call[1] == 'background' for call in scene.calls[before:]))
        plan, reason = scene.policy.next_at_edge()
        self.assertEqual('verified', reason)
        self.assertEqual((3, 80.), (plan['shell_index'], plan['expected_damage']))
        self.assertTrue(all(row['shell_index'] != 2 for row in scene.policy.next_proofs))
        expected = set(job[0] for mode in ('penetration', 'he_fallback')
                       for job in scene.policy._jobs(mode) if job[0][0] != 2)
        self.assertEqual(expected, set(row['key'] for row in scene.policy.next_proofs))

    def test_next_he_cassette_comparison_finishes_after_shared_budget_deferral(self):
        scene = Observations(clips=6, targets=2, points=2)
        alternate = dict(scene.frame['shells'][2], index=3, signature=('he', 2))
        scene.frame.update(shells=scene.frame['shells'] + (alternate,),
                           loaded=2, ammo=(0, 0, 6, 30))
        scene.passed(2)
        scene.prime('penetration', 2)
        # No NEXT facts are primed. The real policy must visit both the
        # alternate shell's penetration and full HE damage domains.
        for target in (1, 2):
            for sample in (0, 1):
                scene.he(20. * target + sample, index=3, target=target, sample=sample)
        scene.he(200., index=3, target=2, sample=1)
        budget = EvaluationBudget()

        def frame_budget(now):
            budget.begin((7, now), range(1, 7))
            return budget

        class Engine(object):
            _begin_evaluation_frame = staticmethod(frame_budget)

        scene.policy.runtime.actor_id = 5
        scene.policy.runtime.engine = Engine()
        frame_budget(0.)
        for actor in (1, 2, 3, 4):
            self.assertEqual(2, budget.background(actor, 2))
        before = len(scene.calls)
        decision = scene.tick(0.)
        self.assertEqual(('aim', 2),
                         (decision['action'], decision['candidate']['shell_index']))
        self.assertEqual(before, len(scene.calls))
        self.assertEqual((None, 'not_observed'), scene.policy.next_at_edge())
        self.assertIn(5, budget.receipt()['background_waiting'])
        # Re-entering in the same frame must neither refill the budget nor
        # construct a NEXT plan from an incomplete comparison.
        scene.policy.background(0.)
        self.assertEqual(before, len(scene.calls))
        self.assertEqual(0, scene.atomic_calls)

        plan = None
        serviced = []
        for step in range(1, 17):
            now = step * .1
            frame_budget(now)
            # Low-id peers continue requesting first. The queued actor must
            # still get its fair reservation and eventually close all facts.
            for actor in (1, 2, 3, 4):
                budget.background(actor, 2)
            start = len(scene.calls)
            decision = scene.tick(now)
            calls = scene.calls[start:]
            if any(call[1] == 'background' for call in calls):
                serviced.append(step)
            self.assertLessEqual(sum(call[1] == 'background' for call in calls), 2)
            self.assertLessEqual(budget.receipt()['background_used'], 8)
            self.assertEqual(('aim', 2),
                             (decision['action'], decision['candidate']['shell_index']))
            self.assertEqual((6, (0, 0, 6, 30)), (scene.frame['clip'], scene.frame['ammo']))
            self.assertFalse(hasattr(scene.policy, 'search_started'))
            plan, reason = scene.policy.next_at_edge()
            if plan is not None:
                break
        self.assertEqual(1, serviced[0], 'the previous frame\'s waiter was starved by new requests')
        self.assertIsNotNone(plan, scene.policy.status())
        self.assertEqual('verified', reason)
        self.assertEqual((3, ('bot', 2), 1, 200.),
            (plan['shell_index'], plan['target_key'], plan['sample'], plan['expected_damage']))
        expected = set(job[0] for mode in ('penetration', 'he_fallback')
                       for job in scene.policy._jobs(mode) if job[0][0] != 2)
        self.assertEqual(8, len(expected))
        self.assertEqual(expected, set(row['key'] for row in scene.policy.next_proofs))
        self.assertTrue(all(row['shell_index'] == 3 for row in scene.policy.next_proofs))
        self.assertEqual(0, scene.atomic_calls,
                         'ordinary fair background work must suffice without reopening atomic caps')


class SharedCurrentHEObservationTests(unittest.TestCase):
    @staticmethod
    def scene(targets=3, points=1, clips=1):
        scene = Observations(clips=clips, targets=targets, points=points,
                             he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(0, 0, 60))
        scene.policy.atomic_clock = lambda: 0.
        for index, target in enumerate(scene.frame['targets'], 1):
            target['sample_identity'] = ('entity', index, 'layout', 1)
            for sample in range(points):
                scene.he(80. + index + sample, target=index, sample=sample)
        return scene

    @staticmethod
    def move_all(scene, revision):
        for target in scene.frame['targets']:
            index = target['key'][1]
            target['pose'] = ('enemy', index, revision)
            target['velocity'] = (1., 0., 0.)
            target['value']['position'] = (revision * .1, 0., 100. + index)

    def tick(self, scene, now, background=True):
        before = len(scene.calls)
        decision = scene.tick(now, background=background)
        calls = scene.calls[before:]
        self.assertEqual((2, 2), (scene.policy.foreground_budget,
                                  scene.policy.background_budget))
        self.assertEqual(48, ATOMIC_CANDIDATES)
        for channel, limit in (('foreground', 2), ('background', 2), ('atomic', 48)):
            self.assertLessEqual(sum(call[1] == channel for call in calls), limit)
        self.assertEqual(('source', 0), scene.frame['pose'])
        return decision

    def assert_current_aim(self, scene, decision, target, sample, damage):
        self.assertEqual('aim', decision['action'], decision)
        candidate = decision['candidate']
        current = scene.policy.current_row(candidate)
        self.assertIsNotNone(current)
        self.assertEqual('he_fallback', candidate['mode'])
        self.assertEqual(current['pose_stamp'], candidate['pose_stamp'])
        self.assertTrue(scene.policy._executable_current(current, 'he_fallback'))
        live = next(row for row in scene.frame['targets'] if row['key'] == ('bot', target))
        self.assertEqual(live['pose'], current['pose_stamp'][2])
        self.assertEqual((2, ('bot', target), sample, damage),
            (candidate['shell_index'], candidate['target_key'], candidate['sample'],
             candidate['expected_damage']))
        self.assertTrue(scene.policy.apply_order({})['fire_allowed'])

    def test_seven_moving_targets_preserve_loaded_he_cassette_and_current_shot_proof(self):
        scene = self.scene(targets=7, points=9, clips=6)
        decision = None
        for step in range(601):
            self.move_all(scene, step)
            decision = self.tick(scene, step * .1)
            self.assertNotIn(decision['action'], ('switch_shell', 'reload_clip', 'search_penetration'))
            self.assertFalse(hasattr(scene.policy, 'search_started'))
            self.assertIsNone(scene.policy.reload_authority)
            if decision['action'] == 'aim':
                break
        self.assert_current_aim(scene, decision, 7, 0, 87.)

    def test_blocked_high_hint_requires_live_proof_before_advancing_to_next_contact(self):
        scene = self.scene()
        first = self.tick(scene, 0.)
        self.assert_current_aim(scene, first, 3, 0, 83.)
        self.move_all(scene, 1)
        scene.value(2, target=3, mode='he_fallback', line='world_blocked',
                    contact=None, expected_damage=None)
        decision = self.tick(scene, .1, background=False)
        self.assertNotEqual('aim', decision['action'])
        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
        blocked = scene.policy.current_row(first['candidate'])
        self.assertIsNotNone(blocked)
        self.assertEqual('world_blocked', blocked['line'])
        self.assertFalse(scene.policy._executable_current(blocked, 'he_fallback'))
        self.assertIsNone(scene.policy._current_he_observations[first['candidate']['key']]['damage'])
        for step in range(2, 31):
            self.move_all(scene, step)
            decision = self.tick(scene, step * .1)
            if decision['action'] == 'aim':
                break
        self.assert_current_aim(scene, decision, 2, 0, 82.)

    def test_pending_top_hint_yields_to_fresh_lower_contact_after_completed_first_pass(self):
        scene = self.scene(targets=2)
        scene.he(200., target=1)
        scene.he(100., target=2)
        first = self.tick(scene, 0.)
        self.assert_current_aim(scene, first, 1, 0, 200.)
        self.assertEqual(2, len(scene.policy._current_he_observations))
        scene.value(2, target=1, mode='he_fallback', armor='unknown',
                    line='pending', review_pending=True, contact=None,
                    expected_damage=None)
        decision = None
        for step in range(1, 101):
            self.move_all(scene, step)
            decision = self.tick(scene, step * .1)
            top = scene.policy.current_row(first['candidate'])
            if top is not None:
                self.assertFalse(scene.policy._he_observed(top))
                self.assertFalse(scene.policy._executable_current(top, 'he_fallback'))
                self.assertIsNone(top['contact'])
                self.assertIsNone(top['expected_damage'])
            if decision['action'] == 'aim':
                break
        self.assert_current_aim(scene, decision, 2, 0, 100.)
        self.assertEqual(200.,
            scene.policy._current_he_observations[first['candidate']['key']]['damage'],
            'deferring an unfinished recheck must not invent zero damage')

    def test_pending_first_contact_does_not_block_a_new_loaded_he_contact(self):
        scene = self.scene(targets=2)
        scene.value(2, target=1, mode='he_fallback', armor='unknown',
                    line='pending', review_pending=True, contact=None,
                    expected_damage=None)
        scene.he(100., target=2)
        verified_lower = False
        for step in range(101):
            self.move_all(scene, step)
            decision = self.tick(scene, step * .1)
            # Pending target 1 is not an executable contact and cannot be
            # ranked as zero. The *loaded* HE may nevertheless shoot the
            # independently proved target 2 without waiting for that probe.
            self.assertNotIn((2, ('bot', 1), 0, 'he_fallback'),
                             scene.policy._current_he_observations)
            verified_lower = verified_lower or any(
                row['target_key'] == ('bot', 2) and row['mode'] == 'he_fallback' and
                scene.policy._executable_current(row, 'he_fallback')
                for row in scene.policy.rows.values())
            if decision['action'] == 'aim':
                self.assert_current_aim(scene, decision, 2, 0, 100.)
                break
        self.assertTrue(verified_lower,
                        'a positive observed lower contact must be independently executable')
        self.assertEqual('aim', decision['action'])

    def test_high_hint_dying_during_recheck_revokes_batch_then_prunes_dead_target(self):
        scene = self.scene()
        first = self.tick(scene, 0.)
        self.assert_current_aim(scene, first, 3, 0, 83.)
        self.move_all(scene, 1)
        changed = []

        def die_during_recheck(channel):
            if scene.calls[-1][3:] == (('bot', 3), 0, 'he_fallback'):
                # Native snapshots remove dead actors from the admitted
                # domain. The old callback's positive result is now stale.
                scene.frame['targets'][-1]['value']['alive'] = False
                scene.frame['targets'] = scene.frame['targets'][:-1]
                changed.append(True)

        scene.on_evaluate = die_during_recheck
        decision = self.tick(scene, .1, background=False)
        self.assertEqual([True], changed)
        self.assertNotEqual('aim', decision['action'])
        self.assertTrue(scene.policy._frame_invalid)
        self.assertEqual({}, scene.policy.rows)
        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
        scene.on_evaluate = None
        before = len(scene.calls)
        for step in range(2, 31):
            self.move_all(scene, step)
            decision = self.tick(scene, step * .1)
            if decision['action'] == 'aim':
                break
        self.assert_current_aim(scene, decision, 2, 0, 82.)
        self.assertTrue(all(key[1] != ('bot', 3)
                            for key in scene.policy._current_he_observations))
        self.assertTrue(all(call[3] != ('bot', 3) for call in scene.calls[before:]))

    def test_current_hints_never_authorize_next_or_eight_second_negative_search(self):
        scene = self.scene(targets=7, points=9, clips=6)
        scene.frame['ammo'] = (30, 0, 60)
        for target in range(1, 8):
            for sample in range(9):
                scene.value(0, target=target, sample=sample, armor='unknown')
        decision, aimed = None, False
        for step in range(121):
            self.move_all(scene, step)
            decision = self.tick(scene, step * .1)
            self.assertFalse(scene.policy._all_failed((0,)))
            self.assertFalse(scene.policy._fallback_qualified((0,)))
            self.assertFalse(hasattr(scene.policy, 'search_started'))
            self.assertFalse(hasattr(scene.policy, 'search_authority'))
            self.assertIsNone(scene.policy.reload_authority)
            self.assertIsNone(scene.policy.next_at_edge()[0])
            aimed = aimed or decision['action'] == 'aim'
        self.assertTrue(aimed)
        self.assert_current_aim(scene, decision, 7, 0, 87.)
        self.assertEqual(7, len(scene.policy._current_he_observations))
        self.assertTrue(all(set(value) == {'identity', 'damage'}
                            for value in scene.policy._current_he_observations.values()))
        self.assertIsNone(scene.policy._best_he(plannable=True),
                          'CURRENT ranking hints cannot satisfy strict NEXT HE comparison')
        self.assertIsNone(scene.policy.next_shell)
        self.assertIsNone(scene.policy.next_plan)

    def test_next_trigger_observes_new_target_samples_before_old_current_hint_can_fire(self):
        scene = self.scene(targets=2, clips=6)
        first = self.tick(scene, 0.)
        self.assert_current_aim(scene, first, 2, 0, 82.)
        # A physical commit opens the next comparison. New contacts need
        # their own physical observation; ordinary HE only samples index 0.
        scene.policy.shot_committed(dict(burst_index=0, burst_count=1),
                                   dict(player_control=dict(candidate=first['candidate'])))
        scene.frame.update(clip=5, ammo=(0, 0, 59))
        for old_target in (1, 2):
            scene.value(2, target=old_target, mode='he_fallback',
                        contact=None, expected_damage=None)
        target = copy.deepcopy(scene.frame['targets'][-1])
        target.update(key=('bot', 3), pose=('enemy', 3, 0), samples=(0, 1, 2),
                      sample_identity=('entity', 3, 'layout', 1))
        target['value'].update(id=103, network_id=3, position=(0., 0., 103.))
        scene.frame['targets'] += (target,)
        for sample in range(3):
            scene.he(300. + sample, target=3, sample=sample)
        self.move_all(scene, 1)
        decision = self.tick(scene, .1, background=False)
        self.assertNotEqual('aim', decision['action'])
        self.assertEqual(3, scene.policy.he_comparison['total'])
        for step in range(2, 31):
            self.move_all(scene, step)
            decision = self.tick(scene, step * .1)
            if decision['action'] == 'aim':
                break
        self.assert_current_aim(scene, decision, 3, 0, 300.)

    def test_next_trigger_entity_or_sample_identity_change_cannot_inherit_current_hint(self):
        for change in ('entity', 'sample_identity', 'sample_layout'):
            with self.subTest(change=change):
                scene = self.scene(clips=6)
                scene.he(200., target=3)
                first = self.tick(scene, 0.)
                self.assert_current_aim(scene, first, 3, 0, 200.)
                scene.policy.shot_committed(dict(burst_index=0, burst_count=1),
                    dict(player_control=dict(candidate=first['candidate'])))
                scene.frame.update(clip=5, ammo=(0, 0, 59))
                target = scene.frame['targets'][1]
                if change == 'entity':
                    target['sample_identity'] = ('replacement_entity', 2, 'layout', 1)
                elif change == 'sample_identity':
                    target['sample_identity'] = ('entity', 2, 'layout', 2)
                else:
                    target['samples'] = (0, 1)
                sample = 0
                scene.he(300., target=2, sample=sample)
                before = len(scene.calls)
                for step in range(1, 31):
                    self.move_all(scene, step)
                    decision = self.tick(scene, step * .1)
                    if decision['action'] == 'aim':
                        break
                self.assert_current_aim(scene, decision, 2, sample, 300.)
                self.assertTrue(any(call[3:] == (('bot', 2), sample, 'he_fallback')
                                    for call in scene.calls[before:]))

    def test_final_trigger_commit_starts_a_new_current_he_comparison(self):
        scene = self.scene(points=2, clips=6)
        first = self.tick(scene, 0.)
        self.assert_current_aim(scene, first, 3, 0, 83.)
        observations = copy.deepcopy(scene.policy._current_he_observations)
        scene.policy.shot_committed(dict(burst_index=0, burst_count=3),
                                   dict(player_control=dict(candidate=first['candidate'])))
        self.assertEqual(observations, scene.policy._current_he_observations)
        scene.frame.update(trigger_active=True, clip=5, ammo=(0, 0, 59))
        self.assertEqual('trigger_active', self.tick(scene, .1, background=False)['action'])
        scene.policy.shot_committed(dict(burst_index=1, burst_count=3), {})
        self.assertEqual(observations, scene.policy._current_he_observations)
        scene.policy.shot_committed(dict(burst_index=2, burst_count=3), {})
        self.assertEqual({}, scene.policy._current_he_observations)
        self.assertIsNone(scene.policy.trigger)
        scene.frame.update(trigger_active=False, clip=3, ammo=(0, 0, 57))
        scene.he(1., target=3, sample=1)
        scene.he(300., target=1, sample=0)
        for step in range(2, 31):
            self.move_all(scene, step)
            decision = self.tick(scene, step * .1)
            if decision['action'] == 'aim':
                break
        self.assert_current_aim(scene, decision, 1, 0, 300.)


class NativeHEBudgetObservationTests(native_fire.AutomaticFireScene):
    def test_native_sample_identity_ignores_motion_but_changes_with_entity_and_collider(self):
        evaluator = self.runtime.attack_policy.evaluator

        def target_snapshot():
            self.observe()
            frame = evaluator.snapshot(self.now)
            return next(row for row in frame['targets'] if row['entity'] is self.target)

        original = target_snapshot()
        self.pose(self.target, (1., 0., 100.))
        self.fixture.now += .1
        moved = target_snapshot()
        self.assertNotEqual(original['pose'], moved['pose'])
        self.assertEqual(original['sample_identity'], moved['sample_identity'])
        self.target = self.vehicle(self.target.id, (1., 0., 100.), team=2)
        self.fixture.now += .1
        replacement = target_snapshot()
        self.assertNotEqual(moved['sample_identity'], replacement['sample_identity'])
        self.target.typeDescriptor.hull.hitTester = copy.copy(self.target.typeDescriptor.hull.hitTester)
        self.fixture.now += .1
        new_collider = target_snapshot()
        self.assertNotEqual(replacement['sample_identity'], new_collider['sample_identity'])

    def atomic_he_job(self):
        self.set_he()
        self.observe()
        policy = self.runtime.attack_policy
        policy.reset()
        evaluator = policy.evaluator
        evaluator.jobs.clear()
        evaluator.predictions.clear()
        evaluator.armour_rays.clear()
        policy.frame = evaluator.snapshot(self.now)
        job = policy._jobs('he_fallback')[0]
        evaluator.atomic_clock = lambda: 0.
        evaluator.atomic_deadline = 1.
        self.assertTrue(evaluator.begin_atomic(policy.frame, (job,), self.now))
        return policy, evaluator, job

    def test_expired_atomic_slice_is_unfinished_not_an_observed_unknown_he_contact(self):
        policy, evaluator, job = self.atomic_he_job()
        evaluator.atomic_clock = lambda: 2.
        before = len(self.world_queries)
        row = policy._evaluate(job, self.now, 'atomic')
        self.assertFalse(policy._he_observed(row),
            dict((key, row.get(key)) for key in ('line', 'reason', 'contact', 'expected_damage')))
        self.assertIsNone(row['contact'])
        self.assertIsNone(row['expected_damage'])
        self.assertEqual(before, len(self.world_queries))
        self.assertEqual('atomic_frame_budget_exhausted', evaluator.atomic_receipt['reason'])

    def test_exhausted_material_budget_is_unfinished_after_real_world_lane_proof(self):
        policy, evaluator, job = self.atomic_he_job()
        evaluator.atomic_receipt['armour_collision_batches'] = ATOMIC_ARMOUR_BATCHES
        before = len(self.world_queries)
        row = policy._evaluate(job, self.now, 'atomic')
        self.assertGreater(len(self.world_queries), before)
        self.assertEqual('atomic_armour_budget_exhausted', evaluator.atomic_receipt['reason'])
        self.assertFalse(policy._he_observed(row),
            dict((key, row.get(key)) for key in ('line', 'reason', 'contact', 'expected_damage')))
        self.assertIsNone(row['contact'])
        self.assertIsNone(row['expected_damage'])
        self.assertEqual(ATOMIC_ARMOUR_BATCHES,
                         evaluator.atomic_receipt['armour_collision_batches'])


if __name__ == '__main__':
    unittest.main()
