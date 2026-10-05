"""Raw navigation visualization and checks stay entirely in the editor."""
import copy
import importlib.util
import os
import tempfile
import tkinter as tk
from tkinter import ttk
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

    def test_check_map_names_wait_place_parent_coordinates_and_reason(self):
        e=self.editor;before=copy.deepcopy(e.document)
        result=[('wait-test','wait_place_unusable',[dict(status='wait_place_unusable',
            nodes=[3],points=[[12.5,-34.5]],wait_slot=2)])]
        with mock.patch.object(storage.runtime,'authoring_check',return_value=result):
            e.check_map();self.root.update()
        texts=[]
        def collect(widget):
            if isinstance(widget,tk.Text):texts.append(widget.get('1.0','end'))
            for child in widget.winfo_children():collect(child)
        collect(e.root)
        self.assertTrue(any('节点 3 / 等待点 2' in text and 'X 12.5, Z -34.5' in text
                            and '等待点不可用' in text for text in texts))
        self.assertEqual(before,e.document)

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

    def test_priority_is_editable_by_class_and_total_but_hidden_in_all(self):
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
        self.assertEqual('normal',str(e.item_fields['route_priority'][1].cget('state')))
        self.assertEqual('8',e.item_vars['route_priority'].get())
        self.assertTrue(e.items.item('builtin:'+identity+'@lightTank','text').startswith('[优先级 8]'))
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

    def test_shared_drag_after_class_edit_wins_without_losing_priorities(self):
        e=self.editor;e.map_name='31_airfield';e._load_map()
        e.route_class_var.set('lightTank');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin:'))
        e.items.selection_set(key);e.select_item();identity=e._selected()['id']
        e.item_vars['route_priority'].set('8');e.update_properties()
        point=e._selected()['points'][1];x,y=e.view.screen(point)
        e.press(SimpleNamespace(x=x,y=y,state=0));e.motion(SimpleNamespace(x=x+12,y=y));e.release(None)
        class_geometry=copy.deepcopy(e._selected()['points'])
        e.route_class_var.set('all');e.change_route_class();e.items.selection_set('builtin:'+identity);e.select_item()
        self.assertEqual(class_geometry,next(r for r in e.entry()['default_routes'] if r['team']==1 and r.get('class_tag')=='lightTank')['points'])
        point=e._selected()['points'][1];x,y=e.view.screen(point)
        e.press(SimpleNamespace(x=x,y=y,state=0));e.motion(SimpleNamespace(x=x-10,y=y));e.release(None)
        shared_geometry=copy.deepcopy(e._selected()['points']);self.assertNotEqual(class_geometry,shared_geometry)
        edits=e.entry()['default_routes'];light=next(r for r in edits if r['team']==1 and r.get('class_tag')=='lightTank')
        self.assertEqual(shared_geometry,light['points']);self.assertEqual(8,light['priority'])
        other=next(r for r in edits if r['team']==2 and r.get('class_tag')=='lightTank')
        self.assertEqual(shared_geometry,list(reversed(other['points'])));self.assertEqual(8,other['priority'])
        e.save(True);self.assertEqual(e.document,e.store.active())
        shared_geometry=copy.deepcopy(e._selected()['points'])
        e.route_class_var.set('lightTank');e.change_route_class();e.items.selection_set('builtin:'+identity);e.select_item()
        point=e._selected()['points'][1];x,y=e.view.screen(point)
        e.press(SimpleNamespace(x=x,y=y,state=0));e.motion(SimpleNamespace(x=x+5,y=y));e.release(None)
        self.assertNotEqual(shared_geometry,e._selected()['points'])
        e.route_class_var.set('heavyTank');e.change_route_class();e.items.selection_set('builtin:'+identity);e.select_item()
        self.assertEqual(shared_geometry,e._selected()['points'])

    def test_shared_wait_reset_and_single_team_changes_preserve_class_priorities(self):
        e=self.editor;e.map_name='31_airfield';e._load_map();e.route_class_var.set('heavyTank');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin:'));e.items.selection_set(key);e.select_item()
        identity=e._selected()['id'];e.item_vars['route_priority'].set('7');e.update_properties()
        other_before=copy.deepcopy(next(r for r in e.entry()['default_routes'] if r['team']==2))
        e.route_class_var.set('all');e.change_route_class();e.items.selection_set(key);e.select_item()
        e.symmetry_var.set(False);e.change_symmetry();e.selected_point=1;e.toggle_hold()
        own=next(r for r in e.entry()['default_routes'] if r['team']==1 and r.get('class_tag')=='heavyTank')
        self.assertEqual(-1.,own['points'][1][3]);self.assertEqual(7,own['priority'])
        self.assertEqual(other_before,next(r for r in e.entry()['default_routes'] if r['team']==2))
        e.undo()
        own=next(r for r in e.entry()['default_routes'] if r['team']==1 and r.get('class_tag')=='heavyTank')
        self.assertEqual(7,own['priority']);self.assertTrue(len(own['points'][1])==3 or own['points'][1][3]!=-1.)
        e.redo();e.reset_builtin()
        own=next(r for r in e.entry()['default_routes'] if r['team']==1 and r.get('class_tag')=='heavyTank')
        original=next(r for r in e.graph_cache[e.map_name]['routes']['1'] if r['id']==identity)['waypoints']
        self.assertEqual(original,own['points']);self.assertEqual(7,own['priority'])
        self.assertEqual(other_before,next(r for r in e.entry()['default_routes'] if r['team']==2))

    def test_wait_nodes_grow_while_editing_and_remain_visible_unselected(self):
        e=self.editor;e.route_class_var.set('all');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin:'))
        e.items.selection_set(key);e.select_item();points=e._editable_points()
        points[0][3:]=[60.];points[1][3:]=[-1.];points[2][3:]=[0.]
        before=copy.deepcopy(e.document);e.selected_point=0;e.redraw()
        def radii():
            return [(e.canvas.coords(i)[2]-e.canvas.coords(i)[0])/2
                    for i in e.canvas.find_withtag('route_wait')]
        self.assertEqual([10.,7.],radii())
        ordinary=e.canvas.find_withtag('route_node');self.assertTrue(ordinary)
        self.assertEqual(4.,(e.canvas.coords(ordinary[0])[2]-e.canvas.coords(ordinary[0])[0])/2)
        e.selection=None;e.selected_point=None;e.redraw()
        self.assertEqual([7.,7.],radii())
        self.assertFalse(e.canvas.find_withtag('route_node'))
        self.assertEqual(before,e.document)
        captions=[str(w.cget('text')) for w in e.node_legend.winfo_children() if isinstance(w,ttk.Label)]
        self.assertEqual(['普通节点','大圆点：等待点组（点击展开）','展开的小方点：独立等待点','◇ 出生点中心；虚线圈：占领基地范围'],captions)
        e.set_language('en')
        self.assertEqual('Node legend',e.node_legend.cget('text'))
        self.assertIn('Expanded squares: individual wait places',[str(w.cget('text')) for w in e.node_legend.winfo_children() if isinstance(w,ttk.Label)])
        e.route_class_var.set('total');e.change_route_class();e.redraw()
        self.assertTrue(radii());self.assertTrue(all(r==7. for r in radii()))
        self.assertFalse(e.canvas.find_withtag('route_node'))
        e.selection=next(target[0] for target in e.route_hit_targets if target[0][0]=='builtin')
        e.redraw();self.assertTrue(e.canvas.find_withtag('route_node'))

    def test_custom_wait_nodes_use_the_same_editing_and_overview_markers(self):
        e=self.editor;e.route_class_var.set('all');e.change_route_class();e.new_route()
        e._selected()['points']=[[-100.,-100.,0,30.],[0.,0.,1,0.],[100.,100.,1,-1.]]
        e.selected_point=2;e.redraw()
        def radii():
            return [(e.canvas.coords(i)[2]-e.canvas.coords(i)[0])/2
                    for i in e.canvas.find_withtag('route_wait')]
        self.assertEqual([7.,10.],radii())
        e.selection=None;e.selected_point=None;e.redraw()
        self.assertEqual([7.,7.],radii())
        self.assertFalse(e.canvas.find_withtag('route_node'))

    def test_delete_default_route_scopes_total_class_and_shared_views(self):
        e=self.editor;e.route_class_var.set('total');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin:') and k.endswith('@lightTank'))
        identity=key.split(':',1)[1].split('@',1)[0]
        e.items.selection_set(key);e.select_item()
        with mock.patch.object(ui.messagebox,'askyesno',return_value=True):e.delete_item()
        self.assertFalse(e.items.exists(key))
        e.route_class_var.set('lightTank');e.change_route_class()
        self.assertFalse(e.items.exists('builtin:'+identity))
        e.team=2;e._refresh_items();self.assertFalse(e.items.exists('builtin:'+identity))
        e.team=1;e._refresh_items();e.route_class_var.set('heavyTank');e.change_route_class()
        self.assertTrue(e.items.exists('builtin:'+identity))
        e.route_class_var.set('all');e.change_route_class();e.items.selection_set('builtin:'+identity);e.select_item()
        with mock.patch.object(ui.messagebox,'askyesno',return_value=True):e.delete_item()
        e.route_class_var.set('heavyTank');e.change_route_class();self.assertFalse(e.items.exists('builtin:'+identity))
        e.save(True);self.assertEqual(e.document,e.store.active())
        e.undo();self.assertTrue(e.items.exists('builtin:'+identity))

    def test_insert_button_places_a_new_point_after_selected_and_mirrors(self):
        e=self.editor;e.route_class_var.set('lightTank');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin:'));e.items.selection_set(key);e.select_item()
        # Shipped default lanes can already contain sixteen nodes.
        item=e._editable_item();item['points']=copy.deepcopy(item['points'][:3])
        old=copy.deepcopy(item['points']);e.selected_point=0;e._refresh_properties()
        self.assertEqual('normal',str(e.insert_button.cget('state')))
        e.insert_button.invoke();current=e._selected()['points']
        self.assertEqual(4,len(current));self.assertEqual(old[0],current[0]);self.assertEqual(old[1:],current[2:])
        self.assertEqual([(old[0][0]+old[1][0])*.5,(old[0][1]+old[1][1])*.5,0],current[1])
        self.assertEqual(1,e.selected_point)
        other=next(r for r in e.entry()['default_routes'] if r['team']==2)
        self.assertEqual(current,list(reversed(other['points'])))
        e.undo();self.assertEqual(old,e._selected()['points'])
        e.selected_point=2;e.insert_point();self.assertEqual(4,len(e._selected()['points']))

    def test_default_names_edit_in_all_and_total_preserving_geometry_and_priorities(self):
        e=self.editor;e.route_class_var.set('heavyTank');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin:'));identity=key.split(':',1)[1]
        e.items.selection_set(key);e.select_item();e.item_vars['route_priority'].set('7');e.update_properties()
        before=copy.deepcopy(e.entry()['default_routes'])
        e.route_class_var.set('all');e.change_route_class();e.items.selection_set(key);e.select_item()
        self.assertEqual('normal',str(e.item_fields['label'][1].cget('state')))
        e.item_vars['label'].set('北侧山口');self.assertTrue(e.update_properties())
        for old in before:
            current=next(r for r in e.entry()['default_routes'] if r['team']==old['team'] and r.get('class_tag')==old.get('class_tag'))
            self.assertEqual(old['points'],current['points']);self.assertEqual(7,current['priority'])
            self.assertEqual('北侧山口',current['label'])
        e.route_class_var.set('total');e.change_route_class();total_key=key+'@heavyTank'
        e.items.selection_set(total_key);e.select_item();e.item_vars['label'].set('重坦山口');e.update_properties()
        self.assertIn('重坦山口',e.items.item(total_key,'text'))
        self.assertIn('北侧山口',e.items.item(key+'@lightTank','text'))
        document=copy.deepcopy(e.document);e.set_language('en')
        self.assertEqual(document,e.document);self.assertIn('重坦山口',e.items.item(total_key,'text'))
        self.assertIn('Heavy tank',e.items.item(total_key,'text'));self.assertIn('Priority 7',e.items.item(total_key,'text'))
        e.save(True);self.assertEqual(e.document,e.store.active())

    def test_default_parking_can_be_named_in_chinese_and_keeps_name_in_english(self):
        e=self.editor;e.route_class_var.set('SPG');e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin_positions:'))
        e.items.selection_set(key);e.select_item();old=copy.deepcopy(e._selected())
        e.item_vars['label'].set('南侧支援炮位');self.assertTrue(e.update_properties())
        self.assertEqual(old['point'],e._selected()['point']);self.assertEqual(old['priority'],e._selected()['priority'])
        e.set_language('en');self.assertIn('南侧支援炮位',e.items.item(key,'text'))
        e.save(True);self.assertEqual(e.document,e.store.active())

    def test_total_priorities_update_only_selected_class_and_parking(self):
        e=self.editor;e.route_class_var.set('all');e.change_route_class();e.new_route()
        item=e._selected();item['points']=[[-100.,-100.,0],[100.,100.,0]];identity=item['id']
        before=copy.deepcopy(item);e.route_class_var.set('total');e.change_route_class()
        key='routes:'+identity+'@lightTank';e.items.selection_set(key);e.select_item()
        e.item_vars['route_priority'].set('9');self.assertTrue(e.update_properties())
        item=next(r for r in e.entry()['routes'] if r['id']==identity)
        self.assertEqual(before['classes'],item['classes']);self.assertEqual(before['points'],item['points'])
        self.assertEqual({'lightTank':9},item['class_priorities'])
        self.assertTrue(e.items.exists('routes:'+identity+'@heavyTank'))
        e.item_vars['route_priority'].set('10');before=copy.deepcopy(e.document)
        with mock.patch.object(e,'error'):self.assertFalse(e.update_properties())
        self.assertEqual(before,e.document)
        key=next(k for k in e.items.get_children() if k.startswith('builtin:') and k.endswith('@heavyTank'))
        e.items.selection_set(key);e.select_item();e.item_vars['route_priority'].set('6');e.update_properties()
        self.assertIn('优先级 6',e.items.item(key,'text'))
        key=next(k for k in e.items.get_children() if k.startswith('builtin_positions:'))
        e.items.selection_set(key);e.select_item();point=copy.deepcopy(e._selected()['point'])
        self.assertEqual('normal',str(e.item_fields['priority'][1].cget('state')))
        e.item_vars['priority'].set('8');self.assertTrue(e.update_properties())
        self.assertEqual(8,e._selected()['priority']);self.assertEqual(point,e._selected()['point'])
        e.save(True);self.assertEqual(e.document,e.store.active())
