"""Continuity at the shared selected-point recovery / original-route seam.

These controlled boundary observations cannot certify a Windows BigWorld
projectile. The final case uses the actual foreground source, actuator,
admission and GunState debit. The retired independent BOT gun-angle finder and
eight-second penetration search are intentionally not recreated as fixtures.
"""
import math
from types import SimpleNamespace
import unittest

from test_player_combat_stop import Scene
from test_player_limited_traverse import TraverseScene
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import AttackPolicy


class SelectedPointRecoveryContinuityTests(unittest.TestCase):
    def scene(self, statuses=None):
        scene = Scene()
        scene.raw_order.update(combat_mode='route', target_kind=None,
            target_id=None, move_position=(20., 0., -30.),
            aim_position=None, throttle_override=None, fire_allowed=False)
        scene.candidate.update(key=(0, ('bot', 2), 0, 'penetration'), sample=0)
        scene.probes = []
        statuses = list(statuses or ())

        def probe(candidate, destination, now):
            scene.probes.append((candidate['key'], tuple(destination), now))
            return dict(status=statuses.pop(0) if statuses else 'clear',
                        fire_permission=False)

        scene.runtime.point_recovery_probe = probe
        return scene

    def test_pending_review_keeps_exact_checked_goal_and_episode(self):
        scene = self.scene()
        first = scene.apply(0.)
        phase = scene.owner._physical_recovery
        goal, key, started = phase['goal'], phase['key'], phase['started']
        self.assertEqual('gun_angle_adjust', first['combat_mode'])
        scene.decide('wait', candidate=False, reason='stationary_domain_review_pending')
        for now in (.1, .2, .4, .8):
            waiting = scene.apply(now)
            self.assertIs(phase, scene.owner._physical_recovery)
            self.assertEqual((goal, key, started),
                (phase['goal'], phase['key'], phase['started']))
            self.assertEqual('gun_angle_adjust', waiting['combat_mode'])
            self.assertEqual(goal, waiting['move_position'])
            self.assertFalse(waiting['fire_allowed'])
            self.assertTrue(scene.owner.stop_allowed)
        self.assertEqual(1, len(scene.probes))

    def test_changing_unsampled_intention_cannot_steal_accepted_goal(self):
        scene = self.scene()
        scene.apply(0.)
        phase = scene.owner._physical_recovery
        previous_goal = phase['goal']
        scene.candidate.update(key=(2, ('bot', 2), 1, 'he_fallback'),
                               sample=1, mode='he_fallback')
        scene.decide('firing_position', reason='another_sample_pending')
        result = scene.apply(.1)
        self.assertIs(phase, scene.owner._physical_recovery)
        self.assertEqual((0, ('bot', 2), 0, 'penetration'), phase['key'])
        self.assertEqual(previous_goal, result['move_position'])
        self.assertFalse(result['fire_allowed'])

    def test_probe_pending_retains_cursor_and_stalls_after_finite_budget(self):
        scene = self.scene(['pending'] * 30)
        first = scene.apply(0.)
        phase = scene.owner._physical_recovery
        self.assertEqual('engage', first['combat_mode'])
        self.assertEqual((0, None), (phase['cursor'], phase['goal']))
        scene.apply(1.)
        self.assertIs(phase, scene.owner._physical_recovery)
        self.assertEqual(0, phase['cursor'])
        result = scene.apply(10.)
        self.assertEqual('route', result['combat_mode'])
        self.assertEqual((20., 0., -30.), result['move_position'])
        self.assertFalse(scene.owner.stop_allowed)
        self.assertEqual('point_recovery_exhausted', scene.owner.receipt['reason'])

    def test_real_arrival_requests_current_position_recheck_not_fire(self):
        scene = self.scene()
        scene.apply(0.)
        phase = scene.owner._physical_recovery
        scene.position(phase['goal'])
        arrived = scene.apply(.1)
        self.assertTrue(phase['checking'])
        self.assertIsNone(phase['goal'])
        self.assertEqual('engage', arrived['combat_mode'])
        self.assertFalse(arrived['fire_allowed'])
        scene.decide('wait', candidate=False, reason='native_geometry_refresh_pending')
        waiting = scene.apply(.2)
        self.assertIs(phase, scene.owner._physical_recovery)
        self.assertTrue(phase['checking'])
        self.assertFalse(waiting['fire_allowed'])

    def test_unproved_arrival_cannot_restart_the_same_route_indefinitely(self):
        scene = self.scene(['blocked'] * 40)
        for tick in range(20):
            result = scene.apply(tick * .1)
            if not scene.owner.stop_allowed:
                break
        self.assertFalse(scene.owner.stop_allowed)
        self.assertEqual('route', result['combat_mode'])
        count = len(scene.probes)
        for now in (2., 2.1, 2.3, 3., 4.):
            self.assertEqual('route', scene.apply(now)['combat_mode'])
        self.assertEqual(count, len(scene.probes))

    def test_material_source_translation_unlocks_fresh_selected_point_review(self):
        scene = self.scene(['blocked'] * 40)
        for tick in range(20):
            scene.apply(tick * .1)
            if not scene.owner.stop_allowed:
                break
        self.assertFalse(scene.owner.stop_allowed)
        scene.position((.5, 0., 0.))
        self.assertEqual('route', scene.apply(2.)['combat_mode'])
        scene.position((1., 0., 0.))
        result = scene.apply(2.1)
        self.assertFalse(scene.owner.stop_allowed)
        scene.runtime.point_recovery_probe = lambda *args: dict(status='clear')
        result = scene.apply(2.2)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertIsNotNone(scene.owner._physical_recovery)
        self.assertFalse(result['fire_allowed'])

    def test_unrelated_target_motion_cannot_unlock_failed_selected_sample(self):
        scene = self.scene(['blocked'] * 40)
        for tick in range(20):
            scene.apply(tick * .1)
            if not scene.owner.stop_allowed:
                break
        scene.runtime._targets += (dict(scene.target, id=3, network_id=3),)
        scene.runtime._targets[-1]['position'] = (0., 0., 1000.)
        self.assertEqual('route', scene.apply(2.)['combat_mode'])
        scene.target['position'] = (0., 0., 79.)
        scene.apply(2.1)
        self.assertFalse(scene.owner.stop_allowed)
        self.assertTrue(scene.owner.physical_recovery_pending())
        scene.runtime.point_recovery_probe = lambda *args: dict(status='clear')
        scene.apply(2.2)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertIsNotNone(scene.owner._physical_recovery)

    def test_yaw_change_requests_review_but_cannot_certify_movement(self):
        scene = self.scene(['blocked'] * 40)
        for tick in range(20):
            scene.apply(tick * .1)
            if not scene.owner.stop_allowed:
                break
        scene.state['yaw'] = .02
        self.assertEqual('route', scene.apply(2.)['combat_mode'])
        scene.state['yaw'] = .16
        scene.apply(2.1)
        self.assertFalse(scene.owner.stop_allowed)
        self.assertTrue(scene.owner.physical_recovery_pending())
        scene.runtime.point_recovery_probe = lambda *args: dict(status='clear')
        scene.apply(2.2)
        self.assertTrue(scene.owner.stop_allowed)

    def test_navigation_decision_and_real_mission_handoff_return_original_driver(self):
        for outcome in ('navigate', 'team_return_base', 'withdraw'):
            with self.subTest(outcome=outcome):
                scene = self.scene()
                scene.apply(0.)
                if outcome == 'navigate':
                    scene.decide('navigate', candidate=False,
                                 reason='no_executable_he_contact')
                else:
                    scene.raw_order.update(combat_mode=outcome)
                result = scene.apply(.1)
                self.assertEqual(outcome if outcome != 'navigate' else 'route',
                                 result['combat_mode'])
                self.assertEqual((20., 0., -30.), result['move_position'])
                self.assertFalse(scene.owner.stop_allowed)
                self.assertIsNone(scene.owner._physical_recovery)


class RecoveryDecisionEpisodeTests(unittest.TestCase):
    @staticmethod
    def policy_and_candidate():
        policy = AttackPolicy(SimpleNamespace(), evaluator=SimpleNamespace())
        policy._executable_current = lambda *args: True
        target = dict(kind='bot', id=2, network_id=2, position=(0., 0., 40.))
        candidate = dict(target=target, target_key=('bot', 2), shell_index=0,
            sample=0, key=(0, ('bot', 2), 0, 'penetration'), mode='penetration',
            armor='passed', line='clear', mechanical='reachable',
            solution=dict(point=(0., 1., 40.)))
        return policy, candidate

    def test_native_query_wait_does_not_reissue_recovery_episode(self):
        policy, candidate = self.policy_and_candidate()
        first = policy._choose('firing_position', 'blocked_current_point', candidate)
        episode = first['move_request']['episode_id']
        for reason in ('global_snapshot_budget_pending',
                       'he_damage_comparison_pending', 'observation_unavailable'):
            policy._choose('wait', reason)
            resumed = policy._choose('firing_position', 'current_point_still_blocked', candidate)
            self.assertEqual(episode, resumed['move_request']['episode_id'])
            self.assertEqual(candidate['key'], resumed['move_request']['key'])
            self.assertNotIn('deadline', resumed['move_request'])
        self.assertFalse(hasattr(policy, 'search_started'))

    def test_actual_completion_starts_new_recovery_episode_without_search(self):
        for completion in ('aim', 'navigate', 'switch_shell', 'reload_clip'):
            with self.subTest(completion=completion):
                policy, candidate = self.policy_and_candidate()
                first = policy._choose('firing_position', 'native_blocked', candidate)
                policy._choose(completion, 'native_terminal', candidate)
                later = policy._choose('firing_position', 'new_obstruction', candidate)
                self.assertNotEqual(first['move_request']['episode_id'],
                                    later['move_request']['episode_id'])
                self.assertFalse(hasattr(policy, 'search_authority'))


class NativeRecoveryAndLaunchTests(unittest.TestCase):
    def test_limited_hull_lay_and_real_trigger_are_not_a_preview(self):
        scene = TraverseScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(limits=(-.2, .2), bearing=.7, clip=1)
        scene.rotator_enabled = True
        starting_ammo = tuple(scene.battle._gun_state.ammo)
        for unused in range(160):
            scene.tick()
            if scene.control.automatic_commits:
                break
        self.assertEqual(1, scene.control.automatic_commits)
        self.assertEqual(starting_ammo[0] - 1, scene.battle._gun_state.ammo[0])
        self.assertEqual(1, len(scene.launches()))
        self.assertTrue(any(row['hull_aiming'] for row in scene.trace))
        self.assertFalse(hasattr(scene.runtime.engine, '_gun_angle_order'))
        self.assertFalse(hasattr(scene.runtime.attack_policy, 'search_started'))


if __name__ == '__main__':
    unittest.main()
