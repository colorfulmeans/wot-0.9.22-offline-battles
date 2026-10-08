"""Read-only editor views of raw baked cells; never changes route admission."""
import math

COLORS = {
    'available': ('#46c7b1', (70, 199, 177, 70)),
    'missing_ground': ('#ffb347', (255, 179, 71, 145)),
    'navigation_hazard': ('#ee5869', (238, 88, 105, 140)),
    'no_navigation_links': ('#a88bdd', (168, 139, 221, 140)),
}


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
    return cell_status(graph, cell_for(graph, point), bounds)


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


def check_map(profile, name, graph, contract):
    """Check unedited defaults as well as every saved class/team override."""
    entry = contract.map_settings(profile, name)
    edits = entry.get('default_routes', ())
    routes = []
    for team, defaults in graph.get('routes', {}).items():
        for source in defaults:
            matching = [r for r in edits if str(r['team']) == str(team) and r['id'] == source['id']]
            if not any(r.get('class_tag', 'all') == 'all' for r in matching):
                routes.append(('%s:%s' % (team, source['id']), source['waypoints']))
    routes.extend(('%s:%s' % (r['team'], contract.default_route_id(r)), r['points']) for r in edits)
    routes.extend((r['id'], r['points']) for r in entry.get('routes', ()))
    results = []
    for identity, points in routes:
        issues = route_issues(graph, points, contract.MAPS[name]['bounds'])
        results.append((identity, 'navigation_cells_issues' if issues else 'navigation_cells_clear', issues))
    for spot in entry.get('positions', ()):
        status = point_status(graph, spot['point'], contract.MAPS[name]['bounds'])
        issues = [] if status == 'available' else [dict(status='navigation_node_issue', reason=status,
            nodes=[1], points=[list(spot['point'])])]
        results.append((spot['id'], 'navigation_cells_issues' if issues else 'navigation_cells_clear', issues))
    return results


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
    return image
