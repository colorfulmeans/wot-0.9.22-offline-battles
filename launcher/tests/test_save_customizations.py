import base64
import copy
import json
import os
import tempfile
import unittest
import zipfile
from unittest import mock
import save_customizations as store


VEHICLES = [dict(name='china:Tank8', compact_descr=101, nation='china', level=8, tags=['premium']),
            dict(name='china:Tank1', compact_descr=102, nation='china', level=1, tags=[]),
            dict(name='usa:Tank10', compact_descr=103, nation='usa', level=10, tags=[])]
STYLES = [dict(id=1, rent_count=100, rules=[('include', {'nations':['china']})]),
          dict(id=128, rent_count=0, hidden=True, rules=[('include', {'nations':['china'], 'levels':['8'], 'tags':['premium']})])]


class StyleInventoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = temp.name; self.slot = 'default'; self.game = 'client'
        self.path = store.save_ledger.ledger_path(self.slot, self.game, root=self.root)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def read(self):
        return store.read_inventory(self.slot, self.game, STYLES, VEHICLES, root=self.root)

    def test_unlocked_default_stock_is_exactly_one_copy_per_compatible_vehicle(self):
        stock = self.read()['4']
        self.assertEqual({'101':100, '102':100}, stock['1'])
        self.assertEqual({'101':1}, stock['128'])
        self.assertFalse(os.path.exists(self.path))

    def test_career_does_not_receive_automatic_styles(self):
        p = store.save_slots.metadata_path(self.slot, self.game, root=self.root)
        store.save_ledger._write_state(p, {'mode':'new_account'})
        self.assertEqual({}, self.read())

    def test_hidden_grant_preserves_wallet_vehicle_and_other_customizations(self):
        state = {'ledger':{'wallet':{'gold':70}, 'styleStockVersion':1,
                          'customizations':{'2':{'5':{'0':3}}}}, 'vehicles':{'101':{'crew':[3]}}}
        store.save_ledger._write_state(self.path, state)
        stock = self.read()
        store.add_style(stock, STYLES[1], VEHICLES, 2)
        store.write_inventory(self.slot, self.game, stock, root=self.root, is_running=lambda:False)
        saved = store.save_ledger._read_state(self.path)
        self.assertEqual(state['vehicles'], saved['vehicles'])
        self.assertEqual(state['ledger']['wallet'], saved['ledger']['wallet'])
        self.assertEqual({'5':{'0':3}}, saved['ledger']['customizations']['2'])
        self.assertEqual({'101':2}, saved['ledger']['customizations']['4']['128'])

    def test_default_topup_counts_only_this_garages_owned_compatible_hulls(self):
        store.save_ledger._write_state(self.path, {'vehicles':{'101':{}},'ledger':{}})
        self.assertEqual({'101':100}, self.read()['4']['1'])

    def test_style_receipts_include_actual_deltas_and_noop_save_does_not_repeat(self):
        for garage in (False,True):
            with self.subTest(garage=garage):
                if garage:store.save_ledger._write_state(self.path,{'vehicles':{'101':{}},'ledger':{}})
                stock={'4':{'128':{'101':2}}}
                store.write_inventory(self.slot,self.game,stock,root=self.root,is_running=lambda:False)
                path=self.path if garage else store.save_slots.metadata_path(self.slot,self.game,root=self.root)
                saved=store.save_ledger._read_state(path)
                notices=(saved['ledger']['personalMissions']['notifications'] if garage else saved['initial_account_notifications'])
                self.assertEqual([{'phase':'granted','rewards':[{'kind':'style','id':128,'count':2}]}],notices[0]['settlement']['account_changes'])
                store.write_inventory(self.slot,self.game,stock,root=self.root,is_running=lambda:False)
                saved=store.save_ledger._read_state(path)
                repeated=saved['ledger']['personalMissions']['notifications'] if garage else saved['initial_account_notifications']
                self.assertEqual(notices,repeated)
                store.write_inventory(self.slot,self.game,{},root=self.root,is_running=lambda:False)
                saved=store.save_ledger._read_state(path)
                rows=saved['ledger']['personalMissions']['notifications'] if garage else saved['initial_account_notifications']
                self.assertEqual('revoked',rows[-1]['settlement']['account_changes'][0]['phase'])

    def test_initial_edit_survives_and_version_prevents_replenishing_used_stock(self):
        stock = self.read(); stock['4']['1']['101'] = 17
        store.write_inventory(self.slot, self.game, stock, root=self.root, is_running=lambda:False)
        self.assertEqual(17, self.read()['4']['1']['101'])
        self.assertFalse(os.path.exists(self.path))
        p=store.save_slots.metadata_path(self.slot, self.game, root=self.root)
        saved=store.save_ledger._read_state(p)
        self.assertEqual(stock,saved['initial_customizations'])
        self.assertEqual(1,saved['styleStockVersion'])

    def test_rental_add_uses_native_battle_count_and_ignores_incompatible_vehicle(self):
        stock={}
        self.assertEqual(2,store.add_style(stock,STYLES[0],VEHICLES,3))
        self.assertEqual({'101':300,'102':300},stock['4']['1'])

    def test_incompatible_or_invalid_quantity_is_atomic(self):
        stock={}
        for count, vehicles in ((0,VEHICLES),(100001,VEHICLES),(True,VEHICLES),(1,VEHICLES[1:])):
            with self.assertRaises(store.save_ledger.SaveLedgerError):
                store.add_style(stock,STYLES[1],vehicles,count)
            self.assertEqual({},stock)

    def test_running_game_cannot_be_overwritten(self):
        with self.assertRaises(store.save_ledger.SaveLedgerError):
            store.write_inventory(self.slot,self.game,self.read(),root=self.root,is_running=lambda:True)
        self.assertFalse(os.path.exists(self.path))

    def test_exclusion_overrides_matching_include(self):
        style=copy.deepcopy(STYLES[0]);style['rules'].append(('exclude',{'vehicles':['china:Tank8']}))
        self.assertFalse(store.compatible(style,VEHICLES[0]))
        self.assertTrue(store.compatible(style,VEHICLES[1]))

    def test_packed_catalogue_loads_hidden_flag_and_native_vehicle_id(self):
        p=store.vehicle_overlays.packed_xml
        def text(s):return p.PackedValue(1,s.encode())
        def number(n):return p.PackedValue(2,n)
        def section(children):return p.PackedValue(0,p.PackedElement(children=children))
        def packed(children):return p.write_packed_xml(p.PackedElement(children=children))
        group=section([(b'priceGroup',text('hidden')),
            (b'vehicleFilter',section([(b'include',section([(b'nations',text('china'))]))])),
            (b'style',section([(b'id',number(128)),(b'userString',text('#vehicle_customization:test'))]))])
        price=section([(b'name',text('hidden')),(b'notInShop',p.PackedValue(5,base64.b64decode('True')))])
        package=os.path.join(self.root,'scripts.pkg')
        with zipfile.ZipFile(package,'w') as archive:
            archive.writestr('scripts/item_defs/customization/styles/list.xml',packed([(b'itemGroup',group)]))
            archive.writestr('scripts/item_defs/customization/priceGroups/styles.xml',packed([(b'priceGroup',price)]))
            archive.writestr('scripts/item_defs/vehicles/china/list.xml',packed([(b'Tank8',section([
                (b'id',number(13)),(b'price',section([(b'gold',text(''))]))]))]))
        vehicle=dict(VEHICLES[0],vehicle='Tank8',label='Tank8',tags=[])
        with mock.patch.object(store.vehicle_overlays,'_require_target',return_value=({'path':self.root},package)), \
             mock.patch.object(store.vehicle_overlays,'list_vehicle_choices',return_value=[vehicle]):
            styles,vehicles=store.catalogue(self.root)
        self.assertTrue(styles[0]['hidden'])
        self.assertEqual(1 | (3<<4) | (13<<8),vehicles[0]['compact_descr'])
        self.assertIn('premium',vehicles[0]['tags'])

    def test_invalid_saved_ownership_is_not_overwritten(self):
        state={'vehicles':{},'ledger':{'customizations':{'4':{'128':{'101':-1}}}}}
        store.save_ledger._write_state(self.path,state)
        with self.assertRaises(store.save_ledger.SaveLedgerError):self.read()
        self.assertEqual(state,store.save_ledger._read_state(self.path))


if __name__=='__main__':unittest.main()
