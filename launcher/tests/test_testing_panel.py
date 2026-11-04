"""Launcher settings and observable player-control UI boundaries; no native GUI proof."""
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import testing_ui
from test_launcher_window import _FakeTk, _FakeTtk, _Widget


class _ControlWindow(_Widget):
    def __init__(self, parent):
        super().__init__(parent)
        self.pending = {}
        self.destroyed = False
        self._next_job = 0

    def geometry(self, value):
        self.options['geometry'] = value

    def title(self, value):
        self.options['title'] = value

    def protocol(self, name, callback):
        self.options[name] = callback

    def after(self, delay, callback):
        self._next_job += 1
        self.pending[self._next_job] = callback
        return self._next_job

    def after_cancel(self, job):
        self.pending.pop(job, None)

    def destroy(self):
        self.destroyed = True

    def lift(self):
        self.options['lifted'] = True


class _PanelTk(_FakeTk):
    Toplevel = _ControlWindow


class TestingPanelTests(unittest.TestCase):
    def setUp(self):
        self.app = mock.Mock(_tk=_PanelTk, _ttk=_FakeTtk, language='en',
                             root=_Widget(), _diagnostic_entry=False)
        self.environ = mock.patch.dict(os.environ, {}, clear=True)
        self.environ.start()
        self.addCleanup(self.environ.stop)

    def panel(self, **settings):
        return testing_ui.TestingPanel(self.app, _Widget(), dict(control=True, **settings))

    def launch(self, panel):
        panel.apply()
        for path in (panel.command_path, panel.result_path):
            if path:
                self.addCleanup(os.unlink, path)

    def status(self, panel, **overrides):
        record = dict(type='status', session_id=panel.session_id, round_id='round-a',
                      player_id=101, live=True, active=False, features=['drive', 'fire'],
                      mission={'kind': 'hold_position', 'phase': 'holding'},
                      ammo={'total': 25, 'clip_left': 2, 'clip_capacity': 4, 'reload_remaining': 1.5},
                      aim={'target_id': 202, 'phase': 'aiming'})
        record.update(overrides)
        with open(panel.result_path, 'a', encoding='utf8') as stream:
            stream.write(json.dumps(record) + '\n')
        panel._update_control_view()
        return record

    def commands(self, panel):
        with open(panel.command_path, encoding='utf8') as stream:
            return [json.loads(line) for line in stream]

    def receipt(self, panel, command, status, reason=''):
        with open(panel.result_path, 'a', encoding='utf8') as stream:
            stream.write(json.dumps(dict(command, type='command', status=status, reason=reason)) + '\n')
        panel._update_control_view()

    def test_scene_flags_are_replaced_and_network_battle_cannot_inherit_a_fixture(self):
        settings = dict(scene='drop', control=True, drive=True, collision=True)
        single = testing_ui.environment(settings)
        self.assertEqual('1', single['WOT_OFFLINE_ROOF_SHOT_DROP'])
        self.assertEqual('drive', single['WOT_OFFLINE_PLAYER_AUTOCONTROL'])
        network = testing_ui.environment(settings, single=False)
        self.assertEqual('0', network['WOT_OFFLINE_ROOF_SHOT_DROP'])
        self.assertEqual('0', network['WOT_OFFLINE_EQUIPMENT_TEST'])
        self.assertEqual('0', testing_ui.environment({})['WOT_OFFLINE_PLAYER_AUTOCONTROL'])

    def test_disabling_control_closes_panel_and_submits_exactly_one_stop(self):
        panel = self.panel()
        self.launch(panel)
        self.status(panel, active=True)
        panel.open_controls()
        window = panel.control_window
        panel.vars['control'].set(False)
        panel._control_changed()
        self.assertIsNone(panel.control_window)
        self.assertTrue(window.destroyed)
        self.assertFalse(window.pending)
        self.assertEqual(['stop'], [item['action'] for item in self.commands(panel)])
        self.assertEqual('disabled', panel.control_button.options['state'])
        panel.open_controls()
        self.assertIsNone(panel.control_window)

    def test_disabling_control_sends_stop_even_when_the_panel_was_never_opened(self):
        panel = self.panel()
        self.launch(panel)
        self.status(panel, active=True)
        panel.vars['control'].set(False)
        panel._control_changed()
        self.assertEqual(['stop'], [item['action'] for item in self.commands(panel)])
        self.assertEqual('submitted', panel.transport.last_result['status'])

    def test_closing_panel_requests_manual_control_and_cancels_poll_callback(self):
        panel = self.panel()
        self.launch(panel)
        self.status(panel, active=True)
        panel.open_controls()
        window = panel.control_window
        window.options['WM_DELETE_WINDOW']()
        self.assertTrue(window.destroyed)
        self.assertFalse(window.pending)
        self.assertEqual(['stop'], [item['action'] for item in self.commands(panel)])
        panel._poll_controls()
        self.assertFalse(window.pending)

    def test_choices_survive_language_switch_and_every_launch_has_new_identity_and_logs(self):
        self.app.language = 'zh'
        panel = self.panel(scene='governor')
        self.assertEqual('BOT调速器行驶测试', panel.scene.get())
        self.app.language = 'en'
        panel.translate()
        self.assertEqual('Bot governor driving test', panel.scene.get())
        self.launch(panel)
        first = (panel.command_path, panel.result_path, panel.session_id)
        self.assertEqual(panel.command_path, os.environ['WOT_OFFLINE_TEST_CONTROL_FILE'])
        self.assertEqual(panel.result_path, os.environ['WOT_OFFLINE_TEST_CONTROL_RESULT_FILE'])
        self.assertEqual(panel.session_id, os.environ['WOT_OFFLINE_TEST_CONTROL_SESSION'])
        self.assertFalse(panel.send('drive', forward=1, seconds=1))
        self.assertEqual([], self.commands(panel))
        self.status(panel)
        self.assertTrue(panel.send('drive', forward=1, seconds=1))
        self.assertEqual({'forward': 1, 'seconds': 1}, self.commands(panel)[0]['args'])
        self.launch(panel)
        self.assertTrue(all(old != new for old, new in zip(first,
            (panel.command_path, panel.result_path, panel.session_id))))
        self.assertEqual([], self.commands(panel))
        self.assertEqual(0, os.path.getsize(panel.result_path))
        panel.vars['control'].set(False)
        panel.apply()
        self.assertIsNone(panel.transport)
        for key in ('WOT_OFFLINE_TEST_CONTROL_FILE', 'WOT_OFFLINE_TEST_CONTROL_RESULT_FILE',
                    'WOT_OFFLINE_TEST_CONTROL_SESSION'):
            self.assertNotIn(key, os.environ)

    def test_buttons_wait_for_live_status_and_receipts_distinguish_sent_accepted_and_completed(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.assertTrue(all(button.options['state'] == 'disabled' for button in panel.action_buttons))
        self.status(panel)
        self.assertTrue(all(button.options['state'] == 'normal' for button in panel.action_buttons))
        fire = next(button for button in panel.action_buttons if button.options['text'] == 'Fire once')
        fire.options['command']()
        command = self.commands(panel)[0]
        self.assertIn('awaiting acknowledgement', panel.status_labels['result'].options['text'])
        self.receipt(panel, command, 'accepted')
        self.assertIn('awaiting completion', panel.status_labels['result'].options['text'])
        self.receipt(panel, command, 'completed', 'shot_fired')
        self.assertIn('Completed', panel.status_labels['result'].options['text'])
        self.assertIn('shot_fired', panel.status_labels['result'].options['text'])
        self.status(panel, live=False, reason='dead')
        self.assertTrue(all(button.options['state'] == ('normal' if button._control_action == 'stop' else 'disabled')
                            for button in panel.action_buttons))
        self.assertIn('destroyed', panel.status_labels['connection'].options['text'])

    def test_open_panel_translation_preserves_actual_client_data_and_all_requested_actions(self):
        panel = self.panel(drive=False)
        self.launch(panel)
        panel.open_controls()
        self.status(panel, active=True)
        labels = [button.options['text'] for button in panel.action_buttons]
        for action in testing_ui.ACTION_LABELS:
            if action != 'drive':
                self.assertIn(testing_ui.ACTION_LABELS[action][0], labels)
        self.assertIn('Driving', panel.status_labels['control'].options['text'])
        self.assertIn('25', panel.status_labels['ammo'].options['text'])
        self.assertIn('1.50', panel.status_labels['ammo'].options['text'])
        self.assertEqual('202', panel.status_labels['target'].options['text'])
        self.app.language = 'zh'
        panel.translate()
        self.assertEqual('玩家测试控制', panel.control_window.options['title'])
        self.assertIn('驾驶', panel.status_labels['control'].options['text'])
        self.assertIn('弹夹余弹: 2', panel.status_labels['ammo'].options['text'])
        self.assertIn('开始接管', [button.options['text'] for button in panel.action_buttons])

    def test_timed_inputs_use_explicit_duration_and_invalid_values_never_write(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        panel.drive_seconds.set('2.5')
        button = next(button for button in panel.action_buttons if button.options['text'] == 'Left')
        button.options['command']()
        self.assertEqual({'seconds': 2.5, 'turn': -1}, self.commands(panel)[0]['args'])
        panel.drive_seconds.set('nan')
        button.options['command']()
        self.assertEqual(1, len(self.commands(panel)))
        self.assertIn('0.1 to 10', panel.status_labels['result'].options['text'])

    def test_failed_or_rejected_commands_display_the_real_reason(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        panel.send('fire')
        self.receipt(panel, self.commands(panel)[0], 'failed', 'no_ammo')
        self.assertIn('Failed', panel.status_labels['result'].options['text'])
        self.assertIn('No ammunition', panel.status_labels['result'].options['text'])

    def test_master_off_during_client_stall_still_submits_identity_bound_stop(self):
        panel = self.panel()
        self.launch(panel)
        self.status(panel, active=True)
        panel.transport.clock = lambda: panel.transport.status_received_at + 10
        panel.vars['control'].set(False)
        panel._control_changed()
        self.assertEqual(['stop'], [item['action'] for item in self.commands(panel)])
        self.assertEqual('round-a', self.commands(panel)[0]['round_id'])
        self.assertEqual('submitted', panel.transport.last_result['status'])

    def test_stale_panel_leaves_only_restore_manual_enabled(self):
        panel = self.panel()
        self.launch(panel)
        self.status(panel, active=True)
        panel.open_controls()
        panel.transport.clock = lambda: panel.transport.status_received_at + 10
        panel._update_control_view()
        for button in panel.action_buttons:
            self.assertEqual('normal' if button._control_action == 'stop' else 'disabled', button.options['state'])
        stop = next(button for button in panel.action_buttons if button._control_action == 'stop')
        stop.options['command']()
        self.assertEqual(['stop'], [item['action'] for item in self.commands(panel)])

    def test_actual_client_snapshot_fields_render_ammo_mission_and_pose(self):
        client_path = str(Path(__file__).resolve().parents[2] / 'src/res/scripts/client')
        with mock.patch.object(sys, 'path', [client_path] + sys.path):
            from gui.mods.offline_lan_0922.player_control import PlayerControl
            from gui.mods.offline_lan_0922.player_control.capabilities import ammunition_state
            from gui.mods.offline_lan_0922.player_control.missions import Mission
        self.app.language = 'zh'
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        gun = types.SimpleNamespace(shots=[{}, {}], ammo=[0, 8], shot_index=1,
                                    clip=2, reload_time=2.75, can_fire=lambda unused: False)
        entity = types.SimpleNamespace(isAlive=lambda: True)
        owner = types.SimpleNamespace(state='running', _battle_live=True, _battle_result=None,
            _server=types.SimpleNamespace(vehicle_id=101), _server_entity=lambda unused: entity,
            _sender=object(), _worker_mode=False, _replay_mode=False,
            _start_message={'round_id': 'snapshot-round'}, client=types.SimpleNamespace(player_id=101),
            local_pose=lambda: ((1.25, 0., 4.5), 1.), _local_speed=3.25)
        control = PlayerControl(owner, ('drive', 'fire'))
        control.ammo_state = ammunition_state(gun)
        mission = Mission('mission-a', 'return_base', {},
            {'now': 0., 'position': (1.25, 0., 4.5)},
            {'point': (10., 10.), 'radius': 25., 'team': 1}, None)
        control.navigation = types.SimpleNamespace(mission_status=mission.snapshot,
            receipt={'status': 'mission_started', 'mission': 'mission-a'})
        control.aim_receipt = {'target': 202, 'aligned': True, 'fire_clear': True}
        def emit(record):
            with open(panel.result_path, 'a', encoding='utf8') as stream:
                stream.write(json.dumps(record) + '\n')
            return True
        control.emit_result = emit
        control.publish_status(1., force=True)
        panel._update_control_view()
        self.assertIn('当前弹种余弹: 8', panel.status_labels['ammo'].options['text'])
        self.assertIn('剩余装填秒数: 2.75', panel.status_labels['ammo'].options['text'])
        self.assertIn('状态: 装填中', panel.status_labels['ammo'].options['text'])
        self.assertIn('返回基地', panel.status_labels['mission'].options['text'])
        self.assertIn('行进中', panel.status_labels['mission'].options['text'])
        self.assertIn('目的地：10.00, 10.00', panel.status_labels['target'].options['text'])
        self.assertIn('位置: 1.25, 0.00, 4.50', panel.status_labels['pose'].options['text'])
        self.assertIn('速度: 3.25', panel.status_labels['pose'].options['text'])


if __name__ == '__main__':
    unittest.main()
