# -*- coding: utf-8 -*-
"""Approved offline ordinary missions, independent of personal campaigns.

Daily, weekly and monthly quality counters have independent calendar boundaries.
Old policy counters are reset without altering assets or personal campaigns.
The catalogue is offline product policy, not a recovered historical server list.
"""
import copy
import hashlib
import time

SCHEMA = 3
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

# Difficulty rows, each containing daily, weekly and monthly prizes.
STRATEGIC = (('simple', 1000, (2, 3, 4), u'简单'),
             ('normal', 1500, (5, 6, 7), u'普通'),
             ('hard', 2000, (8, 9), u'困难'),
             ('elite', 2500, (10,), u'精英'))
PERIODS = (('day', 5, 3, u'日'), ('week', 25, 30, u'周'),
           ('month', 100, 0, u'月'))
for _difficulty, _xp, _tiers, _zh in STRATEGIC:
    for _period, _count, _days, _period_zh in PERIODS:
        _key = 'vehicle_%s_%s' % (_difficulty, _period)
        _prize_en = '%d-day rental' % _days if _days else 'permanent vehicle'
        _prize_zh = u'租用%d天' % _days if _days else u'永久车辆'
        _row = _mission(_key, 'strategic',
            '%s / %s: Tier %s %s' % (_difficulty.title(), _period, '-'.join(
                str(t) for t in (_tiers[0], _tiers[-1])) if len(_tiers)>1 else str(_tiers[0]), _prize_en),
            u'%s%s：%s级%s' % (_zh, _period_zh,
                u'%d—%d' % (_tiers[0], _tiers[-1]) if len(_tiers)>1 else str(_tiers[0]), _prize_zh),
            {_key: _count}, {'vehicle_prize': (_tiers, _days)})
        _row.update(period=_period, difficulty=_difficulty, quality_xp=_xp,
            description=dict(en='Win %d battles with at least %d base XP in each battle' % (_count, _xp),
                zh_cn=u'完成%d场胜利，每场至少获得%d基础经验' % (_count, _xp)))
        CATALOGUE.append(_row)
BY_ID = dict((row['id'], row) for row in CATALOGUE)
DISPLAY_ORDER = dict((row['id'], index) for index, row in enumerate(CATALOGUE))


def _number(seed):
    return int(hashlib.sha256(seed.encode('utf-8')).hexdigest(), 16)


def assignments(day, seed='default'):
    result = []
    for pool, count in (('basic', 2), ('advanced', 2), ('special', 1), ('challenge', 1)):
        rows = [row for row in CATALOGUE if row['pool'] == pool]
        result.extend(row['id'] for row in sorted(rows,
            key=lambda row: _number('%s:%d:%s' % (seed, day, row['id'])))[:count])
    result.extend(row['id'] for row in CATALOGUE if row['pool'] == 'strategic')
    return sorted(result, key=lambda key: DISPLAY_ORDER[key])


def assignment_bounds(day, key):
    from gui.mods.offline_lan_0922.game_calendar import bounds
    return bounds(day * DAY, BY_ID[key].get('period', 'day'))


def reward_seed(snapshot, day, key):
    return '%s:%d:%s' % (snapshot.get('missionSeed', snapshot.get('accountDBID', 'default')),
                        assignment_bounds(day, key)[0], key)


def state(snapshot, now=None):
    day = int(time.time() if now is None else now) // DAY
    raw = snapshot.get('dailyMissions') or {}
    same = raw.get('schema') == SCHEMA
    ids = assignments(day, str(snapshot.get('missionSeed', snapshot.get('accountDBID', 'default'))))
    result = dict(schema=SCHEMA, day=day, missions=ids, claimed=[],
                  progress={}, rewards={}, periods={})
    for key in ids:
        start, finish = assignment_bounds(day, key)
        result['periods'][key] = start
        result['progress'][key] = dict((metric, 0) for metric in BY_ID[key]['goals'])
        if same and raw.get('periods', {}).get(key) == start:
            result['progress'][key] = copy.deepcopy(raw.get('progress', {}).get(key, result['progress'][key]))
            if key in raw.get('claimed', ()):
                result['claimed'].append(key)
            if key in raw.get('rewards', {}):
                result['rewards'][key] = copy.deepcopy(raw['rewards'][key])
    return result


def quest_id(day, key):
    return 'offline_daily_v3_%d_%s' % (assignment_bounds(day, key)[0] // DAY, key)


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
        if row['pool'] == 'strategic':
            result[row['id']] = int(won and xp >= row['quality_xp'])
    return result


def _pay(state_owner, row, now, seed):
    rewards = []
    for kind, amount in sorted(row['rewards'].items()):
        if kind == 'vehicle_prize':
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
    snapshot = state_owner.snapshot()
    if int((snapshot.get('dailyMissions') or {}).get('day', -1)) > now // DAY:
        return []
    daily = state(snapshot, max(now, processing_time))
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
        start, finish = assignment_bounds(daily['day'], key)
        if key in daily['claimed'] or not start <= now < finish:
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
                rewards = _pay(state_owner, row, max(now, processing_time), reward_seed(snapshot, daily['day'], key))
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
