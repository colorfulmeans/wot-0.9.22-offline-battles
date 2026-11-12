"""Bake 1 m meshes for the circled Mittengard streets on exact #1513 geometry."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bake_navigation_0922 as baker
import build_local_navigation_meshes as meshes

ROOT = Path(__file__).resolve().parents[1]
MAP = '100_thepit'
REGIONS = (
    (-144, 23, -93, 95), (-89, 44, -58, 83), (-57, 42, -16, 90),
    (-71, 3, -32, 43), (-31, 3, 5, 43), (-125, -54, -84, 5),
    (-68, -34, -35, 5), (-34, -39, 2, 2), (-49, -75, -21, -39),
)
# The two adjacent northern circles share a mesh.
PASSAGES = (
    ((-111, 68), (-109, 42)), ((-66, 78), (-72, 49)),
    ((-31, 83), (-31, 66)), ((-29, 67), (-29, 45)),
    ((-48, 30), (-49, 7)), ((-15, 31), (-15, 8)),
    ((-106, -7), (-104, -49)), ((-52, -6), (-53, -31)),
    ((-18, -9), (-18, -34)), ((-34, -47), (-34, -72)),
)


def build(client, output):
    sys.path[:0] = [str(ROOT/'src/res/scripts/client'), str(ROOT/'launcher')]
    from gui.mods.offline_lan_0922 import bot_tactics, prebaked_navigation
    from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
    from gui.mods.offline_lan_0922.navigation_graph_schema import validate_graph
    from bot_tactics_navigation import connection

    raw = (ROOT/'navgraphs'/f'{MAP}.json').read_bytes()
    graph = json.loads(raw)
    previous = set(graph.get('navigation_previous_sha256s', ()))
    if not graph.get('local_meshes'):
        previous.add(hashlib.sha256(raw).hexdigest())
    else:
        assert tuple(tuple(r) for r in graph['bake']['local_meshes']['regions']) == REGIONS
    original = json.loads(raw)
    original.pop('local_meshes', None)
    precise = tuple((left-6, bottom-6, right+6, top+6)
                    for left, bottom, right, top in REGIONS)
    terrain, obstacles, legacy = meshes.geometry(client, MAP, precise_regions=precise)
    patches = []
    for region in REGIONS:
        patch = meshes.bake_patch(region, terrain, obstacles, legacy)
        patches.append(patch)
        print(region, 'linked nodes:', sum(bool(mask) for mask in patch['links']), flush=True)
    graph['local_meshes'] = patches
    graph['navigation_previous_sha256s'] = sorted(previous)

    before, after = (prebaked_navigation.with_shore_hazards(item) for item in (original, graph))
    coarse = TerrainGrid(lambda *args: None, baked_graph=before)
    refined = TerrainGrid(lambda *args: None, baked_graph=after)
    proof = []
    for first, last in PASSAGES:
        for a, b in ((first, last), (last, first)):
            old = connection(coarse, before, a, b)
            new = connection(refined, after, a, b)
            if not new['connected'] or new['length'] > 1.8 * math.dist(a, b) + 12.:
                raise ValueError('No local passage from %r to %r' % (a, b))
            path = refined.plan((a[0], 0., a[1]), (b[0], 0., b[1]),
                                max_expansions=len(refined._baked_heights)+1)
            for start, end in zip(path, path[1:]):
                if not baker._resolution_segment_clear(
                        terrain, obstacles, start, end, legacy, legacy._segment_clear):
                    raise ValueError('Passage fails clearance from %r to %r' % (start, end))
            proof.append(dict(start=a, end=b, before=round(old['length'], 2),
                              after=round(new['length'], 2)))

    settings = bot_tactics.default_map(MAP)
    points = [r['points'] for r in settings['default_routes'] + settings['routes']
              if not r.get('disabled')]
    points.extend(r['waypoints'] for team in graph['routes'].values() for r in team)
    pairs = {(tuple(a[:2]), tuple(b[:2])) for route in points
             for a, b in zip(route, route[1:])}
    pairs.update((b, a) for a, b in list(pairs))
    for a, b in sorted(pairs):
        assert connection(refined, after, a, b)['connected'], (a, b)

    graph['bake']['local_meshes'] = dict(
        regions=REGIONS, base_cell_size=4., local_cell_size=1.,
        base_geometry_unchanged=True, collision_edge_sample_metres=.25,
        node_half_width=legacy.VEHICLE_HALF_WIDTH, water_depth_limit=legacy.WATER_DEPTH_LIMIT,
        source='exact_0922_client_compiled_geometry',
        local_collision_policy='body_height_clipped_triangles_against_original_2.15m_disk',
        measured_local_cells=sum(len(patch['heights_mm']) for patch in patches),
        circled_passage_validation=proof, preserved_directed_route_segments=len(pairs))
    validate_graph(graph, MAP)
    output.write_bytes((json.dumps(graph, separators=(',', ':'))+'\n').encode())
    print('Verified', len(proof), 'directed passages and', len(pairs), 'directed route segments.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    build(args.client, args.output)
