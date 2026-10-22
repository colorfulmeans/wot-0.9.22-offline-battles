from __future__ import print_function

"""Exact #1513 TrainingRoom movie backed by the existing LAN room controller.

The native TrainingRoom Python class requires a WG legacy prebattle entity.
Use its generated DAAPI contract directly instead of inventing that entity or
entering the random queue. No native/shared movie is modified.
"""

from gui.mods.offline_lan_0922 import map_catalog
from gui.mods.offline_lan_0922.ui_i18n import as_text, tr
from gui.mods.offline_lan_0922.waiting_room_flash import RoomWindow

ALIAS = 'offlineLanTrainingRoom'
_rooms = {}
_serial = 0


def return_to_hangar():
    from gui.prb_control.events_dispatcher import g_eventDispatcher
    g_eventDispatcher.loadHangar()
    return True


def _view_type():
    import BigWorld
    from gui.Scaleform.daapi.view.meta.TrainingRoomMeta import TrainingRoomMeta

    class TrainingView(TrainingRoomMeta):
        def __init__(self, ctx=None):
            super(TrainingView, self).__init__()
            # #1513's script binder binds every matching public AS member;
            # its owner slot is a UserNameField, not our Python room owner.
            self._offline_token = (ctx or {}).get('token')
            self._offline_owner = _rooms.get(self._offline_token)

        def turnDAAPIon(self, setScript=True, movieClip=None):
            from gui.mods.offline_lan_0922.waiting_room_ui import _log
            try:
                result = super(TrainingView, self).turnDAAPIon(setScript, movieClip)
            except Exception as error:
                # BaseDAAPIModule.setFlashObject replaces this exception with
                # a generic message. Preserve the binding reason first.
                _log('native training bind_failed token=%s error=%s: %s' % (
                    self._offline_token, type(error).__name__, as_text(error)[:300]))
                import traceback
                traceback.print_exc()
                raise
            _log('native training bound token=%s' % self._offline_token)
            return result

        def _populate(self):
            super(TrainingView, self)._populate()
            if not self._owned():
                self._offline_owner = None
                BigWorld.callback(0.0, self.destroy)
                return
            self._offline_owner.view = self
            self._offline_owner.refresh()
            from gui.mods.offline_lan_0922.waiting_room_ui import _log
            _log('native training populated token=%s' % self._offline_token)

        def _owned(self):
            return (self._offline_owner is not None and self._offline_owner.room._open and
                    _rooms.get(self._offline_token) is self._offline_owner)

        def _action(self, role, value=''):
            owner, token = self._offline_owner, self._offline_token
            def invoke():
                if (owner is not None and _rooms.get(token) is owner and
                        owner.view is self and owner.room._open):
                    owner.action(role, value)
            BigWorld.callback(0.0, invoke)

        def showTrainingSettings(self):
            self._action('map')

        def startTraining(self):
            self._action('start')

        def closeTrainingRoom(self):
            self._action('close')

        def onEscape(self):
            child_open = self._owned() and self._offline_owner.settings.token is not None
            self._action('settings_close' if child_open else 'close')

        def showPrebattleInvitationsForm(self):
            # The native invite button is explicitly labelled Training settings.
            self._action('settings')

        def changeTeam(self, accID, slot):
            if self._owned() and int(accID) == self._offline_owner.room._local_player_id():
                if int(slot) in (0, 1, 2):
                    self._action('team', int(slot))

        def getPlayerTeam(self, accID):
            if self._owned():
                for row in self._offline_owner.room._player_roster():
                    if row.get('id') == int(accID):
                        return int(row.get('team', 0))
            return 0

        def canSendInvite(self):
            return self._owned()

        def canChangeSetting(self):
            return self._owned() and bool(self._offline_owner.room._host())

        def canStartBattle(self):
            return self.canChangeSetting()

        def canChangePlayerTeam(self):
            # Native drag/drop exposes all players, but the LAN protocol only
            # permits moving oneself. Team choice remains in Training settings.
            return False

        def canAssignToTeam(self, team):
            return False

        def canDestroyRoom(self):
            return False

        def swapTeams(self):
            return None

        def selectCommonVoiceChat(self, channel):
            return None

        def selectObserver(self, selected):
            return None

        def _dispose(self):
            owner, self._offline_owner = self._offline_owner, None
            if owner is not None and owner.view is self:
                owner.view = None
            super(TrainingView, self)._dispose()

    return TrainingView


def register():
    from gui.Scaleform.framework import (g_entitiesFactories, ViewSettings,
                                        ViewTypes, ScopeTemplates)
    if g_entitiesFactories.getSettings(ALIAS) is None:
        g_entitiesFactories.addSettings(ViewSettings(
            ALIAS, _view_type(), 'trainingRoom.swf', ViewTypes.LOBBY_SUB,
            ALIAS, ScopeTemplates.DEFAULT_SCOPE, True))


class TrainingSettings(RoomWindow):
    def refresh(self):
        if self.view is not None and self.view._isDAAPIInited():
            from gui.mods.offline_lan_0922.waiting_room_flash import model
            data = model(self.room)
            data['title'] = tr('Training settings')
            data['controls']['close']['label'] = tr('Back')
            self.view.flashObject.as_update(data)
        return True

    def action(self, role, value):
        if role == 'close':
            self.close()
            return
        super(TrainingSettings, self).action(role, value)


class TrainingRoomWindow(object):
    training = True
    leave_background = staticmethod(return_to_hangar)

    def __init__(self, room):
        self.room = room
        self.view = None
        self.token = None
        self.settings = TrainingSettings(room)

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
        self.settings.close()
        view, self.view = self.view, None
        if view is not None:
            view._offline_owner = None
            view.destroy()
        self.token = None
        return True

    def refresh(self):
        if self.view is None or not self.view._isDAAPIInited():
            return False
        info, teams = model(self.room)
        self.view.as_setTeam1S(teams[1])
        self.view.as_setTeam2S(teams[2])
        self.view.as_setOtherS(teams[0])
        self.view.as_setInfoS(info)
        self.view.as_setObserverS(False)
        self.view.as_disableStartButtonS(not self.room._host())
        # These are authored SoundButtonEx controls in the unchanged stock movie.
        movie = self.view.flashObject
        movie.startButton.label = tr('Start training')
        movie.settingsButton.label = tr('Select map')
        movie.inviteButton.label = tr('Training settings')
        movie.arenaVoipSettings.visible = False
        movie.arenaVOIPLabel.text = ''
        self.settings.refresh()
        return True

    def action(self, role, value=''):
        if not self.room._open or _rooms.get(self.token) is not self:
            return
        if role == 'settings':
            if self.settings.token is None:
                self.settings.open()
        elif role == 'settings_close':
            self.settings.close()
        elif role == 'team':
            self.room._select_team(value)
        else:
            self.room.activate(role)


def model(room):
    import ArenaType
    room._sync_selection()
    sizes = (room._team_status() or {}).get('sizes') or {}
    arena_id = map_catalog.arena_type_id(ArenaType.g_cache, room._selected_map, room._map_pool())
    arena = ArenaType.g_cache.get(arena_id)
    teams = dict((key, dict(teamLabel=tr('TEAM %d%s') % (key, '') if key else '', listData=[]))
                 for key in (0, 1, 2))
    for row in room._player_roster():
        team = int(row.get('team', 0))
        if team not in teams:
            continue
        name = as_text(row.get('name', ''))
        vehicle = as_text(row.get('vehicle', ''))
        # The native vehicle descriptor provides localized name and icon.
        icon, vehicle_name, level = vehicle_presentation(vehicle)
        teams[team]['listData'].append(dict(
            accID=int(row['id']), dbID=int(row['id']), userName=name,
            fullName=name, clanAbbrev='', region='', igrType=0, tags=[],
            badge=0, badgeImgStr='', icon=icon, vShortName=vehicle_name,
            vLevel=level, stateString='', isPlayerSpeaking=False))
    enabled = room._training_status()[1]
    description = tr('Training: no battle rewards or mission progress.')
    description += '<br/>' + tr('TRAINING BOTS: ON' if enabled else 'TRAINING BOTS: OFF')
    description += '<br/>' + tr('TEAM %d SIZE') % 1 + ': %d; ' % int(sizes.get(1, sizes.get('1', 15)))
    description += tr('TEAM %d SIZE') % 2 + ': %d' % int(sizes.get(2, sizes.get('2', 15)))
    return dict(
        isCreator=bool(room._host()), creator='', creatorFullName='', creatorClan='',
        creatorRegion='', creatorIgrType=0, title=tr('TRAINING ROOM'),
        arenaName=as_text(getattr(arena, 'name', room._selected_map or '')),
        arenaTypeID=arena_id or 0, arenaSubType=tr('Training mode'),
        description=description, comment=as_text(room._message or ''),
        maxPlayersCount=sum(int(sizes.get(k, sizes.get(str(k), 15))) for k in (1, 2)),
        roundLenString=tr('%d minutes') % (int(room._round_seconds() or 900) // 60),
        arenaVoipChannels=0, canChangeArenaVOIP=False, isObserverModeEnabled=False,
        badge=0, badgeImgStr=''), teams


def vehicle_presentation(name):
    from items import vehicles
    from gui.shared.gui_items.Vehicle import Vehicle
    from helpers import int2roman
    descriptor = vehicles.VehicleDescr(typeName=name)
    vehicle = Vehicle(descriptor.makeCompactDescr())
    return vehicle.iconContour, vehicle.shortUserName, int2roman(vehicle.level)
