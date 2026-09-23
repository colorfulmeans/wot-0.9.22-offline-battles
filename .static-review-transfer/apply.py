"""Integrate the reviewed deletion against exact source hashes."""
import base64
import hashlib
import json
import pathlib
import subprocess
import zlib

root = pathlib.Path('.')
transfer = root / '.static-review-transfer'
encoded = ''.join(''.join(p.read_text().split()) for p in sorted(transfer.glob('part-*.b64')))
# Repair transport transcription only; the complete decoded payload and every
# source before/after image must still match independently recorded hashes.
for old, new in [('pSbclNe3', 'pSbclVe3'), ('Flzjq5prFluj', 'Flzjq5prluj'),
                 ('ULa9S1cUdc+', 'ULa9S1cU9+'), ('aaWhVcAsz1ca2', 'aWhVcAsz1ca2')]:
    encoded = encoded.replace(old, new)
raw = zlib.decompress(base64.b64decode(encoded))
assert hashlib.sha256(raw).hexdigest() == '7cc4a6c3be7b057cf60ed7bb3413d3633a0f6cd5e8b5716b7e14357d2a4908f5'
payload = json.loads(raw)
proof_path = root / 'docs/testing/airfield-build-inputs-20260923.json'
proof = json.loads(proof_path.read_text())
def sha(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()
manifest_before = (root / 'navgraphs/manifest.json').read_bytes()
for rec in payload['changes']:
    target = root / rec['path']
    data = target.read_bytes().replace(b'\r\n', b'\n')
    assert sha(data) == rec['before'], rec['path']
    lines = data.decode('utf-8').splitlines(True)
    for first, last, replacement in reversed(rec['edits']):
        lines[first:last] = [replacement]
    updated = ''.join(lines).encode('utf-8')
    assert sha(updated) == rec['after'], rec['path']
    target.write_bytes(updated)
for path, text in payload['files'].items():
    target = root / path
    assert not target.exists(), path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
for rec in payload['changes']:
    proof['runtime_source_sha256_lf'][rec['path']] = rec['after']
    found = False
    for old in proof['changed_files']:
        if old['path'] == rec['path']:
            old['sha256'] = rec['after']
            found = True
    if not found:
        proof['changed_files'].append({'path': rec['path'], 'sha256': rec['after']})
proof['global_static_review_removal'] = {
    'baseline': 'dcbc5b686bb8f522175fc80d38cade4f756ccca6',
    'changes': [{k: v for k, v in rec.items() if k != 'edits'} for rec in payload['changes']],
    'all_maps_rebaked': False, 'native_gameplay_tested': False}
for path, expected in proof['runtime_source_sha256_lf'].items():
    assert sha((root / path).read_bytes()) == expected, path
assert len(proof['runtime_source_sha256_lf']) == 139
assert (root / 'navgraphs/manifest.json').read_bytes() == manifest_before
for rec in json.loads(manifest_before)['maps']:
    assert hashlib.sha256((root / 'navgraphs' / rec['file']).read_bytes()).hexdigest() == rec['sha256']
proof_path.write_text(json.dumps(proof, sort_keys=True, indent=2) + '\n')
readme = root / 'README.md'
text = readme.read_text()
text += '\n### Static navigation review removal test\n\nThis test branch removes broad native static-edge review and its live missing-cell/link repair machinery for every map. The rebuilt Airfield graph is retained; the other 40 graphs are unchanged and are not represented as newly baked. Local displaced-hull connector checks, moving-vehicle avoidance, wreck costs, per-Bot contact recovery and final physical collision remain. Native gameplay and performance require testing on the exact client.\n'
readme.write_text(text)
subprocess.run(['git', 'add', 'src', 'tools/test_immutable_navigation.py', 'tools/verify_immutable_build.py', str(proof_path), 'README.md'], check=True)
subprocess.run(['git', 'rm', '.static-review-transfer/apply.py', '.static-review-transfer/part-00.b64', '.static-review-transfer/part-01.b64'], check=True)
print('Integrated four runtime deletions and verification; all 41 graph assets unchanged.')
