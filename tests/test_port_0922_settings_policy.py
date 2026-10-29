"""Unavailable stock settings cannot be re-enabled by an apply/default diff."""
import unittest
from test_port_0922_tank_collision import tank_collision
from gui.mods.offline_lan_0922 import settings_policy


class PolicyTests(unittest.TestCase):
    def test_policy_preserves_unrelated_settings_and_sanitizes_stale_flags(self):
        for old in (True, False):
            original = dict((key, old) for key in settings_policy.LOCKED)
            original['minimapAlpha'] = .65
            packed = settings_policy.pack(original)
            self.assertEqual(.65, packed['minimapAlpha'])
            for key in settings_policy.LOCKED: self.assertIsNone(packed[key])
            self.assertEqual(old, original['useServerAim'])
            self.assertEqual({'minimapAlpha': .65}, settings_policy.editable(original))


if __name__ == '__main__': unittest.main()
