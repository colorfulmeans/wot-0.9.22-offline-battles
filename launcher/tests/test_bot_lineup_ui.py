"""Draft/identity regressions plus real Tk acceptance on Windows CI."""
import copy
import json
import os
import types
import unittest
from unittest import mock
import bot_lineup_profiles as profiles
import bot_lineup_ui as ui

CHOICES = [dict(nation='china',vehicle='Ch22_113',label='113',level=10,vehicleClass='heavyTank',tags=['heavyTank']),
           dict(nation='china',vehicle='Ch22_113P',label='113',level=10,vehicleClass='heavyTank',tags=['heavyTank']),
           dict(nation='usa',vehicle='T1',label='T1',level=1,vehicleClass='lightTank',tags=['lightTank'])]


def editor():
    store, name = profiles.create(profiles.empty_store(), 'Review')
    e = ui.BotLineupEditorWindow.__new__(ui.BotLineupEditorWindow)
    e._store, e._profile_name = store, name
    e._draft = profiles.runtime_assignments(store, name)
    e._original = copy.deepcopy(e._draft)
    e._choices = profiles.eligible_vehicle_choices(CHOICES)
    e._bulk_states = {1:{},2:{}}
    e._bulk = {1:{},2:{}}
    e._rows = {(r['team'],r['slot']):{} for r in e._draft}
    e._catalog_ready = True
    e.language = 'en'
    e._dirty = False
    e.status = mock.Mock()
    e.root = mock.Mock()
    e._messagebox = mock.Mock()
    e._on_save = mock.Mock(return_value=True)
    e._render = mock.Mock()
    return e


class DraftTests(unittest.TestCase):
    def test_legacy_unpinned_slots_remain_random_instead_of_disappearing(self):
        store,name = profiles.create(profiles.empty_store(),'Old')
        store = profiles.set_assignment(store,name,1,14,None,'elite')
        rows = profiles.runtime_assignments(store,name)
        self.assertEqual(30,len(rows))
        self.assertTrue(all(r['enabled'] for r in rows))
        self.assertEqual('elite',rows[14]['skill'])
        self.assertNotIn('vehicle',rows[14])

    def test_bulk_difficulty_does_not_enable_empty_slots_or_touch_other_team(self):
        e=editor()
        for r in e._draft:r['enabled']=False
        e._read=mock.Mock(return_value='elite')
        e._changed(1,None,'skill')
        self.assertFalse(any(r['enabled'] for r in e._draft))
        self.assertTrue(all(r.get('skill')=='elite' for r in e._draft[:15]))
        self.assertTrue(all('skill' not in r for r in e._draft[15:]))

    def test_empty_slot_difficulty_survives_save_reopen_and_random_enable(self):
        e = editor()
        e._read = mock.Mock(return_value=ui.CLEAR)
        e._changed(1, None, 'vehicle')
        e._read.return_value = 'elite'
        e._changed(1, None, 'skill')
        self.assertTrue(e._save())
        saved = profiles.normalize_store(json.loads(json.dumps(e._store)))
        rows = profiles.runtime_assignments(saved, 'Review')
        self.assertTrue(all(not r['enabled'] and r.get('skill') == 'elite' for r in rows[:15]))
        self.assertEqual('elite', e._bulk_states[1]['skill'])
        reopened = editor()
        reopened._store = saved
        reopened._draft = rows
        reopened._original = copy.deepcopy(rows)
        reopened._read = mock.Mock(return_value=ui.RANDOM)
        reopened._changed(1, None, 'vehicle')
        self.assertTrue(reopened._save())
        self.assertTrue(all(r['enabled'] and r.get('skill') == 'elite' for r in reopened._draft[:15]))
        self.assertTrue(all('skill' not in r for r in reopened._draft[15:]))
        reopened._read.return_value = None
        reopened._changed(1, 14, 'vehicle')
        self.assertTrue(reopened._save())
        self.assertEqual(dict(team=1, slot=14, enabled=False), reopened._draft[14])

    def test_unloaded_catalogue_save_shows_failure_without_writing_or_losing_draft(self):
        e = editor()
        e._catalog_ready = False
        e._draft[0]['skill'] = 'elite'
        before = copy.deepcopy(e._store)
        self.assertFalse(e._save())
        e._messagebox.showerror.assert_called_once()
        e._on_save.assert_not_called()
        self.assertEqual(before, e._store)
        self.assertEqual('elite', e._draft[0]['skill'])

    def test_clear_team_and_sparse_save_preserve_slot_ids(self):
        e=editor();e._read=mock.Mock(return_value=ui.CLEAR)
        e._changed(1,None,'vehicle')
        self.assertFalse(any(r['enabled'] for r in e._draft[:15]))
        self.assertTrue(all(r['enabled'] for r in e._draft[15:]))
        e._read.return_value='china:Ch22_113P'
        e._changed(1,14,'vehicle')
        self.assertTrue(e._save())
        rows=profiles.runtime_assignments(e._on_save.call_args.args[0],e._profile_name)
        self.assertEqual([14],[r['slot'] for r in rows if r['team']==1 and r['enabled']])
        self.assertEqual('china:Ch22_113P',rows[14]['vehicle'])

    def test_failed_save_retains_draft_and_does_not_replace_saved_baseline(self):
        e=editor();original=copy.deepcopy(e._store)
        e._draft[0]['skill']='elite'
        e._on_save.return_value=False
        self.assertFalse(e._save())
        self.assertEqual(original,e._store)
        self.assertNotEqual(e._original,e._draft)
        self.assertEqual('elite',e._draft[0]['skill'])
        e._messagebox.showerror.assert_called_once()

    def test_random_and_disabled_are_distinct_after_roundtrip(self):
        e=editor();e._draft[0]=dict(team=1,slot=0,enabled=False)
        e._draft[1]=dict(team=1,slot=1,enabled=True,nation='china',vehicle_class='heavyTank')
        self.assertTrue(e._save())
        rows=profiles.runtime_assignments(e._store,e._profile_name)
        self.assertFalse(rows[0]['enabled'])
        self.assertTrue(rows[1]['enabled'])
        self.assertNotIn('vehicle',rows[1])
        self.assertEqual('china',rows[1]['nation'])

    def test_single_slot_change_resets_all_bulk_captions_to_individual(self):
        e=editor();e._bulk_states[1]=dict(skill='elite',nation='china')
        e._read=mock.Mock(return_value='rookie')
        e._changed(1,3,'skill')
        self.assertEqual({},e._bulk_states[1])
        self.assertEqual('rookie',e._draft[3]['skill'])


class RealTkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
            from tkinter import ttk
            cls.tk,cls.ttk=tk,ttk
            cls.parent=tk.Tk();cls.parent.withdraw()
        except Exception as error:
            if os.environ.get('GITHUB_ACTIONS') == 'true' and os.name == 'nt':
                # The packaging job must exercise real Tk, not pass via a skip.
                raise
            raise unittest.SkipTest('Tk desktop unavailable: %s'%error)

    @classmethod
    def tearDownClass(cls):
        cls.parent.destroy()

    def setUp(self):
        store,name=profiles.create(profiles.empty_store(),'Review')
        self.saved=[];self.messages=mock.Mock()
        patch=mock.patch.object(ui.vehicle_overlays,'list_vehicle_choices',return_value=CHOICES)
        patch.start();self.addCleanup(patch.stop)
        self.e=ui.open_bot_lineup_editor(self.parent,'/game',name,store,self.saved.append,
            tk_module=self.tk,ttk_module=self.ttk,messagebox_module=self.messages,language='zh')
        self.addCleanup(lambda:self.e.root.destroy() if self.e.root.winfo_exists() else None)

    def choose(self,team,slot,field,value):
        row=self.e._bulk[team] if slot is None else self.e._rows[(team,slot)]
        label=next(label for v,label in row[field+'_options'] if v==value)
        row[field].set(label);self.e._changed(team,slot,field)
        self.parent.update()

    def test_translation_order_identity_filters_and_language_preserve_draft(self):
        e=self.e
        self.assertIn('自定义',e.root.title())
        self.assertEqual(['清空本队全部槽位','各槽位独立设置'],list(e._bulk[1]['vehicle_box']['values'])[:2])
        self.assertEqual(['全部','中国','美国'],list(e._rows[(1,0)]['nation_box']['values']))
        self.choose(1,0,'nation','china')
        self.choose(1,0,'vehicle_class','heavyTank')
        captions=list(e._rows[(1,0)]['vehicle_box']['values'])
        self.assertTrue(any('[Ch22_113P]' in v for v in captions))
        self.assertFalse(any('T1' in v for v in captions))
        self.choose(1,0,'vehicle','china:Ch22_113P')
        draft=copy.deepcopy(e._draft)
        e.set_language('en');self.parent.update()
        self.assertEqual(draft,e._draft)
        self.assertIn('Exact Bot lineup',e.root.title())
        self.assertTrue(e._save())
        self.assertEqual('china:Ch22_113P',profiles.runtime_assignments(self.saved[-1],'Review')[0]['vehicle'])

    def test_bulk_filters_apply_to_the_team_without_enabling_empty_slots(self):
        self.choose(1,None,'vehicle',ui.CLEAR)
        self.choose(1,None,'nation','china')
        self.choose(1,None,'vehicle_class','heavyTank')
        self.choose(1,None,'skill','elite')
        self.assertFalse(any(r['enabled'] for r in self.e._draft[:15]))
        self.choose(1,None,'vehicle',ui.RANDOM)
        self.assertTrue(all(r['enabled'] and r.get('nation')=='china' and r.get('vehicle_class')=='heavyTank' for r in self.e._draft[:15]))
        self.assertTrue(all('nation' not in r for r in self.e._draft[15:]))

    def test_saved_empty_difficulty_matches_widgets_and_enabled_random_slots(self):
        self.e.set_language('en')
        self.choose(1, None, 'vehicle', ui.CLEAR)
        self.choose(1, None, 'skill', 'elite')
        self.assertTrue(self.e._save())
        self.assertEqual('Elite', self.e._bulk[1]['skill'].get())
        self.assertTrue(all(self.e._rows[(1, s)]['skill'].get() == 'Elite' for s in range(15)))
        self.assertTrue(all(not r['enabled'] for r in self.e._draft[:15]))
        saved = json.loads(json.dumps(self.saved[-1]))
        self.e.root.destroy()
        self.e = ui.open_bot_lineup_editor(self.parent, '/game', 'Review', saved,
            self.saved.append, tk_module=self.tk, ttk_module=self.ttk,
            messagebox_module=self.messages, language='en')
        self.choose(1, None, 'vehicle', ui.RANDOM)
        self.assertTrue(self.e._save())
        self.assertTrue(all(r['enabled'] and r.get('skill') == 'elite' for r in self.e._draft[:15]))

    def test_unloaded_catalogue_failure_is_localized_and_preserves_editor(self):
        self.e._catalog_ready = False
        self.assertFalse(self.e._save())
        title, message = self.messages.showerror.call_args.args
        self.assertEqual(ui.ZH['Save'], title)
        self.assertIn(ui.ZH['Save failed: %s'].split('%s')[0], message)
        self.assertTrue(self.e.root.winfo_exists())
        self.assertEqual([], self.saved)

    def test_close_dialog_uses_three_content_sized_buttons_and_discard(self):
        self.choose(1,0,'skill','elite')
        self.e._close();self.parent.update()
        dialog=next(c for c in self.e.root.winfo_children() if isinstance(c,self.tk.Toplevel))
        buttons=[c for frame in dialog.winfo_children() for c in frame.winfo_children() if isinstance(c,self.ttk.Button)]
        self.assertEqual(['保存并关闭','放弃修改','取消'],[b['text'] for b in buttons])
        self.assertTrue(all(str(b['width'])=='0' for b in buttons))
        buttons[1].invoke();self.parent.update()
        self.assertEqual([],self.saved)
        self.assertFalse(self.e.root.winfo_exists())


if __name__=='__main__':unittest.main()
