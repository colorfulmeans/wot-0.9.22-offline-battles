"""Input ownership, bounded script commands, and round lifecycle contracts."""
import json
import itertools
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
    def test_handover_keeps_an_admitted_burst_round_until_its_commit(self):
        from test_port_0922_battle_runtime import NativeBattleRuntime
        burst = dict(committed=0)
        owner = types.SimpleNamespace(_local_player_burst=burst,
                                      _local_fire_intent=dict(player_burst=burst))
        self.assertIs(burst, NativeBattleRuntime._cancel_local_player_burst(owner,apply_settings=True))
        self.assertIs(burst,owner._local_player_burst)
        self.assertTrue(burst['stop_after_pending'])
        owner._local_fire_intent = None
        owner._gun_state = None
        NativeBattleRuntime._cancel_local_player_burst(owner)
        self.assertIsNone(owner._local_player_burst)

    def test_suppressed_native_trigger_is_rejected_not_fake_acknowledged(self):
        from test_port_0922_battle_runtime import _LANInputSender
        self.owner._player_autocontrol = self.control
        sender = _LANInputSender(self.owner)
        self.control.active = True
        self.assertIs(False, sender.send_avatar_input(1, 'shoot', {}))
        self.control.stop()
        shots = []
        self.owner.shoot = lambda *args: shots.append(args) or True
        self.assertTrue(sender.send_avatar_input(1, 'shoot', {}))
        self.assertEqual(1, len(shots))
        self.assertIn('cancel_wait', self.bursts)

    def test_mouse_fire_and_lock_owned_only_during_fire_takeover(self):
        class Handler:
            def handleKeyEvent(self, event): return 'manual'
        handler = Handler()
        self.owner._avatar.inputHandler = handler
        self.control.input_available = lambda: True
        keys = types.SimpleNamespace(KEY_GRAVE=41, KEY_LEFTMOUSE=256, KEY_RIGHTMOUSE=257)
        with mock.patch.dict(sys.modules, {'Keys':keys,
                'game':types.SimpleNamespace(convertKeyEvent=lambda event:event)}):
            self.control.bind_input()
            self.control.active = True
            for key in (256,257):
                for down in (True,False):
                    self.assertIs(True,handler.handleKeyEvent((down,key,0,False)))
            self.control.features.remove('fire')
            self.assertEqual('manual',handler.handleKeyEvent((True,256,0,False)))
            self.control.features.add('fire')
            self.control.active = False
            self.assertEqual('manual',handler.handleKeyEvent((True,257,0,False)))
            self.control.close()

    def test_friendly_hull_blocks_fire_even_when_static_world_ray_is_clear(self):
        self.owner.client.team = 1
        self.owner._mutable_shot_ray = lambda: ((0,1,0),(0,0,1))
        self.owner._collision_shape = lambda td:(1,2,0,2)
        self.owner._tactical_ray_clear = lambda *args:True
        blocker = (dict(kind='bot',network_id=3),object(),(0,0,5))
        self.owner._bot_lane_rows = lambda source,accept: (blocker,)
        self.owner._bot_lane_row_contact = lambda rows,path: blocker
        target = types.SimpleNamespace(id=42,position=(0,0,20),typeDescriptor=object())
        self.assertFalse(self.control.firing_lane(target))
        self.owner._bot_lane_row_contact = lambda rows,path:None
        self.assertTrue(self.control.firing_lane(target))

    def test_manual_selected_round_is_preserved_then_normal_policy_takes_over(self):
        from gui.mods.offline_lan_0922.ammo_policy import ShotPolicy
        profile = dict(shells=[dict(index=0,kind='ARMOR_PIERCING'),
                              dict(index=1,kind='HIGH_EXPLOSIVE')])
        self.control.ammo_policy = ShotPolicy(profile)
        self.control.ammo_policy.phase = self.control.ammo_policy.desired = 1
        self.control.active = self.control.preserve_first = True
        self.owner._gun_state = types.SimpleNamespace(ammo=[20,5],shot_index=1,pending_index=None)
        self.owner.local_pose = lambda:((0,0,0),0)
        self.control.select_ammo() # Must not require or call the switching interface.
        self.control.shot_committed(dict(projectile_id='p1',shot_seq=1,shell_index=1),{})
        self.assertFalse(self.control.preserve_first)
        self.assertEqual(0,self.control.ammo_policy.desired)
        self.control.shot_hit(dict(projectile_id='p1',damage=0,shot_result=1))
        self.control.shot_terminal(dict(projectile_id='p1'))
        self.control.shot_terminal(dict(projectile_id='p1'))
        self.assertEqual({},self.control.shots)

    def test_each_feature_combination_claims_only_its_input_channels(self):
        for flags in itertools.product((False, True), repeat=3):
            with self.subTest(flags=flags):
                self.setUp()
                self.control.features = {name for name, enabled in zip(
                    ('drive', 'fire', 'consumables'), flags) if enabled}
                self.control.active = True
                self.control._contacts = lambda unused: ([], [], {42: types.SimpleNamespace(id=42, position=(2,0,2))})
                order = dict(throttle=-1., turn=-.5, brake=False, target_id=42, fire_allowed=True)
                self.control.navigation = types.SimpleNamespace(decide=lambda *args, **kw: order,
                    receipt={})
                entity = types.SimpleNamespace(isAlive=lambda: True, health=100,
                    typeDescriptor=types.SimpleNamespace(maxHealth=100))
                self.owner._server_entity = lambda unused: entity
                self.owner.local_pose = lambda: ((0, 0, 0), 0)
                self.owner._local_speed = 0
                self.owner._collision_shape = lambda unused: (1, 2, 0, 1)
                locks, consumables, shots = [], [], []
                self.control.lock_target = locks.append
                self.control._consumables = consumables.append
                self.control.aimed_at = lambda unused: True
                self.control.firing_lane = lambda unused: True
                self.control.select_ammo = lambda: None
                self.control.engagement = dict(id=42, at=0, fired=False)
                self.owner._gun_state = types.SimpleNamespace(base_dispersion=.1, can_fire=lambda live: True)
                self.owner._native_dispersion_angle = lambda: .1
                self.owner._local_stat_factor = lambda *args: 1
                self.owner.shoot = lambda *args: shots.append(args) or True
                self.control.update(.1, 1)
                self.assertEqual(-1. if flags[0] else 1, self.owner._sender.forward)
                self.assertEqual(bool(flags[1]), bool(locks))
                self.assertEqual(bool(flags[1]), bool(shots))
                self.assertEqual(bool(flags[2]), bool(consumables))

    def test_avatar_lock_receives_vehicle_and_stop_receives_none(self):
        target = types.SimpleNamespace(id=42)
        calls = []
        def native_lock(value):
            self.assertTrue(value is None or value is target)
            calls.append(value)
            self.owner._avatar._PlayerAvatar__autoAimVehID = value.id if value else 0
        self.owner._avatar.autoAim = native_lock
        self.control.lock_target(target)
        self.control.lock_target(target)
        self.assertEqual([target], calls)
        self.control.stop()
        self.assertEqual([target, None], calls)

    def test_blocked_direction_receipts_are_not_truthy_clear_corridors(self):
        from test_port_0922_bot_runtime import _load
        self.owner._local_speed = 0
        self.owner._bots = types.SimpleNamespace(_probe_is_clear=_load().BotRuntime._probe_is_clear)
        for receipt, expected in ((dict(clear=False), False),
                (dict(clear=True, collision=True), False),
                (dict(clear=True, water=True), False),
                (dict(clear=True, slope=0), True)):
            self.owner._direction_probe = lambda *args: receipt
            self.assertEqual(expected, self.control.direction_clear((0, 0, 0), 0, None, (1, 2)))

    def setUp(self):
        self.sent, self.bursts, self.messages, self.records = [], [], [], []
        sender = types.SimpleNamespace(forward=1, turn=1, handbrake=True,
            aim_yaw=.2, gun_pitch=.1, send_current=lambda: self.sent.append(True))
        self.owner = types.SimpleNamespace(state='running', _battle_live=True,
            client=types.SimpleNamespace(player_id=1), _start_message={'round_id': 1},
            _battle_result=None, _worker_mode=False, _replay_mode=False,
            _server=types.SimpleNamespace(vehicle_id=1), _sender=sender,
            _avatar=types.SimpleNamespace(autoAim=lambda value: None),
            _local_fire_intent=None, _defer_cancel_native_shot_wait=lambda: self.bursts.append('cancel_wait'),
            _local_physics=dict(rotSpd=.5),
            _cancel_local_player_burst=lambda **kw: self.bursts.append(kw),
            shoot=lambda *args: True)
        self.control = control.PlayerControl(self.owner, ['drive', 'fire'], self.messages.append)
        self.control.record = lambda stage, **kw: self.records.append((stage, kw))

    def test_native_vehicle_without_shadow_fields_uses_canonical_consumable_state(self):
        self.owner._clock = lambda: 10
        calls = []
        self.owner._activate_equipment = calls.append
        self.owner._critical_extra_index = lambda td, name: 3
        self.owner._equipment_state = [types.SimpleNamespace(
            contract=dict(id=101, kind='repairkit'), ready=lambda now: True)]
        self.owner._records = {'player:1': {'critical_state': {
            'devices': [{'name': 'engineHealth', 'state': 'destroyed'}],
            'destroyed': ['engineHealth'], 'crew_ko': [], 'fire': False}}}
        entity = types.SimpleNamespace(typeDescriptor=object())
        self.control._consumables(entity)
        self.control._consumables(entity)
        self.assertEqual([101 | (3 << 16)], calls)
        self.owner._records['player:1']['critical_state'] = {}
        self.control._consumables(entity)

    def test_timed_drive_replaces_automatic_writer_and_stop_clears_pending_shots(self):
        self.control.active = True
        self.assertTrue(self.control.command(dict(action='drive', forward=1, seconds=1), 20))
        self.assertFalse(self.control.active)
        self.assertEqual((21, 1, 0), self.control.override)
        self.control.stop()
        self.assertIsNone(self.control.override)
        self.assertEqual((0, 0, False), (self.owner._sender.forward,
            self.owner._sender.turn, self.owner._sender.handbrake))
        self.assertEqual(4, len(self.bursts))
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
        with mock.patch.dict(sys.modules, {'Keys': types.SimpleNamespace(KEY_GRAVE=41,KEY_LEFTMOUSE=256,KEY_RIGHTMOUSE=257),
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

    def test_countdown_press_does_not_latch_or_block_live_toggle(self):
        control._current = self.control
        self.addCleanup(lambda: setattr(control, '_current', None))
        self.control.input_available = lambda: True
        toggles = []
        self.control.toggle = lambda: toggles.append(True)
        with mock.patch.dict(sys.modules, {'Keys': types.SimpleNamespace(KEY_GRAVE=41)}):
            self.owner._battle_live = False
            self.assertFalse(control.handle_key(True, 41))
            self.assertFalse(self.control.key_down)
            self.owner._battle_live = True
            self.assertTrue(control.handle_key(True, 41))
            self.assertEqual([True], toggles)

    def test_native_input_availability_uses_properties_not_absent_method(self):
        handler = types.SimpleNamespace(isStarted=True, isDetached=False)
        self.owner._avatar.inputHandler = handler
        messenger = types.SimpleNamespace(MessengerEntry=types.SimpleNamespace(
            g_instance=types.SimpleNamespace(gui=types.SimpleNamespace(isFocused=lambda: False))))
        with mock.patch.dict(sys.modules, {'messenger': messenger}):
            self.assertTrue(self.control.input_available())
            handler.isDetached = True
            self.assertFalse(self.control.input_available())

    def test_player_contacts_exclude_allies_and_hidden_enemies_without_bot_agents(self):
        td = types.SimpleNamespace(maxHealth=100)
        ally = types.SimpleNamespace(id=11, position=(1, 0, 2), health=70,
            typeDescriptor=td, matrix=types.SimpleNamespace(yaw=0), isAlive=lambda: True)
        enemy = types.SimpleNamespace(id=12, position=(3, 0, 4), health=100,
            typeDescriptor=td, matrix=types.SimpleNamespace(yaw=0), isAlive=lambda: True,
            isStarted=True)
        self.owner.client.team = 1
        self.owner._collision_shape = lambda unused:(1,2,0,2)
        self.owner._records = {
            'ally': dict(ready=True, engine_id=11, state=dict(team=1)),
            'enemy': dict(ready=True, engine_id=12, state=dict(team=2), spot_visible=False)}
        self.owner._server_entity = {11: ally, 12: enemy}.get
        contacts, neighbours, records = self.control._contacts(types.SimpleNamespace(id=1))
        self.assertEqual([], contacts)
        self.assertEqual({}, records)
        self.assertEqual(2, len(neighbours))
        self.assertFalse(hasattr(self.control, 'adapter'))

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

