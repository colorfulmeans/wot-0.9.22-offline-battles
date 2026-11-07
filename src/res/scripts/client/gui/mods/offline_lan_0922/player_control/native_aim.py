"""Native foreground aim geometry for explicit manual test commands.

This module has no target-selection, navigation or automatic fire policy.
The native source inversion and reach checks are preserved from the reviewed
foreground ABI adapter; the actual gun rotator remains the aiming owner.
"""
from __future__ import division

import math

from .. import gun_pitch_limits, shot_geometry
from ..gun_mechanics import _field
from .copied import hull_aiming

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
    base = hydraulic['body']

    def status(correction):
        local_yaw, local_pitch = shot_geometry.world_direction_to_local_gun_angles(
            direction, base[0], base[1]+correction, base[2])
        low, high = gun_pitch_limits.calc_pitch_limits(
            local_yaw, _field(gun, 'pitchLimits'))
        return hull_aiming.classify_pitch(local_pitch, low, high, 1.e-7)

    neutral = max(hydraulic['minimum'], min(hydraulic['maximum'], 0.))
    initial = status(neutral)
    correction = neutral
    if initial:
        boundary = hydraulic['minimum'] if initial < 0 else hydraulic['maximum']
        if status(boundary) == initial:
            return result
        failed, correction = neutral, boundary
        for unused in range(32):
            middle = (failed+correction)*.5
            if status(middle) == initial:
                failed = middle
            else:
                correction = middle
    result.update(reachable=bool(yaw_ok), needs_hull=bool(not yaw_ok),
        needs_hydraulic=True, hydraulic_pitch=correction,
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
                    bool(_field(descriptor, 'hasSiegeMode', False)) and
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
