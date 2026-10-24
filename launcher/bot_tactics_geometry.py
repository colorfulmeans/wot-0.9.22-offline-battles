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


def validate(document, contract, graph_loader):
    for name, settings in document['maps'].items():
        graph = graph_loader(name)
        baseline = contract.default_map(name).get('default_routes', ())
        for kind in ('routes', 'default_routes'):
            for route in settings.get(kind, ()):
                points = route['points']
                ends = anchors(graph, route['team'])
                if kind == 'default_routes':
                    reference = next((r for r in baseline if r['team'] == route['team']
                        and r['id'] == route['id'] and r.get('class_tag', 'all') == route.get('class_tag', 'all')), None)
                    if reference is None:
                        reference = next((r for r in baseline if r['team'] == route['team']
                            and r['id'] == route['id'] and r.get('class_tag', 'all') == 'all'), None)
                    if reference is not None:
                        ends[1] = reference['points'][-1]
                if (len(points) < 2 or points[0][:2] != ends[0][:2]
                        or points[-1][:2] != ends[1][:2]):
                    raise contract.TacticsError('Route endpoints are fixed: %s / %s' % (name, route['id']))
                if route.get('symmetric') and not symmetry_allowed(graph):
                    raise contract.TacticsError('Route symmetry is unavailable on this map: '+name)
