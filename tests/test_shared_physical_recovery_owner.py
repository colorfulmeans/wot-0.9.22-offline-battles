"""One finite combat movement owner; no implicit chase/capture takeover.

Boundary cases use explicit supplied native evidence and the real bounded
driver recovery. The capture case runs the complete player policy/planner
loop. Neither set proves native Windows movement or frame pacing.
"""
import contextlib
import io
import unittest

from test_player_combat_stop import Scene
from test_player_combat_ownership import OwnershipScene
from gui.mods.offline_lan_0922.ai.driver import WAYPOINT_ARRIVAL_RADIUS


class PhysicalRecoveryOwnershipTests(unittest.TestCase):
    def scene(self):
        scene = Scene()
        scene.runtime.engine._actor_controls = {1: scene.runtime}
        scene.raw_order.update(combat_mode='route', target_id=None, target_kind=None,
            move_position=(20., 0., -30.), throttle_override=None,
            aim_position=None, fire_allowed=False)
        scene.candidate.update(mechanical='mechanical_limited', line='clear')
        return scene

    @staticmethod
    def consume(scene, now):
        order = scene.apply(now)
        return scene.runtime.engine._gun_angle_order(
            scene.state, order, {2: scene.target}, now, lambda *args: True)

    def test_new_stationary_sample_cannot_steal_an_active_physical_move(self):
        scene = self.scene()
        self.consume(scene, 0.)
        marker = scene.state['_gun_angle_adjustment']
        self.consume(scene, 2.1)
        destination = marker['destination']
        scene.stationary()
        for now in (2.2, 2.3, 3., 4.):
            result = self.consume(scene, now)
            self.assertIs(marker, scene.state['_gun_angle_adjustment'])
            self.assertEqual(0., marker['start'])
            self.assertNotEqual('native_lay', scene.owner.receipt['reason'])
            self.assertEqual('gun_angle_adjust', result['combat_mode'])
            self.assertEqual(destination, result['move_position'])
            self.assertFalse(result['fire_allowed'])

    def test_exhausted_physical_move_returns_route_and_does_not_reacquire_same_pose(self):
        scene = self.scene()
        self.consume(scene, 0.)
        self.consume(scene, 2.1)
        self.consume(scene, 3.)
        result = self.consume(scene, 9.1)
        self.assertEqual('relocation_stalled', scene.state['_gun_angle_last_terminal']['reason'])
        self.assertEqual('route', result['combat_mode'])
        self.assertEqual((20., 0., -30.), result['move_position'])
        self.assertFalse(scene.owner.stop_allowed)
        for now in (9.2, 10., 20.):
            result = self.consume(scene, now)
            self.assertEqual('route', result['combat_mode'])
            self.assertEqual((20., 0., -30.), result['move_position'])
            self.assertNotIn('_gun_angle_adjustment', scene.state)
        # A newly executable shot is not blocked by a movement-failure receipt.
        scene.candidate.update(mechanical='reachable', line='clear', armor='passed')
        scene.decide('aim')
        result = self.consume(scene, 20.1)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertEqual('engage', result['combat_mode'])
        self.assertEqual(0., result['throttle_override'])

    def test_candidate_churn_cannot_change_the_active_physical_target_or_goal(self):
        scene = self.scene()
        other = dict(scene.target, network_id=3, id=3, position=(60., 0., 0.))
        scene.runtime._targets = (scene.target, other)
        self.consume(scene, 0.)
        self.consume(scene, 2.1)
        marker = scene.state['_gun_angle_adjustment']
        destination = marker['destination']
        for now, selected in ((2.2, other), (2.3, scene.target), (2.4, other), (2.5, other)):
            scene.candidate['target'] = selected
            if now == 2.5:
                scene.candidate['fresh'] = False
                scene.decide('aim')
            result = scene.apply(now)
            result = scene.runtime.engine._gun_angle_order(scene.state, result,
                {2: scene.target, 3: other}, now, lambda *args: True)
            self.assertIs(marker, scene.state['_gun_angle_adjustment'])
            self.assertEqual(0., marker['start'])
            self.assertEqual(2, result['target_id'])
            self.assertEqual(('bot', 2), scene.owner._physical_recovery['target'])
            self.assertEqual(('bot', 2), scene.owner.receipt['selected'])
            self.assertEqual(destination, result['move_position'])

    def test_changed_pose_without_current_stationary_proof_keeps_checked_physical_goal(self):
        scene = self.scene()
        self.consume(scene, 0.)
        self.consume(scene, 2.1)
        marker = scene.state['_gun_angle_adjustment']
        destination = marker['destination']
        scene.stationary()
        scene.candidate['fresh'] = False
        scene.position((WAYPOINT_ARRIVAL_RADIUS, 0., 0.))
        result = self.consume(scene, 2.2)
        self.assertIs(marker, scene.state['_gun_angle_adjustment'])
        self.assertEqual(destination, result['move_position'])
        self.assertEqual('gun_angle_adjust', result['combat_mode'])

    def test_new_physical_context_does_not_inherit_the_old_target_only_cooldown(self):
        for retry_at in (10., 18.):
            with self.subTest(retry_at=retry_at):
                scene = self.scene()
                self.consume(scene, 0.)
                self.consume(scene, 2.1)
                self.consume(scene, 3.)
                self.consume(scene, 9.1)
                self.assertFalse(scene.owner.stop_allowed)
                self.assertIn(('bot', 2), scene.state['_gun_angle_rejected'])
                scene.position((WAYPOINT_ARRIVAL_RADIUS, 0., 0.))
                self.consume(scene, retry_at)
                self.assertTrue(scene.owner.physical_recovery_active())
                self.assertEqual(retry_at, scene.state['_gun_angle_adjustment']['start'])
                self.assertIsNone(scene.owner._failed_recovery)
                self.assertNotIn(('bot', 2), scene.state['_gun_angle_rejected'])

    def test_verified_shot_retires_only_its_physical_lease_before_next_blocker(self):
        scene = self.scene()
        self.consume(scene, 0.)
        self.consume(scene, 2.1)
        first_marker = scene.state['_gun_angle_adjustment']
        scene.candidate.update(mechanical='reachable', line='clear', armor='passed')
        scene.decide('aim')
        self.consume(scene, 2.2)
        self.assertNotIn('_gun_angle_adjustment', scene.state)
        self.assertIsNone(scene.owner._physical_recovery)
        self.assertEqual('verified_shot', scene.state['_gun_angle_last_terminal']['reason'])
        scene.candidate.update(line='world_blocked')
        scene.decide('firing_position')
        self.consume(scene, 3.)
        self.assertIsNot(first_marker, scene.state['_gun_angle_adjustment'])
        self.assertEqual(3., scene.state['_gun_angle_adjustment']['start'])
        self.assertTrue(scene.owner.physical_recovery_active())

    def test_unverified_distant_world_blocker_cannot_admit_from_route(self):
        scene = Scene(admitted=False)
        scene.runtime.engine._actor_controls = {1: scene.runtime}
        scene.raw_order.update(combat_mode='route', target_id=None, target_kind=None,
            move_position=(20., 0., -30.), throttle_override=None,
            aim_position=None, fire_allowed=False)
        scene.candidate.update(mechanical='reachable', line='world_blocked', armor='unknown')
        scene.decide('firing_position', reason='current_he_world_blocked')
        for now in (0., .1, 1., 9.):
            result = self.consume(scene, now)
            self.assertEqual('route', result['combat_mode'])
            self.assertEqual((20., 0., -30.), result['move_position'])
            self.assertFalse(scene.owner.combat_owned)
            self.assertNotIn('_gun_angle_adjustment', scene.state)

    def test_pending_evidence_without_physical_refusal_cannot_start_pursuit(self):
        scene = self.scene()
        scene.candidate.update(mechanical='reachable', line='clear', armor='unknown')
        scene.decide('firing_position', reason='global_snapshot_budget_pending')
        result = self.consume(scene, 0.)
        self.assertEqual('engage', result['combat_mode'])
        self.assertEqual(scene.state['position'], result['move_position'])
        self.assertEqual(0., result['throttle_override'])
        self.assertNotIn('_gun_angle_adjustment', scene.state)

    def test_known_world_blocker_uses_finite_local_recovery_not_enemy_centre(self):
        scene = self.scene()
        scene.candidate.update(mechanical='reachable', line='world_blocked', armor='passed')
        scene.decide('firing_position', reason='current_penetration_obstructed')
        result = self.consume(scene, 0.)
        self.assertNotEqual(scene.target['position'], result['move_position'])
        self.consume(scene, 2.1)
        destination = scene.state['_gun_angle_adjustment']['destination']
        self.assertNotEqual(scene.target['position'], destination)
        self.assertLessEqual(abs(destination[2]), 8.)
        self.assertIsNone(scene.policy.search_started)

    def test_stationary_lay_has_no_second_rear_or_mechanical_decision(self):
        scene = self.scene()
        scene.stationary()
        # This is a leftover refusal from a previous physical observation,
        # not permission to contradict a fresh stationary native plan.
        scene.state['_gun_angle_refusal'] = ('bot', 2)
        result = self.consume(scene, 0.)
        self.assertEqual('native_lay', scene.owner.receipt['reason'])
        self.assertEqual(0., result['throttle_override'])
        self.assertNotIn('_gun_angle_adjustment', scene.state)
        rear = scene.runtime.engine._rear_laying_order(
            scene.state, result, {2: scene.target}, .1)
        self.assertEqual(result, rear)
        self.assertNotIn('_rear_aim_episode', scene.state)

    def test_friendly_escape_owns_one_goal_even_when_stationary_candidates_change(self):
        scene = self.scene()
        scene.candidate.update(mechanical='reachable', line='friendly_blocked',
            blocker=dict(blocker_kind='bot', blocker_id=5, blocker_team=1,
                blocker_position=(0., 0., 12.), blocker_radius=2.))
        scene.apply(0.)
        marker = scene.runtime.engine._friendly_repositions[1]
        scene.stationary()
        for now in (.1, .2, .3):
            result = self.consume(scene, now)
            self.assertNotEqual('native_lay', scene.owner.receipt['reason'])
            self.assertNotIn('_gun_angle_adjustment', scene.state)
            final, expired = scene.runtime.engine._friendly_reposition_order(
                scene.state, {2: scene.target}, now, result)
            self.assertFalse(expired)
            self.assertIs(marker, scene.runtime.engine._friendly_repositions[1])
            self.assertEqual(marker['destination'], final['move_position'])
        self.assertIsNone(scene.policy.search_started)

    def test_failed_friendly_escape_releases_route_without_restarting_the_same_lane(self):
        scene = self.scene()
        scene.candidate.update(mechanical='reachable', line='friendly_blocked',
            blocker=dict(blocker_kind='bot', blocker_id=5, blocker_team=1,
                blocker_position=(0., 0., 12.), blocker_radius=2.))
        initial = scene.apply(0.)
        marker = scene.runtime.engine._friendly_repositions[1]
        unused, expired = scene.runtime.engine._friendly_reposition_order(
            scene.state, {2: scene.target}, marker['deadline'], initial)
        self.assertTrue(expired)
        for now in (marker['deadline'] + .1, marker['deadline'] + 10.):
            result = scene.apply(now)
            self.assertFalse(scene.owner.stop_allowed)
            self.assertEqual('route', result['combat_mode'])
            self.assertEqual((20., 0., -30.), result['move_position'])
            self.assertNotIn(1, scene.runtime.engine._friendly_repositions)


class CombatCircleArrivalTests(unittest.TestCase):
    def test_crossing_capture_circle_during_combat_does_not_complete_suspended_route(self):
        with contextlib.redirect_stdout(io.StringIO()):
            scene = OwnershipScene()
            scene.setUp()
            self.addCleanup(scene.doCleanups)
            scene.configure(clip=1, burst=1)
            target = scene.eligible_enemy(5)
            for unused in range(20):
                scene.tick()
                if scene.runtime.combat_stop.combat_owned:
                    break
            self.assertTrue(scene.runtime.combat_stop.combat_owned)
            owner = scene.runtime.combat_stop
            episode = owner.receipt['episode']
            scene.battle._spawn_planner.capture_bases['2'] = [dict(x=0., z=0., radius=6.)]
            for unused in range(5):
                scene.runtime._strategic_due = 0.
                scene.tick()
                original = scene.original_order()
                self.assertNotIn('capture_area', original)
                self.assertEqual('route', original['combat_mode'])
                self.assertEqual(episode, owner.receipt['episode'])
                self.assertTrue(owner.stop_allowed)
                self.assertIsNone(scene.runtime._mission)
            # Combat really ends; ordinary physical circle arrival is still
            # allowed to constrain the resumed route on subsequent planning.
            scene.battle._records['bot:5']['state'].update(alive=False, health=0)
            target.health = 0
            for unused in range(3):
                scene.runtime._strategic_due = 0.
                scene.tick()
            self.assertFalse(owner.stop_allowed)
            self.assertIn('capture_area', scene.original_order())


if __name__ == '__main__':
    unittest.main()
