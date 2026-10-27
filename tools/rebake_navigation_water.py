"""Rebake water eligibility on every retained grid without resetting gameplay.

Decode the pinned terrain/water/collision again. Preserve grid placement,
authored layers, routes, spawns and existing proved links. Recompute every
cell's water evidence; newly eligible water/shore cells need the same terrain,
collision, shoulder and link proofs as the ordinary baker. This is not a
runtime override and does not infer water from missing navigation heights.
"""
import argparse
import collections
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bake_navigation_0922 as baker


def geometry(client, name):
    original = baker.refine_terrain_edges
    try:
        baker.refine_terrain_edges = lambda graph, terrain, obstacles, legacy: (terrain, obstacles, legacy)
        return baker.bake_map_graph(client, name, existing_graph={'map': name})
    finally:
        baker.refine_terrain_edges = original


def validate_routes(graph, legacy):
    """Validate additive passages with the shipping layered search.

    The baseline validator knows only the coarse layer. Using it alone on
    Windstorm reports the same pre-existing 4.15x detour before and after this
    bake, even though the shipping local bridge mesh provides the passage.
    Check every authored segment through that mesh instead of suppressing it.
    """
    if not graph.get('local_meshes'):
        return legacy.validate_graph(graph, dict(bases=graph['bases']))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'launcher'))
    from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
    from bot_tactics_navigation import connection
    grid = TerrainGrid(lambda *a: None, baked_graph=graph)
    cases = set()
    for routes in graph['routes'].values():
        for route in routes:
            cases.update((tuple(a[:2]), tuple(b[:2])) for a, b in zip(route['waypoints'], route['waypoints'][1:]))
    proofs = []
    for start, end in sorted(cases):
        receipt = connection(grid, graph, start, end)
        if not receipt['connected']:
            raise ValueError('shipping layered route incomplete: %r' % receipt)
        direct = max(graph['cell_size'], math.hypot(end[0]-start[0], end[1]-start[1]))
        receipt['detour'] = receipt['length']/direct
        if receipt['detour'] > legacy.MAX_ROUTE_DETOUR:
            raise ValueError('shipping layered route excessive detour: %r' % receipt)
        proofs.append(receipt)
    return dict(water_rebake_layered_routes=proofs)


def rebake_layer(layer, terrain, obstacles, legacy, previous_limit=.9):
    """Measure all cells, retaining non-water and authored lower-layer proofs."""
    result = copy.deepcopy(layer)
    width, height, size = layer['width'], layer['height'], layer['cell_size']
    old_limit = float(getattr(legacy, 'WATER_DEPTH_LIMIT'))
    limit = baker.NAVIGABLE_WATER_DEPTH
    candidates = set()
    depths = []
    changed = []
    count = collections.Counter()
    for index, old_height in enumerate(layer['heights_mm']):
        x = layer['origin'][0] + index % width * size
        z = layer['origin'][1] + index // width * size
        # An existing bridge/underpass layer is authoritative. In an absent
        # cell the exact static geometry supplies the ground, never a nearby
        # route node or zero-height substitution.
        ground = old_height / 1000. if old_height is not None else legacy._ground_height(terrain, obstacles, x, z)
        depth = None if ground is None else terrain.water_depth(x, z, ground)
        depths.append(depth)
        count['cells_measured'] += 1
        previous = int(layer['hazards'][index])
        hazard = previous
        if depth is None:
            count['missing_ground'] += 1
            continue
        if old_height is not None:
            # Reviewed deeper fords retain their existing scoped permission.
            # Ordinary 0.9--1.2 m water is no longer a special ford.
            # Authored navigation heights have millimetre precision.
            if depth <= limit + .00051:
                hazard &= ~legacy.HAZARD_SHALLOW_WATER
            elif not previous & legacy.HAZARD_SHALLOW_WATER:
                raise ValueError('existing node has unreviewed deep water: %r' % ((x, ground, z),))
        elif previous & (legacy.HAZARD_WATER | legacy.HAZARD_EDGE) and previous_limit < limit:
            hazard &= ~legacy.HAZARD_SHALLOW_WATER
            if depth > limit + 1e-7:
                hazard = (hazard & ~legacy.HAZARD_EDGE) | legacy.HAZARD_WATER
            else:
                hazard &= ~legacy.HAZARD_WATER
                # Only the changed water rule may revive an old cell. A dry
                # cliff or obstacle is not reopened by this water rebake.
                legacy.WATER_DEPTH_LIMIT = previous_limit
                try:
                    old_supported = depth <= previous_limit and baker.continuous_terrain_edge_clearance(
                        terrain, obstacles, x, z, ground, legacy, legacy._has_safe_edge_clearance)
                finally:
                    legacy.WATER_DEPTH_LIMIT = limit
                supported = baker.continuous_terrain_edge_clearance(
                    terrain, obstacles, x, z, ground, legacy, legacy._has_safe_edge_clearance)
                margin = (legacy.BRIDGE_OBSTACLE_MARGIN if obstacles.surface_height(x, z) is not None
                          else legacy.VEHICLE_HALF_WIDTH)
                if not old_supported and supported and not obstacles.blocked(x, z, ground, margin=margin):
                    result['heights_mm'][index] = int(round(ground * 1000.))
                    result['links'][index] = 0
                    hazard &= ~(legacy.HAZARD_WATER | legacy.HAZARD_EDGE)
                    candidates.add(index)
                else:
                    hazard |= legacy.HAZARD_EDGE
        elif old_height is None and depth > limit + 1e-7:
            hazard |= legacy.HAZARD_WATER
        result['hazards'][index] = hazard
        if hazard != previous or result['heights_mm'][index] != old_height:
            changed.append(index)
    legacy.WATER_DEPTH_LIMIT = old_limit
    directions = [tuple(d) for d in layer.get('directions', legacy.DIRECTIONS)]
    checked, added = 0, 0
    def point(index):
        return (layer['origin'][0]+index % width*size, result['heights_mm'][index]/1000.,
                layer['origin'][1]+index//width*size)
    for index in sorted(candidates):
        x, z = index % width, index//width
        for bit, (dx, dz) in enumerate(directions):
            nx, nz = x+dx, z+dz
            if not (0 <= nx < width and 0 <= nz < height):
                continue
            following = nz*width+nx
            if result['heights_mm'][following] is None:
                continue
            if dx and dz and (result['heights_mm'][z*width+nx] is None or result['heights_mm'][nz*width+x] is None):
                continue
            checked += 1
            start, end = point(index), point(following)
            if (baker._resolution_segment_clear(terrain, obstacles, start, end, legacy, legacy._segment_clear) and
                    baker._resolution_segment_clear(terrain, obstacles, end, start, legacy, legacy._segment_clear)):
                result['links'][index] |= 1 << bit
                result['links'][following] |= 1 << directions.index((-dx, -dz))
                added += 1
    # Do not publish isolated water pockets as navigation. Every added cell
    # must connect back to the already reviewed graph, in both directions.
    connected, queue = set(), collections.deque()
    for index in candidates:
        x, z = index % width, index//width
        if any(result['links'][index] & (1 << bit) and (z+dz)*width+x+dx not in candidates and
               layer['links'][(z+dz)*width+x+dx]
               for bit, (dx, dz) in enumerate(directions)):
            connected.add(index); queue.append(index)
    while queue:
        index = queue.popleft()
        x, z = index % width, index//width
        for bit, (dx, dz) in enumerate(directions):
            following = (z+dz)*width+x+dx
            if result['links'][index] & (1 << bit) and following in candidates and following not in connected:
                connected.add(following); queue.append(following)
    for index in candidates-connected:
        x, z = index % width, index//width
        for bit, (dx, dz) in enumerate(directions):
            if not result['links'][index] & (1 << bit):
                continue
            following = (z+dz)*width+x+dx
            reverse = directions.index((-dx, -dz))
            if not layer['links'][following] & (1 << reverse):
                result['links'][following] &= ~(1 << reverse)
        result['heights_mm'][index] = None
        result['links'][index] = layer['links'][index]
        result['hazards'][index] |= legacy.HAZARD_EDGE
    changed = [i for i in range(width*height) if any(
        layer[key][i] != result[key][i] for key in ('heights_mm', 'links', 'hazards'))]
    count.update(revived_cells=len(connected), changed_cells=len(changed),
                 candidate_edges_checked=checked, proved_edge_pairs=added)
    count['water_depth_limit'] = limit
    count['deep_water_cells'] = sum(d is not None and d > limit for d in depths)
    count['changed_indices'] = changed
    return result, dict(count)


def build(client, previous, output):
    raw = Path(previous).read_bytes()
    original = json.loads(raw)
    terrain, obstacles, legacy = geometry(client, original['map'])
    graph, receipt = rebake_layer(original, terrain, obstacles, legacy,
                                  original['bake']['water_depth_limit'])
    layers = []
    patches = []
    for patch in original.get('local_meshes', ()):
        previous_limit = original['bake']['water_depth_limit']
        for details in original['bake'].get('local_meshes', {}).values():
            if (isinstance(details, dict) and details.get('region') and
                    list(details['region'][:2]) == patch['origin'] and
                    'water_depth_limit' in details):
                previous_limit = details['water_depth_limit']
        rebuilt, proof = rebake_layer(patch, terrain, obstacles, legacy, previous_limit)
        patches.append(rebuilt); layers.append(proof)
    if 'local_meshes' in original:
        graph['local_meshes'] = patches
    if (original['bake'].get('water_depth_limit') == legacy.WATER_DEPTH_LIMIT and
            original['bake'].get('shallow_water_threshold') == legacy.SHALLOW_WATER_THRESHOLD and
            original['bake'].get('water_policy_rebake', {}).get('all_cells_measured') and
            all(all(a[k] == b[k] for k in ('heights_mm','hazards','links'))
                for a,b in zip([original]+original.get('local_meshes',[]),[graph]+graph.get('local_meshes',[])))):
        Path(output).parent.mkdir(parents=True,exist_ok=True)
        Path(output).write_bytes(raw)
        print(graph['map'], 'remeasured; retained identical geometry and provenance',flush=True)
        return
    bake = graph['bake']
    bake['water_depth_limit'] = legacy.WATER_DEPTH_LIMIT
    bake['shallow_water_threshold'] = legacy.SHALLOW_WATER_THRESHOLD
    bake['water_policy_rebake'] = dict(base=receipt, local_layers=layers,
        source='pinned #1513 terrain, BWWa water and compiled collision',
        previous_water_depth_limit=original['bake']['water_depth_limit'],
        collision_edge_sample_metres=.25, navigation_strategy_changed=False,
        non_water_geometry_retained=True, all_cells_measured=True)
    identities = set(original.get('navigation_previous_sha256s', ()))
    identities.add(hashlib.sha256(raw).hexdigest())
    if original.get('navigation_previous_sha256'):
        identities.add(original['navigation_previous_sha256'])
    graph['navigation_previous_sha256s'] = sorted(identities)
    for key in ('routes','spawn_formations','spawn_anchors','bases','objective_bases','bounds',
                'origin','width','height','cell_size'):
        assert graph.get(key) == original.get(key), key
    graph['validation'].update(validate_routes(graph, legacy))
    for key, bit in (('rejected_water_nodes', 1), ('rejected_edge_nodes', 2), ('shallow_water_nodes', 4)):
        bake[key] = sum(bool(h & bit) for h in graph['hazards'])
    bake['retained_nodes'] = sum(h is not None for h in graph['heights_mm'])
    components = legacy._connected_components(graph)
    previous_components = legacy._connected_components(original)
    if len(components) > len(previous_components):
        raise ValueError('water rebake introduced a disconnected component')
    bake['water_policy_rebake']['previous_actual_components'] = previous_components
    bake['water_policy_rebake']['actual_components'] = components
    graph['validation'].update(components=len(components),largest_component=components[0],
        largest_fraction=round(components[0]/float(sum(components)),5))
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_bytes((json.dumps(graph, separators=(',', ':'))+'\n').encode())
    print(json.dumps(dict(map=graph['map'], cells_measured=receipt['cells_measured'],
        revived_cells=receipt['revived_cells'], local_layers=len(layers),
        route_segments=graph['validation']['route_segments'])), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True)
    parser.add_argument('--previous', required=True, type=Path)
    parser.add_argument('--output', required=True)
    parser.add_argument('--all', action='store_true',help='Read all 41 maps from --previous directory; write only into --output staging directory')
    parser.add_argument('--jobs',type=int,default=4)
    args = parser.parse_args()
    if not args.all:
        build(args.client, args.previous, args.output)
        return 0
    files=[p for p in sorted(args.previous.glob('*.json')) if p.name!='manifest.json']
    if len(files)!=41 or args.jobs<1:
        parser.error('batch requires the complete 41-map input and a positive job count')
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    def run(path):
        with (output/(path.stem+'.log')).open('w',encoding='utf8') as log:
            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),
                '--client',args.client,'--previous',str(path.resolve()),
                '--output',str((output/path.name).resolve())],stdout=log,stderr=subprocess.STDOUT)
        return path.stem,result.returncode
    failed=[]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for future in as_completed([pool.submit(run,path) for path in files]):
            name,status=future.result();print(name,'FAILED' if status else 'measured and validated',flush=True)
            if status:failed.append(name)
    if failed:
        raise ValueError('batch incomplete; do not publish: %r'%failed)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
