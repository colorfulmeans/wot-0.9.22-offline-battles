import sys
import json
import hashlib
import shutil
import tempfile
from pathlib import Path
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src/res/scripts/client'), str(ROOT/'tools')]
from gui.mods.offline_lan_0922 import waiting_room_ui as ui
from gui.mods.offline_lan_0922 import waiting_room_flash as flash
from build_waiting_room_swf import tags, validate_control_linkages


class StockRoomTests(unittest.TestCase):
    def room(self, host=True, training=False):
        tiers = dict(mode='same', supported=True)
        skills = dict(mode='hard', supported=True)
        teams = dict(sizes={1: 15, 2: 12}, supported=True, size_supported=True, preferred=2, counts={1: 3})
        room = ui.WaitingRoomUI(mock.Mock(), lambda: ['01_karelia'],
            status=lambda: 'LAN SERVER: 127.0.0.1:28782\nPlayer (1): Test',
            host=lambda: host, surface=object(), initial_map='01_karelia',
            request_bot_tier_mode=mock.Mock(), bot_tier_status=lambda: tiers,
            request_bot_skill_mode=mock.Mock(), bot_skill_status=lambda: skills,
            request_team_size=mock.Mock(), team_status=lambda: teams,
            request_team=mock.Mock(), training_status=lambda: (training, True),
            toggle_training_bots=mock.Mock())
        room._open = True
        room.refresh = mock.Mock(return_value=True)
        return room

    def test_menu_order_and_existing_preference_values_are_preserved(self):
        room = self.room()
        model = flash.model(room)
        controls = model['controls']
        self.assertEqual(['mixed','easy','relaxed','hard','brutal'],
                         [item['value'] for item in controls['skill']['options']])
        self.assertEqual(3, controls['skill']['index'])
        self.assertEqual(1, controls['tier']['index'])
        self.assertEqual(11, controls['size2']['index'])
        self.assertTrue(controls['team2']['selected'])
        self.assertEqual(15, len(controls['size1']['options']))
        self.assertFalse(any('previous' in key or 'next' in key or '_up' in key for key in controls))

    def test_guest_cannot_change_host_settings(self):
        controls = flash.model(self.room(host=False))['controls']
        for key in ('tier','skill','size1','size2','map','random','start'):
            self.assertFalse(controls[key]['enabled'], key)
        self.assertTrue(controls['team1']['enabled'])

    def test_native_initial_selection_events_do_not_resubmit_settings(self):
        room = self.room()
        adapter = flash.RoomWindow(room)
        adapter.token = 1
        with mock.patch.dict(flash._rooms, {1: adapter}, clear=True):
            adapter.action('tier', 'same')
            adapter.action('skill', 'hard')
            room._request_bot_tier_mode.assert_not_called()
            room._request_bot_skill_mode.assert_not_called()
            adapter.action('tier', '0_plus2')
            room._request_bot_tier_mode.assert_called_once_with('0_plus2')
            adapter.action('skill', 'brutal')
            room._request_bot_skill_mode.assert_called_once_with('brutal')
            adapter.action('size1', '2')
            room._request_team_size.assert_not_called()  # Three people already joined.
            adapter.action('size1', '10')
            room._request_team_size.assert_called_once_with(1, 10)

    def test_training_bot_selector_does_not_toggle_on_initial_publish(self):
        room = self.room(training=True)
        adapter = flash.RoomWindow(room); adapter.token = 1
        with mock.patch.dict(flash._rooms, {1: adapter}, clear=True):
            adapter.action('tier', 'on')
            room._toggle_training_bots.assert_not_called()
            adapter.action('tier', 'off')
            room._toggle_training_bots.assert_called_once_with()

    def test_random_class_mode_disables_checked_icons_and_manual_low_spg_stays_available(self):
        from gui.mods.offline_lan_0922 import bot_tactics
        room=self.room();teams=room._team_status();teams['class_supported']=True
        teams['classes']=bot_tactics.team_class_choices();teams['sizes'][1]=1
        room._request_team_class=mock.Mock()
        controls=flash.model(room)['controls']
        self.assertTrue(controls['class_1_random']['selected'])
        for tag in bot_tactics.CLASSES:
            self.assertTrue(controls['class_1_'+tag]['selected']);self.assertFalse(controls['class_1_'+tag]['enabled'])
        adapter=flash.RoomWindow(room);adapter.token=1
        with mock.patch.dict(flash._rooms,{1:adapter},clear=True):
            adapter.action('class_1_SPG','');room._request_team_class.assert_not_called()
            adapter.action('class_1_random','');room._request_team_class.assert_called_once_with(1,'random',False)
            room._request_team_class.reset_mock()
            teams['classes']['1']['random']=False;teams['classes']['1']['SPG']=False
            controls=flash.model(room)['controls'];self.assertTrue(controls['class_1_SPG']['enabled'])
            adapter.action('class_1_SPG','');room._request_team_class.assert_called_once_with(1,'SPG',True)
        room._training_status=lambda:(True,False)
        self.assertFalse(flash.model(room)['controls']['class_1_random']['enabled'])

    def test_callbacks_are_deferred_and_stale_views_cannot_control_reopened_room(self):
        class Base(object):
            def __init__(self): self.destroy = mock.Mock()
            def _populate(self): pass
            def _dispose(self): pass
        deferred = []
        native = types.ModuleType('gui.Scaleform.framework.entities.abstract.AbstractWindowView')
        native.AbstractWindowView = Base
        with mock.patch.dict(sys.modules, {'BigWorld': types.SimpleNamespace(callback=lambda t, fn: deferred.append(fn)),
                                          native.__name__: native}):
            view_type = flash._view_type()
            room = self.room()
            adapter = flash.RoomWindow(room); adapter.token = 7; adapter.refresh = mock.Mock()
            with mock.patch.dict(flash._rooms, {7: adapter}, clear=True):
                view = view_type({'token': 7}); view._populate()
                self.assertIs(view, adapter.view)
                adapter.action = mock.Mock()
                view.offlineAction('close', '')
                adapter.action.assert_not_called()
                flash._rooms.pop(7)
                adapter.token = 8; flash._rooms[8] = adapter
                deferred.pop(0)()
                adapter.action.assert_not_called()
                stale = view_type({'token': 7}); stale._populate()
                self.assertIs(view, adapter.view)
                self.assertIsNone(stale.owner)
                deferred.pop(0)()
                stale.destroy.assert_called_once_with()

    def test_model_is_applied_after_clik_initialization_and_wrapper_is_remeasured(self):
        source = (ROOT/'tools/actionscript/OfflineWaitingRoom.as').read_text(encoding='utf8')
        publish = source.split('public function as_update(data:Object):void {', 1)[1]
        self.assertLess(publish.index('validateNow();'), publish.index('for (var key:String in fields)'))
        self.assertLess(publish.index('widget.validateNow();'), publish.index('widget.label = state.label'))
        self.assertIn('UIComponent(window).invalidate(Window.INVALID_SRC_VIEW)', publish)
        self.assertLess(publish.index('UIComponent(window).validateNow();'), publish.index('placeRoom();'))
        self.assertIn('roomChars=', publish)

    def test_runtime_linkages_cannot_use_authoring_names(self):
        with self.assertRaisesRegex(ValueError, 'Unknown native control linkage'):
            validate_control_linkages('item.itemRenderer = "DropDownListItemRendererSoundUI";',
                                      {'DropDownListItemRendererSound'})
        self.assertEqual(['DropDownListItemRendererSound'], validate_control_linkages(
            'item.itemRenderer = "DropDownListItemRendererSound";', {'DropDownListItemRendererSound'}))
        with self.assertRaisesRegex(ValueError, 'ScrollBarTypo'):
            validate_control_linkages('item.scrollBar = "ScrollBarTypo";', {'ScrollBar'})

    def test_stock_sizing_and_dropdown_contract(self):
        source = (ROOT/'tools/actionscript/OfflineWaitingRoom.as').read_text(encoding='utf8')
        initialize = source.split('override protected function initialize():void {')[1].split(
            'override protected function configUI():void {')[0]
        self.assertIn('_originalWidth = 660', initialize)
        self.assertIn('_originalHeight = 282', initialize)
        self.assertIn('setActualScale(1, 1)', initialize)
        component = source.split('private function component(')[1].split('private function button(')[0]
        self.assertIn('App.utils.classFactory.getComponent', component)
        self.assertIn('item.width = w', component)
        self.assertNotIn('item.setSize', component)
        self.assertNotIn('item.height = 22;\n            item.width', component.split('if (linkage == "ButtonRed")')[0])
        dropdown = source.split('private function dropdown(')[1].split('private function clicked(')[0]
        self.assertIn('item.rowCount = 8', dropdown)
        self.assertIn('item.scrollBar = \"ScrollBar\"', dropdown)
        self.assertIn('item.menuRowsFixed = false', dropdown)
        self.assertIn('item.thumbOffsetTop = 0', dropdown)
        self.assertIn('item.thumbOffsetBottom = 0', dropdown)
        self.assertNotIn('item.rowHeight', dropdown)
        self.assertNotIn('item.menuRowCount', dropdown)
        self.assertIn('DropDownListItemRendererSound"', dropdown)

    def test_build_rejects_a_stale_movie_after_actionscript_changes(self):
        import build_wotmod
        build_wotmod._validate_waiting_room_ui(str(ROOT))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('src/res/gui/flash/offlineWaitingRoom.swf',
                         'src/res/gui/flash/offlineWaitingRoom.swf.json',
                         'tools/actionscript/OfflineWaitingRoom.as',
                         'src/res/gui/flash/offlineMapPicker.swf',
                         'src/res/gui/flash/offlineMapPicker.swf.json',
                         'tools/actionscript/OfflineMapPicker.as',
                         'tools/rebuild_review_room.py',
                         'tools/build_waiting_room_swf.py'):
                target = root/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT/name, target)
            build_wotmod._validate_waiting_room_ui(str(root))
            with (root/'tools/actionscript/OfflineWaitingRoom.as').open('ab') as stream:
                stream.write(b'\n// changed source\n')
            with self.assertRaisesRegex(ValueError, 'Rebuild waiting-room'):
                build_wotmod._validate_waiting_room_ui(str(root))

    def test_compiled_movie_is_mod_owned_and_uses_native_shared_libraries(self):
        path = ROOT/'src/res/gui/flash/offlineWaitingRoom.swf'
        parts = tags(path.read_bytes())[1]
        symbols = b''.join(body for code, body in parts if code == 76)
        self.assertIn(b'OfflineWaitingRoomUI\0', symbols)
        self.assertNotIn(b'\0TrainingWindow\0', symbols)
        imports = [body for code, body in parts if code == 71]
        self.assertTrue(any(body.startswith(b'guiControlsLogin.swf\0') for body in imports))
        self.assertFalse((ROOT/'src/res/gui/flash/trainingWindow.swf').exists())
        source = (ROOT/'tools/actionscript/OfflineWaitingRoom.as').read_text(encoding='utf8')
        for control in ('DropdownMenuUI','ButtonNormal','ButtonBlack','ButtonRed'):
            self.assertIn(control, source)
        self.assertIn('queue.modeTitle.getBounds(stage)', source)
        self.assertIn('DisplayObject(queue.exitButton).getBounds(stage)', source)
        self.assertIn('globalToLocal(globalPos)', source)
        self.assertIn('window.getBackground().getBounds(stage)', source)
        self.assertNotIn('DisplayObject(window).getBounds(stage)', source)


if __name__ == '__main__': unittest.main()
