"""Rebuilt point/trigger policy: complete domains and live failure feedback.

The finite-observation fixture below supplies plate/line facts, not policy
decisions. The final class reuses native matrices/component hit testers from
the real PlayerControl + FullPlayerRuntime fire fixture. Neither fixture is a
claim of a Windows BigWorld play test or a certified frame-time bound.
"""
import copy
import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control.attack_policy import (
    AttackPolicy, ATOMIC_CLOSE_INTERVAL, ATOMIC_MAX_JOBS, ATOMIC_WORLD_QUERIES,
    ATOMIC_ARMOUR_BATCHES, ATOMIC_CANDIDATES, native_source_pose)
from gui.mods.offline_lan_0922.player_control.trigger_admission import TriggerAdmission


class Observations(object):
    def __init__(self, clips=1, targets=2, points=2, he=True):
        shells = [dict(index=0, is_he=False, piercing=200., signature=('ap', 1)),
                  dict(index=1, is_he=False, piercing=300., signature=('apcr', 1))]
        if he:
            shells.append(dict(index=2, is_he=True, piercing=100., signature=('he', 1)))
        self.frame = dict(identity=('round', 'gun'), pose=('source', 0),
            position=(0., 0., 0.), loaded=0, clip=clips, clip_size=clips,
            ammo=tuple(30 for shell in shells), reloading=False,
            trigger_active=False, artillery=False, line_revision=0, scene=0,
            shells=tuple(shells), targets=tuple(
                dict(key=('bot', index), pose=('enemy', index, 0),
                     samples=tuple(range(points)), velocity=(0., 0., 0.),
                     value=dict(kind='bot', id=index + 100, network_id=index,
                                position=(0., 0., 100. + index)))
                for index in range(1, targets + 1)))
        self.values, self.calls = {}, []
        self.on_evaluate = None
        self.allow_atomic = True
        self.atomic_calls = 0
        self.atomic_receipt = {}
        self.invalidated = []
        self.policy = AttackPolicy(SimpleNamespace(), evaluator=self)

    def snapshot(self, now):
        value = copy.deepcopy(self.frame)
        value['observed_at'] = now
        return value

    def fence(self, frame):
        return (frame['identity'], frame['pose'], frame['scene'], frame['line_revision'],
                frame['targets'], frame['shells']) == (
                self.frame['identity'], self.frame['pose'], self.frame['scene'],
                self.frame['line_revision'], self.frame['targets'], self.frame['shells'])

    def begin_atomic(self, frame, jobs, now):
        self.atomic_calls += 1
        self.atomic_receipt = dict(world_budget=len(jobs), world_chords=0)
        return self.allow_atomic

    def invalidate_line(self, key):
        self.invalidated.append(key)

    def value(self, index, target=1, sample=0, mode='penetration', **fields):
        result = dict(armor='failed', line='clear', mechanical='reachable',
                      contact=None, expected_damage=None)
        result.update(fields)
        self.values[index, ('bot', target), sample, mode] = result

    def passed(self, index=0, target=1, sample=0):
        self.value(index, target, sample, armor='passed')

    def he(self, damage, index=2, target=1, sample=0):
        self.value(index, target, sample, 'he_fallback', contact=True,
                   expected_damage=damage)

    def evaluate(self, frame, shell, target, sample, mode, now, channel):
        self.calls.append((now, channel, shell['index'], target['key'], sample, mode))
        value = dict(self.values.get((shell['index'], target['key'], sample, mode),
            dict(armor='failed', line='clear', mechanical='reachable',
                 contact=None, expected_damage=None)))
        if sample is None or target['pose'] is None or shell.get('unavailable'):
            value.update(armor='unknown', line='unknown', mechanical='unknown')
        value['solution'] = dict(point=target['value']['position'],
            target_pose=target['pose'], source_pose=frame['pose'], sample=sample,
            sample_value=('hull', sample), velocity=(0., 0., 0.))
        if channel == 'atomic':
            self.atomic_receipt['world_chords'] += 1
        if self.on_evaluate is not None:
            self.on_evaluate(channel)
        return value

    def tick(self, now, background=True):
        result = self.policy.update(now)
        if background:
            self.policy.background(now)
        return result

    def prime(self, mode='penetration', index=None):
        self.policy.frame = self.snapshot(0.)
        for job in self.policy._jobs(mode, index):
            self.policy._evaluate(job, 0., 'background')

    def move_target(self, index, revision):
        self.frame['targets'][index - 1]['pose'] = ('enemy', index, revision)


class RebuiltForegroundTests(unittest.TestCase):
    def test_first_current_point_stops_before_background_and_atomic(self):
        scene = Observations()
        scene.passed()
        result = scene.tick(0., background=False)
        self.assertEqual('aim', result['action'])
        self.assertEqual(1, len(scene.calls))
        self.assertEqual('foreground', scene.calls[0][1])
        self.assertEqual(0, scene.atomic_calls)
        order = scene.policy.apply_order(dict(move_position=(30., 0., 50.), throttle_override=1.))
        self.assertEqual((0., 0., 0.), order['move_position'])
        self.assertEqual(0., order['throttle_override'])
        self.assertTrue(order['fire_allowed'])
        scene.policy.background(0.)
        self.assertEqual(2, sum(row[1] == 'background' for row in scene.calls))

    def test_single_blocked_sample_does_not_exclude_rest_of_same_enemy(self):
        for line in ('friendly_blocked', 'world_blocked'):
            with self.subTest(line=line):
                scene = Observations()
                scene.value(0, sample=0, line=line, armor='unknown')
                scene.passed(0, sample=1)
                result = scene.tick(0.)
                self.assertEqual(('aim', ('bot', 1), 1),
                    (result['action'], result['candidate']['target_key'], result['candidate']['sample']))
                self.assertIsNone(scene.policy.search_started)

    def test_live_admission_friend_feedback_uses_ordinary_navigation(self):
        for clip in (1, 6):
            with self.subTest(clip=clip):
                scene = Observations(clips=clip, targets=1, points=1)
                scene.passed(0)
                scene.passed(1)
                scene.prime()
                first = scene.tick(0.)['candidate']
                scene.policy.admission_failed(first, 'auto_friendly_lane',
                    dict(blocker_team=1, blocker_kind='human', blocker_id=4))
                scene.value(0, line='friendly_blocked', armor='unknown')
                scene.frame['line_revision'] += 1
                result = scene.tick(.1)
                self.assertEqual('firing_position', result['action'])
                self.assertEqual('passed', result['candidate']['armor'])
                self.assertIsNone(scene.policy.search_started)
                self.assertNotIn('shell_index', result)
                self.assertEqual(1, len(scene.invalidated))

    def test_blocked_current_ap_keeps_usage_even_when_apcr_is_executable(self):
        scene = Observations(targets=1, points=1)
        scene.value(0, armor='passed', line='world_blocked')
        scene.passed(1)
        scene.prime()
        result = scene.tick(0.)
        self.assertEqual(('firing_position', 0),
                         (result['action'], result['candidate']['shell_index']))
        self.assertIsNone(scene.policy.search_started)

    def test_copied_other_sample_refusal_does_not_override_verified_sample(self):
        scene = Observations()
        scene.passed(0, sample=1)
        scene.tick(0.)
        command, target = scene.policy.select_command({}, dict(fire_allowed=False), None, 0.)
        self.assertTrue(command['fire_allowed'])
        self.assertEqual(101, target['id'])

    def test_current_selection_stays_stable_until_next_trigger(self):
        scene = Observations()
        scene.passed(0, target=2, sample=1)
        scene.prime(index=0)
        first = scene.tick(0.)['candidate']
        scene.passed(0, target=1, sample=0)
        scene.prime(index=0)
        second = scene.tick(.1)['candidate']
        self.assertEqual(first['key'], second['key'])
        scene.policy.shot_committed(dict(burst_index=0, burst_count=1), {})
        self.assertIsNone(scene.policy.selected)

    def test_hull_laying_intent_stays_stable_while_its_evidence_expires(self):
        scene = Observations(targets=1, points=9)
        for sample in range(9):
            scene.value(0, sample=sample, armor='unknown', mechanical='hull_laying')
        first = scene.tick(0.)['candidate']
        for step in range(1, 60):
            scene.frame['pose'] = ('actual_hull_progress', step)
            result = scene.tick(step * .1)
            self.assertEqual('firing_position', result['action'])
            self.assertEqual(first['key'], result['candidate']['key'])
            self.assertNotEqual(first['pose_stamp'], result['candidate']['pose_stamp'])
        scene.passed(0, sample=first['sample'])
        scene.frame['pose'] = ('aligned', 60)
        result = scene.tick(6.)
        self.assertEqual('aim', result['action'])
        self.assertEqual(first['key'], result['candidate']['key'])

    def test_next_shell_ranking_is_real_piercing_not_currency(self):
        scene = Observations(targets=1, points=1)
        for index in (0, 1, 2):
            scene.passed(index)
        scene.prime()
        result = scene.tick(0.)
        self.assertEqual(0, result['candidate']['shell_index'])
        self.assertEqual(2, scene.policy.next_shell)
        scene.frame['shells'][0]['piercing'] = 350.
        scene.frame['ammo'] = (30, 30, 0)
        scene.prime()
        scene.tick(.1)
        self.assertEqual(1, scene.policy.next_shell)

    def test_background_visits_all_ammo_targets_points_and_he_independently(self):
        scene = Observations()
        scene.passed()
        expected = set()
        for index in (0, 1, 2):
            for target in (1, 2):
                for point in (0, 1):
                    expected.add((index, ('bot', target), point, 'penetration'))
                    if index == 2:
                        expected.add((index, ('bot', target), point, 'he_fallback'))
        for step in range(12):
            result = scene.tick(step * .1)
            self.assertEqual('aim', result['action'])
            self.assertLessEqual(scene.policy._used['foreground'], 2)
            self.assertEqual(2, scene.policy._used['background'])
            scene.policy.background(step * .1)
            self.assertEqual(2, scene.policy._used['background'])
        actual = set(row[2:] for row in scene.calls if row[1] == 'background')
        foreground_proofs = set(row[2:] for row in scene.calls if row[1] == 'foreground')
        # Background ranking consumes the already-current foreground proof;
        # it need not repeat that native query while other points are pending.
        self.assertEqual(expected, actual | foreground_proofs)
        self.assertEqual(expected - foreground_proofs, actual - foreground_proofs)
        self.assertEqual(0, scene.atomic_calls)

    def test_unknown_or_empty_domain_is_never_all_armour_failure(self):
        for kind in ('no_enemies', 'missing_samples', 'missing_pose', 'pending', 'unknown'):
            with self.subTest(kind=kind):
                scene = Observations(targets=1, points=1)
                if kind == 'no_enemies':
                    scene.frame['targets'] = ()
                elif kind == 'missing_samples':
                    scene.frame['targets'][0]['samples'] = ()
                elif kind == 'missing_pose':
                    scene.frame['targets'][0]['pose'] = None
                else:
                    scene.value(1, armor=kind, line=kind)
                for step in range(30):
                    scene.tick(float(step))
                    self.assertIsNone(scene.policy.search_started)
                    self.assertFalse(scene.policy.fallback)

    def test_missing_one_target_prevents_other_targets_from_granting_global_timer(self):
        scene = Observations(targets=3)
        scene.frame['targets'][2]['pose'] = None
        scene.prime()
        result = scene.tick(0.)
        self.assertNotEqual('search_penetration', result['action'])
        self.assertIsNone(scene.policy.search_started)

    def test_all_blocked_four_hundred_seconds_stays_fair_and_later_fires_reopened_point(self):
        scene = Observations(clips=6, targets=2, points=4)
        for shell in range(3):
            for target in (1, 2):
                for sample in range(4):
                    scene.value(shell, target, sample, armor='unknown', line='world_blocked')
        visited = set()
        for tick in range(4100):
            before = len(scene.calls)
            result = scene.tick(tick * .1)
            calls = scene.calls[before:]
            self.assertLessEqual(sum(row[1] == 'foreground' for row in calls), 2)
            self.assertLessEqual(sum(row[1] == 'background' for row in calls), 2)
            self.assertLessEqual(sum(row[1] == 'atomic' for row in calls), ATOMIC_CANDIDATES)
            visited.update((row[3], row[4]) for row in calls if row[1] == 'foreground')
            self.assertEqual('firing_position', result['action'])
            self.assertNotIn('shell_index', result)
            self.assertIsNone(scene.policy.search_started)
            self.assertFalse(scene.policy.fallback)
        self.assertEqual(set((('bot', target), sample)
                             for target in (1, 2) for sample in range(4)), visited)
        scene.passed(0, target=2, sample=3)
        scene.frame['line_revision'] += 1
        for tick in range(12):
            result = scene.tick(410. + tick * .1)
            if result['action'] == 'aim':
                break
        self.assertEqual(('aim', ('bot', 2), 3),
            (result['action'], result['candidate']['target_key'], result['candidate']['sample']))


class RebuiltEvidenceTests(unittest.TestCase):
    def test_positive_proof_expires_for_each_source_and_target_pose_change(self):
        for change in ('source_position', 'source_hull', 'source_turret',
                       'target_hull', 'target_turret', 'ammo_geometry'):
            with self.subTest(change=change):
                scene = Observations(targets=1, points=1)
                scene.passed()
                scene.tick(0.)
                scene.value(0, armor='unknown', line='pending')
                if change.startswith('source'):
                    scene.frame['pose'] = (change, 1)
                elif change.startswith('target'):
                    scene.frame['targets'][0]['pose'] = (change, 1)
                else:
                    scene.frame['shells'][0]['signature'] = ('new_penetration_model', 2)
                result = scene.tick(.1)
                self.assertNotEqual('aim', result['action'])
                self.assertFalse(any(row['armor'] == 'passed' for row in scene.policy.rows.values()))

    def test_world_revision_revokes_line_without_discarding_the_plate_proof(self):
        scene = Observations(targets=1, points=1)
        scene.passed()
        first = scene.tick(0.)['candidate']
        scene.frame['scene'] += 1
        scene.value(0, armor='unknown', line='pending')
        result = scene.tick(.1)
        candidate = result['candidate']
        self.assertEqual('firing_position', result['action'])
        self.assertEqual(first['pose_stamp'], candidate['pose_stamp'])
        self.assertNotEqual(first['line_stamp'], candidate['line_stamp'])
        self.assertEqual(('passed', 'pending'), (candidate['armor'], candidate['line']))
        self.assertIsNone(scene.policy.search_started)

    def test_missing_evidence_releases_wait_to_ordinary_firing_position(self):
        scene = Observations(targets=1, points=1, he=False)
        scene.allow_atomic = False
        for index in (0, 1):
            scene.value(index, armor='unknown', line='unknown')
        self.assertEqual('wait', scene.tick(0.)['action'])
        for now in (.5, 1., 1.5, 2., 3., 10., 76.):
            scene.move_target(1, now)
            result = scene.tick(now)
            self.assertIsNone(scene.policy.search_started)
        self.assertEqual('firing_position', result['action'])
        self.assertEqual('penetration_evidence_incomplete', result['reason'])

    def test_pose_away_then_return_cannot_resurrect_old_proof(self):
        scene = Observations(targets=1, points=1)
        scene.passed()
        scene.tick(0.)
        original = scene.frame['pose']
        scene.frame['pose'] = ('different', 2)
        scene.value(0, armor='unknown', line='pending')
        scene.tick(.1)
        scene.frame['pose'] = original
        result = scene.tick(.2)
        self.assertNotEqual('aim', result['action'])

    def test_stopped_target_velocity_change_expires_old_lead_even_at_same_pose(self):
        scene = Observations(targets=1, points=1)
        scene.frame['targets'][0]['velocity'] = (3., 0., 0.)
        scene.passed()
        scene.tick(0.)
        scene.frame['targets'][0]['velocity'] = (0., 0., 0.)
        scene.value(0, armor='unknown', line='pending')
        result = scene.tick(.1)
        self.assertNotEqual('aim', result['action'])
        self.assertFalse(any(row['armor'] == 'passed' for row in scene.policy.rows.values()))

    def test_negative_proofs_from_different_poses_do_not_sum_to_all_failed(self):
        scene = Observations(targets=1, points=4)
        scene.allow_atomic = False
        scene.policy.background_budget = 1
        for index in range(40):
            scene.move_target(1, index)
            scene.tick(index * .1)
            self.assertIsNone(scene.policy.search_started)
        self.assertLessEqual(len(scene.policy.rows), 3)

    def test_pending_line_preserves_same_pose_armour_but_not_false_executability(self):
        scene = Observations(targets=1, points=1)
        scene.passed()
        first = scene.tick(0.)['candidate']
        scene.frame['line_revision'] += 1
        scene.value(0, armor='unknown', line='pending')
        result = scene.tick(.1)
        self.assertEqual('firing_position', result['action'])
        self.assertEqual(first['pose_stamp'], result['candidate']['pose_stamp'])
        self.assertEqual('passed', result['candidate']['armor'])
        self.assertIsNone(scene.policy.search_started)

    def test_admission_failure_only_invalidates_selected_point(self):
        scene = Observations()
        scene.passed(0, sample=0)
        scene.passed(0, sample=1)
        scene.prime(index=0)
        first = scene.tick(0.)['candidate']
        scene.policy.admission_failed(first, 'auto_world_blocked', dict(kind='world'))
        unaffected = [row for row in scene.policy.rows.values()
                      if row['sample'] == 1 and row['target_key'] == ('bot', 1)]
        self.assertEqual('clear', unaffected[0]['line'])
        self.assertEqual('passed', unaffected[0]['armor'])

    def test_front_vehicle_feedback_cannot_be_erased_by_ideal_target_probe(self):
        scene = Observations(targets=1, points=1)
        scene.passed()
        first = scene.tick(0.)['candidate']
        scene.policy.admission_failed(first, 'auto_front_vehicle')
        # The endpoint armour probe still passes, but the admission proved an
        # intervening vehicle. No same-scene optimistic retry may erase it.
        for step in range(1, 20):
            result = scene.tick(step * .1)
            self.assertEqual('firing_position', result['action'])
            self.assertIsNone(scene.policy.search_started)
        scene.frame['line_revision'] += 1
        self.assertEqual('aim', scene.tick(2.)['action'])


class RebuiltSearchAndClipTests(unittest.TestCase):
    def test_committed_next_shell_preaims_its_proved_point_until_load_completion(self):
        for clip_size in (1, 4):
            with self.subTest(clip_size=clip_size):
                scene = Observations(clips=clip_size, targets=2, points=2)
                scene.passed(0, 1, 0)
                scene.passed(2, 2, 1)
                scene.prime()
                first = scene.tick(0.)
                self.assertEqual(0, first['candidate']['shell_index'])
                plan = scene.policy.next_plan
                self.assertEqual((2, ('bot', 2), 1, 'penetration'), plan['key'])
                scene.policy.shot_committed(dict(burst_index=0, burst_count=1), {})
                scene.frame.update(loaded=2, clip=0, reloading=True)
                preaim = scene.tick(.1)
                self.assertEqual('preaiming', preaim['phase'])
                self.assertEqual(plan['key'], preaim['candidate']['key'])
                self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
                scene.frame.update(clip=clip_size, reloading=False)
                ready = scene.tick(.2)
                self.assertEqual(plan['key'], ready['candidate']['key'])
                self.assertTrue(scene.policy.apply_order({})['fire_allowed'])

    def test_single_all_ammo_domain_and_magazine_current_only(self):
        for clips in (1, 6):
            scene = Observations(clips=clips, targets=1, points=2)
            scene.value(1, armor='pending', line='pending')
            result = scene.tick(0.)
            self.assertEqual(clips > 1, result['action'] == 'search_penetration')

    def test_magazine_preserves_clip_for_eight_seconds_before_alternative_reload(self):
        scene = Observations(clips=6, targets=1, points=2)
        scene.passed(1)
        scene.prime()
        for step in range(80):
            result = scene.tick(step * .1)
            self.assertEqual('search_penetration', result['action'])
            self.assertEqual(6, scene.frame['clip'])
            self.assertEqual(0., scene.policy.search_started)
        result = scene.tick(8.)
        self.assertEqual(('reload_clip', 1, True),
                         (result['action'], result['shell_index'], result['early_reload']))

    def test_empty_clip_reloads_without_eight_second_attempt(self):
        scene = Observations(clips=6)
        scene.frame['clip'] = 0
        scene.passed(1)
        scene.prime()
        result = scene.tick(0.)
        self.assertEqual('reload_clip', result['action'])
        self.assertFalse(result['early_reload'])
        self.assertEqual(1, result['shell_index'])
        self.assertIsNone(scene.policy.search_started)

    def test_empty_current_stock_selects_normal_next_load_without_fake_failure(self):
        for clips in (1, 6):
            scene = Observations(clips=clips, targets=1, points=1)
            scene.frame['ammo'] = (0, 30, 30)
            scene.frame['clip'] = 0
            scene.value(1, armor='unknown', line='pending')
            scene.value(2, armor='unknown', line='pending')
            result = scene.tick(0.)
            self.assertEqual('reload_clip' if clips > 1 else 'switch_shell', result['action'])
            self.assertEqual('current_ammunition_exhausted', result['reason'])
            self.assertEqual(1, result['shell_index'])
            self.assertFalse(result['early_reload'])
            self.assertIsNone(scene.policy.search_started)

    def test_normal_empty_clip_reload_does_not_require_visible_enemy(self):
        scene = Observations(clips=6, targets=0)
        scene.frame['clip'] = 0
        result = scene.tick(0.)
        self.assertEqual('reload_clip', result['action'])
        self.assertFalse(result['early_reload'])
        self.assertIsNone(scene.policy.search_started)

    def test_single_current_complete_failure_switches_only_verified_alternative(self):
        scene = Observations(targets=1)
        scene.passed(1)
        scene.prime()
        result = scene.tick(0.)
        self.assertEqual(('switch_shell', 1), (result['action'], result['shell_index']))
        self.assertIsNone(scene.policy.search_started)

    def test_epoch_survives_each_motion_target_route_and_rejected_navigation(self):
        scene = Observations(clips=6, targets=2)
        scene.tick(0.)
        deadline = scene.policy.decision['search_deadline']
        for step in range(1, 80):
            now = step * .1
            scene.frame['pose'] = ('source_motion', step)
            scene.move_target(1, step)
            scene.frame['targets'] = tuple(reversed(scene.frame['targets']))
            for index in range(3):
                for target in (1, 2):
                    for sample in (0, 1):
                        scene.value(index, target, sample, armor='unknown', line='pending')
            scene.policy.navigation_result(dict(status='rejected', route=step,
                                                 collision=True, progress=False))
            result = scene.tick(now)
            self.assertEqual('search_penetration', result['action'])
            self.assertEqual(deadline, result['move_request']['deadline'])
            self.assertEqual(0., scene.policy.search_started)
        result = scene.tick(8.)
        self.assertTrue(scene.policy.fallback)
        self.assertNotEqual('search_penetration', result['action'])

    def test_new_current_penetration_clears_search_even_when_now_blocked(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.tick(0.)
        scene.value(0, armor='passed', line='friendly_blocked')
        scene.frame['line_revision'] += 1
        result = scene.tick(1.)
        self.assertEqual('firing_position', result['action'])
        self.assertIsNone(scene.policy.search_started)

    def test_normal_firing_position_episode_not_reset_by_path_or_target(self):
        scene = Observations(targets=1, points=1)
        scene.value(0, line='world_blocked', armor='unknown')
        first = scene.tick(0.)['move_request']['episode_id']
        for step in range(1, 30):
            scene.frame['pose'] = ('move', step)
            result = scene.tick(step * .1)
            self.assertEqual(first, result['move_request']['episode_id'])
            self.assertIsNone(result['move_request']['deadline'])
        scene.policy.navigation_result(dict(status='timeout', fallback='ordinary_navigation'))
        self.assertEqual('ordinary_navigation', scene.policy.status()['navigation']['fallback'])
        self.assertIsNone(scene.policy.search_started)

    def test_replaced_gun_cannot_inherit_old_search_or_fallback_authority(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.tick(0.)
        scene.tick(8.)
        self.assertTrue(scene.policy.fallback)
        scene.frame['identity'] = ('round', 'replacement_gun')
        result = scene.tick(9.)
        self.assertFalse(scene.policy.fallback)
        self.assertEqual(9., scene.policy.search_started)
        self.assertEqual('search_penetration', result['action'])


class RebuiltAtomicClosureTests(unittest.TestCase):
    def test_continuously_rotating_target_gets_one_frame_complete_failure(self):
        scene = Observations(clips=6, targets=3, points=9)
        for step in range(30):
            for target in range(1, 4):
                scene.move_target(target, step)
            result = scene.tick(step * .1)
            self.assertEqual('search_penetration', result['action'])
            self.assertEqual(0., scene.policy.search_started)
        self.assertEqual(2, scene.atomic_calls)
        self.assertEqual('all_failed', scene.policy.status()['atomic']['status'])
        self.assertGreater(scene.policy.status()['atomic']['evaluations'], 2)

    def test_atomic_current_positive_stops_before_alternative_work(self):
        scene = Observations(points=9)
        scene.passed(0, sample=5)
        result = scene.tick(0., background=False)
        self.assertEqual('aim', result['action'])
        self.assertEqual(5, result['candidate']['sample'])
        self.assertFalse(any(row[1] == 'atomic' and row[2] != 0 for row in scene.calls))
        self.assertEqual('positive', scene.policy.status()['atomic']['status'])

    def test_atomic_pose_change_during_batch_discards_all_results(self):
        scene = Observations(clips=6, points=9)
        def change(channel):
            if channel == 'atomic':
                scene.move_target(1, 100)
        scene.on_evaluate = change
        result = scene.tick(0., background=False)
        self.assertEqual('wait', result['action'])
        self.assertEqual('pose_changed', scene.policy.status()['atomic']['status'])
        self.assertEqual({}, scene.policy.rows)
        self.assertIsNone(scene.policy.search_started)

    def test_unknown_inside_atomic_batch_never_grants_negative_certificate(self):
        scene = Observations(clips=6, points=9)
        scene.value(0, target=2, sample=8, armor='unknown', line='unknown')
        result = scene.tick(0.)
        self.assertEqual('incomplete', scene.policy.status()['atomic']['status'])
        self.assertIsNone(scene.policy.search_started)
        self.assertNotEqual('search_penetration', result['action'])

    def test_oversized_atomic_universe_is_unknown_not_a_truncated_success(self):
        scene = Observations(clips=1, targets=31, points=9)
        self.assertGreater(31 * 9 * 3, ATOMIC_MAX_JOBS)
        scene.tick(0.)
        self.assertEqual('domain_budget_exceeded', scene.policy.status()['atomic']['status'])
        self.assertIsNone(scene.policy.search_started)

    def test_foreground_and_background_keep_independent_budgets_after_atomic(self):
        scene = Observations(clips=6, points=9)
        scene.tick(0.)
        self.assertEqual(2, scene.policy._used['foreground'])
        self.assertEqual(2, scene.policy._used['background'])
        self.assertGreater(scene.policy._used['atomic'], 2)
        for step in range(1, 20):
            scene.tick(step * .1)
        self.assertEqual(1, scene.atomic_calls)

    def test_atomic_candidate_cap_never_starts_timer_for_partial_domain(self):
        scene = Observations(clips=6, targets=15, points=9)
        scene.policy.atomic_time_budget = 1.
        result = scene.tick(0.)
        self.assertLessEqual(scene.policy._used['atomic'], ATOMIC_CANDIDATES)
        self.assertIsNone(scene.policy.search_started)
        self.assertEqual('firing_position', result['action'])
        self.assertEqual('global_snapshot_budget_pending', result['reason'])

    def test_wall_clock_cap_is_checked_between_candidates_and_never_fake_failure(self):
        scene = Observations(clips=6, points=9)
        clock = [0.]
        scene.policy.atomic_clock = lambda: clock[0]
        def slow_native_boundary(channel):
            if channel == 'atomic':
                clock[0] += .003
        scene.on_evaluate = slow_native_boundary
        result = scene.tick(0.)
        self.assertLessEqual(scene.policy._used['atomic'], 3)
        self.assertIsNone(scene.policy.search_started)
        self.assertEqual('firing_position', result['action'])
        self.assertEqual('atomic_frame_budget_exhausted', scene.policy.status()['atomic']['reason'])


class RebuiltFallbackTests(unittest.TestCase):
    def fallback(self, scene):
        scene.tick(0.)
        scene.prime('he_fallback')
        return scene.tick(8.)

    def test_zero_damage_real_contact_is_executable_fallback(self):
        scene = Observations(targets=1, points=1)
        scene.frame['loaded'] = 2
        scene.he(0.)
        result = self.fallback(scene)
        self.assertEqual(('aim', 'he_fallback'), (result['action'], result['candidate']['mode']))
        self.assertEqual(0., result['candidate']['expected_damage'])
        self.assertTrue(scene.policy.fallback)

    def test_unknown_contact_cannot_be_promoted_to_zero_damage(self):
        scene = Observations(targets=1, points=1)
        scene.frame['loaded'] = 2
        scene.value(2, mode='he_fallback', contact=None, expected_damage=0.)
        result = self.fallback(scene)
        self.assertEqual('wait', result['action'])
        self.assertIsNone(scene.policy._best_he())

    def test_all_he_targets_and_points_compete_by_actual_damage(self):
        scene = Observations(targets=3, points=3)
        scene.frame['shells'] += (dict(index=3, is_he=True, piercing=140., signature=('he2', 1)),)
        scene.frame['ammo'] += (30,)
        scene.frame['loaded'] = 2
        scene.he(30., target=1)
        scene.he(110., target=3, sample=2)
        scene.he(135., index=3, target=2, sample=1)
        scene.prime()
        scene.tick(0.)
        scene.prime('he_fallback')
        result = scene.tick(8.)
        self.assertEqual(('switch_shell', 3, ('bot', 2), 1),
            (result['action'], result['shell_index'], result['candidate']['target_key'],
             result['candidate']['sample']))

    def test_he_clip_remains_useful_even_when_other_he_damage_is_higher(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.frame['loaded'] = 2
        scene.frame['shells'] += (dict(index=3, is_he=True, piercing=140., signature=('he2', 1)),)
        scene.frame['ammo'] += (30,)
        scene.he(0.)
        scene.he(150., index=3)
        result = self.fallback(scene)
        self.assertEqual(('aim', 2, 3),
            (result['action'], result['candidate']['shell_index'], result['next_shell']))

    def test_fallback_survives_many_triggers_failures_and_zero_outcomes(self):
        scene = Observations(clips=6, targets=2, points=2)
        scene.frame['loaded'] = 2
        scene.he(0.)
        self.fallback(scene)
        for trigger in range(30):
            scene.policy.shot_committed(dict(burst_index=0, burst_count=3, result='miss'), {})
            scene.frame['trigger_active'] = True
            scene.passed(1)
            result = scene.tick(8.1 + trigger)
            self.assertEqual('trigger_active', result['action'])
            self.assertTrue(scene.policy.fallback)
            scene.values.pop((1, ('bot', 1), 0, 'penetration'))
            for index in (1, 2):
                scene.policy.shot_committed(dict(burst_index=index, burst_count=3,
                    damage=0, result='not_penetrated'), {})
            scene.frame['trigger_active'] = False
            scene.policy.rows.clear()
            scene.prime('he_fallback')
            result = scene.tick(8.2 + trigger)
            self.assertEqual('aim', result['action'])
            self.assertEqual('he_fallback', result['candidate']['mode'])
            self.assertTrue(scene.policy.fallback)
            self.assertEqual(0., scene.policy.search_started)

    def test_new_penetration_only_exits_fallback_at_new_trigger(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.frame['loaded'] = 2
        scene.he(0.)
        self.fallback(scene)
        scene.frame['trigger_active'] = True
        scene.passed(1)
        scene.prime()
        self.assertEqual('trigger_active', scene.tick(8.1)['action'])
        scene.frame['trigger_active'] = False
        result = scene.tick(8.2)
        self.assertEqual(('reload_clip', 1), (result['action'], result['shell_index']))
        self.assertFalse(scene.policy.fallback)

    def test_no_he_is_retreat_only_after_search_not_after_one_failed_sample(self):
        scene = Observations(targets=1, points=1, he=False)
        self.assertEqual('search_penetration', scene.tick(0.)['action'])
        self.assertEqual('retreat', scene.tick(8.)['action'])


class LaunchGeometryDomainTests(unittest.TestCase):
    def test_invalid_launch_vectors_never_produce_zero_length_proofs(self):
        for velocity, gravity, maximum in (((0., 0., 0.), 0., 25.),
            ((0., 0., 100.), 0., 0.), ((0., 0., 100.), -1., 25.),
            ((float('nan'), 0., 100.), 0., 25.),
            ((0., 0., 100.), 0., float('inf'))):
            self.assertEqual(((), ()), TriggerAdmission._launch_path((0., 0., 0.),
                                                                    velocity, gravity, maximum))

    def test_valid_range_limited_launch_has_finite_terminal_path(self):
        path, times = TriggerAdmission._launch_path((0., 0., 0.), (0., 0., 100.), 0., 25.)
        self.assertAlmostEqual(25., path[-1][2])
        self.assertAlmostEqual(.25, times[-1])
        self.assertTrue(all(times[index + 1] > times[index] for index in range(len(times) - 1)))


import test_player_fire_admission_complete as native_fire


class NativeAtomicClosureTests(native_fire.AutomaticFireScene):
    def hardened_target(self):
        for name in ('chassis', 'hull', 'turret', 'gun'):
            for material in getattr(self.target.typeDescriptor, name).materials.values():
                material.armor = 10000.
        policy = self.runtime.attack_policy
        policy.reset()
        policy.evaluator.jobs.clear()
        # These tests assert pose/physics correctness, not the scheduler's
        # wall time under parallel CI. Production keeps its separate 8ms cap;
        # deterministic cap tests above check that branch without fake claims
        # about native Windows timing.
        policy.atomic_time_budget = .25
        return policy

    def test_actual_turret_keeps_rotating_between_frames_but_negative_domain_closes(self):
        policy = self.hardened_target()
        for step in range(25):
            self.target.appearance.turretMatrix.setRotateY(.01 * step)
            self.step(.1)
            result = policy.update(self.now)
            if step == 0:
                self.assertEqual('search_penetration', result['action'],
                                 (result, policy.status(), policy.rows))
                started = policy.search_started
                receipt = policy.status()['atomic']
                self.assertEqual('all_failed', receipt['status'])
                self.assertGreater(receipt['world_budget'], 0)
                self.assertLessEqual(receipt['world_chords'], receipt['world_budget'])
                self.assertGreater(receipt['evaluations'], 2)
                self.assertGreaterEqual(receipt['elapsed_ms'], 0.)
            self.assertEqual(started, policy.search_started)
            self.assertEqual(started + 8., result['search_deadline'])
            policy.background(self.now)

    def test_world_callback_native_pose_change_cannot_publish_global_failure(self):
        policy = self.hardened_target()
        def move_during_query():
            self.target.appearance.turretMatrix.setRotateY(.3)
        self.on_probe = move_during_query
        self.step(.1)
        result = policy.update(self.now)
        self.assertEqual('wait', result['action'])
        self.assertIsNone(policy.search_started)
        self.assertEqual('pose_changed', policy.status()['atomic']['status'])
        self.assertFalse(policy.rows)

    def test_native_source_turret_angle_expires_pose_even_with_same_muzzle(self):
        original = native_source_pose(self.runtime)
        self.battle._avatar.gunRotator.turretYaw += .03
        changed = native_source_pose(self.runtime)
        self.assertEqual(original[2], changed[2])
        self.assertNotEqual(original, changed)
        self.battle._avatar.gunRotator.turretYaw -= .03
        self.battle._avatar.gunRotator.gunPitch += .03
        self.assertNotEqual(original, native_source_pose(self.runtime))

    def test_native_gun_lay_preserves_the_unchanged_ideal_point_proof(self):
        policy = self.runtime.attack_policy
        self.lay(sample_index=0)
        first = self.candidate
        self.assertEqual('passed', first['armor'])
        physical_pose = policy.frame['pose']
        self.battle._avatar.gunRotator.gunPitch += .03
        self.step(.1)
        selected = policy.update(self.now)['candidate']
        self.assertNotEqual(physical_pose, policy.frame['pose'])
        self.assertEqual(first['key'], selected['key'])
        self.assertEqual(first['pose_stamp'], selected['pose_stamp'])
        self.assertEqual(0, policy.status()['foreground_queries'])

    def test_unmodelled_stock_slot_remains_unknown_in_global_ammo_domain(self):
        policy = self.hardened_target()
        gun = self.battle._gun_state
        gun.clip_size = gun.clip = 1
        gun.ammo = list(gun.ammo) + [20]
        self.step(.1)
        result = policy.update(self.now)
        self.assertEqual(len(gun.ammo), len(policy.frame['shells']))
        self.assertTrue(policy.frame['shells'][-1]['unavailable'])
        self.assertIsNone(policy.search_started)
        self.assertNotEqual('search_penetration', result['action'])

    def test_native_exact_atomic_budget_is_sum_of_actual_trajectories(self):
        policy = self.hardened_target()
        self.step(.1)
        frame = policy.evaluator.snapshot(self.now)
        policy.frame = frame
        jobs = policy._jobs(shell_index=frame['loaded'])
        required = sum(len(policy.evaluator._prediction(frame, shell, target, sample, mode)['path']) - 1
                       for key, shell, target, sample, mode in jobs)
        self.assertTrue(policy.evaluator.begin_atomic(frame, jobs, self.now))
        self.assertEqual(required, policy.evaluator.atomic_receipt['world_budget'])
        self.assertLess(required, ATOMIC_MAX_JOBS * 167)

    def test_fifteen_stable_enemies_three_shells_complete_in_bounded_frames(self):
        from gui.mods.offline_lan_0922.player_control.attack_policy import ATOMIC_WALL_SECONDS
        self.pose(self.target, (0., 0., 150.))
        for index in range(1, 15):
            self.vehicle(42 + index, ((index - 7) * 8., 0., 150.), 2)
        gun = self.battle._gun_state
        gun.shots = list(gun.shots) + [copy.deepcopy(gun.shots[0])]
        gun.shots[2].shell.compactDescr = 999
        gun.ammo = list(gun.ammo) + [30]
        gun.clip_size = gun.clip = 1
        for shot in gun.shots:
            shot.speed, shot.gravity, shot.maxDistance = 600., 9.81, 3000.
        for record in self.battle._records.values():
            target = self.battle._server_entity(record.get('engine_id'))
            if target is None or target is self.entity:
                continue
            for name in ('chassis', 'hull', 'turret', 'gun'):
                for material in getattr(target.typeDescriptor, name).materials.values():
                    material.armor = 10000.
        policy = self.runtime.attack_policy
        policy.reset()
        policy.atomic_time_budget = ATOMIC_WALL_SECONDS
        policy.evaluator.jobs.clear()
        policy.evaluator.predictions.clear()
        policy.evaluator.observations.clear()
        ordinary_navigation_requests = 0
        for step in range(500):
            self.step(.1)
            result = policy.update(self.now)
            receipt = policy.status()['atomic']
            self.assertLessEqual(receipt.get('world_chords', 0), ATOMIC_WORLD_QUERIES)
            self.assertLessEqual(receipt.get('armour_collision_batches', 0), ATOMIC_ARMOUR_BATCHES)
            self.assertLessEqual(policy._used['atomic'], ATOMIC_CANDIDATES)
            if result['action'] == 'firing_position':
                ordinary_navigation_requests += 1
                self.assertIn('move_request', result)
            policy.background(self.now)
            if policy.search_started is not None:
                break
        self.assertIsNotNone(policy.search_started, policy.status())
        self.assertGreater(ordinary_navigation_requests, 0)
        self.assertEqual(405, len(policy._jobs()))
        self.assertTrue(policy._all_failed((0, 1, 2)))
        self.assertGreater(step, 0)

    def test_last_native_lane_probe_cannot_change_target_pose_and_still_launch(self):
        geometry = self.runtime.geometry
        original = geometry._bot_friendly_path_verdict
        calls = []
        def native_probe_with_reentry(*args, **kwargs):
            result = original(*args, **kwargs)
            calls.append(True)
            # prepare + three physical transaction validation boundaries,
            # with a centre and sampled-lane native call at each boundary.
            if len(calls) == 8:
                self.target.appearance.turretMatrix.setRotateY(.2)
            return result
        geometry._bot_friendly_path_verdict = native_probe_with_reentry
        self.assertFalse(self.fire())
        self.assertGreaterEqual(len(calls), 8)
        self.assertEqual('auto_target_changed', self.control.last_fire_failure)
        self.assert_unspent()


if __name__ == '__main__':
    unittest.main()
