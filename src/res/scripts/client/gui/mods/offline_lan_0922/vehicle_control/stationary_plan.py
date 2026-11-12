"""Player-local, motion-only stationary firing-pose plans.

Projected poses never authorize fire. Actual muzzle, geometry and armour
remain the independent first-trigger admission boundary.

This is a sufficient, sampled-native-support planning certificate, not an
exhaustive search of every yaw or a new terrain model.  The original complete
collision arc, peer contact law and arena envelope are retained.  Native
support is independently sampled at the source and at each collision slice's
middle/end.  Unknown or changing support stays pending; it is never an armour
failure.  In particular, an endpoint plane alone cannot certify a rotation.
"""
from __future__ import division

import math

from .actor_observation import observation
from ..native_input_diagnostics import combat_detail, combat_detail_enabled
import time

from .. import arena_boundary, ballistics, shot_geometry, tank_collision, vehicle_physics
from ..gun_mechanics import _field
from .geometry import DESTRUCTIBLE_POSE_MAX_ANGLE_STEP
from .native_aim import (mechanical_reach, NATIVE_ANGLE_TOLERANCE,
                         active_hydraulic_pose, hydraulic_body, hydraulic_reach)
from .stationary_scope import _finite, _native_motion, _point


SLICES_PER_TICK = 4
SUPPORT_SAMPLES_PER_TICK = 12
WALL_SECONDS_PER_TICK = .004
PROJECTION_ITERATIONS = 12
_POSITION_EPSILON = .0001
_PEER_DEPENDENCY = 11
_WALL_CLOCK = getattr(time, 'perf_counter', time.time)


def _angle(value):
    return (float(value) + math.pi) % (2. * math.pi) - math.pi


def _same_point(first, second, tolerance):
    return all(abs(a - b) <= tolerance for a, b in zip(first, second))


def _pending(reason, progressing=False):
    return dict(status='pending', proved=False, reason=reason,
                progressing=bool(progressing))


def _box(value):
    low, high = _point(value[0]), _point(value[1])
    if any(low[axis] >= high[axis] for axis in range(3)):
        raise ValueError('native body box is unavailable')
    return low, high


def _pivot(descriptor, runtime):
    around = _field(_field(descriptor, 'chassis'), 'rotationIsAroundCenter')
    if isinstance(around, bool):
        if around:
            return dict(rotationIsAroundCenter=True)
        params = vehicle_physics.track_pivot_descriptor_params(descriptor)
    else:
        installed = observation(runtime).physical_params()
        params = None
        if isinstance(installed, dict) and isinstance(
                installed.get('rotationIsAroundCenter'), bool):
            params = dict(rotationIsAroundCenter=installed['rotationIsAroundCenter'])
            if not params['rotationIsAroundCenter']:
                # World rotation takes an explicit pivot, but the original
                # catalogue/tree sweep independently recovers its trajectory
                # from this descriptor. A private physics-only gauge cannot
                # establish the same arc for all three native consumers.
                raise ValueError('track pivot descriptor contract is incomplete')
    if (not isinstance(params, dict) or (not params['rotationIsAroundCenter'] and
            not 0. < _finite(params.get('trackCenter')) <= 100.)):
        raise ValueError('native stationary pivot law is unavailable')
    return params


class _EngineView(object):
    """Only a private observation overlay; the real actor is never edited."""
    def __init__(self, engine, actor, state):
        self.original = engine
        self.states = dict(engine.states)
        self.states[actor] = state

    def __getattr__(self, name):
        return getattr(self.original, name)


class _SensorView(object):
    """Retain raw tree evidence before the native motion compatibility seam."""
    def __init__(self, sensor):
        self.original, self.tree_receipt = sensor, None

    def __getattr__(self, name):
        return getattr(self.original, name)

    def _tree_motion_proposal(self, *args, **kwargs):
        self.tree_receipt = self.original._tree_motion_proposal(*args, **kwargs)
        return self.tree_receipt


def _geometry_view(runtime, position, body):
    original = runtime.geometry
    view = object.__new__(type(original))
    view.__dict__.update(original.__dict__)
    state = dict(runtime.state)
    state.update(position=position, x=position[0], y=position[1], z=position[2],
                 yaw=body[0], pitch=body[1], terrain_pitch=body[1], roll=body[2],
                 grounded_once=True, airborne=False, movement_dir=0,
                 rotation_dir=0)
    view._bots = _EngineView(runtime.engine, runtime.actor_id, state)
    view._destructibles = _SensorView(original._destructibles)
    view._bot_motion_kinds = {}
    view._bot_tree_contacts_pending = {}
    view._local_tree_diagnostics = None
    return view


class _Deferred(Exception):
    def __init__(self, reason, progressing=False):
        Exception.__init__(self, reason)
        self.reason, self.progressing = reason, progressing


class StationaryPlanner(object):
    def __init__(self, runtime):
        self.runtime = runtime
        self.clock = _WALL_CLOCK
        self._epoch = None
        self._epoch_serial = 0
        self._supports, self._arcs, self._plans = {}, {}, {}
        self._budget_at = None
        self._slices, self._support_left = 0, 0
        self._deadline = 0.

    def _peers(self, position, radius):
        """Native bodies which can enter the whole stationary-turn envelope.

        Recompute membership on every check, including current() on an old
        frame. Far traffic does not retire completed static-world slices;
        a newly entering body cannot reuse their former peer clearance.
        """
        owner, result = self.runtime.owner, []
        for key, record in sorted(owner._records.items()):
            if observation(self.runtime).owns_record(record) or record.get('tombstone'):
                continue
            state = record.get('state') or {}
            same_team = int(record.get('team', state.get('team', 0))) == int(observation(self.runtime).actor_team)
            if not (same_team or record.get('spot_visible') or not state.get('alive', True)):
                continue
            entity = owner._server_entity(record.get('engine_id'))
            if not record.get('ready') or entity is None or not getattr(entity, 'isStarted', False):
                raise _Deferred('stationary_peer_geometry_pending')
            descriptor = entity.typeDescriptor
            for name in ('chassis', 'hull'):
                _box(_field(_field(descriptor, name), 'hitTester').bbox)
            matrix = owner._runtime.math.Matrix(entity.matrix)
            shape = tuple(_finite(value) for value in tank_collision.chassis_shape(descriptor))
            point = _point(matrix.translation)
            peer_radius = math.sqrt(shape[0] ** 2 + shape[1] ** 2 +
                                    max(abs(shape[2]), abs(shape[3])) ** 2)
            if math.hypot(point[0] - position[0], point[2] - position[2]) > (
                    radius + peer_radius + _POSITION_EPSILON):
                continue
            result.append(dict(id=record.get('engine_id'), key=key,
                position=point, yaw=_finite(matrix.yaw),
                pitch=_finite(matrix.pitch), roll=_finite(matrix.roll), shape=shape,
                descriptor=id(descriptor)))
        return tuple(result)

    def _dependencies(self, frame):
        runtime, owner, descriptor = self.runtime, self.runtime.owner, frame['descriptor']
        from .attack_policy import native_source_pose
        native_origin = _point(observation(runtime).mutable_shot_ray()[0])
        native_pose = native_source_pose(runtime, native_origin)
        if (any(native_pose[index] != frame['pose'][index] for index in (0, 1, 2, 4, 5, 6)) or
                frame['identity'] != tuple(observation(runtime).weapon_identity()) + (id(descriptor.gun),)):
            raise _Deferred('stationary_native_source_changed')
        motion = _native_motion(runtime)
        state = runtime.state
        if (motion[1] or any(abs(value) > 1.e-6 for value in motion[2:5]) or
                not state.get('grounded_once') or state.get('_edge_support_active') or
                state.get('_foreground_support_blocked') or
                observation(runtime).support_rise_blocked()):
            raise _Deferred('stationary_native_support_unsettled')
        if any('engine' in value.lower() or 'track' in value.lower() or
               'chassis' in value.lower() for value in motion[0]):
            raise _Deferred('stationary_rotation_actuator_unavailable')
        if motion[5] in (1, 3):
            raise _Deferred('stationary_mode_transition_pending')
        hydraulic = active_hydraulic_pose(runtime, frame)
        planning_pose = frame.get('planning_pose', frame['pose'])
        position, mounted_position = _point(frame['position']), _point(frame['pose'][6])
        old = self._epoch
        if hydraulic is not None and old is not None and old[-1] is not None:
            previous = dict(old[-1])
            if (planning_pose[2:] == old[1][2:] and
                    _same_point(planning_pose[0], old[1][0], NATIVE_ANGLE_TOLERANCE) and
                    _same_point(planning_pose[1], old[1][1], _POSITION_EPSILON) and
                    _same_point(position, old[2], _POSITION_EPSILON) and
                    _same_point(mounted_position, old[3], _POSITION_EPSILON) and
                    all(hydraulic[key] == previous.get(key) for key in hydraulic
                    if key not in ('body', 'position', 'correction')) and
                    abs(hydraulic['correction'] - previous['correction']) <= NATIVE_ANGLE_TOLERANCE and
                    _same_point(hydraulic['body'], previous['body'], NATIVE_ANGLE_TOLERANCE) and
                    _same_point(hydraulic['position'], previous['position'], _POSITION_EPSILON)):
                planning_pose, position, mounted_position = old[1:4]
                hydraulic = previous
        hydraulic_stamp = tuple(sorted(hydraulic.items())) if hydraulic is not None else None
        pivot = _pivot(descriptor, runtime)
        for name in ('chassis', 'hull', 'turret', 'gun'):
            _box(_field(_field(descriptor, name), 'hitTester').bbox)
        sensor = getattr(runtime.geometry, '_destructibles', None)
        reader = getattr(sensor, '_vehicle_body_bbox', None)
        if not callable(reader):
            reader = getattr(sensor, '_vehicle_hull_bbox', None)
        if (not callable(reader) or not callable(getattr(sensor, '_catalog_motion_proposal', None)) or
                not callable(getattr(sensor, '_tree_motion_proposal', None)) or
                not callable(getattr(owner._runtime.bigworld, 'wg_collideSegment', None))):
            raise _Deferred('stationary_native_collision_contract_unavailable')
        mounted_box = _box(reader(descriptor))
        revision = getattr(sensor, '_spatial_revision_1513', None)
        if not callable(revision):
            raise _Deferred('stationary_native_scene_revision_unavailable')
        native_scene = (id(owner._avatar), owner._avatar.spaceID, revision())
        accepted_plane = observation(runtime).support_plane()
        native_support = (tuple((name, repr(accepted_plane.get(name))) for name in
            ('center_y', 'normal', 'pitch', 'roll', 'gradient_x', 'gradient_z', 'residual'))
            if isinstance(accepted_plane, dict) else None)
        bounds = tuple(_finite(value) for value in runtime.geometry._arena_bounds)
        if not arena_boundary.valid(bounds):
            raise _Deferred('stationary_arena_bounds_unavailable')
        shape = tuple(_finite(value) for value in state['collision_shape'])
        if len(shape) != 4 or shape[0] <= 0. or shape[1] <= 0. or shape[2] >= shape[3]:
            raise ValueError('native collision shape is unavailable')
        # One sphere encloses every yaw and either native stationary track
        # pivot. It is only a conservative peer-membership broad phase, not
        # a replacement for the original exact rotating contact predicate.
        radius = max(math.sqrt(sum(max(abs(mounted_box[0][axis]),
            abs(mounted_box[1][axis])) ** 2 for axis in range(3))),
            math.sqrt(shape[0] ** 2 + shape[1] ** 2 + max(abs(shape[2]), abs(shape[3])) ** 2))
        radius += math.sqrt(sum((native_pose[6][axis] - native_pose[0][axis]) ** 2
                                for axis in range(3)))
        if not pivot['rotationIsAroundCenter']:
            radius += 2. * pivot['trackCenter']
        peers = self._peers(native_pose[0], radius)
        debris = getattr(owner, '_detached_turret_obstacles', None)
        debris_stamp = None
        if debris is not None:
            ready = getattr(debris, '_ready', None)
            if not callable(ready):
                raise _Deferred('stationary_detached_turret_geometry_pending')
            relevant = []
            for turret in ready(runtime.geometry._turret_server_time_ms()):
                rest, turret_radius = _point(turret['rest']), _finite(turret['radius'])
                if turret_radius < 0.:
                    raise ValueError('native detached turret radius is invalid')
                if math.hypot(rest[0] - native_pose[0][0], rest[2] - native_pose[0][2]) <= (
                        radius + turret_radius + _POSITION_EPSILON):
                    row = turret['row']
                    relevant.append((row['actor_kind'], row['actor_id'], row.get('motion_seq', 0),
                        rest, _point(turret['attitude']), turret_radius,
                        'body' in row['flight']))
            debris_stamp = id(debris), tuple(sorted(relevant))
        peer_stamp = tuple((p['key'], p['position'], p['yaw'], p['pitch'], p['roll'],
                           p['shape'], p['descriptor']) for p in peers)
        params = runtime.engine._physics_params_for(runtime.actor_id)
        cap = _finite(params['rotSpd'])
        if cap <= 0.:
            raise _Deferred('stationary_rotation_actuator_unavailable')
        return (frame['identity'], planning_pose, position, mounted_position,
                frame.get('scene'), motion,
                tuple(sorted(pivot.items())), mounted_box, bounds, shape, cap,
                peer_stamp, id(sensor), native_scene, native_support, debris_stamp,
                hydraulic_stamp), pivot, peers, cap

    def _budget(self, now, deadline):
        if self._budget_at != now:
            self._budget_at = now
            self._slices, self._support_left = SLICES_PER_TICK, SUPPORT_SAMPLES_PER_TICK
            self._deadline = self.clock() + WALL_SECONDS_PER_TICK
        limit = self._deadline if deadline is None else min(self._deadline, deadline)
        if self.clock() >= limit:
            raise _Deferred('stationary_probe_budget_pending', True)
        return limit

    def _support(self, frame, position, yaw, now, deadline):
        key = tuple(position), float(yaw)
        if key not in self._supports:
            self._budget(now, deadline)
            if self._support_left <= 0:
                raise _Deferred('stationary_probe_budget_pending', True)
            self._support_left -= 1
            geometry = self.runtime.geometry
            samples, ground_probe = None, None
            if combat_detail_enabled():
                samples = []

                def ground_probe(x, z, hint):
                    height = geometry._ground_y(x, z, hint)
                    samples.append((x, z, height))
                    return height

            plane = geometry._sample_ground_plane(position, yaw, frame['descriptor'], ground_probe)
            if not isinstance(plane, dict):
                if samples is not None:
                    combat_detail(self.runtime, 'stationary_support_plane',
                        self.runtime.actor_id, now, 'sample_plane_unavailable',
                        lambda: dict(position=position, yaw=yaw, samples=samples))
                raise _Deferred('stationary_native_support_pending')
            # The original sampler's broad residual accepts drivable steps;
            # those are not evidence for transporting this exact plane.
            residual = _finite(plane['residual'])
            if residual > _POSITION_EPSILON:
                if samples is not None:
                    combat_detail(self.runtime, 'stationary_support_plane',
                        self.runtime.actor_id, now, 'sample_fit_residual',
                        lambda: dict(position=position, yaw=yaw, residual=residual,
                                     position_tolerance=_POSITION_EPSILON,
                                     center_y=plane.get('center_y'), normal=plane.get('normal'),
                                     samples=samples))
                raise _Deferred('stationary_support_plane_changes')
            plane = dict(plane, position=tuple(position), yaw=float(yaw))
            self._supports[key] = plane
        return self._supports[key]

    def _same_support(self, source, plane, now):
        predicted_y = (source['center_y'] + source['gradient_x'] *
            (plane['position'][0] - source['position'][0]) + source['gradient_z'] *
            (plane['position'][2] - source['position'][2]))
        height_error = _finite(plane['center_y']) - predicted_y
        if (abs(height_error) > _POSITION_EPSILON or
                any(abs(_finite(plane['normal'][axis]) - _finite(source['normal'][axis])) >
                    NATIVE_ANGLE_TOLERANCE for axis in range(3))):
            if combat_detail_enabled():
                combat_detail(self.runtime, 'stationary_support_plane',
                    self.runtime.actor_id, now, 'transported_plane_mismatch',
                    lambda: dict(source_position=source['position'], source_yaw=source['yaw'],
                        position=plane['position'], yaw=plane['yaw'], predicted_y=predicted_y,
                        sampled_y=plane['center_y'], height_error=height_error,
                        source_normal=source['normal'], normal=plane['normal'],
                        position_tolerance=_POSITION_EPSILON,
                        normal_tolerance=NATIVE_ANGLE_TOLERANCE))
            raise _Deferred('stationary_support_plane_changes')
        # The existing rotation resolver transports X/Z, not a vertical
        # suspension path. A track pivot climbing a slope needs that owner.
        if abs(plane['center_y'] - source['center_y']) > _POSITION_EPSILON:
            raise _Deferred('stationary_track_vertical_path_pending')

    def _project_point(self, frame, shell, target, raw, pivot, hydraulic=None):
        descriptor, position, body = frame['descriptor'], _point(frame['position']), _point(frame['body'])
        mounted_position = _point(frame['pose'][6])
        displacement = tuple(mounted_position[i] - position[i] for i in range(3))
        native_model, unused = shot_geometry.shot_origin_and_direction(
            descriptor, mounted_position, body[0], body[1], body[2], frame['pose'][3][0], 0.)
        if any(abs(native_model[i] - frame['origin'][i]) > _POSITION_EPSILON for i in range(3)):
            raise _Deferred('stationary_native_origin_model_pending')
        sample, velocity = _point(raw['sample_point']), _point(target['velocity'])
        speed, gravity, maximum = (_finite(_field(shell['shot'], name))
                                   for name in ('speed', 'gravity', 'maxDistance'))
        gravity = abs(gravity)
        if speed <= 1. or gravity <= .01 or maximum <= 0.:
            raise ValueError('native ballistics are unavailable')
        limits = _field(_field(descriptor, 'gun'), 'turretYawLimits')
        low, high = (-math.pi, math.pi) if limits is None else tuple(_finite(v) for v in limits)
        if not -math.pi <= low <= high <= math.pi:
            raise ValueError('native yaw limits are unavailable')
        # A target-centre heading shares the safe arc between its samples.
        # A zero-width gun may require further bounded point-specific turns.
        centre = _point(target['matrix'].translation)
        support_body = hydraulic['body'] if hydraulic is not None else body
        yaw = math.atan2(centre[0] - position[0], centre[2] - position[2])
        correction = hydraulic['correction'] if hydraulic is not None else 0.
        flat_offset = (shot_geometry.inverse_transform_vehicle_vector(
            tuple(hydraulic['position'][i] - position[i] for i in range(3)), *support_body)
            if hydraulic is not None else None)
        turret, previous = min(high, max(low, 0.)), None
        for unused in range(PROJECTION_ITERATIONS):
            delta = _angle(yaw - support_body[0])
            offset = vehicle_physics.track_pivot_offset(pivot, 0., delta)
            projected_position = vehicle_physics.track_pivot_position(position, support_body[0], yaw, offset)
            pitch, roll = vehicle_physics.ground_pose_for_yaw(
                support_body[1], support_body[2], support_body[0], yaw)
            projected_body = (yaw, pitch, roll)
            flat_body = projected_body
            base = tuple(projected_position[i] + displacement[i] for i in range(3))
            if hydraulic is not None:
                flat_position = shot_geometry.transform_vehicle_point(
                    flat_offset, projected_position, *flat_body)
                base, projected_body = hydraulic_body(
                    flat_position, flat_body, correction, hydraulic['centerZ'])
            origin, unused_direction = shot_geometry.shot_origin_and_direction(
                descriptor, base, projected_body[0], projected_body[1], projected_body[2], turret, 0.)
            solved = ballistics.ballistic_intercept(origin, sample, velocity, speed, gravity)
            if solved is None or solved[2] * speed > maximum + 1.e-6:
                raise _Deferred('stationary_projected_intercept_pending')
            aim, gun_pitch, flight = solved
            gun_yaw = math.atan2(aim[0] - origin[0], aim[2] - origin[2])
            direction = (math.sin(gun_yaw) * math.cos(gun_pitch), -math.sin(gun_pitch),
                         math.cos(gun_yaw) * math.cos(gun_pitch))
            reach = mechanical_reach(descriptor, direction, projected_body)
            next_correction = correction
            if hydraulic is not None:
                active = hydraulic_reach(descriptor, direction, flat_body, hydraulic)
                if not active.get('reachable') and not active.get('needs_hull'):
                    raise _Deferred('stationary_hydraulic_pitch_unreachable')
                next_correction = active['hydraulic_pitch']
                reach = dict(reach, local_yaw=active['local_yaw'])
            following_turret = min(high, max(low, reach['local_yaw']))
            error = _angle(reach['local_yaw'] - following_turret)
            following_yaw = _angle(yaw + error)
            if (previous is not None and abs(error) < 1.e-7 and
                    abs(_angle(following_turret - turret)) < 1.e-7 and
                    abs(next_correction - correction) < 1.e-7 and
                    sum((origin[i] - previous[i]) ** 2 for i in range(3)) < 1.e-12):
                if not reach['reachable']:
                    raise _Deferred('stationary_projected_pitch_pending')
                path = ballistics.ballistic_path(origin, gun_yaw, gun_pitch, speed, gravity, flight)
                solution = dict(raw.get('solution') or {})
                solution.update(point=tuple(aim), aim_position=tuple(aim), source_point=tuple(aim),
                    yaw=gun_yaw, pitch=gun_pitch, direction=direction, origin=origin,
                    flight_time=flight, path=path, reachable=True,
                    needs_hull=abs(delta) > NATIVE_ANGLE_TOLERANCE,
                    hull_yaw=yaw, body=projected_body, position=projected_position,
                    stationary_plan=True, source_verified=False, mechanical_reason='stationary_plan')
                if hydraulic is not None:
                    solution.update(hydraulic_pitch=correction, siege_correction=correction,
                        needs_hydraulic=abs(correction - hydraulic['correction']) > NATIVE_ANGLE_TOLERANCE,
                        flat_body=flat_body, flat_position=flat_position)
                projected = dict(frame, position=projected_position, body=projected_body, origin=origin)
                return dict(projected_frame=projected, pivot_offset=offset,
                    flat_body=flat_body, hydraulic_pitch=correction,
                    prediction=dict(path=path, reach=dict(reach, status='reachable'),
                        solution=solution, sample_point=sample, direction=direction, flight=flight))
            previous, yaw, turret, correction = origin, following_yaw, following_turret, next_correction
        raise _Deferred('stationary_projection_unsettled')

    def _hydraulic_pose(self, frame, position, body, hydraulic, correction):
        # Native hydraulic contact uses a flat chassis and a separately
        # pivoted hull. Match that consumer instead of tilting the terrain.
        offset = shot_geometry.inverse_transform_vehicle_vector(
            tuple(hydraulic['position'][i] - frame['position'][i] for i in range(3)),
            *hydraulic['body'])
        base = shot_geometry.transform_vehicle_point(offset, position, *body)
        mounted, actual = hydraulic_body(base, body, correction, hydraulic['centerZ'])
        pose = dict(x=position[0], y=position[1], z=position[2],
                    yaw=body[0], pitch=body[1], roll=body[2],
                    actor_key=observation(self.runtime).own_record_key)
        pose['hull'] = dict(x=mounted[0], y=mounted[1], z=mounted[2],
                           yaw=actual[0], pitch=actual[1], roll=actual[2])
        return pose

    def _hydraulic_sweep(self, frame, before_position, before_body, before_correction,
                         after_position, after_body, after_correction, hydraulic):
        probe = getattr(self.runtime.geometry, '_turret_motion_is_clear', None)
        if not callable(probe):
            raise _Deferred('stationary_hydraulic_native_sweep_unavailable')
        before = self._hydraulic_pose(frame, before_position, before_body, hydraulic, before_correction)
        after = self._hydraulic_pose(frame, after_position, after_body, hydraulic, after_correction)
        clear = probe(before, after, frame['descriptor'])
        if clear is not True:
            raise _Deferred('stationary_hydraulic_sweep_blocked' if clear is False else
                            'stationary_hydraulic_sweep_pending')
        return dict(before=before, after=after, native_clear=True)

    def _slice(self, frame, source, first, last, offset, peers, cap, now, deadline,
               hydraulic=None):
        key = (float(first), float(last), float(offset))
        position, body = _point(frame['position']), _point(frame['body'])
        start = vehicle_physics.track_pivot_position(position, body[0], first, offset)
        shape = tuple(self.runtime.state['collision_shape'])
        fraction = tank_collision.rotation_fraction(start, first, last, shape, peers,
                                                     pivot_offset=offset)
        if _finite(fraction) < 1.:
            raise _Deferred('stationary_peer_rotation_blocked')
        if key in self._arcs:
            return self._arcs[key]
        self._budget(now, deadline)
        if self._slices <= 0:
            raise _Deferred('stationary_probe_budget_pending', True)
        middle = first + _angle(last - first) * .5
        observations = []
        for angle in (middle, last):
            at = vehicle_physics.track_pivot_position(position, body[0], angle, offset)
            plane = self._support(frame, at, angle, now, deadline)
            self._same_support(source, plane, now)
            observations.append(plane)
        bounds = tuple(self.runtime.geometry._arena_bounds)
        swept = vehicle_physics.track_pivot_sweep_bounds(start, first, last, offset, shape[0], shape[1])
        if (swept[0] < bounds[0] or swept[1] < bounds[1] or
                swept[2] > bounds[2] or swept[3] > bounds[3]):
            raise _Deferred('stationary_arena_rotation_blocked')
        self._budget(now, deadline)
        self._slices -= 1
        pitch, roll = vehicle_physics.ground_pose_for_yaw(body[1], body[2], body[0], first)
        view = _geometry_view(self.runtime, start, (first, pitch, roll))
        endpoint = vehicle_physics.track_pivot_position(start, first, last, offset)
        if not self.runtime.engine._turret_pose_is_clear(
                view._bots.states[self.runtime.actor_id], start, first, endpoint, last):
            raise _Deferred('stationary_detached_turret_rotation_blocked')
        hydraulic_receipt = None
        if hydraulic is not None:
            final_pitch, final_roll = vehicle_physics.ground_pose_for_yaw(
                body[1], body[2], body[0], last)
            hydraulic_receipt = self._hydraulic_sweep(frame, start, (first, pitch, roll),
                hydraulic['correction'], endpoint, (last, final_pitch, final_roll),
                hydraulic['correction'], hydraulic)
        clear = view._resolve_bot_rotation(self.runtime.actor_id, start, first, last,
            frame['descriptor'], max(1.e-6, abs(_angle(last - first)) / cap), now,
            cap, pivot_offset=offset, commit_enabled=False)
        if clear is not True:
            raise _Deferred('stationary_native_rotation_pending' if clear is None else
                            'stationary_native_rotation_blocked')
        tree = view._destructibles.tree_receipt
        if (not isinstance(tree, dict) or tree.get('status') not in ('clear', 'crushed') or
                tree.get('requires_commit')):
            raise _Deferred('stationary_native_tree_contact_pending')
        receipt = dict(start=start, start_yaw=first, end_yaw=last, pivot_offset=offset,
                       support=tuple(observations), peer_fraction=fraction,
                       arena_envelope=swept, native_clear=True, tree=dict(tree),
                       hydraulic=hydraulic_receipt)
        self._arcs[key] = receipt
        return receipt

    def project(self, frame, shell, target, raw_prediction, now, channel,
                deadline=None):
        try:
            dependencies, pivot, peers, cap = self._dependencies(frame)
            if dependencies != self._epoch:
                if self._epoch is not None and combat_detail_enabled():
                    names = ('weapon', 'planning_pose', 'position', 'native_position',
                             'scene', 'motion', 'pivot', 'mounted_box', 'bounds',
                             'shape', 'rotation_limit', 'peers', 'sensor', 'collision',
                             'support', 'debris', 'hydraulic')
                    changed = tuple(name for name, before, after in
                                    zip(names, self._epoch, dependencies) if before != after)
                    combat_detail(self.runtime, 'stationary_dependency_reset',
                        self.runtime.actor_id, now, changed,
                        lambda: dict(fields=changed, epoch=self._epoch_serial,
                                     support=len(self._supports), arcs=len(self._arcs),
                                     plans=len(self._plans)))
                peer = _PEER_DEPENDENCY
                if (self._epoch is None or self._epoch[:peer] != dependencies[:peer] or
                        self._epoch[peer + 1:] != dependencies[peer + 1:]):
                    self._supports, self._arcs = {}, {}
                self._epoch = dependencies
                self._epoch_serial += 1
                self._plans = {}
            key = (shell['signature'], target['key'], target['pose'], target['velocity'],
                   tuple(raw_prediction['sample_point']))
            # Far moving targets no longer restart static arc work. Their
            # obsolete point plans still have a bounded per-target lifetime.
            for old_key in list(self._plans):
                if old_key[1] == key[1] and (old_key[2:4] != key[2:4] or
                        old_key[0][0] == key[0][0] and old_key[0] != key[0]):
                    self._plans.pop(old_key, None)
            if key in self._plans:
                return self._plans[key]
            self._budget(now, deadline)
            hydraulic = dict(dependencies[-1]) if dependencies[-1] is not None else None
            planned = frame
            if frame.get('stable_planning_pose'):
                planned = dict(frame, body=dependencies[1][0], origin=dependencies[1][1],
                    position=dependencies[2], pose=frame['pose'][:6] + (dependencies[3],))
            proposal = self._project_point(planned, shell, target, raw_prediction, pivot, hydraulic)
            support_frame = dict(planned, body=hydraulic['body']) if hydraulic is not None else planned
            support_body = support_frame['body']
            source = self._support(support_frame, support_frame['position'], support_body[0], now, deadline)
            if (abs(source['pitch'] - support_body[1]) > NATIVE_ANGLE_TOLERANCE or
                    abs(source['roll'] - support_body[2]) > NATIVE_ANGLE_TOLERANCE):
                raise _Deferred('stationary_source_support_disagrees')
            delta = _angle(proposal['flat_body'][0] - support_body[0])
            sign = 1. if delta >= 0. else -1.
            count = int(math.floor(abs(delta) / DESTRUCTIBLE_POSE_MAX_ANGLE_STEP))
            angles = [support_body[0] + sign * DESTRUCTIBLE_POSE_MAX_ANGLE_STEP * index
                      for index in range(count + 1)]
            if abs(delta) - count * DESTRUCTIBLE_POSE_MAX_ANGLE_STEP > 1.e-9:
                angles.append(support_body[0] + delta)
            receipts = []
            for first, last in zip(angles, angles[1:]):
                receipts.append(self._slice(support_frame, source, first, last, proposal['pivot_offset'],
                                            peers, cap, now, deadline, hydraulic))
            hydraulic_receipt = None
            if hydraulic is not None:
                self._budget(now, deadline)
                endpoint = proposal['projected_frame']['position']
                hydraulic_receipt = self._hydraulic_sweep(planned, endpoint, proposal['flat_body'],
                    hydraulic['correction'], endpoint, proposal['flat_body'],
                    proposal['hydraulic_pitch'], hydraulic)
            # A projected negative can only join the global domain after
            # every arc chunk and every native support observation finished.
            if self._dependencies(frame)[0] != dependencies:
                raise _Deferred('stationary_observations_changed')
            proof = dict(proved=True, kind='native_stationary_point_plan',
                dependencies=dependencies, source_pose=dependencies[1],
                source_support=source, pivot=dict(pivot), pivot_offset=proposal['pivot_offset'],
                arc=tuple(receipts), support_resolution=DESTRUCTIBLE_POSE_MAX_ANGLE_STEP * .5,
                projected_position=proposal['projected_frame']['position'],
                projected_body=proposal['projected_frame']['body'],
                hydraulic=hydraulic_receipt, fire_permission=False)
            result = dict(proposal, status='proved', proved=True, proof=proof,
                          reason='native_stationary_point_plan', progressing=False)
            self._plans[key] = result
            return result
        except _Deferred as error:
            result = _pending(error.reason, error.progressing)
            result['progress_token'] = (self._epoch_serial, len(self._supports),
                                        len(self._arcs), len(self._plans))
            return result
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError) as error:
            if combat_detail_enabled():
                runtime = self.runtime
                combat_detail(runtime, 'stationary_projection', runtime.actor_id, now,
                    type(error).__name__, lambda: dict(shell=shell['index'], target=target['key'],
                        channel=channel, error=str(error)[:200]))
            return _pending('stationary_native_projection_unavailable')

    def current(self, frame, proof):
        if isinstance(proof, dict) and isinstance(proof.get('proof'), dict):
            proof = proof['proof']
        if (not isinstance(proof, dict) or proof.get('proved') is not True or
                proof.get('kind') != 'native_stationary_point_plan'):
            return False
        try:
            return proof['dependencies'] == self._dependencies(frame)[0]
        except (_Deferred, AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return False
