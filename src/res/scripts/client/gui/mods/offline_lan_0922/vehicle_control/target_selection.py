# -*- coding: utf-8 -*-
"""Initial target ordering; current valid engagements are retained by their owner.

Armor is a tie-breaker for exactly equal initial distance, not a replacement
for native point-by-point penetration validation. Artillery callers must supply
an actual reachable-solution HE estimate, never a nominal shell-damage proxy.
"""
import math


def _number(value, default=0.0):
    try:
        value = float(value)
        return value if not (math.isnan(value) or math.isinf(value)) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _position(value):
    if isinstance(value, dict):
        position = value.get('position')
        if isinstance(position, (dict, list, tuple)):
            return _position(position)
        return (_number(value.get('x')), _number(value.get('y')),
                _number(value.get('z')))
    try:
        return tuple(_number(value[index]) for index in range(3))
    except (TypeError, IndexError, KeyError):
        return (0.0, 0.0, 0.0)


def live_contact(target):
    if not isinstance(target, dict) or target.get('alive') is False:
        return False
    if 'health' in target and _number(target.get('health'), 0.0) <= 0.0:
        return False
    return True


def ordinary_initial_key(source_position, target):
    source, point = _position(source_position), _position(target)
    distance = math.hypot(point[0] - source[0], point[2] - source[2])
    profile = target.get('profile') or {}
    armor = _number(target.get('armor', profile.get('armor')), float('inf'))
    kind = str(target.get('target_kind', target.get('kind', '')) or '')
    identity = target.get('network_id', target.get('id', 0))
    return distance, armor, kind, _number(identity)


def artillery_damage_key(source_position, target, expected_he_damage):
    damage = _number(expected_he_damage, -1.0)
    if damage < 0.0:
        raise ValueError('artillery selection requires a finite HE damage estimate')
    return (-damage,) + ordinary_initial_key(source_position, target)
