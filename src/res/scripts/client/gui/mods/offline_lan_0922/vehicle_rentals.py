"""Fixed-duration rental prizes and integer credit compensation policy."""
import hashlib

COMPENSATION_PERCENT = {1: 1, 3: 3, 7: 5, 14: 10, 30: 25,
                        90: 50, 180: 75, 360: 100}
DAY = 86400

# Offline prize valuations approved for #1513 service/placeholder vehicles.
# These do not alter the native shop or claim to be historical retail prices.
PRIZE_GOLD = {
    'germany:G122_VK6501H': 1500,
    'germany:G137_PzVI_Tiger_217': 3500,
    'ussr:R99_T44_122': 7200,
    'germany:G16_PzVIB_Tiger_II_F': 7700,
    'france:F84_Somua_SM': 12000,
    'germany:G44_JagdTigerH': 10900,
    'germany:G85_Aufklarungspanzer_V': 6500,
    'uk:GB93_Caernarvon_AX': 12000,
    'ussr:R122_T44_100B': 7500,
    'ussr:R127_T44_100_P': 7500,
    'ussr:R135_T_103': 9000,
    'ussr:R98_T44_85M': 6500,
    'uk:GB84_Chieftain_Mk6': 22500,
}


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
    percent = 100 if int(days) == 0 else COMPENSATION_PERCENT[int(days)]
    return int(gold_price) * 400 * percent // 100


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
    if not days:
        return dict(kind='vehicle', vehicle=selected['name'], vehicle_type=selected['cd'])
    previous = int(owned['rent'][1]) if owned and owned.get('rent') else 0
    return dict(kind='rental', vehicle=selected['name'], vehicle_type=selected['cd'],
                days=int(days), expiry=max(now, previous) + int(days) * DAY,
                extended=previous > now)


def catalogue(vehicles, tier):
    from gui.mods.offline_lan_0922 import price_catalogue, vehicle_blacklist
    from gui.mods.offline_lan_0922.vehicle_configuration import is_standard_battle_vehicle
    import nations
    result = []
    tiers = (tier,) if isinstance(tier, int) else tuple(tier)
    for nation in nations.AVAILABLE_NAMES:
        nation_id = nations.INDICES[nation]
        for unused_id, vehicle in vehicles.g_list.getList(nation_id).items():
            if (int(vehicle.level) not in tiers or vehicle.name in vehicle_blacklist.UNUSABLE_VEHICLES
                    or not is_standard_battle_vehicle(vehicle)):
                continue
            price = price_catalogue.VEHICLE_PRICES.get(vehicle.name)
            if not price:
                continue
            gold = PRIZE_GOLD.get(vehicle.name, int(price[1]))
            # Known 5-gold high-tier service placeholders cannot establish a
            # prize's credit value. Keep them outside the audited reward pool.
            if gold <= 0 or (int(vehicle.level) >= 8 and gold <= 5):
                continue
            cd = vehicles.makeIntCompactDescrByID('vehicle', nation_id, unused_id)
            result.append(dict(name=vehicle.name, cd=int(cd), gold=gold))
    return result


def grant(state, tier, days, now, seed):
    vehicles = state._vehicles_module()
    pool = catalogue(vehicles, tier)
    award = choose(pool, state._records(), days, now, seed)
    print('[Offline LAN 0.9.22] VEHICLE PRIZE kind=%s vehicle=%s days=%d pool=%d credits=%d extended=%s' % (
        award['kind'], award['vehicle'], days, len(pool), award.get('credits', 0), award.get('extended', False)))
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
    if award['kind'] == 'vehicle':
        record.pop('rent', None)
    else:
        record['rent'] = [{}, award['expiry'], 0, 0]
    state._touched.add(int(record['id']))
    return award
