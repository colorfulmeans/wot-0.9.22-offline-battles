"""Rebake selected grids without changing authored gameplay or driving laws."""
import argparse
import copy
import json
import math
from pathlib import Path

import bake_navigation_0922 as baker

GAMEPLAY_FIELDS = (
    'bases', 'bounds', 'objective_bases', 'objective_base_radii',
    'ctf_spawn_points', 'spawn_anchors', 'spawn_anchor_source',
    'spawn_formations', 'spawn_formation_source',
)
NARROWS = (((182.606,43.685),(175.887,87.135)),
           ((175.887,87.135),(180.55,116.688)),
           ((190.536,151.486),(216.694,216.882)))


def verify_geometry(graph, terrain, obstacles, navgrid):
    """Prove Default route segments against decoded collision in both directions."""
    from gui.mods.offline_lan_0922 import bot_tactics
    pairs = set(NARROWS)
    for route in bot_tactics.default_map(graph['map']).get('default_routes', ()):
        if not route.get('disabled'):
            points = route['points']
            pairs.update((tuple(a[:2]),tuple(b[:2]))
                         for a,b in zip(points,points[1:]))
    records = []
    for first,last in sorted(pairs):
        start,_=navgrid._nearest_node(graph,first)
        end,_=navgrid._nearest_node(graph,last)
        path,distance=navgrid._graph_path(graph,start,end)
        if not path:
            raise ValueError('Default route segment has no complete path')
        dense=[]
        for a,b in zip(path,path[1:]):
            pa,pb=navgrid._node_point(graph,a),navgrid._node_point(graph,b)
            steps=max(1,int(math.ceil(math.hypot(pb[0]-pa[0],pb[1]-pa[1])/.25)))
            dense.extend((pa[0]+(pb[0]-pa[0])*i/steps,
                          pa[1]+(pb[1]-pa[1])*i/steps) for i in range(steps))
        dense.append(navgrid._node_point(graph,path[-1]))
        proof=baker._sample_reviewed_terrain_path(terrain,obstacles,navgrid,
            dense,'resolution complete route',navgrid.WATER_DEPTH_LIMIT,
            navgrid.VEHICLE_HALF_WIDTH,allow_surfaces=True,
            require_edge_clearance=True,use_surface_ground=True)
        records.append(dict(start=first,end=last,length=round(distance,4),
                            proof=proof,both_directions=True))
    return records


def retain_gameplay(graph, previous):
    if graph['map'] != previous['map']:
        raise ValueError('resolution rebake map mismatch')
    for key in GAMEPLAY_FIELDS:
        if key in previous:
            graph[key] = copy.deepcopy(previous[key])
        else:
            graph.pop(key, None)
    # Fresh spawn packing is not evidence for the retained old layout.
    fresh = graph['validation']
    graph['validation'] = baker.navgrid.validate_graph(graph, dict(bases=graph['bases']))
    graph['validation'].update({key:copy.deepcopy(value)
        for key,value in previous['validation'].items() if key.startswith('spawn_')})
    graph['bake']['resolution_rebake'] = dict(
        previous_cell_size=previous['cell_size'], cell_size=graph['cell_size'],
        preserved_gameplay_fields=list(GAMEPLAY_FIELDS),
        fresh_geometry_validation=fresh,
        sampling_policy='nested_4m_centres_and_2m_midpoints',
        collision_edge_sample_metres=.25,
        retained_spawn_layout_requires_native_acceptance=True,
        navigation_policy_changed=False)
    return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True)
    parser.add_argument('--map', required=True)
    parser.add_argument('--cell-size', required=True, type=float)
    parser.add_argument('--previous', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    raw = args.previous.read_bytes()
    previous = json.loads(raw)
    captured={}
    original=baker.install_reviewed_map_adapters
    def observe(graph,terrain,obstacles,navgrid,name):
        captured.update(terrain=terrain,obstacles=obstacles,navgrid=navgrid)
        return original(graph,terrain,obstacles,navgrid,name)
    baker.install_reviewed_map_adapters=observe
    try:
        graph = baker.bake_map_graph(args.client,args.map,cell_size=args.cell_size)
    finally:
        baker.install_reviewed_map_adapters=original
    retain_gameplay(graph,previous)
    # The graph carries no route data; the Default route proofs gate the bake.
    proofs=verify_geometry(graph,captured['terrain'],captured['obstacles'],captured['legacy'])
    baker.navgrid.write_graph(str(args.output), graph)
    print(json.dumps(dict(map=args.map, cell_size=graph['cell_size'],
                          validated_segments=len(proofs),
                          validation=graph['validation']), sort_keys=True))


if __name__ == '__main__':
    main()
