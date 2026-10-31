"""Measure agreed desktop alignment with real Tk rather than old pixel fixtures."""
import os
import tempfile
import unittest
from unittest import mock
import tkinter as tk
from tkinter import ttk, filedialog
import wot_launcher as ui


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'requires Tk display')
class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for patch in (
                mock.patch.dict(os.environ, {'APPDATA': self.temp.name + '/roaming',
                    'LOCALAPPDATA': self.temp.name + '/local'}),
                mock.patch.object(ui.core, 'load_settings', return_value={
                    'language': 'zh', 'free_notice_seen': True}),
                mock.patch.object(ui.core, 'discover_game_folders', return_value=[]),
                mock.patch.object(ui.core, 'game_is_running', return_value=False)):
            patch.start(); self.addCleanup(patch.stop)
        self.app = ui.LauncherWindow(tk, ttk, filedialog)
        self.addCleanup(self.app.root.destroy)
        self.addCleanup(self.app.root.update)

    def edges(self, widget):
        return widget.winfo_rootx(), widget.winfo_rootx() + widget.winfo_width()

    def test_main_action_rows_and_internal_section_titles(self):
        a = self.app
        for width in (680, 820):
            a.root.geometry('%dx940' % width)
            for panel, buttons in ((a.save_panel, (a.customize_save_button,
                    a.new_save_slot_button, a.rename_save_slot_button, a.delete_save_slot_button)),
                    (a.vehicle_panel, (a.new_profile_button, a.vehicle_editor_button, a.delete_profile_button)),
                    (a.bot_lineup_panel, (a.new_bot_lineup_profile_button,
                        a.bot_lineup_editor_button, a.delete_bot_lineup_profile_button))):
                a.tools_tabs.select(panel); a.root.update()
                self.assertLessEqual(max(b.winfo_width() for b in buttons) -
                                     min(b.winfo_width() for b in buttons), 1)
                self.assertEqual(self.edges(panel)[0] + 10, self.edges(buttons[0])[0])
                self.assertEqual(self.edges(panel)[1] - 10, self.edges(buttons[-1])[1])
        self.assertGreater(a.game_title.winfo_rooty(), a.game_section.winfo_rooty())
        self.assertEqual('游戏客户端', a.game_title.cget('text'))

    def test_save_tabs_and_reserve_midpoint_gap(self):
        a = self.app
        a.save_dialog.deiconify()
        for width in (670, 820):
            a.save_dialog.geometry('%dx620' % width)
            a.save_tabs.select(a.account_panel); a.root.update()
            self.assertEqual(self.edges(a.save_account_button), self.edges(a.edit_badges_button))
            self.assertGreater(a.edit_badges_button.winfo_y(), a.save_account_button.winfo_y())
            a.save_tabs.select(a.shop_panel); a.root.update()
            self.assertEqual(self.edges(a.gold_vehicle_box), self.edges(a.slots_box))
            self.assertEqual(self.edges(a.buy_gold_vehicle_button), self.edges(a.add_slots_button))
            a.save_tabs.select(a.reserves_panel); a.root.update()
            r = a.reserves_editor
            scroll = next(w for w in a.reserves_panel.winfo_children() if isinstance(w, ttk.Scrollbar))
            self.assertEqual(self.edges(r.tree)[0], self.edges(r.save_button)[0])
            self.assertEqual(self.edges(scroll)[1], self.edges(r.save_button)[1])
            midpoint = sum(self.edges(r.save_button)) / 2
            gap_midpoint = (self.edges(r.quantity_box)[1] + self.edges(r.set_button)[0]) / 2
            self.assertLessEqual(abs(midpoint - gap_midpoint), .5)
            self.assertEqual(6, self.edges(r.set_button)[0] - self.edges(r.quantity_box)[1])
        for panel in (a.account_panel, a.shop_panel, a.personal_missions_panel,
                      a.customizations_panel, a.crew_panel, a.reserves_panel):
            self.assertEqual('Frame', panel.winfo_class())
        self.assertEqual('w', a.crew_editor.feedback.cget('anchor'))

    def test_premium_range_feedback_translates_both_parts_and_accepts_one_day(self):
        a = self.app
        slot = ui.save_slots.create_slot('Layout', ui.save_slots.MODE_NEW_ACCOUNT)
        a._save_slot_id = slot['id']; a._refresh_save_slots()
        a.premium_entry.delete(0, 'end'); a.premium_entry.insert(0, '1000000')
        self.assertFalse(a._apply_account()); a.root.update()
        self.assertEqual('余额保存失败：高级账号天数超出客户端支持范围。',
                         a.save_dialog_feedback.cget('text'))
        for days in (1, 0):
            a.premium_entry.delete(0, 'end'); a.premium_entry.insert(0, str(days))
            self.assertTrue(a._apply_account())
            self.assertEqual(days, ui.save_ledger.premium_days(slot['id']))

    def test_builtin_choices_translate_without_changing_saved_or_runtime_keys(self):
        a = self.app
        original = ui.vehicle_overlays.ORIGINAL_PROFILE_LABEL
        automatic = ui.bot_lineup_profiles.AUTOMATIC_PROFILE_LABEL
        a.vehicle_profile.set(original); a.bot_lineup_profile.set(automatic)
        for language, captions in (('中文', ('原始车辆属性', '自动阵容')),
                                   ('English', (original, automatic)),
                                   ('中文', ('原始车辆属性', '自动阵容'))):
            a.language_choice.set(language); a._language_selected(); a.root.update()
            self.assertEqual(original, a.vehicle_profile.get())
            self.assertEqual(automatic, a.bot_lineup_profile.get())
            self.assertEqual(captions, (a.vehicle_profile_box.get(), a.bot_lineup_profile_box.get()))
            self.assertEqual([], ui.bot_lineup_profiles.runtime_assignments(
                a._bot_lineup_store, a.bot_lineup_profile.get()))
        self.assertEqual('启动局域网房间', a.server_button.cget('text'))

    def test_own_text_dialog_has_localized_equal_readable_buttons(self):
        seen = []
        def accept():
            dialogs = [w for w in self.app.root.winfo_children() if isinstance(w, tk.Toplevel)
                       and w.title() == 'Layout input']
            if not dialogs:
                self.app.root.after(10, accept)
                return
            dialog = dialogs[0]
            widgets = []
            def walk(parent):
                for child in parent.winfo_children():
                    widgets.append(child); walk(child)
            walk(dialog); dialog.update_idletasks()
            buttons = [w for w in widgets if isinstance(w, tk.Button)]
            seen.append(([b.cget('text') for b in buttons],
                         [b.winfo_width() for b in buttons]))
            buttons[0].invoke()
        self.app.root.after(10, accept)
        value = ui.ui_layout.ask_string('Layout input', '方案名称：', parent=self.app.root,
                                       initialvalue='Layout QA', language='zh')
        self.assertEqual('Layout QA', value)
        self.assertEqual(['确定', '取消'], seen[0][0])
        self.assertLessEqual(max(seen[0][1]) - min(seen[0][1]), 1)


if __name__ == '__main__':
    unittest.main()
