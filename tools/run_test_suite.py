"""Run every discovered test file in its own interpreter, retaining failures.

Native-module fakes installed while importing one test module must not become
the dependencies of another module. Isolation is by file, not by assertion:
all tests, failures and unittest skips in each file remain visible.
"""
import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = """
import os, sys, unittest
from pathlib import Path
root=Path(sys.argv[1]); directory=sys.argv[2]; pattern=sys.argv[3]
sys.path[:0]=[str(root), str(root/directory), str(root/'tests'), str(root/'server'),
              str(root/'launcher'), str(root/'src/res/scripts/client')]
os.environ['PYTHONDONTWRITEBYTECODE']='1'
unittest.main(module=None, argv=['unittest','discover','-s',str(root/directory),
                               '-p',pattern,'-v'])
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', choices=('tests', 'launcher/tests'), default='tests')
    parser.add_argument('--pattern', action='append')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--logs', type=Path, default=ROOT/'build/test-results')
    args = parser.parse_args()
    patterns=args.pattern or ['test_*.py']
    matches={pattern:list((ROOT/args.directory).glob(pattern)) for pattern in patterns}
    unmatched=[pattern for pattern in patterns if not matches[pattern]]
    if unmatched:
        parser.error('test patterns matched no files in %s: %s' %
                     (args.directory, ', '.join(unmatched)))
    files=sorted({path for paths in matches.values() for path in paths})
    if not files or args.jobs < 1:
        parser.error('select at least one test file and a positive worker count')
    args.logs.mkdir(parents=True, exist_ok=True)

    def run(path):
        result = subprocess.run(
            [sys.executable, '-B', '-X', 'utf8', '-c', BOOTSTRAP, str(ROOT), args.directory, path.name],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding='utf-8', errors='replace')
        ran = re.search(r'^Ran (\d+) tests?', result.stdout, re.M)
        if ran is None or int(ran.group(1)) == 0:
            result.returncode = result.returncode or 1
            result.stdout += '\nERROR: no_tests_discovered (%s)\n' % path.name
        (args.logs/(path.stem+'.log')).write_text(result.stdout, encoding='utf-8')
        return path, result

    failed, records = [], []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        pending = [pool.submit(run, path) for path in files]
        for future in as_completed(pending):
            path, result = future.result()
            ran = re.search(r'^Ran (\d+) tests?', result.stdout, re.M)
            records.append(dict(file=path.name, returncode=result.returncode,
                tests=int(ran.group(1)) if ran else None,
                issues=re.findall(r'^(?:FAIL|ERROR): (.+)$', result.stdout, re.M),
                skips=re.findall(r'^(.+) \.\.\. skipped (.+)$', result.stdout, re.M)))
            print(('FAIL' if result.returncode else 'PASS')+' '+path.name, flush=True)
            if result.returncode:
                failed.append(path.name)
                # Keep native diagnostic chatter and large source dumps in
                # the artifact; print each failing assertion and its traceback.
                blocks=re.split(r'={60,}\n',result.stdout)
                for block in blocks:
                    if block.startswith(('FAIL:', 'ERROR:')):
                        print(block[:3500],flush=True)
                for line in result.stdout.splitlines():
                    if line.startswith(('Ran ', 'FAILED ', 'OK', 'Traceback')):
                        print(line,flush=True)
                if not any(block.startswith(('FAIL:', 'ERROR:')) for block in blocks):
                    print(result.stdout[-3500:],flush=True)
    # Preserve assertion identities, subtest cases and skips. Equal failure
    # counts between two builds do not establish equal behavior.
    (args.logs/'summary.json').write_text(json.dumps(
        sorted(records, key=lambda row: row['file']), indent=2), encoding='utf-8')
    print('%d files: %d passed, %d failed' % (len(files), len(files)-len(failed), len(failed)))
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
