"""Actual rendered artillery categories, connection editing and transactions."""
import copy
from itertools import combinations
import os
from pathlib import Path
import unittest
from unittest import mock

import bot_tactics_ui as ui
import bot_tactics_store as storage
import bot_tactics_geometry as geometry
import test_bot_tactics_route_controls as fixture


ROOT=Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'requires Tk display')
class ArtilleryEditorTests(unittest.TestCase):
    setUp=fixture.RouteControlsTests.setUp
    event=fixture.RouteControlsTests.event
    click=fixture.RouteControlsTests.click

    def review(self):
        self.editor.adopt(storage.contract.default_profile('Review test'))
        return self.editor

    def test_route_tree_colors_match_map_palette_in_every_view_and_language(self):
        e=self.review()
        for scope in ('total','all')+storage.contract.CLASSES:
            e.route_class_var.set(scope);e.change_route_class()
            for key in e.items.get_children():
                row=e.items.item(key)
                if 'positions:' in key or (key.startswith('routes:') and e.entry()['routes'][0].get('purpose')=='spg_attack'):
                    tag='artillery';expected=ui.CLASS_COLORS['SPG']
                else:
                    actual=key.rsplit('@',1)[1] if '@' in key else scope
                    tag='route_'+actual;expected=ui.CLASS_COLORS[actual]
                self.assertIn(tag,row['tags'],(scope,key))
                self.assertEqual(expected,str(e.items.tag_configure(tag,'foreground')))
            keys=e.items.get_children()
            if keys:
                e.items.selection_set(keys[0]);e.select_item()
                selection=e.selection;before={k:e.items.item(k,'tags') for k in keys}
                for language in ('en','zh'):
                    e.set_language(language)
                    self.assertEqual(selection,e.selection)
                    self.assertEqual(before,{k:e.items.item(k,'tags') for k in keys})
        e.route_class_var.set('heavyTank');e.change_route_class();e.new_route()
        key=':'.join(e.selection)
        self.assertEqual(('route_heavyTank',),e.items.item(key,'tags'))
        e.route_class_var.set('all');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('routes:'))
        self.assertEqual(('route_all',),e.items.item(key,'tags'))

    def parking(self):
        e=self.editor;e.route_class_var.set('SPG');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin_positions:'))
        e.items.selection_set(key);e.select_item();return e

    def test_all_41_maps_both_teams_render_the_existing_review_data(self):
        e=self.review();before=copy.deepcopy(e.document)
        for name in storage.contract.MAPS:
            e.map_name=name
            for team in (1,2):
                e.team=team;e.team_var.set(str(team));e._load_map()
                e.route_class_var.set('total');e.change_route_class()
                keys=e.items.get_children()
                parking=[key for key in keys if 'positions:' in key]
                attacks=[key for key in keys if key.startswith('routes:')]
                self.assertEqual(3,len(parking),(name,team));self.assertEqual(1,len(attacks),(name,team))
                self.assertLess(max(keys.index(k) for k in parking),keys.index(attacks[0]))
                self.assertNotIn('优先级',e.items.item(attacks[0],'text'))
                for key in parking:self.assertEqual(0,len(e.items.get_children(key)),(name,team,key))
                self.assertTrue(all(e.canvas.itemcget(i,'fill')==ui.CLASS_COLORS['SPG']
                    for i in e.canvas.find_withtag('artillery_attack')))
                self.assertTrue(e.canvas.find_withtag('artillery_attack'))
                e.route_class_var.set('all');e.change_route_class()
                self.assertFalse(any('positions:' in k or k.startswith('routes:') for k in e.items.get_children()))
                self.assertFalse(e.canvas.find_withtag('artillery_attack'))
        self.assertEqual(before,e.document)

    def test_attack_category_fixed_bases_no_priority_tier_wait_or_ordinary_scope(self):
        e=self.editor;e.route_class_var.set('spg_attack');e.change_route_class();e.new_route()
        row=e._selected_parent();g=e.graph_cache[e.map_name]
        self.assertEqual('spg_attack',row['purpose']);self.assertEqual(['SPG'],row['classes'])
        self.assertEqual(g['objective_bases'][0],row['points'][0][:2])
        self.assertEqual(g['objective_bases'][1],row['points'][-1][:2])
        for key in ('route_priority','policy','capacity','weight','slots'):
            self.assertFalse(e.item_fields[key][0].grid_info(),key)
        self.assertFalse(e.classes_frame.grid_info());self.assertFalse(e.wait_panel_section.grid_info())
        self.assertEqual('disabled',str(e.tier_buttons['main'].cget('state')))
        self.assertEqual('disabled',str(e.defense_add.cget('state')))
        before=copy.deepcopy(e.document);e.set_tier('reserve');self.assertEqual(before,e.document)
        e.insert_point();self.assertEqual(3,len(e._selected()['points']))
        e.item_vars['capacity'].set('not a number');self.assertTrue(e.update_properties())
        e.save(True);self.assertFalse(self.errors.called);self.assertEqual(e.document,self.store.active())
        e.duplicate_item();self.assertEqual(2,len(e.entry()['routes']))
        with mock.patch.object(ui.messagebox,'askyesno',return_value=True):e.delete_item()
        self.assertEqual(1,len(e.entry()['routes']))
        e.route_class_var.set('total');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('routes:'))
        e.items.selection_set(key);e.select_item()
        self.assertEqual('normal',str(e.route_delete_button.cget('state')))
        self.assertEqual('disabled',str(e.tier_buttons['main'].cget('state')))

    def test_parking_uses_no_authored_connections_and_stays_editable(self):
        e=self.review();e=self.parking()
        self.assertFalse(hasattr(e,'connect_all_button'));self.assertFalse(hasattr(e,'network_box'))
        self.assertFalse(e.tree_connections)
        e.new_position();row=e._selected_parent()
        self.assertNotIn('travel',row);self.assertNotIn('links',row)
        e.duplicate_item();self.assertNotIn('travel',e._selected_parent())
        e.save(True);self.assertFalse(self.errors.called)
        self.assertTrue(all(not r.get('travel') and not r.get('links') for r in self.store.active()['maps'][e.map_name]['positions']))

    def test_old_parking_connections_are_discarded_without_touching_attack_or_other_geometry(self):
        p=storage.contract.default_profile('Old profile');name='08_ruinberg'
        original=copy.deepcopy(p)
        for zone in p['maps'][name]['positions']:
            zone['travel']=[[999999,999999,0]];zone['links']={'old':'retired invalid input'}
        self.assertEqual(original,storage.contract.canonical(p))
        self.store.save(p,True)
        self.assertEqual(original,self.store.active())

    def test_reading_an_owned_legacy_file_removes_retired_fields_on_disk(self):
        import json
        p=storage.contract.default_profile('Legacy on disk');original=copy.deepcopy(p)
        for zone in p['maps']['08_ruinberg']['positions']:
            zone['travel']=[[0,0,0],zone['point']+[0]];zone['links']={}
        path=self.store.profile_path(p['name']);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(p),encoding='utf8')
        self.assertEqual(original,self.store.read(p['name']))
        self.assertEqual(original,json.loads(path.read_text(encoding='utf8')))

    def test_artillery_attack_cannot_retain_a_legacy_defense_branch(self):
        p=storage.contract.default_profile('Legacy SPG branch');original=copy.deepcopy(p)
        route=next(r for r in p['maps']['08_ruinberg']['routes'] if r.get('purpose')=='spg_attack')
        route['defense']={'retired':'not executable'}
        self.assertEqual(original,storage.contract.canonical(p))
