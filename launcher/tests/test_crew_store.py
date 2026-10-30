"""Per-save recruit requests and real Tk selector dependencies."""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import crew_store as store
import crew_ui

VEHICLES = [dict(name='ussr:R11_MS-1', nation='ussr', label='MS-1', roles=('commander','driver'),seats=store.crew_skills.seats('ussr:R11_MS-1'),vehicleClass='lightTank'),
            dict(name='usa:A01_T1_Cunningham', nation='usa', label='T1', roles=('commander','driver'),seats=store.crew_skills.seats('usa:A01_T1_Cunningham'),vehicleClass='lightTank')]


class CrewCatalogueTests(unittest.TestCase):
    def test_player_filter_hides_missing_model_and_clones_but_keeps_supported_retired(self):
        import bot_lineup_profiles
        choices=[dict(nation='uk',vehicle='GB70_FV4202_105',member='blocked'),
                 dict(nation='ussr',vehicle='R03_BT-7_bootcamp',member='clone',tags=['secret']),
                 dict(nation='germany',vehicle='G85_Auf_Panther',member='retired'),
                 dict(nation='ussr',vehicle='R11_MS-1',member='normal')]
        def native(member):
            self.assertNotIn(member,('blocked','clone'))
            name=next(r['nation']+':'+r['vehicle'] for r in choices if r['member']==member)
            crew=NS(children=[(roles[0].encode(),None) for roles in store.crew_skills.seats(name)])
            return NS(children=[(b'crew',NS(value=crew))])
        with patch.object(store.vehicle_overlays,'_require_target',return_value=({},'fixture')), \
             patch.object(store.vehicle_overlays,'list_vehicle_choices',return_value=choices), \
             patch.object(store.zipfile,'ZipFile') as archive, \
             patch.object(store.vehicle_overlays.packed_xml,'read_packed_xml',side_effect=native):
            archive.return_value.__enter__.return_value.read.side_effect=lambda name:name
            rows=store.catalogue('game')
        self.assertEqual(['germany:G85_Auf_Panther','ussr:R11_MS-1'],[r['name'] for r in rows])


class CrewStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        for slot in ('one', 'two'): Path(self.root, slot).mkdir()
        self.catalogue = patch.object(store, 'catalogue', return_value=VEHICLES)
        self.catalogue.start(); self.addCleanup(self.catalogue.stop)

    def add(self, slot='one', **changes):
        values = dict(vehicle='ussr:R11_MS-1', seat=0, female=False, skills=2)
        values.update(changes)
        return store.add(slot, 'game', root=self.root, is_running=lambda: False, **values)

    def test_add_before_first_start_is_isolated_and_does_not_touch_existing_garage(self):
        garage = Path(self.root, 'one', 'garage_state.json')
        garage.write_text(json.dumps(dict(preserve=True,ledger=dict(berths=30,barracks=[]))), encoding='utf8')
        before = garage.read_bytes()
        first = self.add(); second = self.add()
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(2, len(store.contract.read(store.inbox_path('one', root=self.root))))
        self.assertEqual([], store.contract.read(store.inbox_path('two', root=self.root)))
        self.assertEqual(before, garage.read_bytes())

    def test_role_mismatch_and_running_game_do_not_queue_anything(self):
        with self.assertRaises(ValueError): self.add(seat=99)
        with self.assertRaises(store.save_ledger.SaveLedgerError):
            store.add('one','game','ussr:R11_MS-1',0,False,2,
                      root=self.root,is_running=lambda:True)
        self.assertFalse(Path(store.inbox_path('one',root=self.root)).exists())

    def test_virtual_default_slot_can_queue_before_its_first_client_start(self):
        self.assertEqual(store.contract.FILE_NAME,store.save_slots.LAUNCHER_CREW_INBOX_NAME)
        self.add(slot='default')
        self.assertEqual(1,len(store.contract.read(store.inbox_path('default',root=self.root))))

    def test_atomic_replace_failure_preserves_previous_requests(self):
        self.add(); path = Path(store.inbox_path('one',root=self.root)); before = path.read_bytes()
        with patch.object(store.os,'replace',side_effect=OSError('write denied')):
            with self.assertRaises(OSError): self.add()
        self.assertEqual(before,path.read_bytes()); self.assertFalse(Path(str(path)+'.tmp').exists())


class BerthTests(CrewStoreTests):
    def state(self, total=2, members=None, receipts=None):
        ledger=dict(berths=total,barracks=members or [],launcherCrewReceipts=receipts or [],wallet=dict(gold=17))
        path=Path(self.root,'one','garage_state.json')
        path.write_text(json.dumps(dict(ledger=ledger)))
        return path

    def test_capacity_reads_real_client_ledger_passports_and_counts_identical_people(self):
        from gui.mods.offline_lan_0922.account_rpc import garage_store
        ledger=garage_store._ledger_payload(dict(accountBerths=2,barracksTankmen={100001:b'passport',100002:b'passport'}))
        Path(self.root,'one','garage_state.json').write_text(json.dumps(dict(ledger=ledger)))
        result=store.capacity('one','game',self.root)
        self.assertEqual(2,result['occupied']);self.assertEqual(0,result['available'])

    def test_pending_reserves_space_but_delivered_receipt_is_not_counted_twice(self):
        path=self.state(total=2)
        first=self.add();self.add()
        with self.assertRaises(store.BerthsFullError):self.add()
        self.assertEqual(2,len(store.contract.read(store.inbox_path('one',root=self.root))))
        self.state(total=2,members=['cGFzc3BvcnQ='],receipts=[first['id']])
        self.assertEqual(dict(total=2,occupied=1,pending=1,available=0),store.capacity('one','game',self.root))

    def test_expand_adds_exactly_sixteen_preserves_wallet_and_is_slot_local(self):
        path=self.state(total=2,members=['cGFzc3BvcnQ='])
        for expected in (18,34):
            result=store.expand_berths('one','game',self.root,is_running=lambda:False)
            self.assertEqual(expected,result['total'])
        value=json.loads(path.read_text())['ledger']
        self.assertEqual(17,value['wallet']['gold']);self.assertEqual(['cGFzc3BvcnQ='],value['barracks'])
        self.assertEqual(2,len(value['personalMissions']['notifications']))
        self.assertEqual(2000,store.capacity('two','game',self.root)['total'])

    def test_new_account_capacity_is_saved_in_metadata_and_backup_restore_reset(self):
        record=store.save_slots.create_slot('New',store.save_slots.MODE_NEW_ACCOUNT,root=self.root)
        identity=record['id'];result=store.expand_berths(identity,'game',self.root,is_running=lambda:False)
        self.assertEqual(46,result['total'])
        metadata=Path(record['path'],'save.json');self.assertEqual(46,json.loads(metadata.read_text())['initial_berths'])
        backup=Path(self.root)/'backup.zip';store.save_slots.backup_slot(identity,str(backup),root=self.root)
        store.expand_berths(identity,'game',self.root,is_running=lambda:False)
        store.save_slots.restore_slot(identity,str(backup),root=self.root,is_running=lambda:False)
        self.assertEqual(46,store.capacity(identity,'game',self.root)['total'])
        store.save_slots.initialize_slot(identity,root=self.root,is_running=lambda:False)
        self.assertEqual(30,store.capacity(identity,'game',self.root)['total'])

    def test_restore_pre_start_capacity_into_default_does_not_reimport_legacy_progress(self):
        root=str(Path(self.root)/'saves')
        record=store.save_slots.create_slot('Prestart',store.save_slots.MODE_NEW_ACCOUNT,root=root)
        store.expand_berths(record['id'],'game',root,is_running=lambda:False)
        backup=Path(self.root)/'prestart.zip';store.save_slots.backup_slot(record['id'],str(backup),root=root)
        legacy=Path(self.root)/'garage_state.json';legacy.write_text('{"old":"legacy progress"}')
        store.save_slots.restore_slot('default',str(backup),root=root,is_running=lambda:False)
        self.assertEqual(46,store.capacity('default','game',root)['total'])
        metadata=json.loads(Path(root,'default','save.json').read_text())
        self.assertTrue(metadata['skip_legacy_import'])
        self.assertEqual(str(Path(root,'default','garage_state.json')),store.save_ledger.ledger_path('default',root=root))

    def test_corrupt_state_and_pending_inbox_refuse_edits(self):
        path=self.state();before=path.read_bytes()
        inbox=Path(store.inbox_path('one',root=self.root));inbox.write_text('not json')
        with self.assertRaises(ValueError):store.expand_berths('one','game',self.root,is_running=lambda:False)
        self.assertEqual(before,path.read_bytes())
        inbox.unlink();path.write_text('{}')
        with self.assertRaises(store.save_ledger.SaveLedgerError):self.add()
        with self.assertRaises(store.save_ledger.SaveLedgerError):store.expand_berths('one','game',self.root,is_running=lambda:False)

    def test_write_failure_and_running_game_keep_original_capacity(self):
        path=self.state();before=path.read_bytes()
        with patch.object(store.save_ledger.os,'replace',side_effect=OSError('full')):
            with self.assertRaises(store.save_ledger.SaveLedgerError):store.expand_berths('one','game',self.root,is_running=lambda:False)
        self.assertEqual(before,path.read_bytes())
        with self.assertRaises(store.save_ledger.SaveLedgerError):store.expand_berths('one','game',self.root,is_running=lambda:True)
        self.assertEqual(before,path.read_bytes())

    def test_other_launcher_process_cannot_write_during_active_edit(self):
        import subprocess,sys
        self.state(total=2)
        repo=Path(__file__).resolve().parents[2]
        script="import sys;sys.path[:0]=sys.argv[2:];import crew_store;\ntry:crew_store.expand_berths('one','game',sys.argv[1],is_running=lambda:False)\nexcept crew_store.save_ledger.SaveLedgerError:sys.exit(42)"
        command=[sys.executable,'-B','-c',script,self.root,str(repo/'launcher'),str(repo/'src/res/scripts/client')]
        with store._edit('one','game',self.root,lambda:False):
            result=subprocess.run(command,capture_output=True,timeout=20)
            self.assertEqual(42,result.returncode,result.stderr)
        result=subprocess.run(command,capture_output=True,timeout=20)
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual(18,store.capacity('one','game',self.root)['total'])

    def test_concurrent_expansions_accumulate_and_native_limit_refuses_overflow(self):
        from concurrent.futures import ThreadPoolExecutor
        self.state(total=2)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda unused:store.expand_berths('one','game',self.root,is_running=lambda:False),range(8)))
        self.assertEqual(130,store.capacity('one','game',self.root)['total'])
        path=self.state(total=2**31-1);before=path.read_bytes()
        with self.assertRaises(store.save_ledger.SaveLedgerError):store.expand_berths('one','game',self.root,is_running=lambda:False)
        self.assertEqual(before,path.read_bytes())

    def test_parallel_recruits_cannot_overbook_last_berth(self):
        from concurrent.futures import ThreadPoolExecutor
        self.state(total=1)
        def recruit(unused):
            try:self.add();return True
            except store.BerthsFullError:return False
        with ThreadPoolExecutor(max_workers=4) as pool:result=list(pool.map(recruit,range(8)))
        self.assertEqual(1,sum(result))


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'requires actual Tk display')
class CrewUITests(unittest.TestCase):
    def test_tier_intersects_class_and_nation_without_recruiting_hidden_vehicle(self):
        p=self.panel
        p.vehicles=[dict(v,level=1 if v['nation']=='ussr' else 2) for v in p.vehicles]
        p.filter();p.variables['tier'].set('2');p.filter()
        self.assertFalse(p.by_label)
        self.assertEqual('',p.variables['vehicle'].get())
        self.assertEqual('disabled',str(p.button.cget('state')))
        p.variables['nation'].set('USA');p.filter()
        self.assertEqual(['usa:A01_T1_Cunningham'],list(p.by_label.values()))
        p.owner._t=lambda text:'translated '+text
        p.translate()
        self.assertEqual(2,p.maps['tier'][p.variables['tier'].get()])
        self.assertEqual('usa:A01_T1_Cunningham',p.maps['vehicle'][p.variables['vehicle'].get()])

    def setUp(self):
        import tkinter as tk
        from tkinter import ttk
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.owner=NS(_tk=tk,_ttk=ttk,_t=lambda x:x,game_root=tk.StringVar(value='game'),
                      _save_slot_id='one',_busy=False,_maintenance_busy=False)
        capacity_patch=patch.object(store,'capacity',return_value=dict(total=2000,occupied=0,pending=0,available=2000))
        capacity_patch.start();self.addCleanup(capacity_patch.stop)
        self.frame=ttk.Frame(self.root)
        self.panel=crew_ui.CrewPanel(self.owner,self.frame)
        with patch.object(store,'catalogue',return_value=copy.deepcopy(VEHICLES)):self.panel.refresh()

    def test_dropdowns_follow_nation_and_primary_role_and_reject_empty_pool(self):
        p=self.panel
        self.assertEqual('ussr:R11_MS-1',next(iter(p.by_label.values())))
        p.variables['class'].set('Heavy tank');p.filter()
        self.assertFalse(p.by_label);self.assertEqual('disabled',str(p.button.cget('state')))
        p.variables['nation'].set('USA');p.variables['class'].set('All');p.filter()
        self.assertEqual('usa:A01_T1_Cunningham',next(iter(p.by_label.values())))
        for box in p.boxes.values():self.assertEqual('readonly',str(box.cget('state')))

    def test_add_button_uses_current_save_gender_and_full_skill_count(self):
        p=self.panel;p.variables['female'].set('Female');p.variables['skills'].set('3')
        self.owner._save_slot_id='two'
        with patch.object(store,'add') as add:
            self.assertTrue(p.add())
        add.assert_called_once_with('two','game','ussr:R11_MS-1',0,True,3,training=100)
        self.assertIn('next game startup',p.feedback.cget('text'))

    def test_language_switch_keeps_internal_selection_and_inbox_identity(self):
        p=self.panel;p.variables['female'].set('Female');p.variables['skills'].set('3')
        self.owner._t=lambda text:'translated '+text
        p.translate()
        self.assertTrue(p.maps['female'][p.variables['female'].get()])
        self.assertEqual(3,p.maps['skills'][p.variables['skills'].get()])

    def test_vehicle_seat_and_training_controls_follow_exact_duplicate_roles(self):
        p=self.panel
        name='ussr:R45_IS-7'
        p.vehicles=[dict(name=name,nation='ussr',label='IS-7',vehicleClass='heavyTank',seats=store.crew_skills.seats(name))]
        p.filter();self.assertIn('Loader1',p.maps['seat']);self.assertIn('Loader2 (Also Radio operator)',p.maps['seat'])
        p.variables['seat'].set('Loader2 (Also Radio operator)');p.update_skills()
        self.assertEqual(11,max(p.maps['skills'].values()))
        p.variables['skills'].set('11');p.variables['seat'].set('Loader1');p.update_skills()
        self.assertEqual('7',p.variables['skills'].get());self.assertIn('limit',p.feedback.cget('text'))
        p.variables['female'].set('Female');p.variables['training'].set('75%');p.update_skills()
        self.assertEqual('1',p.variables['skills'].get());self.assertEqual('disabled',str(p.boxes['skills'].cget('state')))
        p.variables['training'].set('100%');p.update_skills()
        self.assertEqual(1,min(p.maps['skills'].values()));self.assertEqual('readonly',str(p.boxes['skills'].cget('state')))
        self.assertEqual(['nation','class','tier','vehicle','seat','female','training','skills'],list(p.variables))
        p.variables['female'].set('Male');p.variables['training'].set('50%');p.update_skills()
        self.assertEqual('0',p.variables['skills'].get())

    def test_full_barracks_warning_does_not_queue_member(self):
        p=self.panel
        with patch.object(store,'add',side_effect=store.BerthsFullError('Not enough barracks berths. Click Add 16 barracks berths first.')), \
             patch('tkinter.messagebox.showwarning') as warning:
            self.assertFalse(p.add());warning.assert_called_once()
        self.assertIn('Add 16',warning.call_args.args[1])

    def test_unreadable_capacity_disables_both_actions_and_expansion_refreshes_summary(self):
        p=self.panel
        with patch.object(store,'capacity',side_effect=store.save_ledger.SaveLedgerError('broken')):
            p.refresh_capacity()
        self.assertEqual('disabled',str(p.button.cget('state')))
        self.assertEqual('disabled',str(p.expand_button.cget('state')))
        with patch.object(store,'expand_berths',return_value=dict(total=46,occupied=20,pending=3,available=23)) as expand:
            self.assertTrue(p.expand())
        expand.assert_called_once_with('one','game')
        self.assertIn('46',p.capacity_label.cget('text'))
        self.assertEqual('normal',str(p.button.cget('state')))

    def test_nation_order_full_names_and_language_roundtrip_preserve_all_selections(self):
        import nation_choices
        p=self.panel
        self.assertEqual(list(nation_choices.ORDER),list(p.maps['nation'].values()))
        p.variables['female'].set('Female');p.variables['skills'].set('3')
        old={k:p.maps[k].get(v.get()) for k,v in p.variables.items()}
        p.owner._t=lambda text:{'ussr':'苏联','china':'中国'}.get(text,text)
        p.translate()
        self.assertEqual('苏联',p.variables['nation'].get())
        self.assertEqual(old,{k:p.maps[k].get(v.get()) for k,v in p.variables.items()})


if __name__=='__main__':unittest.main()
