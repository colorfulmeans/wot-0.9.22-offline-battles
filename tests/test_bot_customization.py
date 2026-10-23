"""Independent customization, empty-ammo and host-owned class filters."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import bot_tactics as tactics, bot_fittings as fittings, ammo_policy as ammo
from gui.mods.offline_lan_0922.bot_fitting_data import PLANS
from test_port_0922_server_team_size import BattleState,_Connection,_hello,_attach_worker

class CustomizationTests(unittest.TestCase):
    def test_presets_roundtrip_and_independent_inheritance(self):
        doc=tactics.empty('Custom');doc['behavior']=[dict(team=0,class_tag='all',slot=-1,values=dict(skill='regular',equipment='improved',consumables='repeat',crew_preset='all',ammo_ratios=[0,0,0])),dict(team=1,class_tag='heavyTank',slot=0,values=dict(development='full'))]
        values=tactics.effective(tactics.canonical(doc),1,'heavyTank',0)
        self.assertEqual('full',values['development']);self.assertEqual('improved',values['equipment'])
        selected=fittings.plan('ussr:R45_IS-7',values['skill'],values)
        self.assertEqual(PLANS['ussr:R45_IS-7']['elite']['modules'],selected['modules'])
        self.assertEqual(100,selected['crew']);self.assertEqual(3,len(selected['devices']))
        self.assertEqual('regular',values['skill'])
    def test_overweight_is_refused_before_native_installation(self):
        v,d,e='ussr:R45_IS-7','stock','improved'
        with self.assertRaisesRegex(ValueError,'Stock development'):fittings.plan(v,'regular',dict(development=d,equipment=e))
        profile=tactics.empty('Custom');profile['behavior']=[dict(team=0,class_tag='all',slot=-1,values=dict(development=d,equipment=e))]
        with self.assertRaises(tactics.TacticsError):fittings.validate_profile(profile)
    def test_all_digit_ratios_fill_and_zero_never_reappears(self):
        shells=[dict(index=0,name='AP',kind='ARMOR_PIERCING'),dict(index=1,name='HEAT',kind='HOLLOW_CHARGE'),dict(index=2,name='HE',kind='HIGH_EXPLOSIVE')]
        for clip in (1,3,10):
            for a in range(10):
                for b in range(10):
                    for c in (0,1,9):
                        profile=dict(vehicle_name='unknown',shells=shells,ammo_ratios=[a,b,c],clip_size=clip)
                        actual=ammo.allocation(profile,clip*7,3)
                        self.assertEqual(clip*7 if a+b+c else 0,sum(actual))
                        for w,n in zip((a,b,c),actual):
                            if not w:self.assertEqual(0,n)
                            else:self.assertGreater(n,0)
                            self.assertEqual(0,n%clip)
        self.assertEqual([4,2,1],ammo.apportion(7,(6,3,1)))
    def test_empty_manual_inventory_cannot_launch_or_consume(self):
        from gui.mods.offline_lan_0922.bot_runtime import _BotAmmoState
        profile=dict(vehicle_name='test',shells=[dict(index=i,name=str(i),kind='HIGH_EXPLOSIVE') for i in range(3)],ammo_ratios=[0,0,0])
        descriptor=dict(gun=dict(shots=[{}, {}, {}],maxAmmo=60,clip=(3,0.1)))
        state=_BotAmmoState(descriptor,profile)
        self.assertEqual([0,0,0],state.remaining);self.assertFalse(state.can_fire());self.assertFalse(state.consume_loaded())

    def test_bad_digits_and_booleans_are_not_ratios(self):
        for raw in ([10,1,0],[-1,1,0],[True,0,0],[1.5,0,0]):
            with self.assertRaises(tactics.TacticsError):tactics.normalize_values(dict(ammo_ratios=raw))
    def test_host_filter_and_spg_resize_remain_off(self):
        state=BattleState(team_size=15)
        host,error=state.add_player(_Connection(),('127.0.0.1',1001),_hello(1))
        other,error=state.add_player(_Connection(),('127.0.0.1',1002),_hello(2))
        self.assertFalse(state.set_team_class(other.player_id,1,'heavyTank',False))
        self.assertTrue(state.set_team_class(host.player_id,1,'heavyTank',False))
        self.assertTrue(state.set_team_size(host.player_id,1,6)[0]);self.assertFalse(state.team_classes['1']['SPG'])
        self.assertFalse(state.set_team_class(host.player_id,1,'SPG',True))
        self.assertTrue(state.set_team_size(host.player_id,1,15)[0]);self.assertFalse(state.team_classes['1']['SPG'])
        state.phase='loading';self.assertFalse(state.set_team_class(host.player_id,1,'SPG',True))
    def test_full_human_teams_need_no_automatic_classes(self):
        state=BattleState(team_size=1);_attach_worker(state)
        host,error=state.add_player(_Connection(),('127.0.0.1',1001),_hello(1))
        other,error=state.add_player(_Connection(),('127.0.0.1',1002),_hello(2))
        for team in (1,2):
            for tag in tactics.CLASSES:state.set_team_class(host.player_id,team,tag,False)
        start,error=state.request_start(host.player_id)
        self.assertIsNone(error);self.assertEqual([],start['bots'])
    def test_profile_preserves_supported_magazines_above_one_hundred(self):
        state=BattleState(team_size=1)
        self.assertEqual(200,state._sanitize_bot_profile({'clip_size':200})['clip_size'])

    def test_empty_allowed_classes_refuse_standard_but_not_training_without_bots(self):
        state=BattleState(team_size=2);_attach_worker(state)
        host,error=state.add_player(_Connection(),('127.0.0.1',1001),_hello(1))
        for team in (1,2):
            for tag in tactics.CLASSES:state.set_team_class(host.player_id,team,tag,False)
        start,error=state.request_start(host.player_id)
        self.assertEqual('bot_class_pool_empty',error);self.assertEqual('waiting',state.phase)
        start,error=state.request_start(host.player_id,battle_mode='training')
        self.assertIsNone(error);self.assertEqual([],start['bots'])

if __name__=='__main__':unittest.main()
