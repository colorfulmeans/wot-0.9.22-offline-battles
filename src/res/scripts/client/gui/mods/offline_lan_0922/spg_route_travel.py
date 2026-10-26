# -*- coding: utf-8 -*-
"""Authored artillery travel; target choice and fire gates stay with combat."""
import copy
import math

from gui.mods.offline_lan_0922 import bot_tactics, bot_tactics_runtime, route_network, spg_route_recovery, spg_modes, empty_ammo


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
    if order.get('empty_ammo'):
        empty_ammo.handoff(runtime, state, order)
        if state.get('_spg_mode') != 'empty':runtime._spg_modes_tick=None
    spg_modes.update(runtime, now)
    settings=bot_tactics.map_settings(runtime._bot_tactics,runtime._navigation_map_name)
    zone=parking(settings,state)
    mode=order.get('combat_mode')
    pose=(float(state['x']),float(state['z']))
    active=state.get('_authored_spg_travel')
    empty=state.get('_spg_mode') == 'empty'
    if empty:order=dict(order,empty_ammo=True,movement_priority='empty_ammo_capture')
    order=dict(order,spg_mode=state['_spg_mode'])
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
        if original is not None and state['_spg_mode'] == 'deployment':
            state['_spg_initial']=original;state.pop('_spg_arrived_identity',None)
        state['_authored_spg_travel']=active
    if not defense:
        if state['_spg_mode'] == 'deployment':
            if state.get('_spg_deployment') == 'parking':
                if zone and separation(pose,zone['point'])<=zone['radius']:
                    if state.get('_authored_spg_zone')!=zone:state['_authored_spg_zone']=copy.deepcopy(zone)
                    if state.get('_authored_spg_used_initial')!=state.get('_spg_initial'):
                        state['_authored_spg_used_initial']=copy.deepcopy(state.get('_spg_initial'))
                return order
            state.pop('_authored_spg_travel', None)
            if state.get('_spg_deployment') == 'waiting':
                return dict(order,combat_mode='artillery_hold',move_position=(state['x'],state['y'],state['z']),
                    throttle_override=0.,spg_deployment='waiting',route_join=False)
            return automatic(runtime,state,order)
        attack=state.get('_authored_spg_attack')
        if attack is None and not state.get('_spg_automatic_attack'):
            attack=spg_route_recovery.select_route(runtime,state,None,prefer_spg=True)
            if attack is not None:state['_authored_spg_attack']=attack
            else:state['_spg_automatic_attack']=True
        if attack is None:
            base=runtime.baked_graph['objective_bases'][state['team']-1]
            radius=runtime.baked_graph.get('objective_base_radii',(30.,30.))[state['team']-1]
            if not state.get('_empty_spg_home_reached'):
                if separation(pose,base)<=radius:state['_empty_spg_home_reached']=True
                else:
                    return dict(order,move_position=(base[0],state['y'],base[1]),
                        face_position=(base[0],state['y'],base[1]),throttle_override=None,
                        combat_mode='spg_route_travel',route_join=True,
                        route_anchor=(pose[0],state['y'],pose[1]),authored_spg_connection='sortie_return')
            return automatic(runtime,state,order)
        if not active or active['kind'] not in ('sortie_return','attack'):
            base=runtime.baked_graph['objective_bases'][state['team']-1]
            active=_task(runtime,state,'sortie_return',[list(base)+[0]],('sortie_return',attack['id']),0)
            state['_authored_spg_travel']=active
        if not empty and order.get('target_id') is not None and order.get('fire_allowed'):
            spg_route_recovery.pause(active,now)
            # A firing opportunity pauses travel. It never restores the old
            # parking destination carried by the incoming server order.
            return dict(order,combat_mode='engage',move_position=(state['x'],state['y'],state['z']),
                        throttle_override=0.,route_join=False)
    if not active:return order
    if not defense and active['kind']=='defense':return order
    if defense and order.get('throttle_override')==0.:return order
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
        active=_task(runtime,state,'attack',attack['points'],('attack',attack['id']),
                     0 if attack.get('borrowed') else min(1,len(attack['points'])-1))
        state['_authored_spg_travel']=active
        destination=xy(active['points'][active['index']]);arrived=False
        state['_empty_spg_home_reached']=True
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


def automatic(runtime,state,order):
    """Unassigned deployment drives automatically; sortie fallback keeps its mode."""
    pose=(state['x'],state['y'],state['z'])
    if not order.get('empty_ammo') and order.get('target_id') is not None and order.get('fire_allowed'):
        return dict(order,combat_mode='engage',move_position=pose,throttle_override=0.,route_join=False)
    base=runtime.baked_graph['objective_bases'][2-state['team']]
    radius=runtime.baked_graph.get('objective_base_radii',(30.,30.))[2-state['team']]
    inside=separation((pose[0],pose[2]),base)<=radius
    return dict(order,combat_mode='base_capture',move_position=pose if inside else (base[0],pose[1],base[1]),
        face_position=(base[0],pose[1],base[1]),throttle_override=0. if inside else None,route_join=False)
