# -*- coding: utf-8 -*-
"""Authored artillery travel; target choice and fire gates stay with combat."""
import copy
import math

from gui.mods.offline_lan_0922 import bot_tactics, bot_tactics_runtime, route_network, spg_route_recovery


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
    # An authored connection still exists when its join query cannot prove a
    # shortcut. Keep its first node and the normal physical/retry machinery;
    # do not silently substitute the unrelated automatic destination.
    if index is None:index=0
    return dict(kind=kind,points=copy.deepcopy(points),identity=identity,index=index)


def _return_points(active,zone,pose):
    if active and active['kind']=='sortie_return':
        return active['points'][active['index']:]
    if active and active['kind'] == 'attack':
        if active.get('recovery_phase') == 'home':return []
        if active.get('recovery_phase') in ('return','return_skip'):
            return list(reversed(active['points'][:active['index']+1]))
        # The cursor names the pending goal, not the last passed node.
        index=active['index']
        if separation(pose,xy(active['points'][index]))>bot_tactics.ROUTE_ARRIVAL_RADIUS:index-=1
        return list(reversed(active['points'][:max(0,index)+1]))
    return []


def apply(runtime,state,order,now):
    if (state.get('profile') or {}).get('class_tag')!='SPG':return order
    settings=bot_tactics.map_settings(runtime._bot_tactics,runtime._navigation_map_name)
    zone=parking(settings,state)
    mode=order.get('combat_mode')
    pose=(float(state['x']),float(state['z']))
    active=state.get('_authored_spg_travel')
    empty=bool(order.get('empty_ammo'))
    if active and active.get('kind') in ('deploy','relocate','link','travel'):
        state.pop('_authored_spg_travel',None);active=None
    defense=not empty and (bool(order.get('defense_base_id')) or mode in ('base_defense','team_back_to_base','team_guard'))
    if defense:
        if not state.get('_authored_spg_defending'):
            state['_authored_spg_defending']=True
            state['_authored_spg_resume']=copy.deepcopy(active)
            if state['_authored_spg_resume']:
                spg_route_recovery.pause(state['_authored_spg_resume'],now)
            state['_authored_spg_return_zone']=copy.deepcopy(state.get('_authored_spg_zone') or zone)
            used=state.get('_authored_spg_zone') or zone
            initial=state.get('_spg_initial') or {}
            prior=initial if used and initial.get('zone')==used['id'] else state.get('_authored_spg_used_initial') or initial
            state['_authored_spg_return_initial']=copy.deepcopy(prior)
            points=_return_points(active,zone,pose)
            active=_task(runtime,state,'defense',points,('defense',))
            state['_authored_spg_travel']=active
    elif state.pop('_authored_spg_defending',False):
        # Resume the actual interrupted sortie or return to the actual old zone.
        resume=state.pop('_authored_spg_resume',None)
        zone=state.pop('_authored_spg_return_zone',None) or zone
        if resume and resume['kind'] in ('attack','sortie_return'):
            if resume.get('recovery_phase'):
                active=resume
                spg_route_recovery.resume(active,now)
            else:active=_task(runtime,state,resume['kind'],resume['points'],resume['identity'])
        else:active=None
        original=state.pop('_authored_spg_return_initial',None)
        if original is not None:
            state['_spg_initial']=original;state.pop('_spg_arrived_identity',None)
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
        if (alone or empty) and not routes:
            # No authored sortie exists. Do not let a cached deployment
            # override the existing automatic capture/combat destination.
            state.pop('_authored_spg_travel', None)
            state.pop('_authored_spg_attack', None)
            if empty and not state.get('_empty_spg_home_reached'):
                base=runtime.baked_graph['objective_bases'][state['team']-1]
                radius=runtime.baked_graph.get('objective_base_radii',(30.,30.))[state['team']-1]
                if separation(pose,base)<=radius:state['_empty_spg_home_reached']=True
                else:
                    return dict(order,move_position=(base[0],state['y'],base[1]),
                        face_position=(base[0],state['y'],base[1]),throttle_override=None,
                        combat_mode='spg_route_travel',route_join=True,
                        route_anchor=(pose[0],state['y'],pose[1]),authored_spg_connection='sortie_return')
            return order
        if routes and (empty or alone and state['id'] in sorties):
            if not empty and order.get('target_id') is not None and order.get('fire_allowed'):
                if active:spg_route_recovery.pause(active,now)
                return order
            attack=state.get('_authored_spg_attack')
            if attack is None:
                usage=dict((r['id'],sum((s.get('_authored_spg_attack') or {}).get('id')==r['id'] for s in alive)) for r in routes)
                attack=copy.deepcopy(min(routes,key=lambda r:(usage[r['id']],r['id'])))
                state['_authored_spg_attack']=attack
            if not active or active['kind'] not in ('sortie_return','attack'):
                base=runtime.baked_graph['objective_bases'][state['team']-1]
                # Automatic navigation to the own base must precede any route join.
                active=_task(runtime,state,'sortie_return',[list(base)+[0]],('sortie_return',attack['id']),0)
                state['_authored_spg_travel']=active
        elif mode in ('artillery_deploy','artillery_hold','artillery_relocate'):
            state.pop('_authored_spg_travel',None)
            if zone and separation(pose,zone['point'])<=zone['radius']:
                if state.get('_authored_spg_zone')!=zone:state['_authored_spg_zone']=copy.deepcopy(zone)
                if state.get('_authored_spg_used_initial')!=state.get('_spg_initial'):
                    state['_authored_spg_used_initial']=copy.deepcopy(state.get('_spg_initial'))
            return order
    if not active:return order
    if not defense and active['kind']=='defense':return order
    if defense and order.get('throttle_override')==0.:return order
    # Existing local combat keeps ownership; defense alone owns the moving hull.
    if not empty and not defense and mode not in ('artillery_deploy','artillery_hold','artillery_relocate','route','advance','base_capture','spg_route_travel'):
        spg_route_recovery.pause(active,now)
        return order
    if 'paused_at' in active:
        pause=now-active['paused_at']
        spg_route_recovery.resume(active,now)
        if 'since' in active:active['since']+=pause
        if active['kind'] not in ('sortie_return','attack'):
            join=_join(runtime,state,active['points'])
            if join is not None:active['index']=join
    points=active['points']
    if active['kind']=='attack':
        bases=runtime.baked_graph.get('objective_bases',())
        radii=runtime.baked_graph.get('objective_base_radii',())
        if len(bases)==len(radii)==2 and separation(pose,xy(bases[2-state['team']]))<=radii[2-state['team']]:
            active.update(index=len(active['points'])-1)
            for key in ('recovery_phase','failed_index','attack_attempt'):active.pop(key,None)
            return dict(order,move_position=(state['x'],state['y'],state['z']),throttle_override=0.,combat_mode='base_capture')
        destination=spg_route_recovery.advance(runtime,state,active,now)
        points=active['points']
    else:
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
    if active['kind']=='sortie_return':
        base=runtime.baked_graph['objective_bases'][state['team']-1]
        radii=runtime.baked_graph.get('objective_base_radii',(30.,30.))
        arrived=separation(pose,base)<=radii[state['team']-1]
    if arrived and active['kind']=='sortie_return':
        attack=state['_authored_spg_attack']
        active=_task(runtime,state,'attack',attack['points'],('attack',attack['id']),min(1,len(attack['points'])-1))
        state['_authored_spg_travel']=active
        destination=xy(active['points'][active['index']]);arrived=False
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
    if empty:result['face_position']=result['move_position']
    if active['kind']=='attack':
        result['route_id']=active['identity'][1]
        result['authored_spg_recovery']=dict(phase=active.get('recovery_phase','forward'),
            route_id=active['identity'][1],index=active['index'],failed_index=active.get('failed_index'))
    return result
