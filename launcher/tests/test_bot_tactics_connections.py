"""Real Tk draft, stable junction and connection gesture regressions."""
import os
import copy
import unittest
from unittest import mock
from types import SimpleNamespace

import test_bot_tactics_route_controls as fixture
import bot_tactics_store as storage
from gui.mods.offline_lan_0922 import route_network


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ConnectionTests(unittest.TestCase):
    setUp = fixture.RouteControlsTests.setUp

    def route(self):
        e=self.editor;e.new_route();e.selected_point=0;e.insert_point();return e

    def test_defense_wait_mutual_exclusion_and_stable_insert(self):
        e=self.route();e.selected_point=1;e._refresh_properties()
        self.assertEqual('normal',str(e.defense_add.cget('state')))
        e.add_defense();branch=copy.deepcopy(e._selected_parent()['defense'])
        self.assertEqual('defense',e.network_mode)
        e.network_mode='';e.selected_point=1;e._refresh_properties()
        self.assertEqual('disabled',str(e.wait_button.cget('state')))
        self.assertIsNone(e._wait_point())
        e.selected_point=0;e.insert_point()
        self.assertEqual(branch,e._selected_parent()['defense'])
        self.assertEqual(2,route_network.nodes(e._selected_parent()).index(branch['junction']))

    def test_connection_edits_do_not_change_main_route(self):
        e=self.route();e.add_defense()
        original=copy.deepcopy(e._selected_parent()['points'])
        e.selected_point=0;e.insert_point()
        self.assertEqual(3,len(e._selected()['points']))
        self.assertEqual(original,e._selected_parent()['points'])
        e.selected_point=0;e.delete_point()
        self.assertEqual(3,len(e._selected()['points']))
        e.selected_point=1;e.delete_point()
        self.assertEqual(2,len(e._selected()['points']))
        e.undo('maps');self.assertEqual(3,len(e._selected()['points']))

    def test_waiting_node_refuses_defense_connection(self):
        e=self.route();e.edit_point_condition()
        point=e._editable_parent()['points'][1];point[:]=point[:2]+[1,0,[point[:2]+[60]]]
        e.wait_edit=False;e._refresh_properties()
        self.assertEqual('disabled',str(e.defense_add.cget('state')))

    def test_delete_requires_all_classes_and_custom_delete_is_complete(self):
        e=self.route();e.add_defense();identity=e.selection[1]
        e.network_mode='';e.delete_item();self.assertIsNotNone(e._selected_parent())
        e.route_class_var.set('all');e._refresh_properties()
        with mock.patch('bot_tactics_ui.messagebox.askyesno',return_value=True):e.delete_item()
        self.assertFalse(any(r['id']==identity for r in e.entry()['routes']))

    def test_tier_buttons_and_default_restoration_preserve_custom_routes(self):
        e=self.route();e.set_tier('reserve')
        self.assertEqual('reserve',e._selected_parent()['tier'])
        self.assertEqual('disabled',str(e.tier_buttons['reserve'].cget('state')))
        original=copy.deepcopy(e.entry()['routes'])
        with mock.patch('bot_tactics_connections.messagebox.askyesno',return_value=True):e.route_restore_menu.invoke(1)
        self.assertEqual(original,e.entry()['routes'])
        self.assertEqual(storage.contract.default_map(e.map_name)['default_routes'],e.entry()['default_routes'])

    def test_connection_roundtrip_and_clone_rebind(self):
        e=self.route();e.add_defense();e.network_mode=''
        e.network_mode='defense';e.save(True)
        self.assertFalse(e.dirty());self.assertFalse(self.errors.called)
        loaded=self.store.active();row=loaded['maps'][e.map_name]['routes'][0]
        self.assertIn('defense',row)
        clone=route_network.clone_route(row)
        self.assertNotEqual(row['defense']['junction'],clone['defense']['junction'])

    def test_all_scope_rebinds_each_class_by_actual_junction_not_array_index(self):
        e=self.editor;e.route_class_var.set('all');e.change_route_class();e.new_route();e.insert_point()
        source=e._editable_parent();source['family']=source['id']
        peer=route_network.clone_route(source);peer.update(id='class_copy',classes=['heavyTank'],family=source['id'])
        source['classes'].remove('heavyTank');route_network.insert_node(peer,1,[(source['points'][0][0]+source['points'][1][0])*.5,(source['points'][0][1]+source['points'][1][1])*.5,0])
        e.entry()['routes'].append(peer);e.selected_point=1;e._refresh_properties();e.add_defense()
        self.assertEqual(route_network.nodes(peer)[2],peer['defense']['junction'])
        self.assertEqual(source['defense']['points'],peer['defense']['points'])

    def test_long_connection_cannot_create_waits_or_touch_main_geometry(self):
        e=self.route();e.add_defense();parent=copy.deepcopy(e._selected_parent()['points'])
        for unused in range(4):e.selected_point=0;e.insert_point()
        e.selected_point=4;e._refresh_properties();e.toggle_hold()
        self.assertEqual(parent,e._selected_parent()['points'])
        self.assertTrue(all(p[2]==0 for p in e._selected()['points']))
        self.assertEqual('disabled',str(e.hold_button.cget('state')))

    def test_route_toolbar_stays_inside_minimum_width(self):
        e=self.editor;self.root.deiconify();self.root.geometry('1200x800');self.root.update()
        for button in (e.route_delete_button,e.tier_buttons['main'],e.tier_buttons['reserve']):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width()+2)

    def test_toolbar_order_languages_and_restore_default_lock(self):
        e=self.editor
        expected=[('新建路线','New route'),('新建炮位','New SPG'),('复制','Duplicate'),
                  ('删除','Delete'),('撤销','Undo'),('重做','Redo'),
                  ('转换为主要路线','Make main'),('转换为备用路线','Make reserve'),
                  ('检查本图','Check map'),('适应窗口','Fit view'),('导入地图','Load image'),
                  ('恢复','Restore')]
        widgets=sorted(e.route_toolbar.winfo_children(),key=lambda w:(int(w.grid_info()['row']),int(w.grid_info()['column'])))
        self.assertEqual(12,len(widgets))
        before=copy.deepcopy(e.document)
        for language in ('en','zh'):
            e.set_language(language)
            self.assertEqual([pair[0 if language=='zh' else 1] for pair in expected],
                             [str(w.cget('text')) for w in widgets])
            self.assertEqual([(i//6,i%6) for i in range(12)],
                             [(int(w.grid_info()['row']),int(w.grid_info()['column'])) for w in widgets])
            self.assertEqual(e.tr('恢复本路线','Reset route'),e.route_restore_menu.entrycget(0,'label'))
            self.assertEqual(e.tr('恢复默认路线','Restore default routes'),e.route_restore_menu.entrycget(1,'label'))
        self.assertEqual(before,e.document)
        e.adopt(storage.contract.default_profile())
        self.assertEqual('disabled',str(e.route_restore_button.cget('state')))
        e.adopt(storage.contract.empty('Editable again'))
        self.assertEqual('normal',str(e.route_restore_button.cget('state')))

    def test_spg_parking_is_automatic_and_attack_remains_separate(self):
        e=self.editor;e.route_class_var.set('SPG');e.change_route_class();e.new_position()
        self.assertNotIn('travel',e._selected_parent());self.assertNotIn('links',e._selected_parent())
        self.assertFalse(hasattr(e,'network_box'))
        e.new_route();self.assertEqual('spg_attack',e._selected_parent()['purpose'])
        self.assertEqual('disabled',str(e.defense_add.cget('state')))

    def shared_routes(self, separate_junction=False):
        e=self.editor;e.route_class_var.set('all');e.change_route_class();e.new_route();e.insert_point()
        source=e._editable_parent();source['family']=source['id']
        peer=route_network.clone_route(source);peer.update(id='heavy_variant',classes=['heavyTank'],family=source['id'])
        source['classes'].remove('heavyTank')
        if separate_junction:peer['points'][1][0]+=12
        for row in (source,peer):
            ids=route_network.ensure_nodes(row)
            base=e.graph_cache[e.map_name]['objective_bases'][e.team-1]
            row['defense']=dict(junction=ids[1],points=[row['points'][1][:2]+[0],list(base)+[0]])
        e.entry()['routes'].append(peer);e.network_mode='defense';e.selected_point=0;e._refresh_items()
        return e,source['id'],peer['id']

    def test_shared_then_total_single_class_then_shared_last_edit_wins(self):
        e,source_id,peer_id=self.shared_routes()
        before=copy.deepcopy(e.document);e.insert_point();self.root.update()
        self.assertEqual('defense',e.network_mode)
        self.assertFalse(self.errors.called)
        source=next(r for r in e.entry()['routes'] if r['id']==source_id)
        peer=next(r for r in e.entry()['routes'] if r['id']==peer_id)
        self.assertEqual(source['defense']['points'],peer['defense']['points'])
        shared=copy.deepcopy(e.document);e.undo('maps');self.assertEqual(before,e.document)
        e.redo('maps');self.assertEqual(shared,e.document)
        e.route_class_var.set('total');e.change_route_class();e.selection=('routes',peer_id+'@heavyTank')
        e.network_mode='defense';e.selected_point=0;e._refresh_items();e.insert_point()
        source=next(r for r in e.entry()['routes'] if r['id']==source_id)
        peer=next(r for r in e.entry()['routes'] if r['id']==peer_id)
        self.assertEqual(3,len(source['defense']['points']));self.assertEqual(4,len(peer['defense']['points']))
        e.route_class_var.set('all');e.change_route_class();e.selection=('routes',source_id)
        e.network_mode='defense';e.selected_point=0;e._refresh_items();e.insert_point()
        peer=next(r for r in e.entry()['routes'] if r['id']==peer_id)
        self.assertEqual(e._selected_parent()['defense']['points'],peer['defense']['points'])
        e.save(True);self.assertFalse(self.errors.called);self.assertEqual(e.document,self.store.active())

    def test_individual_class_edit_splits_shared_custom_route_without_losing_selection(self):
        e,source_id,peer_id=self.shared_routes()
        before=copy.deepcopy(e.entry()['routes'])
        e.route_class_var.set('lightTank');e.change_route_class()
        e.selection=('routes',source_id);e.network_mode='defense';e.selected_point=0;e._refresh_items()
        e.insert_point();self.root.update()
        self.assertIsNotNone(e.selection);self.assertEqual('defense',e.network_mode)
        self.assertEqual(['lightTank'],e._selected_parent()['classes'])
        self.assertEqual(3,len(e._selected_parent()['defense']['points']))
        original=next(r for r in e.entry()['routes'] if r['id']==source_id)
        self.assertEqual(2,len(original['defense']['points']))
        self.assertNotIn('lightTank',original['classes'])
        self.assertFalse(self.errors.called)

    def test_shared_edit_keeps_each_stable_junction_and_other_main_geometry(self):
        e,source_id,peer_id=self.shared_routes(True)
        peer=next(r for r in e.entry()['routes'] if r['id']==peer_id)
        original=copy.deepcopy(peer);e.insert_point()
        self.assertEqual(original['points'],peer['points'])
        self.assertEqual(original['defense']['junction'],peer['defense']['junction'])
        self.assertEqual(peer['points'][1][:2],peer['defense']['points'][0][:2])
        self.assertEqual(e._selected_parent()['defense']['points'][1:],peer['defense']['points'][1:])

    def test_shared_delete_and_undo_cover_every_variant(self):
        e,source_id,peer_id=self.shared_routes();before=copy.deepcopy(e.document)
        e.delete_defense();self.assertTrue(all('defense' not in r for r in e.entry()['routes']))
        e.undo('maps');self.assertEqual(before,e.document)
        e.redo('maps');self.assertTrue(all('defense' not in r for r in e.entry()['routes']))

    def test_shared_failure_restores_entire_draft_history_and_selection(self):
        e,source_id,peer_id=self.shared_routes(True)
        peer=next(r for r in e.entry()['routes'] if r['id']==peer_id);peer.pop('defense')
        before=copy.deepcopy(e.document);history=copy.deepcopy(e.histories);selection=e.selection
        e.insert_point()
        self.assertTrue(self.errors.called);self.assertEqual(before,e.document)
        self.assertEqual(history,e.histories);self.assertEqual(selection,e.selection)

    def test_symmetry_copies_defense_to_other_team_only_when_enabled(self):
        e,source_id,peer_id=self.shared_routes();source=e._editable_parent()
        counterpart=route_network.clone_route(source);counterpart.update(id='team_two',team=2,family='other_family',mirror_id=source_id)
        source['mirror_id']=counterpart['id'];e.entry()['routes'].append(counterpart)
        base=e.graph_cache[e.map_name]['objective_bases'][1]
        counterpart['defense']['points'][-1]=list(base)+[0]
        before=copy.deepcopy(counterpart);e.insert_point();self.assertEqual(before,counterpart)
        source['symmetric']=True;e._refresh_properties();e.selected_point=0;e.insert_point()
        self.assertEqual(len(source['defense']['points']),len(counterpart['defense']['points']))
        self.assertEqual(list(base),counterpart['defense']['points'][-1][:2])
        after=copy.deepcopy(e.document);e.undo('maps');e.redo('maps');self.assertEqual(after,e.document)
        self.assertFalse(self.errors.called)

    def test_unexpected_shared_sync_failure_rolls_back_the_whole_transaction(self):
        e,source_id,peer_id=self.shared_routes();before=copy.deepcopy(e.document)
        history=copy.deepcopy(e.histories)
        with mock.patch.object(e,'_copy_defense',side_effect=RuntimeError('fixture sync failed')):
            e.insert_point()
        self.assertEqual(before,e.document);self.assertEqual(history,e.histories)
        self.assertTrue(self.errors.called)

    def test_view_switch_is_read_only_and_default_remains_locked(self):
        e,source_id,peer_id=self.shared_routes();before=copy.deepcopy(e.document)
        for scope in ('all','total','heavyTank','all'):
            e.route_class_var.set(scope);e.change_route_class()
        self.assertEqual(before,e.document)
        e.adopt(storage.contract.default_profile())
        self.assertEqual('disabled',str(e.defense_add.cget('state')))


if __name__=='__main__':unittest.main()
