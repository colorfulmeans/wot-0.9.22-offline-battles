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
CUSTOM_TYPES = ((1, 'paints', 'paint', 'Paint'),
                (2, 'camouflages', 'camouflage', 'Camouflage'),
                (3, 'decals', 'decal', 'Decal'),
                (5, 'modifications', 'modification', 'Wear'))
STOCK_VERSION = 1
INITIAL_KEY = 'initial_customizations'
NATIONS = ('ussr', 'germany', 'usa', 'china', 'france', 'uk', 'japan', 'czech', 'sweden', 'poland')
NATION_LABELS = dict(zip(NATIONS,('USSR','Germany','USA','China','France','UK','Japan','Czech','Sweden','Poland')))


def _fields(element):
    return {name.decode('utf8'): value for name, value in element.children}


def _text(value):
    if value.value_type == 5:
        return base64.b64encode(value.value).decode('ascii')
    if isinstance(value.value, bytes):
        return value.value.decode('utf8')
    return str(value.value).lower()


def _vehicle_rules(fields):
    section = fields.get('vehicleFilter')
    if section is None or section.value_type != 0:
        return []
    return [(action.decode('ascii'), {
                key.decode('ascii'): _text(value).split()
                for key, value in (rule.value.children if rule.value_type == 0 else ())})
            for action, rule in section.value.children]


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
            definition = vehicle_overlays.packed_xml.read_packed_xml(archive.read(
                'scripts/item_defs/vehicles/%s/%s.xml' % (nation, vehicle['vehicle'])))
            customization_nation = _fields(definition).get('customizationNation')
            vehicle['customization_nation'] = (_text(customization_nation)
                if customization_nation is not None else nation)
    if not styles or len({s['id'] for s in styles}) != len(styles):
        raise save_ledger.SaveLedgerError('The style catalogue is invalid.')
    return styles, vehicles


def compatible(style, vehicle):
    def matches(rule):
        for key, allowed in rule.items():
            if key == 'nations': actual = {vehicle.get('customization_nation', vehicle['nation'])}
            elif key == 'levels': actual = {str(vehicle['level'])}
            elif key == 'vehicles': actual = {vehicle['name']}
            elif key == 'tags':
                # #1513 FilterNode uses a proper subset, not any shared tag.
                if allowed and not set(allowed) < set(vehicle['tags']): return False
                continue
            else: raise save_ledger.SaveLedgerError('Unknown style vehicle filter: ' + key)
            if not actual.intersection(allowed): return False
        return True
    included = [rule for action, rule in style['rules'] if action == 'include']
    excluded = [rule for action, rule in style['rules'] if action == 'exclude']
    return (not included or any(matches(rule) for rule in included)) and not any(matches(rule) for rule in excluded)


def appearance_catalogue(game_root):
    """Read only active #1513 lists, with IDs scoped by customization type."""
    styles, vehicles = catalogue(game_root)
    status, package = vehicle_overlays._require_target(game_root)
    translations = {}
    for domain in ('vehicle_customization', 'vehicle_customization_cn'):
        path = os.path.join(status['path'], 'res', 'text', 'LC_MESSAGES', domain + '.mo')
        if os.path.isfile(path):
            with open(path, 'rb') as stream:
                translations[domain] = gettext.GNUTranslations(stream)
    items = []
    with zipfile.ZipFile(package) as archive:
        price_root = vehicle_overlays.packed_xml.read_packed_xml(archive.read(
            'scripts/item_defs/customization/priceGroups/list.xml'))
        price_flags = {}
        for tag, raw in price_root.children:
            if tag != b'priceGroup': continue
            fields = _fields(raw.value)
            price_flags[_text(fields['name'])] = ('notInShop' in fields and
                _text(fields['notInShop']).lower() in ('true', '1'))
        for kind, folder, item_tag, label in CUSTOM_TYPES:
            section = vehicle_overlays.packed_xml.read_packed_xml(archive.read(
                'scripts/item_defs/customization/%s/list.xml' % folder))
            for tag, raw in section.children:
                if tag != b'itemGroup': continue
                group = _fields(raw.value)
                for tag, raw_item in raw.value.children:
                    if tag != item_tag.encode('ascii'): continue
                    fields = _fields(raw_item.value)
                    # BaseCustomizationItemXmlReader assigns item fields over
                    # its group prototype. A local filter REPLACES that filter.
                    effective = dict(group)
                    effective.update(fields)
                    key = _text(fields.get('userString') or group['userString'])
                    if ':' in key:
                        domain, text = key.lstrip('#').split(':', 1)
                        name = translations.get(domain, gettext.NullTranslations()).gettext(text)
                    else:
                        name = key or '%s %s' % (label, _text(fields['id']))
                    price_group = _text(effective['priceGroup'])
                    tags = _text(effective['tags']).split() if 'tags' in effective else []
                    category = label
                    if kind == 3:
                        category = ('Inscription' if _text(effective['type']).upper() == 'INSCRIPTION'
                                    else 'Emblem')
                    items.append(dict(id=int(_text(fields['id'])), kind=kind,
                        label=name, category=category, rules=_vehicle_rules(effective),
                        igr='premiumIGR' in tags, hidden=price_flags[price_group],
                        vehicle_bound='vehicleBound' in tags,
                        season=_text(effective['season']) if 'season' in effective else 'ALL',
                        required_token=_text(effective['requiredToken']) if 'requiredToken' in effective else '',
                        rent_count=0, price_group=price_group))
    for item in styles:
        item.update(kind=STYLE_TYPE, category='Preset style', igr=False)
    return items + styles, vehicles


def add_item(inventory, item, vehicles, count, bound_vehicle=False):
    if item['kind'] == STYLE_TYPE:
        return add_style(inventory, item, vehicles, count, bound_vehicle)
    if type(count) is not int or not 1 <= count <= 100000:
        raise save_ledger.SaveLedgerError('Enter a quantity between 1 and 100000.')
    applicable = [v for v in vehicles if compatible(item, v)]
    if not applicable:
        raise save_ledger.SaveLedgerError('This item cannot be installed on the selected vehicle.')
    stock = inventory.setdefault(str(item['kind']), {}).setdefault(str(item['id']), {})
    bindings = [str(v['compact_descr']) for v in applicable] if item.get('vehicle_bound') else ['0']
    updates = {binding:stock.get(binding, 0)+count for binding in bindings}
    if any(value > 2**31-1 for value in updates.values()):
        raise save_ledger.SaveLedgerError('The inventory quantity is too large.')
    stock.update(updates)


def display_name(style, styles, translate=lambda value:value):
    if sum(other['label']==style['label'] for other in styles) <= 1:return style['label']
    nations={nation for action,rule in style['rules'] if action=='include' for nation in rule.get('nations',())}
    suffix=translate(NATION_LABELS[next(iter(nations))]) if len(nations)==1 else str(style['id'])
    return translate('%s (%s)') % (style['label'],suffix)


def applicability(style, vehicles, translate=lambda value:value):
    """Describe each exact include/exclude rule independently of other styles."""
    names={vehicle['name']:vehicle['label'] for vehicle in vehicles}
    includes=[rule for action,rule in style['rules'] if action=='include']
    shared=includes[0].get('nations',()) if includes else ()
    if not all(set(rule.get('nations',()))==set(shared) for rule in includes):shared=()
    join=translate(', ')
    def nation_names(nations):return join.join(translate(NATION_LABELS[n]) for n in nations)
    def description(rule, suppress_nation=False):
        if rule.get('vehicles'):
            text=translate('only %s') % join.join(names.get(n,n) for n in rule['vehicles'])
        elif rule.get('levels')==['8'] and rule.get('tags')==['premium']:
            text=translate('Tier VIII premium/reward vehicles')
        elif rule.get('levels')==['10'] and not rule.get('tags'):
            text=translate('all Tier X vehicles')
        else:
            text=translate('all vehicles')
            if rule.get('levels'):text=translate('Tier %s vehicles') % join.join(rule['levels'])
            if rule.get('tags'):text+=translate(' with tags %s') % join.join(rule['tags'])
        if rule.get('nations') and not suppress_nation:
            text=translate('Vehicles from %s: %s') % (nation_names(rule['nations']),text)
        return text
    result=join.join(description(rule,bool(shared)) for rule in includes) if includes else translate('all vehicles')
    if shared:result=translate('Vehicles from %s: %s') % (nation_names(shared),result)
    elif includes and not any(rule.get('vehicles') for rule in includes):
        result=translate('All nations: %s') % result
    exclusions=[]
    for action,rule in style['rules']:
        if action!='exclude':continue
        exclusions.append(join.join(names.get(n,n) for n in rule['vehicles'])
                          if set(rule)=={'vehicles'} else description(rule))
    if exclusions:result+=translate('; excludes %s') % join.join(exclusions)
    return result


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


def seed_initial_appearance(inventory, metadata, game_root):
    if not metadata.get('appearanceStockSeed') or metadata.get('appearanceStockVersion', 0) >= 1:
        return
    items, vehicles = appearance_catalogue(game_root)
    for item in items:
        if item['kind'] == STYLE_TYPE: continue
        bindings = inventory.setdefault(str(item['kind']), {}).setdefault(str(item['id']), {})
        keys = [str(v['compact_descr']) for v in vehicles if compatible(item, v)] if item.get('vehicle_bound') else ['0']
        for key in keys:bindings[key] = max(bindings.get(key, 0), 1000)


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
    if not has_garage:
        seed_initial_appearance(result, metadata, game_root)
    if metadata.get('mode', save_slots.MODE_UNLOCKED) == save_slots.MODE_UNLOCKED and container.get('styleStockVersion', 0) < STOCK_VERSION:
        stock = result.setdefault(str(STYLE_TYPE), {})
        for style in styles:
            bindings = stock.setdefault(str(style['id']), {})
            for vehicle in vehicles:
                if compatible(style, vehicle):
                    cd = str(vehicle['compact_descr'])
                    bindings[cd] = max(bindings.get(cd, 0), style['rent_count'] or 1)
    return result


def add_style(inventory, style, vehicles, copies, bound_vehicle=False):
    if type(copies) is not int or not 1 <= copies <= 100000:
        raise save_ledger.SaveLedgerError('Enter a quantity between 1 and 100000.')
    applicable = [vehicle for vehicle in vehicles if compatible(style, vehicle)]
    if not applicable:
        raise save_ledger.SaveLedgerError('This style cannot be installed on the selected vehicle.')
    if bound_vehicle and len(vehicles)!=1:
        raise save_ledger.SaveLedgerError('Select one vehicle before adding vehicle-bound stock.')
    if style['rent_count'] and not bound_vehicle:
        raise save_ledger.SaveLedgerError('Select a vehicle before adding a rental style.')
    stock = inventory.setdefault(str(STYLE_TYPE), {}).setdefault(str(style['id']), {})
    count = copies * (style['rent_count'] or 1)
    binding=str(applicable[0]['compact_descr']) if bound_vehicle else '0'
    updates = {binding: stock.get(binding, 0) + count}
    if any(value > 2 ** 31 - 1 for value in updates.values()):
        raise save_ledger.SaveLedgerError('The style inventory quantity is too large.')
    stock.update(updates)
    return copies


def write_inventory(slot_id, game_root, inventory, environment=None, root=None, is_running=None):
    if (core.game_is_running if is_running is None else is_running)():
        raise save_ledger.SaveLedgerError('Close World of Tanks before changing style inventory.')
    path, state, container, key, has_garage = _target(slot_id, game_root, environment, root)
    previous = _inventory(container.get(key, {}))
    if not has_garage:
        seed_initial_appearance(previous, container, game_root)
    updated = _inventory(inventory)
    changes = []
    for kind in sorted(set(previous) | set(updated), key=int):
        before, after = previous.get(kind, {}), updated.get(kind, {})
        for phase, sign in (('granted', 1), ('revoked', -1)):
            rewards = []
            for identifier in sorted(set(before) | set(after), key=int):
                delta = sign * (sum(after.get(identifier, {}).values()) -
                                sum(before.get(identifier, {}).values()))
                if delta > 0:
                    reward = {'kind':'style' if int(kind)==STYLE_TYPE else 'appearance',
                              'id':int(identifier),'count':delta}
                    if int(kind) != STYLE_TYPE: reward['type'] = int(kind)
                    rewards.append(reward)
            if rewards:changes.append({'phase':phase,'rewards':rewards})
    container[key] = updated
    container['styleStockVersion'] = STOCK_VERSION
    if not has_garage and container.get('appearanceStockSeed'):
        container['appearanceStockVersion'] = 1
    save_ledger.queue_account_changes(container, changes, has_garage)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_ledger._write_state(path, state)
