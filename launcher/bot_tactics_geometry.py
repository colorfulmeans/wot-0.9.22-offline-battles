"""Editor endpoint ownership; never changes a submitted route on save."""
import math
import copy


def symmetry_allowed(graph):
    starts = graph.get('spawn_anchors', ())
    bases = graph.get('objective_bases', ())
    radii = graph.get('objective_base_radii', ())
    return (len(starts) == len(bases) == len(radii) == 2 and all(
        math.hypot(a[0]-b[0], a[1]-b[1]) <= radius
        for a, b, radius in zip(starts, bases, radii)))


def anchors(graph, team):
    goal=graph['spawn_anchors'][2-team] if symmetry_allowed(graph) else graph['objective_bases'][2-team]
    return [[round(float(v),4) for v in graph['spawn_anchors'][team-1]]+[0],
            [round(float(v),4) for v in goal]+[0]]


def in_enemy_base(point, graph, team):
    base=graph['objective_bases'][2-team]
    return math.hypot(point[0]-base[0],point[1]-base[1]) <= graph['objective_base_radii'][2-team]


def display_points(points, graph, team):
    if (not symmetry_allowed(graph) and not in_enemy_base(points[-1],graph,team)
            and same_point(points[-1],graph['spawn_anchors'][2-team])):
        points=copy.deepcopy(points);points[-1]=anchors(graph,team)[-1]
    return points


def migrate_legacy_ends(document):
    """Retire only the old enemy-spawn endpoint outside its capture circle."""
    changed=False
    from gui.mods.offline_lan_0922.bot_editor_maps import MAPS
    for name,entry in document['maps'].items():
        # Use the generated objective metadata; opening a profile must not
        # repeatedly deserialize every full navigation graph.
        graph=MAPS[name]
        for route in entry.get('default_routes',[])+entry.get('routes',[]):
            if route.get('purpose')=='spg_attack':continue
            last=route['points'][-1];team=route['team']
            if (not symmetry_allowed(graph) and not in_enemy_base(last,graph,team)
                    and same_point(last,graph['spawn_anchors'][2-team])):
                route['points'][-1]=anchors(graph,team)[-1]
                changed=True
    return changed


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
                    if reference is not None and in_enemy_base(reference['points'][-1],graph,route['team']):
                        ends[1] = reference['points'][-1]
                allowed_ends=[ends[1],anchors(graph,route['team'])[-1]]
                if route.get('purpose')=='spg_attack':allowed_ends=[ends[1]]
                if kind=='default_routes' and route.get('class_tag','all')!='all':
                    shared=next((r for r in baseline if r['team']==route['team'] and r['id']==route['id']
                                 and r.get('class_tag','all')=='all'),None)
                    # A common reset adopts the common fixed end. Later class
                    # edits keep that end even when their interior diverges.
                    if shared is not None and in_enemy_base(shared['points'][-1],graph,route['team']):allowed_ends.append(shared['points'][-1])
                if (len(points) < 2 or not same_point(points[0],ends[0])
                        or not any(same_point(points[-1],end) for end in allowed_ends)):
                    raise contract.TacticsError('Route endpoints are fixed: %s / %s' % (name, route['id']))
                if route.get('symmetric') and not symmetry_allowed(graph):
                    raise contract.TacticsError('Route symmetry is unavailable on this map: '+name)
