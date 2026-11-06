"""Bounded foreground hull laying for a proved, horizontally unlaid ray."""
from __future__ import division
import math

from .aiming import NATIVE_ANGLE_TOLERANCE


class HullAlignment(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.attempt = None

    def matches(self, key, identity):
        return bool(self.attempt is not None and self.attempt['key'] == key and
                    self.attempt['identity'] == identity)

    def apply(self, order, state, key, identity, error, needs_hull, pending, can_turn):
        now = state['now']
        if not self.matches(key, identity):
            self.reset()
        if not needs_hull:
            if self.attempt is not None:
                order['combat_facing'] = dict(key=key, target=key[0], state='aligned',
                    limited_traverse=True, error=error, elapsed=now-self.attempt['start'])
            self.reset()
            return False
        if self.attempt is None:
            rate = state.get('turn_speed_limit')
            # Keep a finite lease, including the proportional controller's
            # final convergence into the installed arc. A constant-rate
            # angle/rate estimate cuts off a slow, still-progressing fixed
            # gun before its decreasing command can finish laying. This is
            # a controller budget, not a replacement for measured body yaw.
            duration = 8.
            if isinstance(rate, (int, float)) and 0. < rate < float('inf'):
                radius = abs(error)
                convergence = .5 * math.log(max(1., min(radius, .5) /
                                                  NATIVE_ANGLE_TOLERANCE))
                duration = max(duration, 2. * (max(0., radius-.5) + convergence) / rate + 2.)
            self.attempt = dict(key=key, identity=identity, start=now, progress=now,
                best=abs(error), deadline=now+duration, pending_since=None)
        attempt = self.attempt
        tolerance = max(NATIVE_ANGLE_TOLERANCE*.1, min(.015, attempt['best']*.05))
        if abs(error) < attempt['best'] - tolerance:
            attempt['best'], attempt['progress'] = abs(error), now
        order.update(throttle=0., turn=0., brake=True, holding=True,
                     travel_intent=False, traffic_hold_protected=True)
        phase = 'checking' if pending else 'braking' if abs(state['speed']) > .2 else 'turning'
        stalled = now < attempt['start'] or now >= attempt['deadline']
        if pending:
            if attempt['pending_since'] is None:
                attempt['pending_since'] = now
            stalled = stalled or now-attempt['pending_since'] >= 5.
        else:
            attempt['pending_since'] = None
            stalled = stalled or now-attempt['progress'] >= 2.4
        if stalled:
            phase = 'stalled'
        elif phase == 'turning':
            # Do not use the old .02-radian cutoff: a fixed or narrow gun
            # can still be outside its actual arc at that residual error.
            turn = max(-1., min(1., error/.5))
            if abs(error) <= NATIVE_ANGLE_TOLERANCE:
                phase = 'checking'
            elif can_turn(turn):
                order.update(turn=turn, brake=False, recovery_mode='combat_facing')
            else:
                phase = 'blocked'
        order['combat_facing'] = dict(key=key, target=key[0], state=phase,
            limited_traverse=True, error=error, elapsed=now-attempt['start'],
            progress_age=now-attempt['progress'], deadline=attempt['deadline'])
        return stalled
