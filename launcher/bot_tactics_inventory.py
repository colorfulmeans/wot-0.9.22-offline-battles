"""Read-only effective route inventory, including absent optional connections."""
import copy
import math
from itertools import combinations

DEFENSE_MAPS = ('100_thepit', '63_tundra', '95_lost_city')


def inventory(profile, name, graph, contract):
    entry = contract.map_settings(profile, name)
    rows = []

    def add(kind, item, points, scope='all', mode='', link='', selection=None):
        rows.append(dict(kind=kind, team=item['team'], scope=scope,
            label=item.get('label', item['id']), identity=item['id'],
            points=copy.deepcopy(points), mode=mode, link=link,
            selection=selection, disabled=bool(item.get('disabled')),
            parking=copy.deepcopy(item) if kind=='parking' else None))

    edits = entry.get('default_routes', ())
    for team, sources in graph.get('routes', {}).items():
        for source in sources:
            for scope in contract.CLASSES[:-1]:
                candidates = [r for r in edits if r['team'] == int(team) and
                    r['id'] == source['id'] and r.get('class_tag', 'all') in ('all', scope)]
                shared = next((r for r in candidates if r.get('class_tag', 'all') == 'all'), None)
                item = next((r for r in candidates if r.get('class_tag') == scope), shared)
                item = copy.deepcopy(item) if item else dict(id=source['id'], points=source['waypoints'])
                item['team'] = int(team)
                if shared and shared.get('disabled'):item['disabled'] = True
                add('route', item, item['points'], scope, selection=('builtin', source['id']+'@'+scope))
                if (name in DEFENSE_MAPS or item.get('defense')) and not item.get('disabled'):
                    add('defense', item, (item.get('defense') or {}).get('points'), scope,
                        'defense', selection=('builtin', source['id']+'@'+scope))
    for item in entry.get('routes', ()):
        for scope in item['classes']:
            add('sortie' if item.get('purpose') == 'spg_attack' else 'route', item,
                item['points'], scope, selection=('routes', item['id']+'@'+scope))
            if scope != 'SPG' and (name in DEFENSE_MAPS or item.get('defense')):
                add('defense', item, (item.get('defense') or {}).get('points'), scope,
                    'defense', selection=('routes', item['id']+'@'+scope))
    # Source parking is part of the effective profile even with no saved overrides.
    from bot_tactics_store import default_spg_positions
    defaults=default_spg_positions(name, graph, profile)
    default_ids={p['id'] for p in defaults}
    positions = {p['id']: p for p in defaults}
    positions.update((p['id'], p) for p in entry.get('positions', ()))
    positions = [p for p in positions.values() if p['id'] not in entry.get('deleted_positions', ())]
    for team in (1, 2):
        peers = sorted((p for p in positions if p['team'] == team), key=lambda p:p['id'])
        for item in peers:
            selection=('builtin_positions' if item['id'] in default_ids else 'positions',item['id'])
            add('parking', item, [item['point']], 'SPG', selection=selection)
            add('deployment', item, item.get('travel'), 'SPG', 'travel', selection=selection)
        for first, last in combinations(peers, 2):
            paths=[(owner,target,owner.get('links',{}).get(target['id'])) for owner,target in ((first,last),(last,first))]
            existing=[path for path in paths if path[2]]
            for owner,target,points in existing or paths[:1]:
                selection=('builtin_positions' if owner['id'] in default_ids else 'positions',owner['id'])
                add('relocation', owner, points, 'SPG', 'link', target['id'], selection)
        if not any(r['kind']=='sortie' and r['team']==team for r in rows):
            add('sortie', dict(id='spg_attack',team=team,label='SPG attack'), None, 'SPG')
    parking_by_id={p['id']:p for p in positions}
    base_radii=graph.get('objective_base_radii',(30.,30.))
    for row in rows:
        own=base_radii[row['team']-1];enemy=base_radii[2-row['team']]
        radius=parking_by_id.get(row['identity'],{}).get('radius',0.)
        row['area_radii']=({'sortie':{0:own,-1:enemy},'defense':{-1:own},
            'deployment':{0:own,-1:radius},'parking':{0:radius},
            'relocation':{0:radius,-1:parking_by_id.get(row['link'],{}).get('radius',0.)}}.get(row['kind'],{}))
    return rows


def inspect(profile, name, graph, contract, receipt=None):
    from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
    import bot_tactics_navigation as nav
    grid=TerrainGrid(lambda *args:None,baked_graph=graph)
    cache={};rows=inventory(profile,name,graph,contract)
    for row in rows:
        row['issues']=[];row['proofs']=[]
        points=row['points']
        row['category']='unconfigured' if not points else 'correct'
        if row['disabled']:continue
        if not points:continue
        for i,p in enumerate(points):
            status=nav.point_status(graph,p,contract.MAPS[name]['bounds'])
            # Fixed objective centers and parking centers are area goals, not
            # mandatory wheel-contact coordinates. Keep exact ordinary-node checks.
            radius=row['area_radii'].get(i,row['area_radii'].get(-1,0.) if i==len(points)-1 else 0.)
            area_goal=radius>0.
            if status=='missing_ground' and area_goal:
                cell=grid._nearest_baked_cell(grid.cell_for((p[0],0.,p[1])),3)
                if cell is not None:
                    target=grid.point_for(cell,grid._baked_cell_height(cell))
                    # Match the shipping bounded endpoint snap, not a global search.
                    if (math.hypot(target[0]-p[0],target[2]-p[1])<=radius and
                            nav.point_status(graph,(target[0],target[2]),contract.MAPS[name]['bounds'])=='available'):status='available'
            if status!='available':row['issues'].append(dict(nodes=[i+1],reason=status,points=[p[:2]]))

        def check(a,b,nodes,kind,wait_slot=None):
            key=tuple(a[:2])+tuple(b[:2])
            if key not in cache:cache[key]=nav.connection(grid,graph,a,b)
            proof=dict(cache[key],nodes=nodes,direction=kind)
            if wait_slot is not None:proof['wait_slot']=wait_slot
            row['proofs'].append(proof)
            if not proof['connected']:
                issue=dict(nodes=nodes,reason='waypoints_disconnected',points=[a[:2],b[:2]],direction=kind)
                if wait_slot is not None:issue['wait_slot']=wait_slot
                row['issues'].append(issue)
        for i,(a,b) in enumerate(zip(points,points[1:])):
            check(a,b,[i+1,i+2],'forward')
            check(b,a,[i+2,i+1],'reverse')
        if row['kind']=='route':
            for i,p in enumerate(points):
                for slot,place in enumerate(contract.waiting_positions(p)):
                    status=nav.point_status(graph,place,contract.MAPS[name]['bounds'])
                    if status!='available':row['issues'].append(dict(nodes=[i+1],wait_slot=slot+1,
                        reason='wait_place_unusable',points=[place[:2]]))
                    check(p,place,[i+1],'wait_entry',slot+1)
                    if i+1<len(points):check(place,points[i+1],[i+1,i+2],'wait_exit',slot+1)
        if row['kind']=='parking':
            from gui.mods.offline_lan_0922 import bot_tactics_runtime
            item=row['parking']
            if item:
                findings=bot_tactics_runtime.authoring_check({'maps':{name:{'positions':[item]}}},name,graph,details=True)
                if any(status=='no_generic_parking' for unused,status,issues in findings):
                    row['issues'].append(dict(nodes=[1],reason='no_generic_parking',points=[points[0][:2]]))
        if row['issues']:row['category']='incorrect'
    if receipt:receipt(dict(map=name,inventory=rows))
    return rows
