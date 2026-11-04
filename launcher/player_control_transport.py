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
                     'drive', 'fire', 'status'))
TERMINAL = frozenset(('completed', 'rejected', 'failed', 'cancelled'))
RESULT_STATES = TERMINAL | frozenset(('accepted',))


class PlayerControlTransport:
    """A successful write means submitted; only client receipts mean executed."""

    MAX_LINE_BYTES = 16384
    MAX_COMMAND_BYTES = 4096
    MAX_POLL_BYTES = 262144
    MAX_POLL_RECORDS = 256
    TAIL_BYTES = 32768
    MAX_TRACKED = 128

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

    def unavailable_reason(self):
        if self._read_failed:
            return 'result_read_failed'
        if not self._caught_up:
            return 'waiting_for_status'
        if not self.status or not self._valid_identity(self.status):
            return 'waiting_for_battle'
        if self.status.get('live') is not True:
            return self.status.get('reason') or 'battle_not_live'
        if (self.status_received_at is None or
                self.clock() - self.status_received_at > self.stale_seconds):
            return 'status_stale'
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
        return self.live

    def _set_error(self, reason, detail=''):
        self.error, self.error_detail = reason, str(detail)

    def _remember(self, target, key, value):
        target[key] = value
        target.move_to_end(key)
        while len(target) > self.MAX_TRACKED:
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
        return any(self.results.get(command_id, {}).get('status') in
                   ('submitted', 'accepted') for command_id in self.requests)

    def _accept_result(self, record):
        command_id = record.get('id')
        if (record.get('session_id') != self.session_id or
                not isinstance(command_id, str) or not command_id or
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
            return
        self._remember(self.results, command_id, record)
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
            self.status, self.status_received_at = record, received_at
            if self._identity(record) != old_identity:
                self.last_result = None
            last_command = record.get('last_command')
            if isinstance(last_command, dict):
                # Status snapshots can repair a missed receipt without changing its identity.
                result = dict(last_command)
                for key in ('session_id', 'round_id', 'player_id'):
                    result.setdefault(key, record.get(key))
                self._accept_result(result)
        elif record.get('type') == 'command':
            self._accept_result(record)

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

    def send(self, action, args=None, timeout_seconds=15.0, replace=True):
        """Return a request ID, or None; callers display submitted until acknowledged."""
        self.poll()
        reason = self.unavailable_reason()
        if reason and not (action == 'stop' and self.can_submit(action)):
            self._set_error(reason)
            return None
        if action not in ACTIONS or args is not None and not isinstance(args, dict):
            self._set_error('invalid_command')
            return None
        if not isinstance(replace, bool):
            self._set_error('invalid_replace')
            return None
        if (isinstance(timeout_seconds, bool) or
                not isinstance(timeout_seconds, (int, float)) or
                not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            self._set_error('invalid_timeout')
            return None
        command = dict(id=uuid.uuid4().hex, session_id=self.session_id,
                       round_id=self.status['round_id'], player_id=self.status['player_id'],
                       action=action, args=args or {}, timeout_seconds=timeout_seconds,
                       replace=replace)
        try:
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
            command=command, deadline=self.clock() + timeout_seconds + 2.0,
            sequence=self._request_sequence))
        return command['id']
