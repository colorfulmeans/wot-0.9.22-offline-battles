#!/usr/bin/env python3
"""Extract #1513 Mercury registrations from its x86 executable, read-only.

This is a pinned binary audit, not a general x86 disassembler. The CRT pointer
order determines registration order. InterfaceMinder::add assigns the next ID;
its range helper fills IDs through count + (254 - count) // remaining_ranges.
The registration records prove IDs and framing, not the handlers' wire fields.
"""

import argparse
import json
from pathlib import Path
import struct
import sys

from inspect_client import inspect_client


INTERFACES = {
    0x1A13CD4: 'ClientInterface',
    0x1A13CF8: 'BaseAppExtInterface',
    0x1A1482C: 'LoginInterface',
}
CRT_START = 0x14934EC
CRT_END = 0x1493784
ADD_ENTRY = 0xF27F70
EXPAND_RANGE = 0xF27FB0
LENGTH_STYLES = {0: 'fixed', 1: 'variable', 2: 'callback'}


class Executable:
    def __init__(self, path):
        self.payload = Path(path).read_bytes()
        if self.payload[:2] != b'MZ':
            raise ValueError('missing DOS signature')
        pe = self.u32(0x3C)
        if self.payload[pe:pe + 4] != b'PE\0\0':
            raise ValueError('missing PE signature')
        machine, count = struct.unpack_from('<HH', self.payload, pe + 4)
        optional_size = struct.unpack_from('<H', self.payload, pe + 20)[0]
        if machine != 0x14C or self.payload[pe + 24:pe + 26] != b'\x0b\x01':
            raise ValueError('expected an x86 PE32 executable')
        self.image_base = self.u32(pe + 52)
        self.sections = []
        for index in range(count):
            offset = pe + 24 + optional_size + index * 40
            unused_virtual_size, rva, raw_size, raw = struct.unpack_from(
                '<IIII', self.payload, offset + 8)
            self.sections.append((rva, raw_size, raw))

    def u32(self, offset):
        return struct.unpack_from('<I', self.payload, offset)[0]

    def _file_backed_span(self, address):
        rva = address - self.image_base
        for start, size, raw in self.sections:
            if start <= rva < start + size:
                return raw + rva - start, raw + size
        raise ValueError('address has no file-backed PE section: 0x%x' % address)

    def offset(self, address):
        return self._file_backed_span(address)[0]

    def read(self, address, count):
        offset, limit = self._file_backed_span(address)
        result = self.payload[offset:min(offset + count, limit)]
        if len(result) != count:
            raise ValueError('truncated executable at 0x%x' % address)
        return result

    def string(self, address):
        offset, limit = self._file_backed_span(address)
        end = self.payload.find(b'\0', offset, min(offset + 128, limit))
        if end < 0:
            raise ValueError('unbounded registration name at 0x%x' % address)
        return self.payload[offset:end].decode('ascii')


def _push(code, offset):
    if code[offset] == 0x68:
        return struct.unpack_from('<I', code, offset + 1)[0], offset + 5
    if code[offset] == 0x6A:
        return struct.unpack_from('<b', code, offset + 1)[0], offset + 2
    raise ValueError('expected an immediate PUSH in registration constructor')


def _call_target(code, offset, address):
    if code[offset] != 0xE8:
        raise ValueError('expected a direct registration CALL')
    displacement = struct.unpack_from('<i', code, offset + 1)[0]
    return address + offset + 5 + displacement


def _registration(executable, address):
    code = executable.read(address, 48)
    if code[0] not in (0x68, 0x6A):
        return None
    offset = 0
    pushes = []
    for unused in range(4):
        try:
            value, offset = _push(code, offset)
        except ValueError:
            return None
        pushes.append(value)
    if code[offset] != 0xB9:
        return None
    interface = struct.unpack_from('<I', code, offset + 1)[0]
    offset += 5
    if interface not in INTERFACES:
        return None
    if _call_target(code, offset, address) != ADD_ENTRY:
        raise ValueError('unexpected registration target at 0x%x' % address)
    handler, length, style, name_address = pushes
    if style not in LENGTH_STYLES:
        raise ValueError('unknown message framing style: %s' % style)
    return interface, {
        'name': executable.string(name_address),
        'lengthStyle': LENGTH_STYLES[style],
        'lengthParameter': length,
        'constructorVA': '0x%x' % address,
        'handlerObjectVA': '0x%x' % handler if handler else None,
    }


def _range(executable, address):
    code = executable.read(address, 48)
    if (code[0] != 0xA1 or code[5] != 0xB9 or
            code[10:13] not in (b'\x53\x6a\x02', b'\x53\x6a\x01')):
        return None
    interface = struct.unpack_from('<I', code, 6)[0]
    if interface not in INTERFACES:
        return None
    if code[13:16] != b'\x50\x8a\x18':
        raise ValueError('unexpected range registration at 0x%x' % address)
    if _call_target(code, 16, address) != EXPAND_RANGE:
        raise ValueError('unexpected range helper target at 0x%x' % address)
    return interface, code[12]


def inspect_native_protocol(client_root):
    identity = inspect_client(client_root)
    executable = Executable(Path(client_root) / 'WorldOfTanks.exe')
    # Verify the native ID-allocation instructions before reproducing them.
    if executable.read(0xF27F85, 8) != b'\x8b\x46\x04\x2b\x06\xc1\xf8\x04':
        raise ValueError('unexpected InterfaceMinder next-ID implementation')
    if executable.read(0xF27FC4, 16) != bytes.fromhex(
            'b8fe000000c1fe042bc6f7750c8d1c06'):
        raise ValueError('unexpected InterfaceMinder range-allocation implementation')
    tables = {address: [] for address in INTERFACES}
    counts = {address: 0 for address in INTERFACES}
    for slot in range(CRT_START, CRT_END, 4):
        address = struct.unpack('<I', executable.read(slot, 4))[0]
        entry = _registration(executable, address)
        if entry is not None:
            interface, row = entry
            row['id'] = counts[interface]
            row['idHex'] = '0x%02x' % counts[interface]
            row['crtPointerVA'] = '0x%x' % slot
            tables[interface].append(row)
            counts[interface] += 1
            continue
        extension = _range(executable, address)
        if extension is not None:
            interface, remaining_ranges = extension
            count = counts[interface]
            last = count + (254 - count) // remaining_ranges
            row = tables[interface][-1]
            row['lastId'] = last
            row['lastIdHex'] = '0x%02x' % last
            row['rangeConstructorVA'] = '0x%x' % address
            counts[interface] = last + 1

    expected = {
        'ClientInterface': (70, 'authenticate', 'entityProperty'),
        'BaseAppExtInterface': (16, 'baseAppLogin', 'baseEntityMethod'),
        'LoginInterface': (4, 'login', 'challengeResponse'),
    }
    for address, rows in tables.items():
        count, first, last = expected[INTERFACES[address]]
        if len(rows) != count or rows[0]['name'] != first or rows[-1]['name'] != last:
            raise ValueError('unexpected #1513 registration sequence: %s' %
                             INTERFACES[address])
        if INTERFACES[address] != 'LoginInterface' and counts[address] != 255:
            raise ValueError('incomplete dynamic message range')
    return {
        'clientRoot': identity['clientRoot'],
        'version': identity['version'],
        'build': identity['build'],
        'evidence': 'Static x86 registration constructors in CRT pointer order.',
        'limitations': [
            'Callback framing requires handler-specific length decoding.',
            'Registration does not establish field layout or runtime behavior.',
        ],
        'interfaces': {INTERFACES[address]: rows for address, rows in tables.items()},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client_root')
    args = parser.parse_args(argv)
    try:
        report = inspect_native_protocol(args.client_root)
    except (OSError, ValueError, struct.error) as error:
        parser.error(str(error))
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
