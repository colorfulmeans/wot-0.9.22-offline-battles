"""Identity-bound JSONL transport for the visible client's test controls."""
import json
import math
import os
import time
import uuid
from collections import OrderedDict


COMMAND_ENV = 'WOT_OFFLINE_TEST_CONTROL_FILE'
RESULT_ENV = 'WOT_OFFLINE_TEST_CONTROL_RESULT_FILE'
SESSION_ENV = 'WOT_OFFLINE_TEST_CONTROL_SESSION'
ACTIONS = frozenset(('start', 'stop', 'halt', 'attack', 'return_base',
                     'defend_base', 'hold_position', 'capture_base',
                     'drive', 'fire', 'status', 'select_shell', 'reload', 'wait_state', 'assert_state'))
READ_ONLY_ACTIONS = frozenset(('status', 'wait_state', 'assert_state'))
STATE_CONDITIONS = frozenset(('ammo_ready', 'ammo_empty', 'halted', 'active',
    'mission_status', 'mission_phase', 'shot_terminal', 'shot_effect'))
MISSION_STATUS_VALUES = frozenset(('idle', 'pending', 'running', 'completed', 'failed', 'cancelled'))
MISSION_PHASE_VALUES = frozenset(('idle', 'attacking', 'travelling', 'capture_travel',
    'arriving', 'capturing', 'defending', 'holding', 'captured', 'failed', 'cancelled'))
TERMINAL = frozenset(('completed', 'rejected', 'failed', 'cancelled'))
RESULT_STATES = TERMINAL | frozenset(('accepted',))
SHOT_STATES = frozenset(('committed', 'hit', 'terminal', 'rejected'))


def validate_arguments(action, arguments):
    """Validate the launcher's copy of the plain-JSON client action schema."""
    if action not in ACTIONS or not isinstance(arguments, dict):
        raise ValueError('invalid_command')
    allowed = set()
    args = dict(arguments)

    def number(value, name, minimum, maximum):
        if isinstance(value, bool):
            raise ValueError('invalid_' + name)
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError('invalid_' + name)
        if not math.isfinite(result) or not minimum <= result <= maximum:
            raise ValueError('invalid_' + name)
        return result

    if action == 'drive':
        allowed = {'seconds', 'forward', 'turn'}
        for name, minimum, maximum in (('seconds', .01, 10.),
                                        ('forward', -1., 1.), ('turn', -1., 1.)):
            if name in args:
                args[name] = number(args[name], name, minimum, maximum)
    elif action in ('attack', 'hold_position'):
        allowed = {'position', 'radius'}
        if 'position' in args:
            position = args['position']
            if not isinstance(position, (list, tuple)) or len(position) != 3:
                raise ValueError('invalid_position')
            args['position'] = [number(value, 'position', -100000., 100000.)
                                for value in position]
        if 'radius' in args:
            args['radius'] = number(args['radius'], 'radius', 2., 150.)
    elif action == 'select_shell':
        allowed = {'compact_descr'}
        value = args.get('compact_descr')
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2147483647:
            raise ValueError('invalid_compact_descr')
    elif action in ('wait_state', 'assert_state'):
        condition = args.get('condition')
        if not isinstance(condition, str) or condition not in STATE_CONDITIONS:
            raise ValueError('invalid_condition')
        allowed = {'condition'}
        if condition == 'active':
            allowed.add('value')
            if not isinstance(args.get('value'), bool):
                raise ValueError('invalid_value')
        elif condition in ('mission_status', 'mission_phase'):
            allowed.add('value')
            values = MISSION_STATUS_VALUES if condition == 'mission_status' else MISSION_PHASE_VALUES
            if not isinstance(args.get('value'), str) or args['value'] not in values:
                raise ValueError('invalid_value')
            if 'command_id' in args:
                allowed.add('command_id')
                if not isinstance(args['command_id'], str) or not 1 <= len(args['command_id']) <= 128:
                    raise ValueError('invalid_command_id')
        elif condition in ('shot_terminal', 'shot_effect'):
            references = [key for key in ('projectile_id', 'command_id') if key in args]
            if len(references) != 1:
                raise ValueError('invalid_shot_reference')
            key = references[0]
            allowed.add(key)
            value = args[key]
            if not isinstance(value, str) or not 1 <= len(value) <= (256 if key == 'projectile_id' else 128):
                raise ValueError('invalid_' + key)
            if condition == 'shot_effect':
                allowed.add('damage_min')
                value = args.get('damage_min', 0.)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError('invalid_damage_min')
                args['damage_min'] = number(value, 'damage_min', 0., float('inf'))
    if set(args) - allowed:
        raise ValueError('unknown_argument')
    return args


class PlayerControlTransport:
    """A successful write means submitted; only client receipts mean executed."""

    MAX_LINE_BYTES = 16384
    MAX_COMMAND_BYTES = 4096
    MAX_POLL_BYTES = 262144
    MAX_POLL_RECORDS = 256
    TAIL_BYTES = 32768
    MAX_TRACKED = 128
    MAX_PROJECTILES = 512
    MAX_PROJECTILES_PER_COMMAND = 128
    ADMISSION_SECONDS = 2.0
    PROJECTILE_GRACE_SECONDS = 5.0

    def __init__(self, command_path, result_path, session_id, *,
                 clock=None, wall_clock=None, stale_seconds=5.0):
        self.command_path = command_path
        self.result_path = result_path
        self.session_id = session_id
        self.clock = clock or time.monotonic
        self.wall_clock = wall_clock or time.time
        self.stale_seconds = stale_seconds
        self.status = None
        self.status_received_at = None
        self.last_result = None
        self.results = OrderedDict()
        self.requests = OrderedDict()
        self.projectiles = OrderedDict()
        self.command_projectiles = OrderedDict()
        self.last_shot_command_id = None
        self._retired_identities = OrderedDict()
        self._request_sequence = 0
        self.error = None
        self.error_detail = ''
        self.offset = 0
        self._discard_line = False
        self._caught_up = True
        self._read_failed = False
        self._file_identity = None

    @staticmethod
    def _identity(record):
        return record.get('round_id'), record.get('player_id')

    @staticmethod
    def _valid_identity(record):
        round_id, player_id = PlayerControlTransport._identity(record)
        return (not isinstance(round_id, bool) and isinstance(round_id, (str, int))
                and round_id not in ('', 0) and not isinstance(player_id, bool)
                and isinstance(player_id, int) and player_id > 0)

    def unavailable_reason(self, action=None):
        if self._read_failed:
            return 'result_read_failed'
        if not self._caught_up:
            return 'waiting_for_status'
        if not self.status or not self._valid_identity(self.status):
            return 'waiting_for_battle'
        if (self.status_received_at is None or
                self.clock() - self.status_received_at > self.stale_seconds):
            return 'status_stale'
        if not (isinstance(action, str) and action in READ_ONLY_ACTIONS) and self.status.get('live') is not True:
            return self.status.get('reason') or 'battle_not_live'
        return None

    @property
    def live(self):
        return self.unavailable_reason() is None

    def can_submit(self, action):
        # Releasing ownership is safe with the last observed identity: the
        # client still rejects an old round. A stall must not defeat Stop.
        if action == 'stop':
            return bool(self.status and self.status.get('session_id') == self.session_id
                        and self._valid_identity(self.status))
        return self.unavailable_reason(action) is None

    def _set_error(self, reason, detail=''):
        self.error, self.error_detail = reason, str(detail)

    def _remember(self, target, key, value, limit=None):
        target[key] = value
        target.move_to_end(key)
        while len(target) > (self.MAX_TRACKED if limit is None else limit):
            target.popitem(last=False)

    def _expire_requests(self):
        for command_id, request in list(self.requests.items()):
            result = self.results.get(command_id, {})
            if (result.get('status') not in TERMINAL and
                    result.get('status') != 'unconfirmed' and
                    self.clock() > request['deadline']):
                result = dict(request['command'], type='command',
                              status='unconfirmed', reason='response_timeout')
                self._remember(self.results, command_id, result)
                if self.last_result and self.last_result.get('id') == command_id:
                    self.last_result = result

    def _has_pending(self):
        return (any(self.results.get(command_id, {}).get('status') in
                    ('submitted', 'accepted') for command_id in self.requests) or
                any(item['flight_status'] in ('awaiting', 'committed') or
                    (item['flight_status'] == 'terminal' and
                     self.clock() - item['flight_finished_at'] <= self.PROJECTILE_GRACE_SECONDS)
                    for item in self.projectiles.values()))

    @staticmethod
    def _valid_projectile_id(projectile_id):
        return isinstance(projectile_id, str) and 0 < len(projectile_id) <= 256

    def _projectile(self, record):
        key = self._identity(record) + (record['projectile_id'],)
        item = self.projectiles.get(key)
        if item is None:
            item = dict(session_id=self.session_id, round_id=record['round_id'],
                        player_id=record['player_id'], projectile_id=record['projectile_id'],
                        command_id=None, claimed_command_id=None, local_committed=False,
                        events={}, damage_total=0., hit_count=0, penetrated=False,
                        flight_status='awaiting', flight_finished_at=None,
                        terminal_observed=False, combat_observed=False, latest_event_seq=0)
            self._remember(self.projectiles, key, item, self.MAX_PROJECTILES)
        return key, item

    def _known_fire(self, command_id, identity):
        request = self.requests.get(command_id)
        command = request['command'] if request else self.results.get(command_id)
        return bool(command and command.get('action') == 'fire' and
                    self._identity(command) == identity and
                    command.get('session_id') == self.session_id)

    def _link_projectile(self, command_id, key, item):
        if (not self._known_fire(command_id, key[:2]) or
                item['command_id'] not in (None, command_id) or
                item['claimed_command_id'] not in (None, command_id)):
            return False
        keys = self.command_projectiles.get(command_id, ())
        if key not in keys:
            if len(keys) >= self.MAX_PROJECTILES_PER_COMMAND:
                return False
            self._remember(self.command_projectiles, command_id, tuple(keys) + (key,))
        item['command_id'] = command_id
        return True

    def _remember_shot_command(self, command_id):
        request, latest = self.requests.get(command_id), self.requests.get(self.last_shot_command_id)
        if request and latest and request['sequence'] < latest['sequence']:
            return
        self.last_shot_command_id = command_id

    def _link_result_projectiles(self, record):
        if record.get('action') != 'fire' or self._identity(record) != self._identity(self.status or {}):
            return
        command_id = record['id']
        self._remember_shot_command(command_id)
        result = record.get('result')
        if isinstance(result, dict):
            ids = result.get('projectile_ids')
            if ids is None and result.get('projectile_id') is not None:
                ids = [result['projectile_id']]
            if (isinstance(ids, (list, tuple)) and len(ids) <= self.MAX_PROJECTILES_PER_COMMAND and
                    all(self._valid_projectile_id(value) for value in ids)):
                for projectile_id in ids:
                    key, item = self._projectile(dict(record, projectile_id=projectile_id))
                    if self._link_projectile(command_id, key, item):
                        item['local_committed'] = True
                        if item['flight_status'] == 'awaiting':
                            item['flight_status'] = 'committed'
        # An event may arrive before its command receipt, including during
        # native re-entry. Only a known matching command can claim that event.
        for key, item in self.projectiles.items():
            if item['claimed_command_id'] == command_id:
                self._link_projectile(command_id, key, item)

    def _accept_shot(self, record):
        if (record.get('session_id') != self.session_id or
                not self._valid_identity(record) or
                self._identity(record) != self._identity(self.status or {}) or
                not isinstance(record.get('status'), str) or
                record.get('status') not in SHOT_STATES or
                not self._valid_projectile_id(record.get('projectile_id'))):
            return
        command_id, sequence = record.get('command_id'), record.get('event_seq')
        if command_id is not None and (not isinstance(command_id, str) or not 0 < len(command_id) <= 128):
            return
        if sequence is not None and (isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1):
            return
        for field in ('time', 'damage_total'):
            if field in record:
                value = record[field]
                try:
                    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                            not math.isfinite(value) or (field == 'damage_total' and value < 0)):
                        return
                except OverflowError:
                    return
        hit_count = record.get('hit_count')
        if 'hit_count' in record and (isinstance(hit_count, bool) or not isinstance(hit_count, int) or hit_count < 0):
            return
        for field in ('penetrated', 'terminal_observed', 'combat_observed'):
            if field in record and not isinstance(record[field], bool):
                return
        if record.get('flight_status', 'committed') not in ('committed', 'terminal', 'rejected'):
            return
        if command_id is not None:
            known = self.requests.get(command_id)
            known = known['command'] if known else self.results.get(command_id)
            if known and not self._known_fire(command_id, self._identity(record)):
                return
        key, item = self._projectile(record)
        if command_id is not None and (item['command_id'] not in (None, command_id) or
                                       item['claimed_command_id'] not in (None, command_id)):
            return
        previous = item['events'].get(record['status'])
        if previous:
            old_seq = previous.get('event_seq')
            if ((sequence is not None and old_seq is not None and sequence <= old_seq) or
                    (sequence is None and old_seq is not None) or
                    (sequence is None and old_seq is None and
                     record.get('time', 0.) <= previous.get('time', 0.))):
                return
        if command_id is not None:
            item['claimed_command_id'] = command_id
            self._link_projectile(command_id, key, item)
        item['events'][record['status']] = dict(record)
        item['local_committed'] = item['local_committed'] or record['status'] == 'committed'
        # The producer sends cumulative combat totals. Never add per-effect
        # damage here: snapshots, duplicates and reordered hit rows would
        # otherwise count the same effect repeatedly.
        item['damage_total'] = max(item['damage_total'], record.get('damage_total', 0.))
        item['hit_count'] = max(item['hit_count'], record.get('hit_count', 0))
        item['penetrated'] = item['penetrated'] or record.get('penetrated', False)
        item['terminal_observed'] = (item['terminal_observed'] or record.get('terminal_observed', False) or
                                      record['status'] == 'terminal')
        item['combat_observed'] = (item['combat_observed'] or record.get('combat_observed', False) or
                                    record['status'] == 'hit')
        flight_status = record.get('flight_status', record['status'])
        if flight_status == 'rejected' or item['flight_status'] == 'rejected':
            item['flight_status'] = 'rejected'
        elif flight_status == 'terminal' or item['terminal_observed']:
            item['flight_status'] = 'terminal'
        elif item['flight_status'] == 'awaiting':
            item['flight_status'] = 'committed'
        if item['flight_status'] in ('terminal', 'rejected') and item['flight_finished_at'] is None:
            # Keep a short catch-up window even after an initial HE effect:
            # there may be more effects. Beyond it, recent status snapshots
            # repair late observations without a ground miss pinning forever.
            item['flight_finished_at'] = self.clock()
        if sequence is None or sequence > item['latest_event_seq']:
            item['latest_event_seq'] = sequence or item['latest_event_seq']
            self.projectiles.move_to_end(key)

    def projectile_results(self, command_id=None):
        """Return a command's observations, or recent shots plus the latest burst.

        The default includes automatic shots after a manual Fire command; that
        older command must never hide the currently active controller's shots.
        """
        if command_id is not None:
            items = [self.projectiles[key] for key in self.command_projectiles.get(command_id, ())
                     if key in self.projectiles]
        else:
            recent = set(list(self.projectiles)[-8:])
            recent.update(self.command_projectiles.get(self.last_shot_command_id, ()))
            items = [item for key, item in self.projectiles.items() if key in recent]
        return [dict(item, events=dict(item['events'])) for item in items]

    def _accept_result(self, record):
        command_id = record.get('id')
        if (record.get('session_id') != self.session_id or
                not isinstance(command_id, str) or not 0 < len(command_id) <= 128 or
                not isinstance(record.get('action'), str) or
                not isinstance(record.get('status'), str) or
                record.get('status') not in RESULT_STATES):
            return
        request = self.requests.get(command_id)
        if request and record.get('action') != request['command']['action']:
            return
        identity = self._identity(request['command'] if request else (self.status or {}))
        if self._identity(record) != identity or not self._valid_identity(record):
            return
        previous = self.results.get(command_id, {})
        if previous.get('status') in TERMINAL:
            self._link_result_projectiles(previous)
            return
        self._remember(self.results, command_id, record)
        self._link_result_projectiles(record)
        latest_request = self.requests.get((self.last_result or {}).get('id'))
        if request and latest_request and request['sequence'] < latest_request['sequence']:
            return
        # An older receipt must not hide the newest submitted command.
        if (not self.last_result or self.last_result.get('id') == command_id or
                self.last_result.get('status') not in ('submitted', 'accepted')):
            if self.status and self._identity(record) == self._identity(self.status):
                self.last_result = record

    def _accept(self, record, received_at):
        if not isinstance(record, dict) or record.get('session_id') != self.session_id:
            return
        if record.get('type') == 'status':
            if not isinstance(record.get('live'), bool):
                return
            old_identity = self._identity(self.status or {})
            new_identity = self._identity(record)
            old_valid, new_valid = self._valid_identity(self.status or {}), self._valid_identity(record)
            if new_valid and new_identity in self._retired_identities:
                return
            self.status, self.status_received_at = record, received_at
            if new_identity != old_identity:
                if old_valid and new_valid:
                    self._remember(self._retired_identities, old_identity, True)
                self.last_result = None
                self.projectiles.clear()
                self.command_projectiles.clear()
                self.last_shot_command_id = None
            last_command = record.get('last_command')
            if isinstance(last_command, dict):
                # Status snapshots can repair a missed receipt without changing its identity.
                result = dict(last_command)
                for key in ('session_id', 'round_id', 'player_id'):
                    result.setdefault(key, record.get(key))
                self._accept_result(result)
            snapshots = record.get('shot_results')
            if isinstance(snapshots, list):
                for shot in snapshots[-32:]:
                    if isinstance(shot, dict):
                        result = dict(shot)
                        for key in ('session_id', 'round_id', 'player_id'):
                            result.setdefault(key, record.get(key))
                        self._accept_shot(result)
        elif record.get('type') == 'command':
            self._accept_result(record)
        elif record.get('type') == 'shot':
            self._accept_shot(record)

    def poll(self):
        """Consume complete records, retaining a partial tail and draining bad rows."""
        self._expire_requests()
        try:
            with open(self.result_path, 'rb') as stream:
                stat = os.fstat(stream.fileno())
                identity = (stat.st_dev, stat.st_ino)
                if ((self._file_identity is not None and identity != self._file_identity) or
                        stat.st_size < self.offset):
                    self.offset, self._discard_line = 0, False
                    self.status, self.status_received_at = None, None
                    self.projectiles.clear()
                    self.command_projectiles.clear()
                    self.last_shot_command_id = None
                self._file_identity = identity
                # A panel opened late needs the latest battle, not hours of old heartbeats.
                # Never skip receipts for a command that is still awaiting confirmation.
                if stat.st_size - self.offset > self.TAIL_BYTES and not self._has_pending():
                    self.offset = max(0, stat.st_size - self.TAIL_BYTES)
                    self._discard_line = self.offset > 0
                stream.seek(self.offset)
                read_bytes = 0
                received_at = self.clock() - max(0.0, self.wall_clock() - stat.st_mtime)
                for _ in range(self.MAX_POLL_RECORDS):
                    if read_bytes >= self.MAX_POLL_BYTES:
                        break
                    line = stream.readline(self.MAX_LINE_BYTES + 1)
                    read_bytes += len(line)
                    if not line:
                        break
                    ended = line.endswith(b'\n')
                    if self._discard_line or len(line) > self.MAX_LINE_BYTES:
                        self.offset = stream.tell()
                        self._discard_line = not ended
                        continue
                    if not ended:
                        break
                    self.offset = stream.tell()
                    try:
                        record = json.loads(line.decode('utf8'))
                    except (ValueError, UnicodeError):
                        continue
                    self._accept(record, received_at)
                self._caught_up = self.offset >= os.fstat(stream.fileno()).st_size
                self._read_failed = False
        except OSError as error:
            self._read_failed = True
            self._set_error('result_read_failed', error)
        return self.status

    def send(self, action, args=None, timeout_seconds=None, replace=True,
             admission_seconds=ADMISSION_SECONDS):
        """Submit with a wall-clock admission deadline, not an execution deadline.

        ``timeout_seconds`` starts after client admission. The launcher waits
        for admission plus execution plus two seconds of response allowance;
        expiry of that wait means unconfirmed, never cancellation or success.
        Stop omits admission expiry so a delayed same-identity release survives.
        """
        self.poll()
        reason = self.unavailable_reason(action)
        if reason and not (action == 'stop' and self.can_submit(action)):
            self._set_error(reason)
            return None
        try:
            arguments = validate_arguments(action, {} if args is None else args)
        except (TypeError, ValueError) as error:
            self._set_error(str(error))
            return None
        if timeout_seconds is None:
            timeout_seconds = (180. if action in ('select_shell', 'reload') else
                               30. if action == 'wait_state' else 15.)
        if not isinstance(replace, bool):
            self._set_error('invalid_replace')
            return None
        if (isinstance(timeout_seconds, bool) or
                not isinstance(timeout_seconds, (int, float)) or
                not .1 <= timeout_seconds <= 3600. or not math.isfinite(timeout_seconds)):
            self._set_error('invalid_timeout')
            return None
        if (isinstance(admission_seconds, bool) or not isinstance(admission_seconds, (int, float)) or
                not .1 <= admission_seconds <= 30. or not math.isfinite(admission_seconds)):
            self._set_error('invalid_admission_timeout')
            return None
        command = dict(id=uuid.uuid4().hex, session_id=self.session_id,
                       round_id=self.status['round_id'], player_id=self.status['player_id'],
                       action=action, args=arguments, timeout_seconds=timeout_seconds,
                       replace=replace)
        try:
            if action != 'stop':
                wall_now = self.wall_clock()
                if (isinstance(wall_now, bool) or not isinstance(wall_now, (int, float)) or
                        not 0. <= wall_now <= 1e12 or not math.isfinite(wall_now)):
                    self._set_error('invalid_admission_clock')
                    return None
                command['expires_at'] = wall_now + admission_seconds
                if (not math.isfinite(command['expires_at']) or
                        not 0. < command['expires_at'] <= 1e12):
                    self._set_error('invalid_admission_clock')
                    return None
            encoded = json.dumps(command, ensure_ascii=True, allow_nan=False) + '\n'
            if len(encoded.encode('utf8')) > self.MAX_COMMAND_BYTES:
                self._set_error('command_too_large')
                return None
            with open(self.command_path, 'a', encoding='utf8') as stream:
                stream.write(encoded)
        except (OSError, TypeError, ValueError) as error:
            self._set_error('command_write_failed', error)
            return None
        self.error, self.error_detail = None, ''
        result = dict(command, type='command', status='submitted', reason='')
        self.last_result = result
        self._remember(self.results, command['id'], result)
        self._request_sequence += 1
        self._remember(self.requests, command['id'], dict(
            command=command, deadline=self.clock() + timeout_seconds + 2.0 +
                (admission_seconds if action != 'stop' else 0.),
            sequence=self._request_sequence))
        if action == 'fire':
            self._remember_shot_command(command['id'])
        return command['id']
