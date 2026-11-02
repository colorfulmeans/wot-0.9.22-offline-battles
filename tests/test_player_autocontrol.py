"""Input ownership, bounded script commands, and round lifecycle contracts."""
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import player_autocontrol as control


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.sent, self.bursts, self.messages, self.records = [], [], [], []
        sender = types.SimpleNamespace(forward=1, turn=1, handbrake=True,
            aim_yaw=.2, gun_pitch=.1, send_current=lambda: self.sent.append(True))
        self.owner = types.SimpleNamespace(state='running', _battle_live=True,
            _battle_result=None, _worker_mode=False, _replay_mode=False,
            _server=types.SimpleNamespace(vehicle_id=1), _sender=sender,
            _avatar=types.SimpleNamespace(autoAim=lambda value: None),
            _cancel_local_player_burst=lambda **kw: self.bursts.append(kw),
            shoot=lambda *args: True)
        self.control = control.PlayerControl(self.owner, ['drive', 'fire'], self.messages.append)
        self.control.record = lambda stage, **kw: self.records.append((stage, kw))

    def test_timed_drive_replaces_automatic_writer_and_stop_clears_pending_shots(self):
        self.control.active = True
        self.assertTrue(self.control.command(dict(action='drive', forward=1, seconds=1), 20))
        self.assertFalse(self.control.active)
        self.assertEqual((21, 1, 0), self.control.override)
        self.control.stop()
        self.assertIsNone(self.control.override)
        self.assertEqual((0, 0, False), (self.owner._sender.forward,
            self.owner._sender.turn, self.owner._sender.handbrake))
        self.assertEqual(2, len(self.bursts))
        self.assertEqual(2, len(self.sent))

    def test_invalid_drive_and_nonlive_commands_cannot_move_player(self):
        for seconds in (0, -1, 11, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                self.control.command(dict(action='drive', seconds=seconds), 0)
            self.assertIsNone(self.control.override)
        self.owner._battle_result = {}
        self.assertFalse(self.control.command(dict(action='drive'), 0))

    def test_replay_and_worker_never_attach_a_player_input_producer(self):
        with mock.patch.dict(os.environ, {'WOT_OFFLINE_PLAYER_AUTOCONTROL': 'drive'}):
            for key in ('_worker_mode', '_replay_mode'):
                setattr(self.owner, key, True)
                self.assertIsNone(control.attach(self.owner))
                setattr(self.owner, key, False)

    def test_native_key_seam_for_all_camera_modes_restores_original_on_close(self):
        class Handler:
            def handleKeyEvent(self, event): return 'native'
        handler = Handler()
        self.owner._avatar.inputHandler = handler
        self.control.input_available = lambda: True
        toggles = []
        self.control.toggle = lambda: toggles.append(True)
        control._current = self.control
        self.addCleanup(lambda: setattr(control, '_current', None))
        with mock.patch.dict(sys.modules, {'Keys': types.SimpleNamespace(KEY_GRAVE=41),
                'game': types.SimpleNamespace(convertKeyEvent=lambda event: event)}):
            self.control.bind_input()
            self.assertTrue(handler.handleKeyEvent((True, 41, 0, False)))
            handler.handleKeyEvent((True, 41, 0, True))
            self.assertEqual([True], toggles)
            handler.handleKeyEvent((False, 41, 0, False))
            self.control.input_available = lambda: False
            self.assertEqual('native', handler.handleKeyEvent((True, 41, 0, False)))
            self.assertEqual([True], toggles)
        self.control.close()
        self.assertNotIn('handleKeyEvent', handler.__dict__)
        self.assertEqual('native', handler.handleKeyEvent(None))

    def test_partial_journal_line_waits_and_complete_command_runs_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'commands.jsonl'
            line = json.dumps({'action': 'fire'})
            path.write_text(line, encoding='utf8')
            with mock.patch.dict(os.environ, {'WOT_OFFLINE_TEST_CONTROL_FILE': str(path)}):
                self.control.poll_commands(1)
                self.assertEqual(0, self.control.command_offset)
                path.write_text(line+'\n', encoding='utf8')
                self.control.poll_commands(2)
                self.control.poll_commands(3)
            self.assertEqual(1, len([r for r in self.records if r[0]=='script_fire']))

    def test_new_round_starts_manual_and_skips_old_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'commands.jsonl'
            path.write_text('{"action":"toggle"}\n', encoding='utf8')
            with mock.patch.dict(os.environ, {'WOT_OFFLINE_PLAYER_AUTOCONTROL': 'drive',
                    'WOT_OFFLINE_TEST_CONTROL_FILE': str(path)}), mock.patch.object(control, '_current', None):
                instance = control.attach(self.owner)
                self.assertFalse(instance.active)
                self.assertEqual(path.stat().st_size, instance.command_offset)

    def test_real_input_sender_preserves_manual_input_only_for_unclaimed_features(self):
        from test_port_0922_battle_runtime import _LANInputSender
        self.owner._player_autocontrol = self.control
        sender = _LANInputSender(self.owner)
        sender.send_current = lambda: True
        self.control.active = True
        sender.send_avatar_input(1, 'move', {'flags': 1})
        self.assertEqual(0, sender.forward)
        self.control.active = False
        self.control.override = (2, 1, 0)
        sender.send_avatar_input(1, 'move', {'flags': 1})
        self.assertEqual(0, sender.forward)
        self.control.override = None
        sender.send_avatar_input(1, 'move', {'flags': 1})
        self.assertNotEqual(0, sender.forward)


if __name__ == '__main__': unittest.main()
