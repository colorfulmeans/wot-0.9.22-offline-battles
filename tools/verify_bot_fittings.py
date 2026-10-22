"""Audit every baked Bot fitting against pinned #1513 packed resources.

This is static resource/adapter evidence, not native installation or gameplay
acceptance. Repeated filter clauses retain their native OR semantics.
"""
import argparse
import copy
import gettext
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from packed_xml import PackedElement, read_packed_xml
from verify_default_loadouts import plain

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/res/scripts/client'))
from gui.mods.offline_lan_0922.bot_fitting_data import PLANS, CLASSES
from gui.mods.offline_lan_0922 import ammo_policy, vehicle_configuration
from gui.mods.offline_lan_0922 import bot_fittings


def audit_rented_outfits(packed):
    """Preserve repeated style/outfit/item nodes, including empty EVENT rows."""
    def children(node, name):
        return [v.value for k,v in node.children if k.decode()==name] if isinstance(node,PackedElement) else []
    rows = []
    for group in children(packed,'itemGroup'):
        for style in children(group,'style'):
            style_id = int(plain(style)['id'])
            for outfits in children(style,'outfits'):
                for outfit in children(outfits,'outfit'):
                    season = plain(outfit)['season']
                    items = []
                    for camouflages in children(outfit,'camouflages'):
                        for item in children(camouflages,'item'):
                            value = plain(item)
                            items.append(SimpleNamespace(id=int(value['id']),appliedTo=int(value['appliedTo'])))
                    camouflage = bot_fittings.hull_camouflage(SimpleNamespace(camouflages=items),16)
                    rows.append(dict(style=style_id,season=season,camouflage=camouflage))
    assert {r['style'] for r in rows} == set(range(1,10))
    for style in range(1,10):
        indexed = {r['season']:r['camouflage'] for r in rows if r['style']==style}
        assert set(indexed)=={'winter','summer','desert','event'}, (style,indexed)
        assert indexed['event'] is None, (style,'native EVENT outfit is empty')
        assert all(indexed[s] is not None for s in ('winter','summer','desert')),style
    return rows


def merge(shared, local):
    result = copy.deepcopy(shared)
    for key, value in local.items():
        result[key] = (merge(result[key], value) if isinstance(value, dict) and
                       isinstance(result.get(key), dict) else copy.deepcopy(value))
    return result


def audit(client):
    client = Path(client)
    cache, translations, rows = {}, {}, []
    def gui_key(name, value):
        label = value.get('userString', name)
        if label.startswith('#') and ':' in label:
            domain, key = label[1:].split(':', 1)
            if domain not in translations:
                with (client/'res/text/LC_MESSAGES'/(domain+'.mo')).open('rb') as stream:
                    translations[domain] = gettext.GNUTranslations(stream)
            label = translations[domain].gettext(key)
        return (int(value.get('level', 1)),
                vehicle_configuration._price_info(type('Price', (), {'price':value.get('price',0)})()), label)
    def children(node, key):
        return [v.value for k,v in node.children if k.decode() == key] if isinstance(node, PackedElement) else []
    with zipfile.ZipFile(client/'res/packages/scripts.pkg') as archive:
        rented_outfits = audit_rented_outfits(read_packed_xml(archive.read(
            'scripts/item_defs/customization/styles/rented_styles.xml')))
        def packed(path):
            if path not in cache:
                cache[path] = read_packed_xml(archive.read('scripts/item_defs/vehicles/'+path))
            return cache[path]
        def read(path):
            return plain(packed(path))
        device_nodes = {k.decode():v.value for k,v in packed('common/optional_devices.xml').children}
        device_data = read('common/optional_devices.xml')
        for vehicle, tiers in sorted(PLANS.items()):
            nation, name = vehicle.split(':')
            definition = read(nation+'/'+name+'.xml')
            listed = read(nation+'/list.xml')[name]
            tags = set(str(listed.get('tags','')).split())
            assert CLASSES[vehicle] in tags, vehicle
            shared = {kind:read(nation+'/components/'+group+'.xml').get('shared',{})
                      for kind,group in [('engine','engines'),('radio','radios'),('fuel_tank','fuelTanks'),('gun','guns')]}
            def parts(kind, group):
                return {n:merge(shared.get(kind,{}).get(n,{}),v if isinstance(v,dict) else {})
                        for n,v in definition[group].items()}
            components = {kind:parts(kind, group) for kind,group in
                          [('chassis','chassis'),('engine','engines'),('radio','radios'),('fuel_tank','fuelTanks')]}
            def clause_ok(node):
                if not isinstance(node,PackedElement):
                    return True
                for key,value in node.children:
                    key = key.decode()
                    if key == 'nations':
                        if nation not in str(plain(value)).split(): return False
                    elif key == 'vehicle':
                        for field,p in value.value.children:
                            field, val = field.decode(), plain(p)
                            if field == 'tags':
                                if not tags.intersection(str(val).split()): return False
                            elif field == 'minLevel':
                                if float(listed['level']) < float(val): return False
                            elif field == 'maxLevel':
                                if float(listed['level']) > float(val): return False
                            elif field == 'names':
                                if name not in str(val).split(): return False
                            else: raise AssertionError(('unhandled native device filter',field))
                    else: raise AssertionError(('unhandled native device clause',key))
                return True
            def allowed(device):
                for node in children(device_nodes[device],'vehicleFilter'):
                    includes, excludes = children(node,'include'), children(node,'exclude')
                    if includes and not any(clause_ok(x) for x in includes): return False
                    if any(clause_ok(x) for x in excludes): return False
                return True
            fixed = isinstance(listed.get('price'),dict) and 'gold' in listed['price']
            for tier, fitting in tiers.items():
                modules = fitting['modules']
                for kind, options in components.items():
                    assert modules[kind] in options, (vehicle,tier,kind)
                turret = definition['turrets0'][modules['turret']]
                assert modules['gun'] in turret['guns'], (vehicle,tier,'turret/gun')
                gun = merge(shared['gun'][modules['gun']], turret['guns'][modules['gun']] or {})
                mass = float(definition['hull']['weight']) + float(turret['weight']) + float(gun['weight'])
                mass += sum(float(options[modules[kind]]['weight']) for kind,options in components.items())
                mass += sum(float(device_data[n].get('script',{}).get('weight',0)) for n in fitting['devices'])
                assert mass <= float(components['chassis'][modules['chassis']]['maxLoad']), (vehicle,tier,mass)
                assert all(allowed(n) for n in fitting['devices']), (vehicle,tier,'device compatibility')
                if fixed:
                    assert modules == tiers['elite']['modules'], (vehicle,tier,'premium fixed')
                elif tier == 'rookie':
                    for kind, options in components.items():
                        assert modules[kind] == next(iter(options)), (vehicle,kind,'native stock')
                    assert modules['turret'] == next(iter(definition['turrets0'])), vehicle
                    assert modules['gun'] == next(iter(turret['guns'])), vehicle
                elif tier == 'regular':
                    assert modules['chassis'] == tiers['elite']['modules']['chassis'], vehicle
                    for kind in ('engine','radio'):
                        ordered = sorted(components[kind], key=lambda n:gui_key(n,components[kind][n]))
                        assert modules[kind] == ordered[min(1,len(ordered)-1)], (vehicle,kind,'second module')
                    stock = next(iter(definition['turrets0']))
                    if modules['gun'] in definition['turrets0'][stock]['guns']:
                        assert modules['turret'] == stock, (vehicle,'stock turret preferred')
                if 'lockOutfit' in tags:
                    assert fitting['style'] is None, (vehicle,'outfit locked')
                shell_data = read(nation+'/components/shells.xml')
                shots = list(gun['shots'])
                shells = [dict(index=i,name=n,kind=shell_data[n]['kind'],
                    gold=isinstance(shell_data[n].get('price'),dict) and 'gold' in shell_data[n]['price'])
                    for i,n in enumerate(shots)]
                clip = int(float((gun.get('clip') or {}).get('count',1)))
                capacity = int(float(gun['maxAmmo']))
                profile = dict(vehicle_name=vehicle, gun_name=modules['gun'],class_tag=CLASSES[vehicle],
                               shells=shells,clip_size=clip)
                allocation = ammo_policy.allocation(profile,capacity,len(shells))
                assert sum(allocation) == capacity, (vehicle,tier,'full capacity')
                assert all(n % clip == 0 for n in allocation), (vehicle,tier,'whole magazine')
                assert all(allocation[s['index']] > 0 for s in ammo_policy.stages(profile)), (vehicle,tier,'missing shell')
                rows.append(dict(vehicle=vehicle,tier=tier,modules=modules,weight=mass,
                    max_health=float(definition['hull'].get('maxHealth',0))+float(turret.get('maxHealth',0)),
                    reload_seconds=gun['reloadTime'],capacity=capacity,clip_size=clip,allocation=allocation))
    return dict(client='0.9.22.0.1 CN #1513', vehicles=len(PLANS), fittings=len(rows),
                evidence='static resources; native install/rendering not asserted',
                rented_outfits=rented_outfits, records=rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = audit(args.client)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Verified %d vehicles / %d fittings.' % (result['vehicles'],result['fittings']))
