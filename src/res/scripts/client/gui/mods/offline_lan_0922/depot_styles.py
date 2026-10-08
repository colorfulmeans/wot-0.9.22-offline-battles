"""Read-only #1513 warehouse style category, using its stock table protocol."""
import copy
import types
import sys

from gui.mods.offline_lan_0922.ui_i18n import as_text, tr

TAB = 'offlineStyles'
_NATIONS = ('USSR','Germany','USA','China','France','UK','Japan','Czech','Sweden','Poland')


def native_text(value):
    text = as_text(value)
    return text.encode('utf8') if sys.version_info[0] == 2 else text


def inventory_rows(stock, styles, localize, nation=None, vehicle_types=None):
    """Build native table rows without creating, consuming or selling items."""
    labels = dict((identifier,as_text(localize(style.userString))) for identifier,style in styles.items())
    result = []
    for identifier,bindings in sorted(stock.items()):
        style = styles.get(identifier)
        count = sum(max(0,int(value)) for value in bindings.values())
        if style is None or count <= 0:continue
        if vehicle_types is not None and not any(style.filter is None or
                style.filter.matchVehicleType(vehicle) for vehicle in vehicle_types):continue
        included = getattr(getattr(style,'filter',None),'include',())
        countries = set(n for rule in included for n in (rule.nations or ()))
        if nation is not None and nation >= 0 and countries and nation not in countries:continue
        name = labels[identifier]
        if list(labels.values()).count(name)>1 and len(countries)==1:
            country=next(iter(countries))
            name=tr('%s (%s)') % (name,tr(_NATIONS[country]))
        rental = int(style.rentCount or 0)>0
        description=tr('Rental style: %d battles remaining.') % count if rental else tr('Permanent style: %d copies.') % count
        result.append(dict(id=str(style.compactDescr),name=name,desc=description,
            inventoryId=0,inventoryCount=count,vehicleCount=0,price=(0,0,0),
            byWeight=False,currency='credits',level=0,nation=-1,type='',disabled=True,
            statusMessage=tr('Use preset styles from the garage Exterior screen.'),isCritLvl=False,
            statusImgSrc='',removable=False,itemTypeName='offlineStyle',goldShellsForCredits=False,
            goldEqsForCredits=False,actionPriceData=None,moduleLabel='',vehCompareData={},
            highlightType='',showActionGoldAndCredits=False,actionPercent=['-0','-0','-0'],
            notForSaleText=tr('Use in Exterior'),extraModuleInfo=style.texture.replace('../','gui/',1)))
    return sorted(result,key=lambda row:(row['name'],row['id']))


def shop_rows(snapshot, styles, localize, nation=None, vehicle_types=None, rental_vehicle=None, balances=None):
    prices=snapshot.get('shopItemPrices',{})
    hidden=set(snapshot.get('notInShopItems',()))
    stock=snapshot.get('customizationItems',{}).get(4,{})
    listed=dict((identifier,{0:1}) for identifier,style in styles.items()
                if style.compactDescr in prices and style.compactDescr not in hidden)
    rows=inventory_rows(listed,styles,localize,nation,vehicle_types)
    balances=snapshot.get('wallet',{}) if balances is None else balances
    by_cd=dict((str(style.compactDescr),(identifier,style)) for identifier,style in styles.items())
    for row in rows:
        identifier,style=by_cd[row['id']]
        price=prices[style.compactDescr]
        row['price']=tuple(int(price.get(key,0)) for key in ('credits','gold','crystal'))
        row['currency']='gold' if price.get('gold') else 'crystal' if price.get('crystal') else 'credits'
        row.update((key,int(balances.get(key,0))) for key in ('credits','gold','crystal'))
        row['inventoryCount']=sum(stock.get(identifier,{}).values())
        row['notForSaleText']=''
        row['disabled']=bool(style.rentCount and (rental_vehicle is None or
            not style.filter.matchVehicleType(rental_vehicle)))
        row['desc']=(tr('Rental style: %d battles per purchase.') % style.rentCount
                     if style.rentCount else tr('Permanent style: one copy per purchase.'))
        if row['disabled']:row['notForSaleText']=tr('Select a compatible vehicle in the garage.')
    return rows


def purchase(view, compact_descr):
    """Confirm one native CMD118 purchase, retaining its durable transaction."""
    import BigWorld
    from items import vehicles
    from helpers import i18n
    from gui import DialogsInterface, SystemMessages
    from gui.Scaleform.daapi.view.dialogs import SimpleDialogMeta, ConfirmDialogButtons
    from gui.mods.offline_lan_0922.compat import g_compatibility
    from gui.mods.offline_lan_0922.account_rpc import commands
    account=BigWorld.player()
    selected_id,selected_type=_selected_vehicle()
    catalogue=vehicles.g_cache.customization20().styles
    rows=shop_rows(g_compatibility.garage_state().snapshot(),catalogue,i18n.makeString,
                   rental_vehicle=selected_type)
    row=next((item for item in rows if item['id']==str(compact_descr)),None)
    if row is None or row['disabled'] or getattr(view,'_offline_style_purchase_pending',False):return
    style=next(style for style in catalogue.values() if str(style.compactDescr)==str(compact_descr))
    vehicle_id=selected_id if style.rentCount else 0
    text=tr('Buy %s for %d %s?') % (as_text(row['name']),sum(row['price']),tr(row['currency']))
    submitted=[False]
    def confirmed(yes):
        if submitted[0] or not yes or BigWorld.player() is not account or not view._isDAAPIInited():return
        if getattr(view,'_offline_style_purchase_pending',False):return
        submitted[0]=True
        view._offline_style_purchase_pending=True
        def completed(result):
            view._offline_style_purchase_pending=False
            if BigWorld.player() is not account:return
            SystemMessages.pushMessage(native_text(tr('Style purchased.') if result==commands.RES_SUCCESS
                else tr('Style purchase failed.')),type=SystemMessages.SM_TYPE.Information)
            if view._isDAAPIInited():view._update()
        try:account.shop.buyCustomizations(vehicle_id,{int(compact_descr):1},completed)
        except Exception:
            view._offline_style_purchase_pending=False
            raise
    DialogsInterface.showDialog(SimpleDialogMeta(native_text(tr('Purchase style')),native_text(text),
                                ConfirmDialogButtons()),confirmed)


def _selected_vehicle():
    from CurrentVehicle import g_currentVehicle
    item=g_currentVehicle.item
    return (item.invID,item.type) if item is not None else (0,None)


def install():
    settings_module=__import__('account_helpers.AccountSettings',fromlist=['AccountSettings'])
    from gui.Scaleform.daapi.view.lobby.store import Inventory as inventory_module
    from gui.Scaleform.daapi.view.lobby.store import StoreComponent as component_module
    from gui.Scaleform.daapi.view.lobby.store.tabs.inventory import InventoryVehicleTab
    from gui.Scaleform.genConsts.STORE_CONSTANTS import STORE_CONSTANTS
    cls=inventory_module.Inventory
    if getattr(cls,'_offline_style_category_installed',False):return
    original=cls._StoreComponent__updateFilterOptions
    function=getattr(original,'im_func',original)
    namespace=dict(getattr(function,'func_globals',None) or function.__globals__)
    class StyleConstants(object):
        VEHICLE=TAB
        def __getattr__(self,name):return getattr(STORE_CONSTANTS,name)
    namespace['STORE_CONSTANTS']=StyleConstants()
    # Reuse the verified stock filter VO builder with this category's own key.
    code=getattr(function,'func_code',None) or function.__code__
    style_options=types.FunctionType(code,namespace,function.__name__,
                                    getattr(function,'func_defaults',None))
    defaults=settings_module.DEFAULT_VALUES[settings_module.KEY_FILTERS]
    defaults.setdefault('inventory_'+TAB,copy.deepcopy(defaults['shop_vehicle']))

    class StylesTab(InventoryVehicleTab):
        is_shop=False
        @classmethod
        def getFilterInitData(cls):return STORE_CONSTANTS.SHOP_VEHICLES_FILTERS_VO_CLASS,False
        @classmethod
        def getTableType(cls):return STORE_CONSTANTS.MODULE
        def buildItems(self,invVehicles):
            from helpers import i18n
            from items import vehicles
            import nations
            from gui.mods.offline_lan_0922.compat import g_compatibility
            state=g_compatibility.garage_state()
            if state is None:return []
            snapshot=state.snapshot()
            stock=snapshot.get('customizationItems',{}).get(4,{})
            catalogue=vehicles.g_cache.customization20().styles
            selected=None
            types_selected=self._filterData.get('selectedTypes',())
            levels_selected=self._filterData.get('selectedLevels',())
            if (types_selected and not all(types_selected) or levels_selected and not all(levels_selected)):
                selected=[]
                for nation in range(len(nations.NAMES)):
                    for vehicle_id in vehicles.g_list.getList(nation):
                        descriptor=vehicles.getVehicleType(vehicles.makeIntCompactDescrByID('vehicle',nation,vehicle_id))
                        if levels_selected and not levels_selected[descriptor.level-1]:continue
                        if types_selected and not any(flag and tag in descriptor.tags for flag,tag in
                                zip(types_selected,component_module.VEHICLE_TYPES_ORDER)):continue
                        selected.append(descriptor)
            rows=(shop_rows(snapshot,catalogue,i18n.makeString,self._nation,selected,_selected_vehicle()[1],state._balances())
                  if self.is_shop else inventory_rows(stock,catalogue,i18n.makeString,self._nation,selected))
            return [(row,None,0) for row in rows]
        def itemWrapper(self,packed):
            row=dict(packed[0])
            for key in ('name','desc','statusMessage','notForSaleText'):
                row[key]=native_text(row[key])
            return row

    inventory_module._INVENTORY_TABS[TAB]=StylesTab
    def options(self,kind):
        return style_options(self,kind) if kind==TAB else original(self,kind)
    old_request=cls.requestTableData
    def request(self,nation,actionsSelected,kind,filters):
        if kind!=TAB:return old_request(self,nation,actionsSelected,kind,filters)
        previous=settings_module.AccountSettings.getFilter('inventory_current')
        try:return old_request(self,nation,actionsSelected,kind,filters)
        finally:settings_module.AccountSettings.setFilter('inventory_current',previous)
    cls._StoreComponent__updateFilterOptions=options
    cls.requestTableData=request
    from gui.Scaleform.daapi.view.lobby.store import Shop as shop_module
    class ShopStylesTab(StylesTab):
        is_shop=True
        @classmethod
        def getFilterInitData(cls):return STORE_CONSTANTS.VEHICLES_FILTERS_VO_CLASS,False
    defaults.setdefault('shop_'+TAB,copy.deepcopy(defaults['shop_vehicle']))
    shop_module._SHOP_TABS[TAB]=ShopStylesTab
    shop=shop_module.Shop
    shop_original=shop._StoreComponent__updateFilterOptions
    shop._StoreComponent__updateFilterOptions=lambda self,kind: (
        style_options(self,kind) if kind==TAB else shop_original(self,kind))
    shop_request=shop.requestTableData
    def request_shop(self,nation,actionsSelected,kind,filters):
        if kind!=TAB:return shop_request(self,nation,actionsSelected,kind,filters)
        previous=settings_module.AccountSettings.getFilter('shop_current')
        try:return shop_request(self,nation,actionsSelected,kind,filters)
        finally:settings_module.AccountSettings.setFilter('shop_current',previous)
    shop.requestTableData=request_shop
    old_buy=shop.buyItem
    def buy(self,itemCD,allowTradeIn=False):
        from items import vehicles
        if any(str(style.compactDescr)==str(itemCD) for style in vehicles.g_cache.customization20().styles.values()):
            return purchase(self,itemCD)
        return old_buy(self,itemCD,allowTradeIn)
    shop.buyItem=buy
    cls._offline_style_category_installed=True
