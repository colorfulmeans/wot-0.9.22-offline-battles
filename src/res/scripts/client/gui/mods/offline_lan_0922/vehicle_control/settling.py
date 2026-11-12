"""One full-body rest law over observed actor motion."""
from __future__ import division

import math


def foreground_motion(owner):
    """Read foreground physics without inventing absent support or velocity."""
    try:
        position, yaw = owner.local_pose()
        return dict(speed=owner._local_speed,
            turn_speed=owner._local_turn_speed,
            pitch=owner._local_pitch, roll=owner._local_roll,
            pitch_speed=owner._local_suspension_pitch_velocity,
            roll_speed=owner._local_suspension_roll_velocity,
            vertical_speed=owner._local_vertical_speed,
            lateral_speed=owner._local_air_lateral,
            position=position, yaw=yaw, airborne=owner._local_airborne,
            support_rise_blocked=owner._local_support_rise_blocked,
            overturn_level=owner._overturn_level)
    except (AttributeError, TypeError, ValueError, IndexError, OverflowError):
        return None


class HaltObservation(object):
    SETTLE_SECONDS = .5

    def __init__(self):
        self.since = None
        self.anchor = None
        self.receipt = dict(known=False, settled=False, reason='not_observed')

    def observe(self, owner, now, releases_pending=False):
        return self.observe_motion(foreground_motion(owner), now, releases_pending)

    def observe_motion(self, motion, now, releases_pending=False):
        """Use the same measured stopping thresholds for every actor binding."""
        try:
            speed = float(motion['speed'])
            turn = float(motion['turn_speed'])
            pitch = float(motion['pitch'])
            roll = float(motion['roll'])
            pitch_speed = float(motion['pitch_speed'])
            roll_speed = float(motion['roll_speed'])
            vertical = float(motion['vertical_speed'])
            lateral = tuple(float(v) for v in motion['lateral_speed'])
            position, yaw = motion['position'], motion['yaw']
            position = tuple(float(position[i]) for i in range(3))
            yaw = float(yaw)
            if (not isinstance(motion['airborne'], bool) or
                    not isinstance(motion['support_rise_blocked'], bool)):
                raise ValueError('unknown support observation')
            supported = not motion['airborne'] and not motion['support_rise_blocked']
            overturn = float(motion['overturn_level'])
            supported = supported and overturn != 2
            orientation = (yaw, pitch, roll)
            values = (speed, turn, vertical, pitch_speed, roll_speed, overturn) + orientation + lateral + position
            if len(lateral) != 2 or any(math.isnan(v) or math.isinf(v) for v in values):
                raise ValueError('invalid motion observation')
        except (AttributeError, KeyError, TypeError, ValueError, IndexError, OverflowError):
            self.since = self.anchor = None
            self.receipt = dict(known=False, settled=False, reason='motion_unavailable')
            return False
        slow = (abs(speed) <= .2 and abs(turn) <= .02 and abs(vertical) <= .2 and
                abs(pitch_speed) <= .02 and abs(roll_speed) <= .02 and
                math.hypot(*lateral) <= .2)
        stable = supported and slow and not releases_pending
        if stable and self.anchor is not None:
            previous, angles = self.anchor
            deltas = [(value - old + math.pi) % (2. * math.pi) - math.pi
                      for value, old in zip(orientation, angles)]
            stable = (sum((position[i] - previous[i]) ** 2 for i in range(3)) <= .1 ** 2 and
                      all(abs(delta) <= .02 for delta in deltas))
        if not stable or self.since is not None and now < self.since:
            self.since = self.anchor = None
        if supported and slow and not releases_pending and self.since is None:
            self.since, self.anchor = now, (position, orientation)
        settled = self.since is not None and now - self.since >= self.SETTLE_SECONDS
        self.receipt = dict(known=True, settled=settled, supported=supported,
            speed=speed, turn_speed=turn, vertical_speed=vertical, lateral_speed=lateral,
            pitch=pitch, roll=roll, pitch_speed=pitch_speed, roll_speed=roll_speed,
            settled_since=self.since, reason=('release_pending' if releases_pending else
                'unsupported' if not supported else 'moving' if not slow else
                'settled' if settled else 'settling'))
        return settled
