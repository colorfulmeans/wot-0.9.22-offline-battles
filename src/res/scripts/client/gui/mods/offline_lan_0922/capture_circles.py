# -*- coding: utf-8 -*-
"""Read exact #1513 capture radii from the installed map's WTCP section."""

import math
import os
import struct
import zipfile


_ROW = struct.Struct('<4s5I')
_CONTROL_POINT_SIZE = 124
_MAX_SPACE_BYTES = 64 * 1024 * 1024


def _points_from_space(data):
    """Decode the pinned compiled control-point layout."""
    if len(data) < _ROW.size:
        raise ValueError('compiled map space header is missing')
    magic, version, directory_end, unused_a, unused_b, count = (
        _ROW.unpack_from(data, 0))
    if (magic != b'BWTB' or version != 1 or count > 128 or
            directory_end != (count + 1) * _ROW.size or
            directory_end > len(data)):
        raise ValueError('compiled map space directory is invalid')
    section = None
    for index in range(count):
        row = _ROW.unpack_from(data, (index + 1) * _ROW.size)
        if row[0] == b'WTCP':
            if section is not None:
                raise ValueError('duplicate WTCP section')
            section = row
    if section is None:
        raise ValueError('compiled map has no WTCP capture circles')
    unused_name, version, offset, unused, length, unused_count = section
    if (version != 2 or offset < directory_end or length < 8 or
            offset + length > len(data)):
        raise ValueError('unsupported WTCP control points')
    size, count = struct.unpack_from('<2I', data, offset)
    if (size != _CONTROL_POINT_SIZE or count > 4096 or
            length != 8 + count * size):
        raise ValueError('WTCP control point layout is invalid')
    points = []
    for index in range(count):
        start = offset + 8 + index * size
        x, z = struct.unpack_from('<f', data, start + 48)[0], (
            struct.unpack_from('<f', data, start + 56)[0])
        radius, team = struct.unpack_from('<fI', data, start + 64)
        visibility = struct.unpack_from('<I', data, start + 120)[0]
        points.append((x, z, radius, team, visibility))
    return points


def standard_circles_from_space(data):
    """Return exact standard-battle centres and radii in team order."""
    result = []
    points = _points_from_space(data)
    for team in (1, 2):
        candidates = [p for p in points if p[3] == team and p[4] & 1]
        if len(candidates) != 1:
            raise ValueError('WTCP must contain one standard circle per team')
        x, z, radius, unused_team, unused_visibility = candidates[0]
        if any(math.isnan(v) or math.isinf(v) for v in (x, z, radius)) or radius <= 0:
            raise ValueError('WTCP standard circle is invalid')
        result.append(([x, z], radius))
    return result


def radii_from_space(data, bases):
    """Match team control points to the two baked standard-mode objectives."""
    matched = {1: set(), 2: set()}
    for x, z, radius, team, unused_visibility in _points_from_space(data):
        if team not in matched:
            continue
        base = bases[team - 1]
        if abs(x - base[0]) <= 0.002 and abs(z - base[1]) <= 0.002:
            if math.isnan(radius) or math.isinf(radius) or radius <= 0.0:
                raise ValueError('WTCP capture radius is invalid')
            matched[team].add(radius)
    if any(len(matched[team]) != 1 for team in (1, 2)):
        raise ValueError('WTCP capture circles do not match both objectives')
    return [matched[1].pop(), matched[2].pop()]


def installed_radii(game_root, map_name, bases):
    """Use the player's original map package without distributing map art."""
    if (not map_name or '/' in map_name or '\\' in map_name or
            '..' in map_name):
        raise ValueError('invalid map package name')
    package = os.path.join(game_root, 'res', 'packages', map_name + '.pkg')
    member = 'spaces/%s/space.bin' % map_name
    with zipfile.ZipFile(package) as archive:
        info = archive.getinfo(member)
        if info.file_size > _MAX_SPACE_BYTES:
            raise ValueError('compiled map space is too large')
        return radii_from_space(archive.read(info), bases)
