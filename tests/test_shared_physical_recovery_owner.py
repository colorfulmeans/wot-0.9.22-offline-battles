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
    def scene(self, statuses=None, admitted=True):
        scene = Scene(admitted=admitted)
        scene.raw_order.update(combat_mode='route', target_kind=None, target_id=None,
            move_position=(20., 0., -30.), throttle_override=None,
            aim_position=None, fire_allowed=False)
        scene.candidate.update(mechanical='mechanical_limited', line='clear',
            key=(0, ('bot', 2), 0, 'penetration'), sample=0)
        statuses = list(statuses or ())
        scene.probes = []
        def probe(candidate, position, now):
            scene.probes.append((candidate['key'], tuple(position), now))
            return dict(status=statuses.pop(0) if statuses else 'clear',
                        fire_permission=False)
        scene.runtime.point_recovery_probe = probe
        return scene

    def test_new_stationary_sample_cannot_steal_an_active_physical_move(self):
        scene = self.scene()
        first = scene.apply(0.)
        marker = scene.owner._physical_recovery
        goal = marker['goal']
        self.assertEqual('gun_angle_adjust', first['combat_mode'])
        scene.stationary()
        for now in (.1, .2, .3, 1.):
            result = scene.apply(now)
            self.assertIs(marker, scene.owner._physical_recovery)
            self.assertEqual(0., marker['started'])
            self.assertNotEqual('native_lay', scene.owner.receipt['reason'])
            self.assertEqual(goal, result['move_position'])
            self.assertFalse(result['fire_allowed'])

    def test_exhausted_physical_move_returns_route_without_same_pose_reentry(self):
        scene = self.scene()
        scene.apply(0.)
        result = scene.apply(10.)
        self.assertEqual('point_recovery_drive_stalled', scene.owner.receipt['reason'])
        self.assertEqual('route', result['combat_mode'])
        self.assertEqual((20., 0., -30.), result['move_position'])
        self.assertFalse(scene.owner.stop_allowed)
        self.assertIsNone(scene.owner._physical_recovery)
        for now in (10.1, 11., 20.):
            self.assertEqual('route', scene.apply(now)['combat_mode'])
        scene.candidate.update(mechanical='reachable', line='clear', armor='passed')
        scene.decide('aim')
        result = scene.apply(20.1)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertEqual('engage', result['combat_mode'])

    def test_candidate_churn_cannot_change_the_active_physical_target_or_goal(self):
        scene = self.scene()
        other = dict(scene.target, network_id=3, id=3, position=(60., 0., 0.))
        scene.runtime._targets = (scene.target, other)
        scene.apply(0.)
        marker = scene.owner._physical_recovery
        destination = marker['goal']
        for now, selected in ((.1, other), (.2, scene.target),
                              (.3, other), (.4, other)):
            scene.candidate['target'] = selected
            scene.decide('wait' if now == .4 else 'firing_position',
                         candidate=now != .4, reason='new_sample_pending')
            result = scene.apply(now)
            self.assertIs(marker, scene.owner._physical_recovery)
            self.assertEqual(destination, result['move_position'])
            self.assertEqual(('bot', 2), scene.owner._physical_recovery['target'])
            self.assertEqual(2, result['target_id'])
            self.assertFalse(result['fire_allowed'])

    def test_small_pose_change_without_new_proof_keeps_checked_goal(self):
        scene = self.scene()
        scene.apply(0.)
        marker = scene.owner._physical_recovery
        goal = marker['goal']
        scene.stationary()
        scene.candidate['fresh'] = False
        scene.position((.25, 0., 0.))
        result = scene.apply(.1)
        self.assertIs(marker, scene.owner._physical_recovery)
        self.assertEqual(goal, result['move_position'])
        self.assertEqual('gun_angle_adjust', result['combat_mode'])

    def test_new_physical_context_rechecks_before_it_can_acquire_movement(self):
        for retry_at in (1., 18.):
            with self.subTest(retry_at=retry_at):
                scene = self.scene(['blocked'] * 40)
                for step in range(20):
                    scene.apply(step * .1)
                    if not scene.owner.stop_allowed:
                        break
                self.assertFalse(scene.owner.stop_allowed)
                scene.position((1., 0., 0.))
                scene.apply(retry_at)
                self.assertFalse(scene.owner.physical_recovery_active())
                self.assertTrue(scene.owner.physical_recovery_pending())
                scene.runtime.point_recovery_probe = lambda *args: dict(status='clear')
                scene.apply(retry_at + .1)
                self.assertTrue(scene.owner.physical_recovery_active())
                self.assertIsNone(scene.owner._failed_recovery)

    def test_verified_shot_retires_its_own_lease_before_new_blocker(self):
        scene = self.scene()
        scene.apply(0.)
        phase = scene.owner._physical_recovery
        scene.candidate.update(mechanical='reachable', line='clear', armor='passed')
        scene.decide('aim')
        scene.apply(.1)
        self.assertTrue(phase['ready'])
        scene.apply(.2)
        self.assertIsNone(scene.owner._physical_recovery)
        scene.candidate.update(line='world_blocked')
        scene.decide('firing_position')
        scene.apply(.3)
        self.assertIsNotNone(scene.owner._physical_recovery)
        self.assertEqual(.3, scene.owner._physical_recovery['started'])

    def test_unverified_world_blocker_cannot_steal_cold_route(self):
        scene = self.scene(admitted=False)
        scene.candidate.update(mechanical='reachable', line='world_blocked',
            armor='unknown', pose_stamp=None, line_stamp=None)
        scene.decide('firing_position', reason='current_he_world_blocked')
        for now in (0., .1, 1., 10.):
            result = scene.apply(now)
            self.assertEqual('route', result['combat_mode'])
            self.assertEqual((20., 0., -30.), result['move_position'])
            self.assertFalse(scene.owner.combat_owned)
            self.assertIsNone(scene.owner._physical_recovery)

    def test_pending_geometry_without_real_refusal_cannot_start_pursuit(self):
        scene = self.scene()
        scene.candidate.update(mechanical='reachable', line='clear', armor='unknown')
        scene.decide('firing_position', reason='global_snapshot_budget_pending')
        result = scene.apply(0.)
        self.assertEqual('engage', result['combat_mode'])
        self.assertEqual(scene.state['position'], result['move_position'])
        self.assertEqual(0., result['throttle_override'])
        self.assertIsNone(scene.owner._physical_recovery)

    def test_known_world_blocker_uses_local_checked_point_not_enemy_centre(self):
        scene = self.scene()
        scene.candidate.update(mechanical='reachable', line='world_blocked', armor='passed')
        scene.decide('firing_position', reason='current_penetration_obstructed')
        result = scene.apply(0.)
        self.assertEqual('gun_angle_adjust', result['combat_mode'])
        self.assertNotEqual(scene.target['position'], result['move_position'])
        self.assertLessEqual(abs(result['move_position'][2]), 12.)
        self.assertEqual(scene.candidate['key'], scene.probes[0][0])
        self.assertFalse(result['fire_allowed'])

    def test_stationary_lay_has_no_independent_rear_or_gun_angle_finder(self):
        scene = self.scene()
        scene.stationary()
        scene.state['_gun_angle_refusal'] = ('bot', 2)
        result = scene.apply(0.)
        self.assertEqual('native_lay', scene.owner.receipt['reason'])
        self.assertEqual(0., result['throttle_override'])
        self.assertIsNone(scene.owner._physical_recovery)
        self.assertFalse(hasattr(scene.runtime.engine, '_gun_angle_order'))
        rear = scene.runtime.engine._rear_laying_order(
            scene.state, result, {2: scene.target}, .1)
        self.assertEqual(result, rear)
        self.assertNotIn('_rear_aim_episode', scene.state)

    def test_friendly_recovery_retains_one_checked_point_during_sample_changes(self):
        scene = self.scene()
        scene.candidate.update(mechanical='reachable', line='friendly_blocked',
            blocker=dict(blocker_kind='bot', blocker_id=5, blocker_team=1,
                blocker_position=(0., 0., 12.), blocker_radius=2.))
        scene.apply(0.)
        marker = scene.owner._physical_recovery
        goal = marker['goal']
        scene.stationary()
        for now in (.1, .2, .3):
            result = scene.apply(now)
            self.assertNotEqual('native_lay', scene.owner.receipt['reason'])
            self.assertIs(marker, scene.owner._physical_recovery)
            self.assertEqual(goal, result['move_position'])
            self.assertEqual(scene.candidate['key'], marker['key'])
            self.assertFalse(result['fire_allowed'])

    def test_failed_friendly_escape_releases_route_without_restarting_same_lane(self):
        scene = self.scene()
        scene.candidate.update(mechanical='reachable', line='friendly_blocked',
            blocker=dict(blocker_kind='bot', blocker_id=5, blocker_team=1,
                blocker_position=(0., 0., 12.), blocker_radius=2.))
        scene.apply(0.)
        scene.apply(6.)
        self.assertIsNone(scene.owner._physical_recovery)
        for now in (6.1, 16.):
            result = scene.apply(now)
            self.assertFalse(scene.owner.stop_allowed)
            self.assertEqual('route', result['combat_mode'])
            self.assertEqual((20., 0., -30.), result['move_position'])
            self.assertIsNone(scene.owner._physical_recovery)


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
