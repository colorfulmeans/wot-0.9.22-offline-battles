"""Fixed-duration rental prizes and integer credit compensation policy."""
import hashlib

COMPENSATION_PERCENT = {1: 1, 3: 3, 7: 5, 14: 10, 30: 25,
                        90: 50, 180: 75, 360: 100}
DAY = 86400


def expire(snapshot, now):
    from gui.mods.offline_lan_0922.personal_campaign_ui import queue_notification
    expired = []
    for record in snapshot.get('vehicles', ()):
        rental = record.get('rent')
        if not rental:
            continue
        expiry = int(rental[1])
        if expiry <= now and rental[0].get('offlineNoticeExpiry') != expiry:
            rental[0]['offlineNoticeExpiry'] = expiry
            expired.append(dict(vehicle_type=int(record['vehicleTypeCompactDescr']), expiry=expiry))
    if expired:
        queue_notification(snapshot, {'rental_expired': expired, 'notification_at': int(now)})
    return expired


def compensation(gold_price, days):
    return int(gold_price) * 400 * COMPENSATION_PERCENT[int(days)] // 100


def choose(pool, records, days, now, seed):
    """Active rentals extend; only an entirely permanent tier pays credits."""
    by_cd = dict((int(row['vehicleTypeCompactDescr']), row) for row in records)
    missing, rented = [], []
    for entry in pool:
        owned = by_cd.get(entry['cd'])
        if owned is None or (owned.get('rent') and int(owned['rent'][1]) <= now):
            missing.append(entry)
        elif owned.get('rent'):
            rented.append(entry)
    candidates = missing or rented or pool
    if not candidates:
        raise ValueError('No audited vehicle exists for this rental tier')
    candidates = sorted(candidates, key=lambda row: row['name'])
    draw = int(hashlib.sha256(seed.encode('utf-8')).hexdigest(), 16) % len(candidates)
    selected = candidates[draw]
    owned = by_cd.get(selected['cd'])
    if not missing and not rented:
        return dict(kind='compensation', vehicle=selected['name'],
                    vehicle_type=selected['cd'], credits=compensation(selected['gold'], days))
    previous = int(owned['rent'][1]) if owned and owned.get('rent') else 0
    return dict(kind='rental', vehicle=selected['name'], vehicle_type=selected['cd'],
                days=int(days), expiry=max(now, previous) + int(days) * DAY,
                extended=previous > now)


def catalogue(vehicles, tier):
    from gui.mods.offline_lan_0922 import price_catalogue, vehicle_blacklist
    from gui.mods.offline_lan_0922.vehicle_configuration import is_standard_battle_vehicle
    import nations
    result = []
    for nation in nations.AVAILABLE_NAMES:
        nation_id = nations.INDICES[nation]
        for unused_id, vehicle in vehicles.g_list.getList(nation_id).items():
            if (int(vehicle.level) != tier or vehicle.name in vehicle_blacklist.UNUSABLE_VEHICLES
                    or not is_standard_battle_vehicle(vehicle)):
                continue
            price = price_catalogue.VEHICLE_PRICES.get(vehicle.name)
            if not price:
                continue
            gold = int(price[1])
            # Known 5-gold high-tier service placeholders cannot establish a
            # prize's credit value. Keep them outside the audited reward pool.
            if gold <= 0 or (tier >= 8 and gold <= 5):
                continue
            cd = vehicles.makeIntCompactDescrByID('vehicle', nation_id, unused_id)
            result.append(dict(name=vehicle.name, cd=int(cd), gold=gold))
    return result


def grant(state, tier, days, now, seed):
    vehicles = state._vehicles_module()
    award = choose(catalogue(vehicles, tier), state._records(), days, now, seed)
    if award['kind'] == 'compensation':
        wallet = state._wallet()
        value = int(wallet.get('credits', 0)) + award['credits']
        if value > 2 ** 31 - 1:
            raise ValueError('Rental compensation exceeds the native credit limit')
        wallet['credits'] = value
        return award
    record = next((row for row in state._records()
                   if int(row['vehicleTypeCompactDescr']) == award['vehicle_type']), None)
    if record is None:
        from items import ITEM_TYPE_INDICES
        from gui.mods.offline_lan_0922 import bootstrap
        bootstrap._build_purchased_vehicle(state.snapshot(), vehicles,
            state._tankmen_module(), ITEM_TYPE_INDICES,
            state._default_vehicle_settings(), award['vehicle'])
        record = next(row for row in state._records()
                      if int(row['vehicleTypeCompactDescr']) == award['vehicle_type'])
        state._touched_tankmen.update(record.get('tankmen', {}))
        state._touch_item_changes({}, record.get('inventoryItems', {}))
        import base64
        award['crew_passports'] = [base64.b64encode(raw).decode('ascii')
                                  for raw in record.get('tankmen', {}).values()]
    # #1513 Vehicle.__init__ calls RentalInfoProvider(*invData['rent'],
    # isRented=True): additionalData, absolute expiry, battles, wins.
    record['rent'] = [{}, award['expiry'], 0, 0]
    state._touched.add(int(record['id']))
    return award
