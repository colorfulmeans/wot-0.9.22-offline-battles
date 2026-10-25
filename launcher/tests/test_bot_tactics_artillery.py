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
        self.editor.adopt(storage.contract.load(str(ROOT/'tools/evidence/route-review-draft-20261025.json')))
        return self.editor

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
                for key in parking:self.assertEqual(3,len(e.items.get_children(key)),(name,team,key))
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
        self.assertFalse(e.classes_frame.grid_info());self.assertFalse(e.wait_panel.grid_info())
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

    def test_connection_child_selection_edits_only_that_path_and_survives_save(self):
        e=self.review();e.route_class_var.set('SPG');e.change_route_class()
        key=next(k for k,value in e.tree_connections.items() if value[1]=='travel')
        e.items.selection_set(key);e.select_item();self.root.update()
        self.assertEqual('travel',e.network_mode)
        original=copy.deepcopy(e._selected_parent()['point']);count=len(e._selected()['points'])
        e.selected_point=0;e.insert_point();self.root.update()
        self.assertEqual('travel',e.network_mode);self.assertEqual(count+1,len(e._selected()['points']))
        self.assertEqual(original,e._selected_parent()['point'])
        e.save(True);self.assertFalse(self.errors.called)
        saved=self.store.active();e.adopt(saved)
        self.assertEqual(saved,e.document)
        self.assertTrue(e.tree_connections)

    def test_separate_panels_and_language_switch_preserve_selected_connection(self):
        e=self.review();e.route_class_var.set('SPG');e.change_route_class()
        key=next(k for k,value in e.tree_connections.items() if value[1]=='link')
        e.items.selection_set(key);e.select_item();self.root.update()
        before=copy.deepcopy(e.document);selection=(e.selection,e.network_mode,e.network_link)
        for language in ('en','zh'):
            e.set_language(language);self.root.update()
            self.assertEqual(selection,(e.selection,e.network_mode,e.network_link))
            self.assertNotEqual(e.defense_panel,e.artillery_panel)
            self.assertNotIn('Defense / SPG',e.artillery_panel.cget('text'))
            self.assertNotIn('（红色）',e.artillery_panel.cget('text'))
            self.assertEqual(e.artillery_panel,e.network_box.master)
        self.assertEqual(before,e.document)

    def test_connect_all_is_once_preserves_links_and_has_single_undo(self):
        e=self.parking();peers=e._parking_items();a,b=peers[:2]
        existing=[a['point']+[0],[20.,20.,0],b['point']+[0]]
        row=copy.deepcopy(a);row['links']={b['id']:existing};e._store_parking(row);e._refresh_items()
        before=copy.deepcopy(e.document);history=len(e.histories['maps'][0])
        e.connect_all_button.invoke();self.root.update()
        self.assertFalse(e.connect_all_var.get());self.assertEqual(history+1,len(e.histories['maps'][0]))
        peers=e._parking_items();a=next(p for p in peers if p['id']==a['id'])
        self.assertEqual(existing,a['links'][b['id']])
        for first,last in combinations(peers,2):
            self.assertTrue(last['id'] in first.get('links',{}) or first['id'] in last.get('links',{}))
        self.assertFalse(any(p['team']==2 for p in e.entry()['positions']))
        after=copy.deepcopy(e.document);e.connect_all_button.invoke()
        self.assertFalse(e.connect_all_var.get());self.assertEqual(after,e.document)
        self.assertEqual(history+1,len(e.histories['maps'][0]))
        e.undo('maps');self.assertEqual(before,e.document);e.redo('maps');self.assertEqual(after,e.document)
        e.new_position();new=e._selected_parent()
        self.assertFalse(new.get('links'))
        self.assertTrue(all(new['id'] not in p.get('links',{}) for p in e._parking_items()))

    def test_connect_failure_rolls_back_all_content_and_history(self):
        e=self.parking();before=copy.deepcopy(e.document);history=copy.deepcopy(e.histories)
        original=e._store_parking;calls=[]
        def fail_second(item):
            calls.append(item)
            if len(calls)==2:raise OSError('fixture write failed')
            original(item)
        with mock.patch.object(e,'_store_parking',side_effect=fail_second):e.connect_all_button.invoke()
        self.assertFalse(e.connect_all_var.get());self.assertEqual(before,e.document);self.assertEqual(history,e.histories)
        self.assertTrue(self.errors.called)

    def test_move_copy_delete_parking_syncs_endpoints_and_drops_stale_references(self):
        self.review();e=self.parking();e.connect_all_positions();zone=e._selected_parent();identity=zone['id']
        e.press(self.event((50.,50.)));e.release(self.event((50.,50.)));zone=e._selected_parent()
        self.assertEqual(zone['point'],zone['travel'][-1][:2])
        for peer in e._parking_items():
            if identity in peer.get('links',{}):self.assertEqual(zone['point'],peer['links'][identity][-1][:2])
        e.duplicate_item();clone=e._selected_parent()
        self.assertNotEqual(identity,clone['id']);self.assertFalse(clone.get('links'))
        self.assertIsNot(zone['travel'],clone['travel'])
        e.selection=('builtin_positions',identity);e._refresh_items()
        with mock.patch.object(ui.messagebox,'askyesno',return_value=True):e.delete_item()
        self.assertTrue(all(identity not in p.get('links',{}) for p in e._parking_items()))
        e.save(True);self.assertFalse(self.errors.called);self.assertEqual(e.document,self.store.active())

    def test_child_delete_does_not_delete_its_parking(self):
        e=self.review();e.route_class_var.set('SPG');e.change_route_class()
        key=next(k for k,v in e.tree_connections.items() if v[1]=='link')
        e.items.selection_set(key);e.select_item();owner,link=e.selection,e.network_link
        e.delete_item();self.assertEqual(owner,e.selection)
        self.assertNotIn(link,e._selected_parent().get('links',{}))
        e.undo('maps');self.assertIn(link,e._selected_parent().get('links',{}))

    def test_default_and_one_parking_refuse_connect_all(self):
        e=self.editor;e.adopt(storage.contract.default_profile());before=copy.deepcopy(e.document)
        e.connect_all_var.set(True);e.connect_all_positions()
        self.assertFalse(e.connect_all_var.get());self.assertEqual(before,e.document)
        e.adopt(storage.contract.empty('Editable again'));e.route_class_var.set('SPG');e.change_route_class()
        e._ensure_entry()['deleted_positions']=[p['id'] for p in e.spg_defaults if p['team']==e.team]
        e.new_position();e._refresh_items()
        self.assertEqual('disabled',str(e.connect_all_button.cget('state')))

    def test_new_parking_has_visible_deployment_child_and_independent_node_editing(self):
        e=self.editor;e.new_position();identity=e._selected_parent()['id']
        key=next(k for k,v in e.tree_connections.items() if v[0]==e.selection and v[1]=='travel')
        e.press(self.event((60.,60.)));e.release(self.event((60.,60.)))
        e.items.selection_set(key);e.select_item();e.selected_point=0;e.insert_point()
        self.assertEqual(identity,e._selected_parent()['id']);self.assertEqual(3,len(e._selected()['points']))
        before=copy.deepcopy(e._selected()['points']);e.selected_point=0
        event=self.event(before[0]);e.press(event);e.motion(self.event((80.,80.)));e.release(event)
        self.assertEqual(before,e._selected()['points'])

    def test_move_materializes_inherited_incoming_links_without_mutating_baseline(self):
        e=self.parking();first,last=e._parking_items()[:2]
        inherited=next(p for p in e.spg_defaults if p['id']==last['id'])
        inherited['links']={first['id']:[last['point']+[0],first['point']+[0]]}
        original=copy.deepcopy(e.spg_defaults)
        self.assertFalse(e.entry()['positions'])
        e.press(self.event((50.,50.)));e.release(self.event((50.,50.)))
        moved=e._selected_parent();peer=next(p for p in e.entry()['positions'] if p['id']==last['id'])
        self.assertEqual(moved['point'],peer['links'][first['id']][-1][:2])
        self.assertEqual(original,e.spg_defaults)

    def test_map_check_locates_attack_in_its_independent_category(self):
        import bot_tactics_inventory as inventory
        import bot_tactics_check_ui as report
        from tkinter import ttk
        e=self.review();row=next(r for r in inventory.inventory(e.document,e.map_name,e.graph_cache[e.map_name],storage.contract) if r['kind']=='sortie')
        row.update(category='correct',issues=[],proofs=[])
        with mock.patch.object(report.inventory,'inspect',return_value=[row]):window=report.show(e)
        try:
            tree=next(w for w in window.winfo_children() if isinstance(w,ttk.Treeview))
            tree.selection_set('row0')
            button=next(w for w in window.winfo_children() if isinstance(w,ttk.Button) and w.cget('text') in ('Locate selection','定位选中项'))
            before=copy.deepcopy(e.document);button.invoke();self.root.update()
            self.assertEqual('spg_attack',e.route_class_var.get())
            self.assertEqual('spg_attack',e._selected_parent()['purpose'])
            self.assertEqual(before,e.document)
        finally:window.destroy()

    def test_total_connection_edit_does_not_retarget_an_overlapping_ordinary_node(self):
        e=self.review();e.route_class_var.set('total');e.change_route_class()
        key=next(k for k,v in e.tree_connections.items() if v[1]=='travel')
        e.items.selection_set(key);e.select_item()
        parent=e._editable_parent();parent['travel']=[parent['travel'][0],[0.,0.,0],parent['travel'][-1]]
        e._refresh_items()
        original=copy.deepcopy(parent['travel'])
        point=e._selected()['points'][1];event=self.event(point)
        ordinary=next(k for k in e.items.get_children() if k.startswith('builtin:'))
        e.route_hit_targets=[(tuple(ordinary.split(':',1)),1,(event.x,event.y))]
        selection=e.selection;roads=copy.deepcopy(e.entry()['default_routes'])
        e.press(event);e.motion(self.event((point[0]+8,point[1]+8)));e.release(event)
        self.assertEqual(selection,e.selection);self.assertEqual('travel',e.network_mode)
        self.assertEqual(roads,e.entry()['default_routes'])
        self.assertNotEqual(original,e._selected()['points'])
