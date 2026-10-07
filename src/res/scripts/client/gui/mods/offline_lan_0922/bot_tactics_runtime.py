# -*- coding: utf-8 -*-
from __future__ import division
"""One-time plan construction from launcher-authored static intent.

Never reads unobserved enemy locations or alters native collision/shot rules.
All geometric checks here are baked navigation checks, not native mesh/arc proof.
"""
import copy
import heapq
import math
import random

from gui.mods.offline_lan_0922 import bot_tactics as config
from gui.mods.offline_lan_0922 import spg_positions
from gui.mods.offline_lan_0922 import initial_allocation


def graph_view(name, graph):
    if not isinstance(graph, dict) or graph.get('map') != name:
        raise config.TacticsError('Missing matching navigation graph')
    # The engine already clips its copy to the exact arena rectangle. Authoring
    # may open the original bake; _Graph.usable applies these same bounds.
    view = dict(graph)
    view['bounds'] = config.MAPS[name]['bounds']
    return spg_positions._Graph(view, config.MAPS[name]['bounds'])


def _route_reachable(grid, position, target):
    """Prove only the requested directed connection, without a full flood.

    Route admission needs membership, not shortest distances to every map
    cell. Prefer cells near the destination, but exhaust the legal graph if
    necessary. Never add a missing link or jump to a nearby free square.
    """
    start = grid.closest(position)
    if start is None or target is None:
        return False
    cache = getattr(grid, '_route_reachability', None)
    if cache is None:
        cache = grid._route_reachability = {}
        grid._route_usable = {}
    key = (start, target)
    if key in cache:
        return cache[key]
    target_row, target_col = divmod(target, grid.width)
    visited = set([start])
    todo = [(0, start)]
    while todo:
        unused_priority, index = heapq.heappop(todo)
        if index == target:
            cache[key] = True
            return True
        row, col = divmod(index, grid.width)
        for bit, (dx, dz) in enumerate(grid.directions):
            if not int(grid.links[index]) & (1 << bit):
                continue
            nx, nz = col + dx, row + dz
            if not (0 <= nx < grid.width and 0 <= nz < grid.height):
                continue
            following = nz * grid.width + nx
            if following in visited:
                continue
            usable = grid._route_usable.get(following)
            if usable is None:
                usable = grid.usable(following)
                grid._route_usable[following] = usable
            if not usable:
                continue
            visited.add(following)
            heapq.heappush(todo, ((nx-target_col)**2 + (nz-target_row)**2,
                                  following))
    cache[key] = False
    return False


def validate_route(grid, route):
    previous = None
    for point in route['points']:
        target = grid.closest((point[0], 0, point[1]))
        if target is None:
            return 'waypoint_unusable'
        if previous is not None and not _route_reachable(grid, previous, target):
            return 'waypoints_disconnected'
        for place in config.waiting_positions(point):
            parked = grid.closest((place[0], 0, place[1]))
            if parked is None:return 'wait_place_unusable'
            if not _route_reachable(grid, grid.point(target), parked):return 'wait_place_disconnected'
        previous = grid.point(target)
    return None


def route_value(route):
    return {'id': 'user_' + route['id'], 'capacity': min(3, route['capacity']), 'risk': 0.5,
            'role_weights': {}, 'class_weights': dict((c, 1.0 if c in route['classes'] else 0.0) for c in config.CLASSES),
            # Wait conditions stay in the canonical tactics document on the
            # server. The manifest keeps its existing three-field geometry.
            'waypoints': tuple(tuple(p[:3]) for p in route['points'])}


def default_routes(profile, name, graph):
    """Apply editor geometry before the director assigns or restores routes.

    Keep source graphs immutable and retain identities and allocation metadata.
    Unusable edits fall back independently, just like authored custom routes.
    """
    edits = config.map_settings(profile, name).get('default_routes', ())
    result = copy.deepcopy(graph.get('routes'))
    spawns, bases, radii = (graph.get(key) or () for key in
                            ('spawn_anchors', 'objective_bases', 'objective_base_radii'))
    symmetric = (len(spawns) == len(bases) == len(radii) == 2 and all(
        math.hypot(a[0]-b[0], a[1]-b[1]) <= radius
        for a, b, radius in zip(spawns, bases, radii)))
    for team in (1, 2):
        for route in result.get(str(team), ()):
            route['_allocation_symmetric'] = symmetric
    if not edits:
        return result, {}
    grid = graph_view(name, graph)
    outcomes = {}
    for edit in edits:
        if edit.get('class_tag') == 'SPG':continue
        key = '%s:%s' % (edit['team'], config.default_route_id(edit))
        source = next((r for r in result.get(str(edit['team']), ())
                       if r['id'] == edit['id']), None)
        if edit.get('disabled'):
            outcomes[key]='route_deleted'
            continue
        error = validate_route(grid, edit) if source is not None else 'unknown_default_route'
        outcomes[key] = error or 'baked_route_connected'
        if error is None:
            if edit.get('class_tag', 'all') == 'all':
                source['waypoints'] = [list(p[:3]) for p in edit['points']]
                source['_allocation_symmetric'] = bool(edit.get('symmetric', False))
            else:
                if 'priority' in edit:
                    source.setdefault('class_priorities', {})[edit['class_tag']]=edit['priority']
                variant = copy.deepcopy(source)
                variant.update(id=config.default_route_id(edit),
                               _editor_source=source['id'],
                               _editor_class=edit['class_tag'],
                               _allocation_symmetric=bool(edit.get('symmetric', False)),
                               waypoints=[list(p[:3]) for p in edit['points']],
                               class_weights=dict((tag, 1.0 if tag == edit['class_tag'] else 0.0)
                                                  for tag in config.CLASSES))
                result[str(edit['team'])].append(variant)
    if any(edit.get('disabled') and edit.get('class_tag','all')=='all' for edit in edits):
        result['_editor_allow_empty']=True
    for edit in edits:
        if not edit.get('disabled'):continue
        team_routes=result.get(str(edit['team']),[])
        scope=edit.get('class_tag','all')
        if scope=='all':
            result[str(edit['team'])]=[r for r in team_routes
                if r['id']!=edit['id'] and r.get('_editor_source')!=edit['id']]
        else:
            result[str(edit['team'])]=[r for r in team_routes
                if not (r.get('_editor_source')==edit['id'] and r.get('_editor_class')==scope)]
            for route in result[str(edit['team'])]:
                if route['id']==edit['id']:
                    route.setdefault('_editor_disabled_classes',[]).append(scope)
                    route.setdefault('class_weights',{})[scope]=0.0
    return result, outcomes


def assign_initial_routes(profile, name, graph, states, catalog, seed):
    """Allocate lanes with independent per-team, per-class capacity.

    Shared geometry is an editing template; each class owns its occupancy.
    Priorities are local to the vehicle class. Empty/full catalogs explicitly produce automatic routing.
    Restored manifests bypass this fresh-round allocator entirely.
    """
    settings = config.map_settings(profile, name)
    authored = settings.get('routes', ())
    deleted_positions = set(settings.get('deleted_positions', ()))
    grid = graph_view(name, graph) if authored else None
    errors = dict((r['id'], validate_route(grid, r)) for r in authored)
    usage, plans, outcomes = {}, {}, {}
    by_id = dict((r['id'], r) for r in authored)

    def candidates(state):
        tag = (state.get('profile') or {}).get('class_tag')
        if tag not in config.CLASSES:
            return []
        rows = catalog.get(state['team'], catalog.get(str(state['team']), ())) or ()
        variants = dict((r['_editor_source'], r) for r in rows
                        if r.get('_editor_source') and r.get('_editor_class') == tag)
        choices = []
        custom = [r for r in authored if tag != 'SPG' and config.matches(r, state)]
        fixed = any(r['policy'] == 'fixed' for r in custom)
        for base in rows:
            if base.get('_editor_source') or fixed:
                continue
            if tag == 'SPG' and 'spg_%d_%s' % (state['team'], base['id']) in deleted_positions:
                continue
            route = variants.get(base['id'], base)
            weights = route.get('class_weights') or {}
            if tag in base.get('_editor_disabled_classes', ()):
                continue
            # A class deletion writes a sparse zero mask. Missing entries mean
            # unchanged eligibility, not a prohibition on every other class.
            if tag in weights and weights[tag] <= 0:
                continue
            key = (state['team'], ('spg:' if tag == 'SPG' else '') + base['id'], tag)
            if usage.get(key, 0) >= 3:
                continue
            priority = (route.get('class_priorities') or {}).get(tag, config.DEFAULT_ROUTE_PRIORITY)
            choices.append((priority, 'default:' + base['id'],
                            bool(route.get('_allocation_symmetric')), (route, key, 'random_default')))
        for route in custom:
            key = (state['team'], 'user_' + route['id'], tag)
            if errors[route['id']] or usage.get(key, 0) >= min(3, route['capacity']):
                continue
            if fixed and route['policy'] != 'fixed':
                continue
            p = route['points'][0]
            if not _route_reachable(grid, (state['x'], state['y'], state['z']),
                                    grid.closest((p[0], 0, p[1]))):
                continue
            peer = by_id.get(route.get('mirror_id'))
            paired = bool(route.get('symmetric') and peer and peer.get('symmetric') and
                          peer.get('mirror_id') == route['id'] and peer['team'] != route['team'])
            family = min(route['id'], peer['id']) if paired else route['id']
            priority = route.get('class_priorities', {}).get(tag, config.DEFAULT_ROUTE_PRIORITY)
            choices.append((priority, 'custom:' + family, paired,
                            (route_value(route), key, 'random_' + route['policy'])))
        return choices

    def reserve(state, selected):
        if selected is None:
            plans[state['id']] = None
            outcomes[state['id']] = 'full_or_unusable_routes_auto'
            return
        route, key, status = selected[3]
        plans[state['id']] = route
        usage[key] = usage.get(key, 0) + 1
        outcomes[state['id']] = status

    initial_allocation.allocate(states, candidates, reserve, seed, name + ':routes')
    return plans, outcomes, usage


def assign_routes(profile, name, graph, states, round_id):
    routes = config.map_settings(profile, name).get('routes', ())
    if not routes:
        return {}, {}
    grid = graph_view(name, graph)
    errors = dict((r['id'], validate_route(grid, r)) for r in routes)
    result, outcomes, usage = {}, {}, {}
    for state in sorted(states, key=lambda s: (s['team'], s.get('slot', 0), s['id'])):
        if (state.get('profile') or {}).get('class_tag') == 'SPG':continue
        applicable = [r for r in routes if config.matches(r, state)]
        if not applicable:
            continue
        available = []
        tag=(state.get('profile') or {}).get('class_tag')
        current_route = state.get('route') or {}
        default_priority = current_route.get('class_priorities', {}).get(
            tag, config.DEFAULT_ROUTE_PRIORITY) if current_route else 0
        for route in applicable:
            priority=route.get('class_priorities', {}).get(tag, config.DEFAULT_ROUTE_PRIORITY)
            if priority < default_priority and route['policy'] != 'fixed':continue
            if errors[route['id']] or usage.get((state['team'], route['id'], tag), 0) >= min(3, route['capacity']):
                continue
            p = route['points'][0]
            target = grid.closest((p[0], 0, p[1]))
            if not _route_reachable(grid,
                    (state['x'], state['y'], state['z']), target):
                continue
            # A deterministic weighted draw without global random-state changes.
            seed = '%s:%s:%s:%s' % (config.digest(profile), round_id, state['id'], route['id'])
            rank = -math.log(max(1e-12, random.Random(seed).random())) / route['weight']
            available.append((-priority, rank, route['id'], route))
        if not available:
            outcomes[state['id']] = 'no_usable_user_route'
            continue
        route = min(available, key=lambda value: value[:3])[3]
        result[state['id']] = route_value(route)
        key = (state['team'], route['id'], tag)
        usage[key] = usage.get(key, 0) + 1
        outcomes[state['id']] = route['policy']
    return result, outcomes


def _manual_candidates(grid, zone, clearance):
    x, z = zone['point']; radius = zone['radius'] - 2.0
    ox, oz = grid.origin; cell = grid.cell
    lo_x = max(0, int(math.ceil((x-radius-ox)/cell)))
    hi_x = min(grid.width-1, int(math.floor((x+radius-ox)/cell)))
    lo_z = max(0, int(math.ceil((z-radius-oz)/cell)))
    hi_z = min(grid.height-1, int(math.floor((z+radius-oz)/cell)))
    candidates = []
    for row in range(lo_z, hi_z+1):
        for col in range(lo_x, hi_x+1):
            index = row*grid.width+col
            if not grid.usable(index):
                continue
            p = grid.point(index)
            distance = math.hypot(p[0]-x, p[2]-z)
            if distance <= radius and grid.parking_clear(index, clearance):
                candidates.append((distance, index, p))
    return sorted(candidates)


def assign_manual_positions(profile, name, graph, states, mode='regular',
                            actor_ids=None, excluded=(), occupied=(), preferred_zone=None,
                            allocation_seed=None, paired_routes=None):
    settings = config.map_settings(profile, name)
    deleted = set(settings.get('deleted_positions', ()))
    zones = [z for z in settings.get('positions', ()) if z['id'] not in deleted] if mode == 'regular' else ()
    if not zones:
        return {}, {}
    grid = graph_view(name, graph)
    plans, outcomes, reservations, cache = {}, {}, {1: [], 2: []}, {}
    identity = config.digest(profile)
    paired_families = set()
    if paired_routes is not None:
        for team in (1, 2):
            rows = paired_routes.get(team, paired_routes.get(str(team), ())) or ()
            for route in rows:
                family = route['id']
                if route.get('_editor_source') or not route.get('_allocation_symmetric'):
                    continue
                peer_rows = paired_routes.get(3-team, paired_routes.get(str(3-team), ())) or ()
                if (any(r['id'] == family and r.get('_allocation_symmetric') for r in peer_rows) and
                        all(any(z['id'] == 'spg_%d_%s' % (side, family) and z['team'] == side
                                for z in zones) for side in (1, 2))):
                    paired_families.add(family)
    ordinals = {}
    for unused_tag, ordinal, pair in initial_allocation.ordered_pairs(states):
        for actor in pair:
            if actor is not None:ordinals[actor['id']] = ordinal
    for state in sorted(states, key=lambda s: (s['team'], s.get('slot', 0), s['id'])):
        if actor_ids is not None and state['id'] not in actor_ids:
            continue
        if (state.get('profile') or {}).get('class_tag') != 'SPG':
            continue
        choices = [z for z in zones if z['team'] == state['team']]
        if not choices:
            continue
        shape = state['collision_shape']
        clearance = math.hypot(float(shape[0]), float(shape[1])) + 2.0
        distances = grid.distances((state['x'], state['y'], state['z']))
        candidates = []
        for zone in choices:
            key = (zone['id'], clearance)
            if key not in cache:
                cache[key] = _manual_candidates(grid, zone, clearance)
            for centre_distance, index, p in cache[key]:
                if not spg_positions.parking_point_available(p, clearance, state['team'], excluded, occupied):
                    continue
                if index not in distances:
                    continue
                if any(math.hypot(p[0]-old[0][0], p[2]-old[0][2]) < clearance+old[1]+3
                       for old in reservations[state['team']]):
                    continue
                candidates.append((0 if preferred_zone is None or zone['id'] == preferred_zone else 1,
                    -zone['priority'], centre_distance, distances[index], zone['id'], p, zone))
        if not candidates:
            outcomes[state['id']] = 'manual_no_reachable_parking_space'
            continue
        if allocation_seed is not None:
            # Zone tickets are uniform, not proportional to the number of
            # graph cells. Retain safe closest placement inside the drawn zone.
            tier = min(c[0] for c in candidates)
            by_zone = {}
            for candidate in sorted(candidates):
                if candidate[0] == tier:
                    by_zone.setdefault(candidate[4], candidate)
            tickets = []
            for candidate in by_zone.values():
                family = candidate[4][len('spg_%d_' % state['team']):]
                paired = family in paired_families and candidate[4].startswith('spg_%d_' % state['team'])
                tickets.append((-candidate[1], family if paired else candidate[4], paired, candidate))
            chosen = initial_allocation.choose(allocation_seed, name + ':manual_spg', 'SPG',
                ordinals[state['id']], tickets, 0 if all(t[2] for t in tickets) else state['team'])
            selected = chosen[3]
        else:
            selected = min(candidates)
        unused_preferred, unused_a, unused_b, unused_c, unused_id, p, zone = selected
        angle = math.radians(zone['heading']); bounds = config.MAPS[name]['bounds']
        face = (max(bounds[0], min(bounds[2], p[0]+math.sin(angle)*100)), p[1],
                max(bounds[1], min(bounds[3], p[2]+math.cos(angle)*100)))
        plan = dict(schema=1, catalog=identity, map=name, mode='regular',
                    side='team%d' % state['team'], zone=zone['id'], cell='manual',
                    source='launcher_manual_v1', vehicle=state['vehicle'],
                    point=dict(zip(('x','y','z'),p)), face=dict(zip(('x','y','z'),face)),
                    radius=2.0, clearance=clearance,
                    geometry='baked_checked', fire_validation='runtime_required')
        if config.canonical_manual_plan(plan, profile, name, state['vehicle'], state['team']) is None:
            raise config.TacticsError('Generated manual plan failed its own contract')
        plans[state['id']] = plan
        outcomes[state['id']] = 'manual_selected'
        reservations[state['team']].append((p, clearance))
    return plans, outcomes


def route_issues(grid, route):
    """Report every unusable node and every disconnected adjacent pair."""
    issues, previous = [], None
    for index, point in enumerate(route['points']):
        target = grid.closest((point[0], 0, point[1]))
        if target is None:
            x, z = point[:2]
            reason = 'outside_bounds'
            if grid.bounds[0] <= x <= grid.bounds[2] and grid.bounds[1] <= z <= grid.bounds[3]:
                col = int(round((x - grid.origin[0]) / grid.cell))
                row = int(round((z - grid.origin[1]) / grid.cell))
                if 0 <= col < grid.width and 0 <= row < grid.height:
                    cell = row * grid.width + col
                    reason = 'missing_ground' if grid.heights[cell] is None else 'navigation_hazard'
            issues.append(dict(status='waypoint_unusable', nodes=[index + 1],
                               points=[list(point[:2])], reason=reason))
        elif previous is not None and not _route_reachable(grid, previous, target):
            issues.append(dict(status='waypoints_disconnected', nodes=[index, index + 1],
                               points=[list(route['points'][index-1][:2]), list(point[:2])]))
        for slot, place in enumerate(config.waiting_positions(point)):
            parked = grid.closest((place[0], 0, place[1]))
            status = ('wait_place_unusable' if parked is None else
                      'wait_place_disconnected' if target is not None and
                      not _route_reachable(grid, grid.point(target), parked) else None)
            if status:
                issues.append(dict(status=status, nodes=[index + 1],
                                   points=[list(place[:2])], wait_slot=slot + 1))
            if parked is not None and index + 1 < len(route['points']):
                following = route['points'][index + 1]
                exit_target = grid.closest((following[0], 0, following[1]))
                if exit_target is not None and not _route_reachable(grid, grid.point(parked), exit_target):
                    issues.append(dict(status='wait_place_exit_disconnected',
                        nodes=[index + 1, index + 2],
                        points=[list(place[:2]),list(following[:2])],wait_slot=slot + 1))
        previous = grid.point(target) if target is not None else None
    return issues


def authoring_check(profile, name, graph, details=False):
    """Cheap UI evidence only; actual vehicle-sized parking is tested on load."""
    grid = graph_view(name, graph)
    messages = []
    for route in config.map_settings(profile, name).get('default_routes', ()):
        if route.get('disabled'):continue
        error = validate_route(grid, route)
        identity = '%s:%s' % (route['team'], config.default_route_id(route))
        issues = route_issues(grid, route) if details else []
        messages.append((identity, error or (issues[0]['status'] if issues else 'baked_route_connected'), issues)
                        if details else (identity, error or 'baked_route_connected'))
    for route in config.map_settings(profile, name).get('routes', ()):
        error = validate_route(grid, route)
        issues = route_issues(grid, route) if details else []
        messages.append((route['id'], error or (issues[0]['status'] if issues else 'baked_route_connected'), issues)
                        if details else (route['id'], error or 'baked_route_connected'))
    for zone in config.map_settings(profile, name).get('positions', ()):
        # Generic radius is explicitly not a claim about a particular vehicle.
        spots = _manual_candidates(grid, zone, 6.0)
        valid = bool(spots)
        status = 'generic_parking_found' if valid else 'no_generic_parking'
        issues = []
        messages.append((zone['id'], status, issues) if details else (zone['id'], status))
    return messages
