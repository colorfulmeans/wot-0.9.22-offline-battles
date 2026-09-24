"""Read the #1513 visible base circles from the installed map's WTCP data.

Only the root directory and the small control-point section are retained.
The large compiled geometry preceding WTCP is streamed through a bounded
buffer, including on the embedded Python 2.7 ZipExtFile which cannot seek.
"""

from __future__ import print_function

import math
import os
import struct
import zipfile


_ROW = struct.Struct('<4s5I')
_POINT_SIZE = 124
_READ_CHUNK = 65536


def _read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise ValueError('truncated compiled-space capture data')
    return data


def read_ctf_radii(stream, size, bases):
    """Decode WTCP v2 and match its circles to the stock CTF base positions."""
    root = _ROW.unpack(_read_exact(stream, _ROW.size))
    if root[0] != b'BWTB' or root[1] != 1:
        raise ValueError('unsupported compiled-space root table')
    count = root[5]
    directory_end = _ROW.size * (count + 1)
    if directory_end > size:
        raise ValueError('compiled-space root table exceeds the resource')
    control = None
    for unused in range(count):
        row = _ROW.unpack(_read_exact(stream, _ROW.size))
        if row[0] == b'WTCP':
            if control is not None or row[1] != 2:
                raise ValueError('ambiguous or unsupported WTCP section')
            control = row
    if control is None:
        raise ValueError('compiled space has no WTCP capture circles')
    start, length = control[2], control[4]
    if start < directory_end or length < 8 or start + length > size:
        raise ValueError('WTCP section exceeds the resource')
    remaining = start - directory_end
    while remaining:
        amount = min(remaining, _READ_CHUNK)
        _read_exact(stream, amount)
        remaining -= amount
    point_size, point_count = struct.unpack('<2I', _read_exact(stream, 8))
    if point_size != _POINT_SIZE or length != 8 + point_count * point_size:
        raise ValueError('invalid WTCP v2 control-point layout')
    if not isinstance(bases, (tuple, list)) or len(bases) != 2:
        raise ValueError('CTF requires the two authored base positions')
    matches = [set(), set()]
    for unused in range(point_count):
        point = _read_exact(stream, point_size)
        x, unused_y, z = struct.unpack_from('<3f', point, 48)
        radius, team = struct.unpack_from('<fI', point, 64)
        if team not in (1, 2):
            continue
        base = bases[team - 1]
        if (abs(x - base[0]) > 0.001 or abs(z - base[1]) > 0.001):
            continue
        if math.isnan(radius) or math.isinf(radius) or radius <= 0.0:
            raise ValueError('invalid authored capture radius')
        matches[team - 1].add(radius)
    if any(len(values) != 1 for values in matches):
        raise ValueError('WTCP circles do not unambiguously match CTF bases')
    return [values.pop() for values in matches]


def apply_installed_radii(graph, game_root='.'):
    """Overlay exact local capture metadata without changing navigation cells."""
    map_name = graph['map']
    package_path = os.path.join(game_root, 'res', 'packages', map_name + '.pkg')
    if not os.path.isfile(package_path):
        return False
    member = 'spaces/%s/space.bin' % map_name
    archive = zipfile.ZipFile(package_path, 'r')
    try:
        size = archive.getinfo(member).file_size
        stream = archive.open(member, 'r')
        try:
            radii = read_ctf_radii(stream, size, graph['objective_bases'])
        finally:
            stream.close()
    finally:
        archive.close()
    graph['objective_base_radii'] = radii
    print('[Offline LAN 0.9.22] capture circles map=%s radius=%.3f/%.3f '
          'source=%s WTCP-v2' % (map_name, radii[0], radii[1], member))
    return True
