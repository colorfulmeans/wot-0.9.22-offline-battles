"""Player-owned, pointwise attack planning above the copied driving laws.

This policy changes attack intent, never throttle/turn integration or physical
trigger execution.  The foreground frontier examines the mounted shell first;
the independent background frontier compares every stocked shell and target.
An armour proof and a currently clear firing lane are separate facts.
"""
from __future__ import division

import math
import time

from .. import ballistics, combat_rules, gun_pitch_limits, shot_geometry
from ..gun_mechanics import _field
from ..projectile_runtime import PROJECTILE_BROADPHASE_RADIUS


PENETRATION_PROBABILITY = .65
# Lower 35th percentile of the existing bounded, three-sigma penetration law.
# Resolving a structural penetration at this multiplier proves at least 65%
# under that law, without drawing a prospective shot's random penetration.
PENETRATION_FACTOR_65 = .9679810530375992
SEARCH_SECONDS = 8.
FOREGROUND_CANDIDATES = 2
BACKGROUND_CANDIDATES = 2
WORLD_CHORDS_PER_FRONTIER = 12
ATOMIC_CLOSE_INTERVAL = 2.
ATOMIC_WALL_SECONDS = .008
ATOMIC_WORLD_QUERIES = 128
ATOMIC_ARMOUR_BATCHES = 32
ATOMIC_CANDIDATES = 48
NEXT_EDGE_WALL_SECONDS = .004
NEXT_EDGE_CANDIDATES = 8
NATIVE_LINE_RETRY_REASONS = ('auto_front_vehicle', 'auto_lane_geometry_unknown',
                             'auto_world_geometry_unknown')
_WALL_CLOCK = getattr(time, 'perf_counter', time.time)
# A retail battle has fewer than 30 opponents, three shell slots and nine
# finite native aim samples. Custom data exceeding this explicitly reported
# budget is unknown, not an armour failure or a silently truncated universe.
ATOMIC_MAX_JOBS = 30 * 3 * 9
ATOMIC_MAX_CHORDS_PER_JOB = int(math.ceil(ballistics.PROJECTILE_MAX_FLIGHT_SECONDS / .12))
HE = 'HIGH_EXPLOSIVE'


def _point(value):
    point = tuple(float(value[index]) for index in range(3))
    if any(math.isnan(item) or math.isinf(item) for item in point):
        raise ValueError('non-finite observed geometry')
    return point


def _distance_sq(first, last):
    return sum((first[index] - last[index]) ** 2 for index in range(3))


def _target_key(target):
    return target.get('key', (target.get('kind'),
                             target.get('network_id', target.get('id'))))


def _shell_rank(shell):
    return (0 if shell.get('is_he') else 1,
            float(shell['piercing']), int(shell['index']))


def _mechanical(descriptor, direction, body):
    yaw, pitch = shot_geometry.world_direction_to_local_gun_angles(
        direction, *body)
    limits = _field(descriptor.gun, 'turretYawLimits')
    yaw_ok = limits is None or float(limits[0]) - 1.e-5 <= yaw <= float(limits[1]) + 1.e-5
    low, high = gun_pitch_limits.calc_pitch_limits(
        yaw, _field(descriptor.gun, 'pitchLimits'))
    pitch_ok = float(low) - 1.e-5 <= pitch <= float(high) + 1.e-5
    return dict(status=('reachable' if yaw_ok and pitch_ok else
                        'hull_laying' if pitch_ok else 'mechanical_limited'),
                reason=('reachable' if yaw_ok and pitch_ok else
                        'yaw_limit' if pitch_ok else 'pitch_limit'),
                local_yaw=yaw, local_pitch=pitch,
                pitch_limits=(float(low), float(high)))


def _matrix_signature(matrix):
    return (_point(matrix.translation), float(matrix.yaw),
            float(matrix.pitch), float(matrix.roll))


def native_source_pose(runtime, origin=None):
    """Exact physical barrel observation for first-trigger admission."""
    owner = runtime.owner
    entity = owner._server_entity(owner._server.vehicle_id)
    descriptor = entity.typeDescriptor
    if origin is None:
        origin = owner._mutable_shot_ray()[0]
    # Native gun limits are relative to the stabilised body. Ground chassis
    # pitch omits a siege/hydraulic aiming correction and falsely rejects
    # targets the actual native actuator has already brought into reach.
    matrix = owner._runtime.math.Matrix(owner._local_stabilised_pose())
    body = (float(matrix.yaw), float(matrix.pitch), float(matrix.roll))
    rotator = owner._avatar.gunRotator
    lay = (float(rotator.turretYaw), float(rotator.gunPitch))
    return (_point(owner.local_pose()[0]), body, _point(origin), lay,
            id(descriptor), id(descriptor.gun), _point(matrix.translation))


def _planning_pose(pose):
    # Laying the gun does not change an ideal trajectory unless the actual
    # pivot moves. Body rotation, pivot and descriptor fence its proof. The
    # raw physics position is independent of the native shot transform.
    return pose[1:3] + pose[4:6]


def _shell_signature(index, shot):
    native = combat_rules.legacy_shot(shot)
    shell = native.get('shell') or {}
    return (index, id(shot),
            tuple(float(_field(shot, name)) for name in ('speed', 'gravity', 'maxDistance')),
            tuple(native.get('piercingPower') or ()),
            tuple((name, repr(shell.get(name))) for name in (
                'kind', 'caliber', 'damage', 'explosionRadius',
                'explosionDamageFactor', 'explosionDamageAbsorptionFactor',
                'explosionEdgeDamageFactor', 'compactDescr')))


def native_geometry_complete(entity):
    """Missing attached collision data is unknown, not an absent component."""
    names = ('chassis', 'hull')
    if not bool(getattr(entity, 'isTurretDetached', False)):
        names += ('turret', 'gun')
    descriptor = getattr(entity, 'typeDescriptor', None)
    return descriptor is not None and all(callable(getattr(
        _field(_field(descriptor, name), 'hitTester'), 'localHitTest', None)) for name in names)


def native_lane_geometry_complete(runtime):
    """Close friendly/dead-hull geometry before a copied clear-lane verdict."""
    owner = runtime.owner
    for record in owner._records.values():
        if record.get('local') or record.get('tombstone') or not record.get('ready'):
            continue
        entity = owner._server_entity(record.get('engine_id'))
        if entity is None or not getattr(entity, 'isStarted', False):
            return False
        state = record.get('state') or {}
        alive = bool(entity.isAlive()) and state.get('alive', True)
        if (not alive or int(state.get('team', record.get('team', 0))) == int(owner.client.team)):
            if not native_geometry_complete(entity):
                return False
    return True


def native_target_pose(owner, target, record=None):
    """Freeze the actual foreground body/chassis/turret/gun collision pose."""
    if record is None:
        record = next((row for row in owner._records.values()
                       if row.get('engine_id') == target.id), None)
    if record is None:
        raise ValueError('observed target has no foreground record')
    body, chassis = owner._projectile_vehicle_matrices(record, target)
    matrix = owner._runtime.math.Matrix
    body, chassis = matrix(body), matrix(chassis)
    turret = matrix(target.appearance.turretMatrix)
    gun = matrix(target.appearance.gunMatrix)
    signature = (id(target), id(target.typeDescriptor),
                 _matrix_signature(body), _matrix_signature(chassis),
                 _matrix_signature(turret), _matrix_signature(gun),
                 bool(getattr(target, 'isTurretDetached', False)),
                 tuple(id(_field(_field(target.typeDescriptor, name), 'hitTester'))
                       for name in ('chassis', 'hull', 'turret', 'gun')),
                 record.get('geometry_revision'), record.get('armor_revision'))
    return signature, body, chassis


class AttackPolicy(object):
    """A complete search episode belongs to the gun, not a selected enemy.

    A snapshot lists every relevant enemy and every sample, including targets
    whose collision data is missing. Such targets have an unknown sample and
    cannot accidentally make an empty universal test mean "all armour failed".
    The background budget can run at the final trigger edge, or after control
    when there was no such edge. It runs at most once per observation.
    """

    def __init__(self, runtime, evaluator=None,
                 foreground_budget=FOREGROUND_CANDIDATES,
                 background_budget=BACKGROUND_CANDIDATES,
                 atomic_time_budget=ATOMIC_WALL_SECONDS):
        self.runtime = runtime
        self.evaluator = evaluator or NativeAttackEvaluator(runtime)
        self.foreground_budget = max(1, int(foreground_budget))
        self.background_budget = max(1, int(background_budget))
        self.atomic_time_budget = max(0., float(atomic_time_budget))
        self.atomic_clock = _WALL_CLOCK
        self.reset()

    def reset(self):
        self.frame = None
        self.rows = {}
        self._admission_blocks = {}
        self._lay_recovery = None
        self.selected = None
        self.trigger = None
        self.foreground_cursor = 0
        self.background_cursor = None
        self.search_started = None
        self.search_authority = None
        self.fallback = False
        self.next_shell = None
        self.next_plan = None
        self.next_status = 'not_observed'
        self.next_proofs = ()
        self.loading_plan = None
        self._penetration_hints = {}
        self._next_edge_at = float('-inf')
        self.next_edge_receipt = {}
        self.proof_revocations = dict(source=0, target=0, domain=0, shell=0, lane_rechecks=0)
        self.background_coverage = ()
        self.navigation_receipt = None
        self._identity = None
        self._magazine = None
        self._foreground_at = None
        self._background_at = None
        self._atomic_at = float('-inf')
        self._atomic_receipt = dict(status='not_started')
        self._move_episode = 0
        self._evidence_wait_since = None
        self._frame_invalid = False
        self._job_frame = None
        self._job_lists = {}
        self._used = dict(foreground=0, background=0, atomic=0)
        self.decision = dict(action='wait', reason='not_observed', candidate=None)

    @staticmethod
    def _key(shell, target, sample, mode):
        return int(shell['index']), _target_key(target), sample, mode

    @staticmethod
    def _stamp(frame, shell, target):
        return (frame['identity'], frame.get('planning_pose', frame['pose']),
                target.get('pose'), target.get('velocity'),
                shell.get('signature', (int(shell['index']),
                                       bool(shell.get('is_he')),
                                       float(shell['piercing']))))

    def _line_stamp(self, frame, region=None):
        local_stamp = getattr(self.evaluator, 'lane_stamp', None)
        if region is not None and callable(local_stamp):
            return local_stamp(frame, region)
        return frame.get('scene'), frame.get('line_revision')

    def _jobs(self, mode='penetration', shell_index=None):
        frame = self.frame
        if frame is None:
            return ()
        if frame is not self._job_frame:
            self._job_frame = frame
            self._job_lists = {}
        key = mode, shell_index
        if key in self._job_lists:
            return self._job_lists[key]
        jobs = []
        for shell in sorted(frame.get('shells', ()), key=_shell_rank):
            index = int(shell['index'])
            if shell_index is not None and index != shell_index:
                continue
            if (index >= len(frame['ammo']) or frame['ammo'][index] <= 0 or
                    mode == 'he_fallback' and not shell.get('is_he')):
                continue
            for target in frame.get('targets', ()):
                # Missing geometry remains an explicit unknown obligation.
                for sample in target.get('samples') or (None,):
                    jobs.append((self._key(shell, target, sample, mode),
                                 shell, target, sample, mode))
        self._job_lists[key] = tuple(jobs)
        return self._job_lists[key]

    def _current(self, job, require_line=False):
        key, shell, target, unused_sample, unused_mode = job
        row = self.rows.get(key)
        if row is None or row.get('pose_stamp') != self._stamp(self.frame, shell, target):
            return None
        if (require_line and row.get('line_stamp') !=
                self._line_stamp(self.frame, row.get('line_region'))):
            return None
        return row

    @staticmethod
    def _executable(row, mode='penetration'):
        if row is None or row.get('line') != 'clear' or row.get('mechanical') != 'reachable':
            return False
        if not isinstance(row.get('solution'), dict):
            return False
        if mode == 'he_fallback':
            return row.get('contact') is True and row.get('expected_damage') is not None
        return row.get('armor') == 'passed'

    @staticmethod
    def _matching_admission_block(blocked, stamp):
        previous = blocked['pose_stamp']
        # A native lane refusal briefly steers the search away from its
        # point. Source-only refreshes still retire every positive proof, but
        # must not erase this bounded retry on the very next observation.
        return (previous == stamp or (blocked['reason'] in NATIVE_LINE_RETRY_REASONS and
                previous[0] == stamp[0] and previous[2:] == stamp[2:]))

    @staticmethod
    def _needs_firing_position(row):
        return (row.get('line') in ('friendly_blocked', 'world_blocked') or
                row.get('mechanical') in ('hull_laying', 'mechanical_limited') or
                row.get('reason') in NATIVE_LINE_RETRY_REASONS)

    def _evaluate(self, job, now, channel, ranked_recheck=False):
        key, shell, target, sample, mode = job
        previous = self._current(job)
        evaluate = self.evaluator.evaluate
        if ranked_recheck:
            evaluate = getattr(self.evaluator, 'evaluate_ranked_recheck', evaluate)
        value = evaluate(self.frame, shell, target, sample, mode, now, channel)
        if not isinstance(value, dict):
            value = dict(armor='unknown', line='unknown', mechanical='unknown',
                         reason='evaluation_unavailable')
        row = dict(value)
        row.update(key=key, shell_index=int(shell['index']), shell=shell,
                   target=target.get('value', target), target_key=_target_key(target),
                   sample=sample, mode=mode, observed_at=now,
                   pose_stamp=self._stamp(self.frame, shell, target),
                   line_stamp=self._line_stamp(self.frame, row.get('line_region')))
        row.setdefault('armor', 'unknown')
        row.setdefault('line', 'unknown')
        row.setdefault('mechanical', 'unknown')
        row.setdefault('contact', None)
        row.setdefault('expected_damage', None)
        if previous is not None and row['line_stamp'] != previous['line_stamp']:
            self.proof_revocations['lane_rechecks'] += 1
        blocked = self._admission_blocks.get(key)
        if (blocked is not None and self._matching_admission_block(blocked, row['pose_stamp']) and
                blocked['line_stamp'] == row['line_stamp']):
            # A previous front vehicle is only a retry hint from a new pose.
            line = blocked['line'] if blocked['pose_stamp'] == row['pose_stamp'] else 'unknown'
            if line != 'unknown' or row['line'] not in ('friendly_blocked', 'world_blocked'):
                row.update(line=line, reason=blocked['reason'], blocker=blocked['blocker'])
        # A new friendly obstruction cannot erase a still-valid plate proof.
        # Neither a pose change nor an explicit failed recalculation uses this
        # preservation path: _current has already fenced the exact geometry.
        if (row['armor'] in ('pending', 'unknown') and previous is not None and
                previous.get('armor') in ('passed', 'failed')):
            row['armor'] = previous['armor']
            for field in ('penetration_threshold', 'penetration_factor'):
                if field in previous:
                    row[field] = previous[field]
        if row['expected_damage'] is not None:
            damage = float(row['expected_damage'])
            if math.isnan(damage) or math.isinf(damage) or damage < 0. or row['contact'] is not True:
                row['expected_damage'], row['contact'] = None, None
            else:
                row['expected_damage'] = damage
        self.rows[key] = row
        if mode == 'penetration' and self._executable(row):
            self._penetration_hints[row['shell_index']] = key
        self._used[channel] += 1
        return row

    def _frontier(self, now):
        jobs = self._jobs(shell_index=self.frame['loaded'])
        if not jobs:
            return None
        plan_key = self.selected or (self.loading_plan or self.next_plan or {}).get('key')
        selected_job = next((job for job in jobs if job[0] == plan_key), None)
        if selected_job is not None:
            row = self._current(selected_job, require_line=True)
            if self._executable(row):
                return row
        # Refresh a retained point first, but never let one pending point
        # prevent all other points or enemies from receiving a budget slice.
        remaining = max(0, self.foreground_budget - self._used['foreground'])
        ordered = [(None, selected_job)] if selected_job is not None and remaining else []
        for offset in range(len(jobs)):
            if len(ordered) >= remaining:
                break
            position = (self.foreground_cursor + offset) % len(jobs)
            job = jobs[position]
            if job is not selected_job:
                ordered.append((position, job))
        for position, job in ordered:
            if position is not None:
                self.foreground_cursor = (position + 1) % len(jobs)
            row = self._current(job, require_line=True)
            if row is None or row.get('armor') in ('pending', 'unknown') or row.get('line') != 'clear':
                row = self._evaluate(job, now, 'foreground')
            if self._executable(row):
                return row
        # A prior frame/background proof can be the earliest useful point.
        for job in jobs:
            row = self._current(job, require_line=True)
            if self._executable(row):
                return row
        return None

    def _rows_for(self, mode, shell_index=None, executable=False, fresh_line=False):
        result = []
        for job in self._jobs(mode, shell_index):
            row = self._current(job, require_line=executable or fresh_line)
            if row is not None and (not executable or self._executable(row, mode)):
                result.append(row)
        return result

    def _all_failed(self, indices):
        jobs = [job for job in self._jobs() if job[0][0] in indices]
        if not jobs or not self.frame.get('targets'):
            return False
        for job in jobs:
            row = self._current(job, require_line=True)
            if (row is None or row.get('armor') != 'failed' or
                    row.get('line') != 'clear' or
                    row.get('mechanical') != 'reachable'):
                return False
        return True

    def _best_penetration(self, exclude=None):
        rows = [row for row in self._rows_for('penetration', executable=True)
                if row['shell_index'] != exclude]
        if not rows:
            return None
        return min(rows, key=self._penetration_order)

    def _penetration_order(self, row):
        return (_shell_rank(row['shell']), 0 if row['key'] == self.selected else 1,
                repr(row['target_key']), repr(row['sample']))

    def _best_he(self, shell_index=None, exclude=None):
        rows = [row for row in self._rows_for('he_fallback', shell_index, executable=True)
                if row['shell_index'] != exclude]
        if not rows:
            return None
        return min(rows, key=lambda row: (-row['expected_damage'],
                   0 if row['key'] == self.selected else 1,
                   _shell_rank(row['shell']), repr(row['target_key']),
                   repr(row['sample'])))

    def _plan_next(self, row, status='verified', proofs=()):
        self.next_plan = row
        self.next_shell = row['shell_index'] if row is not None else None
        self.next_status = status
        self.next_proofs = proofs

    @staticmethod
    def _reviewed(row, mode):
        if row is None:
            return False
        if (row.get('line') in ('friendly_blocked', 'world_blocked') or
                row.get('mechanical') in ('hull_laying', 'mechanical_limited')):
            return True
        if row.get('line') != 'clear' or row.get('mechanical') != 'reachable':
            return False
        if mode == 'he_fallback':
            return row.get('contact') is True
        return row.get('armor') in ('passed', 'failed')

    def _ranked_penetration(self, groups, exclude=None):
        # A fresh qualifying point decides its shell's rank. An unchecked
        # earlier shell can still win; a later shell cannot. Every group
        # continues to receive background work, including after a winner.
        if any(shell.get('unavailable') and shell['index'] != exclude and
               self.frame['ammo'][shell['index']] > 0 for shell in self.frame['shells']):
            return None, 'shell_rank_unavailable', ()
        checked = []
        for index, rows in groups:
            if index == exclude:
                continue
            options = [row for row in rows if self._executable(row)]
            if options:
                best = min(options, key=self._penetration_order)
                return best, 'verified', tuple(checked + [best])
            if not all(self._reviewed(row, 'penetration') for row in rows):
                return None, 'higher_rank_pending', ()
            checked.extend(rows)
        return None, 'no_verified_penetration', ()

    def _penetration_groups(self, jobs, current=None):
        groups = []
        for job in jobs:
            index = job[0][0]
            if not groups or groups[-1][0] != index:
                groups.append((index, []))
            groups[-1][1].append(self._current(job, require_line=True) if current is None else
                                 current[job[0]])
        return groups

    def next_at_edge(self):
        plan = self.next_plan
        current = self.current_row(plan)
        if plan is None:
            return None, self.next_status
        if not self._executable(current, plan['mode']):
            return None, 'candidate_expired'
        proofs = self.next_proofs or (plan,)
        jobs = dict((job[0], job) for job in self._jobs(plan['mode']))
        rows = tuple(self._current(jobs[proof['key']], require_line=True)
                     if proof['key'] in jobs else None for proof in proofs)
        if any(row is None or row is not proof for row, proof in zip(rows, proofs)):
            return None, 'rank_evidence_changed'
        fence = getattr(self.evaluator, 'fence_next', None)
        valid = (fence(self.frame, proofs, len(proofs) > 1) if callable(fence)
                 else self.evaluator.fence(self.frame))
        return (current, 'verified') if valid else (None, 'observation_changed')

    def _next_excluded(self):
        frame = self.frame
        loaded = frame['loaded']
        in_load = frame['clip_size'] if frame.get('reloading') else frame['clip']
        # The last mounted round or cassette is not stocked for the next
        # full load, even though it is still stocked for this trigger.
        return loaded if frame['ammo'][loaded] <= in_load else None

    def _refresh_ranked_next(self, groups, exclude):
        best, status, proofs = self._ranked_penetration(groups, exclude=exclude)
        if best is None and self.fallback and self._best_penetration(exclude=exclude) is None:
            best = self._best_he(exclude=exclude)
            if best is not None:
                status, proofs = 'verified_he_fallback', (best,)
        self._plan_next(best, status, proofs)
        self.background_coverage = tuple((index, sum(self._reviewed(row, 'penetration')
                                                     for row in rows), len(rows))
                                         for index, rows in groups)
        self.decision['next_shell'] = self.next_shell

    def _ranked_recheck_key(self, groups, exclude):
        planned_key = (self.next_plan or {}).get('key')
        for index, rows in groups:
            if index == exclude:
                continue
            if any(self._executable(row) for row in rows):
                return None
            if not all(self._reviewed(row, 'penetration') for row in rows):
                if (planned_key is not None and planned_key[0] == index and
                        planned_key[-1] == 'penetration'):
                    return planned_key
                return self._penetration_hints.get(index)
        return None

    def next_review_details(self, plan, reason):
        """Describe lost proof without doing more collision work."""
        details = dict(coverage=self.background_coverage, blocked_rank=None)
        frame = self.frame
        if frame is None or self._frame_invalid:
            details['proof_changes'] = ('observation',)
            return details
        details['ranked_stock'] = tuple((shell['index'], shell.get('is_he'), shell.get('piercing'))
            for shell in sorted(frame['shells'], key=_shell_rank)
            if frame['ammo'][shell['index']] > 0 and not shell.get('unavailable'))
        if reason == 'higher_rank_pending':
            exclude = self._next_excluded()
            details['blocked_rank'] = next((index for index, reviewed, total
                in self.background_coverage if index != exclude and reviewed < total), None)
        if plan is None or plan.get('key') is None:
            return details
        job = next((job for job in self._jobs(plan['mode'], plan['shell_index'])
                    if job[0] == plan['key']), None)
        if job is None:
            details['proof_changes'] = ('domain',)
            return details
        old = plan['pose_stamp']
        new = self._stamp(frame, job[1], job[2])
        changes = [part for part, before, after in zip(
            ('identity', 'source', 'target', 'velocity', 'shell'), old, new)
            if before != after]
        if 'source' in changes and 'planning_pose' in frame:
            details['source_parts'] = tuple(part for part, before, after in zip(
                ('body_angles', 'shot_origin', 'descriptor', 'gun'), old[1], new[1])
                if before != after)
            details['origin_shift_m'] = math.sqrt(_distance_sq(old[1][1], new[1][1]))
        if plan['line_stamp'] != self._line_stamp(frame, plan.get('line_region')):
            changes.append('lane')
        details['proof_changes'] = tuple(changes)
        current = self._current(job, require_line=True)
        if current is not None:
            details['candidate'] = dict((name, current.get(name)) for name in
                ('armor', 'line', 'mechanical', 'reason', 'observed_at'))
        return details

    def refresh_next_at_trigger(self, now):
        """Give the final trigger a bounded, same-observation ranked pass."""
        self.background(now)
        plan, reason = self.next_at_edge()
        self.next_edge_receipt = dict(at=now, checked=0, status=reason,
            result=(plan or {}).get('key'))
        if (plan is not None or reason != 'higher_rank_pending' or
                self.frame is None or self._frame_invalid or self._atomic_at == now or
                now < self._next_edge_at + ATOMIC_CLOSE_INTERVAL):
            return plan, reason
        self._next_edge_at = now
        started = self.atomic_clock()
        self.evaluator.atomic_deadline = started + NEXT_EDGE_WALL_SECONDS
        self.evaluator.atomic_clock = self.atomic_clock
        exclude = self._next_excluded()
        domain = self._jobs()
        jobs = [job for job in domain if job[0][0] != exclude]
        begin = getattr(self.evaluator, 'begin_atomic', None)
        if not callable(begin) or not begin(self.frame, jobs, now):
            return None, reason
        self._used['atomic'] = 0
        # Rank always comes before a retained point. The hint only chooses
        # which point of that same shell gets tested first. It carries no
        # physical proof, and all points still participate in the fair pass.
        jobs.sort(key=lambda job: (_shell_rank(job[1]),
            self._penetration_hints.get(job[0][0]) != job[0],
            repr(job[0][1]), repr(job[3])))
        count, unresolved, index = 0, False, None
        for job in jobs:
            shell_index = job[0][0]
            if index != shell_index and unresolved:
                break
            index = shell_index
            row = self._current(job, require_line=True)
            if not self._reviewed(row, 'penetration'):
                if count >= NEXT_EDGE_CANDIDATES or self.atomic_clock() >= self.evaluator.atomic_deadline:
                    break
                row = self._evaluate(job, now, 'atomic')
                count += 1
            if self._executable(row):
                break
            unresolved = unresolved or not self._reviewed(row, 'penetration')
        self._refresh_ranked_next(self._penetration_groups(domain), exclude)
        plan, reason = self.next_at_edge()
        self.next_edge_receipt = dict(at=now, checked=count, status=reason,
            result=(plan or {}).get('key'),
            elapsed_ms=(self.atomic_clock() - started) * 1000.)
        return plan, reason

    def load_started(self, shell_index, plan=None):
        self.selected = None
        self.loading_plan = (plan if plan is not None and
                             plan['shell_index'] == shell_index else None)

    def current_row(self, candidate, require_line=True):
        if candidate is None or self.frame is None or self._frame_invalid:
            return None
        job = next((job for job in self._jobs(candidate['mode'], candidate['shell_index'])
                    if job[0] == candidate['key']), None)
        return self._current(job, require_line) if job is not None else None

    def _recover_incomplete(self, now, reason, rows=()):
        if self._evidence_wait_since is None:
            self._evidence_wait_since = now
        candidate = next((row for row in rows if row['key'] == self.selected and
                          isinstance(row.get('solution'), dict)), None)
        if now - self._evidence_wait_since >= ATOMIC_CLOSE_INTERVAL:
            candidate = candidate or next((row for row in rows
                if isinstance(row.get('solution'), dict)), None)
            return self._choose('firing_position', reason, candidate)
        if (candidate is not None and candidate.get('mechanical') == 'reachable' and
                candidate.get('line') in ('clear', 'pending') and
                self.decision['action'] in ('aim', 'preaim')):
            return self._choose('preaim', reason, candidate)
        return self._choose('wait', reason)

    def _end_search(self, penetration_found=False):
        self.search_started = None
        self.search_authority = None
        if penetration_found:
            self.fallback = False

    def _choose(self, action, reason, candidate=None, **fields):
        row = dict(action=action, reason=reason, candidate=candidate,
                   next_shell=self.next_shell,
                   phase=('preaiming' if action == 'preaim' or action == 'aim' and
                          (self.frame or {}).get('reloading') else action),
                   search_started=self.search_started,
                   search_deadline=(self.search_started + SEARCH_SECONDS
                                    if self.search_started is not None else None),
                   fallback=bool(self.fallback),
                   foreground_queries=self._used['foreground'],
                   background_queries=self._used['background'])
        row.update(fields)
        if action in ('firing_position', 'search_penetration'):
            if self.decision.get('action') != action:
                self._move_episode += 1
            episode_id = (self._identity, action, self._move_episode)
            row['move_request'] = dict(kind=action, reason=reason,
                target=candidate.get('target') if candidate else None,
                sample=candidate.get('sample') if candidate else None,
                solution=candidate.get('solution') if candidate else None,
                blocker=candidate.get('blocker') if candidate else None,
                deadline=row['search_deadline'] if action == 'search_penetration' else None,
                episode_id=episode_id)
            if action == 'search_penetration':
                self.search_authority['episode_id'] = episode_id
        self.decision = row
        if action in ('aim', 'preaim', 'firing_position', 'switch_shell', 'reload_clip') and candidate is not None:
            # Intent stability and evidence validity are separate lifetimes.
            # A zero-width gun must be able to finish laying toward one point
            # even though every hull step invalidates that point's old proof.
            self.selected = candidate['key']
        elif action not in ('trigger_active', 'wait'):
            self.selected = None
        if action == 'aim' or reason == 'no_relevant_enemy':
            self._evidence_wait_since = None
        return row

    def _atomic_close(self, now):
        """Close a finite negative universe in one current-pose observation.

        Normal two-point slices cannot accumulate negative proof for a turret
        moving on every frame. This separately rate-limited frontier can close
        a small moving domain within strict work/time limits. A larger stable
        domain retains only its still-current rows across bounded attempts.
        Any missing/blocked point, unfinished budget or changed pose remains
        unknown. A positive current-shell result stops this work immediately.
        """
        if now < self._atomic_at + ATOMIC_CLOSE_INTERVAL:
            return None
        jobs = self._jobs(shell_index=(self.frame['loaded']
            if int(self.frame.get('clip_size', 1)) > 1 else None))
        if not jobs:
            return None
        self._atomic_at = now
        self._used['atomic'] = 0
        self._atomic_receipt = dict(status='incomplete', candidates=len(jobs),
                                    observed_at=now, evaluations=0)
        if len(jobs) > ATOMIC_MAX_JOBS:
            self._atomic_receipt.update(status='domain_budget_exceeded')
            return None
        begin = getattr(self.evaluator, 'begin_atomic', None)
        fence = getattr(self.evaluator, 'fence', None)
        started = self.atomic_clock()
        deadline = started + self.atomic_time_budget
        self.evaluator.atomic_deadline = deadline
        self.evaluator.atomic_clock = self.atomic_clock
        if not callable(begin) or not callable(fence) or not begin(self.frame, jobs, now):
            self._atomic_receipt.update(getattr(self.evaluator, 'atomic_receipt', {}))
            self._atomic_receipt.setdefault('reason', 'atomic_observation_unavailable')
            return None
        # All-or-nothing negative publication. The foreground/background map
        # is restored if even one object changes during this synchronous pass.
        jobs = sorted(jobs, key=lambda job: (
            0 if job[0][0] == self.frame['loaded'] else 1,
            _shell_rank(job[1]), repr(job[2]['key']), repr(job[3])))
        positive = None
        for job in jobs:
            if self.atomic_clock() >= deadline or self._used['atomic'] >= ATOMIC_CANDIDATES:
                self._atomic_receipt['reason'] = 'atomic_frame_budget_exhausted'
                break
            row = self._current(job, require_line=True)
            if row is None or row.get('armor') in ('unknown', 'pending') or row.get('line') != 'clear':
                row = self._evaluate(job, now, 'atomic')
            if self._executable(row):
                positive = row
                break
            if (row.get('armor') != 'failed' or row.get('line') != 'clear' or
                    row.get('mechanical') != 'reachable'):
                break
        if not fence(self.frame):
            self.rows.clear()
            self.selected = None
            self._frame_invalid = True
            self._atomic_receipt.update(status='pose_changed', evaluations=self._used['atomic'])
            self._atomic_receipt.update(getattr(self.evaluator, 'atomic_receipt', {}))
            self._atomic_receipt['elapsed_ms'] = (self.atomic_clock() - started) * 1000.
            return None
        complete = self._all_failed(tuple(job[0][0] for job in jobs))
        self._atomic_receipt.update(status='positive' if positive is not None else
            'all_failed' if complete else 'incomplete', evaluations=self._used['atomic'])
        self._atomic_receipt.update(getattr(self.evaluator, 'atomic_receipt', {}))
        self._atomic_receipt['elapsed_ms'] = (self.atomic_clock() - started) * 1000.
        return positive if positive is not None and positive['shell_index'] == self.frame['loaded'] else None

    def update(self, now, frame=None):
        """Run foreground work only; ready current ammunition wins immediately."""
        now = float(now)
        try:
            frame = self.evaluator.snapshot(now) if frame is None else frame
        except (AttributeError, TypeError, ValueError, RuntimeError, KeyError, IndexError):
            self.frame = None
            return self._recover_incomplete(now, 'observation_unavailable')
        if not isinstance(frame, dict):
            self.frame = None
            return self._recover_incomplete(now, 'observation_unavailable')
        identity = frame['identity']
        if self._identity is not None and identity != self._identity:
            self.reset()
        self._identity = identity
        self.frame = frame
        self._frame_invalid = False
        if self._foreground_at != now:
            self._used['foreground'] = 0
            self._foreground_at = now
        if self._background_at != now:
            self._used['background'] = 0
        jobs = tuple(job for mode in ('penetration', 'he_fallback')
                     for job in self._jobs(mode))
        valid_keys = set(job[0] for job in jobs)
        stamps = dict((job[0], self._stamp(frame, job[1], job[2])) for job in jobs)
        for key in list(self.rows):
            old, stamp = self.rows[key].get('pose_stamp'), stamps.get(key)
            if old != stamp or key not in valid_keys:
                if key not in valid_keys or old is None or old[0] != stamp[0]:
                    reason = 'domain'
                elif old[1] != stamp[1]:
                    reason = 'source'
                elif old[2:4] != stamp[2:4]:
                    reason = 'target'
                else:
                    reason = 'shell'
                self.proof_revocations[reason] += 1
                self.rows.pop(key, None)
        for key in list(self._admission_blocks):
            blocked = self._admission_blocks[key]
            if (key not in valid_keys or not self._matching_admission_block(blocked, stamps[key]) or
                    blocked['line_stamp'] != self._line_stamp(frame, blocked.get('line_region')) or
                    now >= blocked.get('retry_at', float('inf'))):
                self._admission_blocks.pop(key, None)
                if key in self.rows:
                    self.rows[key]['line'] = 'pending'
        if self.selected is not None and self.selected not in valid_keys:
            self.selected = None
        loaded = int(frame['loaded'])
        if self.loading_plan is not None and self.loading_plan['shell_index'] != loaded:
            self.loading_plan = None
        magazine = (loaded, int(frame['clip']))
        previous = self._magazine
        if previous is not None and (loaded != previous[0] or magazine[1] > previous[1]):
            # A genuinely different shell/clip gets new penetration evidence;
            # the continuing HE fallback phase is not another eight seconds.
            self._end_search()
            # A completed load retains the point already being laid. A
            # different loaded shell requires its own point and proof.
            if self.selected is not None and self.selected[0] != loaded:
                self.selected = None
        self._magazine = magazine
        if frame.get('artillery'):
            return self._choose('unchanged', 'copied_artillery_owner')
        if frame.get('trigger_active'):
            return self._choose('trigger_active', 'physical_trigger_owns_tail',
                                self.trigger)
        if not any(amount > 0 for amount in frame.get('ammo', ())):
            return self._choose('retreat', 'ammunition_exhausted')
        if not frame.get('targets'):
            empty_clip = (int(frame.get('clip_size', 1)) > 1 and frame['clip'] <= 0 and
                          not frame.get('reloading'))
            if frame['ammo'][loaded] <= 0 or empty_clip:
                # No observed target can support a prior ranked plan.
                planned = (loaded if frame['ammo'][loaded] > 0 else
                           min(index for index, count in enumerate(frame['ammo']) if count > 0))
                self._end_search()
                return self._choose('reload_clip' if empty_clip else 'switch_shell',
                    'empty_clip' if empty_clip else 'current_ammunition_exhausted',
                    shell_index=planned, early_reload=False)
            return self._choose('wait', 'no_relevant_enemy')
        if self._lay_recovery is not None:
            refused, retry_at = self._lay_recovery
            if now < retry_at:
                candidate = self.current_row(refused)
                if candidate is not None:
                    candidate = dict(candidate, mechanical='mechanical_limited',
                                     reason='native_lay_stalled')
                return self._choose('firing_position', 'native_lay_stalled', candidate)
            self._lay_recovery = None
        current = self._frontier(now)
        if current is None and not any(row.get('armor') == 'passed'
                for row in self._rows_for('penetration', loaded)):
            current = self._atomic_close(now)
        if self._frame_invalid:
            return self._recover_incomplete(now, 'observation_changed_during_atomic_close')
        is_magazine = int(frame.get('clip_size', 1)) > 1
        if frame['ammo'][loaded] <= 0:
            # Exhaustion is not a fabricated penetration failure. There is no
            # current round/clip to preserve and therefore no eight-second
            # prerequisite for selecting stocked ammunition for normal load.
            planned = self._ranked_penetration(self._penetration_groups(self._jobs()))[0]
            planned = planned or (self._best_he() if self.fallback else None)
            index = (planned['shell_index'] if planned is not None else
                     min(shell['index'] for shell in frame['shells']
                         if frame['ammo'][shell['index']] > 0))
            self._end_search()
            return self._choose('reload_clip' if is_magazine else 'switch_shell',
                'current_ammunition_exhausted', planned, shell_index=index,
                early_reload=False)
        if is_magazine and frame['clip'] <= 0 and not frame.get('reloading'):
            planned = self._ranked_penetration(self._penetration_groups(self._jobs()))[0]
            planned = planned or (self._best_he() if self.fallback else None)
            index = planned['shell_index'] if planned is not None else loaded
            if frame['ammo'][index] <= 0:
                index = min((shell for shell in frame['shells']
                             if frame['ammo'][shell['index']] > 0), key=_shell_rank)['index']
            self._end_search()
            return self._choose('reload_clip', 'empty_clip', planned,
                                shell_index=index, early_reload=False)
        if current is not None:
            self._end_search(penetration_found=True)
            return self._choose('aim', 'current_shell_verified', current)
        valid_pen = [row for row in self._rows_for('penetration', loaded, fresh_line=True)
                     if row.get('armor') == 'passed' and self._needs_firing_position(row)]
        if valid_pen:
            self._end_search()
            candidate = min(valid_pen, key=lambda row: (
                0 if row['key'] == self.selected else 1,
                0 if row.get('mechanical') == 'hull_laying' else 1,
                repr(row['target_key']), repr(row['sample'])))
            return self._choose('firing_position', 'current_penetration_obstructed',
                                candidate, movement_reason=candidate.get('reason'))
        current_failed = self._all_failed((loaded,))
        if not is_magazine and current_failed:
            ranked = self._ranked_penetration(
                self._penetration_groups(self._jobs()), exclude=loaded)[0]
            if ranked is not None:
                self._end_search(penetration_found=True)
                return self._choose('switch_shell', 'current_shell_all_armour_failed',
                                    ranked, shell_index=ranked['shell_index'])
        if self.fallback:
            alternative = self._best_penetration(exclude=loaded)
            if alternative is not None:
                self._end_search(penetration_found=True)
                return self._choose('reload_clip' if is_magazine else 'switch_shell',
                                    'new_penetration_opportunity', alternative,
                                    shell_index=alternative['shell_index'],
                                    early_reload=is_magazine)
            return self._fallback_decision(loaded, is_magazine, now)
        stocked = tuple(shell['index'] for shell in frame['shells']
                        if frame['ammo'][shell['index']] > 0)
        eligible = (current_failed and frame['clip'] > 0
                    if is_magazine else self._all_failed(stocked))
        if self.search_authority is None and eligible:
            if frame.get('search_drive') is False:
                return self._choose('wait', 'search_drive_authority_unavailable')
            fence = getattr(self.evaluator, 'fence', None)
            if callable(fence) and not fence(frame):
                self.rows.clear()
                return self._recover_incomplete(now, 'observation_changed_before_search')
            self.search_authority = dict(qualified_at=now, pose=frame['pose'],
                targets=tuple(_target_key(target) for target in frame['targets']),
                shells=(loaded,) if is_magazine else stocked)
        if self.search_authority is not None:
            if self.search_started is not None and now >= self.search_started + SEARCH_SECONDS:
                alternative = self._best_penetration(exclude=loaded)
                if alternative is not None:
                    self._end_search(penetration_found=True)
                    return self._choose('reload_clip' if is_magazine else 'switch_shell',
                                        'penetration_search_expired', alternative,
                                        shell_index=alternative['shell_index'],
                                        early_reload=is_magazine)
                self.fallback = True
                return self._fallback_decision(loaded, is_magazine, now)
            rows = self._rows_for('penetration', loaded, fresh_line=True)
            return self._choose('search_penetration', 'confirmed_global_armour_failure',
                                rows[0] if rows else None)
        rows = self._rows_for('penetration', None if current_failed and not is_magazine else loaded,
                              fresh_line=True)
        obstructed = [row for row in rows if self._needs_firing_position(row)]
        if obstructed:
            return self._choose('firing_position', 'unverified_points_obstructed',
                min(obstructed, key=lambda row: (0 if row['key'] == self.selected else 1,
                                                repr(row['target_key']), repr(row['sample']))))
        if ('budget' in self._atomic_receipt.get('reason', '') and
                self._atomic_receipt.get('status') != 'all_failed'):
            # A large/moving observation is incomplete, not a reason to park
            # the copied driver indefinitely while waiting for a certificate.
            candidates = [row for row in rows if isinstance(row.get('solution'), dict)]
            return self._choose('firing_position', 'global_snapshot_budget_pending',
                                candidates[0] if candidates else None)
        return self._recover_incomplete(now, 'penetration_evidence_incomplete', rows)

    def _fallback_decision(self, loaded, is_magazine, now):
        best = self._best_he()
        if best is not None:
            self._plan_next(best)
        current = self._best_he(loaded)
        if is_magazine and current is not None:
            return self._choose('aim', 'current_he_clip_fallback', current)
        if best is not None:
            if best['shell_index'] == loaded:
                return self._choose('aim', 'he_fallback_contact', best)
            return self._choose('reload_clip' if is_magazine else 'switch_shell',
                                'he_fallback_plan', best,
                                shell_index=best['shell_index'], early_reload=is_magazine)
        he_shells = [shell for shell in self.frame['shells']
                     if shell.get('is_he') and self.frame['ammo'][shell['index']] > 0]
        if not he_shells:
            return self._choose('retreat', 'no_he_or_verified_penetration')
        rows = self._rows_for('he_fallback', loaded if is_magazine else None, fresh_line=True)
        blocked = next((row for row in rows if row.get('contact') is True and
                        (row.get('line') != 'clear' or
                         row.get('mechanical') != 'reachable')), None)
        if blocked is not None:
            return self._choose('firing_position', 'he_fallback_obstructed', blocked)
        return self._recover_incomplete(now, 'he_contact_evidence_incomplete', rows)

    def background(self, now):
        """One independent, fair all-shell/all-target frontier after control."""
        now = float(now)
        if (self.frame is None or self.frame.get('artillery') or self._frame_invalid or
                self._background_at == now):
            return self.next_shell
        self._background_at = now
        self._used['background'] = 0
        penetration = self._jobs()
        jobs = penetration + self._jobs('he_fallback')
        # The cursor survives roster changes and completes the ordered pass.
        # A moving high-rank point cannot repeatedly restart it, and the last
        # selected point never jumps the ammunition order.
        current = dict((job[0], self._current(job, require_line=True)) for job in jobs)
        pending = sorted(((job[4] == 'he_fallback', _shell_rank(job[1]),
                           repr(job[0][1]), repr(job[3])), job) for job in jobs
                         if not self._reviewed(current[job[0]], job[4]))
        exclude = self._next_excluded()
        recheck = None
        if self.background_budget > 1 and pending and self._penetration_hints:
            # Spend at most one existing slot on a previously proved point
            # of the first unresolved rank. A pose change retires its proof,
            # not its place in that rank's queue. Leave a slot for the fair
            # scan so a moving tank cannot starve the rest of the domain.
            key = self._ranked_recheck_key(self._penetration_groups(penetration, current), exclude)
            recheck = next((job for unused, job in pending if job[0] == key), None)
            if recheck is not None:
                current[recheck[0]] = self._evaluate(recheck, now, 'background', ranked_recheck=True)
        if self.background_cursor is not None:
            split = next((offset for offset, (key, unused) in enumerate(pending)
                          if key > self.background_cursor), len(pending))
            pending = pending[split:] + pending[:split]
        for key, job in pending:
            if self._used['background'] >= self.background_budget:
                break
            if job is recheck:
                continue
            self.background_cursor = key
            current[job[0]] = self._evaluate(job, now, 'background')
        if not pending:
            self.background_cursor = None
        self._refresh_ranked_next(self._penetration_groups(penetration, current), exclude)
        self.decision['background_queries'] = self._used['background']
        return self.next_shell

    def navigation_result(self, receipt):
        """Observe normal recovery without granting a new search deadline."""
        self.navigation_receipt = dict(receipt or {})
        authority = self.search_authority
        observed = self.navigation_receipt
        if (authority is not None and observed.get('action') == 'search_penetration' and
                observed.get('episode_id') == authority.get('episode_id')):
            authority['navigation_status'] = observed.get('status')
            if self.search_started is None and observed.get('attempted'):
                self.search_started = float(observed['at'])
                deadline = self.search_started + SEARCH_SECONDS
                self.decision.update(search_started=self.search_started, search_deadline=deadline)
                self.decision['move_request']['deadline'] = deadline

    def lay_stalled(self, candidate, now):
        self._lay_recovery = candidate, now + ATOMIC_CLOSE_INTERVAL

    def admission_failed(self, candidate, reason, blocker=None):
        """A first-edge refusal invalidates only its point, never its tank.

        Point evidence is not a launched shell's result. A still-valid armour
        proof survives a new friendly/world obstruction and remains owned by
        ordinary firing-position navigation, not the eight-second search.
        """
        if not isinstance(candidate, dict):
            return
        row = self.rows.get(candidate.get('key'))
        if row is None or row.get('pose_stamp') != candidate.get('pose_stamp'):
            return
        classifications = dict(auto_friendly_lane='friendly_blocked',
            auto_friendly_splash='friendly_blocked', auto_world_blocked='world_blocked',
            auto_front_vehicle='world_blocked', auto_lane_geometry_unknown='unknown',
            auto_world_geometry_unknown='unknown')
        line = classifications.get(reason)
        if line is not None:
            row.update(line=line, reason=reason, blocker=dict(blocker or {}))
            self._admission_blocks[row['key']] = dict(line=line, reason=reason,
                blocker=dict(blocker or {}), pose_stamp=row['pose_stamp'],
                line_stamp=row['line_stamp'], line_region=row.get('line_region'))
            if reason in NATIVE_LINE_RETRY_REASONS:
                # A live front vehicle or unavailable native contact can
                # clear before either of the planning stamps changes.
                self._admission_blocks[row['key']]['retry_at'] = (
                    self.frame['observed_at'] + ATOMIC_CLOSE_INTERVAL)
            invalidate = getattr(self.evaluator, 'invalidate_line', None)
            if callable(invalidate):
                invalidate(row['key'])
        if reason in ('auto_pose_changed', 'auto_target_pose_changed',
                       'auto_source_pose_changed', 'auto_shell_changed'):
            self.rows.pop(row['key'], None)
        if self.selected == candidate.get('key'):
            self.selected = None

    def shot_committed(self, event, pending):
        # Hit, miss, zero damage and penetration results are deliberately not
        # inputs. Only the physical group's first/final commit bounds its lock.
        if int(event.get('burst_index', 0)) == 0:
            self.trigger = (pending.get('player_control') or {}).get('candidate')
            if self.trigger is None:
                self.trigger = self.decision.get('candidate')
            self.selected = None
            self.loading_plan = None
        if int(event.get('burst_index', 0)) + 1 >= int(event.get('burst_count', 1)):
            self.trigger = None
            self._evidence_wait_since = None

    def apply_order(self, order, now=None):
        """Only replace attack intent; the copied navigation still owns motion."""
        decision = self.decision
        if decision['action'] == 'unchanged':
            return order
        if decision['action'] == 'trigger_active':
            return dict(order or {}, fire_allowed=False)
        result = dict(order or {})
        candidate = decision.get('candidate')
        if candidate is not None:
            target = candidate['target']
            result.update(target_id=target.get('network_id', target.get('id')),
                          target_kind=target.get('kind'),
                          aim_position=(candidate.get('solution') or {}).get('point'),
                          face_position=target.get('position'))
        result['shell_index'] = (decision.get('shell_index', self.frame['loaded'])
                                 if self.frame is not None else result.get('shell_index'))
        if decision['action'] == 'aim':
            position = self.frame.get('position')
            if position is not None:
                result.update(move_position=position, throttle_override=0.,
                              combat_mode='engage')
            result['fire_allowed'] = not self.frame.get('reloading')
        else:
            result['fire_allowed'] = False
        return result

    def select_command(self, source, command, target, now):
        decision = self.decision
        if decision['action'] in ('unchanged', 'trigger_active'):
            return command, target
        result = dict(command)
        result['_player_attack'] = decision
        candidate = decision.get('candidate')
        if candidate is not None:
            target = candidate['target']
            result['target_id'] = target.get('id')
            solution = candidate.get('solution') or {}
            result.update(aim_position=solution.get('point'),
                          _player_attack_solution=solution)
        if decision['action'] != 'aim':
            result['fire_allowed'] = False
        elif self._executable(candidate, candidate.get('mode', 'penetration')):
            # The copied gate may have examined another sample. Replace its
            # attack intent only; the native gun/lane first-edge gate remains.
            result['fire_allowed'] = not (self.frame or {}).get('reloading')
        return result, target

    def status(self):
        candidate = self.decision.get('candidate')
        return dict(action=self.decision['action'], reason=self.decision['reason'],
            target=candidate.get('target_key') if candidate else None,
            sample=candidate.get('sample') if candidate else None,
            shell=candidate.get('shell_index') if candidate else None,
            phase=self.decision.get('phase'),
            point=(candidate.get('solution') or {}).get('point') if candidate else None,
            mode=candidate.get('mode') if candidate else None,
            armor=candidate.get('armor') if candidate else None,
            penetration_threshold=candidate.get('penetration_threshold') if candidate else None,
            line=candidate.get('line') if candidate else None,
            mechanical=candidate.get('mechanical') if candidate else None,
            proof_at=candidate.get('observed_at') if candidate else None,
            next_shell=self.next_shell, fallback=self.fallback,
            next_status=self.next_status, background_coverage=self.background_coverage,
            proof_revocations=dict(self.proof_revocations), next_edge=dict(self.next_edge_receipt),
            loading_plan=(self.loading_plan or {}).get('key'),
            next_target=(self.next_plan or {}).get('target_key'),
            next_sample=(self.next_plan or {}).get('sample'),
            next_point=((self.next_plan or {}).get('solution') or {}).get('point'),
            next_proof=dict((name, self.next_plan.get(name)) for name in
                            ('mode', 'armor', 'line', 'mechanical', 'observed_at',
                             'penetration_threshold', 'expected_damage')) if self.next_plan else None,
            search_started=self.search_started,
            search_deadline=(self.search_started + SEARCH_SECONDS
                             if self.search_started is not None else None),
            foreground_queries=self._used['foreground'],
            background_queries=self._used['background'],
            atomic=dict(self._atomic_receipt),
            navigation=dict(self.navigation_receipt or {}))


class NativeAttackEvaluator(object):
    """Bounded real-plate observations for the independent foreground policy."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.owner = runtime.owner
        self.jobs = {}
        self.predictions = {}
        self._at = None
        self._budgets = {}
        self.observations = {}
        self.atomic_receipt = {}
        self._atomic_predictions = {}
        self.atomic_clock = _WALL_CLOCK
        self.atomic_deadline = float('inf')

    def snapshot(self, now):
        runtime, owner = self.runtime, self.owner
        source = runtime.current_source()
        gun = runtime.gun
        entity = owner._server_entity(owner._server.vehicle_id)
        descriptor = entity.typeDescriptor
        origin, unused_direction = owner._mutable_shot_ray()
        origin = _point(origin)
        pose = native_source_pose(runtime, origin)
        body = pose[1]
        targets, observations = [], {}
        for raw in runtime.visible_targets():
            if not raw.get('alive', True):
                continue
            target = runtime.target_entity(raw)
            row = dict(key=_target_key(raw), value=raw, entity=target,
                       samples=(), pose=None)
            try:
                signature, matrix, chassis = native_target_pose(owner, target)
                row.update(pose=signature, matrix=matrix, chassis=chassis,
                           samples=tuple(range(len(shot_geometry.ordered_vehicle_aim_samples(
                               target.typeDescriptor)))))
                previous = self.observations.get(row['key'])
                position = _point(matrix.translation)
                velocity = tuple(raw.get('velocity', ()))
                if len(velocity) != 3:
                    if previous is not None and .001 <= now - previous[0] <= 1.:
                        dt = now - previous[0]
                        velocity = tuple((position[index] - previous[1][index]) / dt
                                         for index in range(3))
                    else:
                        velocity = (0., 0., 0.)
                row['velocity'] = _point(velocity)
                observations[row['key']] = (now, position, row['velocity'])
            except (AttributeError, TypeError, ValueError, RuntimeError, KeyError, IndexError):
                row['velocity'] = None
            targets.append(row)
        self.observations = observations
        shells = []
        for index, shot in enumerate(gun.shots):
            try:
                piercing = float(combat_rules.range_piercing(shot, 0.))
                shells.append(dict(index=index, is_he=combat_rules.is_he(shot),
                                   piercing=piercing, shot=shot,
                                   signature=_shell_signature(index, shot)))
            except (AttributeError, TypeError, ValueError, KeyError, IndexError):
                # A stocked but malformed shell still belongs to the domain.
                # Silently dropping it would forge "all ammunition failed".
                shells.append(dict(index=index, is_he=False, piercing=float('inf'),
                    shot=shot, signature=(index, id(shot), 'unavailable'), unavailable=True))
        for index in range(len(gun.shots), len(gun.ammo)):
            # An inventory slot without a mounted shot descriptor is still
            # unknown stock, never permission to shrink the global universe.
            shells.append(dict(index=index, is_he=False, piercing=float('inf'),
                shot=None, signature=(index, 'descriptor_missing'), unavailable=True))
        scene = self._scene_stamp()
        planning_pose = _planning_pose(pose)
        frame = dict(identity=(owner._generation, id(gun), id(descriptor.gun)),
            source=source, pose=pose, planning_pose=planning_pose,
            position=pose[0], body=body, origin=origin,
            descriptor=descriptor, entity=entity, loaded=int(gun.shot_index),
            ammo=tuple(gun.ammo), clip=int(gun.clip), clip_size=int(gun.clip_size),
            reloading=float(gun.reload_time) > 0.,
            trigger_active=owner._local_player_burst is not None,
            search_drive=runtime.attack_search_drive_available(),
            artillery='SPG' in (descriptor.type.tags or ()),
            targets=tuple(targets), shells=tuple(shells),
            scene=scene, observed_at=now)
        self._observe_lanes(frame)
        if self._at != now:
            self._at = now
            self._budgets = dict(foreground=WORLD_CHORDS_PER_FRONTIER,
                                 background=WORLD_CHORDS_PER_FRONTIER)
        valid = set((shell['index'], target['key'], sample)
                    for shell in shells if frame['ammo'][shell['index']] > 0
                    for target in targets for sample in target['samples'] or (None,))
        target_poses = dict((target['key'], (target['pose'], target['velocity']))
                            for target in targets)
        signatures = dict((shell['index'], shell['signature']) for shell in shells)
        for key in list(self.jobs):
            geometry = self.jobs[key]['geometry']
            if (key not in valid or geometry[0] != planning_pose or
                    (geometry[1], geometry[3]) != target_poses.get(key[1]) or
                    geometry[2] != signatures.get(key[0])):
                self.jobs.pop(key, None)
        for key in list(self.predictions):
            stamp, unused = self.predictions[key]
            if (key not in valid or stamp[0] != planning_pose or
                    (stamp[1], stamp[3]) != target_poses.get(key[1]) or
                    stamp[2] != signatures.get(key[0])):
                self.predictions.pop(key, None)
        return frame

    def _scene_stamp(self):
        owner = self.owner
        sensor = getattr(owner, '_destructibles', None)
        revision = getattr(sensor, '_spatial_revision_1513', None)
        return (id(owner._avatar), owner._avatar.spaceID,
                revision() if callable(revision) else None)

    @staticmethod
    def _cell(value):
        return int(math.floor(value / PROJECTILE_BROADPHASE_RADIUS))

    @classmethod
    def _lane_region(cls, path):
        # Every chord is contained in its path's box. Expand it by the same
        # radius as the copied lane resolver before quantising outwards.
        radius = PROJECTILE_BROADPHASE_RADIUS
        return tuple(cls._cell(bound(point[axis] for point in path) + padding)
                     for axis in (0, 2) for bound, padding in ((min, -radius), (max, radius)))

    @staticmethod
    def lane_stamp(frame, region):
        cached = frame['lane_regions'].get(region)
        if cached is None:
            x0, x1, z0, z1 = region
            blockers = tuple(row for row in frame['blockers']
                             if x0 <= row[0] <= x1 and z0 <= row[1] <= z1)
            cached = frame['scene'], frame['lane_missing'], frame['debris'], blockers
            frame['lane_regions'][region] = cached
        return cached

    def _observe_lanes(self, frame):
        blockers, missing = self._dynamic_stamp()
        debris = getattr(self.owner, '_detached_turret_obstacles', None)
        ready = getattr(debris, '_ready', None)
        if callable(ready):
            now = self.runtime.geometry._turret_server_time_ms()
            debris = tuple(sorted((turret['row']['actor_kind'], turret['row']['actor_id'],
                turret['row'].get('motion_seq', 0), turret['rest'], turret['attitude'])
                for turret in ready(now)))
        elif debris is not None:
            debris = frame['observed_at']
        frame.update(blockers=blockers, lane_missing=missing, debris=debris, lane_regions={},
                     line_revision=(frame['scene'], blockers, missing, debris))

    def _dynamic_stamp(self):
        owner = self.owner
        dynamic, missing = [], []
        for record in owner._records.values():
            if record.get('local') or record.get('tombstone') or not record.get('ready'):
                continue
            other = owner._server_entity(record.get('engine_id'))
            try:
                if other is None or not getattr(other, 'isStarted', False):
                    raise ValueError('native lane entity unavailable')
                state = record.get('state') or {}
                alive = bool(other.isAlive() and state.get('alive', True))
                team = int(state.get('team', record.get('team', 0)))
                # This frontier tests allies and wrecks. The selected enemy
                # already has its own geometry stamp. Other live enemies are
                # tested against the real scattered path at first admission.
                if alive and team != int(owner.client.team):
                    continue
                if not native_geometry_complete(other):
                    raise ValueError('native lane geometry unavailable')
                point = _point(other.position)
                dynamic.append((self._cell(point[0]), self._cell(point[2]),
                    record.get('engine_id'), record.get('kind'), record.get('network_id'),
                    alive, team, point, native_target_pose(owner, other, record)[0]))
            except (AttributeError, TypeError, ValueError, RuntimeError, KeyError, IndexError,
                    OverflowError):
                missing.append(record.get('engine_id'))
        return tuple(sorted(dynamic, key=lambda row: repr(row[2]))), tuple(sorted(missing, key=repr))

    def invalidate_line(self, key):
        job = self.jobs.get(key[:3])
        if job is not None:
            job.update(cursor=0, done=False, blocked=None, lane=None)

    def begin_atomic(self, frame, jobs, now):
        self.atomic_receipt = dict(world_chords=0, armour_collision_batches=0,
            friendly_path_calls=0, world_budget=None, priced_candidates=0,
            priced_world_chords=0, world_query_limit=ATOMIC_WORLD_QUERIES,
            armour_batch_limit=ATOMIC_ARMOUR_BATCHES)
        self._atomic_predictions = {}
        shells = set(job[0][0] for job in jobs)
        if (len(frame['targets']) > 30 or len(shells) > 3 or
                any(len(target.get('samples') or ()) > 9 for target in frame['targets'])):
            self.atomic_receipt['reason'] = 'atomic_supported_domain_exceeded'
            return False
        # Reuse only exact-current-pose predictions already computed by either
        # frontier. Do not spend the entire frame merely pricing 405 new rays.
        # Missing predictions are priced incrementally in evaluate; their
        # absence leaves the full-domain cost unknown, never guessed as zero.
        count = 0
        for job in jobs:
            key, shell, target, sample, mode = job
            if self.atomic_clock() >= self.atomic_deadline:
                self.atomic_receipt['reason'] = 'atomic_frame_budget_exhausted'
                break
            cached = self.predictions.get(key[:3])
            stamp = (frame['planning_pose'], target['pose'], shell['signature'],
                     target.get('velocity'), frame['identity'])
            prediction = cached[1] if cached is not None and cached[0] == stamp else None
            if prediction is None:
                continue
            chords = max(0, len(prediction['path']) - 1)
            if chords > ATOMIC_MAX_CHORDS_PER_JOB:
                self.atomic_receipt['reason'] = 'atomic_path_domain_exceeded'
                return False
            count += chords
            self._atomic_predictions[key] = prediction
        self._atomic_domain = set(job[0] for job in jobs)
        self._budgets['atomic'] = ATOMIC_WORLD_QUERIES
        self.atomic_receipt.update(priced_candidates=len(self._atomic_predictions),
                                  priced_world_chords=count)
        if len(self._atomic_predictions) == len(jobs):
            self.atomic_receipt['world_budget'] = count
        return True

    def fence(self, frame):
        return self._fence(frame)

    def fence_next(self, frame, rows, ranked_domain):
        return self._fence(frame, rows=rows, ranked_domain=ranked_domain)

    def _fence(self, frame, rows=None, ranked_domain=True):
        try:
            owner = self.owner
            if (_planning_pose(native_source_pose(self.runtime)) != frame['planning_pose'] or
                    self.runtime.gun.shot_index != frame['loaded'] or
                    tuple(self.runtime.gun.ammo) != frame['ammo']):
                return False
            scene = self._scene_stamp()
            if scene != frame['scene']:
                return False
            live = dict(scene=scene, observed_at=self.runtime.now)
            self._observe_lanes(live)
            if rows is None and live['line_revision'] != frame['line_revision']:
                return False
            target_keys = None
            if rows is not None:
                for row in rows:
                    region = row.get('line_region')
                    if region is None:
                        if live['line_revision'] != frame['line_revision']:
                            return False
                    elif self.lane_stamp(live, region) != row['line_stamp']:
                        return False
                target_keys = set(row['target_key'] for row in rows)
            observed = dict((_target_key(row), row) for row in self.runtime.visible_targets()
                            if row.get('alive', True))
            if ranked_domain and set(observed) != set(target['key'] for target in frame['targets']):
                return False
            for target in frame['targets']:
                key = target['key']
                if target_keys is not None and key not in target_keys:
                    continue
                current = observed.get(key)
                if (current is None or
                        native_target_pose(owner, self.runtime.target_entity(current))[0] != target['pose']):
                    return False
                velocity = tuple(current.get('velocity', ()))
                if len(velocity) == 3 and _point(velocity) != target['velocity']:
                    return False
            return True
        except (AttributeError, TypeError, ValueError, KeyError, IndexError, RuntimeError):
            return False

    def _prediction(self, frame, shell, target, sample):
        if (sample is None or shell.get('unavailable') or target.get('pose') is None or
                target.get('velocity') is None):
            return None
        try:
            owner, entity, shot = self.owner, target['entity'], shell['shot']
            key = (shell['index'], target['key'], sample)
            stamp = (frame['planning_pose'], target['pose'], shell['signature'],
                     target['velocity'], frame['identity'])
            previous = self.predictions.get(key)
            if previous is not None and previous[0] == stamp:
                return previous[1]
            samples = shot_geometry.ordered_vehicle_aim_samples(entity.typeDescriptor)
            body = target['matrix']
            pose = dict(position=_point(body.translation), yaw=float(body.yaw),
                        pitch=float(body.pitch), roll=float(body.roll),
                        turret_yaw=float(owner._runtime.math.Matrix(
                            entity.appearance.turretMatrix).yaw))
            sample_point = shot_geometry.vehicle_aim_point(samples[sample], pose)
            speed = float(_field(shot, 'speed'))
            gravity = abs(float(_field(shot, 'gravity')))
            maximum = float(_field(shot, 'maxDistance'))
            solved = ballistics.ballistic_intercept(frame['origin'], sample_point,
                target['velocity'], speed, gravity)
            if solved is None or solved[2] * speed > maximum + 1.e-6:
                result = dict(unreachable=True, path=(), reason='no_reachable_intercept')
                self.predictions[key] = stamp, result
                return result
            aim, pitch, flight = solved
            yaw = math.atan2(aim[0] - frame['origin'][0], aim[2] - frame['origin'][2])
            direction = (math.sin(yaw) * math.cos(pitch), -math.sin(pitch),
                         math.cos(yaw) * math.cos(pitch))
            reach = _mechanical(frame['descriptor'], direction, frame['body'])
            path = ballistics.ballistic_path(frame['origin'], yaw, pitch, speed, gravity, flight)
            solution = dict(target=entity.id, sample=sample, sample_value=samples[sample],
                point=tuple(aim), aim_position=tuple(aim), source_point=tuple(aim),
                yaw=yaw, pitch=pitch, flight_time=flight,
                direction=direction, velocity=target['velocity'], origin=frame['origin'],
                path=path, reachable=reach['status'] == 'reachable',
                needs_hull=reach['status'] == 'hull_laying',
                mechanical_reason=reach['reason'],
                target_pose=target['pose'], source_pose=frame['pose'],
                shell_index=shell['index'], source_verified=False,
                _aim_token=(id(entity), id(entity.typeDescriptor), samples[sample]))
            result = dict(path=path, reach=reach, solution=solution, sample_point=sample_point,
                          line_region=self._lane_region(path),
                          direction=direction, flight=flight)
            self.predictions[key] = stamp, result
            return result
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return None

    def _armour_geometry(self, frame, shell, target, sample_point, direction, flight):
        from ..entities.remote_vehicle import collide_vehicle_at_matrix
        owner, entity, shot = self.owner, target['entity'], shell['shot']
        speed = float(_field(shot, 'speed'))
        gravity = abs(float(_field(shot, 'gravity')))
        # The target collider is observed at the current pose. Use the same
        # relative-motion chord convention as the authoritative projectile
        # and first-trigger proof, not a stationary-target incidence angle.
        velocity = target.get('velocity') or (0., 0., 0.)
        arrival = (direction[0] * speed - velocity[0],
                   direction[1] * speed - gravity * flight - velocity[1],
                   direction[2] * speed - velocity[2])
        magnitude = math.sqrt(sum(value * value for value in arrival))
        direction = tuple(value / magnitude for value in arrival)
        shape = owner._collision_shape(entity.typeDescriptor)
        reach = max(10., 4. * max(abs(value) for value in shape))
        before = min(reach, math.sqrt(_distance_sq(frame['origin'], sample_point)))
        after = max(combat_rules.vehicle_material_trace_end(shot, 0.),
                    combat_rules.he_radius(shot) if shell['is_he'] else 0.)
        first = owner._vector(tuple(sample_point[index] - direction[index] * before
                                    for index in range(3)))
        last = owner._vector(tuple(sample_point[index] + direction[index] * after
                                   for index in range(3)))
        if not native_geometry_complete(entity):
            return None
        hits = collide_vehicle_at_matrix(entity, target['matrix'], first, last,
            owner._runtime.math, chassis_matrix=target['chassis'])
        if not hits:
            return None
        first_distance = min(float(hit.dist) for hit in hits)
        retained = combat_rules.vehicle_material_hits(
            hits, combat_rules.vehicle_material_trace_end(shot, first_distance))
        entry = tuple(float(first[index]) + direction[index] * first_distance
                      for index in range(3))
        distance = math.sqrt(_distance_sq(frame['origin'], entry))
        contact = combat_rules.resolve_armor_contact(shot, distance, retained,
                                                    penetration_factor=PENETRATION_FACTOR_65)
        passed = bool(contact is not None and contact['layer'] == 'structural' and
                      contact['result'] == 2)
        penetration = dict(armor='passed' if passed else 'failed',
                      penetration_threshold=PENETRATION_PROBABILITY,
                      penetration_factor=PENETRATION_FACTOR_65,
                      contact=None, expected_damage=None)
        return dict(penetration=penetration, retained=retained, distance=distance,
                    first_distance=first_distance, direction=direction, seed=(first, last, hits))

    def _he_damage(self, shell, target, geometry):
        owner, entity, shot = self.owner, target['entity'], shell['shot']
        result = dict(geometry['penetration'])
        first, last, hits = geometry['seed']
        direction = geometry['direction']
        distance, retained = geometry['distance'], geometry['retained']
        nominal = combat_rules.resolve_armor_contact(shot, distance, retained,
                                                     penetration_factor=1.)
        rolled = combat_rules.shell_nominal_damage(shot)
        if nominal is not None and nominal['layer'] == 'structural' and nominal['result'] == 2:
            result.update(contact=True, expected_damage=float(rolled))
            return result
        impact_distance = (float(nominal['distance']) if nominal is not None else
                           geometry['first_distance'])
        impact = tuple(float(first[index]) + direction[index] * impact_distance
                       for index in range(3))
        record = next((row for row in owner._records.values()
                       if row.get('engine_id') == entity.id), None)
        if record is None:
            return result
        blast = owner._projectile_he_blast_contact(
            dict(shooter_kind='player'), record, entity, shot, impact, rolled,
            state=dict(velocity=direction, gravity=(0., 0., 0.), elapsed=0.),
            seed=geometry['seed'])
        if blast is not None:
            result.update(contact=True, expected_damage=float(blast['damage']),
                          he_contact=dict(blast))
        return result

    def evaluate_ranked_recheck(self, frame, shell, target, sample, mode, now, channel):
        # Preserve a share of the same chord budget for the fair scan, even
        # when a long path cannot complete the retained point this frame.
        return self.evaluate(frame, shell, target, sample, mode, now, channel,
                             world_limit=WORLD_CHORDS_PER_FRONTIER // 2)

    def evaluate(self, frame, shell, target, sample, mode, now, channel, world_limit=None):
        result = dict(armor='unknown', line='unknown', mechanical='unknown',
                      reason='native_geometry_unavailable', contact=None,
                      expected_damage=None)
        try:
            owner, entity, shot = self.owner, target['entity'], shell['shot']
            if channel == 'atomic' and self.atomic_clock() >= self.atomic_deadline:
                self.atomic_receipt['reason'] = 'atomic_frame_budget_exhausted'
                return result
            key = (shell['index'], target['key'], sample, mode)
            predicted = (self._atomic_predictions.get(key) if channel == 'atomic' else None)
            if predicted is None:
                predicted = self._prediction(frame, shell, target, sample)
            if predicted is None:
                return result
            if channel == 'atomic' and key not in self._atomic_predictions:
                self._atomic_predictions[key] = predicted
                self.atomic_receipt['priced_candidates'] += 1
                self.atomic_receipt['priced_world_chords'] += max(0, len(predicted['path']) - 1)
                if len(self._atomic_predictions) == len(self._atomic_domain):
                    self.atomic_receipt['world_budget'] = self.atomic_receipt['priced_world_chords']
            if predicted.get('unreachable'):
                result.update(mechanical='mechanical_limited', reason=predicted['reason'])
                return result
            path, reach = predicted['path'], predicted['reach']
            solution = dict(predicted['solution'], source_pose=frame['pose'], mode=mode,
                            penetration_threshold=(None if mode == 'he_fallback' else
                                                   PENETRATION_FACTOR_65))
            sample_point, direction, flight = predicted['sample_point'], predicted['direction'], predicted['flight']
            result['mechanical'] = reach['status']
            result['solution'] = solution
            result['line_region'] = predicted['line_region']
            geometry = (frame['planning_pose'], target['pose'], shell['signature'],
                        target['velocity'], frame['identity'])
            job = self.jobs.get(key[:3])
            if job is None or job['geometry'] != geometry:
                job = dict(geometry=geometry, scene=frame['scene'], cursor=0, done=False,
                           blocked=None, armour=None, he=None, lane=None)
                self.jobs[key[:3]] = job
            elif job['scene'] != frame['scene']:
                job.update(scene=frame['scene'], cursor=0, done=False, blocked=None, lane=None)
            available = self._budgets.get(channel, 0)
            allowance = min(available, world_limit) if world_limit is not None else available
            budget = allowance
            while not job['done'] and job['cursor'] < len(path) - 1 and budget > 0:
                if channel == 'atomic' and self.atomic_clock() >= self.atomic_deadline:
                    self.atomic_receipt['reason'] = 'atomic_frame_budget_exhausted'
                    break
                first, last = path[job['cursor']], path[job['cursor'] + 1]
                hit = owner._runtime.bigworld.wg_collideSegment(
                    owner._avatar.spaceID, owner._vector(first), owner._vector(last), 128)
                if channel == 'atomic':
                    self.atomic_receipt['world_chords'] += 1
                budget -= 1
                job['cursor'] += 1
                if hit is not None:
                    job['blocked'] = _point(hit[0])
                    job['done'] = True
            self._budgets[channel] = available - (allowance - budget)
            if job['cursor'] >= len(path) - 1:
                job['done'] = True
            if not job['done']:
                result.update(line='pending', reason='world_proof_pending')
                if channel == 'atomic' and budget <= 0:
                    self.atomic_receipt['reason'] = 'atomic_world_budget_exhausted'
                return result
            if job['blocked'] is not None:
                result.update(line='world_blocked', reason='world_blocked',
                              blocker=dict(point=job['blocked'], kind='world'))
                return result
            if frame['lane_missing']:
                result.update(line='unknown', reason='lane_geometry_unavailable')
                return result
            stamp = self.lane_stamp(frame, predicted['line_region'])
            cached = job['lane']
            if cached is not None and cached[0] == stamp:
                verdict = cached[1]
            else:
                verdict = self.runtime.geometry._bot_friendly_path_verdict(frame['source'], path, 0.)
                if channel == 'atomic':
                    self.atomic_receipt['friendly_path_calls'] += 1
                if isinstance(verdict, dict) and (verdict.get('clear') is True or
                        verdict.get('blocker_team') == frame['source']['team']):
                    job['lane'] = (stamp, verdict)
            if not isinstance(verdict, dict) or verdict.get('clear') is not True:
                friendly = isinstance(verdict, dict) and verdict.get('blocker_team') == frame['source']['team']
                result.update(line='friendly_blocked' if friendly else 'unknown',
                              reason='friendly_blocked' if friendly else 'lane_geometry_unavailable',
                              blocker=dict(verdict or {}))
                return result
            result['line'] = 'clear'
            if reach['status'] != 'reachable':
                result['reason'] = reach['reason']
                return result
            if job['armour'] is None:
                if channel == 'atomic':
                    if (self.atomic_clock() >= self.atomic_deadline or
                            self.atomic_receipt['armour_collision_batches'] >= ATOMIC_ARMOUR_BATCHES):
                        self.atomic_receipt['reason'] = 'atomic_armour_budget_exhausted'
                        return result
                    self.atomic_receipt['armour_collision_batches'] += 1
                job['armour'] = self._armour_geometry(frame, shell, target, sample_point,
                                                      direction, flight)
            if job['armour'] is None:
                result['reason'] = 'native_armour_unknown'
                return result
            if mode == 'he_fallback':
                blast_stamp = frame['scene'], frame['debris']
                if job['he'] is None or job['he'][0] != blast_stamp:
                    damage = self._he_damage(shell, target, job['armour'])
                    if damage.get('contact') is True:
                        job['he'] = (blast_stamp, damage)
                else:
                    damage = job['he'][1]
                result.update(damage)
            else:
                result.update(job['armour']['penetration'])
            result['reason'] = ('verified' if result['armor'] == 'passed' else
                                'armour_failed' if result['armor'] == 'failed' else
                                'native_armour_unknown')
            solution['clear'] = True
            solution['armor'] = result['armor']
            solution['he_contact'] = result.get('contact')
            solution['expected_damage'] = result.get('expected_damage')
            return result
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return result
