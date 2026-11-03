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


class Strategy(object):
    def __init__(self):
        self.mode='route'
        self.clear_at=0.
        self.next_front = None
        self.ally_health = {}
        self.recent_losses = []
        self.receipt={}

    def decide(self, now, routes, current, contacts, allies, base, home, engaged=False):
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
