# -*- coding: utf-8 -*-
"""Round-owned artillery deployment, sortie admission and parking reservations."""
import copy
import random

from gui.mods.offline_lan_0922 import empty_ammo


def _invalidate(runtime, state):
    getattr(runtime, '_decision_cache', {}).pop(state['id'], None)


def parking_exclusions(runtime, state):
    return sorted(key[1] for key, slot in getattr(runtime, '_spg_mode_slots', {}).items()
                  if key[0] == state['team'] and (slot['disabled'] or
                  slot['owner'] not in (None, state['id'])))


def release_parking(runtime, state, failed=False):
    for slot in getattr(runtime, '_spg_mode_slots', {}).values():
        if slot['owner'] == state['id']:
            slot.update(owner=None, disabled=slot['disabled'] or failed)
    state.pop('_spg_initial', None)
    state.pop('_spg_replacement_zone', None)
    state.pop('_spg_arrived_identity', None)
    state.pop('_spg_deployment_progress', None)
    state.pop('_authored_spg_zone', None)
    state.pop('_authored_spg_used_initial', None)
    state['_spg_deployment'] = 'automatic'
    _invalidate(runtime, state)


def update(runtime, now):
    token = (getattr(runtime, 'round_id', 0), now)
    if getattr(runtime, '_spg_modes_tick', None) == token:
        return
    runtime._spg_modes_tick = token
    states = list(runtime._ordered_states())
    round_id = token[0]
    if getattr(runtime, '_spg_modes_round', None) != round_id:
        runtime._spg_modes_round = round_id
        runtime._spg_mode_slots = {}
        runtime._spg_endgame_teams = set()
    slots = runtime._spg_mode_slots
    living = dict((s['id'], s) for s in states if s.get('alive', True))
    artillery = sorted((s for s in living.values() if (s.get('profile') or {}).get('class_tag') == 'SPG'), key=lambda s:(s['team'],s.get('slot',s['id']),s['id']))
    for s in artillery:
        if s.get('_spg_mode_round') != round_id:
            if '_spg_mode_round' in s:
                for name in list(s):
                    if name.startswith('_authored_spg_') or name in (
                            '_spg_automatic_attack', '_empty_spg_home_reached',
                            '_spg_replacement_zone'):
                        s.pop(name, None)
            s['_spg_mode_round'] = round_id
            s['_spg_mode'] = 'deployment'
            initial = s.get('_spg_initial')
            key = (s['team'], initial['zone']) if initial else None
            if (key is not None and key not in slots and
                    sum(k[0] == s['team'] for k in slots) < 3):
                slots[key] = dict(owner=s['id'], plan=copy.deepcopy(initial), disabled=False)
                s['_spg_deployment'] = 'parking'
            else:
                s.pop('_spg_initial', None)
                s['_spg_deployment'] = 'automatic'
            _invalidate(runtime, s)
        if empty_ammo.confirmed(s,s.get('profile')) or s.get('_empty_ammo_active'):
            if s['_spg_mode'] != 'empty':
                empty_ammo.handoff(runtime, s, dict(empty_ammo=True))
                release_parking(runtime, s)
                for key in ('_authored_spg_travel', '_authored_spg_attack',
                            '_authored_spg_defending', '_authored_spg_resume',
                            '_authored_spg_return_initial', '_empty_spg_home_reached',
                            '_spg_automatic_attack'):
                    s.pop(key, None)
            s['_spg_mode'] = 'empty'
    for key, slot in list(slots.items()):
        owner = living.get(slot['owner'])
        if owner is None or owner.get('_spg_mode') != 'deployment':
            slot['owner'] = None
        elif owner.get('_spg_initial') and owner['_spg_initial']['zone'] != key[1]:
            # Relocation changes a reservation, not the number of occupied slots.
            destination = (key[0], owner['_spg_initial']['zone'])
            if destination in slots and (slots[destination]['disabled'] or
                    slots[destination]['owner'] not in (None, owner['id'])):
                release_parking(runtime, owner)
            else:
                slots.pop(key)
                slots[destination] = dict(owner=owner['id'], plan=copy.deepcopy(owner['_spg_initial']), disabled=False)
    for team in (1, 2):
        team_alive = [s for s in living.values() if s['team'] == team]
        spgs = [s for s in artillery if s['team'] == team]
        # Humans never participate in this admission test.
        if team_alive and len(team_alive) == len(spgs):
            runtime._spg_endgame_teams.add(team)
        if team in runtime._spg_endgame_teams:
            selected = [s for s in spgs if s['_spg_mode'] == 'sortie']
            candidates = [s for s in spgs if s['_spg_mode'] == 'deployment']
            while len(selected) < 3 and candidates:
                free = [s for s in candidates if not s.get('_spg_initial')]
                chosen = random.choice(free or candidates)
                candidates.remove(chosen)
                release_parking(runtime, chosen)
                chosen['_spg_mode'] = 'sortie'
                selected.append(chosen)
            for s in candidates:
                if s.get('_spg_deployment') != 'waiting':_invalidate(runtime, s)
                s['_spg_deployment'] = 'waiting'
            continue
        # Dead owners free the reserved region, not every transient stop.
        for key, slot in sorted(slots.items()):
            if key[0] != team or slot['disabled'] or slot['owner'] is not None:
                continue
            free = [s for s in spgs if s['_spg_mode'] == 'deployment' and not s.get('_spg_initial')]
            if not free:
                break
            chosen = random.choice(free)
            plan = copy.deepcopy(slot['plan'])
            plan['vehicle'] = chosen.get('vehicle', plan.get('vehicle'))
            shape = chosen.get('collision_shape')
            if shape:
                plan['clearance'] = (float(shape[0])**2 + float(shape[1])**2)**.5 + 2.
            chosen.update(_spg_initial=plan, _spg_replacement_zone=key,
                          _spg_deployment='parking')
            slot['owner'] = chosen['id']
            _invalidate(runtime, chosen)
