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
        garage.write_text('{"preserve":true}', encoding='utf8')
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


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'requires actual Tk display')
class CrewUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from tkinter import ttk
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.owner=NS(_tk=tk,_ttk=ttk,_t=lambda x:x,game_root=tk.StringVar(value='game'),
                      _save_slot_id='one',_busy=False,_maintenance_busy=False)
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
        self.assertEqual(['nation','class','vehicle','seat','female','training','skills'],list(p.variables))
        p.variables['female'].set('Male');p.variables['training'].set('50%');p.update_skills()
        self.assertEqual('0',p.variables['skills'].get())


if __name__=='__main__':unittest.main()
