"""Add an exact-client southern Windstorm bridge mesh; retain the coarse map."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_local_navigation_meshes as meshes

ROOT = Path(__file__).resolve().parents[1]
REGION = (106, -302, 214, -230)


def build(client):
    # Exact triangle clipping is confined to this bridge and its two mouths.
    meshes.EXTRA_REGIONS = (REGION,)
    terrain, obstacles, legacy = meshes.geometry(client, '84_winter')
    patch = meshes.bake_patch(REGION, terrain, obstacles, legacy)
    # Carry the original water/fall evidence at the new sampling resolution.
    # Building footprints remain unknown support, not invented water hazards.
    for index in range(patch['width'] * patch['height']):
        x = REGION[0] + index % patch['width']
        z = REGION[1] + index // patch['width']
        y = legacy._ground_height(terrain, obstacles, x, z)
        if y is None:
            patch['hazards'][index] = legacy.HAZARD_EDGE
        elif terrain.water_depth(x, z, y) > legacy.WATER_DEPTH_LIMIT:
            patch['hazards'][index] = legacy.HAZARD_WATER
        elif not legacy._has_safe_edge_clearance(terrain, obstacles, x, z, y):
            patch['hazards'][index] = legacy.HAZARD_EDGE
    path = ROOT / 'navgraphs/84_winter.json'
    raw = subprocess.check_output(['git', 'show', '346ae477:navgraphs/84_winter.json'], cwd=ROOT)
    graph = json.loads(raw)
    graph['local_meshes'] = [patch]
    # Coarse shortcuts must not cross samples rejected by the new mesh. Refine
    # only these local links, so Python and native A* receive identical data;
    # otherwise an old shortcut can bypass the fine mouth and fail at commit.
    refined = []
    for index, mask in enumerate(graph['links']):
        if not mask:
            continue
        x = graph['origin'][0] + index % graph['width'] * graph['cell_size']
        z = graph['origin'][1] + index // graph['width'] * graph['cell_size']
        if not (REGION[0]-4 <= x <= REGION[2]+4 and REGION[1]-4 <= z <= REGION[3]+4):
            continue
        for bit, (dx, dz) in enumerate(legacy.DIRECTIONS):
            if not mask & (1 << bit):
                continue
            steps = int(math.ceil(math.hypot(dx*4., dz*4.)/.25))
            for step in range(steps+1):
                px, pz = x+dx*4.*step/steps, z+dz*4.*step/steps
                if not (REGION[0] <= px <= REGION[2] and REGION[1] <= pz <= REGION[3]):
                    continue
                column, row = int(math.floor(px-REGION[0]+.5)), int(math.floor(pz-REGION[1]+.5))
                local_index = row*patch['width']+column
                if patch['heights_mm'][local_index] is None or patch['hazards'][local_index]:
                    graph['links'][index] &= ~(1 << bit)
                    refined.append([index, bit])
                    break
    previous = set(graph.get('navigation_previous_sha256s', ()))
    previous.add(hashlib.sha256(raw).hexdigest())
    graph['navigation_previous_sha256s'] = sorted(previous)
    graph['bake']['local_meshes'] = dict(
        regions=[REGION], base_cell_size=graph['cell_size'], local_cell_size=1.,
        coarse_heights_hazards_unchanged=True, refined_coarse_links=refined,
        collision_edge_sample_metres=.25,
        node_half_width=legacy.VEHICLE_HALF_WIDTH,
        bridge_obstacle_margin=legacy.BRIDGE_OBSTACLE_MARGIN,
        water_depth_limit=legacy.WATER_DEPTH_LIMIT,
        local_collision_policy='body_height_clipped_triangles_against_original_margin',
        source='exact_0922_client_compiled_geometry',
        recorded_exit=[126.7290046558638, -8.950407028198242, -276.07781896536494,
                       1.654004054630426, 3.1200008771171768])
    for key, value in json.loads(raw).items():
        if key not in ('local_meshes', 'bake', 'links', 'navigation_previous_sha256s'):
            assert graph[key] == value, key
    path.write_bytes((json.dumps(graph, separators=(',', ':')) + '\n').encode())
    manifest_path = ROOT / 'navgraphs/manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    for row in manifest['maps']:
        if row['file'] == '84_winter.json':
            row['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_bytes((json.dumps(manifest, indent=2) + '\n').encode())
    print('Windstorm local nodes: %d; supported: %d; directed links: %d' % (
        len(patch['links']), sum(v is not None for v in patch['heights_mm']),
        sum(bin(v).count('1') for v in patch['links'])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True)
    build(parser.parse_args().client)
