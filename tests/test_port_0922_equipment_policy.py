"""Five-class priorities, native refusal and fitting-tier boundaries."""
import types
import unittest
from unittest import mock

import test_port_0922_garage as fixture


class EquipmentPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = fixture._load_port_module('equipment_policy')

    def test_player_falls_back_within_family_before_next_family(self):
        records = fixture._load_port_module('vehicle_records')
        names = ['deluxImprovedVentilation', 'improvedVentilation_class1',
                 'deluxCoatedOptics', 'deluxAimingStabilizer']
        ids = dict((n, i+1) for i,n in enumerate(names))
        devices = dict((i, types.SimpleNamespace(compactDescr=i)) for i in ids.values())
        directives = {'improvedVentilationBattleBooster': 90}
        cache = types.SimpleNamespace(optionalDeviceIDs=lambda: ids,
            optionalDevices=lambda: devices, equipmentIDs=lambda: directives,
            equipments=lambda: {90: types.SimpleNamespace(compactDescr=900)})
        installed, attempts = [], []
        def may_install(cd, slot):
            attempts.append((cd, slot))
            return (cd != ids['deluxImprovedVentilation'], 'native refusal')
        descriptor = types.SimpleNamespace(type=types.SimpleNamespace(
            name='example', tags={'lightTank'}), mayInstallOptionalDevice=may_install,
            installOptionalDevice=lambda cd, slot: installed.append(cd))
        result = records.initialize_elite_devices(types.SimpleNamespace(g_cache=cache), descriptor)
        self.assertEqual([2, 3, 4], installed)
        self.assertEqual([(1,0), (2,0), (3,1), (4,2)], attempts)
        self.assertEqual(900, result)

    def test_directive_skips_net_and_preserves_equipment_order(self):
        self.assertEqual(['coatedOpticsBattleBooster', 'rammerBattleBooster'],
            list(self.policy.directive_candidates(['camouflageNet', 'coatedOptics', 'deluxRammer'])))

    def test_daily_window_uses_stock_flash_instead_of_fixed_native_quads(self):
        ui = fixture._load_port_module('offline_services_ui')
        panel = ui.ServicePanel()
        self.assertEqual('DailyWindow', type(panel._flash).__name__)
        self.assertIsNone(panel._surface)
        self.assertIsNone(panel._panel)

    def test_baked_bot_tiers_have_exact_equipment_and_directive_boundaries(self):
        data = fixture._load_port_module('bot_fitting_data')
        for vehicle, tiers in data.PLANS.items():
            for tier, count in [('rookie',0), ('regular',1), ('veteran',3), ('elite',3)]:
                plan = tiers[tier]
                self.assertEqual(count, len(plan['devices']), (vehicle,tier))
                if tier != 'elite':
                    self.assertFalse(any(n.startswith('delux') for n in plan['devices']), (vehicle,tier))
                    self.assertIsNone(plan['directive'], (vehicle,tier))
                else:
                    self.assertEqual(next(self.policy.directive_candidates(plan['devices']), None), plan['directive'])

    def test_all_five_classes_keep_the_approved_family_order(self):
        expected = {
            'lightTank': ('ventilation', 'optics', 'stabilizer', 'rammer', 'aim_drives'),
            'mediumTank': ('stabilizer', 'rammer', 'ventilation', 'optics', 'aim_drives'),
            'heavyTank': ('stabilizer', 'rammer', 'ventilation', 'aim_drives', 'optics'),
            'AT-SPG': ('ventilation', 'rammer', 'aim_drives', 'camouflage', 'optics'),
            'SPG': ('ventilation', 'rammer', 'aim_drives', 'camouflage', 'optics'),
        }
        self.assertEqual(expected, self.policy.PRIORITIES)
        for tag, families in expected.items():
            self.assertEqual(tag, self.policy.class_tag({tag, 'other'}))
            groups = list(self.policy.candidates(tag, improved=True))
            for family, names in zip(families, groups):
                normal = self.policy.NORMAL[family]
                self.assertEqual(normal, names[-len(normal):])
                self.assertEqual(len(normal) + int(family in self.policy.IMPROVED), len(names))
        for tags in ({'other'}, {'lightTank', 'heavyTank'}):
            with self.assertRaises(ValueError):
                self.policy.class_tag(tags)


if __name__ == '__main__':
    unittest.main()
