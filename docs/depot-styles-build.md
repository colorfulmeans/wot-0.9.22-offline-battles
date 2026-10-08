# Warehouse preset styles (#1513)

The warehouse adapter displays existing STYLE inventory (type 4), including
hidden styles with positive stock. Permanent quantities sum shared and
vehicle-bound copies; rental quantities are remaining battles. Rows are
read-only. Installation remains in the native garage Exterior screen.

The shop category lists priced styles which the existing account catalogue
permits for sale. Confirmation submits one native
`Account.shop.buyCustomizations` CMD118 transaction. Hidden/non-shop flags,
deduction, durable inventory and failures remain under the account owner.
Rental purchases bind to the selected compatible garage vehicle.

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
StoreComponent, ShopVehicleView, BaseStoreMenuView, StoreListItemRenderer and
the inventory/shop module renderers. Original shop categories keep their
dispatch. The warehouse uses the otherwise unused shop
vehicle filter linkage, with its fitting-type dispatch changed only in the
inventory context. The adapter registers the matching ShopVehiclesFiltersVO,
uses the original native filter builder, and preserves the previous saved
category so removing the mod does not leave an unknown startup category.

Style names/descriptions use UTF-8 bytes on the Python2.7 native boundary.
Only style rows use Windows Microsoft YaHei device glyphs; recycled ordinary
rows restore their original fonts and embedding settings. Filter-control
labels reuse native vehicle labels while requests retain the style category.
Shop uses the otherwise unused inventory vehicle-filter graphic with its
matching VehiclesFiltersVO rather than colliding with the vehicle shop skin.

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

For v0.10.0 GitHub packaging, `tools/stage_release_style_ui.py` retrieves the reviewed generated input from a pinned Git blob build cache. The source tree does not contain the client Flash asset. The transformer digest and output digest must match `tools/release0100-style-input.json`; changing the transformer requires regenerating and reviewing this input with the exact client.
