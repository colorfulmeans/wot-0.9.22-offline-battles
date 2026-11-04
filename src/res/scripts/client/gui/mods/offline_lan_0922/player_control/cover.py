"""Player-owned, bounded whole-body cover evidence from visible observations.

No Bot sampler, remembered target, allocator or cover state is consulted.
Only descriptor geometry, local native probes and currently visible contacts
enter a search. Completed probe prefixes survive a budget yield; an identity,
pose, threat or scene change invalidates them before any candidate is used.
"""
from __future__ import division
import math

from .. import gun_pitch_limits, shot_geometry


QUERY_BUDGET = 40
FRESH_CANDIDATE_BUDGET = 84
FRESH_CANDIDATE_INTERVAL = .5
MAX_SEARCH_SECONDS = 3.
MAX_UNKNOWN_ATTEMPTS = 4
WEIGHTS = dict(travel_distance=-.055, route_alignment=22., enemy_occlusion=32.,
               exposure=-28., slope=-1.4, water=-55., ally_congestion=-18.,
               peek_feasible=9., escape_feasible=12.)


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _point(value):
    point = tuple(float(value[i]) for i in range(3))
    if any(math.isnan(v) or math.isinf(v) for v in point):
        raise ValueError('non-finite cover position')
    return point


def _distance(first, second):
    return math.hypot(first[0] - second[0], first[2] - second[2])


def _angles(yaw, pitch):
    if yaw is None or pitch is None:
        return None
    values = (float(yaw), float(pitch))
    return None if any(math.isnan(v) or math.isinf(v) for v in values) else values


def body_samples(descriptor):
    samples = shot_geometry.vehicle_aim_samples(descriptor)
    return tuple(list(samples[:2]) + [row for row in samples[2:] if row[0] == 'hull'][:2])


def search_offsets(width, length, phase):
    radius = max(width, length) * 2.
    offsets = [(0., 0.)]
    for scale in (1., 2.):
        for index in range(8):
            angle = index * math.pi / 4.
            offsets.append((math.cos(angle) * radius * scale,
                            math.sin(angle) * radius * scale))
    first = int(phase) % len(offsets)
    return tuple(offsets[first:] + offsets[:first])


def score_candidate(candidate):
    parts = dict((key, float(candidate[key]) * weight) for key, weight in WEIGHTS.items())
    return dict(candidate, score=sum(parts.values()), breakdown=parts)


class _Deferred(Exception):
    pass


class _Budget(object):
    def __init__(self, cache, maximum):
        self.cache, self.remaining, self.used = cache, maximum, 0

    def call(self, kind, function, *args):
        key = (kind,) + tuple(args)
        if key in self.cache:
            return self.cache[key]
        if self.remaining <= 0:
            raise _Deferred('query_budget')
        self.remaining -= 1
        self.used += 1
        try:
            value = function(*args)
        except _Deferred:
            raise
        except Exception:
            raise _Deferred('query_unavailable')
        if value is None:
            raise _Deferred('query_unknown')
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            raise _Deferred('query_unknown')
        self.cache[key] = value
        return value


class PlayerCover(object):
    def __init__(self, owner):
        self.owner = owner
        self.epoch = 0
        self.phase = 0
        self.job = None
        self.episode = None
        self.last_sample = None
        self.invalidated_budgets = 0
        self.next_fresh_candidate = float('-inf')
        self.receipt = dict(status='idle', queries=0)

    def reset(self):
        self.epoch += 1
        self.job = None
        self.episode = None
        self.invalidated_budgets = 0
        self.receipt = dict(status='idle', queries=0)

    def close(self):
        self.reset()
        self.owner = None

    def identity(self, entity):
        owner = self.owner
        avatar = getattr(owner, '_avatar', None)
        control = getattr(owner, '_player_control', None)
        return (self.epoch, id(owner), id(avatar), getattr(avatar, 'spaceID', None),
                id(getattr(owner, 'client', None)),
                (getattr(owner, '_start_message', {}) or {}).get('round_id'),
                getattr(control, 'control_generation', None), id(entity),
                id(entity.typeDescriptor))

    def own_angles(self, entity):
        rotator = getattr(getattr(self.owner, '_avatar', None), 'gunRotator', None)
        try:
            if rotator is not None:
                return _angles(getattr(rotator, 'turretYaw', None), getattr(rotator, 'gunPitch', None))
            read = getattr(entity, 'getAimParams', None)
            return _angles(*read()) if callable(read) else None
        except (AttributeError, TypeError, ValueError):
            return None

    def observe(self, state, context, target):
        """Use the contact's observed pose and the visible native gun mount."""
        if self.owner is None or target is None:
            return None
        focus = _field(target, 'id')
        available = {}
        eligible = {}
        records = getattr(self.owner, '_records', {}) or {}
        read = getattr(self.owner, '_server_entity', None)
        if not callable(read):
            return None
        for raw in context.get('contacts') or ():
            if (not raw.get('visible') or not raw.get('alive', True) or
                    raw.get('health', 1) <= 0 or raw.get('position') is None):
                continue
            record = next((row for row in records.values()
                           if row.get('engine_id') == raw.get('id')), None)
            if (not record or not record.get('ready') or record.get('tombstone') or
                    record.get('local') or not record.get('spot_visible') or
                    int((record.get('state') or {}).get('team', 0)) ==
                    int(self.owner.client.team)):
                continue
            entity = read(raw['id'])
            if (entity is None or not getattr(entity, 'isStarted', False) or
                    not entity.isAlive()):
                continue
            descriptor = entity.typeDescriptor
            public = record.get('state') or {}
            try:
                eligible[raw['id']] = _point(entity.position)
                matrix = getattr(entity, 'matrix', None)
                pose = dict(position=eligible[raw['id']],
                    yaw=float(getattr(matrix, 'yaw', raw['yaw'])),
                    pitch=float(getattr(matrix, 'pitch', raw.get('pitch', 0.))),
                    roll=float(getattr(matrix, 'roll', raw.get('roll', 0.))))
                turret = raw.get('turret_yaw', public.get('turret_yaw'))
                pitch = raw.get('gun_pitch', public.get('gun_pitch'))
                read_angles = getattr(entity, 'getAimParams', None)
                native_angles = _angles(*read_angles()) if callable(read_angles) else None
                appearance = getattr(entity, 'appearance', None)
                matrix = getattr(appearance, 'turretMatrix', None)
                if native_angles is not None:
                    turret, pitch = native_angles
                elif matrix is not None:
                    turret = float(self.owner._runtime.math.Matrix(matrix).yaw)
                if turret is None:
                    static = _field(_field(descriptor, 'gun'), 'staticTurretYaw')
                    if static is not None:
                        turret = static
                    elif public.get('aim_yaw') is not None:
                        turret = float(public['aim_yaw']) - pose['yaw']
                angles = _angles(turret, pitch)
                if angles is None:
                    continue  # A missing mount angle is not a guessed muzzle.
                pose['turret_yaw'], pose['gun_pitch'] = angles
                origin, unused = shot_geometry.shot_origin_and_direction(descriptor,
                    pose['position'], pose['yaw'], pose['pitch'], pose['roll'],
                    pose['turret_yaw'], pose['gun_pitch'])
                available[raw['id']] = dict(id=raw['id'], pose=pose, origin=_point(origin),
                                            descriptor=descriptor, entity=entity)
            except (AttributeError, TypeError, ValueError, KeyError, IndexError):
                continue
        first = available.get(focus)
        if first is None:
            return None
        origin = state['position']
        heading = math.atan2(first['pose']['position'][0] - origin[0],
                             first['pose']['position'][2] - origin[2])
        def priority(row):
            identity, point = row
            bearing = math.atan2(point[0] - origin[0], point[2] - origin[2])
            separation = abs(math.atan2(math.sin(bearing-heading), math.cos(bearing-heading)))
            return (-(1. + separation) / max(1., _distance(origin, point)), str(identity))
        others = sorted((row for row in eligible.items() if row[0] != focus), key=priority)[:1]
        if any(identity not in available for identity, unused in others):
            return None  # An unknown relevant crossfire is not absent fire.
        return (first,) + tuple(available[identity] for identity, unused in others)

    @staticmethod
    def _threat_key(threats):
        return tuple((row['id'], id(row['entity']), id(row['descriptor']), row['origin'],
            row['pose']['position'], row['pose']['yaw'], row['pose']['pitch'],
            row['pose']['roll'], row['pose']['turret_yaw'], row['pose']['gun_pitch']) for row in threats)

    @staticmethod
    def _exposure(samples, pose, threats, ray, budget):
        if not samples or not threats:
            raise _Deferred('missing_body_geometry')
        points = [shot_geometry.vehicle_aim_point(sample, pose) for sample in samples]
        return max(sum(1. for point in points if budget.call('ray', ray, row['origin'], point)) /
                   len(points) for row in threats)

    @staticmethod
    def _surface(point, state, ground, budget):
        yaw = state['yaw']
        length, width = state['half_length'], state['half_width']
        forward, side = (math.sin(yaw), math.cos(yaw)), (math.cos(yaw), -math.sin(yaw))
        centre = budget.call('height', ground, point[0], point[2], point[1])
        heights = []
        for direction, reach in ((forward, length), (side, width)):
            heights.append(tuple(budget.call('height', ground,
                point[0] + sign * direction[0] * reach,
                point[2] + sign * direction[1] * reach, centre) for sign in (-1., 1.)))
        if min(length, width) <= 0.:
            return None
        grade = max(abs(height-centre)/reach for row, reach in zip(heights, (length, width))
                    for height in row)
        if grade > math.tan(math.radians(24.)):
            return None
        pitch = -math.atan2(heights[0][1] - heights[0][0], 2. * length)
        roll = math.atan2(heights[1][1] - heights[1][0], 2. * width)
        return dict(position=(point[0], centre, point[2]), yaw=yaw, pitch=pitch, roll=roll,
                    turret_yaw=state['turret_yaw'], gun_pitch=state['gun_pitch'])

    @staticmethod
    def _gun_lane(pose, descriptor, focus, ray, budget):
        gun = _field(descriptor, 'gun')
        origin, unused = shot_geometry.shot_origin_and_direction(descriptor, pose['position'],
            pose['yaw'], pose['pitch'], pose['roll'], pose['turret_yaw'], pose['gun_pitch'])
        for sample in body_samples(focus['descriptor'])[:2]:
            point = shot_geometry.vehicle_aim_point(sample, focus['pose'])
            direction = tuple(point[i] - origin[i] for i in range(3))
            yaw, pitch = shot_geometry.world_direction_to_local_gun_angles(
                direction, pose['yaw'], pose['pitch'], pose['roll'])
            low, high = gun_pitch_limits.calc_pitch_limits(yaw, _field(gun, 'pitchLimits'))
            limits = _field(gun, 'turretYawLimits')
            if (not low <= pitch <= high or limits is not None and not limits[0] <= yaw <= limits[1]):
                continue
            aimed, unused = shot_geometry.shot_origin_and_direction(descriptor,
                pose['position'], pose['yaw'], pose['pitch'], pose['roll'], yaw, pitch)
            if budget.call('ray', ray, _point(aimed), point):
                return True
        return False

    def _evaluate(self, job, offset, state, context, descriptor, threats,
                  ground, water, segment, ray, budget, route_goal):
        current, focus = state['position'], threats[0]['pose']['position']
        span = _distance(current, focus)
        if span < 2.:
            return None
        away = ((current[0]-focus[0])/span, (current[2]-focus[2])/span)
        side = (away[1], -away[0])
        point = (current[0] + away[0]*offset[0] + side[0]*offset[1], current[1],
                 current[2] + away[1]*offset[0] + side[1]*offset[1])
        pose = self._surface(point, state, ground, budget)
        if pose is None:
            return None
        point = pose['position']
        depth = float(budget.call('water', water, point))
        if depth > 1.2 or not budget.call('segment', segment, current, point):
            return None
        samples = body_samples(descriptor)
        hidden = self._exposure(samples, pose, threats, ray, budget)
        if hidden > .5:
            return None
        # The already visited firing pose is a useful first peek, but it must
        # be proved again. Both flank peeks use actual mounted-gun geometry.
        width = state['half_width'] * 2.
        peeks = [current]
        for sign in ((-1., 1.) if job['phase'] % 2 else (1., -1.)):
            peeks.append((point[0]+side[0]*width*1.5*sign, point[1],
                          point[2]+side[1]*width*1.5*sign))
        for peek in peeks:
            if _distance(peek, point) < 1.5:
                continue
            peek_pose = self._surface(peek, state, ground, budget)
            if peek_pose is None:
                continue
            peek = peek_pose['position']
            if (float(budget.call('water', water, peek)) > 1.2 or
                    not budget.call('segment', segment, point, peek) or
                    not budget.call('segment', segment, peek, point) or
                    not self._gun_lane(peek_pose, descriptor, threats[0], ray, budget)):
                continue
            exposed = self._exposure(samples, peek_pose, threats, ray, budget)
            midpoint = tuple((point[i]+current[i])*.5 for i in range(3))
            middle_height = budget.call('height', ground, midpoint[0], midpoint[2], midpoint[1])
            middle_pose = dict(pose, position=(midpoint[0], middle_height, midpoint[2]))
            approach = self._exposure(samples[:2], middle_pose, threats, ray, budget)
            travel = _distance(current, point)
            alignment = .5
            if route_goal is not None and travel > .1 and _distance(current, route_goal) > .1:
                alignment = max(0., min(1., .5 + .5 * sum(
                    (point[i]-current[i])*(route_goal[i]-current[i]) for i in (0, 2)) /
                    (travel * _distance(current, route_goal))))
            nearby = sum(1 for row in context.get('allies') or () if row.get('position') is not None
                and row.get('id') != state.get('engine_id') and row.get('alive', True)
                and .5 < _distance(point, row['position']) < 13.)
            return score_candidate(dict(goal=point, peek=peek, travel_distance=travel,
                route_alignment=alignment, enemy_occlusion=1.-hidden,
                exposure=(hidden+exposed+approach)/3.,
                slope=math.degrees(max(abs(pose['pitch']), abs(pose['roll']))),
                water=max(0., min(1., depth)), ally_congestion=min(1., nearby/3.),
                peek_feasible=True, escape_feasible=True, threats=tuple(row['id'] for row in threats),
                cover_exposure=hidden, peek_exposure=exposed, approach_exposure=approach))
        return None

    def update(self, state, context, target, entity, ground, water, segment, ray,
               scene=None, route_goal=None):
        now = state['now']
        threats = self.observe(state, context, target)
        angles = self.own_angles(entity)
        samples = body_samples(entity.typeDescriptor)
        if (threats is None or angles is None or not samples or
                not context.get('supported', True) or context.get('overturned')):
            self.reset()
            self.receipt = dict(status='unavailable', reason='observed_geometry_unavailable', queries=0)
            return None
        state = dict(state, turret_yaw=angles[0], gun_pitch=angles[1])
        binding = self.identity(entity)
        scene_value = scene() if callable(scene) else scene
        episode_key = (binding, threats[0]['id'])
        if self.episode is None or self.episode[0] != episode_key:
            self.episode = (episode_key, now)
        signature = (binding, tuple(state['position']), state['yaw'], state.get('pitch', 0.),
                     state.get('roll', 0.), angles, self._threat_key(threats), scene_value)
        if self.job is None or self.job['signature'] != signature:
            if self.job is not None and self.job.get('deferred') == 'query_budget':
                self.invalidated_budgets += 1
            self.job = dict(signature=signature, binding=binding, at=self.episode[1], cursor=0,
                cache={}, candidates=[], unknown=0, phase=self.phase,
                offsets=search_offsets(state['half_width']*2., state['half_length']*2., self.phase))
        job = self.job
        if self.last_sample == now:
            self.receipt = dict(status='pending', reason='same_decision', queries=0)
            return None
        self.last_sample = now
        fresh = self.invalidated_budgets >= 2 and now >= self.next_fresh_candidate
        maximum = FRESH_CANDIDATE_BUDGET if fresh else QUERY_BUDGET
        if fresh:
            # Two moving snapshots cannot repeatedly discard the same prefix.
            # At most one whole candidate receives this finite, throttled pass.
            self.next_fresh_candidate = now + FRESH_CANDIDATE_INTERVAL
            self.invalidated_budgets = 0
        budget = _Budget(job['cache'], maximum)
        reason = 'candidate_search'
        while job['cursor'] < len(job['offsets']) and now - job['at'] < MAX_SEARCH_SECONDS:
            try:
                candidate = self._evaluate(job, job['offsets'][job['cursor']], state, context,
                    entity.typeDescriptor, threats, ground, water, segment, ray, budget, route_goal)
            except _Deferred as error:
                reason = str(error)
                job['deferred'] = reason
                if reason != 'query_budget':
                    job['unknown'] += 1
                    if job['unknown'] >= MAX_UNKNOWN_ATTEMPTS:
                        job['cursor'] += 1
                        self.phase += 1
                        job['cache'], job['unknown'] = {}, 0
                break
            except (AttributeError, TypeError, ValueError, KeyError, IndexError):
                candidate = None
                reason = 'descriptor_geometry_unavailable'
            if self.job is not job:
                return None
            job['cursor'] += 1
            self.phase += 1
            job['unknown'] = 0
            job['deferred'] = None
            if candidate is not None:
                job['candidates'].append(candidate)
            if fresh or budget.remaining <= 0:
                break
        if self.job is not job:
            return None
        if job['candidates']:
            fresh_threats = self.observe(state, context, target)
            local_pose = getattr(self.owner, 'local_pose', None)
            own_changed = False
            if callable(local_pose):
                own_position, own_yaw = local_pose()
                own_changed = (_point(own_position) != tuple(state['position']) or
                    float(own_yaw) != state['yaw'] or
                    getattr(self.owner, '_local_pitch', state.get('pitch', 0.)) != state.get('pitch', 0.) or
                    getattr(self.owner, '_local_roll', state.get('roll', 0.)) != state.get('roll', 0.))
            invalid = (self.identity(entity) != binding or self.own_angles(entity) != angles or
                    own_changed or fresh_threats is None or
                    self._threat_key(fresh_threats) != self._threat_key(threats) or
                    (scene() if callable(scene) else scene) != scene_value)
            if self.job is not job or self.epoch != binding[0]:
                return None  # Do not reset a newly installed owner's job.
            if invalid:
                self.reset()
                self.receipt = dict(status='unavailable', reason='evidence_changed', queries=budget.used)
                return None
            # The final angle/revision readers above may themselves re-enter
            # Reset/Retask. No native or user callback follows this fence.
            if self.job is not job or self.identity(entity) != binding:
                return None
            candidates = sorted(job['candidates'], key=lambda row: (-row['score'], row['travel_distance'], row['goal']))
            result = dict(candidates[0], binding=binding, target=threats[0]['id'])
            self.receipt = dict(status='ready', queries=budget.used, evaluated=job['cursor'],
                reason='whole_body_multithreat', selected=dict(result), candidates=len(candidates),
                query_limit=maximum, fresh_candidate=fresh)
            self.job = None
            self.episode = None
            return result
        done = job['cursor'] >= len(job['offsets']) or now - job['at'] >= MAX_SEARCH_SECONDS
        self.receipt = dict(status='complete' if done else 'pending', queries=budget.used,
            evaluated=job['cursor'], reason=reason, threats=tuple(row['id'] for row in threats),
            query_limit=maximum, fresh_candidate=fresh)
        if done:
            self.job = None
            self.episode = None
        return None

    def peek_clear(self, state, context, target, entity, point, ground, ray):
        threats = self.observe(state, context, target)
        angles, binding = self.own_angles(entity), self.identity(entity)
        if threats is None or angles is None:
            return None
        state = dict(state, turret_yaw=angles[0], gun_pitch=angles[1])
        budget = _Budget({}, min(12, QUERY_BUDGET))
        try:
            pose = self._surface(point, state, ground, budget)
            result = False if pose is None else self._gun_lane(pose, entity.typeDescriptor, threats[0], ray, budget)
            latest = self.observe(state, context, target)
            if (latest is None or self.identity(entity) != binding or self.own_angles(entity) != angles or
                    self._threat_key(latest) != self._threat_key(threats)):
                return None
            if self.identity(entity) != binding:
                return None
            return result
        except (_Deferred, AttributeError, TypeError, ValueError, KeyError, IndexError):
            return None

    def current_exposure(self, state, context, target, entity, ray):
        threats = self.observe(state, context, target)
        angles, binding = self.own_angles(entity), self.identity(entity)
        if threats is None or angles is None:
            return None
        pose = dict(position=state['position'], yaw=state['yaw'],
                    pitch=state.get('pitch', 0.), roll=state.get('roll', 0.),
                    turret_yaw=angles[0], gun_pitch=angles[1])
        try:
            result = self._exposure(body_samples(entity.typeDescriptor), pose, threats, ray,
                                   _Budget({}, 8))
            latest = self.observe(state, context, target)
            if (latest is None or self.identity(entity) != binding or self.own_angles(entity) != angles or
                    self._threat_key(latest) != self._threat_key(threats)):
                return None
            if self.identity(entity) != binding:
                return None
            return result
        except (_Deferred, AttributeError, TypeError, ValueError, KeyError, IndexError):
            return None
