"""Prepare the verified 1.1.1 Windows launcher release asset."""
import argparse
import io
import json
from pathlib import Path
import struct
import zipfile
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.1.1'


def pe_machine(data):
    if data[:2] != b'MZ':
        raise ValueError('Missing PE header')
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    if data[offset:offset + 4] != b'PE\0\0':
        raise ValueError('Invalid PE signature')
    return struct.unpack_from('<H', data, offset + 4)[0]


def prepare(launcher, output):
    from verify_launch_entries import verify_archive
    from verify_native_payload import verify_bytes
    launcher, output = Path(launcher), Path(output)
    if pe_machine((launcher / 'wot-0.9.22-offline-battles.exe').read_bytes()) != 0x8664:
        raise ValueError('Launcher must be Windows x64')
    with zipfile.ZipFile(launcher / '_internal/client/0.9.22.zip') as client:
        if client.testzip() is not None:
            raise ValueError('Corrupt client package')
        identity = json.loads(client.read('mods/configs/offline_lan_0922/build_identity.json'))
        if identity['semanticVersion'] != VERSION:
            raise ValueError('Client version does not match release')
        mods = [name for name in client.namelist() if name.endswith('.wotmod')]
        if len(mods) != 1 or not mods[0].endswith('_1.1.1.wotmod'):
            raise ValueError('Incorrect embedded mod')
        with zipfile.ZipFile(io.BytesIO(client.read(mods[0]))) as mod:
            if any(name.rsplit('/', 1)[-1] in ('roof_crush_test.py', 'roof_crush_test.pyc') for name in mod.namelist()):
                sources = [name for name in mod.namelist() if name.endswith('/roof_crush_test.py')]
                if not sources or b"WOT_OFFLINE_DIAGNOSTICS" not in mod.read(sources[0]):
                    raise ValueError('Ungated development scenario is embedded in the mod')
            if mod.testzip() is not None or ElementTree.fromstring(mod.read('meta.xml')).findtext('version') != VERSION:
                raise ValueError('Incorrect mod metadata or CRC')
        native = client.read('mods/0.9.22.0.1/offline_math_batch_native.pyd')
        if pe_machine(native) != 0x14c:
            raise ValueError('Game extension must remain x86')
        verify_bytes(str(ROOT), native)
    output.mkdir(parents=True, exist_ok=True)
    assets = []
    package = output / 'wot-0.9.22-offline-battles-1.1.1-Windows-x64.zip'
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(launcher.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(launcher).as_posix())
    with zipfile.ZipFile(package) as archive:
        if archive.testzip() is not None:
            raise ValueError('Corrupt launcher ZIP')
        verify_archive(archive)
    assets.append(package)
    actual = {p.name for p in output.iterdir() if p.is_file()}
    if len(assets) != 1 or actual != {p.name for p in assets}:
        raise ValueError('Release must contain exactly one verified launcher ZIP')
    print(json.dumps({'version': VERSION, 'build': identity, 'assets':
                     [{'name': p.name, 'size': p.stat().st_size} for p in assets]}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    prepare(args.launcher, args.output)
