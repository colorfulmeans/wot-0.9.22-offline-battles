"""Real bilingual Tk edits use current save and current stock, not old fixtures."""
import os
import tempfile
import unittest
from unittest import mock
import tkinter as tk
from tkinter import ttk, filedialog
import wot_launcher as ui


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'requires Tk display')
class ServiceWidgetTests(unittest.TestCase):
    def test_account_reserve_and_capacity_controls_edit_the_selected_save(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {
                'APPDATA': os.path.join(temp, 'roaming'), 'LOCALAPPDATA': os.path.join(temp, 'local')}), \
                mock.patch.object(ui.core, 'load_settings', return_value={'language': 'zh', 'free_notice_seen': True}), \
                mock.patch.object(ui.core, 'discover_game_folders', return_value=[]), \
                mock.patch.object(ui.core, 'game_is_running', return_value=False):
            app = ui.LauncherWindow(tk, ttk, filedialog)
            try:
                slot = ui.save_slots.create_slot('Widgets', ui.save_slots.MODE_NEW_ACCOUNT)
                app._save_slot_id = slot['id']; app._refresh_save_slots()
                tabs = list(app.save_tabs.tabs())
                self.assertEqual(str(app.reserves_panel), tabs[1])
                self.assertEqual(4, app.premium_entry.grid_info()['row'])
                self.assertEqual(5, app.earnings_entry.master.grid_info()['row'])
                app.premium_entry.delete(0, 'end'); app.premium_entry.insert(0, '7')
                self.assertTrue(app._apply_account())
                self.assertEqual(7, ui.save_ledger.premium_days(slot['id']))
                app.slots_quantity.set('5'); self.assertTrue(app._add_garage_slots())
                metadata = ui.save_ledger._read_state(ui.save_slots.metadata_path(slot['id']))
                self.assertEqual(35, metadata['initial_slots'])
                panel = app.reserves_editor
                panel.refresh(); panel.tree.selection_set('xp'); panel.select()
                panel.quantity.set('23'); panel.set_quantity(); panel.save()
                self.assertEqual(23, ui.save_services.read_reserves(slot['id'])['xp'])
                panel.quantity.set('0'); panel.set_quantity(); panel.save()
                self.assertEqual(0, ui.save_services.read_reserves(slot['id'])['xp'])
                before = ui.save_ledger._read_state(ui.save_slots.metadata_path(slot['id']))
                panel.save()
                self.assertEqual(before, ui.save_ledger._read_state(ui.save_slots.metadata_path(slot['id'])))
                for language in ('English', '中文'):
                    app.language_choice.set(language); app._language_selected()
                    self.assertEqual('0', str(panel.tree.item('xp', 'values')[-1]))
                second = ui.save_slots.create_slot('Other', ui.save_slots.MODE_NEW_ACCOUNT)
                app._save_slot_id = second['id']
                panel.quantity.set('99'); panel.set_quantity(); panel.save()
                self.assertEqual(0, ui.save_services.read_reserves(second['id'])['xp'])
                panel.refresh(); self.assertEqual(0, panel.counts['xp'])
            finally:
                app.root.destroy()
