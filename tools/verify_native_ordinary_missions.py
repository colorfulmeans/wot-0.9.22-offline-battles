"""Run #1513's compiled quest parser with engine-I/O fixtures (Python 2.7).

This proves XML/schema consumption, not Scaleform rendering or live rewards.
No quest parsing, enum, condition reader or battle-results packer is replaced.
The two unused item-name sequences only omit interaction-detail packer fields;
ordinary cumulative conditions use the untouched full/base result schemas.
"""
from __future__ import print_function
import argparse
import io
import os
import sys
import tempfile
import types
import xml.etree.ElementTree as ET


class Section(object):
    def __init__(self, element):
        self.element = element

    def __getitem__(self, name):
        value = self.element.find(name)
        return Section(value) if value is not None else None

    def has_key(self, name):
        return self[name] is not None

    def items(self):
        return [(value.tag, Section(value)) for value in self.element]

    def keys(self):
        return [value.tag for value in self.element]

    def values(self):
        return [Section(value) for value in self.element]

    @property
    def asString(self):
        return (self.element.text or '').strip().encode('utf-8')

    @property
    def asInt(self):
        return int(self.asString)

    @property
    def asFloat(self):
        return float(self.asString)

    @property
    def asBool(self):
        return self.asString.lower() in ('true', '1')

    def readString(self, name, default=''):
        if name == '':
            return self.asString
        value = self[name]
        return default if value is None else value.asString

    def readInt(self, name, default=0):
        return int(self.readString(name, default))

    def readFloat(self, name, default=0.):
        return float(self.readString(name, default))

    def readBool(self, name, default=False):
        return str(self.readString(name, default)).lower() in ('true', '1')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client')
    args = parser.parse_args()
    if sys.version_info[:2] != (2, 7):
        parser.error('The stock compiled modules require Python 2.7')
    package = os.path.join(os.path.abspath(args.client), 'res', 'packages', 'scripts.pkg')
    sys.path[:0] = [package + '/scripts/common', package + '/scripts/client']
    import __builtin__
    __builtin__.IS_CELLAPP = False
    __builtin__.IS_BASEAPP = False
    for name in ('ResMgr', 'BigWorld', 'ArenaType', 'items.vehicles', 'items.tankmen',
                 'debug_utils', 'helpers', 'helpers.i18n'):
        sys.modules[name] = types.ModuleType(name)
    sys.modules['ResMgr'].isFile = lambda path: False
    sys.modules['ResMgr'].purge = lambda path: None
    sys.modules['ResMgr'].openSection = lambda path: Section(ET.parse(path).getroot())
    class DataSection(object):
        def createSectionFromString(self, text):
            return Section(ET.fromstring(text))
    sys.modules['ResMgr'].DataSection = DataSection
    sys.modules['BigWorld'].component = 'client'
    sys.modules['helpers'].__path__ = [package + '/scripts/client/helpers']
    sys.modules['helpers'].i18n = sys.modules['helpers.i18n']
    sys.modules['helpers.i18n'].makeString = lambda text, *args, **kwargs: text
    for name in ('LOG_ERROR', 'LOG_WARNING', 'LOG_DEBUG', 'LOG_CURRENT_EXCEPTION', 'LOG_NOTE',
                 'LOG_CRITICAL', 'LOG_DEBUG_DEV', 'LOG_WRAPPED_CURRENT_EXCEPTION', 'CRITICAL_ERROR'):
        setattr(sys.modules['debug_utils'], name, lambda *args, **kwargs: None)
    import items
    items.vehicles = sys.modules['items.vehicles']
    items.tankmen = sys.modules['items.tankmen']
    items.vehicles.VEHICLE_DEVICE_TYPE_NAMES = ()
    items.vehicles.VEHICLE_TANKMAN_TYPE_NAMES = ()
    from quest_xml_source import Source
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = os.path.join(root, 'src', 'res', 'scripts', 'client')
    for name, suffix in (('gui', 'gui'), ('gui.mods', 'gui/mods'),
                         ('gui.mods.offline_lan_0922', 'gui/mods/offline_lan_0922')):
        module = types.ModuleType(name)
        module.__path__ = [os.path.join(source, *suffix.split('/'))]
        sys.modules[name] = module
    from gui.mods.offline_lan_0922 import ordinary_missions as policy
    from gui.mods.offline_lan_0922 import ordinary_missions_native as adapter
    daily = dict(day=1, missions=sorted(policy.BY_ID), claimed=[], progress={})
    handle, path = tempfile.mkstemp(suffix='.xml')
    os.close(handle)
    try:
        with io.open(path, 'w', encoding='utf-8') as stream:
            stream.write(adapter.xml_definition(daily))
        nodes = adapter.parse_xml(adapter.xml_definition(daily), 1000000000, 0, 2000000000)
        definitions = dict((node.info['id'], node.info['questClientData'])
                           for group in nodes.values() for node in group)
        assert len(definitions) == len(policy.BY_ID) == 55
        for key in daily['missions']:
            row = definitions[policy.quest_id(1, key)]
            assert row['name']['en'] == policy.BY_ID[key]['name']['en']
            assert row['description']['zh_cn']
            assert row['showCongrats'] is False
            common = dict(row['conditions'])['common']
            assert dict(dict(common)['bonusLimit'])['value'] == 1
        sample = dict(definitions[policy.quest_id(1, 'damage3000')]['conditions'])['common']
        assert dict(dict(sample)['cumulative'])['value'] == ('damageDealt', 3000)
        composite = dict(definitions[policy.quest_id(1, 'crit7')]['conditions'])['common']
        counter = dict(dict(composite)['battles'])
        assert counter['title']['en'] == 'Objective'
        assert 'Cause 7 module or crew injuries' in counter['description']['en']
        assert '0/7' in counter['description']['en']
        assert dict(counter['count'])['value'] == 7
        combined = dict(definitions[policy.quest_id(1, 'win8damage')]['conditions'])['common']
        combined = dict(combined)
        assert dict(dict(combined['battles'])['count'])['value'] == 8
        assert dict(combined['cumulative'])['value'] == ('damageDealt', 20000)
        print('PASS: exact #1513 Source parsed 55 ordinary quests; native common counters and no congratulations flag verified.')
        print('Boundary: engine-I/O fixtures; live MissionsPage/render/payment acceptance remains separate.')
    finally:
        os.unlink(path)


if __name__ == '__main__':
    main()
