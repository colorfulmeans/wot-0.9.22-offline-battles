"""Test-mode reset, language mapping, persistence, and bounded mouse journal."""
import json
import os
import unittest
from unittest import mock
import testing_ui
from test_launcher_window import _FakeTk, _FakeTtk, _Widget


class TestingPanelTests(unittest.TestCase):
    def test_scene_flags_are_replaced_and_network_battle_cannot_inherit_a_fixture(self):
        settings = dict(scene='drop', control=True, drive=True, collision=True)
        single = testing_ui.environment(settings)
        self.assertEqual('1', single['WOT_OFFLINE_ROOF_SHOT_DROP'])
        self.assertEqual('drive', single['WOT_OFFLINE_PLAYER_AUTOCONTROL'])
        network = testing_ui.environment(settings, single=False)
        self.assertEqual('0', network['WOT_OFFLINE_ROOF_SHOT_DROP'])
        self.assertEqual('0', network['WOT_OFFLINE_EQUIPMENT_TEST'])
        self.assertEqual('0', testing_ui.environment({})['WOT_OFFLINE_PLAYER_AUTOCONTROL'])

    def test_disabling_control_closes_panel_and_sends_stop(self):
        app = mock.Mock(_tk=_FakeTk, _ttk=_FakeTtk, language='en')
        panel = testing_ui.TestingPanel(app, _Widget(), dict(control=True))
        window = panel.control_window = mock.Mock()
        panel.command_path = 'active.jsonl'
        panel.send = mock.Mock()
        panel.vars['control'].set(False)
        panel._control_changed()
        self.assertIsNone(panel.control_window)
        window.destroy.assert_called_once()
        panel.send.assert_called_once_with('stop')
        self.assertEqual('disabled', panel.control_button.options['state'])
        panel.open_controls()
        self.assertIsNone(panel.control_window)

    def test_choices_survive_language_switch_and_each_launch_has_a_fresh_journal(self):
        class App:
            _tk, _ttk, language = _FakeTk, _FakeTtk, 'zh'
            def _save_settings(self): pass
            def _log(self, message): pass
        app = App()
        panel = testing_ui.TestingPanel(app, _Widget(), dict(scene='governor', control=True))
        self.assertEqual('BOT调速器行驶测试', panel.scene.get())
        app.language = 'en'; panel.translate()
        self.assertEqual('Bot governor driving test', panel.scene.get())
        with mock.patch.dict(os.environ, {}):
            panel.apply()
            first = panel.command_path
            self.addCleanup(os.unlink, first)
            panel.send('drive', forward=1)
            with open(first, encoding='utf8') as stream:
                self.assertEqual(dict(action='drive', forward=1), json.loads(stream.read()))
            panel.apply()
            self.addCleanup(os.unlink, panel.command_path)
            self.assertNotEqual(first, panel.command_path)
            self.assertEqual(0, os.path.getsize(panel.command_path))


if __name__ == '__main__': unittest.main()
