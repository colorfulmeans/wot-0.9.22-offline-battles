"""Elite default ammunition crosses the worker/server boundary unchanged."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src/res/scripts/client'), str(ROOT/'server'), str(ROOT/'tests')]
from gui.mods.offline_lan_0922 import ammo_policy, default_loadouts, bot_fittings
from gui.mods.offline_lan_0922.ai.planner import build_vehicle_profile
from lan_battle_server import BattleState
import test_special_default_loadouts as special_defaults


class EliteAmmunitionTests(unittest.TestCase):
    def ordinary(self):
        return dict(vehicle_name='ussr:R04_T-34', gun_name='_57mm_ZiS-4',
                    class_tag='mediumTank', bot_tier='elite', clip_size=1,
                    shells=[dict(index=i, name=n, kind=k) for i, (n, k) in enumerate((
                        ('_57mm_UBR-271K', 'ARMOR_PIERCING'),
                        ('_57mm_UBR-271N', 'ARMOR_PIERCING_CR'),
                        ('_57mm_UO-271U', 'HIGH_EXPLOSIVE')))])

    def test_ordinary_and_clip_capacity_and_he_return(self):
        p = self.ordinary()
        self.assertIn('ussr:_57mm_UBR-271N', default_loadouts.GOLD_SHELLS)
        self.assertEqual([0, 90, 10], ammo_policy.allocation(p, 100, 3))
        for clip in (1, 3, 4, 6):
            p['clip_size'] = clip
            counts = ammo_policy.allocation(p, 60, 3)
            self.assertEqual(60, sum(counts))
            self.assertEqual(0, counts[0])
            self.assertTrue(all(n % clip == 0 for n in counts))
        policy = ammo_policy.ShotPolicy(p)
        self.assertEqual([1, 2], [s['index'] for s in policy.shells])
        self.assertEqual(1, policy.desired)
        self.assertEqual([1], [s['index'] for s in ammo_policy.stages(p, [0, 10, 0])])

    def test_elite_he_returns_to_premium_after_two_shots(self):
        p = self.ordinary()
        policy = ammo_policy.ShotPolicy(p)
        state = dict(shell_index=1, clip=1, ammo_remaining=[0, 20, 10],
                     ammo_reload_pending=False)
        policy.choose(state)
        for seq in (1, 2):
            policy.launch(seq, 1, seq, 1, dict(x=0, z=0), ('bot', 9))
            policy.resolve(seq, True, 0, False)
        self.assertEqual(2, policy.desired)
        state['shell_index'] = 2
        policy.choose(state)
        for seq in (3, 4):
            policy.launch(seq, 2, seq, 1, dict(x=0, z=0), ('bot', 9))
            policy.resolve(seq, False, 0, False)
        self.assertEqual(1, policy.choose(state))

    def test_manual_player_and_other_tiers_keep_existing_policy(self):
        for tier in (None, 'rookie', 'regular', 'veteran'):
            p = self.ordinary()
            p['bot_tier'] = tier
            self.assertEqual([60, 30, 10], ammo_policy.allocation(p, 100, 3))
        p = self.ordinary()
        p['ammo_ratios'] = [1, 0, 0]
        self.assertEqual([100, 0, 0], ammo_policy.allocation(p, 100, 3))
        p['ammo_ratios'] = [0, 0, 0]
        self.assertEqual([0, 0, 0], ammo_policy.allocation(p, 100, 3))

    def test_no_premium_counterpart_retains_inventory(self):
        p = self.ordinary()
        p['shells'][1]['name'] = 'not_a_premium_round'
        base = dict(p, bot_tier='veteran')
        self.assertEqual(ammo_policy.allocation(base, 52, 3),
                         ammo_policy.allocation(p, 52, 3))

    def test_he_primary_and_premium_he_only_keep_their_roles(self):
        for vehicle in ('usa:A100_T49', 'uk:GB24_Centurion_Mk3',
                        'japan:J25_Type_4', 'japan:J20_Type_2605'):
            descriptor = special_defaults.SpecialDefaultsTests().descriptor(vehicle)
            p = build_vehicle_profile(descriptor)
            base = ammo_policy.allocation(p, 100, len(p['shells']))
            p['bot_tier'] = 'elite'
            self.assertEqual(base, ammo_policy.allocation(p, 100, len(p['shells'])), vehicle)

    def test_gold_primary_su100y_keeps_higher_penetration_silver_backup(self):
        descriptor = special_defaults.SpecialDefaultsTests().descriptor('ussr:R49_SU100Y')
        p = build_vehicle_profile(descriptor)
        p['bot_tier'] = 'elite'
        self.assertEqual([30, 60, 10], ammo_policy.allocation(p, 100, 3))
        self.assertEqual([1, 0, 2], [s['index'] for s in ammo_policy.stages(p)])

    def profile(self, vehicle, gun, names, kinds, class_tag='AT-SPG'):
        return dict(vehicle_name=vehicle, gun_name=gun, class_tag=class_tag,
                    bot_tier='elite', clip_size=1,
                    shells=[dict(index=i, name=n, kind=k)
                            for i, (n, k) in enumerate(zip(names, kinds))])

    def test_artillery_merges_both_he_quotas_and_whole_clips(self):
        p = self.profile('germany:G23_Grille', '_170mm_fake_test_gun',
            ('_170mm_Sprg18', '_170mm_Sprg18_Ausf_G'),
            ('HIGH_EXPLOSIVE', 'HIGH_EXPLOSIVE'), 'SPG')
        for clip in (1, 3, 6):
            p['clip_size'] = clip
            self.assertEqual([0, 60], ammo_policy.allocation(p, 60, 2))
            self.assertEqual([1], [s['index'] for s in ammo_policy.stages(p)])
        p['bot_tier'] = 'regular'
        p['clip_size'] = 1
        self.assertEqual([48, 12], ammo_policy.allocation(p, 60, 2))
        p['bot_tier'] = 'elite'
        p['ammo_ratios'] = [1, 0]
        self.assertEqual([60, 0], ammo_policy.allocation(p, 60, 2))

    def test_he_primary_keeps_its_backup_and_returns_after_one_probe(self):
        p = self.profile('germany:G09_Hetzer', '_105mm_StuH42_L28',
            ('_105mm_Sprg_K', '_105mmGr39H1A', '_105mm_PzGr39'),
            ('HIGH_EXPLOSIVE', 'HOLLOW_CHARGE', 'ARMOR_PIERCING'))
        self.assertEqual([80, 20, 0], ammo_policy.allocation(p, 100, 3))
        policy = ammo_policy.ShotPolicy(p)
        state = dict(ammo_remaining=[80, 20, 0])
        policy.choose(state)
        for seq in (1, 2):
            policy.launch(seq, 0, seq, 1, dict(x=0, z=0), ('bot', 9))
            policy.resolve(seq, True, 50, False)
        self.assertEqual(1, policy.choose(state))
        policy.launch(3, 1, 3, 1, dict(x=0, z=0), ('bot', 9))
        policy.resolve(3, False, 0, False)
        self.assertEqual(0, policy.choose(state))

    def test_both_ap_exceptions_switch_to_silver_then_he(self):
        cases = (
            ('ussr:R49_SU100Y', '_130mm_B-13-S2',
             ('_130mm_PB-46', '_130mm_PB-46A', '_130mm_OF-46')),
            ('ussr:R111_ISU130', '_130mm_S-26A',
             ('_130mm_2-02864A', '_130mm_2-01743', '_130mm_2-02742')))
        for vehicle, gun, names in cases:
            p = self.profile(vehicle, gun, names,
                ('ARMOR_PIERCING', 'ARMOR_PIERCING', 'HIGH_EXPLOSIVE'))
            self.assertEqual([30, 60, 10], ammo_policy.allocation(p, 100, 3))
            policy = ammo_policy.ShotPolicy(p)
            state = dict(ammo_remaining=[30, 60, 10])
            policy.choose(state)
            for seq, index in ((1,1), (2,1), (3,0), (4,0)):
                policy.launch(seq, index, seq, 1, dict(x=0,z=0), ('bot',9))
                policy.resolve(seq, True, 0, False)
                policy.choose(state)
                if seq == 2:self.assertEqual(0, policy.desired)
            self.assertEqual(2, policy.desired)
            for seq in (5,6):
                policy.launch(seq, 2, seq, 1, dict(x=0,z=0), ('bot',9))
                policy.resolve(seq, False, 0, False)
            self.assertEqual(1, policy.choose(state))

    def test_su5_only_stronger_silver_he_for_every_tier(self):
        p = self.profile('ussr:R14_SU-5', '_122mm_cannon_mod_1930',
            ('_122mm_OF420SOMSH', '_122mm_OF420SO'),
            ('HIGH_EXPLOSIVE', 'HIGH_EXPLOSIVE'), 'SPG')
        for tier in ('rookie','regular','veteran','elite'):
            p['bot_tier'] = tier
            self.assertEqual([0,18], ammo_policy.allocation(p,18,2))
            policy=ammo_policy.ShotPolicy(p)
            state=dict(ammo_remaining=[0,18])
            for seq in (1,2,3):
                policy.launch(seq,1,seq,1,dict(x=0,z=0),('bot',9))
                policy.resolve(seq,False,0,False)
                self.assertEqual(1,policy.choose(state))

    def test_legacy_he_only_artillery_does_not_admit_premium_ap_or_heat(self):
        cases=(('uk:GB78_Sexton_I','_25pdr_Field_Gun',
                ('_25pdr_HE_Mk_1D','_25pdr_AP_Mk_1T_SC','_25pdr_AP_Mk_1T'),
                ('HIGH_EXPLOSIVE','ARMOR_PIERCING','ARMOR_PIERCING')),
               ('france:F28_105_leFH18B2','_105mm_leFH18_L28',
                ('_105mm_Sprg_K','_105mmGr39H1A','_105mm_PzGr39K'),
                ('HIGH_EXPLOSIVE','HOLLOW_CHARGE','ARMOR_PIERCING')))
        for v,g,n,k in cases:
            p=self.profile(v,g,n,k,'SPG')
            self.assertEqual([100,0,0],ammo_policy.allocation(p,100,3))

    def test_ikv103_is_not_an_exception_and_rhm_full_uses_150(self):
        p=self.profile('sweden:S14_Ikv_103','_105mm_kan_ikv_102',
            ('_105mm_slpgr_m_43','_105mm_slpsgr_m_49','_105mm_lt_sgr_m_34'),
            ('ARMOR_PIERCING','HOLLOW_CHARGE','HIGH_EXPLOSIVE'))
        self.assertEqual([0,90,10],ammo_policy.allocation(p,100,3))
        self.assertIsNone(default_loadouts.gun_override('germany:G99_RhB_Waffentrager'))
        for tier in ('veteran','elite'):
            self.assertEqual('_150mm_Rohr_L29_5',bot_fittings.plan('germany:G99_RhB_Waffentrager',tier)['modules']['gun'])
        self.assertEqual('_128mm_K44_L55',bot_fittings.plan('germany:G99_RhB_Waffentrager','rookie')['modules']['gun'])
        self.assertEqual('_128mm_K44_2_L61',bot_fittings.plan('germany:G97_Waffentrager_IV','elite')['modules']['gun'])

    def test_tier_survives_native_profile_and_wire_sanitizer(self):
        descriptor = special_defaults.SpecialDefaultsTests().descriptor()
        with mock.patch.object(bot_fittings, 'context', return_value=dict(wire=dict(tier='elite'))):
            p = build_vehicle_profile(descriptor)
        wire = BattleState._sanitize_bot_profile(p)
        self.assertEqual('elite', wire['bot_tier'])
        self.assertEqual(ammo_policy.allocation(p, 100, len(p['shells'])),
                         ammo_policy.allocation(wire, 100, len(p['shells'])))

    def test_reviewed_guns_update_full_only(self):
        cases = {'china:Ch31_M3G_FT': '_57mm_ZiS_2',
                 'germany:G08_Pz38t': '_47mm_PaK_38t_L43',
                 'uk:GB15_Stuart_I': '_2pdr_Gun_Mk_IX',
                 'japan:J09_Chi_He': '_57mm_Gun_Shin'}
        for vehicle, gun in cases.items():
            self.assertEqual(gun, default_loadouts.gun_override(vehicle))
            for tier in ('veteran', 'elite'):
                self.assertEqual(gun, bot_fittings.plan(vehicle, tier)['modules']['gun'])
                self.assertEqual(gun, bot_fittings.plan(vehicle, tier, {'development':'full'})['modules']['gun'])
        self.assertEqual('_37mm_KwK_38t_L47',
                         bot_fittings.plan('germany:G08_Pz38t', 'elite', {'development':'stock', 'equipment':'none'})['modules']['gun'])


if __name__ == '__main__':
    unittest.main()
