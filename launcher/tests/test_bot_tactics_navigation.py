"""Raw navigation visualization and checks stay entirely in the editor."""
import copy
import importlib.util
import os
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock

import bot_tactics_navigation as nav
import bot_tactics_store as storage
import bot_tactics_ui as ui

HAS_PIL = importlib.util.find_spec('PIL') is not None


def graph():
    return dict(width=5, height=5, cell_size=4.0, origin=[0., 0.],
        heights_mm=[0]*25, hazards=[0]*25, links=[255]*25,
        directions=[[1,0],[1,1],[0,1],[-1,1],[-1,0],[-1,-1],[0,-1],[1,-1]])


class NavigationDataTests(unittest.TestCase):
    def test_missing_real_start_is_not_hidden_by_nearby_valid_cell(self):
        data=storage.graph_data('31_airfield')
        issues=nav.route_issues(data,[[-333.01,-195.16,0],[-325.287,-53.595,0]],
                                storage.contract.MAPS['31_airfield']['bounds'])
        node=next(i for i in issues if i['status']=='navigation_node_issue' and i['nodes']==[1])
        self.assertEqual('missing_ground',node['reason'])
        self.assertEqual([[-333.01,-195.16]],node['points'])

    def test_segment_reports_interior_holes_and_exact_node_pair(self):
        data=graph();data['heights_mm'][12]=None
        issues=nav.route_issues(data,[[0.,8.,0],[16.,8.,0]],(0,0,16,16))
        self.assertEqual(1,len(issues))
        self.assertEqual([1,2],issues[0]['nodes'])
        self.assertEqual('missing_ground',issues[0]['reason'])
        self.assertEqual(1,issues[0]['cell_count'])
        self.assertEqual([[8.,8.]],issues[0]['cells'])

    def test_directed_link_is_checked_in_travel_direction(self):
        data=graph();data['links'][10]=255 & ~1
        self.assertEqual('navigation_link_missing',nav.route_issues(
            data,[[0.,8.,0],[16.,8.,0]],(0,0,16,16))[0]['reason'])
        self.assertEqual([],nav.route_issues(data,[[16.,8.,0],[0.,8.,0]],(0,0,16,16)))

    @unittest.skipUnless(HAS_PIL, 'requires Pillow')
    def test_display_distinguishes_height_links_and_hazard_with_north_up(self):
        data=graph();data['heights_mm'][20]=None;data['hazards'][0]=4;data['links'][24]=0
        image=nav.overlay_image(data,(0,0,16,16))
        for pixel,key in (((1,1),'missing_ground'),((1,13),'navigation_hazard'),
                          ((13,1),'no_navigation_links'),((7,7),'available')):
            self.assertEqual(nav.COLORS[key][1],image.getpixel(pixel))

    def test_default_routes_and_class_overrides_checked_without_mutation(self):
        data=storage.graph_data('31_airfield');profile=storage.contract.empty()
        first=data['routes']['1'][0]
        profile['maps']['31_airfield']=dict(default_routes=[dict(id=first['id'],team=1,
            class_tag='heavyTank',points=[list(p) for p in first['waypoints']])],routes=[],positions=[])
        before=copy.deepcopy((profile,data))
        result=nav.check_map(profile,'31_airfield',data,storage.contract)
        identities=[r[0] for r in result]
        self.assertIn('1:'+first['id'],identities)
        self.assertIn('1:class_ht_'+first['id'],identities)
        self.assertEqual(before,(profile,data))

    def test_outside_node_does_not_walk_an_unbounded_segment(self):
        with mock.patch.object(nav,'segment_cells',side_effect=AssertionError('unbounded walk')):
            issues=nav.route_issues(graph(),[[0.,0.,0],[100000.,0.,0]],(0,0,16,16))
        self.assertEqual([2],issues[0]['nodes'])
        self.assertEqual('outside_bounds',issues[0]['reason'])


@unittest.skipUnless(HAS_PIL and (os.name == 'nt' or os.environ.get('DISPLAY')),
                     'requires Pillow and Tk display')
class NavigationUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.editor=ui.BotTacticsEditor(self.root,store=storage.Store(self.temp.name),language='zh')
        self.editor.book.select(1)
        self.root.update()

    def test_checkbox_is_right_of_symmetry_off_by_default_and_does_not_edit_profile(self):
        editor=self.editor;before=copy.deepcopy(editor.document)
        self.assertFalse(editor.navigation_grid_var.get())
        self.assertGreaterEqual(editor.navigation_grid_check.winfo_x(),
            editor.symmetry_check.winfo_x()+editor.symmetry_check.winfo_width())
        with mock.patch.object(ui.navigation_view,'overlay_image',wraps=nav.overlay_image) as render:
            editor.navigation_grid_check.invoke();self.root.update()
            self.assertIsNotNone(editor.navigation_photo)
            editor.wheel(SimpleNamespace(x=300,y=300),delta=1);editor.fit_view()
            editor.navigation_grid_check.invoke();editor.navigation_grid_check.invoke()
            self.assertEqual(1,render.call_count)
        self.assertEqual(before,editor.document)

    def test_check_map_does_not_run_raw_grid_checks_or_write_profile(self):
        editor=self.editor;before=copy.deepcopy(editor.document)
        editor.map_var.set('阿拉曼机场');editor.map_name='31_airfield';editor._load_map()
        with mock.patch.object(nav,'check_map',side_effect=AssertionError('raw grid checks disabled')) as raw_check:
            editor.check_map();self.root.update()
        raw_check.assert_not_called()
        texts=[]
        def collect(widget):
            if isinstance(widget,tk.Text):texts.append(widget.get('1.0','end'))
            for child in widget.winfo_children():collect(child)
        collect(editor.root)
        self.assertTrue(texts)
        self.assertTrue(all('导航格检查' not in text and '涉及' not in text for text in texts))
        self.assertTrue(any('本图没有自定义数据' in text for text in texts))
        self.assertEqual(before,editor.document)

    def test_total_view_lists_effective_classes_and_parking_without_generic_line(self):
        e=self.editor;e.map_name='31_airfield';e._load_map()
        before=copy.deepcopy(e.document)
        e.route_class_var.set('total');e.change_route_class()
        keys=e.items.get_children()
        for tag in storage.contract.CLASSES[:-1]:
            self.assertTrue(any(k.startswith('builtin:') and k.endswith('@'+tag) for k in keys),tag)
        self.assertTrue(any(k.startswith('builtin_positions:') for k in keys))
        self.assertFalse(any(k.endswith('@all') for k in keys))
        fills=[e.canvas.itemcget(i,'fill') for i in e.canvas.find_all() if e.canvas.type(i)=='line']
        self.assertNotIn('#000000',fills)
        self.assertEqual(before,e.document)
        e.route_class_var.set('all');e.change_route_class()
        fills=[e.canvas.itemcget(i,'fill') for i in e.canvas.find_all() if e.canvas.type(i)=='line']
        self.assertIn('#000000',fills)
        self.assertEqual('#a5a5a5',ui.CLASS_COLORS['heavyTank'])

    def test_total_drag_edits_only_selected_class_and_reversed_team(self):
        e=self.editor;e.map_name='31_airfield';e._load_map()
        e.route_class_var.set('total');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin:') and k.endswith('@heavyTank'))
        e.items.selection_set(key);e.select_item()
        original=copy.deepcopy(e._selected()['points'])
        e.checkpoint();e._editable_points()[1][0]+=5;e._sync_symmetry();e._refresh_items()
        edits=e.entry()['default_routes']
        self.assertEqual({'heavyTank'},{r['class_tag'] for r in edits})
        own=next(r for r in edits if r['team']==1);peer=next(r for r in edits if r['team']==2)
        self.assertEqual(own['points'],list(reversed(peer['points'])))
        e.route_class_var.set('mediumTank');e.change_route_class()
        e.selection=('builtin',own['id'])
        self.assertEqual(original,e._selected()['points'])
        storage.contract.canonical(e.document)
        e.route_class_var.set('total');e.change_route_class();e.selection=('builtin',own['id']+'@heavyTank')
        e.reset_builtin();self.assertFalse(e.entry().get('default_routes'))

    def test_total_shared_custom_route_edit_splits_class_and_its_mirror(self):
        e=self.editor;e.route_class_var.set('all');e.new_route()
        item=e._selected();item['points']=[[-100.,-100.,0],[100.,100.,0]];e._sync_symmetry()
        old_id=item['id'];e.route_class_var.set('total');e.change_route_class()
        e.selection=('routes',old_id+'@lightTank')
        e.checkpoint();e._editable_points()[0][0]+=7;e._sync_symmetry();e._refresh_items()
        entries=e.entry()['routes'];self.assertEqual(4,len(entries))
        for r in entries:
            if r['id']==old_id:
                self.assertNotIn('lightTank',r['classes']);self.assertEqual(-100.,r['points'][0][0])
        selected=e._selected();self.assertEqual(['lightTank'],selected['classes'])
        self.assertEqual(-93.,selected['points'][0][0])
        other=next(r for r in entries if r['id']==selected['mirror_id'])
        self.assertEqual(selected['points'],list(reversed(other['points'])))
        storage.contract.canonical(e.document)

    def test_total_canvas_can_select_and_drag_colored_node(self):
        e=self.editor;e.map_name='31_airfield';e._load_map()
        e.route_class_var.set('total');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin:') and k.endswith('@mediumTank'))
        e.items.selection_set(key);e.select_item()
        point=e._selected()['points'][1];x,y=e.view.screen(point)
        e.press(SimpleNamespace(x=x,y=y,state=0))
        self.assertEqual(tuple(key.split(':',1)),e.selection)
        e.motion(SimpleNamespace(x=x+10,y=y));e.release(None)
        self.assertTrue(e.items.exists(':'.join(e.selection)))
        self.assertEqual('mediumTank',e._selected()['class_tag'])
        self.assertNotEqual(point[:2],e._selected()['points'][1][:2])

    def test_priority_is_editable_by_class_hidden_in_all_and_readonly_in_total(self):
        e=self.editor;e.map_name='31_airfield';e._load_map()
        e.route_class_var.set('lightTank');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin:'))
        e.items.selection_set(key);e.select_item();old=copy.deepcopy(e._selected()['points'])
        e.item_vars['route_priority'].set('8');self.assertTrue(e.update_properties())
        e.save(True);saved=e.store.active()['maps']['31_airfield']['default_routes']
        self.assertEqual({('lightTank',8)},{(r['class_tag'],r['priority']) for r in saved})
        self.assertEqual({1,2},{r['team'] for r in saved});self.assertEqual(old,e._selected()['points'])
        identity=e._selected()['id']
        e.route_class_var.set('all');e.change_route_class();e.selection=('builtin',identity);e._refresh_properties();self.root.update()
        self.assertFalse(e.item_fields['route_priority'][1].winfo_ismapped())
        e.item_vars['route_priority'].set('9');e.update_properties()
        self.assertEqual(saved,e.document['maps']['31_airfield']['default_routes'])
        e.route_class_var.set('total');e.change_route_class();e.selection=('builtin',identity+'@lightTank');e._refresh_properties()
        self.assertEqual('readonly',str(e.item_fields['route_priority'][1].cget('state')))
        self.assertEqual('8',e.item_vars['route_priority'].get())
        self.assertIn('优先级 8',e.items.item('builtin:'+identity+'@lightTank','text'))
        self.assertIn('优先级 0',e.items.item('builtin:'+identity+'@heavyTank','text'))
        e.navigation_grid_check.invoke();self.root.update();self.assertIsNotNone(e.navigation_photo)

    def test_custom_route_priority_values_are_independent_for_each_class(self):
        e=self.editor;e.route_class_var.set('all');e.new_route();item=e._selected()
        item['points']=[[-100.,-100.,0],[100.,100.,0]];identity=item['id']
        for tag,value in (('lightTank',8),('heavyTank',2)):
            e.route_class_var.set(tag);e.change_route_class();e.selection=('routes',identity);e._refresh_properties()
            e.item_vars['route_priority'].set(str(value));self.assertTrue(e.update_properties())
        self.assertEqual({'lightTank':8,'heavyTank':2},e._selected()['class_priorities'])
        e.route_class_var.set('total');e.change_route_class()
        self.assertIn('优先级 8',e.items.item('routes:'+identity+'@lightTank','text'))
        self.assertIn('优先级 2',e.items.item('routes:'+identity+'@heavyTank','text'))
