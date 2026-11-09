"""Native foreground aim geometry for explicit manual test commands.

This module has no target-selection, navigation or automatic fire policy.
The native source inversion and reach checks are preserved from the reviewed
foreground ABI adapter; the actual gun rotator remains the aiming owner.
"""
from __future__ import division

import math

from .actor_observation import observation

from .. import gun_pitch_limits, shot_geometry
from ..gun_mechanics import _field
from .. import hull_aiming

NATIVE_ANGLE_TOLERANCE = .00001
NATIVE_ANGLES_PER_REQUEST = 12


def _angle(value):
    return (float(value) + math.pi) % (2. * math.pi) - math.pi


def _point(value):
    result = tuple(float(value[i]) for i in range(3))
    if any(math.isnan(v) or math.isinf(v) for v in result):
        raise ValueError('non-finite aiming position')
    return result


def _distance_sq(left, right):
    return sum((left[i] - right[i]) ** 2 for i in range(3))


def _direction(yaw, pitch):
    return (math.sin(yaw) * math.cos(pitch), -math.sin(pitch),
            math.cos(yaw) * math.cos(pitch))


def hydraulic_body(position, body, correction, center_z):
    """Compose the installed local hydraulic pivot with flat native support.

    Adding Euler pitches changes the rotation on rolled ground. This is the
    same local-aim * base transform used by the native foreground provider,
    expressed as a value only; neither matrix provider nor gun is mutated.
    """
    position, body = _point(position), _point(body)
    correction, center_z = float(correction), float(center_z)
    if any(math.isnan(v) or math.isinf(v) for v in (correction, center_z)):
        raise ValueError('invalid hydraulic transform')
    offset = hull_aiming.correction_translation(correction, center_z)
    translated = shot_geometry.transform_vehicle_point(offset, position, *body)
    axes = [shot_geometry.transform_vehicle_vector(
        shot_geometry.transform_vehicle_vector(vector, 0., correction, 0.), *body)
        for vector in ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))]
    right, up, forward = axes
    pitch = math.asin(max(-1., min(1., -forward[1])))
    if abs(math.cos(pitch)) < 1.e-9:
        raise ValueError('singular hydraulic body')
    return translated, (math.atan2(forward[0], forward[2]), pitch,
                        math.atan2(right[1], up[1]))


def hydraulic_reach(descriptor, direction, flat_body, config):
    """One active-mode direction, native pitch stops and hydraulic range.

    The bounded bisection only inverts local angles. It does not sample
    terrain, solve future modes, trace lines or certify a firing permission.
    The caller separately proves any chassis/hydraulic movement it needs.
    """
    local = shot_geometry.inverse_transform_vehicle_vector(direction, *flat_body)
    gun = _field(descriptor, 'gun')

    def at(correction):
        sine, cosine = math.sin(correction), math.cos(correction)
        x, y, z = (local[0], cosine * local[1] + sine * local[2],
                   -sine * local[1] + cosine * local[2])
        yaw, pitch = math.atan2(x, z), -math.atan2(y, math.hypot(x, z))
        low, high = gun_pitch_limits.calc_pitch_limits(yaw, _field(gun, 'pitchLimits'))
        return (hull_aiming.classify_pitch(pitch, low, high, 1.e-8),
                yaw, pitch, (float(low), float(high)))

    if config is None or not config['isAvailable'] or not config['isEnabled']:
        raise ValueError('active hydraulic parameters unavailable')
    neutral = max(config['minimum'], min(config['maximum'], 0.))
    initial = at(neutral)
    correction, result = neutral, initial
    if initial[0]:
        edge = config['minimum'] if initial[0] < 0 else config['maximum']
        result = at(edge)
        if result[0] == initial[0]:
            return dict(reachable=False, reason='hydraulic_pitch_limit',
                        local_yaw=result[1], local_pitch=result[2],
                        pitch_limits=result[3], hydraulic_pitch=edge)
        failed, correction = neutral, edge
        for unused in range(32):
            middle = (failed + correction) * .5
            if at(middle)[0] == initial[0]:
                failed = middle
            else:
                correction = middle
        result = at(correction)
    limits = _field(gun, 'turretYawLimits')
    yaw_ok = limits is None or (float(limits[0]) - NATIVE_ANGLE_TOLERANCE <=
        result[1] <= float(limits[1]) + NATIVE_ANGLE_TOLERANCE)
    return dict(reachable=bool(yaw_ok), needs_hull=not yaw_ok,
        reason='hydraulic_laying' if yaw_ok else 'yaw_limit',
        local_yaw=result[1], local_pitch=result[2], pitch_limits=result[3],
        hydraulic_pitch=correction, hydraulic_speed=config['speed'])


def active_hydraulic_pose(runtime, frame):
    """Read the currently enabled actuator and its actual flat/body pair."""
    owner = runtime.owner
    entity = observation(runtime).source_entity()
    if (entity.typeDescriptor is not frame['descriptor'] or
            getattr(entity, 'siegeState', hull_aiming.DISABLED) != hull_aiming.ENABLED):
        return None
    config = hull_aiming.pitch_params(frame['descriptor'])
    if config is None or not config['isAvailable'] or not config['isEnabled']:
        return None
    flat = observation(runtime).hydraulic_state().get('flat_matrix')
    if flat is None:
        raise ValueError('active hydraulic flat pose unavailable')
    matrix = owner._runtime.math.Matrix(flat)
    position = _point(matrix.translation)
    body = _point((matrix.yaw, matrix.pitch, matrix.roll))
    correction = float(observation(runtime).hydraulic_state()['pitch'])
    mounted, actual = hydraulic_body(position, body, correction, config['centerZ'])
    if (any(abs(mounted[i] - frame['pose'][6][i]) > .0001 for i in range(3)) or
            any(abs(_angle(actual[i] - frame['body'][i])) > NATIVE_ANGLE_TOLERANCE
                for i in range(3))):
        raise ValueError('actual hydraulic body disagrees with native observation')
    return dict(config, position=position, body=body, correction=correction)


def mechanical_reach(descriptor, direction, body_ypr, hydraulic=None):
    """Check the mounted yaw and yaw-dependent pitch envelope in body space."""
    yaw, pitch = shot_geometry.world_direction_to_local_gun_angles(
        direction, *body_ypr)
    gun = _field(descriptor, 'gun')
    limits = _field(gun, 'turretYawLimits')
    # The inverse body transform can leave round-off even at a fixed gun's
    # exact heading. Use the native source solver's precision, not a wider
    # tactical alignment threshold. Artillery retains its existing contract.
    tolerance = (0. if 'SPG' in (_field(_field(descriptor, 'type'), 'tags', ()) or ())
                 else NATIVE_ANGLE_TOLERANCE)
    yaw_ok = (limits is None or
              float(limits[0]) - tolerance <= yaw <= float(limits[1]) + tolerance)
    try:
        minimum, maximum = gun_pitch_limits.calc_pitch_limits(
            yaw, _field(gun, 'pitchLimits'))
    except (TypeError, ValueError, KeyError, IndexError):
        return dict(reachable=False, needs_hull=False,
                    reason='pitch_limits_unavailable', local_yaw=yaw,
                    local_pitch=pitch)
    pitch_ok = minimum - 1.e-5 <= pitch <= maximum + 1.e-5
    result = dict(reachable=bool(yaw_ok and pitch_ok),
                needs_hull=bool(not yaw_ok and pitch_ok),
                reason=('pitch_limit' if not pitch_ok else
                        'yaw_limit' if not yaw_ok else 'reachable'),
                local_yaw=yaw, local_pitch=pitch,
                pitch_limits=(minimum, maximum))
    if pitch_ok or hydraulic is None:
        return result
    # The actuator has a separate chassis pitch. Do not enlarge the native
    # gun's own stops, and do not claim that a theoretically reachable ray
    # is already laid. Only the active local siege descriptor supplies travel.
    projected = hydraulic_reach(descriptor, direction, hydraulic['body'], hydraulic)
    if not projected.get('reachable') and not projected.get('needs_hull'):
        return result
    result.update(reachable=projected['reachable'], needs_hull=projected['needs_hull'],
        needs_hydraulic=True, hydraulic_pitch=projected['hydraulic_pitch'],
        hydraulic_speed=hydraulic['speed'], reason='hydraulic_laying')
    return result



class NativeAimGeometry(object):
    def __init__(self, owner):
        self.owner = owner
        self._angles = NATIVE_ANGLES_PER_REQUEST

    def _own(self, shell_index=None):
        owner = self.owner
        entity = owner._server_entity(owner._server.vehicle_id)
        descriptor = entity.typeDescriptor
        gun = owner._gun_state
        shell_index = gun.shot_index if shell_index is None else shell_index
        shot = gun.shots[shell_index]
        speed = float(_field(shot, 'speed'))
        gravity = abs(float(_field(shot, 'gravity')))
        maximum = float(_field(shot, 'maxDistance'))
        if (speed <= 0. or maximum <= 0. or
                any(math.isnan(v) or math.isinf(v)
                    for v in (speed, gravity, maximum))):
            raise ValueError('missing or invalid mounted shell ballistics')
        origin, unused_direction = owner._mutable_shot_ray()
        matrix = owner._runtime.math.Matrix(owner._local_stabilised_pose())
        hydraulic = None
        try:
            config = hull_aiming.pitch_params(descriptor)
            flat = getattr(owner, '_local_siege_flat_body_matrix', None)
            if (config is not None and config['isAvailable'] and config['isEnabled'] and
                    getattr(entity, 'siegeState', hull_aiming.DISABLED) == hull_aiming.ENABLED and
                    flat is not None):
                base = owner._runtime.math.Matrix(flat)
                hydraulic = dict(config, body=(float(base.yaw), float(base.pitch), float(base.roll)))
        except (AttributeError, TypeError, ValueError):
            pass
        return dict(descriptor=descriptor, shot=shot, origin=_point(origin),
                    speed=speed, gravity=gravity, maximum=maximum,
                    hydraulic=hydraulic,
                    matrix=matrix, body=(float(matrix.yaw), float(matrix.pitch),
                                         float(matrix.roll)),
                    key=(shell_index, id(shot), speed, gravity, maximum,
                         id(_field(descriptor, 'gun'))))

    def _source_point(self, own, point, reach):
        """Invert only the installed getShotAngles contract, then verify it.

        A high ballistic root cannot be requested merely by passing its final
        impact point: the native solver may choose the low root. A short world
        point along the requested launch ray selects its local neighbourhood.
        Bounded angle-error corrections handle the gun pivot/trajectory solve;
        a source is accepted only when that exact native call reproduces the
        desired local yaw and pitch. No rotator state is written here.
        """
        getter = getattr(self.owner._runtime, 'get_shot_angles', None)
        if not callable(getter):
            return None
        rotator = self.owner._avatar.gunRotator
        current = (float(rotator.turretYaw), float(rotator.gunPitch))
        desired = reach['local_yaw'], reach['local_pitch']
        local = [desired[0], desired[1]]
        distance = min(100., max(5., own['speed']*.12))
        source = point
        for attempt in range(6):
            if self._angles <= 0:
                return None
            self._angles -= 1
            try:
                yaw, pitch = getter(own['descriptor'], own['matrix'],
                                    current, self.owner._vector(source))
                errors = (_angle(desired[0]-float(yaw)),
                          desired[1]-float(pitch))
                if any(math.isnan(v) or math.isinf(v) for v in errors):
                    return None
            except (TypeError, ValueError, AttributeError, RuntimeError):
                return None
            if max(abs(v) for v in errors) <= NATIVE_ANGLE_TOLERANCE:
                return source
            # The first query checks the natural target point. Subsequent
            # queries solve a short virtual source in the exact body basis.
            if attempt:
                local[0] = _angle(local[0] + errors[0])
                local[1] = max(-math.pi*.499, min(math.pi*.499,
                                               local[1] + errors[1]))
            world = shot_geometry.transform_vehicle_vector(
                _direction(local[0], local[1]), *own['body'])
            source = tuple(own['origin'][i] + world[i]*distance for i in range(3))
        return None
