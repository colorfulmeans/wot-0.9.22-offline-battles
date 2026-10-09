"""Lifecycle coverage for an opt-in real #1513 connection experiment."""

import contextlib
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'res' / 'scripts' / 'client'))
from gui.mods.offline_lan_0922 import native_protocol_probe as probe_module


class NativeProtocolProbeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        self.now = [0.0]
        self.events = []
        self.pending = {}
        self.next_callback = 0
        self.login_ready = False
        self.lobby_ready = True
        self.native_disconnect_count = 0
        self.requested_disconnects = 0
        self.disconnect_request_pending = False
        self.forced_disconnect_requests = []
        self.native_progress = None
        self.native_data = None
        self.native_login_status = 'LOGGED_ON'
        self.native_disconnect_delivery = True
        self.manager_progress = []
        self.account_context = {'selected_vehicle': {'shells': [7, 8]},
                                'account_state': object()}
        self.restored_context = None

        class Avatar(object):
            def handleKey(self, *args, **kwargs):
                return ('key', args, kwargs)

            def moveVehicle(self, *args, **kwargs):
                return ('move', args, kwargs)

            def shoot(self, *args, **kwargs):
                return ('shoot', args, kwargs)

            def leaveArena(self, *args, **kwargs):
                return ('leave', args, kwargs)

        self.avatar_type = Avatar
        self.original_methods = dict(Avatar.__dict__)
        self.player = SimpleNamespace(id=1, spaceID=1, isOffline=True)
        self.world = SimpleNamespace(
            callback=self.callback, cancelCallback=self.cancel_callback,
            player=lambda: self.player, entities={1: self.player},
            connect=self.native_connect, disconnect=self.native_disconnect)
        self.manager = SimpleNamespace()
        self.manager._ConnectionManager__serverResponseHandler = self.progress
        self.runtime = SimpleNamespace(
            bigworld=self.world, connection_manager=self.manager,
            avatar_module=SimpleNamespace(PlayerAvatar=Avatar),
            login_status=SimpleNamespace(LOGGED_ON='LOGGED_ON', NOT_SET='NOT_SET'))
        self.compatibility = SimpleNamespace(
            _runtime=self.runtime, _fake_connected=True,
            _battle_active=False, installed=True,
            is_ready=lambda: self.compatibility._fake_connected,
            seed_account_context=lambda: dict(self.account_context),
            disconnect=self.offline_disconnect,
            _rollback_install=self.rollback,
            connect=self.offline_connect)
        self.context = {
            'account_context': self.account_context,
            'suspend_session': lambda: self.events.append('suspend_session'),
            'restore_session': lambda: self.events.append('restore_session'),
            'login_ready': lambda: self.login_ready,
            'lobby_ready': lambda: self.lobby_ready,
        }
        self.manifest = dict(endpoint='127.0.0.1:20013', key_path='/probe.pem',
                             report_path=str(Path(self.temp.name) / 'probe.jsonl'),
                             timeout=1.0)
        self.probe = probe_module.NativeProtocolProbe(
            self.compatibility, self.context, self.manifest,
            clock=lambda: self.now[0], data_factory=lambda unused: object())
        disconnect_patch = mock.patch.dict(sys.modules, {
            'gui.app_loader': SimpleNamespace(g_appLoader=SimpleNamespace(
                goToLoginByRQ=self.request_disconnect))})
        disconnect_patch.start()
        self.addCleanup(disconnect_patch.stop)
        self.addCleanup(self.probe.stop, 'test_cleanup', False)

    def callback(self, delay, function):
        self.next_callback += 1
        self.pending[self.next_callback] = (delay, function)
        return self.next_callback

    def cancel_callback(self, callback_id):
        self.pending.pop(callback_id, None)

    def tick(self):
        callback_id = min(self.pending)
        unused_delay, function = self.pending.pop(callback_id)
        function()

    def drain(self, limit=20):
        for unused in range(limit):
            if not self.pending:
                return
            self.tick()
        self.fail('callbacks did not settle')

    def offline_disconnect(self):
        if not self.compatibility._fake_connected:
            return
        self.events.append('offline_disconnect')
        self.compatibility._fake_connected = False
        self.player = None
        self.world.entities.clear()
        self.login_ready = True
        self.lobby_ready = False

    def request_disconnect(self, forced=False):
        self.requested_disconnects += 1
        self.forced_disconnect_requests.append(forced)
        self.events.append('disconnect_request')
        if not self.disconnect_request_pending or forced:
            self.disconnect_request_pending = True
            if self.compatibility.installed:
                self.offline_disconnect()
            else:
                self.native_disconnect()
        self.login_ready = True

    def rollback(self):
        self.events.append('rollback')
        self.compatibility.installed = False

    def native_connect(self, endpoint, data, progress):
        self.assertFalse(self.compatibility.installed)
        self.assertIsNone(self.player)
        self.assertEqual(endpoint, self.manifest['endpoint'])
        self.events.append('native_connect')
        self.native_data = data
        self.native_progress = progress
        self.login_ready = False
        progress(1, self.native_login_status, '{}')

    def native_disconnect(self):
        self.native_disconnect_count += 1
        self.events.append('native_disconnect')
        if self.native_disconnect_delivery:
            self.deliver_disconnect()

    def deliver_disconnect(self):
        self.player = None
        self.world.entities.clear()
        self.native_progress(6, 'NOT_SET', '{}')

    def progress(self, stage, status, response):
        self.manager_progress.append((stage, status, response))
        if stage == 6 or (stage == 1 and status != 'LOGGED_ON'):
            self.login_ready = True

    def offline_connect(self, show_lobby, account_context):
        self.assertTrue(show_lobby)
        self.events.append('offline_connect')
        self.compatibility.installed = True
        self.compatibility._fake_connected = True
        self.restored_context = account_context
        self.player = SimpleNamespace(id=2, spaceID=2, isOffline=True)
        self.world.entities[2] = self.player
        self.lobby_ready = True

    def start_native(self):
        self.assertTrue(self.probe.start())
        self.assertIsNone(self.native_progress)
        self.tick()
        self.assertIsNone(self.native_progress)
        self.tick()
        self.assertEqual('connected', self.probe.state)

    def test_no_environment_means_no_runtime_access(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(probe_module.maybe_start(None, None))

    def test_manifest_rejects_relative_paths_and_nonfinite_timeouts(self):
        with self.assertRaises(ValueError):
            probe_module._manifest('relative.json')
        key = Path(self.temp.name) / 'key.pem'
        key.write_text('experiment public key')
        manifest_path = Path(self.temp.name) / 'manifest.json'
        for timeout in (float('nan'), float('inf'), 0, 301):
            manifest_path.write_text(json.dumps(dict(
                self.manifest, key_path=str(key), timeout=timeout)))
            with self.assertRaises(ValueError):
                probe_module._manifest(str(manifest_path))

    def test_manifest_accepts_explicit_resource_key_without_a_file_fallback(self):
        manifest_path = Path(self.temp.name) / 'manifest.json'
        manifest_path.write_text(json.dumps(dict(
            self.manifest, key_path='native_protocol_probe.pubkey')))
        self.assertEqual('native_protocol_probe.pubkey',
                         probe_module._manifest(str(manifest_path))['key_path'])
        for path in ('', ' ', '../key', 'a/../key', 'a\\..\\key', './key', 'C:key'):
            manifest_path.write_text(json.dumps(dict(self.manifest, key_path=path)))
            with self.assertRaises(ValueError):
                probe_module._manifest(str(manifest_path))

    def test_synthetic_credentials_do_not_reuse_account_data(self):
        connection_module = SimpleNamespace(ConnectionData=SimpleNamespace)
        with mock.patch.dict(sys.modules, {
                'connection_mgr': connection_module,
                'helpers': SimpleNamespace(getClientLanguage=lambda: 'zh_cn')}):
            data = probe_module._connection_data(self.manifest)
        self.assertEqual('offline_probe', data.username)
        self.assertEqual('offline_probe', data.password)
        self.assertEqual('/probe.pem', data.publicKeyPath)
        self.assertEqual({'lang_id': 'zh_cn'}, json.loads(data.clientContext))

    def test_request_disconnect_uses_forced_stock_request_not_direct_disconnect(self):
        app_loader = SimpleNamespace(goToLoginByRQ=mock.Mock())
        with mock.patch.dict(sys.modules, {
                'gui.app_loader': SimpleNamespace(g_appLoader=app_loader)}):
            probe_module._request_disconnect()
        app_loader.goToLoginByRQ.assert_called_once_with(forced=True)

    def test_vehicle_state_uses_selected_native_descriptor_and_arena(self):
        descriptor = SimpleNamespace(
            type=SimpleNamespace(name='ussr:R11_MS-1'), maxHealth=237,
            gun=SimpleNamespace(pitchLimits={'absolute': (-0.2, 0.4)}),
            turret=SimpleNamespace(circularVisionRadius=270),
            makeCompactDescr=lambda: b'\x00\xffmounted')
        outfit_reader = mock.Mock(return_value=SimpleNamespace(
            strCompactDescr=None,
            pack=lambda: SimpleNamespace(makeCompDescr=lambda: b'\x01\xfeoutfit')))
        item = SimpleNamespace(descriptor=descriptor, invID=37, intCD=257,
                               getOutfit=outfit_reader)
        arena = SimpleNamespace(geometryName='01_karelia', gameplayName='ctf',
                                id=1, vehicleCamouflageKind='summer')
        angles = mock.Mock(return_value=191)
        modules = {
            'ArenaType': SimpleNamespace(g_cache={1: arena}),
            'constants': SimpleNamespace(
                VEHICLE_PHYSICS_MODE=SimpleNamespace(STANDARD=3),
                VEHICLE_SIEGE_STATE=SimpleNamespace(DISABLED=7)),
            'CurrentVehicle': SimpleNamespace(
                g_currentVehicle=SimpleNamespace(item=item)),
            'gun_rotation_shared': SimpleNamespace(encodeGunAngles=angles),
            'items': SimpleNamespace(vehicles=SimpleNamespace(VehicleDescr=object)),
            'items.components.c11n_constants': SimpleNamespace(
                SeasonType=SimpleNamespace(fromArenaKind=lambda kind: 2)),
        }
        with mock.patch.dict(sys.modules, modules):
            result = probe_module._vehicle_state(self.world, self.manifest)
        self.assertEqual('ussr:R11_MS-1', result['vehicle'])
        self.assertEqual(1, result['arena_type_id'])
        self.assertEqual(37, result['vehicle_identity']['inventory_id'])
        self.assertEqual(237, result['properties']['health'])
        self.assertEqual(191, result['properties']['gunAnglesPacked'])
        self.assertEqual(3, result['properties']['physicsMode'])
        self.assertEqual(7, result['properties']['siegeState'])
        public = result['properties']['publicInfo']
        self.assertEqual(b'\x00\xffmounted', base64.b64decode(public['compDescr']['base64']))
        self.assertEqual(b'\x01\xfeoutfit', base64.b64decode(public['outfit']['base64']))
        self.assertEqual('offline_probe', public['name'])
        outfit_reader.assert_called_once_with(2)
        angles.assert_called_once_with(0, 0, (-0.2, 0.4))

    def test_vehicle_export_precedes_account_retirement(self):
        self.manifest['vehicle_state_path'] = str(Path(self.temp.name) / 'vehicle.json')
        state = dict(vehicle='ussr:R11_MS-1', arena_type_id=1, properties={})

        def read(world, manifest):
            self.assertEqual([], self.events)
            self.assertTrue(self.compatibility._fake_connected)
            return state

        with mock.patch.object(probe_module, '_vehicle_state', side_effect=read):
            self.assertTrue(self.probe.start())
        self.assertEqual(state, json.loads(
            Path(self.manifest['vehicle_state_path']).read_text()))

    def test_vehicle_export_failure_leaves_existing_garage_connected(self):
        self.manifest['vehicle_state_path'] = str(Path(self.temp.name) / 'vehicle.json')
        with mock.patch.object(probe_module, '_vehicle_state',
                               side_effect=ValueError('missing real descriptor')):
            self.assertFalse(self.probe.start())
        self.assertEqual([], self.events)
        self.assertTrue(self.compatibility._fake_connected)
        self.assertEqual('export_failed', self.probe.state)

    def test_handoff_and_recovery_preserve_garage_after_native_boundary(self):
        self.start_native()
        self.assertEqual(['suspend_session', 'disconnect_request',
                          'offline_disconnect', 'rollback', 'native_connect'],
                         self.events)
        self.account_context['selected_vehicle']['shells'][0] = 99
        self.probe.stop('test_complete')
        self.assertNotIn('offline_connect', self.events)
        self.tick()
        self.assertNotIn('offline_connect', self.events)
        self.tick()
        self.assertEqual(['restore_session', 'offline_connect'], self.events[-2:])
        self.drain()
        self.assertEqual('finished', self.probe.state)
        self.assertEqual([7, 8], self.restored_context['selected_vehicle']['shells'])
        self.assertIs(self.account_context['account_state'],
                      self.restored_context['account_state'])
        rows = [json.loads(line) for line in
                Path(self.manifest['report_path']).read_text().splitlines()]
        events = [row['event'] for row in rows]
        self.assertIn('lobby_restored', events)
        self.assertLess(events.index('restore_begin'),
                        events.index('restore_connect_returned'))
        self.assertLess(events.index('restore_connect_returned'),
                        events.index('lobby_restore_poll'))

    def test_native_connect_waits_for_login_state_to_finish_old_space_cleanup(self):
        self.assertTrue(self.probe.start())
        self.login_ready = False
        self.tick()
        self.assertIsNone(self.native_progress)
        self.login_ready = True
        self.tick()
        self.assertIsNone(self.native_progress)
        self.tick()
        self.assertEqual('connected', self.probe.state)

    def test_observers_count_current_player_and_preserve_arguments_and_return(self):
        self.start_native()
        self.player = self.avatar_type()
        other = self.avatar_type()
        self.assertEqual(('move', (7,), {'isKeyDown': True}),
                         self.player.moveVehicle(7, isKeyDown=True))
        other.moveVehicle(3, False)
        self.assertEqual(('leave', (), {}), self.player.leaveArena())
        self.assertEqual(1, self.probe._inputs['moveVehicle'])
        self.assertEqual(1, self.probe._inputs['leaveArena'])
        self.assertEqual('connected', self.probe.state)
        self.probe.stop('test_complete')
        for name in self.probe._inputs:
            self.assertIs(self.original_methods[name], self.avatar_type.__dict__[name])

    def test_asynchronous_disconnect_must_arrive_before_recovery(self):
        self.start_native()
        self.native_disconnect_delivery = False
        self.probe.stop('test_complete')
        self.login_ready = True
        self.tick()
        self.assertNotIn('offline_connect', self.events)
        self.assertEqual([(1, 'LOGGED_ON', '{}')], self.manager_progress)
        self.deliver_disconnect()
        self.drain()
        self.assertEqual('finished', self.probe.state)

    def test_missing_disconnect_is_reported_without_synthetic_success(self):
        self.start_native()
        self.native_disconnect_delivery = False
        self.probe.stop('test_complete')
        self.now[0] = 31.0
        self.tick()
        self.assertEqual('recovery_failed', self.probe.state)
        self.assertEqual([(1, 'LOGGED_ON', '{}')], self.manager_progress)
        self.assertNotIn('offline_connect', self.events)

    def test_real_stage_one_key_rejection_restores_without_a_stage_six_event(self):
        self.native_login_status = 'PUBLIC_KEY_LOOKUP_FAILED'
        self.native_disconnect_delivery = False
        self.assertTrue(self.probe.start())
        self.drain()
        self.assertEqual('finished', self.probe.state)
        self.assertEqual([(1, 'PUBLIC_KEY_LOOKUP_FAILED', '{}')],
                         self.manager_progress)
        self.assertIn('offline_connect', self.events)
        self.assertIn('PUBLIC_KEY_LOOKUP_FAILED', self.output.getvalue())
        self.assertEqual(1, self.requested_disconnects)
        self.assertEqual(0, self.native_disconnect_count)

    def test_unsolicited_native_disconnect_preserves_stock_event_reason(self):
        self.start_native()
        self.deliver_disconnect()
        self.drain()
        self.assertEqual('finished', self.probe.state)
        self.assertEqual(1, self.requested_disconnects)
        self.assertEqual(0, self.native_disconnect_count)
        self.assertEqual((6, 'NOT_SET', '{}'), self.manager_progress[-1])

    def test_duplicate_stop_and_late_native_progress_cannot_retire_new_account(self):
        self.start_native()
        self.probe.stop('test_complete')
        self.probe.stop('duplicate')
        self.drain()
        self.native_progress(6, 'NOT_SET', '{}')
        self.assertEqual(1, self.native_disconnect_count)
        self.assertEqual(2, len(self.manager_progress))
        self.assertEqual(2, self.player.id)

    def test_cancelled_connect_callback_cannot_start_after_shutdown(self):
        self.assertTrue(self.probe.start())
        late_callback = next(iter(self.pending.values()))[1]
        self.probe.stop('shutdown', restore=False)
        late_callback()
        self.assertNotIn('native_connect', self.events)
        self.assertNotIn('offline_connect', self.events)

    def test_timeout_returns_to_lobby(self):
        self.start_native()
        self.now[0] = 1.0
        self.tick()
        self.drain()
        self.assertEqual('finished', self.probe.state)
        self.assertIn('"reason": "timeout"', self.output.getvalue())
        self.assertEqual(2, self.requested_disconnects)
        self.assertEqual(1, self.native_disconnect_count)

    def test_partial_avatar_timeout_forces_disconnect_with_prior_request_pending(self):
        self.start_native()
        self.assertTrue(self.disconnect_request_pending)
        self.player = SimpleNamespace(id=100, spaceID=1, playerVehicleID=0)
        self.login_ready = True
        self.now[0] = 1.0
        self.tick()
        self.drain()
        self.assertEqual('finished', self.probe.state)
        self.assertEqual([True, True], self.forced_disconnect_requests)
        self.assertEqual(1, self.native_disconnect_count)
        self.assertEqual((6, 'NOT_SET', '{}'), self.manager_progress[-1])

    def test_stage_two_logged_on_is_forwarded_without_ending_connection(self):
        self.start_native()
        self.native_progress(2, 'LOGGED_ON', '{}')
        self.assertEqual('connected', self.probe.state)
        self.assertEqual((2, 'LOGGED_ON', '{}'), self.manager_progress[-1])
        self.assertEqual(0, self.native_disconnect_count)

    def test_snapshot_records_native_avatar_progress_without_promoting_it(self):
        self.start_native()
        self.player = self.avatar_type()
        self.player.id = 100
        self.player.spaceID = 7
        self.player.playerVehicleID = 101
        self.player._PlayerAvatar__initProgress = 3
        self.player.inputHandler = object()
        vehicle = SimpleNamespace(spaceID=7, position=(1.0, 2.0, 3.0), filter=object())
        self.world.entities.update({100: self.player, 101: vehicle})
        state = self.probe._snapshot()
        self.assertEqual(3, state['avatar_init_bits'])
        self.assertEqual('Avatar', state['player_type'])
        self.assertEqual([7], state['spaces'])
        self.assertEqual([1.0, 2.0, 3.0], state['own_vehicle_position'])
        self.assertFalse(state['offline_overlay'])

    def test_snapshot_distinguishes_missing_cell_property_from_zero_vehicle(self):
        lookup_ids = []

        class NativeEntities(dict):
            def get(self, entity_id):
                if not isinstance(entity_id, int):
                    raise TypeError('entity lookup requires an integer ID')
                lookup_ids.append(entity_id)
                return super().get(entity_id)

        self.start_native()
        self.player = self.avatar_type()
        self.player.id = 100
        self.player.spaceID = 0
        self.world.entities = NativeEntities()
        self.assertIsNone(self.probe._snapshot()['own_vehicle_id'])
        self.assertFalse(hasattr(self.player, 'playerVehicleID'))
        self.assertEqual([], lookup_ids)
        self.player.playerVehicleID = 0
        self.assertEqual(0, self.probe._snapshot()['own_vehicle_id'])
        self.assertEqual([0], lookup_ids)


if __name__ == '__main__':
    unittest.main()
