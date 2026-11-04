"""Foreground completion regressions; analytic boundaries are not native QA."""
import math
import types
import unittest
from unittest import mock

import test_player_weapon_migration as migration

from gui.mods.offline_lan_0922.player_control import PlayerControl
from gui.mods.offline_lan_0922.player_control.ammunition import Ammunition
from gui.mods.offline_lan_0922.player_control.aiming import Aiming, PLAN_SECONDS
from gui.mods.offline_lan_0922.player_control.weapon import artillery_path


class RejectionCompletionTests(unittest.TestCase):
    def policy(self, artillery=False):
        kinds = (('HIGH_EXPLOSIVE', 'ARMOR_PIERCING') if artillery else
                 ('ARMOR_PIERCING', 'ARMOR_PIERCING_CR', 'HIGH_EXPLOSIVE'))
        policy = Ammunition([dict(index=i, kind=kind) for i, kind in enumerate(kinds)],
                            0, 0, clip_size=6, artillery=artillery)
        policy.protected = False
        self.inventory = [100] * len(kinds)
        policy.choose(self.inventory)
        return policy

    def launch(self, policy, identity, **kwargs):
        arguments = dict(position=(0., 0., 0.), target=42, now=0., shell=0)
        arguments.update(kwargs)
        policy.launch(identity, **arguments)

    def terminal(self, policy, identity, damage=0., hit=True, known=True):
        if hit and known:
            policy.hit(dict(projectile_id=identity, damage=damage, shot_result=1))
        policy.terminal(dict(projectile_id=identity, hit_vehicle=hit), 1.)

    def test_rejected_head_drains_later_real_results_without_refunding_commit(self):
        policy = self.policy()
        for i, identity in enumerate(('rejected', 'later-a', 'later-b')):
            self.launch(policy, identity, clip_remaining=5-i)
        for identity in ('later-a', 'later-b'):
            self.terminal(policy, identity)
        self.assertEqual([], policy.settle(self.inventory, 2.))
        committed = (policy.fired, policy.used, policy.magazine, policy._clip_remaining)
        self.assertTrue(policy.reject('rejected', 2., 'projectile_launch_rejected'))
        rows = policy.settle(self.inventory, 2.)
        self.assertEqual(['rejected', 'later-a', 'later-b'], [r['id'] for r in rows])
        self.assertTrue(rows[0]['rejected'])
        self.assertEqual(committed, (policy.fired, policy.used,
                                    policy.magazine, policy._clip_remaining))
        self.assertEqual([100, 100, 100], self.inventory)
        self.assertEqual(1, policy.desired)
        self.assertTrue(policy.idle)

    def test_all_rejected_burst_preserves_the_existing_failure_streak(self):
        for artillery in (False, True):
            with self.subTest(artillery=artillery):
                policy = self.policy(artillery)
                self.launch(policy, 'real')
                self.terminal(policy, 'real', hit=not artillery)
                policy.settle(self.inventory, 2.)
                self.assertEqual(1, policy.failures)
                previous = dict(policy._failures)
                for identity in ('a', 'b'):
                    self.launch(policy, identity, group=7, count=3)
                    policy.reject(identity, 2., 'launch_rejected')
                self.assertEqual(2, policy._groups[7]['admitted'])
                policy.close_group(7, 2)
                with mock.patch.object(policy, '_result', wraps=policy._result) as result:
                    policy.settle(self.inventory, 2.)
                    result.assert_not_called()
                self.assertEqual(previous, policy._failures)
                self.assertEqual(1, policy.failures)
                self.assertEqual((3, 3), (policy.fired, policy.used))
                self.assertTrue(policy.idle)

    def test_mixed_burst_uses_real_feedback_and_keeps_actual_committed_count(self):
        for rejected_first in (False, True):
            for damage in (0., 100.):
                with self.subTest(rejected_first=rejected_first, damage=damage):
                    policy = self.policy()
                    order = ('rejected', 'real') if rejected_first else ('real', 'rejected')
                    for identity in order:
                        self.launch(policy, identity, group=7, count=3)
                    policy.close_group(7, 2)
                    self.terminal(policy, 'real', damage=damage)
                    policy.reject('rejected', 2., 'launch_rejected')
                    with mock.patch.object(policy, '_result', wraps=policy._result) as result:
                        policy.settle(self.inventory, 2.)
                        result.assert_called_once()
                        combined = result.call_args[0][0]
                    self.assertEqual(2, combined['actual_count'])
                    self.assertTrue(combined['known'])
                    self.assertTrue(combined['hit'])
                    self.assertEqual(damage, combined['damage'])
                    self.assertEqual(1 if damage == 0. else 0, policy.desired)
                    self.assertTrue(policy.idle)

    def test_rejected_round_is_not_an_artillery_miss(self):
        policy = self.policy(artillery=True)
        self.launch(policy, 'rejected')
        policy.reject('rejected', 1.)
        policy.settle(self.inventory, 1.)
        self.assertEqual(0, policy.failures)
        for identity in ('rejected-mixed', 'actual-miss'):
            self.launch(policy, identity, group=7, count=2)
        policy.reject('rejected-mixed', 1.)
        self.terminal(policy, 'actual-miss', hit=False)
        policy.settle(self.inventory, 1.)
        self.assertEqual(1, policy.failures)
        self.assertTrue(policy.idle)

    def test_rejection_does_not_bypass_a_real_unknown_contact_grace(self):
        policy = self.policy()
        for identity in ('rejected', 'unknown'):
            self.launch(policy, identity, group=7, count=2)
        policy.reject('rejected', 1.)
        self.terminal(policy, 'unknown', known=False)
        self.assertEqual(['rejected'], [r['id'] for r in policy.settle(self.inventory, 1.)])
        self.assertFalse(policy.idle)
        self.assertEqual(['unknown'], [r['id'] for r in policy.settle(self.inventory, 3.1)])
        self.assertEqual(0, policy.failures)
        self.assertTrue(policy.idle)

    def test_old_rejection_cannot_erase_current_target_or_position_failures(self):
        for target, position in ((43, (0., 0., 0.)), (42, (4., 0., 0.))):
            with self.subTest(target=target, position=position):
                policy = self.policy()
                self.launch(policy, 'old')
                for identity in ('current-a', 'current-b'):
                    self.launch(policy, identity, target=target, position=position)
                    self.terminal(policy, identity)
                policy.reject('old', 2.)
                policy.settle(self.inventory, 2.)
                self.assertEqual(1, policy.desired)
                self.assertTrue(policy.idle)

    def test_mixed_epoch_rejection_does_not_relabel_old_real_feedback(self):
        policy = self.policy()
        self.launch(policy, 'old-real', group=7, count=2)
        self.launch(policy, 'new-rejected', group=7, count=2, target=43)
        self.terminal(policy, 'old-real')
        policy.reject('new-rejected', 2.)
        policy.settle(self.inventory, 2.)
        self.assertEqual(0, policy.desired)
        self.assertEqual(0, policy.failures)
        self.assertTrue(policy.idle)

    def test_duplicate_rejection_and_late_hit_terminal_are_harmless(self):
        policy = self.policy()
        self.launch(policy, 'rejected')
        self.assertTrue(policy.reject('rejected', 1., 'original'))
        self.assertFalse(policy.reject('rejected', 2., 'duplicate'))
        policy.hit(dict(projectile_id='rejected', damage=100., shot_result=2))
        policy.terminal(dict(projectile_id='rejected', hit_vehicle=True), 2.)
        row = policy.rows['rejected']
        self.assertEqual((1., 'original', None, 0.),
                         (row['terminal'], row['rejection_reason'], row['hit'], row['damage']))
        policy.settle(self.inventory, 2.)
        self.assertFalse(policy.reject('rejected', 3.))
        self.assertFalse(policy.reject('unrelated', 3.))
        self.assertTrue(policy.idle)

    def test_repeated_rejections_leave_no_retained_groups_or_rows(self):
        policy = self.policy()
        for index in range(500):
            identity = str(index)
            self.launch(policy, identity)
            policy.reject(identity, float(index))
            self.assertEqual(1, len(policy.settle(self.inventory, float(index))))
            self.assertTrue(policy.idle)
        self.assertEqual(500, policy.fired)

    def test_runtime_launch_rejection_reaches_active_and_retired_policy(self):
        import test_port_0922_battle_projectiles as projectile_tests
        for retired in (False, True):
            with self.subTest(retired=retired):
                case = projectile_tests.BattleProjectileTests()
                self.addCleanup(case.doCleanups)
                battle, echo, canonical = case._preinstalled_high_precision_player_projectile()
                battle._gun_state = types.SimpleNamespace(clip=0, reload_time=5., ammo=[10, 10, 10])
                control = PlayerControl(battle, ('fire',), notify=lambda unused: None)
                battle._player_control = control
                control.record = lambda *args, **kwargs: None
                control.emit_result = lambda unused: None
                policy = Ammunition([dict(index=2, kind='ARMOR_PIERCING'),
                    dict(index=1, kind='ARMOR_PIERCING_CR'),
                    dict(index=0, kind='HIGH_EXPLOSIVE')], 2, 2)
                policy.protected = False
                policy.choose(battle._gun_state.ammo)
                control.ammo_policy = policy
                control.trigger_context = dict(command=None, target=42, policy=policy,
                    time=10., projectiles=[])
                control.shot_committed(echo, dict(x=0., y=0., z=0.,
                    burst_group_seq=3, burst_count=1))
                control.trigger_context = None
                if retired:
                    control.retired_policies.append(policy)
                    control.ammo_policy = None
                before = (list(battle._gun_state.ammo), battle._gun_state.clip,
                          battle._gun_state.reload_time)
                event = dict(type='fire_intent_result', round_id=9, player_id=7,
                    intent_seq=5, shot_seq=3, projectile_id=canonical['projectile_id'],
                    accepted=False, reason='projectile_launch_rejected')
                self.assertTrue(battle.on_fire_intent_result(event))
                self.assertNotIn(canonical['projectile_id'], battle._projectile_meta)
                for index in range(2):
                    identity = 'later-%s' % index
                    policy.launch(identity, 2, 42, 11.+index, position=(0., 0., 0.))
                    control.shot_hit(dict(projectile_id=identity, damage=0.,
                                          shot_result=1, cosmetic_only=True))
                    control.shot_terminal(dict(projectile_id=identity, hit_vehicle=True))
                rows = policy.settle(battle._gun_state.ammo, 100.)
                self.assertEqual(3, len(rows))
                self.assertTrue(rows[0]['rejected'])
                self.assertEqual(1, policy.desired)
                self.assertTrue(policy.idle)
                self.assertEqual(before, (battle._gun_state.ammo, battle._gun_state.clip,
                                          battle._gun_state.reload_time))


class ArcCompletionTests(unittest.TestCase):
    def setUp(self):
        collision = mock.patch(
            'gui.mods.offline_lan_0922.entities.remote_vehicle.collide_vehicle_at_matrix',
            return_value=())
        collision.start()
        self.addCleanup(collision.stop)

    def scene(self, count, drop=0.):
        # Repository-recorded FV3805/FV206 5.5-inch shell and surveyed envelope
        # (test_port_0922_bot_runtime). These are constant analytic yaw curves,
        # not recovered native getShotAngles/minPitch/maxPitch implementations.
        own = migration.descriptor(minimum=-math.radians(70.), maximum=math.radians(5.))
        owner, first, shot, body = migration.aiming_scene(
            speed=440., gravity=146., distance=900., own_descriptor=own)
        shot['maxDistance'] = 10000.
        shot['shell']['kind'] = 'HIGH_EXPLOSIVE'
        targets = []
        for index in range(count):
            target = types.SimpleNamespace(**dict(first.__dict__, id=42+index))
            target.position = (float(index)*2., -drop, 900.)
            target.matrix = migration.PresentedMatrix(target)
            targets.append(target)
        return Aiming(owner), owner, targets, shot, body

    @staticmethod
    def ridge(first, last):
        # Analytic scenery deliberately blocks the low arc only.
        wall = 400.
        if (first[2]-wall)*(last[2]-wall) <= 0. and abs(last[2]-first[2]) > 1.e-9:
            height = first[1]+(last[1]-first[1])*(wall-first[2])/(last[2]-first[2])
            return height >= 300.
        return True

    def tick(self, planner, targets, now):
        planner.begin(targets, now)
        result = [(target, planner.update(target, now, self.ridge, artillery=True))
                  for target in targets]
        for key, limit in (('segments', 12), ('candidates', 2), ('native_angles', 12)):
            self.assertLessEqual(planner.receipt[key], limit)
        self.assertLessEqual(len(planner.entries), len(targets))
        for entry in planner.entries.values():
            self.assertLessEqual(len(entry['jobs']), 2*len(entry['samples']))
        return result

    def test_catalog_high_arcs_complete_for_every_target_over_a_long_run(self):
        for count, drop in ((12, 0.), (8, 89.106), (15, 0.)):
            with self.subTest(targets=count, drop=drop):
                planner, owner, targets, shot, body = self.scene(count, drop)
                seen, previous, cancelled = set(), {}, 0
                required = 0
                for tick in range(601):
                    for target, result in self.tick(planner, targets, tick*.1):
                        if result['clear'] and result['reachable']:
                            self.assertEqual('high', result['arc'])
                            self.assertTrue(result['source_verified'])
                            seen.add(target.id)
                    jobs = {(target_id, key): job for target_id, entry in planner.entries.items()
                            for key, job in entry['jobs'].items()}
                    cancelled += sum(key not in jobs or jobs[key] is not job
                                     for key, job in previous.items() if not job['done'])
                    previous = jobs
                    required = max([required]+[len(j['solution']['path'])-1 for j in jobs.values()
                                               if j['solution']['arc'] == 'high'])
                self.assertEqual(set(t.id for t in targets), seen)
                self.assertEqual(49 if drop else 47, required)
                self.assertEqual(0, cancelled)

    def test_low_cadence_does_not_impose_a_deadline_on_pending_chords(self):
        for count, cadence in ((1, 1.1), (12, .5)):
            with self.subTest(targets=count, cadence=cadence):
                planner, owner, targets, shot, body = self.scene(count)
                seen, aged_completion = set(), False
                for tick in range(200):
                    now = tick*cadence
                    for target, result in self.tick(planner, targets, now):
                        if result['clear'] and result['reachable']:
                            seen.add(target.id)
                            job = planner.entries[target.id]['jobs'][result['key']]
                            aged_completion |= job['completed']-job['solution']['created'] > PLAN_SECONDS
                self.assertEqual(set(t.id for t in targets), seen)
                self.assertTrue(aged_completion)

    def test_completed_freshness_starts_at_completion_and_is_not_renewed_by_reuse(self):
        planner, owner, targets, shot, body = self.scene(1)
        for tick in range(30):
            target, result = self.tick(planner, targets, float(tick))[0]
            if result['clear'] and result['reachable']:
                break
        self.assertTrue(result['clear'])
        job = planner.entries[target.id]['jobs'][result['key']]
        completed = job['completed']
        self.assertGreater(completed-job['solution']['created'], PLAN_SECONDS)
        fresh = self.tick(planner, targets, completed+.2)[0][1]
        self.assertTrue(fresh['clear'])
        self.assertIs(job, planner.entries[target.id]['jobs'][result['key']])
        self.assertEqual(completed, job['completed'])
        self.tick(planner, targets, completed+PLAN_SECONDS+.1)
        self.assertFalse(any(value is job for value in planner.entries[target.id]['jobs'].values()))

    def test_pending_geometry_still_invalidates_shell_muzzle_body_and_target_changes(self):
        for change in ('shell', 'muzzle', 'body', 'target', 'hidden'):
            with self.subTest(change=change):
                planner, owner, targets, shot, body = self.scene(1)
                self.tick(planner, targets, 0.)
                job = planner.entries[targets[0].id]['jobs'][(0, 'high')]
                self.tick(planner, targets, 4.)
                self.assertIs(job, planner.entries[targets[0].id]['jobs'][(0, 'high')])
                self.assertFalse(job['done'])
                if change == 'shell':
                    owner._gun_state.shots.append(dict(shot))
                    owner._gun_state.shot_index = 1
                elif change == 'muzzle':
                    owner._mutable_shot_ray = lambda: ((.51, 1., 0.), (0., 0., 1.))
                elif change == 'body':
                    body.yaw = .031
                elif change == 'target':
                    targets[0].position = (2., 0., 900.)
                else:
                    planner.begin([], 4.1)
                    self.assertFalse(planner.entries)
                    continue
                self.tick(planner, targets, 4.1)
                self.assertFalse(any(value is job for value in planner.entries[targets[0].id]['jobs'].values()))

    def test_long_running_motion_uses_fresh_intercept_and_exact_final_world_path(self):
        planner, owner, targets, shot, body = self.scene(12)
        confirmed = set()
        for tick in range(250):
            now = tick*.1
            for index, target in enumerate(targets):
                target.position = (index*2.+now, 0., 900.)
            for target, result in self.tick(planner, targets, now):
                if not result['clear'] or not result['reachable']:
                    continue
                checked = []
                def static_lane(first, last):
                    checked.append((first, last))
                    return self.ridge(first, last)
                if planner.confirm(target, result, result['direction'], now,
                                   static_lane, lambda path: True):
                    confirmed.add(target.id)
                    path = artillery_path(result['origin'], result['point'], shot, result['direction'])
                    self.assertEqual(list(zip(path, path[1:])), checked)
                    self.assertEqual(now, result['created'])
                    self.assertEqual(0., result['lead_delay'])
                    self.assertEqual(2, planner.receipt['dynamic_checks'])
                self.assertLessEqual(planner.receipt['final_segments'], 167)
                self.assertLessEqual(planner.receipt['final_attempts'], 1)
        self.assertTrue(confirmed)

    def test_aged_advisory_proof_cannot_bypass_current_dynamic_or_world_blockers(self):
        planner, owner, targets, shot, body = self.scene(12)
        selected = None
        for tick in range(150):
            now = tick*.1
            results = self.tick(planner, targets, now)
            selected = next(((t, r) for t, r in results if r['clear'] and r['reachable']), None)
            if selected is not None:
                break
        self.assertIsNotNone(selected)
        target, result = selected
        job = planner.entries[target.id]['jobs'][result['key']]
        self.assertGreater(now-job['solution']['created'], PLAN_SECONDS)
        static = mock.Mock(return_value=True)
        self.assertFalse(planner.confirm(target, result, result['direction'], now,
                                         static, lambda path: False))
        static.assert_not_called()
        self.assertEqual('dynamic_blocked', planner.receipt['final_reason'])
        self.assertFalse(planner.confirm(target, result, result['direction'], now,
                                         lambda first, last: False, lambda path: True))
        self.assertEqual('static_blocked', planner.receipt['final_reason'])
        self.assertFalse(job['clear'])
        self.assertEqual(now, job['completed'])


if __name__ == '__main__':
    unittest.main()
