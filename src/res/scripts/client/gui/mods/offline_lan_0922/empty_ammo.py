# -*- coding: utf-8 -*-
"""Positive empty-inventory proof, distinct from reload or unknown state."""


def confirmed(state, profile=None):
    values = state.get('ammo_remaining')
    if not isinstance(values, (list, tuple)) or not values:
        return False
    shells = (profile or {}).get('shells') or ()
    if shells and len(values) != len(shells):
        return False
    return all(not isinstance(value, bool) and isinstance(value, (int, float))
               and value == 0 for value in values)


def active(bot):
    return bool(bot.get('empty_ammo') or confirmed(bot.get('state') or {}, bot.get('profile')))


def handoff(runtime, state, order):
    """Retire old local motion once; never touch launched shot ownership."""
    if not order.get('empty_ammo') or state.get('_empty_ammo_active'):
        return
    state['_empty_ammo_active'] = True
    for key in ('_rear_motion_lease', '_rear_aim_episode', '_rear_hull_aim',
                '_gun_angle_adjustment', '_gun_angle_pivot_refusal',
                '_authored_spg_travel', '_authored_spg_attack',
                '_authored_spg_defending', '_authored_spg_resume',
                '_authored_spg_return_zone', '_authored_spg_return_initial'):
        state.pop(key, None)
    adapter = getattr(runtime, 'adapter', None)
    driver = getattr(adapter, 'driver', None)
    getattr(driver, 'states', {}).pop(state['id'], None)
    for name in ('_withdrawal_attempts', '_contact_escapes', '_flank_arrivals'):
        getattr(adapter, name, {}).pop(state['id'], None)
    # These are unlaunched planning intents, not projectile ledgers.
    cancel = getattr(runtime, '_cancel_artillery_intent', None)
    if callable(cancel):
        cancel(state['id'])
