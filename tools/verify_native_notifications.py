"""Exercise #1513's compiled badge invoice reader with Python 2.7.

Engine localization/template I/O is recorded, not reimplemented. The actual
stock preprocessing bytecode must classify both grant and withdrawal payloads.
This is an ABI check, not proof of native notification-center rendering.
"""
from __future__ import print_function
import imp
import marshal
import os
import sys
import types
import zipfile


def codes(code):
    yield code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            for child in codes(value):
                yield child


def main(client):
    archive = zipfile.ZipFile(os.path.join(client, 'res', 'packages', 'scripts.pkg'))
    def compiled(member):
        return marshal.loads(archive.read('scripts/' + member + '.pyc')[8:])
    chat = compiled('common/chat_shared')
    assert 'adminTextMessage' in chat.co_consts
    assert 'adminMessage' not in chat.co_consts
    blocks = compiled('common/dossiers2/ui/achievements')
    assert 'playerBadges' in blocks.co_consts
    reader = next(c for c in codes(compiled('client/messenger/formatters/service_channel'))
                  if c.co_name == '__prerocessRareAchievements')
    adapter = imp.load_source('notification_adapter', os.path.join(
        os.path.dirname(__file__), '..', 'src', 'res', 'scripts', 'client',
        'gui', 'mods', 'offline_lan_0922', 'native_notifications.py'))
    class Object(object):
        pass
    class Templates(object):
        def format(self, key, **kwargs):
            return (key, kwargs)
    settings = Object()
    settings.htmlTemplates = Templates()
    badges = Object()
    badges.badgeName = lambda identifier: '#badge:badge_%s' % identifier
    i18n = Object()
    i18n.makeString = lambda value: value
    achievements = Object()
    achievements.RARE = 'rareAchievements'
    preprocess = types.FunctionType(reader, dict(
        BADGES_BLOCK='playerBadges', ACHIEVEMENT_BLOCK=achievements,
        BADGE=badges, i18n=i18n, g_settings=settings))
    for sign, expected in ((1, 'badgeAchievement'), (-1, 'removedBadgeAchievement')):
        owner = Object()
        assets = adapter.reward_assets([dict(kind='badge', id=10, count=1)], sign)
        preprocess(owner, {'data': assets})
        result = owner._InvoiceReceivedFormatter__dossierResult
        assert result[0][0] == expected, result
        assert '#badge:badge_10' in result[0][1]['ctx']['badges'], result
    print('Exact #1513 badge grant/withdrawal reader and admin enum passed')


if __name__ == '__main__':
    main(sys.argv[1])
