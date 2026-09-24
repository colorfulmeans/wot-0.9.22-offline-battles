#!/usr/bin/env python3
"""Transcribe Hawg's historical SPG markers and project them onto pinned #1513 graphs.

No downloaded image, executable, or third-party code is copied into the repo.
Rebuilding from committed marker facts needs only the Python standard library.
--archive additionally checks the author archive and repeats icon extraction
with Pillow (a tool dependency, never a game-runtime dependency).
"""
import argparse
from collections import deque
import hashlib
import heapq
import io
import json
import math
from pathlib import Path
import pprint
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.ai import maps as tactical_maps

SOURCE_SHA = '22ec2f4bf5e438237b02eb94d9cf3e0b68c76d5fd51cfb05230c7113a04b0710'
SOURCE = ROOT / 'data/spg_positions/hawg_2527609_markers.json'
OUTPUT = ROOT / 'src/res/scripts/client/gui/mods/offline_lan_0922/ai/spg_positions_data.py'
REPORT = ROOT / 'docs/testing/spg-position-coverage.json'
# Local placement tolerances, NOT retail or Hawg-authored values.
MAX_PROJECTION = 24.0
PARKING_SHOULDER = 1  # require a connected dry 3x3 patch on the 4 m grid
MAX_PARK_GRADE = 0.18
SLOT_SPACING = 14.0
SLOTS_PER_MARKER = 3


def sha(data):
    return hashlib.sha256(data).hexdigest()


def extract_archive(path):
    from PIL import Image
    raw = Path(path).read_bytes()
    if sha(raw) != SOURCE_SHA:
        raise ValueError('historical author archive checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [n for n in archive.namelist() if n.endswith('.wotmod')]
        if names != ['Spg_Tac_/Hawg_Tac_spaces.wotmod']:
            raise ValueError('unexpected historical archive layout')
        packed = archive.read(names[0])
    result = {}
    with zipfile.ZipFile(io.BytesIO(packed)) as mod:
        for name in sorted(mod.namelist()):
            if not name.endswith('/mmap.dds'):
                continue
            image_bytes = mod.read(name)
            image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
            width, height = image.size
            pixels = image.load()
            yellow = {(x, y) for y in range(height) for x in range(width)
                      if pixels[x, y][0] > 210 and pixels[x, y][1] > 210
                      and pixels[x, y][2] < 110}
            markers = []
            rejected = []
            while yellow:
                start = min(yellow, key=lambda p: (p[1], p[0]))
                yellow.remove(start)
                group = [start]
                queue = deque([start])
                while queue:
                    x, y = queue.popleft()
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            neighbour = (x + dx, y + dy)
                            if neighbour in yellow:
                                yellow.remove(neighbour)
                                group.append(neighbour)
                                queue.append(neighbour)
                left, right = min(p[0] for p in group), max(p[0] for p in group) + 1
                top, bottom = min(p[1] for p in group), max(p[1] for p in group) + 1
                if len(group) < 15:
                    continue
                blue = sum(pixels[x, y][2] > 110 and pixels[x, y][0] < 125
                           and pixels[x, y][1] < 185
                           for y in range(top, bottom) for x in range(left, right))
                box = [left, top, right, bottom]
                if 8 <= right-left <= 20 and 8 <= bottom-top <= 20 and blue >= 12:
                    markers.append({'pixel_center': [(left+right)/2.0, (top+bottom)/2.0],
                                    'pixel_box': box})
                else:
                    rejected.append(box)
            result[name.split('/')[-2]] = {
                'image_size': [width, height], 'image_sha256': sha(image_bytes),
                'markers': sorted(markers, key=lambda p: (p['pixel_box'][1], p['pixel_box'][0])),
                'rejected': rejected,
            }
    return result


def pixel_to_world(pixel, size, bounds):
    x0, z0, x1, z1 = bounds
    return (x0 + pixel[0]/size[0]*(x1-x0), z1 - pixel[1]/size[1]*(z1-z0))


def cell(graph, point):
    return (int(round((point[0]-graph['origin'][0])/graph['cell_size'])),
            int(round((point[1]-graph['origin'][1])/graph['cell_size'])))


def node(graph, column, row):
    if 0 <= column < graph['width'] and 0 <= row < graph['height']:
        return row * graph['width'] + column
    return None


def coordinate(graph, index):
    row, column = divmod(index, graph['width'])
    return (graph['origin'][0]+column*graph['cell_size'],
            graph['heights_mm'][index]/1000.0,
            graph['origin'][1]+row*graph['cell_size'])


def dry(graph, index, bounds):
    if index is None or graph['heights_mm'][index] is None or not graph['links'][index]:
        return False
    if graph['hazards'][index] & 3:
        return False
    x, unused_y, z = coordinate(graph, index)
    return bounds[0] <= x <= bounds[2] and bounds[1] <= z <= bounds[3]


def distances(graph, start, bounds):
    origin = node(graph, *cell(graph, start))
    if not dry(graph, origin, bounds):
        return {}
    width, height = graph['width'], graph['height']
    links, heights, hazards = graph['links'], graph['heights_mm'], graph['hazards']
    valid = bytearray(len(links))
    for index in range(len(links)):
        if heights[index] is not None and links[index] and not hazards[index] & 3:
            row, column = divmod(index, width)
            x = graph['origin'][0]+column*graph['cell_size']
            z = graph['origin'][1]+row*graph['cell_size']
            if bounds[0] <= x <= bounds[2] and bounds[1] <= z <= bounds[3]:
                valid[index] = 1
    directions = graph['directions']
    moves = [(1 << bit, dx+dz*width, 1 << directions.index([-dx, -dz]),
              math.hypot(dx, dz)*graph['cell_size'], dx, dz)
             for bit, (dx, dz) in enumerate(directions)]
    move_cache = {mask: [m for m in moves if mask & m[0]] for mask in range(256)}
    best = [float('inf')]*len(links)
    best[origin] = 0.0
    queue = [(0.0, origin)]
    pop, push = heapq.heappop, heapq.heappush
    while queue:
        cost, current = pop(queue)
        if cost != best[current]:
            continue
        row, column = divmod(current, width)
        for unused_bit, offset, reverse, length, dx, dz in move_cache[links[current]]:
            other = current+offset
            if (not 0 <= column+dx < width or not 0 <= row+dz < height or
                    not valid[other] or not links[other] & reverse):
                continue
            new_cost = cost+length
            if new_cost < best[other]:
                best[other] = new_cost
                push(queue, (new_cost, other))
    return {i: cost for i, cost in enumerate(best) if cost < float('inf')}


def parking_patch(graph, index, bounds):
    row, column = divmod(index, graph['width'])
    center_y = graph['heights_mm'][index]
    for dz in range(-PARKING_SHOULDER, PARKING_SHOULDER+1):
        for dx in range(-PARKING_SHOULDER, PARKING_SHOULDER+1):
            other = node(graph, column+dx, row+dz)
            if not dry(graph, other, bounds) or graph['hazards'][other] & 4:
                return False
            if dx or dz:
                distance = graph['cell_size']*math.hypot(dx, dz)
                if abs(graph['heights_mm'][other]-center_y)/1000.0 > distance*MAX_PARK_GRADE:
                    return False
                bit = graph['directions'].index([dx, dz])
                reverse = graph['directions'].index([-dx, -dz])
                if (not graph['links'][index] & (1 << bit)
                        or not graph['links'][other] & (1 << reverse)):
                    return False
    return True


def generate(source):
    manifest = json.loads((ROOT/'navgraphs/manifest.json').read_text())
    maps = {}
    for entry in manifest['maps']:
        name = entry['map']
        raw = (ROOT/'navgraphs'/entry['file']).read_bytes()
        if sha(raw) != entry['sha256']:
            raise ValueError('navigation baseline drift: '+name)
        graph = json.loads(raw)
        bounds = list(tactical_maps.TACTICAL_MAPS[name]['bounds'])
        image = source['maps'].get(name)
        starts = graph['spawn_anchors']
        reachable = [distances(graph, p, bounds) for p in starts]
        row = {
            'map': name, 'game_version': manifest['game_version'], 'mode': 'ctf',
            'bounds': bounds, 'nav_sha256': entry['sha256'],
            'grid': [graph['width'], graph['height'], graph['cell_size'], graph['origin']],
            'spawn_anchors': starts, 'source_status': ('missing_image' if image is None else
                            'no_source_markers' if not image['markers'] else 'sourced'),
            'markers': [], 'positions': [],
        }
        for marker_number, marker in enumerate(image['markers'] if image else [], 1):
            x, z = pixel_to_world(marker['pixel_center'], image['image_size'], bounds)
            # Use true CTF starts, not team-id == north/south or a route midpoint.
            side_cost = [(math.hypot(x-p[0], z-p[1]), team) for team, p in enumerate(starts, 1)]
            side_cost.sort()
            team = side_cost[0][1]
            marker_id = '%s:h%02d' % (name, marker_number)
            marker_record = dict(marker, id=marker_id, world=[round(x, 4), round(z, 4)], team=team)
            options = []
            c, r = cell(graph, (x, z))
            radius = int(math.ceil(MAX_PROJECTION/graph['cell_size']))+1
            for dr in range(-radius, radius+1):
                for dc in range(-radius, radius+1):
                    index = node(graph, c+dc, r+dr)
                    if index not in reachable[team-1]:
                        continue
                    point = coordinate(graph, index)
                    error = math.hypot(x-point[0], z-point[2])
                    if error <= MAX_PROJECTION and parking_patch(graph, index, bounds):
                        options.append((error, reachable[team-1][index], index, point))
            adopted = []
            for error, distance, index, point in sorted(options):
                if any(math.hypot(point[0]-p[0], point[2]-p[2]) < SLOT_SPACING for p in adopted):
                    continue
                adopted.append(point)
                # The author marked a region, not a surveyed metre-precise parking pose.
                # Preserve the source marker independently from the snapped graph node.
                row['positions'].append({
                    'id': marker_id+':%d' % len(adopted), 'marker_id': marker_id,
                    'team': team, 'point': list(point), 'node': index,
                    'projection_metres': round(error, 4),
                    'path_from_base_metres': round(distance, 3),
                    'verification': 'dry_connected_graph_patch_not_native_firing_arc',
                })
                if len(adopted) >= SLOTS_PER_MARKER:
                    break
            marker_record['status'] = 'graph_projected' if adopted else 'no_dry_connected_parking_patch'
            marker_record['slots'] = len(adopted)
            row['markers'].append(marker_record)
        maps[name] = row
    payload = {
        'schema': 1, 'revision': 'hawg2527609-1513-v1',
        'game_version': manifest['game_version'], 'mode': 'ctf',
        'source': source['source'],
        'policy': {'maximum_projection_metres': MAX_PROJECTION,
                   'parking_shoulder_cells': PARKING_SHOULDER, 'maximum_parking_grade': MAX_PARK_GRADE,
                   'minimum_slot_spacing_metres': SLOT_SPACING, 'slots_per_marker': SLOTS_PER_MARKER,
                   'not_official_positions': True, 'native_arcs_prevalidated': False},
        'maps': maps,
    }
    report = {
        'source_maps': len(source['maps']), 'runtime_maps': len(maps),
        'runtime_source_markers': sum(len(m['markers']) for m in maps.values()),
        'runtime_parking_slots': sum(len(m['positions']) for m in maps.values()),
        'maps_with_source_markers': sum(bool(m['markers']) for m in maps.values()),
        'maps_with_slots': sum(bool(m['positions']) for m in maps.values()),
        'maps': {n: {'source_status': m['source_status'], 'markers': len(m['markers']),
                     'slots': len(m['positions']),
                     'team_slots': {str(t): sum(p['team'] == t for p in m['positions']) for t in (1, 2)},
                     'rejected_markers': [p['id'] for p in m['markers'] if not p['slots']]}
                 for n, m in maps.items()},
    }
    return payload, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    source = json.loads(SOURCE.read_text())
    if args.archive:
        if extract_archive(args.archive) != source['maps']:
            raise ValueError('committed marker facts differ from the pinned author archive')
        print('PASS author archive checksum and all extracted marker coordinates')
    payload, report = generate(source)
    output = ('# -*- coding: utf-8 -*-\n'
              '# Generated by tools/build_spg_positions.py; do not edit by hand.\n'
              '# Hawg community marker facts, not official positions or validated firing arcs.\n'
              'DATA = '+pprint.pformat(payload, width=120, sort_dicts=True)+'\n')
    report_text = json.dumps(report, indent=2, sort_keys=True)+'\n'
    for path, text in ((OUTPUT, output), (REPORT, report_text)):
        if args.check:
            if path.read_text() != text:
                raise ValueError('regenerated data differ: '+str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    print(json.dumps({k: v for k, v in report.items() if k != 'maps'}, sort_keys=True))
    for name, row in report['maps'].items():
        print(name, row['source_status'], row['markers'], row['slots'], row['team_slots'], row['rejected_markers'])

if __name__ == '__main__':
    main()
