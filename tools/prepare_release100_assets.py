"""Prepare the verified 1.0.0 launcher and eighteen standalone guide assets."""
import argparse
import io
import json
from pathlib import Path
import re
import struct
import zipfile
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0.0'


def export_guides(output, root=ROOT):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    sources = {language: sorted((Path(root) / 'docs/releases' /
               ('v1.0.0-guides.' + language)).glob('*.md'))
               for language in ('en', 'zh-CN')}
    for language, files in sources.items():
        if len(files) != 9 or [p.name[:2] for p in files] != ['%02d' % i for i in range(1, 10)]:
            raise ValueError('Expected exactly nine ordered guides: ' + language)
    assets = []
    for english, chinese in zip(sources['en'], sources['zh-CN']):
        for path, language in ((english, 'English'), (chinese, 'Chinese')):
            text = path.read_text(encoding='utf-8-sig')
            if not text.startswith('# ') or '\ufffd' in text or '\x00' in text:
                raise ValueError('Invalid guide text: ' + str(path))
            if language == 'English' and re.search('[\u3400-\u9fff]', text):
                raise ValueError('Untranslated English guide: ' + str(path))
            text = re.sub(r'^#{1,6} ', '', text, flags=re.M).replace('**', '').replace('`', '')
            target = output / (english.stem + '-' + language + '.txt')
            target.write_bytes(b'\xef\xbb\xbf' + text.replace('\r\n', '\n').encode('utf-8'))
            assets.append(target)
    return assets


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
        if len(mods) != 1 or not mods[0].endswith('_1.0.0.wotmod'):
            raise ValueError('Incorrect embedded mod')
        with zipfile.ZipFile(io.BytesIO(client.read(mods[0]))) as mod:
            if mod.testzip() is not None or ElementTree.fromstring(mod.read('meta.xml')).findtext('version') != VERSION:
                raise ValueError('Incorrect mod metadata or CRC')
        native = client.read('mods/0.9.22.0.1/offline_math_batch_native.pyd')
        if pe_machine(native) != 0x14c:
            raise ValueError('Game extension must remain x86')
        verify_bytes(str(ROOT), native)
    assets = export_guides(output)
    package = output / 'wot-0.9.22-offline-battles-1.0.0-Windows-x64.zip'
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
    if len(assets) != 19 or actual != {p.name for p in assets}:
        raise ValueError('Release must contain one launcher and eighteen guides')
    print(json.dumps({'version': VERSION, 'build': identity, 'assets':
                     [{'name': p.name, 'size': p.stat().st_size} for p in assets]}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    prepare(args.launcher, args.output)
