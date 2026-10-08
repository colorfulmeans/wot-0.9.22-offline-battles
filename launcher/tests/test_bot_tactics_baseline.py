"""The adopted tactics are the actual first-run and restoration baseline."""
import copy
import json
import os
import tempfile
import tkinter as tk
import unittest
from unittest import mock

import bot_tactics_store as storage
import bot_tactics_ui as ui
import bot_tactics_labels as labels


class BaselineDataTests(unittest.TestCase):
    def test_complete_canonical_baseline_returns_independent_documents(self):
        a=storage.contract.default_profile()
        self.assertEqual(41,len(a['maps']))
        self.assertEqual(a,storage.contract.canonical(a))
        a['maps'].clear()
        self.assertEqual(41,len(storage.contract.default_profile()['maps']))

    def test_fresh_store_adopts_baseline_but_existing_profiles_are_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            store=storage.Store(temp)
            self.assertEqual(storage.contract.default_profile(),store.active())
            explicit=storage.contract.empty('Independent')
            store.save(explicit,apply=True)
            self.assertEqual(explicit,storage.Store(temp).active())

    def test_baseline_parking_deletion_includes_authored_identity(self):
        p=storage.contract.default_profile();name='08_ruinberg'
        zone=next(z for z in p['maps'][name]['positions'] if z['id'].startswith('p_'))
        p['maps'][name]['deleted_positions'].append(zone['id'])
        p=storage.contract.canonical(p)
        shown=storage.default_spg_positions(name,storage.graph_data(name),p)
        self.assertNotIn(zone['id'],[z['id'] for z in shown])
        self.assertTrue(any(z['team']!=zone['team'] for z in shown))

    def test_every_explicit_baseline_name_has_both_display_languages(self):
        for entry in storage.contract.default_profile()['maps'].values():
            for kind in ('routes','default_routes','positions'):
                for row in entry.get(kind,[]):
                    if 'label' not in row:continue
                    self.assertTrue(any(ord(c)>127 for c in labels.tactic_name(row['label'],'zh')))
                    self.assertTrue(all(ord(c)<128 for c in labels.tactic_name(row['label'],'en')))


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'requires Tk display')
class BaselineEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        patch=mock.patch.object(ui.messagebox,'showerror')
        self.errors=patch.start();self.addCleanup(patch.stop)
        self.editor=ui.BotTacticsEditor(self.root,store=storage.Store(self.temp.name))
        self.editor.map_var.set(storage.MAP_LABELS['29_el_hallouf']);self.editor.change_map()
        self.editor.route_class_var.set('AT-SPG');self.editor.change_route_class()

    def test_class_reset_restores_exact_geometry_waits_priorities_and_save(self):
        e=self.editor
        original=next(r for r in storage.contract.default_map(e.map_name)['default_routes']
            if r['team']==e.team and r.get('class_tag')=='AT-SPG' and not r.get('disabled'))
        e.selection=('builtin',original['id']);e._refresh_properties()
        item=e._editable_item();item['points'][1][0]+=7;item['priority']=9
        for point in item['points']:
            if len(point)>4:point[4][0][2]=3
        e.reset_builtin()
        self.assertEqual(original,e._editable_item())
        e.save(True)
        actual=next(r for r in e.store.active()['maps'][e.map_name]['default_routes']
            if r['team']==e.team and r['id']==original['id'] and r.get('class_tag')=='AT-SPG')
        self.assertEqual(original,actual)
        self.errors.assert_not_called()

    def test_parking_reset_restores_authored_default_instead_of_community_anchor(self):
        e=self.editor;e.route_class_var.set('SPG');e.change_route_class()
        original=next(z for z in storage.contract.default_map(e.map_name)['positions'] if z['team']==e.team)
        e.selection=('builtin_positions',original['id']);e._refresh_properties()
        e._editable_item()['point'][0]+=9
        e.reset_builtin()
        self.assertEqual(original,e._selected())
        e.save(True);self.errors.assert_not_called()

    def test_whole_default_restore_and_new_profile_use_adopted_baseline(self):
        e=self.editor;e.document['maps'].clear()
        with mock.patch.object(e,'discard_prompt',return_value=True):e.default_profile()
        self.assertEqual(storage.contract.default_profile(),e.document)
        with mock.patch.object(e,'discard_prompt',return_value=True):e.new_profile()
        self.assertEqual(storage.contract.default_profile()['maps'],e.document['maps'])
        e.set_language('en');self.root.update()
        self.assertTrue(all(ord(c)<128 for i in e.items.get_children() for c in e.items.item(i,'text')))
