"""Player's local vehicle/wreck clearance, using ordinary collision geometry."""
from __future__ import division
import math
from .. import tank_collision
from .observations import actor_priority


def protected_hold(order):
    """Explicit task stops must never turn into an unsolicited courtesy move."""
    return bool(order.get('traffic_hold_protected') or
        order.get('recovery_mode') == 'arrival_brake' or
        order.get('combat_mode') in ('physical_hold', 'mission_hold') or
        order.get('parking_phase') in ('waiting', 'recheck', 'queue') or
        order.get('holding') and order.get('mission'))


class TurnClearance(object):
    """Keep an admitted long-way pivot instead of undoing it next update."""
    def __init__(self):
        self.sign = 0.
        self.heading = None
        self.advance_origin = None
        self.advance_sign = 1.

    def apply(self, order, yaw, traffic, position=None, clear=None):
        if protected_hold(order):
            # A previous obstruction's pivot cannot acquire the controls from
            # a newly admitted terminal brake or explicit task stop.
            self.sign, self.heading, self.advance_origin = 0., None, None
            return
        if order.get('cover_motion'):
            # The cover leg owns a fixed gear and a bounded short alignment.
            # A previous route pivot must not add a long-way turn or a forward
            # escape. Refused rotation remains stopped until cover times out.
            self.sign, self.heading, self.advance_origin = 0., None, None
            turn = order['turn'] * (-1. if order['throttle'] < 0. else 1.)
            if turn and not traffic.can_turn(turn):
                order.update(throttle=0., turn=0., brake=True,
                             recovery_mode='cover_turn_blocked')
            return
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
            turn=order['turn'] * (-1. if order['throttle'] < 0. else 1.)
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

    def sweep(self, heading, reach, living_only=False, ignore_ids=()):
        # A rear translation does not rotate the physical hull by 180 degrees.
        # Preserve front/rear offsets of asymmetric collision footprints.
        hull_heading = heading if math.cos(heading-self.current['yaw']) >= 0 else heading+math.pi
        moving = dict(self.current, yaw=hull_heading)
        hits = []
        peers = [b for b in self.neighbours if b['id'] not in ignore_ids and
                 (not living_only or self.peers[b['id']]['alive'])]
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

    def can_turn(self, turn, ignore_ids=()):
        if not turn:
            return True
        b = self.current
        peers = [peer for peer in self.neighbours if peer['id'] not in ignore_ids]
        return tank_collision.rotation_fraction((b['x'],b['y'],b['z']),b['yaw'],
            b['yaw']+turn*.15,b['shape'],peers) >= .999

    def can_steer(self, throttle, turn, speed, ignore_ids=(), reach=None):
        """Check turning and translation together over the near command horizon."""
        moving = dict(self.current)
        yaw = moving['yaw']
        sign = 1. if throttle > 0. else -1.
        reach = (max(1., min(8., abs(speed) * .65 + 1.)) if reach is None
                 else max(0., float(reach)))
        peers = [peer for peer in self.neighbours if peer['id'] not in ignore_ids]
        step = sign * reach / 4.
        for index in range(4):
            new_yaw = yaw + turn * sign * .12
            position = (moving['x'], moving['y'], moving['z'])
            if tank_collision.rotation_fraction(position, yaw, new_yaw,
                    moving['shape'], peers) < .999:
                return False
            moving['yaw'] = new_yaw
            dx, dz = math.sin(new_yaw) * step, math.cos(new_yaw) * step
            if tank_collision.translation_fraction(moving, (dx, dz), peers) < .999:
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
        self.escape_retry_after = 0.
        self.failures = {}
        self.observations = {}
        self.jams = {}
        self.parked = None
        self.contact_escape = None
        self.contact_memory = None
        self.receipt = {}

    def _finish_pair(self, lease, first, second, peer_id, now, reason, remaining=None):
        from .traffic_laws import HEAD_ON_RETREAT_SECONDS, TRAFFIC_REENTRY_SECONDS
        # A finished encounter is a non-owning memory, not a zero-throttle
        # command. Keep it until a physical departure/reentry, otherwise the
        # same stationary pair would start a fresh lease on the next decision.
        if lease.get('phase') != 'finished':
            lease.update(phase='finished', reason=reason, finished_at=now,
                retry_after=now+TRAFFIC_REENTRY_SECONDS, clear_seen=False,
                finished_poses=((tuple(first['position']), first['yaw']),
                                (tuple(second['position']), second['yaw'])))
            lease.setdefault('actors', (actor_priority(first), actor_priority(second)))
            if remaining is not None:
                lease['remaining'] = remaining
        until = lease['until'] + (HEAD_ON_RETREAT_SECONDS if 'retreat' in lease else 0.)
        self.receipt = dict(mode=lease['mode'], phase='finished', peer=peer_id,
            reason=lease['reason'], until=until, exhausted=lease['reason'] == 'deadline',
            retry_after=lease['retry_after'])
        for name in ('priority', 'retreat', 'remaining'):
            if name in lease:
                self.receipt[name] = lease[name]

    @staticmethod
    def _pair_departed(lease, first, second, candidate):
        from .traffic_laws import _cleared
        if _cleared(lease, first, second):
            return True
        if candidate is not None:
            return False
        # A reversed speed sample or sub-centimetre native-pose jitter alone
        # is not a new encounter. The previously conflicting geometry must
        # have changed while the pair is outside the admission envelope.
        for actor, previous in zip((first, second), lease['finished_poses']):
            position, yaw = previous
            moved = math.hypot(actor['position'][0]-position[0],
                               actor['position'][2]-position[2])
            turned = abs((actor['yaw']-yaw+math.pi) % (2.*math.pi)-math.pi)
            if moved >= .5 or turned >= .35:
                return True
        return False

    def _coordinate(self, order, current, peers, now, traffic, clear):
        from .traffic_laws import _begin, _cleared, _same_level, HEAD_ON_RETREAT_SECONDS
        identity = current['id']
        allies = dict((peer['id'], peer) for peer in peers if peer['alive'] and
                      peer['team'] == current['team'] and _same_level(current, peer))
        for peer_id in list(self.pairs):
            if peer_id not in allies:
                del self.pairs[peer_id]
        if not order.get('travel_intent') or current['speed'] < -.05:
            # An existing backing lease still owns its already-admitted exit.
            if not any(row.get('retreat') == identity and row.get('phase') != 'finished'
                       for row in self.pairs.values()):
                return False
        # Local vehicle clearance runs before coordination. A proved obstacle
        # may already have reduced the raw driving command to zero; requiring
        # positive throttle here would make the very jam we coordinate
        # unreachable from the real driver.
        may_begin = (order.get('travel_intent') and order['throttle'] >= 0. and
                     current['speed'] >= -.05 and order['recovery_mode'] not in
                     ('hold', 'arrival_brake', 'reverse_clearance',
                      'short_reverse_escape', 'contact_escape',
                      'vehicle_turn_reverse_clearance'))
        for peer_id in sorted(allies, key=lambda key:actor_priority(allies[key])):
            peer = allies[peer_id]
            first, second = ((current, peer) if actor_priority(current) < actor_priority(peer)
                             else (peer, current))
            lease = self.pairs.get(peer_id)
            actors = (actor_priority(first), actor_priority(second))
            if lease is not None and lease.get('actors', actors) != actors:
                # Native handles can be reused; a different public actor must
                # not inherit another actor's active or spent encounter.
                del self.pairs[peer_id]
                lease = None
            if lease is not None and lease.get('phase') == 'finished':
                candidate = _begin(first, second, now, None)
                if self._pair_departed(lease, first, second, candidate):
                    lease['clear_seen'] = True
                if not lease['clear_seen'] or now < lease['retry_after']:
                    self._finish_pair(lease, first, second, peer_id, now, lease['reason'])
                    continue
                del self.pairs[peer_id]
                lease = None
            if lease is not None and _cleared(lease, first, second):
                del self.pairs[peer_id]
                lease = None
            if lease is None:
                if not may_begin:
                    continue
                lease = _begin(first, second, now, identity if self.wait is not None else None)
                if lease is None:
                    continue
                self.pairs[peer_id] = lease
            lease.setdefault('actors', actors)
            if lease['mode'] == 'yield':
                if now < lease['until'] and identity != lease['winner']:
                    order.update(throttle=0., turn=0., brake=True, traffic_mode='yield')
                    self.receipt = dict(mode='yield', phase='active', peer=peer_id,
                                        winner=lease['winner'], until=lease['until'])
                    return True
                if now >= lease['until']:
                    self._finish_pair(lease, first, second, peer_id, now, 'deadline')
                continue
            if now >= lease['until']:
                until = lease['until'] + HEAD_ON_RETREAT_SECONDS
                if now >= until:
                    remaining = None
                    if 'origin' in lease:
                        remaining = max(2., current['shape'][1]*3.2)-math.hypot(
                            current['position'][0]-lease['origin'][0],
                            current['position'][2]-lease['origin'][2])
                    self._finish_pair(lease, first, second, peer_id, now, 'deadline',
                                      remaining=remaining)
                    continue
                # Both visible clients independently derive the same roles
                # from public actor identities. No Bot queue or peer order is
                # read. A stopped peer plus our rejected lateral sweep is the
                # local evidence of this encounter's blocked sidestep.
                peer_speed = math.hypot(peer['velocity'][0], peer['velocity'][2])
                if lease.get('blocked') and peer_speed <= .65:
                    lease.setdefault('priority', first['id'])
                    lease.setdefault('retreat', second['id'])
                    lease.setdefault('origin', tuple(current['position']))
                if 'retreat' not in lease:
                    if not lease.get('blocked'):
                        self._finish_pair(lease, first, second, peer_id, now, 'sidestep_complete')
                    continue
                sign = -1. if identity == lease['retreat'] else 1.
                heading = current['yaw'] + (math.pi if sign < 0. else 0.)
                maximum = max(2., current['shape'][1] * 3.2)
                travelled = math.hypot(current['position'][0]-lease['origin'][0],
                                       current['position'][2]-lease['origin'][2])
                remaining = maximum-travelled
                if remaining <= .1:
                    self._finish_pair(lease, first, second, peer_id, now,
                                      'distance_complete', remaining=remaining)
                    continue
                allowed = clear(heading, remaining)
                order.update(throttle=.7*sign if allowed else 0., turn=0.,
                    brake=not allowed, traffic_mode='head_on_retreat',
                    recovery_mode='head_on_retreat', suppress_fire=True,
                    fire_allowed=False)
                self.receipt = dict(mode='head_on_retreat', peer=peer_id,
                    phase='active' if allowed else 'blocked',
                    priority=lease['priority'], retreat=lease['retreat'], until=until,
                    exhausted=now >= until, remaining=remaining)
                return True
            heading = lease['targets'][identity]
            delta = (heading - current['yaw'] + math.pi) % (2.*math.pi) - math.pi
            turn = max(-1., min(1., delta / .58))
            if not traffic.can_turn(turn) or not clear(heading):
                lease['blocked'] = True
                order.update(throttle=0., turn=0., brake=True, traffic_mode='head_on_blocked')
                self.receipt = dict(mode='head_on', phase='blocked', peer=peer_id,
                                    until=lease['until'])
                return True
            order.update(turn=turn, traffic_mode='head_on')
            self.receipt = dict(mode='head_on', phase='active', peer=peer_id,
                                until=lease['until'])
            return True
        return False

    def _observe(self, peers, now):
        identities = set(peer['id'] for peer in peers)
        for peer_id in list(self.observations):
            if peer_id not in identities:
                self.observations.pop(peer_id, None)
                self.jams.pop(peer_id, None)
        for peer in peers:
            velocity = peer['velocity']
            magnitude = math.hypot(velocity[0], velocity[2])
            old = self.observations.get(peer['id'], {})
            if magnitude > .2:
                old.update(axis=(velocity[0]/magnitude, velocity[2]/magnitude),
                           moving_at=now)
            intent = peer.get('movement_intent', peer.get('throttle', 0.))
            if isinstance(intent, (int, float)) and abs(intent) > .01:
                sign = 1. if intent > 0. else -1.
                old.update(axis=(math.sin(peer['yaw'])*sign, math.cos(peer['yaw'])*sign),
                           moving_at=now)
            old.update(speed=magnitude, position=tuple(peer['position']))
            self.observations[peer['id']] = old

    def _parked_yield(self, order, current, peers, now, clear):
        from .traffic_laws import (_axes, _dot, _radius, _same_level, separation,
            PARKED_JAM_SECONDS, PARKED_YIELD_SECONDS, PARKED_CONTACT_MARGIN)
        by_id = dict((peer['id'], peer) for peer in peers)
        lease = self.parked
        if lease is not None:
            peer = by_id.get(lease['peer'])
            if peer is None or not peer['alive'] or separation(current, peer) > 1.:
                self.parked = lease = None
        for peer_id in list(self.jams):
            peer = by_id.get(peer_id)
            if peer is None or separation(current, peer) > 1.:
                self.jams.pop(peer_id, None)
        parked = (order.get('holding') or order['recovery_mode'] in ('hold', 'combat_facing'))
        if lease is None and parked and abs(current['speed']) <= .65:
            for peer in sorted(peers, key=actor_priority):
                observed = self.observations[peer['id']]
                if (not peer['alive'] or peer['team'] != current['team'] or
                        not _same_level(current, peer) or observed['speed'] > .65):
                    continue
                delta = (current['position'][0]-peer['position'][0],
                         current['position'][2]-peer['position'][2])
                axis = observed.get('axis')
                # Remember an observed approaching peer through its stop; an
                # arbitrary nearby stationary hull does not request a yield.
                if axis is None or now-observed.get('moving_at', -100.) > 4.:
                    continue
                side = axis[1], -axis[0]
                gap = separation(current, peer)
                blocked_by_us = (peer.get('forward_blocked_by') == current['id'] or
                                 peer.get('reverse_blocked_by') == current['id'])
                if (_dot(delta, axis) <= 0. or
                        abs(_dot(delta, side)) >= _radius(current, side)+_radius(peer, side) or
                        not blocked_by_us and gap > 3.*PARKED_CONTACT_MARGIN):
                    continue
                jam = self.jams.setdefault(peer['id'], dict(since=now, spent=False))
                if jam['spent'] or now-jam['since'] < PARKED_JAM_SECONDS:
                    continue
                forward = _axes(current)[1]
                preferred = 1. if _dot(delta, forward) >= 0. else -1.
                distance = _radius(current, axis)+_radius(peer, axis)+3.*PARKED_CONTACT_MARGIN
                for sign in (preferred, -preferred):
                    heading = current['yaw']+(math.pi if sign < 0. else 0.)
                    if not clear(heading, distance):
                        continue
                    lease = dict(peer=peer['id'], origin=tuple(current['position']),
                        yaw=current['yaw'], sign=sign, distance=distance,
                        until=now+PARKED_YIELD_SECONDS)
                    self.parked = lease
                    jam['spent'] = True
                    break
                if lease is not None:
                    break
        if lease is None:
            return False
        heading = lease['yaw']+(math.pi if lease['sign'] < 0. else 0.)
        progress = ((current['position'][0]-lease['origin'][0])*math.sin(heading)+
                    (current['position'][2]-lease['origin'][2])*math.cos(heading))
        remaining = lease['distance']-progress
        if now >= lease['until'] or remaining <= .05:
            self.parked = None
            self.receipt.update(mode='friendly_yield', phase='finished', peer=lease['peer'])
            return False
        delta = (current['yaw']-lease['yaw']+math.pi) % (2.*math.pi)-math.pi
        allowed = abs(delta) <= .3 and clear(heading, remaining)
        order.update(throttle=.7*lease['sign'] if allowed else 0., turn=0., brake=not allowed,
            holding=False, recovery_mode='friendly_yield', traffic_mode='friendly_yield',
            suppress_fire=True, fire_allowed=False)
        self.receipt.update(mode='friendly_yield', phase='active' if allowed else 'blocked',
            peer=lease['peer'], until=lease['until'], remaining=remaining)
        return True

    def _contact_plan(self, order, state, current, peers, now, clear, contact):
        from .traffic_laws import separation, separating_exit
        position, yaw = state['position'], state['yaw']
        by_id = dict((peer['id'], peer) for peer in peers)
        memory = self.contact_memory
        if memory is not None:
            peer = by_id.get(memory['peer'])
            moved = math.hypot(position[0]-memory['origin'][0], position[2]-memory['origin'][2])
            if (peer is None or moved > 2.*current['shape'][1]+2. or
                    math.hypot(peer['position'][0]-memory['peer_origin'][0],
                               peer['position'][2]-memory['peer_origin'][2]) >= 1.):
                self.contact_memory = memory = None
                self.contact_escape = None
        escape = self.contact_escape
        if escape is not None:
            heading = escape['yaw']+(math.pi if escape['sign'] < 0. else 0.)
            progress = ((position[0]-escape['origin'][0])*math.sin(heading)+
                        (position[2]-escape['origin'][2])*math.cos(heading))
            remaining = escape['distance']-progress
            if progress >= escape['best']+.25:
                escape.update(best=progress, progress_at=now)
            delta = (yaw-escape['yaw']+math.pi) % (2.*math.pi)-math.pi
            peer = by_id.get(escape['peer'])
            reason = ('completed' if remaining <= .05 else
                      'peer_changed' if peer is None or peer['alive'] != escape['alive'] else
                      'heading_changed' if abs(delta) > .3 else
                      'no_progress' if now >= escape['until'] or now-escape['progress_at'] >= 8. else
                      'sweep_withdrawn' if not clear(heading, remaining) else None)
            if reason is not None:
                if memory is not None and reason not in ('completed', 'peer_changed'):
                    memory['failed'].add(self._yaw_bucket(heading))
                    memory['failed_headings'].append(heading)
                    del memory['failed_headings'][:-32]
                    self.failures[self._yaw_bucket(heading)] = (position, now+8.)
                self.contact_escape = escape = None
                self.receipt.update(mode='contact_escape', phase=reason)
                if reason == 'completed':
                    order.update(throttle=0., turn=0., brake=True,
                                 recovery_mode='contact_escape_complete')
                    return True
        if escape is None and isinstance(contact, dict):
            peer = by_id.get(contact.get('peer'))
            normal = contact.get('normal')
            at = contact.get('at')
            valid = (peer is not None and isinstance(normal, (tuple, list)) and
                     len(normal) == 2 and isinstance(at, (int, float)) and
                     0. <= now-at <= max(.25, 2.*state.get('decision_horizon', .1)))
            if valid:
                try:
                    normal = float(normal[0]), float(normal[1])
                    length = math.hypot(*normal)
                    valid = (not math.isnan(length) and not math.isinf(length) and length > .01 and
                             separation(current, peer) <= .5)
                    if valid:
                        normal = normal[0]/length, normal[1]/length
                        valid = ((position[0]-peer['position'][0])*normal[0]+
                                 (position[2]-peer['position'][2])*normal[1]) >= -.05
                except (TypeError, ValueError, OverflowError):
                    valid = False
            if valid:
                if memory is None or memory['peer'] != peer['id']:
                    memory = dict(peer=peer['id'], origin=tuple(position),
                                  peer_origin=tuple(peer['position']), failed=set(), failed_headings=[])
                    self.contact_memory = memory
                preferred, unused_distance = separating_exit(current, peer, normal)
                for sign in (preferred, -preferred):
                    unused_sign, distance = separating_exit(current, peer, normal, sign)
                    heading = yaw+(math.pi if sign < 0. else 0.)
                    if (self._yaw_bucket(heading) in memory['failed'] or
                            not self._escape_clear(position, heading, distance, now, clear)):
                        continue
                    escape = dict(peer=peer['id'], alive=peer['alive'], origin=tuple(position),
                        yaw=yaw, sign=sign, distance=distance, until=now+20.,
                        best=0., progress_at=now)
                    self.contact_escape = escape
                    break
        if escape is None:
            return False
        order.update(throttle=escape['sign'], turn=0., brake=False, holding=False,
            recovery_mode='contact_escape', suppress_fire=True, fire_allowed=False)
        self.receipt.update(mode='contact_escape', phase='active', peer=escape['peer'],
            sign=escape['sign'], until=escape['until'], distance=escape['distance'])
        return True

    @staticmethod
    def _yaw_bucket(yaw):
        return int(math.floor((yaw + math.pi) % (2.*math.pi) * 24. / (2.*math.pi) + .5)) % 24

    def _escape_clear(self, position, heading, distance, now, clear):
        if self.contact_memory is not None:
            if self._yaw_bucket(heading) in self.contact_memory['failed'] or any(
                    abs((heading-failed+math.pi) % (2.*math.pi)-math.pi) <= .35
                    for failed in self.contact_memory['failed_headings']):
                return False
        failure = self.failures.get(self._yaw_bucket(heading))
        if failure is not None and now < failure[1] and sum(
                (position[i] - failure[0][i]) ** 2 for i in range(3)) <= .25 ** 2:
            return False
        return clear(heading, distance)

    def _recover(self, order, state, clear, stopping_distance, step, start, failure):
        from .traffic_laws import TRAFFIC_REENTRY_SECONDS
        position, yaw, now = state['position'], state['yaw'], state['now']
        if isinstance(failure, dict):
            failure = (failure.get('position', position), failure.get('attempted_heading'))
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
                if now >= until:
                    # Expiring one gear and admitting the other in this same
                    # frame can keep a stationary vehicle under recovery's
                    # ownership forever. The driver/replanner gets a finite
                    # unmodified interval before a fresh, fully proved retry.
                    self.escape_retry_after = now+TRAFFIC_REENTRY_SECONDS
                    self.receipt = dict(mode='short_escape', phase='finished',
                        reason='deadline', retry_after=self.escape_retry_after)
        if escape is None and now < self.escape_retry_after:
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
              stalled, failure, contact=None):
        from .traffic_laws import _reference_braking_roster, _reference_braking_blocker, YIELD_SECONDS
        yaw, now = state['yaw'], state['now']
        current = dict(traffic.current, team=team, position=state['position'],
            actor_key=state.get('actor_key'),
            velocity=(math.sin(yaw)*state['speed'], 0., math.cos(yaw)*state['speed']),
            speed=state['speed'])
        peers = []
        for peer in traffic.neighbours:
            observed = traffic.peers[peer['id']]
            peers.append(dict(peer, position=observed['position'],
                actor_key=observed.get('actor_key'),
                team=observed['team'], alive=observed['alive'],
                velocity=observed.get('velocity', (0., 0., 0.)),
                movement_intent=observed.get('movement_intent', observed.get('throttle', 0.)),
                forward_blocked_by=observed.get('forward_blocked_by'),
                reverse_blocked_by=observed.get('reverse_blocked_by')))
        self.receipt = {}
        self._observe(peers, now)
        mode = order['recovery_mode']
        protected = protected_hold(order) or bool(state.get('burst_active'))
        soft_hold = mode in ('hold', 'combat_facing') or order.get('holding')
        if protected or order.get('cover_motion'):
            # Cover already owns its travel deadline. Retire route/traffic
            # translations at this boundary, including leases admitted before
            # the phase began; clearance and physical braking below still run.
            self.escape = self.wait = self.parked = self.contact_escape = None
            by_id = dict((peer['id'], peer) for peer in peers)
            for peer_id, lease in list(self.pairs.items()):
                peer = by_id.get(peer_id)
                if peer is None or not peer['alive'] or peer['team'] != team:
                    self.pairs.pop(peer_id, None)
                    continue
                first, second = ((current, peer) if actor_priority(current) < actor_priority(peer)
                                 else (peer, current))
                self._finish_pair(lease, first, second, peer_id, now, 'control_hold')
        else:
            managed = self._parked_yield(order, current, peers, now, clear)
            if not managed and not soft_hold:
                managed = self._coordinate(order, current, peers, now, traffic, clear)
            if not managed:
                managed = self._contact_plan(order, state, current, peers, now, clear, contact)
            waited = self.wait is not None and now - self.wait >= YIELD_SECONDS
            waiting = order.get('traffic_mode') in ('yield', 'head_on_blocked')
            if waiting and self.wait is None:
                self.wait = now
            elif not waiting:
                self.wait = None
            if not managed and not soft_hold and (not waiting or waited):
                self._recover(order, state, clear, stopping_distance, step,
                    start=stalled or waited or (
                        mode == 'vehicle_turn_clearance_latched' and order['brake']),
                    failure=failure)
            elif soft_hold and not managed:
                self.escape = self.wait = None
        throttle = order['throttle']
        speed, sign, position, axis, allies, candidates = _reference_braking_roster(
            current, peers, throttle)
        if candidates and abs(throttle) + abs(speed) > .01:
            blocker = _reference_braking_blocker(
                current, candidates, position, axis, speed,
                max(step, state.get('decision_horizon', step)), stopping_distance())
            if blocker is not None and speed * throttle >= -.01:
                # Removing reverse throttle reverses a retained steering
                # input's native yaw sign. A brake is not an unchecked pivot.
                order.update(throttle=0., turn=0., brake=True, traffic_mode='vehicle_brake')
                order['forward_blocked_by' if sign > 0. else 'reverse_blocked_by'] = blocker
        physical_turn = order['turn'] * (-1. if order['throttle'] < 0. else 1.)
        if allies and not traffic.can_turn(physical_turn):
            order.update(turn=0., traffic_mode='vehicle_brake')
        if self.receipt:
            order['traffic_control'] = dict(self.receipt)
