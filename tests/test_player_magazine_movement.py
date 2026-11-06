"""Magazine search/reload ownership through the final player movement sender.

Only native point/armor observations and native setting acceptance are seams.
PlayerControl, DirectEngagement, navigation, movement guards, next-clip requests
and GunState are production consumers. These tests establish ordering and
termination, not physical reachability of an authored Windows game position.
"""
from types import SimpleNamespace
import unittest
from unittest import mock

from test_player_magazine_policy import MagazineScene
from test_player_stationary_engagement import StationaryScenario


class MagazineMovementScene(object):
    def __init__(self, test, blocked=False, loaded=0):
        self.scene = StationaryScenario(distance=100.)
        self.policy = MagazineScene(6, 3, loaded=loaded)
        self.control = control = self.scene.control
        self.owner, self.gun = control.owner, self.policy.gun
        self.policy.target = self.scene.target
        self.owner._gun_state = self.scene.gun = self.gun
        self.owner._local_player_burst = self.owner._local_fire_intent = None
        self.scene.entity.typeDescriptor = self.policy.descriptor
        self.policy.descriptor.type = SimpleNamespace(tags=('mediumTank',))
        self.policy.descriptor.maxHealth = 1000
        for shot in self.gun.shots:
            shot.update(speed=1000., gravity=0., maxDistance=720.)
        control.direct_engagement = self.policy.state
        control.ammo_policy = self.policy.control.ammo_policy
        control.ammo_policy.context = lambda *unused: None
        control.aiming.compare_direct = self.compare
        control.aiming.direct_samples = lambda unused: 2
        control.aiming.direct_pose = lambda unused: (
            self.scene.position, 0., self.scene.target.position, 0., 0., 0., 0.)
        control.aiming.defer_ordered_point = mock.Mock()
        control.lane_from = mock.Mock(return_value=True)
        control.direction_clear = lambda *unused: not blocked
        control.probe_receipt = dict(collision=blocked)
        control.navigation.navigator.report_blocked_corridor = mock.Mock()
        control.navigation.firing_position = mock.Mock(wraps=control.navigation.firing_position)
        control.navigation.ammo_withdrawal = mock.Mock(wraps=control.navigation.ammo_withdrawal)
        test.addCleanup(control.navigation.close)
        self.settings = settings = SimpleNamespace(
            CURRENT_SHELLS=1, NEXT_SHELLS=2, RELOAD_PARTIAL_CLIP=3)
        self.owner._runtime = SimpleNamespace(constants=SimpleNamespace(VEHICLE_SETTING=settings))
        self.events = []
        self.owner._sender.send_current.side_effect = self.sent
        self.owner.change_vehicle_setting = mock.Mock(side_effect=self.change)
        self.policy.ready(1)

    def compare(self, target, shell, sample, now, lane, threshold, **options):
        verdict, solution = self.policy.compare(target, shell, sample, now, lane, threshold, **options)
        solution.update(point=(target.position[0], 1., target.position[2]),
                        source_point=target.position, clear=verdict == 'ready')
        return verdict, solution

    def sent(self):
        sender = self.owner._sender
        self.events.append(('movement', self.scene.now, self.control.last_order.get('combat_mode'),
                            sender.forward, sender.turn, sender.handbrake))
        return True

    def change(self, code, compact):
        self.events.append(('setting', self.scene.now, code, compact,
                            self.control.last_order.get('combat_mode')))
        if code == self.settings.RELOAD_PARTIAL_CLIP:
            return self.gun.reload_partial_clip()
        if code == self.settings.NEXT_SHELLS:
            self.gun.request_shell_index(compact-100)
        else:
            self.gun.sync_shell_index(compact-100)
        return True

    def step(self, now):
        self.scene.now = now
        with mock.patch('gui.mods.offline_lan_0922.player_control.weapon.barrel_aligned',
                        return_value=True):
            self.control.update(.11, now)
        return self.control.last_order

    def run_until_reload(self, count=160):
        for tick in range(count):
            self.step(tick*.11)
            if self.gun.clip == 0:
                return


class MagazineMovementTests(unittest.TestCase):
    def test_search_is_bounded_then_final_withdrawal_precedes_partial_reload(self):
        for blocked, loaded in ((False, 0), (True, 0), (False, 2), (True, 2)):
            with self.subTest(blocked=blocked, loaded=loaded):
                scene = MagazineMovementScene(self, blocked, loaded)
                initial = tuple(scene.gun.ammo)
                scene.run_until_reload()
                reloads = [i for i, row in enumerate(scene.events)
                           if row[0] == 'setting' and row[2] == scene.settings.RELOAD_PARTIAL_CLIP]
                self.assertEqual(1, len(reloads), (scene.control.last_order, scene.events[-5:]))
                at = reloads[0]
                movement = next(row for row in reversed(scene.events[:at]) if row[0] == 'movement')
                self.assertEqual(scene.events[at][1], movement[1])
                self.assertIn(movement[2], ('ammo_retreat', 'ammo_retreat_hold'))
                self.assertLessEqual(movement[3], 0.)
                self.assertEqual(0., movement[4])
                self.assertGreaterEqual(movement[1], 8.)
                self.assertEqual((1, 0, scene.gun.reload),
                                 (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
                self.assertEqual(initial, tuple(scene.gun.ammo))
                self.assertTrue(scene.control.last_order['magazine_reload_started']['after_withdrawal'])
                self.assertGreater(scene.control.navigation.firing_position.call_count, 0)
                for tick in range(5):
                    scene.step(movement[1] + .2 + tick*.11)
                self.assertEqual(1, sum(row[0] == 'setting' and row[2] == scene.settings.RELOAD_PARTIAL_CLIP
                                        for row in scene.events))

    def test_explicit_move_has_no_search_credit_or_partial_reload(self):
        scene = MagazineMovementScene(self)
        scene.control.navigation.start_mission('hold_position', dict(position=(0., 0., 140.)),
            dict(now=0., position=scene.scene.position, speed=0., yaw=0.))
        scene.run_until_reload()
        self.assertEqual((0, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
        self.assertEqual(0., scene.control.direct_engagement.search_elapsed)
        scene.control.navigation.firing_position.assert_not_called()
        scene.control.navigation.ammo_withdrawal.assert_not_called()
        self.assertFalse(any(row[0] == 'setting' for row in scene.events))

    def test_no_drive_owner_cannot_convert_scan_time_into_a_reload(self):
        scene = MagazineMovementScene(self)
        scene.control.features.remove('drive')
        scene.run_until_reload()
        self.assertEqual(0., scene.control.direct_engagement.search_elapsed)
        self.assertEqual((0, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
        self.assertFalse(any(row[0] == 'setting' for row in scene.events))

    def test_completed_unknown_never_discards_the_current_magazine(self):
        scene = MagazineMovementScene(self)
        scene.policy.verdicts[(0, 0)] = 'unknown'
        scene.run_until_reload()
        self.assertEqual((0, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
        self.assertEqual(0., scene.control.direct_engagement.search_elapsed)
        self.assertFalse(any(row[0] == 'setting' for row in scene.events))

    def test_manual_next_clip_plan_is_preserved_during_automatic_search_timeout(self):
        scene = MagazineMovementScene(self)
        scene.gun.request_shell_index(2)
        scene.run_until_reload()
        self.assertEqual((0, 6, 2, 0.),
                         (scene.gun.shot_index, scene.gun.clip, scene.gun.pending_index, scene.gun.reload_time))
        self.assertFalse(any(row[0] == 'setting' for row in scene.events))

    def test_stop_reentered_from_withdrawal_sender_revokes_the_reload(self):
        scene = MagazineMovementScene(self)
        scene.control.weapon.close = mock.Mock()
        scene.control.notify = mock.Mock()
        stopped = []
        def send_and_stop():
            scene.sent()
            if (scene.control.active and scene.control.last_order.get('combat_mode') in
                    ('ammo_retreat', 'ammo_retreat_hold')):
                stopped.append(True)
                scene.control.stop('test_stop_during_withdrawal_commit')
            return True
        scene.owner._sender.send_current.side_effect = send_and_stop
        for tick in range(160):
            scene.step(tick*.11)
            if stopped:
                break
        self.assertTrue(stopped)
        self.assertFalse(scene.control.active)
        self.assertEqual((0., 0.), (scene.owner._sender.forward, scene.owner._sender.turn))
        self.assertEqual((0, 6, None, 0.),
                         (scene.gun.shot_index, scene.gun.clip, scene.gun.pending_index, scene.gun.reload_time))
        self.assertFalse(any(row[0] == 'setting' and row[2] == scene.settings.RELOAD_PARTIAL_CLIP
                             for row in scene.events))

    def test_rejected_withdrawal_submission_cannot_unload_until_a_later_acceptance(self):
        scene = MagazineMovementScene(self)
        def refuse_withdrawal():
            scene.sent()
            return scene.control.last_order.get('combat_mode') not in ('ammo_retreat', 'ammo_retreat_hold')
        scene.owner._sender.send_current.side_effect = refuse_withdrawal
        scene.run_until_reload()
        self.assertEqual((0, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
        self.assertTrue(any(row[0] == 'movement' and row[2] in ('ammo_retreat', 'ammo_retreat_hold')
                            for row in scene.events))
        self.assertFalse(any(row[0] == 'setting' and row[2] == scene.settings.RELOAD_PARTIAL_CLIP
                             for row in scene.events))
        scene.owner._sender.send_current.side_effect = scene.sent
        for tick in range(10):
            scene.step(18. + tick*.11)
            if scene.gun.clip == 0:
                break
        self.assertEqual((1, 0, scene.gun.reload),
                         (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))


if __name__ == '__main__':
    unittest.main()
