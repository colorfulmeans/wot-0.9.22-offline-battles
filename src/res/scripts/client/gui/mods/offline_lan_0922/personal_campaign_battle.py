"""Evaluate personal missions from installed definitions and settled facts.

This deliberately does not infer event history from final counters. Conditions
requiring unrecorded hit timing or visibility remain unevaluated
until the authoritative receipt carries those facts. Unknown XML modifiers
must never silently turn a harder mission into an easier one.
"""

from __future__ import division

from gui.mods.offline_lan_0922 import mission_events

_CLASSES = frozenset(('lightTank', 'heavyTank', 'mediumTank', 'AT-SPG', 'SPG'))
_DECORATION = frozenset(('title', 'description', 'hideInGui'))
_RELATIONS = frozenset(('greaterOrEqual', 'greater', 'equal', 'less',
                        'lessOrEqual'))
_STAT_KEYS = {
    'damageDealt': 'damage', 'damageReceived': 'damage_received',
    'damageBlockedByArmor': 'damage_blocked', 'damaged': 'damaged',
    'kills': 'kills', 'spotted': 'spotted',
    'damageAssistedRadio': 'assist_radio',
    'damageAssistedTrack': 'assist_track',
    'damageAssistedStun': 'assist_stun',
    'stunNum': 'stun_num', 'stunned': 'stunned',
    'killsAssistedStun': 'kills_assisted_stun',
    'killsAssistedTrack': 'kills_assisted_track',
    'critsCount': 'critical_hits', 'isNotSpotted': 'not_spotted',
    'capturePoints': 'capture_points',
    'droppedCapturePoints': 'dropped_capture_points',
}
_ASSIST_TARGET_KEYS = {
    'damagedVehicleCntAssistedRadio': 'assist_radio',
    'damagedVehicleCntAssistedTrack': 'assist_track',
    'damagedVehicleCntAssistedStun': 'assist_stun',
}


def _children(node, name=None):
    items = (node or {}).get('children', ())
    return [item for key, item in items if name is None or key == name]


def _child(node, name):
    return next(iter(_children(node, name)), None)


def _value(node, name, default=''):
    item = _child(node, name)
    return default if item is None else item.get('value', '')


def _names(node):
    return set(name for name, unused in (node or {}).get('children', ()))


def _unknown(reason):
    return None, set((str(reason),))


def _known(value):
    return bool(value), set()


def _combine(results, disjunction=False):
    results = list(results)
    values = [value for value, unused in results]
    if disjunction and True in values:
        return _known(True)
    if not disjunction and False in values:
        return _known(False)
    if None in values:
        return None, set(reason for unused, reasons in results
                         for reason in reasons)
    return _known(any(values) if disjunction else all(values))


def _compare(node, actual):
    relations = _names(node) & _RELATIONS
    if not relations:
        return _unknown('missing comparison')
    checks = []
    for name in relations:
        try:
            required = float(_value(node, name))
        except (TypeError, ValueError):
            return _unknown('invalid comparison: ' + name)
        checks.append({
            'greaterOrEqual': actual >= required,
            'greater': actual > required,
            'equal': actual == required,
            'less': actual < required,
            'lessOrEqual': actual <= required,
        }[name])
    return _known(all(checks))


class _Facts(object):
    def __init__(self, receipt, vehicles_module):
        self.receipt = receipt
        self.vehicles_module = vehicles_module
        self.descriptions = {}
        self.rows = dict(((row.get('actor_kind'), row.get('actor_id')), row)
                         for row in receipt.get('public_results', ()))

    def describe(self, name):
        if name not in self.descriptions:
            description = None
            if self.vehicles_module is not None:
                try:
                    descriptor = self.vehicles_module.VehicleDescr(
                        typeName=str(name))
                    description = {
                        'tags': set(descriptor.type.tags),
                        'level': int(descriptor.type.level),
                    }
                except (AttributeError, TypeError, ValueError, KeyError):
                    pass
            self.descriptions[name] = description
        return self.descriptions[name]

    def result(self, key, row=None):
        source = self.receipt if row is None else row
        if key in _STAT_KEYS:
            return (source.get('stats') or {}).get(_STAT_KEYS[key])
        if key == 'stunDuration':
            duration = (source.get('stats') or {}).get('stun_duration_ms')
            return None if duration is None else duration / 1000.0
        if key == 'xp':
            if row is not None:
                return row.get('xp')
            return (self.receipt.get('rewards') or {}).get('xp')
        if row is not None:
            return None
        if key == 'percentFromTotalTeamDamage':
            damage = self.result('damageDealt')
            team = self.receipt.get('team')
            rows = [item for item in self.rows.values()
                    if item.get('team') == team]
            values = [self.result('damageDealt', item) for item in rows]
            if damage is None or not rows or None in values:
                return None
            total = sum(values)
            return 100.0 * damage / total if total else 0
        if key == 'isEnemyBaseCaptured':
            if 'finish_reason' not in source:
                return None
            return int(source['finish_reason'] == 2 and
                       source.get('team') == source.get('winner'))
        # These counters are derivable from the per-target facts without
        # reconstructing unseen hit order or pretending hits were damaging.
        if key in _ASSIST_TARGET_KEYS or key == 'spottedAndDamagedSPG':
            if 'interactions' not in source:
                return None
            count = 0
            for item in source['interactions']:
                row = self.rows.get((item.get('target_kind'),
                                     item.get('target_id')))
                if row is None:
                    return None
                if row.get('team') == source.get('team'):
                    continue
                if key in _ASSIST_TARGET_KEYS:
                    if _ASSIST_TARGET_KEYS[key] not in item:
                        return None
                    count += int(item[_ASSIST_TARGET_KEYS[key]] > 0)
                elif item.get('spotted', 0) and item.get('damage', 0):
                    info = self.describe(row.get('vehicle'))
                    if info is None:
                        return None
                    count += int('SPG' in info['tags'])
            return count
        return None


def _results(node, facts):
    allowed = (_DECORATION | _RELATIONS |
               set(('key', 'plus', 'max', 'total')))
    unexpected = _names(node) - allowed
    if unexpected:
        return _unknown('results modifier: ' + ','.join(sorted(unexpected)))
    plus = _child(node, 'plus')
    if plus is not None:
        if _names(plus) != set(('key',)):
            return _unknown('results aggregate')
        keys = [item.get('value', '') for item in _children(plus, 'key')]
    else:
        keys = [_value(node, 'key')]
    values = [facts.result(key) for key in keys]
    if None in values or not keys:
        return _unknown('result: ' + ','.join(keys))
    amount = sum(values)
    checks = []
    if _child(node, 'max') is not None:
        try:
            limit = int(_value(node, 'max'))
        except (TypeError, ValueError):
            return _unknown('result rank')
        rows = list(facts.rows.values())
        if not rows or ('player', facts.receipt.get('player_id')) not in facts.rows:
            return _unknown('result roster')
        if _child(node, 'total') is None:
            rows = [row for row in rows
                    if row.get('team') == facts.receipt.get('team')]
        ahead = 0
        for row in rows:
            other = [facts.result(key, row) for key in keys]
            if None in other:
                return _unknown('ranked result: ' + ','.join(keys))
            ahead += int(sum(other) > amount)
        checks.append(_known(ahead < limit))
    elif _child(node, 'total') is not None:
        return _unknown('total without rank')
    if _names(node) & _RELATIONS:
        checks.append(_compare(node, amount))
    return _combine(checks) if checks else _unknown('result comparison')


def _vehicle_events(name, node, facts):
    allowed = (_DECORATION | _RELATIONS |
               set(('classes', 'classesDiversity')))
    if name in ('vehicleDamage', 'vehicleStun'):
        allowed = allowed | set(('eventCount',))
    if name == 'vehicleKills':
        allowed = allowed | set(('attackReason', 'distance'))
    if name in ('vehicleDamage', 'vehicleKills'):
        allowed = allowed | set(('limittedTime', 'enemyImmobilized'))
    unexpected = _names(node) - allowed
    if unexpected:
        return _unknown(name + ' modifier: ' + ','.join(sorted(unexpected)))
    if 'interactions' not in facts.receipt:
        return _unknown('per-target interactions')
    classes = set(_value(node, 'classes').split())
    event_count = _child(node, 'eventCount')
    if (event_count is not None and
            (_names(event_count) or event_count.get('value', ''))):
        return _unknown(name + ' eventCount modifier')
    diversity = _child(node, 'classesDiversity')
    filtered_history = bool(_names(node) & set((
        'limittedTime', 'enemyImmobilized', 'distance')))
    try:
        time_limit = (int(_value(node, 'limittedTime')) * 1000
                      if _child(node, 'limittedTime') is not None else None)
        distance_limit = (int(_value(node, 'distance'))
                          if _child(node, 'distance') is not None else None)
        if time_limit is not None and time_limit < 0:
            raise ValueError('negative event deadline')
    except (TypeError, ValueError):
        return _unknown(name + ' limittedTime or distance boundary')
    immobilized = _child(node, 'enemyImmobilized')
    if immobilized is not None and (_names(immobilized) or immobilized.get('value', '')):
        return _unknown(name + ' enemyImmobilized modifier')
    amount, seen_classes = 0, set()
    for event in facts.receipt['interactions']:
        if name == 'vehicleStun':
            field = 'stun_num' if event_count is not None else 'stun_duration'
        elif name == 'vehicleDamage':
            field = 'damage_events' if event_count is not None else 'damage'
        else:
            field = 'target_kills'
        value = event.get(field)
        if value is None:
            return _unknown('interaction: ' + field +
                            (' (eventCount)' if event_count is not None else ''))
        if value <= 0:
            continue
        row = facts.rows.get((event.get('target_kind'), event.get('target_id')))
        if row is None:
            return _unknown('target roster')
        if row.get('team') == facts.receipt.get('team'):
            continue
        if classes or diversity is not None:
            info = facts.describe(row.get('vehicle'))
            if info is None:
                return _unknown('target vehicle descriptor')
            tags = info['tags'] & _CLASSES
            if classes and not tags & classes:
                continue
        else:
            tags = set()
        if filtered_history:
            history = _mission_history(event)
            if history is None:
                return _unknown('interaction: complete mission event history (' +
                                ','.join(sorted(_names(node) & set((
                                    'limittedTime', 'enemyImmobilized', 'distance')))) + ')')
            value = 0
            for occurrence in history:
                if occurrence[0] != ('damage' if name == 'vehicleDamage' else 'kill'):
                    continue
                if time_limit is not None and occurrence[1] > time_limit:
                    continue
                if immobilized is not None and not occurrence[3]:
                    continue
                if distance_limit is not None:
                    distance = occurrence[4]
                    if distance is None:
                        return _unknown('interaction: kill distance')
                    # Signed XML ranges use an inclusive lower bound and an
                    # exclusive negative upper bound (-101 covers 100 m).
                    if (distance_limit < 0 and distance >= -distance_limit or
                            distance_limit >= 0 and distance < distance_limit):
                        continue
                value += (occurrence[2] if name == 'vehicleDamage' and
                          event_count is None else 1)
        if _child(node, 'attackReason') is not None:
            try:
                reason = int(_value(node, 'attackReason'))
            except (TypeError, ValueError):
                return _unknown('attack reason')
            if 'death_reason' not in event:
                return _unknown('interaction: death_reason')
            if event['death_reason'] != reason:
                continue
        # Sum the worker's milliseconds, including across targets. A binary
        # float addition must not leave an exact 50 seconds just below 50.
        amount += (int(round(value * 1000))
                   if field == 'stun_duration' else value)
        seen_classes.update(tags)
    if name == 'vehicleStun' and event_count is None:
        amount /= 1000.0
    checks = [_compare(node, amount)]
    if diversity is not None:
        try:
            checks.append(_known(len(seen_classes) >= int(
                diversity.get('value', ''))))
        except (TypeError, ValueError):
            return _unknown('vehicle class diversity')
    return _combine(checks)


def _mission_history(interaction):
    if (interaction.get('mission_events_complete') is not True or
            not mission_events.valid(interaction)):
        return None
    return interaction.get('mission_events')


def _critical_events(node, facts):
    if _names(node) - (_DECORATION | set(('destroyed',))):
        return _unknown('crits modifier')
    destroyed = _child(node, 'destroyed')
    if destroyed is None or _names(destroyed) != set(('crit',)):
        return _unknown('crits destroyed condition')
    checks = []
    for condition in _children(destroyed, 'crit'):
        if (_names(condition) - (_DECORATION | _RELATIONS | set(('critName',))) or
                _value(condition, 'critName') != 'track'):
            return _unknown('destroyed critical type or modifier')
        if 'interactions' not in facts.receipt:
            return _unknown('per-target critical history')
        count = 0
        for interaction in facts.receipt['interactions']:
            row = facts.rows.get((interaction.get('target_kind'), interaction.get('target_id')))
            if row is None:
                return _unknown('target roster')
            if row.get('team') == facts.receipt.get('team'):
                continue
            history = _mission_history(interaction)
            if history is None:
                return _unknown('interaction: complete mission critical history')
            # #1513 destroyed-device bits start at 12; track is device 4.
            count += sum(1 for event in history
                         if event[0] == 'critical' and event[2] & (1 << 16))
        checks.append(_compare(condition, count))
    return _combine(checks)


def _multi_stun_event(node, facts):
    if _names(node) - (_DECORATION | _RELATIONS | set(('stunnedByShot',))):
        return _unknown('multiStunEvent modifier')
    try:
        targets = int(_value(node, 'stunnedByShot'))
    except (TypeError, ValueError):
        return _unknown('multiStunEvent target count')
    # Only these two per-shot thresholds are recorded. Never infer a third
    # threshold from the total number of hits or distinct stunned vehicles.
    if targets not in (2, 3):
        return _unknown('multiStunEvent target count')
    count = (facts.receipt.get('stats') or {}).get('stun_shots_%d' % targets)
    if count is None:
        return _unknown('multiStunEvent shot evidence')
    return (_compare(node, count) if _names(node) & _RELATIONS
            else _known(count >= 1))


def _condition(name, node, facts):
    if name in ('postBattle', 'and', 'or'):
        items = [(key, item) for key, item in node.get('children', ())
                 if key not in _DECORATION]
        if not items:
            return _unknown('empty condition')
        return _combine((_condition(key, item, facts) for key, item in items),
                        disjunction=name == 'or')
    if name in ('win', 'isAlive'):
        if _names(node) - _DECORATION:
            return _unknown(name + ' modifier')
        if name == 'win':
            if not all(key in facts.receipt for key in ('team', 'winner')):
                return _unknown('battle winner')
            return _known(facts.receipt['team'] == facts.receipt['winner'])
        if 'death_reason' not in facts.receipt:
            return _unknown('player survival')
        return _known(facts.receipt['death_reason'] == -1)
    if name == 'results':
        return _results(node, facts)
    if name in ('vehicleDamage', 'vehicleKills', 'vehicleStun'):
        return _vehicle_events(name, node, facts)
    if name == 'multiStunEvent':
        return _multi_stun_event(node, facts)
    if name == 'crits':
        return _critical_events(node, facts)
    return _unknown('condition: ' + name)


def _postbattle(definition, facts):
    if _value(definition, 'enabled', 'true').lower() == 'false':
        return _known(False)
    conditions = _child(definition, 'conditions')
    if conditions is None:
        return _unknown('mission conditions')
    # The regular main/add definitions have postBattle only. Never omit a
    # newly encountered preBattle/common restriction from an installed file.
    if _names(conditions) != set(('postBattle',)):
        return _unknown('mission condition groups')
    return _condition('postBattle', _child(conditions, 'postBattle'), facts)


def _eligible(metadata, completed, facts):
    info = facts.describe(facts.receipt.get('vehicle'))
    if metadata is None or info is None:
        return _unknown('mission metadata or player vehicle descriptor')
    tags = set(_value(metadata, 'tags').split()) & _CLASSES
    try:
        minimum = int(_value(metadata, 'minLevel'))
        maximum = int(_value(metadata, 'maxLevel'))
        required = [int(value) for value in
                    _value(metadata, 'requiredUnlocks').split()]
    except (TypeError, ValueError):
        return _unknown('mission vehicle/prerequisite metadata')
    return _known(bool(tags & info['tags']) and
                  minimum <= info['level'] <= maximum and
                  all(completed.get(str(qid), 0) >= 1 for qid in required))


def evaluate(snapshot, receipt, vehicles_module=None, definition_provider=None,
             evaluations=None):
    """Return newly completed states and unmet evidence; never change the save.

    The settlement owner applies ``completed`` through the same reward path as
    a launcher edit, inside the battle receipt's exactly-once transaction.
    ``unsupported`` is diagnostic and must not block ordinary battle earnings.
    """
    result = {'completed': {}, 'unsupported': {}}
    if (not isinstance(receipt, dict) or
            receipt.get('battle_mode', 'regular') != 'regular' or
            receipt.get('premature_leave', False)):
        return result
    selections = snapshot.get('personalMissionSelections') or {}
    if not selections.get('regular'):
        return result
    if definition_provider is None:
        from gui.mods.offline_lan_0922.personal_campaign import mission_definition
        definition_provider = mission_definition
    completed = snapshot.get('personalMissionProgress') or {}
    facts = _Facts(receipt, vehicles_module)
    for raw_qid in selections.get('regular', ()):
        try:
            qid = int(raw_qid)
        except (TypeError, ValueError):
            continue
        key = str(qid)
        if not 1 <= qid <= 300 or completed.get(key, 0) >= 2:
            continue
        try:
            definition = definition_provider(qid)
        except Exception as error:
            # A missing or malformed installed mission must not leave the
            # otherwise valid battle's ordinary settlement permanently pending.
            result['unsupported'][key] = ['mission resource: ' + str(error)]
            continue
        if not isinstance(definition, dict):
            result['unsupported'][key] = ['mission resource']
            continue
        eligible, reasons = _eligible(definition.get('metadata'), completed, facts)
        if eligible is not True:
            if reasons:
                result['unsupported'][key] = sorted(reasons)
            continue
        main, reasons = _postbattle(definition.get('main'), facts)
        evaluated = {'definition': definition, 'main': main, 'add': False}
        if evaluations is not None:
            evaluations[key] = evaluated
        if main is not True:
            if reasons:
                result['unsupported'][key] = sorted(reasons)
            continue
        additional, reasons = _postbattle(definition.get('add'), facts)
        evaluated['add'] = additional
        level = 2 if additional is True else 1
        if level > completed.get(key, 0):
            result['completed'][key] = level
        if reasons:
            result['unsupported'][key] = sorted(reasons)
    return result
