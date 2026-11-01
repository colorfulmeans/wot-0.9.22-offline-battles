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

    def test_gold_primary_su100y_removes_silver_backup(self):
        descriptor = special_defaults.SpecialDefaultsTests().descriptor('ussr:R49_SU100Y')
        p = build_vehicle_profile(descriptor)
        p['bot_tier'] = 'elite'
        self.assertEqual([0, 90, 10], ammo_policy.allocation(p, 100, 3))
        self.assertEqual([1, 2], [s['index'] for s in ammo_policy.stages(p)])

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
