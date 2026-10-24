"""Actual Tk gestures and storage fences for the fixed-endpoint editor."""
import copy
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock

import bot_tactics_store as storage
import bot_tactics_ui as ui


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'requires Tk')
class RouteControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = storage.Store(self.temp.name)
        self.store.save(storage.contract.empty('Editable'), apply=True)
        self.root = tk.Tk(); self.root.withdraw(); self.addCleanup(self.root.destroy)
        self.errors = mock.patch.object(ui.messagebox, 'showerror').start()
        self.addCleanup(mock.patch.stopall)
        self.editor = ui.BotTacticsEditor(self.root, store=self.store)
        e = self.editor
        e.map_var.set(storage.MAP_LABELS['08_ruinberg']); e.change_map()
        e.route_class_var.set('heavyTank'); e.change_route_class()
        e.symmetry_var.set(False); e.book.select(1); self.root.update()

    def event(self, point, state=0):
        x, y = self.editor.view.screen(point)
        return SimpleNamespace(x=x, y=y, state=state)

    def click(self, point, shift=False):
        e = self.editor; event = self.event(point, int(shift))
        e.press(event); e.release(event)

    def test_blank_click_selection_and_fixed_drag_do_not_mutate_or_clear_redo(self):
        e = self.editor; e.new_route()
        e.selected_point=0; e.insert_point(); e.undo()
        before=copy.deepcopy(e.document); history=copy.deepcopy(e.histories)
        self.click((0,0)); self.click(e._selected()['points'][0])
        event=self.event(e._selected()['points'][0]); e.press(event)
        e.motion(SimpleNamespace(x=event.x+20,y=event.y+20)); e.release(event)
        e.selected_point=len(e._selected()['points'])-1; e.delete_point()
        self.assertEqual(before,e.document); self.assertEqual(history,e.histories)

    def test_shift_and_button_insert_before_terminal_with_one_undo_per_gesture(self):
        e = self.editor; e.new_route(); ends=copy.deepcopy(e._selected()['points'])
        self.assertEqual(0,e.selected_point)
        self.click((-96,276),True)
        self.assertEqual(3,len(e._selected()['points'])); self.assertEqual(1,e.selected_point)
        e.selected_point=2; self.click((-126,246),True)
        self.assertEqual(ends[-1],e._selected()['points'][-1])
        e.selected_point=None; self.click((-156,216),True)
        self.assertEqual(5,len(e._selected()['points']))
        e.selected_point=len(e._selected()['points'])-1; e.insert_point()
        self.assertEqual(ends[0],e._selected()['points'][0]); self.assertEqual(ends[-1],e._selected()['points'][-1])
        before=copy.deepcopy(e.document); point=e._selected()['points'][1]
        event=self.event(point); e.press(event)
        for delta in (10,20,30):e.motion(SimpleNamespace(x=event.x+delta,y=event.y))
        e.release(event); self.assertNotEqual(before,e.document)
        e.undo(); self.assertEqual(before,e.document)
        e.redo(); self.assertNotEqual(before,e.document)

    def test_asymmetric_maps_cannot_enable_symmetry_or_change_terminal_on_save(self):
        e = self.editor
        for name in ('100_thepit','63_tundra','95_lost_city'):
            e.map_var.set(storage.MAP_LABELS[name]); e.change_map(); e.new_route()
            self.assertTrue(e.symmetry_check.instate(['disabled']))
            points=copy.deepcopy(e._selected()['points'])
            e.symmetry_var.set(True); e.change_symmetry()
            self.assertFalse(e._selected()['symmetric'])
            e.save(False); self.assertEqual(points,e._selected()['points'])
        self.errors.assert_not_called()

    def test_save_and_import_reject_moved_endpoints_without_rewriting_or_applying(self):
        e = self.editor; e.new_route(); e.save(False)
        active=copy.deepcopy(self.store.active()); saved=self.store.read('Editable')
        invalid=copy.deepcopy(saved); invalid['maps']['08_ruinberg']['routes'][0]['points'][0][0]+=10
        with self.assertRaises(storage.contract.TacticsError):self.store.save(invalid,apply=True)
        path=Path(self.temp.name)/'invalid.json'; path.write_text(storage.contract.dumps(invalid))
        with self.assertRaises(storage.contract.TacticsError):self.store.import_file(path)
        self.assertEqual(active,self.store.active()); self.assertEqual(saved,self.store.read('Editable'))

    def test_shared_geometry_preserves_enabled_waits_and_disabled_status(self):
        e=self.editor; e.adopt(storage.contract.default_profile('Editable'))
        e.map_var.set(storage.MAP_LABELS['11_murovanka']); e.change_map()
        rows=e.entry()['default_routes']; shared=next(r for r in rows if r['team']==1 and r['id']=='central_field' and r.get('class_tag','all')=='all')
        enabled=next(r for r in rows if r['team']==1 and r['id']=='central_field' and r.get('class_tag')=='lightTank')
        enabled['points'][1][3:]=[0.,[enabled['points'][1][:2]+[25.]]]
        before=copy.deepcopy(enabled); shared['points'][1][0]+=2
        e._sync_shared_default_geometry(shared)
        self.assertEqual(before,enabled)
        for r in rows:
            if r['team']==1 and r['id']=='central_field' and r.get('disabled'):
                self.assertEqual(shared['points'],r['points'])
                self.assertTrue(all(len(p)==3 and p[2]==0 for p in r['points']))

    def test_wait_mode_and_artillery_keep_explicit_click_behavior(self):
        e=self.editor; e.new_route(); self.click((-96,276),True)
        count=len(e._selected()['points']); e.edit_point_condition()
        self.click((-90,280)); self.assertEqual(count,len(e._selected()['points']))
        self.assertEqual(60,storage.contract.waiting_positions(e._wait_point())[0][2])
        before=copy.deepcopy(e.document); event=self.event(storage.contract.waiting_positions(e._wait_point())[0])
        history=copy.deepcopy(e.histories); e.press(event); e.release(event)
        self.assertEqual(before,e.document); self.assertEqual(history,e.histories)
        e.wait_edit=False; e.new_position(); self.click((-106,346))
        self.assertAlmostEqual(-106,e._selected()['point'][0])
        self.assertAlmostEqual(346,e._selected()['point'][1])

    def test_copy_asymmetric_approach_keeps_old_terminal_as_intermediate(self):
        e=self.editor; e.adopt(storage.contract.default_profile('Editable'))
        e.map_var.set(storage.MAP_LABELS['95_lost_city']); e.change_map()
        e.route_class_var.set('lightTank'); e.change_route_class()
        key=next(k for k in e.items.get_children() if k.startswith('builtin:'))
        e.items.selection_set(key); e.select_item()
        before=copy.deepcopy(e._selected()['points']); e.duplicate_item()
        self.assertEqual(before,e._selected()['points'][:-1])
        self.assertEqual(e.graph_cache[e.map_name]['spawn_anchors'][1],e._selected()['points'][-1][:2])
        e.save(False); self.errors.assert_not_called()


class SharedRouteDataTests(unittest.TestCase):
    def test_old_default_with_retired_identity_refreshes_before_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            store=storage.Store(temp)
            old=storage.contract.default_profile()
            old['maps']['04_himmelsdorf']['default_routes'].append(dict(
                id='rear_guard',team=1,disabled=True,points=[[46.,270.,0],[70.,346.,0]]))
            store.active_path.write_text(storage.contract.dumps(old))
            self.assertEqual(storage.contract.default_profile(),store.active())

    def test_retired_routes_are_absent_and_disabled_rows_have_no_waits(self):
        from gui.mods.offline_lan_0922.ai.maps import TACTICAL_MAPS
        profile=storage.contract.default_profile()
        for team in (1,2):
            self.assertNotIn('rear_guard',[r['id'] for r in TACTICAL_MAPS['04_himmelsdorf']['routes'][team]])
            self.assertNotIn('rear_guard',[r['id'] for r in storage.graph_data('04_himmelsdorf')['routes'][str(team)]])
        for name,entry in profile['maps'].items():
            for row in entry['default_routes']:
                if not row.get('disabled'):continue
                source=next(r for r in entry['default_routes'] if r['team']==row['team'] and r['id']==row['id'] and r.get('class_tag','all')=='all')
                self.assertEqual([p[:2]+[0] for p in source['points']],row['points'],(name,row['id']))


if __name__=='__main__':unittest.main()
