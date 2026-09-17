"""Offline shop and reserve policy; no native GUI or network dependencies.

The permanent bond shop postdates 0.9.22. The first 2019 assortment is
intersected with this client's definitions. Retired prices, reserve prices
and daily missions below are explicit offline extensions, not retail data.
"""

import copy
import hashlib
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
# Each template has a fixed reward. Only the daily selection is random;
# opening the page, restarting or receiving a late receipt cannot reroll it.
MISSION_POOL = (
    ('battles_3', 'Play %d battles', 'battles', 3, 'xp'),
    ('battles_4', 'Play %d battles', 'battles', 4, 'free_xp'),
    ('battles_5', 'Play %d battles', 'battles', 5, 'crew_xp'),
    ('damage_2000', 'Deal %d damage', 'damage', 2000, 'xp'),
    ('damage_3000', 'Deal %d damage', 'damage', 3000, 'credits'),
    ('damage_5000', 'Deal %d damage', 'damage', 5000, 'crew_xp'),
    ('wins_1', 'Win %d battles', 'wins', 1, 'free_xp'),
    ('wins_2', 'Win %d battles', 'wins', 2, 'credits'),
    ('wins_3', 'Win %d battles', 'wins', 3, 'crew_xp'),
)
MISSION_BY_ID = dict((row[0], row) for row in MISSION_POOL)
for _key, _label, _target, _reward in DAILY_MISSIONS:
    MISSION_BY_ID[_key] = (_key, _label, _key, _target, _reward)

# Mod-owned IDs, using the retail GoodieData and GoodieVariable wire shapes.
RESERVE_IDS = dict((row[0], 92001 + index)
                  for index, row in enumerate(RESERVES))
RESERVE_KEYS = dict((value, key) for key, value in RESERVE_IDS.items())


def owned_vehicle_types(snapshot):
    return set(int(row.get('vehicleTypeCompactDescr', 0))
               for row in snapshot.get('vehicles', ()))


def reserve_catalogue():
    resources = {'xp': 30, 'crew_xp': 40, 'free_xp': 50, 'credits': 20}
    return {
        'prices': dict((RESERVE_IDS[key], (0, price))
                       for key, unused, percent, price in RESERVES),
        'notInShop': set(),
        'goodies': dict((RESERVE_IDS[key],
                        (1, (3, None, None), True, 3600, None, 0, False,
                         None, (resources[key], percent, True)))
                       for key, unused, percent, price in RESERVES)}


def reserve_inventory(snapshot, now=None):
    reserves = reserve_state(snapshot)
    stamp = now_seconds(now)
    result = {}
    for key, uid in RESERVE_IDS.items():
        interval = reserves['active'].get(key)
        active = interval is not None and interval[1] > stamp
        result[uid] = (1 if active else 0,
                       interval[1] if active else 0, reserves['counts'][key])
    return result


def service_diff(snapshot, unused_outcome=None):
    return {'goodies': reserve_inventory(snapshot),
            'badges': tuple(snapshot.get('selectedBadges') or ())}


def badge_catalogue():
    # Read the installed client's definitions only when choosing a cosmetic.
    # Do not add a GUI dependency to hidden-worker bootstrap.
    from gui.shared.utils.requesters.badges_requester import (
        _readBadges, _BADGES_XML_PATH)
    return _readBadges(_BADGES_XML_PATH)


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
    same_day = int(raw.get('day', -1)) == day
    ids = raw.get('missions') if same_day else None
    if same_day and ids is None:
        # Finish the old fixed set today without granting its rewards twice.
        ids = [row[0] for row in DAILY_MISSIONS]
    if not (isinstance(ids, (list, tuple)) and len(ids) == 3 and
            len(set(ids)) == 3 and all(key in MISSION_BY_ID for key in ids)):
        def rank(row):
            return hashlib.sha256(('%d:%s' % (day, row[0])).encode('ascii')).digest()
        ids = [min((row for row in MISSION_POOL if row[2] == metric),
                   key=rank)[0] for metric in ('battles', 'damage', 'wins')]
    claimed = (raw.get('claimed') or []) if same_day else []
    result = {'day': day, 'missions': list(ids),
              'claimed': [key for key in ids if key in claimed]}
    for key in ids:
        target = MISSION_BY_ID[key][3]
        result[key] = min(target, max(0, int(raw.get(key, 0)))) if same_day else 0
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
        # Offers grant purchase access, not inventory ownership. Account sync
        # requires vehicleTypeCompactDescrs to match complete garage records;
        # GarageState.buy_vehicle adds that ownership only after a purchase.
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
            if offer['cd'] in owned_vehicle_types(snapshot):
                raise GarageError('the account already owns this vehicle')
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
        elif action == 'expire_reserves':
            reserves = reserve_state(snapshot)
            for kind, interval in list(reserves['active'].items()):
                if interval[1] <= stamp:
                    reserves['history'][kind].append(interval)
                    del reserves['active'][kind]
            snapshot['personalReserves'] = reserves
        elif action == 'select_badge':
            try:
                badge = int(key)
            except (TypeError, ValueError):
                raise GarageError('Unknown badge.')
            if badge and badge not in badge_catalogue():
                raise GarageError('Unknown badge.')
            snapshot['selectedBadges'] = [badge] if badge else []
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
    for key in daily['missions']:
        unused_id, unused_label, metric, target, reward = MISSION_BY_ID[key]
        daily[key] = min(target, daily[key] + values[metric])
        if daily[key] >= target and key not in daily['claimed']:
            daily['claimed'].append(key)
            reserves['counts'][reward] += 1
            granted.append(reward)
    snapshot['dailyMissions'] = daily
    snapshot['personalReserves'] = reserves
    return granted


def saved_fields(snapshot):
    return {'personalReserves': reserve_state(snapshot),
            'dailyMissions': copy.deepcopy(snapshot.get('dailyMissions') or {}),
            'firstWinDays': dict(snapshot.get('firstWinDays') or {}),
            'selectedBadges': [int(value) for value in
                               (snapshot.get('selectedBadges') or ())[:1]
                               if int(value) > 0]}
