"""A native Lakeville van hit must not inherit an authored absent-slot gate."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import test_port_0922_destructibles as fixture

d = fixture.destructibles_sensor


class ContactedLayoutTests(unittest.TestCase):
    def setUp(self):
        patcher=mock.patch.object(d,'xrange',range,create=True)
        patcher.start();self.addCleanup(patcher.stop)
        d.set_catalog(json.loads((Path(__file__).resolve().parents[1] /
                                 'destructibles/07_lakeville.json').read_text()))
        self.catalog=d._destructible_catalog
        self.record=self.catalog['baked_instances'][(33149,188)]
        self.catalog['excluded_instances'].add((33149,189))
        self.catalog['baked_instances'].pop((33149,189),None)
        self.manager=fixture._Manager()
        self.manager.space_id=1
        self.manager.set_chunk_count(33149,222)
        self.area=types.ModuleType('AreaDestructibles')
        self.area.g_destructiblesManager=self.manager
        self.area.DESTR_TYPE_FRAGILE=2
        self.area.g_cache=types.SimpleNamespace(getDescByFilename=lambda name:dict(type=2,health=20))
        self.bigworld=types.ModuleType('BigWorld')
        self.bigworld.wg_getChunkMatrix=lambda *args:types.SimpleNamespace(translation=fixture._Vector())
        self.bigworld.wg_getDestructibleMatrix=mock.Mock(return_value=
            fixture._CatalogSignatureMatrix(self.record['signature']))
        self.bigworld.wg_getDestructibleEffectCategory=lambda *args:2
        math_module=types.ModuleType('Math')
        math_module.Matrix=lambda value:value
        math_module.Vector3=fixture._Vector
        patcher=mock.patch.dict(sys.modules,{'BigWorld':self.bigworld,
            'AreaDestructibles':self.area,'Math':math_module})
        patcher.start();self.addCleanup(patcher.stop)
        for name,value in (('_item_name_query_allowance_1513',1),
                           ('_chunk_native_name_list_1513',(('',)*222,'ready'))):
            patcher=mock.patch.object(d,name,return_value=value)
            patcher.start();self.addCleanup(patcher.stop)
        patcher=mock.patch.object(sys,'stdout',mock.Mock())
        patcher.start();self.addCleanup(patcher.stop)
        self.saved={name:d.__dict__.get(name) for name in
                    ('g_offh_destr_isolated_slots','g_offh_destr_isolated_chunks')}
        d.g_offh_destr_isolated_slots={(33149,188)}
        d.g_offh_destr_isolated_chunks=set()
        self.addCleanup(self.restore)

    def restore(self):
        d.set_catalog(None)
        for name,value in self.saved.items():
            if value is None:d.__dict__.pop(name,None)
            else:setattr(d,name,value)

    def test_exact_contact_rehomes_omitted_van_and_preserves_quarantine(self):
        self.assertTrue(d._recover_contacted_model_slot_1513(1,(33149,189)))
        self.assertFalse(d.is_excluded_1513(33149,189))
        self.assertEqual(self.record,self.catalog['baked_instances'][(33149,189)])
        self.assertTrue(d.is_isolated_1513(33149,188))
        self.assertEqual((33149,189),self.catalog['instances'][self.record['signature']]['wire'])
        self.assertEqual(self.record['descriptor_filename'],
            d.g_offh_destr_proved_layouts[(1,33149)][1][189])
        instance=d._stream_baked_shot_instance_1513(1,(33149,189))
        self.assertIsNotNone(instance)
        point=fixture._Vector(209.28936767578125,-3.620638847351074,-151.54971313476562)
        payload=(True,point,fixture._Vector(0,1,0),73,'',189,33149)
        named=d._recover_contact_material_1513(1,payload,point)
        self.assertEqual(self.record['descriptor_filename'],named[4])
        self.assertEqual((189,33149),named[5:7])

    def test_active_duplicate_owner_is_not_guessed_away(self):
        d.g_offh_destr_isolated_slots=set()
        self.assertFalse(d._recover_contacted_model_slot_1513(1,(33149,189)))
        self.assertTrue(d.is_excluded_1513(33149,189))

    def test_quarantined_live_slot_is_never_queried(self):
        d.g_offh_destr_isolated_slots.add((33149,189))
        self.assertFalse(d._recover_contacted_model_slot_1513(1,(33149,189)))
        self.bigworld.wg_getDestructibleMatrix.assert_not_called()

    def test_wrong_full_transform_does_not_register_or_destroy(self):
        signature=list(self.record['signature']);signature[3]+=20
        self.bigworld.wg_getDestructibleMatrix.return_value=fixture._CatalogSignatureMatrix(signature)
        self.assertFalse(d._recover_contacted_model_slot_1513(1,(33149,189)))
        self.assertTrue(d.is_excluded_1513(33149,189))

    def test_named_or_off_contact_material_needs_no_layout_probe(self):
        point=fixture._Vector(209.,-3.6,-151.5)
        for payload,contact in (( (True,point,fixture._Vector(0,1,0),73,'van.model',189,33149),point),
                ((True,point,fixture._Vector(0,1,0),73,'',189,33149),fixture._Vector(210,-3.6,-151.5))):
            with mock.patch.object(d,'_recover_contacted_model_slot_1513') as recover:
                self.assertEqual(payload,d._recover_contact_material_1513(1,payload,contact))
                recover.assert_not_called()


if __name__=='__main__':unittest.main()
