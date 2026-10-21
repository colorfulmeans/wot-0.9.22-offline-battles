"""Read-only exact-client audit of every special default fitting and round."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from packed_xml import PackedElement, PackedValue, read_packed_xml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/res/scripts/client'))
from gui.mods.offline_lan_0922.default_loadouts import LOADOUTS, shell_roles


def plain(value):
    if isinstance(value, PackedValue):
        return plain(value.value)
    if isinstance(value, PackedElement):
        return {(key.decode() if isinstance(key, bytes) else key): plain(child)
                for key, child in value.children}
    if isinstance(value, bytes):
        return value.decode('utf8', errors='replace')
    return value


def audit(client):
    rows = []
    with zipfile.ZipFile(Path(client)/'res/packages/scripts.pkg') as archive:
        for vehicle, (gun, requested) in sorted(LOADOUTS.items()):
            nation, name = vehicle.split(':')
            def read(path):
                return plain(read_packed_xml(archive.read('scripts/item_defs/vehicles/'+path)))
            definition = read(nation+'/'+name+'.xml')
            gun_data = read(nation+'/components/guns.xml')['shared'][gun]
            compatible = []
            for turret, turret_data in definition['turrets0'].items():
                if gun in turret_data.get('guns', {}):
                    compatible.append(turret)
            if not compatible:
                raise ValueError('No matching turret/gun: '+vehicle)
            native_shots = tuple(gun_data['shots'])
            roles = shell_roles(vehicle, gun, native_shots)
            shell_data = read(nation+'/components/shells.xml')
            ammo = []
            for shell in requested:
                data = shell_data[shell]
                ammo.append(dict(name=shell, kind=data['kind'],
                                 gold=isinstance(data.get('price'), dict) and 'gold' in data['price']))
            rows.append(dict(vehicle=vehicle, gun=gun, compatible_turrets=compatible,
                             native_shells=native_shots, roles=roles, ordered_ammo=ammo))
    # High-risk exceptions: both HE identities and lower-penetration premium AP
    # are intentional. Currency is observed, never rewritten.
    indexed = {row['vehicle']: row for row in rows}
    for vehicle in ('usa:A100_T49', 'usa:A116_XM551'):
        ammo = indexed[vehicle]['ordered_ammo']
        assert ammo[0]['gold'] and ammo[0]['kind'] == 'HIGH_EXPLOSIVE'
        assert ammo[1]['kind'] == 'HOLLOW_CHARGE'
    for vehicle in ('japan:J25_Type_4', 'japan:J20_Type_2605'):
        ammo = indexed[vehicle]['ordered_ammo']
        assert len(ammo) == 1 and ammo[0]['gold'] and ammo[0]['kind'] == 'HIGH_EXPLOSIVE'
    for vehicle in ('uk:GB80_Charioteer','uk:GB81_FV4004','uk:GB83_FV4005','uk:GB48_FV215b_183'):
        ammo = indexed[vehicle]['ordered_ammo']
        assert ammo[0]['gold'] and ammo[0]['kind'] == 'HIGH_EXPLOSIVE'
        assert not ammo[1]['gold'] and ammo[1]['kind'] in ('ARMOR_PIERCING', 'ARMOR_PIERCING_CR')
    kv2 = indexed['ussr:R77_KV2']['ordered_ammo']
    assert kv2[0]['kind'] == 'HIGH_EXPLOSIVE' and not kv2[0]['gold']
    assert kv2[1]['kind'] == 'ARMOR_PIERCING' and kv2[1]['gold']
    return dict(vehicles=len(rows), client='#1513', rows=rows)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('client'); p.add_argument('--output', required=True)
    args = p.parse_args()
    result = audit(args.client)
    Path(args.output).write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    print('Verified native turret/gun/shell identities for %d vehicles.' % result['vehicles'])
