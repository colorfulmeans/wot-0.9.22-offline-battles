"""One shared tactical admission per new physical trigger.

This owner has no burst-tail state, cancellation, timeout or continuation API.
It proves the first launch against the observed native gun/target and retains
one random draw while that uncommitted launch is being proved. The physical
gun owns all subsequent shells, irrespective of target or controller changes.
"""
from __future__ import division

import math
import random

from .. import ballistics, combat_rules, projectile_runtime, shot_geometry
from ..projectile_wire import round_scalar
from .attack_policy import (PENETRATION_FACTOR_65, _distance_sq, _mechanical,
                            _point, native_source_pose, native_target_pose,
                            native_geometry_complete, native_lane_geometry_complete)
from .actor_observation import observation


WORLD_CHORDS_PER_ATTEMPT = 24
MAX_PROOF_CHORDS = 334
PROBE_INTERVAL = .05
FULL_PROOF_INTERVAL = .5
COMPLETED_PROOF_TTL = .2
MAX_COLLISION_ROSTER = 30


def barrel_path(origin, direction, shot, point):
    """Sample the current real barrel to the selected target's aiming plane."""
    speed, gravity = float(shot['speed']), abs(float(shot['gravity']))
    horizontal = direction[0] ** 2 + direction[2] ** 2
    if speed <= 0. or horizontal <= 1.e-8:
        return (), (), None
    flight = sum((point[index] - origin[index]) * direction[index]
                 for index in (0, 2)) / (speed * horizontal)
    if not 0. < flight <= ballistics.PROJECTILE_MAX_FLIGHT_SECONDS:
        return (), (), None
    if speed * flight > float(shot['maxDistance']) + 1.e-6:
        return (), (), None
    yaw = math.atan2(direction[0], direction[2])
    pitch = math.atan2(-direction[1], math.sqrt(horizontal))
    path = ballistics.ballistic_path(origin, yaw, pitch, speed, gravity, flight)
    times = tuple(flight * index / (len(path) - 1) for index in range(len(path)))
    return path, times, flight


class _ScatterDraw(object):
    """Replay the same random inputs through the unchanged gun sampler."""

    def __init__(self):
        self.normal = random.gauss(0., 1.)
        self.uniforms = []
        self.cursor = 0

    def gauss(self, mean, sigma):
        return mean + sigma * self.normal

    def uniform(self, low, high):
        if self.cursor == len(self.uniforms):
            self.uniforms.append(random.uniform(0., 1.))
        value = self.uniforms[self.cursor]
        self.cursor += 1
        return low + (high - low) * value

    def scatter(self, owner, gun, direction, perfect, dispersion):
        self.cursor = 0
        result = owner._vector(direction)
        result.normalise()
        gun.scatter(result, perfect, gauss=self.gauss, uniform=self.uniform,
                    dispersion_angle=dispersion)
        return _point(result)


class TriggerAdmission(object):

    def __init__(self, control):
        self.control = control
        self.owner = control.owner
        self.physical = observation(control.runtime)
        self.reset()

    def reset(self):
        self.pending = None
        self.receipt = dict(status='idle', reason='idle')
        self._next_probe = float('-inf')
        self._next_full_probe = float('-inf')

    @staticmethod
    def terminal_reason(reason):
        return reason in ('auto_not_owned', 'auto_target_lost',
                          'auto_owner_changed', 'auto_shell_changed',
                          'auto_tail_not_admissible')

    def _result(self, status, reason, token=None, **fields):
        result = dict(status=status, reason=reason, token=token)
        result.update(fields)
        self.receipt = dict((key, value) for key, value in result.items()
                            if key not in ('token', 'target', 'path', 'raw_ray'))
        return result

    def _target(self, context):
        value = context.get('target')
        runtime = self.control.runtime
        target = runtime.target_entity(value) if isinstance(value, dict) else self.owner._server_entity(value)
        if target is None or not getattr(target, 'isStarted', False) or not target.isAlive():
            return None
        bot = getattr(runtime, 'actor_kind', 'human') == 'bot'
        if bot:
            # The hidden worker can render both teams. Rendering by its
            # observer avatar is not a spotting receipt for this BOT.
            visible = any(runtime.target_entity(row) is target
                          for row in runtime.visible_targets()
                          if row.get('alive', True) and row.get('visible', True))
            if not visible:
                return None
        for record in self.owner._records.values():
            if record.get('engine_id') != target.id:
                continue
            if (record.get('ready') and not record.get('tombstone') and
                    not self.physical.owns_record(record) and (bot or record.get('spot_visible')) and
                    int((record.get('state') or {}).get('team', 0)) != self.physical.actor_team):
                return target
        return None

    def _scene(self):
        owner = self.owner
        sensor = getattr(owner, '_destructibles', None)
        revision = getattr(sensor, '_spatial_revision_1513', None)
        return (id(owner._avatar), owner._avatar.spaceID, owner._generation,
                id(sensor), revision() if callable(revision) else None)

    def _fresh(self, context, entity, gun, raw_ray, shot, now):
        control, owner = self.control, self.owner
        if (not context.get('automatic') or not control.active or control.closed or
                control.control_generation != context.get('generation') or
                not self.physical.control_current(control)):
            return 'auto_owner_changed', None, None
        if gun is not control.runtime.gun or gun.shot_index != context.get('shell_index', gun.shot_index):
            return 'auto_shell_changed', None, None
        target = self._target(context)
        if target is None:
            return 'auto_target_lost', None, None
        solution = context.get('solution')
        if not isinstance(solution, dict):
            return 'auto_solution_unavailable', target, None
        solution = dict(solution)
        solution['point'] = _point(solution.get('point', solution.get('aim_position')))
        solution['velocity'] = _point(solution.get('velocity', (0., 0., 0.)))
        signature = native_target_pose(owner, target)[0]
        if solution.get('target_pose') is not None and solution['target_pose'] != signature:
            return 'auto_target_pose_changed', target, solution
        candidate = context.get('candidate')
        artillery = 'SPG' in (entity.typeDescriptor.type.tags or ())
        if not artillery:
            if solution.get('source_pose') != native_source_pose(control.runtime, raw_ray[0]):
                return 'auto_source_pose_changed', target, solution
            if not isinstance(candidate, dict) or candidate.get('shell_index') != gun.shot_index:
                return 'auto_candidate_unavailable', target, solution
            if candidate.get('mode') == 'he_fallback':
                if (not combat_rules.is_he(shot) or candidate.get('contact') is not True or
                        candidate.get('expected_damage') is None):
                    return 'auto_he_contact_unknown', target, solution
            elif candidate.get('armor') != 'passed':
                return 'auto_penetration_unproved', target, solution
        reach = _mechanical(entity.typeDescriptor, raw_ray[1],
                            native_source_pose(control.runtime, raw_ray[0])[1])
        if reach['status'] != 'reachable':
            return 'auto_gun_laying', target, solution
        path, times, flight = barrel_path(raw_ray[0], raw_ray[1], shot, solution['point'])
        if not path:
            return 'auto_actual_barrel_unavailable', target, solution
        # A point inside a broad target bbox is not sufficient; the centre
        # flight must reach this selected point before its exact plate proof.
        if _distance_sq(path[-1], solution['point']) > .30 ** 2:
            return 'auto_gun_laying', target, solution
        solution.update(raw_path=path, raw_times=times, flight_time=flight,
                        target_pose=signature, artillery=artillery)
        return None, target, solution

    def _collision_roster(self, target, velocity, now):
        from ..entities.remote_vehicle import vehicle_target_bounds_at_matrix
        owner, runtime, rows = self.owner, self.control.runtime, []
        observed = dict((row.get('engine_id'), row) for row in runtime.visible_targets())
        policy = getattr(runtime, 'attack_policy', None)
        measurements = getattr(getattr(policy, 'evaluator', None), 'observations', {})
        bot = getattr(runtime, 'actor_kind', 'human') == 'bot'
        for record in owner._records.values():
            if (self.physical.owns_record(record) or record.get('tombstone') or not record.get('ready') or
                    (record.get('engine_id') not in observed if bot else not record.get('spot_visible')) or
                    int((record.get('state') or {}).get('team', 0)) == self.physical.actor_team):
                continue
            other = owner._server_entity(record.get('engine_id'))
            if other is None or not getattr(other, 'isStarted', False) or not other.isAlive():
                continue
            if not native_geometry_complete(other):
                return None
            if len(rows) >= MAX_COLLISION_ROSTER:
                return None
            signature, body, chassis = native_target_pose(owner, other, record)
            raw = observed.get(other.id, {})
            key = (raw.get('kind'), raw.get('network_id', raw.get('id')))
            sample = measurements.get(key)
            measured = (sample[2] if sample is not None and 0. <= now - sample[0] <= .35
                        else raw.get('velocity', (0., 0., 0.)))
            speed = tuple(velocity) if other is target else _point(measured)
            bounds = vehicle_target_bounds_at_matrix(other, body, owner._runtime.math,
                                                      chassis_matrix=chassis)
            if bounds is None:
                return None
            rows.append(dict(target=other, record=record, body=body, chassis=chassis,
                             velocity=speed, bounds=bounds,
                             actor_key=(raw.get('kind') or
                                 ('bot' if record.get('kind') == 'bot' else 'human'),
                                 raw.get('network_id', record.get('network_id'))),
                             team=int((record.get('state') or {}).get(
                                 'team', record.get('team', 0))),
                             signature=(other.id, signature, speed)))
        rows.sort(key=lambda row: row['target'].id)
        return rows

    def _contact(self, proof, first, last, first_time, last_time, centre=False):
        """Find the first native collision, preserving material traversal."""
        from ..entities.remote_vehicle import collide_vehicle_at_matrix
        owner, candidates, best = self.owner, [], None
        for row in proof['roster']:
            velocity = row['velocity']
            start = tuple(first[index] - velocity[index] * first_time for index in range(3))
            end = tuple(last[index] - velocity[index] * last_time for index in range(3))
            length = math.sqrt(_distance_sq(start, end))
            entry = shot_geometry.segment_box_entry_distance(start, end, row['bounds'])
            if entry is not None and length > 0.:
                candidates.append((entry / length, row, start, end, length))
        candidates.sort(key=lambda item: item[0])
        for broad_fraction, row, start, end, length in candidates:
            if best is not None and broad_fraction > best['fraction']:
                break
            proof['target_queries'] += 1
            hits = collide_vehicle_at_matrix(row['target'], row['body'],
                owner._vector(start), owner._vector(end), owner._runtime.math,
                chassis_matrix=row['chassis'])
            if not hits:
                continue
            entry_distance = min(float(hit.dist) for hit in hits)
            trace_end = combat_rules.vehicle_material_trace_end(proof['shot'], entry_distance)
            material_end = end
            if trace_end > length + 1.e-6 and not combat_rules.is_he(proof['shot']):
                material_end = tuple(start[index] + (end[index] - start[index]) * trace_end / length
                                     for index in range(3))
                proof['target_queries'] += 1
                extended = collide_vehicle_at_matrix(row['target'], row['body'],
                    owner._vector(start), owner._vector(material_end), owner._runtime.math,
                    chassis_matrix=row['chassis'])
                if extended:
                    hits = extended
            retained = combat_rules.vehicle_material_hits(hits, trace_end)
            fraction = entry_distance / length
            if not 0. <= fraction <= 1.:
                raise ValueError('native entry lies outside its queried chord')
            point = tuple(first[index] + fraction * (last[index] - first[index]) for index in range(3))
            distance = math.sqrt(_distance_sq(proof['range_origin'], point))
            factor = PENETRATION_FACTOR_65 if centre else proof['penetration_factor']
            contact = combat_rules.resolve_armor_contact(proof['shot'], distance, retained,
                                                         penetration_factor=factor)
            if not centre and contact is None and not combat_rules.is_he(proof['shot']):
                # Traversing only penetrated external plates is not a
                # terminal hit. Continue this sampled ray to the next vehicle,
                # world obstacle or range boundary before friendly checks.
                continue
            item = dict(fraction=fraction, point=point, row=row, contact=contact,
                        start=owner._vector(start), end=owner._vector(material_end),
                        hits=hits, distance=distance)
            if best is None or fraction < best['fraction']:
                best = item
        return best

    def _centre_verdict(self, proof, contact):
        if contact['row']['target'] is not proof['target']:
            return 'auto_front_vehicle'
        solution, candidate = proof['solution'], proof.get('candidate') or {}
        if solution['artillery']:
            return None
        armor = contact['contact']
        if candidate.get('mode') != 'he_fallback':
            return (None if armor is not None and armor['layer'] == 'structural' and
                    armor['result'] == 2 else 'auto_actual_barrel_armour')
        if armor is not None and armor['layer'] == 'structural' and armor['result'] == 2:
            return None
        row = contact['row']
        # Map the observed local chord back to the target's currently visible
        # frame. The native HE surface search must not mix an observed body
        # with the predicted future impact point.
        direction = contact['end'] - contact['start']
        length = float(direction.length)
        if length <= 1.e-9:
            return 'auto_he_contact_unknown'
        direction.normalise()
        hit_distance = (float(armor['distance']) if armor is not None else
                        min(float(hit.dist) for hit in contact['hits']))
        impact = tuple(float(contact['start'][index]) + float(direction[index]) * hit_distance
                       for index in range(3))
        kind = getattr(self.control.runtime, 'actor_kind', 'human')
        blast = self.owner._projectile_he_blast_contact(
            dict(shooter_kind='player' if kind == 'human' else kind),
            row['record'], row['target'], proof['shot'], impact,
            combat_rules.shell_nominal_damage(proof['shot']),
            state=dict(velocity=_point(direction), gravity=(0., 0., 0.), elapsed=0.),
            seed=(contact['start'], contact['end'], contact['hits']))
        return None if blast is not None else 'auto_he_contact_unknown'

    def _probe(self, first, last):
        hit = self.owner._runtime.bigworld.wg_collideSegment(
            self.owner._avatar.spaceID, self.owner._vector(first), self.owner._vector(last), 128)
        return None if hit is None else _point(hit[0])

    def _advance(self, proof, budget):
        used = 0
        while used < budget and not proof['done'] and proof.get('refusal') is None:
            centre = proof['stage'] == 0
            path = proof['raw_path'] if centre else proof['path']
            times = proof['raw_times'] if centre else proof['times']
            index = proof['cursor']
            if index >= len(path) - 1:
                if centre:
                    proof['refusal'] = 'auto_actual_barrel_miss'
                else:
                    proof['done'] = True
                break
            first, last = path[index], path[index + 1]
            hit = self._probe(first, last)
            used += 1
            target = self._contact(proof, first, last, times[index], times[index + 1], centre)
            fraction = None
            if hit is not None:
                delta = tuple(last[axis] - first[axis] for axis in range(3))
                length2 = sum(value * value for value in delta)
                fraction = (sum((hit[axis] - first[axis]) * delta[axis] for axis in range(3)) / length2
                            if length2 > 0. else -1.)
                closest = tuple(first[axis] + fraction * delta[axis] for axis in range(3))
                if not -.0001 <= fraction <= 1.0001 or _distance_sq(closest, hit) > .1 ** 2:
                    proof['refusal'] = 'auto_world_geometry_unknown'
                    break
            if target is not None and (hit is None or target['fraction'] <= fraction):
                if centre:
                    proof['centre_path'] = tuple(path[:index + 1]) + (target['point'],)
                    proof['refusal'] = self._centre_verdict(proof, target)
                    if proof['refusal'] == 'auto_front_vehicle':
                        row = target['row']
                        # Native entity ids and tactical actor ids are not
                        # interchangeable. Keep the actual first collision so
                        # the same admitted enemy domain can review it; this
                        # receipt neither selects it nor permits a shot.
                        proof['blocker'] = dict(kind='vehicle', point=target['point'],
                            vehicle_id=row['target'].id, actor_key=row['actor_key'],
                            team=row['team'], hostile=(
                                row['team'] != self.physical.actor_team
                                if row['team'] in (1, 2) else None),
                            target_pose=row['signature'][1])
                    proof['stage'], proof['cursor'] = 1, 0
                    continue
                proof['path'] = tuple(path[:index + 1]) + (target['point'],)
                proof['terminal_impact'] = target['point']
                proof['terminal_kind'] = 'vehicle'
                proof['terminal_vehicle'] = target['row']['target'].id
                proof['done'] = True
                break
            if hit is not None:
                if centre or _distance_sq(hit, path[0]) <= 25. ** 2:
                    proof['refusal'] = 'auto_world_blocked'
                    proof['blocker'] = dict(kind='world', point=hit)
                    break
                proof['path'] = tuple(path[:index + 1]) + (hit,)
                proof['terminal_impact'] = hit
                proof['terminal_kind'] = 'world'
                proof['done'] = True
                break
            proof['cursor'] += 1
        if proof['stage'] == 1 and proof['cursor'] >= len(proof['path']) - 1:
            proof['done'] = True
        return used

    def _lane(self, path, splash=0.):
        runtime = self.control.runtime
        if not native_lane_geometry_complete(runtime):
            return 'auto_lane_geometry_unknown', dict(reason='attached_collision_unavailable')
        verdict = runtime.geometry._bot_friendly_path_verdict(runtime.current_source(), path, splash)
        if isinstance(verdict, dict) and verdict.get('clear') is True:
            return None, None
        if (isinstance(verdict, dict) and verdict.get('blocked') is True and
                verdict.get('blocker_kind') in ('wreck', 'debris')):
            return 'auto_world_blocked', verdict
        if isinstance(verdict, dict) and verdict.get('blocker_team') is not None:
            return 'auto_friendly_lane' if splash <= 0. else 'auto_friendly_splash', verdict
        return 'auto_lane_geometry_unknown', verdict

    def _dynamic(self, proof):
        reason, blocker = self._lane(proof.get('centre_path', proof['raw_path']))
        if reason is not None:
            return reason, blocker
        splash = combat_rules.he_radius(proof['shot']) if proof.get('terminal_impact') is not None else 0.
        return self._lane(proof['path'], splash)

    @staticmethod
    def _launch_path(origin, velocity, gravity, maximum):
        try:
            origin, velocity = _point(origin), _point(velocity)
            gravity, maximum = float(gravity), float(maximum)
            if (sum(value * value for value in velocity) <= 1.e-12 or
                    maximum <= 0. or gravity < 0. or
                    any(math.isnan(value) or math.isinf(value) for value in (gravity, maximum))):
                return (), ()
        except (TypeError, ValueError, IndexError, KeyError):
            return (), ()
        path, times, travelled = [origin], [0.], 0.
        count = int(math.ceil(ballistics.PROJECTILE_MAX_FLIGHT_SECONDS / .12))
        for index in range(1, count + 1):
            end = min(ballistics.PROJECTILE_MAX_FLIGHT_SECONDS, index * .12)
            first, last, actual, terminal = projectile_runtime.prepare_chord(
                origin, velocity, (0., -gravity, 0.), 0., times[-1], end, maximum, travelled)
            travelled += math.sqrt(_distance_sq(first, last))
            path.append(_point(last))
            times.append(actual)
            if terminal:
                break
        return tuple(path), tuple(times)

    def _feedback(self, context, reason, blocker=None):
        policy = getattr(self.control.runtime, 'attack_policy', None)
        if policy is not None:
            policy.admission_failed(context.get('candidate'), reason, blocker)

    def prepare(self, context, entity, gun, raw_ray, dispersion, source_shot,
                now, range_origin=None):
        if not context.get('automatic'):
            return self._result('rejected', 'auto_not_owned')
        if self.physical.trigger_active():
            return self._result('rejected', 'auto_tail_not_admissible')
        try:
            now = float(now)
            raw_ray = (_point(raw_ray[0]), _point(raw_ray[1]))
            reason, target, solution = self._fresh(context, entity, gun, raw_ray, source_shot, now)
            if reason is not None:
                if self.terminal_reason(reason):
                    self.pending = None
                self._feedback(context, reason)
                return self._result('rejected' if self.terminal_reason(reason) else 'pending', reason)
            key = (self.owner._generation, self.control.control_generation,
                   id(gun), gun.shot_index, tuple(gun.ammo), gun.clip)
            candidate = self.pending
            if candidate is None or candidate['weapon_key'] != key:
                candidate = dict(weapon_key=key, draw=_ScatterDraw(), proof=None,
                    restarts=0, penetration_factor=round_scalar(combat_rules.sample_penetration_factor()))
                self.pending = candidate
            roster = self._collision_roster(target, solution['velocity'], now)
            if roster is None:
                return self._result('pending', 'auto_collision_geometry_unknown')
            roster_signature = tuple(row['signature'] for row in roster)
            perfect = bool(getattr(self.control.runtime, 'actor_kind', 'human') == 'human' and
                           self.owner._config and self.owner._config.get('perfect_accuracy', False))
            direction = candidate['draw'].scatter(self.owner, gun, raw_ray[1], perfect, dispersion)
            origin = tuple(round_scalar(value) for value in raw_ray[0])
            velocity = tuple(round_scalar(value * float(source_shot['speed'])) for value in direction)
            gravity = round_scalar(float(source_shot['gravity']))
            maximum = round_scalar(float(source_shot['maxDistance']))
            range_origin = tuple(round_scalar(value) for value in (
                self.physical.source_pose()[0] if range_origin is None else range_origin))
            geometry = (raw_ray, float(dispersion), perfect, solution['point'],
                        solution['target_pose'], solution['velocity'], roster_signature,
                        range_origin, velocity, gravity, maximum,
                        (context.get('candidate') or {}).get('mode'), id(target))
            scene = self._scene()
            proof = candidate['proof']
            if (proof is None or proof['geometry'] != geometry or proof['scene'] != scene or
                    proof.get('refusal') is not None or
                    proof['done'] and now - proof['completed'] > COMPLETED_PROOF_TTL):
                if proof is not None and (proof['cursor'] or proof['stage']):
                    candidate['restarts'] += 1
                path, times = self._launch_path(origin, velocity, gravity, maximum)
                if len(path) < 2:
                    return self._result('pending', 'auto_actual_barrel_unavailable')
                if len(path) + len(solution['raw_path']) - 2 > MAX_PROOF_CHORDS:
                    return self._result('pending', 'auto_path_budget_exceeded')
                proof = dict(geometry=geometry, raw_ray=raw_ray,
                    raw_path=solution['raw_path'], raw_times=solution['raw_times'],
                    path=path, times=times, origin=origin, velocity=velocity,
                    gravity=gravity, maximum=maximum, range_origin=range_origin,
                    stage=0, cursor=0, done=False, refusal=None, completed=None,
                    created=now, scene=scene, target=target, solution=solution,
                    candidate=context.get('candidate'), roster=roster,
                    roster_signature=roster_signature, target_queries=0,
                    shot=source_shot, penetration_factor=candidate['penetration_factor'])
                candidate['proof'] = proof
            full = candidate['restarts'] >= 2
            used = 0
            if not proof['done']:
                if now < self._next_probe or full and now < self._next_full_probe:
                    return self._result('pending', 'auto_proof_pending', candidate, world_chords=0)
                self._next_probe = now + PROBE_INTERVAL
                if full:
                    self._next_full_probe = now + FULL_PROOF_INTERVAL
                used = self._advance(proof, MAX_PROOF_CHORDS if full else WORLD_CHORDS_PER_ATTEMPT)
                if candidate is not self.pending or self._scene() != scene:
                    candidate['proof'] = None
                    return self._result('pending', 'auto_world_changed', world_chords=used)
                if proof.get('refusal') is not None:
                    self._feedback(context, proof['refusal'], proof.get('blocker'))
                    return self._result('pending', proof['refusal'], candidate, world_chords=used,
                                        blocker=proof.get('blocker'))
                if not proof['done']:
                    return self._result('pending', 'auto_proof_pending', candidate, world_chords=used)
                proof['completed'] = float(self.owner._clock())
            reason, blocker = self._dynamic(proof)
            if reason is not None:
                self._feedback(context, reason, blocker)
                return self._result('pending', reason, candidate, world_chords=used, blocker=blocker)
            candidate.update(context=context, target=target, source_shot=source_shot,
                             solution=solution, entity=entity, gun=gun)
            return self._result('ready', 'clear', candidate,
                origin=proof['origin'], velocity=proof['velocity'],
                penetration_factor=candidate['penetration_factor'],
                world_chords=used, target_queries=proof['target_queries'],
                proof_mode='complete' if full else 'sliced',
                terminal_kind=proof.get('terminal_kind'),
                terminal_vehicle=proof.get('terminal_vehicle'))
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return self._result('pending', 'auto_geometry_unavailable')

    def validate(self, token, context, entity, gun, now, launch=None):
        if token is None or token is not self.pending or not token.get('proof', {}).get('done'):
            return 'auto_candidate_changed'
        proof = token['proof']
        try:
            now = float(self.owner._clock())
            if (self._scene() != proof['scene'] or
                    not 0. <= now - proof['completed'] <= COMPLETED_PROOF_TTL):
                token['proof'] = None
                return 'auto_world_changed'
            native = self.physical.mutable_shot_ray()
            raw_ray = (_point(native[0]), _point(native[1]))
            if (raw_ray != proof['raw_ray'] or
                    self.physical.native_dispersion_angle() != proof['geometry'][1]):
                token['proof'] = None
                return 'auto_pose_changed'
            reason, target, solution = self._fresh(context, entity, gun, raw_ray,
                                                   token['source_shot'], now)
            if reason is not None:
                return reason
            roster = self._collision_roster(target, solution['velocity'], now)
            if (target is not token['target'] or entity is not token['entity'] or gun is not token['gun'] or
                    tuple(gun.ammo) != token['weapon_key'][4] or gun.clip != token['weapon_key'][5] or
                    solution['point'] != token['solution']['point'] or
                    roster is None or tuple(row['signature'] for row in roster) != proof['roster_signature']):
                token['proof'] = None
                return 'auto_target_changed'
            if launch is not None and (
                    tuple(launch['origin']) != proof['origin'] or
                    tuple(launch['velocity']) != proof['velocity'] or
                    launch['gravity'] != proof['gravity'] or
                    launch['max_distance'] != proof['maximum'] or
                    tuple(launch['range_origin']) != proof['range_origin'] or
                    launch['penetration_factor'] != proof['penetration_factor']):
                return 'auto_launch_changed'
            reason, blocker = self._dynamic(proof)
            if reason is not None:
                self._feedback(context, reason, blocker)
                return reason
            # Friendly/native component probes can re-enter game callbacks.
            # Fence the exact source and whole collision roster again after
            # the final native probe, not merely before that callback window.
            latest = self.physical.mutable_shot_ray()
            if ((_point(latest[0]), _point(latest[1])) != proof['raw_ray'] or
                    self.physical.native_dispersion_angle() != proof['geometry'][1] or
                    not 0. <= float(self.owner._clock()) - proof['completed'] <= COMPLETED_PROOF_TTL):
                token['proof'] = None
                return 'auto_pose_changed'
            if (not solution['artillery'] and
                    solution.get('source_pose') != native_source_pose(self.control.runtime, latest[0])):
                token['proof'] = None
                return 'auto_source_pose_changed'
            final_roster = self._collision_roster(target, solution['velocity'], now)
            if (final_roster is None or
                    tuple(row['signature'] for row in final_roster) != proof['roster_signature']):
                token['proof'] = None
                return 'auto_target_changed'
            if (token is not self.pending or self._scene() != proof['scene'] or
                    not self.control.active or self.control.closed or
                    self.control.control_generation != context.get('generation') or
                    not self.physical.control_current(self.control)):
                return 'auto_owner_changed'
            return None
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return 'auto_geometry_unavailable'

    def deferred(self, reason):
        self.receipt.update(status='pending', reason=reason)

    def rejected(self, reason):
        self.pending = None
        self.receipt.update(status='rejected', reason=reason)

    def committed(self, token):
        if self.pending is token:
            self.pending = None
        self.receipt.update(status='committed', reason='trigger_started')
