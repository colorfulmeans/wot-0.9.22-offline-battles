"""One-time source integration; never reads original client resources or secrets."""
import base64
import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'e9e9417be5c0c4ab3d1271d705ef661549065ae6'
PACKET_SHA = '5349b6cdb37e072f7384d2873c1ffe60b4be8f2b1e6fc7d8792e537ca2e3a87c'
GRAPH_SHA = '5c981f89f2ab2f36058cf8835e3ea9a666587d15521227a2e121e02c5d0a737f'
BRANCH = 'fix/093-airfield-rebuilt-test-20260923'
PROOF = 'docs/testing/airfield-build-inputs-20260923.json'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def local_path(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or p.parts[0] not in ('src', 'tools', 'tests', 'navgraphs'):
        raise ValueError('Unapproved transfer path: ' + name)
    return ROOT.joinpath(*p.parts)

def git(*args):
    return subprocess.check_output(['git'] + list(args), cwd=str(ROOT), text=True).strip()

def main():
    if os.environ.get('GITHUB_REF_NAME') != BRANCH:
        raise RuntimeError('Source integration is limited to the dedicated test branch')
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], cwd=str(ROOT))
    packet_bytes = base64.b64decode(''.join((ROOT / '.airfield-transfer' / ('part-%02d.b64' % i)).read_text() for i in range(2)), validate=True)
    if sha(packet_bytes) != PACKET_SHA:
        raise RuntimeError('Source transfer checksum mismatch')
    packet = json.loads(lzma.decompress(packet_bytes))
    if packet['schema'] != 1 or packet['base_commit'] != BASE or len(packet['files']) != 13:
        raise RuntimeError('Unexpected transfer schema or baseline')
    outputs = {}
    records = []
    for rec in packet['files']:
        path = local_path(rec['path'])
        if rec['path'] in outputs:
            raise RuntimeError('Duplicate transfer path')
        old = path.read_bytes() if path.exists() else None
        if (sha(old) if old is not None else None) != rec['base_sha256']:
            raise RuntimeError('Base file changed: ' + rec['path'])
        kind = rec['kind']
        if kind == 'copy':
            data = local_path(rec['source']).read_bytes()
            if sha(data) != rec['source_sha256']:
                raise RuntimeError('Copy source changed')
        elif kind == 'text':
            data = rec['text'].encode('utf-8')
        elif kind == 'lines':
            lines = old.decode('utf-8').splitlines(True)
            for first, last, replacement in reversed(rec['edits']):
                if not 0 <= first <= last <= len(lines):
                    raise RuntimeError('Invalid source edit')
                lines[first:last] = [replacement]
            data = ''.join(lines).encode('utf-8')
        elif kind == 'json':
            obj = json.loads(old)
            for keys, value in rec['edits']:
                if not keys:
                    obj = value
                    continue
                target = obj
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
            data = (json.dumps(obj, **rec['format']) + '\n').encode('utf-8')
        else:
            raise RuntimeError('Unknown source transfer kind')
        if sha(data) != rec['sha256']:
            raise RuntimeError('Result checksum mismatch: ' + rec['path'])
        outputs[rec['path']] = data
        records.append({'path': rec['path'], 'base_sha256': rec['base_sha256'], 'sha256': rec['sha256']})
    if sha(outputs['navgraphs/31_airfield.json']) != GRAPH_SHA:
        raise RuntimeError('Wrong rebuilt Airfield asset')
    # Validate every output before touching any tracked source.
    for name, data in outputs.items():
        path = local_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    source_hashes = {}
    runtime = ROOT / 'src/res/scripts/client/gui/mods/offline_lan_0922'
    for path in sorted(runtime.rglob('*.py')):
        source_hashes[path.relative_to(ROOT).as_posix()] = sha(path.read_bytes().replace(b'\r\n', b'\n'))
    if len(source_hashes) != 139:
        raise RuntimeError('Unexpected runtime source inventory')
    proof = {'schema': 1, 'public_base_commit': BASE, 'preserved_runtime_build': 'b51324c5',
             'source_transfer_sha256': PACKET_SHA, 'airfield_sha256': GRAPH_SHA,
             'original_b51324c5_package_sha256': '67212336e4d4c333b2cb3ff7d133cb6fccc8e60d71c848c461361002c1bca8be',
             'changed_files': records, 'runtime_source_sha256_lf': source_hashes,
             'scope': 'Airfield test only; other 40 maps unchanged; no native gameplay claim'}
    path = ROOT / PROOF
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proof, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    subprocess.check_call(['git', 'add', '--'] + list(outputs) + [PROOF], cwd=str(ROOT))
    subprocess.check_call(['git', 'rm', '-r', '--', '.airfield-transfer'], cwd=str(ROOT))
    print('Verified and staged %d exact source/asset files plus provenance.' % len(outputs))

if __name__ == '__main__':
    main()
