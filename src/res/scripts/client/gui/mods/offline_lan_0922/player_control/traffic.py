"""Player's local vehicle/wreck clearance, using ordinary collision geometry."""
from __future__ import division
import math
from .. import tank_collision


class TurnClearance(object):
    """Keep an admitted long-way pivot instead of undoing it next update."""
    def __init__(self):
        self.sign = 0.
        self.heading = None
        self.advance_origin = None
        self.advance_sign = 1.

    def apply(self, order, yaw, traffic, position=None, clear=None):
        def delta(a,b):
            return (a-b+math.pi) % (2*math.pi)-math.pi
        goal=order.get('driving',{}).get('heading',yaw)
        if (order['recovery_mode'] in ('hold','reverse_clearance','forward_clearance') or
                self.heading is not None and abs(delta(goal,self.heading))>.35):
            self.sign,self.heading,self.advance_origin=0.,None,None
        if self.heading is not None and abs(delta(self.heading,yaw))<.25:
            self.sign,self.heading,self.advance_origin=0.,None,None
        if self.advance_origin is not None and position is not None and math.hypot(
                position[0]-self.advance_origin[0],position[2]-self.advance_origin[2])>=3.:
            self.sign,self.heading,self.advance_origin=0.,None,None
        if self.heading is None:
            turn=order['turn']
            if not turn or traffic.can_turn(turn):
                return
            opposite=-1. if turn>0 else 1.
            if traffic.can_turn(opposite):
                self.sign,self.heading=opposite,goal
            else:
                self.sign,self.heading=(1. if turn>0 else -1.),goal
        # Continue the same pivot across the shortest-angle boundary. Normal
        # measured nonprogress recovery can still request a proved rear exit.
        allowed=traffic.can_turn(self.sign)
        if not allowed and traffic.can_turn(-self.sign):
            # A moving neighbour may release the other side first. A latched
            # preference is not authority to ignore newly proved clearance.
            self.sign = -self.sign
            allowed = True
        if not allowed and position is not None and clear is not None:
            # A parked hull can obstruct pivoting even when the forward swept
            # corridor is open. Create at most three metres of turn space,
            # proving ordinary static and dynamic clearance on every update.
            # Keep a proved escape direction across updates, including a rear
            # exit when the captured Type 62's forward corridor is occupied.
            # Recheck both native world and vehicle sweeps every update.
            directions = (self.advance_sign, -self.advance_sign)
            for sign in directions:
                if clear(yaw if sign > 0 else yaw+math.pi, 4.):
                    if self.advance_origin is None or sign != self.advance_sign:
                        self.advance_origin = tuple(position)
                    self.advance_sign = sign
                    order.update(turn=0., throttle=.45*sign, brake=False,
                        recovery_mode=('vehicle_turn_forward_clearance' if sign > 0
                                       else 'vehicle_turn_reverse_clearance'))
                    return
        order.update(turn=self.sign if allowed else 0.,throttle=0.,brake=not allowed,
                     recovery_mode='vehicle_turn_clearance_latched')


def body(identity, position, yaw, shape, pitch=0., roll=0.):
    return dict(id=identity, kind='player', x=position[0], y=position[1], z=position[2],
                yaw=yaw, pitch=pitch, roll=roll, shape=tuple(shape))


class Traffic(object):
    def __init__(self, current, neighbours):
        self.current = current
        self.neighbours = [body(r['id'],r['position'],r['yaw'],r['collision_shape'],
                               r.get('pitch',0.),r.get('roll',0.)) for r in neighbours]
        self.receipt = {}
        self.blocked_queries = []
        self.peers = dict((r['id'], r) for r in neighbours)

    def sweep(self, heading, reach, living_only=False):
        # A rear translation does not rotate the physical hull by 180 degrees.
        # Preserve front/rear offsets of asymmetric collision footprints.
        hull_heading = heading if math.cos(heading-self.current['yaw']) >= 0 else heading+math.pi
        moving = dict(self.current, yaw=hull_heading)
        hits = []
        peers = [b for b in self.neighbours if not living_only or self.peers[b['id']]['alive']]
        fraction = tank_collision.translation_fraction(moving,
            (math.sin(heading)*reach,math.cos(heading)*reach),peers,contacts=hits)
        return fraction, hits

    def wreck_ahead(self, heading, reach):
        unused, hits = self.sweep(heading, reach)
        if not hits:
            return None
        identity, unused = min(hits, key=lambda item:item[1])
        peer = self.peers[identity]
        return peer if not peer['alive'] else None

    def clear(self, heading, reach):
        fraction, hits = self.sweep(heading, reach)
        self.receipt = dict(fraction=fraction, blockers=[r[0] for r in hits],
                            heading=heading, reach=reach)
        if fraction < .999 and len(self.blocked_queries) < 12:
            self.blocked_queries.append(dict(self.receipt,
                actors=[dict(id=identity, alive=self.peers[identity]['alive'],
                    team=self.peers[identity].get('team'),
                    position=self.peers[identity]['position']) for identity, at in hits]))
        self.receipt['blocked_queries'] = self.blocked_queries
        return fraction >= .999

    def can_turn(self, turn):
        if not turn:
            return True
        b = self.current
        return tank_collision.rotation_fraction((b['x'],b['y'],b['z']),b['yaw'],
            b['yaw']+turn*.15,b['shape'],self.neighbours) >= .999

    def can_steer(self, throttle, turn, speed):
        """Check turning and translation together over the near command horizon."""
        moving = dict(self.current)
        yaw = moving['yaw']
        sign = 1. if throttle > 0. else -1.
        reach = max(1., min(8., abs(speed) * .65 + 1.))
        step = sign * reach / 4.
        for index in range(4):
            new_yaw = yaw + turn * .12
            position = (moving['x'], moving['y'], moving['z'])
            if tank_collision.rotation_fraction(position, yaw, new_yaw,
                    moving['shape'], self.neighbours) < .999:
                return False
            moving['yaw'] = new_yaw
            dx, dz = math.sin(new_yaw) * step, math.cos(new_yaw) * step
            if tank_collision.translation_fraction(moving, (dx, dz), self.neighbours) < .999:
                return False
            moving['x'] += dx
            moving['z'] += dz
            yaw = new_yaw
        return True


class PlayerTraffic(object):
    """Finite traffic and escape leases for the foreground vehicle only."""
    def __init__(self):
        self.pairs = {}
        self.wait = None
        self.escape = None
        self.failures = {}

    def _coordinate(self, order, current, peers, now, traffic, clear):
        from .traffic_laws import _begin, _cleared, _same_level
        identity = current['id']
        allies = dict((peer['id'], peer) for peer in peers if peer['alive'] and
                      peer['team'] == current['team'] and _same_level(current, peer))
        for peer_id in list(self.pairs):
            if peer_id not in allies:
                del self.pairs[peer_id]
        if (not order.get('travel_intent') or order['combat_mode'] not in ('route', 'advance')
                or order['recovery_mode'] != 'travel' or order['throttle'] <= 0.
                or current['speed'] < 0.):
            return
        for peer_id in sorted(allies):
            peer = allies[peer_id]
            first, second = (current, peer) if identity < peer_id else (peer, current)
            lease = self.pairs.get(peer_id)
            if lease is not None and _cleared(lease, first, second):
                del self.pairs[peer_id]
                lease = None
            if lease is None:
                lease = _begin(first, second, now, identity if self.wait is not None else None)
                if lease is None:
                    continue
                self.pairs[peer_id] = lease
            if now >= lease['until']:
                continue
            if lease['mode'] == 'yield':
                if identity != lease['winner']:
                    order.update(throttle=0., turn=0., brake=True, traffic_mode='yield')
                    return
                continue
            heading = lease['targets'][identity]
            delta = (heading - current['yaw'] + math.pi) % (2.*math.pi) - math.pi
            turn = max(-1., min(1., delta / .58))
            if not traffic.can_turn(turn) or not clear(heading):
                order.update(throttle=0., turn=0., brake=True, traffic_mode='head_on_blocked')
                return
            order.update(turn=turn, traffic_mode='head_on')

    @staticmethod
    def _yaw_bucket(yaw):
        return int(math.floor((yaw + math.pi) % (2.*math.pi) * 24. / (2.*math.pi) + .5)) % 24

    def _escape_clear(self, position, heading, distance, now, clear):
        failure = self.failures.get(self._yaw_bucket(heading))
        if failure is not None and now < failure[1] and sum(
                (position[i] - failure[0][i]) ** 2 for i in range(3)) <= .25 ** 2:
            return False
        return clear(heading, distance)

    def _recover(self, order, state, clear, stopping_distance, step, start, failure):
        position, yaw, now = state['position'], state['yaw'], state['now']
        if failure is not None and failure[1] is not None:
            origin, heading = failure
            self.failures[self._yaw_bucket(heading)] = (origin, now + 2.)
        escape = self.escape
        if escape is not None:
            origin, initial_yaw, sign, distance, until = escape
            heading = initial_yaw + (math.pi if sign < 0. else 0.)
            travelled = ((position[0] - origin[0]) * math.sin(heading) +
                         (position[2] - origin[2]) * math.cos(heading))
            remaining = distance - travelled
            delta = (yaw - initial_yaw + math.pi) % (2.*math.pi) - math.pi
            if (remaining <= .05 or now >= until or abs(delta) > .30 or
                    not self._escape_clear(position, heading, remaining, now, clear)):
                self.escape = escape = None
                if now >= until and travelled < .25:
                    # A lease with no progress must not renew the same gear.
                    self.failures[self._yaw_bucket(heading)] = (position, now + 2.)
                if remaining <= .05:
                    order.update(throttle=0., turn=0., brake=True,
                                 recovery_mode='short_escape_complete')
                    return
        if escape is None and start and abs(state['speed']) <= 1.5:
            minimum = max(.5, stopping_distance() + abs(state['speed']) * step)
            for distance in (max(2., minimum), max(1., minimum), minimum):
                for sign in (-1., 1.):
                    heading = yaw + (math.pi if sign < 0. else 0.)
                    if self._escape_clear(position, heading, distance, now, clear):
                        self.escape = (position, yaw, sign, distance, now + 4.)
                        break
                if self.escape is not None:
                    break
        if self.escape is not None:
            sign = self.escape[2]
            order.update(throttle=sign, turn=0., brake=False,
                         recovery_mode='short_reverse_escape' if sign < 0. else 'short_forward_escape')

    def apply(self, order, state, traffic, team, clear, stopping_distance, step,
              stalled, failure):
        from .traffic_laws import _reference_braking_roster, _reference_braking_blocker, YIELD_SECONDS
        yaw, now = state['yaw'], state['now']
        current = dict(traffic.current, team=team, position=state['position'],
            velocity=(math.sin(yaw)*state['speed'], 0., math.cos(yaw)*state['speed']),
            speed=state['speed'])
        peers = []
        for peer in traffic.neighbours:
            observed = traffic.peers[peer['id']]
            peers.append(dict(peer, position=observed['position'],
                team=observed['team'], alive=observed['alive'],
                velocity=observed.get('velocity', (0., 0., 0.))))
        mode = order['recovery_mode']
        if mode in ('hold', 'combat_facing') or order.get('holding'):
            self.escape = self.wait = None
            self.failures.clear()
        else:
            self._coordinate(order, current, peers, now, traffic, clear)
            waited = self.wait is not None and now - self.wait >= YIELD_SECONDS
            waiting = order.get('traffic_mode') in ('yield', 'head_on_blocked')
            if waiting and self.wait is None:
                self.wait = now
            elif not waiting:
                self.wait = None
            if not waiting or waited:
                self._recover(order, state, clear, stopping_distance, step,
                    start=stalled or waited or (
                        mode == 'vehicle_turn_clearance_latched' and order['brake']),
                    failure=failure)
        throttle = order['throttle']
        speed, sign, position, axis, allies, candidates = _reference_braking_roster(
            current, peers, throttle)
        if candidates and abs(throttle) + abs(speed) > .01:
            blocker = _reference_braking_blocker(
                current, candidates, position, axis, speed, step, stopping_distance())
            if blocker is not None and speed * throttle >= -.01:
                order.update(throttle=0., brake=True, traffic_mode='vehicle_brake')
                order['forward_blocked_by' if sign > 0. else 'reverse_blocked_by'] = blocker
        if allies and not traffic.can_turn(order['turn']):
            order.update(turn=0., traffic_mode='vehicle_brake')
