"""Validate chunk preparation using complete CPython 2.7/x86 host builds.

Reuse the established compiler, PE auditor and baseline comparison machinery.
Only a successful complete run permits runtime/binary publication together.
"""
from pathlib import Path
import difflib
import json
import os
import shutil
import sys
import tarfile
import build_verify_native_migration as h


def main():
    h.OUT.mkdir(parents=True, exist_ok=True)
    h.REPORT.update(runtime_baseline=os.environ['VALIDATION_BASELINE_SHA'],
                    migration='destructible_chunk_preparation', passed=False)
    try:
        assert not h.BASE.exists(), 'use a fresh disposable validation tree'
        shutil.copytree(h.ROOT,h.BASE,symlinks=True,
            ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc','*.pyo','build','dist'))
        h.run('toolchain',[h.PY27,'-B','-c',
            "import sys,struct,sysconfig,math,zlib,bz2,ctypes; assert sys.version_info[:3]==(2,7,18); assert struct.calcsize('P')==4; assert '-mfpmath=sse' in sysconfig.get_config_var('CFLAGS'); print(sys.version); print('pointer bytes:',struct.calcsize('P')); print(sysconfig.get_config_var('CFLAGS'))"])
        # The preceding chunk-planning conformance group needs its native
        # test-only Vector3 fixture. It is never part of the shipping module.
        vector = h.OUT/'native_chunk_vector.so'
        h.run('compile-test-only-vector',['g++','-m32','-std=c++17','-O2',
            '-msse2','-mfpmath=sse','-shared','-fPIC','-fno-fast-math','-ffp-contract=off',
            '-I/opt/python27/include/python2.7',
            h.ROOT/'tools/check_native_destructible_chunks_vector.cpp','-o',vector])
        os.environ['WOT_NATIVE_CHUNK_VECTOR'] = str(vector)
        old = h.build_host(h.BASE,'baseline')
        h.REPORT['baseline_native'] = h.native_groups(h.BASE,'baseline',old)
        failed = [r['name'] for r in h.REPORT['baseline_native'] if r['returncode']]
        assert not failed, ('baseline native failures',failed)
        patterns = h.PATTERNS + ['test*destruct*.py','test*tree*.py','test*falling*.py']
        paths = sorted(set(p for pattern in patterns for p in (h.ROOT/'tests').glob(pattern)))
        assert len(paths) >= 73, ('insufficient reference coverage',len(paths))
        h.run('apply-integration',['/usr/bin/python3',h.ROOT/'tools/apply_native_destructible_prepare_migration.py',h.OUT/'changed-paths.json'])
        compile_code = "import os; paths=sorted(os.path.join(b,n) for b,d,fs in os.walk('src/res/scripts/client') for n in fs if n.endswith('.py')); assert len(paths)>=180,len(paths); [compile(open(p,'rb').read(),p,'exec') for p in paths]; print('CPython 2.7 source compile:',len(paths))"
        h.run('current/compile-client-sources',[h.PY27,'-B','-c',compile_code])
        new = h.build_host(h.ROOT,'current')
        unused, text = h.run('current/destructible-preparation-contract',
            [h.PY27,'-B',h.ROOT/'tools/check_native_destructible_prepare.py',new])
        prefix = 'Destructible preparation conformance:'
        line = next(line for line in text.splitlines() if line.startswith(prefix))
        h.REPORT['migration_checks'] = json.loads(line[len(prefix):].strip())
        print(line,flush=True)
        h.REPORT['current_native'] = h.native_groups(h.ROOT,'current',new)
        failed = [r['name'] for r in h.REPORT['current_native'] if r['returncode']]
        assert not failed, ('current native failures',failed)
        h.run('current/build-shipping-x86',['sh',h.ROOT/'tools/build_math_batch_native.sh'],timeout=1200)
        shipping = h.ROOT/'native/offline_math_batch_native.pyd'
        h.audit_pe(shipping)
        shutil.copy2(shipping,h.OUT/'current/offline_math_batch_native.pyd')
        h.REPORT['baseline_reference'] = h.python_tests(h.BASE,'baseline',paths)
        h.REPORT['current_reference'] = h.python_tests(h.ROOT,'current',paths)
        regressions = []
        for name, row in h.REPORT['current_reference'].items():
            baseline = h.REPORT['baseline_reference'][name]
            if row['tests'] != baseline['tests']:
                regressions.append((name,'test count',baseline['tests'],row['tests']))
            if row['returncode'] and (
                    row['failures'] != baseline['failures'] or
                    row['exception_messages'] != baseline['exception_messages'] or
                    not baseline['returncode']):
                regressions.append((name,baseline['failures'],row['failures']))
        h.REPORT['new_reference_failures'] = regressions
        assert not regressions, ('new reference regressions',regressions)
        h.run('current/incremental-benchmark',[h.PY27,'-B',
            h.ROOT/'tools/benchmark_native_destructible_prepare.py',new,
            h.OUT/'incremental-benchmark.json'])
        h.REPORT['component_timings'] = json.loads((h.OUT/'incremental-benchmark.json').read_text())
        changed = json.loads((h.OUT/'changed-paths.json').read_text())
        diff = []
        for name in changed:
            if name.endswith('.pyd'):
                continue
            before = (h.BASE/name).read_text().splitlines(True)
            after = (h.ROOT/name).read_text().splitlines(True)
            diff.extend(difflib.unified_diff(before,after,'a/'+name,'b/'+name))
        (h.OUT/'integration.patch').write_text(''.join(diff))
        with tarfile.open(h.OUT/'validated-source.tar.gz','w:gz') as archive:
            for path in sorted(h.ROOT.rglob('*')):
                relative = path.relative_to(h.ROOT)
                if (path.is_file() and '.git' not in relative.parts and
                        '__pycache__' not in relative.parts and path.suffix not in ('.pyc','.pyo')):
                    archive.add(path,arcname=str(relative),recursive=False)
        h.REPORT['reference_files'] = len(paths)
        h.REPORT['reference_tests'] = sum(r['tests'] for r in h.REPORT['current_reference'].values())
        h.REPORT['retained_baseline_failures'] = {
            name:row['failures'] for name,row in h.REPORT['current_reference'].items() if row['returncode']}
        h.REPORT['passed'] = True
        summary = {key:h.REPORT[key] for key in ('validation_source','runtime_baseline',
            'passed','shipping','migration_checks','component_timings','reference_files',
            'reference_tests','retained_baseline_failures','new_reference_failures')}
        print('NATIVE_DESTRUCTIBLE_MIGRATION_SUMMARY '+json.dumps(summary,sort_keys=True),flush=True)
    except Exception as error:
        h.REPORT['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        (h.OUT/'report.json').write_text(json.dumps(h.REPORT,indent=2,sort_keys=True)+'\n')


if __name__ == '__main__':
    main()
