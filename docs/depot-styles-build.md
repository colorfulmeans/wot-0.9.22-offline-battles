# Warehouse preset styles (#1513)

The warehouse adapter displays existing STYLE inventory (type 4), including
hidden styles with positive stock. Permanent quantities sum shared and
vehicle-bound copies; rental quantities are remaining battles. Rows are
read-only. Installation remains in the native garage Exterior screen.

The Chinese HD #1513 warehouse has six hardcoded Flash categories and no
customization category. Build its additional category from a locally owned
client with Java 17 and FFDec 26.3.0:

```
python3 tools/build_depot_style_swf.py --client CLIENT_ROOT --java JAVA_EXECUTABLE --ffdec FFDEC_JAR --output build/depot/lobby.swf
```

Set `WOT_OFFLINE_DEPOT_STYLE_SWF` to that output before running the existing
Python 2.7 `build_wotmod.py`. The builder verifies the generated sidecar and
stages `res/gui/flash/lobby.swf` inside the mod. Builds without this asset retain
the stock six-category menu. Never modify the installed `gui.pkg` directly.

The transformer gates the original lobby asset SHA-256 and edits only
StoreComponent, ShopVehicleView and InventoryModuleListItemRenderer. The shop
keeps its original categories. The warehouse uses the otherwise unused shop
vehicle filter linkage, with its fitting-type dispatch changed only in the
inventory context. The adapter registers the matching ShopVehiclesFiltersVO,
uses the original native filter builder, and preserves the previous saved
category so removing the mod does not leave an unknown startup category.

Reviewed native Python producers and consumers: store/Inventory.pyc,
store/StoreComponent.pyc, store/StoreTableDataProvider.pyc, store/tabs/
__init__.pyc, store/tabs/inventory.pyc and AccountSettings.pyc, read from
scripts.pkg under CPython 2.7.18. Relevant contracts include classmethod filter
VO/table selectors, four-argument table requests, tuple-to-row wrappers,
normalized nation IDs and per-category filter settings.

Pure inventory/installer tests and FFDec rebuild/re-export verify these
boundaries. They do not prove BigWorld Flash rendering or native navigation.
Acceptance must check opening the new category, counts after adding/using a
style, country/type/tier filters, original categories, and returning to garage
Exterior to install a style on Chinese HD #1513.
