"""Foreground crossing, contact and braking geometry; no actor allocations."""

import math

from .. import tank_collision, vehicle_physics
from .observations import actor_priority


PREDICTION_SECONDS = 1.0
YIELD_SECONDS = 1.5
HEAD_ON_OFFSET = 0.42
HEAD_ON_RETREAT_SECONDS = 6.0
PARKED_JAM_SECONDS = 1.5
PARKED_YIELD_SECONDS = 4.0
PARKED_CONTACT_MARGIN = .15
_EPSILON = 1.0e-9


def _dot(first, second):
    return first[0] * second[0] + first[1] * second[1]


def _cross(first, second):
    return first[0] * second[1] - first[1] * second[0]


def _position(body):
    point = body['position']
    return point[0], point[2]


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
    # The production collision shape ends in lower_y/upper_y, not XZ offsets.
    first_shape, second_shape = first.get('shape'), second.get('shape')
    if first_shape is None or second_shape is None:
        return True
    first_y, second_y = first['position'][1], second['position'][1]
    return tank_collision.vertical_overlap(
        first_y, first_shape, second_y, second_shape, slop=0.0,
        pitch_a=first.get('pitch', 0.0), roll_a=first.get('roll', 0.0),
        pitch_b=second.get('pitch', 0.0), roll_b=second.get('roll', 0.0))


def _dimensions(body):
    shape = body.get('shape')
    return ((shape[1], shape[0]) if shape is not None else
            (body.get('half_length', 3.5), body.get('half_width', 1.7)))


def separation(first, second):
    """Signed observed hull gap, not a manufactured native impact receipt."""
    if not _same_level(first, second):
        return float('inf')
    a, b = _position(first), _position(second)
    first_shape = first.get('shape') or (_dimensions(first)[1], _dimensions(first)[0])
    second_shape = second.get('shape') or (_dimensions(second)[1], _dimensions(second)[0])
    return -tank_collision._obb_overlap(a[0], a[1], first['yaw'], first_shape,
                                       b[0], b[1], second['yaw'], second_shape)[2]


def separating_exit(first, second, normal, sign=None):
    """Choose the separating face or nearer longitudinal end of a side touch.

    The normal must point from the observed peer towards this hull. An end
    choice is only a proposal; the caller still proves its complete sweep.
    """
    forward = _axes(first)[1]
    a, b = _position(first), _position(second)
    alignment = _dot(forward, normal)
    offset = _dot((a[0] - b[0], a[1] - b[1]), forward)
    epsilon = tank_collision.POSITION_SLOP
    value = alignment if abs(alignment) > epsilon else offset
    sign = (1. if value > epsilon else -1.) if sign is None else sign
    remaining = _radius(first, forward) + _radius(second, forward) - sign * offset
    return sign, max(.5, remaining + PARKED_CONTACT_MARGIN * 3.)


def _contact_time(first, second):
    """Intersect exact OBB intervals under their actual relative velocity."""
    first_pos, second_pos = _position(first), _position(second)
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
        return (0, front_distance, actor_priority(body))
    pace = speed if speed > _EPSILON else reference
    return (1, front_distance / pace if pace > _EPSILON else float('inf'),
            actor_priority(body))


def _reference_braking_roster(body, neighbours, throttle):
    speed = _dot(_velocity(body), _axes(body)[1])
    peers = [peer for peer in neighbours
             if peer['id'] != body['id'] and peer.get('alive', True) and
             (body.get('team') is None or peer.get('team') is None or
              peer.get('team') == body.get('team')) and
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
    return speed, sign, position, axis, peers, candidates


def _reference_braking_blocker(body, candidates, position, axis, speed, step,
                               brake_distance):
    # One held control-decision horizon plus a small standstill gap.
    # The brake integral is based on this vehicle's real parameters.
    distance = min(80.0, brake_distance) + abs(speed) * step + 0.12
    horizon = min(1.0, max(step, 2.0 * min(brake_distance, 80.0) /
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
            return peer['id']
        velocity = _velocity(peer)
        predicted = dict(peer, velocity=(velocity[0] * horizon, 0.0,
                                         velocity[1] * horizon))
        if _contact_time(swept, predicted) is not None:
            return peer['id']
    return None


def _begin(first, second, now, held):
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
                   pace if first['id'] == held else 0.0),
          first, first_axis, second),
         (_arrival(second, second_axis, second_speed, gate,
                   pace if second['id'] == held else 0.0),
          second, second_axis, first)), key=lambda value: value[0])
    unused_rank, winner, axis, loser = ranked[0]
    return {'mode': 'yield', 'winner': winner['id'], 'axis': axis,
            'clear_after': _dot(gate, axis) + _radius(winner, axis) +
                           _radius(loser, axis),
            'until': now + YIELD_SECONDS}


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


def traffic_stopping_distance(p, speed, slope_pitch, steering,
                              epsilon=0.02, step=1.0 / 30.0):
    """Integrate the copied coast law to the first stationary pose.

    This returns only the coast distance. The caller separately includes the
    interval for which its previous foreground decision can remain held.
    Advancing with the same nominal 30 Hz semi-implicit step used by copied
    physics gives the actual forward travel remaining after throttle is
    released. A grade which cannot reduce forward speed has no finite
    stopping distance.
    """
    current = float(speed)
    if abs(current) <= epsilon:
        return 0.0
    native_distance = vehicle_physics.native_stopping_distance(
        p, current, float(slope_pitch), bool(steering),
        epsilon, step)
    if native_distance is not None:
        return native_distance
    distance = 0.0
    # Valid #1513 vehicle parameters settle in a few dozen steps.  This is
    # only a finite-number guard for malformed/tuned inputs, not a traffic
    # distance coefficient.
    for unused_step in range(4096):
        following = vehicle_physics.longitudinal_step(
            p, current, 0.0, bool(steering),
            float(slope_pitch), step, False, 0, False)
        if math.isnan(following) or math.isinf(following):
            return float('inf')
        if abs(following) <= epsilon:
            return distance + abs(following) * step
        if abs(following) >= abs(current):
            return float('inf')
        distance += abs(following) * step
        current = following
    return float('inf')
