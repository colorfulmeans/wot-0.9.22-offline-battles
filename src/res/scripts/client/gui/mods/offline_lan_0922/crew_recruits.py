"""Launcher recruit handoff and native, durable barracks delivery (#1513)."""
import copy
import io
import json
import os
import re
from gui.mods.offline_lan_0922 import crew_skills

NATIONS = ('ussr', 'germany', 'usa', 'china', 'france', 'uk', 'japan', 'czech', 'sweden', 'poland')
ROLES = ('commander', 'gunner', 'driver', 'loader', 'radioman')
MAX_SKILLS = max(len(crew_skills.skills_for(roles)) for rows in crew_skills.data.SEATS.values() for roles in rows)
MAX_PENDING = 512
FILE_NAME = 'launcher_crew_inbox.json'
RECEIPTS = 'launcherCrewReceipts'


def request(value):
    fields = ('id', 'nation', 'vehicle', 'role', 'female', 'skills')
    if not isinstance(value, dict) or set(value) not in (set(fields),set(fields+('seat','training'))):
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
    result=dict(value)
    if 'seat' not in result:
        rows=crew_skills.seats(result['vehicle'])
        result['seat']=next((i for i,r in enumerate(rows) if r[0]==result['role']),-1)
        result['training']=100
        if result['seat']>=0:
            low,high=crew_skills.bounds(result['vehicle'],result['seat'],result['female'],100)
            result['skills']=max(low,min(high,result['skills']))
    low,high=crew_skills.bounds(result['vehicle'],result['seat'],result['female'],result['training'])
    if not low<=result['skills']<=high:raise ValueError('Skill count does not match this crew seat and training level.')
    if crew_skills.seats(result['vehicle'])[result['seat']][0]!=result['role']:
        raise ValueError('The primary role does not match the chosen seat.')
    return result


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


def passport_group(config, female):
    """Select a complete native passport group without inventing name IDs."""
    for premium in (False, True):
        for index, group in enumerate(config.getGroups(premium)):
            if (bool(group.isFemales) == female and group.firstNamesList and
                    group.lastNamesList and group.iconsList):
                return premium, index
    raise ValueError('No native passport group matches the requested gender')


def build(row, vehicles, tankmen):
    row = request(row)
    vehicle = vehicles.VehicleDescr(typeName=row['vehicle']).type
    nation, vehicle_id = vehicle.id
    if NATIONS[nation] != row['nation'] or row['role'] not in [seat[0] for seat in vehicle.crewRoles]:
        raise ValueError('The trained vehicle has no requested primary crew role')
    if tuple(vehicle.crewRoles[row['seat']])!=tuple(crew_skills.seats(row['vehicle'])[row['seat']]):
        raise ValueError('The native crew seat differs from the pinned table')
    passport = passport_group(tankmen.getNationConfig(nation), row['female'])
    raw = tankmen.makeTmanDescrByTmanData(dict(nationID=nation, vehicleTypeID=vehicle_id,
        role=row['role'], roleLevel=row['training'], isFemale=row['female'], isPremium=passport[0],
        fnGroupID=passport[1], lnGroupID=passport[1], iGroupID=passport[1],
        skills=[], freeSkills=['brotherhood'] if row['female'] else [], freeXP=0))
    actual = tankmen.TankmanDescr(raw)
    if (actual.roleLevel != row['training'] or actual.skills != (['brotherhood'] if row['female'] else []) or
            actual.freeSkills != (['brotherhood'] if row['female'] else []) or actual.freeXP != 0 or
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
            identity=state._next_tankman_id()
            state._to_barracks(identity, raw)
            staged = state.snapshot()
            staged.setdefault(crew_skills.CREDITS,{})[str(identity)]=dict(remaining=row['skills']-int(row['female']),learned=[])
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
