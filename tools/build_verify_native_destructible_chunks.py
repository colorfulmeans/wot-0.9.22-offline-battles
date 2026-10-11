"""Validate/publish chunk planning against the unchanged preceding runtime.

Reuse the established full 32-bit host, strict Win32 build and PE audit. The
Vector3 fixture is separate test code, never part of the shipped extension.
"""
from pathlib import Path
import ast
import difflib
import json
import os
import shutil
import tarfile
import traceback

import build_verify_native_migration as gate

ROOT, BASE, OUT = gate.ROOT, gate.BASE, gate.OUT
PATTERNS = [
    'test_port_0922_destructibles*.py', 'test_port_0922_tree*.py',
    'test_port_0922_bot_destructible_approach.py',
    'test_port_0922_planning_destructible_overlap.py',
    'test_port_0922_navigation_destructibles.py', 'test_port_0922_vehicle_collision_flags.py',
    'test_port_0922_battle_projectiles.py', 'test_port_0922_projectile*.py',
    'test_port_0922_tactical_radio*.py', 'test_port_0922_team*.py',
    'test_port_0922_parking*.py', 'test_port_0922_wait_parking.py',
    'test_native_input_diagnostics.py', 'test_port_0922_worker_diagnostics.py',
    'test_port_0922_contact_motion.py', 'test_port_0922_traffic*.py',
]


def verify_oracle():
    path = 'src/res/scripts/client/gui/mods/offline_lan_0922/destructibles_sensor.py'
    before, after = [ast.parse((root / path).read_text()) for root in (BASE, ROOT)]
    current = {node.name: node for node in after.body if isinstance(node, ast.FunctionDef)}
    count = 0
    for original in before.body:
        if not isinstance(original, ast.FunctionDef):
            continue
        name = original.name
        if name == '_tree_motion_required_chunks_1513':
            original.name = '_reference_tree_motion_required_chunks_1513'
        assert ast.dump(original) == ast.dump(current[original.name]), ('changed original law', name)
        count += 1
    gate.REPORT['unchanged_sensor_functions'] = count


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gate.REPORT.update(runtime_baseline='49cde52953a569a40becab29df5468f8a6ce477e',
                       batch='destructible-required-chunks', game_acceptance=False)
    try:
        assert not BASE.exists(), 'use a fresh disposable validation directory'
        shutil.copytree(ROOT, BASE, symlinks=True,
            ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc', '*.pyo', 'build', 'dist'))
        gate.run('toolchain', [gate.PY27, '-B', '-c',
            "import sys,struct,sysconfig; assert sys.version_info[:3]==(2,7,18); assert struct.calcsize('P')==4; assert '-mfpmath=sse' in sysconfig.get_config_var('CFLAGS'); print(sys.version); print('pointer bytes:',struct.calcsize('P')); print(sysconfig.get_config_var('CFLAGS'))"])
        vector = OUT / 'native_chunk_vector.so'
        gate.run('compile-test-only-vector', ['g++', '-m32', '-std=c++17', '-O2',
            '-msse2', '-mfpmath=sse', '-shared', '-fPIC', '-fno-fast-math', '-ffp-contract=off',
            '-I/opt/python27/include/python2.7', ROOT/'tools/check_native_destructible_chunks_vector.cpp',
            '-o', vector])
        os.environ['WOT_NATIVE_CHUNK_VECTOR'] = str(vector)
        baseline_host = gate.build_host(BASE, 'baseline')
        gate.REPORT['baseline_native'] = gate.native_groups(BASE, 'baseline', baseline_host)
        assert not any(row['returncode'] for row in gate.REPORT['baseline_native']), 'baseline native failure'
        gate.run('apply-chunk-integration', ['/usr/bin/python3',
            ROOT/'tools/apply_native_destructible_chunks.py', OUT/'changed-paths.json'])
        verify_oracle()
        code = "import os; paths=sorted(os.path.join(b,n) for b,d,fs in os.walk('src/res/scripts/client') for n in fs if n.endswith('.py')); assert len(paths)>=180,len(paths); [compile(open(p,'rb').read(),p,'exec') for p in paths]; print('CPython 2.7 source compile:',len(paths))"
        gate.run('current/compile-client-sources', [gate.PY27, '-B', '-c', code])
        current_host = gate.build_host(ROOT, 'current')
        _, text = gate.run('current/new-chunk-contract', [gate.PY27, '-B',
            ROOT/'tools/check_native_destructible_chunks.py', current_host])
        prefix = 'Destructible required-chunk conformance:'
        line = next(line for line in text.splitlines() if line.startswith(prefix))
        gate.REPORT['chunk_checks'] = ast.literal_eval(line[len(prefix):].strip())
        gate.REPORT['current_native'] = gate.native_groups(ROOT, 'current', current_host)
        assert not any(row['returncode'] for row in gate.REPORT['current_native']), 'current native failure'
        paths = sorted(set(path for pattern in PATTERNS for path in (ROOT/'tests').glob(pattern)))
        assert len(paths) >= 18, ('incomplete regression selection', len(paths))
        gate.REPORT['baseline_reference'] = gate.python_tests(BASE, 'baseline', paths)
        gate.REPORT['current_reference'] = gate.python_tests(ROOT, 'current', paths)
        new_failures = []
        for name, current in gate.REPORT['current_reference'].items():
            previous = gate.REPORT['baseline_reference'][name]
            if (current['tests'] != previous['tests'] or
                    current['failures'] != previous['failures'] or
                    current['exception_messages'] != previous['exception_messages'] or
                    current['returncode'] != previous['returncode']):
                new_failures.append(name)
        gate.REPORT['new_reference_failures'] = new_failures
        assert not new_failures, ('changed regression outcomes', new_failures)
        gate.run('incremental-benchmark', [gate.PY27, '-B',
            ROOT/'tools/benchmark_native_destructible_chunks.py', current_host,
            OUT/'incremental-benchmark.json'])
        gate.REPORT['benchmark'] = json.loads((OUT/'incremental-benchmark.json').read_text())
        gate.run('current/build-shipping-x86', ['sh', ROOT/'tools/build_math_batch_native.sh'], timeout=1200)
        shipping = ROOT/'native/offline_math_batch_native.pyd'
        gate.audit_pe(shipping)
        shutil.copy2(shipping, OUT/'current/offline_math_batch_native.pyd')
        manifest = json.loads((OUT/'changed-paths.json').read_text())
        patch = []
        for name in manifest:
            if name.endswith('.pyd'):
                continue
            patch.extend(difflib.unified_diff((BASE/name).read_text().splitlines(True),
                (ROOT/name).read_text().splitlines(True), fromfile='a/'+name, tofile='b/'+name))
        (OUT/'integration.patch').write_text(''.join(patch))
        # A source snapshot makes the exact validated tree reusable without
        # packaging a launcher/mod. No credentials or local git directory.
        with tarfile.open(OUT/'validated-source.tar.gz', 'w:gz') as archive:
            for path in sorted(ROOT.rglob('*')):
                relative = path.relative_to(ROOT)
                if (path.is_file() and '.git' not in relative.parts and
                        '__pycache__' not in relative.parts and path.suffix not in ('.pyc', '.pyo')):
                    archive.add(path, arcname=str(relative), recursive=False)
        gate.REPORT['passed'] = True
    except Exception as error:
        gate.REPORT['error'] = str(error)
        traceback.print_exc()
        raise
    finally:
        (OUT/'report.json').write_text(json.dumps(gate.REPORT, indent=2, sort_keys=True) + '\n')
        print('CHUNK_VALIDATION_RESULT', json.dumps({
            'passed': gate.REPORT.get('passed'), 'checks': gate.REPORT.get('chunk_checks'),
            'shipping': gate.REPORT.get('shipping'), 'error': gate.REPORT.get('error')}, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
