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

    def test_daily_window_reuses_room_button_styles_and_dimensions(self):
        import test_port_0922_waiting_room_ui as room_fixture
        ui = fixture._load_port_module('offline_services_ui')
        surface = room_fixture._Surface()
        with mock.patch.object(room_fixture._Component, 'delChild',
                lambda component, child: component.children.remove(child), create=True):
            panel = ui.ServicePanel(surface=surface)
            panel.install()
            self.assertTrue(panel._controls['close'].texture.endswith('waiting_button_close.dds'))
            self.assertTrue(panel._controls['reserves'].texture.endswith('waiting_button_normal.dds'))
            self.assertAlmostEqual(100, panel._controls['close'].width*640/2)
            self.assertAlmostEqual(180, panel._controls['reserves'].width*640/2)
            self.assertAlmostEqual(22, panel._controls['close'].height*320/2)
            self.assertEqual(panel._labels['close'].font, panel.panel_font)
            self.assertIn('reward2', panel._labels)

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

    def test_diagnostics_are_opt_in_and_observation_only(self):
        diagnostic = fixture._load_port_module('native_input_diagnostics')
        entity = types.SimpleNamespace(id=7, health=0, isCrewActive=False,
            gunAnglesPacked=12345, appearance=types.SimpleNamespace())
        with mock.patch.object(diagnostic, 'detailed_enabled', return_value=False), \
             mock.patch.object(diagnostic, 'write_json_record') as write:
            diagnostic.turret_pose('before_death', entity)
            write.assert_not_called()
        with mock.patch.object(diagnostic, 'detailed_enabled', return_value=True), \
             mock.patch.object(diagnostic, 'write_json_record') as write:
            diagnostic.turret_pose('before_death', entity)
            self.assertEqual(12345, write.call_args[0][1]['gun_angles_packed'])
            self.assertEqual(12345, entity.gunAnglesPacked)


if __name__ == '__main__':
    unittest.main()
