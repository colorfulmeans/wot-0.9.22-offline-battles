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


# Category colors follow the inspected WOTInspector X-ray legend (2026-11-01).
MODULE_STYLES = (
    ('engine', 'Engine', '#ff245c'),
    ('ammoBay', 'Ammo rack', '#f4f72b'),
    ('fuelTank', 'Fuel tank', '#ff8924'),
    ('radio', 'Radio', '#20d9b9'),
    ('turretRotator', 'Turret rotation mechanism', '#3689f5'),
    ('surveyingDevice', 'Observation devices', '#22dced'),
)
COLORS = {entity: color for entity, unused_label, color in MODULE_STYLES}
CREW_STYLES = {
    'commander': ('Commander', '#29bdcd'),
    'gunner': ('Gunner', '#327fbc'),
    'driver': ('Driver', '#c62859'),
    'loader': ('Loader', '#cbd03b'),
    'radioman': ('Radio operator', '#26b99f'),
}


def crew_slots(roles):
    """Keep actual seats, combined duties and duplicate primary roles distinct."""
    counts = {}
    totals = {row[0]: sum(other[0] == row[0] for other in roles) for row in roles if row}
    result = []
    for index, duties in enumerate(roles):
        if not duties:
            continue
        role = duties[0]
        counts[role] = counts.get(role, 0) + 1
        label, color = CREW_STYLES.get(role, (role, '#72c485'))
        number = counts[role] if totals[role] > 1 else None
        if number and number > 1:
            # Additional seats retain the role's hue with a distinct lighter swatch.
            rgb = [int(color[i:i+2], 16) for i in (1, 3, 5)]
            factor = min(.5, .2 * (number - 1))
            color = '#%02x%02x%02x' % tuple(round(c + (255-c)*factor) for c in rgb)
        result.append(dict(identity='crew %d' % (index+1), roles=tuple(duties),
                           number=number, color=color))
    return tuple(result)


def load_scene(armor_scene, layouts=None):
    member = armor_scene['vehicleMember'].split('/')
    nation, vehicle = member[-2], member[-1].rsplit('.', 1)[0]
    key = (nation, ''.join(c.lower() for c in vehicle if c.isalnum()))
    record = (catalogue() if layouts is None else layouts).get(key)
    roles = armor_scene.get('crewRoles', record[2] if record else ())
    slots = crew_slots(roles)
    if record is None:
        return dict(armor_scene, parts=(), crewSlots=slots,
                    warnings=('No decoded interior geometry is available.',))
    modules = [(row[0], row[0], row[1], row[2], row[3]) for row in record[4]]
    roster_matches = tuple(roles) == tuple(record[2])
    modules.extend(('crew %d' % (index + 1), 'crew', row[0], row[1], row[2])
                   for index, alternatives in enumerate(record[5]) for row in alternatives or ()
                   if roster_matches)
    parts, missing = [], list(record[3])
    represented, expected = set(), set(row[0] for row in modules)
    expected.update(slot['identity'] for slot in slots)
    slot_by_id = {slot['identity']: slot for slot in slots}
    if not roster_matches:
        missing.append('Crew roster does not match the decoded layout.')
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
            'moduleLabel': '%s / %s' % (identity, zone),
            'moduleEntity': entity, 'fieldKey': None,
            'crewSlot': slot_by_id.get(identity),
            'color': (slot_by_id[identity]['color'] if identity in slot_by_id
                      else COLORS.get(entity, '#a889d3'))},)})
        represented.add(identity)
    missing.extend('%s: selected component has no matching interior' % identity
                   for identity in sorted(expected - represented))
    return dict(armor_scene, parts=tuple(parts), crewSlots=slots, warnings=tuple(sorted(set(missing))),
                provenance='Decoded Console surfaces; selected PC component frame verified')
