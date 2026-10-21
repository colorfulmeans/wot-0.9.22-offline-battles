"""Read-only editor evidence from the shipping base and additive local meshes."""
import math
import json
import time
from pathlib import Path

COLORS = {
    'available': ('#46c7b1', (70, 199, 177, 70)),
    'missing_ground': ('#ffb347', (255, 179, 71, 145)),
    'navigation_hazard': ('#ee5869', (238, 88, 105, 140)),
    'no_navigation_links': ('#a88bdd', (168, 139, 221, 140)),
}
DANGER_COLOR = (255, 45, 45, 155)


def classified_hazards(graph):
    """Use the worker's actual shore classification, including local layers."""
    from gui.mods.offline_lan_0922.prebaked_navigation import with_shore_hazards
    return with_shore_hazards(graph)


def hazard_at(graph, point):
    """Show flags used by either the pose guard or the motion grid.

    The motion grid can reuse an exactly coincident base node; a local pose
    guard instead reads its local mark. Display their union rather than hide
    a real veto when reviewing a patch boundary.
    """
    from gui.mods.offline_lan_0922.prebaked_navigation import local_cell_at
    local = local_cell_at(graph, (point[0], 0., point[1]))
    if local is not None:
        layer, index = local
    else:
        layer = graph
        x, z = cell_for(graph, point)
        if not (0 <= x < graph['width'] and 0 <= z < graph['height']):
            return 0
        index = z*graph['width']+x
    value = int(layer['hazards'][index])
    for patch in graph.get('local_meshes', ()):
        x = (point[0]-patch['origin'][0])/patch['cell_size']
        z = (point[1]-patch['origin'][1])/patch['cell_size']
        if not (0 <= x <= patch['width']-1 and 0 <= z <= patch['height']-1):
            continue
        i = int(math.floor(z+.5))*patch['width']+int(math.floor(x+.5))
        motion = int(patch['hazards'][i])
        wx = patch['origin'][0]+i % patch['width']*patch['cell_size']
        wz = patch['origin'][1]+i//patch['width']*patch['cell_size']
        bx, bz = cell_for(graph, (wx, wz))
        if 0 <= bx < graph['width'] and 0 <= bz < graph['height']:
            j = bz*graph['width']+bx
            base_height, local_height = graph['heights_mm'][j], patch['heights_mm'][i]
            if (local_height is not None and base_height is not None and
                    not int(graph['hazards'][j]) & 3 and abs(base_height-local_height) < 10 and
                    abs(graph['origin'][0]+bx*graph['cell_size']-wx) < 1e-6 and
                    abs(graph['origin'][1]+bz*graph['cell_size']-wz) < 1e-6):
                motion = int(graph['hazards'][j])
        return value | motion
    return value


def danger_parameters(graph):
    """Raw reviewed values; the UI translates their meanings, not the policy."""
    bake = graph.get('bake', {})
    return dict(water_depth=bake.get('water_depth_limit'),
        edge_radii=bake.get('edge_clearance_radii', ()),
        max_grade=bake.get('max_grade'),
        half_width=bake.get('vehicle_half_width'),
        base_cell_size=graph['cell_size'],
        local_cell_sizes=sorted({p['cell_size'] for p in graph.get('local_meshes', ())}),
        ford_depths=sorted({p['local_water_depth_limit'] for p in bake.get('verified_local_adapters', ())
                           if p.get('kind') == 'ford' and p.get('local_water_depth_limit', 0) > bake.get('water_depth_limit', 0)}))


def cell_for(graph, point):
    return tuple(int(math.floor((float(point[i]) - graph['origin'][i]) /
                                graph['cell_size'] + .5)) for i in (0, 1))


def cell_status(graph, cell, bounds):
    x, z = cell
    if not (0 <= x < graph['width'] and 0 <= z < graph['height']):
        return 'outside_bounds'
    wx = graph['origin'][0] + x * graph['cell_size']
    wz = graph['origin'][1] + z * graph['cell_size']
    if not (bounds[0] <= wx <= bounds[2] and bounds[1] <= wz <= bounds[3]):
        return 'outside_bounds'
    index = z * graph['width'] + x
    if graph['heights_mm'][index] is None:
        return 'missing_ground'
    if graph['hazards'][index]:
        return 'navigation_hazard'
    if not graph['links'][index]:
        return 'no_navigation_links'
    return 'available'


def segment_cells(start, end):
    """Match the baked straight-corridor walk, without snapping missing starts."""
    x, z = start
    tx, tz = end
    dx, dz = abs(tx - x), abs(tz - z)
    sx, sz = (1 if x < tx else -1), (1 if z < tz else -1)
    error = dx - dz
    yield x, z
    while (x, z) != (tx, tz):
        double = error * 2
        if double > -dz:
            error -= dz
            x += sx
        if double < dx:
            error += dx
            z += sz
        yield x, z


def point_status(graph, point, bounds):
    if not (bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]):
        return 'outside_bounds'
    base = cell_status(graph, cell_for(graph, point), bounds)
    if base == 'available':
        return base
    for patch in graph.get('local_meshes', ()):
        x, z = point[:2]
        ox, oz = patch['origin']; size = patch['cell_size']
        if ox <= x <= ox+(patch['width']-1)*size and oz <= z <= oz+(patch['height']-1)*size:
            status = cell_status(patch, cell_for(patch, point), bounds)
            if status == 'available':
                return status
    return base


def route_issues(graph, points, bounds):
    issues = []
    for index, point in enumerate(points):
        status = point_status(graph, point, bounds)
        if status != 'available':
            issues.append(dict(status='navigation_node_issue', reason=status,
                nodes=[index + 1], points=[list(point[:2])]))
    directions = [tuple(d) for d in graph['directions']]
    for index in range(len(points) - 1):
        if any(point_status(graph, p, bounds) == 'outside_bounds' for p in points[index:index + 2]):
            continue
        # The drawn line is a static reference, not the A* route travelled.
        counts, samples, previous = {}, {}, None
        for cell in segment_cells(cell_for(graph, points[index]),
                                  cell_for(graph, points[index + 1])):
            status = cell_status(graph, cell, bounds)
            if status == 'available' and previous is not None:
                delta = (cell[0] - previous[0], cell[1] - previous[1])
                if cell_status(graph, previous, bounds) == 'available':
                    bit = directions.index(delta)
                    old = previous[1] * graph['width'] + previous[0]
                    if not int(graph['links'][old]) & (1 << bit):
                        status = 'navigation_link_missing'
            if status != 'available':
                counts[status] = counts.get(status, 0) + 1
                examples = samples.setdefault(status, [])
                if len(examples) < 6:
                    examples.append([graph['origin'][0] + cell[0] * graph['cell_size'],
                                     graph['origin'][1] + cell[1] * graph['cell_size']])
            previous = cell
        for reason, count in sorted(counts.items()):
            issues.append(dict(status='navigation_segment_issue', reason=reason,
                nodes=[index + 1, index + 2],
                points=[list(p[:2]) for p in points[index:index + 2]],
                cell_count=count, cells=samples[reason]))
    return issues


def check_map(profile, name, graph, contract, receipt=None):
    """Check unedited defaults as well as every saved class/team override."""
    entry = contract.map_settings(profile, name)
    edits = entry.get('default_routes', ())
    routes = []
    for team, defaults in graph.get('routes', {}).items():
        for source in defaults:
            matching = [r for r in edits if str(r['team']) == str(team) and r['id'] == source['id']]
            if not any(r.get('class_tag', 'all') == 'all' for r in matching):
                routes.append(('%s:%s' % (team, source['id']), source['waypoints']))
    routes.extend(('%s:%s' % (r['team'], contract.default_route_id(r)), r['points'])
                  for r in edits if not r.get('disabled'))
    routes.extend((r['id'], r['points']) for r in entry.get('routes', ()))
    from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
    grid = TerrainGrid(lambda *args: None, baked_graph=graph)
    results, receipts = [], []
    for identity, points in routes:
        issues = []
        bounds = contract.MAPS[name]['bounds']
        for index, point in enumerate(points):
            status = point_status(graph, point, bounds)
            if status != 'available':
                issues.append(dict(status='navigation_node_issue', reason=status,
                                   nodes=[index+1], points=[list(point[:2])]))
        for index, (a, b) in enumerate(zip(points, points[1:])):
            proof = connection(grid, graph, a, b)
            receipts.append(dict(route=identity, nodes=[index+1,index+2], **proof))
            if not proof['connected']:
                issues.append(dict(status='waypoints_disconnected', nodes=[index+1,index+2],
                                   points=[list(a[:2]),list(b[:2])]))
        for index, point in enumerate(points):
            for slot, place in enumerate(contract.waiting_positions(point)):
                status = point_status(graph, place, bounds)
                checks = [(point, place, 'wait_place_disconnected')]
                if index+1 < len(points):
                    checks.append((place, points[index+1], 'wait_place_exit_disconnected'))
                if status != 'available':
                    issues.append(dict(status='wait_place_unusable', nodes=[index+1],
                                       points=[list(place[:2])],wait_slot=slot+1))
                for a,b,reason in checks:
                    proof = connection(grid, graph, a, b)
                    receipts.append(dict(route=identity, nodes=[index+1],wait_slot=slot+1, **proof))
                    if status == 'available' and not proof['connected']:
                        issues.append(dict(status=reason,nodes=[index+1],
                                           points=[list(a[:2]),list(b[:2])],wait_slot=slot+1))
        results.append((identity, 'navigation_cells_issues' if issues else 'baked_route_connected', issues))
    # Parking has a radius/vehicle-envelope contract beyond route connectivity.
    # Retain its existing check rather than silently replacing it by one point.
    from gui.mods.offline_lan_0922 import bot_tactics_runtime
    parking_profile={'maps':{name:{'positions':entry.get('positions',())}}}
    results.extend(bot_tactics_runtime.authoring_check(parking_profile,name,graph,details=True))
    evidence=dict(
        map=name,base_cell_size=graph['cell_size'],local_meshes=[dict(
            origin=p['origin'],cell_size=p['cell_size'],width=p['width'],height=p['height'])
            for p in graph.get('local_meshes',())],connections=receipts,results=results)
    if receipt is not None:receipt(evidence)
    return results


def persist_receipt(evidence, path=None):
    """Write into the launcher log already collected by error reports."""
    try:
        from . import core, error_reports
    except ImportError:
        import core, error_reports
    target=Path(path or core.launcher_log_path())
    target.parent.mkdir(parents=True,exist_ok=True)
    with error_reports.LAUNCHER_LOG_LOCK:
        with target.open('a',encoding='utf-8',newline='\n') as stream:
            stream.write('[%s] EDITOR NAVIGATION CHECK %s\n'%(time.strftime('%Y-%m-%d %H:%M:%S'),
                json.dumps(evidence,separators=(',',':'))))


def connection(grid, graph, first, last):
    """Use the shipping graph and planner; never accept its partial frontier."""
    start=(first[0],0.,first[1]);end=(last[0],0.,last[1])
    bounds=grid.bounds
    if any(not(bounds[0]<=p[0]<=bounds[2] and bounds[1]<=p[2]<=bounds[3]) for p in (start,end)):
        return dict(start=list(first[:2]),end=list(last[:2]),connected=False,
                    target_cell=None,reached_cell=None,path_nodes=0,length=0.)
    path=grid.plan(start,end,max_expansions=len(grid._baked_heights)+1)
    target=grid._nearest_baked_cell(grid.cell_for(end),3)
    reached=grid.cell_for(path[-1]) if path else None
    target_point=grid.point_for(target,grid._baked_cell_height(target)) if target is not None else None
    # An exact appended endpoint also names its un-snapped coarse cell.
    complete=bool(path) and (target_point is not None and
        math.hypot(path[-1][0]-target_point[0],path[-1][2]-target_point[2]) < .001 or
        math.hypot(path[-1][0]-end[0],path[-1][2]-end[2]) < .001)
    if complete and target_point is not None and math.hypot(path[-1][0]-target_point[0],path[-1][2]-target_point[2]) < .001:
        reached=target
    return dict(start=list(first[:2]),end=list(last[:2]),connected=complete,
                target_cell=target,reached_cell=reached,path_nodes=len(path or ()),
                length=sum(math.hypot(b[0]-a[0],b[2]-a[2]) for a,b in zip(path or (), (path or ())[1:])))


def overlay_image(graph, bounds):
    """One cached raster, rather than thousands of live Tk canvas objects."""
    from PIL import Image, ImageDraw
    width, height = graph['width'], graph['height']
    image = Image.new('RGBA', (width * 3, height * 3))
    draw = ImageDraw.Draw(image)
    for z in range(height):
        for x in range(width):
            status = cell_status(graph, (x, z), bounds)
            if status == 'outside_bounds':
                continue
            px, py = x * 3, (height - 1 - z) * 3
            draw.rectangle((px, py, px + 2, py + 2), fill=COLORS[status][1],
                           outline=(180, 200, 200, 45))
    patches=graph.get('local_meshes',())
    if patches:
        smallest=min(p['cell_size'] for p in patches)
        factor=max(1,int(math.ceil(graph['cell_size']/smallest)))
        image=image.resize((image.width*factor,image.height*factor),Image.Resampling.NEAREST)
        draw=ImageDraw.Draw(image)
        scale=3.*factor/graph['cell_size']
        left=graph['origin'][0]-graph['cell_size']*.5
        top=graph['origin'][1]+(height-.5)*graph['cell_size']
        for patch in patches:
            size=patch['cell_size']
            for z in range(patch['height']):
                for x in range(patch['width']):
                    wx=patch['origin'][0]+x*size;wz=patch['origin'][1]+z*size
                    status=point_status(graph,(wx,wz),bounds)
                    if status == 'outside_bounds':continue
                    px=round((wx-size*.5-left)*scale);py=round((top-wz-size*.5)*scale)
                    span=max(1,round(size*scale))
                    draw.rectangle((px,py,px+span-1,py+span-1),fill=COLORS[status][1],outline=(180,200,200,45))
    return image


def danger_overlay_image(graph, bounds):
    """Red hazard raster; supported local cells replace coarse marks exactly.

    Missing local cells with no hazard evidence retain the parent evidence.
    A red mark describes a policy flag, not a claim of absolute impassability:
    bit 4 remains the original reviewed, conditional ford permission.
    """
    from PIL import Image, ImageDraw
    graph = classified_hazards(graph)
    size = graph['cell_size']
    patches = graph.get('local_meshes', ())
    minimum = min([size]+[p['cell_size'] for p in patches])
    factor = max(1, int(math.ceil(size/minimum)))
    scale = 3.*factor/size
    image = Image.new('RGBA', (graph['width']*3*factor, graph['height']*3*factor))
    draw = ImageDraw.Draw(image)
    left = graph['origin'][0]-size*.5
    top = graph['origin'][1]+(graph['height']-.5)*size
    for layer in (graph,)+tuple(reversed(patches)):
        cell = layer['cell_size']
        for index, value in enumerate(layer['hazards']):
            if layer is not graph and layer['heights_mm'][index] is None and not value:
                continue
            x = layer['origin'][0]+index % layer['width']*cell
            z = layer['origin'][1]+index//layer['width']*cell
            if not (bounds[0] <= x <= bounds[2] and bounds[1] <= z <= bounds[3]):
                continue
            x0, x1, z0, z1 = x-cell*.5, x+cell*.5, z-cell*.5, z+cell*.5
            if layer is not graph:
                # LocalMeshes.cell owns only the rectangle between its first
                # and last centres, not the outside half of boundary cells.
                x0, x1 = max(x0,layer['origin'][0]), min(x1,layer['origin'][0]+(layer['width']-1)*cell)
                z0, z1 = max(z0,layer['origin'][1]), min(z1,layer['origin'][1]+(layer['height']-1)*cell)
            px, py = round((x0-left)*scale), round((top-z1)*scale)
            right, bottom = round((x1-left)*scale), round((top-z0)*scale)
            flags = hazard_at(graph, (x, z)) if layer is not graph else int(value)
            if right > px and bottom > py:
                draw.rectangle((px, py, right-1, bottom-1),
                               fill=DANGER_COLOR if flags & 15 else (0, 0, 0, 0))
    return image
