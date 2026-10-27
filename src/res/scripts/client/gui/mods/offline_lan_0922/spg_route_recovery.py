# -*- coding: utf-8 -*-
"""Artillery sortie recovery; local driving and combat retain their owners."""
import copy
import math
import random

from gui.mods.offline_lan_0922 import bot_tactics, bot_tactics_runtime, route_network

ATTEMPT_SECONDS = 20.


def geometry(points):
    return tuple((float(p[0]), float(p[1])) for p in points)


def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])


def _catalog(runtime, team):
    director = getattr(getattr(runtime, 'adapter', None), 'director', None)
    catalog = (getattr(director, 'map_data', None) or {}).get('routes')
    if catalog is None:
        if not runtime.baked_graph.get('routes'):
            return []
        catalog, unused = bot_tactics_runtime.default_routes(
            runtime._bot_tactics, runtime._navigation_map_name, runtime.baked_graph)
    rows = list(catalog.get(team, catalog.get(str(team), ())))
    settings = bot_tactics.map_settings(runtime._bot_tactics, runtime._navigation_map_name)
    rows.extend(bot_tactics_runtime.route_value(r) for r in settings.get('routes', ())
                if r['team'] == team and not r.get('disabled') and r.get('purpose') != 'spg_attack')
    # A source road with class variants is only effective for the remaining
    # classes. Do not resurrect its old geometry when every class overrides it.
    ordinary = [tag for tag in bot_tactics.CLASSES if tag != 'SPG']
    result = []
    for row in rows:
        if row.get('disabled') or row.get('_route_purpose') == 'spg_attack':
            continue
        overridden = set(r.get('_editor_class') for r in rows
                         if r.get('_editor_source') == row['id'])
        weights = row.get('class_weights') or {}
        if not any(tag not in overridden and tag not in row.get('_editor_disabled_classes', ())
                   and weights.get(tag, 1.) > 0 for tag in ordinary):
            continue
        if len(row.get('waypoints', ())) >= 2:
            result.append(row)
    return result


def _road(runtime, state, row):
    points = [[p[0], p[1], 0] for p in row['waypoints']]
    source = bot_tactics.route_config(runtime._bot_tactics, runtime._navigation_map_name,
                                     row['id'], state['team'], row['waypoints'])
    branch = (source or {}).get('defense')
    if branch:
        junction = route_network.nodes(source).index(branch['junction'])
        # Reverse the home connector, then continue forward after its junction.
        points = [list(p[:2])+[0] for p in reversed(branch['points'])] + points[junction+1:]
    return points


def select_route(runtime, state, failed, prefer_spg=False):
    """At home, reserve an attack lane or a least occupied effective road."""
    rows = _catalog(runtime, state['team'])
    settings = bot_tactics.map_settings(runtime._bot_tactics, runtime._navigation_map_name)
    artillery = [dict(id=r['id'], points=copy.deepcopy(r['points']), artillery=True,
                      road_ids=[r['id']]) for r in settings.get('routes', ())
                 if r['team'] == state['team'] and r.get('purpose') == 'spg_attack' and not r.get('disabled')]
    groups = {}
    for row in rows:
        key = geometry(row['waypoints'])
        group = groups.setdefault(key, dict(id=row['id'], points=_road(runtime,state,row),
                                            road_geometry=key, ids=set()))
        group['ids'].update(value for value in (row['id'], row.get('_route_family'),
                           row.get('_editor_source')) if value)
    candidates = artillery + [dict(id=g['id'], points=g['points'], borrowed=True,
                        road_geometry=g['road_geometry'], road_ids=sorted(g['ids'])) for g in groups.values()]
    orders = getattr(runtime, '_server_orders', {})
    agents = getattr(getattr(getattr(runtime, 'adapter', None), 'director', None), 'agents', {})
    occupied = []
    for other in runtime._ordered_states():
        if other['id'] == state['id'] or other['team'] != state['team'] or not other.get('alive', True):continue
        attack = other.get('_authored_spg_attack')
        if attack:
            occupied.append((tuple(tuple(p) for p in attack.get('road_geometry', geometry(attack['points']))),
                             set(attack.get('road_ids', (attack['id'],)))))
        else:
            order = orders.get(other['id']) or {}
            route = (next((r for r in rows if r['id'] == order.get('route_id')),None)
                     or other.get('route') or (agents.get(other['id']) or {}).get('route') or {})
            occupied.append((geometry(route.get('waypoints', ())),set(v for v in
                (order.get('route_id'),route.get('id'),route.get('_route_family'),route.get('_editor_source')) if v)))
    def usage(r):
        shape=tuple(tuple(p) for p in r.get('road_geometry', geometry(r['points'])))
        return sum(shape == old or bool(set(r.get('road_ids', ())) & ids) for old,ids in occupied)
    # Navigation is checked on acquisition, not on every driving update.
    graph = None
    candidates=[r for r in candidates if not (r.get('artillery') and usage(r)>=3)
                and (not failed or geometry(r['points'])!=geometry(failed['points']))]
    def rank(r):return (0 if prefer_spg and r.get('artillery') else 1,usage(r))
    candidates.sort(key=rank)
    valid = []
    selected_rank=None
    for candidate in candidates:
        # Higher-occupancy roads cannot win once this tier has a valid road.
        # Check ties to retain uniform random selection without proving every
        # road again for every arriving artillery vehicle.
        if selected_rank is not None and rank(candidate)!=selected_rank:break
        if graph is None:
            try:graph=bot_tactics_runtime.graph_view(runtime._navigation_map_name,runtime.baked_graph)
            except (KeyError,ValueError,TypeError):return copy.deepcopy(failed) if failed else None
        if bot_tactics_runtime.validate_route(graph,dict(team=state['team'],points=candidate['points'])) is not None:continue
        base=runtime.baked_graph.get('objective_bases',((state['x'],state['z']),)*2)[state['team']-1]
        entry=[[base[0],base[1],0],candidate['points'][0]]
        if bot_tactics_runtime.validate_route(graph,dict(team=state['team'],points=entry)) is not None:continue
        valid.append(candidate)
        selected_rank=rank(candidate)
    if not valid:return copy.deepcopy(failed) if failed else None
    return copy.deepcopy(random.choice(valid))


def pause(active, now):
    active.setdefault('paused_at', now)


def resume(active, now):
    if 'paused_at' not in active:
        return
    elapsed = now-active.pop('paused_at')
    attempt = active.get('attack_attempt')
    if attempt:
        attempt['since'] += elapsed


def advance(runtime, state, active, now):
    """C -> D -> B -> A -> home -> another entry; no terminal retry limit."""
    pose = (state['x'], state['z'])
    radius = bot_tactics.ROUTE_ARRIVAL_RADIUS
    points = active['points']
    phase = active.get('recovery_phase', 'forward')
    index = active['index']
    base = runtime.baked_graph['objective_bases'][state['team']-1]
    home_radius = runtime.baked_graph.get('objective_base_radii', (30., 30.))[state['team']-1]
    destination = base if phase == 'home' else points[index][:2]
    reached = distance(pose, destination) <= (home_radius if phase == 'home' else radius)
    if reached:
        active.pop('attack_attempt', None)
        if phase == 'home':
            attack = select_route(runtime, state, state['_authored_spg_attack'])
            # Publish the claim before another artillery vehicle chooses.
            state['_authored_spg_attack'] = attack
            active.update(points=copy.deepcopy(attack['points']), identity=('attack', attack['id']),
                          index=0, recovery_phase='transfer')
            active.pop('failed_index', None)
        elif phase in ('return', 'return_skip'):
            if index == 0:
                active['recovery_phase'] = 'home'
            else:
                active.update(index=index-1, recovery_phase='return')
        else:
            active.pop('recovery_phase', None)
            active.pop('failed_index', None)
            while active['index'] < len(points)-1 and distance(pose, points[active['index']][:2]) <= radius:
                active['index'] += 1
    phase = active.get('recovery_phase', 'forward')
    destination = base if phase == 'home' else active['points'][active['index']][:2]
    current = distance(pose, destination)
    key = (phase, active['index'])
    attempt = active.get('attack_attempt')
    if not attempt or attempt['key'] != key:
        active['attack_attempt'] = dict(key=key, since=now, best=current)
    elif current < attempt['best']-.5:
        attempt.update(since=now, best=current)
    elif current > (home_radius if phase == 'home' else radius) and now-attempt['since'] >= ATTEMPT_SECONDS:
        index = active['index']
        if phase == 'forward':
            active['failed_index'] = index
            if index < len(active['points'])-1:
                active.update(index=index+1, recovery_phase='skip')
            else:
                active.update(index=max(0, index-1), recovery_phase='return')
        elif phase == 'skip':
            active.update(index=max(0, active['failed_index']-1), recovery_phase='return')
        elif phase == 'return' and index > 0:
            active.update(index=index-1, recovery_phase='return_skip')
        elif phase in ('return', 'return_skip'):
            active.update(index=active.get('failed_index', min(1, len(active['points'])-1)), recovery_phase='forward')
        elif phase == 'transfer':
            active['recovery_phase'] = 'home'
        # Home navigation is automatic and retains local driving recovery.
        # Renew its attempt without ever terminating the sortie.
        active.pop('attack_attempt', None)
    return base if active.get('recovery_phase') == 'home' else active['points'][active['index']][:2]
