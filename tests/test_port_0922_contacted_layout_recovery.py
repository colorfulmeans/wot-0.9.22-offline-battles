"""Fixed raw WGDE slots enter ordinary native registration without reindexing."""
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
        self.record=self.catalog['baked_instances'][(33149,189)]
        self.manager=fixture._Manager()
        self.manager.space_id=1
        self.manager.set_chunk_count(33149,222)
        self.area=types.ModuleType('AreaDestructibles')
        self.area.g_destructiblesManager=self.manager
        self.area.DESTR_TYPE_FRAGILE=2
        self.area.DESTR_TYPE_TREE=0
        self.area.DESTR_TYPE_FALLING_ATOM=1
        self.area.DESTR_TYPE_STRUCTURE=3
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
                    ('g_offh_destr_isolated_slots','g_offh_destr_isolated_chunks',
                     'g_offh_destr_isolation_reasons')}
        d.g_offh_destr_isolated_slots=set()
        d.g_offh_destr_isolated_chunks=set()
        d.g_offh_destr_isolation_reasons={}
        self.addCleanup(self.restore)

    def restore(self):
        d.set_catalog(None)
        for name,value in self.saved.items():
            if value is None:d.__dict__.pop(name,None)
            else:setattr(d,name,value)

    def test_van_is_in_the_native_slot_before_any_contact(self):
        self.assertTrue(d.is_excluded_1513(33149,188))
        self.assertFalse(d.is_excluded_1513(33149,189))
        self.assertIn('van',self.record['filename'].lower())
        name=d._resolve_catalog_model_name_1513(self.bigworld,self.area,1,33149,189,222,('',)*222)
        self.assertEqual(self.record['descriptor_filename'],name)
        self.bigworld.wg_getDestructibleMatrix.assert_called_once_with(1,33149,189)
        # The normal shot instance path consumes exactly that baked slot.
        instance=d._stream_baked_shot_instance_1513(1,(33149,189))
        self.assertIsNotNone(instance)
        self.assertEqual(self.record,self.catalog['baked_instances'][(33149,189)])

    def test_quarantined_slot_cannot_be_reproved_or_remapped(self):
        d._isolate_destructible_1513('native_failure',33149,189)
        self.assertIsNone(d._resolve_catalog_model_name_1513(self.bigworld,self.area,1,33149,189,222,()))
        self.bigworld.wg_getDestructibleMatrix.assert_not_called()
        self.assertFalse(hasattr(d,'_recover_contact_material_1513'))
        self.assertFalse(hasattr(d,'_commit_proved_chunk_layout_1513'))

    def test_fixed_van_slot_enters_normal_crush_commit(self):
        self.area.g_cache.unitVehicleMass=10000.
        self.area.g_cache.getDescByFilename=lambda name:dict(type=2,health=20,kineticDamageCorrection=0.)
        cache=types.ModuleType('DestructiblesCache')
        cache.scaledDestructibleHealth=lambda scale,health:scale*health
        hull=fixture._Strict1513Component(hitTester=types.SimpleNamespace(
            bbox=((-1.7,-1.,-3.7),(1.7,1.5,3.7),None)))
        descriptor=fixture._Strict1513Component(physics={'weight':57000.},hull=hull)
        authority=types.SimpleNamespace(is_destroyed=lambda *args:False,
            destroy_fragile=mock.Mock(return_value=True))
        d.set_event_sink(lambda event:True)
        self.addCleanup(d.set_event_sink,None)
        centre=fixture._Vector(*(x/1000. for x in self.record['signature'][:3]))
        with mock.patch.dict(sys.modules,{'DestructiblesCache':cache}),mock.patch.object(d,'_get_destr_authority',return_value=authority):
            detail=d._catalog_motion_blocked(1,centre,0.,3.3,descriptor,10.,dt=.05,
                return_detail=True,commit_enabled=True)
        self.assertEqual('crushed',detail['status'])
        self.assertEqual(((33149,189,None),),detail['token'])
        authority.destroy_fragile.assert_called_once()
        self.assertTrue(d.is_excluded_1513(33149,188))

    def test_wrong_transform_is_not_reassigned_to_a_nearby_slot(self):
        signature=list(self.record['signature']);signature[0]+=20000
        self.bigworld.wg_getDestructibleMatrix.return_value=fixture._CatalogSignatureMatrix(signature)
        self.assertIsNone(d._resolve_catalog_model_name_1513(self.bigworld,self.area,1,33149,189,222,()))
        self.assertEqual(self.record,self.catalog['baked_instances'][(33149,189)])
        self.assertNotIn((33149,188),self.catalog['baked_instances'])

    def test_chunk_lifetime_retires_isolation_provenance(self):
        d._isolate_destructible_1513('native_failure',33149,189)
        d._isolate_destructible_1513('native_count_abi',123)
        d.retire_chunk_identity_1513(33149)
        self.assertNotIn((33149,189),d.g_offh_destr_isolation_reasons)
        self.assertIn((123,None),d.g_offh_destr_isolation_reasons)


if __name__=='__main__':unittest.main()
