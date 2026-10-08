"""Report 204046: an erased slope entry must not sustain a pivot loop."""
import unittest
import math
from unittest import mock
from test_port_0922_navigation import TerrainNavigator, LocalDriver


class SheridanIngressTests(unittest.TestCase):
    def test_search_and_combat_changes_do_not_erase_stationary_evidence(self):
        nav = TerrainNavigator(lambda *unused: 0.0, lambda *unused: False, cell_size=4.0)
        current = (-401.67, 51.28, -310.89)
        escape = (-399.67, 50.9, -311.89)
        with mock.patch.object(nav.grid, 'safe_local_target', return_value=escape) as choose:
            for now in range(12):
                nav.next_target(29, current, (-295.829 + now, 0.0, -274.558),
                                ('local', 29, now), float(now))
            choose.reset_mock()
            selected = nav.next_target(29, current, (-295.829, 0.0, -274.558),
                                       ('route', 2, 'middle'), 12.0)
            self.assertEqual(escape, selected)
            self.assertEqual(1, choose.call_count)
            with mock.patch.object(nav.grid, 'dry_segment_clear', return_value=True):
                self.assertEqual(escape, nav.next_target(
                    29, current, (10.0, 20.0, 10.0), ('local', 29, 'combat'), 13.0))
            self.assertEqual(1, choose.call_count)

    def test_scripted_hold_does_not_start_escape(self):
        nav = TerrainNavigator(lambda *unused: 0.0, lambda *unused: False)
        state = {}
        for now in (0.0, 30.0, 60.0):
            self.assertIsNone(nav._stationary_ingress_escape(
                29, state, (0.0, 0.0, 0.0), (40.0, 0.0, 0.0), now, False, None))
        self.assertNotIn('ingress_replans', state)

    def test_short_translation_precedes_another_available_pivot(self):
        driver = LocalDriver()
        position, target = (0.0, 0.0, 0.0), (0.0, 0.0, 40.0)
        def clear(yaw, distance=None):
            return distance is not None and distance <= 2.0 and math.cos(yaw) > 0.5
        orders = []
        for unused in range(100):
            orders.append(driver.drive(29, 1, position, 0.0, 0.0, 0.1,
                target, (), clear, pose_clear=lambda yaw: True, progress_target=target))
        escaped = [o for o in orders if o['recovery_mode'].startswith('short_')]
        self.assertTrue(escaped)
        self.assertTrue(all(abs(o['throttle']) > 0 and o['turn'] == 0 for o in escaped))
        self.assertTrue(all(o['recovery_mode'] == 'short_forward_escape' for o in escaped))


if __name__ == '__main__':
    unittest.main()
