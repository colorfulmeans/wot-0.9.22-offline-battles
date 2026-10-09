"""Opt-in #1513 native connection experiment, entered from a ready Hangar."""

import base64
import copy
import json
import math
import os
import re
import sys
import time


ENVIRONMENT = 'OFFLINE_LAN_0922_NATIVE_PROTOCOL_PROBE'
_probe = None
_attempted = False
try:
    _string_types = (basestring,)
except NameError:
    _string_types = (str,)


def _manifest(path):
    if not os.path.isabs(path):
        raise ValueError('native probe manifest path must be absolute')
    with open(path, 'rb') as source:
        data = json.load(source)
    endpoint = data.get('endpoint', '')
    if not re.match(r'^[A-Za-z0-9.-]+:[0-9]+$', endpoint):
        raise ValueError('native probe endpoint must be host:port')
    if not 1 <= int(endpoint.rsplit(':', 1)[1]) <= 65535:
        raise ValueError('native probe port is outside 1..65535')
    key_path = data.get('key_path')
    if (not isinstance(key_path, _string_types) or not key_path or
            key_path != key_path.strip()):
        raise ValueError('native probe public key path must not be empty')
    if os.path.isabs(key_path):
        if not os.path.isfile(key_path):
            raise ValueError('native probe public key does not exist')
    elif (':' in key_path or
          any(part in ('', '.', '..') for part in re.split(r'[/\\]', key_path))):
        raise ValueError('native probe public key resource path must not traverse')
    if not os.path.isabs(data.get('report_path', '')):
        raise ValueError('native probe report_path must be absolute')
    timeout = float(data.get('timeout', 15.0))
    if math.isnan(timeout) or math.isinf(timeout) or not 1 <= timeout <= 300:
        raise ValueError('native probe timeout must be 1..300 seconds')
    result = dict(endpoint=endpoint, key_path=data['key_path'],
                  report_path=data['report_path'], timeout=timeout)
    if 'vehicle_state_path' in data:
        if not os.path.isabs(data['vehicle_state_path']):
            raise ValueError('native probe vehicle_state_path must be absolute')
        result['vehicle_state_path'] = data['vehicle_state_path']
        result['map'] = data.get('map', '01_karelia')
    return result


def _connection_data(manifest):
    from connection_mgr import ConnectionData
    from helpers import getClientLanguage
    data = ConnectionData()
    data.username = 'offline_probe'
    data.password = 'offline_probe'
    data.inactivityTimeout = manifest['timeout']
    data.publicKeyPath = manifest['key_path']
    data.clientContext = json.dumps({'lang_id': getClientLanguage()})
    return data


def _request_disconnect():
    from gui.app_loader import g_appLoader
    # #1513 sets REQUEST before disconnecting; a direct BigWorld.disconnect
    # is otherwise reported as an unexpected loss and opens a modal dialog.
    # A partial Avatar can remain in LoginState with the prior REQUEST intact.
    g_appLoader.goToLoginByRQ(forced=True)


def _vehicle_state(world, manifest):
    import ArenaType
    import constants
    from CurrentVehicle import g_currentVehicle
    from gun_rotation_shared import encodeGunAngles
    from items import vehicles
    from items.components.c11n_constants import SeasonType
    from gui.mods.offline_lan_0922.entities.bigworld_binding import \
        BigWorldVehicleBinding

    map_name = manifest.get('map', '01_karelia')
    arenas = [arena for arena in ArenaType.g_cache.values()
              if (arena.geometryName == map_name and
                  arena.gameplayName == 'ctf')]
    if len(arenas) != 1:
        raise ValueError('native probe map has no unique standard arena')
    arena = arenas[0]
    item = g_currentVehicle.item
    if item is None:
        raise ValueError('native probe selected garage vehicle is unavailable')
    descriptor = item.descriptor
    season = SeasonType.fromArenaKind(arena.vehicleCamouflageKind)
    outfit = item.getOutfit(season)
    if outfit is None:
        raise ValueError('native probe selected vehicle outfit is unavailable')
    # #1513 creates a default Outfit with strCompactDescr=None. Its stock
    # copy() serializes the current containers through pack().makeCompDescr().
    outfit_bytes = outfit.pack().makeCompDescr()
    binding = BigWorldVehicleBinding(
        world, None, constants, vehicles.VehicleDescr, encodeGunAngles,
        outfit_provider=lambda unused_descriptor: outfit_bytes)
    properties = binding._properties_from_descriptor(
        descriptor, 1, 'offline_probe')
    for name in ('compDescr', 'outfit'):
        value = properties['publicInfo'][name]
        if not isinstance(value, bytes):
            raise ValueError('native probe %s must contain native bytes' % name)
        properties['publicInfo'][name] = {
            'base64': base64.b64encode(value).decode('ascii')}
    return {
        'client_build': 'wot-0.9.22.0.1-cn-1513',
        'vehicle': descriptor.type.name,
        'arena_type_id': int(arena.id),
        'map': map_name,
        'vehicle_identity': {'inventory_id': int(item.invID),
                             'type_compact_descr': int(item.intCD)},
        'properties': properties,
    }


class NativeProtocolProbe(object):
    def __init__(self, compatibility, context, manifest,
                 clock=None, data_factory=None):
        self.compatibility = compatibility
        self.context = context
        self.manifest = manifest
        self.runtime = compatibility._runtime
        self.world = self.runtime.bigworld
        self.manager = self.runtime.connection_manager
        self.clock = clock or time.time
        self.data_factory = data_factory or _connection_data
        self.state = 'new'
        self._callbacks = set()
        self._token = object()
        self._native_started = False
        self._connection_token = None
        self._disconnect_notified = False
        self._connection_rejected = False
        self._login_seen = False
        self._observers = []
        self._inputs = dict(handleKey=0, moveVehicle=0, shoot=0, leaveArena=0)
        self._account_context = None
        self._report = None
        self._start_time = self.clock()
        self._next_recovery_record = 0.0

    def _record(self, event, **values):
        record = dict(event=event, elapsed=round(self.clock() -
                                               self._start_time, 3),
                      state=self.state)
        record.update(values)
        line = json.dumps(record, sort_keys=True)
        if self._report is not None:
            self._report.write((line + '\n').encode('ascii'))
            self._report.flush()
        sys.stdout.write('[Offline LAN 0.9.22] NATIVE_PROTOCOL %s\n' % line)

    def _schedule(self, delay, function):
        token = self._token
        holder = []

        def deliver():
            if holder:
                self._callbacks.discard(holder[0])
            if token is not self._token:
                return
            try:
                function()
            except Exception as error:
                self._record('callback_error', error=str(error))
                if self.state in ('restoring', 'disconnecting'):
                    self._finish('recovery_failed')
                else:
                    self.stop('callback_error')

        callback_id = self.world.callback(delay, deliver)
        holder.append(callback_id)
        self._callbacks.add(callback_id)

    def _cancel_callbacks(self):
        self._token = object()
        callbacks = tuple(self._callbacks)
        self._callbacks.clear()
        for callback_id in callbacks:
            try:
                self.world.cancelCallback(callback_id)
            except Exception:
                pass

    def start(self):
        if self.state != 'new' or not self.compatibility.is_ready():
            return False
        for name in ('suspend_session', 'restore_session', 'login_ready',
                     'lobby_ready'):
            if not callable(self.context.get(name)):
                raise ValueError('native probe requires %s callback' % name)
        if (getattr(self.compatibility, '_battle_active', False) or
                not self.context['lobby_ready']()):
            return False
        self._account_context = dict(self.context.get('account_context') or {})
        self._account_context.update(self.compatibility.seed_account_context())
        if 'selected_vehicle' in self._account_context:
            self._account_context['selected_vehicle'] = copy.deepcopy(
                self._account_context['selected_vehicle'])
        self._report = open(self.manifest['report_path'], 'ab')
        self._record('experiment_start', endpoint=self.manifest['endpoint'])
        if self.manifest.get('vehicle_state_path'):
            try:
                vehicle_state = _vehicle_state(self.world, self.manifest)
                encoded = json.dumps(vehicle_state, sort_keys=True).encode('ascii')
                with open(self.manifest['vehicle_state_path'], 'wb') as target:
                    target.write(encoded + b'\n')
                self._record('vehicle_state_exported',
                             vehicle=vehicle_state['vehicle'],
                             arena_type_id=vehicle_state['arena_type_id'])
            except Exception as error:
                self._record('vehicle_state_error', error=str(error))
                self._finish('export_failed')
                return False
        self.state = 'suspending'
        try:
            self.context['suspend_session']()
            _request_disconnect()
            self.compatibility.disconnect()
            self.compatibility._rollback_install()
            self._record('offline_retired')
            self._deadline = self.clock() + 30.0
            self._schedule(0.0, self._wait_for_native_entry)
        except Exception as error:
            self._record('handoff_error', error=str(error))
            self.stop('handoff_error')
        return True

    def _wait_for_native_entry(self):
        if self.clock() >= self._deadline:
            self.stop('handoff_timeout')
            return
        if self.world.player() is not None or not self.context['login_ready']():
            self._login_seen = False
            self._schedule(0.1, self._wait_for_native_entry)
            return
        if not self._login_seen:
            self._login_seen = True
            self._schedule(0.0, self._wait_for_native_entry)
            return
        self._connect()

    def _install_observers(self):
        avatar_type = self.runtime.avatar_module.PlayerAvatar
        for name in self._inputs:
            original = avatar_type.__dict__[name]

            def make_observer(method_name, method):
                def observe(avatar, *args, **kwargs):
                    if (self.state in ('connecting', 'connected') and
                            self.world.player() is avatar):
                        self._inputs[method_name] += 1
                    return method(avatar, *args, **kwargs)
                return observe

            observer = make_observer(name, original)
            self._observers.append((avatar_type, name, original, observer))
            setattr(avatar_type, name, observer)

    def _remove_observers(self):
        for owner, name, original, observer in self._observers:
            if owner.__dict__.get(name) is observer:
                setattr(owner, name, original)
        self._observers = []

    def _connect(self):
        self.state = 'connecting'
        self._deadline = self.clock() + self.manifest['timeout']
        self._install_observers()
        data = self.data_factory(self.manifest)
        self.manager._ConnectionManager__connectionData = data
        self.manager._ConnectionManager__connectionUrl = self.manifest['endpoint']
        token = object()
        self._connection_token = token

        def progress(stage, status, response):
            if token is self._connection_token:
                self._progress(stage, status, response)

        self._native_started = True
        self._record('native_connect')
        self.world.connect(self.manifest['endpoint'], data, progress)
        if self.state in ('connecting', 'connected'):
            self._schedule(0.0, self._sample)

    def _progress(self, stage, status, response):
        self._record('connection_progress', stage=stage, status=status)
        if self.state == 'disconnecting' and stage != 6:
            return
        if stage == 6:
            self._disconnect_notified = True
        if (self.state == 'connecting' and stage == 1 and
                status != self.runtime.login_status.LOGGED_ON):
            self._connection_rejected = True
        handler = self.manager._ConnectionManager__serverResponseHandler
        handler(stage, status, response)
        if self.state == 'disconnecting':
            return
        if stage == 1 and status == self.runtime.login_status.LOGGED_ON:
            self.state = 'connected'
        elif stage == 6 or status != self.runtime.login_status.LOGGED_ON:
            self._schedule(0.0, lambda: self.stop('connection_ended'))

    def _snapshot(self):
        player = self.world.player()
        result = dict(player_id=None, player_type=None, space_id=None,
                      avatar_init_bits=None, own_vehicle_id=None,
                      own_vehicle_present=False, input_handler=None,
                      entity_count=len(self.world.entities), spaces=[],
                      input_counts=dict(self._inputs))
        spaces = set()
        for entity in self.world.entities.values():
            space_id = getattr(entity, 'spaceID', None)
            if space_id is not None:
                spaces.add(int(space_id))
        result['spaces'] = sorted(spaces)
        if player is None:
            return result
        vehicle_id = getattr(player, 'playerVehicleID', None)
        vehicle = (self.world.entities.get(vehicle_id)
                   if vehicle_id is not None else None)
        result.update(player_id=int(player.id),
                      player_type=type(player).__name__,
                      space_id=getattr(player, 'spaceID', None),
                      avatar_init_bits=getattr(
                          player, '_PlayerAvatar__initProgress', None),
                      own_vehicle_id=vehicle_id,
                      own_vehicle_present=vehicle is not None,
                      input_handler=type(getattr(
                          player, 'inputHandler', None)).__name__,
                      offline_overlay=bool(getattr(player, 'isOffline', False)))
        if vehicle is not None:
            result['own_vehicle_position'] = list(vehicle.position)
            result['own_vehicle_filter'] = type(vehicle.filter).__name__
        return result

    def _sample(self):
        if self.state not in ('connecting', 'connected'):
            return
        self._record('sample', **self._snapshot())
        if self.clock() >= self._deadline:
            self.stop('timeout')
        else:
            self._schedule(0.5, self._sample)

    def stop(self, reason='cancelled', restore=True):
        if self.state in ('finished', 'recovery_failed', 'export_failed', 'disconnecting',
                          'restoring'):
            if not restore and self.state in ('disconnecting', 'restoring'):
                self._finish('finished')
            return
        self._cancel_callbacks()
        self._login_seen = False
        self.state = 'disconnecting'
        self._record('stop', reason=reason, input_counts=dict(self._inputs))
        self._remove_observers()
        try:
            if self._native_started and not (self._disconnect_notified or
                                             self._connection_rejected):
                _request_disconnect()
            elif self.compatibility._fake_connected:
                _request_disconnect()
                self.compatibility.disconnect()
        except Exception as error:
            self._record('disconnect_error', error=str(error))
            self._connection_token = None
            self._finish('recovery_failed')
            return
        if not restore:
            self._finish('finished')
            return
        self._deadline = self.clock() + 30.0
        self._schedule(0.0, self._restore)

    def _restore(self):
        if self.clock() >= self._deadline:
            self._record('recovery_timeout')
            self._finish('recovery_failed')
            return
        connection_terminal = (not self._native_started or
                               self._disconnect_notified or
                               self._connection_rejected)
        player_present = self.world.player() is not None
        login_ready = bool(self.context['login_ready']())
        if self.clock() >= self._next_recovery_record:
            self._next_recovery_record = self.clock() + 5.0
            self._record('restore_wait', connection_terminal=connection_terminal,
                         player_present=player_present, login_ready=login_ready)
        if not connection_terminal or player_present or not login_ready:
            self._login_seen = False
            self._schedule(0.1, self._restore)
            return
        if not self._login_seen:
            self._login_seen = True
            self._schedule(0.0, self._restore)
            return
        self.state = 'restoring'
        self._connection_token = None
        self._record('restore_begin')
        self.context['restore_session']()
        self._record('restore_session_returned')
        self.compatibility.connect(show_lobby=True,
                                   account_context=self._account_context)
        self._record('restore_connect_returned',
                     fake_connected=bool(self.compatibility._fake_connected),
                     compatibility_connecting=bool(getattr(
                         self.compatibility, '_connecting', False)))
        self._next_recovery_record = 0.0
        self._schedule(0.1, self._wait_for_lobby)

    def _wait_for_lobby(self):
        compatibility_ready = bool(self.compatibility.is_ready())
        lobby_ready = (bool(self.context['lobby_ready']())
                       if compatibility_ready else None)
        if self.clock() >= self._next_recovery_record:
            self._next_recovery_record = self.clock() + 5.0
            player = self.world.player()
            self._record('lobby_restore_poll',
                         compatibility_ready=compatibility_ready,
                         lobby_ready=lobby_ready,
                         player_id=getattr(player, 'id', None),
                         player_type=None if player is None else type(player).__name__,
                         fake_connected=bool(self.compatibility._fake_connected),
                         compatibility_connecting=bool(getattr(
                             self.compatibility, '_connecting', False)))
        if compatibility_ready and lobby_ready:
            self._record('lobby_restored')
            self._finish('finished')
        elif self.clock() >= self._deadline:
            self._record('lobby_restore_timeout')
            self._finish('recovery_failed')
        else:
            self._schedule(0.1, self._wait_for_lobby)

    def _finish(self, state):
        self._cancel_callbacks()
        self._connection_token = None
        self._remove_observers()
        self.state = state
        self._record('experiment_end')
        if self._report is not None:
            self._report.close()
            self._report = None


def maybe_start(compatibility, context):
    """Return True once an explicitly requested probe owns the transition."""
    global _probe, _attempted
    path = os.environ.get(ENVIRONMENT)
    if not path or _attempted:
        return False
    _attempted = True
    try:
        probe = NativeProtocolProbe(compatibility, context, _manifest(path))
        _probe = probe
        return probe.start()
    except Exception as error:
        sys.stdout.write('[Offline LAN 0.9.22] NATIVE_PROTOCOL start failed: '
                         '%s\n' % error)
        return False


def fini():
    if _probe is not None:
        _probe.stop('shutdown', restore=False)
