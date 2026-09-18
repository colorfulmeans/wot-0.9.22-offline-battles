"""Regular personal-mission rewards from the installed client's resources.

Completion, paid reward stages and delayed crew claims are separate facts.
Launcher edits and battle receipts enter the same idempotent settlement path.
"""
from __future__ import print_function

import time

from gui.mods.offline_lan_0922.account_rpc import data
from gui.mods.offline_lan_0922.account_rpc.garage import GarageError

RESOURCE_ROOT = 'scripts/item_defs/potapov_quests/'
TOKEN_EXPIRY = 4104777660
_resources = {}


def children(node, name):
    return [item for tag, item in (node or {}).get('children', ()) if tag == name]


def child(node, name):
    found = children(node, name)
    return found[0] if found else None


def value(node, name=None, default=''):
    item = child(node, name) if name is not None else node
    return item.get('value', default) if item is not None else default


def _node(section):
    return {'value': section.asString.strip(),
            'children': [(name, _node(item)) for name, item in section.items()]}


def _resource(path, open_section=None):
    if open_section is None:
        if path in _resources:
            return _resources[path]
        import ResMgr
        section = ResMgr.openSection(RESOURCE_ROOT + path)
    else:
        section = open_section(RESOURCE_ROOT + path)
    if section is None:
        raise GarageError('PERSONAL_MISSION_RESOURCE_UNAVAILABLE: ' + path)
    result = _node(section)
    if open_section is None:
        _resources[path] = result
    return result


def mission_definition(mission_id, open_section=None):
    mission_id = int(mission_id)
    if not 1 <= mission_id <= 300:
        raise GarageError('INVALID_PERSONAL_MISSION')
    operation, offset = divmod(mission_id - 1, 75)
    chain, index = divmod(offset, 15)
    name = 'regular_%d_%d_%d' % (operation + 1, chain + 1, index + 1)
    path = 'regular/tile_%d/chain_%d/%s.xml' % (
        operation + 1, chain + 1, name)
    resource = _resource(path, open_section)
    quests = child(resource, 'quests')
    result = {'metadata': child(_resource('list.xml', open_section), name)}
    stages = ('main', 'main_award_list', 'add', 'add_award_list')
    quest_rows = children(quests, 'potapovQuest')
    if len(quest_rows) != 4 or result['metadata'] is None:
        raise GarageError('INVALID_PERSONAL_MISSION_RESOURCE: ' + name)
    # PQCache consumes the four entries in resource order and checks each
    # suffix. Their unique IDs need not duplicate the containing file name.
    for stage, quest in zip(stages, quest_rows):
        if not value(quest, 'id').endswith(stage):
            raise GarageError('INVALID_PERSONAL_MISSION_STAGE: ' + name)
        result[stage] = quest
    return result


def _tokens(snapshot):
    raw = snapshot.get('personalMissionTokens') or {}
    result = {}
    for name, row in raw.items():
        try:
            expiry, count = row
            result[str(name)] = [int(expiry), max(0, int(count))]
        except (TypeError, ValueError):
            continue
    return result


def _grant_vehicle(state, name):
    snapshot = state.snapshot()
    existing = next((record for record in state._records()
                     if record.get('vehicleTypeName') == name), None)
    if existing is not None:
        # Explicit offline policy: a first operation claim for an owned tank
        # pays its existing bare-vehicle credit refund. The operation receipt
        # makes this compensation one-time, even after a mission reset.
        refund = state._item_refund(int(existing['vehicleTypeCompactDescr']))
        state._wallet()['credits'] += int(refund.get('credits', 0))
        return
    # Use the existing stock-record builder; the XML defines this as a free
    # 100%-crew reward, so no wallet-dependent shop transaction is involved.
    from items import ITEM_TYPE_INDICES
    from gui.mods.offline_lan_0922 import bootstrap
    compact_descr = bootstrap._build_purchased_vehicle(
        snapshot, state._vehicles_module(), state._tankmen_module(),
        ITEM_TYPE_INDICES, state._default_vehicle_settings(), name)
    for record in state._records():
        if int(record.get('vehicleTypeCompactDescr', 0)) == compact_descr:
            state._touched.add(int(record['id']))
            state._touched_tankmen.update(record.get('tankmen', {}))
            for item_type, items in record.get('inventoryItems', {}).items():
                state._touched_items.setdefault(int(item_type), set()).update(items)


def _grant_bonus(state, bonus, now):
    snapshot = state.snapshot()
    for name, item in (bonus or {}).get('children', ()):
        amount = value(item)
        if name in ('credits', 'gold', 'freeXP', 'crystal'):
            wallet = state._wallet()
            wallet[name] = wallet.get(name, 0) + int(amount)
        elif name in ('slots', 'berths'):
            key = 'accountSlots' if name == 'slots' else 'accountBerths'
            snapshot[key] = int(snapshot.get(key, 0)) + int(amount)
        elif name == 'premium':
            snapshot['premiumExpiryTime'] = max(
                now, int(snapshot.get('premiumExpiryTime', 0))) + int(amount) * 86400
        elif name == 'item':
            compact_descr, count = int(amount), int(value(item, 'count', '1'))
            item_type = state._item_type(compact_descr)
            # Resolve before changing stock: unknown items leave this stage
            # pending instead of marking a reward paid without delivery.
            state._vehicles_module().getItemByCompactDescr(compact_descr)
            old = snapshot.get('inventoryItems', {}).get(item_type, {}).get(compact_descr, 0)
            state._set_owned(compact_descr, item_type, int(old) + count)
        elif name == 'token':
            identifier, count = value(item, 'id'), int(value(item, 'count', '1'))
            if identifier == 'free_award_list':
                snapshot['personalMissionOrders'] = data.personal_mission_orders(
                    snapshot.get('personalMissionOrders', 0) + count)
            else:
                tokens = _tokens(snapshot)
                old = tokens.get(identifier, [TOKEN_EXPIRY, 0])[1]
                limit = int(value(item, 'limit', '2147483647'))
                tokens[identifier] = [TOKEN_EXPIRY, min(limit, old + count)]
                snapshot['personalMissionTokens'] = tokens
        elif name == 'vehicle':
            _grant_vehicle(state, amount)
        elif name == 'dossier':
            identifier = value(item, 'name')
            raw = value(item, 'value')
            count = now if raw == 'timestamp' else int(raw)
            if identifier.startswith('playerBadges:'):
                snapshot.setdefault('accountBadges', {})[identifier.split(':', 1)[1]] = count
            else:
                dossier = snapshot.setdefault('personalMissionDossier', {})
                dossier[identifier] = (int(dossier.get(identifier, 0)) + count
                                       if value(item, 'type') == 'add' else count)
        elif name == 'customizations':
            from items.components import c11n_constants
            kinds = {'camouflage': c11n_constants.CustomizationType.CAMOUFLAGE}
            for row in children(item, 'item'):
                kind = kinds.get(value(row, 'custType'))
                if kind is None:
                    raise GarageError('UNSUPPORTED_PERSONAL_MISSION_CUSTOMIZATION')
                vehicle = state._vehicles_module().VehicleDescr(typeName=value(row, 'boundVehicle'))
                nation, vehicle_id = vehicle.type.id
                bound = state._vehicles_module().makeIntCompactDescrByID('vehicle', nation, vehicle_id)
                buckets = snapshot.setdefault('customizationItems', {}).setdefault(
                    kind, {}).setdefault(int(value(row, 'id')), {})
                buckets[bound] = buckets.get(bound, 0) + int(value(row, 'value'))
        else:
            raise GarageError('UNSUPPORTED_PERSONAL_MISSION_REWARD: ' + name)


def _rebuild_progress_tokens(state, progress, definitions=None, open_section=None):
    """Recompute counters after launcher resets; permanent claims stay claimed."""
    totals = {}
    for key, level in progress.items():
        definition = (definitions[int(key)] if definitions is not None
                      else mission_definition(int(key), open_section))
        for stage in ('main', 'add')[:level]:
            for row in children(child(definition[stage], 'bonus'), 'token'):
                name = value(row, 'id')
                if name != 'free_award_list':
                    totals[name] = totals.get(name, 0) + int(value(row, 'count', '1'))
    claimed = set(state.snapshot().get('personalMissionTokenRewards') or ())
    if claimed:
        for quest in children(child(_resource('tiles.xml', open_section), 'quests'), 'tokenQuest'):
            if value(quest, 'id') not in claimed:
                continue
            for row in children(child(quest, 'bonus'), 'token'):
                name = value(row, 'id')
                if name != 'free_award_list':
                    totals[name] = totals.get(name, 0) + int(value(row, 'count', '1'))
            account = child(child(child(quest, 'conditions'), 'preBattle'), 'account')
            for row in children(account, 'token'):
                name = value(row, 'id')
                totals[name] = totals.get(name, 0) - int(value(row, 'consume', '0'))
    tokens = dict((name, [TOKEN_EXPIRY, max(0, count)]) for name, count in totals.items())
    if tokens != _tokens(state.snapshot()):
        state.snapshot()['personalMissionTokens'] = tokens
        state.revision += 1


def saved_fields(snapshot):
    """JSON fields shared by startup, receipt settlement and launcher edits."""
    progress = data.personal_mission_completed(snapshot.get('personalMissionProgress'))
    rewarded = data.personal_mission_completed(snapshot.get('personalMissionRewarded'))
    result = {
        # Retain ordinary reward claims when completion is reset. Only
        # explicitly journaled orders and female crew can be reclaimed.
        'rewarded': rewarded,
        'pawned': dict((str(key), int(count)) for key, count in
                       (snapshot.get('personalMissionPawned') or {}).items()
                       if str(key) in progress and int(count) in (1, 4)),
        'tankwomen': dict((str(key), True) for key, claimed in
                          (snapshot.get('personalMissionTankwomen') or {}).items()
                          if claimed and str(key) in progress),
        'tokens': _tokens(snapshot),
        'tokenRewards': list(snapshot.get('personalMissionTokenRewards') or ()),
        'dossier': dict(snapshot.get('personalMissionDossier') or {}),
        'rewardJournal': dict(snapshot.get('personalMissionRewardJournal') or {}),
        'resetError': snapshot.get('personalMissionResetError', ''),
    }
    for source, target in (('personalMissionRequestedCompleted', 'requestedCompleted'),
                           ('personalMissionRequestedRegular', 'requestedRegular')):
        if source in snapshot:
            result[target] = snapshot[source]
    return result


def restored_fields(personal_missions):
    mapping = {'rewarded': 'personalMissionRewarded', 'pawned': 'personalMissionPawned',
               'tankwomen': 'personalMissionTankwomen', 'tokens': 'personalMissionTokens',
               'tokenRewards': 'personalMissionTokenRewards', 'dossier': 'personalMissionDossier',
               'rewardJournal': 'personalMissionRewardJournal', 'resetError': 'personalMissionResetError',
               'requestedCompleted': 'personalMissionRequestedCompleted',
               'requestedRegular': 'personalMissionRequestedRegular'}
    return dict((target, personal_missions[source])
                for source, target in mapping.items() if source in personal_missions)


def _token_quests(state, now, open_section=None):
    snapshot = state.snapshot()
    if not snapshot.get('personalMissionTokens'):
        return []
    completed = set(snapshot.get('personalMissionTokenRewards') or ())
    granted = []
    for quest in children(child(_resource('tiles.xml', open_section), 'quests'), 'tokenQuest'):
        identifier = value(quest, 'id')
        if identifier in completed or value(quest, 'enabled') != 'true':
            continue
        conditions = child(child(child(quest, 'conditions'), 'preBattle'), 'account')
        requirements = children(conditions, 'token')
        if not requirements or any(tag != 'token' for tag, unused in conditions['children']):
            continue
        tokens = _tokens(snapshot)
        if any(tokens.get(value(row, 'id'), [0, 0])[1] < int(value(row, 'greaterOrEqual', '1'))
               for row in requirements):
            continue
        with state._transaction():
            _grant_bonus(state, child(quest, 'bonus'), now)
            tokens = _tokens(snapshot)
            for row in requirements:
                token = value(row, 'id')
                tokens[token][1] = max(0, tokens[token][1] - int(value(row, 'consume', '0')))
            snapshot['personalMissionTokens'] = tokens
            completed.add(identifier)
            snapshot['personalMissionTokenRewards'] = sorted(completed)
            state.revision += 1
        granted.append(identifier)
    return granted


def _apply_requested_progress(state):
    """Commit an editor request and its limited clawback together or reject it."""
    snapshot = state.snapshot()
    if 'personalMissionRequestedCompleted' not in snapshot:
        return ''
    from gui.mods.offline_lan_0922 import personal_campaign_ledger
    requested = data.personal_mission_completed(snapshot['personalMissionRequestedCompleted'])
    previous = data.personal_mission_completed(snapshot.get('personalMissionProgress'))
    try:
        with state._transaction():
            journal = snapshot.setdefault('personalMissionRewardJournal', {})
            # Return only orders from missions cancelled in this same edit
            # before reclaiming earnings, so dictionary order cannot reject
            # an otherwise balanced reset.
            for key in previous:
                if requested.get(key, 0) == 0:
                    refund = snapshot.setdefault('personalMissionPawned', {}).pop(key, 0)
                    snapshot['personalMissionOrders'] = data.personal_mission_orders(
                        snapshot.get('personalMissionOrders', 0) + int(refund))
            for key, level in previous.items():
                target = requested.get(key, 0)
                if level == 2 and target < 2:
                    order_key = 'orders:' + key
                    if order_key in journal:
                        personal_campaign_ledger.revoke_orders(state, journal[order_key]['count'])
                        del journal[order_key]
                if target == 0:
                    crew_key = 'crew:' + key
                    if snapshot.get('personalMissionTankwomen', {}).get(key):
                        if crew_key not in journal:
                            raise GarageError('PERSONAL_MISSION_CREW_PROVENANCE_MISSING: ' + key)
                        personal_campaign_ledger.revoke_tankwoman(state, journal[crew_key])
                        del journal[crew_key]
                        snapshot['personalMissionTankwomen'].pop(key, None)
            snapshot['personalMissionProgress'] = requested
            if 'personalMissionRequestedRegular' in snapshot:
                snapshot['personalMissionSelections'] = {'regular':
                    data.personal_mission_regular_selection(snapshot['personalMissionRequestedRegular'])}
            snapshot.pop('personalMissionRequestedCompleted', None)
            snapshot.pop('personalMissionRequestedRegular', None)
            snapshot.pop('personalMissionResetError', None)
            state.revision += 1
    except Exception as error:
        # The transaction restored completion and every asset. Consume the
        # refused edit, so future logins do not repeat an impossible reset.
        snapshot = state.snapshot()
        snapshot.pop('personalMissionRequestedCompleted', None)
        snapshot.pop('personalMissionRequestedRegular', None)
        snapshot['personalMissionResetError'] = str(error)
        state.revision += 1
        return str(error)
    return ''


def _earned_order_count(definition):
    return sum(int(value(row, 'count', '1')) for row in
               children(child(definition['add'], 'bonus'), 'token')
               if value(row, 'id') == 'free_award_list')


def order_balance(snapshot):
    """Available orders are earned final rewards less still-pledged orders.

    A legacy manually entered balance is not an entitlement. Excess legacy
    pledges remain attached to completed missions, but their later refund can
    only release real earned orders, never manufacture a positive balance.
    """
    progress = data.personal_mission_completed(snapshot.get('personalMissionProgress'))
    journal = snapshot.get('personalMissionRewardJournal') or {}
    earned = 0
    for mission_id in range(15, 301, 15):
        key = str(mission_id)
        if progress.get(key) == 2:
            row = journal.get('orders:' + key) or {}
            earned += max(0, int(row.get('count', 0)))
    pledged = sum(int(count) for count in
                  (snapshot.get('personalMissionPawned') or {}).values())
    return max(0, earned - pledged)


def _reconcile_order_balance(state):
    snapshot = state.snapshot()
    balance = order_balance(snapshot)
    if snapshot.get('personalMissionOrders', 0) != balance:
        snapshot['personalMissionOrders'] = balance
        state.revision += 1
    return balance


def _reconcile_order_sources(state, definitions=None, open_section=None):
    """Restore missing legacy receipts and validate counts against live XML."""
    snapshot = state.snapshot()
    progress = data.personal_mission_completed(snapshot.get('personalMissionProgress'))
    rewarded = data.personal_mission_completed(snapshot.get('personalMissionRewarded'))
    journal = dict(snapshot.get('personalMissionRewardJournal') or {})
    for key in list(journal):
        if key.startswith('orders:'):
            del journal[key]
    for mission_id in range(15, 301, 15):
        key = str(mission_id)
        if progress.get(key) != 2 or rewarded.get(key, 0) < 2:
            continue
        definition = (definitions[mission_id] if definitions is not None
                      else mission_definition(mission_id, open_section))
        count = _earned_order_count(definition)
        if count:
            journal['orders:' + key] = {'count': count}
    if journal != (snapshot.get('personalMissionRewardJournal') or {}):
        snapshot['personalMissionRewardJournal'] = journal
        state.revision += 1
    _reconcile_order_balance(state)


def settle(state, now=None, definitions=None, open_section=None):
    """Pay permanent stages once; resettable orders and crew have provenance."""
    now = int(time.time() if now is None else now)
    granted, pending = [], []
    # Normalize before a reset checks its available refund budget. A save
    # without completed missions still needs to lose its old manual balance.
    _reconcile_order_balance(state)
    try:
        _reconcile_order_sources(state, definitions, open_section)
    except Exception as error:
        pending.append(('orders', str(error)))
    reset_error = _apply_requested_progress(state)
    snapshot = state.snapshot()
    progress = data.personal_mission_completed(snapshot.get('personalMissionProgress'))
    rewarded = data.personal_mission_completed(snapshot.get('personalMissionRewarded'))
    for key in sorted(progress, key=int):
        level, paid = progress[key], rewarded.get(key, 0)
        order_key = 'orders:' + key
        journal = snapshot.setdefault('personalMissionRewardJournal', {})
        # Only final missions earn an order. Unchanged ordinary missions need
        # no resource read on every later battle settlement.
        order_may_be_due = level == 2 and int(key) % 15 == 0 and order_key not in journal
        pawn_may_be_due = level == 2 and key in snapshot.get('personalMissionPawned', {})
        if paid >= level and not order_may_be_due and not pawn_may_be_due:
            continue
        try:
            definition = (definitions[int(key)] if definitions is not None
                          else mission_definition(int(key), open_section))
            with state._transaction():
                for stage in range(paid + 1, level + 1):
                    stage_name = 'main' if stage == 1 else 'add'
                    if stage == 1 and key in snapshot.get('personalMissionPawned', {}):
                        stage_name = 'main_award_list'
                    _grant_bonus(state, child(definition[stage_name], 'bonus'), now)
                earned_orders = (_earned_order_count(definition)
                                 if level == 2 and int(key) % 15 == 0 else 0)
                if earned_orders and order_key not in journal:
                    if paid >= 2:
                        # A prior reset retained the credits/items receipt but
                        # reclaimed this exact order reward. Restore only it.
                        snapshot['personalMissionOrders'] = data.personal_mission_orders(
                            snapshot.get('personalMissionOrders', 0) + earned_orders)
                    journal[order_key] = {'count': earned_orders}
                if level == 2:
                    refund = snapshot.setdefault('personalMissionPawned', {}).pop(key, 0)
                    snapshot['personalMissionOrders'] = data.personal_mission_orders(
                        snapshot.get('personalMissionOrders', 0) + int(refund))
                snapshot.setdefault('personalMissionRewarded', {})[key] = max(paid, level)
                state.revision += 1
            granted.append(int(key))
        except Exception as error:
            snapshot = state.snapshot()
            pending.append((int(key), str(error)))
    try:
        _rebuild_progress_tokens(state, progress, definitions, open_section)
        operation_rewards = []
        while True:
            batch = _token_quests(state, now, open_section)
            operation_rewards.extend(batch)
            if not batch:
                break
    except Exception as error:
        pending.append(('operation', str(error)))
        operation_rewards = []
    _reconcile_order_balance(state)
    return {'completed': granted, 'operation_rewards': operation_rewards,
            'pending': pending, 'reset_error': reset_error}


def claim_tankwoman(state, mission_id, nation, vehicle_id, role_id,
                    definition=None, now=None):
    """Redeem the native delayed crew choice, preserving its zero-skill data."""
    key = str(int(mission_id))
    snapshot = state.snapshot()
    if not snapshot.get('personalMissionProgress', {}).get(key):
        raise GarageError('PERSONAL_MISSION_NOT_COMPLETE')
    if snapshot.get('personalMissionTankwomen', {}).get(key):
        raise GarageError('PERSONAL_MISSION_REWARD_ALREADY_CLAIMED')
    definition = definition or mission_definition(int(mission_id))
    delayed = child(definition['main'], 'bonusDelayed')
    crew = children(child(delayed, 'tankmen'), 'tman')
    if len(crew) != 1:
        raise GarageError('PERSONAL_MISSION_HAS_NO_CREW_REWARD')
    tankmen = state._tankmen_module()
    role = state._crew_role_name(role_id)
    vehicle_cd = state._vehicles_module().makeIntCompactDescrByID('vehicle', int(nation), int(vehicle_id))
    vehicle_type = state._vehicles_module().getVehicleType(vehicle_cd)
    if not any(role in roles for roles in vehicle_type.crewRoles):
        raise GarageError('PERSONAL_MISSION_INVALID_CREW_ROLE')
    crew_data = {}
    for name, row in crew[0]['children']:
        raw = value(row)
        if name in ('isPremium', 'isFemale'):
            crew_data[name] = raw == 'true'
        elif name in ('skills', 'freeSkills'):
            crew_data[name] = raw.split()
        elif name == 'role':
            crew_data[name] = raw
        else:
            crew_data[name] = int(raw)
    crew_data.update(nationID=int(nation), vehicleTypeID=int(vehicle_id), role=role)
    descriptor = tankmen.makeTmanDescrByTmanData(crew_data)
    with state._transaction():
        tankman_id = state._next_tankman_id()
        state._to_barracks(tankman_id, descriptor)
        state._touched_tankmen.add(tankman_id)
        import base64
        journal = snapshot.setdefault('personalMissionRewardJournal', {})
        bonus_key = 'crewBonus:' + key
        first_claim = bonus_key not in journal
        bonus = {'children': [(name, row) for name, row in delayed['children']
                 if name != 'tankmen' and (first_claim or name == 'dossier')]}
        dossier_count = sum(int(value(row, 'value', '0')) for row in children(bonus, 'dossier')
                            if value(row, 'name') == 'achievements:tankwomenProgress')
        _grant_bonus(state, bonus, int(time.time() if now is None else now))
        journal[bonus_key] = True
        journal['crew:' + key] = {'tankman': tankman_id,
            'descriptor': base64.b64encode(descriptor).decode('ascii'),
            'dossier_count': dossier_count}
        snapshot.setdefault('personalMissionTankwomen', {})[key] = True
        state.revision += 1
    return tankman_id
