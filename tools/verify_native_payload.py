"""Bind the shipping x86 extension to every current native source input.

Python 2.7 compatible: the package builder and independent artifact audit use
the same check. A host-test extension is deliberately not a shipping proof.
"""
from __future__ import print_function
import argparse
import hashlib
import os
import struct


PREFIX = b'WOT_NATIVE_SOURCE_V1:'


def source_stamp(root):
    names = ['tools/build_math_batch_native.sh', 'tools/verify_native_payload.py']
    names += ['native/' + name for name in os.listdir(os.path.join(root, 'native'))
              if name.endswith(('.cpp', '.h', '.inc'))]
    digest = hashlib.sha256()
    for name in sorted(names):
        with open(os.path.join(root, name), 'rb') as stream:
            data = stream.read().replace(b'\r\n', b'\n')
        digest.update(name.encode('ascii') + b'\0')
        digest.update(hashlib.sha256(data).digest())
    return PREFIX + digest.hexdigest().encode('ascii')


def write_header(root, path):
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, 'wb') as stream:
        stream.write(b'#define WOT_NATIVE_SOURCE_STAMP "' + source_stamp(root) + b'"\n')


def verify_bytes(root, data):
    if len(data) < 64 or data[:2] != b'MZ':
        raise ValueError('Native payload is not a Windows PE image')
    offset = struct.unpack_from('<I', data, 60)[0]
    if (offset + 6 > len(data) or data[offset:offset+4] != b'PE\0\0' or
            struct.unpack_from('<H', data, offset + 4)[0] != 0x14c):
        raise ValueError('Native payload must be the shipping x86 extension')
    if data.count(PREFIX) != 1 or source_stamp(root) + b'\0' not in data:
        raise ValueError('Native payload does not match current C++/header/include/build inputs; rebuild it')
    return True


def verify_file(root, path):
    with open(path, 'rb') as stream:
        return verify_bytes(root, stream.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--header')
    group.add_argument('--verify')
    args = parser.parse_args()
    if args.header:
        write_header(args.root, args.header)
    else:
        verify_file(args.root, args.verify)
        print('Shipping x86 native source stamp verified')


if __name__ == '__main__':
    main()
