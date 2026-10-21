"""Build a mod-owned room movie with stock #1513 controls and window chrome.

FFDec 26.3.0 and Java 17 are build tools only. Native lobby ABCs are supplied
as compile-time type information, then removed byte-for-byte from the output.
The installed trainingWindow.swf and shared control movies are never patched.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile
from build_map_picker_swf import (_decompress_swf, _skip_rect, _iter_tags,
                                  _parse_place_object3)

ROOT = Path(__file__).resolve().parents[1]


def tags(raw):
    raw = _decompress_swf(raw)
    start = _skip_rect(raw, 8) + 4
    result = []
    offset = start
    while offset < len(raw):
        head = struct.unpack_from('<H', raw, offset)[0]
        code, length = head >> 6, head & 63
        offset += 2
        if length == 63:
            length = struct.unpack_from('<I', raw, offset)[0]
            offset += 4
        result.append((code, raw[offset:offset + length]))
        offset += length
        if code == 0:
            break
    return raw[:start], result


def pack(header, parts):
    raw = header + b''.join(struct.pack('<HI', (code << 6) | 63, len(body)) + body
                            for code, body in parts)
    raw = raw[:4] + struct.pack('<I', len(raw)) + raw[8:]
    return raw


def read_u30(raw, offset):
    value = shift = 0
    while True:
        b = raw[offset]; offset += 1
        value |= (b & 127) << shift
        if not b & 128:
            return value, offset
        shift += 7


def u30(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128); value >>= 7
    result.append(value)
    return bytes(result)


def rename_abc(body):
    start = body.index(b'\0', 4) + 1
    abc = body[start:]
    offset = 4
    for size in (None, None, 8):
        count, offset = read_u30(abc, offset)
        for unused in range(max(0, count - 1)):
            if size:
                offset += size
            else:
                unused_value, offset = read_u30(abc, offset)
    count, next_offset = read_u30(abc, offset)
    output = abc[:next_offset]
    offset = next_offset
    for unused in range(max(0, count - 1)):
        length, offset = read_u30(abc, offset)
        value = abc[offset:offset + length]
        offset += length
        if value == b'TrainingWindow': value = b'OfflineWaitingRoomUI'
        if value == b'trainingWindow_fla': value = b'offlineWaitingRoom_fla'
        output += u30(len(value)) + value
    return body[:start] + output + abc[offset:]


def build(client, java, ffdec, output):
    with zipfile.ZipFile(Path(client) / 'res/packages/gui.pkg') as archive:
        original = archive.read('gui/flash/trainingWindow.swf')
        lobby = archive.read('gui/flash/lobby.swf')
    if hashlib.sha256(original).hexdigest() != 'aeaf9efe4ef1180ed8c65cd7d1c2d9d2e7ddfa8297e5cf1e0819c34c7281a019':
        raise ValueError('Requires pinned #1513 trainingWindow.swf')
    if hashlib.sha256(lobby).hexdigest() != '3a54f7081b35b77dfbcb0048bfe9e8c77f0071cf0586cfb68dabf5a00ff81e55':
        raise ValueError('Requires pinned #1513 lobby.swf')
    header, parts = tags(original)
    dependencies = [(c, b) for c, b in tags(lobby)[1] if c == 82]
    dependency_bodies = set(body for code, body in dependencies)
    # The exact native application definitions resolve every inherited method.
    # The stock movie imports the two control libraries with zero asset IDs:
    # their ABC definitions register the linkage classes. Match that producer
    # contract for the additional red-button library (do not invent exports).
    compile_parts = [(71, b'guiControlsLogin.swf\0\x01\x00\x00\x00')]
    inserted = False
    for code, body in parts:
        if code == 82 and not inserted:
            compile_parts.extend(dependencies); inserted = True
        compile_parts.append((code, body))
    command = [str(java), '-Djava.awt.headless=true', '-jar', str(ffdec)]
    with tempfile.TemporaryDirectory(prefix='wot-stock-room-') as directory:
        temp = Path(directory)
        source = temp / 'input.swf'; compiled = temp / 'compiled.swf'
        source.write_bytes(pack(header, compile_parts))
        subprocess.run(command + ['-replace', str(source), str(compiled),
            'TrainingWindow', str(ROOT / 'tools/actionscript/OfflineWaitingRoom.as')], check=True)
        compiled_header, compiled_parts = tags(compiled.read_bytes())
        result = []
        for code, body in compiled_parts:
            if code == 82 and body in dependency_bodies:
                continue
            if code == 82:
                body = rename_abc(body)
            if code == 39 and struct.unpack_from('<H', body)[0] == 16:
                # Keep only the stock text-format prototype. The old map list,
                # minimap and inputs must never instantiate or attach listeners.
                children = []
                names = []
                for child_code, start, begin, end, sprite_id in _iter_tags(
                        body, 4, len(body), sprite_id=16):
                    if child_code in (26, 70):
                        encoded = body[begin:end]
                        if child_code == 26:
                            encoded = encoded[:1] + b'\0' + encoded[1:]
                        placement = _parse_place_object3(encoded, 0, len(encoded), 16)
                        if placement.name != 'battleType':
                            continue
                        names.append(placement.name)
                    elif child_code == 4:
                        continue
                    children.append((child_code, body[begin:end]))
                if names != ['battleType']:
                    raise ValueError('Missing stock text-format prototype')
                body = body[:4] + b''.join(struct.pack('<HI', (c << 6) | 63, len(b)) + b
                                          for c, b in children)
            if code == 76:
                # SymbolClass names are C strings preceded by their character IDs.
                body = body.replace(b'TrainingWindow\0', b'OfflineWaitingRoomUI\0')
                body = body.replace(b'trainingWindow_fla.', b'offlineWaitingRoom_fla.')
            result.append((code, body))
        if sum(code == 82 for code, body in result) != sum(code == 82 for code, body in parts):
            raise ValueError('Compile-time lobby definitions leaked into the room')
        output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(pack(compiled_header, result))
        subprocess.run(command + ['-selectclass', 'OfflineWaitingRoomUI', '-export',
            'script', str(temp / 'verify'), str(output.resolve())], check=True)
        verified = (temp / 'verify/scripts/OfflineWaitingRoomUI.as').read_text(encoding='utf8')
        for token in ('DropdownMenuUI', 'ButtonBlack', 'ButtonRed', 'modeTitle', 'exitButton'):
            if token not in verified: raise ValueError('Missing compiled room contract: ' + token)
    proof = dict(actionscript_sha256=hashlib.sha256((ROOT/'tools/actionscript/OfflineWaitingRoom.as').read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                 builder_sha256=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                 client='Chinese HD 0.9.22.0.1 #1513',
                 source_sha256=hashlib.sha256(original).hexdigest(),
                 lobby_sha256=hashlib.sha256(lobby).hexdigest(),
                 output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                 shared_movies_unchanged=True)
    output.with_suffix('.swf.json').write_text(json.dumps(proof, indent=2)+'\n', encoding='utf8')
    print('Built stock-component room:', output)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('client', 'java', 'ffdec', 'output'): p.add_argument('--' + arg, required=True)
    args = p.parse_args()
    build(args.client, args.java, args.ffdec, args.output)
