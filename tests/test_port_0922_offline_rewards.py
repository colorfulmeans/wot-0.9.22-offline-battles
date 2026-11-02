"""Independent reward-law and event-attribution checks for economy v2.

Credits intentionally use the complete 2015 community model. These fixtures
are arithmetic examples of that selected model, not claims of WG server parity.
"""
import sys
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'server'), str(ROOT/'src/res/scripts/client')]
from offline_rewards import compute_offline_rewards, tier_weight
from gui.mods.offline_lan_0922 import credit_coefficients, battle_achievements


class RewardModelTests(unittest.TestCase):
    def test_complete_community_credit_model_not_official_splices(self):
        facts = dict(credit_damage_units=1000*100+1000*75,
                     credit_assist_damage=400, damage_units=150000,
                     assist_units=40000)
        # Tier VIII, own 1000 + other-spot 1000, assist 400, 2 spots incl SPG.
        loss = compute_offline_rewards({'spotted':2}, False, vehicle_tier=8,
            spotted_spgs=1, reward_facts=facts, captured=True)
        win = compute_offline_rewards({'spotted':2}, True, vehicle_tier=8,
            spotted_spgs=1, reward_facts=facts, captured=True)
        self.assertEqual(25900, loss['credits']) # 5600+17500+2000+300+500
        self.assertEqual(30700, win['credits']) # participation 10400
        self.assertEqual(4800, win['credits']-loss['credits'])
        # 1.85 would produce 4760, and 50% other spotting would lose 2500.

    def test_type59_coefficient_and_resistance_once(self):
        coefficient, source = credit_coefficients.COEFFICIENTS['china:Ch01_Type59']
        self.assertEqual((15750,6), (coefficient,source))
        row = {'damage_dealt':4394,'spotted':6, 'kills':4,
               'damage_assisted_track':237}
        normal = compute_offline_rewards(row,False,vehicle_tier=8,
            spotted_spgs=1,vehicle_coefficient=coefficient)
        brave = compute_offline_rewards(row,False,vehicle_tier=8,
            spotted_spgs=1,vehicle_coefficient=coefficient,courageous=True)
        self.assertEqual(80994, normal['credits'])
        self.assertEqual(7560, brave['achievement_credits'])
        self.assertEqual(normal['credits']+7560, brave['credits'])
        self.assertEqual(normal['xp']*3//2, brave['xp'])
        win = compute_offline_rewards(row,True,vehicle_tier=8,
            spotted_spgs=1,vehicle_coefficient=coefficient,courageous=True)
        self.assertEqual(0,win['achievement_credits'])
        self.assertEqual(brave['credits'],win['credits'])

    def test_credits_do_not_import_official_target_tier_bonus(self):
        def rewards(weight):
            return compute_offline_rewards({},False,vehicle_tier=8,reward_facts={
                'damage_units':1000*weight*10,'credit_damage_units':100000})
        low,same,high=[rewards(w) for w in (8,10,12)]
        self.assertEqual([15600]*3,[r['credits'] for r in (low,same,high)])
        self.assertLess(low['xp'],same['xp']);self.assertLess(same['xp'],high['xp'])

    def test_capture_is_full_payment_per_current_capturer(self):
        plain=compute_offline_rewards({'capture_points':90},False)
        captured=compute_offline_rewards({'capture_points':90},False,captured=True)
        self.assertEqual(500,captured['credits']-plain['credits'])
        self.assertEqual(plain['xp'],captured['xp'])

    def test_assists_are_paid_but_aggregate_fallback_does_not_sum_categories(self):
        one=compute_offline_rewards({'damage_assisted_track':100},False)
        both=compute_offline_rewards({'damage_assisted_track':100,
                                     'damage_assisted_radio':100},False)
        self.assertEqual(one['credits'],both['credits'])
        self.assertEqual(one['xp'],both['xp'])
        self.assertEqual(1200,one['credits'])

    def test_survival_criticals_activity_and_defence_are_distinct(self):
        detail={}
        result=compute_offline_rewards({'critical_hits':3, 'capture_points':10,
            'dropped_capture_points':70},False,reward_facts={
            'critical_units':300,'active_events':999,'survived':True},breakdown=detail)
        self.assertEqual(dict(participation=100,damage=0,assistance=0,kills=0,
            criticals=15,spotting=0,capture=20,defence=140,survival=20,
            active_combat=50),detail['xp_parts'])
        self.assertEqual(345,result['xp'])
        # Defence does not manufacture a credit reward absent from this model.
        self.assertEqual(700,result['credits'])

    def test_kill_xp_uses_actual_tier_not_victim_hitpoints(self):
        self.assertEqual(8,tier_weight(8,6));self.assertEqual(12,tier_weight(8,10))
        same=compute_offline_rewards({},False,reward_facts={'kill_units':100})
        higher=compute_offline_rewards({},False,reward_facts={'kill_units':120})
        self.assertEqual(20,higher['xp']-same['xp'])
        self.assertEqual(same['credits'],higher['credits'])

    def test_costs_stay_client_owned_and_free_xp_is_derived_after_bonus(self):
        r=compute_offline_rewards({'damage_dealt':1419},False,courageous=True)
        self.assertEqual(r['xp']*5//100,r['free_xp'])
        self.assertEqual((0,0),(r['repair_cost'],r['ammo_cost']))
        self.assertLessEqual(r['achievement_free_xp'],r['free_xp'])

    def test_bad_inputs_are_contained(self):
        r=compute_offline_rewards({'damage_dealt':-5,'spotted':None},False,
            vehicle_tier=None,spotted_spgs=-1)
        self.assertEqual((700,100),(r['credits'],r['xp']))
        self.assertEqual(0,compute_offline_rewards({},False,participated=False)['credits'])

    def test_only_battle_hero_and_epic_medals_qualify(self):
        medals=battle_achievements.COURAGEOUS_RESISTANCE_ACHIEVEMENTS
        self.assertTrue({'mainGun','warrior','defender','medalPascucci','huntsman'}<=medals)
        self.assertTrue({'ironMan','markOfMastery','marksOnGun','kamikaze'}.isdisjoint(medals))


class ServerRewardInputTests(unittest.TestCase):
    def _state(self):
        from lan_battle_server import BattleState, CLIENT_BUILD_0922
        state=BattleState(map_name='13_erlenberg',clock=lambda:10)
        state.client_build=CLIENT_BUILD_0922
        state.vehicle_catalogs={1:(
            {'name':'ussr:R04_T-34','level':5,'tags':('mediumTank',)},
            {'name':'ussr:R66_SU-26','level':3,'tags':('SPG',)})}
        state.bot_manifest=[dict(id=11,vehicle='ussr:R04_T-34',team=2),
            dict(id=12,vehicle='ussr:R66_SU-26',team=2),
            dict(id=13,vehicle='ussr:R04_T-34',team=1),
            dict(id=14,vehicle='ussr:R04_T-34',team=1)]
        state.bot_states={r['id']:dict(r,alive=True,health=100,max_health=100,
                                     x=r['id']*2,y=0,z=0) for r in state.bot_manifest}
        return state

    def test_first_spot_spg_is_not_an_extra_ordinary_tank(self):
        s=self._state()
        for i in (11,12):s._statistics_interaction(('bot',13),('bot',i))['spotted']=1
        self.assertEqual(1,s._spotted_spg_count('bot',13))

    def test_damage_freezes_other_spot_and_deduplicates_overlapping_assists(self):
        s=self._state();actor,target,helper=('bot',13),('bot',11),('bot',14)
        with mock.patch.object(s,'_radio_assisters',return_value=[helper]),mock.patch.object(
                s,'_impairment_assisters',return_value=[('track',helper),('stun',helper)]):
            s._record_damage(actor,target,40,{})
        own=s._reward_facts(*actor);assist=s._reward_facts(*helper)
        self.assertEqual((2000,3000),(own['damage_units'],own['credit_damage_units']))
        self.assertEqual((4000,40),(assist['assist_units'],assist['credit_assist_damage']))
        self.assertEqual((40,40,40),tuple(s._statistics_row(*helper)[
            'damage_assisted_'+key] for key in ('radio','track','stun')))
        # A later local reveal must not retroactively upgrade the earlier shot.
        s.bot_spotted[13]={target}
        self.assertEqual(3000,s._reward_facts(*actor)['credit_damage_units'])

    def test_blind_damage_and_fire_use_the_same_event_accounting(self):
        s=self._state()
        with mock.patch.object(s,'_radio_assisters',return_value=[]):
            s._record_damage(('bot',13),('bot',12),50,{})
        facts=s._reward_facts('bot',13)
        self.assertEqual(4000,facts['damage_units']) # tier V vs III
        self.assertEqual(5000,facts['credit_damage_units']) # no credit tier term

    def test_dead_or_departed_capture_contributor_gets_no_completion_credit(self):
        s=self._state();s.base_captured_team=1
        s._statistics_row('bot',13)['capture_points']=90
        self.assertFalse(s._completed_capture('bot',13,1))
        s.capture_invaders[2]={('bot',14)}
        self.assertFalse(s._completed_capture('bot',13,1))
        self.assertTrue(s._completed_capture('bot',14,1))

    def test_public_and_personal_rewards_share_one_calculator(self):
        s=self._state()
        s._statistics_interaction(('bot',13),('bot',11))['target_kills']=1
        raw=s._actor_rewards('bot',13,2)
        brave=s._actor_rewards('bot',13,2,['mainGun','warrior'])
        self.assertEqual(raw['xp']*3//2,brave['xp'])
        self.assertGreater(brave['credits'],raw['credits'])
        self.assertEqual(100,s._reward_facts('bot',13)['kill_units'])

    def test_tiers_remain_exact_after_catalogue_donor_disconnects(self):
        s=self._state()
        s.vehicle_catalogs.clear()
        self.assertEqual(5,s._reward_tier(('bot',13)))
        self.assertEqual(3,s._reward_tier(('bot',12)))
        self.assertEqual(8,s._reward_weight(('bot',13),('bot',12)))

    def test_different_assist_events_accumulate_without_category_overlap(self):
        s=self._state();actor,target,helper=('bot',13),('bot',11),('bot',14)
        with mock.patch.object(s,'_radio_assisters',return_value=[helper]),mock.patch.object(
                s,'_impairment_assisters',return_value=[('track',helper)]):
            s._record_damage(actor,target,40,{})
        with mock.patch.object(s,'_radio_assisters',return_value=[]),mock.patch.object(
                s,'_impairment_assisters',return_value=[('stun',helper)]):
            s._record_damage(actor,target,60,{})
        self.assertEqual(100,s._reward_facts(*helper)['credit_assist_damage'])

    def test_estimated_coefficients_are_explicit_and_positive(self):
        rows=credit_coefficients.COEFFICIENTS
        self.assertGreater(len(rows),600)
        self.assertTrue(all(factor>0 and source>=0 for factor,source in rows.values()))
        self.assertGreater(sum(source>0 for factor,source in rows.values()),350)
        self.assertGreater(sum(source==0 for factor,source in rows.values()),0)


if __name__=='__main__':unittest.main()
