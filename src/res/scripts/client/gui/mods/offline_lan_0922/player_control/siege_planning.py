"""Player-only prospective Siege geometry, never first-trigger permission.

The travel descriptor of a static gun can have zero vertical travel.  Entry
must therefore be checked against the immutable enabled descriptor, including
its hydraulic pivot and the resulting physical gun origin.  A projected ray
is kept outside AttackPolicy's actual-pose proof table.  After entry it can
continue to drive the native aiming actuator while the ordinary attack owner
waits for the *observed* body and barrel to become executable.
"""
from __future__ import division

import math
import time

from .. import ballistics, combat_rules, gun_pitch_limits, shot_geometry, siege_mechanics
from ..gun_mechanics import _field, GunState, mounted_shot_order
from ..vehicle_physics import ground_pose_for_yaw
from .copied import hull_aiming


PRECHECK_CANDIDATES = 2
PRECHECK_WORLD_CHORDS = 12
PRECHECK_WALL_SECONDS = .004
PROJECTION_ITERATIONS = 12
ANGLE_TOLERANCE = .00001
_WALL_CLOCK = getattr(time, 'perf_counter', time.time)


def _number(value):
    if isinstance(value, bool):
        raise ValueError('boolean is not a Siege geometry number')
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise ValueError('non-finite Siege geometry')
    return value


def _point(value):
    return tuple(_number(value[index]) for index in range(3))


def _angle(value):
    return (float(value) + math.pi) % (2. * math.pi) - math.pi


def _direction(yaw, pitch):
    return (math.sin(yaw) * math.cos(pitch), -math.sin(pitch),
            math.cos(yaw) * math.cos(pitch))


def projected_body(position, body, correction, center_z):
    """Compose local hydraulic pitch/pivot with the measured support pose.

    Simply adding two pitch angles is wrong on rolled terrain.  Compose the
    same local aim * base transform as BattleRuntime's native providers, then
    recover its YPR chart for the already reviewed gun-origin helper.
    """
    position, body = _point(position), _point(body)
    correction, center_z = _number(correction), _number(center_z)
    offset = hull_aiming.correction_translation(correction, center_z)
    translated = shot_geometry.transform_vehicle_point(offset, position, *body)
    axes = []
    for vector in ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)):
        tilted = shot_geometry.transform_vehicle_vector(vector, 0., correction, 0.)
        axes.append(shot_geometry.transform_vehicle_vector(tilted, *body))
    right, up, forward = axes
    pitch = math.asin(max(-1., min(1., -forward[1])))
    if abs(math.cos(pitch)) < 1.e-9:
        raise ValueError('singular projected Siege body')
    yaw = math.atan2(forward[0], forward[2])
    roll = math.atan2(right[1], up[1])
    return translated, (yaw, pitch, roll)


def _yaw_limits(descriptor):
    limits = _field(_field(descriptor, 'gun'), 'turretYawLimits')
    if limits is None:
        return -math.pi, math.pi
    low, high = _number(limits[0]), _number(limits[1])
    if low > high or low < -math.pi - ANGLE_TOLERANCE or high > math.pi + ANGLE_TOLERANCE:
        raise ValueError('invalid native Siege yaw limits')
    return low, high


def _pitch_at(descriptor, direction, position, body, correction, center_z):
    # Invert the two rotations directly. Translating the hydraulic pivot is
    # relevant to the ballistic origin, not to this direction-only test.
    # Avoid rebuilding three body axes at every bisection boundary.
    local = shot_geometry.inverse_transform_vehicle_vector(direction, *body)
    sine, cosine = math.sin(correction), math.cos(correction)
    x, y, z = (local[0], cosine * local[1] + sine * local[2],
               -sine * local[1] + cosine * local[2])
    yaw, pitch = math.atan2(x, z), -math.atan2(y, math.hypot(x, z))
    low, high = gun_pitch_limits.calc_pitch_limits(
        yaw, _field(_field(descriptor, 'gun'), 'pitchLimits'))
    return (hull_aiming.classify_pitch(pitch, low, high, 1.e-7),
            yaw, pitch, (float(low), float(high)))


def _correction(descriptor, direction, position, body, config):
    center = config['centerZ'] if config is not None else 0.
    neutral = (max(config['minimum'], min(config['maximum'], 0.))
               if config is not None and config['isAvailable'] and config['isEnabled'] else 0.)
    initial = _pitch_at(descriptor, direction, position, body, neutral, center)
    if initial[0] == 0:
        return neutral, initial, None
    if config is None:
        return neutral, initial, 'hydraulic_parameters_unavailable'
    if not config['isAvailable'] or not config['isEnabled']:
        return neutral, initial, 'siege_pitch_limit'
    edge = config['minimum'] if initial[0] < 0 else config['maximum']
    at_edge = _pitch_at(descriptor, direction, position, body, edge, center)
    if at_edge[0] == initial[0]:
        return edge, at_edge, 'siege_pitch_limit'
    failed, feasible = neutral, edge
    # Only the inexpensive angle transform is bisected; the ballistic lead
    # is solved once per outer iteration, not once per bisection.
    for unused in range(24):
        middle = (failed + feasible) * .5
        status = _pitch_at(descriptor, direction, position, body, middle, center)
        if status[0] == initial[0]:
            failed = middle
        else:
            feasible = middle
    return feasible, _pitch_at(descriptor, direction, position, body, feasible, center), None


def project_solution(descriptor, flat_position, flat_ypr, shot, target_point,
                     target_velocity, allow_hull=True):
    """Project one concrete target point using only installed native data.

    ``ready`` means that the *future* mode can lay this ray.  A required yaw
    rotation still needs the ordinary non-committing body-sweep proof; this
    pure function cannot supply it.  Missing parameters remain ``unknown``.
    """
    try:
        unused_travel, enabled = siege_mechanics.descriptor_pair(descriptor)
        if enabled is None:
            return dict(status='unavailable', reason='vehicle_has_no_siege_mode')
        position, terrain = _point(flat_position), _point(flat_ypr)
        target_point, velocity = _point(target_point), _point(target_velocity)
        speed, gravity, maximum = (_number(_field(shot, name))
                                   for name in ('speed', 'gravity', 'maxDistance'))
        gravity = abs(gravity)
        if speed <= 1. or gravity <= .01 or maximum <= 0.:
            raise ValueError('invalid installed shell ballistics')
        config = hull_aiming.pitch_params(enabled)
        center = config['centerZ'] if config is not None else 0.
        low_yaw, high_yaw = _yaw_limits(enabled)
        correction, hull_yaw, turret_yaw = 0., terrain[0], 0.
        turret_yaw = max(low_yaw, min(high_yaw, turret_yaw))
        previous_origin = None
        for unused in range(PROJECTION_ITERATIONS):
            terrain_pitch, terrain_roll = ground_pose_for_yaw(
                terrain[1], terrain[2], terrain[0], hull_yaw)
            base = (hull_yaw, terrain_pitch, terrain_roll)
            body_position, body = projected_body(position, base, correction, center)
            # #1513 launches from the physical gun pivot, not the barrel tip.
            # Pitch affects its direction but not this descriptor-owned
            # origin; yaw rotates turret.gunPosition and must converge.
            origin, unused_direction = shot_geometry.shot_origin_and_direction(
                enabled, body_position, body[0], body[1], body[2], turret_yaw, 0.)
            solved = ballistics.ballistic_intercept(origin, target_point, velocity, speed, gravity)
            if solved is None or solved[2] * speed > maximum + 1.e-6:
                return dict(status='unreachable', reason='no_reachable_siege_intercept')
            aim, pitch, flight = solved
            yaw = math.atan2(aim[0] - origin[0], aim[2] - origin[2])
            direction = _direction(yaw, pitch)
            next_correction, reach, refusal = _correction(
                enabled, direction, position, base, config)
            local_yaw, local_pitch, limits = reach[1:]
            if refusal is not None:
                # First let a needed yaw change bring the requested direction
                # into the forward hydraulic plane. A side ray cannot be
                # classified against an unturned fixed-gun pitch envelope.
                outside_yaw = (local_yaw < low_yaw - ANGLE_TOLERANCE or
                               local_yaw > high_yaw + ANGLE_TOLERANCE)
                if not outside_yaw or not allow_hull:
                    return dict(status=('unknown' if refusal ==
                        'hydraulic_parameters_unavailable' else 'unreachable'), reason=refusal)
            next_turret = max(low_yaw, min(high_yaw, local_yaw))
            yaw_error = _angle(local_yaw - next_turret)
            next_hull = hull_yaw
            if abs(yaw_error) > 1.e-7:
                if not allow_hull:
                    return dict(status='needs_hull', reason='siege_yaw_limit')
                next_hull = _angle(hull_yaw + yaw_error)
            converged = (previous_origin is not None and
                sum((origin[axis] - previous_origin[axis]) ** 2 for axis in range(3)) < 1.e-12 and
                abs(next_correction - correction) < 1.e-7 and
                abs(_angle(next_hull - hull_yaw)) < 1.e-7 and
                abs(_angle(next_turret - turret_yaw)) < 1.e-7)
            if converged:
                check_yaw, check_pitch = shot_geometry.world_direction_to_local_gun_angles(
                    direction, *body)
                check_low, check_high = gun_pitch_limits.calc_pitch_limits(
                    check_yaw, _field(_field(enabled, 'gun'), 'pitchLimits'))
                if not (low_yaw - ANGLE_TOLERANCE <= check_yaw <= high_yaw + ANGLE_TOLERANCE and
                        check_low - ANGLE_TOLERANCE <= check_pitch <= check_high + ANGLE_TOLERANCE):
                    return dict(status='unknown', reason='siege_projection_unsettled')
                path = ballistics.ballistic_path(origin, yaw, pitch, speed, gravity, flight)
                return dict(status='ready', reason='future_siege_reachable', descriptor=enabled,
                    origin=tuple(origin), direction=direction, point=tuple(aim),
                    aim_position=tuple(aim), source_point=tuple(aim), path=path,
                    yaw=yaw, pitch=pitch, flight_time=flight, velocity=velocity,
                    local_yaw=check_yaw, local_pitch=check_pitch,
                    body=body, position=body_position, flat_body=base,
                    hull_yaw=hull_yaw, hydraulic_pitch=correction, siege_correction=correction,
                    needs_hull=abs(_angle(hull_yaw - terrain[0])) > ANGLE_TOLERANCE,
                    needs_hydraulic=abs(correction) > ANGLE_TOLERANCE,
                    future_reachable=True, reachable=False, source_verified=False,
                    siege_precheck=True)
            previous_origin = origin
            correction, hull_yaw, turret_yaw = next_correction, next_hull, next_turret
        return dict(status='unknown', reason='siege_projection_unsettled')
    except (AttributeError, TypeError, ValueError, KeyError, IndexError,
            RuntimeError, OverflowError, ZeroDivisionError):
        return dict(status='unknown', reason='siege_projection_data_unavailable')


def native_descriptor_pair(runtime, descriptor):
    """Recover the retained composite only for its actually installed member.

    #1513 may expose the active plain child after a mode callback. The paired
    composite already retained by the local actor is authoritative; a random
    same-name descriptor or a pair from an earlier gun is not.
    """
    try:
        pair = siege_mechanics.descriptor_pair(descriptor)
        if pair[1] is not None:
            return descriptor, pair
    except (AttributeError, TypeError, ValueError):
        pass
    retained = getattr(runtime.owner, '_local_descriptor', None)
    pairs = getattr(getattr(runtime, 'engine', None), '_descriptor_pairs', {})
    observed = pairs.get(getattr(runtime, 'actor_id', None))
    candidates = []
    if retained is not None:
        try:
            candidates.append((retained, siege_mechanics.descriptor_pair(retained)))
        except (AttributeError, TypeError, ValueError):
            pass
    if observed is not None and len(observed) == 2 and observed[1] is not None:
        # A projection exposing these exact members is enough for the pure
        # planner; it never mutates this wrapper or either descriptor.
        candidates.append((dict(defaultVehicleDescr=observed[0],
                                siegeVehicleDescr=observed[1], hasSiegeMode=True), observed))
    installed = _field(descriptor, 'gun')
    for composite, pair in candidates:
        if pair[1] is not None and (descriptor is pair[0] or descriptor is pair[1] or
                installed is not None and any(installed is _field(member, 'gun') for member in pair)):
            return composite, pair
    return descriptor, (descriptor, None)


class SiegePrecheck(object):
    """Bounded real line/contact precheck with a private projected frontier."""

    def __init__(self, runtime):
        # Reuse the actual native world/ally/armour observation implementation,
        # not its current-pose policy cache or any worker behaviour owner.
        from .attack_policy import NativeAttackEvaluator
        self.runtime = runtime
        self.evaluator = NativeAttackEvaluator(runtime)
        self.clock = _WALL_CLOCK
        self.reset()

    def reset(self):
        self.evaluator.jobs.clear()
        self.evaluator.predictions.clear()
        self._projections = {}
        self._selected = None
        self._cursor = 0
        self._at = None
        self._used = 0
        self._identity = None
        self._hydraulic_lease = None
        self.receipt = dict(status='idle', reason='no_siege_precheck', candidates=0)

    def status(self):
        return dict(self.receipt)

    def _flat_pose(self, frame):
        owner = self.runtime.owner
        flat = getattr(owner, '_local_siege_flat_body_matrix', None)
        if flat is None:
            # No hydraulic provider is needed for a mode whose mounted gun
            # can reach without correction. A nonzero actual correction must
            # never be silently treated as the uncorrected support pose.
            if abs(float(getattr(owner, '_local_siege_aim_pitch', 0.))) > ANGLE_TOLERANCE:
                raise ValueError('uncorrected local Siege body unavailable')
            flat = owner._local_stabilised_pose()
        matrix = owner._runtime.math.Matrix(flat)
        return _point(matrix.translation), (float(matrix.yaw), float(matrix.pitch), float(matrix.roll))

    def _sample(self, target, sample):
        owner, entity = self.runtime.owner, target['entity']
        samples = shot_geometry.ordered_vehicle_aim_samples(entity.typeDescriptor)
        body = target['matrix']
        pose = dict(position=_point(body.translation), yaw=float(body.yaw),
            pitch=float(body.pitch), roll=float(body.roll), turret_yaw=float(
                owner._runtime.math.Matrix(entity.appearance.turretMatrix).yaw))
        return shot_geometry.vehicle_aim_point(samples[sample], pose)

    def _future_shell(self, frame, enabled):
        from .attack_policy import _shell_signature
        gun = self.runtime.gun
        shots = mounted_shot_order(_field(_field(enabled, 'gun'), 'shots'), gun.shell_order)
        # These are exactly the native mode-adoption slot laws. Matching a
        # shell name or simply taking the travel shot can plan a different
        # mode-specific speed, gravity or mounted slot.
        if GunState._shot_compact_descrs(shots) != GunState._shot_compact_descrs(gun.shots):
            return None
        index = frame['loaded']
        if index < 0 or index >= len(shots) or frame['ammo'][index] <= 0:
            return None
        shot = shots[index]
        return dict(index=index, is_he=combat_rules.is_he(shot),
            piercing=float(combat_rules.range_piercing(shot, 0.)), shot=shot,
            signature=_shell_signature(index, shot))

    def _motion_proof(self, frame, projection, now):
        runtime, source = self.runtime, frame['source']
        destroyed = set((source.get('critical') or {}).get('destroyed') or ())
        if projection['needs_hull']:
            if ('drive' not in runtime.features or source.get('airborne') or source.get('_overturned') or
                    destroyed.intersection(('engineHealth', 'leftTrackHealth', 'rightTrackHealth'))):
                return dict(proved=False, clear=None, reason='siege_hull_actuator_unavailable')
            around_center = _field(_field(projection['descriptor'], 'chassis'), 'rotationIsAroundCenter')
            if around_center is not True:
                # The retained ordinary local probe certifies a stationary
                # centre arc. A track-pivot chassis translates during its
                # real turn; never reuse that receipt as a proof of another
                # muzzle/footprint path. Ordinary actual-pose recovery still
                # owns that manoeuvre and may later expose a current-yaw point.
                return dict(proved=False, clear=None, reason=(
                    'siege_track_pivot_projection_pending' if around_center is False else
                    'siege_rotation_contract_unavailable'))
            probe = getattr(runtime.geometry, '_probe_bot_local_motion', None)
            if not callable(probe):
                return dict(proved=False, clear=None, reason='siege_rotation_proof_unavailable')
            rotation = probe(runtime.actor_id, frame['position'], float(source['yaw']),
                projection['hull_yaw'], None, projection['descriptor'],
                max(.001, float(getattr(runtime.engine, '_local_sweep_step', .001))), now)
            if not isinstance(rotation, dict) or rotation.get('proved') is not True or rotation.get('clear') is not True:
                return rotation or dict(proved=False, clear=None, reason='siege_rotation_proof_unavailable')
        else:
            rotation = dict(proved=True, clear=True, reason='siege_no_hull_rotation')
        observed_correction = float(getattr(runtime.owner, '_local_siege_aim_pitch', 0.))
        hydraulic_movement = abs(projection['hydraulic_pitch'] - observed_correction) > ANGLE_TOLERANCE
        if hydraulic_movement:
            if source.get('_overturned') or 'engineHealth' in destroyed:
                return dict(proved=False, clear=None, reason='siege_hydraulic_actuator_unavailable')
            probe = getattr(runtime.geometry, '_turret_motion_is_clear', None)
            if not callable(probe):
                return dict(proved=False, clear=None, reason='siege_hydraulic_proof_unavailable')
            actual = frame['pose']
            start = dict(x=frame['position'][0], y=frame['position'][1], z=frame['position'][2],
                         yaw=source['yaw'], pitch=source.get('terrain_pitch', source['pitch']),
                         roll=source['roll'])
            end = dict(start, yaw=projection['hull_yaw'],
                       pitch=projection['flat_body'][1], roll=projection['flat_body'][2])
            actual_body_position = actual[6]
            start['hull'] = dict(x=actual_body_position[0], y=actual_body_position[1],
                z=actual_body_position[2], yaw=frame['body'][0],
                pitch=frame['body'][1], roll=frame['body'][2])
            end['hull'] = dict(x=projection['position'][0], y=projection['position'][1],
                z=projection['position'][2], yaw=projection['body'][0],
                pitch=projection['body'][1], roll=projection['body'][2])
            clear = probe(start, end, projection['descriptor'])
            if clear is not True:
                return dict(proved=clear is False, clear=clear, reason='siege_hydraulic_sweep')
        return rotation

    def _projected_frame(self, frame, projection):
        descriptor = projection['descriptor']
        body, origin = projection['body'], projection['origin']
        pose = (frame['position'], body, origin,
                (projection['local_yaw'], projection['local_pitch']),
                id(descriptor), id(_field(descriptor, 'gun')), projection['position'])
        return dict(frame, descriptor=descriptor, body=body, origin=origin, pose=pose,
            planning_pose=pose[1:3] + pose[4:6],
            identity=tuple(frame['identity'][:2]) + (id(_field(descriptor, 'gun')), 'siege_precheck'))

    def _motion_source(self, frame, projection, point, shell):
        """Invert the *flat-body* hydraulic input, not first-edge gun aim.

        The actuator asks the native flat-body solver about its source point.
        Feeding the target's raw coordinate solves from a different pivot
        than the projected tilted body. A zero-travel gun can then remain a
        few native angle units outside reach forever. Resolve a motion-only
        source through that exact native input and verify the requested
        correction; the actual attack proof is still made after motion.
        """
        owner = self.runtime.owner
        correction = projection['hydraulic_pitch']
        observed = float(getattr(owner, '_local_siege_aim_pitch', 0.))
        if abs(correction) <= ANGLE_TOLERANCE and abs(observed) <= ANGLE_TOLERANCE:
            return tuple(point)
        descriptor = projection['descriptor']
        config = hull_aiming.pitch_params(descriptor)
        if config is None or not config['isAvailable'] or not config['isEnabled']:
            return None
        minimum, maximum = hull_aiming.absolute_pitch_limits(descriptor)
        getter = getattr(owner._runtime, 'get_shot_angles', None)
        if not callable(getter):
            return None
        flat_position, unused_flat_body = self._flat_pose(frame)
        body = projection['flat_body']
        matrix = owner._runtime.math.Matrix()
        matrix.setRotateYPR(body)
        matrix.translation = owner._vector(flat_position)
        rotator = owner._avatar.gunRotator
        current = float(rotator.turretYaw), float(rotator.gunPitch)
        yaw, pitch = shot_geometry.world_direction_to_local_gun_angles(
            projection['direction'], *body)
        desired = (yaw, minimum + correction if correction < -ANGLE_TOLERANCE else
                        maximum + correction if correction > ANGLE_TOLERANCE else
                        max(minimum, min(maximum, pitch)))
        local = [desired[0], desired[1]]
        origin = shot_geometry.shot_origin_and_direction(descriptor, flat_position,
            body[0], body[1], body[2], current[0], current[1])[0]
        distance = min(100., max(5., float(_field(shell['shot'], 'speed')) * .12))
        source = tuple(point)
        for attempt in range(6):
            actual = getter(descriptor, matrix, current, owner._vector(source))
            actual = _number(actual[0]), _number(actual[1])
            errors = _angle(desired[0] - actual[0]), desired[1] - actual[1]
            produced, reachable = hull_aiming.minimal_correction(
                actual[1], minimum, maximum, config['minimum'], config['maximum'])
            if reachable and max(abs(errors[0]), abs(errors[1]), abs(produced - correction)) <= 1.e-7:
                return source
            if attempt:
                local[0] = _angle(local[0] + errors[0])
                local[1] += errors[1]
            direction = shot_geometry.transform_vehicle_vector(_direction(*local), *body)
            source = tuple(origin[axis] + direction[axis] * distance for axis in range(3))
        return None

    def hydraulic_point(self, candidate, weapon_point):
        """Read one matched native hydraulic input without replanning a ray.

        A native gun source is inverted in the *actual* body, while hydraulic
        correction consumes a source inverted in the *flat* body. They are
        two inputs for the same target/sample/shot, not competing aim owners.
        Keep the flat input stable during hydraulic progress, but revoke it
        on an actual chassis/target/shell/scene change. The caller separately
        fences automatic native-source ownership and mode/mission lifecycle.
        """
        lease = self._hydraulic_lease
        if lease is None or not isinstance(candidate, dict) or weapon_point is None:
            return None
        try:
            from .attack_policy import native_target_pose
            runtime, owner = self.runtime, self.runtime.owner
            key = candidate.get('shell_index'), candidate.get('target_key'), candidate.get('sample')
            if key != lease['key']:
                return None
            solution = candidate.get('solution') or {}
            saved = lease['row']['solution']
            if (solution.get('sample_value') != saved.get('sample_value') or
                    solution.get('target_pose') != lease['target_pose']):
                return None
            point = _point(weapon_point)
            allowed = (solution.get('point'), solution.get('source_point'))
            if not any(value is not None and point == _point(value) for value in allowed):
                return None
            if (tuple(lease['identity'][:2]) != (owner._generation, id(runtime.gun)) or
                    int(runtime.gun.shot_index) != key[0] or runtime.gun.ammo[key[0]] <= 0):
                return None
            entity = owner._server_entity(owner._server.vehicle_id)
            unused_composite, pair = native_descriptor_pair(runtime, entity.typeDescriptor)
            if pair[1] is not lease['descriptor']:
                return None
            current_shell = self._future_shell(dict(loaded=key[0], ammo=tuple(runtime.gun.ammo)), pair[1])
            if current_shell is None or current_shell['signature'] != lease['shell_signature']:
                return None
            if self._flat_pose(lease['frame']) != lease['flat_pose']:
                return None
            current = next((target for target in runtime.visible_targets()
                if target.get('key', (target.get('kind'), target.get('network_id', target.get('id')))) == key[1]
                and target.get('alive', True)), None)
            if current is None:
                return None
            target = runtime.target_entity(current)
            if target is not lease['entity'] or native_target_pose(owner, target)[0] != lease['target_pose']:
                return None
            velocity = tuple(current.get('velocity') or ())
            if len(velocity) == 3 and _point(velocity) != lease['velocity']:
                return None
            source = runtime.current_source()
            destroyed = set((source.get('critical') or {}).get('destroyed') or ())
            if source.get('airborne') or source.get('_overturned') or 'engineHealth' in destroyed:
                return None
            scene = self.evaluator._scene_stamp()
            if scene != lease['frame']['scene']:
                return None
            live = dict(scene=scene, observed_at=runtime.now)
            self.evaluator._observe_lanes(live)
            if self.evaluator.lane_stamp(live, lease['line_region']) != lease['line_stamp']:
                return None
            return tuple(saved['source_point'])
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return None

    def candidate(self, frame, now, preferred_target=None):
        self.receipt = dict(status='pending', reason='siege_point_pending', candidates=0)
        try:
            if frame is None:
                frame = self.evaluator.snapshot(now)
            if frame.get('artillery') or frame.get('trigger_active'):
                self.receipt.update(status='held', reason='siege_trigger_or_artillery_owner')
                return None
            composite, pair = native_descriptor_pair(self.runtime, frame['descriptor'])
            unused_travel, enabled = pair
            if enabled is None:
                known_mode = (bool(_field(frame['descriptor'], 'hasSiegeMode', False)) or
                              siege_mechanics.params(frame['descriptor']) is not None)
                self.receipt.update(status='pending' if known_mode else 'unavailable',
                    reason='siege_descriptor_pair_unavailable' if known_mode else 'vehicle_has_no_siege_mode')
                return None
            identity = tuple(frame['identity'][:2]) + (id(enabled), id(_field(enabled, 'gun')))
            if identity != self._identity:
                self.reset()
                self._identity = identity
            if self._at != now:
                self._at, self._used = now, 0
                self.evaluator._budgets['siege'] = PRECHECK_WORLD_CHORDS
            position, body = self._flat_pose(frame)
            shell = self._future_shell(frame, enabled)
            if shell is None:
                self.receipt.update(status='pending', reason='siege_loaded_shell_contract_unavailable')
                return None
            jobs = [(target, sample) for target in frame['targets']
                    for sample in target.get('samples') or ()]
            if not jobs:
                self.receipt.update(status='pending', reason='siege_target_geometry_unavailable')
                return None
            valid = set((shell['index'], target['key'], sample) for target, sample in jobs)
            for cache in (self._projections, self.evaluator.jobs, self.evaluator.predictions):
                for key in list(cache):
                    if key not in valid:
                        cache.pop(key, None)
            preferred_key = None
            if isinstance(preferred_target, dict) and preferred_target.get('target_key') is not None:
                preferred_key = (preferred_target.get('shell_index'),
                                 preferred_target['target_key'], preferred_target.get('sample'))
                preferred_target = preferred_target.get('target')
            preferred = ((preferred_target.get('kind'), preferred_target.get('network_id'))
                         if isinstance(preferred_target, dict) else None)
            offset = self._cursor % len(jobs)
            ordered = jobs[offset:] + jobs[:offset]
            if preferred_key is not None:
                ordered.sort(key=lambda item: (shell['index'], item[0]['key'], item[1]) != preferred_key)
            elif self._selected is not None:
                ordered.sort(key=lambda item: (shell['index'], item[0]['key'], item[1]) != self._selected)
            elif preferred is not None:
                ordered.sort(key=lambda item: (item[0]['value'].get('kind'),
                    item[0]['value'].get('network_id')) != preferred)
            deadline = self.clock() + PRECHECK_WALL_SECONDS
            for target, sample in ordered:
                if self._used >= PRECHECK_CANDIDATES or self.clock() >= deadline:
                    break
                self._used += 1
                self.receipt['candidates'] = self._used
                key = shell['index'], target['key'], sample
                stamp = (identity, position, body, shell['signature'],
                         target['pose'], target.get('velocity'))
                previous = self._projections.get(key)
                if previous is not None and previous[0] == stamp:
                    projection = previous[1]
                else:
                    projection = project_solution(composite, position, body,
                        shell['shot'], self._sample(target, sample), target['velocity'])
                    self._projections[key] = stamp, projection
                self._cursor = (jobs.index((target, sample)) + 1) % len(jobs)
                if projection.get('status') != 'ready':
                    self.receipt.update(status=projection['status'], reason=projection['reason'])
                    continue
                motion = self._motion_proof(frame, projection, now)
                if motion.get('proved') is not True or motion.get('clear') is not True:
                    self.receipt.update(status=('blocked' if motion.get('proved') is True else 'pending'),
                        reason=motion.get('reason', 'siege_motion_pending'))
                    continue
                projected = self._projected_frame(frame, projection)
                row = self.evaluator.evaluate(projected, shell, target, sample, 'penetration', now, 'siege')
                if (row.get('line') != 'clear' or row.get('mechanical') != 'reachable' or
                        row.get('armor') not in ('passed', 'failed')):
                    self.receipt.update(status='pending', reason=row.get('reason', 'siege_line_pending'))
                    continue
                solution = dict(row['solution'])
                motion_source = self._motion_source(frame, projection, solution['point'], shell)
                if motion_source is None:
                    self.receipt.update(status='pending', reason='siege_native_motion_source_pending')
                    continue
                if not self.evaluator.fence(frame):
                    self.receipt.update(status='pending', reason='siege_observation_changed')
                    return None
                for name in ('hull_yaw', 'hydraulic_pitch', 'siege_correction',
                             'needs_hull', 'needs_hydraulic'):
                    solution[name] = projection[name]
                solution['needs_hydraulic'] = abs(projection['hydraulic_pitch'] - float(
                    getattr(self.runtime.owner, '_local_siege_aim_pitch', 0.))) > ANGLE_TOLERANCE
                solution.update(projected_body=projection['body'],
                    projected_position=projection['position'], future_reachable=True,
                    reachable=False, source_verified=False, siege_precheck=True)
                solution['source_point'] = tuple(motion_source)
                result = dict(row, key=key + ('siege_precheck',), target=target['value'],
                    target_key=target['key'], shell_index=shell['index'], sample=sample,
                    mode='siege_precheck', mechanical='siege_projected', solution=solution,
                    observed_at=now, source_identity=frame['identity'], source_pose=frame['pose'],
                    target_pose=target['pose'], shell_signature=shell['signature'],
                    motion_proof=dict(motion))
                self._selected = key
                self._hydraulic_lease = dict(key=key, row=result, identity=frame['identity'],
                    descriptor=enabled, shell_signature=shell['signature'], frame=frame,
                    flat_pose=(position, body), entity=target['entity'], target_pose=target['pose'],
                    velocity=target['velocity'], line_region=row['line_region'],
                    line_stamp=self.evaluator.lane_stamp(projected, row['line_region']))
                self.receipt.update(status='ready', reason='future_siege_point_verified',
                    target=target['key'], sample=sample, shell=shell['index'],
                    needs_hull=projection['needs_hull'], needs_hydraulic=solution['needs_hydraulic'])
                return result
            return None
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            self.receipt.update(status='pending', reason='siege_native_data_unavailable')
            return None
