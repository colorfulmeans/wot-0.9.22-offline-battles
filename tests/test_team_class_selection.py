"""Exhaust positive class masks, guarantees, quotas and actual roster generation."""
import copy
import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import team_class_policy as p,bot_tactics
from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime
from gui.mods.offline_lan_0922.bot_fitting_data import CLASSES as VEHICLE_CLASSES
from test_port_0922_server_team_size import BattleState,_Connection,_hello,_attach_worker


def selection(tags):
    row={tag:tag in tags for tag in p.CLASSES};row.update(random=False,order=list(tags));return row


class PositiveSelectionTests(unittest.TestCase):
    def test_all_masks_capacities_trim_newest_and_never_restore_on_growth(self):
        for count in range(16):
            for mask in range(1,32):
                tags=[tag for i,tag in enumerate(p.CLASSES) if mask&(1<<i)]
                row=selection(tags);removed=p.trim(row,count)
                self.assertEqual(tags[:count],row['order'])
                self.assertEqual(list(reversed(tags[count:])),removed)
                before=copy.deepcopy(row);p.trim(row,15);self.assertEqual(before,row)
                self.assertEqual(not bool(row['order']),row['random'])
    def test_pinned_bots_satisfy_guarantees_and_humans_do_not(self):
        row=selection(['heavyTank','SPG']);p.trim(row,1,['heavyTank'])
        self.assertEqual(['SPG'],p.required(row,['heavyTank']))
        self.assertEqual(1,p.artillery_limit(2,1,0,row))
        self.assertEqual(0,p.artillery_limit(2,1,1,row))
    def test_only_artillery_refuses_impossible_fill_and_low_manual_spg_is_legal(self):
        for size in range(1,16):
            row=selection(['SPG']);limit=p.artillery_limit(size,0,0,row)
            self.assertEqual(max(1,0 if size<=6 else min(3,(size-4)//3)),limit)
            self.assertIsNone(p.validate(row,1,[],{'SPG'},limit))
            if size>limit:self.assertEqual('pool',p.validate(row,size,[],{'SPG'},limit))
    def test_random_restores_old_quota_and_ignores_remembered_false_flags(self):
        row=selection(['SPG']);row['random']=True
        self.assertTrue(all(p.allows(row,t) for t in p.CLASSES));self.assertFalse(p.required(row))
        self.assertEqual(0,p.artillery_limit(6,0,0,row))
    def test_missing_classes_and_impossible_tier_windows_refuse(self):
        row=selection(['heavyTank']);self.assertEqual('missing_class',p.validate(row,2,[],{'lightTank'},0))
        candidates=[(7,'lightTank'),(8,'mediumTank'),(9,'heavyTank')]
        self.assertEqual((7,8,9),p.matching_tiers(candidates,['lightTank','heavyTank'],[8],(8,),True))
        self.assertIsNone(p.matching_tiers(candidates,['lightTank','heavyTank'],[8],(8,),False))
        self.assertEqual((8,9),p.matching_tiers(candidates,[],[8],(8,),True,[['heavyTank']]))

    def test_adjustment_messages_are_deduplicated_and_malformed_rows_are_contained(self):
        from gui.mods.offline_lan_0922.lan_session import LANSession
        from unittest.mock import Mock
        owner=NS(_status_notifier=Mock())
        message=dict(team_class_notice=dict(revision=3,changes=[dict(team=1,removed=['SPG']),dict(team=2,removed=['heavyTank'])]))
        LANSession._show_class_adjustment(owner,message)
        self.assertEqual(2,owner._status_notifier.call_count)
        LANSession._show_class_adjustment(owner,message)
        self.assertEqual(2,owner._status_notifier.call_count)
        LANSession._show_class_adjustment(owner,dict(team_class_notice=dict(revision=4,changes=[None,dict(team=2,removed='SPG')])))
        self.assertEqual(2,owner._status_notifier.call_count)


class ActualRosterTests(unittest.TestCase):
    def prepare(self,size,tags,worker,pinned=(),human='mediumTank'):
        entries={i:NS(name='ussr:'+tag,level=8,tags=(tag,)) for i,tag in enumerate(p.CLASSES)}
        by_name={v.name:v for v in entries.values()};descriptor=NS(type=by_name['ussr:'+human])
        battle=BattleRuntime.__new__(BattleRuntime)
        battle._runtime=NS(nations=NS(AVAILABLE_NAMES=('all',),INDICES={'all':0}),vehicles=NS(g_list=NS(getList=lambda unused:entries)))
        battle._worker_mode=worker;battle._config={'vehicle':descriptor.type.name}
        battle.client=NS(team=1,player_id=1);battle._resolve_descriptor=lambda name:NS(type=by_name[name])
        choices=p.canonical();choices['2']=selection(tags)
        battle._start_message=dict(round_id=19,map='01_karelia',team_sizes={'1':size,'2':size},team_classes=choices,
            players=[dict(id=1,team=1,slot=0,vehicle=descriptor.type.name)],
            bots=[dict(id=team*100+slot,team=team,slot=slot) for team in (1,2) for slot in range(1 if team==1 else 0,size)],
            bot_tier_mode='same',bot_lineup=list(pinned))
        with redirect_stdout(io.StringIO()):ok=battle._prepare_bot_vehicle_assignments(descriptor)
        return ok,battle._bot_vehicle_assignments,by_name
    def test_every_five_class_subset_at_every_team_size_matches_worker_and_visible(self):
        for size in range(1,16):
            for mask in range(1,32):
                tags=[t for i,t in enumerate(p.CLASSES) if mask&(1<<i)]
                expected=len(tags)<=size and (tags!=['SPG'] or size<=p.artillery_limit(size,0,0,selection(tags)))
                results=[]
                for worker in (False,True):
                    ok,assigned,by_name=self.prepare(size,tags,worker)
                    self.assertEqual(expected,ok,(size,tags,worker))
                    if ok:
                        actual=[next(iter(by_name[n].tags)) for (team,slot),n in assigned.items() if team==2]
                        self.assertEqual(size,len(actual));self.assertEqual(set(tags),set(actual))
                        self.assertLessEqual(actual.count('SPG'),p.artillery_limit(size,0,0,selection(tags)))
                    results.append(assigned)
                self.assertEqual(results[0],results[1])
    def test_fixed_unselected_bots_survive_and_satisfy_selected_type(self):
        pinned=[dict(team=2,slot=0,vehicle='ussr:heavyTank')]
        ok,assigned,by_name=self.prepare(6,['lightTank','SPG'],True,pinned)
        self.assertTrue(ok);self.assertEqual('ussr:heavyTank',assigned[(2,0)])
        actual=[next(iter(by_name[n].tags)) for (team,slot),n in assigned.items() if team==2 and slot!=0]
        self.assertEqual({'lightTank','SPG'},set(actual));self.assertEqual(1,actual.count('SPG'))


class StartPreflightTests(unittest.TestCase):
    def state(self,size=15):
        state=BattleState(team_size=size);_attach_worker(state)
        host,error=state.add_player(_Connection(),('127.0.0.1',1001),_hello(1,team=1))
        names={tag:next(n for n in sorted(VEHICLE_CLASSES) if VEHICLE_CLASSES[n]==tag) for tag in p.CLASSES}
        state.vehicle_catalogs[host.player_id]=tuple([dict(name=n,level=8,tags=[t]) for t,n in names.items()]+[dict(name=host.vehicle,level=8,tags=['lightTank'])])
        state.bot_tier_mode='same';return state,host,names
    def test_invalid_all_spg_and_missing_class_are_refused_before_loading(self):
        state,host,names=self.state();state.team_classes['2']=selection(['SPG'])
        start,error=state.request_start(host.player_id)
        self.assertEqual('bot_class_pool_empty',error);self.assertEqual('waiting',state.phase)
        self.assertEqual(dict(team=2,reason='pool',classes=['SPG']),state.last_bot_class_error)
        state.team_classes['2']=selection(['heavyTank'])
        state.bot_excluded_vehicles=[names['heavyTank']]
        start,error=state.request_start(host.player_id)
        self.assertEqual('bot_class_pool_empty',error);self.assertEqual('missing_class',state.last_bot_class_error['reason'])
    def test_one_bot_slot_can_replace_its_only_checked_type_without_a_toggle_trap(self):
        state,host,names=self.state(1)
        self.assertTrue(state.set_team_class(host.player_id,2,'random',False))
        self.assertTrue(state.set_team_class(host.player_id,2,'SPG',True))
        row=state.team_classes['2']
        self.assertEqual(['SPG'],row['order']);self.assertFalse(row['random'])
        self.assertEqual(['lightTank'],state.team_class_notice['removed'])

    def test_random_human_assignment_rechecks_actual_bot_slots_before_start(self):
        state,host,names=self.state(2)
        state.select_team(host.player_id,0)
        state.team_classes['1']=selection(['lightTank','mediumTank'])
        state.team_classes['2']=selection(['lightTank','mediumTank'])
        start,error=state.request_start(host.player_id)
        self.assertIsNone(error)
        side=state.players[host.player_id].team
        self.assertEqual(['lightTank'],start['team_classes'][str(side)]['order'])
        self.assertTrue(start['team_class_notice']['removed'])

    def test_single_manual_artillery_is_accepted_below_seven(self):
        state,host,names=self.state(1);state.team_classes['2']=selection(['SPG'])
        start,error=state.request_start(host.player_id)
        self.assertIsNone(error);self.assertEqual(1,len(start['bots']))
        self.assertFalse(start['team_classes']['2']['random']);self.assertTrue(start['team_classes']['2']['SPG'])


if __name__=='__main__':unittest.main()
