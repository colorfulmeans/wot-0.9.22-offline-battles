# -*- coding: utf-8 -*-
"""Authored travel topology shared by the editor and both runtime owners."""
import copy
import uuid


def nodes(route):
    return route.get('node_ids') or ['node_%d' % i for i in range(len(route['points']))]


def ensure_nodes(route):
    if 'node_ids' not in route:
        route['node_ids'] = list(nodes(route))
    return route['node_ids']


def insert_node(route, index, point):
    ids = ensure_nodes(route)
    route['points'].insert(index, point)
    ids.insert(index, 'n_' + uuid.uuid4().hex[:16])


def delete_node(route, index):
    ids = ensure_nodes(route)
    identity = ids.pop(index)
    del route['points'][index]
    if (route.get('defense') or {}).get('junction') == identity:
        route.pop('defense', None)


def sync_junction(route):
    branch = route.get('defense')
    if branch is not None:
        index = nodes(route).index(branch['junction'])
        branch['points'][0] = route['points'][index][:2] + [0]


def replace_points(route, points):
    old = route.get('points', [])
    old_ids = list(nodes(route)) if old else []
    if len(old) == len(points):
        ids = old_ids
    else:
        lookup = dict((tuple(p[:2]), identity) for p, identity in zip(old, old_ids))
        ids = [lookup.get(tuple(p[:2]), 'n_'+uuid.uuid4().hex[:16]) for p in points]
    route['points'] = points
    route['node_ids'] = ids
    if route.get('defense'):
        if route['defense']['junction'] not in ids:route.pop('defense')
        else:sync_junction(route)


def copy_fields(raw, result, contract, bounds):
    """Validate stable references without guessing another nearby node."""
    if 'family' in raw:result['family'] = contract._id(raw['family'])
    if 'tier' in raw:
        if raw['tier'] not in ('main', 'reserve'):
            raise contract.TacticsError('Unknown route tier')
        result['tier'] = raw['tier']
    if 'node_ids' in raw:
        ids = raw['node_ids']
        if (not isinstance(ids, list) or len(ids) != len(result['points']) or
                any(not isinstance(value,contract.TEXT) for value in ids) or len(set(ids)) != len(ids)):
            raise contract.TacticsError('Route node identities must be unique and match geometry')
        result['node_ids'] = [contract._id(value) for value in ids]
    if 'purpose' in raw:
        if raw['purpose'] != 'spg_attack':
            raise contract.TacticsError('Unknown route purpose')
        if result.get('classes')!=['SPG']:
            raise contract.TacticsError('SPG attack routes require only artillery')
        result['purpose'] = raw['purpose']
    if 'defense' in raw:
        branch = raw['defense']
        contract._keys(branch, ('junction', 'points'), ('junction', 'points'))
        identity = contract._id(branch['junction'])
        ids = nodes(result)
        if identity not in ids[1:-1]:
            raise contract.TacticsError('Defense connection requires an intermediate route node')
        index = ids.index(identity)
        if result['points'][index][2] or contract.waiting_positions(result['points'][index]):
            raise contract.TacticsError('A waiting node cannot own a defense connection')
        points = travel_points(branch['points'], contract, bounds)
        if points[0][:2] != result['points'][index][:2]:
            raise contract.TacticsError('Defense connection is detached from its route node')
        result['defense'] = dict(junction=identity, points=points)


def travel_points(raw, contract, bounds):
    if not isinstance(raw, list) or not 2 <= len(raw) <= 16:
        raise contract.TacticsError('A connection requires 2..16 points')
    result = []
    for value in raw:
        if not isinstance(value, (list, tuple)) or len(value) != 3 or value[2] != 0:
            raise contract.TacticsError('Connections cannot contain waiting places')
        point = contract.point(value[:2], bounds) + [0]
        if result and point[:2] == result[-1][:2] and len(raw) != 2:
            raise contract.TacticsError('Adjacent connection points must differ')
        result.append(point)
    return result


def position_fields(raw, result, contract, bounds):
    if 'travel' in raw:
        points = travel_points(raw['travel'], contract, bounds)
        if points[-1][:2] != result['point']:
            raise contract.TacticsError('SPG connection must end at its parking point')
        result['travel'] = points
    if 'links' in raw:
        if not isinstance(raw['links'], dict) or len(raw['links']) > 48:
            raise contract.TacticsError('Invalid SPG connections')
        result['links'] = dict((contract._id(key), travel_points(value, contract, bounds))
                               for key, value in raw['links'].items())
        if any(points[0][:2] != result['point'] for points in result['links'].values()):
            raise contract.TacticsError('SPG link must start at its parking point')


def migrate_default_rows(rows):
    """Retired class deletions become reserve; whole-route exclusions survive."""
    disabled=set((row['team'],row['id']) for row in rows if row.get('disabled') and row.get('class_tag','all')=='all')
    for row in rows:
        if (row['team'],row['id']) not in disabled and row.get('disabled') and row.get('class_tag', 'all') != 'all':
            shared=next((r for r in rows if r['team']==row['team'] and r['id']==row['id'] and r.get('class_tag','all')=='all'),None)
            if shared is not None:
                row['points']=[p[:2]+[0] for p in shared['points']]
                row.pop('node_ids',None);row.pop('defense',None)
            row.pop('disabled')
            row['tier'] = 'reserve'
    return rows


def clone_route(route):
    result = copy.deepcopy(route)
    old = list(nodes(result))
    result['node_ids'] = ['n_' + uuid.uuid4().hex[:16] for unused in old]
    if result.get('defense'):
        result['defense']['junction'] = result['node_ids'][old.index(result['defense']['junction'])]
    return result


def reachable_join(graph, pose, points):
    """Choose an authored node by directed 3D graph cost on task handoff."""
    import heapq
    import math
    start=graph.closest(pose)
    if start is None:return None
    goals={}
    for index,p in enumerate(points):
        value=(p['x'],p.get('y',0),p['z']) if isinstance(p,dict) else (p[0],0,p[1])
        cell=graph.closest(value)
        if cell is not None:goals.setdefault(cell,[]).append(index)
    if not goals:return None
    locations=[graph.point(cell) for cell in goals]
    def heuristic(cell):
        p=graph.point(cell)
        return min(math.hypot(p[0]-g[0],p[2]-g[2]) for g in locations)
    todo=[(heuristic(start),0.,start)];costs={start:0.}
    while todo:
        unused,cost,cell=heapq.heappop(todo)
        if cost!=costs[cell]:continue
        if cell in goals:return max(goals[cell])
        row,col=divmod(cell,graph.width)
        a=graph.point(cell)
        for bit,(dx,dz) in enumerate(graph.directions):
            if not int(graph.links[cell]) & (1<<bit):continue
            x,z=col+dx,row+dz
            if not 0<=x<graph.width or not 0<=z<graph.height:continue
            nxt=z*graph.width+x
            if not graph.usable(nxt):continue
            b=graph.point(nxt)
            value=cost+math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))
            if value<costs.get(nxt,float('inf')):
                costs[nxt]=value;heapq.heappush(todo,(value+heuristic(nxt),value,nxt))
