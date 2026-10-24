"""Build a mod-owned room movie with stock #1513 controls and window chrome.

FFDec 26.3.0 and Java 17 are build tools only. Native lobby ABCs are supplied
as compile-time type information, then removed byte-for-byte from the output.
The installed trainingWindow.swf and shared control movies are never patched.
"""
import argparse
import hashlib
import json
import re
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


def symbol_classes(raw):
    result = set()
    for code, body in tags(raw)[1]:
        if code != 76:
            continue
        count = struct.unpack_from('<H', body)[0]
        offset = 2
        for unused in range(count):
            offset += 2
            end = body.index(b'\0', offset)
            result.add(body[offset:end].decode('utf8'))
            offset = end + 1
    return result


def validate_control_linkages(source, available):
    # Runtime strings evade the AS3 type checker. Verify them against actual
    # stock SymbolClass definitions, not inferred authoring instance names.
    names = re.findall(r'item\.(?:dropdown|itemRenderer|scrollBar) = "([^"]+)"', source)
    names += re.findall(r'button\("[^"]+", "([^"]+)"', source)
    names += re.findall(r'component\(key, "([^"]+)"', source)
    names += re.findall(r'classFactory.getComponent\("([^"]+)"', source)
    missing = sorted(set(names) - set(available))
    if missing:
        raise ValueError('Unknown native control linkage: ' + ', '.join(missing))
    return sorted(set(names))


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


def rename_abc(body, class_name=b'OfflineWaitingRoomUI', namespace=b'offlineWaitingRoom_fla'):
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
        if value == b'TrainingWindow': value = class_name
        if value == b'trainingWindow_fla': value = namespace
        output += u30(len(value)) + value
    return body[:start] + output + abc[offset:]


def rename_picker_abc(body):
    """Rename the document class while retaining its same-named native base.

    Both QNames share the TrainingWindow string-pool entry. A global string
    replacement would also rename net.wg.gui.lobby.training.TrainingWindow.
    Split that one QName before performing the normal document rename.
    """
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
    string_start = offset
    count, offset = read_u30(abc, offset)
    strings = [b'']
    for unused in range(count - 1):
        length, offset = read_u30(abc, offset)
        strings.append(abc[offset:offset + length])
        offset += length
    # This distinct pool entry is deliberately not a TrainingWindow string
    # until after rename_abc has processed the document class.
    sentinel = b'OfflineNativePickerBase'
    output = abc[:string_start] + u30(count + 1)
    output += b''.join(u30(len(s)) + s for s in strings[1:] + [sentinel])
    namespace_start = offset
    namespace_count, offset = read_u30(abc, offset)
    namespaces = [b'']
    for unused in range(namespace_count - 1):
        offset += 1
        name, offset = read_u30(abc, offset)
        namespaces.append(strings[name])
    set_count, offset = read_u30(abc, offset)
    for unused in range(set_count - 1):
        length, offset = read_u30(abc, offset)
        for ignored in range(length):
            value, offset = read_u30(abc, offset)
    multiname_count, offset = read_u30(abc, offset)
    output += abc[namespace_start:offset]
    for unused in range(multiname_count - 1):
        kind = abc[offset]
        offset += 1
        output += bytes([kind])
        if kind in (7, 13):
            ns, offset = read_u30(abc, offset)
            name, offset = read_u30(abc, offset)
            if namespaces[ns] == b'net.wg.gui.lobby.training' and strings[name] == b'TrainingWindow':
                name = count
            output += u30(ns) + u30(name)
        else:
            widths = {15: 1, 16: 1, 17: 0, 18: 0, 9: 2, 14: 2, 27: 1, 28: 1}
            if kind == 29:
                base, offset = read_u30(abc, offset)
                length, offset = read_u30(abc, offset)
                output += u30(base) + u30(length)
                width = length
            elif kind in widths:
                width = widths[kind]
            else:
                raise ValueError('Unknown ABC multiname kind: %s' % kind)
            for ignored in range(width):
                value, offset = read_u30(abc, offset)
                output += u30(value)
    renamed = rename_abc(body[:start] + output + abc[offset:],
                         b'OfflineMapPickerUI', b'offlineMapPicker_fla')
    # Replace the sentinel through the string-pool-aware rewriter, since the
    # native class and document class names have different encoded lengths.
    return replace_abc_string(renamed, sentinel, b'TrainingWindow')


def replace_abc_string(body, old, new):
    start = body.index(b'\0', 4) + 1
    abc = body[start:]
    offset = 4
    for size in (None, None, 8):
        count, offset = read_u30(abc, offset)
        for unused in range(max(0, count - 1)):
            if size:
                offset += size
            else:
                value, offset = read_u30(abc, offset)
    count, offset = read_u30(abc, offset)
    output = abc[:offset]
    for unused in range(max(0, count - 1)):
        length, offset = read_u30(abc, offset)
        value = abc[offset:offset + length]
        offset += length
        if value == old:
            value = new
        output += u30(len(value)) + value
    return body[:start] + output + abc[offset:]


def build(client, java, ffdec, output):
    with zipfile.ZipFile(Path(client) / 'res/packages/gui.pkg') as archive:
        original = archive.read('gui/flash/trainingWindow.swf')
        lobby = archive.read('gui/flash/lobby.swf')
        available = set()
        for movie in ('guiControlsLobbyBattle', 'guiControlsLoginBattle', 'guiControlsLogin'):
            available.update(symbol_classes(archive.read('gui/flash/' + movie + '.swf')))
    control_linkages = validate_control_linkages(
        (ROOT/'tools/actionscript/OfflineWaitingRoom.as').read_text(encoding='utf8'), available)
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
        for token in tuple(control_linkages) + ('modeTitle', 'exitButton', '_originalWidth', 'rowCount'):
            if token not in verified: raise ValueError('Missing compiled room contract: ' + token)
    proof = dict(actionscript_sha256=hashlib.sha256((ROOT/'tools/actionscript/OfflineWaitingRoom.as').read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                 builder_sha256=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                 client='Chinese HD 0.9.22.0.1 #1513',
                 source_sha256=hashlib.sha256(original).hexdigest(),
                 lobby_sha256=hashlib.sha256(lobby).hexdigest(),
                 output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                 shared_movies_unchanged=True, native_control_linkages=control_linkages)
    output.with_suffix('.swf.json').write_bytes((json.dumps(proof, indent=2)+'\n').encode('utf8'))
    print('Built stock-component room:', output)
    build_picker(original, lobby, java, ffdec, output.parent / 'offlineMapPicker.swf')


def build_picker(original, lobby, java, ffdec, output):
    """Retain the complete native picker authoring; scope cosmetics to our copy."""
    header, parts = tags(original)
    dependencies = [(c, b) for c, b in tags(lobby)[1] if c == 82]
    dependency_bodies = set(b for c, b in dependencies)
    compile_parts = []
    inserted = False
    for code, body in parts:
        if code == 82 and not inserted:
            compile_parts.extend(dependencies)
            inserted = True
        compile_parts.append((code, body))
    source_path = ROOT / 'tools/actionscript/OfflineMapPicker.as'
    command = [str(java), '-Djava.awt.headless=true', '-jar', str(ffdec)]
    with tempfile.TemporaryDirectory(prefix='wot-stock-picker-') as directory:
        temp = Path(directory)
        source = temp / 'input.swf'
        compiled = temp / 'compiled.swf'
        source.write_bytes(pack(header, compile_parts))
        subprocess.run(command + ['-replace', str(source), str(compiled),
            'TrainingWindow', str(source_path)], check=True)
        compiled_header, compiled_parts = tags(compiled.read_bytes())
        result = []
        for code, body in compiled_parts:
            if code == 82 and body in dependency_bodies:
                continue
            if code == 82:
                body = rename_picker_abc(body)
            if code == 76:
                body = body.replace(b'TrainingWindow\0', b'OfflineMapPickerUI\0')
                body = body.replace(b'trainingWindow_fla.', b'offlineMapPicker_fla.')
            result.append((code, body))
        if sum(c == 82 for c, b in result) != sum(c == 82 for c, b in parts):
            raise ValueError('Compile-time lobby definitions leaked into picker')
        output.write_bytes(pack(compiled_header, result))
        subprocess.run(command + ['-selectclass', 'OfflineMapPickerUI', '-export',
            'script', str(temp / 'verify'), str(output.resolve())], check=True)
        verified = (temp / 'verify/scripts/OfflineMapPickerUI.as').read_text(encoding='utf8')
        for token in ('as_setOfflineOptions', 'super.draw()', 'teamSizes', 'isPrivate.visible = false'):
            if token not in verified:
                raise ValueError('Missing compiled picker contract: ' + token)
        if ('net.wg.gui.lobby.training.TrainingWindow' not in verified or
                'net.wg.gui.lobby.training.OfflineMapPickerUI' in verified):
            raise ValueError('Scoped picker lost its native TrainingWindow base')
    proof = dict(actionscript_sha256=hashlib.sha256(source_path.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                 builder_sha256=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                 source_sha256=hashlib.sha256(original).hexdigest(),
                 output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                 shared_movies_unchanged=True)
    output.with_suffix('.swf.json').write_bytes((json.dumps(proof, indent=2)+'\n').encode('utf8'))
    print('Built scoped native map picker:', output)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('client', 'java', 'ffdec', 'output'): p.add_argument('--' + arg, required=True)
    args = p.parse_args()
    build(args.client, args.java, args.ffdec, args.output)
