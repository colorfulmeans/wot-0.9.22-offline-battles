"""Real Tk event/storage tests (Windows desktop or Linux DISPLAY required)."""
import copy
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog
import unittest
from unittest import mock

import bot_tactics_ui as ui_module
import bot_tactics_store as storage


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'requires actual Tk display')
class EditorUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.errors=mock.patch.object(ui_module.messagebox,'showerror');self.error_mock=self.errors.start();self.addCleanup(self.errors.stop)
        self.ui=ui_module.BotTacticsEditor(self.root,store=storage.Store(self.temp.name))
        self.initial_defaults=(self.ui.route_class_var.get(),self.ui.symmetry_var.get())
        self.initial_map=(self.ui.map_name,self.ui.map_var.get(),self.ui.map_box.cget('values')[0])
        self.ui.map_var.set(storage.MAP_LABELS['08_ruinberg']);self.ui.change_map()
        self.ui.route_class_var.set('heavyTank');self.ui.change_route_class();self.ui.symmetry_var.set(False)
        self.ui.book.select(1);self.root.update()

    def click(self,point,shift=False):
        x,y=self.ui.view.screen(point)
        self.ui.canvas.event_generate('<ButtonPress-1>',x=int(x),y=int(y),state=1 if shift else 0)
        self.ui.canvas.event_generate('<ButtonRelease-1>',x=int(x),y=int(y));self.root.update()

    def test_wait_panel_three_places_individual_times_delete_and_collapse(self):
        self.ui.new_route();self.click((-66,306));self.click((-126,246))
        self.ui.selected_point=0;self.ui.edit_point_condition()
        self.assertTrue(self.ui.wait_edit)
        self.assertLess(int(self.ui.point_actions.grid_info()['row']),int(self.ui.wait_panel.grid_info()['row']))
        self.assertLess(int(self.ui.wait_panel.grid_info()['row']),int(self.ui.node_legend.grid_info()['row']))
        for point,seconds in [((-66,306),10),((-46,306),20),((-26,306),30)]:
            self.click(point);self.ui.wait_seconds.set(str(seconds));self.ui.update_wait_time()
        self.assertEqual([10,20,30],[p[2] for p in self.ui._wait_point()[4]])
        before=copy.deepcopy(self.ui.document);self.click((-6,306))
        self.assertTrue(self.error_mock.called);self.assertEqual(before,self.ui.document)
        self.assertEqual(3,len(self.ui.canvas.find_withtag('wait_place')))
        self.ui.wait_edit_var.set(False);self.ui.change_wait_edit()
        self.ui.selected_point=None;self.ui.redraw()
        self.assertEqual(0,len(self.ui.canvas.find_withtag('wait_place')))
        self.assertEqual(1,len(self.ui.canvas.find_withtag('route_wait')))
        self.ui.selected_point=0;self.ui.edit_point_condition()
        self.ui.selected_wait=1;self.ui.delete_selected_point()
        self.assertEqual([10,30],[p[2] for p in self.ui._wait_point()[4]])
        self.assertEqual(2,len(self.ui._selected()['points']))
        self.ui.selected_wait=0;self.ui.delete_wait_point()
        self.ui.selected_wait=0;self.ui.delete_wait_point()
        self.assertEqual(3,len(self.ui._wait_point()))
        self.ui.undo();self.ui.selected_point=0;self.assertEqual(1,len(self.ui._wait_point()[4]))
        storage.contract.canonical(self.ui.document)

    def test_opening_does_not_create_dirty_or_active_map_entries(self):
        self.assertFalse(self.ui.dirty());self.assertEqual({},self.ui.store.active()['maps'])
        self.assertEqual(41,len(self.ui.map_labels));self.assertTrue(self.ui.graph_cache['08_ruinberg'])

    def test_symmetry_is_visible_beside_base_coordinates_before_route_selection(self):
        self.assertEqual(self.ui.base_label.master,self.ui.symmetry_check.master)
        self.assertTrue(self.ui.symmetry_check.winfo_ismapped())
        self.assertGreater(self.ui.symmetry_check.winfo_x(),self.ui.base_label.winfo_x())

    def test_initial_defaults_show_total_routes_with_symmetry_enabled(self):
        self.assertEqual(('total',True),self.initial_defaults)
        self.assertEqual(('33_fjord','北欧峡湾','北欧峡湾'),self.initial_map)

    def test_base_snap_is_between_coordinates_and_symmetry_and_resets_on_noop(self):
        self.assertEqual('路线首尾移至出生点中心',self.ui.base_snap_check.cget('text'))
        self.assertEqual(self.ui.base_label.master,self.ui.base_snap_check.master)
        self.assertLess(self.ui.base_label.winfo_x(),self.ui.base_snap_check.winfo_x())
        self.assertLess(self.ui.base_snap_check.winfo_x(),self.ui.symmetry_check.winfo_x())
        before=copy.deepcopy(self.ui.document)
        self.ui.base_snap_check.invoke()
        self.assertFalse(self.ui.base_snap_var.get());self.assertEqual(before,self.ui.document)
        self.ui.new_route();self.root.update();before=copy.deepcopy(self.ui.document)
        self.ui.base_snap_check.invoke()
        self.assertFalse(self.ui.base_snap_var.get());self.assertEqual(before,self.ui.document)
        self.ui.new_position();self.root.update();before=copy.deepcopy(self.ui.document)
        self.ui.base_snap_check.invoke()
        self.assertFalse(self.ui.base_snap_var.get());self.assertEqual(before,self.ui.document)

    def test_all_map_base_markers_and_snapped_endpoints_use_validated_spawn_centres(self):
        for name in storage.contract.MAPS:
            with self.subTest(map=name):
                self.ui.map_var.set(storage.MAP_LABELS[name]);self.ui.change_map()
                bases=self.ui.graph_cache[name]['spawn_anchors']
                self.assertEqual(2,len(self.ui.canvas.find_withtag('spawn_anchor')))
                self.assertEqual(2,len(self.ui.canvas.find_withtag('capture_base')))
                for team,centre in enumerate(bases,1):
                    box=self.ui.canvas.coords('spawn_anchor_'+str(team))
                    marker=((min(box[::2])+max(box[::2]))/2,(min(box[1::2])+max(box[1::2]))/2)
                    expected=self.ui.view.screen(centre)
                    self.assertAlmostEqual(expected[0],marker[0])
                    self.assertAlmostEqual(expected[1],marker[1])
                    graph=self.ui.graph_cache[name]
                    capture=self.ui.canvas.coords('capture_base_'+str(team))
                    expected_capture=self.ui.view.screen(graph['objective_bases'][team-1])
                    self.assertAlmostEqual(expected_capture[0],(capture[0]+capture[2])/2)
                    self.assertAlmostEqual(expected_capture[1],(capture[1]+capture[3])/2)
                    self.assertAlmostEqual(graph['objective_base_radii'][team-1]*self.ui.view.frame()[2],(capture[2]-capture[0])/2)
                self.ui.new_route();item=self.ui._editable_item()
                item['symmetric']=False;item['points']=[[0,0,0],[1,1,0]]
                self.ui.base_snap_check.invoke()
                self.assertEqual(bases[self.ui.team-1],item['points'][0][:2])
                self.assertEqual(bases[2-self.ui.team],item['points'][-1][:2])

    def test_separate_spawn_maps_disable_symmetry_and_never_copy_the_other_team(self):
        disabled=[]
        for name in storage.contract.MAPS:
            self.ui.map_var.set(storage.MAP_LABELS[name]);self.ui.change_map()
            if not self.ui._supports_route_symmetry():disabled.append(name)
        self.assertEqual(['100_thepit','63_tundra','95_lost_city'],sorted(disabled))
        for name in disabled:
            self.ui.map_var.set(storage.MAP_LABELS[name]);self.ui.change_map()
            self.ui.new_route();item=self.ui._editable_item()
            self.assertTrue(self.ui.symmetry_check.instate(['disabled']))
            self.assertFalse(self.ui.symmetry_var.get())
            item['points']=[[0,0,0],[1,1,0]];item['symmetric']=True
            self.ui.base_snap_check.invoke()
            self.assertFalse(item['symmetric'])
            self.assertFalse(any(r['team']!=self.ui.team for r in self.ui.entry()['routes']))
            before=copy.deepcopy(self.ui.document)
            self.ui.symmetry_var.set(True);self.ui.change_symmetry()
            self.assertFalse(self.ui.symmetry_var.get());self.assertEqual(before,self.ui.document)

    def test_base_snap_default_uses_spawn_centres_preserves_waits_and_undo(self):
        source=self.ui.graph_cache['08_ruinberg']['routes']['1'][0]
        self.ui.items.selection_set('builtin:'+source['id']);self.root.update()
        item=self.ui._editable_item();item['points'][0][3:]=[12.0]
        item['points'][-1][3:]=[-1.0];before=copy.deepcopy(self.ui.document)
        old=copy.deepcopy(item['points']);self.ui.base_snap_check.invoke()
        points=self.ui._selected()['points'];bases=self.ui.graph_cache['08_ruinberg']['spawn_anchors']
        self.assertEqual(bases[0],points[0][:2]);self.assertEqual(bases[1],points[-1][:2])
        self.assertEqual(old[1:-1],points[1:-1]);self.assertEqual(old[0][2:],points[0][2:])
        self.assertEqual(old[-1][2:],points[-1][2:]);self.assertFalse(self.ui.base_snap_var.get())
        self.assertIn(str(bases[0]),self.ui.base_label.cget('text'))
        self.ui.undo();self.assertEqual(before,self.ui.document)

    def test_base_snap_team_two_single_point_and_repeat_click(self):
        self.ui.team_var.set('2');self.ui.change_map();self.ui.new_route();self.root.update()
        item=self.ui._editable_item();item['symmetric']=False;item['points']=[[0.0,0.0,0,7.0]]
        self.ui.base_snap_check.invoke();bases=self.ui.graph_cache['08_ruinberg']['spawn_anchors']
        self.assertEqual([bases[1]+[0,7.0]],item['points'])
        item['points'].append([100.0,100.0,0]);self.ui.base_snap_check.invoke()
        self.assertEqual(bases[0],item['points'][-1][:2]);self.assertFalse(self.ui.base_snap_var.get())

    def test_base_snap_total_class_respects_symmetry_and_saved_geometry(self):
        self.ui.route_class_var.set('total');self.ui.change_route_class()
        identity=next(i for i in self.ui.items.get_children() if i.startswith('builtin:') and i.endswith('@heavyTank'))
        self.ui.items.selection_set(identity);self.root.update()
        self.ui._editable_item()['points'][0][0]+=10.0
        self.ui.base_snap_check.invoke();edits=self.ui.entry()['default_routes']
        own=next(r for r in edits if r['team']==1);peer=next(r for r in edits if r['team']==2)
        self.assertEqual('heavyTank',own['class_tag'])
        self.assertEqual(list(reversed(own['points'])),peer['points'])
        self.assertTrue(all(r['class_tag']=='heavyTank' for r in edits))
        self.ui.profile_name.set('Base endpoints');self.ui.save(True)
        saved=self.ui.store.active()['maps']['08_ruinberg']['default_routes']
        expected=storage.contract.canonical(self.ui.document)['maps']['08_ruinberg']['default_routes']
        self.assertEqual(expected,saved)

    def test_spg_defaults_only_allow_repositioning_parking(self):
        self.ui.map_var.set(storage.MAP_LABELS['31_airfield']);self.ui.change_map()
        self.ui.route_class_var.set('SPG');self.ui.change_route_class();self.root.update()
        ids=self.ui.items.get_children()
        self.assertTrue(ids);self.assertTrue(all(i.startswith('builtin_positions:') for i in ids))
        self.assertFalse(self.ui.dirty())
        self.ui.items.selection_set(ids[0]);self.root.update()
        self.assertFalse(self.ui.point_actions.winfo_ismapped())
        first=self.ui._selected()['point'];x,y=self.ui.view.screen(first)
        self.click(self.ui.view.world(x-30,y),shift=True)
        self.assertNotEqual(first,self.ui._selected()['point'])
        self.assertNotIn('points',self.ui._selected())
        with mock.patch.object(ui_module.simpledialog,'askfloat') as ask:
            self.ui.edit_point_condition();ask.assert_not_called()
        self.ui.save(True);self.assertFalse(self.error_mock.called,self.error_mock.call_args)
        self.assertNotIn('points',self.ui.store.active()['maps']['31_airfield']['positions'][0])
        self.ui.reset_builtin();self.assertFalse(self.ui.entry()['positions'])
        self.ui.new_route();self.assertEqual('positions',self.ui.selection[0])

    def test_default_symmetry_reverses_geometry_waits_and_detaches_when_disabled(self):
        source=self.ui.graph_cache['08_ruinberg']['routes']['1'][0]
        self.ui.items.selection_set('builtin:'+source['id']);self.root.update()
        self.ui.symmetry_var.set(True);self.ui.change_symmetry()
        self.ui.selected_point=1
        self.ui.edit_point_condition()
        self.click(self.ui._selected()['points'][1][:2])
        self.ui.wait_seconds.set('12.5');self.ui.update_wait_time()
        entries=self.ui.entry()['default_routes']
        own=next(r for r in entries if r['team']==1)
        peer=next(r for r in entries if r['team']==2)
        self.assertEqual(list(reversed(own['points'])),peer['points'])
        self.assertEqual(12.5,own['points'][1][4][0][2])
        self.assertEqual('heavyTank',peer['class_tag'])
        self.ui.symmetry_var.set(False);self.ui.change_symmetry()
        original=copy.deepcopy(peer['points'])
        self.ui.delete_point()
        self.assertEqual(original,peer['points'])
        self.ui.undo();self.assertEqual(12.5,self.ui._selected()['points'][1][4][0][2])
        self.assertFalse(self.error_mock.called)

    def test_class_default_edit_does_not_replace_other_class_geometry(self):
        source=self.ui.graph_cache['08_ruinberg']['routes']['1'][0]
        self.ui.items.selection_set('builtin:'+source['id']);self.root.update()
        self.ui.selected_point=1;self.ui.delete_point()
        changed=copy.deepcopy(self.ui._selected()['points'])
        self.ui.route_class_var.set('mediumTank');self.ui.change_route_class()
        self.ui.items.selection_set('builtin:'+source['id']);self.root.update()
        self.assertEqual(source['waypoints'],self.ui._selected()['points'])
        self.ui.route_class_var.set('heavyTank');self.ui.change_route_class()
        self.ui.items.selection_set('builtin:'+source['id']);self.root.update()
        self.assertEqual(changed,self.ui._selected()['points'])
        colors=[self.ui.canvas.itemcget(i,'fill') for i in self.ui.canvas.find_all()
                if self.ui.canvas.type(i)=='line']
        self.assertIn(ui_module.CLASS_COLORS['heavyTank'],colors)

    def test_custom_symmetry_updates_from_other_side_and_copy_is_independent(self):
        self.ui.new_route();self.click((-66,306));self.click((-126,246))
        self.ui.symmetry_var.set(True);self.ui.change_symmetry()
        own=self.ui._selected();peer=next(r for r in self.ui.entry()['routes'] if r['id']==own['mirror_id'])
        self.assertEqual(list(reversed(own['points'])),peer['points'])
        self.ui.team=2;self.ui._refresh_items()
        self.ui.items.selection_set('routes:'+peer['id']);self.root.update()
        self.ui.selected_point=0
        self.ui.edit_point_condition();self.click(self.ui._selected()['points'][0][:2])
        self.ui.wait_seconds.set('-1');self.ui.update_wait_time()
        self.assertEqual(-1,own['points'][-1][4][0][2])
        self.ui.duplicate_item()
        self.assertNotIn('mirror_id',self.ui._selected())
        self.assertNotIn('symmetric',self.ui._selected())
        storage.contract.canonical(self.ui.document)

    def test_builtin_drag_insert_delete_undo_save_reopen_and_reset(self):
        graph=copy.deepcopy(self.ui.graph_cache['08_ruinberg'])
        source=graph['routes']['1'][0]
        self.ui.items.selection_set('builtin:'+source['id']);self.root.update()
        self.assertEqual(('builtin',source['id']),self.ui.selection)
        self.assertFalse(self.ui.dirty());self.assertEqual({},self.ui.document['maps'])
        original=copy.deepcopy(self.ui._selected()['points'])
        self.ui.selected_point=1;self.ui.delete_point()
        self.assertEqual(len(original)-1,len(self.ui._selected()['points']))
        self.ui.undo();self.assertEqual(original,self.ui._selected()['points']);self.ui.redo()
        first=self.ui._selected()['points'][0];start=self.ui.view.screen(first)
        end=self.ui.view.screen((first[0]+8,first[1]-8))
        self.ui.canvas.event_generate('<ButtonPress-1>',x=int(start[0]),y=int(start[1]))
        self.ui.canvas.event_generate('<B1-Motion>',x=int(end[0]),y=int(end[1]))
        self.ui.canvas.event_generate('<ButtonRelease-1>',x=int(end[0]),y=int(end[1]));self.root.update()
        self.assertNotEqual(original[0][:2],self.ui._selected()['points'][0][:2])
        self.ui.selected_point=0;self.click(original[1],shift=True)
        self.assertEqual(len(original),len(self.ui._selected()['points']))
        self.ui.profile_name.set('Default adjustments');self.ui.save(True);self.root.update()
        self.assertFalse(self.error_mock.called,self.error_mock.call_args)
        saved=self.ui.store.active();entry=saved['maps']['08_ruinberg']
        self.assertEqual([],entry['routes']);self.assertEqual(2,len(entry['default_routes']))
        self.assertEqual(source['id'],entry['default_routes'][0]['id'])
        self.ui.adopt(saved);self.ui.items.selection_set('builtin:'+source['id']);self.root.update()
        self.assertEqual(entry['default_routes'][0]['points'],self.ui._selected()['points'])
        self.assertEqual(graph,self.ui.graph_cache['08_ruinberg'])
        self.ui.reset_builtin();self.assertEqual(original,self.ui._selected()['points'])
        self.assertNotIn('08_ruinberg',self.ui.document['maps'])
        self.ui.undo();self.assertEqual(entry['default_routes'][0]['points'],self.ui._selected()['points'])

    def test_draw_drag_insert_undo_save_reopen_and_apply_route(self):
        self.ui.new_route();self.root.update()
        self.click((-66,306));self.click((-126,246));self.click((-186,186))
        route=self.ui._selected();self.assertEqual(3,len(route['points']))
        first=copy.deepcopy(route['points'][0]);x,y=self.ui.view.screen(first)
        end=self.ui.view.screen((-80,290))
        self.ui.canvas.event_generate('<ButtonPress-1>',x=int(x),y=int(y))
        self.ui.canvas.event_generate('<B1-Motion>',x=int(end[0]),y=int(end[1]))
        self.ui.canvas.event_generate('<ButtonRelease-1>',x=int(end[0]),y=int(end[1]));self.root.update()
        self.assertNotEqual(first,route['points'][0]);self.ui.undo();self.root.update()
        self.assertEqual(first,self.ui._selected()['points'][0]);self.ui.redo();self.root.update()
        self.ui.selected_point=0;self.click((-90,270),shift=True)
        self.assertEqual(4,len(self.ui._selected()['points']))
        self.ui.item_vars['label'].set('Test road');self.ui.item_vars['policy'].set('fixed')
        self.ui.profile_name.set('UI test');self.ui.save(False);self.root.update()
        self.assertFalse(self.error_mock.called,self.error_mock.call_args)
        self.assertEqual({},self.ui.store.active()['maps'])
        draft=self.ui.store.read('UI test');self.assertEqual('fixed',draft['maps']['08_ruinberg']['routes'][0]['policy'])
        self.ui.adopt(draft);self.ui.save(True)
        self.assertEqual(draft,self.ui.store.active());self.assertFalse(self.ui.dirty())

    def test_manual_spg_position_fields_persist_to_active_document(self):
        self.ui.new_position();self.root.update();self.click((-106,346))
        self.ui.item_vars['radius'].set('34');self.ui.item_vars['heading'].set('-180');self.ui.item_vars['priority'].set('9')
        self.ui.save(True);self.root.update();self.assertFalse(self.error_mock.called,self.error_mock.call_args)
        point=self.ui.store.active()['maps']['08_ruinberg']['positions'][0]
        self.assertEqual(34,point['radius']);self.assertEqual(-180,point['heading']);self.assertEqual(9,point['priority'])
        self.assertLess(abs(point['point'][0]+106),2)
        self.assertLess(abs(point['point'][1]-346),2)

    def test_switching_class_keeps_saved_routes_and_limits_visible_items(self):
        self.ui.new_route();self.root.update()
        self.click((-66,306));self.click((-126,246))
        heavy=copy.deepcopy(self.ui._selected())
        self.assertEqual(['heavyTank'],heavy['classes'])
        self.ui.route_class_var.set('mediumTank');self.ui.change_route_class()
        self.assertNotIn('routes:'+heavy['id'],self.ui.items.get_children())
        self.ui.new_route();self.root.update()
        self.click((-76,306));self.click((-136,246))
        medium=copy.deepcopy(self.ui._selected())
        self.assertEqual(['mediumTank'],medium['classes'])
        self.ui.profile_name.set('Separate classes');self.ui.save(False)
        saved=self.ui.store.read('Separate classes')
        self.assertEqual(2,len(saved['maps']['08_ruinberg']['routes']))
        self.ui.route_class_var.set('heavyTank');self.ui.change_route_class()
        self.assertIn('routes:'+heavy['id'],self.ui.items.get_children())
        self.assertNotIn('routes:'+medium['id'],self.ui.items.get_children())

    def test_double_click_condition_survives_save_and_reopen(self):
        self.ui.new_route();self.root.update()
        self.click((-66,306));self.click((-126,246))
        point=self.ui._selected()['points'][0]
        x,y=self.ui.view.screen(point)
        event=type('Event',(),dict(x=x,y=y))()
        self.ui.edit_point_condition(event)
        self.click(point[:2]);self.ui.wait_seconds.set('25');self.ui.update_wait_time()
        self.ui.profile_name.set('Timed route');self.ui.save(False)
        saved=self.ui.store.read('Timed route')
        self.assertEqual(25,saved['maps']['08_ruinberg']['routes'][0]['points'][0][4][0][2])
        self.ui.adopt(saved)
        self.assertEqual(saved,self.ui.document)

    def test_invalid_form_does_not_replace_prior_active_config(self):
        before=self.ui.store.active();self.ui.new_position();self.root.update()
        self.ui.item_vars['radius'].set('nan');self.ui.save(True)
        self.assertTrue(self.error_mock.called);self.assertEqual(before,self.ui.store.active())

    def test_behavior_form_changes_actual_schema_and_can_be_removed(self):
        self.ui.book.select(0);self.root.update()
        self.ui.rule_vars['team'].set('1');self.ui.rule_vars['class_tag'].set('SPG')
        self.ui.rule_vars['crew_level'].set('100');self.ui.rule_vars['reaction_seconds'].set('2.7')
        self.ui.save_rule();self.ui.save(True)
        raw=self.ui.store.active();actual=storage.contract.effective(raw,1,'SPG',2)
        self.assertEqual({'crew_level':100,'reaction_seconds':2.7},actual)
        self.assertEqual({},storage.contract.effective(raw,2,'SPG',2))
        self.ui.rules.selection_set('0');self.root.update();self.ui.delete_rule();self.ui.save(True)
        self.assertEqual([],self.ui.store.active()['behavior'])

    def test_copy_builtin_route_does_not_change_baked_source(self):
        graph=copy.deepcopy(self.ui.graph_cache['08_ruinberg'])
        self.ui.items.selection_set('builtin:'+graph['routes']['1'][0]['id']);self.root.update()
        self.ui.duplicate_item();self.root.update()
        self.assertEqual('routes',self.ui.selection[0]);self.assertTrue(self.ui._selected()['points'])
        self.assertEqual(graph,self.ui.graph_cache['08_ruinberg']);self.ui.save(False)
        self.assertFalse(self.error_mock.called,self.error_mock.call_args)

    def test_map_switch_keeps_world_points_and_shows_different_base(self):
        self.ui.new_position();self.root.update();self.click((-106,346));saved=copy.deepcopy(self.ui.entry()['positions'])
        self.ui.map_var.set(storage.MAP_LABELS['35_steppes']);self.ui.change_map();self.root.update()
        self.assertEqual('35_steppes',self.ui.map_name)
        self.assertIn(str(self.ui.graph_cache['35_steppes']['spawn_anchors'][self.ui.team-1]),self.ui.base_label.cget('text'))
        self.ui.map_var.set(storage.MAP_LABELS['08_ruinberg']);self.ui.change_map();self.root.update()
        self.assertEqual(saved,self.ui.entry()['positions'])

    def test_apply_controls_remain_visible_at_minimum_window_size(self):
        self.ui.root.geometry('1000x700');self.root.update()
        self.assertLess(self.ui.book.winfo_y(),self.ui.root.winfo_height())
        for label in self.ui.root.winfo_children():
            if isinstance(label,ttk.Frame):
                for child in label.winfo_children():
                    if isinstance(child,ttk.Button) and '下一局' in str(child.cget('text')):
                        self.assertTrue(child.winfo_ismapped())
                        self.assertLess(child.winfo_rooty(),self.ui.root.winfo_rooty()+self.ui.root.winfo_height())


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'requires actual Tk display')
class LauncherEntryTests(unittest.TestCase):
    def test_real_launcher_button_opens_real_editor(self):
        import core,wot_launcher
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict(os.environ,{'LOCALAPPDATA':tmp}),\
             mock.patch.object(core,'load_settings',return_value={'language':'zh','free_notice_seen':True}),\
             mock.patch.object(core,'discover_game_folders',return_value=[]),\
             mock.patch.object(ui_module.messagebox,'showerror') as errors:
            app=wot_launcher.LauncherWindow(tk,ttk,filedialog)
            try:
                app.root.update()
                app.bot_tactics_button.invoke();app.root.update()
                self.assertFalse(errors.called,errors.call_args)
                self.assertTrue(any(isinstance(w,tk.Toplevel) and w.title()=='Bot 配置与地图战术' for w in app.root.winfo_children()))
            finally:app.root.destroy()


if __name__=='__main__':unittest.main()
