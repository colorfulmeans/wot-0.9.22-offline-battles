# -*- coding: utf-8 -*-
"""Friendly crossing coordination and a per-slice vehicle braking guard."""

import math
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from gui.mods.offline_lan_0922 import tank_collision


PREDICTION_SECONDS = 1.0
YIELD_SECONDS = 1.5
HEAD_ON_OFFSET = 0.42
# A single bounded backing manoeuvre after both lateral exits are denied.
HEAD_ON_RETREAT_SECONDS = 6.0
# A firing hold may make room for a stalled friendly hull, but only for one
# short, checked manoeuvre per physical blockage. It is not a new route.
PARKED_JAM_SECONDS = 1.5
PARKED_YIELD_SECONDS = 4.0
PARKED_CONTACT_MARGIN = 0.15
ORDER_FRESH_SECONDS = 1.5
_EPSILON = 1.0e-9


def _dot(first, second):
    return first[0] * second[0] + first[1] * second[1]


def _cross(first, second):
    return first[0] * second[1] - first[1] * second[0]


def _position(body):
    point = body['position']
    return point[0], point[2]


def _body_center(body):
    position = _position(body)
    shape = body.get('shape')
    return (tank_collision.shape_center(position[0], position[1], body['yaw'], shape)
            if shape is not None else position)


def _velocity(body):
    value = body.get('velocity', (0.0, 0.0, 0.0))
    return value[0], value[2]


def _axes(body):
    sine, cosine = math.sin(body['yaw']), math.cos(body['yaw'])
    return (cosine, -sine), (sine, cosine)


def _radius(body, axis):
    side, forward = _axes(body)
    shape = body.get('shape')
    width, length = (shape[:2] if shape is not None else
                     (body['half_width'], body['half_length']))
    return abs(_dot(side, axis)) * width + abs(_dot(forward, axis)) * length


def _travel(body):
    velocity = _velocity(body)
    speed = math.hypot(*velocity)
    if speed > _EPSILON:
        return (velocity[0] / speed, velocity[1] / speed), speed
    return _axes(body)[1], 0.0


def _same_level(first, second):
    # Vertical limits are indices 2/3; optional centre offsets are indices 4/5.
    first_shape, second_shape = first.get('shape'), second.get('shape')
    if first_shape is None or second_shape is None:
        return True
    first_y, second_y = first['position'][1], second['position'][1]
    return min(first_y + first_shape[3], second_y + second_shape[3]) > max(
        first_y + first_shape[2], second_y + second_shape[2])


def _separation(first, second):
    """Largest signed gap between the actual hulls on their SAT axes."""
    first_pos, second_pos = _body_center(first), _body_center(second)
    delta = (second_pos[0] - first_pos[0], second_pos[1] - first_pos[1])
    return max(abs(_dot(delta, axis)) - _radius(first, axis) -
               _radius(second, axis) for axis in _axes(first) + _axes(second))


def _dimensions(body):
    shape = body.get('shape')
    return ((shape[1], shape[0]) if shape is not None else
            (body.get('half_length', 3.5), body.get('half_width', 1.7)))


def _contact_time(first, second):
    """Intersect exact OBB intervals under their actual relative velocity."""
    first_pos, second_pos = _body_center(first), _body_center(second)
    first_vel, second_vel = _velocity(first), _velocity(second)
    delta = (second_pos[0] - first_pos[0], second_pos[1] - first_pos[1])
    relative = (second_vel[0] - first_vel[0], second_vel[1] - first_vel[1])
    enter, leave = 0.0, PREDICTION_SECONDS
    for axis in _axes(first) + _axes(second):
        distance, rate = _dot(delta, axis), _dot(relative, axis)
        radius = _radius(first, axis) + _radius(second, axis)
        if abs(rate) <= _EPSILON:
            if abs(distance) >= radius:
                return None
            continue
        start, end = (-radius - distance) / rate, (radius - distance) / rate
        enter, leave = max(enter, min(start, end)), min(leave, max(start, end))
        if enter >= leave:
            return None
    return enter


def _intersection(first, second, first_axis, second_axis):
    denominator = _cross(first_axis, second_axis)
    if abs(denominator) <= _EPSILON:
        return None
    first_pos, second_pos = _position(first), _position(second)
    delta = (second_pos[0] - first_pos[0], second_pos[1] - first_pos[1])
    distance = _cross(delta, second_axis) / denominator
    return (first_pos[0] + first_axis[0] * distance,
            first_pos[1] + first_axis[1] * distance)


def _arrival(body, axis, speed, gate, reference=0.0):
    """Rank one body's arrival at the shared crossing point.

    ``reference`` is the pair's pace, supplied only for a hull this coordinator
    is itself holding. Such a hull has no measured speed while its route intent
    is unchanged, and ranking it as never arriving made it lose every following
    lease it entered, so the hull that already waited kept waiting. Every other
    stationary hull - parked, in cover, or deployed - still ranks as not
    arriving, because nothing says it intends to enter the junction.
    """
    position = _position(body)
    distance = _dot((gate[0] - position[0], gate[1] - position[1]), axis)
    front_distance = distance - _radius(body, axis)
    if front_distance <= 0.0:
        return (0, front_distance, body['id'])
    pace = speed if speed > _EPSILON else reference
    return (1, front_distance / pace if pace > _EPSILON else float('inf'),
            body['id'])


class TrafficCoordinator(object):
    """Coordinate ordinary forward route commands from frozen body snapshots.

    Bodies carry id/team/alive, position, yaw, velocity and actual half_width /
    half_length or the production collision shape. No body is enlarged. The
    returned command never moves an entity or replaces physical collision.
    """

    def __init__(self):
        self._pairs = {}
        self._held = {}
        self._orders = {}
        self._jams = {}
        self._parked = {}
        self._escape_probe = LocalDriver()

    def forget(self, bot_id):
        self._held.pop(bot_id, None)
        self._orders.pop(bot_id, None)
        self._parked.pop(bot_id, None)
        for actor, lease in list(self._parked.items()):
            if lease['requester'] == bot_id:
                del self._parked[actor]
        for pair in list(self._jams):
            if bot_id in pair:
                del self._jams[pair]
        for pair in list(self._pairs):
            if bot_id in pair:
                del self._pairs[pair]

    def _blocks_requester(self, body, peer, order, margin):
        if _separation(body, peer) <= margin:
            return True
        if order.get('forward_blocked_by') == body['id']:
            length, width = _dimensions(peer)
            return self._escape_probe._reverse_blocked_by_vehicle(
                peer['position'], peer['yaw'] + math.pi,
                [body], length, width) is not None
        if order.get('reverse_blocked_by') != body['id']:
            return False
        length, width = _dimensions(peer)
        return self._escape_probe._reverse_blocked_by_vehicle(
            peer['position'], peer['yaw'], [body], length, width) is not None

    def _parked_yield(self, bot_id, body, command, peers, neighbours, now,
                      direction_clear):
        """Ask a parked ally to clear a persistent, observed traffic blockage.

        Only a fresh movement order from another bot can request clearance.
        Nearby parked tanks, players and ordinary passing traffic cannot start
        it. The original hold/target is restored after separation or a fixed
        deadline, which cannot be renewed while the same pair stays wedged.
        """
        parked_hold = (command.get('recovery_mode') == 'arrived' and
                       command.get('combat_mode') not in
                       ('physical_hold', 'nav_wait'))
        route_order = (command.get('combat_mode') in ('route', 'advance') and
                       command.get('recovery_mode') in
                       ('drive', 'avoid', 'blocked', 'reverse_turn',
                        'pivot_recovery', 'forward_escape'))
        # A route tank can itself be the neighbour occupying a proved reverse
        # escape. The driver already waited through its stuck threshold and
        # checked both pivots/forward travel before naming this blocker. Honour
        # that explicit request even when the blocker is also trying to drive.
        # Mere proximity between two route orders must not steal either route.
        requests = set(peer_id for peer_id in peers
                       if peer_id in self._orders and
                       now - self._orders[peer_id][0] <= ORDER_FRESH_SECONDS and
                       (self._orders[peer_id][1].get('reverse_blocked_by') == bot_id or
                        self._orders[peer_id][1].get('forward_blocked_by') == bot_id) and
                       peer_id not in self._parked)
        eligible = (body.get('alive', True) and
                    (parked_hold or
                     (route_order and (requests or bot_id in self._parked))))
        for pair in list(self._jams):
            if pair[0] == bot_id and pair[1] not in peers:
                del self._jams[pair]
        if not eligible:
            self._parked.pop(bot_id, None)
            for pair in list(self._jams):
                if pair[0] == bot_id:
                    del self._jams[pair]
            return None
        lease = self._parked.get(bot_id)
        if lease is not None:
            peer = peers.get(lease['requester'])
            observation = self._orders.get(lease['requester'])
            if (peer is None or observation is None or
                    now - observation[0] > ORDER_FRESH_SECONDS or
                    not observation[1].get('movement_intent', True) or
                    observation[1].get('recovery_mode') in
                    ('arrived', 'nav_wait', 'physical_hold') or
                    not self._blocks_requester(
                        body, peer, observation[1], PARKED_CONTACT_MARGIN * 3.0)):
                self._parked.pop(bot_id, None)
                self._jams.pop((bot_id, lease['requester']), None)
                lease = None
            elif now >= lease['until']:
                # Keep the exhausted episode until the physical blockage ends.
                return None
        if lease is None:
            candidates = []
            for peer_id in sorted(peers):
                peer = peers[peer_id]
                observation = self._orders.get(peer_id)
                pair = (bot_id, peer_id)
                blocked = (observation is not None and
                           now - observation[0] <= ORDER_FRESH_SECONDS and
                           observation[1].get('movement_intent', True) and
                           (parked_hold or peer_id in requests) and
                           observation[1].get('recovery_mode') not in
                           ('arrived', 'nav_wait', 'physical_hold') and
                           math.hypot(*_velocity(body)) <= 0.65 and
                           math.hypot(*_velocity(peer)) <= 0.65 and
                           self._blocks_requester(
                               body, peer, observation[1], PARKED_CONTACT_MARGIN))
                if not blocked:
                    self._jams.pop(pair, None)
                    continue
                since = self._jams.setdefault(pair, now)
                if (not parked_hold and peer_id in requests or
                        now - since >= PARKED_JAM_SECONDS):
                    candidates.append(peer)
            if not candidates:
                return None
            peer = candidates[0]
            length, width = _dimensions(body)
            away = (_position(body)[0] - _position(peer)[0],
                    _position(body)[1] - _position(peer)[1])
            preferred = 1.0 if _dot(away, _axes(body)[1]) >= 0.0 else -1.0
            sign = None
            for candidate in (preferred, -preferred):
                heading = body['yaw'] + (math.pi if candidate < 0.0 else 0.0)
                # Reuse the exact longitudinal hull sweep in either direction;
                # every other tank, including wrecks/enemies, remains a veto.
                if (self._escape_probe._clear(direction_clear, heading, length * 1.6) and
                        self._escape_probe._reverse_blocked_by_vehicle(
                            body['position'], heading + math.pi,
                            neighbours, length, width) is None):
                    sign = candidate
                    break
            if sign is None:
                return None
            lease = {'requester': peer['id'], 'until': now + PARKED_YIELD_SECONDS,
                     'sign': sign, 'origin': _position(body),
                     'distance': length + _radius(peer, _axes(body)[1]) +
                                 PARKED_CONTACT_MARGIN * 3.0}
            self._parked[bot_id] = lease
        displacement = math.hypot(
            _position(body)[0] - lease['origin'][0],
            _position(body)[1] - lease['origin'][1])
        if displacement >= lease['distance']:
            lease['until'] = now
            return None
        length, width = _dimensions(body)
        heading = body['yaw'] + (math.pi if lease['sign'] < 0.0 else 0.0)
        clear = (self._escape_probe._clear(direction_clear, heading, length * 1.6) and
                 self._escape_probe._reverse_blocked_by_vehicle(
                     body['position'], heading + math.pi,
                     neighbours, length, width) is None)
        result = dict(command)
        result.update(throttle=0.65 * lease['sign'] if clear else 0.0,
                      turn=0.0, target_yaw=body['yaw'], movement_intent=True,
                      recovery_mode='friendly_yield', traffic_mode='friendly_yield',
                      fire_allowed=False)
        return result

    def safe_controls(self, body, command, neighbours, now, stopping_distance,
                      step=1.0 / 30.0):
        """Release drive into occupied hulls after planning and gun aiming.

        This guard is independent of friendly leases and tactical modes. In
        particular a player does not have to publish a cooperative Bot order.
        It changes controls only: momentum, contact mass and player pushing
        remain owned by physics. Re-evaluate even when a decision is cached.
        """
        result = dict(command)
        speed = _dot(_velocity(body), _axes(body)[1])
        throttle, turn = result.get('throttle', 0.0), result.get('turn', 0.0)
        peers = [peer for peer in neighbours
                 if peer['id'] != body['id'] and peer.get('alive', True) and
                 _same_level(body, peer)]
        # Braking against current travel must remain available. At rest the
        # intended gear determines which hull face needs a clear corridor.
        sign = -1.0 if throttle < -0.01 or (
            abs(throttle) <= 0.01 and speed < 0.0) else 1.0
        forward = _axes(body)[1]
        axis = forward[0] * sign, forward[1] * sign
        position = _position(body)
        candidates = []
        for peer in peers:
            delta = (_position(peer)[0] - position[0],
                     _position(peer)[1] - position[1])
            if _dot(delta, axis) <= 0.0:
                continue  # Do not brake a leader because of a rear follower.
            reach = sum(_dimensions(body)) + sum(_dimensions(peer))
            if math.hypot(*delta) > reach + max(2.0, speed * speed):
                continue
            candidates.append(peer)
        blocker = None
        if candidates and (abs(throttle) > 0.01 or abs(speed) > 0.01):
            coast = max(0.0, stopping_distance())
            # One integration slice of reaction plus a small standstill gap.
            # The coast integral is based on this vehicle's real parameters.
            distance = min(80.0, coast) + abs(speed) * step + 0.12
            horizon = min(1.0, max(step, 2.0 * min(coast, 80.0) /
                                    max(abs(speed), 0.1)))
            swept = dict(body, velocity=(axis[0] * distance, 0.0,
                                         axis[1] * distance))
            for peer in candidates:
                own_shape = body.get('shape') or (
                    body['half_width'], body['half_length'])
                peer_shape = peer.get('shape') or (
                    peer['half_width'], peer['half_length'])
                contact = tank_collision._obb_overlap(
                    position[0], position[1], body['yaw'], own_shape,
                    _position(peer)[0], _position(peer)[1], peer['yaw'], peer_shape)
                if contact[2] >= -1.0e-9:
                    if _dot(axis, contact[:2]) >= -1.0e-9:
                        continue  # Existing side contact can slide or separate.
                    blocker = peer['id']
                    break
                velocity = _velocity(peer)
                predicted = dict(peer, velocity=(velocity[0] * horizon, 0.0,
                                                 velocity[1] * horizon))
                if _contact_time(swept, predicted) is not None:
                    blocker = peer['id']
                    break
        if blocker is not None and speed * throttle >= -0.01:
            result.update(throttle=0.0, traffic_mode='vehicle_brake')
            result['forward_blocked_by' if sign > 0.0 else
                   'reverse_blocked_by'] = blocker
        if abs(turn) > 0.01 and peers:
            shape = body.get('shape') or (
                body['half_width'], body['half_length'], -0.8, 2.0)
            steer_sign = -1.0 if result['throttle'] < 0.0 else 1.0
            if tank_collision.rotation_fraction(
                    body['position'], body['yaw'],
                    body['yaw'] + turn * steer_sign * max(step, 0.1),
                    shape, peers) < 1.0:
                result.update(turn=0.0, traffic_mode='vehicle_brake')
        # A stopped follower can request clearance before physical contact.
        # Preserve raw movement intent so the driver's stuck clock still runs.
        observation = self._orders.get(body['id'])
        if observation is not None:
            order = dict(observation[1])
            order.pop('forward_blocked_by', None)
            if blocker is not None and sign > 0.0:
                order['forward_blocked_by'] = blocker
            self._orders[body['id']] = (now, order)
        return result

    def _holding(self, body, now):
        """Report whether this coordinator is the reason a hull is stopped."""
        since = self._held.get(body['id'])
        return since is not None and now - since <= YIELD_SECONDS

    def _begin(self, first, second, now):
        # A neighbour reversing out of a blockage is not an oncoming route
        # convoy. Its existing recovery and physical contacts retain control.
        if any(_dot(_velocity(body), _axes(body)[1]) < -_EPSILON
               for body in (first, second)):
            return None
        first_axis, first_speed = _travel(first)
        second_axis, second_speed = _travel(second)
        alignment = _dot(first_axis, second_axis)
        # Same-direction neighbours can follow or touch without being diverted.
        if alignment >= math.cos(0.35):
            return None
        contact_time = _contact_time(first, second)
        if alignment <= -math.cos(0.60):
            first_pos, second_pos = _position(first), _position(second)
            delta = (second_pos[0] - first_pos[0], second_pos[1] - first_pos[1])
            ahead = _dot(delta, first_axis)
            second_ahead = -_dot(delta, second_axis)
            side = (first_axis[1], -first_axis[0])
            lateral = abs(_dot(delta, side))
            width = _radius(first, side) + _radius(second, side)
            gap = ahead - _radius(first, first_axis) - _radius(second, first_axis)
            if (ahead <= 0.0 or second_ahead <= 0.0 or lateral >= width or
                    (contact_time is None and gap > width * 0.5)):
                return None
            return {'mode': 'head_on', 'axis': first_axis, 'until': now + YIELD_SECONDS,
                    'targets': {first['id']: first['yaw'] + HEAD_ON_OFFSET,
                                second['id']: second['yaw'] + HEAD_ON_OFFSET}}
        if contact_time is None:
            return None
        gate = _intersection(first, second, first_axis, second_axis)
        if gate is None:
            return None
        pace = max(first_speed, second_speed)
        ranked = sorted(
            ((_arrival(first, first_axis, first_speed, gate,
                       pace if self._holding(first, now) else 0.0),
              first, first_axis, second),
             (_arrival(second, second_axis, second_speed, gate,
                       pace if self._holding(second, now) else 0.0),
              second, second_axis, first)), key=lambda value: value[0])
        unused_rank, winner, axis, loser = ranked[0]
        return {'mode': 'yield', 'winner': winner['id'], 'axis': axis,
                'clear_after': _dot(gate, axis) + _radius(winner, axis) +
                               _radius(loser, axis),
                'until': now + YIELD_SECONDS}

    @staticmethod
    def _cleared(lease, first, second):
        if lease['mode'] == 'yield':
            winner = first if first['id'] == lease['winner'] else second
            return _dot(_position(winner), lease['axis']) > lease['clear_after']
        delta = (_position(second)[0] - _position(first)[0],
                 _position(second)[1] - _position(first)[1])
        axis = lease['axis']
        side = (axis[1], -axis[0])
        # Both right-side departures are complete once their real lateral
        # footprints separate, or their centres have passed one another.
        return (_dot(delta, axis) <= 0.0 or
                abs(_dot(delta, side)) >= _radius(first, side) + _radius(second, side))

    def adjust(self, bot_id, body, command, neighbours, now, direction_clear):
        result = dict(command)
        self._orders[bot_id] = (now, dict(command))
        peers = dict((peer['id'], peer) for peer in neighbours
                     if peer['id'] != bot_id and peer.get('alive', True) and
                     peer.get('team') == body.get('team') and _same_level(body, peer))
        parked = self._parked_yield(
            bot_id, body, command, peers, neighbours, now, direction_clear)
        if parked is not None:
            return parked
        retreat_active = any(bot_id in pair and lease['mode'] == 'head_on' and
                             len(lease.get('blocked', ())) == 2 and
                             lease['until'] <= now < lease['until'] + HEAD_ON_RETREAT_SECONDS
                             for pair, lease in self._pairs.items())
        if (not body.get('alive', True) or
                not command.get('movement_intent', True) or
                command.get('combat_mode', 'route') not in ('route', 'advance') or
                (not retreat_active and
                 (command.get('recovery_mode', 'drive') != 'drive' or
                  command.get('throttle', 0.0) <= 0.0 or
                  _dot(_velocity(body), _axes(body)[1]) < -_EPSILON))):
            return result
        for pair in list(self._pairs):
            if bot_id in pair and any(actor != bot_id and actor not in peers
                                     for actor in pair):
                del self._pairs[pair]
        for peer_id in sorted(peers):
            peer = peers[peer_id]
            first, second = (body, peer) if bot_id < peer_id else (peer, body)
            pair = (first['id'], second['id'])
            lease = self._pairs.get(pair)
            if lease is not None and self._cleared(lease, first, second):
                del self._pairs[pair]
                lease = None
            if lease is None:
                lease = self._begin(first, second, now)
                if lease is None:
                    continue
                self._pairs[pair] = lease
            if lease['mode'] == 'yield':
                if bot_id != lease['winner'] and now < lease['until']:
                    result.update(throttle=0.0, turn=0.0, traffic_mode='yield')
                    self._held[bot_id] = now
                continue
            if result.get('traffic_mode') == 'yield':
                continue
            # A frozen avoidance heading cannot own a junction forever.
            # If both exits were denied, allow one bounded backing attempt.
            # Neither deadline renews until this pair physically separates.
            if now >= lease['until']:
                blocked = lease.get('blocked', set())
                if (len(blocked) == 2 and now < lease['until'] + HEAD_ON_RETREAT_SECONDS):
                    # Only one member backs out, so alternating short driver
                    # recoveries cannot make both hulls re-enter the same
                    # narrow passage. This chooses controls, never moves a body.
                    retreating = second['id']
                    target = body['yaw'] + (math.pi if bot_id == retreating else 0.0)
                    length = body.get('half_length', 3.5)
                    width = body.get('half_width', 1.7)
                    clear = self._escape_probe._clear(direction_clear, target, length*1.6)
                    if bot_id == retreating:
                        clear = clear and self._escape_probe._reverse_blocked_by_vehicle(
                            body['position'], body['yaw'], neighbours, length, width) is None
                    if clear:
                        result.update(throttle=-0.72 if bot_id == retreating else 0.72,
                                      turn=0.0, target_yaw=body['yaw'], traffic_mode='head_on_retreat')
                continue
            target = lease['targets'][bot_id]
            try:
                pose_clear = body.get('pose_clear')
                clear = bool(direction_clear(target)) and (
                    pose_clear is None or bool(pose_clear(target)))
            except Exception:
                clear = False
            if not clear:
                lease.setdefault('blocked', set()).add(bot_id)
                # Do not swing into a blocked passage during the finite
                # yield lease. Its deadline above permits checked backing;
                # the second deadline returns ordinary route/recovery control.
                result.update(throttle=0.0, turn=0.0, target_yaw=body['yaw'],
                              traffic_mode='head_on_blocked')
                self._held[bot_id] = now
                continue
            delta = (target - body['yaw'] + math.pi) % (2.0 * math.pi) - math.pi
            result.update(turn=max(-1.0, min(1.0, delta / 0.58)),
                          target_yaw=target, traffic_mode='head_on')
        return result
