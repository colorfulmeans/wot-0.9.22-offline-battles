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
        with mock.patch('bot_tactics_connections.messagebox.askyesno',return_value=True):e.restore_default_routes()
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

    def test_spg_deploy_connection_and_attack_endpoints_are_separate(self):
        e=self.editor;e.route_class_var.set('SPG');e.change_route_class();e.new_position()
        e.press(SimpleNamespace(x=e.view.screen((20,20))[0],y=e.view.screen((20,20))[1],state=0))
        zone=e._selected_parent()
        self.assertEqual(zone['point'],zone['travel'][-1][:2])
        e.network_choices=[('deploy','travel','')];e.network_box.configure(values=['deploy']);e.network_box.current(0)
        e.choose_network();e.selected_point=0;e.insert_point()
        self.assertEqual(3,len(e._selected()['points']))
        e.network_mode='';e.new_route()
        self.assertEqual('spg_attack',e._selected_parent()['purpose'])
        self.assertEqual(['SPG'],e._selected_parent()['classes'])


if __name__=='__main__':unittest.main()
