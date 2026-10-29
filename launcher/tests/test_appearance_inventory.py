"""Typed additions, durable notifications, and one-time sandbox seed ownership."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import save_customizations as store
import save_slots


class AppearanceTests(unittest.TestCase):
    def test_components_are_added_in_native_binding_units(self):
        vehicles = [dict(compact_descr=101, nation='ussr'), dict(compact_descr=102, nation='ussr')]
        item = dict(kind=2, id=77, rules=[], vehicle_bound=False)
        inventory = {}
        store.add_item(inventory, item, vehicles, 7)
        store.add_item(inventory, item, vehicles, 3)
        self.assertEqual({'0':10}, inventory['2']['77'])
        item.update(id=78, vehicle_bound=True)
        store.add_item(inventory, item, vehicles, 7)
        self.assertEqual({'101':7, '102':7}, inventory['2']['78'])
        before = copy.deepcopy(inventory)
        for count in (-1, 0, True, 1.5):
            with self.assertRaises(store.save_ledger.SaveLedgerError): store.add_item(inventory,item,vehicles,count)
        self.assertEqual(before,inventory)

    def test_new_unlocked_seed_is_explicit_and_existing_slots_are_not_migrated(self):
        with tempfile.TemporaryDirectory() as root:
            for mode, expected in ((save_slots.MODE_UNLOCKED,1),(save_slots.MODE_NEW_ACCOUNT,0)):
                slot=save_slots.create_slot(mode,mode,root=root)
                metadata=json.loads(Path(save_slots.metadata_path(slot['id'],root=root)).read_text())
                self.assertEqual(expected,metadata['appearanceStockSeed'])
            save_slots.replace_default(root=root)
            metadata=json.loads(Path(save_slots.metadata_path('default',root=root)).read_text())
            self.assertEqual(1,metadata['appearanceStockSeed'])
            old=Path(root)/'old';old.mkdir();(old/'save.json').write_text('{"mode":"unlocked"}')
            self.assertFalse(save_slots.replace_default(root=root))
            self.assertEqual('{"mode":"unlocked"}',(old/'save.json').read_text())

    def test_typed_notification_is_saved_once_with_exact_addition(self):
        with tempfile.TemporaryDirectory() as root:
            slot=save_slots.create_slot('Career',save_slots.MODE_NEW_ACCOUNT,root=root)
            args=dict(root=root,is_running=lambda:False)
            inventory={'1':{'137':{'0':9}},'2':{'137':{'101':5}}}
            store.write_inventory(slot['id'],'unused',inventory,**args)
            path=Path(save_slots.metadata_path(slot['id'],root=root))
            data=json.loads(path.read_text());notices=data['initial_account_notifications']
            rewards=[r for n in notices for c in n['settlement']['account_changes'] for r in c['rewards']]
            self.assertEqual([(1,137,9),(2,137,5)],[(r['type'],r['id'],r['count']) for r in rewards])
            store.write_inventory(slot['id'],'unused',inventory,**args)
            self.assertEqual(notices,json.loads(path.read_text())['initial_account_notifications'])

    def test_exact_client_catalogue_has_all_categories_and_no_inactive_style(self):
        game=os.environ.get('WOT_0922_CLIENT')
        if not game:self.skipTest('requires exact client')
        items, vehicles=store.appearance_catalogue(game)
        self.assertEqual(1341,len(items));self.assertEqual(614,len(vehicles))
        self.assertEqual(30,sum(i['igr'] and i['kind']==2 for i in items))
        self.assertEqual(15,sum(i['igr'] and i['kind']==3 for i in items))
        self.assertNotIn((4,137),[(i['kind'],i['id']) for i in items])
        self.assertEqual(len(items),len(set((i['kind'],i['id']) for i in items)))
        by_id={(i['kind'],i['id']):i for i in items}
        self.assertTrue(by_id[2,15335]['vehicle_bound'])
        self.assertEqual(105,sum(bool(i.get('vehicle_bound')) for i in items))
        self.assertEqual([('include',{'nations':['china','france','uk','usa','ussr']})],by_id[3,15872]['rules'])
        ddr=next(v for v in vehicles if v['name']=='germany:G105_T-55_NVA_DDR')
        self.assertEqual('ussr',ddr['customization_nation'])
        self.assertTrue(store.compatible(by_id[2,15050],ddr))
        unavailable=[i for i in items if not any(store.compatible(i,v) for v in vehicles)]
        # #1513 has only the Pudel in Poland; these legacy definitions exclude it.
        self.assertEqual(15,len(unavailable))
        self.assertTrue(all(i['kind']==2 and ('include',{'nations':['poland']}) in i['rules']
                            for i in unavailable))


if __name__ == '__main__':unittest.main()
