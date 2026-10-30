# -*- coding: utf-8 -*-
"""Feed #1513's own quest parser, cache, progress and mission page."""
import hashlib
import time
import zlib
try:
    import cPickle as pickle
except ImportError:
    import pickle

from gui.mods.offline_lan_0922 import ordinary_missions as policy
from gui.mods.offline_lan_0922.ui_i18n import as_text

_cache = {}
_errors = set()
_presented = set()
SCALAR_FIELDS = {'damage': 'damageDealt', 'xp': 'xp', 'kills': 'kills',
                 'blocked': 'damageBlockedByArmor'}


def _escape(text):
    return as_text(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _localized(tag, values):
    return '<%s>%s</%s>' % (tag, ''.join(
        '<%s>%s</%s>' % (language, _escape(text), language)
        for language, text in sorted(values.items())), tag)


def condition(row, descriptions=None):
    """Use stock counters only where their meaning matches this mission.

    Composite and event-count conditions retain their complete description
    and actual counters. They must not masquerade as XP or ordinary battles.
    """
    goals = row['goals']
    metric, target = next(iter(goals.items()))
    if len(row['goals']) == 1 and metric in SCALAR_FIELDS:
        name = SCALAR_FIELDS[metric]
        return '<cumulative><%s>%d</%s></cumulative>' % (name, target, name), {'cumulative': metric}
    if len(goals) == 1:
        # The stock counter widget supports a custom objective description.
        # Feed the actual event/assistance count, not a fabricated 0/1 battle.
        mapping = {'battlesCount': metric}
    else:
        # The approved combined objective has independent wins and damage.
        # Keep both native counters; damage in a loss still contributes.
        metric, target = 'wins', goals['wins']
        mapping = {'battlesCount': metric, 'cumulative': 'damage'}
    title = dict(en='Objective', zh_cn=u'任务条件')
    metadata = _localized('meta', {'offlineOrdinary': 'v2'}) + _localized('title', title) + _localized(
        'description', descriptions or row.get('description', row['name']))
    text = '<battles><count>%d</count>%s</battles>' % (target, metadata)
    if len(goals) > 1:
        text += '<cumulative><damageDealt>%d</damageDealt></cumulative>' % goals['damage']
    return text, mapping


def xml_definition(daily):
    output = [u'<?xml version="1.0" encoding="utf-8"?><root><quests>']
    for priority, key in enumerate(daily['missions']):
        row = policy.BY_ID[key]
        descriptions = {}
        counters = daily.get('progress', {}).get(key, {})
        for language, label in row.get('description', row['name']).items():
            counts = ', '.join('%d/%d' % (counters.get(metric, 0), target)
                               for metric, target in sorted(row['goals'].items()))
            suffix = (u'进度：%s。跨日重置。' if language == 'zh_cn'
                      else 'Progress: %s. Resets at the next game day.') % counts
            descriptions[language] = label + u'\n' + suffix
        native_condition, unused = condition(row, descriptions)
        output.append(u'<battleQuest><enabled>true</enabled><id>%s</id>' %
                      policy.quest_id(daily['day'], key))
        for tag, values in (('name', row['name']), ('description', descriptions)):
            output.append('<%s>' % tag)
            output.extend('<%s>%s</%s>' % (language, _escape(text), language)
                          for language, text in sorted(values.items()))
            output.append('</%s>' % tag)
        output.append('<priority>%d</priority><showCongrats>false</showCongrats>' % (100 - priority))
        post = '<postBattle><win/></postBattle>' if set(row['goals']) == set(('wins',)) else ''
        output.append('<conditions>%s<common><bonusLimit>1</bonusLimit>%s</common></conditions>' %
                      (post, native_condition))
        output.append('</battleQuest>')
    output.append('</quests></root>')
    return u''.join(output)


def preview(row, vehicles, snapshot=None, daily=None, now=None):
    assets = {}
    for kind, amount in row['rewards'].items():
        if kind == 'rental':
            from gui.mods.offline_lan_0922 import vehicle_rentals
            if snapshot is None or daily is None:
                raise ValueError('Rental preview requires the current account inventory')
            paid = daily.get('rewards', {}).get(row['id'])
            if paid:
                award = paid[0]
            else:
                award = vehicle_rentals.choose(vehicle_rentals.catalogue(vehicles, amount[0]),
                    snapshot.get('vehicles', ()), amount[1],
                    int(time.time() if now is None else now), '%d:%s:%s' %
                    (daily['day'], row['id'], snapshot.get('accountDBID', 'default')))
            if award['kind'] == 'compensation':
                assets['credits'] = award['credits']
            else:
                # VehiclesBonus consumes a CD -> info dictionary; rent.time
                # is days. Selection is pure and identical to grant(), and is
                # recalculated when inventory changes before completion.
                assets['vehicles'] = {int(award['vehicle_type']):
                    {'rent': {'time': int(award['days'])}}}
            continue
        if kind in ('credits', 'gold', 'crystal', 'freeXP'):
            assets[kind] = amount
        else:
            cache = vehicles.g_cache
            item = cache.equipments()[cache.equipmentIDs()[kind]]
            assets.setdefault('items', {})[int(item.compactDescr)] = amount
    return assets


def native_progress(daily, key):
    counters = daily.get('progress', {}).get(key, {})
    values = {'bonusCount': int(key in daily['claimed'])}
    unused, mapping = condition(policy.BY_ID[key])
    if 'cumulative' in mapping:
        metric = mapping['cumulative']
        values[SCALAR_FIELDS[metric]] = counters.get(metric, 0)
    if 'battlesCount' in mapping:
        values['battlesCount'] = counters.get(mapping['battlesCount'], 0)
    return values


def parse_xml(text, stamp, start, finish):
    # #1513's native prefetcher/wgnc use this exact in-memory XML entrance.
    # ResMgr's virtual resource paths cannot read an arbitrary APPDATA file.
    import ResMgr
    from quest_xml_source import Source
    section = ResMgr.DataSection().createSectionFromString(text.encode('utf-8'))
    if section is None:
        raise ValueError('Native DataSection could not parse ordinary mission XML')
    # The pinned Source exposes its DataSection reader privately. Keep its
    # condition/header/bonus readers, without replacing global ResMgr I/O.
    return Source()._Source__readXML(section['quests'], stamp, start, finish)


def install_presentation(patch):
    """Keep stock renderers while adapting only this offline quest family.

    #1513 BattlesCountFormatter calls _getDescription directly, bypassing its
    inherited native custom-description reader. Honor that reader only for our
    marked conditions. The original method owns every other condition.
    """
    from gui.server_events.cond_formatters.bonus import BattlesCountFormatter
    from gui.server_events.cond_formatters import packDescriptionField
    from gui.Scaleform.daapi.view.lobby.missions.regular import group_packers
    original_description = BattlesCountFormatter._getDescription
    original_sort = group_packers.missionsSortFunc

    def description(formatter, condition):
        if getattr(condition, '_data', {}).get('meta', {}).get('offlineOrdinary') == 'v2':
            custom = condition.getCustomDescription()
            if custom is not None:
                if custom not in _presented and len(_presented) < 64:
                    _presented.add(custom)
                    print('[Offline LAN 0.9.22] NATIVE MISSION objective_description rendered')
                return packDescriptionField(custom)
        return original_description(formatter, condition)

    def compare(first, second):
        if all(as_text(event.getID()).startswith('offline_daily_v2_')
               for event in (first, second)):
            a, b = first.getPriority(), second.getPriority()
            return (a > b) - (a < b)
        return original_sort(first, second)

    patch(BattlesCountFormatter, '_getDescription', description)
    patch(group_packers, 'missionsSortFunc', compare)


def sync(snapshot, now=None):
    """Return account-native fields. Engine-free tests exercise xml_definition.

    A missing actual client parser fails diagnostically, never by replacing
    MissionsPage with a mod window. The Windows acceptance must exercise it.
    """
    try:
        import BigWorld
    except ImportError:
        return {}
    if getattr(BigWorld, 'component', None) != 'client':
        return {}
    daily = policy.state(snapshot, now)
    stamp = int(time.time() if now is None else now)
    text = xml_definition(daily)
    try:
        from constants import EVENT_CLIENT_DATA
        from items import vehicles
        previews = dict((key, preview(policy.BY_ID[key], vehicles, snapshot, daily, stamp))
                        for key in daily['missions'])
        digest = hashlib.sha256(text.encode('utf-8') + pickle.dumps(previews, 2)).hexdigest()
        if digest not in _cache:
            nodes = parse_xml(text, stamp, daily['day'] * policy.DAY,
                              (daily['day'] + 1) * policy.DAY)
            definitions = {}
            for group in nodes.values():
                for node in group:
                    data = dict(node.info['questClientData'])
                    data['isDaily'] = True
                    key = next(key for key in daily['missions']
                               if policy.quest_id(daily['day'], key) == data['id'])
                    data['bonus'] = previews[key]
                    definitions[data['id']] = data
            if len(definitions) != len(daily['missions']):
                raise ValueError('Native quest parser returned %d/%d missions' %
                                 (len(definitions), len(daily['missions'])))
            _cache.clear()
            _cache[digest] = zlib.compress(pickle.dumps(definitions, 2))
            print('[Offline LAN 0.9.22] NATIVE MISSIONS parsed count=%d day=%d schema=%d' %
                  (len(definitions), daily['day'], policy.SCHEMA))
            for key in daily['missions']:
                if 'rental' in policy.BY_ID[key]['rewards']:
                    print('[Offline LAN 0.9.22] NATIVE MISSION rental_preview quest=%s bonus=%s' %
                          (key, previews[key]))
        progress = {}
        for key in daily['missions']:
            row = policy.BY_ID[key]
            values = native_progress(daily, key)
            progress[policy.quest_id(daily['day'], key)] = {'progress': {None: values}}
        return {'eventsData': {EVENT_CLIENT_DATA.QUEST: _cache[digest]}, 'quests': progress}
    except Exception as error:
        identity = (text, str(error))
        if identity not in _errors:
            print('[Offline LAN 0.9.22] NATIVE MISSIONS unavailable day=%d error=%s' % (daily['day'], error))
            _errors.add(identity)
        return {}
