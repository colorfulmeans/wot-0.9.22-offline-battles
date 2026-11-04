"""Private local flanking and stable stationary armour orientation.

Only visible target geometry and friendly native observations are inputs.
This module returns intent; PlayerNavigation, foreground collision sweeps,
gun admission and the native drive step retain their independent vetoes.
"""
from __future__ import division
import math
from .strategy import CLASS_RANGES, target_value
from .observations import actor_priority


def _distance(first, second):
    return math.hypot(first[0] - second[0], first[2] - second[2])


def _angle(value):
    return math.atan2(math.sin(value), math.cos(value))


def _tag(descriptor):
    tags = target_value(target_value(descriptor, 'type', {}), 'tags', ()) or ()
    return next((tag for tag in ('SPG', 'AT-SPG', 'heavyTank', 'mediumTank', 'lightTank')
                 if tag in tags), 'mediumTank')


class CombatTactics(object):
    def __init__(self):
        self.flank = None
        self.completed = set()
        self.retry_at = 0.
        self.angle_anchor = None
        self.receipt = dict(phase='idle')

    def reset(self):
        self.flank = self.angle_anchor = None
        self.completed.clear()
        self.retry_at = 0.
        self.receipt = dict(phase='idle')

    def _retire(self, now, reason, completed=False):
        if completed and self.flank is not None:
            self.completed.add(self.flank['target'])
        self.flank = None
        self.retry_at = now + 15.
        self.receipt = dict(phase='idle', reason=reason, retry_at=self.retry_at)

    def movement(self, state, context, descriptor, allowed, height, clear):
        now, position = state['now'], state['position']
        target = context.get('target')
        identity, point = target_value(target, 'id'), target_value(target, 'position')
        tag = _tag(descriptor)
        if (not allowed or point is None or tag not in ('mediumTank', 'lightTank') or
                context.get('empty_ammo') or context.get('burst_active') or
                not context.get('fire_clear') or not context.get('supported', True) or
                context.get('overturned') or target_value(descriptor, 'hasSiegeMode', False)):
            if self.flank is not None:
                self._retire(now, 'movement_owner_changed')
            return None
        if self.flank is not None:
            record = self.flank
            if identity != record['target'] or _distance(point, record['target_point']) > 15.:
                self._retire(now, 'target_geometry_changed')
                return None
            if _distance(position, record['goal']) <= 4. and abs(position[1]-record['goal'][1]) <= 1.:
                self._retire(now, 'flank_approach_reached', completed=True)
                return None
            if _distance(position, record['progress_position']) >= 2.:
                record['progress_position'], record['progress_at'] = tuple(position), now
            if now - record['progress_at'] >= 8. or now - record['at'] >= 30.:
                self._retire(now, 'flank_progress_timeout')
                return None
            self.receipt = dict(phase='flank', goal=record['goal'], target=identity,
                                support=record['support'], source='local_observation')
            return dict(self.receipt)
        if now < self.retry_at or identity in self.completed:
            return None
        desired, fire_range = CLASS_RANGES[tag]
        span = _distance(position, point)
        if span < max(70., desired*.55) or span > fire_range:
            return None
        if float(state.get('health', 1)) / max(1., float(state.get('max_health', 1))) < .3:
            return None
        own = state.get('engine_id', state.get('id'))
        supporters = []
        for ally in context.get('allies') or ():
            if (ally.get('id') == own or ally.get('position') is None or
                    not ally.get('alive', True) or ally.get('health', 1) <= 0 or
                    ally.get('class_tag') == 'SPG' or _distance(ally['position'], point) > 280.):
                continue
            supporters.append(ally)
        if not supporters:
            self.receipt = dict(phase='idle', reason='retain_firing_support')
            return None
        # Elect at most one local mobile flanker from the same observation.
        # At least one other combat hull remains available to support it.
        own_actor = dict(state, id=own)
        mobile = [own_actor] + [row for row in supporters
                               if row.get('class_tag') in ('mediumTank', 'lightTank')]
        if min(mobile, key=actor_priority) is not own_actor:
            self.receipt = dict(phase='idle', reason='local_flanker_already_preferred')
            return None
        base_bearing = math.atan2(position[0]-point[0], position[2]-point[2])
        # Prefer the side which opens a different firing bearing to observed
        # supporters, rather than copying their lane or reserving a team slot.
        candidates = []
        radius = min(span, desired*1.05)
        for side in (-1., 1.):
            bearing = base_bearing + side*math.radians(32.)
            horizontal = (point[0]+math.sin(bearing)*radius,
                          point[2]+math.cos(bearing)*radius)
            diversity = min(abs(_angle(bearing-math.atan2(
                ally['position'][0]-point[0], ally['position'][2]-point[2])))
                for ally in supporters)
            candidates.append((diversity, side, horizontal))
        for unused, side, horizontal in sorted(candidates, reverse=True):
            y = height(horizontal, position[1])
            if y is None:
                continue
            goal = (horizontal[0], y, horizontal[1])
            bearing = math.atan2(goal[0]-position[0], goal[2]-position[2])
            if not clear(bearing, min(8., _distance(position, goal))):
                continue
            self.flank = dict(target=identity, target_point=tuple(point), goal=goal,
                at=now, progress_at=now, progress_position=tuple(position),
                support=[row['id'] for row in supporters], side=side)
            self.receipt = dict(phase='flank', target=identity, goal=goal,
                                support=self.flank['support'], source='local_observation')
            return dict(self.receipt)
        self.retry_at = now + 1.
        self.receipt = dict(phase='idle', reason='flank_geometry_unproved', retry_at=self.retry_at)
        return None

    def facing(self, state, target, descriptor, limited=False):
        """One stable target-relative angle, never a periodic open-ground jiggle."""
        tag = _tag(descriptor)
        point, identity = target_value(target, 'position'), target_value(target, 'id')
        if (limited or tag in ('SPG', 'AT-SPG') or point is None or
                target_value(descriptor, 'hasSiegeMode', False) or
                abs(state.get('speed', 0.)) > 1.5 or state.get('burst_active')):
            return None
        armour = []
        for component in ('hull', 'turret'):
            value = target_value(target_value(descriptor, component, {}), 'primaryArmor', 0.)
            armour.extend(value if isinstance(value, (tuple, list)) else (value,))
        if max([float(value or 0.) for value in armour] or [0.]) < 60.:
            return None
        position = state['position']
        if _distance(position, point) <= 10.:
            return None
        if self.angle_anchor is None or self.angle_anchor['target'] != identity:
            # A public actor identity is stable across local engine mappings.
            parity = sum(ord(value) for value in str(actor_priority(state))) % 2
            offset = math.radians(22.) * (-1. if parity else 1.)
            self.angle_anchor = dict(target=identity, offset=offset)
        bearing = math.atan2(point[0]-position[0], point[2]-position[2])
        self.receipt = dict(phase='angled_hold', target=identity,
                            degrees=math.degrees(self.angle_anchor['offset']))
        return _angle(bearing + self.angle_anchor['offset'] - state['yaw'])


class CombatFacing(object):
    """One stop/pivot attempt for an established direct-fire engagement."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.attempt = None

    def active_for(self, target):
        return bool(self.attempt is not None and self.attempt['target'] == target and
                    self.attempt['phase'] in ('braking', 'turning', 'settling'))

    def apply(self, order, state, target, error, limit, yaw_rate, clear, obstacles):
        now, position = state['now'], state['position']
        attempt = self.attempt
        if (attempt is None or attempt['target'] != target or
                attempt['phase'] in ('aligned', 'blocked', 'timed_out') and
                _distance(attempt['position'], position) > .5 or
                attempt['phase'] == 'blocked' and now >= attempt['retry'] and
                attempt['obstacles'] != obstacles()):
            attempt = self.attempt = dict(target=target, position=tuple(position),
                phase='braking', started=now, progress=now, best=abs(error),
                obstacles=None, retry=0., outcome=None)
        phase = attempt['phase']
        moving = abs(state['speed']) > .2
        rotating = abs(yaw_rate) > .05
        if phase in ('braking', 'turning'):
            if abs(error) < attempt['best'] - .015:
                attempt.update(best=abs(error), progress=now)
            if abs(error) <= limit:
                attempt['outcome'] = 'aligned'
            elif (now-attempt['started'] >= 8. or
                    phase == 'turning' and now-attempt['progress'] >= 2.):
                attempt['outcome'] = 'timed_out'
            elif moving or phase == 'braking' and rotating:
                attempt['phase'] = 'braking'
            else:
                turn = max(-1., min(1., error / .5))
                if clear(turn):
                    order.update(throttle=0., turn=turn, brake=False,
                                 recovery_mode='combat_facing')
                    if phase != 'turning':
                        attempt['progress'] = now
                    attempt['phase'] = 'turning'
                else:
                    attempt.update(outcome='blocked', obstacles=obstacles(), retry=now + .7)
            if attempt['outcome'] is not None:
                attempt['phase'] = 'settling' if moving or rotating else attempt['outcome']
                attempt['position'] = tuple(position)
        elif phase == 'settling' and not (moving or rotating):
            attempt['phase'] = attempt['outcome']
            attempt['position'] = tuple(position)

        phase = attempt['phase']
        if phase in ('braking', 'settling', 'blocked', 'timed_out'):
            order.update(throttle=0., turn=0., brake=True)
        if phase != 'aligned':
            order['traffic_hold_protected'] = True
        order['combat_facing'] = dict(target=target, error=error, state=phase,
            elapsed=now-attempt['started'], waiting_to_fire=self.active_for(target))
        return self.active_for(target)
