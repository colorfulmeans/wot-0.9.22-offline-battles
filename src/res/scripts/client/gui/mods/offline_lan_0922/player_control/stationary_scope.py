"""Conservative per-point exclusions from the player's stationary domain.

An unsuccessful gun pose is not a failed armour test.  In particular, a yaw
turn may change the supporting terrain pose as well as the gun pivot.  This
module never exhausts that continuum by trying a few headings.  It proves
only necessary ballistic bounds, or a whole pitch envelope when native
critical/motion observations establish that the hull cannot currently turn.
Everything else remains a firing-position obligation.
"""
from __future__ import division

import math

from .. import ballistics, gun_pitch_limits, shot_geometry, siege_mechanics
from ..gun_mechanics import _field
from .copied import hull_aiming
from .native_aim import NATIVE_ANGLE_TOLERANCE


_NUMBER_EPSILON = 1.e-6


def _finite(value):
    if isinstance(value, bool):
        raise ValueError('boolean geometry')
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise ValueError('non-finite geometry')
    return value


def _point(value):
    return tuple(_finite(value[index]) for index in range(3))


def _length(value):
    return math.sqrt(sum(component * component for component in value))


def _pending(reason):
    return dict(scope='pending', reason=reason)


def _native_motion(runtime):
    """Read current native dependencies, including repairs after a snapshot."""
    owner = runtime.owner
    source = runtime.current_source()
    critical = source.get('critical')
    records = getattr(owner, '_records', {})
    local_key = getattr(runtime, '_local_record_key', None)
    record = records.get(local_key)
    if record is None:
        record = next((row for row in records.values() if row.get('local')), None)
    if record is not None:
        critical = (record.get('state') or {}).get('critical')
    if not isinstance(critical, dict) or 'destroyed' not in critical:
        raise ValueError('native critical observation is unavailable')
    destroyed = tuple(sorted(str(name) for name in critical['destroyed']))
    airborne = getattr(owner, '_local_airborne')
    if not isinstance(airborne, bool):
        raise ValueError('native support state is unavailable')
    entity = owner._server_entity(owner._server.vehicle_id)
    return (destroyed, airborne, _finite(owner._local_speed),
            _finite(owner._local_turn_speed), _finite(owner._local_vertical_speed),
            int(entity.siegeState))


def _fixed_body(motion):
    return bool(motion is not None and 'engineHealth' in motion[0] and
                not motion[1] and all(abs(value) <= _NUMBER_EPSILON
                                     for value in motion[2:5]) and
                motion[5] not in (siege_mechanics.SWITCHING_ON,
                                  siege_mechanics.SWITCHING_OFF))


def _pair(descriptor):
    travel, siege = siege_mechanics.descriptor_pair(descriptor)
    return (travel,) if siege is None else (travel, siege)


def _pivot_radius(runtime, descriptors, fixed):
    if fixed:
        return 0.
    maximum = 0.
    for descriptor in descriptors:
        chassis = _field(descriptor, 'chassis')
        around = _field(chassis, 'rotationIsAroundCenter')
        physics = _field(descriptor, 'physics')
        if not isinstance(around, bool):
            # This is the actual local actuator's installed law, not a new
            # guessed default for a partial descriptor.
            native = getattr(runtime.owner, '_local_physics', None)
            around = _field(native, 'rotationIsAroundCenter')
            gauge = _field(native, 'trackCenter')
        else:
            gauge = _field(physics, 'trackCenterOffset')
        if not isinstance(around, bool):
            raise ValueError('stationary pivot contract is unavailable')
        if not around:
            gauge = abs(_finite(gauge))
            if gauge <= 0.:
                raise ValueError('stationary pivot width is unavailable')
            # A complete inner-track turn moves the centre through a circle
            # of this diameter. Free centre rotation is a smaller domain.
            maximum = max(maximum, 2. * gauge)
    return maximum


def _origin_radius(runtime, frame, descriptors, fixed):
    """Enclose every installed gun-pivot offset, without inventing a barrel."""
    maximum = 0.
    for descriptor in descriptors:
        chassis, hull, turret = (_field(descriptor, name)
                                 for name in ('chassis', 'hull', 'turret'))
        base = _point(_field(chassis, 'hullPosition'))
        mount = _point(_field(hull, 'turretPositions')[0])
        gun = _point(_field(turret, 'gunPosition'))
        radius = _length(tuple(base[index] + mount[index] for index in range(3)))
        radius += _length(gun)
        hydraulic = hull_aiming.pitch_params(descriptor)
        if hydraulic is not None and hydraulic['isAvailable']:
            # The correction rotates around (0, 0, centerZ).  Twice its
            # radius encloses all correction translations, including mode
            # changes; no UI combinedPitchLimits are used as native travel.
            radius += 2. * abs(hydraulic['centerZ'])
        maximum = max(maximum, radius)
    anchor, actual = _point(frame['position']), _point(frame['origin'])
    pose = frame['pose']
    lay = pose[3]
    model, unused_direction = shot_geometry.shot_origin_and_direction(
        frame['descriptor'], anchor, frame['body'][0], frame['body'][1],
        frame['body'][2], lay[0], lay[1])
    # A measured native pivot/body translation is allowed to differ from
    # the ideal mount. Preserve that observed offset for the whole bound.
    maximum += _length(tuple(actual[index] - model[index] for index in range(3)))
    return maximum + _pivot_radius(runtime, descriptors, fixed)


def _pitch_envelope(descriptor):
    limits = _field(_field(descriptor, 'gun'), 'pitchLimits')
    low = gun_pitch_limits._curve_points(_field(limits, 'minPitch'))
    high = gun_pitch_limits._curve_points(_field(limits, 'maxPitch'))
    for curve in (low, high):
        if (curve[0][0] > 0. or curve[-1][0] < gun_pitch_limits._TWO_PI or
                any(curve[index][0] >= curve[index + 1][0]
                    for index in range(len(curve) - 1))):
            raise ValueError('pitch curves do not bound the whole native yaw domain')
    # Linear interpolation stays inside its node envelope. Using every yaw
    # (even forbidden turret yaw) is a superset, so it cannot falsely exclude
    # a point that a different hull heading makes reachable.
    minimum = min(value for unused_yaw, value in low)
    maximum = max(value for unused_yaw, value in high)
    if minimum > maximum or minimum < -math.pi * .5 or maximum > math.pi * .5:
        raise ValueError('unsupported pitch envelope')
    return minimum - NATIVE_ANGLE_TOLERANCE, maximum + NATIVE_ANGLE_TOLERANCE


def _world_elevation_envelope(frame, descriptors):
    unused_yaw, pitch, roll = (_finite(value) for value in frame['body'])
    tilt = math.acos(max(-1., min(1., math.cos(pitch) * math.cos(roll))))
    minimum, maximum = math.pi * .5, -math.pi * .5
    for descriptor in descriptors:
        low, high = _pitch_envelope(descriptor)
        hydraulic = hull_aiming.pitch_params(descriptor)
        extra = (max(abs(hydraulic['minimum']), abs(hydraulic['maximum']))
                 if hydraulic is not None and hydraulic['isAvailable'] else 0.)
        minimum = min(minimum, -high - tilt - extra)
        maximum = max(maximum, -low + tilt + extra)
    return max(-math.pi * .5, minimum), min(math.pi * .5, maximum)


def _quadratic_minimum(constant, linear, quadratic, low, high):
    values = [constant + linear * time + quadratic * time * time
              for time in (low, high)]
    if quadratic > 0.:
        middle = -linear / (2. * quadratic)
        if low < middle < high:
            values.append(constant + linear * middle + quadratic * middle * middle)
    return min(values)


def current(runtime, frame, proof):
    """A repaired or still-moving hull cannot reuse a fixed-support proof."""
    if (not isinstance(proof, dict) or proof.get('scope') != 'excluded' or
            proof.get('proof_type') not in ('all_pose_ballistic_bound',
                                          'fixed_support_envelope')):
        return False
    if proof.get('source_pose') != frame.get('planning_pose', frame.get('pose')):
        return False
    if proof.get('dependencies') is None:
        return True
    try:
        return proof['dependencies'] == _native_motion(runtime)
    except (AttributeError, TypeError, ValueError, KeyError, IndexError, OverflowError):
        return False


def assess(runtime, frame, shell, target, predicted):
    """Return a sufficient exclusion or an explicit unclosed obligation.

    There are no new collision queries. The caller must keep blocked/pending
    lanes separate, and must still revalidate the actual source before fire.
    A returned exclusion is geometry evidence only; it never says that armour
    was hit or failed. ``source_pose`` is additionally fenced by the policy's
    existing target, ammo and line stamps.
    """
    if not isinstance(predicted, dict):
        return _pending('stationary_prediction_unavailable')
    if (predicted.get('reach') or {}).get('status') == 'reachable':
        return dict(scope='reachable', reason='observed_mechanical_reach')
    try:
        point, velocity = _point(predicted['sample_point']), _point(target['velocity'])
        anchor = _point(frame['position'])
        shot = shell['shot']
        speed, gravity, maximum = (_finite(_field(shot, name))
                                   for name in ('speed', 'gravity', 'maxDistance'))
        gravity = abs(gravity)
        if speed <= 1. or gravity <= .01 or maximum <= 0.:
            return _pending('stationary_ballistics_unavailable')
        try:
            motion = _native_motion(runtime)
        except (AttributeError, TypeError, ValueError, KeyError, IndexError, OverflowError):
            motion = None
        fixed = _fixed_body(motion)
        descriptors = _pair(frame['descriptor'])
        radius = _origin_radius(runtime, frame, descriptors, fixed)
        horizon = min(ballistics.PROJECTILE_MAX_FLIGHT_SECONDS, maximum / speed)
        delta = tuple(point[index] - anchor[index] for index in range(3))
        horizontal = math.hypot(delta[0], delta[2])
        drift = math.hypot(velocity[0], velocity[2])
        closest_at = 0.
        if drift > 0.:
            closest_at = max(0., min(horizon,
                -(delta[0] * velocity[0] + delta[2] * velocity[2]) / (drift * drift)))
        closest = math.hypot(delta[0] + velocity[0] * closest_at,
                             delta[2] + velocity[2] * closest_at)
        proof = dict(scope='excluded', source_pose=frame.get('planning_pose', frame['pose']),
            dependencies=motion if fixed else None, origin_radius=radius, time_limit=horizon,
            target_velocity=velocity, point=point)
        if closest > radius + maximum + _NUMBER_EPSILON:
            proof.update(reason='outside_stationary_horizontal_range',
                         proof_type='all_pose_ballistic_bound', closest_horizontal=closest)
            return proof
        # For an unrestricted heading/support pose, allow *all* elevations.
        # A sampled current ground plane is not a proof for a full hull turn.
        low, high = -math.pi * .5, math.pi * .5
        if fixed:
            low, high = _world_elevation_envelope(frame, descriptors)
        first_time = max(0., (horizontal - radius) / (speed + drift))
        last_time = horizon
        minimum_horizontal_speed = speed * min(math.cos(low), math.cos(high))
        if minimum_horizontal_speed > drift + _NUMBER_EPSILON:
            last_time = min(last_time, (horizontal + radius) /
                            (minimum_horizontal_speed - drift))
        if first_time > last_time + _NUMBER_EPSILON:
            proof.update(reason='outside_stationary_flight_interval',
                         proof_type='fixed_support_envelope' if fixed else 'all_pose_ballistic_bound')
        else:
            above = _quadratic_minimum(delta[1] - radius,
                velocity[1] - speed * math.sin(high), .5 * gravity,
                first_time, last_time)
            below = _quadratic_minimum(-delta[1] - radius,
                speed * math.sin(low) - velocity[1], -.5 * gravity,
                first_time, last_time)
            if max(above, below) <= _NUMBER_EPSILON:
                return _pending('stationary_support_domain_unproved' if not fixed else
                                'stationary_envelope_contains_point')
            proof.update(reason='above_stationary_envelope' if above > _NUMBER_EPSILON else
                         'below_stationary_envelope',
                         proof_type='fixed_support_envelope' if fixed else 'all_pose_ballistic_bound')
        if fixed:
            proof['dependencies'] = motion
        proof.update(elevation_limits=(low, high), flight_interval=(first_time, last_time))
        return proof
    except (AttributeError, TypeError, ValueError, KeyError, IndexError,
            RuntimeError, OverflowError, ZeroDivisionError):
        return _pending('stationary_scope_data_unavailable')
