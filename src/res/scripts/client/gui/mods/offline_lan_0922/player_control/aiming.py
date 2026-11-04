"""Observed-target aiming owned solely by the foreground player.

The native gun rotator still lays the gun and Avatar still owns shooting. This
module supplies verified world-space point sources, never forced gun angles.
Only geometry, ballistics and nominal armour laws are shared with other actors.
"""
from __future__ import division

import math

from .. import ballistics, gun_pitch_limits, hull_aiming, shot_geometry
from ..gun_mechanics import _field


CANDIDATES_PER_TICK = 2
SEGMENTS_PER_TICK = 12
NATIVE_ANGLES_PER_TICK = 12
NATIVE_ANGLE_TOLERANCE = .00001
# Freshness of a completed advisory result, not a deadline for sliced work.
# Pending paths retain their bounded cursor while their geometry is valid.
PLAN_SECONDS = 3.
PLAN_MOVE_METRES = 1.
# The final real-barrel gate is synchronous: 20 s / .12 s gives 167
# chords. Planning remains sliced; this separate bounded cost is at most 2 Hz.
FINAL_SEGMENTS_PER_ATTEMPT = 167
FINAL_PROBE_SECONDS = .5


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
    yaw_ok = limits is None or float(limits[0]) <= yaw <= float(limits[1])
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


def _straight_intercept(start, point, velocity, speed):
    relative = tuple(point[i] - start[i] for i in range(3))
    a = sum(v*v for v in velocity) - speed*speed
    b = 2. * sum(relative[i]*velocity[i] for i in range(3))
    c = sum(v*v for v in relative)
    if abs(a) < 1.e-9:
        roots = (-c / b,) if abs(b) > 1.e-9 else ()
    else:
        determinant = b*b - 4.*a*c
        roots = () if determinant < 0. else (
            (-b-math.sqrt(determinant))/(2.*a),
            (-b+math.sqrt(determinant))/(2.*a))
    roots = [t for t in roots if 0. < t <= ballistics.PROJECTILE_MAX_FLIGHT_SECONDS]
    if not roots:
        return None
    flight = min(roots)
    aim = tuple(point[i] + velocity[i]*flight for i in range(3))
    dx, dy, dz = (aim[i] - start[i] for i in range(3))
    return aim, -math.atan2(dy, math.hypot(dx, dz)), flight


class Aiming(object):
    """Bounded player planner; begin receives only locally visible entities.

    All updates with the same now share two candidate builds, twelve world
    chords and twelve native angle queries. These are advisory arc-family
    proofs. confirm separately checks the entire current real-barrel path in
    one game-thread call, at most 167 static chords per half-second, bracketed
    by fresh whole-path dynamic checks. It never reuses a previous gun pose.
    """
    def __init__(self, owner):
        self.owner = owner
        self.reset()

    def reset(self):
        self.targets = {}
        self.observations = {}
        self.entries = {}
        self.direct_entries = {}
        self.comparison_jobs = {}
        self.comparison_deferrals = {}
        self._tick = None
        self._next_final_at = float('-inf')
        self._final_segments = self._final_attempts = self._dynamic_checks = 0
        self._final_reason = 'idle'
        self._cursor = 0
        self._preferred = None
        self._due = set()
        self._worked = set()
        self._candidates = self._segments = self._angles = 0
        self.receipt = {}

    def begin(self, visible_targets, now):
        now = float(now)
        if self._tick is not None and now < self._tick:
            self.reset()
        previous = self.observations
        observations, targets = {}, {}
        for target in visible_targets:
            point = _point(self.owner._runtime.math.Matrix(target.matrix).translation)
            old = previous.get(target.id)
            velocity = (0., 0., 0.)
            if old is not None:
                elapsed = now - old['time']
                if elapsed == 0.:
                    velocity = old['velocity']
                elif .02 <= elapsed <= 1.:
                    measured = tuple((point[i]-old['position'][i])/elapsed
                                     for i in range(3))
                    # A native presentation discontinuity is not a measured
                    # velocity. It must not predict a shot across the map.
                    if _distance_sq(point, old['position']) <= 25.*25.:
                        weight = .5 if old.get('measured') else 1.
                        velocity = tuple(weight*measured[i] +
                                         (1.-weight)*old['velocity'][i]
                                         for i in range(3))
            observations[target.id] = dict(position=point, time=now,
                velocity=velocity, measured=bool(old and (
                old.get('measured') if now == old['time'] else
                .02 <= now-old['time'] <= 1.)))
            targets[target.id] = target
        self.targets, self.observations = targets, observations
        for target_id in list(self.entries):
            if target_id not in targets:
                self.entries.pop(target_id, None)
        for key in list(self.direct_entries):
            if key[0] not in targets:
                self.direct_entries.pop(key)
        for store in (self.comparison_jobs, self.comparison_deferrals):
            for key in list(store):
                if key[0] not in targets:
                    del store[key]
        if now == self._tick:
            return
        self._tick = now
        self._candidates = CANDIDATES_PER_TICK
        self._segments = SEGMENTS_PER_TICK
        self._angles = NATIVE_ANGLES_PER_TICK
        self._final_segments = self._final_attempts = self._dynamic_checks = 0
        self._final_reason = 'idle'
        self._worked = set()
        identifiers = sorted(targets)
        self._due = set()
        if self._preferred in identifiers:
            self._due.add(self._preferred)
        if identifiers:
            start = self._cursor % len(identifiers)
            for offset in range(len(identifiers)):
                self._due.add(identifiers[(start+offset) % len(identifiers)])
                if len(self._due) >= min(CANDIDATES_PER_TICK, len(identifiers)):
                    break
            self._cursor = (start+offset+1) % len(identifiers)
        self._publish_budget()

    def _publish_budget(self):
        self.receipt = dict(candidates=CANDIDATES_PER_TICK-self._candidates,
                            segments=SEGMENTS_PER_TICK-self._segments,
                            native_angles=NATIVE_ANGLES_PER_TICK-self._angles,
                            final_segments=self._final_segments,
                            final_attempts=self._final_attempts,
                            dynamic_checks=self._dynamic_checks,
                            final_reason=self._final_reason)

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

    def _pose(self, target):
        matrix = self.owner._runtime.math.Matrix(target.matrix)
        pose = dict(position=_point(matrix.translation), yaw=float(matrix.yaw),
                    pitch=float(matrix.pitch), roll=float(matrix.roll))
        appearance = getattr(target, 'appearance', None)
        turret_matrix = getattr(appearance, 'turretMatrix', None)
        if turret_matrix is not None:
            pose['turret_yaw'] = float(self.owner._runtime.math.Matrix(turret_matrix).yaw)
        return pose

    def _fallback(self, target, reason):
        # The entity origin remains a finite look point if native hit boxes
        # are not ready. It is never promoted into a firing candidate.
        point = self.observations.get(target.id, {}).get('position', _point(target.position))
        return dict(target=target.id, point=point, source_point=point,
                    clear=False, geometry_clear=False, reachable=False,
                    needs_hull=False, arc='low', path=(), reason=reason,
                    velocity=self.observations.get(target.id, {}).get('velocity', (0., 0., 0.)))

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

    def _armor_score(self, target, own, sample_point, direction, flight, threshold=None, nominal_only=False):
        """Nominal damage against observed native plates, without shot RNG."""
        from .. import combat_rules
        from ..entities.remote_vehicle import collide_vehicle_at_matrix
        try:
            # Score the arrival direction, including a descending SPG arc,
            # against the current observed model rather than a future proxy.
            arrival = (direction[0]*own['speed'],
                       direction[1]*own['speed']-own['gravity']*flight,
                       direction[2]*own['speed'])
            length = math.sqrt(sum(v*v for v in arrival))
            shape = self.owner._collision_shape(target.typeDescriptor)
            reach = max(10., 4.*max(abs(v) for v in shape))
            start = tuple(sample_point[i]-arrival[i]*reach/length for i in range(3))
            collisions = collide_vehicle_at_matrix(
                target, target.matrix, self.owner._vector(start),
                self.owner._vector(sample_point), self.owner._runtime.math)
            if not collisions:
                return None
            if nominal_only:
                return combat_rules.he_nominal_armor(collisions, target.typeDescriptor)
            distance = math.sqrt(_distance_sq(own['origin'], sample_point))
            contact = combat_rules.resolve_armor_contact(
                own['shot'], distance, collisions,
                penetration_factor=1. if threshold is None else threshold)
            if contact is None:
                return None
            if threshold is not None:
                return contact['layer'] == 'structural' and contact['result'] == 2
            if contact['layer'] != 'structural' and not combat_rules.is_he(own['shot']):
                return 0.
            nominal = combat_rules.he_nominal_armor(collisions, target.typeDescriptor)
            damage = combat_rules.shell_damage_roll(
                own['shot'], random_gauss=lambda mean, unused_sigma: mean)
            return float(combat_rules.damage(own['shot'], contact['result'],
                                            nominal, rolled_damage=damage))
        except (AttributeError, TypeError, ValueError, IndexError, KeyError,
                RuntimeError, ZeroDivisionError):
            # Lack of loaded native plate geometry is unknown armour, not a
            # fictitious weak spot or proof of zero damage.
            return None

    def _candidate(self, target, own, entry, key, now, direct=False, threshold=None):
        if self._candidates <= 0:
            return None
        self._candidates -= 1
        sample_index, arc = key
        sample = entry['samples'][sample_index]
        pose = self._pose(target)
        point = shot_geometry.vehicle_aim_point(sample, pose)
        velocity = self.observations[target.id]['velocity']
        result = dict(self._fallback(target, 'no_ballistic_intercept'),
                      point=point, source_point=point, sample=sample_index,
                      part=sample[0], arc=arc, velocity=velocity, score=None,
                      lead_delay=0.,
                      created=now, observed=pose['position'], body=own['body'],
                      origin=own['origin'], shell_key=own['key'], key=key)
        if own['gravity'] == 0.:
            solution = None if arc == 'high' else _straight_intercept(
                own['origin'], point, velocity, own['speed'])
            result['arc'] = 'direct'
        else:
            solution = ballistics.ballistic_intercept(
                own['origin'], point, velocity, own['speed'], own['gravity'],
                prefer_high=arc == 'high')
            if solution is not None and arc == 'high' and len(
                    ballistics.ballistic_solutions(own['origin'], solution[0],
                                                  own['speed'], own['gravity'])) < 2:
                solution = None
        if solution is None:
            return result
        aim, pitch, flight = solution
        result.update(point=aim, source_point=aim, pitch=pitch, flight_time=flight)
        if own['speed']*flight > own['maximum'] + 1.e-6:
            result['reason'] = 'range_limit'
            return result
        yaw = math.atan2(aim[0]-own['origin'][0], aim[2]-own['origin'][2])
        direction = _direction(yaw, pitch)
        result.update(yaw=yaw, direction=direction,
            path=ballistics.ballistic_path(own['origin'], yaw, pitch,
                own['speed'], own['gravity'], flight))
        reach = mechanical_reach(own['descriptor'], direction, own['body'], own.get('hydraulic'))
        result.update(reach)
        mounted = own['key'][0] == self.owner._gun_state.shot_index
        source = self._source_point(own, aim, reach) if reach['reachable'] and (
            not direct or mounted) else None
        if direct and not mounted and reach['reachable']:
            source = aim
        result['source_verified'] = source is not None
        if source is not None:
            result['source_point'] = source
        elif reach['reachable']:
            result['reason'] = 'native_source_unverified'
        if not direct:
            result['score'] = self._armor_score(target, own, point, direction, flight)
        elif threshold is not None and reach['reachable'] and source is not None:
            result['penetration_ok'] = self._armor_score(
                target, own, point, direction, flight, threshold)
        return result

    @staticmethod
    def _valid(result, own, observation, now):
        """Check geometry independently of the scheduler's service latency.

        The frozen path is an advisory arc-family proof. A moving target may
        keep the same measured trajectory; fresh candidates still supply the
        current intercept and confirm always checks the current entire barrel
        path. Elapsed time alone must not repeatedly erase unfinished chords.
        """
        expected = tuple(result['observed'][i] + result['velocity'][i] *
                         max(0., now-result['created']) for i in range(3))
        return (result.get('shell_key') == own['key'] and
                _distance_sq(result['origin'], own['origin']) <= .5*.5 and
                _distance_sq(expected, observation['position']) <= PLAN_MOVE_METRES**2 and
                max(abs(_angle(result['body'][i]-own['body'][i]))
                    for i in range(3)) <= .03)

    def _advance(self, job, lane, limit, now):
        path = job['solution'].get('path', ())
        while (job['next'] < len(path)-1 and self._segments > 0 and limit > 0):
            index = job['next']
            self._segments -= 1
            limit -= 1
            job['next'] += 1
            if not lane(path[index], path[index+1]):
                job['done'], job['clear'] = True, False
                job['completed'] = now
                return
        if path and job['next'] == len(path)-1:
            job['done'], job['clear'] = True, True
        elif not path:
            job['done'], job['clear'] = True, False
        if job['done']:
            job['completed'] = now

    @staticmethod
    def _rank(result, preferred):
        score = result.get('score')
        return (bool(result.get('clear') and result.get('reachable')),
                bool(result.get('geometry_clear') and result.get('needs_hull')),
                bool(result.get('geometry_clear')),
                score is not None and score > 0., score if score is not None else -1.,
                result.get('key') == preferred, result.get('arc') != 'high',
                -int(result.get('sample', 0)))

    @staticmethod
    def _result(solution, job):
        result = dict(solution)
        result['geometry_clear'] = bool(job['done'] and job['clear'])
        result['needs_hull'] = bool(result.get('needs_hull') and result['geometry_clear'])
        result['clear'] = bool(result['geometry_clear'] and result.get('source_verified'))
        if result['reachable'] and result.get('source_verified'):
            result['reason'] = ('hydraulic_laying' if result.get('needs_hydraulic') else
                                'clear' if job['done'] and job['clear'] else
                                'world_blocked' if job['done'] else 'checking_path')
        return result

    def update(self, target, now, lane, artillery=False):
        if target.id not in self.targets or self.targets[target.id] is not target:
            return self._fallback(target, 'not_observed')
        try:
            own = self._own()
        except (AttributeError, TypeError, ValueError, IndexError, RuntimeError):
            return self._fallback(target, 'native_aim_inputs_unavailable')
        entry = self.entries.get(target.id)
        signature = (id(target.typeDescriptor), own['key'], bool(artillery))
        if entry is None or entry['signature'] != signature:
            samples = shot_geometry.ordered_vehicle_aim_samples(target.typeDescriptor)
            entry = dict(signature=signature, samples=samples, jobs={}, cursor=0,
                         selected=None)
            self.entries[target.id] = entry
        if not entry['samples']:
            return self._fallback(target, 'target_geometry_unavailable')
        for key, job in list(entry['jobs'].items()):
            if (not self._valid(job['solution'], own, self.observations[target.id], now) or
                    (job['done'] and now-job['completed'] > PLAN_SECONDS)):
                entry['jobs'].pop(key, None)
        choices = [(index, arc) for index in range(len(entry['samples']))
                   for arc in (('low', 'high') if artillery else ('low',))]
        results = []
        may_work = target.id in self._due and target.id not in self._worked
        count = 2 if len(self.targets) == 1 else 1
        work = []
        if may_work:
            self._worked.add(target.id)
            selected = entry['selected']
            selected_job = entry['jobs'].get(selected)
            if selected_job is not None and selected_job['done'] and selected_job['clear']:
                fresh = self._candidate(target, own, entry, selected, now)
                if fresh is not None:
                    results.append(self._result(fresh, selected_job))
                    count -= 1
            pending = [key for key in choices if key in entry['jobs'] and
                       not entry['jobs'][key]['done']]
            while count > 0 and self._candidates > 0:
                if pending:
                    key = pending.pop(0)
                    job = entry['jobs'][key]
                    # Keep the advisory arc proof frozen while laying to a
                    # fresh observed intercept of that same part and family.
                    candidate = self._candidate(target, own, entry, key, now)
                    if candidate is None:
                        break
                else:
                    key = None
                    for unused in choices:
                        probe = choices[entry['cursor'] % len(choices)]
                        entry['cursor'] += 1
                        existing = entry['jobs'].get(probe)
                        if existing is None or (existing['done'] and
                                not existing['clear'] and now-existing['completed'] >= .5):
                            key = probe
                            break
                    if key is None:
                        break
                    candidate = self._candidate(target, own, entry, key, now)
                    if candidate is None:
                        break
                    job = dict(solution=candidate, next=0, done=False, clear=False,
                               completed=None)
                    entry['jobs'][key] = job
                work.append((job, candidate))
                count -= 1
            clear_selected = bool(results and results[0].get('clear'))
            allowance = min(self._segments, 2 if clear_selected else
                            max(1, SEGMENTS_PER_TICK // max(1, len(self._due))))
            for index, (job, candidate) in enumerate(work):
                share = max(1, allowance // (len(work)-index))
                before = self._segments
                self._advance(job, lane, share, now)
                allowance -= before-self._segments
                results.append(self._result(candidate, job))
        # Unworked entities may expose their latest finite point for laying,
        # but only this tick's built/retained solution can admit a shot.
        if not results:
            jobs = list(entry['jobs'].values())
            if jobs:
                cached = max((self._result(j['solution'], j) for j in jobs),
                             key=lambda r: self._rank(r, entry['selected']))
                result = dict(cached, clear=False, reason='budget_pending')
            else:
                result = self._fallback(target, 'budget_pending')
            self._publish_budget()
            return result
        result = max(results, key=lambda r: self._rank(r, entry['selected']))
        if result.get('geometry_clear'):
            entry['selected'] = result['key']
        if result.get('clear') and result.get('reachable'):
            self._preferred = target.id
        elif self._preferred == target.id:
            self._preferred = None
        self._publish_budget()
        return result

    def actual_contact(self, target, solution, own, direction, threshold, velocity=None):
        """Resolve the laid, pre-dispersion barrel against the observed vehicle."""
        from .. import combat_rules
        from ..entities.remote_vehicle import collide_vehicle_at_matrix
        from .weapon import barrel_aligned
        origin, speed, gravity = own['origin'], own['speed'], own['gravity']
        point = solution['point']
        if not barrel_aligned(origin, direction, speed, gravity, point, .30):
            return 'laying'
        horizontal = direction[0]**2 + direction[2]**2
        flight = sum((point[i]-origin[i])*direction[i] for i in (0, 2))/(speed*horizontal)
        radius = max(abs(v) for v in self.owner._collision_shape(target.typeDescriptor))
        span = max(4., radius*2.) / speed
        first, last = max(0., flight-span), min(own['maximum']/speed, flight+span)
        if last <= first:
            return 'miss'
        if velocity is None:
            velocity = self.observations[target.id]['velocity']

        def observed_chord(at):
            projected = [origin[i] + (direction[i]*speed-velocity[i])*at for i in range(3)]
            projected[1] -= .5*gravity*at*at
            return self.owner._vector(projected)

        try:
            hits = collide_vehicle_at_matrix(target, target.matrix,
                observed_chord(first), observed_chord(last), self.owner._runtime.math)
            if not hits:
                return 'miss'
            if threshold is None:
                if solution.get('nominal_required') and combat_rules.he_nominal_armor(
                        hits, target.typeDescriptor) is None:
                    return 'miss'
                return 'ready'
            contact = combat_rules.resolve_armor_contact(
                own['shot'], flight*speed, hits, penetration_factor=threshold)
            if contact is None:
                return 'unknown'
            return ('ready' if contact['layer'] == 'structural' and
                    contact['result'] == 2 else 'armor')
        except (AttributeError, TypeError, ValueError, IndexError, KeyError, RuntimeError):
            return 'unknown'

    def defer_ordered_point(self, target, index, solution, now):
        """Try the remaining samples when the final lane repeatedly rejects one."""
        key = solution.get('key')
        if key is not None:
            self.comparison_deferrals[(target.id, index, key[0])] = now + 1.5
        identity = (target.id, index, solution.get('penetration_threshold'), True)
        entry = self.direct_entries.get(identity)
        if entry is not None and key is not None and entry['locked'] == key:
            entry.setdefault('blocked_points', {})[key[0]] = now + 1.5
            entry.update(cursor=0, locked=None, job=None, mechanical=None,
                         unknown=False, blocked_armor=False, laying_since=None,
                         deferred_at=None)

    def ordered(self, target, index, threshold, now, lane, physical=False):
        """Advance one fixed-order scan without publishing an unverified point."""
        if target.id not in self.targets or self._candidates <= 0:
            return 'pending', None
        try:
            own = self._own(index)
        except (AttributeError, TypeError, ValueError, IndexError, RuntimeError):
            return 'pending', None
        identity = (target.id, index, threshold, physical)
        entry = self.direct_entries.get(identity)
        signature = (id(target), id(target.typeDescriptor), own['key'],
                     index == self.owner._gun_state.shot_index)
        if entry is None or entry['signature'] != signature:
            entry = dict(signature=signature,
                samples=shot_geometry.ordered_vehicle_aim_samples(target.typeDescriptor),
                cursor=0, locked=None, job=None, retry=0., blocked_armor=False,
                unknown=False, mechanical=None, deferred_at=None, laying_since=None)
            self.direct_entries[identity] = entry
        if not entry['samples']:
            return 'unavailable', None
        if now < entry['retry']:
            return 'pending', entry['mechanical']
        locked = entry['locked']
        blocked_points = entry.get('blocked_points', {})
        while entry['cursor'] < len(entry['samples']) and locked is None:
            if now >= blocked_points.get(entry['cursor'], 0.):
                break
            entry['unknown'] = True
            entry['cursor'] += 1
        if entry['cursor'] >= len(entry['samples']):
            entry.update(cursor=0, retry=now + .7, blocked_armor=False,
                         unknown=False, mechanical=None)
            return 'unavailable', None
        key = locked if locked is not None else (entry['cursor'], 'low')
        candidate = self._candidate(target, own, entry, key, now, True,
                                    None if physical else threshold)
        job = entry['job']
        if (job is None or job['solution']['key'] != key or
                not self._valid(job['solution'], own, self.observations[target.id], now)):
            job = dict(solution=candidate, next=0, done=False, clear=False, completed=None)
            entry['job'] = job
        self._advance(job, lane, min(self._segments, 8), now)
        result = self._result(candidate, job)
        result['ordered'] = True
        result['physical'] = physical
        result['penetration_threshold'] = threshold
        if not job['done']:
            return 'pending', None
        if result['clear'] and result['reachable']:
            if physical and result.get('needs_hydraulic'):
                result['laying'] = True
                return 'laying', result
            penetrates = result.get('penetration_ok')
            if physical:
                unused, direction = self.owner._mutable_shot_ray()
                verdict = self.actual_contact(target, result, own, direction, threshold)
                if verdict in ('laying', 'miss', 'unknown'):
                    if entry['laying_since'] is None:
                        entry['laying_since'] = now
                    if now - entry['laying_since'] < (5. if verdict == 'laying' else .5):
                        result['laying'] = True
                        return 'laying', result
                    entry['unknown'] |= verdict == 'unknown'
                penetrates = verdict == 'ready' if verdict in ('ready', 'armor') else None
            if (not physical and threshold is None) or penetrates is True:
                entry.update(locked=key, job=None, deferred_at=None, laying_since=None)
                return 'ready', result
            if penetrates is False:
                entry['blocked_armor'] = True
            elif not physical:
                entry['unknown'] = True
        elif result['geometry_clear'] and not result['reachable']:
            if entry['mechanical'] is None:
                entry['mechanical'] = result
        elif result['geometry_clear'] and not result.get('source_verified'):
            entry['unknown'] = True

        if locked is not None:
            entry.update(locked=None, cursor=0, job=None, blocked_armor=False,
                         unknown=False, mechanical=None, deferred_at=None, laying_since=None)
            return 'lost', None
        if (not physical and result['geometry_clear'] and result['reachable'] and
                (not result.get('source_verified') or
                 (threshold is not None and result.get('penetration_ok') is None))):
            if entry['deferred_at'] is None:
                entry['deferred_at'] = now
            if now - entry['deferred_at'] < .5:
                return 'pending', None
        entry['job'] = None
        entry['deferred_at'] = entry['laying_since'] = None
        entry['cursor'] += 1
        if entry['cursor'] < len(entry['samples']):
            return 'pending', entry['mechanical']
        status = ('armor' if entry['blocked_armor'] and not entry['unknown'] else
                  'unavailable')
        mechanical = entry['mechanical']
        entry.update(cursor=0, retry=now + .7, blocked_armor=False,
                     unknown=False, mechanical=None)
        return status, mechanical

    def direct_pose(self, target):
        pose = self._pose(target)
        position, yaw = self.owner.local_pose()
        return (tuple(position), yaw, tuple(pose['position']), pose['yaw'],
                pose.get('turret_yaw', 0.), pose['pitch'], pose['roll'])

    def direct_samples(self, target):
        return len(shot_geometry.ordered_vehicle_aim_samples(target.typeDescriptor))

    def compare_direct(self, target, index, sample, now, lane, threshold,
                       physical=False, current_barrel=False, nominal=False):
        """Compare one shell and one ordered point within the shared aim budget."""
        if target.id not in self.targets or self._candidates <= 0:
            return 'pending', None
        if now < self.comparison_deferrals.get((target.id, index, sample), 0.):
            return 'unavailable', None
        try:
            own = self._own(index)
            samples = shot_geometry.ordered_vehicle_aim_samples(target.typeDescriptor)
            if sample >= len(samples):
                return 'unknown', None
            key = (sample, 'low')
            result = self._candidate(target, own, dict(samples=samples), key, now,
                                     True, None if physical or current_barrel else threshold)
            if current_barrel:
                from .weapon import artillery_path
                unused, direction = self.owner._mutable_shot_ray()
                result['path'] = artillery_path(own['origin'], result['point'], own['shot'], direction)
                if not result['path']:
                    return 'unavailable', None
                contact = self.actual_contact(target, result, own, direction, threshold)
                if contact != 'ready':
                    return ('unknown' if contact == 'unknown' else contact), None
            identity = (target.id, index, sample, current_barrel)
            job = self.comparison_jobs.get(identity)
            if (job is None or not self._valid(job['solution'], own, self.observations[target.id], now)
                    or now - job['solution']['created'] > 1.
                    or current_barrel and job['solution']['path'] != result['path']):
                job = dict(solution=result, next=0, done=False, clear=False, completed=None)
                self.comparison_jobs[identity] = job
            self._advance(job, lane, min(self._segments, 8), now)
            if not job['done']:
                return 'pending', None
            result = self._result(result, job)
            result.update(ordered=True, physical=True, penetration_threshold=threshold)
            if not result['geometry_clear'] or not result['reachable']:
                return 'unavailable', result
            if not result['source_verified']:
                return 'unknown', None
            if nominal:
                thickness = self._armor_score(target, own,
                    shot_geometry.vehicle_aim_point(samples[sample], self._pose(target)),
                    result['direction'], result['flight_time'], nominal_only=True)
                if thickness is None:
                    return 'unknown', None
                result['nominal_armor'] = thickness
                result['nominal_required'] = True
            if current_barrel:
                return 'ready', result
            if physical:
                unused, direction = self.owner._mutable_shot_ray()
                verdict = ('laying' if result.get('needs_hydraulic') else
                           self.actual_contact(target, result, own, direction, threshold))
                if verdict in ('laying', 'miss', 'unknown'):
                    error = None
                    if verdict == 'laying':
                        dot = sum(result['direction'][i]*direction[i] for i in range(3))
                        error = math.acos(max(-1., min(1., dot)))
                    return 'laying', dict(result, laying=True, barrel_error=error)
                return verdict, result
            if threshold is None:
                return 'ready', result
            proof = result.get('penetration_ok')
            return ('ready' if proof is True else 'armor' if proof is False else 'unknown'), result
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return 'unknown', None

    def fire_preflight(self, target, solution, raw_ray, shot, now):
        """Fresh pre-dispersion gate for a first shot or any automatic tail.

        Unlike the advisory planner's half-second confirm throttle, this is
        called for each actual physical round. It rebuilds the ordered point
        from the currently presented target and checks the current native
        barrel. World/friendly proofs belong to FireAdmission, not Bot AI.
        """
        from .weapon import barrel_aligned
        if (self.targets.get(target.id) is not target or
                solution.get('target') != target.id or
                not solution.get('clear') or not solution.get('source_verified')):
            return 'auto_solution_stale', None
        observation = self.observations.get(target.id)
        if observation is None or not 0. <= float(now)-observation['time'] <= .35:
            return 'auto_observation_stale', None
        try:
            own = self._own()
            if solution.get('shell_key') != own['key']:
                return 'auto_shell_changed', None
            origin, direction = _point(raw_ray[0]), _point(raw_ray[1])
            own.update(origin=origin, shot=shot, speed=float(_field(shot, 'speed')),
                gravity=abs(float(_field(shot, 'gravity'))),
                maximum=float(_field(shot, 'maxDistance')))
            samples = (shot_geometry.ordered_vehicle_aim_samples(target.typeDescriptor)
                       if solution.get('ordered') else
                       shot_geometry.vehicle_aim_samples(target.typeDescriptor))
            point = shot_geometry.vehicle_aim_point(samples[solution['sample']], self._pose(target))
            velocity = observation['velocity']
            if own['gravity'] == 0.:
                intercept = _straight_intercept(origin, point, velocity, own['speed'])
            else:
                intercept = ballistics.ballistic_intercept(origin, point, velocity,
                    own['speed'], own['gravity'], prefer_high=solution.get('arc') == 'high')
            if intercept is None or own['speed']*intercept[2] > own['maximum']:
                return 'auto_intercept_unavailable', None
            fresh = dict(solution, point=intercept[0], pitch=intercept[1],
                         flight_time=intercept[2], velocity=velocity, origin=origin)
            # This gate deliberately uses only the current mechanical pose.
            # Hydraulic reachability authorizes laying, never premature fire.
            reach = mechanical_reach(own['descriptor'], direction, own['body'])
            if not reach['reachable']:
                return 'auto_gun_laying', fresh
            if solution.get('physical'):
                verdict = self.actual_contact(target, fresh, own, direction,
                    solution.get('penetration_threshold'), velocity=velocity)
                if verdict != 'ready':
                    return 'auto_actual_barrel_'+verdict, fresh
            radius = max(.3, self.owner._collision_shape(target.typeDescriptor)[0]*.5)
            if not barrel_aligned(origin, direction, own['speed'], own['gravity'], fresh['point'], radius):
                return 'auto_gun_laying', fresh
            return None, fresh
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return 'auto_geometry_unavailable', None

    def _final_verdict(self, reason):
        self._final_reason = reason
        self._publish_budget()
        return reason == 'clear'

    def confirm(self, target, solution, direction, now, static_lane, dynamic_clear=None):
        """Check this current real barrel in one bounded, synchronous call.

        static_lane(start, end) checks BSP scenery. dynamic_clear(path) reads
        current allies/wrecks and conservatively tests the whole path without
        BSP queries. A caller omitting dynamic_clear must supply a combined
        static-and-dynamic lane; no cross-tick launch proof is retained.
        """
        from .weapon import artillery_path, barrel_aligned
        if (now != self._tick or target.id not in self.targets or
                self.targets[target.id] is not target or not solution.get('clear') or
                not solution.get('reachable') or solution.get('target') != target.id):
            return self._final_verdict('not_current')
        if solution.get('needs_hydraulic'):
            return self._final_verdict('hydraulic_laying')
        if now < self._next_final_at:
            return self._final_verdict('probe_cooldown')
        try:
            own = self._own()
            direction = _point(direction)
        except (AttributeError, TypeError, ValueError, IndexError, RuntimeError):
            return self._final_verdict('native_aim_inputs_unavailable')
        if solution.get('shell_key') != own['key']:
            return self._final_verdict('shell_changed')
        if solution.get('physical'):
            verdict = self.actual_contact(
                target, solution, own, direction, solution.get('penetration_threshold'))
            if verdict != 'ready':
                return self._final_verdict('actual_barrel_' + verdict)
        radius = max(.3, self.owner._collision_shape(target.typeDescriptor)[0]*.5)
        if not barrel_aligned(own['origin'], direction, own['speed'], own['gravity'],
                              solution['point'], radius):
            return self._final_verdict('barrel_not_aligned')
        path = artillery_path(own['origin'], solution['point'], own['shot'], direction)
        if not path or len(path)-1 > FINAL_SEGMENTS_PER_ATTEMPT:
            return self._final_verdict('path_budget')
        entry = self.entries.get(target.id)
        if entry is not None:
            sample = entry['samples'][solution['sample']]
            current = shot_geometry.vehicle_aim_point(sample, self._pose(target))
            velocity = self.observations[target.id]['velocity']
            arrival = tuple(current[i] + velocity[i]*solution['flight_time'] for i in range(3))
            if _distance_sq(arrival, solution['point']) > radius*radius:
                return self._final_verdict('target_moved')
        if dynamic_clear is not None:
            self._dynamic_checks += 1
            if not dynamic_clear(path):
                return self._final_verdict('dynamic_blocked')
        # Do not charge/retry the expensive static pass while a current ally
        # blocks the line. Once admitted, this entire pass is bound to exactly
        # the current origin/direction; tiny suspension jitter needs no key or
        # tolerance because nothing is borrowed from an earlier barrel pose.
        self._next_final_at = now + FINAL_PROBE_SECONDS
        self._final_attempts += 1
        for first, last in zip(path, path[1:]):
            self._final_segments += 1
            if not static_lane(first, last):
                if solution.get('ordered'):
                    for identity, ordered in self.direct_entries.items():
                        if identity[:2] == (target.id, own['key'][0]):
                            ordered.update(locked=None, cursor=0, job=None,
                                blocked_armor=False, unknown=False, mechanical=None,
                                deferred_at=None, retry=0.)
                if entry is not None:
                    failed = entry['jobs'].get(solution.get('key'))
                    if failed is not None:
                        failed.update(done=True, clear=False, completed=now)
                    if entry['selected'] == solution.get('key'):
                        entry['selected'] = None
                return self._final_verdict('static_blocked')
        if dynamic_clear is not None:
            self._dynamic_checks += 1
            if not dynamic_clear(path):
                return self._final_verdict('dynamic_blocked')
        return self._final_verdict('clear')
