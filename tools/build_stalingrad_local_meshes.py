"""Refine the owner's circled Stalingrad passages on exact #1513 collision."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
sys.path.insert(0, str(ROOT/'src/res/scripts/client'))
import build_local_navigation_meshes as meshes

# Fourteen screenshot circles. Retain the four metre base and authored roads.
# Two metre samples start on the original lattice; no whole-map refinement.
REGIONS = (
    (-332, 194, -262, 266), (-204, 182, -140, 244),
    (-206, 66, -142, 130), (-404, -120, -338, -52),
    (-318, -294, -254, -224), (-396, -334, -322, -272),
    (-206, -254, -138, -182), (26, 38, 94, 106),
    (-4, -84, 64, -16), (18, -226, 86, -158),
    (22, -314, 90, -246), (228, 192, 298, 264),
    (206, -158, 274, -90), (164, -354, 232, -286),
)
PASSAGES = (
    ((-277.2849, 230.0629), (-300.7464, 191.7835)),
    ((-164.9164, 241.7937), (-181.4729, 106.4298)),
    ((-181.4729, 106.4298), (-167.5306, 71.3337)),
    ((-341.2571, -18.928), (-383.084, -116.5962)),
    ((-290.3445, -192.0473), (-297.3985, -263.6173)),
    ((-375.8577, -294.8617), (-293.8373, -315.8436)),
    ((-168.7496, -210.6374), (-167.4814, -245.493)),
    ((65.221, 82.9177), (53.8605, 64.1659)),
    ((53.5501, -8.1707), (53.8843, -83.0909)),
    ((46.0681, -171.8522), (54.6903, -249.8624)),
    ((54.6903, -249.8624), (64.9133, -305.9704)),
    ((131.0859, 251.2445), (279.4823, 227.4235)),
    ((252.223, -111.8999), (221.0552, -150.5189)),
    ((223.553, -224.8273), (192.331, -335.3534)),
)


def prove(graph):
    from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
    from gui.mods.offline_lan_0922 import prebaked_navigation as pn
    grid = TerrainGrid(lambda *args: None, baked_graph=pn.with_shore_hazards(graph))
    rows = []
    for number, (first, last) in enumerate(PASSAGES):
        for a, b in ((first, last), (last, first)):
            path = grid.plan((a[0], 0., a[1]), (b[0], 0., b[1]),
                             max_expansions=len(grid._baked_heights)+1)
            target = grid._nearest_baked_cell(grid.cell_for((b[0], 0., b[1])), 3)
            end = grid.point_for(target, grid._baked_cell_height(target)) if target is not None else None
            if not path or end is None or math.hypot(path[-1][0]-end[0], path[-1][2]-end[2]) > 4.:
                raise ValueError('Passage %d has no complete path' % (number+1))
            distance = sum(math.hypot(y[0]-x[0], y[2]-x[2]) for x,y in zip(path,path[1:]))
            direct = math.hypot(b[0]-a[0], b[1]-a[1])
            if distance > direct*1.8+12.:
                raise ValueError('Passage %d still detours: %.1fm / %.1fm' % (number+1,distance,direct))
            rows.append(dict(passage=number+1,start=a,end=b,length=round(distance,4),path=path))
    return rows


def build(client, output):
    source = ROOT/'navgraphs/92_stalingrad.json'
    raw = source.read_bytes()
    graph = json.loads(raw)
    if graph.get('local_meshes'):
        raise ValueError('Build from the reviewed coarse Stalingrad source')
    meshes.EXTRA_REGIONS = REGIONS
    terrain, obstacles, legacy = meshes.geometry(client, '92_stalingrad')
    patches = []
    for number, region in enumerate(REGIONS):
        patch = meshes.bake_patch(region, terrain, obstacles, legacy, cell_size=2.)
        patches.append(patch)
        print('Circle %d: %d supported / %d samples' % (number+1,
            sum(v is not None for v in patch['heights_mm']),len(patch['heights_mm'])),flush=True)
    graph['local_meshes'] = patches
    graph['bake']['local_meshes'] = dict(regions=REGIONS,base_cell_size=4.,
        local_cell_size=2.,base_geometry_unchanged=True,
        node_half_width=legacy.VEHICLE_HALF_WIDTH,collision_edge_sample_metres=.25,
        water_depth_limit=legacy.WATER_DEPTH_LIMIT,
        measured_local_cells=sum(len(p['heights_mm']) for p in patches),
        source='exact_0922_client_compiled_geometry',
        local_collision_policy='body_height_clipped_triangles_against_original_2.15m_disk')
    graph['bake']['local_meshes']['circled_passage_validation'] = prove(graph)
    previous = set(graph.get('navigation_previous_sha256s', ()))
    previous.add(hashlib.sha256(raw).hexdigest())
    graph['navigation_previous_sha256s'] = sorted(previous)
    for key in ('origin','width','height','cell_size','heights_mm','links','hazards',
                'routes','spawn_formations','objective_bases','spawn_anchors'):
        assert graph[key] == json.loads(raw)[key], key
    Path(output).write_text(json.dumps(graph,separators=(',',':'))+'\n',encoding='utf8',newline='\n')
    print('Candidate written to',output,flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    build(args.client,args.output)
