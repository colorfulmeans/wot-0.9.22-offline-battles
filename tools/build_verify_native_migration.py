"""Build, exercise and audit the complete current native extension.

Run inside the isolated native-build environment with this checkout at
/work/repo. Publish integration and the matching shipping binary only after
all native contracts pass and no reference regression is new. A 32-bit
CPython 2.7.18 host is not the embedded #1513 Windows game runtime.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import ast
import difflib
import json
import os
import re
import shutil
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
WORK, OUT, BASE = ROOT.parent, ROOT.parent / 'out', ROOT.parent / 'baseline'
PY27 = '/opt/python27/bin/python2.7'
SOURCES = [
    'offline_math_batch_geometry.cpp', 'offline_async_worker.cpp',
    'offline_navigation.cpp', 'native_visibility_core.cpp',
    'offline_visibility.cpp', 'offline_contact_roster.cpp',
    'offline_destructible_geometry.cpp', 'world_stage.cpp',
    'navigation_query_stage.cpp', 'offline_simulation.cpp',
    'offline_simulation_control.cpp', 'offline_simulation_motion.cpp',
    'offline_simulation_weapons.cpp', 'offline_simulation_navigation.cpp',
    'offline_math_batch_native.cpp']
FP = ['-fno-fast-math', '-ffp-contract=off', '-fno-builtin-sin',
      '-fno-builtin-cos', '-fno-builtin-pow', '-fno-builtin-hypot', '-fno-builtin-fmod']
NATIVE = [
    ('check_native_driver_geometry.py', False), ('check_native_driver_aim.py', False),
    ('check_native_math.py', True), ('check_native_release_math.py', False),
    ('check_native_release_ground.py', False), ('check_native_release_suspension.py', False),
    ('check_native_rotation_current.py', False), ('check_native_workers.py', True),
    ('check_native_contacts.py', True), ('check_native_world.py', True),
    ('check_native_world_segments.py', False), ('check_native_turn_world.py', False),
    ('check_native_world_pipeline.py', False), ('check_native_navigation_query.py', False),
    ('check_native_simulation.py', True), ('check_native_simulation_weapons.py', True),
    ('check_native_destructibles.py', False), ('check_native_visibility_frontier.py', False),
    ('check_native_simulation_diagnostics.py', False),
]
PATTERNS = [
    'test_port_0922_ai.py', 'test_port_0922_eroded_fallback_cycle.py',
    'test_port_0922_initial_allocation.py', 'test_port_0922_navigation*.py',
    'test_port_0922_driver*.py', 'test_port_0922_traffic*.py',
    'test_port_0922_bot*.py', 'test_port_0922_contact*.py',
    'test_port_0922_wreck*.py', 'test_port_0922_artillery*.py',
    'test_port_0922_spg*.py', 'test_port_0922_downhill*.py',
    'test_port_0922_parking*.py', 'test_port_0922_withdrawal*.py',
    'test_port_0922_gun_angle*.py', 'test_port_0922_wait_parking.py',
    'test_port_0922_server_bot_ai.py', 'test_port_0922_projectile_manager.py',
    'test_port_0922_projectile_runtime.py', 'test_port_0922_battle_projectiles.py',
    'test_internal_mesh*.py', 'test_port_0922_decoded_interior.py',
    'test_port_0922_worker_diagnostics.py', 'test_port_0922_battle_visibility.py',
    'test_port_0922_tactical_radio*.py', 'test_port_0922_team*.py',
    'test_native_input_diagnostics.py',
]
REPORT = {'validation_source': os.environ.get('VALIDATION_SOURCE_SHA'),
          'runtime_baseline': '53b7561577cd68eacf4cdfa848d07b460db4ae92',
          'game_acceptance': False, 'commands': [], 'passed': False}


def env_for(root):
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0',
               WOT_NATIVE_BASELINE=str(BASE))
    env['PYTHONPATH'] = os.pathsep.join(str(root / p) for p in
        ('tools', 'tests', 'server', 'src/res/scripts/client'))
    return env


def run(name, command, root=ROOT, timeout=900, required=True):
    path = OUT / (name + '.log')
    path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    print('RUN', name, ' '.join(str(p) for p in command), flush=True)
    try:
        with path.open('wb') as log:
            process = subprocess.run([str(p) for p in command], cwd=str(root),
                env=env_for(root), stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        code = process.returncode
    except subprocess.TimeoutExpired:
        code = 124
        with path.open('ab') as log:
            log.write(b'\nVALIDATION TIMEOUT\n')
    text = path.read_text(errors='replace')
    row = {'name': name, 'command': [str(p) for p in command], 'cwd': str(root),
           'returncode': code, 'seconds': round(time.monotonic() - start, 3),
           'log': str(path.relative_to(OUT))}
    REPORT['commands'].append(row)
    print('RESULT', name, code, row['seconds'], flush=True)
    if name in ('toolchain', 'current/new-driver-mesh-contract', 'current/compile-client-sources'):
        print(text[-8000:], flush=True)
    if code:
        print(text[-14000:], flush=True)
        if required:
            raise RuntimeError('Required gate failed: ' + name)
    return row, text


def build_host(root, label):
    output = OUT / label / 'offline_math_batch_native.so'
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = ['g++', '-m32', '-std=c++17', '-O3', '-msse2', '-mfpmath=sse',
           '-fPIC', '-shared', '-pthread', '-DWOT_HOST_PYTHON',
           '-I/opt/python27/include/python2.7'] + FP
    cmd += [str(root / 'native' / source) for source in SOURCES]
    cmd += ['-o', str(output)]
    run(label + '/compile-full-host', cmd, root, timeout=1200)
    data = output.read_bytes()
    assert data[:4] == b'\x7fELF' and data[4] == 1, 'host extension must be ELF32'
    return output


def native_groups(root, label, host):
    records = []
    for name, needs_scripts in NATIVE:
        cmd = [PY27, '-B', root / 'tools' / name, host]
        if needs_scripts:
            cmd.append(root / 'src/res/scripts/client')
        records.append(run(label + '/' + name[:-3], cmd, root, required=False)[0])
    control = [PY27, '-B', root / 'tools/check_native_simulation_control.py',
               '--extension', host, '--client-scripts', root / 'src/res/scripts/client']
    records.append(run(label + '/check_native_simulation_control', control, root, required=False)[0])
    return records


def python_tests(root, label, paths):
    def one(path):
        row, text = run(label + '/reference/' + path.stem,
            ['/usr/bin/python3', '-m', 'unittest', 'discover', '-s', 'tests',
             '-p', path.name, '-v'], root, timeout=600, required=False)
        failures = re.findall(r'^(?:FAIL|ERROR): (.+)$', text, re.MULTILINE)
        messages = re.findall(r'^(?:AssertionError|[A-Za-z]+Error): .+$', text, re.MULTILINE)
        count = re.search(r'^Ran (\d+) tests? in ', text, re.MULTILINE)
        row.update(tests=int(count.group(1)) if count else 0,
                   failures=sorted(failures), exception_messages=sorted(messages))
        if row['returncode'] and not failures:
            row['failures'] = ['PROCESS_FAILURE_' + str(row['returncode'])]
        return path.name, row
    with ThreadPoolExecutor(max_workers=3) as executor:
        return dict(executor.map(one, paths))


def audit_pe(path):
    raw = path.read_bytes()
    assert raw[:2] == b'MZ'
    header = struct.unpack_from('<I', raw, 0x3c)[0]
    assert raw[header:header + 4] == b'PE\0\0'
    machine = struct.unpack_from('<H', raw, header + 4)[0]
    assert machine == 0x14c, ('expected x86 PE', machine)
    _, text = run('current/shipping-pe-audit', ['i686-w64-mingw32-objdump', '-p', path])
    imports = re.findall(r'DLL Name: (\S+)', text)
    assert imports, 'no PE import evidence'
    for name in imports:
        assert name in ('KERNEL32.dll', 'msvcrt.dll') or re.match(r'api-ms-win-crt-.*\.dll$', name), name
    assert '[Ordinal/Name Pointer] Table' in text, 'export table missing'
    names = []
    suffix = text.split('[Ordinal/Name Pointer] Table', 1)[1]
    for line in suffix.splitlines():
        match = re.match(r'\s*\[\s*\d+\]\s+(\S+)\s*$', line)
        if match:
            names.append(match.group(1))
        elif names and not line.strip():
            break
    assert names == ['initoffline_math_batch_native'], ('unexpected exports', names)
    path.chmod(0o755)
    REPORT['shipping'] = {'bytes': len(raw), 'machine': '0x014c',
                          'imports': imports, 'exports': names, 'mode': '100755'}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        assert not BASE.exists(), 'baseline already exists; use a fresh validation checkout'
        shutil.copytree(ROOT, BASE, symlinks=True,
            ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc', '*.pyo', 'build', 'dist'))
        run('toolchain', [PY27, '-B', '-c',
            "import sys,struct,sysconfig,math,zlib,bz2,ctypes; assert sys.version_info[:3]==(2,7,18); assert struct.calcsize('P')==4; print(sys.version); print('pointer bytes:',struct.calcsize('P')); print(sysconfig.get_config_var('CFLAGS'))"])
        baseline_host = build_host(BASE, 'baseline')
        REPORT['baseline_native'] = native_groups(BASE, 'baseline', baseline_host)
        failures = [r['name'] for r in REPORT['baseline_native'] if r['returncode']]
        if failures:
            raise RuntimeError('Baseline native gates failed: ' + ', '.join(failures))
        paths = sorted(set(p for pattern in PATTERNS for p in (ROOT / 'tests').glob(pattern)))
        assert len(paths) >= 25, ('too few regression files', len(paths))
        REPORT['baseline_reference'] = python_tests(BASE, 'baseline', paths)
        run('apply-integration', ['/usr/bin/python3', ROOT / 'tools/apply_native_driver_mesh_migration.py',
                                 OUT / 'changed-paths.json'])
        compile_code = "import os; paths=sorted(os.path.join(b,n) for b,d,fs in os.walk('src/res/scripts/client') for n in fs if n.endswith('.py')); assert len(paths)>=179,len(paths); [compile(open(p,'rb').read(),p,'exec') for p in paths]; print('CPython 2.7 source compile:',len(paths))"
        run('current/compile-client-sources', [PY27, '-B', '-c', compile_code])
        current_host = build_host(ROOT, 'current')
        _, text = run('current/new-driver-mesh-contract', [PY27, '-B',
            ROOT / 'tools/check_native_driver_mesh_migration.py', current_host])
        for prefix, key in (('Current driver/mesh conformance:', 'migration_checks'),
                            ('Complete consumer reference/native seconds:', 'component_timings')):
            line = next((line for line in text.splitlines() if line.startswith(prefix)), None)
            assert line is not None, ('missing contract summary', prefix)
            REPORT[key] = ast.literal_eval(line[len(prefix):].strip())
        REPORT['current_native'] = native_groups(ROOT, 'current', current_host)
        failures = [r['name'] for r in REPORT['current_native'] if r['returncode']]
        if failures:
            raise RuntimeError('Current native gates failed: ' + ', '.join(failures))
        REPORT['current_reference'] = python_tests(ROOT, 'current', paths)
        new_failures = {}
        for name, current in REPORT['current_reference'].items():
            old = REPORT['baseline_reference'][name]
            extra = sorted(set(current['failures']) - set(old['failures']))
            if extra or (not old['returncode'] and current['returncode']):
                new_failures[name] = extra or ['nonzero return code']
            if current['tests'] < old['tests']:
                new_failures.setdefault(name, []).append('test count decreased')
            if current['returncode'] and current['exception_messages'] != old['exception_messages']:
                new_failures.setdefault(name, []).append('failure exception evidence changed')
        REPORT['new_reference_failures'] = new_failures
        if new_failures:
            raise RuntimeError('New reference regressions: ' + repr(new_failures))
        run('current/build-shipping-x86', ['sh', ROOT / 'tools/build_math_batch_native.sh'], timeout=1200)
        shipping = ROOT / 'native/offline_math_batch_native.pyd'
        audit_pe(shipping)
        shutil.copy2(shipping, OUT / 'current/offline_math_batch_native.pyd')
        changed = json.loads((OUT / 'changed-paths.json').read_text())
        diff = []
        for name in changed:
            if name.endswith('.pyd'):
                continue
            before, after = (BASE / name).read_text().splitlines(True), (ROOT / name).read_text().splitlines(True)
            diff.extend(difflib.unified_diff(before, after, 'a/' + name, 'b/' + name))
        (OUT / 'integration.patch').write_text(''.join(diff))
        REPORT['reference_files'] = len(paths)
        REPORT['reference_tests'] = sum(r['tests'] for r in REPORT['current_reference'].values())
        REPORT['retained_baseline_failures'] = {
            name: row['failures'] for name, row in REPORT['current_reference'].items() if row['returncode']}
        REPORT['passed'] = True
        summary = dict((key, REPORT[key]) for key in
            ('validation_source', 'passed', 'shipping', 'reference_files', 'reference_tests',
             'retained_baseline_failures', 'migration_checks', 'component_timings'))
        print('NATIVE_MIGRATION_SUMMARY ' + json.dumps(summary, sort_keys=True), flush=True)
    except Exception as error:
        REPORT['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        (OUT / 'report.json').write_text(json.dumps(REPORT, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
