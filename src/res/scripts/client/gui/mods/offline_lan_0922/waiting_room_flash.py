from __future__ import print_function

"""Stock Scaleform room adapter; the existing LAN controller owns all policy."""

from gui.mods.offline_lan_0922.ui_i18n import as_text, tr

ALIAS = 'offlineLanWaitingRoom'
_rooms = {}
_serial = 0


def _view_type():
    import BigWorld
    from gui.Scaleform.framework.entities.abstract.AbstractWindowView import AbstractWindowView

    class RoomView(AbstractWindowView):
        def __init__(self, ctx=None):
            super(RoomView, self).__init__()
            self.token = (ctx or {}).get('token')
            self.owner = _rooms.get(self.token)

        def _populate(self):
            super(RoomView, self)._populate()
            if (self.owner is None or not self.owner.room._open or
                    _rooms.get(self.token) is not self.owner):
                self.owner = None
                BigWorld.callback(0.0, self.destroy)
                return
            self.owner.view = self
            self.owner.refresh()

        def offlineAction(self, role, value):
            # Never unload a Scaleform view inside its own native callback.
            owner = self.owner
            if owner is not None:
                token = self.token
                def invoke():
                    if _rooms.get(token) is owner and owner.view is self:
                        owner.action(str(role), value)
                BigWorld.callback(0.0, invoke)

        def onWindowClose(self):
            self.offlineAction('close', '')

        def _dispose(self):
            owner, self.owner = self.owner, None
            if owner is not None and owner.view is self:
                owner.view = None
                owner.view_disposed()
            super(RoomView, self)._dispose()

    return RoomView


def register():
    from gui.Scaleform.framework import (g_entitiesFactories, ViewSettings,
                                        ViewTypes, ScopeTemplates)
    if g_entitiesFactories.getSettings(ALIAS) is None:
        g_entitiesFactories.addSettings(ViewSettings(
            ALIAS, _view_type(), 'offlineWaitingRoom.swf', ViewTypes.WINDOW,
            None, ScopeTemplates.DEFAULT_SCOPE, canDrag=False,
            canClose=True, isModal=False, isCentered=False, isResizable=False))


class RoomWindow(object):
    training = False
    def __init__(self, room):
        self.room = room
        self.view = None
        self.token = None

    def open(self):
        global _serial
        from gui.app_loader import g_appLoader
        from gui.Scaleform.framework.managers.loaders import ViewLoadParams
        app = g_appLoader.getDefLobbyApp()
        if app is None:
            return False
        register()
        _serial += 1
        self.token = _serial
        _rooms[self.token] = self
        try:
            app.loadView(ViewLoadParams(ALIAS, ALIAS + str(self.token)),
                         {'token': self.token})
        except Exception:
            _rooms.pop(self.token, None)
            self.token = None
            raise
        return True

    def close(self):
        _rooms.pop(self.token, None)
        view, self.view = self.view, None
        if view is not None:
            view.owner = None
            view.destroy()
        self.token = None
        return True

    def refresh(self):
        if self.view is not None and self.view._isDAAPIInited():
            self.view.flashObject.as_update(self.model())
        return True

    def model(self):
        return model(self.room)

    def view_disposed(self):
        pass

    def action(self, role, value):
        room = self.room
        if not room._open or self.token not in _rooms:
            return
        if role == 'diagnostics':
            from gui.mods.offline_lan_0922.waiting_room_ui import _log
            _log('stock room initialized: %s' % as_text(value)[:256])
            return
        if role.startswith('class_'):
            from gui.mods.offline_lan_0922 import bot_tactics
            parts = role.split('_',2)
            if len(parts)!=3 or parts[1] not in ('1','2') or parts[2] not in bot_tactics.CLASSES+('random',):return
            team, tag = int(parts[1]), parts[2]
            status = room._team_status() or {}
            if not room._host() or not status.get('class_supported'):return
            if room._training_status()[0] and not room._training_status()[1]:return
            choices=bot_tactics.team_class_choices(status.get('classes') or None)
            if tag!='random' and choices[str(team)]['random']:return
            if callable(room._request_team_class):room._request_team_class(team,tag,not choices[str(team)][tag])
            return
        if role == 'tier':
            if room._training_status()[0]:
                if value == ('on' if room._training_status()[1] else 'off'):
                    return
                room.activate('tier')
                return
            from gui.mods.offline_lan_0922.waiting_room_ui import BOT_TIER_OPTIONS
            modes = [item[0] for item in BOT_TIER_OPTIONS]
            if value not in modes:
                return
            current = room._pending_bot_tier_mode or (room._bot_tier_status() or {}).get('mode', 'random')
            if value != current:
                room._cycle_bot_tier_mode(modes.index(value) - modes.index(current))
        elif role == 'skill':
            current = room._pending_bot_skill_mode or (room._bot_skill_status() or {}).get('mode', 'mixed')
            if value != current:
                room._choose_bot_skill_mode(value)
        elif role in ('size1', 'size2'):
            try:
                target = int(value)
            except (TypeError, ValueError):
                return
            if target < 1 or target > 15:
                return
            team = int(role[-1])
            sizes = (room._team_status() or {}).get('sizes') or {}
            current = room._pending_team_sizes.get(team, sizes.get(team, sizes.get(str(team), 15)))
            room._adjust_team_size(team, target - int(current))
        else:
            room.activate(role)


def model(room):
    from gui.mods.offline_lan_0922.waiting_room_ui import (
        BOT_TIER_OPTIONS, BOT_SKILL_OPTIONS, friendly_map_name,
        friendly_round_length)
    options = room._sync_selection()
    host = bool(room._host())
    teams = room._team_status() or {}
    tier = room._bot_tier_status() or {}
    skill = room._bot_skill_status() or {}
    training, bots = room._training_status()
    lines = as_text(room._status() or '').splitlines()
    labels = dict(room=lines[0] if lines else '',
                  players=lines[1] if len(lines) > 1 else '',
                  tierLabel=tr('Training bots') if training else tr('BOT TIER: %s%s') % ('', ''),
                  skillLabel=tr('BOT SKILL: %s%s') % ('', ''),
                  size1Label=tr('TEAM %d SIZE') % 1,
                  size2Label=tr('TEAM %d SIZE') % 2,
                  message=room._message or (tr('Training: no battle rewards or mission progress.') if training else ''))
    controls = {}

    def button(key, caption, enabled=True, visible=True, selected=False):
        controls[key] = dict(label=caption, enabled=bool(enabled), visible=bool(visible), selected=bool(selected))

    def menu(key, choices, current, enabled=True, visible=True):
        values = [str(value) for value, caption in choices]
        current = str(current)
        if current not in values:
            current = values[0]
        controls[key] = dict(options=[dict(label=as_text(caption), value=str(value)) for value, caption in choices],
                             optionsKey='|'.join(values) + '|' + '|'.join(as_text(caption) for value, caption in choices),
                             index=values.index(current), enabled=bool(enabled), visible=bool(visible))

    tier_mode = tier.get('mode', 'random')
    if room._pending_bot_tier_mode == tier_mode: room._pending_bot_tier_mode = None
    skill_mode = skill.get('mode', 'mixed')
    if room._pending_bot_skill_mode == skill_mode: room._pending_bot_skill_mode = None
    if training:
        menu('tier', [('off', tr('TRAINING BOTS: OFF')), ('on', tr('TRAINING BOTS: ON'))],
             'on' if bots else 'off', host and callable(room._toggle_training_bots))
    else:
        menu('tier', [(v, tr(c)) for v, c in BOT_TIER_OPTIONS], room._pending_bot_tier_mode or tier_mode,
             host and tier.get('supported'))
    menu('skill', [(v, tr(c)) for v, c in BOT_SKILL_OPTIONS], room._pending_bot_skill_mode or skill_mode,
         host and skill.get('supported') and (not training or bots))
    for team in (1, 2):
        sizes = teams.get('sizes') or {}
        current = int(sizes.get(team, sizes.get(str(team), 15)))
        if room._pending_team_sizes.get(team) == current: room._pending_team_sizes.pop(team, None)
        first = 0 if current == 0 and not teams.get('size_supported') else 1
        menu('size%d' % team, [(str(i), str(i)) for i in range(first, 16)], room._pending_team_sizes.get(team, current),
             host and teams.get('size_supported'))
    from gui.mods.offline_lan_0922 import bot_tactics
    choices=bot_tactics.team_class_choices(teams.get('classes') or None)
    for team in (1,2):
        row=choices[str(team)];enabled=host and teams.get('class_supported') and (not training or bots)
        button('class_%d_random'%team,tr('RANDOM'),enabled,selected=row['random'])
        for tag in bot_tactics.CLASSES:
            button('class_%d_%s'%(team,tag),'',enabled and not row['random'],selected=row['random'] or row[tag])
    button('map', tr('MAP: %s') % friendly_map_name(room._selected_map), host and bool(options))
    button('random', tr('RANDOM MAP'), host and room._random_supported())
    preferred = teams.get('preferred', 0)
    for key, team in [('team1', 1), ('team2', 2), ('team_random', 0)]:
        caption = (tr('TEAM %d%s') % (team, tr('  (YOU)') if preferred == team else '')
                   if team else tr('RANDOM%s') % (tr(' (ON)') if preferred == 0 else ''))
        button(key, caption, teams.get('supported'), selected=preferred == team)
    button('start', tr('Start training' if training else 'START BATTLE') + friendly_round_length(room._round_seconds()), host)
    button('close', tr('LEAVE'))
    return dict(title=tr('TRAINING ROOM') if training else tr('LAN WAITING ROOM'), labels=labels, controls=controls)
