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
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import (
    AttackPolicy, NativeAttackEvaluator, ATOMIC_CLOSE_INTERVAL, ATOMIC_MAX_JOBS, ATOMIC_WORLD_QUERIES,
    ATOMIC_ARMOUR_BATCHES, ATOMIC_CANDIDATES, native_source_pose, limited_traverse)
from gui.mods.offline_lan_0922.vehicle_control.trigger_admission import TriggerAdmission


class Observations(object):
    def __init__(self, clips=1, targets=2, points=2, he=True, he_validation='full'):
        shells = [dict(index=0, is_he=False, piercing=200., signature=('ap', 1)),
                  dict(index=1, is_he=False, piercing=300., signature=('apcr', 1))]
        if he:
            # These historical complete-domain tests exercise the reviewed
            # L7 HESH role. Ordinary HE tests request single_point explicitly.
            shells.append(dict(index=2, is_he=True,
                piercing=210. if he_validation == 'full' else 100., signature=('he', 1),
                validation_mode=he_validation, gun_identity='uk:_105mm_Gun_L7',
                shell_identity=('uk:_105mm_HESH_L7' if he_validation == 'full' else
                                'uk:_105mm_HE_L7')))
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
                frame['targets'], frame['shells'], frame.get('combat_signature')) == (
                self.frame['identity'], self.frame['pose'], self.frame['scene'],
                self.frame['line_revision'], self.frame['targets'], self.frame['shells'],
                self.frame.get('combat_signature'))

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

    def tick(self, now, background=True, navigation='accepted'):
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
    def test_existing_green_point_precedes_any_new_foreground_query(self):
        scene = Observations(targets=6, points=2, he=False)
        policy = scene.policy
        scene.passed(target=6, sample=1)
        policy.frame = scene.snapshot(0.)
        key = (0, ('bot', 6), 1, 'penetration')
        job = next(job for job in policy._jobs(shell_index=0) if job[0] == key)
        policy._evaluate(job, 0., 'background')
        scene.calls.clear()

        decision = policy.update(.05)

        self.assertEqual('aim', decision['action'])
        self.assertEqual(key, decision['candidate']['key'])
        self.assertEqual([], scene.calls)

    def test_exhausted_inventory_returns_to_existing_navigation_without_retreat(self):
        scene = Observations()
        scene.frame['ammo'] = (0, 0, 0)
        decision = scene.tick(0.)
        self.assertEqual(('navigate', 'ammunition_exhausted'),
                         (decision['action'], decision['reason']))
        self.assertEqual([], scene.calls)
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertIsNone(scene.policy.reload_authority)
        original = dict(combat_mode='route', move_position=(30., 0., 50.),
            face_position=(10., 0., 80.), throttle_override=1., route_index=3)
        order = scene.policy.apply_order(original)
        for name, value in original.items():
            self.assertEqual(value, order[name])
        self.assertFalse(order['fire_allowed'])

    def test_first_current_point_is_ready_without_taking_movement_ownership(self):
        scene = Observations()
        scene.passed()
        result = scene.tick(0., background=False)
        self.assertEqual('aim', result['action'])
        self.assertEqual(1, len(scene.calls))
        self.assertEqual('foreground', scene.calls[0][1])
        self.assertEqual(0, scene.atomic_calls)
        order = scene.policy.apply_order(dict(move_position=(30., 0., 50.), throttle_override=1.))
        self.assertEqual((30., 0., 50.), order['move_position'])
        self.assertEqual(1., order['throttle_override'])
        self.assertNotIn('combat_mode', order)
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
                self.assertFalse(hasattr(scene.policy, 'search_started'))

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
                self.assertFalse(hasattr(scene.policy, 'search_started'))
                self.assertNotIn('shell_index', result)
                self.assertEqual(1, len(scene.invalidated))

    def test_native_lane_refusal_survives_source_refresh_and_yields_to_other_points(self):
        cases = ((False, 'auto_lane_geometry_unknown'), (True, 'auto_lane_geometry_unknown'),
                 (False, 'auto_front_vehicle'), (True, 'auto_front_vehicle'))
        for alternate, refusal in cases:
            with self.subTest(alternate=alternate, refusal=refusal):
                scene = Observations(targets=1, points=2)
                scene.passed()
                scene.passed(1)
                first = scene.tick(0.)['candidate']
                scene.policy.load_started(0, first)
                scene.policy.admission_failed(first, refusal)
                if alternate:
                    scene.passed(0, sample=1)
                for step in range(1, 10):
                    scene.frame['pose'] = ('source', 1.e-8 * step)
                    result = scene.tick(.1 * step)
                    if alternate:
                        self.assertEqual(('aim', 1), (result['action'], result['candidate']['sample']))
                    else:
                        self.assertEqual('wait', result['action'])
                        refused = scene.policy.rows[first['key']]
                        self.assertEqual(('unknown', 'passed'),
                                         (refused['line'], refused['armor']))
                        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
                    self.assertFalse(hasattr(scene.policy, 'search_started'))
                if not alternate:
                    scene.frame['pose'] = ('source', 1.e-7)
                    result = scene.tick(ATOMIC_CLOSE_INTERVAL)
                    self.assertEqual(('aim', 0), (result['action'], result['candidate']['sample']))
                    scene.policy.admission_failed(result['candidate'], refusal)
                    scene.frame['line_revision'] += 1
                    result = scene.tick(ATOMIC_CLOSE_INTERVAL + .1)
                    self.assertEqual(('aim', 0), (result['action'], result['candidate']['sample']))

    def test_blocked_current_ap_keeps_usage_even_when_apcr_is_executable(self):
        scene = Observations(targets=1, points=1)
        scene.value(0, armor='passed', line='world_blocked')
        scene.passed(1)
        scene.prime()
        result = scene.tick(0.)
        self.assertEqual(('firing_position', 0),
                         (result['action'], result['candidate']['shell_index']))
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_repeated_refusals_do_not_turn_query_age_into_movement_authority(self):
        for refusal in ('auto_front_vehicle', 'auto_lane_geometry_unknown'):
            with self.subTest(refusal=refusal):
                scene = Observations(targets=5, points=9)
                for target in range(1, 6):
                    for sample in range(9):
                        scene.passed(target=target, sample=sample)
                attempted = set()
                for step in range(61):
                    now = step / 5.
                    scene.frame['pose'] = ('source', 1.e-8 * step)
                    result = scene.tick(now)
                    self.assertEqual('aim', result['action'])
                    point = result['candidate']
                    attempted.add(point['key'])
                    scene.policy.admission_failed(point, refusal)

                self.assertGreater(len(attempted), 1)
                self.assertEqual(('aim', 'current_shell_verified'),
                                 (result['action'], result['reason']))
                self.assertFalse(hasattr(scene.policy, 'search_started'))
                self.assertNotIn('move_request', result)

    def test_committed_alternative_clears_native_refusal_wait(self):
        scene = Observations(targets=1, points=3)
        for sample in range(3):
            scene.passed(sample=sample)
        first = scene.tick(0.)['candidate']
        scene.policy.admission_failed(first, 'auto_front_vehicle')
        alternative = scene.tick(1.9)
        self.assertEqual('aim', alternative['action'])
        self.assertNotEqual(first['sample'], alternative['candidate']['sample'])
        scene.policy.shot_committed({}, {})
        point = scene.tick(2.2)['candidate']
        scene.policy.admission_failed(point, 'auto_front_vehicle')
        self.assertEqual('aim', scene.tick(2.3)['action'])

    def test_physical_lane_receipt_not_a_timer_owns_recovery(self):
        for departed in (False, True):
            with self.subTest(departed=departed):
                scene = Observations(targets=1, points=1)
                scene.frame['search_drive'] = True
                scene.passed()
                point = scene.tick(0.)['candidate']
                scene.policy.admission_failed(point, 'auto_front_vehicle',
                    dict(kind='vehicle', vehicle_id=8, hostile=True, actor_key=('bot', 8)))
                scene.value(0, armor='passed', line='enemy_blocked')
                entered = scene.tick(.1)
                self.assertEqual('current_penetration_obstructed', entered['reason'])
                scene.policy.navigation_result(dict(
                    action='firing_position', status='accepted', turn=1.,
                    position=(0., 0., 0.), at=.1))
                parked = scene.tick(8.)
                self.assertEqual('firing_position', parked['action'])
                self.assertEqual(entered['move_request']['episode_id'],
                                 parked['move_request']['episode_id'])
                self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
                if departed:
                    scene.frame['position'] = (2., 0., 0.)
                    scene.frame['pose'] = ('source', 1)
                else:
                    scene.frame['line_revision'] += 1
                scene.passed()
                self.assertEqual('aim', scene.tick(8.1)['action'])
                self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_copied_other_sample_refusal_does_not_override_verified_sample(self):
        scene = Observations()
        scene.passed(0, sample=1)
        scene.tick(0.)
        selected = scene.policy.decision['candidate']['target']
        order = scene.policy.apply_order({})
        command, target = scene.policy.select_command({}, dict(order, fire_allowed=False), selected, 0.)
        self.assertTrue(command['fire_allowed'])
        self.assertEqual(101, target['id'])

    def test_shooting_intent_preserves_every_solved_movement_field(self):
        scene = Observations()
        scene.passed()
        scene.tick(0.)
        movement = dict(move_position=(30., 0., 50.), throttle_override=.75,
            throttle=.8, turn=-.25, brake=False, combat_mode='route',
            route_id='default', path=((0., 0., 0.), (30., 0., 50.)))
        applied = scene.policy.apply_order(movement)
        selected = scene.policy.decision['candidate']['target']
        command, target = scene.policy.select_command({}, applied, selected, 0.)
        self.assertIs(selected, target)
        for key, value in movement.items():
            self.assertEqual(value, applied[key], key)
            self.assertEqual(value, command[key], key)
        self.assertNotIn('fire_allowed', movement)
        self.assertTrue(command['fire_allowed'])

    def test_stationary_review_only_closes_fire_without_parking_or_erasing_contact(self):
        scene = Observations()
        scene.tick(0.)
        scene.policy.decision = dict(action='wait',
            reason='stationary_domain_review_pending', candidate=None)
        target = scene.frame['targets'][0]['value']
        order = dict(move_position=(30., 0., 50.), throttle_override=.75,
            throttle=.8, turn=-.25, brake=False, combat_mode='route',
            target_id=target['network_id'], target_kind=target['kind'],
            face_position=target['position'], fire_allowed=True,
            aim_position=(0., 1., 20.), _player_attack_solution={'stale': True})
        applied = scene.policy.apply_order(order)
        command, selected = scene.policy.select_command({}, order, target, 0.)
        self.assertIs(target, selected)
        for result in (applied, command):
            for key in ('move_position', 'throttle_override', 'throttle', 'turn',
                        'brake', 'combat_mode', 'target_id', 'target_kind', 'face_position'):
                self.assertEqual(order[key], result[key], key)
            self.assertIsNone(result['aim_position'])
            self.assertFalse(result['fire_allowed'])
            self.assertNotIn('_player_attack_solution', result)
        self.assertTrue(order['fire_allowed'])

    def test_late_shooting_callback_cannot_retarget_driver_or_create_contact(self):
        scene = Observations()
        scene.passed(target=2)
        scene.tick(0.)
        for target in (None, scene.frame['targets'][0]['value']):
            with self.subTest(target=target):
                order = dict(target_id=target['id'] if target else None,
                    target_kind=target['kind'] if target else None,
                    throttle=.8, turn=-.25, brake=False,
                    aim_position=(5., 1., 20.), fire_allowed=True)
                command, selected = scene.policy.select_command({}, order, target, 0.)
                self.assertIs(target, selected)
                self.assertEqual(order['target_id'], command['target_id'])
                self.assertEqual(order['target_kind'], command['target_kind'])
                self.assertEqual(order['aim_position'], command['aim_position'])
                self.assertEqual((.8, -.25, False),
                    (command['throttle'], command['turn'], command['brake']))
                self.assertFalse(command['fire_allowed'])
                self.assertNotIn('_player_attack_solution', command)

    def test_late_shooting_callback_rejects_mismatched_command_identity(self):
        scene = Observations()
        scene.passed()
        scene.tick(0.)
        target = scene.policy.decision['candidate']['target']
        for identity in (dict(target_id=999, target_kind='bot'),
                         dict(target_id=target['id'], target_kind='human')):
            command, selected = scene.policy.select_command({},
                dict(identity, fire_allowed=True), target, 0.)
            self.assertIs(target, selected)
            self.assertFalse(command['fire_allowed'])
            for key, value in identity.items():
                self.assertEqual(value, command[key])

    def test_current_selection_stays_stable_across_committed_triggers(self):
        scene = Observations()
        scene.passed(0, target=2, sample=1)
        scene.prime(index=0)
        first = scene.tick(0.)['candidate']
        scene.passed(0, target=1, sample=0)
        scene.prime(index=0)
        second = scene.tick(.1)['candidate']
        self.assertEqual(first['key'], second['key'])
        scene.policy.shot_committed(dict(burst_index=0, burst_count=1), {})
        self.assertEqual(first['key'], scene.policy.selected)
        self.assertIsNone(scene.policy.trigger)
        self.assertEqual(first['key'], scene.tick(.2)['candidate']['key'])
        # The intention is not a stale firing certificate. Changed armour
        # retires its evidence and lets the next legal point take over.
        scene.move_target(2, 1)
        scene.value(0, target=2, sample=1, armor='failed')
        self.assertEqual(('bot', 1), scene.tick(.3)['candidate']['target_key'])

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

    def test_ranked_scan_keeps_current_fire_and_does_not_publish_lower_pending_plan(self):
        scene = Observations(targets=2, points=2)
        scene.passed(0)
        scene.passed(2, target=2, sample=1)
        first = scene.tick(0.)
        self.assertEqual('aim', first['action'])
        self.assertEqual(0, first['candidate']['shell_index'])
        self.assertIsNone(scene.policy.next_shell)
        self.assertEqual('higher_rank_pending', scene.policy.next_status)
        scene.tick(.1)
        self.assertEqual(2, scene.policy.next_shell)
        self.assertEqual(('bot', 2), scene.policy.next_plan['target_key'])

    def test_last_stocked_current_round_is_not_ranked_for_the_next_load(self):
        scene = Observations(targets=1, points=1)
        scene.frame['ammo'] = (1, 10, 10)
        scene.passed(0)
        scene.passed(1)
        scene.prime()
        self.assertEqual(0, scene.tick(0.)['candidate']['shell_index'])
        self.assertEqual(1, scene.policy.next_shell)

    def test_background_next_target_cannot_steal_valid_current_point(self):
        scene = Observations(targets=2, points=1)
        scene.frame['shells'][1]['piercing'] = 150.
        scene.passed(0, target=1)
        scene.passed(0, target=2)
        scene.passed(1, target=2)
        scene.prime()
        first = scene.tick(0.)['candidate']
        self.assertEqual(('bot', 1), first['target_key'])
        self.assertEqual(('bot', 2), scene.policy.next_plan['target_key'])
        for now in (.1, .5, 1., 3., 9.):
            result = scene.tick(now)
            self.assertEqual('aim', result['action'])
            self.assertEqual(first['key'], result['candidate']['key'])
            self.assertEqual(first['pose_stamp'], result['candidate']['pose_stamp'])
            self.assertEqual(('bot', 2), scene.policy.next_plan['target_key'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_current_retention_releases_on_dead_target_or_real_line_change(self):
        for reason in ('dead', 'blocked', 'armour_changed'):
            with self.subTest(reason=reason):
                scene = Observations(targets=2, points=1)
                scene.passed(0, target=1)
                scene.passed(0, target=2)
                scene.prime()
                first = scene.tick(0.)['candidate']
                self.assertEqual(('bot', 1), first['target_key'])
                if reason == 'dead':
                    scene.frame['targets'] = scene.frame['targets'][1:]
                elif reason == 'blocked':
                    scene.frame['line_revision'] += 1
                    scene.value(0, target=1, armor='passed', line='world_blocked')
                else:
                    scene.move_target(1, 1)
                    scene.value(0, target=1, armor='failed')
                result = scene.tick(.1)
                self.assertEqual('aim', result['action'])
                self.assertEqual(('bot', 2), result['candidate']['target_key'])
                self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_next_preparation_revalidates_expired_point_in_its_ammunition_rank(self):
        scene = Observations(targets=2, points=5)
        # Exercise the background backstop when the frame has only a fair
        # background slot and cannot reserve a ranked recheck.
        scene.policy.background_budget = 1
        scene.passed(0)
        scene.passed(2, target=2, sample=4)
        scene.prime()
        scene.tick(0.)
        old = scene.policy.next_plan
        self.assertEqual((2, ('bot', 2), 4, 'penetration'), old['key'])
        scene.frame['line_revision'] += 1
        self.assertEqual(0, scene.tick(.1)['candidate']['shell_index'])
        self.assertIsNone(scene.policy.next_plan)
        self.assertIsNone(scene.policy.current_row(old))
        scene.policy.atomic_clock = lambda: 0.
        renewed, status = scene.policy.prepare_next_load(.1)
        self.assertEqual('verified', status)
        self.assertEqual(old['key'], renewed['key'])
        self.assertNotEqual(old['line_stamp'], renewed['line_stamp'])
        self.assertEqual([(2, ('bot', 2), 4, 'penetration')],
                         [call[2:] for call in scene.calls if call[:2] == (.1, 'atomic')])

    def test_next_preparation_keeps_lower_plan_pending_when_higher_rank_unresolved(self):
        for he, first_rank in ((True, 2), (False, 1)):
            with self.subTest(he=he):
                scene = Observations(targets=2, points=5, he=he)
                if not he:
                    scene.frame['shells'][first_rank]['piercing'] = 150.
                scene.passed(0)
                scene.prime()
                scene.tick(0.)
                self.assertEqual(0, scene.policy.next_shell)
                scene.frame['line_revision'] += 1
                for sample in range(5):
                    scene.value(first_rank, sample=sample, armor='pending', line='pending')
                scene.tick(.1)
                scene.policy.atomic_clock = lambda: 0.
                self.assertEqual((None, 'higher_rank_pending'), scene.policy.prepare_next_load(.1))
                probes = [call for call in scene.calls if call[:2] == (.1, 'atomic')]
                self.assertTrue(probes)
                self.assertEqual({first_rank}, set(call[2] for call in probes))

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
                    self.assertFalse(hasattr(scene.policy, 'search_started'))
                    self.assertFalse(scene.policy.fallback)

    def test_missing_one_target_prevents_other_targets_from_granting_global_timer(self):
        scene = Observations(targets=3)
        scene.frame['targets'][2]['pose'] = None
        scene.prime()
        result = scene.tick(0.)
        self.assertNotEqual('search_penetration', result['action'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))

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
            self.assertFalse(hasattr(scene.policy, 'search_started'))
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
    def test_expired_blocker_cannot_create_a_firing_position_request(self):
        scene = Observations(targets=1, points=3)
        scene.value(0, sample=2, armor='passed', line='friendly_blocked',
                    blocker=dict(blocker_kind='bot', blocker_id=22))
        scene.prime(index=0)
        scene.frame['line_revision'] = 1
        scene.value(0, sample=2, armor='unknown', line='pending')
        result = scene.tick(.1, background=False)
        self.assertEqual('wait', result['action'])
        self.assertNotIn('move_request', result)
        self.assertFalse(hasattr(scene.policy, 'search_started'))

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
        self.assertEqual('preaim', result['action'])
        self.assertEqual(first['pose_stamp'], candidate['pose_stamp'])
        self.assertNotEqual(first['line_stamp'], candidate['line_stamp'])
        self.assertEqual(('passed', 'pending'), (candidate['armor'], candidate['line']))
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_missing_evidence_never_grants_firing_position_authority(self):
        scene = Observations(targets=1, points=1, he=False)
        scene.allow_atomic = False
        for index in (0, 1):
            scene.value(index, armor='unknown', line='unknown')
        self.assertEqual('wait', scene.tick(0.)['action'])
        for now in (.5, 1., 1.5, 2., 3., 10., 76.):
            scene.move_target(1, now)
            result = scene.tick(now)
            self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertEqual('wait', result['action'])
        self.assertNotIn('move_request', result)
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
            self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertLessEqual(len(scene.policy.rows), 3)

    def test_pending_line_preserves_same_pose_armour_but_not_false_executability(self):
        scene = Observations(targets=1, points=1)
        scene.passed()
        first = scene.tick(0.)['candidate']
        scene.frame['line_revision'] += 1
        scene.value(0, armor='unknown', line='pending')
        result = scene.tick(.1)
        self.assertEqual('preaim', result['action'])
        self.assertEqual(first['pose_stamp'], result['candidate']['pose_stamp'])
        self.assertEqual('passed', result['candidate']['armor'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))

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

    def test_scattered_world_hit_does_not_turn_a_clear_centre_into_a_move_request(self):
        scene = Observations(targets=1, points=1)
        scene.passed(0)
        candidate = scene.tick(0.)['candidate']
        scene.policy.admission_failed(candidate, 'auto_world_blocked',
            dict(kind='world', ray_stage='scatter'))
        self.assertEqual('clear', scene.policy.rows[candidate['key']]['line'])
        self.assertEqual(candidate['key'], scene.policy.selected)
        self.assertNotIn(candidate['key'], scene.policy._admission_blocks)
        self.assertEqual([], scene.invalidated)
        self.assertEqual('aim', scene.tick(.1)['action'])

        blocked = Observations(targets=1, points=1)
        blocked.passed(0)
        actual = blocked.tick(0.)['candidate']
        blocked.policy.admission_failed(actual, 'auto_world_blocked',
            dict(kind='world', ray_stage='centre'))
        self.assertEqual('world_blocked', blocked.policy.rows[actual['key']]['line'])
        self.assertIsNone(blocked.policy.selected)
        self.assertIn(actual['key'], blocked.policy._admission_blocks)
        self.assertEqual([actual['key']], blocked.invalidated)

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
            self.assertFalse(hasattr(scene.policy, 'search_started'))
        scene.frame['line_revision'] += 1
        self.assertEqual('aim', scene.tick(2.)['action'])


class RebuiltSearchAndClipTests(unittest.TestCase):
    def test_new_combat_domain_cannot_reuse_an_old_point_recovery_request(self):
        scene = Observations(targets=1, points=1, he=False)
        scene.value(0, line='world_blocked', armor='unknown')
        scene.frame['combat_signature'] = ('admitted', 1)
        first = scene.tick(0., navigation=None)['move_request']['episode_id']
        scene.frame['combat_signature'] = ('admitted', 2)
        scene.tick(1., navigation=None)
        second = scene.tick(2.01, navigation=None)['move_request']['episode_id']
        self.assertNotEqual(first, second)
        self.assertEqual('firing_position', scene.policy.decision['action'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertFalse(hasattr(scene.policy, 'search_authority'))

    def test_no_he_exits_immediately_without_route_refusal_or_eight_second_clock(self):
        scene = Observations(targets=1, points=1, he=False)
        first = scene.tick(0., navigation=None)
        self.assertEqual(('navigate', 'no_he_or_verified_penetration'),
                         (first['action'], first['reason']))
        for now in (1., 8., 12., 21.):
            result = scene.tick(now, navigation=None)
            self.assertEqual('navigate', result['action'])
            self.assertNotIn('move_request', result)
            self.assertFalse(hasattr(scene.policy, 'search_started'))

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
                scene.policy.load_started(2, plan)
                scene.policy._plan_next(scene.policy._best_penetration(exclude=2))
                scene.passed(2, 1, 0)
                other = next(job for job in scene.policy._jobs(shell_index=2)
                             if job[0] == (2, ('bot', 1), 0, 'penetration'))
                scene.policy._evaluate(other, .05, 'background')
                scene.frame.update(loaded=2, clip=0, reloading=True)
                preaim = scene.tick(.1)
                self.assertEqual('preaiming', preaim['phase'])
                self.assertEqual(plan['key'], preaim['candidate']['key'])
                self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
                scene.frame.update(clip=clip_size, reloading=False)
                ready = scene.tick(.2)
                self.assertEqual(plan['key'], ready['candidate']['key'])
                self.assertTrue(scene.policy.apply_order({})['fire_allowed'])

    def test_both_single_and_magazine_require_the_all_ammo_domain(self):
        for clips in (1, 6):
            scene = Observations(clips=clips, targets=1, points=2)
            scene.value(1, armor='pending', line='pending')
            result = scene.tick(0.)
            self.assertNotEqual('search_penetration', result['action'])
            self.assertFalse(hasattr(scene.policy, 'search_authority'))

    def test_failed_magazine_reloads_verified_alternative_without_penetration_search(self):
        scene = Observations(clips=6, targets=1, points=2)
        scene.passed(1)
        scene.prime()
        result = scene.tick(0.)
        self.assertEqual(('reload_clip', 1, True),
                         (result['action'], result['shell_index'], result['early_reload']))
        self.assertEqual(6, scene.frame['clip'], 'policy cannot mutate physical ammunition')
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_empty_clip_reloads_without_eight_second_attempt(self):
        scene = Observations(clips=6)
        scene.frame['clip'] = 0
        scene.passed(1)
        scene.prime()
        result = scene.tick(0.)
        self.assertEqual('reload_clip', result['action'])
        self.assertFalse(result['early_reload'])
        self.assertEqual(1, result['shell_index'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))

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
            self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_normal_empty_clip_reload_does_not_require_visible_enemy(self):
        scene = Observations(clips=6, targets=0)
        scene.frame['clip'] = 0
        result = scene.tick(0.)
        self.assertEqual('reload_clip', result['action'])
        self.assertFalse(result['early_reload'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_single_current_complete_failure_switches_only_verified_alternative(self):
        scene = Observations(targets=1)
        scene.passed(1)
        scene.prime()
        result = scene.tick(0.)
        self.assertEqual(('switch_shell', 1), (result['action'], result['shell_index']))
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_moving_unknown_domain_never_invents_a_failure_or_movement_epoch(self):
        scene = Observations(clips=6, targets=2)
        scene.tick(0.)
        for step in range(1, 80):
            now = step * .1
            scene.frame['pose'] = ('source_motion', step)
            scene.move_target(1, step)
            scene.frame['targets'] = tuple(reversed(scene.frame['targets']))
            for index in range(3):
                for target in (1, 2):
                    for sample in (0, 1):
                        scene.value(index, target, sample, armor='unknown', line='pending')
            result = scene.tick(now, navigation='path_refused')
            self.assertEqual('wait', result['action'])
            self.assertNotIn('move_request', result)
            self.assertFalse(hasattr(scene.policy, 'search_started'))
            self.assertFalse(scene.policy._all_failed((0, 1, 2)))

    def test_new_current_penetration_clears_search_even_when_now_blocked(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.tick(0.)
        scene.value(0, armor='passed', line='friendly_blocked')
        scene.frame['line_revision'] += 1
        result = scene.tick(1.)
        self.assertEqual('firing_position', result['action'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_normal_firing_position_episode_not_reset_by_path_or_target(self):
        scene = Observations(targets=1, points=1)
        scene.value(0, line='world_blocked', armor='unknown')
        first = scene.tick(0.)['move_request']['episode_id']
        for step in range(1, 30):
            scene.frame['pose'] = ('move', step)
            result = scene.tick(step * .1)
            self.assertEqual(first, result['move_request']['episode_id'])
            self.assertEqual('firing_position', result['move_request']['kind'])
            self.assertNotIn('deadline', result['move_request'])
        scene.policy.navigation_result(dict(status='timeout', fallback='ordinary_navigation'))
        self.assertEqual('ordinary_navigation', scene.policy.status()['navigation']['fallback'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_replaced_gun_reproves_current_fallback_without_old_geometry_authority(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.tick(0.)
        scene.tick(8.)
        self.assertTrue(scene.policy.fallback)
        scene.frame['identity'] = ('round', 'replacement_gun')
        result = scene.tick(9.)
        self.assertEqual('wait', result['action'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertTrue(all(row['pose_stamp'][0] == scene.frame['identity']
                            for row in scene.policy.rows.values()))


class RebuiltAtomicClosureTests(unittest.TestCase):
    def test_continuously_rotating_target_gets_one_frame_complete_failure(self):
        scene = Observations(clips=6, targets=1, points=9)
        for step in range(30):
            for target in range(1, 2):
                scene.move_target(target, step)
            result = scene.tick(step * .1)
            self.assertEqual('wait', result['action'])
            self.assertFalse(hasattr(scene.policy, 'search_started'))
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
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_unknown_inside_atomic_batch_never_grants_negative_certificate(self):
        scene = Observations(clips=6, points=9)
        scene.value(0, target=2, sample=8, armor='unknown', line='unknown')
        result = scene.tick(0.)
        self.assertEqual('incomplete', scene.policy.status()['atomic']['status'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertNotEqual('search_penetration', result['action'])

    def test_pending_he_point_does_not_delay_proving_the_other_points(self):
        scene = Observations(clips=3, targets=1, points=9)
        scene.frame['loaded'] = 2
        scene.value(2, sample=2, armor='unknown', line='pending')
        scene.he(0.)

        result = scene.tick(0., background=False)
        self.assertNotEqual('search_penetration', result['action'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        receipt = scene.policy.status()['atomic']
        self.assertEqual('incomplete', receipt['status'])
        self.assertEqual('pending', receipt['first_unresolved']['line'])

        scene.value(2, sample=2)
        result = scene.tick(.1, background=False, navigation='path_refused')
        self.assertNotEqual('search_penetration', result['action'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertEqual(1, scene.atomic_calls)

        scene.prime('he_fallback', index=2)
        result = scene.tick(.2, background=False)
        self.assertEqual(('aim', 'current_he_clip_fallback'),
                         (result['action'], result['reason']))
        self.assertEqual(2, result['candidate']['shell_index'])
        self.assertEqual(0., result['candidate']['expected_damage'])

    def test_first_blocked_point_does_not_hide_later_usable_he_point(self):
        scene = Observations(clips=3, targets=15, points=9)
        scene.frame['loaded'] = 2
        scene.value(2, sample=0, armor='unknown', line='world_blocked')
        scene.passed(2, sample=5)
        result = scene.tick(0., background=False)
        self.assertEqual(('aim', 5), (result['action'], result['candidate']['sample']))
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_oversized_atomic_universe_is_unknown_not_a_truncated_success(self):
        scene = Observations(clips=1, targets=31, points=9)
        self.assertGreater(31 * 9 * 3, ATOMIC_MAX_JOBS)
        scene.tick(0.)
        self.assertEqual('domain_budget_exceeded', scene.policy.status()['atomic']['status'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))

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
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertEqual('wait', result['action'])
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
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertEqual('wait', result['action'])
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

    def test_loaded_he_penetration_is_not_stolen_by_background_damage_rank(self):
        for clip in (1, 6):
            with self.subTest(clip=clip):
                scene = Observations(clips=clip, targets=2, points=1)
                scene.frame['loaded'] = 2
                scene.frame['ammo'] = (0, 0, 30)
                scene.passed(2, target=1)
                scene.prime()
                first = scene.tick(0.)['candidate']
                self.assertEqual(('bot', 1), first['target_key'])
                scene.he(150., target=2)
                scene.prime('he_fallback')
                for now in (.1, .5, 1.):
                    result = scene.tick(now)
                    self.assertEqual('aim', result['action'])
                    self.assertEqual(first['key'], result['candidate']['key'])
                    self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_unknown_contact_cannot_be_promoted_to_zero_damage(self):
        scene = Observations(targets=1, points=1)
        scene.frame['loaded'] = 2
        scene.value(2, mode='he_fallback', contact=None, expected_damage=0.)
        result = self.fallback(scene)
        self.assertEqual('wait', result['action'])
        self.assertIsNone(scene.policy._best_he())

    def test_current_he_chooses_highest_observed_damage_without_a_search_clock(self):
        scene = Observations(clips=6, targets=3, points=3, he_validation='single_point')
        scene.allow_atomic = False
        scene.frame.update(loaded=2, ammo=(0, 0, 30))
        scene.he(0.)
        scene.he(140., target=3, sample=0)
        # Prime the measured contacts before the first current-HE decision.
        # Incomplete competitors cannot hold an otherwise executable round.
        scene.prime()
        scene.prime('he_fallback', 2)
        decision = scene.tick(0., background=False)
        self.assertTrue(scene.policy._single_point_failed(2),
                        'each enemy completed exactly one ordinary HE armour trial')
        self.assertEqual(('aim', ('bot', 3), 0, 140.),
            (decision['action'], decision['candidate']['target_key'],
             decision['candidate']['sample'], decision['candidate']['expected_damage']))
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertEqual(0, scene.policy.status()['he_comparison']['pending'])

    def test_unavailable_he_contact_is_not_ranked_as_zero_or_allowed_to_starve_valid_damage(self):
        scene = Observations(clips=3, targets=2, points=1, he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(0, 0, 30))
        scene.he(20.)
        scene.value(2, target=2, mode='he_fallback', armor='unknown',
                    line='unknown', contact=None, expected_damage=None)
        for step in range(8):
            decision = scene.tick(step * .1)
            if decision['action'] == 'aim':
                break
        self.assertEqual(('aim', ('bot', 1), 20.),
            (decision['action'], decision['candidate']['target_key'],
             decision['candidate']['expected_damage']))
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertEqual(1, len(scene.policy._rows_for('he_fallback', executable=True)))

    def test_all_he_targets_and_points_compete_by_actual_damage(self):
        scene = Observations(targets=3, points=3)
        scene.frame['shells'] += (dict(index=3, is_he=True, piercing=140.,
            signature=('hesh', 1), validation_mode='full',
            gun_identity='uk:_105mm_Gun_L7', shell_identity='uk:_105mm_HESH_L7'),)
        scene.frame['ammo'] += (30,)
        scene.frame['loaded'] = 2
        scene.he(30., target=1)
        scene.he(110., target=3, sample=2)
        scene.he(135., index=3, target=2, sample=1)
        scene.prime()
        scene.prime('he_fallback')
        # A loaded round picks its best *measured* current contact. A NEXT
        # load remains independent, even if another HE shell ranks higher.
        result = scene.tick(0.)
        self.assertEqual(('aim', 2, ('bot', 3), 2),
            (result['action'], result['candidate']['shell_index'], result['candidate']['target_key'],
             result['candidate']['sample']))
        self.assertEqual(3, scene.policy.next_shell)

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
            scene.prime(index=2)
            scene.prime('he_fallback')
            result = scene.tick(8.2 + trigger)
            self.assertEqual('aim', result['action'])
            self.assertEqual('he_fallback', result['candidate']['mode'])
            self.assertTrue(scene.policy.fallback)
            self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_other_shell_penetration_never_discards_loaded_he_even_at_new_trigger(self):
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
        self.assertEqual(('aim', 2), (result['action'], result['candidate']['shell_index']))
        self.assertTrue(scene.policy.fallback)
        self.assertEqual(1, scene.policy.next_shell)

    def test_no_he_returns_to_navigation_immediately_after_verified_failure(self):
        scene = Observations(targets=1, points=1, he=False)
        self.assertEqual('navigate', scene.tick(0.)['action'])
        self.assertEqual('navigate', scene.tick(8.)['action'])


class IndependentAmmoTraverseTests(unittest.TestCase):
    def test_installed_yaw_span_not_vehicle_name_clip_or_siege_decides_exception(self):
        for limits, expected in ((None, False), ((-math.pi, math.pi), False),
                ((-3.1, 3.1), True), ((-.2, .2), True), ((0., 0.), True)):
            with self.subTest(limits=limits):
                descriptor = SimpleNamespace(gun=SimpleNamespace(turretYawLimits=limits))
                self.assertEqual(expected, limited_traverse(descriptor))

    def test_every_he_clip_switches_penetration_fallback_and_back_without_eight_seconds(self):
        for limited in (False, True):
            for burst in (1, 3):
                for siege in (False, True):
                    with self.subTest(limited=limited, burst=burst, siege=siege):
                        scene = Observations(clips=6, targets=2, points=2)
                        scene.frame.update(loaded=2, limited_traverse=limited,
                                           burst_count=burst, siege=siege)
                        scene.passed(2, target=1)
                        scene.passed(1, target=2)
                        scene.he(0., target=2)
                        scene.he(120., target=2, sample=1)
                        scene.prime()
                        scene.prime('he_fallback')
                        first = scene.tick(0.)
                        self.assertEqual(('aim', 'penetration', ('bot', 1)),
                            (first['action'], first['candidate']['mode'], first['candidate']['target_key']))
                        scene.policy.shot_committed(dict(burst_index=0, burst_count=burst), {})
                        # A killed weak target cannot retarget an admitted
                        # physical burst; the next trigger owns the change.
                        scene.frame['targets'] = scene.frame['targets'][1:]
                        scene.frame['trigger_active'] = burst > 1
                        if burst > 1:
                            self.assertEqual('trigger_active', scene.tick(.1)['action'])
                            scene.policy.shot_committed(dict(burst_index=burst - 1,
                                                             burst_count=burst), {})
                        scene.frame.update(trigger_active=False, clip=6 - burst)
                        fallback = scene.tick(.2)
                        self.assertEqual(('aim', 'he_fallback', 2, 1),
                            (fallback['action'], fallback['candidate']['mode'],
                             fallback['candidate']['shell_index'], fallback['candidate']['sample']))
                        self.assertEqual(120., fallback['candidate']['expected_damage'])
                        self.assertFalse(hasattr(scene.policy, 'search_started'))
                        self.assertIsNone(scene.policy.reload_authority)
                        self.assertEqual(1, scene.policy.next_shell)
                        scene.policy.shot_committed(dict(burst_index=0, burst_count=1), {})
                        # An actual target change revokes the old plate
                        # certificate and proves a new HE penetration point.
                        scene.frame['targets'][0]['pose'] = ('enemy', 2, 1)
                        scene.passed(2, target=2)
                        restored = scene.tick(.3)
                        self.assertEqual(('aim', 'penetration', 2),
                            (restored['action'], restored['candidate']['mode'],
                             restored['candidate']['shell_index']))
                        self.assertFalse(scene.policy.fallback)
                        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_he_current_execution_survives_pending_but_next_trigger_requires_new_negative_proof(self):
        scene = Observations(clips=6, targets=1, points=2)
        scene.frame['loaded'] = 2
        scene.he(0.)
        scene.prime()
        scene.prime('he_fallback')
        first = scene.tick(0.)
        self.assertEqual('aim', first['action'])
        scene.frame['pose'] = ('source', 1)
        scene.value(2, sample=1, armor='unknown', line='pending')
        scene.prime('he_fallback')
        current = scene.tick(.1)
        # Another point's newly incomplete penetration proof cannot revoke
        # this still-valid HESH contact before its first physical trigger.
        self.assertEqual(('aim', first['candidate']['key']),
                         (current['action'], current['candidate']['key']))
        self.assertEqual(('source', 1), current['candidate']['pose_stamp'][1])
        self.assertTrue(scene.policy._executable_current(
            scene.policy.current_row(current['candidate']), 'he_fallback'))
        self.assertEqual(0., current['candidate']['expected_damage'])
        self.assertFalse(scene.policy._all_failed((2,)))
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertFalse(hasattr(scene.policy, 'search_authority'))
        # Once the physical first/final edge commits, a new trigger must
        # establish its own complete HESH penetration/fallback boundary.
        scene.policy.shot_committed(dict(burst_index=0, burst_count=1),
                                   dict(player_control=dict(candidate=current['candidate'])))
        scene.frame.update(clip=5, ammo=(30, 30, 29))
        pending = scene.tick(.2)
        self.assertNotEqual('aim', pending['action'])
        self.assertNotEqual('search_penetration', pending['action'])
        self.assertTrue(scene.policy.fallback)
        scene.value(2, sample=1)
        scene.prime(index=2)
        ready = scene.tick(.3)
        self.assertEqual(('aim', 'he_fallback'),
                         (ready['action'], ready['candidate']['mode']))
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_obstructed_he_clip_keeps_remaining_ammo_even_if_other_he_has_contact(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.frame.update(loaded=2, limited_traverse=True)
        scene.frame['shells'] += (dict(index=3, is_he=True, piercing=140., signature=('he2', 1)),)
        scene.frame['ammo'] += (30,)
        scene.value(2, armor='unknown', line='world_blocked')
        scene.value(2, mode='he_fallback', armor='unknown', line='world_blocked',
                    contact=True, expected_damage=0.)
        scene.passed(1)
        scene.he(200., index=3)
        scene.prime()
        scene.prime('he_fallback')
        scene.policy.fallback = True
        for now in (0., 1., 9., 40.):
            result = scene.tick(now)
            self.assertEqual('firing_position', result['action'])
            self.assertNotIn('shell_index', result)
            self.assertEqual(6, scene.frame['clip'])
            self.assertFalse(hasattr(scene.policy, 'search_started'))
            self.assertIsNone(scene.policy.reload_authority)
        self.assertEqual(1, scene.policy.next_shell)

    def test_next_rank_pending_clears_plan_even_while_current_he_fallback_is_usable(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.frame['loaded'] = 2
        scene.he(0.)
        scene.passed(1)
        scene.prime()
        scene.prime('he_fallback')
        scene.tick(0.)
        self.assertEqual(1, scene.policy.next_shell)
        scene.frame['line_revision'] += 1
        scene.value(0, armor='unknown', line='pending')
        scene.prime()
        scene.prime('he_fallback')
        result = scene.tick(.1)
        self.assertEqual(('aim', 2), (result['action'], result['candidate']['shell_index']))
        self.assertIsNone(scene.policy.next_shell)
        self.assertEqual('higher_rank_pending', scene.policy.next_status)

    def test_next_he_fallback_plan_depends_on_the_completed_penetration_review(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.frame['loaded'] = 2
        scene.he(0.)
        scene.prime()
        scene.prime('he_fallback')
        scene.tick(0.)
        self.assertEqual('verified_he_fallback', scene.policy.next_status)
        self.assertEqual('verified', scene.policy.next_at_edge()[1])
        self.assertEqual(4, len(scene.policy.next_proofs))
        # The HE contact remains unchanged, but a distinct penetration
        # obligation is now pending. The old HE plan cannot approve itself.
        scene.value(1, armor='pending', line='pending')
        job = scene.policy._jobs(shell_index=1)[0]
        scene.policy._evaluate(job, .1, 'background')
        self.assertEqual((None, 'rank_evidence_changed'), scene.policy.next_at_edge())
        scene.policy.background(.1)
        self.assertIsNone(scene.policy.next_plan)

    def test_limited_single_switches_to_verified_he_without_eight_second_drive(self):
        scene = Observations(targets=1, points=1)
        scene.frame['limited_traverse'] = True
        scene.passed(1)
        scene.prime()
        result = scene.tick(0.)
        self.assertEqual(('switch_shell', 1), (result['action'], result['shell_index']))
        scene.value(1)
        scene.frame['targets'][0]['pose'] = ('changed', 1)
        scene.he(0.)
        scene.prime()
        scene.prime('he_fallback')
        result = scene.tick(.1)
        self.assertEqual(('switch_shell', 2, 'he_fallback'),
            (result['action'], result['shell_index'], result['candidate']['mode']))
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertIsNone(scene.policy.reload_authority)

    def test_limited_non_he_waits_until_replacement_is_verified_before_reload(self):
        for siege in (False, True):
            with self.subTest(siege=siege):
                scene = Observations(clips=6, targets=1, points=1)
                scene.frame.update(limited_traverse=True, siege=siege)
                scene.value(1, armor='unknown', line='pending')
                scene.value(2, armor='unknown', line='pending')
                result = scene.tick(0.)
                self.assertEqual('wait', result['action'])
                self.assertIsNone(scene.policy.reload_authority)
                self.assertFalse(hasattr(scene.policy, 'search_started'))
                scene.passed(1)
                scene.value(2)
                scene.prime()
                result = scene.tick(.05)
                self.assertEqual(('reload_clip', True, 1),
                    (result['action'], result['early_reload'], result['shell_index']))
                qualified = scene.policy.reload_authority['qualified_at']
                for step in range(1, 10):
                    scene.frame['pose'] = ('physically_moving', step)
                    scene.value(0, armor='unknown', line='pending')
                    result = scene.tick(step * .1)
                    self.assertEqual('reload_clip', result['action'])
                    self.assertEqual(qualified, result['reload_qualified_at'])
                    self.assertFalse(hasattr(scene.policy, 'search_started'))
                # An actual new current-shell opportunity ends the reload
                # qualification rather than discarding the newly useful clip.
                scene.frame['pose'] = ('new_firing_lane', 11)
                scene.passed(0)
                self.assertEqual('aim', scene.tick(1.1)['action'])
                self.assertIsNone(scene.policy.reload_authority)

    def test_load_start_and_observed_clip_change_end_early_reload_authority(self):
        for event in ('load_started', 'observed_load', 'gun_changed'):
            with self.subTest(event=event):
                scene = Observations(clips=6, targets=1, points=1)
                scene.frame.update(limited_traverse=True, clip=3)
                scene.passed(1)
                scene.prime()
                scene.tick(0.)
                self.assertIsNotNone(scene.policy.reload_authority)
                if event == 'load_started':
                    scene.policy.load_started(0)
                    self.assertIsNone(scene.policy.reload_authority)
                elif event == 'observed_load':
                    scene.frame.update(clip=0, reloading=True)
                else:
                    scene.frame['identity'] = ('round', 'new_gun')
                scene.value(0, armor='pending', line='pending')
                scene.frame['pose'] = ('loading', 1)
                scene.tick(.1)
                self.assertIsNone(scene.policy.reload_authority)

    def test_siege_descriptor_change_keeps_reload_transaction_not_old_geometry(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.frame.update(limited_traverse=True, clip=3,
                           weapon_identity=('round', 'physical_gun'))
        scene.passed(1)
        scene.prime()
        scene.tick(0.)
        qualified = scene.policy.reload_authority['qualified_at']
        self.assertTrue(scene.policy.rows)
        scene.frame['identity'] = ('round', 'travel_descriptor')
        for index in (0, 1, 2):
            scene.value(index, armor='unknown', mechanical='mechanical_limited')
        result = scene.tick(.1)
        self.assertEqual('reload_clip', result['action'])
        self.assertEqual(qualified, scene.policy.reload_authority['qualified_at'])
        self.assertTrue(all(row['armor'] == 'unknown' for row in scene.policy.rows.values()))
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        scene.frame['weapon_identity'] = ('round', 'replacement_physical_gun')
        scene.frame['identity'] = ('round', 'replacement_descriptor')
        result = scene.tick(.2)
        self.assertNotEqual('reload_clip', result['action'])
        self.assertIsNone(scene.policy.reload_authority)

    def test_scope_exclusion_is_separate_from_unknown_geometry_and_empty_domain(self):
        scene = Observations(clips=6, targets=1, points=2)
        scene.frame['limited_traverse'] = True
        scene.frame['ammo'] = (30, 0, 0)
        scene.value(0, sample=1, armor='unknown', line='clear',
            mechanical='mechanical_limited', scope='excluded',
            scope_proof=dict(scope='excluded', reason='complete_native_pitch_envelope'))
        scene.prime(index=0)
        result = scene.tick(0.)
        self.assertEqual('navigate', result['action'])
        domain = scene.policy.failure_domains[(0,)]
        self.assertEqual((1, 1, 0), (domain['failed'], domain['excluded'], domain['geometry_pending']))
        self.assertEqual('unknown', scene.policy.rows[0, ('bot', 1), 1, 'penetration']['armor'])
        scene.policy.reset()
        scene.value(0, sample=0, armor='unknown', line='clear',
            mechanical='mechanical_limited', scope='excluded',
            scope_proof=dict(scope='excluded', reason='complete_native_pitch_envelope'))
        result = scene.tick(.1)
        self.assertEqual('firing_position', result['action'])
        self.assertFalse(scene.policy.failure_domains[(0,)]['all_failed'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_pending_geometry_never_borrows_reachable_points_negative_result(self):
        for limited in (False, True):
            for mechanical, line in (('hull_laying', 'clear'),
                    ('mechanical_limited', 'clear'), ('reachable', 'world_blocked')):
                with self.subTest(limited=limited, mechanical=mechanical, line=line):
                    scene = Observations(clips=6, targets=1, points=2)
                    scene.frame['limited_traverse'] = limited
                    scene.value(0, sample=1, armor='unknown', line=line, mechanical=mechanical)
                    scene.prime(index=0)
                    result = scene.tick(0.)
                    self.assertEqual('firing_position', result['action'])
                    self.assertFalse(scene.policy.failure_domains[(0,)]['all_failed'])
                    self.assertFalse(hasattr(scene.policy, 'search_started'))
                    self.assertIsNone(scene.policy.reload_authority)

    @staticmethod
    def stationary_evidence(armor='failed', contact=None, damage=None, proved=True):
        return dict(status='proved', proof=dict(proved=proved, source='native_stationary_arc'),
            line='clear', mechanical='reachable', armor=armor, contact=contact,
            expected_damage=damage, solution=dict(point=(20., 2., 100.),
                source_point=(20., 2., 100.), needs_hull=True, reachable=False,
                source_verified=False))

    def test_stationary_failure_is_counted_separately_and_never_becomes_actual_fire(self):
        scene = Observations(clips=6, targets=2, points=1)
        scene.frame.update(limited_traverse=True, clip=3)
        scene.value(0, target=2, armor='unknown', mechanical='hull_laying',
                    stationary_plan=self.stationary_evidence())
        scene.prime(index=0)
        result = scene.tick(0.)
        self.assertEqual('wait', result['action'])
        domain = scene.policy.failure_domains[(0,)]
        self.assertEqual((1, 1, True),
            (domain['failed'], domain['projected_failed'], domain['all_failed']))
        row = scene.policy.rows[0, ('bot', 2), 0, 'penetration']
        self.assertEqual(('unknown', 'hull_laying'), (row['armor'], row['mechanical']))
        self.assertFalse(scene.policy._executable(row))

    def test_incomplete_or_invalidated_stationary_arc_cannot_close_failure_domain(self):
        for state in ('unproved', 'invalidated', 'blocked'):
            with self.subTest(state=state):
                scene = Observations(clips=6, targets=2, points=1)
                scene.frame.update(limited_traverse=True, clip=3)
                plan = self.stationary_evidence(proved=state != 'unproved')
                if state == 'blocked':
                    plan['line'] = 'world_blocked'
                if state == 'invalidated':
                    scene.stationary_plan_current = lambda frame, proof: False
                scene.value(0, target=2, armor='unknown', mechanical='hull_laying',
                            stationary_plan=plan)
                scene.prime(index=0)
                result = scene.tick(0.)
                self.assertNotEqual('reload_clip', result['action'])
                self.assertFalse(scene.policy.failure_domains[(0,)]['all_failed'])
                self.assertIsNone(scene.policy.reload_authority)

    def test_current_executable_he_contact_precedes_hypothetical_pivot_penetration(self):
        scene = Observations(clips=6, targets=2, points=1)
        scene.frame.update(loaded=2, limited_traverse=True)
        scene.value(2, target=2, armor='unknown', mechanical='hull_laying',
                    stationary_plan=self.stationary_evidence('passed'))
        scene.he(100., target=1)
        scene.prime()
        scene.prime('he_fallback')
        result = scene.tick(0.)
        self.assertEqual(('aim', 'current_he_fallback_contact'),
                         (result['action'], result['reason']))
        self.assertEqual(('bot', 1), result['candidate']['target_key'])
        self.assertFalse(hasattr(scene.policy, 'search_started'))
        self.assertTrue(scene.policy.apply_order({})['fire_allowed'])
        target = result['candidate']['target']
        command, unused = scene.policy.select_command({}, scene.policy.apply_order({}), target, 0.)
        self.assertEqual(target['position'], command['aim_position'])
        self.assertTrue(command['fire_allowed'])
        planned = scene.policy.rows[2, ('bot', 2), 0, 'penetration']
        self.assertFalse(scene.policy._executable(planned))

    def test_next_rank_uses_safe_stationary_plan_but_first_trigger_rejects_it(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.passed(0)
        scene.value(2, armor='unknown', mechanical='hull_laying',
                    stationary_plan=self.stationary_evidence('passed'))
        scene.prime()
        result = scene.tick(0.)
        self.assertEqual(('aim', 0), (result['action'], result['candidate']['shell_index']))
        self.assertEqual(2, scene.policy.next_shell)
        planned, status = scene.policy.next_at_edge()
        self.assertEqual('verified', status)
        self.assertTrue(scene.policy._plannable(planned))
        self.assertFalse(scene.policy._executable(planned))
        scene.stationary_plan_current = lambda frame, proof: False
        self.assertEqual((None, 'candidate_expired'), scene.policy.next_at_edge())

    def test_next_he_fallback_does_not_require_current_clip_to_be_in_fallback(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.frame['ammo'] = (6, 30, 30)
        scene.passed(0)
        scene.he(0.)
        scene.prime()
        scene.prime('he_fallback')
        result = scene.tick(0.)
        self.assertEqual(('aim', 0), (result['action'], result['candidate']['shell_index']))
        self.assertFalse(scene.policy.fallback)
        self.assertEqual((2, 'he_fallback', 'verified_he_fallback'),
            (scene.policy.next_shell, scene.policy.next_plan['mode'], scene.policy.next_status))
        planned, status = scene.policy.next_at_edge()
        self.assertEqual((2, 'verified'), (planned['shell_index'], status))
        self.assertFalse(hasattr(scene.policy, 'search_started'))

    def test_checked_blocked_unknown_rank_cannot_authorise_next_he_fallback(self):
        for blocked in ('world_blocked', 'friendly_blocked'):
            with self.subTest(blocked=blocked):
                scene = Observations(clips=6, targets=1, points=1)
                scene.frame['ammo'] = (6, 30, 30)
                scene.passed(0)
                scene.value(1, armor='unknown', line=blocked)
                scene.he(20.)
                scene.prime()
                scene.prime('he_fallback')
                result = scene.tick(0.)
                self.assertEqual('aim', result['action'])
                self.assertIsNone(scene.policy.next_plan)
                self.assertEqual('fallback_evidence_incomplete', scene.policy.next_status)
                self.assertFalse(scene.policy.failure_domains[(1, 2)]['all_failed'])

    def test_current_he_contact_is_not_delayed_by_a_future_higher_damage_turn(self):
        scene = Observations(clips=6, targets=2, points=1)
        scene.frame.update(loaded=2, limited_traverse=True)
        scene.he(0., target=1)
        scene.value(2, target=2, mode='he_fallback', armor='unknown',
            mechanical='hull_laying', stationary_plan=self.stationary_evidence(
                'failed', contact=True, damage=50.))
        scene.prime()
        scene.prime('he_fallback')
        result = scene.tick(0.)
        self.assertEqual(('aim', 'current_he_fallback_contact'),
            (result['action'], result['reason']))
        self.assertEqual(('bot', 1), result['candidate']['target_key'])
        self.assertTrue(scene.policy._executable(result['candidate'], 'he_fallback'))
        future = scene.policy.rows[2, ('bot', 2), 0, 'he_fallback']
        self.assertFalse(scene.policy._executable(future, 'he_fallback'))


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
    def test_known_wreck_or_debris_lane_receipt_is_obstruction_not_unknown(self):
        geometry = self.runtime.geometry
        original = geometry._bot_friendly_path_verdict
        self.addCleanup(setattr, geometry, '_bot_friendly_path_verdict', original)
        for kind in (None, 'wreck', 'debris'):
            with self.subTest(kind=kind):
                # This is the geometry -> evaluator receipt boundary. The
                # native wreck collision itself is covered by the report
                # replay and geometry collision tests, not this adapter case.
                verdict = dict(clear=False)
                if kind is not None:
                    verdict.update(blocked=True, blocker_kind=kind,
                                   blocker_id=1010, blocker_position=(0., 0., 50.))
                geometry._bot_friendly_path_verdict = lambda *args: dict(verdict)
                policy = self.runtime.attack_policy
                policy.reset()
                policy.evaluator.jobs.clear()
                for unused in range(30):
                    self.step(.1)
                    policy.frame = policy.evaluator.snapshot(self.now)
                    row = policy._evaluate(policy._jobs(shell_index=0)[0],
                                           self.now, 'foreground')
                    if row['line'] != 'pending':
                        break
                if kind is None:
                    self.assertEqual(('unknown', 'lane_geometry_unavailable'),
                                     (row['line'], row['reason']))
                    self.assertFalse(policy._needs_firing_position(row))
                else:
                    self.assertEqual(('world_blocked', kind + '_blocked'),
                                     (row['line'], row['reason']))
                    self.assertEqual(kind, row['blocker']['blocker_kind'])
                    self.assertTrue(policy._needs_firing_position(row))
                self.assertEqual('unknown', row['armor'])
                self.assertFalse(policy._all_failed((0,)))
                self.assertFalse(policy._executable(row))

    def combat_evaluator(self, targets):
        # Native geometry remains real; only the already-completed original
        # BOT admission result is supplied at the explicit observation seam.
        runtime = SimpleNamespace(owner=self.battle, gun=self.runtime.gun,
            geometry=self.runtime.geometry, now=self.now,
            current_source=self.runtime.current_source,
            target_entity=self.runtime.target_entity,
            visible_targets=self.runtime.visible_targets,
            combat_targets=lambda: targets,
            combat_stop=SimpleNamespace(signature=('admitted', 1)))
        return NativeAttackEvaluator(runtime), runtime

    def test_native_attack_domain_is_only_original_bot_admitted_contacts(self):
        other = self.vehicle(43, (10., 0., 100.), team=2)
        self.observe()
        visible = self.runtime.visible_targets()
        self.assertEqual(2, len(visible))
        accepted = next(target for target in visible if target['engine_id'] == other.id)
        evaluator, runtime = self.combat_evaluator([accepted])

        def forbidden_visible_scan():
            self.fail('combat admission must not be replaced by all visible targets')

        runtime.visible_targets = forbidden_visible_scan
        frame = evaluator.snapshot(self.now)
        self.assertEqual((('bot', other.id),), tuple(row['key'] for row in frame['targets']))
        self.assertTrue(evaluator.fence(frame))
        runtime.combat_targets = lambda: []
        self.assertFalse(evaluator.fence(frame))
        empty = evaluator.snapshot(self.now)
        self.assertEqual((), empty['targets'])

    def test_observation_only_fixture_without_admission_method_still_has_targets(self):
        evaluator, runtime = self.combat_evaluator([])
        del runtime.combat_targets
        del runtime.combat_stop
        frame = evaluator.snapshot(self.now)
        self.assertEqual((('bot', self.target.id),),
                         tuple(row['key'] for row in frame['targets']))
        self.assertIsNone(frame['combat_signature'])
        self.assertTrue(evaluator.fence(frame))

    def test_changed_combat_authority_expires_frame_without_changing_native_identity(self):
        evaluator, runtime = self.combat_evaluator(self.runtime.visible_targets())
        frame = evaluator.snapshot(self.now)
        self.assertTrue(evaluator.fence(frame))
        self.assertEqual(runtime.combat_stop.signature, frame['combat_signature'])
        self.assertEqual((self.battle._generation, id(runtime.gun),
                          id(self.entity.typeDescriptor.gun)), frame['identity'])
        shell, target = frame['shells'][0], frame['targets'][0]
        self.assertIsNotNone(evaluator._prediction(frame, shell, target, target['samples'][0]))
        self.assertTrue(evaluator.predictions)
        prediction = evaluator.predictions[(shell['index'], target['key'], target['samples'][0])]
        runtime.combat_stop.signature = ('admitted', 2)
        self.assertFalse(evaluator.fence(frame))
        self.assertFalse(evaluator.fence_next(frame, [], ranked_domain=False))
        refreshed = evaluator.snapshot(self.now)
        self.assertEqual(frame['identity'], refreshed['identity'])
        self.assertNotEqual(frame['combat_signature'], refreshed['combat_signature'])
        self.assertIs(prediction, evaluator.predictions[
            (shell['index'], target['key'], target['samples'][0])])
        self.assertTrue(evaluator.fence(refreshed))

    def test_remote_ally_outside_lane_region_keeps_proof_until_it_enters(self):
        self.pose(self.target, (0., 0., 100.))
        friend = self.vehicle(71, (85., 0., 45.), 1)
        policy = self.runtime.attack_policy
        self.step(.1)
        policy.frame = policy.evaluator.snapshot(self.now)
        job = next(job for job in policy._jobs(shell_index=0) if job[2]['entity'] is self.target)
        proof = policy._evaluate(job, self.now, 'foreground')
        self.assertTrue(policy._executable(proof), proof)
        self.pose(friend, (100., 0., 45.))
        self.step(.1)
        policy.frame = policy.evaluator.snapshot(self.now)
        self.assertIs(proof, policy.current_row(proof))
        self.pose(friend, (0., 0., 45.))
        self.step(.1)
        policy.frame = policy.evaluator.snapshot(self.now)
        self.assertIsNone(policy.current_row(proof))
        job = next(job for job in policy._jobs(shell_index=0) if job[0] == proof['key'])
        blocked = policy._evaluate(job, self.now, 'foreground')
        self.assertEqual('friendly_blocked', blocked['line'])
        self.assertEqual('passed', blocked['armor'])

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

    def admit_search_domain(self):
        """Advance the original lane/target law after enabling drive or peers."""
        self.battle._spawn_planner = SimpleNamespace(capture_bases={
            '1': [dict(x=0., z=-45., radius=6.)],
            '2': [dict(x=45., z=45., radius=6.)]})
        self.runtime.features.add('drive')
        self.runtime.set_mission('attack', {})
        self.observe()
        for target in self.runtime.visible_targets():
            self.runtime.engine._shot_clear(self.runtime.state, target, self.now, force=True)
        self.runtime._strategic_due = 0.
        self.runtime._planner_order(self.now)
        self.assertTrue(self.runtime.combat_stop.stop_allowed,
                        self.runtime.combat_stop.receipt)

    def test_actual_turret_keeps_rotating_between_frames_but_negative_domain_closes(self):
        self.admit_search_domain()
        policy = self.hardened_target()
        for step in range(25):
            self.target.appearance.turretMatrix.setRotateY(.01 * step)
            self.step(.1)
            result = policy.update(self.now)
            if step == 0:
                self.assertEqual('navigate', result['action'],
                                 (result, policy.status(), policy.rows))
                self.assertFalse(hasattr(policy, 'search_started'))
                receipt = policy.status()['atomic']
                self.assertEqual('all_failed', receipt['status'])
                self.assertGreater(receipt['world_budget'], 0)
                self.assertLessEqual(receipt['world_chords'], receipt['world_budget'])
                self.assertGreater(receipt['evaluations'], 2)
                self.assertGreaterEqual(receipt['elapsed_ms'], 0.)
            self.assertNotEqual('search_penetration', result['action'])
            self.assertFalse(hasattr(policy, 'search_started'))
            policy.background(self.now)

    def test_world_callback_native_pose_change_cannot_publish_global_failure(self):
        policy = self.hardened_target()
        def move_during_query():
            self.target.appearance.turretMatrix.setRotateY(.3)
        self.on_probe = move_during_query
        self.step(.1)
        result = policy.update(self.now)
        self.assertEqual('wait', result['action'])
        self.assertFalse(hasattr(policy, 'search_started'))
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
        self.assertFalse(hasattr(policy, 'search_started'))
        self.assertNotEqual('search_penetration', result['action'])

    def test_native_exact_atomic_budget_is_sum_of_actual_trajectories(self):
        policy = self.hardened_target()
        self.step(.1)
        frame = policy.evaluator.snapshot(self.now)
        policy.frame = frame
        jobs = policy._jobs(shell_index=frame['loaded'])
        required = sum(len(policy.evaluator._prediction(frame, shell, target, sample)['path']) - 1
                       for key, shell, target, sample, mode in jobs)
        self.assertTrue(policy.evaluator.begin_atomic(frame, jobs, self.now))
        self.assertEqual(required, policy.evaluator.atomic_receipt['world_budget'])
        self.assertLess(required, ATOMIC_MAX_JOBS * 167)

    def test_ranked_recheck_leaves_world_chords_for_the_fair_candidate(self):
        from gui.mods.offline_lan_0922.vehicle_control.attack_policy import WORLD_CHORDS_PER_FRONTIER

        shot = self.battle._gun_state.shots[0]
        shot.speed, shot.gravity = 100., .1
        self.step(.1)
        policy = self.runtime.attack_policy
        policy.frame = policy.evaluator.snapshot(self.now)
        first, second = policy._jobs(shell_index=0)[:2]
        before = len(self.world_queries)
        row = policy._evaluate(first, self.now, 'background', ranked_recheck=True)
        self.assertEqual('pending', row['line'], row['reason'])
        self.assertEqual(WORLD_CHORDS_PER_FRONTIER // 2, len(self.world_queries) - before)
        policy._evaluate(second, self.now, 'background')
        self.assertEqual(WORLD_CHORDS_PER_FRONTIER, len(self.world_queries) - before)

    def test_fifteen_stable_enemies_three_shells_complete_in_bounded_frames(self):
        from gui.mods.offline_lan_0922.vehicle_control.attack_policy import ATOMIC_WALL_SECONDS
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
        self.admit_search_domain()
        self.assertEqual(15, len(self.runtime.combat_targets()))
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
            self.assertFalse(hasattr(policy, 'search_started'))
            if policy._all_failed((0, 1, 2)):
                break
        self.assertTrue(policy._all_failed((0, 1, 2)), policy.status())
        self.assertEqual(0, ordinary_navigation_requests,
                         'an unfinished global proof is not ordinary movement authority')
        self.assertEqual(405, len(policy._jobs()))
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
