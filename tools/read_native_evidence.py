"""Read complete or fragmented evidence from a log or error-report ZIP."""
import argparse
import json
from pathlib import Path
import zipfile

LABELS = ('BOT HEIGHT LINKS', 'VEHICLE STACK', 'LANDING CONTACT DECISION', 'BOT NAV CHOICE', 'MODULE PRESENT', 'BOT SUPPORT MODE', 'BOT LANDING IMPACT', 'PLAYER LANDING IMPACT', 'DAMAGE FEEDBACK', 'ENV CRITICAL FEEDBACK', 'NATIVE INPUT FALLBACK', 'NATIVE INPUT SUMMARY',
          'RICOCHET SURFACE EVIDENCE', 'PROJECTILE INTERFACE', 'PROJECTILE SETTLEMENT',
          'TREE DESCRIPTOR', 'ENV MODULE CONTACT', 'ENV MODULE DAMAGE', 'RAM TRACK CONTACT', 'RAM CONTACT GEOMETRY', 'BOT VERTICAL SUPPORT', 'BOT SLOPE POSE', 'BOT MOTION PRESENT', 'BOT MOTION')


def parse_lines(lines, source='log'):
    records, issues, pending = [], [], {}
    for number, line in enumerate(lines, 1):
        for label in LABELS:
            marker = ('' if label == 'PROJECTILE SETTLEMENT' else '[Offline LAN 0.9.22] ') + label + ' '
            if marker not in line:
                if label == 'BOT MOTION' and '[BOT MOTION] ' in line:
                    marker = '[BOT MOTION] '
                else:
                    continue
            text = line.split(marker, 1)[1]
            try:
                if not text.startswith('PART '):
                    records.append({'source': source, 'label': label,
                                    'line': number, 'data': json.loads(text)})
                    break
                part = json.loads(text[5:])
                if (part['schema'] != 1 or type(part['part']) is not int or
                        type(part['parts']) is not int or
                        not 1 <= part['part'] <= part['parts'] <= 4096 or
                        type(part['data']) is not str):
                    raise ValueError('invalid part header')
                key = (label, part['pid'], part['record'])
                row = pending.setdefault(key, {'line': number, 'parts': part['parts'],
                                                'pieces': {}, 'conflict': False})
                prior = row['pieces'].get(part['part'])
                row['conflict'] |= (row['parts'] != part['parts'] or
                                    prior is not None and prior != part['data'])
                row['pieces'][part['part']] = part['data']
                if len(row['pieces']) == row['parts'] and not row['conflict']:
                    payload = ''.join(row['pieces'][i] for i in range(1, row['parts'] + 1))
                    records.append({'source': source, 'label': label,
                                    'line': row['line'], 'data': json.loads(payload)})
                    del pending[key]
            except (ValueError, KeyError, TypeError) as error:
                issues.append({'source': source, 'label': label, 'line': number,
                               'reason': str(error)})
            break
    for key, row in pending.items():
        issues.append({'source': source, 'label': key[0], 'line': row['line'],
                       'pid': key[1], 'record': key[2], 'conflict': row['conflict'],
                       'missing_parts': [i for i in range(1, row['parts'] + 1)
                                         if i not in row['pieces']]})
    return {'records': records, 'issues': issues}


def read_path(path):
    if zipfile.is_zipfile(path):
        result = {'records': [], 'issues': []}
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.endswith(('hidden-worker.log', 'visible-client.log', 'server.log')):
                    rows = parse_lines(archive.read(name).decode('utf-8', 'replace').splitlines(), name)
                    for key in result: result[key].extend(rows[key])
        return result
    return parse_lines(path.read_text(encoding='utf-8', errors='replace').splitlines(), str(path))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    print(json.dumps(read_path(args.path), ensure_ascii=True, indent=2))
