"""The reported blocked HE scans complete; they must not become a fire bypass."""
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from test_player_weapon_migration import aiming_scene
from gui.mods.offline_lan_0922.player_control.aiming import Aiming
from gui.mods.offline_lan_0922.player_control.direct_engagement import DirectEngagement


class BlockedScanLivenessTests(unittest.TestCase):
    def test_unchanged_blocked_targets_finish_and_rotate_during_410_second_hold(self):
        owner, first, shot, unused_body = aiming_scene()
        unused_owner, second, unused_shot, unused_body = aiming_scene(distance=110.)
        second.id = first.id + 1
        owner.local_pose = lambda: ((0., 0., 0.), 0.)
        gun = owner._gun_state
        gun.ammo, gun.clip, gun.clip_size, gun.reload_time = [56], 1, 1, 0.
        shot['shell']['kind'] = 'HIGH_EXPLOSIVE'
        aiming = Aiming(owner)
        engagement = DirectEngagement(owner._server_entity(1).typeDescriptor)
        engagement.search_since = 0.
        lane = mock.Mock(return_value=False)
        control = NS(owner=owner, aiming=aiming,
            ammo_policy=NS(main=0, shells=[dict(index=0, kind='HIGH_EXPLOSIVE')]),
            lane_from=lane, queue_automatic_shell=mock.Mock())
        completed, selected = 0, set()
        max_comparisons = 0
        for tick in range(4101):
            now = 8.1 + tick * .1
            aiming.begin([first, second], now)
            aiming.comparison_trace = []
            before = lane.call_count
            target, solution, ready = engagement.update(control, [first, second], now)
            selected.add(engagement.target)
            completed += engagement.scan is None
            max_comparisons = max(max_comparisons, len(aiming.comparison_trace))
            self.assertIsNone(target)
            self.assertIsNone(solution)
            self.assertFalse(ready)
            self.assertLessEqual(lane.call_count-before, 12)
            self.assertGreaterEqual(aiming._candidates, 0)
            self.assertGreaterEqual(aiming._segments, 0)
            for comparison in aiming.comparison_trace:
                self.assertEqual('unavailable', comparison['verdict'])
                self.assertEqual('world_blocked', comparison['reason'])
        self.assertEqual({first.id, second.id}, selected)
        # Nine fixed points at two per tick finish each five-tick scan.
        self.assertEqual(9, aiming.direct_samples(first))
        self.assertEqual(820, completed)
        self.assertEqual(2, max_comparisons)
        self.assertTrue(engagement.seek)
        self.assertIsNone(engagement.sample)
        control.queue_automatic_shell.assert_not_called()


if __name__ == '__main__':
    unittest.main()
