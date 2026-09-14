# -*- coding: utf-8 -*-
"""Append the hovered shell's installed-gun muzzle velocity to #1513 text."""
import math


def _shot_field(shot, name, default=None):
    # #1513 GunShot inherits NoLegacyStuff in the client: get(), indexing
    # and every other dict-like operation deliberately raise AssertionError.
    # Its supported API is shell/speed attributes. Plain dictionaries are
    # retained for serialized descriptors and test fixtures only.
    if isinstance(shot, dict):
        return shot.get(name, default)
    return getattr(shot, name, default)


def append_speed(tooltip, shell, vehicle):
    gun = getattr(vehicle, 'gun', None)
    shell_cd = getattr(shell, 'compactDescr', None)
    speed = None
    for shot in getattr(gun, 'shots', ()):
        candidate = _shot_field(shot, 'shell')
        if (candidate is shell or (shell_cd is not None and
                getattr(candidate, 'compactDescr', None) == shell_cd)):
            speed = float(_shot_field(shot, 'speed', 0.0))
            break
    if speed is None or speed <= 0 or math.isnan(speed) or math.isinf(speed):
        return tooltip
    was_bytes = isinstance(tooltip, bytes)
    text = tooltip.decode('utf-8') if was_bytes else tooltip
    line = u'\u5f39\u901f\uff1a%.0f \u7c73/\u79d2' % speed
    if '{/BODY}' in text:
        text = text.replace('{/BODY}', u'\n' + line + '{/BODY}', 1)
    else:
        text += u'\n/{BODY}' + line + '{/BODY}'
    return text.encode('utf-8') if was_bytes else text
