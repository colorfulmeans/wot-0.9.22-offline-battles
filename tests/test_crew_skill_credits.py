"""Seat bounds and member-owned skill credits, independent of native UI mocks."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import crew_skills as policy,crew_recruits
from gui.mods.offline_lan_0922.account_rpc.garage import GarageState,GarageError
from gui.mods.offline_lan_0922.account_rpc import garage_store


class Descriptor:
    levelUpXpCost=staticmethod(lambda level,sequence:(level+1)*100*2**sequence)
    def __init__(self,raw):
        self.__dict__.update(json.loads(raw.decode('ascii')) if isinstance(raw,bytes) else copy.deepcopy(raw))
    @property
    def freeSkillsNumber(self):return len(self.freeSkills)
    def addSkill(self,skill):
        if skill in self.skills or self.roleLevel!=100:raise ValueError('native guard')
        cost=sum(self.levelUpXpCost(n,len(self.skills)-self.freeSkillsNumber+1) for n in range(100))
        self.skills.append(skill);self.freeXP-=cost;self.last=100
    def skillLevel(self,skill):return 100 if skill in self.skills else None
    def makeCompactDescr(self):
        if not 0<=self.freeXP<=2000000000:raise ValueError('native serialized XP bound')
        return json.dumps(self.__dict__).encode('ascii')
    def dropSkills(self,fraction,unused):self.skills=list(self.freeSkills);self.freeXP=0
    def addXP(self,amount):self.freeXP+=amount
    def isFreeDropSkills(self):return not self.skills


def member(female=False):
    return Descriptor(dict(skills=['brotherhood'] if female else [],freeSkills=['brotherhood'] if female else [],
        freeXP=0,roleLevel=100,role='commander',passport='original',dossier='original'))


class SeatBoundsTests(unittest.TestCase):
    def test_every_vehicle_seat_and_gender_training_combination(self):
        self.assertEqual(614,len(policy.data.SEATS));self.assertEqual(2676,sum(map(len,policy.data.SEATS.values())))
        for vehicle,rows in policy.data.SEATS.items():
            for index,roles in enumerate(rows):
                expected=set(policy.data.COMMON)
                for role in roles:expected.update(policy.data.ROLE_SKILLS[role])
                expected.intersection_update(policy.data.ACTIVE)
                for female in (False,True):
                    for training in (50,75,100):
                        low,high=policy.bounds(vehicle,index,female,training)
                        self.assertEqual(int(female),low)
                        self.assertEqual(len(expected) if training==100 else low,high)
    def test_duplicate_loaders_and_combined_commander_are_distinct(self):
        self.assertEqual((0,7),policy.bounds('ussr:R45_IS-7',3,False,100))
        self.assertEqual((0,11),policy.bounds('ussr:R45_IS-7',4,False,100))
        self.assertEqual((1,20),policy.bounds('france:F62_ELC_AMX',0,True,100))
    def test_new_requests_cannot_exceed_the_selected_seat(self):
        row=dict(id='a'*32,nation='ussr',vehicle='ussr:R45_IS-7',role='loader',seat=3,training=100,female=False,skills=11)
        with self.assertRaises(ValueError):crew_recruits.request(row)
        row['seat']=4;self.assertEqual(11,crew_recruits.request(row)['skills'])
        row.update(training=75,female=True,skills=1);crew_recruits.request(row)
        row['skills']=0
        with self.assertRaises(ValueError):crew_recruits.request(row)


class SkillCreditTests(unittest.TestCase):
    def test_twenty_choices_never_serialize_unbounded_xp_or_change_passport(self):
        d=member();tankmen=NS(TankmanDescr=Descriptor)
        for skill in policy.skills_for(('commander','gunner','loader','radioman')):
            d=Descriptor(policy.grant_skill(d,skill,tankmen))
            self.assertEqual(0,d.freeXP);self.assertEqual('original',d.passport);self.assertEqual('original',d.dossier)
        self.assertEqual(20,len(d.skills))
        d.freeXP=1234
        result=policy.reset_grants(d,dict(remaining=0,learned=list(d.skills)),.5,tankmen)
        self.assertEqual(dict(remaining=20,learned=[]),result)
        self.assertEqual(617,d.freeXP);self.assertFalse(d.skills)
    def state(self,remaining=2):
        raw=member().makeCompactDescr()
        snapshot=dict(vehicles=[],barracksTankmen={100001:raw},accountBerths=10,
                      dropSkillsCosts={0:dict(credits=0,gold=0,xpReuseFraction=1.)},
                      launcherCrewSkillCredits={'100001':dict(remaining=remaining,learned=[])})
        return GarageState(snapshot,tankmen_module=NS(TankmanDescr=Descriptor,SKILL_NAMES=policy.data.ACTIVE))
    def test_credit_and_skill_commit_together_reject_duplicates_and_survive_restore(self):
        state=self.state();skill='repair';index=policy.data.ACTIVE.index(skill)
        state.add_tankman_skill(100001,index)
        row=state.snapshot()[policy.CREDITS]['100001'];self.assertEqual(1,row['remaining'])
        before=copy.deepcopy(state.snapshot())
        with self.assertRaises(GarageError):state.add_tankman_skill(100001,index)
        self.assertEqual(before,state.snapshot())
        payload=garage_store._ledger_payload(state.snapshot());restored=copy.deepcopy(state.snapshot())
        restored.pop(policy.CREDITS);garage_store._apply_ledger(restored,dict(ledger=payload))
        self.assertEqual(row,restored[policy.CREDITS]['100001'])
        state.drop_tankman_skills(100001,0)
        self.assertEqual(dict(remaining=2,learned=[]),state.snapshot()[policy.CREDITS]['100001'])
    def test_seat_changes_and_dismissal_do_not_mint_or_reassign_credits(self):
        state=self.state();original=copy.deepcopy(state.snapshot()[policy.CREDITS])
        state.snapshot()['barracksTankmen'].clear()
        self.assertEqual(100002,state._next_tankman_id())
        self.assertEqual(original,state.snapshot()[policy.CREDITS])
    def test_real_transfer_and_recovery_keep_member_credits_and_combined_role_rules(self):
        state=self.state();snapshot=state.snapshot()
        d=Descriptor(snapshot['barracksTankmen'][100001]);d.nationID=0;d.vehicleTypeID=1
        snapshot['barracksTankmen'][100001]=d.makeCompactDescr()
        snapshot['vehicles']=[dict(id=1,vehicleTypeCompactDescr=1,compDescr=b'vehicle',crew=[None,None],tankmen={})]
        snapshot['tankmenRestoreConfig']=dict(freeDuration=100,goldDuration=1000,goldCost=0,limit=10)
        state._vehicles=NS(VehicleDescr=lambda **kw:NS(type=NS(id=(0,1),crewRoles=(('commander',),('commander','radioman')))))
        index=policy.data.ACTIVE.index('radioman_finder')
        state.equip_tankman(1,0,100001)
        with self.assertRaises(GarageError):state.add_tankman_skill(100001,index)
        self.assertEqual(2,snapshot[policy.CREDITS]['100001']['remaining'])
        state.equip_tankman(1,1,100001);state.add_tankman_skill(100001,index)
        credit=copy.deepcopy(snapshot[policy.CREDITS]['100001'])
        self.assertEqual(1,credit['remaining'])
        state.equip_tankman(1,0,100001);state.equip_tankman(1,0,-1)
        state.dismiss_tankman(100001);state.restore_tankman(100001)
        self.assertEqual(credit,snapshot[policy.CREDITS]['100001'])
        self.assertIn('radioman_finder',Descriptor(snapshot['barracksTankmen'][100001]).skills)

    def test_saved_credit_validation_rejects_corrupt_or_duplicate_grants(self):
        self.assertEqual({},policy.saved_credits({'2':dict(remaining=True,learned=[]),'3':dict(remaining=1,learned=['repair','repair'])}))

    def test_failed_durable_skill_save_restores_descriptor_and_credit(self):
        from gui.mods.offline_lan_0922.account_rpc import requests,commands
        from unittest.mock import patch
        state=self.state();before=copy.deepcopy(state.snapshot())
        context=dict(garage=state,selected_vehicle=state.snapshot(),garage_store=NS(mark_dirty=lambda:None,flush=lambda snapshot:False))
        with patch.object(requests.data,'stats',return_value={'stats':{}}):
            result=requests._add_tankman_skill(context,[100001,policy.data.ACTIVE.index('repair')])
        self.assertEqual(commands.RES_FAILURE,result.result_id);self.assertEqual(before,state.snapshot())
        self.assertEqual(before,context['selected_vehicle'])

    def test_stock_ui_counter_is_member_scoped_and_uninstall_is_idempotent(self):
        from unittest.mock import patch
        class Native:
            newSkillCount=property(lambda self:(1,0))
            invID=100001
            hasNewSkill=lambda self,**kw:True
            availableSkills=lambda self,**kw:['repair','camouflage','brotherhood']
        original=Native.newSkillCount;state=self.state(2)
        from gui.mods.offline_lan_0922 import offline_services_ui as svc
        modules={'gui.shared.gui_items.Tankman':NS(Tankman=Native)}
        with patch.dict(sys.modules,modules),patch.object(svc,'snapshot',side_effect=state.snapshot):
            try:
                svc._install_crew_skill_counter();svc._install_crew_skill_counter()
                self.assertEqual((2,100),Native().newSkillCount)
                other=Native();other.invID=100002;self.assertEqual((1,0),other.newSkillCount)
                state.snapshot()[policy.CREDITS]['100001']['remaining']=0
                self.assertEqual((1,0),Native().newSkillCount)
            finally:svc.uninstall();svc.uninstall()
        self.assertIs(original,Native.newSkillCount)


if __name__=='__main__':unittest.main()
