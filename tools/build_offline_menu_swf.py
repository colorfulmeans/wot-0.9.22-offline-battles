"""Disable logoff in all four native #1513 menu timeline states.

The native FRAME_CONSTRUCTED inspector rewrites enabled after Python population.
Keep its controls, art, frame scripts and every other enabled property intact.
Native lobby ABCs provide compile-time definitions and are removed unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile
from build_waiting_room_swf import tags, pack

ROOT = Path(__file__).resolve().parents[1]
INPUT_SHA256 = 'ae1d2ff617578395e2a425cf7b502ad92cea7a19631455352f4fdb25245eb027'


def transform(source):
    if source.count('logoffBtn.enabled = true;') != 4:
        raise ValueError('Expected four #1513 logoff timeline initializers')
    return re.sub(r'^\s*\[Embed\([^\n]*\)\]\s*$', '', source, flags=re.M).replace(
        'logoffBtn.enabled = true;', 'logoffBtn.enabled = false;')


def build(client, java, ffdec, output):
    with zipfile.ZipFile(Path(client) / 'res/packages/gui.pkg') as archive:
        original = archive.read('gui/flash/LobbyMenu.swf')
        lobby = archive.read('gui/flash/lobby.swf')
    if hashlib.sha256(original).hexdigest() != INPUT_SHA256:
        raise ValueError('Requires exact Chinese HD #1513 LobbyMenu.swf')
    header, parts = tags(original)
    dependencies = [(code, body) for code, body in tags(lobby)[1] if code == 82]
    dependency_bodies = {body for code, body in dependencies}
    first = next(i for i, (code, body) in enumerate(parts) if code == 82)
    command = [str(java), '-Djava.awt.headless=true', '-jar', str(ffdec)]
    with tempfile.TemporaryDirectory(prefix='wot-native-logoff-') as directory:
        temp = Path(directory)
        source, compiled = temp / 'input.swf', temp / 'compiled.swf'
        source.write_bytes(pack(header, parts[:first] + dependencies + parts[first:]))
        subprocess.run(command + ['-selectclass', 'LobbyMenuUI', '-export', 'script',
            str(temp / 'export'), str(source)], check=True)
        script = temp / 'export/scripts/LobbyMenuUI.as'
        script.write_text(transform(script.read_text(encoding='utf8')), encoding='utf8')
        subprocess.run(command + ['-replace', str(source), str(compiled),
                                   'LobbyMenuUI', str(script)], check=True)
        subprocess.run(command + ['-selectclass', 'LobbyMenuUI', '-export', 'script',
            str(temp / 'verify'), str(compiled)], check=True)
        verified = (temp / 'verify/scripts/LobbyMenuUI.as').read_text(encoding='utf8')
        if verified.count('logoffBtn.enabled = false;') != 4 or 'logoffBtn.enabled = true;' in verified:
            raise ValueError('Compiled menu did not retain all four logoff locks')
        compiled_header, compiled_parts = tags(compiled.read_bytes())
        result = [(code, body) for code, body in compiled_parts
                  if not (code == 82 and body in dependency_bodies)]
        # Compilation must not change native artwork, linkage or timeline tags.
        assert [(c, b) for c, b in result if c != 82] == [(c, b) for c, b in parts if c != 82]
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(pack(compiled_header, result))
    output.with_suffix('.swf.json').write_text(json.dumps(dict(
        source_sha256=INPUT_SHA256, output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        builder_sha256=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
        disabled_logoff_initializers=4, client='Chinese HD 0.9.22.0.1 #1513'), indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('client', 'java', 'ffdec', 'output'):
        parser.add_argument('--' + name, required=True)
    build(**vars(parser.parse_args()))
