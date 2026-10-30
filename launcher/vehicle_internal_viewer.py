"""Render existing interior surfaces without fitting or inventing geometry."""
import ast
import base64
import functools
import os
from pathlib import Path
import struct
import sys
import zlib


@functools.lru_cache(maxsize=1)
def catalogue():
    relative = Path('src/res/scripts/client/gui/mods/offline_lan_0922/internal_layout_console.py')
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    path = base / ('servers/0.9.22' if getattr(sys, 'frozen', False) else '') / relative
    tree = ast.parse(path.read_text(encoding='utf-8'))
    value = next((node.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'CONSOLE_LAYOUTS_0922'
                         for target in node.targets)), None)
    if value is None:
        raise ValueError('The interior catalogue has no decoded layout table')
    return ast.literal_eval(value)


COLORS = {'engine': '#df8c42', 'ammoBay': '#d65b63', 'fuelTank': '#e9c64b',
          'radio': '#69b6d7', 'turretRotator': '#a889d3', 'crew': '#72c485'}


def load_scene(armor_scene, layouts=None):
    member = armor_scene['vehicleMember'].split('/')
    nation, vehicle = member[-2], member[-1].rsplit('.', 1)[0]
    key = (nation, ''.join(c.lower() for c in vehicle if c.isalnum()))
    record = (catalogue() if layouts is None else layouts).get(key)
    if record is None:
        return dict(armor_scene, parts=(), warnings=('No decoded interior geometry is available.',))
    modules = [(row[0], row[0], row[1], row[2], row[3]) for row in record[4]]
    modules.extend(('crew %d' % (index + 1), 'crew', row[0], row[1], row[2])
                   for index, alternatives in enumerate(record[5]) for row in alternatives or ())
    parts, missing = [], list(record[3])
    represented, expected = set(), set(row[0] for row in modules)
    for identity, entity, parent, zone, geometry in modules:
        part = next((p for p in armor_scene['parts'] if p['role'] == parent and
                     os.path.basename(p['model']).split('.')[0].lower() == geometry['part']), None)
        if part is None:
            continue
        reference = geometry['reference_bounds']
        bounds = part.get('localBounds')
        if bounds is None or any(abs(bounds[side][axis] - reference[side][axis]) > .002
               for side in range(2) for axis in range(3)):
            missing.append('%s: component frame mismatch' % entity)
            continue
        blob = zlib.decompress(base64.b64decode(geometry['payload']))
        magic, vertices_count, triangles_count = struct.unpack_from('<4sII', blob)
        if magic != b'IM01' or len(blob) != 12 + vertices_count * 24 + triangles_count * 12:
            raise ValueError('Invalid interior mesh: %s' % entity)
        offset = part['offset']
        vertices = [tuple(value + offset[axis] for axis, value in enumerate(
            struct.unpack_from('<3d', blob, 12 + index * 24))) for index in range(vertices_count)]
        triangles = []
        for index in range(triangles_count):
            indices = struct.unpack_from('<3I', blob, 12 + vertices_count * 24 + index * 12)
            triangles.append(tuple(vertices[point] for point in indices))
        parts.append({'role': parent, 'surfaces': ({'triangles': tuple(triangles),
            'moduleLabel': '%s / %s' % (entity, zone), 'fieldKey': None,
            'color': COLORS.get(entity, '#a889d3')},)})
        represented.add(identity)
    missing.extend('%s: selected component has no matching interior' % identity
                   for identity in sorted(expected - represented))
    return dict(armor_scene, parts=tuple(parts), warnings=tuple(sorted(set(missing))),
                provenance='Decoded Console surfaces; selected PC component frame verified')
