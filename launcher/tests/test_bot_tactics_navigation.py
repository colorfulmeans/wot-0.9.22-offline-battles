"""Raw navigation visualization and checks stay entirely in the editor."""
import copy
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock

import bot_tactics_navigation as nav
import bot_tactics_store as storage
import bot_tactics_ui as ui


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

    def test_check_map_includes_unedited_defaults_and_does_not_write_profile(self):
        editor=self.editor;before=copy.deepcopy(editor.document)
        editor.map_var.set('阿拉曼机场');editor.map_name='31_airfield';editor._load_map()
        editor.check_map();self.root.update()
        texts=[]
        def collect(widget):
            if isinstance(widget,tk.Text):texts.append(widget.get('1.0','end'))
            for child in widget.winfo_children():collect(child)
        collect(editor.root)
        self.assertTrue(any('导航格检查' in text and '队伍 1' in text and '队伍 2' in text for text in texts))
        self.assertEqual(before,editor.document)
