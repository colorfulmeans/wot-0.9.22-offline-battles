"""Bounded foreground command journal and observable execution receipts.

The launcher transports requests; only the visible player's controller may
validate identities, execute them and publish their terminal result.
"""
from __future__ import division
import json
import math
import os
import time

try:
    STRING_TYPES = (basestring,)
    INTEGER_TYPES = (int, long)
except NameError:
    STRING_TYPES = (str,)
    INTEGER_TYPES = (int,)

TERMINAL = frozenset(('completed', 'rejected', 'failed', 'cancelled'))
MISSIONS = frozenset(('attack', 'return_base', 'defend_base',
                      'hold_position', 'capture_base'))
READ_ONLY_ACTIONS = frozenset(('status', 'wait_state', 'assert_state'))
AIM_ACTIONS = frozenset(('aim_target', 'aim_point'))
NATIVE_ACTIONS = frozenset(('use_equipment', 'set_siege'))
ACTIONS = MISSIONS | READ_ONLY_ACTIONS | AIM_ACTIONS | NATIVE_ACTIONS | frozenset((
    'start', 'stop', 'halt', 'drive', 'fire', 'select_shell', 'reload', 'release_aim'))
# A fixed protocol vocabulary, parity-tested against equipment_mechanics.
# Keep this module independently importable by desktop journal tools.
EQUIPMENT_TARGETS = frozenset((
    'engineHealth', 'ammoBayHealth', 'fuelTankHealth', 'radioHealth',
    'leftTrackHealth', 'rightTrackHealth', 'gunHealth',
    'turretRotatorHealth', 'surveyingDeviceHealth',
    'commander', 'driver', 'gunner1', 'gunner2', 'loader1',
    'loader2', 'radioman1', 'radioman2'))
STATE_CONDITIONS = frozenset(('ammo_ready', 'ammo_empty', 'halted', 'active',
    'mission_status', 'mission_phase', 'shot_terminal', 'shot_effect'))
MISSION_STATUS_VALUES = frozenset(('idle', 'pending', 'running', 'completed', 'failed', 'cancelled'))
MISSION_PHASE_VALUES = frozenset(('idle', 'attacking', 'travelling', 'capture_travel',
    'arriving', 'capturing', 'defending', 'holding', 'captured', 'failed', 'cancelled'))


def number(value, name, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError('invalid_' + name)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('invalid_' + name)
    if math.isnan(result) or math.isinf(result) or not minimum <= result <= maximum:
        raise ValueError('invalid_' + name)
    return result


def validate_action(action, arguments):
    if action not in ACTIONS:
        raise ValueError('unknown_action')
    if not isinstance(arguments, dict):
        raise ValueError('invalid_args')
    args = dict(arguments)
    allowed = set()
    if action == 'drive':
        allowed = set(('seconds', 'forward', 'turn'))
        args = dict(seconds=number(args.get('seconds', 1.), 'seconds', .01, 10.),
                    forward=number(args.get('forward', 0.), 'forward', -1., 1.),
                    turn=number(args.get('turn', 0.), 'turn', -1., 1.))
    elif action in ('attack', 'hold_position'):
        allowed = set(('position', 'radius'))
        if 'position' in args:
            value = args['position']
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                raise ValueError('invalid_position')
            args['position'] = tuple(number(v, 'position', -100000., 100000.) for v in value)
        if 'radius' in args:
            args['radius'] = number(args['radius'], 'radius', 2., 150.)
    elif action == 'select_shell':
        allowed = set(('compact_descr',))
        value = args.get('compact_descr')
        if isinstance(value, bool) or not isinstance(value, INTEGER_TYPES) or not 1 <= value <= 2147483647:
            raise ValueError('invalid_compact_descr')
    elif action in AIM_ACTIONS:
        allowed = set(('tolerance_deg',))
        args['tolerance_deg'] = number(args.get('tolerance_deg', .5), 'tolerance_deg', .05, 5.)
        if action == 'aim_target':
            allowed.add('target_id')
            value = args.get('target_id')
            if isinstance(value, bool) or not isinstance(value, INTEGER_TYPES) or not 1 <= value <= 2147483647:
                raise ValueError('invalid_target_id')
        else:
            allowed.add('position')
            value = args.get('position')
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                raise ValueError('invalid_position')
            args['position'] = tuple(number(v, 'position', -100000., 100000.) for v in value)
    elif action == 'release_aim':
        allowed = set(('command_id',))
        if 'command_id' in args:
            value = args['command_id']
            if not isinstance(value, STRING_TYPES) or not 1 <= len(value) <= 128:
                raise ValueError('invalid_command_id')
    elif action == 'use_equipment':
        allowed = set(('equipment_id', 'target', 'active'))
        value = args.get('equipment_id')
        if isinstance(value, bool) or not isinstance(value, INTEGER_TYPES) or not 0 <= value <= 65535:
            raise ValueError('invalid_equipment_id')
        if 'target' in args:
            value = args['target']
            if (not isinstance(value, STRING_TYPES) or not 1 <= len(value) <= 64 or
                    value not in EQUIPMENT_TARGETS):
                raise ValueError('invalid_equipment_target')
        if 'active' in args and not isinstance(args['active'], bool):
            raise ValueError('invalid_active')
    elif action == 'set_siege':
        allowed = set(('enabled',))
        if not isinstance(args.get('enabled'), bool):
            raise ValueError('invalid_enabled')
    elif action in ('wait_state', 'assert_state'):
        condition = args.get('condition')
        if not isinstance(condition, STRING_TYPES) or condition not in STATE_CONDITIONS:
            raise ValueError('invalid_condition')
        allowed = set(('condition',))
        if condition == 'active':
            allowed.add('value')
            if not isinstance(args.get('value'), bool):
                raise ValueError('invalid_value')
        elif condition in ('mission_status', 'mission_phase'):
            allowed.add('value')
            values = MISSION_STATUS_VALUES if condition == 'mission_status' else MISSION_PHASE_VALUES
            if not isinstance(args.get('value'), STRING_TYPES) or args['value'] not in values:
                raise ValueError('invalid_value')
            if 'command_id' in args:
                allowed.add('command_id')
                if not isinstance(args['command_id'], STRING_TYPES) or not 1 <= len(args['command_id']) <= 128:
                    raise ValueError('invalid_command_id')
        elif condition in ('shot_terminal', 'shot_effect'):
            references = [key for key in ('projectile_id', 'command_id') if key in args]
            if len(references) != 1:
                raise ValueError('invalid_shot_reference')
            key = references[0]
            allowed.add(key)
            value = args[key]
            if not isinstance(value, STRING_TYPES) or not 1 <= len(value) <= (256 if key == 'projectile_id' else 128):
                raise ValueError('invalid_' + key)
            if condition == 'shot_effect':
                allowed.add('damage_min')
                value = args.get('damage_min', 0.)
                if isinstance(value, bool) or not isinstance(value, INTEGER_TYPES + (float,)):
                    raise ValueError('invalid_damage_min')
                args['damage_min'] = number(value, 'damage_min', 0., float('inf'))
    if set(arguments) - allowed:
        raise ValueError('unknown_argument')
    return args


class JournalReader(object):
    """Keep partial tails; drain oversized lines without pinning later stop."""
    def __init__(self, offset=0):
        self.offset = offset
        self.discarding = False
        self.identity = None

    def poll(self, path, consume, reject):
        if not path or not os.path.isfile(path):
            return
        stat = os.stat(path)
        identity = (stat.st_dev, stat.st_ino)
        if (self.identity is not None and self.identity != identity) or stat.st_size < self.offset:
            self.offset, self.discarding = 0, False
        self.identity = identity
        # At most 64 KiB and 16 records per frame, including discarded data.
        budget, records = 65536, 0
        with open(path, 'rb') as stream:
            stream.seek(self.offset)
            while budget > 0 and records < 16:
                start = stream.tell()
                line = stream.readline(min(4097, budget))
                budget -= len(line)
                if not line:
                    break
                complete = line.endswith(b'\n')
                if self.discarding:
                    self.offset = stream.tell()
                    if complete:
                        self.discarding = False
                        records += 1
                    continue
                if len(line) > 4096:
                    self.offset = stream.tell()
                    self.discarding = not complete
                    reject('oversize', start)
                    records += int(complete)
                    continue
                if not complete:
                    # An unfinished valid record remains on disk until its
                    # newline arrives. No unbounded in-memory accumulation.
                    break
                self.offset = stream.tell()
                records += 1
                try:
                    request = json.loads(line.decode('utf8'))
                except (ValueError, UnicodeError):
                    reject('invalid_json', start)
                    continue
                consume(request)


def append_result(path, row):
    if not path:
        return False
    payload = (json.dumps(row, ensure_ascii=True, allow_nan=False,
                          sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
    with open(path, 'ab') as stream:
        stream.write(payload)
        stream.flush()
    return True


def same_identity(left, right):
    """JSON identity includes type; Python's bool/int equality is not enough."""
    def kind(value):
        return (bool if isinstance(value, bool) else int if isinstance(value, INTEGER_TYPES)
                else str if isinstance(value, STRING_TYPES) else type(value))
    return all(left.get(key) == right.get(key) and kind(left.get(key)) == kind(right.get(key))
               for key in ('session_id', 'round_id', 'player_id'))


class CommandGateway(object):
    def __init__(self, identity, emit, execute, preflight, cancel, wall_clock=None):
        self.identity = identity
        self.emit, self.execute = emit, execute
        self.preflight, self.cancel = preflight, cancel
        self.wall_clock = wall_clock or time.time
        self.requests = {}
        self.last = None

    def rejection(self, request, reason, now, conflict=False):
        current = self.identity()
        identity = dict(current)
        if isinstance(request, dict):
            for field in ('session_id', 'round_id', 'player_id'):
                if field in request:
                    identity[field] = request[field]
        row = dict(identity, type='request_error' if conflict else 'command',
                   status='rejected', reason=reason,
                   id=request.get('id') if isinstance(request, dict) else None,
                   action=request.get('action') if isinstance(request, dict) else None,
                   time=now)
        if identity != current:
            row['current_identity'] = current
        self.emit(row)
        # A conflicting request is a protocol error, not the terminal state
        # of the already admitted operation bearing that ID.
        if not conflict:
            self.last = row
        return row

    def submit(self, request, now):
        cacheable = False
        try:
            if not isinstance(request, dict):
                raise ValueError('invalid_request')
            identity = dict(self.identity())
            if not identity.get('session_id'):
                raise ValueError('session_unavailable')
            for field in ('session_id', 'round_id', 'player_id'):
                # JSON types are part of the identity; bool is not player 1.
                if (request.get(field) != identity.get(field) or
                        isinstance(request.get(field), bool)):
                    raise ValueError('stale_' + field)
                expected = identity.get(field)
                if ((isinstance(expected, INTEGER_TYPES) and
                     not isinstance(request.get(field), INTEGER_TYPES)) or
                    (isinstance(expected, STRING_TYPES) and
                     not isinstance(request.get(field), STRING_TYPES))):
                    raise ValueError('invalid_' + field)
            request_id = request.get('id')
            if not isinstance(request_id, STRING_TYPES) or not 1 <= len(request_id) <= 128:
                raise ValueError('invalid_id')
            fingerprint = json.dumps(request, sort_keys=True, allow_nan=False,
                                     separators=(',', ':'))
            previous = self.requests.get(request_id)
            if previous is not None:
                if previous['fingerprint'] != fingerprint:
                    return self.rejection(request, 'id_conflict', now, conflict=True)
                self.emit(previous['receipt'])
                return previous['receipt']
            # Never evict an ID and accidentally replay a timed drive/shot.
            if len(self.requests) >= 2048 and request.get('action') != 'stop':
                raise ValueError('session_command_limit')
            cacheable = True
            action = request.get('action')
            args = validate_action(action, request.get('args', {}))
            expires_at = None
            # Producer and consumer are separate processes. Admission uses
            # shared Unix wall time, never the client's battle clock. A retry
            # already in the ID ledger returned above keeps its original
            # outcome even after expiry. Stop deliberately has no admission
            # deadline: a stalled client must still release the same identity.
            if 'expires_at' in request or action != 'stop':
                expires_at = request.get('expires_at')
                if (isinstance(expires_at, bool) or not isinstance(
                        expires_at, INTEGER_TYPES + (float,))):
                    raise ValueError('invalid_expires_at')
                expires_at = number(expires_at, 'expires_at', 0., 1e12)
                if action != 'stop' and number(self.wall_clock(), 'admission_clock', 0., 1e12) >= expires_at:
                    raise ValueError('request_expired')
            default_timeout = (args['seconds'] + 2. if action == 'drive' else
                               600. if action in MISSIONS else
                               180. if action in ('select_shell', 'reload') else
                               30. if action == 'wait_state' or action in AIM_ACTIONS | NATIVE_ACTIONS else 10.)
            timeout = number(request.get('timeout_seconds', default_timeout),
                             'timeout', .1, 3600.)
            replace = request.get('replace', True)
            if not isinstance(replace, bool):
                raise ValueError('invalid_replace')
            command = dict(id=request_id, action=action, args=args,
                           timeout_seconds=timeout, replace=replace, identity=dict(identity))
            reason = self.preflight(command)
            if reason:
                raise ValueError(reason)
            if not same_identity(identity, self.identity()):
                raise ValueError('identity_changed')
            if action != 'stop' and number(self.wall_clock(), 'admission_clock', 0., 1e12) >= expires_at:
                raise ValueError('request_expired')
        except (TypeError, ValueError, OverflowError) as error:
            row = self.rejection(request, str(error), now)
            if cacheable:
                self.requests[request_id] = dict(fingerprint=fingerprint, receipt=row)
            return row
        receipt = dict(identity, type='command', id=request_id, action=action,
                       status='accepted', reason='validated', time=now)
        # A file write is only transport. Execution starts after an actual
        # client acceptance can be observed by the test producer.
        if not self.emit(receipt):
            row = self.rejection(request, 'result_unavailable', now)
            self.requests[request_id] = dict(fingerprint=fingerprint, receipt=row)
            return row
        self.requests[request_id] = dict(fingerprint=fingerprint, receipt=receipt,
                                        command=command, deadline=now + timeout)
        self.last = receipt
        if not same_identity(identity, self.identity()):
            self.finish(request_id, 'cancelled', 'identity_changed', now)
            return self.requests[request_id]['receipt']
        try:
            outcome = self.execute(command, now)
        except Exception as error:
            self.finish(request_id, 'failed', 'execution_error', now,
                        dict(error=repr(error)[:160]))
            self.cancel(command, 'execution_error')
            raise
        if outcome is not None:
            self.finish(request_id, outcome.get('status', 'completed'),
                        outcome.get('reason', 'completed'), now, outcome.get('result'))
        return self.requests[request_id]['receipt']

    def finish(self, request_id, status, reason, now, result=None):
        entry = self.requests.get(request_id)
        if entry is None or entry['receipt']['status'] in TERMINAL:
            return False
        if status not in TERMINAL:
            raise ValueError('invalid_terminal_status')
        row = dict(entry['receipt'], status=status, reason=reason, time=now)
        if result is not None:
            row['result'] = result
        entry['receipt'] = row
        self.last = row
        self.emit(row)
        return True

    def tick(self, now):
        for request_id, entry in list(self.requests.items()):
            if entry['receipt']['status'] == 'accepted' and now >= entry['deadline']:
                self.finish(request_id, 'failed', 'command_timeout', now)
                self.cancel(entry['command'], 'command_timeout')
