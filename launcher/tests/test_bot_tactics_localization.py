"""Catalog coverage and real bilingual UI tests. No mutation of runtime IDs."""
import copy
import json
import os
from pathlib import Path
import re
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog
import unittest
from unittest import mock

import bot_tactics_labels as labels
import bot_tactics_store as storage
import bot_tactics_ui as ui_module
import i18n

ROOT = Path(__file__).resolve().parents[2]


class CatalogTests(unittest.TestCase):
    def test_all_41_maps_have_full_unique_names_in_both_languages(self):
        self.assertEqual(set(storage.contract.MAPS), set(labels.MAP_NAMES))
        self.assertEqual(41, len(labels.MAP_NAMES))
        for lang in ('zh', 'en'):
            names = list(storage.map_labels(lang).values())
            self.assertEqual(41, len(set(names)))
            self.assertTrue(all('/' not in n and not re.match(r'^\d+_', n) for n in names))
            self.assertNotIn('锡城', names)
        self.assertEqual('锡莫尔斯多夫', labels.map_label('04_himmelsdorf', 'zh'))
        self.assertEqual('锡莫尔斯多夫（冬季）', labels.map_label('86_himmelsdorf_winter', 'zh'))
        self.assertEqual('Himmelsdorf', labels.map_label('04_himmelsdorf', 'en'))

    def test_internal_ids_are_not_mistaken_for_actual_map_names(self):
        self.assertEqual('Live Oaks', labels.map_label('44_north_america', 'en'))
        self.assertEqual('Highway', labels.map_label('45_north_america', 'en'))
        self.assertEqual('Paris', labels.map_label('112_eiffel_tower_ctf', 'en'))
        self.assertEqual('Arctic Region', labels.map_label('38_mannerheim_line', 'en'))
        self.assertEqual('Kharkov', labels.map_label('83_kharkiv', 'en'))
        self.assertEqual('布拉格', labels.map_label('114_czech', 'zh'))
        self.assertEqual('荒蛮之地', labels.map_label('35_steppes', 'zh'))

    def test_all_96_shipped_route_ids_are_covered(self):
        identifiers = set()
        for name in storage.contract.MAPS:
            for routes in storage.graph_data(name)['routes'].values():
                identifiers.update(route['id'] for route in routes)
        self.assertEqual(96, len(identifiers))
        self.assertEqual(identifiers, set(labels.ROUTE_NAMES))
        for name in identifiers:
            self.assertRegex(labels.route_label(name, 'zh'), r'[\u4e00-\u9fff]')
            self.assertNotIn('_', labels.route_label(name, 'en'))
        self.assertEqual(('瀑布', '高地', '村庄'), tuple(labels.route_label(k, 'zh') for k in ('waterfall','plateau','village')))

    def test_all_dropdown_values_have_unique_bilingual_captions(self):
        for kind, codes in [('skill', ('',) + storage.contract.SKILLS),
                            ('class_tag', ('all',) + storage.contract.CLASSES),
                            ('policy', ('preferred','fixed'))]:
            for lang in ('zh','en'):
                captions = [labels.enum_label(kind, code, lang) for code in codes]
                self.assertEqual(len(codes),len(set(captions)))
                if lang == 'zh':
                    self.assertTrue(all(re.search(r'[\u4e00-\u9fff]', c) for c in captions))


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'requires actual Tk display')
class LocaleUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.error_mock = mock.patch.object(ui_module.messagebox, 'showerror').start()
        self.addCleanup(mock.patch.stopall)
        self.ui = ui_module.BotTacticsEditor(self.root, store=storage.Store(self.temp.name), language='zh')
        self.root.update()

    def select_code(self, kind, code):
        box = self.ui.rule_boxes[kind]
        box.current(box.codes.index(code));self.root.update()
        self.assertEqual(code, self.ui.rule_vars[kind].get())

    def test_chinese_controls_show_captions_not_internal_values(self):
        self.assertEqual(('继承','新手','普通','老兵','精英'), tuple(self.ui.rule_boxes['skill']['values']))
        self.assertEqual('全部车型', self.ui.rule_boxes['class_tag'].get())
        for kind, code in [('class_tag','SPG'),('skill','veteran'),('team','2')]:
            self.select_code(kind,code)
        self.assertEqual('自行火炮', self.ui.rule_boxes['class_tag'].get())
        self.assertEqual('老兵', self.ui.rule_boxes['skill'].get())
        self.ui.save_rule();self.ui.save(True)
        actual = self.ui.store.active()['behavior'][0]
        self.assertEqual('SPG', actual['class_tag']);self.assertEqual('veteran',actual['values']['skill'])
        self.assertFalse(self.error_mock.called, self.error_mock.call_args)
        self.assertIn('老兵',self.ui.rules.item('0','values')[-1])
        self.assertNotIn('class_tag',str(self.ui.rules.item('0','values')))

    def test_switch_keeps_unsaved_document_form_view_selection_and_history(self):
        self.ui.new_position();self.root.update()
        self.ui.item_vars['label'].set('Custom English 用户名称')
        self.ui.item_vars['radius'].set('invalid draft 31.')
        self.ui.rule_vars['skill'].set('veteran');self.ui.rule_vars['reaction_seconds'].set('2.')
        self.ui.view.zoom = 1.7;self.ui.view.pan_x = 15
        before = copy.deepcopy(self.ui.document)
        active = self.ui.store.active_path.read_bytes()
        form = {k:v.get() for k,v in self.ui.item_vars.items()}
        rules = {k:v.get() for k,v in self.ui.rule_vars.items()}
        selected = self.ui.selection;history = copy.deepcopy(self.ui.undo_stack)
        for language in ('en','zh','en','zh'):
            self.ui.set_language(language);self.root.update()
            self.assertEqual(before, self.ui.document)
            self.assertEqual(active, self.ui.store.active_path.read_bytes())
            self.assertEqual(form,{k:v.get() for k,v in self.ui.item_vars.items()})
            self.assertEqual(rules,{k:v.get() for k,v in self.ui.rule_vars.items()})
            self.assertEqual(selected,self.ui.selection);self.assertEqual(history,self.ui.undo_stack)
            self.assertEqual((1.7,15),(self.ui.view.zoom,self.ui.view.pan_x))
        self.assertEqual('老兵',self.ui.rule_boxes['skill'].get())
        self.assertFalse(self.error_mock.called)

    def test_switch_keeps_clean_profile_and_does_not_change_digest(self):
        self.select_code('class_tag','heavyTank');self.select_code('skill','elite')
        self.ui.save_rule();self.ui.save(True);self.root.update()
        before = storage.contract.digest(self.ui.document)
        self.assertFalse(self.ui.dirty())
        self.ui.set_language('en');self.root.update()
        self.assertEqual('Elite',self.ui.rule_boxes['skill'].get())
        self.assertEqual('Heavy tank',self.ui.rule_boxes['class_tag'].get())
        self.assertEqual(before,storage.contract.digest(self.ui.document));self.assertFalse(self.ui.dirty())

    def test_map_and_builtin_captions_change_without_reloading_the_map(self):
        self.ui.map_var.set(labels.map_label('63_tundra','zh'));self.ui.change_map();self.root.update()
        graph = self.ui.graph_cache['63_tundra']
        selected_id = next(row for row in self.ui.items.get_children() if row.startswith('builtin:'))
        self.ui.items.selection_set(selected_id);self.root.update()
        self.ui.set_language('en');self.root.update()
        self.assertEqual('Tundra',self.ui.map_var.get());self.assertEqual('63_tundra',self.ui.map_name)
        self.assertIs(graph,self.ui.graph_cache['63_tundra'])
        self.assertEqual(selected_id,':'.join(self.ui.selection))
        self.assertTrue(self.ui.items.item(selected_id,'text').startswith('[Built-in] '))
        self.ui.set_language('zh');self.root.update()
        self.assertEqual('喀秋莎',self.ui.map_var.get())
        self.assertTrue(self.ui.items.item(selected_id,'text').startswith('[内置] '))
        self.assertIn('导航栅格',self.ui.map_status.cget('text'))

    def test_localized_route_policy_is_saved_as_canonical_enum(self):
        self.ui.new_route();self.root.update()
        self.ui._selected()['points'] = [[-66,306,0],[-126,246,0]]
        box = self.ui.item_fields['policy'][1]
        self.assertEqual('优先路线', box.get())
        box.current(1);self.root.update();self.assertEqual('fixed',self.ui.item_vars['policy'].get())
        self.ui.save(True)
        self.assertEqual('fixed',self.ui.store.active()['maps']['08_ruinberg']['routes'][0]['policy'])
        self.ui.set_language('en');self.root.update();self.assertEqual('Fixed route',box.get())
        self.assertFalse(self.error_mock.called,self.error_mock.call_args)

    def test_localized_copy_title_does_not_rename_original_or_user_titles(self):
        graph = copy.deepcopy(self.ui.graph_cache[self.ui.map_name])
        rid = graph['routes']['1'][0]['id']
        self.ui.items.selection_set('builtin:'+rid);self.root.update();self.ui.duplicate_item();self.root.update()
        self.assertEqual(labels.route_label(rid,'zh')+' 副本',self.ui._selected()['label'])
        self.assertEqual(graph,self.ui.graph_cache[self.ui.map_name])
        name = self.ui._selected()['label'];self.ui.set_language('en');self.root.update()
        self.assertEqual(name,self.ui._selected()['label'])

    def test_preview_uses_localized_names_without_changing_values(self):
        self.ui.rule_vars['class_tag'].set('SPG')
        with mock.patch.object(ui_module.messagebox,'showinfo') as show:
            self.ui.preview_rule()
        value = show.call_args.args[1]
        self.assertIn('自行火炮',value);self.assertIn('反应时间',value)
        self.assertNotIn('reaction_seconds',value);self.assertNotIn('regular',value)

    def test_auto_language_uses_same_resolver_as_launcher(self):
        with mock.patch.object(i18n,'detect_system_language',return_value='en'):
            self.ui.set_language('auto')
        self.assertEqual('Ruinberg',self.ui.map_var.get())
        with mock.patch.object(i18n,'detect_system_language',return_value='zh'):
            self.ui.set_language('auto')
        self.assertEqual('鲁别克',self.ui.map_var.get())


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'requires actual Tk display')
class MainLanguageTests(unittest.TestCase):
    def test_real_main_language_event_updates_two_open_editors_and_new_windows(self):
        import core,wot_launcher
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict(os.environ,{'LOCALAPPDATA':tmp}),\
             mock.patch.object(core,'load_settings',return_value={'language':'zh','free_notice_seen':True}),\
             mock.patch.object(core,'discover_game_folders',return_value=[]),\
             mock.patch.object(ui_module.messagebox,'showerror') as errors:
            app=wot_launcher.LauncherWindow(tk,ttk,filedialog)
            try:
                app.root.update()
                for _ in range(2):
                    app.bot_tactics_button.invoke();app.root.update()
                editors=app._bot_tactics_editors[:]
                self.assertEqual(2,len(editors))
                editors[0].new_position();app.root.update();editors[0].item_vars['radius'].set('draft.')
                before=copy.deepcopy(editors[0].document)
                app.language_choice.set('English')
                app.language_box.event_generate('<<ComboboxSelected>>');app.root.update()
                for editor in editors:self.assertEqual('Ruinberg',editor.map_var.get())
                self.assertEqual(before,editors[0].document)
                self.assertEqual('draft.',editors[0].item_vars['radius'].get())
                editors[1].root.destroy()
                app.language_choice.set('中文');app.language_box.event_generate('<<ComboboxSelected>>');app.root.update()
                self.assertEqual(1,len(app._bot_tactics_editors))
                self.assertEqual('鲁别克',editors[0].map_var.get())
                with mock.patch.object(i18n,'detect_system_language',return_value='en'):
                    app.language_choice.set('Auto / 自动');app.language_box.event_generate('<<ComboboxSelected>>');app.root.update()
                app.bot_tactics_button.invoke();app.root.update()
                self.assertTrue(all(ed.language=='en' for ed in app._bot_tactics_editors))
                self.assertFalse(errors.called,errors.call_args)
            finally:app.root.destroy()

if __name__=='__main__':unittest.main()
