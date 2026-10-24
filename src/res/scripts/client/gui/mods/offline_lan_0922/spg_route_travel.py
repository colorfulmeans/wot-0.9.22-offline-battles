# -*- coding: utf-8 -*-
"""Authored artillery travel; target choice and fire gates stay with combat."""
import copy
import math

from gui.mods.offline_lan_0922 import bot_tactics, bot_tactics_runtime, route_network


def xy(value):
    if isinstance(value,dict):return float(value['x']),float(value['z'])
    return float(value[0]),float(value[1])


def separation(a,b):return math.hypot(a[0]-b[0],a[1]-b[1])


def parking(settings,state):
    initial=state.get('_spg_initial') or {}
    rows=[p for p in settings.get('positions',()) if p['team']==state['team']]
    exact=next((p for p in rows if p['id']==initial.get('zone')),None)
    if exact is not None:return exact
    if rows and initial.get('point'):
        p=min(rows,key=lambda p:separation(p['point'],xy(initial['point'])))
        if separation(p['point'],xy(initial['point']))<=p['radius']:return p


def _join(runtime,state,points):
    graph=bot_tactics_runtime.graph_view(runtime._navigation_map_name,runtime.baked_graph)
    return route_network.reachable_join(graph,(state['x'],state['y'],state['z']),points)


def _task(runtime,state,kind,points,identity,index=None):
    if not points:return None
    if index is None:index=_join(runtime,state,points)
    if index is None:return None
    return dict(kind=kind,points=copy.deepcopy(points),identity=identity,index=index)


def _return_points(active,zone,pose):
    if active and active['kind']=='sortie_return':
        return active['points'][active['index']:]
    if active and active['kind'] in ('attack','deploy'):
        # The cursor names the pending goal, not the last passed node.
        index=active['index']
        if separation(pose,xy(active['points'][index]))>bot_tactics.ROUTE_ARRIVAL_RADIUS:index-=1
        return list(reversed(active['points'][:max(0,index)+1]))
    if zone and zone.get('travel'):return list(reversed(zone['travel']))
    return []


def apply(runtime,state,order,now):
    if (state.get('profile') or {}).get('class_tag')!='SPG':return order
    settings=bot_tactics.map_settings(runtime._bot_tactics,runtime._navigation_map_name)
    zone=parking(settings,state)
    mode=order.get('combat_mode')
    pose=(float(state['x']),float(state['z']))
    active=state.get('_authored_spg_travel')
    defense=bool(order.get('defense_base_id')) or mode in ('base_defense','team_back_to_base','team_guard')
    if defense:
        if not active or active['kind']!='defense':
            state['_authored_spg_resume']=copy.deepcopy(active)
            state['_authored_spg_return_zone']=copy.deepcopy(state.get('_authored_spg_zone') or zone)
            points=_return_points(active,zone,pose)
            active=_task(runtime,state,'defense',points,('defense',))
            state['_authored_spg_travel']=active
    elif active and active['kind']=='defense':
        # Resume the actual interrupted sortie or return to the actual old zone.
        resume=state.pop('_authored_spg_resume',None)
        zone=state.pop('_authored_spg_return_zone',None) or zone
        if resume:
            active=_task(runtime,state,resume['kind'],resume['points'],resume['identity'])
        elif zone and zone.get('travel'):
            active=_task(runtime,state,'deploy',zone['travel'],('deploy',zone['id']))
        else:active=None
        state['_authored_spg_travel']=active
    if not defense:
        alive=[s for s in runtime._ordered_states() if s.get('alive',True) and s['team']==state['team']]
        alone=alive and all((s.get('profile') or {}).get('class_tag')=='SPG' for s in alive)
        if alone:
            for human in getattr(runtime,'_contact_players',()):
                if not human.get('alive',True) or human.get('team')!=state['team']:continue
                tag=(human.get('profile') or {}).get('class_tag') or human.get('class_tag')
                if not tag:
                    resolve=getattr(runtime,'_player_vehicle_profile',None)
                    try:tag=resolve(human).get('class_tag') if callable(resolve) else None
                    except (ValueError,TypeError,KeyError):tag=None
                if tag!='SPG':alone=False;break
        sorties=sorted(s['id'] for s in alive if s['team']==state['team'])[:3]
        routes=[r for r in settings.get('routes',()) if r.get('purpose')=='spg_attack' and r['team']==state['team']]
        if alone and routes and state['id'] in sorties:
            if order.get('target_id') is not None and order.get('fire_allowed'):return order
            attack=state.get('_authored_spg_attack')
            if attack is None:
                usage=dict((r['id'],sum((s.get('_authored_spg_attack') or {}).get('id')==r['id'] for s in alive)) for r in routes)
                attack=copy.deepcopy(min(routes,key=lambda r:(usage[r['id']],r['id'])))
                state['_authored_spg_attack']=attack
            if not active or active['kind'] not in ('sortie_return','attack'):
                points=_return_points(active,zone,pose)
                active=_task(runtime,state,'sortie_return',points,('sortie_return',attack['id'])) if points else None
                if active is None:
                    active=_task(runtime,state,'attack',attack['points'],('attack',attack['id']),0)
                state['_authored_spg_travel']=active
        elif zone and zone.get('travel') and mode in ('artillery_deploy','artillery_hold','artillery_relocate'):
            identity=('deploy',zone['id'])
            if active is None or active['identity']!=identity:
                previous=state.get('_authored_spg_zone')
                points=zone['travel']
                if previous and previous['id']!=zone['id']:
                    points=previous.get('links',{}).get(zone['id']) or list(reversed(zone.get('links',{}).get(previous['id'],()))) or list(reversed(previous.get('travel',())))+zone['travel']
                active=_task(runtime,state,'deploy',points,identity,0)
                state['_authored_spg_travel']=active
            state['_authored_spg_zone']=copy.deepcopy(zone)
    if not active:return order
    if defense and order.get('throttle_override')==0.:return order
    # Existing local combat keeps ownership; defense alone owns the moving hull.
    if not defense and mode not in ('artillery_deploy','artillery_hold','artillery_relocate','route','advance','base_capture','spg_route_travel'):
        active.setdefault('paused_at',now)
        return order
    if 'paused_at' in active:
        pause=now-active.pop('paused_at')
        if 'since' in active:active['since']+=pause
        join=_join(runtime,state,active['points'])
        if join is not None:active['index']=join
    points=active['points']
    while active['index']<len(points)-1 and separation(pose,xy(points[active['index']]))<=bot_tactics.ROUTE_ARRIVAL_RADIUS:
        active['index']+=1
    destination=xy(points[active['index']])
    if defense:
        episode=active.setdefault('attempt',dict(index=active['index'],since=now,best=separation(pose,destination),failures=0))
        current=separation(pose,destination)
        if episode['index']!=active['index']:
            episode.update(index=active['index'],since=now,best=current,failures=0)
        elif current<episode['best']-.5:episode.update(best=current,since=now)
        elif now-episode['since']>=20. and current>bot_tactics.ROUTE_ARRIVAL_RADIUS:
            episode['failures']+=1
            active['index']=len(points)-1 if episode['failures']>=2 else min(active['index']+1,len(points)-1)
            destination=xy(points[active['index']])
            episode.update(index=active['index'],since=now,best=separation(pose,destination))
    arrived=active['index']==len(points)-1 and separation(pose,destination)<=bot_tactics.ROUTE_ARRIVAL_RADIUS
    if arrived and active['kind']=='sortie_return':
        attack=state['_authored_spg_attack']
        active=_task(runtime,state,'attack',attack['points'],('attack',attack['id']),0)
        state['_authored_spg_travel']=active
        destination=xy(active['points'][0]);arrived=False
    if arrived and active['kind']=='deploy':return order
    if arrived and active['kind']=='defense':return order
    if active['kind']=='attack':
        graph=runtime.baked_graph
        bases=graph.get('objective_bases',())
        radii=graph.get('objective_base_radii',())
        # Graph payload uses the same x/z objective contract as the editor.
        if len(bases)==2 and len(radii)==2:
            arrived=separation(pose,xy(bases[2-state['team']]))<=radii[2-state['team']]
        if arrived:
            return dict(order,move_position=(state['x'],state['y'],state['z']),throttle_override=0.,combat_mode='base_capture')
    result=dict(order,move_position=(destination[0],state['y'],destination[1]),
        route_anchor=(pose[0],state['y'],pose[1]),route_join=True,route_index=active['index'],
        throttle_override=None,combat_mode='base_defense' if defense else 'spg_route_travel')
    result['authored_spg_connection']=active['kind']
    return result
