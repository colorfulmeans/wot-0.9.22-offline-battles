"""Released foreground bursts retain short waits, then release an unusable tail.

The controller, aim planner, physical admission, gun transaction and projectile
install are real. The existing fixture supplies native matrices, component
boxes, world segments and deterministic random draws. These tests do not claim
to reproduce native BigWorld rendering or vehicle physics.
"""
import math
import unittest
from unittest import mock

import test_player_fire_admission_complete as boundary
from gui.mods.offline_lan_0922 import ballistics
from gui.mods.offline_lan_0922.entities.remote_vehicle import collide_vehicle_at_matrix
from gui.mods.offline_lan_0922.player_control.aiming import Aiming
from gui.mods.offline_lan_0922.player_control.ammunition import policy_from_gun
from gui.mods.offline_lan_0922.player_control.direct_engagement import DirectEngagement, PENETRATION_FACTOR_65
from gui.mods.offline_lan_0922.player_control.weapon import Weapon


class PlayerBurstLivenessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = boundary.AutomaticFireAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.owner = self.fixture.battle
        self.control = self.fixture.control
        self.normal = 0.
        self.gauss = mock.patch(
            'gui.mods.offline_lan_0922.player_control.fire_admission.random.gauss',
            side_effect=lambda mean, sigma: mean + self.normal * sigma)
        self.uniform = mock.patch(
            'gui.mods.offline_lan_0922.player_control.fire_admission.random.uniform',
            return_value=.25)
        self.gauss.start()
        self.uniform.start()
        self.addCleanup(self.gauss.stop)
        self.addCleanup(self.uniform.stop)
        self.owner._config['perfect_accuracy'] = False
        self.owner._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        self._configure_control()

    def _configure_control(self):
        control, owner = self.control, self.owner
        control.active = True
        control.bind_input = lambda: None
        control.poll_commands = lambda now: None
        control.publish_status = lambda *args, **kwargs: None
        control.record = lambda *args, **kwargs: None
        control.target_engine = self.fixture.target.id
        control.ammo_policy = policy_from_gun(owner._gun_state, self.fixture.entity.typeDescriptor)
        control.direct_engagement = DirectEngagement(self.fixture.entity.typeDescriptor)
        control.direct_engagement.adopt(self.fixture.target.id, (0, PENETRATION_FACTOR_65))
        control.direct_engagement.sample = 0
        control.direct_engagement.last_solution = control.weapon.solution

    def _head(self):
        self.normal = 0.
        self.assertTrue(self.fixture.fire(), self.control.fire_admission.receipt)
        self.burst = self.owner._local_player_burst
        self.assertEqual(1, self.burst['committed'])
        self.normal = 1.
        return self.burst

    def _block(self, kind):
        if kind == 'world':
            # The center ray remains clear. Only this tail's frozen scatter
            # ray intersects the nearby world box.
            self.fixture.world = [((-2.5, 0., 19.), (-1.5, 3., 21.))]
            self.friend = None
        else:
            self.friend = self.fixture.vehicle(43, (-5., 0., 50.), 1)
            self.friend.collideSegmentExt = lambda first, last: collide_vehicle_at_matrix(
                self.friend, self.friend.matrix, first, last, self.owner._runtime.math)

    def _clear(self):
        self.fixture.world = []
        if self.friend is not None:
            self.fixture.pose(self.friend, (-20., 0., 50.))

    def _tick(self, seconds=.11):
        self.fixture.step(seconds)
        self.control.update(seconds, self.fixture.now)
        # The foreground frame advances its native gun clock in _drive_local
        # before consuming the released burst, including after cancellation.
        self.owner._advance_local_gun_to(self.fixture.entity, self.fixture.now)
        return self.owner._advance_local_player_burst()

    def _wait(self, seconds):
        end = self.fixture.now + seconds
        while self.fixture.now < end and self.owner._local_player_burst is self.burst:
            self._tick()

    def _assert_cancelled_without_tail_debit(self, reason):
        self.assertIsNone(self.owner._local_player_burst)
        self.assertIsNone(self.control.owned_burst)
        self.assertIsNone(self.owner._local_fire_intent)
        self.assertEqual(0, self.owner._gun_state._burst_remaining)
        self.assertEqual([19, 10], self.owner._gun_state.ammo)
        self.assertEqual(5, self.owner._gun_state.clip)
        self.assertEqual(1, self.control.shot_commits)
        self.assertEqual(1, len(self.owner._projectile_meta))
        self.assertEqual('rejected', self.control.fire_admission.receipt['status'])
        self.assertEqual(reason, self.control.fire_admission.receipt['reason'])

    def _persistent(self, kind):
        self._head()
        self._block(kind)
        self._tick()
        self.assertIs(self.burst, self.owner._local_player_burst)
        self.assertIsNone(self.control.blocked_fire_sample)
        self.assertFalse(self.owner._gun_state.can_fire(True))
        self._wait(5.3)
        self._assert_cancelled_without_tail_debit('auto_burst_path_timeout')
        # A path refusal is not a failed armor comparison and must not alter
        # the loaded cassette. The next trigger searches another point.
        direct = self.control.direct_engagement
        self.assertEqual(self.fixture.target.id, direct.target)
        self.assertIsNone(direct.sample)
        self.assertIsNone(direct.last_solution)
        self.assertIsNone(direct.failed_penetration_shells)
        self.assertGreater(self.control.aiming.comparison_deferrals[(42, 0, 0)],
                           self.fixture.now)
        self.assertEqual(0, self.owner._gun_state.shot_index)
        self.assertIsNone(self.owner._gun_state.pending_index)

    def test_persistent_scattered_world_refusal_releases_the_physical_tail(self):
        self._persistent('world')

    def test_persistent_scattered_friendly_refusal_releases_the_physical_tail(self):
        self._persistent('friend')

    def test_short_world_wait_resumes_the_same_group_without_rerolling(self):
        self._temporary('world')

    def test_short_friendly_wait_resumes_the_same_group_without_rerolling(self):
        self._temporary('friend')

    def _temporary(self, kind):
        self._head()
        self._block(kind)
        self._tick()
        candidate = self.control.fire_admission.pending
        velocity = tuple(candidate['proof']['velocity'])
        self._wait(.44)
        self.assertIs(self.burst, self.owner._local_player_burst)
        self.assertIs(candidate, self.control.fire_admission.pending)
        self.assertEqual([19, 10], self.owner._gun_state.ammo)
        self._clear()
        self.assertTrue(self._tick(), self.control.fire_admission.receipt)
        self.assertIs(self.burst, self.owner._local_player_burst)
        self.assertTrue(self._tick(), self.control.fire_admission.receipt)
        self.assertIsNone(self.owner._local_player_burst)
        self.assertEqual([17, 10], self.owner._gun_state.ammo)
        launches = sorted(self.owner._projectile_meta.values(), key=lambda row: row['shot_seq'])
        self.assertEqual([0, 1, 2], [row['burst_index'] for row in launches])
        self.assertEqual(1, len({row['burst_group_seq'] for row in launches}))
        self.assertEqual(velocity, tuple(launches[1]['velocity']))

    def test_pose_wait_after_a_real_refusal_does_not_renew_the_deadline(self):
        self._head()
        self._block('world')
        self._tick()
        self.fixture.pose(self.fixture.target, (10., 0., 100.))
        self._tick()
        self.assertEqual('auto_actual_barrel_laying', self.control.last_fire_failure)
        self._wait(5.)
        self._assert_cancelled_without_tail_debit('auto_burst_path_timeout')

    def test_next_trigger_rechecks_another_point_and_uses_the_remaining_clip(self):
        self._persistent('world')
        old_group = self.burst['group_seq']
        self._clear()
        self.normal = 0.
        for unused in range(35):
            # Supply native barrel convergence to the actual newly requested
            # point. Current armor, world, friend and projectile checks remain
            # real; only the native gun actuator is represented here.
            point, origin = self.control.weapon.point, self.fixture.origin
            shot = self.owner._gun_state.shots[0]
            pitch = ballistics.ballistic_solutions(origin, point, shot.speed, shot.gravity)[0][0]
            yaw = math.atan2(point[0]-origin[0], point[2]-origin[2])
            self.fixture.direction = (math.sin(yaw)*math.cos(pitch),
                -math.sin(pitch), math.cos(yaw)*math.cos(pitch))
            self._tick()
            if self.control.shot_commits > 1:
                break
        self.assertEqual(2, self.control.shot_commits)
        self.assertEqual([18, 10], self.owner._gun_state.ammo)
        self.assertEqual(4, self.owner._gun_state.clip)
        self.assertEqual(0, self.owner._gun_state.shot_index)
        self.assertNotEqual(0, self.control.direct_engagement.sample)
        self.assertEqual(self.control.direct_engagement.sample, self.control.weapon.solution['sample'])
        self.assertNotEqual(old_group, self.owner._local_player_burst['group_seq'])
        self.assertEqual('committed', self.control.fire_admission.receipt['status'])

    def test_target_death_cancels_immediately_without_a_path_timeout(self):
        self._head()
        self._block('world')
        self._tick()
        self.fixture.target.health = 0
        self.owner._records['test:42']['state'].update(health=0, alive=False)
        self._tick()
        self._assert_cancelled_without_tail_debit('auto_target_lost')
        self.assertNotIn((42, 0, 0), self.control.aiming.comparison_deferrals)

    def test_stop_releases_the_wait_without_committing_or_retaining_a_tail(self):
        self._head()
        self._block('world')
        self._tick()
        self.assertTrue(self.control.stop('test_stop'))
        self.fixture.fixture.now += 6.
        self.assertFalse(self.owner._advance_local_player_burst())
        self.assertIsNone(self.owner._local_player_burst)
        self.assertIsNone(self.control.owned_burst)
        self.assertEqual(0, self.owner._gun_state._burst_remaining)
        self.assertEqual([19, 10], self.owner._gun_state.ammo)
        self.assertEqual(1, len(self.owner._projectile_meta))

    def test_retired_session_callback_cannot_cancel_or_defer_a_new_burst(self):
        old = self._head()
        self._block('world')
        self._tick()
        self.control.stop('round_changed')
        self.owner._generation += 1
        self.owner._start_message['round_id'] = 99
        self.fixture.fixture.now += 6.
        self.owner._advance_local_gun_to(self.fixture.entity, self.fixture.now)
        self._clear()
        self.control.aiming = Aiming(self.owner)
        self.control.weapon = Weapon(self.owner)
        self.fixture.lay()
        self._configure_control()
        current = self._head()
        self.assertIsNot(old, current)
        self.control.burst_cancelled(old)
        self.assertIs(current, self.owner._local_player_burst)
        self.assertIs(current, self.control.owned_burst)
        self.assertEqual(0, self.control.direct_engagement.sample)
        self.assertNotIn((42, 0, 0), self.control.aiming.comparison_deferrals)
        self._block('world')
        self._tick()
        self.assertIs(current, self.owner._local_player_burst)
        self.assertEqual(2, self.control.shot_commits)

    def test_spg_preserves_its_existing_tail_wait_behavior(self):
        self.fixture.entity.typeDescriptor.type.tags = frozenset(('SPG',))
        self._head()
        self._block('world')
        self._wait(6.)
        self.assertIs(self.burst, self.owner._local_player_burst)
        self.assertEqual('auto_world_blocked', self.control.last_fire_failure)
        self.assertEqual([19, 10], self.owner._gun_state.ammo)
        self.assertEqual(1, self.control.shot_commits)


if __name__ == '__main__':
    unittest.main()
