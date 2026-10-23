"""Launcher recruit handoff and native, durable barracks delivery (#1513)."""
import copy
import io
import json
import os
import re

NATIONS = ('ussr', 'germany', 'usa', 'china', 'france', 'uk', 'japan', 'czech', 'sweden', 'poland')
ROLES = ('commander', 'gunner', 'driver', 'loader', 'radioman')
MAX_SKILLS = 13  # Fourteen complete skills exceed #1513's 2,000,000,000 free XP cap.
MAX_PENDING = 512
FILE_NAME = 'launcher_crew_inbox.json'
RECEIPTS = 'launcherCrewReceipts'


def request(value):
    fields = ('id', 'nation', 'vehicle', 'role', 'female', 'skills')
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError('Invalid crew request fields')
    if not isinstance(value['id'], type(u'')) and not isinstance(value['id'], str):
        raise ValueError('Invalid crew request identity')
    if len(value['id']) != 32 or not re.match(r'^[0-9a-f]{32}\Z', value['id']):
        raise ValueError('Invalid crew request identity')
    if value['nation'] not in NATIONS or value['role'] not in ROLES or type(value['female']) is not bool:
        raise ValueError('Invalid crew nation, role or gender')
    if not isinstance(value['vehicle'], (str, type(u''))) or not re.match(r'^[A-Za-z0-9_-]+:[A-Za-z0-9_-]+\Z', value['vehicle']) or len(value['vehicle']) > 64 or value['vehicle'].split(':')[0] != value['nation']:
        raise ValueError('The trained vehicle belongs to another nation')
    if isinstance(value['skills'], bool) or not isinstance(value['skills'], int) or not 0 <= value['skills'] <= MAX_SKILLS:
        raise ValueError('Invalid complete skill count')
    return dict(value)


def identities(value):
    if not isinstance(value, (list, tuple)):
        return []
    return sorted(set(item for item in value[:MAX_PENDING] if isinstance(item, (str, type(u'')))
                      and len(item) == 32 and re.match(r'^[0-9a-f]{32}$', item)))


def keep_pending(path, rows):
    from gui.mods.offline_lan_0922 import config
    config.write_json(path, {'schema': 1, 'crew': [request(row) for row in rows]})


def read(path):
    if not os.path.isfile(path):
        return []
    with io.open(path, 'r', encoding='utf8') as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('crew'), list) or len(data['crew']) > MAX_PENDING:
        raise ValueError('Invalid crew inbox')
    rows = [request(row) for row in data['crew']]
    if len(set(row['id'] for row in rows)) != len(rows):
        raise ValueError('Duplicate crew request identity')
    return rows


def build(row, vehicles, tankmen):
    row = request(row)
    vehicle = vehicles.VehicleDescr(typeName=row['vehicle']).type
    nation, vehicle_id = vehicle.id
    if NATIONS[nation] != row['nation'] or row['role'] not in [seat[0] for seat in vehicle.crewRoles]:
        raise ValueError('The trained vehicle has no requested primary crew role')
    xp = sum(tankmen.TankmanDescr.levelUpXpCost(level, sequence)
             for sequence in range(1, row['skills'] + 1) for level in range(100))
    if not 0 <= xp <= 2000000000:
        raise ValueError('Complete skills exceed the native free XP cap')
    raw = tankmen.makeTmanDescrByTmanData(dict(nationID=nation, vehicleTypeID=vehicle_id,
        role=row['role'], roleLevel=100, isFemale=row['female'], isPremium=False,
        skills=[], freeSkills=[], freeXP=xp))
    actual = tankmen.TankmanDescr(raw)
    if (actual.roleLevel != 100 or actual.skills or actual.freeSkills or actual.freeXP != xp or
            bool(actual.isFemale) != row['female'] or actual.nationID != nation or
            actual.vehicleTypeID != vehicle_id or actual.role != row['role']):
        raise ValueError('Native crew generation changed the requested preset')
    return raw


def deliver(snapshot, vehicles, tankmen, store, path, write_pending, report):
    """Commit recruits, notices and retry identities in the same garage save."""
    pending = read(path)
    if not pending or store is None:
        return 0
    from gui.mods.offline_lan_0922.account_rpc.garage import GarageState
    from gui.mods.offline_lan_0922.personal_campaign_ui import queue_notification
    working = copy.deepcopy(snapshot)
    receipts = set(working.get(RECEIPTS) or ()) & set(row['id'] for row in pending)
    remaining, added = [], 0
    for row in pending:
        if row['id'] in receipts:
            continue
        staged = copy.deepcopy(working)
        try:
            raw = build(row, vehicles, tankmen)
            state = GarageState(staged, vehicles_module=vehicles, tankmen_module=tankmen)
            state._require_berths(1)
            state._to_barracks(state._next_tankman_id(), raw)
            staged = state.snapshot()
            queue_notification(staged, {'account_changes': [
                {'phase': 'granted', 'rewards': [{'kind': 'crew', 'count': 1}]}]})
        except Exception as error:
            remaining.append(row)
            report('crew request %s stays pending: %s' % (row['id'], error))
            continue
        receipts.add(row['id'])
        working = staged
        added += 1
    working[RECEIPTS] = sorted(receipts)
    if added:
        store.mark_dirty()
        if not store.flush(working):
            return 0
        snapshot.clear()
        snapshot.update(working)
    # A crash or failed inbox write after flush is safe: the saved identities
    # acknowledge the requests on retry without generating another passport.
    write_pending(path, remaining)
    return added
