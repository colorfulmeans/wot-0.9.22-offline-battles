"""Real Windows widgets: language changes preserve unsaved editor state."""
import os
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog
import unittest
from unittest import mock
import core
import i18n
import vehicle_editor_ui
import vehicle_armor_viewer
import wot_launcher
from test_vehicle_editor_ui import _Service


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'requires Tk display')
class VehicleEditorLanguageTests(unittest.TestCase):
    def test_editor_edges_and_internal_title_remain_aligned_on_resize(self):
        root = tk.Tk(); root.withdraw()
        def viewer(*args):
            def unavailable(*unused, **kwargs):
                raise vehicle_armor_viewer.ArmorViewerError('fixture')
            return vehicle_armor_viewer.ArmorViewerPanel(*args, scene_loader=unavailable)
        editor = vehicle_editor_ui.VehicleEditorWindow(root, 'fixture', 'Layout',
            tk, ttk, mock.Mock(), service=_Service(), armor_viewer_factory=viewer)
        try:
            for size in ('1320x740', '1480x820'):
                editor.root.geometry(size); root.update()
                right = lambda w: w.winfo_rootx() + w.winfo_width()
                self.assertEqual(right(editor.vehicle_box), right(editor.apply_button))
                self.assertEqual(right(editor.field_box), right(editor.apply_button))
                self.assertEqual(editor.nation_box.winfo_rootx(), editor.category_box.winfo_rootx())
                panel = editor.armor_viewer
                self.assertEqual('Frame', panel.frame.winfo_class())
                self.assertGreater(panel.title_label.winfo_rooty(), panel.frame.winfo_rooty())
                self.assertEqual(editor.nation_box.winfo_rootx() - editor.root.winfo_rootx(),
                    editor.root.winfo_rootx() + editor.root.winfo_width() - right(panel.frame))
        finally:
            editor.root.destroy(); root.destroy()

    def test_main_language_event_relabels_open_windows_without_reloading_or_saving(self):
        service = _Service()
        member = vehicle_editor_ui.DEFAULT_MEMBER
        path = 'turrets0/Test/guns/Gun/burst/count'
        service.extra_fields = [service._field(member, path, 'Gun',
            'Gun / Magazine / Rounds per trigger', False, ('R11_MS-1',))]
        scene_calls = []
        def unavailable(*args, **kwargs):
            scene_calls.append(args)
            raise vehicle_armor_viewer.ArmorViewerError('fixture has no collision model')
        def viewer(*args):
            return vehicle_armor_viewer.ArmorViewerPanel(*args, scene_loader=unavailable)
        def open_editor(parent, game_root, profile_name, **options):
            return vehicle_editor_ui.VehicleEditorWindow(parent, game_root, profile_name,
                tk, ttk, mock.Mock(), service=service, armor_viewer_factory=viewer, **options)
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {'LOCALAPPDATA': temp}), \
             mock.patch.object(core, 'load_settings', return_value={'language': 'en', 'free_notice_seen': True}), \
             mock.patch.object(core, 'discover_game_folders', return_value=[]):
            app = wot_launcher.LauncherWindow(tk, ttk, filedialog)
            try:
                app._profile_names = ['Test']
                app.vehicle_profile.set('Test')
                with mock.patch.object(app, '_refresh_client', return_value={'client': core.PORT_0_9_22, 'path': 'fixture'}), \
                     mock.patch.object(app, '_remember_folder'), \
                     mock.patch.object(vehicle_editor_ui, 'open_vehicle_editor', side_effect=open_editor):
                    self.assertTrue(app._open_vehicle_editor())
                editor = app._vehicle_editors[0]
                editor.select_field_from_viewer((member, path))
                editor.replacement.set('unfinished number')
                editor.replacement_entry.focus_force()
                editor.replacement_entry.icursor(4)
                editor._show_error('Enter one numeric scalar.')
                editor.armor_viewer._yaw, editor.armor_viewer._zoom = .4, 1.7
                before = list(service.inspect_calls), list(service.apply_calls), list(scene_calls)
                for choice, language in (('中文', 'zh'), ('English', 'en'), ('Auto / 自动', 'zh')):
                    with mock.patch.object(i18n, 'detect_system_language', return_value='zh'):
                        app.language_choice.set(choice)
                        app._language_selected()
                        app.root.update()
                    self.assertEqual(language, editor._language)
                    self.assertEqual(language, editor.armor_viewer._language)
                    self.assertEqual('unfinished number', editor.replacement.get())
                    self.assertEqual(4, editor.replacement_entry.index('insert'))
                    self.assertEqual((member, path), editor._selection())
                    self.assertEqual((.4, 1.7), (editor.armor_viewer._yaw, editor.armor_viewer._zoom))
                    self.assertEqual(before, (service.inspect_calls, service.apply_calls, scene_calls))
                    if language == 'zh':
                        self.assertIn('请输入一个数值', editor.status.get())
                        self.assertIn('每扳机发射炮弹', editor.field.get())
                        self.assertEqual('3D 装甲检视', editor.armor_viewer.title_label.cget('text'))
                editor.root.destroy()
                app.language_choice.set('English')
                app._language_selected()
                self.assertEqual([], app._vehicle_editors)
            finally:
                app.root.destroy()


if __name__ == '__main__':
    unittest.main()
