import copy
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import test_port_0922_garage as fixture

STORE_CONSTANTS = types.SimpleNamespace(VEHICLE='vehicle', MODULE='module',
    SHOP_VEHICLES_FILTERS_VO_CLASS='ShopVehiclesFiltersVO',VEHICLES_FILTERS_VO_CLASS='VehiclesFiltersVO')


class DepotStyleTests(unittest.TestCase):
    def test_permanent_raw_default_quantity_is_not_a_rental(self):
        self.setUp()
        self.styles[34].isRent = False
        self.styles[34].rentCount = 1
        rows = self.depot.inventory_rows({34: {0: 1}}, self.styles, lambda x: x)
        self.assertIn('Permanent style', rows[0]['desc'])
        snapshot = {'shopItemPrices': {self.styles[34].compactDescr: {'gold': 10}}}
        rows = self.depot.shop_rows(snapshot, self.styles, lambda x: x)
        self.assertFalse(rows[0]['disabled'])
        self.assertIn('Permanent style', rows[0]['desc'])

    def setUp(self):
        self.depot = fixture._load_port_module('depot_styles')
        rule = lambda countries: types.SimpleNamespace(nations=countries)
        def style(identifier, countries, rental=0):
            return types.SimpleNamespace(userString='Black Widow',compactDescr=identifier * 256,
                isRent=bool(rental),rentCount=rental,texture='../maps/vehicles/styles/style_01.png',
                filter=types.SimpleNamespace(include=[rule(countries)],
                    matchVehicleType=lambda vehicle: vehicle.nation in countries))
        self.styles = {34:style(34,[3]), 33:style(33,[0]), 1:style(1,[3],100)}

    def test_counts_include_shared_and_vehicle_bound_stock_without_mutation(self):
        stock={34:{0:1,101:2},33:{102:0},1:{101:200,102:100},999:{0:2}}
        before=copy.deepcopy(stock)
        rows=self.depot.inventory_rows(stock,self.styles,lambda name:name)
        self.assertEqual([3,300],sorted(row['inventoryCount'] for row in rows))
        self.assertEqual(stock,before)
        self.assertTrue(all(row['disabled'] and not row['removable'] for row in rows))
        self.assertTrue(all(row['extraModuleInfo'].startswith('gui/') for row in rows))
        self.assertTrue(any('300 battles' in row['desc'] for row in rows))

    def test_all_and_country_filter_and_duplicate_names(self):
        stock={34:{0:1},33:{0:1}}
        all_rows=self.depot.inventory_rows(stock,self.styles,lambda name:name,nation=-1)
        self.assertEqual(2,len(all_rows))
        self.assertEqual({'Black Widow (China)','Black Widow (USSR)'},
                         {row['name'] for row in all_rows})
        rows=self.depot.inventory_rows(stock,self.styles,lambda name:name,nation=3)
        self.assertEqual(['Black Widow (China)'],[row['name'] for row in rows])

    def test_vehicle_filter_uses_native_style_predicate(self):
        rows=self.depot.inventory_rows({34:{0:1},33:{0:1}},self.styles,lambda name:name,
            vehicle_types=[types.SimpleNamespace(nation=0)])
        self.assertEqual(['Black Widow (USSR)'],[row['name'] for row in rows])
        self.assertEqual([],self.depot.inventory_rows({34:{0:1}},self.styles,lambda name:name,
                                                      vehicle_types=[]))

    def test_installer_reuses_native_filter_builder_and_preserves_stock_categories(self):
        state={'inventory_current':(-1,'vehicle',False)}
        class Settings:
            getFilter=staticmethod(lambda key: state[key])
            setFilter=staticmethod(lambda key,value:state.__setitem__(key,value))
        class Inventory:
            def _StoreComponent__updateFilterOptions(self,kind):
                self.options=(kind==STORE_CONSTANTS.VEHICLE,
                              self._getTabClass(kind).getFilterInitData())
            def _getTabClass(self,kind):return tabs[kind]
            def requestTableData(self,nation,actions,kind,filters):
                Settings.setFilter('inventory_current',(nation,kind,actions))
                self.requested=(nation,actions,kind,filters)
                if filters=='error':raise ValueError('table failure')
                return 17
        class VehicleTab:
            @classmethod
            def getFilterInitData(cls):return 'VehiclesFiltersVO',True
        tabs=dict.fromkeys(('vehicle','module','shell','optionalDevice','equipment','battleBooster'),VehicleTab)
        original=dict(tabs)
        class Shop(Inventory):
            def buyItem(self,*args):return 'ordinary'
        shop_tabs=dict(tabs)
        defaults={'shop_vehicle':{'selectedTypes':[True]*5,'selectedLevels':[True]*10}}
        def module(name,**values):
            result=types.ModuleType(name);result.__dict__.update(values);return result
        modules={
            'account_helpers.AccountSettings':module('AccountSettings',AccountSettings=Settings,
                DEFAULT_VALUES={'filters':defaults},KEY_FILTERS='filters'),
            'gui.Scaleform.daapi.view.lobby.store.Inventory':module('Inventory',Inventory=Inventory,_INVENTORY_TABS=tabs),
            'gui.Scaleform.daapi.view.lobby.store.Shop':module('Shop',Shop=Shop,_SHOP_TABS=shop_tabs),
            'gui.Scaleform.daapi.view.lobby.store.StoreComponent':module('StoreComponent'),
            'gui.Scaleform.daapi.view.lobby.store.tabs.inventory':module('inventory',InventoryVehicleTab=VehicleTab),
            'gui.Scaleform.genConsts.STORE_CONSTANTS':module('STORE_CONSTANTS',STORE_CONSTANTS=STORE_CONSTANTS)}
        for name in list(modules):
            parts=name.split('.')
            for index in range(1,len(parts)):
                parent='.'.join(parts[:index])
                if parent not in modules:
                    modules[parent]=module(parent,__path__=[])
        for name in sorted(modules,key=lambda value:value.count('.'),reverse=True):
            if '.' in name:
                parent,child=name.rsplit('.',1)
                setattr(modules[parent],child,modules[name])
        with mock.patch.dict(sys.modules,modules):
            self.depot.install()
            method=Inventory.requestTableData
            self.depot.install()
            self.assertIs(method,Inventory.requestTableData)
            self.assertEqual(original,{key:tabs[key] for key in original})
            self.assertEqual('module',tabs[self.depot.TAB].getTableType())
            view=Inventory()
            view._StoreComponent__updateFilterOptions(self.depot.TAB)
            self.assertEqual((True,('ShopVehiclesFiltersVO',False)),view.options)
            view._StoreComponent__updateFilterOptions('vehicle')
            self.assertEqual((True,('VehiclesFiltersVO',True)),view.options)
            self.assertEqual(17,view.requestTableData(-1,False,self.depot.TAB,{}))
            self.assertEqual((-1,'vehicle',False),state['inventory_current'])
            with self.assertRaises(ValueError):view.requestTableData(-1,False,self.depot.TAB,'error')
            self.assertEqual((-1,'vehicle',False),state['inventory_current'])
            self.assertIsNot(defaults['inventory_'+self.depot.TAB],defaults['shop_vehicle'])
            self.assertEqual(('VehiclesFiltersVO',False),shop_tabs[self.depot.TAB].getFilterInitData())

    def test_shop_quotes_actual_prices_and_hides_unsold_styles(self):
        state={'shopItemPrices':{34*256:{'gold':750},33*256:{'gold':750},256:{'credits':75000}},
               'notInShopItems':[33*256],'customizationItems':{4:{34:{0:2}}}}
        rows=self.depot.shop_rows(state,self.styles,lambda value:value)
        self.assertEqual(2,len(rows))
        permanent=next(row for row in rows if row['id']==str(34*256))
        self.assertEqual((0,750,0),permanent['price'])
        self.assertEqual(2,permanent['inventoryCount'])
        self.assertFalse(permanent['disabled'])
        rental=next(row for row in rows if row['id']=='256')
        self.assertTrue(rental['disabled'])
        rows=self.depot.shop_rows(state,self.styles,lambda value:value,
                                 rental_vehicle=types.SimpleNamespace(nation=3))
        self.assertFalse(next(row for row in rows if row['id']=='256')['disabled'])

    def test_shop_purchase_confirmation_submits_one_native_transaction_and_refreshes(self):
        state={'shopItemPrices':{34*256:{'gold':750}},'notInShopItems':[],
               'customizationItems':{4:{}}}
        pending=[];messages=[]
        account=types.SimpleNamespace(shop=types.SimpleNamespace(buyCustomizations=mock.Mock()))
        view=types.SimpleNamespace(_isDAAPIInited=lambda:True,_update=mock.Mock())
        def show(meta,callback):pending.append(callback)
        def module(name,**values):
            result=types.ModuleType(name);result.__dict__.update(values);return result
        modules={
            'BigWorld':module('BigWorld',player=lambda:account),
            'items.vehicles':module('vehicles',g_cache=types.SimpleNamespace(
                customization20=lambda:types.SimpleNamespace(styles=self.styles))),
            'helpers.i18n':module('i18n',makeString=lambda value:value),
            'gui.DialogsInterface':module('DialogsInterface',showDialog=show),
            'gui.SystemMessages':module('SystemMessages',pushMessage=lambda *args,**kw:messages.append(args),
                SM_TYPE=types.SimpleNamespace(Information='info')),
            'gui.Scaleform.daapi.view.dialogs':module('dialogs',SimpleDialogMeta=lambda *args:args,
                                                     ConfirmDialogButtons=lambda:()),
            'gui.mods.offline_lan_0922.compat':module('compat',g_compatibility=types.SimpleNamespace(
                garage_state=lambda:types.SimpleNamespace(snapshot=lambda:state))),
            'gui.mods.offline_lan_0922.account_rpc.commands':module('commands',RES_SUCCESS=0)}
        for name in list(modules):
            parts=name.split('.')
            for index in range(1,len(parts)):
                parent='.'.join(parts[:index])
                if parent not in modules:modules[parent]=module(parent,__path__=[])
        for name in sorted(modules,key=lambda value:value.count('.'),reverse=True):
            if '.' in name:
                parent,child=name.rsplit('.',1);setattr(modules[parent],child,modules[name])
        with mock.patch.dict(sys.modules,modules),mock.patch.object(self.depot,'_selected_vehicle',return_value=(9,None)):
            self.depot.purchase(view,34*256)
            self.assertEqual(1,len(pending))
            pending[0](False);account.shop.buyCustomizations.assert_not_called()
            pending[0](True)
            self.assertEqual((0,{34*256:1}),account.shop.buyCustomizations.call_args.args[:2])
            pending[0](True);self.assertEqual(1,account.shop.buyCustomizations.call_count)
            callback=account.shop.buyCustomizations.call_args.args[2]
            callback(0)
            pending[0](True);self.assertEqual(1,account.shop.buyCustomizations.call_count)
            view._update.assert_called_once()
            self.assertEqual(1,len(messages))
            self.assertFalse(view._offline_style_purchase_pending)

    @unittest.skipUnless(os.environ.get('WOT_0922_CLIENT') and os.environ.get('WOT_0922_PY27'),
                         'Requires pinned #1513 archive and Python 2.7')
    def test_actual_python27_native_filter_function_with_new_category(self):
        code=r'''
import copy,marshal,sys,types,zipfile
archive=zipfile.ZipFile(sys.argv[1]+'/res/packages/scripts.pkg')
root=marshal.loads(archive.read('scripts/client/gui/Scaleform/daapi/view/lobby/store/StoreComponent.pyc')[8:])
def find(code,name):
 if code.co_name==name:return code
 for value in code.co_consts:
  if isinstance(value,types.CodeType):
   result=find(value,name)
   if result is not None:return result
native=find(root,'__updateFilterOptions')
assert native.co_argcount==2
def module(name,**values):
 result=types.ModuleType(name);result.__dict__.update(values);return result
constants=module('constants',VEHICLE='vehicle',RESTORE_VEHICLE='restore',TRADE_IN_VEHICLE='trade',
 MODULE='module',SHOP_VEHICLES_FILTERS_VO_CLASS='net.wg.gui.lobby.store.views.data.ShopVehiclesFiltersVO',
 VEHICLES_FILTERS_VO_CLASS='VehiclesFiltersVO')
defaults={'shop_vehicle':dict(selectedTypes=[True]*5,selectedLevels=[True]*10)}
class Settings(object):
 @staticmethod
 def getFilter(key):return copy.deepcopy(defaults[key])
class VehicleTab(object):
 @classmethod
 def getFilterInitData(cls):return 'VehiclesFiltersVO',True
tabs={'vehicle':VehicleTab}
class Inventory(object):
 def getName(self):return 'inventory'
 def _getTabClass(self,kind):return tabs[kind]
 def as_setFilterOptionsS(self,data):self.data=data
 def _update(self):self.updated=True
 def requestTableData(self,*args):pass
namespace=dict(__builtins__=__builtins__,AccountSettings=Settings,STORE_CONSTANTS=constants,VEHICLE_TYPES_ORDER=('lightTank',
 'mediumTank','heavyTank','AT-SPG','SPG'),VEHICLE_LEVELS=range(1,11),
 getVehicleTypeAssetPath=lambda v:v,getLevelsAssetPath=lambda v:v,makeTooltip=lambda *args:args)
Inventory._StoreComponent__updateFilterOptions=types.FunctionType(native,namespace)
class Shop(Inventory):
 def buyItem(self,*args):pass
modules={
 'account_helpers.AccountSettings':module('settings',AccountSettings=Settings,DEFAULT_VALUES={'filters':defaults},KEY_FILTERS='filters'),
 'gui.Scaleform.daapi.view.lobby.store.Inventory':module('Inventory',Inventory=Inventory,_INVENTORY_TABS=tabs),
 'gui.Scaleform.daapi.view.lobby.store.Shop':module('Shop',Shop=Shop,_SHOP_TABS=dict(tabs)),
 'gui.Scaleform.daapi.view.lobby.store.StoreComponent':module('StoreComponent'),
 'gui.Scaleform.daapi.view.lobby.store.tabs.inventory':module('inventory',InventoryVehicleTab=VehicleTab),
 'gui.Scaleform.genConsts.STORE_CONSTANTS':module('constants',STORE_CONSTANTS=constants),
 'gui.mods.offline_lan_0922.ui_i18n':module('i18n',tr=lambda v:v,as_text=unicode)}
for name in list(modules):
 parts=name.split('.')
 for index in range(1,len(parts)):
  parent='.'.join(parts[:index])
  if parent not in modules:modules[parent]=module(parent,__path__=[])
for name in sorted(modules,key=lambda v:v.count('.'),reverse=True):
 if '.' in name:
  parent,child=name.rsplit('.',1);setattr(modules[parent],child,modules[name])
sys.modules.update(modules)
depot=module('depot');exec compile(open(sys.argv[2],'rb').read(),sys.argv[2],'exec') in depot.__dict__
depot.install();instance=Inventory();instance._StoreComponent__updateFilterOptions(depot.TAB)
assert instance.data['voClassName']==constants.SHOP_VEHICLES_FILTERS_VO_CLASS
assert instance.data['showExtra'] is False
assert len(instance.data['voData']['vehicleTypes'])==5
assert len(instance.data['voData']['levels'])==10
assert instance.updated
assert isinstance(depot.native_text(u'\u9ed1\u5be1\u5987'),str)
assert depot.native_text(u'\u9ed1\u5be1\u5987').decode('utf8')==u'\u9ed1\u5be1\u5987'
print('Actual #1513 filter function builds the style VO under CPython 2.7')
'''
        source=Path(__file__).resolve().parents[1]/'src/res/scripts/client/gui/mods/offline_lan_0922/depot_styles.py'
        subprocess.run([os.environ['WOT_0922_PY27'],'-E','-c',code,
                        os.environ['WOT_0922_CLIENT'],str(source)],check=True)


if __name__=='__main__':unittest.main()
