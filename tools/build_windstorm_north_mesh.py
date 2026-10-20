"""Bake the north bridge and measured shallow bank without changing driving law."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import build_local_navigation_meshes as meshes
import bake_navigation_0922 as baker

REGION = (202, 190, 310, 274)
BANK = (260, 210, 284, 230)
MOUTHS = ((210, 202, 234, 228), (258, 230, 290, 260))
BASELINE = '4855e49d'
ORIGIN = (280.3538467765204, -14.974234580993652, 219.5717056753799)
YAW = -1.2797609560299639


def footprint_support(terrain, obstacles, legacy, x, z, y):
    """Prove the original 2.15 m half-width, rather than a 6 m spare apron.

    This is a bake-only, bounded bank measurement. Keep the same water and
    drop/grade limits on a dense quarter-metre lattice over the width disk.
    Runtime collision shapes, queries and guards are untouched.
    """
    width = legacy.VEHICLE_HALF_WIDTH
    count = int(math.ceil(width/.25))

    def anchor(px, pz, height):
        surface = obstacles.surface_height(px, pz)
        if surface is not None and abs(height-surface) < 1e-7:
            # A bridge surface value belongs to the 1 m raster cell centre,
            # not the arbitrary sub-cell query position. Using a .24 m run
            # for a 1 m height difference invented cliffs at both deck ends.
            size = float(obstacles.raster_size)
            return ((math.floor(px/size)+.5)*size,
                    (math.floor(pz/size)+.5)*size)
        return px, pz

    origin = anchor(x, z, y)
    for iz in range(-count, count+1):
        for ix in range(-count, count+1):
            dx, dz = ix*width/count, iz*width/count
            distance = math.hypot(dx, dz)
            if distance > width+1e-8:
                continue
            ground = legacy._ground_height(terrain, obstacles, x+dx, z+dz)
            if ground is None or terrain.water_depth(x+dx, z+dz, ground) > legacy.WATER_DEPTH_LIMIT:
                return False
            sample = anchor(x+dx, z+dz, ground)
            measured_run = math.hypot(sample[0]-origin[0], sample[1]-origin[1])
            if abs(ground-y) > measured_run*legacy.MAX_GRADE+1e-6:
                return False
    return True


def bank_support(terrain, obstacles, legacy, x, z, y):
    return (any(left <= x <= right and bottom <= z <= top
                for left, bottom, right, top in (BANK,)+MOUTHS) and
            footprint_support(terrain, obstacles, legacy, x, z, y))


def build(client):
    raw = subprocess.check_output(['git', 'show', BASELINE+':navgraphs/84_winter.json'], cwd=ROOT)
    graph = json.loads(raw)
    meshes.EXTRA_REGIONS = (REGION,)
    terrain, obstacles, legacy = meshes.geometry(client, '84_winter')
    # The original bridge/ordinary-ground law remains the primary proof. Only
    # this explicitly measured bank uses the full-width local support proof.
    original_edge = legacy._has_safe_edge_clearance
    measured = set()

    def edge_clear(t, o, x, z, y):
        if original_edge(t, o, x, z, y):
            # The existing 1 m deck shoulder admits a centreline which can
            # still hang a wide track off this diagonal bridge. Prove the
            # original full width here as well, without altering the hull.
            if o.surface_height(x, z) is not None:
                return footprint_support(t, o, legacy, x, z, y)
            return True
        if bank_support(t, o, legacy, x, z, y):
            measured.add((x, z))
            return True
        return False

    try:
        legacy._has_safe_edge_clearance = edge_clear
        patch = meshes.bake_patch(REGION, terrain, obstacles, legacy)
        for i in range(patch['width']*patch['height']):
            x, z = REGION[0]+i%patch['width'], REGION[1]+i//patch['width']
            y = legacy._ground_height(terrain, obstacles, x, z)
            if y is None:
                patch['hazards'][i] = legacy.HAZARD_EDGE
            elif terrain.water_depth(x, z, y) > legacy.WATER_DEPTH_LIMIT:
                patch['hazards'][i] = legacy.HAZARD_WATER
            elif not edge_clear(terrain, obstacles, x, z, y):
                patch['hazards'][i] = legacy.HAZARD_EDGE
    finally:
        legacy._has_safe_edge_clearance = original_edge
    graph['local_meshes'].append(patch)
    refined = []
    for i, mask in enumerate(graph['links']):
        x = graph['origin'][0]+i%graph['width']*graph['cell_size']
        z = graph['origin'][1]+i//graph['width']*graph['cell_size']
        if not mask or not (REGION[0]-4 <= x <= REGION[2]+4 and REGION[1]-4 <= z <= REGION[3]+4):
            continue
        for bit, (dx, dz) in enumerate(legacy.DIRECTIONS):
            if not mask & (1 << bit):
                continue
            steps = int(math.ceil(math.hypot(dx*4., dz*4.)/.25))
            for step in range(steps+1):
                px, pz = x+dx*4.*step/steps, z+dz*4.*step/steps
                if not (REGION[0] <= px <= REGION[2] and REGION[1] <= pz <= REGION[3]):
                    continue
                index = int(math.floor(pz-REGION[1]+.5))*patch['width']+int(math.floor(px-REGION[0]+.5))
                if patch['heights_mm'][index] is None or patch['hazards'][index]:
                    graph['links'][i] &= ~(1 << bit)
                    refined.append([i, bit])
                    break
    meta = graph['bake']['local_meshes']
    meta['regions'].append(REGION)
    meta['refined_coarse_links'] += refined
    meta['north_bridge'] = dict(
        region=REGION, measured_bank=BANK, measured_mouths=MOUTHS, baseline=BASELINE,
        supported_nodes=sum(v is not None for v in patch['heights_mm']),
        measured_bank_nodes=[list(p) for p in sorted(measured)],
        bank_support_half_width=legacy.VEHICLE_HALF_WIDTH,
        bridge_support_half_width=legacy.VEHICLE_HALF_WIDTH,
        support_sample_metres=.25, water_depth_limit=legacy.WATER_DEPTH_LIMIT,
        bridge_height_basis='actual_1m_surface_raster_cell_centres',
        drop_grade_limit=legacy.MAX_GRADE, coarse_links_refined=refined,
        recorded_origin=ORIGIN, recorded_yaw=YAW, recorded_distances=[.5, 3.4308600425720215])
    previous = set(graph.get('navigation_previous_sha256s', ()))
    previous.add(hashlib.sha256(raw).hexdigest())
    graph['navigation_previous_sha256s'] = sorted(previous)
    assert graph['local_meshes'][0] == json.loads(raw)['local_meshes'][0]
    for key in ('routes', 'spawn_formations', 'heights_mm', 'hazards', 'width', 'height', 'origin', 'cell_size'):
        assert graph[key] == json.loads(raw)[key], key
    path = ROOT/'navgraphs/84_winter.json'
    path.write_bytes((json.dumps(graph, separators=(',', ':'))+'\n').encode())
    manifest_path = ROOT/'navgraphs/manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    for row in manifest['maps']:
        if row['file'] == '84_winter.json':
            row['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_bytes((json.dumps(manifest, indent=2)+'\n').encode())
    runpy.run_path(str(ROOT/'tools/build_bot_editor_maps.py'), run_name='__main__')
    for name in ('bot_editor_maps.py', 'bot_tactics_default_data.py'):
        path = ROOT/'src/res/scripts/client/gui/mods/offline_lan_0922'/name
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
    print('North bridge nodes=%d supported=%d links=%d bank proofs=%d coarse refinements=%d' % (
        len(patch['links']), meta['north_bridge']['supported_nodes'],
        sum(bin(v).count('1') for v in patch['links']), len(measured), len(refined)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True)
    build(parser.parse_args().client)
