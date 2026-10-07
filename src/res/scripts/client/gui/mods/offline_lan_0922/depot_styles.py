"""Read-only #1513 warehouse style category, using its stock table protocol."""
import copy
import types

from gui.mods.offline_lan_0922.ui_i18n import as_text, tr

TAB = 'offlineStyles'
_NATIONS = ('USSR','Germany','USA','China','France','UK','Japan','Czech','Sweden','Poland')


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
            stock=state.snapshot().get('customizationItems',{}).get(4,{})
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
            rows=inventory_rows(stock,catalogue,i18n.makeString,self._nation,selected)
            return [(row,None,0) for row in rows]
        def itemWrapper(self,packed):return packed[0]

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
    cls._offline_style_category_installed=True
