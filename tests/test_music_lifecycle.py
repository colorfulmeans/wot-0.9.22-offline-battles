"""Exact #1513 remembered playback must not survive the lobby boundary."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922.music_lifecycle import retire_lobby_music


class MusicLifecycleTests(unittest.TestCase):
    def module(self, event_id):
        class Event:
            def __init__(self):
                self.event_id=event_id; self.sound=object(); self.stopped=0
            def getEventId(self):return self.event_id
            def stop(self):self.stopped+=1
            def destroy(self):
                self.stop(); self.sound=None; self.event_id=None
        event=Event()
        class Controller:
            _MUSIC_EVENT=0
            def __init__(self):self._MusicController__musicEvents=(event, Event())
            def stopMusic(self):event.destroy()
            def reload(self):return event.getEventId()
        return SimpleNamespace(MusicController=Controller,
                               MUSIC_EVENT_LOBBY=2, g_musicController=Controller()), event

    def test_native_stop_alone_would_restore_lobby_but_boundary_clears_it(self):
        module,event=self.module(2)
        event.stop()
        self.assertEqual(2,module.g_musicController.reload())
        ambient=module.g_musicController._MusicController__musicEvents[1].sound
        self.assertTrue(retire_lobby_music(module))
        self.assertIsNone(module.g_musicController.reload())
        self.assertIsNone(event.sound)
        self.assertIs(ambient,module.g_musicController._MusicController__musicEvents[1].sound)
        self.assertFalse(retire_lobby_music(module))
        self.assertEqual(2,event.stopped)

    def test_loading_combat_results_and_empty_music_are_preserved(self):
        for identity in (None,0,4,5,6,7,8):
            module,event=self.module(identity); original=event.sound
            self.assertFalse(retire_lobby_music(module))
            self.assertIs(original,event.sound)
            self.assertEqual(identity,event.event_id)
            self.assertEqual(0,event.stopped)
        self.assertFalse(retire_lobby_music(None))

    def test_actual_loading_boundary_retires_music_only_after_gui_transition(self):
        # Use the production boundary, not a duplicated call sequence.
        from test_port_0922_battle_runtime import NativeBattleRuntime
        module,event=self.module(2); state=[1]; calls=[]
        def show():
            calls.append(event.getEventId()); state[0]=2; return True
        runtime=SimpleNamespace(gui_global_space_id=SimpleNamespace(LOBBY=1,BATTLE_LOADING=2),
            app_loader=SimpleNamespace(showBattleLoading=show), music_controller_module=module)
        owner=SimpleNamespace(_runtime=runtime,_actual_gui_space_id=lambda:state[0])
        NativeBattleRuntime._enter_battle_loading(owner)
        self.assertEqual([2],calls)
        self.assertIsNone(event.getEventId())


if __name__=='__main__':unittest.main()
