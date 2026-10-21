"""Densify the requested upstream city bridge and both mouths on #1513 geometry."""
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
from build_windstorm_north_mesh import footprint_support

REGION = (82, -188, 164, -126)


def edge_support(terrain, obstacles, legacy, start, end):
    """Retain full-hull support while refining the old circular apron.

    Check the existing wide-body validation envelope and the recorded VK168
    chassis separately. A supported centre must not create a corner shortcut
    whose leading track passes through deep water.
    """
    distance = math.hypot(end[0]-start[0], end[2]-start[2])
    yaw = math.atan2(end[0]-start[0], end[2]-start[2])
    sine, cosine = math.sin(yaw), math.cos(yaw)
    count = max(1, int(math.ceil(distance/.25)))
    for i in range(count+1):
        x = start[0]+(end[0]-start[0])*i/count
        z = start[2]+(end[2]-start[2])*i/count
        for length, width in ((3.2, 2.15), (4.265017986297607, 1.7200759649276733)):
            for along in (-length, 0., length):
                for across in (-width, 0., width):
                    sx, sz = x+sine*along+cosine*across, z+cosine*along-sine*across
                    y = legacy._ground_height(terrain, obstacles, sx, sz)
                    if y is None or terrain.water_depth(sx, sz, y) > legacy.WATER_DEPTH_LIMIT:
                        return False
    return True


def build(client):
    path = ROOT/'navgraphs/84_winter.json'
    raw = path.read_bytes()
    graph = json.loads(raw)
    assert len(graph['local_meshes']) in (2, 3)
    if len(graph['local_meshes']) == 3:
        # Rebuild this patch from the retained pre-addition graph, so removed
        # coarse links are recalculated rather than accumulated on each bake.
        graph = json.loads(subprocess.check_output(
            ['git', 'show', '09b87889:navgraphs/84_winter.json'], cwd=ROOT))
    meshes.EXTRA_REGIONS = (REGION,)
    terrain, obstacles, legacy = meshes.geometry(client, '84_winter')
    original = legacy._has_safe_edge_clearance

    def supported(t, o, x, z, y):
        # Deck AND adjoining bank use the same measured full-width support.
        # A remote 6 m erosion apron rejected flat, fully supported approaches
        # even though the native local exit admitted the identical movement.
        return footprint_support(t, o, legacy, x, z, y)

    try:
        legacy._has_safe_edge_clearance = supported
        patch = meshes.bake_patch(REGION, terrain, obstacles, legacy)
        for i in range(patch['width']*patch['height']):
            x, z = REGION[0]+i%patch['width'], REGION[1]+i//patch['width']
            y = legacy._ground_height(terrain, obstacles, x, z)
            if y is None:
                patch['hazards'][i] = legacy.HAZARD_EDGE
            elif terrain.water_depth(x, z, y) > legacy.WATER_DEPTH_LIMIT:
                patch['hazards'][i] = legacy.HAZARD_WATER
            elif not supported(terrain, obstacles, x, z, y):
                patch['hazards'][i] = legacy.HAZARD_EDGE
        for i, mask in enumerate(patch['links']):
            start = (REGION[0]+i%patch['width'], patch['heights_mm'][i]/1000.
                if patch['heights_mm'][i] is not None else 0., REGION[1]+i//patch['width'])
            for bit, (dx, dz) in enumerate(legacy.DIRECTIONS):
                if not mask & (1 << bit):
                    continue
                j = i+dx+dz*patch['width']
                end = (start[0]+dx, patch['heights_mm'][j]/1000., start[2]+dz)
                if not edge_support(terrain, obstacles, legacy, start, end):
                    patch['links'][i] &= ~(1 << bit)
    finally:
        legacy._has_safe_edge_clearance = original
    graph['local_meshes'].append(patch)
    refined = []
    for i, mask in enumerate(graph['links']):
        x = graph['origin'][0]+i%graph['width']*4.
        z = graph['origin'][1]+i//graph['width']*4.
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
    meta['middle_bridge'] = dict(region=REGION, local_cell_size=1.,
        supported_nodes=sum(y is not None for y in patch['heights_mm']),
        coarse_links_refined=refined, support_half_width=legacy.VEHICLE_HALF_WIDTH,
        support_sample_metres=.25, water_depth_limit=legacy.WATER_DEPTH_LIMIT,
        source='exact_0922_client_compiled_geometry')
    graph['navigation_previous_sha256s'] = sorted(set(graph.get('navigation_previous_sha256s', ())) |
                                                {hashlib.sha256(raw).hexdigest()})
    path.write_bytes((json.dumps(graph, separators=(',', ':'))+'\n').encode())
    manifest_path = ROOT/'navgraphs/manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    for row in manifest['maps']:
        if row['file'] == '84_winter.json':
            row['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_bytes((json.dumps(manifest, indent=2)+'\n').encode())
    runpy.run_path(str(ROOT/'tools/build_bot_editor_maps.py'), run_name='__main__')
    for name in ('bot_editor_maps.py', 'bot_tactics_default_data.py'):
        dest = ROOT/'src/res/scripts/client/gui/mods/offline_lan_0922'/name
        dest.write_bytes(dest.read_bytes().replace(b'\r\n', b'\n'))
    print('Middle bridge: %d supported nodes; %d directed links; %d coarse refinements' % (
        meta['middle_bridge']['supported_nodes'], sum(bin(v).count('1') for v in patch['links']), len(refined)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True)
    build(parser.parse_args().client)
