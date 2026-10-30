"""#1513 service-channel envelopes; stock formatters own all presentation.

These functions publish facts only. They never grant assets or mark a receipt
delivered; the durable caller retains ownership of retries and acknowledgement.
"""

import copy
import time
import uuid

_sent = set()


def publish(kind, data, identifier=None, timestamp=None):
    from chat_shared import SYS_MESSAGE_IMPORTANCE, SYS_MESSAGE_TYPE
    from messenger import MessengerEntry
    stamp = int(time.time() if timestamp is None else timestamp)
    message_type = getattr(SYS_MESSAGE_TYPE, kind)
    identifier = int(identifier if identifier is not None else
                     (uuid.uuid4().int & 0x7fffffffffffffff))
    identity = (kind, identifier)
    if identity in _sent:
        return identifier
    action = {'sentTime': stamp, 'data': {
        'messageID': identifier, 'user_id': 0,
        'type': message_type.index(),
        'importance': SYS_MESSAGE_IMPORTANCE.normal.index(),
        'active': True, 'started_at': stamp, 'finished_at': None,
        'created_at': stamp, 'data': copy.deepcopy(data)}}
    MessengerEntry.g_instance.protos.BW.serviceChannel.onReceiveSysMessage(action)
    _sent.add(identity)
    print('[Offline LAN 0.9.22] NATIVE NOTICE admitted type=%s id=%s' % (kind, identifier))
    return identifier


def publish_settlement(settlement, identifier=None):
    import hashlib
    from gui.mods.offline_lan_0922.ui_i18n import as_text
    rows = settlement_messages(settlement, settlement.get('notification_at'))
    identity = as_text(identifier or uuid.uuid4().hex)
    for index, (kind, payload) in enumerate(rows):
        key = ('%s:%d' % (identity, index)).encode('utf-8')
        message_id = int(hashlib.sha256(key).hexdigest()[:15], 16)
        publish(kind, payload, message_id, settlement.get('notification_at'))
    return bool(rows)


def invoice(assets, timestamp=None):
    """InvoiceReceivedFormatter._composeOperations consumes this exact shape."""
    from constants import INVOICE_ASSET
    stamp = int(time.time() if timestamp is None else timestamp)
    return {'assetType': INVOICE_ASSET.DATA, 'at': stamp,
            'data': copy.deepcopy(assets)}


def _add(assets, key, value):
    if value:
        assets[key] = assets.get(key, 0) + value


def _vehicle_cd(row):
    if row.get('vehicle_type'):
        return int(row['vehicle_type'])
    from items import vehicles
    nation, vehicle = vehicles.VehicleDescr(typeName=row['vehicle']).type.id
    return int(vehicles.makeIntCompactDescrByID('vehicle', nation, vehicle))


def reward_assets(rows, sign=1):
    """Convert actual ledger deltas, never current balances or quest bonuses.

    Unsupported facts fail visibly to their queue owner instead of silently
    acknowledging an empty native message or fabricating another payment.
    """
    import base64
    assets = {}
    for row in rows:
        if 'kind' not in row:
            nested = []
            for kind, node in row.get('children', ()):
                children = dict(node.get('children', ()))
                if kind in ('credits', 'gold', 'crystal', 'freeXP', 'slots', 'berths', 'premium'):
                    nested.append({'kind': kind, 'count': int(node.get('value', 0))})
                elif kind == 'item':
                    nested.append({'kind': kind, 'id': int(node['value']),
                        'count': int(children.get('count', {}).get('value', 1))})
                elif kind == 'token':
                    nested.append({'kind': kind,
                        'id': children.get('id', {}).get('value', ''),
                        'count': int(children.get('count', {}).get('value', 1))})
                elif kind == 'customizations':
                    for tag, item in node.get('children', ()):
                        if tag != 'item':
                            continue
                        values = dict(item.get('children', ()))
                        assets.setdefault('customizations', []).append({
                            'custType': values['custType']['value'],
                            'value': sign * int(values['value']['value']),
                            'isPermanent': True})
                elif kind not in ('free_award_list',):
                    raise ValueError('Unreviewed native XML reward: %s' % kind)
            _merge(assets, reward_assets(nested, sign))
            continue
        kind = row.get('kind')
        count = sign * int(row.get('count', 0))
        if kind in ('credits', 'gold', 'crystal', 'freeXP', 'slots', 'berths'):
            _add(assets, kind, count)
        elif kind == 'premium':
            seconds = int(row.get('seconds', int(row.get('count', 0)) * 86400))
            _add(assets, 'premium', sign * seconds / 86400.0)
        elif kind == 'item':
            items = assets.setdefault('items', {})
            identifier = int(row['id'])
            items[identifier] = items.get(identifier, 0) + count
        elif kind in ('vehicle', 'vehicle_restored'):
            assets.setdefault('vehicles', {})[sign * _vehicle_cd(row)] = {}
        elif kind == 'compensation':
            _add(assets, 'credits', sign * int(row['credits']))
            from gui.shared.money import Money
            assets.setdefault('vehicles', {})[_vehicle_cd(row)] = {
                'customCompensation': tuple(Money(credits=sign * int(row['credits'])))}
        elif kind == 'rental':
            assets.setdefault('vehicles', {})[_vehicle_cd(row)] = {
                'rent': {'time': int(row['days'])}}
            assets.setdefault('tankmen', []).extend(base64.b64decode(value)
                for value in row.get('crew_passports', ()))
        elif kind == 'crew':
            passports = row.get('passports')
            if not passports:
                raise ValueError('Native crew invoice requires durable crew passports')
            if sign < 0:
                raise ValueError('Native crew withdrawal requires a reviewed invoice contract')
            assets.setdefault('tankmen', []).extend(
                base64.b64decode(value) for value in passports)
        elif kind in ('style', 'appearance', 'customization'):
            # The stock reader selects localization keys by textual custType,
            # not by the numeric customization-2.0 cache index.
            cust_type = ('style' if kind == 'style' else 'camouflage'
                         if kind == 'customization' else
                         {1: 'paint', 2: 'camouflage', 3: 'decal',
                          5: 'modification'}[int(row['type'])])
            permanent = True
            if kind == 'style':
                from items import vehicles
                from gui.mods.offline_lan_0922.customization_rules import is_rental
                style = vehicles.g_cache.customization20().styles.get(int(row['id']))
                if style is None:
                    raise ValueError('Native style notification descriptor is unavailable')
                permanent = not is_rental(style)
            assets.setdefault('customizations', []).append({
                'custType': cust_type, 'value': count, 'isPermanent': permanent})
        elif kind == 'token':
            assets.setdefault('tokens', {})[row['id']] = {'count': count}
        elif kind == 'badge':
            assets.setdefault('dossier', {}).setdefault('account', {})[
                ('badges', int(row['id']))] = {'value': count}
        elif kind == 'dossier':
            assets.setdefault('dossier', {}).setdefault('account', {})[
                ('achievements', row['id'])] = {'value': count}
        else:
            raise ValueError('Unreviewed native notification asset: %s' % kind)
    return assets


def _merge(destination, source):
    for key, value in source.items():
        if isinstance(value, dict):
            target = destination.setdefault(key, {})
            for identifier, entry in value.items():
                if isinstance(entry, (int, float)):
                    target[identifier] = target.get(identifier, 0) + entry
                else:
                    target[identifier] = copy.deepcopy(entry)
        elif isinstance(value, list):
            destination.setdefault(key, []).extend(value)
        else:
            _add(destination, key, value)


def quest_payload(assets):
    """TokenQuestsFormatter expects a list of vehicle-invoice dictionaries."""
    payload = copy.deepcopy(assets)
    vehicles = payload.get('vehicles')
    if isinstance(vehicles, dict):
        compensation = sum(int(row['customCompensation'][0])
            for row in vehicles.values() if row.get('customCompensation'))
        if compensation:
            payload['credits'] = payload.get('credits', 0) - compensation
        payload['vehicles'] = [vehicles]
    return payload


def settlement_messages(settlement, timestamp=None):
    """Native message families for immutable campaign and launcher deltas."""
    result = []
    if settlement.get('reset_error'):
        from gui.mods.offline_lan_0922.personal_campaign_ui import _reset_error
        result.append(('adminMessage', _reset_error(settlement['reset_error'])))

    def assets_for(rows, sign=1):
        # Old saves recorded a count but not the members' native passports.
        # Preserve that known fact through the stock general notice instead
        # of inventing member identities or holding the queue indefinitely.
        current = []
        for row in rows:
            if row.get('kind') == 'crew' and not row.get('passports') and sign > 0:
                from gui.mods.offline_lan_0922.ui_i18n import tr
                result.append(('adminMessage', tr('Crew members: %d') % int(row['count'])))
            else:
                current.append(row)
        return reward_assets(current, sign)
    for row in settlement.get('rental_expired', ()):
        result.append(('rentalsExpired', {'vehTypeCD': int(row['vehicle_type'])}))
    for row in settlement.get('ordinary_missions', ()):
        assets = assets_for(row['rewards'])
        payload = quest_payload(assets)
        payload['completedQuestIDs'] = set((row['id'],))
        result.append(('tokenQuests', payload))
        for reward in row['rewards']:
            if reward['kind'] == 'rental':
                result.append(('vehicleRented', {'vehTypeCD': int(reward['vehicle_type']),
                                                'time': int(reward['expiry'])}))
    for row in settlement.get('missions', ()):
        revoked = row.get('phase') == 'revoked'
        changed = int(row.get('after', 0)) > int(row.get('before', 0))
        paid = bool(row.get('paid_stages'))
        if not (revoked or changed or paid or row.get('orders_refunded')):
            continue
        assets = assets_for(row.get('rewards', ()) if paid or revoked else (),
                               -1 if revoked else 1)
        orders = (int(row.get('orders_earned', 0)) +
                  int(row.get('orders_refunded', 0)) -
                  int(row.get('orders_revoked', 0)))
        if orders:
            from constants import PERSONAL_QUEST_FREE_TOKEN_NAME
            assets.setdefault('tokens', {})[PERSONAL_QUEST_FREE_TOKEN_NAME] = {'count': orders}
        # The native PersonalMissionsFormatter reads this account quest ID,
        # while completedQuestIDs carries the unique main/add cache IDs.
        if not revoked:
            assets['potapovQuestID'] = int(row['id'])
            assets['completedQuestIDs'] = set(
                row[name] for name in ('main_quest', 'add_quest')
                if row.get(name) and (name == 'main_quest' or int(row.get('after', 0)) == 2))
            result.append(('potapovQuestBonus', quest_payload(assets)))
        elif assets:
            result.append(('invoiceReceived', invoice(assets, timestamp)))
    for row in list(settlement.get('operations', ())) + list(settlement.get('account_changes', ())):
        rewards = row.get('rewards', ())
        for reward in rewards:
            if reward.get('kind') == 'earnings_percent':
                # This offline-only setting is not an asset grant. Use the
                # stock general server notice, never a counterfeit invoice.
                from gui.mods.offline_lan_0922.ui_i18n import tr
                result.append(('adminMessage', tr('Battle earnings multiplier: %d%% -> %d%%') %
                    (int(reward['before']), int(reward['count']))))
        assets = assets_for([reward for reward in rewards
                                if reward.get('kind') != 'earnings_percent'],
            -1 if row.get('phase') == 'revoked' else 1)
        if assets:
            result.append(('invoiceReceived', invoice(assets, timestamp)))
    return result
