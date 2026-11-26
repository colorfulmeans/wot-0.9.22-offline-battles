# -*- coding: utf-8 -*-
"""Tactical profile of one vehicle, read from its installed descriptor.

The server tactics read the class, the role scores, the engagement ranges,
the forward speed and the armour. Route pressure weighs every role score
against a route's role weights. The ammunition policy reads the gun, clip
and shells. The module is engine-free and must parse on Python 2.7.
"""

CLASSES = ('heavyTank', 'mediumTank', 'lightTank', 'AT-SPG', 'SPG')
DEFAULT_CLASS = 'mediumTank'

# Role scores per class before the speed and armour adjustments below.
ROLE_SCORES = {
    'heavyTank': {'brawler': 0.92, 'support': 0.55, 'flanker': 0.18, 'sniper': 0.20, 'scout': 0.05},
    'mediumTank': {'brawler': 0.46, 'support': 0.76, 'flanker': 0.86, 'sniper': 0.48, 'scout': 0.42},
    'lightTank': {'brawler': 0.10, 'support': 0.45, 'flanker': 0.72, 'sniper': 0.28, 'scout': 0.96},
    'AT-SPG': {'brawler': 0.32, 'support': 0.78, 'flanker': 0.18, 'sniper': 0.92, 'scout': 0.08},
    'SPG': {'brawler': 0.00, 'support': 0.10, 'flanker': 0.00, 'sniper': 0.16, 'scout': 0.00},
}

# Desired engagement range and maximum fire range, in metres. The SPG pair
# describes its battery role; the client proves every real trajectory.
ENGAGEMENT_RANGES = {
    'heavyTank': (72.0, 260.0),
    'mediumTank': (135.0, 340.0),
    'lightTank': (175.0, 320.0),
    'AT-SPG': (255.0, 450.0),
    'SPG': (650.0, 1250.0),
}

FAST_SPEED = 15.0
SLOW_SPEED = 9.0
HEAVY_ARMOR = 120.0


def _field(value, key, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _number(value, default=0.0):
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or abs(result) == float('inf'):
        return float(default)
    return result


def _middle(value):
    """Representative value of a scalar or of a min/max pair."""
    if isinstance(value, (tuple, list)):
        values = [_number(item) for item in value]
        if values:
            return sum(values) / float(len(values))
    return _number(value)


def _component_armor(component):
    armor = _field(component if component is not None else {}, 'primaryArmor', 0.0)
    if isinstance(armor, (tuple, list)):
        return max([_number(item) for item in armor] or [0.0])
    return _number(armor)


def vehicle_class(descriptor):
    """The descriptor's class tag; an untagged vehicle counts as medium."""
    try:
        tags = tuple(_field(_field(descriptor, 'type', None), 'tags', ()) or ())
    except Exception:
        tags = ()
    for tag in CLASSES:
        if tag in tags:
            return tag
    return DEFAULT_CLASS


def armor(descriptor):
    """Thickest primary hull or turret plate."""
    return max(_component_armor(_field(descriptor, 'hull', {})),
               _component_armor(_field(descriptor, 'turret', {})))


def _forward_speed(descriptor):
    # #1513 keeps physics as a plain dict; anything else has no known limit.
    physics = _field(descriptor, 'physics', {}) or {}
    if not isinstance(physics, dict):
        return 0.0
    try:
        return abs(float(physics.get('speedLimits')[0]))
    except Exception:
        return 0.0


def _roles(tag, speed, plate):
    roles = dict(ROLE_SCORES[tag])
    if speed >= FAST_SPEED:
        roles['flanker'] = min(1.0, roles['flanker'] + 0.12)
        roles['scout'] = min(1.0, roles['scout'] + 0.08)
    elif speed and speed < SLOW_SPEED:
        roles['flanker'] = max(0.0, roles['flanker'] - 0.16)
    # Armour never turns a tank destroyer into a short-range brawler.
    if plate >= HEAVY_ARMOR and tag != 'AT-SPG':
        roles['brawler'] = min(1.0, roles['brawler'] + 0.18)
        roles['sniper'] = max(0.0, roles['sniper'] - 0.08)
    return roles


def _shells(gun):
    result = []
    try:
        shots = list(enumerate(_field(gun, 'shots', ()) or ()))
    except Exception:
        shots = []
    for index, shot in shots:
        shell = _field(shot, 'shell', {})
        if shell is None:
            shell = {}
        result.append({
            'index': int(index),
            'kind': str(_field(shell, 'kind', '') or ''),
            'name': _field(shell, 'name', ''),
            'penetration': _middle(_field(shell, 'piercingPower', 0.0)),
            'damage': _middle(_field(shell, 'damage', 0.0)),
            'speed': _number(_field(shot, 'speed', 0.0)),
        })
    return tuple(result)


def vehicle_profile(descriptor):
    """Return the serializable tactical profile of one installed vehicle."""
    tag = vehicle_class(descriptor)
    plate = armor(descriptor)
    gun = _field(descriptor, 'gun', {})
    if gun is None:
        gun = {}
    desired_range, fire_range = ENGAGEMENT_RANGES[tag]
    speed = _forward_speed(descriptor)
    name = _field(_field(descriptor, 'type', None), 'name', tag)
    from gui.mods.offline_lan_0922 import bot_fittings
    fitting = bot_fittings.context(descriptor)
    return {
        'bot_tier': fitting['wire'].get('tier') if fitting is not None else None,
        'class_tag': tag,
        'vehicle_name': str(name or tag),
        'roles': _roles(tag, speed, plate),
        'desired_range': desired_range,
        'fire_range': fire_range,
        # Base-defense responder selection estimates arrival from it.
        'speed': speed,
        'armor': plate,
        'clip_size': int((_field(gun, 'clip', (1,)) or (1,))[0]),
        'gun_name': str(_field(gun, 'name', '')),
        'shells': _shells(gun),
    }
