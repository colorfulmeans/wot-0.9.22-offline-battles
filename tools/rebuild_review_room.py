"""Recompile the mod-owned room using the verified staged lobby type library.

The exact client remains local. CI uses the same reviewed lobby ABCs staged
for the depot build; imported client definitions are removed from the result.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from build_waiting_room_swf import tags, pack

ROOT = Path(__file__).resolve().parents[1]


def rebuild(java, ffdec):
    target = ROOT / 'src/res/gui/flash/offlineWaitingRoom.swf'
    source = ROOT / 'tools/actionscript/OfflineWaitingRoom.as'
    proof = json.loads(target.with_suffix('.swf.json').read_text())
    original = target.read_bytes()
    if hashlib.sha256(original).hexdigest() != proof['output_sha256']:
        raise ValueError('Room input does not match its reviewed receipt')
    lobby = (ROOT / 'build/depot/lobby.swf').read_bytes()
    header, parts = tags(original)
    dependencies = [(c, b) for c, b in tags(lobby)[1] if c == 82]
    dependency_bodies = {b for c, b in dependencies}
    compile_parts = []
    inserted = False
    for code, body in parts:
        if code == 82 and not inserted:
            compile_parts.extend(dependencies)
            inserted = True
        compile_parts.append((code, body))
    command = [java, '-Djava.awt.headless=true', '-jar', ffdec]
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        input_path, compiled = temp/'input.swf', temp/'compiled.swf'
        input_path.write_bytes(pack(header, compile_parts))
        replacement = temp/'OfflineWaitingRoomUI.as'
        replacement.write_text(source.read_text().replace('TrainingWindow',
            'OfflineWaitingRoomUI'), encoding='utf-8')
        subprocess.run(command + ['-replace', str(input_path), str(compiled),
            'OfflineWaitingRoomUI', str(replacement)], check=True)
        compiled_header, compiled_parts = tags(compiled.read_bytes())
        result = [(c, b) for c, b in compiled_parts
                  if not (c == 82 and b in dependency_bodies)]
        if sum(c == 82 for c, b in result) != sum(c == 82 for c, b in parts):
            raise ValueError('Client compile definitions leaked into room')
        output = pack(compiled_header, result)
        candidate = temp/'candidate.swf'
        candidate.write_bytes(output)
        subprocess.run(command + ['-selectclass', 'OfflineWaitingRoomUI',
            '-export', 'script', str(temp/'verify'), str(candidate)], check=True)
        verified = (temp/'verify/scripts/OfflineWaitingRoomUI.as').read_text()
        for token in ('configureDaily', 'sizeDailyFooter', 'ButtonBlack',
                      'ButtonNormal', 'FOOTER_GAP', '560', '381'):
            if token not in verified:
                raise ValueError('Compiled room is missing ' + token)
        target.write_bytes(output)
    proof.update(actionscript_sha256=hashlib.sha256(
        source.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
        output_sha256=hashlib.sha256(output).hexdigest(),
        rebuilder_sha256=hashlib.sha256(Path(__file__).read_bytes().replace(
            b'\r\n', b'\n')).hexdigest(), native_daily_window=True,
        settings_footer_reference=dict(submit_x=491, cancel_x=596,
            face_width=100, gap=5, client='CN #1513'))
    target.with_suffix('.swf.json').write_text(json.dumps(proof, indent=2)+'\n')
    print('Verified rebuilt native daily/room movie and removed compile-only ABCs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', default='java')
    parser.add_argument('--ffdec', required=True)
    args = parser.parse_args()
    rebuild(args.java, args.ffdec)
