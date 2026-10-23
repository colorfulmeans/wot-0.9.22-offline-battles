"""Exact-client recruit choices and per-save native generation requests."""
import json
import os
import uuid
import zipfile

try:
    from . import core, save_ledger, save_slots, vehicle_overlays
except ImportError:
    import core, save_ledger, save_slots, vehicle_overlays

# Loading the tactics store installs the shared Python-2-compatible contract path.
try:
    from . import bot_tactics_store
except ImportError:
    import bot_tactics_store
from gui.mods.offline_lan_0922 import crew_recruits as contract


def catalogue(game_root):
    unused, package = vehicle_overlays._require_target(game_root)
    result = []
    with zipfile.ZipFile(package) as archive:
        for vehicle in vehicle_overlays.list_vehicle_choices(game_root):
            root = vehicle_overlays.packed_xml.read_packed_xml(archive.read(vehicle['member']))
            crew = next((value.value for key, value in root.children if key == b'crew'), None)
            roles = tuple(key.decode('ascii') for key, unused in crew.children) if crew is not None else ()
            roles = tuple(role for role in roles if role in contract.ROLES)
            if roles:
                result.append(dict(vehicle, name=vehicle['nation'] + ':' + vehicle['vehicle'], roles=roles))
    return result


def inbox_path(slot, game_root=None, root=None):
    return os.path.join(save_slots.slot_dir(slot, game_root, root=root), contract.FILE_NAME)


def write_pending(path, rows):
    payload = {'schema': 1, 'crew': [contract.request(row) for row in rows]}
    if len(payload['crew']) > contract.MAX_PENDING:
        raise ValueError('Start the game to receive pending crew first.')
    temporary = path + '.tmp'
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temporary, 'w', encoding='utf8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    except Exception:
        if os.path.isfile(temporary):
            os.remove(temporary)
        raise


def add(slot, game_root, vehicle, role, female, skills, root=None, is_running=None):
    if (is_running or core.game_is_running)():
        raise save_ledger.SaveLedgerError('Close World of Tanks before adding crew.')
    choices = {row['name']: row for row in catalogue(game_root)}
    selected = choices.get(vehicle)
    if selected is None or role not in selected['roles']:
        raise ValueError('Select a trained vehicle with the requested crew role.')
    row = contract.request(dict(id=uuid.uuid4().hex, nation=selected['nation'], vehicle=vehicle,
                                role=role, female=female, skills=skills))
    path = inbox_path(slot, game_root, root)
    rows = contract.read(path)
    write_pending(path, rows + [row])
    return row
