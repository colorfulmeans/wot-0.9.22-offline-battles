"""Human-only base defence and observed-front support. No Bot scheduling."""
from __future__ import division
import math


def lane_distance(position, route):
    points = route.get('waypoints', ())
    distances = []
    for first,last in zip(points,points[1:]):
        dx,dz=last[0]-first[0],last[1]-first[1]
        length=dx*dx+dz*dz
        t=max(0.,min(1.,((position[0]-first[0])*dx+(position[2]-first[1])*dz)/length)) if length else 0.
        distances.append(math.hypot(position[0]-first[0]-t*dx,position[2]-first[1]-t*dz))
    return min(distances) if distances else float('inf')


def defence_routes(home, routes):
    # A flag centre can be occupied or have no supported navigation cell.
    # Offer nearby approach points; PlayerNavigation must still prove each
    # candidate's actual height and connected path, including bridge layers.
    points=[tuple(home)]
    points.extend((home[0]+math.sin(i*math.pi/4.)*20.,
                   home[1]+math.cos(i*math.pi/4.)*20.) for i in range(8))
    for route in routes:
        points.extend(tuple(p) for p in route.get('waypoints',())
                      if math.hypot(p[0]-home[0],p[1]-home[1])<=40.)
    unique=[]
    for point in points:
        if point not in unique:unique.append(point)
    return [dict(id='player_base_defence' if i==0 else
        'player_base_defence_approach_%s'%i,waypoints=[point])
        for i,point in enumerate(unique)]


FRONT_INTERVAL = 180.
PRESSURE_WINDOW = 45.

# The static class distances match the current battle profile catalogue. They
# are local intent, never a claim that a shot is possible at that distance.
CLASS_RANGES = {'heavyTank': (72., 260.), 'mediumTank': (135., 340.),
                'lightTank': (175., 320.), 'AT-SPG': (255., 450.),
                'SPG': (650., 1250.)}


def target_value(target, name, default=None):
    return target.get(name, default) if isinstance(target, dict) else getattr(target, name, default)


class CombatPolicy(object):
    """Player-owned range intent and a bounded ready-without-shot lease."""
    def __init__(self, tag):
        self.desired_range, self.fire_range = CLASS_RANGES.get(tag, CLASS_RANGES['mediumTank'])
        self.record = None
        self.recovery = None
        self.receipt = {}

    def reset(self):
        self.record = self.recovery = None

    def update(self, state, context, allowed=True):
        now, position = state['now'], state['position']
        target = context.get('target')
        point = target_value(target, 'position')
        identity = target_value(target, 'id')
        span = math.hypot(point[0] - position[0], point[2] - position[2]) if point is not None else None
        hold = bool(allowed and point is not None and context.get('fire_clear') and
                    span <= self.desired_range * 1.15)
        self.receipt = dict(hold=hold, desired_range=self.desired_range,
                            fire_range=self.fire_range, distance=span, phase='idle')
        if not allowed or context.get('empty_ammo'):
            self.reset()
            self.receipt.update(hold=False, reason='mission_owns_movement')
            return False
        if self.recovery is not None:
            if (now < self.recovery['until'] and identity == self.recovery['target'] and
                    point is not None and context.get('fire_seq') == self.recovery['sequence']):
                self.receipt.update(hold=False, phase='recovering',
                                    reason='ready_without_shot', until=self.recovery['until'])
                return False
            self.reset()
        sequence = context.get('fire_seq')
        if (not hold or not context.get('gun_ready') or sequence is None or
                (not context.get('aligned') and context.get('aim_progress'))):
            self.record = None
            self.receipt['phase'] = 'engage' if hold else 'advance'
            return hold
        record = self.record
        moved = record is not None and math.hypot(position[0] - record['position'][0],
                                                  position[2] - record['position'][2]) >= 2.
        if record is None or record['target'] != identity or record['sequence'] != sequence or moved:
            record = dict(target=identity, sequence=sequence, since=now, position=tuple(position))
            self.record = record
        elapsed = now - record['since']
        self.receipt.update(phase='engage', ready_elapsed=elapsed, reason='ready_without_shot')
        if elapsed >= 8.:
            self.recovery = dict(target=identity, point=tuple(point), sequence=sequence,
                                 until=now + 4., goal=None)
            self.receipt.update(hold=False, phase='recovering', until=now + 4.)
            return False
        return True


class Strategy(object):
    def __init__(self):
        self.mode='route'
        self.clear_at=0.
        self.next_front = None
        self.ally_health = {}
        self.recent_losses = []
        self.receipt={}

    def decide(self, now, routes, current, contacts, allies, base, home, engaged=False,
               mission=None, empty_ammo=False):
        # Damage is observed from the player's friendly roster. A route with
        # many idle hulls has no more pressure than an empty route.
        health = {}
        for ally in allies:
            identity = ally['id']
            current_health = max(0., ally['health'])
            health[identity] = current_health
            previous = self.ally_health.get(identity, current_health)
            if current_health < previous and ally['max_health'] > 0:
                self.recent_losses.append((now, ally['position'],
                    (previous - current_health) / ally['max_health']))
        self.ally_health = health
        self.recent_losses = [loss for loss in self.recent_losses
                              if now - loss[0] <= PRESSURE_WINDOW]
        if self.next_front is None:
            self.next_front = now + FRONT_INTERVAL
        check_front = now >= self.next_front
        if check_front:
            self.next_front = now + FRONT_INTERVAL

        if ((mission and mission.get('explicit') and mission.get('status') != 'cancelled') or
                empty_ammo):
            self.receipt = dict(mode='mission_owned', action=(mission or {}).get('action'),
                                reason='empty_ammo_capture' if empty_ammo else 'explicit_command')
            return None

        alarm = bool(base.get('points', 0) > 0 or base.get('invaders', 0) > 0)
        if alarm and home is not None:
            self.clear_at = now + 5.
            self.receipt = dict(mode='defend', points=base.get('points', 0),
                                invaders=base.get('invaders', 0))
            if self.mode != 'defend':
                self.mode = 'defend'
                return defence_routes(home, routes)
            return None
        if self.mode == 'defend':
            if now < self.clear_at:
                return None
            self.mode = 'route'
            self.receipt = dict(mode='rejoin_after_defence')
            return list(routes)
        if not check_front or engaged or current is None or not contacts:
            return None
        scores = dict((route['id'], 0.) for route in routes)
        for unused, position, loss in self.recent_losses:
            if not any(math.hypot(position[0] - enemy['position'][0],
                                  position[2] - enemy['position'][2]) < 150.
                       for enemy in contacts):
                continue
            nearest = min(routes, key=lambda route: lane_distance(position, route)) if routes else None
            if nearest is not None and lane_distance(position, nearest) < 100.:
                scores[nearest['id']] += loss
        if not scores:
            return None
        best = max(routes, key=lambda route: (scores[route['id']], route['id']))
        if (best['id'] == current['id'] or
                scores[best['id']] <= scores.get(current['id'], 0.)):
            return None
        self.receipt = dict(mode='support_observed_front', route=best['id'],
                            scores=scores, next_front=self.next_front)
        return [best]
