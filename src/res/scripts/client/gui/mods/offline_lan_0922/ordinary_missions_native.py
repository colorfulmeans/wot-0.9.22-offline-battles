# -*- coding: utf-8 -*-
"""Feed #1513's own quest parser, cache, progress and mission page."""
import hashlib
import io
import json
import os
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
SCALAR_FIELDS = {'damage': 'damageDealt', 'xp': 'xp', 'kills': 'kills',
                 'blocked': 'damageBlockedByArmor'}


def _escape(text):
    return as_text(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def condition(row):
    """Use stock counters only where their meaning matches this mission.

    Composite and event-count conditions retain their complete description
    and actual counters. They must not masquerade as XP or ordinary battles.
    """
    if len(row['goals']) != 1:
        return '', {}
    metric, target = next(iter(row['goals'].items()))
    if metric in SCALAR_FIELDS:
        name = SCALAR_FIELDS[metric]
        return '<cumulative><%s>%d</%s></cumulative>' % (name, target, name), {'cumulative': metric}
    if metric in ('battles', 'wins') or metric.startswith('rental_') or metric in (
            'damage_top3', 'xp_top10'):
        return '<battles><count>%d</count></battles>' % target, {'battlesCount': metric}
    return '', {}


def xml_definition(daily):
    output = [u'<?xml version="1.0" encoding="utf-8"?><root><quests>']
    for priority, key in enumerate(daily['missions']):
        row = policy.BY_ID[key]
        native_condition, unused = condition(row)
        descriptions = {}
        counters = daily.get('progress', {}).get(key, {})
        for language, label in row['name'].items():
            counts = ', '.join('%d/%d' % (counters.get(metric, 0), target)
                               for metric, target in sorted(row['goals'].items()))
            suffix = (u'进度：%s。跨日重置。' if language == 'zh_cn'
                      else 'Progress: %s. Resets at the next game day.') % counts
            descriptions[language] = label + u'\n' + suffix
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


def preview(row, vehicles):
    assets = {}
    for kind, amount in row['rewards'].items():
        if kind == 'rental':
            # No vehicle is selected until payment. The native description
            # states tier and duration; never preview an invented vehicle.
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
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    try:
        from constants import EVENT_CLIENT_DATA
        from quest_xml_source import Source
        from items import vehicles
        if digest not in _cache:
            from gui.mods.offline_lan_0922 import config
            path = config.save_slot_state_path('ordinary_missions.xml')
            directory = os.path.dirname(path)
            if not os.path.isdir(directory):
                os.makedirs(directory)
            temporary = path + '.tmp'
            with io.open(temporary, 'w', encoding='utf-8') as stream:
                stream.write(text)
            config._replace(temporary, path)
            nodes = Source().readFromExternalFile(path,
                daily['day'] * policy.DAY, (daily['day'] + 1) * policy.DAY, stamp)
            definitions = {}
            for group in nodes.values():
                for node in group:
                    data = dict(node.info['questClientData'])
                    data['isDaily'] = True
                    key = next(key for key in daily['missions']
                               if policy.quest_id(daily['day'], key) == data['id'])
                    data['bonus'] = preview(policy.BY_ID[key], vehicles)
                    definitions[data['id']] = data
            if len(definitions) != len(daily['missions']):
                raise ValueError('Native quest parser returned %d/%d missions' %
                                 (len(definitions), len(daily['missions'])))
            _cache.clear()
            _cache[digest] = zlib.compress(pickle.dumps(definitions, 2))
            print('[Offline LAN 0.9.22] NATIVE MISSIONS parsed count=%d day=%d schema=%d' %
                  (len(definitions), daily['day'], policy.SCHEMA))
        progress = {}
        for key in daily['missions']:
            row = policy.BY_ID[key]
            values = native_progress(daily, key)
            progress[policy.quest_id(daily['day'], key)] = {'progress': {None: values}}
        return {'eventsData': {EVENT_CLIENT_DATA.QUEST: _cache[digest]}, 'quests': progress}
    except Exception as error:
        identity = (digest, str(error))
        if identity not in _errors:
            print('[Offline LAN 0.9.22] NATIVE MISSIONS unavailable day=%d error=%s' % (daily['day'], error))
            _errors.add(identity)
        return {}
