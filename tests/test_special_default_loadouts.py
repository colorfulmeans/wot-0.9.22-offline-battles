import sys
from pathlib import Path
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src/res/scripts/client'), str(ROOT/'server'), str(ROOT/'tests')]
from gui.mods.offline_lan_0922 import default_loadouts as policy
from gui.mods.offline_lan_0922 import default_crew
from gui.mods.offline_lan_0922.ai.planner import build_vehicle_profile, select_shell_index
from server_bot_ai import BotPlanner
from lan_battle_server import BattleState


class SpecialDefaultsTests(unittest.TestCase):
    def descriptor(self, vehicle='usa:A100_T49'):
        gun_name, names = policy.LOADOUTS[vehicle]
        if vehicle.startswith('usa:'):
            names = ('_152mm_HE_XM657E2', '_152mm_HEAT_XM409', '_152mm_HE_XM657E3')
            kinds = ('HIGH_EXPLOSIVE', 'HOLLOW_CHARGE', 'HIGH_EXPLOSIVE')
        elif vehicle == 'ussr:R49_SU100Y':
            names = ('_130mm_PB-46', '_130mm_PB-46A', '_130mm_OF-46')
            kinds = ('ARMOR_PIERCING', 'ARMOR_PIERCING', 'HIGH_EXPLOSIVE')
        else:
            kinds = ('HIGH_EXPLOSIVE',) * len(names)
        shots = [types.SimpleNamespace(shell=types.SimpleNamespace(
            name=name, compactDescr=100+i, kind=kinds[i],
            piercingPower=(100-i*10, 100-i*10), damage=(300+i*30, 300+i*30)), speed=700)
                 for i, name in enumerate(names)]
        return types.SimpleNamespace(type=types.SimpleNamespace(name=vehicle, tags={'lightTank'}),
                                     gun=types.SimpleNamespace(name=gun_name, shots=shots, maxAmmo=23))

    def test_t49_keeps_native_indices_but_excludes_silver_he(self):
        descriptor = self.descriptor()
        roles = policy.descriptor_roles(descriptor)
        self.assertEqual({2: 'standard', 1: 'premium'}, roles)
        self.assertEqual([102, 14, 101, 9], policy.garage_ammo(descriptor))
        profile = build_vehicle_profile(descriptor)
        wire = BattleState._sanitize_bot_profile(profile)
        self.assertEqual(roles, policy.profile_roles(wire))
        for plans in (False, True):
            self.assertEqual(2, BotPlanner._shell_index(wire, {'armor': 0}, {'aggression': .5},
                                                      {'ammo_remaining': [0, 9, 14]}, plans))
        self.assertEqual(2, select_shell_index(profile, {'armor': 0}, {'aggression': .5}))
        self.assertEqual(1, BotPlanner._shell_index(wire, {'armor': 0}, {'aggression': .5},
                                                  {'ammo_remaining': [0, 9, 0]}, False))

    def test_worker_initial_inventory_and_load_use_the_same_roles(self):
        from gui.mods.offline_lan_0922.bot_runtime import _BotAmmoState
        descriptor = self.descriptor()
        state = _BotAmmoState(descriptor, build_vehicle_profile(descriptor))
        self.assertEqual([0, 9, 14], state.remaining)
        self.assertEqual((2, 2), (state.loaded, state.next))
        self.assertEqual(2, state._available(0))

    def test_lower_penetration_gold_ap_remains_primary(self):
        descriptor = self.descriptor('ussr:R49_SU100Y')
        profile = BattleState._sanitize_bot_profile(build_vehicle_profile(descriptor))
        self.assertEqual({1: 'standard', 0: 'premium', 2: 'he'}, policy.profile_roles(profile))
        self.assertEqual(1, BotPlanner._shell_index(profile, {'armor': 0}, {'aggression': .5}, None, True))
        self.assertEqual(1, BotPlanner._shell_index(profile, {'armor': 0}, {'aggression': .5}, None, False))
        self.assertEqual([101, 11, 100, 8, 102, 4], policy.garage_ammo(descriptor))

    def test_two_japanese_premium_he_only_loads_fill_capacity(self):
        for vehicle in ('japan:J25_Type_4', 'japan:J20_Type_2605'):
            descriptor = self.descriptor(vehicle)
            self.assertEqual([100, 23], policy.garage_ammo(descriptor))

    def test_all_role_counts_fill_capacity_without_excluded_rounds(self):
        for maximum in range(1, 150):
            for roles in ({2: 'standard'}, {2: 'standard', 0: 'premium'},
                          {2: 'standard', 0: 'premium', 1: 'he'}):
                with self.subTest(maximum=maximum, roles=roles):
                    values = policy.allocate(maximum, roles, 3)
                    self.assertEqual(maximum, sum(values))
                    self.assertTrue(all(values[i] == 0 for i in range(3) if i not in roles))
                    self.assertTrue(all(isinstance(v, int) for v in values))

    def test_an_alternate_player_gun_and_unlisted_vehicles_are_unmodified(self):
        descriptor = self.descriptor()
        descriptor.gun.name = 'player_selected_alternate'
        self.assertIsNone(policy.descriptor_roles(descriptor))
        self.assertIsNone(policy.garage_ammo(descriptor))
        self.assertIsNone(policy.gun_override('ussr:R11_MS-1'))

    def test_missing_named_shell_is_rejected_instead_of_using_wrong_round(self):
        descriptor = self.descriptor()
        descriptor.gun.shots = descriptor.gun.shots[:2]
        with self.assertRaisesRegex(ValueError, 'shell missing'):
            policy.garage_ammo(descriptor)

    def test_server_preserves_complete_descriptor_keys(self):
        raw = dict(vehicle_name='germany:G83_Pz_IV_AusfA', gun_name='_75mm_KwK_37_L24', shells=[
            dict(name='_75mm_Sprg.18', index=2, kind='HIGH_EXPLOSIVE')])
        sanitized = BattleState._sanitize_bot_profile(raw)
        self.assertEqual(raw['vehicle_name'], sanitized['vehicle_name'])
        self.assertEqual(raw['shells'][0]['name'], sanitized['shells'][0]['name'])
        self.assertEqual('', BattleState._sanitize_bot_profile(dict(gun_name='x'*97))['gun_name'])

    def test_source_skill_mask_has_only_the_reviewed_25_active_ids(self):
        mask = default_crew.sandbox_skill_mask()
        self.assertEqual(set(default_crew.SKILL_IDS), {i for i in range(64) if mask & (1 << i)})
        self.assertEqual(25, len(default_crew.SKILL_IDS))


if __name__ == '__main__':
    unittest.main()
