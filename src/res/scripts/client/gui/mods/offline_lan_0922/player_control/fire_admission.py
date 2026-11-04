"""Fresh foreground-only admission for every physical automatic round.

The random draw belongs to the next round, not to an admission attempt. World
proofs may be invalidated/rebuilt as the native barrel moves; a blocked lane
must never buy another dispersion draw. Manual Avatar triggers do not enter
this owner. Shared native collision/ballistic laws are not Bot decisions.
"""
from __future__ import division

import math
import random

from .. import ballistics, combat_rules, lan_client, projectile_runtime, shot_geometry
from .weapon import artillery_path
from .firing_lane import FiringLane


WORLD_CHORDS_PER_ATTEMPT = 24
MAX_PROOF_CHORDS = 334
PROBE_INTERVAL = .05
COMPLETED_PROOF_TTL = .2
FULL_PROOF_INTERVAL = .5
GEOMETRY_RESTART_LIMIT = 2
MAX_COLLISION_ROSTER = 30


def _point(value):
    point = tuple(float(value[i]) for i in range(3))
    if any(math.isnan(v) or math.isinf(v) for v in point):
        raise ValueError('non-finite fire geometry')
    return point


def _distance_sq(a, b):
    return sum((a[i]-b[i])**2 for i in range(3))


class _ScatterDraw(object):
    """Replay unit random inputs through the ordinary mounted-gun sampler."""
    def __init__(self):
        self.normal = random.gauss(0., 1.)
        self.uniforms = []
        self.cursor = 0

    def gauss(self, mean, sigma):
        return mean + sigma*self.normal

    def uniform(self, minimum, maximum):
        if self.cursor == len(self.uniforms):
            self.uniforms.append(random.uniform(0., 1.))
        value = self.uniforms[self.cursor]
        self.cursor += 1
        return minimum + (maximum-minimum)*value

    def scatter(self, owner, gun, direction, perfect, dispersion):
        self.cursor = 0
        result = owner._vector(direction)
        result.normalise()
        gun.scatter(result, perfect, gauss=self.gauss,
                    uniform=self.uniform, dispersion_angle=dispersion)
        return _point(result)


class FireAdmission(object):
    """Own one immutable random candidate and bounded, replaceable path proof."""
    def __init__(self, control):
        self.control = control
        self.reset()

    def reset(self):
        self.pending = self.front_contact = None
        self.lane = FiringLane()
        self.receipt = dict(status='idle', reason='idle', world_chords=0)
        self._next_probe = float('-inf')
        self._next_full_probe = float('-inf')

    def _result(self, status, reason, token=None, **fields):
        result = dict(status=status, reason=reason, token=token)
        result.update(fields)
        if getattr(self.control, 'direct_engagement', None) is not None:
            result.update(self.lane.receipt())
            if status != 'pending' or reason == 'auto_friendly_lane':
                self.lane.pending_since = None
        result['proof_native_collision_calls_upper'] = (int(fields.get('world_chords', 0)) +
            4*int(fields.get('target_queries', 0)))
        self.receipt = dict((key, value) for key, value in result.items()
                            if key not in ('token', 'target'))
        return result

    def _target(self, context):
        """Use this client's currently visible native entity, never Bot memory."""
        control, owner = self.control, self.control.owner
        identity = context.get('target')
        planner = getattr(control, 'aiming', None)
        target = getattr(planner, 'targets', {}).get(identity)
        if (target is None or identity != control.target_engine or
                not target.isStarted or not target.isAlive()):
            return None
        for record in owner._records.values():
            if record.get('engine_id') != identity:
                continue
            team = int((record.get('state') or {}).get('team', 0))
            if (record.get('ready') and not record.get('tombstone') and
                    not record.get('local') and record.get('spot_visible') and
                    team in (1, 2) and team != int(owner.client.team) and
                    owner._server_entity(identity) is target):
                return target
        return None

    def _fresh(self, context, raw_ray, source_shot, now):
        target = self._target(context)
        weapon = context.get('weapon')
        if weapon is None:
            weapon = getattr(self.control, 'weapon', None)
        rotator = getattr(self.control.owner._avatar, 'gunRotator', None)
        if (not self.control.active or weapon is not getattr(self.control, 'weapon', None) or
                not getattr(weapon, 'saved', None) or weapon.saved[0] is not rotator or
                getattr(rotator, '_VehicleGunRotator__shotPointSourceFunctor', None) is not
                getattr(weapon, 'bound_source', None) or rotator.clientMode is not True):
            return 'auto_aim_owner_changed', None, None
        solution = getattr(weapon, 'solution', None)
        if (target is None or not isinstance(solution, dict) or
                getattr(weapon, 'target', None) != target.id):
            return 'auto_target_lost', target, None
        order = getattr(self.control, 'last_order', {}) or {}
        mission = order.get('mission') or {}
        if mission.get('status') in ('failed', 'cancelled'):
            return 'auto_mission_'+mission['status'], target, None
        if order.get('suppress_fire') or not order.get('fire_allowed', True):
            return 'auto_order_holds_fire', target, None
        if (not mission and (order.get('artillery') or {}).get('phase') in
                ('deploying', 'relocating', 'sortie_return')):
            return 'auto_artillery_repositioning', target, None
        reason, fresh = self.control.aiming.fire_preflight(
            target, solution, raw_ray, source_shot, now)
        return reason, target, fresh

    @staticmethod
    def terminal_reason(reason):
        return reason in ('auto_target_lost', 'auto_aim_owner_changed',
                         'auto_mission_failed', 'auto_mission_cancelled',
                         'auto_shell_changed')

    def _identity(self, context, entity, gun, target, burst):
        identity = context.get('identity') or {}
        return (context.get('generation'), tuple(sorted(identity.items())),
                id(entity), id(gun), gun.shot_index, context.get('shell_signature'),
                id(target), context.get('target'),
                burst.get('group_seq') if isinstance(burst, dict) else None,
                burst.get('committed') if isinstance(burst, dict) else None)

    @staticmethod
    def _restart(candidate, proof):
        if (not proof['done'] and not proof['blocked'] and
                (proof['stage'] or proof['cursor'])):
            candidate['restarts'] += 1
            if candidate['restarts'] >= GEOMETRY_RESTART_LIMIT:
                candidate['full_proof'] = True

    def _splash_clear(self, point, radius):
        """Test current allied full component bounds at the actual endpoint."""
        if radius <= 0.:
            return True
        from ..entities.remote_vehicle import vehicle_target_bounds_at_matrix
        owner = self.control.owner
        for record in owner._records.values():
            if (record.get('local') or record.get('tombstone') or
                    not record.get('ready') or
                    int((record.get('state') or {}).get('team', 0)) != int(owner.client.team)):
                continue
            other = owner._server_entity(record.get('engine_id'))
            if other is None or not other.isStarted or not other.isAlive():
                continue
            if record.get('native_remote'):
                body, chassis = owner._projectile_vehicle_matrices(record, other)
            else:
                body, chassis = other.matrix, None
            bounds = vehicle_target_bounds_at_matrix(
                other, body, owner._runtime.math, chassis_matrix=chassis)
            if bounds is None:
                return False
            closest = tuple(max(bounds[0][axis], min(bounds[1][axis], point[axis]))
                            for axis in range(3))
            if _distance_sq(closest, point) <= radius*radius:
                return False
        return True

    def _dynamic_reason(self, target, proof, splash):
        for name in ('raw_path', 'path'):
            path = proof.get('centre_path', proof[name]) if name == 'raw_path' else proof[name]
            reason, blocker = self._check_lane(target, path, name)
            if reason is not None:
                return reason, blocker
        # Range/time expiry is not an explosion. HE safety is tied to the
        # first proved actual world/vehicle contact, never an aiming plane.
        impact = proof.get('terminal_impact')
        if impact is not None and not self._splash_clear(impact, splash):
            return 'auto_friendly_splash', None
        return None, None

    def _check_lane(self, target, path, name):
        if getattr(self.control, 'direct_engagement', None) is not None:
            status, blocker = self.lane.check(self.control.owner, target, path)
            if status == 'clear':
                return None, None
            reason = dict(blocked='auto_friendly_lane', pending='auto_lane_pending',
                          unknown='auto_lane_geometry_unavailable')[status]
            return reason, dict(blocker or {}, path=name)
        if not self.control.dynamic_path_clear(target, path):
            return 'auto_friendly_lane', self._lane_blocker(name)
        return None, None

    def _lane_blocker(self, path):
        return dict(getattr(self.control, 'dynamic_blocker', None) or {}, path=path)

    def _target_pose(self, target):
        """Snapshot only this client's observed native collision geometry."""
        owner = self.control.owner
        matrix = owner._runtime.math.Matrix
        body, chassis = target.matrix, target.matrix
        for record in owner._records.values():
            if record.get('engine_id') == target.id:
                body, chassis = owner._projectile_vehicle_matrices(record, target)
                break
        body, chassis = matrix(body), matrix(chassis)
        turret = matrix(target.appearance.turretMatrix)
        gun = matrix(target.appearance.gunMatrix)
        signature = (id(target.typeDescriptor),
            _point(body.translation), float(body.yaw), float(body.pitch), float(body.roll),
            _point(chassis.translation), float(chassis.yaw), float(chassis.pitch), float(chassis.roll),
            float(turret.yaw), float(gun.pitch), bool(getattr(target, 'isTurretDetached', False)))
        return signature, body, chassis

    def _collision_roster(self, target, selected_velocity, now):
        """Freeze visible enemies that can end the shot before its target.

        A full room has at most thirty vehicles. Do not silently truncate an
        inconsistent roster: without every locally visible collision actor,
        a proof cannot claim the first HE impact is safe.
        """
        owner, rows = self.control.owner, []
        for record in owner._records.values():
            if (record.get('local') or record.get('tombstone') or not record.get('ready') or
                    not record.get('spot_visible') or
                    int((record.get('state') or {}).get('team', 0)) == int(owner.client.team)):
                continue
            other = owner._server_entity(record.get('engine_id'))
            if other is None or not other.isStarted or not other.isAlive():
                continue
            if len(rows) >= MAX_COLLISION_ROSTER:
                return None
            signature, body, chassis = self._target_pose(other)
            observation = self.control.aiming.observations.get(other.id)
            velocity = (tuple(selected_velocity) if other is target else
                tuple(observation['velocity']) if observation is not None and
                0. <= now-observation['time'] <= .35 else (0., 0., 0.))
            rows.append(dict(target=other, body=body, chassis=chassis,
                velocity=velocity, signature=(other.id, id(other), signature, velocity)))
        rows.sort(key=lambda row: row['target'].id)
        return rows

    def _target_contact(self, proof, first, last, first_time, last_time, first_only=False):
        """Find a real terminal plate, not an approximate target-box entry.

        A moving target is queried in its currently observed frame. The same
        measured velocity used by the independent aim planner supplies the
        relative sweep; this never consults a Bot/worker pose owner.
        """
        from ..entities.remote_vehicle import collide_vehicle_at_matrix
        owner, candidates, best = self.control.owner, [], None
        for row in proof['collision_roster']:
            velocity = row['velocity']
            start = tuple(first[i]-velocity[i]*first_time for i in range(3))
            end = tuple(last[i]-velocity[i]*last_time for i in range(3))
            entry = shot_geometry.segment_box_entry_distance(start, end, row['bounds'])
            length = math.sqrt(_distance_sq(start, end))
            if entry is not None and length > 0.:
                candidates.append((entry/length, row, start, end, length))
        candidates.sort(key=lambda item: item[0])
        for broad_fraction, row, start, end, length in candidates:
            if best is not None and broad_fraction > best[0]:
                break
            proof['target_queries'] += 1
            hits = collide_vehicle_at_matrix(row['target'], row['body'],
                owner._vector(start), owner._vector(end), owner._runtime.math,
                chassis_matrix=row['chassis'])
            if not hits:
                continue
            entry_distance = min(float(hit.dist) for hit in hits)
            entry_fraction = entry_distance/length
            entry_point = tuple(first[i]+entry_fraction*(last[i]-first[i]) for i in range(3))
            if first_only:
                if not 0. <= entry_fraction <= 1.:
                    raise ValueError('native target entry outside its queried chord')
                if best is None or entry_fraction < best[0]:
                    best = (entry_fraction, entry_point, row['target'].id)
                continue
            shot = proof['shot']
            material_trace = proof.get('material_trace')
            if material_trace:
                trace_end = combat_rules.vehicle_material_trace_end(shot, entry_distance)
                if trace_end > length + .000001 and not combat_rules.is_he(shot):
                    extended_end = tuple(start[i] + (end[i]-start[i])*trace_end/length
                                         for i in range(3))
                    proof['target_queries'] += 1
                    extended = collide_vehicle_at_matrix(row['target'], row['body'],
                        owner._vector(start), owner._vector(extended_end), owner._runtime.math,
                        chassis_matrix=row['chassis'])
                    if extended:
                        hits = extended
                        trace_end = combat_rules.vehicle_material_trace_end(
                            shot, min(float(hit.dist) for hit in hits))
                hits = combat_rules.vehicle_material_hits(hits, trace_end)
            contact = combat_rules.resolve_armor_contact(shot,
                math.sqrt(_distance_sq(proof['range_origin'], entry_point)), hits,
                penetration_factor=proof['penetration_factor'])
            if material_trace:
                if not 0. <= entry_fraction <= 1.:
                    raise ValueError('native target entry outside its queried chord')
                # The simulated round reaches this actor at the first plate.
                # Its damage trace may find another plate, or only externals.
                impact = entry_point
                if contact is not None and combat_rules.is_he(shot):
                    fraction = min(1., max(0., float(contact['distance'])/length))
                    impact = tuple(first[i]+fraction*(last[i]-first[i]) for i in range(3))
                if best is None or entry_fraction < best[0]:
                    best = (entry_fraction, entry_point, row['target'].id, impact,
                            (contact or {}).get('layer'), (contact or {}).get('result', 1))
                continue
            if contact is None:
                # Penetrated screens/tracks alone do not stop the shell.
                continue
            fraction = float(contact['distance'])/length
            if not 0. <= fraction <= 1.:
                raise ValueError('native target contact outside its queried chord')
            point = tuple(first[i]+fraction*(last[i]-first[i]) for i in range(3))
            if best is None or fraction < best[0]:
                best = fraction, point, row['target'].id
        return best

    def _probe(self, first, last):
        owner = self.control.owner
        hit = owner._runtime.bigworld.wg_collideSegment(
            owner._avatar.spaceID, owner._vector(first), owner._vector(last), 128)
        return None if hit is None else _point(hit[0])

    def _scene(self):
        owner = self.control.owner
        sensor = getattr(owner, '_destructibles', None)
        revision = getattr(sensor, '_spatial_revision_1513', None)
        return (id(owner._avatar), owner._avatar.spaceID,
                getattr(owner, '_generation', None), id(sensor),
                revision() if callable(revision) else None)

    def _advance(self, proof, budget=WORLD_CHORDS_PER_ATTEMPT):
        """Prove both centre and exact scattered rays under one native quota."""
        used = 0
        while used < budget:
            path_name = 'raw_path' if proof['stage'] == 0 else 'path'
            path = proof[path_name]
            cursor = proof['cursor']
            if cursor >= len(path)-1:
                if proof['stage'] == 0:
                    proof['stage'], proof['cursor'] = 1, 0
                    continue
                proof['done'] = True
                break
            first, last = path[cursor], path[cursor+1]
            hit = self._probe(first, last)
            used += 1
            target_hit = None
            if proof['stage'] == 1:
                target_hit = self._target_contact(proof, first, last,
                    proof['times'][cursor], proof['times'][cursor+1])
            elif proof.get('material_trace'):
                step = proof['raw_step']
                target_hit = self._target_contact(proof, first, last,
                    cursor*step, (cursor+1)*step, first_only=True)
            fraction = None
            if hit is not None:
                delta = tuple(last[i]-first[i] for i in range(3))
                length2 = sum(v*v for v in delta)
                fraction = (sum((hit[i]-first[i])*delta[i] for i in range(3))/length2
                            if length2 > 0. else -1.)
                closest = tuple(first[i]+fraction*delta[i] for i in range(3))
                valid = (-.0001 <= fraction <= 1.0001 and
                         _distance_sq(hit, closest) <= .1*.1)
                if not valid:
                    proof['blocked'] = True
                    break
            if target_hit is not None and (hit is None or target_hit[0] <= fraction):
                if proof['stage'] == 0:
                    if target_hit[2] != proof['target'].id:
                        proof['front_vehicle'] = target_hit[2]
                        proof['centre_path'] = tuple(path[:cursor+1]) + (target_hit[1],)
                        break
                    proof['centre_path'] = tuple(path[:cursor+1]) + (target_hit[1],)
                    proof['stage'], proof['cursor'] = 1, 0
                    continue
                proof['path'] = tuple(path[:cursor+1]) + (target_hit[1],)
                proof['terminal_impact'] = target_hit[3] if len(target_hit) > 3 else target_hit[1]
                if len(target_hit) > 3:
                    proof['terminal_layer'], proof['terminal_result'] = target_hit[4:6]
                proof['terminal_kind'] = 'vehicle'
                proof['terminal_vehicle'] = target_hit[2]
                proof['done'] = True
                break
            if hit is not None:
                # A scattered miss may terminate on distant scenery. Reject
                # muzzle-adjacent obstructions, but never keep rolling until
                # a favourable scattered hit happens to clear the world.
                if proof['stage'] == 0 or _distance_sq(hit, path[0]) <= 25.*25.:
                    proof['blocked'] = True
                    break
                proof['path'] = tuple(path[:cursor+1]) + (hit,)
                proof['terminal_impact'] = hit
                proof['terminal_kind'] = 'world'
                proof['done'] = True
                break
            proof['cursor'] += 1
        if proof['stage'] == 1 and proof['cursor'] >= len(proof['path'])-1:
            proof['done'] = True
        return used

    @staticmethod
    def _launch_path(origin, velocity, gravity, maximum):
        """Trace the same wire launch to its real flight/range limit.

        Scattering can miss the selected tank, so its aiming plane cannot be
        the path endpoint. Native world/plate queries may shorten this path
        only after proving a real first contact. The neutral projectile law
        clips accumulated travelled distance, not horizontal target range.
        """
        if sum(v*v for v in velocity) <= 0. or maximum <= 0.:
            return (), ()
        count = int(math.ceil(ballistics.PROJECTILE_MAX_FLIGHT_SECONDS/.12))
        path, times, distance = [origin], [0.], 0.
        for step in range(1, count+1):
            end_time = min(ballistics.PROJECTILE_MAX_FLIGHT_SECONDS, step*.12)
            first, last, actual_time, terminal = projectile_runtime.prepare_chord(
                origin, velocity, (0., -gravity, 0.), 0., times[-1], end_time,
                maximum, distance)
            distance += math.sqrt(_distance_sq(first, last))
            path.append(_point(last))
            times.append(actual_time)
            if terminal:
                break
        return tuple(path), tuple(times)

    def _reject_front(self, proof, solution, now, used, target_queries=0):
        front = proof['front_vehicle']
        self.front_contact = (proof['target'], front, solution, now)
        return self._result('rejected', 'auto_front_vehicle',
            front_vehicle=front, world_chords=used, target_queries=target_queries)

    def prepare(self, context, entity, gun, raw_ray, dispersion, source_shot,
                now, burst=None, range_origin=None):
        """Return ready/pending/rejected without sending or debiting ammunition."""
        if not context.get('automatic'):
            return self._result('rejected', 'auto_not_owned')
        now = float(now)
        try:
            raw_ray = (_point(raw_ray[0]), _point(raw_ray[1]))
            reason, target, solution = self._fresh(context, raw_ray, source_shot, now)
            if target is None or self.terminal_reason(reason):
                self.pending = None
                return self._result('rejected', reason or 'auto_target_lost')
            if reason is not None:
                return self._result('pending', reason, world_chords=0)
            key = self._identity(context, entity, gun, target, burst)
            candidate = self.pending
            if candidate is None or candidate['identity'] != key:
                candidate = dict(identity=key, draw=_ScatterDraw(), proof=None,
                    restarts=0, full_proof=False,
                    penetration_factor=lan_client._projectile_wire_round(
                        combat_rules.sample_penetration_factor()))
                self.pending = candidate
            owner = self.control.owner
            canonical = lan_client._projectile_wire_round
            range_origin = tuple(canonical(value) for value in (
                owner.local_pose()[0] if range_origin is None else range_origin))
            target_signature, target_body, target_chassis = self._target_pose(target)
            target_velocity = tuple(solution['velocity'])
            collision_roster = self._collision_roster(target, target_velocity, now)
            if collision_roster is None:
                return self._result('pending', 'auto_collision_roster_limit', world_chords=0)
            roster_signature = tuple(row['signature'] for row in collision_roster)
            perfect = bool(owner._config and owner._config.get('perfect_accuracy', False))
            direction = candidate['draw'].scatter(owner, gun, raw_ray[1], perfect, dispersion)
            geometry = (raw_ray, float(dispersion), perfect, tuple(solution['point']),
                        float(source_shot['speed']), float(source_shot['gravity']),
                        float(source_shot['maxDistance']), target_signature,
                        target_velocity, range_origin, roster_signature)
            proof = candidate['proof']
            scene = self._scene()
            if (proof is None or proof['geometry'] != geometry or proof['scene'] != scene or
                    proof['done'] and now-proof['completed'] > COMPLETED_PROOF_TTL):
                if proof is not None and (proof['geometry'] != geometry or proof['scene'] != scene):
                    # Exact proofs cannot survive a moving barrel/target or a
                    # scene revision. After two productive restarts, finish one
                    # bounded synchronous proof instead of starving the shot
                    # forever at cursor zero. Retain the same random draw.
                    self._restart(candidate, proof)
                raw_path = artillery_path(raw_ray[0], solution['point'], source_shot, raw_ray[1])
                raw_step = 0.
                if len(raw_path) >= 2 and getattr(self.control, 'direct_engagement', None) is not None:
                    horizontal = sum(raw_ray[1][i]**2 for i in (0, 2))
                    flight = sum((solution['point'][i]-raw_ray[0][i])*raw_ray[1][i]
                                 for i in (0, 2))/(source_shot['speed']*horizontal)
                    raw_step = flight/(len(raw_path)-1)
                origin = tuple(canonical(value) for value in raw_ray[0])
                velocity = tuple(canonical(value*source_shot['speed']) for value in direction)
                gravity = canonical(source_shot['gravity'])
                maximum = canonical(source_shot['maxDistance'])
                path, times = self._launch_path(origin, velocity, gravity, maximum)
                if (len(raw_path) < 2 or len(path) < 2 or
                        len(raw_path)+len(path)-2 > MAX_PROOF_CHORDS):
                    return self._result('pending', 'auto_path_unavailable', world_chords=0)
                from ..entities.remote_vehicle import vehicle_target_bounds_at_matrix
                for row in collision_roster:
                    row['bounds'] = vehicle_target_bounds_at_matrix(row['target'], row['body'],
                        owner._runtime.math, chassis_matrix=row['chassis'])
                    if row['bounds'] is None:
                        return self._result('pending', 'auto_geometry_unavailable', world_chords=0)
                proof = dict(geometry=geometry, raw_ray=raw_ray, raw_path=raw_path, raw_step=raw_step,
                    path=path, direction=direction, origin=origin, velocity=velocity,
                    gravity=gravity, maximum=maximum, stage=0,
                    cursor=0, done=False, blocked=False, created=now, scene=scene,
                    completed=None, times=times, target=target, target_body=target_body,
                    target_chassis=target_chassis, target_signature=target_signature,
                    target_velocity=target_velocity, collision_roster=collision_roster,
                    roster_signature=roster_signature,
                    target_queries=0, shot=source_shot, range_origin=range_origin,
                    material_trace=getattr(self.control, 'direct_engagement', None) is not None,
                    penetration_factor=candidate['penetration_factor'])
                candidate['proof'] = proof
            splash = (combat_rules.he_radius(source_shot)
                      if combat_rules.is_he(source_shot) else 0.)
            # Check the full current centre lane before native work. A random
            # ray can terminate on scenery earlier than its nominal endpoint,
            # so its friendly/splash check follows that exact terminal proof.
            if not proof.get('material_trace') or proof.get('front_vehicle') is not None:
                reason, blocker = self._check_lane(target, proof.get('centre_path', proof['raw_path']), 'raw_path')
                if reason is not None:
                    return self._result('pending', reason, candidate, world_chords=0, blocker=blocker)
            if proof.get('front_vehicle') is not None:
                return self._reject_front(proof, solution, now, 0)
            if proof['blocked']:
                # Scenery may be destroyed. Re-prove this same random shot,
                # not a newly sampled one, on the next bounded attempt.
                proof.pop('centre_path', None)
                proof.update(stage=0, cursor=0, blocked=False, done=False)
            queries_before = proof['target_queries']
            if not proof['done']:
                full = candidate['full_proof']
                mode = 'complete' if full else 'sliced'
                if now < self._next_probe or full and now < self._next_full_probe:
                    return self._result('pending', 'auto_proof_pending', candidate, world_chords=0)
                self._next_probe = now + PROBE_INTERVAL
                if full:
                    self._next_full_probe = now + FULL_PROOF_INTERVAL
                used = self._advance(proof, MAX_PROOF_CHORDS if full else WORLD_CHORDS_PER_ATTEMPT)
                proof['mode'] = mode
                if self._scene() != scene or self.pending is not candidate:
                    if self.pending is candidate:
                        self._restart(candidate, proof)
                    candidate['proof'] = None
                    return self._result('pending', 'auto_world_changed', candidate, world_chords=used,
                        target_queries=proof['target_queries']-queries_before)
                if proof.get('front_vehicle') is not None:
                    reason, blocker = self._check_lane(target, proof.get('centre_path', proof['raw_path']), 'raw_path')
                    if reason is not None:
                        return self._result('pending', reason, candidate, world_chords=used,
                                            blocker=blocker,
                                            target_queries=proof['target_queries']-queries_before)
                    return self._reject_front(proof, solution, now, used,
                        proof['target_queries']-queries_before)
                if proof['blocked']:
                    return self._result('pending', 'auto_world_blocked', candidate,
                        world_chords=used, proof_mode=mode,
                        target_queries=proof['target_queries']-queries_before)
                if not proof['done']:
                    return self._result('pending', 'auto_proof_pending', candidate,
                        world_chords=used, proof_mode=mode,
                        target_queries=proof['target_queries']-queries_before)
                proof['completed'] = float(owner._clock())
            else:
                used = 0
            reason, blocker = self._dynamic_reason(target, proof, splash)
            if reason is not None:
                return self._result('pending', reason, candidate, world_chords=used, blocker=blocker,
                    proof_mode=proof.get('mode'),
                    target_queries=proof['target_queries']-queries_before)
            candidate.update(target=target, source_shot=source_shot, splash=splash,
                             now=now, solution=solution)
            return self._result('ready', 'clear', candidate, origin=proof['origin'],
                direction=proof['direction'], velocity=proof['velocity'], path=proof['path'], raw_ray=raw_ray,
                penetration_factor=candidate['penetration_factor'], target=target,
                world_chords=used, terminal_impact=proof.get('terminal_impact'),
                terminal_kind=proof.get('terminal_kind'), proof_mode=proof.get('mode'),
                target_queries=proof['target_queries']-queries_before,
                terminal_vehicle=proof.get('terminal_vehicle'),
                terminal_layer=proof.get('terminal_layer'),
                terminal_result=proof.get('terminal_result'),
                collision_vehicles=len(collision_roster))
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return self._result('pending', 'auto_geometry_unavailable', world_chords=0)

    def validate(self, token, context, entity, gun, now, burst=None, launch=None):
        """Recheck current owners/native ray after every reentrant boundary."""
        if token is None or token is not self.pending or not token.get('proof', {}).get('done'):
            return 'auto_candidate_changed'
        owner, proof = self.control.owner, token['proof']
        try:
            now = float(owner._clock())
            if (self._scene() != proof['scene'] or
                    not 0. <= now-proof['completed'] <= COMPLETED_PROOF_TTL):
                token['proof'] = None
                return 'auto_world_changed'
            if launch is not None and (tuple(launch['origin']) != proof['origin'] or
                    tuple(launch['velocity']) != proof['velocity'] or
                    launch['gravity'] != proof['gravity'] or
                    launch['max_distance'] != proof['maximum'] or
                    tuple(launch['range_origin']) != proof['range_origin'] or
                    launch['penetration_factor'] != proof['penetration_factor']):
                return 'auto_launch_changed'
            native = owner._mutable_shot_ray()
            raw_ray = (_point(native[0]), _point(native[1]))
            if (raw_ray != proof['raw_ray'] or
                    float(owner._native_dispersion_angle()) != proof['geometry'][1]):
                token['proof'] = None
                return 'auto_pose_changed'
            reason, target, fresh = self._fresh(context, raw_ray, token['source_shot'], now)
            if reason is not None:
                return reason
            roster = self._collision_roster(target, fresh['velocity'], now)
            if (self._identity(context, entity, gun, target, burst) != token['identity'] or
                    tuple(fresh['point']) != tuple(token['solution']['point']) or
                    tuple(fresh['velocity']) != proof['target_velocity'] or
                    self._target_pose(target)[0] != proof['target_signature'] or roster is None or
                    tuple(row['signature'] for row in roster) != proof['roster_signature']):
                token['proof'] = None
                return 'auto_target_changed'
            reason, blocker = self._dynamic_reason(target, proof, token['splash'])
            if reason is not None:
                self.receipt['blocker'] = blocker
                if getattr(self.control, 'direct_engagement', None) is not None:
                    self.receipt.update(self.lane.receipt())
                return reason
            if (token is not self.pending or not self.control.active or
                    self.control.control_generation != context.get('generation')):
                return 'auto_candidate_changed'
            if self._scene() != proof['scene']:
                token['proof'] = None
                return 'auto_world_changed'
            return None
        except (AttributeError, TypeError, ValueError, KeyError, IndexError, RuntimeError):
            return 'auto_geometry_unavailable'

    def deferred(self, reason):
        """Keep a public wait receipt coherent after a final-boundary failure."""
        receipt = dict(self.receipt)
        receipt.update(status='pending', reason=reason)
        self.receipt = receipt

    def rejected(self, reason):
        self.pending = None
        self._result('rejected', reason)

    def committed(self, token):
        if self.pending is token:
            self.pending = None
        receipt = dict(self.receipt)
        receipt.update(status='committed', reason='committed')
        self.receipt = receipt
