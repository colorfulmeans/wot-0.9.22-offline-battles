"""Apply only the reviewed six-line runtime change, then refresh build proof."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

BASE = '5e2ee54bd736593ec28aeee7549059fee5cd265f'
NAV = 'src/res/scripts/client/gui/mods/offline_lan_0922/ai/navigation.py'
OLD = '42b130474f5ceee8f39028ef4720198fc935ee17348017071f54b56af1ad8d2f'
NEW = '588500101e66df3d7e9306649c13a72848cd851461af2dec15fddcb4ef387e4b'
proof_path = Path('docs/testing/airfield-build-inputs-20260923.json')
proof = json.loads(proof_path.read_text())
for rel, expected in proof['runtime_source_sha256_lf'].items():
    assert hashlib.sha256(Path(rel).read_bytes().replace(b'\r\n', b'\n')).hexdigest() == expected, rel
p = Path(NAV)
data = p.read_bytes()
assert hashlib.sha256(data).hexdigest() == OLD
needle = b'\t\tif not self.prebaked or not callable(self.obstacle_probe):\n'
start = data.index(b'\tdef review_native_corridor(')
pos = data.index(needle, start)
addition = (b'\t\t# A clean offline graph must not be reclassified by the legacy flat\n'
    b'\t\t# corridor rays. Their lateral lanes reuse centre-line heights and can\n'
    b'\t\t# intersect rising side terrain. Keep dynamic hull/contact penalties\n'
    b'\t\t# separate; physical movement still owns the final collision checks.\n'
    b'\t\tif self._static_topology_complete:\n'
    b'\t\t\treturn False\n')
data = data[:pos] + addition + data[pos:]
assert hashlib.sha256(data).hexdigest() == NEW
p.write_bytes(data)
proof['runtime_source_sha256_lf'][NAV] = NEW
for record in proof['changed_files']:
    if record['path'] == NAV:
        record['sha256'] = NEW
proof['review_gate_followup'] = {
    'base_commit': BASE, 'source_report': 'wot-error-report-20260923-131201-9b6d65c11a80.zip',
    'only_runtime_change': NAV, 'before_sha256': OLD, 'after_sha256': NEW,
    'runtime_added_lines': 6, 'graph_changed': False, 'native_gameplay_tested': False}
proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + '\n')
# Extend the existing bytecode/distribution verifier; never substitute a source
# import for the additional compiled production-entry regression.
v = Path('tools/verify_airfield_test_build.py')
text = v.read_text()
blob = v.read_bytes()
assert hashlib.sha1(b'blob ' + str(len(blob)).encode() + b'\0' + blob).hexdigest() == '302307d8f99883a5c99f3fc85c146640df864335'
text = text.replace('import shutil\n', 'import shutil\nimport subprocess\n', 1)
needle = "        save(os.path.join(ROOT, 'dist', 'airfield-bytecode-verification.json'), result)"
assert text.count(needle) == 1
insert = """        review_output = os.path.join(ROOT, 'dist', 'airfield-review-entry-verification.json')
        subprocess.check_call([sys.executable, os.path.join(ROOT, 'tools',
            'test_airfield_review_gate.py'), '--package', '--output', review_output], cwd=ROOT)
        review = json.loads(read(review_output))
        assert review['passed'] and review['mode'] == 'bytecode'
        assert review['wotmod_sha256'] == result['wotmod_sha256']
        result['review_entry_verification'] = review
"""
text = text.replace(needle, insert + needle, 1)
needle = "    save(os.path.join(app_root, 'AIRFIELD_BUILD_EVIDENCE.json'), result)"
assert text.count(needle) == 1
insert = """    review = compiled['review_entry_verification']
    assert review['passed'] and review['tests_run'] == 7 and len(review['paths']) == 30
    assert review['wotmod_sha256'] == sha(wotmod)
    result['review_entry_verification'] = review
    save(os.path.join(app_root, 'AIRFIELD_REVIEW_ENTRY_TESTS.json'), review)
    with open(os.path.join(app_root, 'REVIEW_GATE_TEST_NOTES.txt'), 'wb') as stream:
        stream.write(b'Airfield review-gate follow-up TEST BUILD.\\n'
            b'Based on 5e2ee54b; only ai/navigation.py changes at runtime (six added lines).\\n'
            b'The existing clean Airfield graph no longer enters legacy broad native edge review.\\n'
            b'Other maps, final physical collisions, traffic and recovery logic are unchanged.\\n'
            b'Source and compiled production-entry tests are not native driving tests.\\n'
            b'Tiger/north-side stalls and performance still require Windows gameplay testing.\\n')
"""
text = text.replace(needle, insert + needle, 1)
v.write_text(text)
Path('build-evidence').mkdir(exist_ok=True)
subprocess.check_call([sys.executable, 'tools/test_airfield_review_gate.py',
    '--output', 'build-evidence/review-source-verification.json'])
# Remove only this task's transfer file; permanent tests/verifier remain.
subprocess.check_call(['git', 'rm', '--', '.airfield-transfer/apply.py'])
subprocess.check_call(['git', 'add', NAV, str(proof_path), str(v)])
print('Applied exact six-line review gate; other runtime and map assets retained.')
