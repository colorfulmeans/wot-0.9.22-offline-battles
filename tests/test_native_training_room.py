import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import training_room as training
from gui.mods.offline_lan_0922.waiting_room_ui import WaitingRoomUI


class NativeTrainingTests(unittest.TestCase):
    def room(self, host=True):
        room = WaitingRoomUI(
            mock.Mock(), lambda: ['01_karelia'], host=lambda: host,
            training_status=lambda: (True, False),
            team_status=lambda: dict(sizes={1: 10, 2: 12}, supported=True),
            player_roster=lambda: [dict(id=3, team=1, name='A', vehicle='ussr:R11_MS-1'),
                                   dict(id=4, team=2, name='B', vehicle='ussr:R11_MS-1')],
            local_player_id=lambda: 3, round_seconds=lambda: 600)
        room._open = True
        return room

    def test_native_roster_map_capacity_and_time_use_live_room_state(self):
        arena = types.SimpleNamespace(geometryName='01_karelia', name='Karelia')
        with mock.patch.dict(sys.modules, {'ArenaType': types.SimpleNamespace(g_cache={1: arena})}), \
                mock.patch.object(training.map_catalog, 'arena_type_id', return_value=1), \
                mock.patch.object(training, 'vehicle_presentation', return_value=('icon', 'MS-1', 'I')):
            info, teams = training.model(self.room())
        self.assertEqual(1, info['arenaTypeID'])
        self.assertEqual(22, info['maxPlayersCount'])
        self.assertEqual('10 minutes', info['roundLenString'])
        self.assertFalse(info['isObserverModeEnabled'])
        self.assertIn('Training', info['description'])
        self.assertEqual([3], [row['accID'] for row in teams[1]['listData']])
        self.assertEqual([4], [row['accID'] for row in teams[2]['listData']])
        self.assertEqual([], teams[0]['listData'])

    def native_view(self, room, pending):
        class NativeMeta(object):
            def __init__(self):
                self.destroy = mock.Mock()
            def _populate(self):
                # Native onPopulate asks these synchronously before Python
                # _populate has published the roster; owner must exist already.
                self.initial_permissions = (self.canStartBattle(), self.canSendInvite())
            def _dispose(self):
                pass
        meta = types.ModuleType('gui.Scaleform.daapi.view.meta.TrainingRoomMeta')
        meta.TrainingRoomMeta = NativeMeta
        adapter = training.TrainingRoomWindow(room)
        adapter.token = 11
        adapter.refresh = mock.Mock()
        training._rooms[11] = adapter
        self.addCleanup(training._rooms.clear)
        modules = {meta.__name__: meta,
                   'BigWorld': types.SimpleNamespace(callback=lambda delay, fn: pending.append(fn))}
        with mock.patch.dict(sys.modules, modules):
            view = training._view_type()({'token': 11})
            view._populate()
        return adapter, view, modules

    def test_native_callbacks_defer_teardown_and_reject_stale_room(self):
        pending = []
        room = self.room()
        adapter, view, modules = self.native_view(room, pending)
        self.assertEqual((True, True), view.initial_permissions)
        adapter.action = mock.Mock()
        with mock.patch.dict(sys.modules, modules):
            view.startTraining()
            view.closeTrainingRoom()
        adapter.action.assert_not_called()
        pending.pop(0)()
        adapter.action.assert_called_once_with('start', '')
        training._rooms.pop(11)
        pending.pop(0)()
        self.assertEqual(1, adapter.action.call_count)

    def test_guest_cannot_start_or_change_map_and_cannot_move_another_player(self):
        pending = []
        adapter, view, modules = self.native_view(self.room(host=False), pending)
        self.assertEqual((False, True), view.initial_permissions)
        self.assertFalse(view.canChangeSetting())
        self.assertFalse(view.canChangePlayerTeam())
        self.assertFalse(view.canAssignToTeam(1))
        adapter.action = mock.Mock()
        with mock.patch.dict(sys.modules, modules):
            view.changeTeam(4, 1)
            view.changeTeam(3, 2)
        self.assertEqual(1, len(pending))
        pending.pop()()
        adapter.action.assert_called_once_with('team', 2)

    def test_close_invalidates_callbacks_and_closes_child_settings_once(self):
        pending = []
        adapter, view, modules = self.native_view(self.room(), pending)
        adapter.settings = mock.Mock()
        with mock.patch.dict(sys.modules, modules):
            view.onEscape()
        adapter.action = mock.Mock()
        adapter.close()
        pending.pop()()
        adapter.action.assert_not_called()
        view.destroy.assert_called_once_with()
        self.assertIsNone(view.owner)
        adapter.close()
        view.destroy.assert_called_once_with()

    def test_settings_close_returns_to_native_room_without_leaving_lan(self):
        room = self.room()
        room.activate = mock.Mock()
        settings = training.TrainingSettings(room)
        settings.close = mock.Mock()
        settings.action('close', '')
        settings.close.assert_called_once_with()
        room.activate.assert_not_called()

    def test_escape_with_child_settings_never_leaves_training_room(self):
        pending = []
        adapter, view, modules = self.native_view(self.room(), pending)
        adapter.settings.token = 22
        adapter.settings.close = mock.Mock()
        adapter.room.activate = mock.Mock()
        with mock.patch.dict(sys.modules, modules):
            view.onEscape()
        pending.pop()()
        adapter.settings.close.assert_called_once_with()
        adapter.room.activate.assert_not_called()

    def test_training_page_registration_uses_original_movie_and_lobby_sub_contract(self):
        factory = types.SimpleNamespace(getSettings=mock.Mock(return_value=None), addSettings=mock.Mock())
        framework = types.SimpleNamespace(g_entitiesFactories=factory,
            ViewSettings=mock.Mock(), ViewTypes=types.SimpleNamespace(LOBBY_SUB=2),
            ScopeTemplates=types.SimpleNamespace(DEFAULT_SCOPE=3))
        with mock.patch.dict(sys.modules, {'gui.Scaleform.framework': framework}), \
                mock.patch.object(training, '_view_type', return_value='native-contract-adapter'):
            training.register()
        framework.ViewSettings.assert_called_once_with(
            training.ALIAS, 'native-contract-adapter', 'trainingRoom.swf', 2,
            training.ALIAS, 3, True)


if __name__ == '__main__':
    unittest.main()
