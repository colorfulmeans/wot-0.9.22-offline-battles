"""Profile ownership, explicit saves and independent real-Tk undo histories."""
import copy
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest import mock

import bot_tactics_store as storage
import bot_tactics_ui as ui


def profile(name,skill='regular'):
    doc=storage.contract.default_profile(name)
    doc['behavior']=[dict(team=0,class_tag='all',slot=-1,values={'skill':skill})]
    return doc


class StoreOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=storage.Store(self.temp.name)

    def test_saving_applied_file_updates_next_battle_but_other_file_does_not(self):
        s=self.store;s.save(profile('A'),True);s.save(profile('B','elite'))
        self.assertEqual(profile('A'),s.active())
        s.save(profile('A','elite'));self.assertEqual(profile('A','elite'),s.active())
        storage._atomic(s.profile_path('A'),profile('A','veteran'))
        self.assertEqual(profile('A','veteran'),storage.contract.load(s.ensure_active()))

    def test_rename_moves_file_and_applied_owner_delete_returns_default(self):
        s=self.store;s.save(profile('A'),True)
        s.save(profile('B','elite'),previous_name='A')
        self.assertFalse(s.profile_path('A').exists());self.assertEqual('B',s.active()['name'])
        self.assertEqual(profile('B','elite'),s.read('B'))
        s.delete('B');self.assertEqual(['Default'],s.names())
        self.assertEqual(storage.contract.default_profile(),s.active())
        with self.assertRaises(storage.contract.TacticsError):s.delete('Default')

    def test_collision_and_default_cannot_overwrite_existing_files(self):
        s=self.store;s.save(profile('A'),True);before=s.active_path.read_bytes()
        for name in ('A','a','Default','default'):
            with self.assertRaises(storage.contract.TacticsError):s.save(profile(name,'elite'),previous_name=None)
        self.assertEqual(before,s.active_path.read_bytes())
        self.assertEqual(profile('A'),s.read('A'))

    def test_failed_rename_and_delete_restore_files_and_active_content(self):
        s=self.store;s.save(profile('A'),True)
        before={p:p.read_bytes() for p in (s.profile_path('A'),s.active_path)}
        replace=storage.os.replace
        def fail_active(src,dst):
            if Path(dst)==s.active_path:raise OSError('test write failure')
            return replace(src,dst)
        with mock.patch.object(storage.os,'replace',side_effect=fail_active):
            with self.assertRaises(OSError):s.save(profile('B','elite'),previous_name='A')
            with self.assertRaises(OSError):s.delete('A')
        self.assertFalse(s.profile_path('B').exists())
        for path,data in before.items():self.assertEqual(data,path.read_bytes())
        self.assertFalse(list(s.root.rglob('*.tmp')))


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'requires actual Tk display')
class ProfileEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.store=storage.Store(self.temp.name)
        self.store.save(profile('A'));self.store.save(profile('B'))
        self.e=ui.BotTacticsEditor(self.root,store=self.store)
        self.errors=mock.patch.object(self.e,'error').start();self.addCleanup(mock.patch.stopall)

    def test_selection_opens_without_false_prompt_and_same_selection_keeps_forms(self):
        e=self.e;self.assertEqual('readonly',str(e.profile_box.cget('state')))
        with mock.patch.object(ui.messagebox,'askyesno') as ask:
            e.profile_name.set('A');e.open_profile()
            ask.assert_not_called();self.assertEqual('A',e.document['name'])
            e.rule_vars['reaction_seconds'].set('1');e.open_profile()
            self.assertEqual('1',e.rule_vars['reaction_seconds'].get())
            e.profile_name.set('B');e.open_profile();ask.assert_not_called()
            self.assertEqual('',e.rule_vars['reaction_seconds'].get())
        self.errors.assert_not_called()

    def test_dirty_cancel_and_read_failure_keep_draft_and_display(self):
        e=self.e;e.adopt(self.store.read('A'));e.rule_vars['skill'].set('elite');e.save_rule()
        before=copy.deepcopy(e.document)
        with mock.patch.object(ui.messagebox,'askyesno',return_value=False) as ask:
            e.profile_name.set('B');e.open_profile();ask.assert_called_once()
        self.assertEqual(before,e.document);self.assertEqual('A',e.profile_name.get())
        with mock.patch.object(e,'discard_prompt',return_value=True),mock.patch.object(self.store,'read',side_effect=OSError('read')):
            e.profile_name.set('B');e.open_profile()
        self.assertEqual(before,e.document);self.assertEqual('A',e.profile_name.get())

    def test_new_and_import_are_unsaved_and_export_requires_save(self):
        e=self.e
        with mock.patch.object(ui.ui_layout,'ask_string',return_value='New'):e.new_profile()
        self.assertTrue(e.dirty());self.assertIsNone(e.saved_name)
        with mock.patch.object(ui.messagebox,'showinfo') as info,mock.patch.object(ui.filedialog,'asksaveasfilename') as dialog:
            e.export_profile();info.assert_called_once();dialog.assert_not_called()
        source=Path(self.temp.name)/'import.json';storage._atomic(source,profile('Imported'))
        with mock.patch.object(e,'discard_prompt',return_value=True),mock.patch.object(ui.filedialog,'askopenfilename',return_value=str(source)):
            e.import_profile()
        self.assertTrue(e.unsaved_new);self.assertEqual('Imported',e.document['name'])
        e.save();self.assertFalse(e.dirty());self.assertEqual('Imported',e.saved_name)
        self.errors.assert_not_called()

    def test_rename_is_draft_until_save_and_undo_never_restores_name(self):
        e=self.e;e.adopt(self.store.read('A'))
        e.rule_vars['skill'].set('elite');e.save_rule()
        with mock.patch.object(ui.ui_layout,'ask_string',return_value='Renamed'):e.rename_profile()
        self.assertTrue(e.dirty());self.assertTrue(self.store.profile_path('A').exists())
        self.assertFalse(self.store.profile_path('Renamed').exists())
        e.save();self.assertFalse(e.dirty());self.assertFalse(self.store.profile_path('A').exists())
        e.undo('behavior');self.assertEqual('Renamed',e.document['name']);self.assertTrue(e.dirty())
        e.redo('behavior');self.assertFalse(e.dirty());self.errors.assert_not_called()

    def test_independent_histories_and_button_grid(self):
        e=self.e;e.adopt(self.store.read('A'))
        e.rule_vars['skill'].set('elite');e.save_rule()
        e.checkpoint('maps');e.document['maps']={};e.mark()
        maps=copy.deepcopy(e.document['maps'])
        e.undo('behavior');self.assertEqual('regular',e.document['behavior'][0]['values']['skill'])
        self.assertEqual(maps,e.document['maps'])
        behavior=copy.deepcopy(e.document['behavior']);e.undo('maps')
        self.assertEqual(behavior,e.document['behavior']);self.assertTrue(e.document['maps'])
        e.redo('behavior');self.assertEqual('elite',e.document['behavior'][0]['values']['skill'])
        buttons=[b for scope,redo,b in e.history_buttons if scope=='behavior']
        self.assertEqual(['1','1'],[str(b.grid_info()['row']) for b in buttons])
        self.assertEqual(['0','1'],[str(b.grid_info()['column']) for b in buttons])
        e.adopt(storage.contract.default_profile())
        self.assertTrue(all(str(b.cget('state'))=='disabled' for _,_,b in e.history_buttons))
        self.assertEqual('normal',str(e.apply_button.cget('state')))

    def test_delete_confirmation_and_failure_preserve_editor_then_success_resets(self):
        e=self.e;self.store.save(profile('A'),True);e.adopt(self.store.read('A'))
        with mock.patch.object(ui.messagebox,'askyesno',return_value=False):e.delete_profile()
        self.assertEqual('A',e.document['name'])
        with mock.patch.object(ui.messagebox,'askyesno',return_value=True),mock.patch.object(self.store,'delete',side_effect=OSError('delete')):
            e.delete_profile()
        self.assertEqual('A',e.document['name'])
        with mock.patch.object(ui.messagebox,'askyesno',return_value=True) as ask:e.delete_profile()
        self.assertIn('Default',ask.call_args.args[1]);self.assertTrue(e.builtin)
        self.assertEqual('Default',self.store.active()['name'])

    def test_new_collision_and_cancelled_import_keep_current_draft(self):
        e=self.e;before=copy.deepcopy(e.document)
        with mock.patch.object(ui.ui_layout,'ask_string',return_value='A'):e.new_profile()
        self.assertEqual(before,e.document);self.errors.assert_called_once()
        source=Path(self.temp.name)/'default.json';storage._atomic(source,storage.contract.default_profile())
        with mock.patch.object(ui.filedialog,'askopenfilename',return_value=str(source)),mock.patch.object(ui.ui_layout,'ask_string',return_value=None):
            e.import_profile()
        self.assertEqual(before,e.document)
        with mock.patch.object(ui.filedialog,'askopenfilename',return_value=str(source)),mock.patch.object(ui.ui_layout,'ask_string',return_value='Imported default'):
            e.import_profile()
        self.assertFalse(e.builtin);self.assertTrue(e.dirty());e.save()
        self.assertEqual('Imported default',e.saved_name)
        self.assertEqual(storage.contract.default_profile(),self.store.read('Default'))

    def test_save_failure_keeps_renamed_draft_and_old_owner(self):
        e=self.e;e.adopt(self.store.read('A'))
        with mock.patch.object(ui.ui_layout,'ask_string',return_value='Renamed'):e.rename_profile()
        with mock.patch.object(self.store,'save',side_effect=OSError('write')):e.save(True)
        self.assertEqual('Renamed',e.document['name']);self.assertEqual('A',e.saved_name)
        self.assertTrue(e.dirty());self.assertTrue(self.store.profile_path('A').exists())


if __name__=='__main__':unittest.main()
