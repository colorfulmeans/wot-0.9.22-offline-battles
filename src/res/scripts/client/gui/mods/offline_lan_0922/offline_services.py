"""Offline shop and reserve policy; no native GUI or network dependencies.

The permanent bond shop postdates 0.9.22. The first 2019 assortment is
intersected with this client's definitions. Retired prices, reserve prices
and daily missions below are explicit offline extensions, not retail data.
"""

import copy
import time

OFFICIAL_BOND_OFFERS = {
    'china:Ch25_121_mod_1971B': 15000,
    'usa:A92_M60': 15000,
    'uk:GB13_FV215b': 12000,
    'france:F74_AMX_M4_1949_Liberte': 8000,
    'usa:A117_T26E5_Patriot': 8000,
    'germany:G119_Pz58_Mutz': 8000,
    'ussr:R146_STG_Tday': 8000,
    'germany:G70_PzIV_Hydro': 3000,
}
# Tier VII / IX / X offline brackets. The old tech-tree credit prices and
# placeholder gold values are not offers for these removed definitions.
RETIRED_BOND_OFFERS = {
    'germany:G85_Auf_Panther': 6000,
    'ussr:R75_SU122_54': 12000,
    'ussr:R96_Object_430B': 15000,
    'ussr:R93_Object263B': 15000,
    'germany:G98_Waffentrager_E100': 15000,
}
BOND_OFFERS = dict(OFFICIAL_BOND_OFFERS, **RETIRED_BOND_OFFERS)

# Keep the four pre-1.18 reserve types separate. At most three different
# types may be active, each for one real-time hour including time offline.
RESERVES = (
    ('xp', 'Combat XP', 50, 50),
    ('crew_xp', 'Crew XP', 200, 100),
    ('free_xp', 'Free XP', 200, 50),
    ('credits', 'Credits', 50, 100),
)
RESERVE_BY_ID = dict((row[0], row) for row in RESERVES)
DAILY_MISSIONS = (
    ('battles', 'Play 3 battles', 3, 'xp'),
    ('damage', 'Deal 3000 damage', 3000, 'credits'),
    ('wins', 'Win 1 battle', 1, 'crew_xp'),
)


def now_seconds(now=None):
    return int(time.time() if now is None else now)


def reserve_state(snapshot):
    raw = snapshot.get('personalReserves') or {}
    counts, active, history = {}, {}, {}
    for key in RESERVE_BY_ID:
        counts[key] = max(0, int((raw.get('counts') or {}).get(key, 0)))
        value = (raw.get('active') or {}).get(key)
        if isinstance(value, (list, tuple)) and len(value) == 2:
            start, end = int(value[0]), int(value[1])
            if 0 <= start < end:
                active[key] = [start, end]
        history[key] = []
        for interval in (raw.get('history') or {}).get(key, ()):
            if isinstance(interval, (list, tuple)) and len(interval) == 2:
                start, end = int(interval[0]), int(interval[1])
                if 0 <= start < end:
                    history[key].append([start, end])
    return {'counts': counts, 'active': active, 'history': history}


def daily_state(snapshot, now=None):
    day = now_seconds(now) // 86400
    raw = snapshot.get('dailyMissions') or {}
    if int(raw.get('day', -1)) != day:
        return {'day': day, 'battles': 0, 'damage': 0, 'wins': 0,
                'claimed': []}
    result = {'day': day, 'claimed': list(raw.get('claimed') or [])}
    for key, unused_label, target, unused_reward in DAILY_MISSIONS:
        result[key] = min(target, max(0, int(raw.get(key, 0))))
    return result


def publish_offers(snapshot, vehicles):
    """Publish one price and entitlement to all native purchase consumers."""
    rows = []
    for name, price in sorted(BOND_OFFERS.items()):
        try:
            descriptor = vehicles.VehicleDescr(typeName=name)
            vehicle_type = descriptor.type
            nation, vehicle_id = vehicle_type.id
            cd = vehicles.makeIntCompactDescrByID('vehicle', nation, vehicle_id)
        except (KeyError, ValueError):
            continue
        snapshot.setdefault('shopItemPrices', {})[cd] = {'crystal': price}
        snapshot.setdefault('notInShopItems', set()).discard(cd)
        snapshot.setdefault('shopVehicleOfferCompactDescrs', set()).add(cd)
        snapshot.setdefault('vehicleTypeCompactDescrs', set()).add(cd)
        rows.append({'name': name, 'cd': cd, 'price': price,
                     'level': int(vehicle_type.level),
                     'label': vehicle_type.userString,
                     'retired': name in RETIRED_BOND_OFFERS})
    snapshot['offlineVehicleOffers'] = rows


def transact(state, action, key, now=None):
    """Mutate through GarageState's rollback and persistence boundary."""
    from gui.mods.offline_lan_0922.account_rpc.garage import GarageError
    stamp = now_seconds(now)
    with state._transaction():
        snapshot = state.snapshot()
        if action == 'vehicle':
            offer = next((row for row in snapshot.get('offlineVehicleOffers', [])
                          if row['name'] == key), None)
            if offer is None:
                raise GarageError('This vehicle is not offered.')
            # The common purchase owns duplicate/slot/affordability checks,
            # real stock modules and crew. Never construct a reward clone.
            state.buy_vehicle(offer['cd'], recruit_crew=True)
        elif action in ('buy_reserve', 'activate_reserve'):
            if key not in RESERVE_BY_ID:
                raise GarageError('Unknown personal reserve.')
            reserves = reserve_state(snapshot)
            if action == 'buy_reserve':
                state._charge({'gold': RESERVE_BY_ID[key][3]})
                reserves['counts'][key] += 1
            else:
                # Reconnect receipts can arrive after another reserve was
                # activated. Retain expired intervals so their battle-start
                # entitlement cannot be overwritten by the new activation.
                for kind, interval in reserves['active'].items():
                    if interval[1] <= stamp:
                        reserves['history'][kind].append(interval)
                active = dict((kind, interval) for kind, interval in
                              reserves['active'].items() if interval[1] > stamp)
                if key in active:
                    raise GarageError('This reserve type is already active.')
                if len(active) >= 3:
                    raise GarageError('Only three reserve types can be active.')
                if reserves['counts'][key] < 1:
                    raise GarageError('No personal reserve of this type is owned.')
                reserves['counts'][key] -= 1
                active[key] = [stamp, stamp + 3600]
                reserves['active'] = active
            snapshot['personalReserves'] = reserves
        else:
            raise GarageError('Unknown offline service action.')
        state.revision += 1
    return True


def reserve_bonuses(snapshot, awarded, battle_start):
    """Freeze reserve eligibility at battle start, including expiry in battle."""
    reserves = reserve_state(snapshot)
    bonuses = dict((key, 0) for key in RESERVE_BY_ID)
    for key, unused_label, percent, unused_price in RESERVES:
        intervals = list(reserves['history'][key])
        if key in reserves['active']:
            intervals.append(reserves['active'][key])
        if any(start <= battle_start < end for start, end in intervals):
            base = awarded.get('xp' if key == 'crew_xp' else key, 0)
            bonuses[key] = max(0, int(base)) * percent // 100
    return bonuses


def advance_daily(snapshot, facts, now=None):
    """Called inside the durable battle receipt transaction, once per battle."""
    stamp = now_seconds(now)
    if int((snapshot.get('dailyMissions') or {}).get('day', -1)) > stamp // 86400:
        return []
    daily = daily_state(snapshot, stamp)
    reserves = reserve_state(snapshot)
    values = {'battles': 1, 'damage': max(0, int(facts.get('damage', 0))),
              'wins': int(bool(facts.get('won')))}
    granted = []
    for key, unused_label, target, reward in DAILY_MISSIONS:
        daily[key] = min(target, daily[key] + values[key])
        if daily[key] >= target and key not in daily['claimed']:
            daily['claimed'].append(key)
            reserves['counts'][reward] += 1
            granted.append(reward)
    snapshot['dailyMissions'] = daily
    snapshot['personalReserves'] = reserves
    return granted


def saved_fields(snapshot):
    return {'personalReserves': reserve_state(snapshot),
            'dailyMissions': copy.deepcopy(snapshot.get('dailyMissions') or {})}
