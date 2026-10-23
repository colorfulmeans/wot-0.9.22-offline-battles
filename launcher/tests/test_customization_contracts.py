"""Real Tk protection/reset and native packed burst authoring regressions."""
import copy
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest import mock
import bot_tactics_ui as ui
import bot_tactics_store as storage
import vehicle_overlays as overlays
import test_vehicle_overlays as fixture

class ProfileProtectionTests(unittest.TestCase):
    def test_storage_default_cannot_be_overwritten_and_old_debug_default_is_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            store=storage.Store(directory)
            debug=storage.contract.default_profile();debug['behavior']=[dict(team=0,class_tag='all',slot=-1,values={'skill':'elite'})]
            storage._atomic(store.active_path,debug)
            self.assertEqual(storage.contract.default_profile(),store.active())
            with self.assertRaises(storage.contract.TacticsError):store.save(debug)
            self.assertEqual('Default1',store.unique_name('Default'))
            custom=storage.contract.default_profile('Default1');store.save(custom)
            self.assertEqual('Default2',store.unique_name('Default'))
            store.save(custom);self.assertEqual(['Default','Default1'],store.names())
    def test_preview_ignores_binary_geometry_and_uses_the_selected_ratio(self):
        from gui.mods.offline_lan_0922 import bot_fittings
        packed=overlays.packed_xml
        def pack(value):
            if isinstance(value,dict):return packed.PackedValue(packed.TYPE_ELEMENT,packed.PackedElement(children=[(k.encode(),pack(v)) for k,v in value.items()]))
            if isinstance(value,bytes):return packed.PackedValue(packed.TYPE_VECTOR,value)
            return packed.PackedValue(packed.TYPE_STRING,str(value).encode())
        documents={
            'ussr/R77_KV2.xml':dict(turrets0=dict(T=dict(guns=dict(G={}))),geometry=bytes([144,0,0,0])),
            'ussr/components/guns.xml':dict(shared=dict(G=dict(shots=dict(AP={},HE={}),maxAmmo=20))),
            'ussr/components/shells.xml':dict(AP=dict(kind='ARMOR_PIERCING'),HE=dict(kind='HIGH_EXPLOSIVE')),
            'ussr/list.xml':dict(R77_KV2=dict(price=100)),
        }
        def read(package,member):return b'',pack(documents[member.split('vehicles/',1)[1]]).value
        with mock.patch.object(overlays,'_read_source_member',side_effect=read),mock.patch.object(overlays,'_vehicle_translations',return_value=None),mock.patch.object(bot_fittings,'plan',return_value=dict(modules=dict(turret='T',gun='G'))):
            preview=storage.ammunition_preview('fixture','ussr:R77_KV2',{},[0,9])
            self.assertEqual([0,20],preview['counts'])
            inherited=storage.ammunition_preview('fixture','ussr:R77_KV2',{})
            self.assertEqual([16,4],inherited['counts'])
            empty=storage.ammunition_preview('fixture','ussr:R77_KV2',{},[0,0])
            self.assertEqual([0,0],empty['counts'])

    def test_burst_nodes_are_materialized_only_for_the_requested_gun(self):
        f=fixture.VehicleOverlayTest();f.setUp();self.addCleanup(f.doCleanups)
        overlays.create_vehicle_profile(f.game,'Burst')
        fields=overlays.list_vehicle_profile_field_choices(f.game,'Burst',f.VEHICLE)
        self.assertTrue(any(row['fieldPath']=='shared/Gun-A/burst/count' for row in fields))
        result=overlays.apply_profile_edit(f.game,'Burst',f.GUNS,'shared/Gun-A/burst/count','2')
        self.assertEqual('2',result['currentValue'])
        result=overlays.apply_profile_edit(f.game,'Burst',f.GUNS,'shared/Gun-A/burst/rate','600')
        self.assertEqual('600',result['currentValue'])
        for raw in ('0','65','2.5'):
            with self.assertRaises(overlays.VehicleOverlayError):overlays.apply_profile_edit(f.game,'Burst',f.GUNS,'shared/Gun-A/burst/count',raw)
        with self.assertRaises(overlays.VehicleOverlayError):overlays.apply_profile_edit(f.game,'Burst',f.GUNS,'shared/Gun-A/burst/rate','1')
        current=overlays.inspect_profile_field(f.game,'Burst',f.GUNS,'shared/Gun-A/burst/rate')
        self.assertEqual('600',current['currentValue'])

@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'requires actual Tk display')
class EditorProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.editor=ui.BotTacticsEditor(self.root,store=storage.Store(self.temp.name))
    def test_name_text_and_undo_do_not_unlock_default(self):
        e=self.editor;before=copy.deepcopy(e.document)
        e.profile_name.set('Edited');e.rule_vars['skill'].set('elite');e.save_rule();e.new_route();e.undo();e.redo();e.save()
        self.assertEqual(before,e.document)
        self.assertEqual('disabled',str(e.save_button.cget('state')))
        self.assertEqual('disabled',str(e.restore_button.cget('state')))
        self.assertEqual(['Default'],e.store.names())
    def test_restore_keeps_custom_name_resets_pending_fields_and_history(self):
        e=self.editor;e.adopt(storage.contract.default_profile('Custom'))
        e.rule_vars['reaction_seconds'].set('0.125');e.ammo_vars[0].set('9');e.wait_seconds.set('123')
        e.document['behavior']=[dict(team=0,class_tag='all',slot=-1,values={'skill':'elite'})]
        e.checkpoint()
        with mock.patch.object(e,'discard_prompt',return_value=True):e.default_profile()
        self.assertEqual(storage.contract.default_profile('Custom'),e.document)
        self.assertEqual('',e.rule_vars['reaction_seconds'].get());self.assertEqual(['','',''],[v.get() for v in e.ammo_vars])
        self.assertEqual('60',e.wait_seconds.get());self.assertEqual([],e.undo_stack);self.assertEqual([],e.redo_stack)
        e.undo();self.assertEqual('Custom',e.document['name'])
    def test_import_name_collision_is_renamed_without_replacing_default(self):
        e=self.editor;source=Path(self.temp.name)/'import.json';storage._atomic(source,storage.contract.default_profile())
        for expected in ('Default1','Default2'):
            with mock.patch.object(ui.filedialog,'askopenfilename',return_value=str(source)),mock.patch.object(e,'discard_prompt',return_value=True):e.import_profile()
            self.assertEqual(expected,e.document['name']);e.save()
        self.assertEqual(storage.contract.default_profile(),e.store.read('Default'))
    def test_leaving_a_two_shell_pinned_vehicle_reenables_generic_ratios(self):
        e=self.editor;e.adopt(storage.contract.default_profile('Custom'))
        e.lineup=lambda:[dict(team=1,slot=0,vehicle='ussr:R77_KV2')]
        e.rule_vars['team'].set('1');e.rule_vars['slot'].set('1')
        preview=dict(vehicle='ussr:R77_KV2',gun='G',shells=[dict(name='A',index=0),dict(name='B',index=1)])
        with mock.patch.object(storage,'ammunition_preview',return_value=preview):e._refresh_ammunition()
        self.assertEqual('disabled',str(e.ammo_boxes[2].cget('state')))
        e.rule_vars['slot'].set('');e._refresh_ammunition()
        self.assertEqual(['readonly']*3,[str(box.cget('state')) for box in e.ammo_boxes])
        self.assertEqual((),e._ammo_identity)

    def test_packaged_editor_verifier_forks_default_and_exercises_the_new_presets(self):
        import bot_tactics_smoke
        destination=Path(self.temp.name)/'smoke.json'
        self.assertEqual(0,bot_tactics_smoke.run(destination),destination.read_text() if destination.exists() else 'no report')
        report=json.loads(destination.read_text())
        self.assertTrue(report['default_readonly']);self.assertTrue(report['independent_presets_and_empty_ammo'])

    def test_stock_only_offers_no_equipment_and_restores_choices_after_leaving_stock(self):
        e=self.editor;e.adopt(storage.contract.default_profile('Custom'))
        e.rule_vars['equipment'].set('improved');e.rule_vars['development'].set('stock');e._refresh_equipment_choices()
        self.assertEqual('none',e.rule_vars['equipment'].get());self.assertEqual(('none',),e.rule_boxes['equipment'].keys)
        e.rule_vars['development'].set('full');e._refresh_equipment_choices()
        self.assertEqual('none',e.rule_vars['equipment'].get());self.assertIn('improved',e.rule_boxes['equipment'].keys)
        e.rule_vars['equipment'].set('improved');e.rule_vars['development'].set('stock');e._refresh_equipment_choices();e.save_rule();e.save()
        values=storage.contract.effective(e.store.read('Custom'),1,'heavyTank',0)
        self.assertEqual('none',values['equipment']);self.assertEqual('stock',values['development'])

    def test_numeric_forms_are_readonly_and_keep_imported_fraction(self):
        e=self.editor;e.adopt(storage.contract.default_profile('Custom'))
        for box in list(e.rule_boxes.values())+e.ammo_boxes:self.assertEqual('readonly',str(box.cget('state')))
        e.document['behavior']=[dict(team=0,class_tag='all',slot=-1,values={'reaction_seconds':0.125})]
        e._refresh_rules();e.rules.selection_set('0');e._select_rule()
        self.assertIn('0.125',e.rule_boxes['reaction_seconds'].keys)

if __name__=='__main__':unittest.main()
