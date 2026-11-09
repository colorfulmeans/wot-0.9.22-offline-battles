"""Pending shot evidence must not terminate the original mechanical manoeuvre.

The boundary cases feed supplied observation states through CombatStop and the
unchanged copied gun-angle consumer. The full-loop case uses native component
geometry and finite scan budgets, then reaches the real projectile/ammo path.
These tests do not certify Windows BigWorld motion or frame timing.
"""
import copy
import math
from types import SimpleNamespace
import unittest

from test_player_combat_stop import Scene
from test_player_combat_ownership import OwnershipScene
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import AttackPolicy, SEARCH_SECONDS


class OriginalRecoveryContinuityTests(unittest.TestCase):
    def scene(self):
        scene = Scene()
        scene.state['profile']['class_tag'] = 'mediumTank'
        scene.runtime.gun.clip_size = scene.runtime.gun.clip = 1
        scene.runtime.engine._gun_yaw_limits[1] = (-math.pi, math.pi, False)
        scene.candidate.update(mechanical='mechanical_limited', line='clear')
        scene.raw_order.update(combat_mode='route', target_id=None, target_kind=None,
            move_position=(20., 0., -30.), throttle_override=None,
            aim_position=None, fire_allowed=False)
        return scene

    @staticmethod
    def consume(scene, now, clear=lambda *args: True):
        order = scene.apply(now)
        return scene.runtime.engine._gun_angle_order(
            scene.state, order, {2: scene.target}, now, clear)

    def test_pending_and_ordinary_samples_keep_original_start_until_stalled(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                scene = self.scene()
                clear = lambda yaw, distance: not reverse or yaw > math.pi / 2.
                self.consume(scene, 0., clear)
                marker = scene.state['_gun_angle_adjustment']
                states = (
                    ('mechanical_limited', 'clear', 'unverified_points_obstructed'),
                    ('reachable', 'clear', 'global_snapshot_budget_pending'),
                    ('reachable', 'world_blocked', 'unverified_points_obstructed'),
                )
                terminal = None
                for tick in range(1, 101):
                    mechanical, line, reason = states[tick % len(states)]
                    scene.candidate.update(mechanical=mechanical, line=line)
                    scene.decide('firing_position', reason=reason)
                    result = self.consume(scene, tick / 10., clear)
                    if '_gun_angle_adjustment' not in scene.state:
                        terminal = scene.state['_gun_angle_last_terminal']
                        break
                    self.assertIs(marker, scene.state['_gun_angle_adjustment'])
                    self.assertEqual(0., marker['start'])
                    self.assertNotEqual('advance_contact', result['combat_mode'])
                    self.assertFalse(result['fire_allowed'])
                self.assertIsNotNone(terminal)
                self.assertEqual('relocation_stalled', terminal['reason'])
                self.assertGreaterEqual(terminal['progress_age'], 6.)
                self.assertEqual(-8. if reverse else 8., marker['destination'][2])
                self.assertEqual('route', result['combat_mode'])
                self.assertEqual((20., 0., -30.), result['move_position'])
                self.assertIsNone(scene.policy.search_started)
                self.assertEqual(1, scene.runtime.gun.clip)
                # A failed phase cannot reclaim the same route on each tick.
                scene.candidate.update(mechanical='mechanical_limited', line='clear')
                scene.decide('firing_position')
                self.consume(scene, terminal['sampled_at'] + .1, clear)
                self.assertNotIn('_gun_angle_adjustment', scene.state)
                self.assertFalse(scene.owner.stop_allowed)
                self.assertEqual('ineligible', scene.state['_gun_angle_handoff']['reason'])

    def test_original_arrival_completes_during_pending_evidence(self):
        scene = self.scene()
        self.consume(scene, 0.)
        marker = scene.state['_gun_angle_adjustment']
        self.consume(scene, 2.)
        destination = marker['destination']
        scene.candidate.update(mechanical='reachable', line='clear')
        scene.decide('firing_position', reason='global_snapshot_budget_pending')
        scene.position(destination)
        result = self.consume(scene, 2.1)
        self.assertNotIn('_gun_angle_adjustment', scene.state)
        self.assertEqual('relocation_arrived',
                         scene.state['_gun_angle_last_terminal']['reason'])
        self.assertEqual('engage', result['combat_mode'])
        self.assertEqual(0., result['throttle_override'])

    def test_ordinary_route_hint_cannot_retire_the_accepted_recovery(self):
        scene = self.scene()
        self.consume(scene, 0.)
        marker = scene.state['_gun_angle_adjustment']
        scene.raw_order.update(combat_mode='route', target_id=None, target_kind=None,
            move_position=(20., 0., -30.), throttle_override=None,
            aim_position=None, fire_allowed=False)
        scene.candidate.update(mechanical='reachable', line='clear')
        scene.decide('firing_position', reason='global_snapshot_budget_pending')
        before = copy.deepcopy(scene.raw_order)
        result = self.consume(scene, .1)
        self.assertEqual(before, scene.raw_order)
        self.assertTrue(scene.owner.combat_owned)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertIs(marker, scene.state['_gun_angle_adjustment'])
        self.assertEqual(0., marker['start'])
        self.assertNotIn('_gun_angle_last_terminal', scene.state)
        self.assertNotEqual('route', result['combat_mode'])
        self.assertNotEqual(before['move_position'], result['move_position'])
        self.assertEqual(2, result['target_id'])
        self.assertFalse(result['fire_allowed'])

    def test_real_task_handoff_still_retires_original_recovery(self):
        for mode in ('team_return_base', 'withdraw'):
            with self.subTest(mode=mode):
                scene = self.scene()
                self.consume(scene, 0.)
                scene.raw_order.update(combat_mode=mode,
                    move_position=(20., 0., -30.), throttle_override=None)
                scene.candidate.update(mechanical='reachable', line='clear')
                scene.decide('firing_position', reason='global_snapshot_budget_pending')
                before = copy.deepcopy(scene.raw_order)
                result = self.consume(scene, .1)
                self.assertEqual(before, result)
                self.assertNotIn('_gun_angle_adjustment', scene.state)
                self.assertEqual('combat_task_handoff',
                                 scene.state['_gun_angle_last_terminal']['reason'])

    def test_verified_shot_releases_recovery_without_waiting_for_timeout(self):
        scene = self.scene()
        self.consume(scene, 0.)
        scene.candidate.update(mechanical='reachable', line='clear', armor='passed')
        scene.decide('aim')
        result = self.consume(scene, .1)
        self.assertNotIn('_gun_angle_adjustment', scene.state)
        self.assertNotIn('_gun_angle_refusal', scene.state)
        self.assertEqual('verified_shot',
                         scene.state['_gun_angle_last_terminal']['reason'])
        self.assertEqual('engage', result['combat_mode'])
        self.assertTrue(result['fire_allowed'])

    def test_pending_without_original_recovery_does_not_request_ordinary_approach(self):
        scene = self.scene()
        scene.candidate.update(mechanical='reachable', line='clear', armor='failed')
        scene.decide('firing_position', reason='global_snapshot_budget_pending')
        result = self.consume(scene, 0.)
        self.assertEqual('engage', result['combat_mode'])
        self.assertEqual(scene.state['position'], result['move_position'])
        self.assertEqual(0., result['throttle_override'])
        self.assertNotIn('_gun_angle_adjustment', scene.state)

    def test_query_wait_keeps_the_accepted_finite_physical_recovery(self):
        scene = self.scene()
        scene.candidate.update(mechanical='reachable', line='world_blocked', armor='passed')
        scene.decide('firing_position', reason='current_penetration_obstructed')
        self.consume(scene, 0.)
        approach = self.consume(scene, 2.1)
        marker = scene.state['_gun_angle_adjustment']
        self.assertEqual('gun_angle_adjust', approach['combat_mode'])
        self.assertEqual(1., approach['throttle_override'])
        self.assertNotEqual(scene.target['position'], approach['move_position'])
        self.assertFalse(scene.runtime.engine._friendly_repositions)
        scene.decide('wait', candidate=False, reason='stationary_domain_review_pending')
        for now in (2.2, 2.3, 2.4):
            waiting = self.consume(scene, now)
            for name in ('combat_mode', 'move_position', 'throttle_override', 'target_id'):
                self.assertEqual(approach[name], waiting[name])
            self.assertTrue(scene.owner.combat_owned)
            self.assertTrue(scene.owner.stop_allowed)
            self.assertIs(marker, scene.state['_gun_angle_adjustment'])
            self.assertEqual(0., marker['start'])
            self.assertFalse(waiting['fire_allowed'])


class RecoveryEpisodeTransitionTests(unittest.TestCase):
    """Unit boundary for chosen actions, not fabricated native proof tests.

    These supplied action/point observations deliberately isolate the real
    AttackPolicy._choose and navigation_result state transitions. Native
    evaluation and all-enemy failure qualification have separate full-loop
    tests; assigning search_authority here is not evidence of either.
    """
    @staticmethod
    def policy_and_candidate():
        # _choose consumes supplied observations in this isolated boundary;
        # it must not instantiate or imply a native evaluator execution.
        policy = AttackPolicy(SimpleNamespace(), evaluator=SimpleNamespace())
        target = dict(kind='bot', id=2, network_id=2, position=(0., 0., 40.))
        candidate = dict(target=target, target_key=('bot', 2), shell_index=0,
            sample=0, key=(0, ('bot', 2), 0, 'penetration'), mode='penetration',
            armor='passed', line='clear', mechanical='reachable',
            solution=dict(point=(0., 1., 40.)))
        return policy, candidate

    def test_pending_status_does_not_renew_movement_episode_or_global_search_deadline(self):
        for action in ('firing_position', 'search_penetration'):
            with self.subTest(action=action):
                policy, candidate = self.policy_and_candidate()
                if action == 'search_penetration':
                    policy.search_authority = dict(qualified_at=9.)
                first = policy._choose(action, 'supplied_observation', candidate)
                episode = first['move_request']['episode_id']
                if action == 'search_penetration':
                    policy.navigation_result(dict(action=action, episode_id=episode,
                        status='accepted', attempted=True, at=10.))
                deadline = first['move_request']['deadline']
                for reason in ('stationary_domain_review_pending',
                               'he_damage_comparison_pending',
                               'global_snapshot_budget_pending', 'observation_unavailable'):
                    waiting = policy._choose('wait', reason)
                    self.assertIsNone(waiting['candidate'])
                    resumed = policy._choose(action, 'supplied_observation_resumed', candidate)
                    self.assertEqual(episode, resumed['move_request']['episode_id'])
                    self.assertEqual(deadline, resumed['move_request']['deadline'])
                    self.assertEqual(deadline, resumed['search_deadline'])
                if action == 'search_penetration':
                    self.assertEqual(10., policy.search_started)
                    self.assertEqual(10. + SEARCH_SECONDS, deadline)

    def test_completed_or_changed_movement_phase_starts_a_new_episode(self):
        for completion in ('aim', 'navigate', 'switch_shell', 'reload_clip'):
            with self.subTest(completion=completion):
                policy, candidate = self.policy_and_candidate()
                first = policy._choose('firing_position', 'supplied_recovery', candidate)
                episode = first['move_request']['episode_id']
                terminal = policy._choose(completion, 'supplied_terminal', candidate)
                self.assertEqual(completion, terminal['action'])
                later = policy._choose('firing_position', 'new_supplied_recovery', candidate)
                self.assertNotEqual(episode, later['move_request']['episode_id'])
        policy, candidate = self.policy_and_candidate()
        first = policy._choose('firing_position', 'supplied_recovery', candidate)
        policy.search_authority = dict(qualified_at=9.)
        search = policy._choose('search_penetration', 'supplied_negative_domain', candidate)
        self.assertNotEqual(first['move_request']['episode_id'], search['move_request']['episode_id'])


class FullRecoveryAndFireTests(unittest.TestCase):
    def test_real_evidence_fluctuation_keeps_recovery_then_allows_native_shot(self):
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(clip=1, burst=1)
        limits = scene.entity.typeDescriptor.gun.pitchLimits
        limits.update(absolute=(-.2, .2),
            minPitch=((0., -.2), (2. * math.pi, -.2)),
            maxPitch=((0., .2), (2. * math.pi, .2)))
        target = scene.eligible_enemy(5, armor=10000.)
        scene.pose(target, (20., 20., 40.))
        self.assertEqual({5: True}, scene.sample_original_lanes())
        policy = scene.runtime.attack_policy
        # Complete the real stationary alternatives before the physical
        # phase is authorized; a pending first point is no movement proof.
        policy.atomic_time_budget = .25
        for unused in range(120):
            scene.tick()
            if scene.runtime.state.get('_gun_angle_adjustment') is not None:
                break
        marker = scene.runtime.state.get('_gun_angle_adjustment')
        self.assertIsNotNone(marker, policy.status())
        policy.atomic_time_budget = 0.
        started = marker['start']
        reasons = set()
        initial_ammo = tuple(scene.battle._gun_state.ammo)
        # Actual target geometry alternates between pitch refusal and a
        # reachable thick plate while the all-point budget remains pending.
        # Two observations at each height also exercise zero target velocity.
        # No tactical order, proof, or navigation result is manufactured.
        for tick in range(1, 41):
            scene.pose(target, (20., 0. if tick % 4 in (1, 2) else 20., 40.))
            scene.tick()
            reasons.add(policy.decision['reason'])
            self.assertIs(marker, scene.runtime.state.get('_gun_angle_adjustment'),
                          (tick, policy.status(), scene.runtime.state.get('_gun_angle_last_terminal')))
            self.assertEqual(started, marker['start'])
            self.assertFalse(scene.launches())
            self.assertEqual(initial_ammo, tuple(scene.battle._gun_state.ammo))
            self.assertIsNone(policy.search_started)
        self.assertTrue(reasons.intersection(('global_snapshot_budget_pending',
            'stationary_alternatives_pending')), reasons)
        # A newly observable, penetrable target point is a real firing exit.
        # The native actuator must consume the new source before admission;
        # actual launch and GunState debit are asserted, not just action=aim.
        scene.pose(target, (20., 0., 40.))
        for component in ('chassis', 'hull', 'turret', 'gun'):
            getattr(target.typeDescriptor, component).materials[0].armor = 10.
        policy.atomic_time_budget = .25
        for unused in range(80):
            scene.tick()
            if scene.launches():
                break
        self.assertEqual(1, len(scene.launches()), scene.runtime.status())
        self.assertEqual(initial_ammo[0] - 1, scene.battle._gun_state.ammo[0])
        self.assertEqual(initial_ammo[1], scene.battle._gun_state.ammo[1])
        self.assertEqual(1, scene.control.shot_commits)
        self.assertNotIn('_gun_angle_adjustment', scene.runtime.state)
        self.assertIsNone(policy.search_started)


if __name__ == '__main__':
    unittest.main()
