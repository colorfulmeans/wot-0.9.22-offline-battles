"""Editor endpoint ownership; never changes a submitted route on save."""
import math


def symmetry_allowed(graph):
    starts = graph.get('spawn_anchors', ())
    bases = graph.get('objective_bases', ())
    radii = graph.get('objective_base_radii', ())
    return (len(starts) == len(bases) == len(radii) == 2 and all(
        math.hypot(a[0]-b[0], a[1]-b[1]) <= radius
        for a, b, radius in zip(starts, bases, radii)))


def anchors(graph, team):
    starts = graph['spawn_anchors']
    return [list(starts[team-1])+[0], list(starts[2-team])+[0]]


def insertion_index(points, selected):
    return min(len(points)-1, selected+1 if selected is not None else len(points)-1)


def same_point(a, b):
    return all(abs(float(x)-float(y)) <= .00011 for x,y in zip(a[:2],b[:2]))


def validate(document, contract, graph_loader):
    for name, settings in document['maps'].items():
        graph = graph_loader(name)
        baseline = contract.default_map(name).get('default_routes', ())
        for kind in ('routes', 'default_routes'):
            for route in settings.get(kind, ()):
                points = route['points']
                ends = anchors(graph, route['team'])
                if route.get('purpose')=='spg_attack':
                    ends=[list(p)+[0] for p in (graph['objective_bases'][route['team']-1],graph['objective_bases'][2-route['team']])]
                if route.get('defense') and not same_point(route['defense']['points'][-1],graph['objective_bases'][route['team']-1]):
                    raise contract.TacticsError('Defense connection must end at the own base')
                if kind == 'default_routes':
                    reference = next((r for r in baseline if r['team'] == route['team']
                        and r['id'] == route['id'] and r.get('class_tag', 'all') == route.get('class_tag', 'all')), None)
                    if reference is None:
                        reference = next((r for r in baseline if r['team'] == route['team']
                            and r['id'] == route['id'] and r.get('class_tag', 'all') == 'all'), None)
                    if reference is not None:
                        ends[1] = reference['points'][-1]
                if (len(points) < 2 or not same_point(points[0],ends[0])
                        or not same_point(points[-1],ends[1])):
                    raise contract.TacticsError('Route endpoints are fixed: %s / %s' % (name, route['id']))
                if route.get('symmetric') and not symmetry_allowed(graph):
                    raise contract.TacticsError('Route symmetry is unavailable on this map: '+name)

        positions=settings.get('positions',())
        by_id=dict((p['id'],p) for p in positions)
        for parking in positions:
            if parking.get('travel') and not same_point(parking['travel'][0],graph['objective_bases'][parking['team']-1]):
                raise contract.TacticsError('SPG deployment connection must start at the own base')
            for identity,points in parking.get('links',{}).items():
                if identity in settings.get('deleted_positions',()):raise contract.TacticsError('Detached SPG parking connection')
                peer=by_id.get(identity)
                if peer is None:
                    peer=next((p for p in contract.default_map(name).get('positions',()) if p['id']==identity),None)
                if peer is None or peer['team']!=parking['team'] or not same_point(points[-1],peer['point']):
                    raise contract.TacticsError('Detached SPG parking connection')
