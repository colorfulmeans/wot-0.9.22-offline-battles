"""Compact diagnostic-only control history, independent of bulk trace quota."""
from . import native_input_diagnostics as diagnostics


def observe(runtime, state, command, throttle, turn, path_clear, probe, now):
    try:
        _observe(runtime, state, command, throttle, turn, path_clear, probe, now)
    except Exception:
        # Logging must never change movement or a native shot's outcome.
        pass


def _observe(runtime, state, command, throttle, turn, path_clear, probe, now):
    if not diagnostics.detailed_enabled() or (state.get('profile') or {}).get('class_tag') != 'SPG':
        return
    episode = state.get('_spg_control_observation')
    token = getattr(runtime, 'round_id', None)
    if episode is None or episode['round'] != token or now < episode['sample']:
        episode = dict(round=token, sample=-1e9, emitted=-1e9, rows=[], turn_sign=0, turn_flips=0)
        state['_spg_control_observation'] = episode
    sign = 1 if turn > .01 else -1 if turn < -.01 else 0
    if sign:
        if episode['turn_sign'] and sign != episode['turn_sign']:
            episode['turn_flips'] += 1
            episode['last_flip_at'] = now
        episode['turn_sign'] = sign
    if now - episode['sample'] < .25:
        return
    episode['sample'] = now
    # Eight scalar rows cover the full two-second publication interval.
    episode['rows'].append([round(now, 3), state.get('yaw'),
        state.get('turret_yaw'), state.get('gun_pitch'), state.get('speed'),
        throttle, turn, command.get('target_yaw'), state.get('hull_aiming')])
    del episode['rows'][:-8]
    if now - episode['emitted'] < 2.:
        return
    episode['emitted'] = now
    probe = probe if isinstance(probe, dict) else {}
    nav = getattr(getattr(runtime, 'navigator', None), 'bot_states', {}).get(state['id'], {})
    task = state.get('_authored_spg_travel') or {}
    target = command.get('target_id')
    diagnostics.write_json_record('SPG CONTROL', dict(round=token, bot=state['id'],
        vehicle=state.get('vehicle'), at=now, position=[state.get(k) for k in ('x','y','z')],
        columns=['at','yaw','turret_yaw','gun_pitch','speed','throttle','turn','target_yaw','hull_aiming'],
        controls=list(episode['rows']), mode=command.get('combat_mode'),
        turn_flips=episode['turn_flips'], last_flip_at=episode.get('last_flip_at'),
        empty=command.get('empty_ammo', False), stock=state.get('ammo_remaining'),
        fire_seq=state.get('fire_seq'), reload=state.get('reload_time'),
        target=[command.get('target_kind'), target], aim=command.get('aim_position'),
        fire_allowed=command.get('fire_allowed'), gun_aligned=state.get('gun_aligned'),
        desired_pitch=state.get('desired_gun_pitch'), aim_yaw=state.get('aim_yaw'),
        aim_intent={k:(state.get('_diagnostic_aim_intent') or {}).get(k) for k in
                    ('target_kind','target_id','turret_yaw','gun_pitch','planning_pending','time_us')},
        face=command.get('face_position'), goal=command.get('move_position'),
        driver=[command.get('throttle'),command.get('turn')],
        movement=command.get('movement_intent'), brake=command.get('brake'),
        spg_mode=state.get('_spg_mode'), deployment=state.get('_spg_deployment'),
        task={k:task.get(k) for k in ('kind','identity','index','recovery_phase','paused_at')},
        navigation={k:nav.get(k) for k in ('index','planned_goal','navigation_status','pending_since')},
        path_clear=path_clear, probe={k:(probe or {}).get(k) for k in ('clear','reason','collision')},
        gates=list(state.get('_motion_control_gates') or ())[-8:],
        proof=state['id'] in getattr(runtime,'_artillery_reproofs',{}),
        intent=state['id'] in getattr(runtime,'_artillery_intents',{})))
