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


FRONT_INTERVAL = 12.
PRESSURE_WINDOW = 45.
FRONT_LEASE = 30.

# The static class distances match the current battle profile catalogue. They
# are local intent, never a claim that a shot is possible at that distance.
CLASS_RANGES = {'heavyTank': (72., 260.), 'mediumTank': (135., 340.),
                'lightTank': (175., 320.), 'AT-SPG': (255., 450.),
                'SPG': (650., 1250.)}


def target_value(target, name, default=None):
    return target.get(name, default) if isinstance(target, dict) else getattr(target, name, default)


def local_support(state, context):
    """Count observed friendly combat support, not a shared Bot assignment."""
    target = target_value(context.get('target'), 'position')
    if target is None:
        return 0.
    own, support = state.get('engine_id', state.get('id')), 0.
    seen = set()
    for ally in context.get('allies') or ():
        identity, point = ally.get('id'), ally.get('position')
        if (identity == own or identity in seen or point is None or
                not ally.get('alive', True) or ally.get('health', 1) <= 0 or
                ally.get('class_tag') == 'SPG'):
            continue
        seen.add(identity)
        span = math.hypot(point[0] - target[0], point[2] - target[2])
        if span <= 300.:
            health = max(0., min(1., float(ally.get('health', 1)) /
                max(1., float(ally.get('max_health', 1)))))
            support += health * (1. - .5 * span / 300.)
    return min(2., support)


class CombatPolicy(object):
    """Player-owned range intent and a bounded ready-without-shot lease."""
    def __init__(self, tag):
        self.tag = tag
        self.desired_range, self.fire_range = CLASS_RANGES.get(tag, CLASS_RANGES['mediumTank'])
        self.record = None
        self.recovery = None
        self.receipt = {}
        self.range_target = None
        self.range_mode = 'advance'
        self.range_changed = 0.

    def reset(self):
        self.record = self.recovery = None
        self.range_target = None
        self.range_mode = 'advance'

    def _range(self, state, context, identity, span, allowed):
        support = local_support(state, context)
        clear = bool(allowed and span is not None and context.get('fire_clear') and
                     not context.get('empty_ammo'))
        previous = self.range_mode if identity == self.range_target else 'advance'
        near = self.desired_range * (1.28 if previous == 'engage' else 1.15)
        phase = 'advance'
        if clear and span <= near:
            phase = 'engage'
        elif (clear and span <= self.fire_range and
              self.tag in ('AT-SPG', 'lightTank') and support < .65):
            phase = 'support_hold'
        if (clear and span <= self.fire_range and previous in ('engage', 'support_hold') and
                (context.get('burst_active') or state['now'] - self.range_changed < 2.)):
            phase = previous
        if phase != self.range_mode or identity != self.range_target:
            self.range_changed = state['now']
        self.range_target, self.range_mode = identity, phase
        return phase, support

    def update(self, state, context, allowed=True):
        now, position = state['now'], state['position']
        target = context.get('target')
        point = target_value(target, 'position')
        identity = target_value(target, 'id')
        span = math.hypot(point[0] - position[0], point[2] - position[2]) if point is not None else None
        phase, support = self._range(state, context, identity, span, allowed)
        hold = phase in ('engage', 'support_hold')
        self.receipt = dict(hold=hold, desired_range=self.desired_range,
                            fire_range=self.fire_range, distance=span, phase=phase,
                            support=support, range_changed=self.range_changed)
        if not allowed or context.get('empty_ammo'):
            self.reset()
            self.receipt.update(hold=False, reason='mission_owns_movement')
            return False
        if context.get('pivot_hold'):
            # Preserve the previous recovery clock while the admitted pivot
            # or its stationary point search owns the tracks.
            return hold
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
            self.receipt['phase'] = phase
            return hold
        record = self.record
        moved = record is not None and math.hypot(position[0] - record['position'][0],
                                                  position[2] - record['position'][2]) >= 2.
        if record is None or record['target'] != identity or record['sequence'] != sequence or moved:
            record = dict(target=identity, sequence=sequence, since=now, position=tuple(position))
            self.record = record
        elapsed = now - record['since']
        self.receipt.update(phase=phase, ready_elapsed=elapsed, reason='ready_without_shot')
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
        self.front_until = 0.
        self.pressure_seen = {}
        self.last_observation = None
        self.receipt={}

    def decide(self, now, routes, current, contacts, allies, base, home, engaged=False,
               mission=None, empty_ammo=False, state=None):
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
        if not routes or current is None or not contacts:
            self.pressure_seen.clear()
            self.last_observation = now
            return None
        scores = dict((route['id'], 0.) for route in routes)
        # Visible opponents establish pressure before a teammate must be hit.
        # Healthy nearby allies reduce an already-covered front's deficit;
        # idle hull count by itself never attracts more vehicles to a lane.
        for enemy in contacts:
            if enemy.get('position') is None or not enemy.get('alive', True):
                continue
            nearest = min(routes, key=lambda route: lane_distance(enemy['position'], route))
            if lane_distance(enemy['position'], nearest) > 100.:
                continue
            strength = max(.25, min(1., float(enemy.get('health', 1)) /
                           max(1., float(enemy.get('max_health', 1)))))
            scores[nearest['id']] += .75 + .5 * strength
        for ally in allies:
            if (ally.get('position') is None or not ally.get('alive', True) or
                    ally.get('health', 0) <= 0 or ally.get('class_tag') == 'SPG' or
                    not any(math.hypot(ally['position'][0]-enemy['position'][0],
                        ally['position'][2]-enemy['position'][2]) <= 180. for enemy in contacts)):
                continue
            nearest = min(routes, key=lambda route: lane_distance(ally['position'], route))
            if lane_distance(ally['position'], nearest) < 100.:
                scores[nearest['id']] -= .65 * min(1., float(ally['health']) /
                                                    max(1., float(ally.get('max_health', 1))))
        for unused, position, loss in self.recent_losses:
            if not any(math.hypot(position[0] - enemy['position'][0],
                                  position[2] - enemy['position'][2]) < 150.
                       for enemy in contacts):
                continue
            nearest = min(routes, key=lambda route: lane_distance(position, route)) if routes else None
            if nearest is not None and lane_distance(position, nearest) < 100.:
                scores[nearest['id']] += 3. * loss
        if not scores:
            return None
        continuous = self.last_observation is not None and 0. <= now - self.last_observation <= 5.
        self.last_observation = now
        for identity, score in scores.items():
            if score > .5:
                if not continuous or identity not in self.pressure_seen:
                    self.pressure_seen[identity] = now
            else:
                self.pressure_seen.pop(identity, None)
        if not check_front or engaged or now < self.front_until:
            return None
        best = max(routes, key=lambda route: (scores[route['id']], route['id']))
        if (best['id'] == current['id'] or
                scores[best['id']] <= max(.5, scores.get(current['id'], 0.) + .5) or
                now - self.pressure_seen.get(best['id'], now) < 2.):
            return None
        # A distant route still needs the independent navigator's connected
        # entry proof. This private lease only prevents tactical oscillation;
        # it reserves no Bot slots and sends no team assignment messages.
        self.front_until = now + FRONT_LEASE
        self.receipt = dict(mode='support_observed_front', route=best['id'],
                            scores=scores, next_front=self.next_front,
                            lease_until=self.front_until, source='local_visible_pressure')
        return [best]
