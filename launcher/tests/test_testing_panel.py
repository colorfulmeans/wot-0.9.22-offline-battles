"""Launcher control wiring, receipts and optional real-Tk layout; no game-engine proof."""
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock
import tkinter as tk
from tkinter import ttk

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

    def receipt(self, panel, command, status, reason='', **fields):
        with open(panel.result_path, 'a', encoding='utf8') as stream:
            record = dict(command, type='command', status=status, reason=reason)
            record.update(fields)
            stream.write(json.dumps(record) + '\n')
        panel._update_control_view()

    def shot(self, panel, command, status, **fields):
        row = dict(type='shot', session_id=panel.session_id, round_id=command['round_id'],
            player_id=command['player_id'], command_id=command['id'], projectile_id='test:p',
            status=status, event_seq=1, time=1.)
        row.update(fields)
        with open(panel.result_path, 'a', encoding='utf8') as stream:
            stream.write(json.dumps(row) + '\n')
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
        self.assertTrue(all(button.options['state'] == ('normal' if button._control_action in
                            testing_ui.player_control_transport.READ_ONLY_ACTIONS | {'stop'} and
                            not getattr(button, '_requires_live', False) else 'disabled')
                            for button in panel.action_buttons))
        self.assertIn('destroyed', panel.status_labels['connection'].options['text'])

    def test_open_panel_translation_preserves_actual_client_data_and_all_requested_actions(self):
        panel = self.panel(drive=False)
        self.launch(panel)
        panel.open_controls()
        self.status(panel, active=True)
        labels = [button.options['text'] for button in panel.action_buttons]
        for action in testing_ui.ACTION_LABELS:
            if action not in ('drive', 'wait_state', 'assert_state'):
                self.assertIn(testing_ui.ACTION_LABELS[action][0], labels)
        self.assertEqual(set(testing_ui.ACTION_LABELS), {button._control_action for button in panel.action_buttons})
        self.assertIn('Wait for ammunition ready', labels)
        self.assertIn('Assert ammunition empty', labels)
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
        root = Path(__file__).resolve().parents[2]
        paths = [str(root / 'src/res/scripts/client'), str(root / 'tests')]
        with mock.patch.object(sys, 'path', paths + sys.path):
            from test_player_limited_traverse import TraverseScene
            scene = TraverseScene()
            scene.setUp()
            self.addCleanup(scene.doCleanups)
            scene.configure(limits=None, tag='mediumTank', clip=4,
                            burst=1, bearing=0., rate=0.)
        self.app.language = 'zh'
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        control, owner = scene.control, scene.battle
        gun = owner._gun_state
        gun.ammo, gun.shot_index, gun.clip, gun.reload_time = [0, 8], 1, 2, 2.75
        scene.position = (1.25, 0., 4.5)
        scene.set_hull(1.)
        owner._local_speed = 3.25
        owner._last_snapshot = dict(round_id=owner._start_message['round_id'],
            capture_bases={'1': [dict(id='1:0', x=10., y=0., z=10., radius=3.)],
                           '2': [dict(id='2:0', x=0., y=0., z=40., radius=3.)]})
        scene.observe()
        # The real bound runtime derives its home destination from canonical
        # base data. Its update publishes the observed gun and mission; no
        # cached status or hand-written mission is substituted for the owner.
        scene.runtime.set_mission('return_base', dict(command_id='mission-a'))
        def emit(record):
            with open(panel.result_path, 'a', encoding='utf8') as stream:
                stream.write(json.dumps(record) + '\n')
            return True
        control.emit_result = emit
        scene.tick()
        self.assertIsNone(control.last_control_failure)
        self.assertEqual(control._runtime_binding, control._native_binding())
        control.publish_status(scene.now, force=True)
        panel._update_control_view()
        self.assertIn('当前弹种余弹: 8', panel.status_labels['ammo'].options['text'])
        self.assertIn('剩余装填秒数: 2.75', panel.status_labels['ammo'].options['text'])
        self.assertIn('状态: 装填中', panel.status_labels['ammo'].options['text'])
        self.assertIn('返回基地', panel.status_labels['mission'].options['text'])
        self.assertIn('行进中', panel.status_labels['mission'].options['text'])
        self.assertIn('目的地：10.00, 10.00', panel.status_labels['target'].options['text'])
        self.assertIn('位置: 1.25, 0.00, 4.50', panel.status_labels['pose'].options['text'])
        self.assertIn('速度: 3.25', panel.status_labels['pose'].options['text'])

    def test_late_launch_rejection_is_visible_without_rewriting_local_commit(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        panel.send('fire')
        command = self.commands(panel)[0]
        self.receipt(panel, command, 'completed', 'shot_committed',
            result={'projectile_ids': ['test:p'], 'stage': 'local_committed'})
        local_receipt = dict(panel.transport.last_result)
        self.assertIn('Local commit confirmed', panel.status_labels['result'].options['text'])
        self.shot(panel, command, 'rejected', reason='projectile_launch_rejected')
        self.assertEqual(local_receipt, panel.transport.last_result)
        text = panel.status_labels['projectiles'].options['text']
        self.assertIn('Local commit observed', text)
        self.assertIn('Launch rejected', text)
        self.assertIn('later rejected', text)
        self.assertIn('Local commit confirmed', panel.status_labels['result'].options['text'])

    def test_terminal_then_late_combat_remains_observations_in_both_languages_after_stop(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        panel.send('fire')
        command = self.commands(panel)[0]
        self.receipt(panel, command, 'completed', 'shot_committed',
                     result={'projectile_ids': ['test:p']})
        self.shot(panel, command, 'terminal')
        text = panel.status_labels['projectiles'].options['text']
        self.assertIn('Flight terminal observed', text)
        self.assertIn('No combat effect observed yet', text)
        self.assertNotIn('miss', text.lower())
        panel.send('stop')
        self.receipt(panel, self.commands(panel)[1], 'completed', 'manual_control')
        self.shot(panel, command, 'hit', event_seq=2, damage_total=140., hit_count=2, penetrated=True)
        self.assertIn('Restore manual control', panel.status_labels['result'].options['text'])
        self.assertIn('Damage 140.00', panel.status_labels['projectiles'].options['text'])
        self.assertIn('Combat effects 2', panel.status_labels['projectiles'].options['text'])
        self.app.language = 'zh'
        panel.translate()
        self.assertIn('飞行终结', panel.status_labels['projectiles'].options['text'])
        self.assertIn('伤害140.00', panel.status_labels['projectiles'].options['text'])
        self.assertIn('战斗效果2次', panel.status_labels['projectiles'].options['text'])
        self.assertIn('恢复手动', panel.status_labels['result'].options['text'])

    def test_fire_then_start_shows_new_automatic_shots_without_mislabeling_the_command(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        panel.send('fire')
        command = self.commands(panel)[0]
        self.receipt(panel, command, 'completed', 'shot_committed', result={'projectile_ids': ['test:p']})
        panel.send('start')
        self.receipt(panel, self.commands(panel)[1], 'completed', 'active')
        self.shot(panel, command, 'committed', command_id=None, projectile_id='automatic:p', event_seq=2)
        text = panel.status_labels['projectiles'].options['text']
        self.assertIn('test:p · Command [%s]' % command['id'][:8], text)
        self.assertIn('automatic:p · Automatic / unlinked', text)
        self.assertNotIn('automatic:p · Command', text)
        self.assertIn('Start takeover', panel.status_labels['result'].options['text'])
        self.app.language = 'zh'
        panel.translate()
        self.assertIn('自动射击／未关联命令', panel.status_labels['projectiles'].options['text'])

    def test_attack_and_hold_buttons_send_explicit_xyz_and_radius_and_keep_settings_on_translation(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        panel.mission_custom_point.set(True)
        panel._refresh_point_fields()
        for axis, value in zip(('x', 'y', 'z'), ('12.5', '-2', '34')):
            panel.mission_position[axis].set(value)
        panel.mission_radius.set('7.5')
        for action in ('attack', 'hold_position'):
            button = next(button for button in panel.action_buttons if button._control_action == action)
            self.assertTrue(button.options['command']())
        self.assertEqual(['attack', 'hold_position'], [command['action'] for command in self.commands(panel)])
        for command in self.commands(panel):
            self.assertEqual({'position': [12.5, -2., 34.], 'radius': 7.5}, command['args'])
            self.assertIn('expires_at', command)
        self.app.language = 'zh'
        panel.translate()
        self.assertEqual(['12.5', '-2', '34'], [panel.mission_position[axis].get() for axis in ('x', 'y', 'z')])
        self.assertEqual('7.5', panel.mission_radius.get())

    def test_default_attack_and_hold_do_not_invent_a_point_from_launcher_state(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel, pose={'position': [100., 20., 30.]})
        self.assertFalse(panel.mission_custom_point.get())
        self.assertTrue(all(entry.options['state'] == 'disabled' for entry in panel.mission_entries))
        for action in ('attack', 'hold_position'):
            next(button for button in panel.action_buttons if button._control_action == action).options['command']()
        self.assertEqual([{}, {}], [command['args'] for command in self.commands(panel)])

    def test_invalid_point_and_radius_never_write_a_request(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        panel.mission_custom_point.set(True)
        button = next(button for button in panel.action_buttons if button._control_action == 'attack')
        for value in ('nan', 'inf', '100001', '', 'not a number'):
            panel.mission_position['x'].set(value)
            self.assertFalse(button.options['command']())
            self.assertIn('coordinates', panel.status_labels['result'].options['text'])
        panel.mission_position['x'].set('0')
        for value in ('nan', 'inf', '1.9', '150.1', 'bad'):
            panel.mission_radius.set(value)
            self.assertFalse(button.options['command']())
            self.assertIn('Radius', panel.status_labels['result'].options['text'])
        self.assertEqual([], self.commands(panel))
        self.assertFalse(panel.send('hold_position', position=[1, 2]))
        self.assertEqual([], self.commands(panel))

    def test_use_current_pose_is_an_explicit_mouse_choice_without_sending_a_command(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel, pose={'position': [1.25, -3., 8.5]})
        button = next(button for button in panel.action_buttons if button.options['text'] == 'Use current pose')
        self.assertTrue(button.options['command']())
        self.assertTrue(panel.mission_custom_point.get())
        self.assertEqual(['1.25', '-3.0', '8.5'], [panel.mission_position[axis].get() for axis in ('x', 'y', 'z')])
        self.assertEqual([], self.commands(panel))
        next(button for button in panel.action_buttons if button._control_action == 'hold_position').options['command']()
        self.assertEqual({'position': [1.25, -3., 8.5]}, self.commands(panel)[0]['args'])
        self.status(panel, pose={})
        self.assertFalse(panel._use_current_pose())
        self.assertEqual('position_unavailable', panel.notice)
        self.assertEqual(1, len(self.commands(panel)))

    def test_empty_feature_selection_preserves_enabled_manual_test_controller_launch(self):
        panel = self.panel(drive=False, fire=False, consumables=False)
        self.launch(panel)
        self.assertEqual('enabled', os.environ['WOT_OFFLINE_PLAYER_AUTOCONTROL'])
        self.assertIsNotNone(panel.transport)
        self.assertIsNotNone(panel.session_id)
        self.assertEqual([], self.commands(panel))
        panel.open_controls()
        self.status(panel, features=[], active=False)
        self.assertIn('No automatic channels', panel.status_labels['control'].options['text'])

    def test_expired_admission_is_reported_as_not_executed_not_as_command_completion(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        panel.send('attack')
        self.receipt(panel, self.commands(panel)[0], 'rejected', 'request_expired')
        text = panel.status_labels['result'].options['text']
        self.assertIn('Rejected', text)
        self.assertIn('not executed', text)

    def test_compact_shell_selection_and_reload_use_fixed_actions_and_native_wait_deadlines(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel, testing={'gun': {'stock': [{'index': 0, 'compact_descr': 65537, 'ammo': 12}],
                                           'pending_index': None, 'stock_truncated': False}})
        self.assertIn('65537', panel.status_labels['ammo'].options['text'])
        panel.shell_compact_descr.set('65537')
        load = next(button for button in panel.action_buttons if button._control_action == 'select_shell')
        reload_button = next(button for button in panel.action_buttons if button._control_action == 'reload')
        self.assertTrue(load.options['command']())
        self.assertTrue(reload_button.options['command']())
        self.assertEqual(['select_shell', 'reload'], [command['action'] for command in self.commands(panel)])
        self.assertEqual([{'compact_descr': 65537}, {}], [command['args'] for command in self.commands(panel)])
        self.assertTrue(all(command['timeout_seconds'] == 180. for command in self.commands(panel)))
        self.assertIn('awaiting acknowledgement', panel.status_labels['result'].options['text'])
        self.app.language = 'zh'
        panel.translate()
        self.assertEqual('65537', panel.shell_compact_descr.get())
        self.assertIn('装填指定弹种', [button.options['text'] for button in panel.action_buttons])

    def test_invalid_shell_descriptor_never_writes_any_command(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        button = next(button for button in panel.action_buttons if button._control_action == 'select_shell')
        for value in ('', '0', '-1', '1.5', '1e3', 'True', 'nan', '2147483648', 'a.b'):
            panel.shell_compact_descr.set(value)
            self.assertFalse(button.options['command']())
            self.assertEqual('invalid_compact_descr', panel.notice)
        self.assertEqual([], self.commands(panel))

    def test_compact_state_check_buttons_observe_fresh_nonlive_without_claiming_completion(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel, live=False, reason='dead', active=False)
        for action in ('wait_state', 'assert_state'):
            button = next(button for button in panel.action_buttons if button._control_action == action)
            self.assertEqual('normal', button.options['state'])
            self.assertTrue(button.options['command']())
        commands = self.commands(panel)
        self.assertEqual([{'condition': 'ammo_ready'}, {'condition': 'ammo_empty'}], [command['args'] for command in commands])
        self.assertEqual(30., commands[0]['timeout_seconds'])
        self.assertTrue(all(command['replace'] is False for command in commands))
        self.assertIn('awaiting acknowledgement', panel.status_labels['result'].options['text'])
        self.receipt(panel, commands[1], 'failed', 'assertion_failed',
            result={'condition': 'ammo_empty', 'known': True, 'matched': False, 'value': False})
        text = panel.status_labels['result'].options['text']
        self.assertIn('Failed', text)
        self.assertIn('Ammunition empty', text)
        self.assertIn('Matched: No', text)
        panel.transport.clock = lambda: panel.transport.status_received_at + 10.
        panel._update_control_view()
        for button in panel.action_buttons:
            self.assertEqual('normal' if button._control_action == 'stop' else 'disabled', button.options['state'])
        self.assertFalse(panel.send('wait_state', condition='ammo_ready'))
        self.assertEqual(2, len(self.commands(panel)))

    def test_unconfirmed_command_reference_is_not_presented_as_verified_linkage(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel, shot_snapshot_omitted=4, shot_results=[dict(
            projectile_id='observed:p', command_id='unconfirmed-id', status='terminal',
            event_seq=1, terminal_observed=True, time=1.)])
        text = panel.status_labels['projectiles'].options['text']
        self.assertIn('receipt not observed', text)
        self.assertIn('4 older shots', text)
        self.assertNotIn('Command [unconfir]', text)
        self.assertIsNone(panel.transport.projectile_results()[0]['command_id'])

    def test_explicit_aim_buttons_send_bounded_args_and_translation_preserves_fields(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel, manual_aim={'held': False, 'aligned': False,
            'visible_targets': [{'target_id': 202, 'position': [1, 2, 3]}]})
        panel.aim_target_id.set('202')
        panel.aim_tolerance.set('1.25')
        for axis, value in zip(('x', 'y', 'z'), ('-10.5', '3', '42')):
            panel.aim_position[axis].set(value)
        panel.aim_release_id.set('aim-holder')
        for action in ('aim_target', 'aim_point', 'release_aim'):
            button = next(button for button in panel.action_buttons if button._control_action == action)
            self.assertTrue(button.options['command']())
        commands = self.commands(panel)
        self.assertEqual([{'target_id': 202, 'tolerance_deg': 1.25},
                          {'position': [-10.5, 3., 42.], 'tolerance_deg': 1.25},
                          {'command_id': 'aim-holder'}], [row['args'] for row in commands])
        self.assertEqual([30., 30., 10.], [row['timeout_seconds'] for row in commands])
        self.assertTrue(all(row['expires_at'] > 0 for row in commands))
        panel.aim_release_id.set('')
        self.assertTrue(panel._release_aim())
        self.assertEqual({}, self.commands(panel)[-1]['args'])
        self.app.language = 'zh'
        panel.translate()
        self.assertEqual('202', panel.aim_target_id.get())
        self.assertEqual('1.25', panel.aim_tolerance.get())
        self.assertEqual(['-10.5', '3', '42'], [panel.aim_position[axis].get() for axis in ('x', 'y', 'z')])
        self.assertIn('可见目标', panel.status_labels['manual_aim'].options['text'])

    def test_invalid_aim_input_never_writes_or_claims_ownership(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel, manual_aim={'held': False, 'aligned': False})
        for value in ('', '0', '-1', '1.5', '1e3', 'True', '2147483648', True):
            panel.aim_target_id.set(value)
            self.assertFalse(panel._send_aim('aim_target'))
        panel.aim_target_id.set('202')
        for value in ('nan', 'inf', '0.049', '5.1', True):
            panel.aim_tolerance.set(value)
            self.assertFalse(panel._send_aim('aim_target'))
        panel.aim_tolerance.set('0.5')
        for axis in ('x', 'y', 'z'):
            panel.aim_position[axis].set('0')
        for value in ('', 'nan', 'inf', '100001', True):
            panel.aim_position['x'].set(value)
            self.assertFalse(panel._send_aim('aim_point'))
        for value in ('x' * 129, True):
            panel.aim_release_id.set(value)
            self.assertFalse(panel._release_aim())
        self.assertEqual([], self.commands(panel))
        self.assertFalse(panel.transport.status['manual_aim']['held'])

    def test_completed_alignment_is_not_presented_as_current_ownership_or_a_hit(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        panel.send('aim_target', target_id=202)
        command = self.commands(panel)[0]
        self.receipt(panel, command, 'completed', 'aligned', result={'held': True, 'aligned': True})
        self.status(panel, manual_aim={'held': True, 'aligned': True, 'command_id': command['id'],
            'phase': 'holding', 'target_id': 202})
        self.assertIn('Aim source held: Yes', panel.status_labels['manual_aim'].options['text'])
        self.assertIn('Holding aim', panel.status_labels['manual_aim'].options['text'])
        self.status(panel, manual_aim={'held': False, 'aligned': False, 'command_id': None, 'reason': 'released'})
        self.assertIn('Alignment observed; current ownership is shown separately', panel.status_labels['result'].options['text'])
        self.assertIn('No owned aim source', panel.status_labels['manual_aim'].options['text'])
        self.assertEqual([], panel.transport.projectile_results())
        self.assertEqual('completed', panel.transport.results[command['id']]['status'])
        self.app.language = 'zh'
        panel.translate()
        self.assertIn('当前控制权另行显示', panel.status_labels['result'].options['text'])
        self.assertIn('当前未持有瞄准源', panel.status_labels['manual_aim'].options['text'])

    def test_equipment_and_siege_buttons_use_requested_values_not_toggle_or_wire_flags(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        panel.equipment_id.set('3')
        panel.equipment_target.set('gunHealth')
        use = next(button for button in panel.action_buttons if button._control_action == 'use_equipment')
        self.assertTrue(use.options['command']())
        panel.equipment_id.set('0')
        panel.equipment_target.set('')
        panel.equipment_use_active.set(True)
        panel.equipment_active.set(False)
        self.assertTrue(use.options['command']())
        siege = next(button for button in panel.action_buttons if button._control_action == 'set_siege')
        for value in (True, False):
            panel.siege_enabled.set(value)
            self.assertTrue(siege.options['command']())
        commands = self.commands(panel)
        self.assertEqual([{'equipment_id': 3, 'target': 'gunHealth'}, {'equipment_id': 0, 'active': False},
                          {'enabled': True}, {'enabled': False}], [row['args'] for row in commands])
        self.assertTrue(all(row['timeout_seconds'] == 30. and row['expires_at'] > 0 for row in commands))
        self.app.language = 'zh'
        panel.translate()
        self.assertEqual('0', panel.equipment_id.get())
        self.assertTrue(panel.equipment_use_active.get())
        self.assertFalse(panel.equipment_active.get())
        self.assertFalse(panel.siege_enabled.get())

    def test_invalid_equipment_and_mode_inputs_never_write(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel)
        for value in ('', '-1', '65536', '3.5', '1e3', 'True', True):
            panel.equipment_id.set(value)
            self.assertFalse(panel._send_equipment())
        panel.equipment_id.set('3')
        for value in ('engine', 'loader', 'gunner3', '__import__', True):
            panel.equipment_target.set(value)
            self.assertFalse(panel._send_equipment())
        panel.equipment_target.set('')
        panel.equipment_use_active.set(True)
        panel.equipment_active.set(1)
        self.assertFalse(panel._send_equipment())
        panel.siege_enabled.set('true')
        self.assertFalse(panel._send_siege())
        self.assertEqual([], self.commands(panel))

    def test_native_readiness_pending_sequence_and_terminal_receipts_remain_distinct(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        native = {'equipment': {'available': True, 'revision': 7, 'intent_seq': 0,
                    'stock': [{'equipment_id': 3, 'kind': 'repair', 'ready': True,
                        'repair_all': False, 'uses_left': 1, 'targets': ['gunHealth']}]},
                  'siege': {'available': True, 'enabled': False, 'state': 'disabled',
                    'time_left_ms': 0, 'input_seq': 5, 'presented': False}}
        self.status(panel, native_actions=native)
        self.assertIn('Equipment ID: 3', panel.status_labels['equipment'].options['text'])
        self.assertIn('Ready: Yes', panel.status_labels['equipment'].options['text'])
        self.assertIn('gunHealth', panel.status_labels['equipment'].options['text'])
        self.assertIn('Siege enabled: No', panel.status_labels['siege'].options['text'])
        for action, args, pending_key, sequence in (
                ('use_equipment', {'equipment_id': 3, 'target': 'gunHealth'}, 'equipment', {'intent_seq': 8}),
                ('set_siege', {'enabled': True}, 'siege', {'request_seq': 6})):
            self.assertTrue(panel.send(action, **args))
            command = self.commands(panel)[-1]
            self.receipt(panel, command, 'accepted')
            native[pending_key]['pending'] = dict(id=command['id'], phase='waiting', **sequence)
            self.status(panel, native_actions=native)
            text = panel.status_labels['result'].options['text']
            self.assertIn('awaiting correlated native confirmation', text)
            self.assertNotIn('Canonical state confirmed', text)
            self.receipt(panel, command, 'completed', 'confirmed', result=dict(args, **sequence))
            text = panel.status_labels['result'].options['text']
            self.assertIn('Canonical state confirmed', text)
            self.assertIn(str(next(iter(sequence.values()))), text)
        self.app.language = 'zh'
        panel.translate()
        self.assertIn('权威状态已确认', panel.status_labels['result'].options['text'])
        self.assertIn('给养ID: 3', panel.status_labels['equipment'].options['text'])

    def test_siege_numeric_states_show_transition_names_without_altering_observed_status(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        english = ('Travel mode (0)', 'Switching to siege (1)', 'Siege mode (2)', 'Switching to travel (3)')
        chinese = ('行驶模式（0）', '正在进入攻城模式（1）', '攻城模式（2）', '正在退出攻城模式（3）')
        for state in range(4):
            self.app.language = 'en'
            self.status(panel, native_actions={'siege': {'available': True, 'enabled': state == 2,
                'state': state, 'time_left_ms': 0 if state in (0, 2) else 1000, 'input_seq': 10}})
            self.assertIn(english[state], panel.status_labels['siege'].options['text'])
            self.app.language = 'zh'
            panel.translate()
            self.assertIn(chinese[state], panel.status_labels['siege'].options['text'])
            self.assertEqual(state, panel.transport.status['native_actions']['siege']['state'])

    def test_pending_native_cleanup_is_not_labelled_as_an_aim_release(self):
        panel = self.panel()
        self.launch(panel)
        panel.open_controls()
        self.status(panel, native_actions={'siege': {'available': True, 'enabled': False,
            'state': 0, 'pending': {'id': 'siege-one', 'request_seq': None, 'phase': 'releasing'}}})
        self.assertIn('Releasing owned control', panel.status_labels['siege'].options['text'])
        self.assertNotIn('aim source', panel.status_labels['siege'].options['text'])
        self.app.language = 'zh'
        panel.translate()
        self.assertIn('正在释放持有的控制权', panel.status_labels['siege'].options['text'])


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'requires Tk display')
class TestingPanelTkLayoutTests(unittest.TestCase):
    """Exercise actual widget allocation without implying native game acceptance."""
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.app = types.SimpleNamespace(_tk=tk, _ttk=ttk, root=self.root,
            language='en', _diagnostic_entry=False, _save_settings=lambda: None)
        self.panel = testing_ui.TestingPanel(self.app, self.root, {'control': True})
        self.panel.open_controls()
        self.addCleanup(lambda: self.panel._close_controls(send_stop=False))
        self.root.update()

    def test_controls_scroll_in_fixed_window_and_both_languages_have_readable_buttons(self):
        panel, window = self.panel, self.panel.control_window
        canvas = next(widget for widget in window.winfo_children() if isinstance(widget, tk.Canvas))
        content = canvas.winfo_children()[0]
        for language in ('en', 'zh'):
            self.app.language = language
            panel.translate()
            self.root.update()
            self.assertEqual((660, 680), (window.winfo_width(), window.winfo_height()))
            self.assertGreater(content.winfo_reqheight(), canvas.winfo_height())
            for button in panel.action_buttons:
                if button._control_action not in ('aim_target', 'aim_point', 'release_aim', 'use_equipment', 'set_siege'):
                    continue
                text_width = int(button.tk.call('font', 'measure', button.cget('font'), button.cget('text')))
                self.assertGreaterEqual(button.winfo_width(), text_width + 12)
                self.assertGreaterEqual(button.winfo_height(), 20)
            canvas.yview_moveto(1)
            self.root.update()
            button = next(button for button in panel.action_buttons if button._control_action == 'set_siege')
            self.assertGreaterEqual(button.winfo_rooty(), canvas.winfo_rooty())
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                 canvas.winfo_rooty() + canvas.winfo_height())

    def test_real_entries_and_checkboxes_keep_request_values_during_translation(self):
        panel = self.panel
        panel.aim_target_id.set('202')
        panel.aim_tolerance.set('0.25')
        panel.aim_release_id.set('holder-one')
        for axis, value in zip(('x', 'y', 'z'), ('-12', '5.5', '36')):
            panel.aim_position[axis].set(value)
        panel.equipment_id.set('3')
        panel.equipment_target.set('loader1')
        panel.equipment_use_active.set(True)
        panel.equipment_active.set(False)
        panel.siege_enabled.set(False)
        for language in ('zh', 'en'):
            self.app.language = language
            panel.translate()
            self.root.update()
            self.assertEqual('202', panel.aim_target_id.get())
            self.assertEqual('0.25', panel.aim_tolerance.get())
            self.assertEqual('holder-one', panel.aim_release_id.get())
            self.assertEqual(['-12', '5.5', '36'], [panel.aim_position[axis].get() for axis in ('x', 'y', 'z')])
            self.assertEqual('loader1', panel.equipment_target.get())
            self.assertTrue(panel.equipment_use_active.get())
            self.assertFalse(panel.equipment_active.get())
            self.assertFalse(panel.siege_enabled.get())


if __name__ == '__main__':
    unittest.main()
