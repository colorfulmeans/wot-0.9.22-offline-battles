# -*- coding: utf-8 -*-
"""Approved offline ordinary missions, independent of personal campaigns.

Every progress counter expires with its assignment day. Three/seven-day rental
missions describe appearance cadence and prize duration, not progress carryover.
The catalogue is offline product policy, not a recovered historical server list.
"""
import copy
import hashlib
import time

SCHEMA = 2
DAY = 86400


def _mission(key, pool, english, chinese, goals, rewards):
    return dict(id=key, pool=pool, name=dict(en=english, zh_cn=chinese),
                goals=goals, rewards=rewards)


CATALOGUE = [
    _mission('participate3', 'basic', 'Complete 3 battles', u'累计完成3场战斗',
        {'battles': 3}, {'credits': 30000, 'smallRepairkit': 2}),
    _mission('win1', 'basic', 'Win a battle', u'取得1场胜利', {'wins': 1}, {'credits': 40000}),
    _mission('destroy3', 'basic', 'Destroy 3 enemy vehicles', u'累计击毁3辆敌车', {'kills': 3}, {'credits': 50000}),
    _mission('damage3000', 'basic', 'Deal 3000 damage', u'累计造成3000伤害', {'damage': 3000}, {'credits': 60000}),
    _mission('damage8', 'basic', 'Damage 8 enemy vehicles', u'累计对8辆敌车造成伤害', {'damaged': 8},
        {'smallRepairkit': 3, 'smallMedkit': 3, 'handExtinguishers': 3}),
    _mission('xp1500', 'basic', 'Earn 1500 base XP', u'累计获得1500基础经验', {'xp': 1500}, {'freeXP': 1000}),
    _mission('top5', 'basic', 'Top 5 by base XP in a battle', u'单场基础经验进入本队前5名', {'top5': 1},
        {'credits': 40000, 'freeXP': 500}),
    _mission('hp_survive', 'basic', 'Deal your HP in damage and survive', u'单场造成不低于自身生命值的伤害并存活',
        {'hp_survive': 1}, {'credits': 60000}),
    _mission('crit7', 'advanced', 'Cause 7 module or crew injuries', u'累计造成7次模块或乘员损伤',
        {'crits': 7}, {'gold': 100}),
    _mission('win3', 'advanced', 'Win 3 battles', u'累计取得3场胜利', {'wins': 3}, {'gold': 100}),
    _mission('destroy8', 'advanced', 'Destroy 8 enemy vehicles', u'累计击毁8辆敌车', {'kills': 8}, {'gold': 100}),
    _mission('damage10000', 'advanced', 'Deal 10000 damage', u'累计造成10000伤害', {'damage': 10000}, {'credits': 120000}),
    _mission('xp3000', 'advanced', 'Earn 3000 base XP', u'累计获得3000基础经验', {'xp': 3000}, {'freeXP': 2000}),
    _mission('penetrate7', 'advanced', '7 penetrations and 1500 damage in a battle', u'单场击穿7次且造成1500伤害',
        {'penetrate7': 1}, {'gold': 100}),
    _mission('kill3win', 'special', 'Destroy 3 vehicles and win a battle', u'单场击毁3辆敌车并获胜',
        {'kill3win': 1}, {'gold': 100, 'largeRepairkit': 2}),
    _mission('xp850win', 'special', '850 base XP and a victory', u'单场获得850基础经验并获胜',
        {'xp850win': 1}, {'gold': 200}),
    _mission('damage2hp', 'special', 'Deal twice your HP in a battle', u'单场造成不低于自身生命值2倍的伤害',
        {'damage2hp': 1}, {'gold': 100, 'crystal': 25}),
    _mission('assist2500', 'special', '2500 assisted damage in a battle', u'单场协助造成2500伤害',
        {'assist2500': 1}, {'gold': 100, 'crystal': 25}),
    _mission('block2hp', 'special', 'Block twice your HP and deal 1500 damage', u'单场抵挡不低于自身生命值2倍的伤害且造成1500伤害',
        {'block2hp': 1}, {'gold': 100, 'crystal': 25}),
    _mission('medium4', 'special', 'Medium tank: damage 4 enemies and destroy one', u'中型坦克单场伤害4辆不同敌车且击毁1辆',
        {'medium4': 1}, {'gold': 100}),
    _mission('td3500', 'special', 'Tank destroyer: 3500 damage and a victory', u'反坦克炮单场造成3500伤害并获胜',
        {'td3500': 1}, {'gold': 200}),
    _mission('spot3assist', 'special', 'Spot 3 enemies and assist 1000 damage', u'单场发现3辆敌车且协助造成1000伤害',
        {'spot3assist': 1}, {'gold': 100, 'crystal': 25}),
    _mission('damage_top3', 'challenge', 'Top 3 by team damage in 3 battles', u'累计3场伤害进入本队前3名',
        {'damage_top3': 3}, {'gold': 150, 'crystal': 25}),
    _mission('xp_top10', 'challenge', 'Top 10 by base XP in 5 battles', u'累计5场基础经验进入本队前10名',
        {'xp_top10': 5}, {'credits': 100000, 'freeXP': 1500}),
    _mission('assist8000', 'challenge', 'Assist 8000 damage', u'累计协助造成8000伤害', {'assist': 8000},
        {'credits': 150000, 'largeRepairkit': 2, 'largeMedkit': 2, 'autoExtinguishers': 2}),
    _mission('block10000', 'challenge', 'Block 10000 damage', u'累计抵挡10000伤害', {'blocked': 10000},
        {'credits': 150000, 'largeRepairkit': 5}),
    _mission('spot16alive', 'challenge', 'Spot 16 enemies in battles you survive', u'累计发现16辆敌车，仅计存活的战斗',
        {'spot_alive': 16}, {'gold': 200, 'crystal': 25}),
    _mission('win8damage', 'challenge', 'Win 8 battles and deal 20000 damage', u'累计获胜8场且造成20000伤害',
        {'wins': 8, 'damage': 20000}, {'gold': 300, 'crystal': 50}),
]

RENTAL_WEIGHTS = {1: (15, 15, 15, 15, 14, 10, 8, 5, 3),
                 3: (15, 15, 16, 16, 15, 10, 7, 4, 2),
                 7: (18, 18, 17, 16, 14, 9, 5, 2, 1)}
RENTAL_COUNTS = {1: (2, 3, 3, 3, 3, 4, 5, 6, 6),
                3: (3, 4, 4, 4, 4, 6, 8, 8, 8),
                7: (4, 5, 5, 5, 6, 8, 12, 10, 10)}
RENTAL_EN = ('Top 10 by base XP', 'Deal your HP in damage', 'Top 5 by base XP',
             'Deal your HP in damage and win', '750 base XP and a victory',
             '850 base XP and a victory', '1000 base XP and a victory')
RENTAL_ZH = (u'基础经验进入本队前10名', u'造成不低于自身生命值的伤害', u'基础经验进入本队前5名',
             u'造成不低于自身生命值的伤害并获胜', u'获得750基础经验并获胜',
             u'获得850基础经验并获胜', u'获得1000基础经验并获胜')
for _days in (1, 3, 7):
    for _tier in range(2, 11):
        _count = RENTAL_COUNTS[_days][_tier - 2]
        _xp = None if _tier < 9 else (1000 if _days == 1 and _tier == 9 else
                    1100 if _days == 3 and _tier == 9 else 1200)
        _en = RENTAL_EN[_tier - 2] if _tier < 9 else '%d base XP and a victory' % _xp
        _zh = RENTAL_ZH[_tier - 2] if _tier < 9 else u'获得%d基础经验并获胜' % _xp
        if _tier == 10 and _days == 7:
            _en += ', top 3 by team base XP'
            _zh += u'，且基础经验进入本队前3名'
        _key = 'rental_%d_%d' % (_tier, _days)
        _row = _mission(_key, 'rental_%d' % _days,
            '%s in %d battles: Tier %d rental, %d days' % (_en, _count, _tier, _days),
            u'累计%d场%s：%d级战车租用%d天' % (_count, _zh, _tier, _days),
            {_key: _count}, {'rental': (_tier, _days)})
        _row.update(rental_tier=_tier, rental_days=_days, rental_xp=_xp,
                    weight=RENTAL_WEIGHTS[_days][_tier - 2])
        CATALOGUE.append(_row)
BY_ID = dict((row['id'], row) for row in CATALOGUE)


def _number(seed):
    return int(hashlib.sha256(seed.encode('utf-8')).hexdigest(), 16)


def assignments(day, seed='default'):
    result = []
    for pool, count in (('basic', 2), ('advanced', 2), ('special', 1), ('challenge', 1)):
        rows = [row for row in CATALOGUE if row['pool'] == pool]
        result.extend(row['id'] for row in sorted(rows,
            key=lambda row: _number('%s:%d:%s' % (seed, day, row['id'])))[:count])
    for days in (1, 3, 7):
        if day % days:
            continue
        draw = _number('%s:%d:rental:%d' % (seed, day, days)) % 100
        for row in (row for row in CATALOGUE if row['pool'] == 'rental_%d' % days):
            draw -= row['weight']
            if draw < 0:
                result.append(row['id'])
                break
    return result


def state(snapshot, now=None):
    day = int(time.time() if now is None else now) // DAY
    raw = snapshot.get('dailyMissions') or {}
    same = raw.get('schema') == SCHEMA and raw.get('day') == day
    ids = assignments(day, str(snapshot.get('accountDBID', 'default')))
    if same and raw.get('missions') == ids:
        return copy.deepcopy(raw)
    return dict(schema=SCHEMA, day=day, missions=ids, claimed=[],
                progress=dict((key, dict((metric, 0) for metric in BY_ID[key]['goals']))
                              for key in ids), rewards={})


def quest_id(day, key):
    return 'offline_daily_v2_%d_%s' % (day, key)


def battle_values(receipt, vehicle_tags=()):
    stats = receipt['stats']
    won = receipt['winner'] == receipt['team']
    own = next((row for row in receipt['public_results']
                if row['actor_kind'] == 'player' and row['actor_id'] == receipt['player_id']), {})
    team = [row for row in receipt['public_results'] if row['team'] == receipt['team']]
    xp = int(receipt['rewards']['xp'])
    damage = int(stats['damage'])
    rank = 1 + sum(int(row['xp']) > xp for row in team)
    damage_rank = 1 + sum(int(row['stats']['damage']) > damage for row in team)
    hp = int(receipt.get('max_health', 0))
    alive = int(own.get('health', 0)) > 0
    assist = sum(int(stats.get(key, 0)) for key in ('assist_radio', 'assist_track', 'assist_stun'))
    hp_damage = damage >= hp if hp > 0 else None
    result = dict(battles=1, wins=int(won), kills=int(stats['kills']), damage=damage,
        damaged=int(stats.get('damaged', 0)), xp=xp, crits=int(stats.get('critical_hits', 0)),
        assist=assist, blocked=int(stats.get('damage_blocked', 0)),
        top5=int(rank <= 5), xp_top10=int(rank <= 10), damage_top3=int(damage_rank <= 3),
        spot_alive=int(stats.get('spotted', 0)) if alive else 0,
        hp_survive=None if hp_damage is None else int(hp_damage and alive),
        penetrate7=int(stats.get('piercings', 0) >= 7 and damage >= 1500),
        kill3win=int(stats['kills'] >= 3 and won), xp850win=int(xp >= 850 and won),
        damage2hp=int(damage >= 2 * hp) if hp > 0 else None,
        assist2500=int(assist >= 2500),
        block2hp=int(stats.get('damage_blocked', 0) >= 2 * hp and damage >= 1500) if hp > 0 else None,
        medium4=int('mediumTank' in vehicle_tags and stats.get('damaged', 0) >= 4 and stats['kills'] >= 1),
        td3500=int('AT-SPG' in vehicle_tags and damage >= 3500 and won),
        spot3assist=int(stats.get('spotted', 0) >= 3 and assist >= 1000))
    for row in CATALOGUE:
        if 'rental_tier' not in row:
            continue
        tier = row['rental_tier']
        if tier == 2:
            eligible = rank <= 10
        elif tier == 3:
            eligible = hp_damage
        elif tier == 4:
            eligible = rank <= 5
        elif tier == 5:
            eligible = None if hp_damage is None else hp_damage and won
        else:
            eligible = won and xp >= ({6: 750, 7: 850, 8: 1000}.get(tier) or row['rental_xp'])
            if tier == 10 and row['rental_days'] == 7:
                eligible = eligible and rank <= 3
        result[row['id']] = None if eligible is None else int(eligible)
    return result


def _pay(state_owner, row, now, seed):
    rewards = []
    for kind, amount in sorted(row['rewards'].items()):
        if kind == 'rental':
            from gui.mods.offline_lan_0922 import vehicle_rentals
            rewards.append(vehicle_rentals.grant(state_owner, amount[0], amount[1], now, seed))
        elif kind in ('credits', 'gold', 'crystal', 'freeXP'):
            wallet = state_owner._wallet()
            value = int(wallet.get(kind, 0)) + amount
            if value > 2 ** 31 - 1:
                raise ValueError('Mission reward exceeds the native balance limit: %s' % kind)
            wallet[kind] = value
            rewards.append(dict(kind=kind, count=amount))
        else:
            cache = state_owner._vehicles_module().g_cache
            equipment = cache.equipments()[cache.equipmentIDs()[kind]]
            compact = int(equipment.compactDescr)
            item_type = state_owner._item_type(compact)
            existing = state_owner.snapshot().get('inventoryItems', {}).get(item_type, {}).get(compact, 0)
            state_owner._set_owned(compact, item_type, int(existing) + amount)
            rewards.append(dict(kind='item', id=compact, count=amount))
    return rewards


def advance(state_owner, receipt, now):
    """Called inside the battle's durable transaction, never by the UI."""
    if receipt.get('battle_mode', 'regular') != 'regular' or receipt.get('premature_leave'):
        return []
    required = set(('stats', 'rewards', 'public_results', 'player_id', 'team', 'winner', 'vehicle'))
    missing = sorted(required.difference(receipt))
    if now is None or missing:
        print('[Offline LAN 0.9.22] MISSION EVIDENCE unavailable receipt=%s clock=%s missing=%s' %
              (receipt.get('receipt_id'), now, ','.join(missing)))
        return []
    now = int(now)
    processing_time = int(time.time())
    if now // DAY < processing_time // DAY:
        print('[Offline LAN 0.9.22] MISSION EVIDENCE expired receipt=%s battle_day=%d current_day=%d' %
              (receipt.get('receipt_id'), now // DAY, processing_time // DAY))
        return []
    snapshot = state_owner.snapshot()
    if int((snapshot.get('dailyMissions') or {}).get('day', -1)) > now // DAY:
        return []
    daily = state(snapshot, now)
    snapshot['dailyMissions'] = daily
    from gui.mods.offline_lan_0922.ordinary_missions_native import native_progress
    before = dict((key, native_progress(daily, key)) for key in daily['missions'])
    tags = ()
    if any(metric in ('medium4', 'td3500') for key in daily['missions']
           for metric in BY_ID[key]['goals']):
        try:
            tags = state_owner._vehicles_module().VehicleDescr(typeName=receipt['vehicle']).type.tags
        except (ImportError, AttributeError, KeyError, ValueError):
            tags = None
            print('[Offline LAN 0.9.22] MISSION EVIDENCE unavailable vehicle_tags receipt=%s' % receipt['receipt_id'])
    values = battle_values(receipt, tags or ())
    if tags is None:
        values.update(medium4=None, td3500=None)
    completed, unavailable = [], set()
    for key in daily['missions']:
        if key in daily['claimed']:
            continue
        row = BY_ID[key]
        progress = daily['progress'][key]
        for metric, target in row['goals'].items():
            value = values.get(metric)
            if value is None:
                unavailable.add(metric)
                continue
            progress[metric] = min(target, progress.get(metric, 0) + value)
        if not all(progress.get(metric, 0) >= target for metric, target in row['goals'].items()):
            continue
        try:
            with state_owner._transaction():
                rewards = _pay(state_owner, row, max(now, processing_time), '%d:%s:%s' %
                    (daily['day'], key, snapshot.get('accountDBID', 'default')))
                daily['claimed'].append(key)
                daily['rewards'][key] = rewards
        except Exception as error:
            print('[Offline LAN 0.9.22] MISSION REWARD pending quest=%s receipt=%s error=%s' %
                  (key, receipt['receipt_id'], error))
            daily = state_owner.snapshot()['dailyMissions']
            snapshot = state_owner.snapshot()
            continue
        completed.append(dict(id=quest_id(daily['day'], key), key=key,
                              rewards=copy.deepcopy(rewards)))
    if completed:
        from gui.mods.offline_lan_0922.personal_campaign_ui import queue_notification
        queue_notification(state_owner.snapshot(), {'ordinary_missions': completed,
                                                   'notification_at': int(now)})
    if unavailable:
        print('[Offline LAN 0.9.22] MISSION EVIDENCE unavailable receipt=%s metrics=%s' %
              (receipt['receipt_id'], ','.join(sorted(unavailable))))
    return [dict(id=quest_id(daily['day'], key), key=key,
                 before=before[key], after=native_progress(daily, key),
                 rewards=copy.deepcopy(daily.get('rewards', {}).get(key, [])))
            for key in daily['missions'] if before[key] != native_progress(daily, key)]
