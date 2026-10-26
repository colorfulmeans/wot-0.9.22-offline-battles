"""Correlate session audio errors without adding work to the game worker."""
import collections
import json
import os
import re
import struct
import zipfile


class SoundScanner:
    def __init__(self):
        self.pending = b''
        self.recent = collections.deque(maxlen=64)
        self.errors = []
        self.coverage = []
        self.events = {}
        self.diagnostic = False
        self.error_count = 0

    def feed(self, payload):
        lines = (self.pending + payload).split(b'\n')
        self.pending = lines.pop()[-65536:]
        for raw in lines:
            line = raw.decode('utf8', 'replace')
            marker = 'SOUND CALL '
            if marker in line:
                self.diagnostic = True
                try:record = json.loads(line.split(marker, 1)[1])
                except ValueError:continue
                if record.get('stage') in ('installed', 'object_coverage'):
                    if len(self.coverage) < 32:self.coverage.append(record)
                for event in record.get('event_ids', ()):
                    if len(self.events) < 4096:
                        self.events.setdefault(str(event['id']), set()).add(event['name'])
                self.recent.append(dict(time=line[:26], **record))
            else:
                match = re.search(r'Sound fail:\s*(\d+)\s*-\s*ErrorCode:\s*(\d+)', line)
                if match:
                    self.error_count += 1
                    if len(self.errors) < 128:
                        self.errors.append(dict(resource_id=int(match[1]), code=int(match[2]),
                            line=line[:1000], recent=list(self.recent)))

    def result(self):
        return dict(diagnostic=self.diagnostic, coverage=self.coverage,
            error_count=self.error_count, retained_errors=self.errors,
            event_names={key: sorted(value) for key, value in self.events.items()})


def bank_membership(game_root, identifiers):
    """Read HIRC object IDs, never infer bank membership from raw byte hits."""
    wanted = set(identifiers)
    matches, failures = [], []
    if not wanted:return dict(matches=matches, failures=failures)
    packages = os.path.join(game_root or '', 'res', 'packages')
    paths = [os.path.join(packages, name) for name in ('audioww.pkg',)]
    def scan(name, payload, source):
        offset = 0
        while offset + 8 <= len(payload):
            kind, size = struct.unpack_from('<4sI', payload, offset)
            start, end = offset + 8, offset + 8 + size
            if end > len(payload):raise ValueError('truncated bank chunk')
            if kind == b'HIRC':
                count, = struct.unpack_from('<I', payload, start)
                pos = start + 4
                for unused in range(count):
                    if pos + 9 > end:raise ValueError('truncated HIRC object')
                    object_type, length, identifier = struct.unpack_from('<BII', payload, pos)
                    if length < 4 or pos + 5 + length > end:raise ValueError('invalid HIRC length')
                    if identifier in wanted:
                        matches.append(dict(bank=name, source=source, resource_id=identifier,
                                            hirc_type=object_type, event=object_type == 4))
                    pos += 5 + length
            offset = end
    try:
        with zipfile.ZipFile(paths[0]) as archive:
            for item in archive.infolist():
                if item.filename.endswith('.bnk') and item.file_size <= 64 * 1024 * 1024:
                    try:scan(item.filename, archive.read(item), 'client_package')
                    except (ValueError, struct.error) as error:failures.append(str(error)[:200])
        folder = os.path.join(game_root, 'res', 'audioww')
        for base, unused, names in os.walk(folder):
            for name in names:
                path = os.path.join(base, name)
                if name.endswith('.bnk') and os.path.getsize(path) <= 64 * 1024 * 1024:
                    with open(path, 'rb') as stream:scan(os.path.relpath(path, folder), stream.read(), 'loose_resource')
    except (OSError, ValueError, zipfile.BadZipFile, struct.error) as error:
        failures.append(str(error)[:300])
    return dict(matches=matches, failures=failures)


def describe(scanners, game_root):
    roles = {role: scanner.result() for role, scanner in scanners.items()}
    if not any(row['diagnostic'] for row in roles.values()):return None
    ids = {error['resource_id'] for row in roles.values() for error in row['retained_errors']}
    return json.dumps(dict(schema=1, roles=roles,
        resource_membership=bank_membership(game_root, ids),
        limits=dict(recent_calls=64, errors_per_role=128, native_objects_not_retained=True),
        interpretation='Bank membership and matching event IDs are exact; nearby calls alone are not causation.'),
        ensure_ascii=True, indent=2)
