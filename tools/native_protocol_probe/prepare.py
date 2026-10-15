"""Fetch the pinned experiment codec; normalize its SSH-only submodule URL."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / '.deps' / 'wg-toolkit'
REVISION = '5b879f0b960ccb4a3b799ede952256e253ef74cb'


def prepare():
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    if not REFERENCE.exists():
        subprocess.run([
            'git', 'clone', '--no-checkout',
            'https://github.com/theorzr/wg-toolkit-rs.git', str(REFERENCE),
        ], check=True)
        subprocess.run(['git', '-C', str(REFERENCE), 'checkout', '--detach',
                        REVISION], check=True)
    actual = subprocess.check_output([
        'git', '-C', str(REFERENCE), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        raise SystemExit('Existing codec checkout is not the pinned revision')
    subprocess.run([
        'git', '-C', str(REFERENCE), 'config', 'submodule.serde-pickle.url',
        'https://github.com/mindstorm38/serde-pickle.git'], check=True)
    subprocess.run(['git', '-C', str(REFERENCE), 'submodule', 'update',
                    '--init', 'serde-pickle'], check=True)
    print('Prepared pinned Mercury codec:', REFERENCE)


if __name__ == '__main__':
    prepare()
