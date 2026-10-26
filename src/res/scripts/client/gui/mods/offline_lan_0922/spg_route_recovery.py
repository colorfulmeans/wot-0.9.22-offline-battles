# -*- coding: utf-8 -*-
"""Artillery sortie recovery; local driving and combat retain their owners."""
import copy
import math
import random

from gui.mods.offline_lan_0922 import bot_tactics, bot_tactics_runtime

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


def select_route(runtime, state, failed):
    """Run navigation checks only at home, then reserve the least occupied road."""
    rows = _catalog(runtime, state['team'])
    if not rows:
        return copy.deepcopy(failed)
    graph = bot_tactics_runtime.graph_view(runtime._navigation_map_name, runtime.baked_graph)
    groups = {}
    for row in rows:
        points = [[p[0], p[1], 0] for p in row['waypoints']]
        key = geometry(points)
        group = groups.setdefault(key, dict(id=row['id'], points=points, ids=set()))
        group['ids'].update((row['id'], row.get('_route_family') or row.get('_editor_source') or row['id']))
    valid = []
    for key, group in groups.items():
        if bot_tactics_runtime.validate_route(graph, dict(team=state['team'], points=group['points'])) is not None:
            continue
        # Check the entry, not the nearest later node: switching must not cut
        # across the map to the middle of a newly selected road.
        entry = [[state['x'], state['z'], 0], group['points'][0]]
        if bot_tactics_runtime.validate_route(graph, dict(team=state['team'], points=entry)) is not None:
            continue
        valid.append((key, group))
    alternatives = [(key, group) for key, group in valid if key != geometry(failed['points'])]
    if not alternatives:
        return copy.deepcopy(failed)
    orders = getattr(runtime, '_server_orders', {})
    director = getattr(getattr(runtime, 'adapter', None), 'director', None)
    agents = getattr(director, 'agents', {})
    occupied = []
    for other in runtime._ordered_states():
        if other['id'] == state['id'] or other['team'] != state['team'] or not other.get('alive', True):
            continue
        attack = other.get('_authored_spg_attack')
        if attack:
            occupied.append((geometry(attack['points']), set(attack.get('road_ids', ()))))
            continue
        order = orders.get(other['id']) or {}
        agent = agents.get(other['id']) or {}
        route = (next((r for r in rows if r['id'] == order.get('route_id')), None)
                 or other.get('route') or agent.get('route') or {})
        ids = set(value for value in (order.get('route_id'), route.get('id'),
                  route.get('_route_family'), route.get('_editor_source')) if value)
        occupied.append((geometry(route.get('waypoints', ())), ids))
    ranked = []
    for key, group in alternatives:
        used = sum(key == shape or bool(group['ids'] & ids) for shape, ids in occupied)
        ranked.append((used, group))
    minimum = min(used for used, group in ranked)
    selected = random.choice([group for used, group in ranked if used == minimum])
    return dict(id=selected['id'], points=copy.deepcopy(selected['points']), borrowed=True,
                road_ids=sorted(selected['ids']))


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
