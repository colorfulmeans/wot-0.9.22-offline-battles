"""Exact #1513 style catalogue and atomic inventory edits for one save."""
import gettext
import base64
import os
import zipfile

try:
    from . import core, save_ledger, save_slots, vehicle_overlays
except ImportError:
    import core, save_ledger, save_slots, vehicle_overlays

STYLE_TYPE = 4  # #1513 items.components.c11n_constants.CustomizationType.STYLE
STOCK_VERSION = 1
INITIAL_KEY = 'initial_customizations'
NATIONS = ('ussr', 'germany', 'usa', 'china', 'france', 'uk', 'japan', 'czech', 'sweden', 'poland')


def _fields(element):
    return {name.decode('utf8'): value for name, value in element.children}


def _text(value):
    if value.value_type == 5:
        return base64.b64encode(value.value).decode('ascii')
    if isinstance(value.value, bytes):
        return value.value.decode('utf8')
    return str(value.value).lower()


def catalogue(game_root):
    """Read the active merged list, including hidden styles, not unused files."""
    status, package = vehicle_overlays._require_target(game_root)
    with zipfile.ZipFile(package) as archive:
        root = vehicle_overlays.packed_xml.read_packed_xml(archive.read(
            'scripts/item_defs/customization/styles/list.xml'))
        styles = []
        prices = {}
        price_root = vehicle_overlays.packed_xml.read_packed_xml(archive.read(
            'scripts/item_defs/customization/priceGroups/styles.xml'))
        for name, raw in price_root.children:
            if name != b'priceGroup': continue
            fields = _fields(raw.value)
            prices[_text(fields['name'])] = (_text(fields.get('notInShop'))
                if fields.get('notInShop') is not None else 'false').lower() in ('true', '1')
        translation = gettext.NullTranslations()
        path = os.path.join(status['path'], 'res', 'text', 'LC_MESSAGES', 'vehicle_customization.mo')
        if os.path.isfile(path):
            with open(path, 'rb') as stream:
                translation = gettext.GNUTranslations(stream)
        for name, raw in root.children:
            if name != b'itemGroup': continue
            fields = _fields(raw.value)
            group = _text(fields['priceGroup'])
            rules = []
            for action, rule in fields['vehicleFilter'].value.children:
                rules.append((action.decode('ascii'), {
                    key.decode('ascii'): _text(value).split()
                    for key, value in rule.value.children}))
            for child, style_raw in raw.value.children:
                if child != b'style': continue
                item = _fields(style_raw.value)
                identifier = int(_text(item['id']))
                key = _text(item['userString']).split(':', 1)[1]
                styles.append(dict(id=identifier, label=translation.gettext(key),
                    english_label=key, hidden=prices[group], rules=rules,
                    rent_count=int(_text(item['rentCount'])) if 'rentCount' in item else 0))
        vehicles = vehicle_overlays.list_vehicle_choices(status['path'])
        lists = {}
        for vehicle in vehicles:
            nation = vehicle['nation']
            if nation not in lists:
                section = vehicle_overlays.packed_xml.read_packed_xml(archive.read(
                    'scripts/item_defs/vehicles/%s/list.xml' % nation))
                lists[nation] = {name.decode('utf8'): value.value
                    for name, value in section.children if value.value_type == 0}
            identifier = int(_text(_fields(lists[nation][vehicle['vehicle']])['id']))
            price = _fields(lists[nation][vehicle['vehicle']]).get('price')
            # VehicleList adds premium from the gold denomination, including
            # a zero-gold reward. It is not generally present in XML tags.
            if price is not None and price.value_type == 0 and any(
                    name == b'gold' for name, unused in price.value.children):
                vehicle['tags'] = tuple(set(vehicle['tags']) | {'premium'})
            vehicle['compact_descr'] = 1 | (NATIONS.index(nation) << 4) | (identifier << 8)
            vehicle['name'] = nation + ':' + vehicle['vehicle']
    if not styles or len({s['id'] for s in styles}) != len(styles):
        raise save_ledger.SaveLedgerError('The style catalogue is invalid.')
    return styles, vehicles


def compatible(style, vehicle):
    def matches(rule):
        for key, allowed in rule.items():
            if key == 'nations': actual = {vehicle['nation']}
            elif key == 'levels': actual = {str(vehicle['level'])}
            elif key == 'vehicles': actual = {vehicle['name']}
            elif key == 'tags': actual = set(vehicle['tags'])
            else: raise save_ledger.SaveLedgerError('Unknown style vehicle filter: ' + key)
            if not actual.intersection(allowed): return False
        return True
    included = [rule for action, rule in style['rules'] if action == 'include']
    excluded = [rule for action, rule in style['rules'] if action == 'exclude']
    return (not included or any(matches(rule) for rule in included)) and not any(matches(rule) for rule in excluded)


def _target(slot_id, game_root, environment=None, root=None):
    path = save_ledger.ledger_path(slot_id, game_root, environment, root)
    state = save_ledger._read_state(path)
    if state is not None:
        if not isinstance(state.get('ledger'), dict):
            raise save_ledger.SaveLedgerError('The save is not in the expected format.')
        return path, state, state['ledger'], 'customizations', True
    path = save_slots.metadata_path(slot_id, game_root, environment, root)
    state = save_ledger._read_state(path) or {}
    return path, state, state, INITIAL_KEY, False


def _inventory(value):
    try:
        result = {str(int(k)): {str(int(i)): {str(int(v)): int(n)
                      for v, n in bindings.items()} for i, bindings in items.items()}
                  for k, items in value.items()}
        if any(int(k) <= 0 or any(int(i) <= 0 or any(int(v) < 0 or not 0 <= n <= 2**31-1
                for v,n in bindings.items()) for i,bindings in items.items()) for k,items in result.items()):
            raise ValueError('invalid ownership count')
        return result
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise save_ledger.SaveLedgerError('The style inventory is not in the expected format.')


def read_inventory(slot_id, game_root, styles, vehicles, environment=None, root=None):
    unused_path, state, container, key, has_garage = _target(slot_id, game_root, environment, root)
    inventory = container.get(key, {})
    if not isinstance(inventory, dict):
        raise save_ledger.SaveLedgerError('The save is not in the expected format.')
    # JSON owns string keys. Keep non-style items and unbound stock intact.
    result = _inventory(inventory)
    if has_garage:
        owned = set(state.get('vehicles', {}))
        vehicles = [v for v in vehicles if str(v['compact_descr']) in owned]
    metadata = save_ledger._read_state(save_slots.metadata_path(slot_id, game_root, environment, root)) or {}
    if metadata.get('mode', save_slots.MODE_UNLOCKED) == save_slots.MODE_UNLOCKED and container.get('styleStockVersion', 0) < STOCK_VERSION:
        stock = result.setdefault(str(STYLE_TYPE), {})
        for style in styles:
            bindings = stock.setdefault(str(style['id']), {})
            for vehicle in vehicles:
                if compatible(style, vehicle):
                    cd = str(vehicle['compact_descr'])
                    bindings[cd] = max(bindings.get(cd, 0), style['rent_count'] or 1)
    return result


def add_style(inventory, style, vehicles, copies):
    if type(copies) is not int or not 1 <= copies <= 100000:
        raise save_ledger.SaveLedgerError('Enter a quantity between 1 and 100000.')
    applicable = [vehicle for vehicle in vehicles if compatible(style, vehicle)]
    if not applicable:
        raise save_ledger.SaveLedgerError('This style cannot be installed on the selected vehicle.')
    stock = inventory.setdefault(str(STYLE_TYPE), {}).setdefault(str(style['id']), {})
    count = copies * (style['rent_count'] or 1)
    updates = {str(v['compact_descr']): stock.get(str(v['compact_descr']), 0) + count for v in applicable}
    if any(value > 2 ** 31 - 1 for value in updates.values()):
        raise save_ledger.SaveLedgerError('The style inventory quantity is too large.')
    stock.update(updates)
    return len(applicable)


def write_inventory(slot_id, game_root, inventory, environment=None, root=None, is_running=None):
    if (core.game_is_running if is_running is None else is_running)():
        raise save_ledger.SaveLedgerError('Close World of Tanks before changing style inventory.')
    path, state, container, key, unused = _target(slot_id, game_root, environment, root)
    container[key] = _inventory(inventory)
    container['styleStockVersion'] = STOCK_VERSION
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_ledger._write_state(path, state)
