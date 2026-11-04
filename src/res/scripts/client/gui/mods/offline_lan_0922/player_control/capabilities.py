"""Observed player capability state; absence of data never proves no ammo."""
from __future__ import division
import math


def ammunition_state(gun):
    unknown = dict(state='unknown', empty=False, available=False, total=None,
                   current=None, clip=None, reload_seconds=None, can_fire=False)
    if gun is None:
        return unknown
    ammo, shots = getattr(gun, 'ammo', None), getattr(gun, 'shots', None)
    if not isinstance(ammo, (tuple, list)) or not shots or len(ammo) != len(shots):
        return unknown
    try:
        counts = [int(value) for value in ammo]
        if any(isinstance(value, bool) or value != count or count < 0
               for value, count in zip(ammo, counts)):
            return unknown
        current = int(gun.shot_index)
        if not 0 <= current < len(counts):
            return unknown
        clip, reload_seconds = int(gun.clip), float(gun.reload_time)
        if clip < 0 or math.isnan(reload_seconds) or math.isinf(reload_seconds):
            return unknown
    except (AttributeError, TypeError, ValueError, OverflowError):
        return unknown
    total = sum(counts)
    can_fire = bool(gun.can_fire(True))
    state = ('empty' if total == 0 else 'shell_empty' if counts[current] == 0 else
             'reloading' if reload_seconds > 0. or clip == 0 else
             'ready' if can_fire else 'busy')
    return dict(state=state, empty=total == 0, available=True, total=total,
                current=counts[current], shell_index=current, clip=clip,
                reload_seconds=max(0., reload_seconds), can_fire=can_fire)


class Governor(object):
    """Player-owned uphill and progressing wreck-push equipment decisions."""
    def __init__(self):
        self.uphill_since = self.push = None

    def wanted(self, now, speed, pitch, supported, engine_damaged, push=None):
        if not supported or engine_damaged:
            self.uphill_since = self.push = None
            return False
        if push and push.get('phase') == 'pushing':
            self.uphill_since = None
            previous = self.push
            progress = float(push.get('progress', 0.))
            if (previous is None or previous[0] != push['peer'] or
                    progress >= previous[1] + .1 or now < previous[2]):
                self.push = (push['peer'], progress, now)
            return now - self.push[2] < 2.
        self.push = None
        grade = (-pitch if speed > 0. else pitch) if pitch is not None else 0.
        if abs(speed) <= .1 or grade <= math.radians(.5):
            self.uphill_since = None
            return False
        if self.uphill_since is None or now < self.uphill_since:
            self.uphill_since = now
        return now - self.uphill_since >= 2.
