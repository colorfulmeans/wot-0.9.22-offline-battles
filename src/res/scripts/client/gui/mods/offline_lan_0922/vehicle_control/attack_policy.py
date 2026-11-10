"""Actor-local pointwise attack planning above the shared driving laws.

This policy changes attack intent, never throttle/turn integration or physical
trigger execution.  The foreground frontier examines the mounted shell first;
the independent background frontier compares every stocked shell and target.
An armour proof and a currently clear firing lane are separate facts.
"""
from __future__ import division

import math

from .actor_observation import observation
from .evaluation_budget import EvaluationBudget
import time

from .. import ballistics, combat_rules, gun_pitch_limits, shot_geometry
from ..gun_mechanics import _field
from ..projectile_runtime import PROJECTILE_BROADPHASE_RADIUS
from . import ammunition_validation, stationary_plan, stationary_scope


PENETRATION_PROBABILITY = .65
# Lower 35th percentile of the existing bounded, three-sigma penetration law.
# Resolving a structural penetration at this multiplier proves at least 65%
# under that law, without drawing a prospective shot's random penetration.
PENETRATION_FACTOR_65 = .9679810530375992
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


def _combat_targets(runtime):
    # Runtime admission belongs to the shared combat owner. The fallback
    # supports observation-only fixtures which predate that runtime seam.
    targets = getattr(runtime, 'combat_targets', None)
    return targets() if targets is not None else runtime.visible_targets()


def _combat_signature(runtime):
    return getattr(getattr(runtime, 'combat_stop', None), 'signature', None)


def _shell_rank(shell):
    return (0 if shell.get('is_he') else 1,
            float(shell['piercing']), int(shell['index']))


def limited_traverse(descriptor):
    """Classify the mounted gun, independently of clip and siege support."""
    limits = _field(descriptor.gun, 'turretYawLimits')
    if limits is None:
        return False
    low, high = float(limits[0]), float(limits[1])
    if (not all(not math.isnan(value) and not math.isinf(value)
                for value in (low, high)) or high < low):
        raise ValueError('installed gun yaw limits are invalid')
    return high - low < 2. * math.pi - 1.e-5


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
    """Exact physical barrel observation from the controlled actor."""
    return observation(runtime).source_pose(origin)



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
                'explosionEdgeDamageFactor', 'compactDescr', 'name')))


def native_geometry_complete(entity):
    """Missing attached collision data is unknown, not an absent component."""
    names = ('chassis', 'hull')
    if not bool(getattr(entity, 'isTurretDetached', False)):
        names += ('turret', 'gun')
    descriptor = getattr(entity, 'typeDescriptor', None)
    return descriptor is not None and all(callable(getattr(
        _field(_field(descriptor, name), 'hitTester'), 'localHitTest', None)) for name in names)


def native_lane_geometry_complete(runtime):
    """Close friendly/dead-hull geometry before a shared clear-lane verdict."""
    owner = runtime.owner
    for record in owner._records.values():
        if observation(runtime).owns_record(record) or record.get('tombstone') or not record.get('ready'):
            continue
        entity = owner._server_entity(record.get('engine_id'))
        if entity is None or not getattr(entity, 'isStarted', False):
            return False
        state = record.get('state') or {}
        alive = bool(entity.isAlive()) and state.get('alive', True)
        if (not alive or int(state.get('team', record.get('team', 0))) == int(observation(runtime).actor_team)):
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
    """One ammunition decision belongs to the gun, not a selected enemy.

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
        self._physical_review = None
        self.selected = None
        self._current_he_execution = None
        self.trigger = None
        self.foreground_cursor = 0
        self.he_cursor = 0
        self.he_comparison = dict(total=0, observed=0, pending=0)
        self._current_he_observations = {}
        self._current_he_deferred = set()
        self.background_cursor = None
        self.reload_authority = None
        self.fallback = False
        self.next_shell = None
        self.next_plan = None
        self.next_status = 'not_observed'
        self.next_proofs = ()
        self.next_domain = None
        self.loading_plan = None
        self._penetration_hints = {}
        self._single_point_trials = {}
        self._single_point_history = {}
        self._next_edge_at = float('-inf')
        self.next_edge_receipt = {}
        self.proof_revocations = dict(source=0, target=0, domain=0, shell=0, lane_rechecks=0)
        self.background_coverage = ()
        self.navigation_receipt = None
        self.failure_domains = {}
        self._identity = None
        self._weapon_identity = None
        self._combat_signature = None
        self._magazine = None
        self._foreground_at = None
        self._background_at = None
        self._atomic_at = float('-inf')
        self._atomic_target_cursor = None
        self._atomic_frame = None
        self._atomic_started = None
        self._atomic_deadline = float('-inf')
        self._atomic_receipt = dict(status='not_started')
        self._move_episode = 0
        self._move_kind = None
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
                                       float(shell['piercing']))),
                frame.get('combat_signature'))

    def _line_stamp(self, frame, region=None):
        local_stamp = getattr(self.evaluator, 'lane_stamp', None)
        if region is not None and callable(local_stamp):
            return local_stamp(frame, region)
        return frame.get('scene'), frame.get('line_revision')

    def _single_point_trial(self, shell, target=None):
        """Keep one ordinary HE attempt per enemy, not a full plate proof.

        Source settling cannot restart a decision to use HE contact damage.
        A different target or changed target geometry gets a new attempt;
        actual HE contact and every launch still require current geometry.
        """
        if ammunition_validation.shell_mode(shell) != ammunition_validation.SINGLE_POINT:
            return None
        targets = self.frame.get('targets', ())
        if not targets:
            return None
        # NEXT is a future load, not a change of the currently operated gun
        # target. It must not restart an already completed HE attempt.
        intention = self.selected or (self.loading_plan or {}).get('key')
        trial = self._single_point_trials.get(shell['index'])
        if target is None:
            retained = next((row for row in targets if trial is not None and
                             _target_key(row) == trial['target_key']), targets[0])
            target = next((row for row in targets if intention is not None and
                           _target_key(row) == intention[1]), retained)
        identity = _target_key(target)
        signature = shell.get('signature', (shell['index'], shell.get('piercing')))
        history_key = (shell['index'], identity)
        trial = self._single_point_history.get(history_key)
        samples = target.get('samples') or (None,)
        if (trial is None or trial['target_key'] != identity or
                trial['shell_signature'] != signature or
                trial['target_pose'] != target.get('pose') or
                trial['velocity'] != target.get('velocity') or trial['sample'] not in samples):
            sample = (intention[2] if intention is not None and intention[1] == identity and
                      intention[2] in samples else samples[0])
            trial = dict(target_key=identity, sample=sample, shell_signature=signature,
                         target_pose=target.get('pose'), velocity=target.get('velocity'),
                         failed=False)
            self._single_point_history[history_key] = trial
        self._single_point_trials[shell['index']] = trial
        return trial

    def _single_point_failed(self, index):
        shell = next((row for row in self.frame['shells'] if row['index'] == index), None)
        if (shell is None or ammunition_validation.shell_mode(shell) !=
                ammunition_validation.SINGLE_POINT):
            return False
        targets = self.frame.get('targets', ())
        return bool(targets) and all(self._single_point_trial(shell, target)['failed']
                                     for target in targets)

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
                trial = self._single_point_trial(shell, target)
                if mode == 'penetration' and trial is not None and trial['failed']:
                    continue
                # Missing geometry remains an explicit unknown obligation.
                samples = ((trial['sample'],) if trial is not None else
                           target.get('samples') or (None,))
                for sample in samples:
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
        scope_current = getattr(self.evaluator, 'scope_current', None)
        if (row.get('scope') == 'excluded' and callable(scope_current) and
                not scope_current(self.frame, row.get('scope_proof'))):
            return None
        plan = row.get('stationary_plan')
        plan_current = getattr(self.evaluator, 'stationary_plan_current', None)
        if (plan is not None and callable(plan_current) and
                not plan_current(self.frame, plan.get('proof'))):
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

    def _executable_current(self, row, mode='penetration'):
        """Current gun consumption is separate from the global armour domain."""
        if not self._executable(row, mode):
            return False
        allowed = getattr(getattr(self, 'runtime', None), 'attack_candidate_consumable', None)
        return not callable(allowed) or allowed(row)

    @classmethod
    def _planned_evidence(cls, row):
        """A proved future stationary pose is planning data, never fire data."""
        plan = (row or {}).get('stationary_plan')
        if (not isinstance(plan, dict) or plan.get('status') != 'proved' or
                (plan.get('proof') or {}).get('proved') is not True):
            return None
        return plan

    @classmethod
    def _plannable(cls, row, mode='penetration'):
        # Loading another cassette is not launching its first round. A
        # proved native stationary turn may rank that future load, but the
        # exact physical barrel still has to satisfy _executable at firing.
        return cls._executable(row, mode) or cls._executable(cls._planned_evidence(row), mode)

    @staticmethod
    def _matching_admission_block(blocked, stamp):
        previous = blocked['pose_stamp']
        # A native lane refusal briefly steers the search away from its
        # point. Source-only refreshes still retire every positive proof, but
        # must not erase this bounded retry on the very next observation.
        return (previous == stamp or (blocked['reason'] in NATIVE_LINE_RETRY_REASONS and
                previous[0] == stamp[0] and previous[2:] == stamp[2:]))

    @classmethod
    def _needs_firing_position(cls, row):
        planned = cls._planned_evidence(row)
        if (row.get('armor') != 'passed' and planned is not None and
                planned.get('line') == 'clear' and planned.get('mechanical') == 'reachable' and
                planned.get('armor') == 'failed'):
            # This point is no longer an unexamined yaw obstruction. Turning
            # toward its known failure would destroy the source snapshot
            # before the other stationary-domain points can be completed.
            return False
        return (row.get('line') in ('friendly_blocked', 'world_blocked', 'enemy_blocked', 'vehicle_blocked') or
                row.get('mechanical') in ('hull_laying', 'mechanical_limited'))

    def _physical_review_source(self, shell):
        return (self.frame['identity'], self.frame.get('weapon_identity'),
                self.frame['position'], int(shell['index']), shell.get('signature'))

    @staticmethod
    def _physical_review_cause(row):
        obstacle = row.get('blocker') or {}
        identity = tuple((name, obstacle.get(name)) for name in
            ('actor_key', 'kind', 'vehicle_id', 'blocker_kind', 'blocker_id', 'blocker_team'))
        if not any(value is not None for unused, value in identity):
            identity += (('point', obstacle.get('point')),)
        return row['target_key'], row.get('line'), identity

    def _record_physical_review(self, job, row):
        review = self._physical_review
        if (review is None or
                self._physical_review_source(job[1]) != review['source']):
            return
        if job[0] == review['anchor'] and row is not None:
            clear = row.get('line') == 'clear' and row.get('mechanical') == 'reachable'
            blocked = row.get('line') in ('friendly_blocked', 'world_blocked',
                                           'enemy_blocked', 'vehicle_blocked')
            if (self._he_observation_identity(job) != review['anchor_identity'] or clear or
                    blocked and self._physical_review_cause(row) != review['cause']):
                self._physical_review = None
                return
        # The existing observation-completion check also rejects projected
        # pending work. A terminal unavailable observation means only that
        # this point was inspected, never that its armour failed.
        if job[4] == 'penetration' and self._he_observed(row):
            review['observed'][job[0]] = self._he_observation_identity(job)

    def _physical_review_pending(self, shell_index, blocker):
        """Finish one inspection pass, not a simultaneous firing snapshot.

        Other vehicles may keep laying their guns while a known obstruction
        prevents this gun from firing. Requiring all their point receipts to
        remain exact at once makes physical recovery depend on machine speed.
        Only coverage survives pose changes; every launch and global armour
        certificate still uses _current and its original exact fences.
        """
        fresh = self.current_row(blocker, require_line=True)
        if (self._frame_invalid or fresh is None or not (
                fresh.get('line') in ('friendly_blocked', 'world_blocked',
                                      'enemy_blocked', 'vehicle_blocked') or
                fresh.get('mechanical') in ('hull_laying', 'mechanical_limited'))):
            return True
        shell = next(row for row in self.frame['shells'] if row['index'] == shell_index)
        source = self._physical_review_source(shell)
        review = self._physical_review
        if review is not None and review['source'] == source:
            anchor = next((job for job in self._jobs(review['anchor'][3], shell_index)
                           if job[0] == review['anchor']), None)
            if anchor is None or self._he_observation_identity(anchor) != review['anchor_identity']:
                self._physical_review = None
            else:
                self._record_physical_review(anchor, self._current(anchor, require_line=True))
        review = self._physical_review
        if review is None or review['source'] != source:
            anchor = next(job for job in self._jobs(fresh['mode'], shell_index)
                          if job[0] == fresh['key'])
            review = self._physical_review = dict(source=source,
                cause=self._physical_review_cause(fresh), anchor=fresh['key'],
                anchor_identity=self._he_observation_identity(anchor), observed={})
        # Which blocked sample was fresh this frame is scheduling, not a new
        # task. Only an observed change of the anchored obstruction, or its
        # departure from the domain, retires this inspection episode.
        jobs = self._jobs(shell_index=shell_index)
        identities = dict((job[0], self._he_observation_identity(job)) for job in jobs)
        for key in list(review['observed']):
            if review['observed'][key] != identities.get(key):
                review['observed'].pop(key, None)
        for job in jobs:
            self._record_physical_review(job, self._current(job, require_line=True))
        return any(job[0] not in review['observed'] for job in jobs)

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
            if line != 'unknown' or row['line'] not in ('friendly_blocked', 'world_blocked', 'enemy_blocked', 'vehicle_blocked'):
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
        observations = (row, row.get('stationary_plan'))
        for observation in observations:
            if isinstance(observation, dict) and observation.get('expected_damage') is not None:
                damage = float(observation['expected_damage'])
                if (math.isnan(damage) or math.isinf(damage) or damage < 0. or
                        observation.get('contact') is not True):
                    observation['expected_damage'], observation['contact'] = None, None
                else:
                    observation['expected_damage'] = damage
        self.rows[key] = row
        self._record_physical_review(job, row)
        if (mode == 'penetration' and
                ammunition_validation.shell_mode(shell) == ammunition_validation.SINGLE_POINT and
                row['armor'] == 'failed' and row['line'] == 'clear' and
                row['mechanical'] == 'reachable'):
            trial = self._single_point_trial(shell, target)
            if trial is not None and (trial['target_key'], trial['sample']) == (key[1], sample):
                trial['failed'] = True
                # The reduced ordinary-HE obligation is now a policy choice,
                # never a fabricated all-points/all-enemies armour failure.
                self._job_lists = {}
        if mode == 'penetration' and self._plannable(row):
            self._penetration_hints[row['shell_index']] = key
        self._used[channel] += 1
        return row

    def _frontier(self, now):
        jobs = self._jobs(shell_index=self.frame['loaded'])
        if not jobs:
            return None
        # A background NEXT plan cannot take over the currently loaded gun.
        # Only a current intention or the load which actually began may lead.
        plan_key = self.selected or (self.loading_plan or {}).get('key')
        # A retained aim is a target/sample intention, not an ammunition or
        # armour proof. In particular, the same HE point may alternate
        # between penetration and fallback without losing its aim priority.
        # Rotate the remaining finite frontier as before: an unresolved
        # preferred target must not starve the other observed enemies.
        if plan_key is not None:
            jobs = tuple(job for job in jobs if job[0][1] == plan_key[1]) + tuple(
                job for job in jobs if job[0][1] != plan_key[1])
        selected_job = next((job for job in jobs if plan_key is not None and
                             job[0][1:3] == plan_key[1:3]), None)
        if selected_job is not None:
            row = self._current(selected_job, require_line=True)
            if self._executable_current(row):
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
            projected = self._planned_evidence(row)
            projected_complete = bool(projected is not None and
                projected.get('line') == 'clear' and self._reviewed(projected, 'penetration'))
            if (row is None or not projected_complete and
                    (row.get('armor') in ('pending', 'unknown') or row.get('line') != 'clear')):
                row = self._evaluate(job, now, 'foreground')
            if self._executable_current(row):
                return row
        # A prior frame/background proof can be the earliest useful point.
        for job in jobs:
            row = self._current(job, require_line=True)
            if self._executable_current(row):
                return row
        return None

    def _rows_for(self, mode, shell_index=None, executable=False, fresh_line=False,
                  plannable=False):
        result = []
        for job in self._jobs(mode, shell_index):
            row = self._current(job, require_line=executable or plannable or fresh_line)
            if (row is not None and (not executable or self._executable(row, mode)) and
                    (not plannable or self._plannable(row, mode))):
                result.append(row)
        return result

    def _failure_domain(self, indices):
        """Keep an excluded geometric domain distinct from armour failure.

        A current yaw limit, blocked ray or navigation timeout is not an
        exclusion certificate. Only a native stationary-scope proof can
        exclude a point; an empty remaining domain still cannot qualify.
        """
        indices = tuple(sorted(set(indices)))
        jobs = [job for job in self._jobs() if job[0][0] in indices]
        counts = dict(total=len(jobs), failed=0, passed=0, excluded=0,
                      projected_failed=0, projected_passed=0,
                      geometry_pending=0, armor_pending=0, unobserved=0,
                      single_point_failed=sum(self._single_point_failed(index) for index in indices),
                      strategy_excluded=tuple(index for index in indices
                          if self._single_point_failed(index)))
        for job in jobs:
            row = self._current(job, require_line=True)
            if row is None:
                counts['unobserved'] += 1
            elif (row.get('scope') == 'excluded' and
                  (row.get('scope_proof') or {}).get('scope') == 'excluded'):
                counts['excluded'] += 1
            elif row.get('line') != 'clear' or row.get('mechanical') != 'reachable':
                projected = self._planned_evidence(row)
                if (projected is None or projected.get('line') != 'clear' or
                        projected.get('mechanical') != 'reachable'):
                    counts['geometry_pending'] += 1
                elif projected.get('armor') == 'failed':
                    counts['projected_failed'] += 1
                elif projected.get('armor') == 'passed':
                    counts['projected_passed'] += 1
                else:
                    counts['armor_pending'] += 1
            elif row.get('armor') == 'failed':
                counts['failed'] += 1
            elif row.get('armor') == 'passed':
                counts['passed'] += 1
            else:
                counts['armor_pending'] += 1
        counts['all_failed'] = bool((counts['failed'] or counts['projected_failed']) and
            self.frame.get('targets') and
            not any(counts[name] for name in ('passed', 'projected_passed', 'geometry_pending',
                                             'armor_pending', 'unobserved')))
        self.failure_domains[indices] = counts
        return counts

    def _all_failed(self, indices):
        return self._failure_domain(indices)['all_failed']

    def _stocked_indices(self, exclude=None):
        return tuple(shell['index'] for shell in self.frame['shells']
                     if shell['index'] != exclude and self.frame['ammo'][shell['index']] > 0)

    def _fallback_qualified(self, indices):
        """Combine exact negative proof with completed ordinary-HE trials.

        Removed single-point jobs do not make an empty armour universe a
        negative certificate. Every caller supplies its actual stocked
        alternatives, including HE whose one-point trial has already ended.
        """
        indices = tuple(sorted(set(indices)))
        remaining = tuple(index for index in indices if not self._single_point_failed(index))
        return self._all_failed(remaining) if remaining else bool(indices)

    def _loaded_he_fallback_targets(self, loaded):
        """Keep current HE fallback local to each proved enemy domain.

        A blocked or unavailable other enemy is not a failed armour point,
        but cannot veto a legal current HE contact on a fully reviewed enemy.
        These keys never qualify NEXT or global armour failure.
        """
        shell = next((row for row in self.frame['shells'] if row['index'] == loaded), None)
        if shell is None or not shell.get('is_he'):
            return frozenset()
        targets = self.frame.get('targets', ())
        failed, incomplete = set(), set()
        if ammunition_validation.shell_mode(shell) == ammunition_validation.SINGLE_POINT:
            failed.update(_target_key(target) for target in targets
                          if self._single_point_trial(shell, target)['failed'])
            # A native stationary plan can finish the remaining single
            # attempt for recovery, but never becomes a durable actual
            # failure or permission to fire from the current physical pose.
        # One pass over the loaded shell, not a repeated all-ammunition
        # failure-domain scan for every enemy in a crowded battle.
        for job in self._jobs(shell_index=loaded):
            row, key = self._current(job, require_line=True), job[0][1]
            if row is not None and row.get('scope') == 'excluded' and (
                    row.get('scope_proof') or {}).get('scope') == 'excluded':
                continue
            proof = row
            if proof is not None and (proof.get('line') != 'clear' or
                                      proof.get('mechanical') != 'reachable'):
                proof = self._planned_evidence(proof)
            if (proof is not None and proof.get('line') == 'clear' and
                    proof.get('mechanical') == 'reachable' and proof.get('armor') == 'failed'):
                failed.add(key)
            else:
                incomplete.add(key)
        return frozenset(failed - incomplete)

    def _best_penetration(self, exclude=None, plannable=False):
        rows = [row for row in self._rows_for('penetration',
                executable=not plannable, plannable=plannable)
                if row['shell_index'] != exclude]
        if not rows:
            return None
        return min(rows, key=self._penetration_order)

    def _penetration_order(self, row):
        return (_shell_rank(row['shell']), self._intent_order(row['key']),
                repr(row['target_key']), repr(row['sample']))

    def _intent_order(self, key):
        # Keep the existing shell/damage ranking outside this tie-breaker.
        # A mode rebind may preserve this key while discarding all its rows;
        # it grants only evaluation/selection priority, never shot authority.
        if self.selected is None or key[1] != self.selected[1]:
            return 2
        return 0 if key[2] == self.selected[2] else 1

    def _best_he(self, shell_index=None, exclude=None, plannable=False, consumable=False):
        jobs = tuple(job for job in self._jobs('he_fallback', shell_index)
                     if job[0][0] != exclude)
        if not all(self._he_observed(self._current(job, require_line=True)) for job in jobs):
            return None
        rows = [row for row in self._rows_for('he_fallback', shell_index,
                executable=not plannable, plannable=plannable)
                if row['shell_index'] != exclude and
                    (not consumable or self._executable_current(row, 'he_fallback'))]
        if not rows:
            return None
        return min(rows, key=lambda row: (-float((row if self._executable(row, 'he_fallback')
                   else self._planned_evidence(row))['expected_damage']),
                   self._intent_order(row['key']),
                   _shell_rank(row['shell']), repr(row['target_key']),
                   repr(row['sample'])))

    def _plan_next(self, row, status='verified', proofs=()):
        self.next_plan = row
        self.next_shell = row['shell_index'] if row is not None else None
        self.next_status = status
        self.next_proofs = proofs
        self.next_domain = self._next_domain(row['mode']) if row is not None else None

    def _next_domain(self, mode):
        # Row identity fences changes to a compared point, not newly added
        # points. A NEXT ranking also belongs to its exact stocked candidate
        # domain; a new enemy or ammunition slot must receive a fair review.
        exclude = self._next_excluded()
        modes = ('penetration', 'he_fallback') if mode == 'he_fallback' else ('penetration',)
        return (exclude, frozenset(job[0] for candidate_mode in modes
                    for job in self._jobs(candidate_mode) if job[0][0] != exclude))

    @classmethod
    def _he_observed(cls, row):
        # An unavailable contact is not zero damage. It may be left out of
        # this positive ranking only after receiving an actual observation;
        # an unvisited or unfinished point may still beat the first contact.
        # This is not an armour-failure/exclusion certificate.
        if (row is None or row.get('line') == 'pending' or row.get('stationary_progress') or
                row.get('review_pending')):
            return False
        projected = cls._planned_evidence(row)
        return projected is None or cls._he_observed(projected)

    def _he_frontier(self, now, shell_index=None):
        """Compare the finite HE point domain using the existing work budget."""
        jobs = self._jobs('he_fallback', shell_index)
        if not jobs:
            self.he_comparison = dict(total=0, observed=0, pending=0)
            return True
        start = self.he_cursor
        for offset in range(len(jobs)):
            if self._used['foreground'] >= self.foreground_budget:
                break
            position = (start + offset) % len(jobs)
            job = jobs[position]
            row = self._current(job, require_line=True)
            if self._he_observed(row):
                continue
            self.he_cursor = (position + 1) % len(jobs)
            self._evaluate(job, now, 'foreground')
        if any(not self._he_observed(self._current(job, require_line=True)) for job in jobs):
            self._atomic_he_compare(jobs, now)
        observed = sum(self._he_observed(self._current(job, require_line=True))
                       for job in jobs)
        if observed == len(jobs):
            # A native query can re-enter Python while the final competitor
            # is being observed. A completed foreground pass needs the same
            # whole-domain publication fence as a completed atomic pass.
            fence = getattr(self.evaluator, 'fence', None)
            if not callable(fence) or not fence(self.frame):
                self.rows.clear()
                self.selected = None
                self._frame_invalid = True
                observed = 0
        self.he_comparison = dict(total=len(jobs), observed=observed,
                                  pending=len(jobs) - observed)
        return not self._frame_invalid and observed == len(jobs)

    def _he_observation_identity(self, job):
        # Normal motion revokes firing rows, not a finite ranking pass. A
        # different shell, entity or sample layout cannot inherit that pass.
        unused_key, shell, target, unused_sample, unused_mode = job
        return (self.frame['identity'], shell.get('signature'),
                target.get('sample_identity'), target.get('samples'))

    def _choose_current_he(self, reason, candidate):
        """Qualify a completed comparison's actual, uncommitted aim only."""
        decision = self._choose('aim', reason, candidate)
        if decision['action'] == 'aim':
            job = next((job for job in self._jobs('he_fallback', self.frame['loaded'])
                        if job[0] == self.selected), None)
            if job is not None:
                # This is execution phase/identity, never a firing row or
                # damage hint. It cannot select or revive a different key.
                self._current_he_execution = (job[0], self._he_observation_identity(job))
        return decision

    def _continue_current_he(self, now):
        """Reprove the current HE point until its first physical commit.

        A new competitor or NEXT plan cannot restart the comparison while
        its winner is still being laid. Every pose, line and mechanical
        proof is nevertheless current; real failure uses normal recovery.
        """
        execution = self._current_he_execution
        if execution is None:
            return None
        key, identity = execution
        job = next((job for job in self._jobs('he_fallback', self.frame['loaded'])
                    if job[0] == key), None)
        if (self.selected != key or job is None or
                self._he_observation_identity(job) != identity or
                self.frame['clip'] <= 0 and not self.frame.get('reloading')):
            self._current_he_execution = None
            return None
        row = self._current(job, require_line=True)
        if not self._he_observed(row) and self._used['foreground'] < self.foreground_budget:
            self._evaluate(job, now, 'foreground')
            row = self._current(job, require_line=True)
        # Ranking has already finished for this trigger. Fence its current
        # source, selected target and line, not unrelated competitors which
        # may move during a native query. With no row to scope, keep the
        # conservative observation fence; it cannot grant a firing proof.
        fence = getattr(self.evaluator, 'fence_next', None)
        if row is not None and callable(fence):
            valid = fence(self.frame, (row,), False)
        else:
            fence = getattr(self.evaluator, 'fence', None)
            valid = callable(fence) and fence(self.frame)
        if not valid:
            self.rows.clear()
            self.selected = None
            self._current_he_execution = None
            self._frame_invalid = True
            return self._recover_incomplete(now, 'current_he_observation_changed')
        if self._he_observed(row) and self._executable_current(row, 'he_fallback'):
            self.fallback = True
            reason = ('current_he_clip_fallback' if int(self.frame.get('clip_size', 1)) > 1
                      else 'he_fallback_contact')
            return self._choose('aim', reason, row)
        if not self._he_observed(row):
            # A finished ranking may defer a now-pending recheck in favour
            # of another fresh contact. Keep its measured damage hint, never
            # turn the pending value into zero or a new movement authority.
            if row is None:
                return self._recover_incomplete(now, 'current_he_evidence_pending')
            self._current_he_deferred.add(key)
            self._current_he_execution = None
            return None
        self._current_he_execution = None
        self._collect_current_he_observations((job,), self._current_he_observations,
                                             self._current_he_deferred)
        # A real refusal ends this point's execution, not CURRENT HE. Review
        # the remaining same-shell contacts before granting movement; a front
        # enemy may itself be the next legal stationary contact.
        return None

    def _collect_current_he_observations(self, jobs, observations, deferred=None):
        for job in jobs:
            row = self._current(job, require_line=True)
            if not self._he_observed(row):
                continue
            evidence = (row if self._executable(row, 'he_fallback') else
                        self._planned_evidence(row))
            damage = (evidence.get('expected_damage') if
                      self._executable(evidence, 'he_fallback') else None)
            # Only measured ranking data lives here: never a solution, plate
            # result, launch permission, NEXT plan or negative certificate.
            observations[job[0]] = dict(identity=self._he_observation_identity(job),
                                        damage=damage)
            if deferred is not None:
                deferred.discard(job[0])

    def _ranked_current_he_jobs(self, jobs, observations):
        return sorted((job for job in jobs if
                       observations.get(job[0], {}).get('damage') is not None),
            key=lambda job: (-observations[job[0]]['damage'], self._intent_order(job[0]),
                             _shell_rank(job[1]), repr(job[0][1]), repr(job[3])))

    def _best_current_he(self, loaded, consumable=False, observations=None, deferred=None):
        observations = (self._current_he_observations if observations is None else
                        observations)
        deferred = self._current_he_deferred if deferred is None else deferred
        jobs = self._jobs('he_fallback', loaded)
        eligible = self._loaded_he_fallback_targets(loaded)
        # A proved usable CURRENT contact is enough to fire this trigger.
        # Unobserved competitors may be better, but cannot hold an already
        # loaded HE round indefinitely. Completed competitors remain ranked.
        for job in self._ranked_current_he_jobs(jobs, observations):
            if job[0][1] not in eligible:
                continue
            row = self._current(job, require_line=True)
            if not self._he_observed(row):
                if job[0] in deferred:
                    # An already ranked point received its recheck but is
                    # unfinished. Let other ranked points prove a real shot;
                    # this does not declare the unfinished point zero damage.
                    continue
                # A stale high-ranked hint requests work; it cannot license
                # either its own shot or an unchecked lower-ranked shot.
                return None
            if (self._plannable(row, 'he_fallback') and
                    (not consumable or self._executable_current(row, 'he_fallback'))):
                return row
        return None

    def _current_he_frontier(self, now, loaded):
        """Finish one bounded positive ranking pass, then prove its live choice.

        A large moving domain cannot be observed in one frame. These hints
        preserve fair coverage across frames; every returned aiming row still
        comes from _current, and NEXT/armour failure use only strict rows.
        """
        jobs = self._jobs('he_fallback', loaded)
        identities = dict((job[0], self._he_observation_identity(job)) for job in jobs)
        observations = dict((key, value) for key, value in self._current_he_observations.items()
            if key in identities and value['identity'] == identities[key])
        deferred = self._current_he_deferred.intersection(observations)
        self._collect_current_he_observations(jobs, observations, deferred)
        refresh_unusable = bool(jobs and len(observations) == len(jobs) and not any(
            value['damage'] is not None for value in observations.values()))
        # A completed blocked/unknown comparison must not restart before a
        # fresh obstruction can reach geometric recovery. Retain coverage
        # only and refresh its finite queue within the original budget;
        # neither a shot nor a negative certificate can use these hints.
        start = self.he_cursor
        for offset in range(len(jobs)):
            if self._used['foreground'] >= self.foreground_budget:
                break
            position = (start + offset) % len(jobs)
            job = jobs[position]
            if job[0] in observations and not refresh_unusable:
                continue
            self.he_cursor = (position + 1) % len(jobs)
            self._evaluate(job, now, 'foreground')
            self._collect_current_he_observations((job,), observations, deferred)
        pending = tuple(job for job in jobs if job[0] not in observations)
        ready = self._best_current_he(loaded, consumable=True,
                                      observations=observations, deferred=deferred)
        if pending and ready is None:
            self._atomic_he_compare(pending, now)
            self._collect_current_he_observations(pending, observations, deferred)
        # The highest observation is only the next key to check. Recheck it
        # with the remaining original budgets; a changed/blocked winner is
        # demoted without restarting the entire candidate domain.
        checked = set()
        ranked = self._ranked_current_he_jobs(jobs, observations)
        if ranked and all(job[0] in deferred for job in ranked):
            # Every ranked key got a turn. Revisit the finite queue rather
            # than turning an incomplete probe into a permanent exclusion.
            deferred.clear()
        while len(observations) == len(jobs) and not self._frame_invalid:
            eligible = self._loaded_he_fallback_targets(loaded)
            job = next((job for job in self._ranked_current_he_jobs(jobs, observations)
                        if job[0] not in checked and job[0] not in deferred and
                        job[0][1] in eligible), None)
            if job is None:
                break
            checked.add(job[0])
            row = self._current(job, require_line=True)
            if not self._he_observed(row):
                if self._used['foreground'] < self.foreground_budget:
                    self._evaluate(job, now, 'foreground')
                else:
                    self._atomic_he_compare((job,), now)
                self._collect_current_he_observations((job,), observations, deferred)
                row = self._current(job, require_line=True)
                if not self._he_observed(row):
                    if row is None:
                        break
                    deferred.add(job[0])
                    continue
            if self._best_current_he(loaded, consumable=True, observations=observations,
                                     deferred=deferred) is not None:
                break
        fence = getattr(self.evaluator, 'fence', None)
        if self._frame_invalid or not callable(fence) or not fence(self.frame):
            self.rows.clear()
            self.selected = None
            self._frame_invalid = True
            # A reentrant query may invalidate this whole batch. Do not
            # publish even its ranking hints; previously fenced hints remain.
            observed = 0
        else:
            self._current_he_observations = observations
            self._current_he_deferred = deferred
            observed = len(observations)
        self.he_comparison = dict(total=len(jobs), observed=observed,
                                  pending=len(jobs) - observed)
        # A native budget receipt on a proved negative-penetration enemy is
        # not a genuine missing contact.  Under a slow 8 ms atomic slice the
        # first HE point can finish while the second merely runs out of work
        # quota. Do not turn that scheduling result into an irrevocable first
        # trigger lock before the pending point receives its next fair turn.
        # Explicitly pending native queries, replaced/moving competitors and
        # unqualified enemies must NOT hold an independently executable HE
        # contact hostage; they cannot certify a higher damage score.
        eligible = self._loaded_he_fallback_targets(loaded)
        competing_budget = False
        for job in jobs:
            if job[0][1] not in eligible or job[0] in observations:
                continue
            row = self._current(job, require_line=True)
            reason = (row or {}).get('reason') or ''
            if (row is not None and row.get('review_pending') and
                    reason.startswith('atomic_') and reason.endswith('_budget_exhausted')):
                competing_budget = True
                break
        if not competing_budget:
            receipt = self._atomic_receipt or {}
            reason = receipt.get('reason') or ''
            if (receipt.get('observed_at') == now and reason.startswith('atomic_') and
                    reason.endswith('_budget_exhausted')):
                # The slice may expire *after* the first positive contact,
                # before the next qualified enemy is even visited. That
                # unvisited point has no row-level budget receipt to inspect.
                # An explicitly pending native query is different: it must
                # not prevent firing the independently proved CURRENT HE.
                competing_budget = any(job[0][1] in eligible and
                    job[0] not in observations and
                    self._current(job, require_line=True) is None for job in jobs)
        return (not self._frame_invalid and not competing_budget and
            (observed == len(jobs) or
             self._best_current_he(loaded, consumable=True,
                                   observations=observations, deferred=deferred) is not None))

    def _atomic_he_compare(self, jobs, now):
        """Finish a moving HE domain within the same bounded atomic slice.

        Negative ammunition proof and HE ranking must sometimes coexist in
        one source observation. Reuse that slice's remaining time, world and
        armour budgets; opening another slice must obey its existing cadence.
        No unobserved or stale contact becomes a zero-damage candidate.
        """
        if self._frame_invalid:
            return
        if self._atomic_frame is not self.frame:
            if now < self._atomic_at + ATOMIC_CLOSE_INTERVAL or len(jobs) > ATOMIC_MAX_JOBS:
                return
            if not self._optional_work_budget(now).atomic(self._work_actor()):
                return
            self._atomic_at = now
            self._used['atomic'] = 0
            self._atomic_started = self.atomic_clock()
            self._atomic_deadline = self._atomic_started + self.atomic_time_budget
            self._atomic_receipt = dict(status='he_comparison', candidates=len(jobs),
                                        observed_at=now, evaluations=0)
            begin = getattr(self.evaluator, 'begin_atomic', None)
            self.evaluator.atomic_deadline = self._atomic_deadline
            self.evaluator.atomic_clock = self.atomic_clock
            if (not callable(begin) or not callable(getattr(self.evaluator, 'fence', None)) or
                    not begin(self.frame, jobs, now)):
                self._atomic_receipt.update(getattr(self.evaluator, 'atomic_receipt', {}))
                self._atomic_receipt.setdefault('reason', 'atomic_observation_unavailable')
                return
            self._atomic_frame = self.frame
        for job in jobs:
            if self.atomic_clock() >= self._atomic_deadline or self._used['atomic'] >= ATOMIC_CANDIDATES:
                self._atomic_receipt['reason'] = 'atomic_frame_budget_exhausted'
                break
            if not self._he_observed(self._current(job, require_line=True)):
                self._evaluate(job, now, 'atomic')
        if not self.evaluator.fence(self.frame):
            self.rows.clear()
            self.selected = None
            self._frame_invalid = True
            self._atomic_receipt['status'] = 'pose_changed'
        self._atomic_receipt.update(getattr(self.evaluator, 'atomic_receipt', {}))
        self._atomic_receipt.update(evaluations=self._used['atomic'],
            elapsed_ms=(self.atomic_clock() - self._atomic_started) * 1000.)

    @classmethod
    def _reviewed(cls, row, mode):
        if row is None:
            return False
        if (row.get('scope') == 'excluded' and
                (row.get('scope_proof') or {}).get('scope') == 'excluded'):
            return True
        projected = cls._planned_evidence(row)
        if projected is not None:
            return cls._reviewed(projected, mode)
        if row.get('stationary_progress'):
            return False
        if row.get('line') in ('friendly_blocked', 'world_blocked', 'enemy_blocked', 'vehicle_blocked'):
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
            options = [row for row in rows if self._plannable(row)]
            if options:
                best = min(options, key=self._penetration_order)
                return best, 'verified', tuple(checked + [best])
            if not all(self._reviewed(row, 'penetration') for row in rows):
                return None, 'higher_rank_pending', ()
            checked.extend(rows)
        return None, 'no_verified_penetration', tuple(checked)

    def _penetration_groups(self, jobs, current=None):
        groups = []
        for job in jobs:
            index = job[0][0]
            if not groups or groups[-1][0] != index:
                groups.append((index, []))
            groups[-1][1].append(current[job[0]] if current is not None and job[0] in current else
                                 self._current(job, require_line=True))
        return groups

    def next_at_edge(self):
        plan = self.next_plan
        current = self.current_row(plan)
        if plan is None:
            return None, self.next_status
        if self.next_domain != self._next_domain(plan['mode']):
            return None, 'rank_domain_changed'
        if not self._plannable(current, plan['mode']):
            return None, 'candidate_expired'
        proofs = self.next_proofs or (plan,)
        jobs = dict((job[0], job) for mode in ('penetration', 'he_fallback')
                    for job in self._jobs(mode))
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
        if best is None and status == 'no_verified_penetration':
            if self._fallback_qualified(self._stocked_indices(exclude)):
                best = self._best_he(exclude=exclude, plannable=True)
                if best is not None:
                    he_rows = tuple(self._current(job, require_line=True)
                                    for job in self._jobs('he_fallback') if job[0][0] != exclude)
                    status, proofs = 'verified_he_fallback', proofs + he_rows
                elif any(not self._he_observed(self._current(job, require_line=True))
                         for job in self._jobs('he_fallback') if job[0][0] != exclude):
                    status = 'he_damage_comparison_pending'
            else:
                # A checked blocked lane can reject a penetration candidate
                # for ranking. It cannot prove that its unknown plate failed
                # and thereby authorise the independent HE fallback plan.
                status = 'fallback_evidence_incomplete'
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
            if any(self._plannable(row) for row in rows):
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
            ('identity', 'source', 'target', 'velocity', 'shell', 'combat_domain'), old, new)
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
        if not self._optional_work_budget(now).atomic(self._work_actor()):
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
            if self._plannable(row):
                break
            unresolved = unresolved or not self._reviewed(row, 'penetration')
        self._refresh_ranked_next(self._penetration_groups(self._jobs()), exclude)
        plan, reason = self.next_at_edge()
        self.next_edge_receipt = dict(at=now, checked=count, status=reason,
            result=(plan or {}).get('key'),
            elapsed_ms=(self.atomic_clock() - started) * 1000.)
        return plan, reason

    def load_started(self, shell_index, plan=None):
        self.selected = None
        self._current_he_execution = None
        self._physical_review = None
        self.reload_authority = None
        self.loading_plan = (plan if plan is not None and
                             plan['shell_index'] == shell_index else None)

    def current_row(self, candidate, require_line=True):
        if candidate is None or self.frame is None or self._frame_invalid:
            return None
        job = next((job for job in self._jobs(candidate['mode'], candidate['shell_index'])
                    if job[0] == candidate['key']), None)
        return self._current(job, require_line) if job is not None else None

    def intent_solution(self, candidate):
        """Return only an aiming/navigation point, not a firing certificate."""
        row = self.current_row(candidate)
        if (row is not None and not self._executable(row, row['mode']) and
                self._plannable(row, row['mode'])):
            return self._planned_evidence(row)['solution']
        return (candidate or {}).get('solution') or {}

    @staticmethod
    def _apply_native_range(command, solution):
        # The final engine distance guard must use the same mounted shell as
        # the native solution. A role profile's preferred range is not a
        # physical limit; this field does not replace any launch proof.
        maximum = solution.get('fire_range')
        if (isinstance(maximum, (int, float)) and maximum > 0. and
                not math.isinf(maximum) and not math.isnan(maximum)):
            command['fire_range'] = maximum

    def _recover_incomplete(self, now, reason, rows=()):
        if self._evidence_wait_since is None:
            self._evidence_wait_since = now
        candidate = next((row for row in rows if row['key'] == self.selected and
                          isinstance(row.get('solution'), dict)), None)
        # A query's age proves neither an obstruction nor armour failure.
        # Keep the admitted task and let the bounded frontier continue;
        # physical recovery needs its own observed cause.
        if (candidate is not None and candidate.get('mechanical') == 'reachable' and
                candidate.get('line') in ('clear', 'pending') and
                self.decision['action'] in ('aim', 'preaim')):
            return self._choose('preaim', reason, candidate)
        return self._choose('wait', reason)

    def _clear_fallback(self):
        self.fallback = False
        self.reload_authority = None

    def _failure_fenced(self, indices=None):
        fence = getattr(self.evaluator, 'fence', None)
        valid = not callable(fence) or fence(self.frame)
        proofs = tuple(row for row in self.rows.values()
                       if row.get('mode') == 'penetration' and
                       (indices is None or row['shell_index'] in indices))
        scope_current = getattr(self.evaluator, 'scope_current', None)
        if valid and callable(scope_current):
            # A native query may synchronously observe an engine repair.
            # That reopens a fixed-support exclusion even if the geometric
            # snapshot and all ordinary armour stamps stayed identical.
            valid = all(scope_current(self.frame, row.get('scope_proof'))
                        for row in proofs if row.get('scope') == 'excluded')
        plan_current = getattr(self.evaluator, 'stationary_plan_current', None)
        if valid and callable(plan_current):
            valid = all(plan_current(self.frame, row['stationary_plan'].get('proof'))
                        for row in proofs if row.get('stationary_plan') is not None)
        if not valid:
            self.rows.clear()
            self._frame_invalid = True
            return False
        return True

    def _grant_early_reload(self, now, reason):
        # Qualification survives physical movement. The next clip's point
        # proof does not: every changed pose still requires its own review.
        self.reload_authority = dict(identity=self._weapon_identity,
            loaded=self.frame['loaded'], clip=self.frame['clip'],
            qualified_at=now, reason=reason)

    def _early_reload_decision(self, loaded):
        authority = self.reload_authority
        groups = self._penetration_groups(self._jobs())
        alternative, status, unused_proofs = self._ranked_penetration(
            groups, exclude=loaded)
        if (alternative is None and status == 'no_verified_penetration' and
                self._fallback_qualified(self._stocked_indices(loaded))):
            alternative = self._best_he(exclude=loaded, plannable=True)
        # Pending review does not revoke the already qualified reload. It
        # leaves the replacement unspecified; the existing partial-reload
        # input may continue the currently legal shell. Never substitute an
        # unproved alternative just to finish the reload transaction.
        index = alternative['shell_index'] if alternative is not None else loaded
        return self._choose('reload_clip', authority['reason'], alternative,
            shell_index=index, early_reload=True,
            reload_qualified_at=authority['qualified_at'],
            replacement_status=status if alternative is None else 'verified')

    def current_target_key(self):
        """Return this actor's current intention, never a reusable shot proof.

        Ordinary strategic hints cannot replace an acquired point or its
        recovery. Visibility, weapon identity and the next native snapshot
        still invalidate targets/rows normally; this adds no target timer.
        """
        if self.decision.get('action') in ('unchanged', 'navigate'):
            return None
        if self.selected is not None:
            return self.selected[1]
        target = (self.decision.get('move_request') or {}).get('target')
        if target is None:
            target = (self.decision.get('candidate') or {}).get('target')
        return _target_key(target) if isinstance(target, dict) else None

    def _choose(self, action, reason, candidate=None, **fields):
        if (action == 'aim' and candidate is not None and
                not self._executable_current(candidate, candidate.get('mode', 'penetration'))):
            action, reason, candidate = 'wait', 'current_shot_navigation_owned', None
        if (action in ('aim', 'navigate', 'unchanged', 'switch_shell', 'reload_clip',
                       'trigger_active') or reason == 'no_relevant_enemy'):
            # A recovered shot or another task ends this obstruction's
            # inspection pass. Waiting for the same native work does not.
            self._physical_review = None
        row = dict(action=action, reason=reason, candidate=candidate,
                   next_shell=self.next_shell,
                   phase=('preaiming' if action == 'preaim' or action == 'aim' and
                          (self.frame or {}).get('reloading') else action),
                   fallback=bool(self.fallback),
                   foreground_queries=self._used['foreground'],
                   background_queries=self._used['background'])
        row.update(fields)
        if action == 'firing_position':
            if self._move_kind != action:
                self._move_episode += 1
            self._move_kind = action
            episode_id = (self._identity, self._combat_signature, action, self._move_episode)
            row['move_request'] = dict(kind=action, reason=reason,
                target=candidate.get('target') if candidate else None,
                sample=candidate.get('sample') if candidate else None,
                shell_index=candidate.get('shell_index') if candidate else None,
                mode=candidate.get('mode') if candidate else None,
                key=candidate.get('key') if candidate else None,
                solution=self.intent_solution(candidate) if candidate else None,
                blocker=candidate.get('blocker') if candidate else None,
                episode_id=episode_id)
        elif action not in ('wait', 'preaim', 'trigger_active'):
            # A native query wait changes evidence status, not the accepted
            # movement task. A real aim/navigation/loading transition still
            # completes the old phase before a later recovery starts anew.
            self._move_kind = None
        self.decision = row
        if action in ('aim', 'preaim', 'firing_position', 'switch_shell', 'reload_clip') and candidate is not None:
            # Intent stability and evidence validity are separate lifetimes.
            # A zero-width gun must be able to finish laying toward one point
            # even though every hull step invalidates that point's old proof.
            self.selected = candidate['key']
        elif action not in ('trigger_active', 'wait'):
            self.selected = None
        if (self._current_he_execution is not None and
                (self._current_he_execution[0] != self.selected or
                 action not in ('aim', 'preaim', 'wait'))):
            self._current_he_execution = None
        if action == 'aim' or reason == 'no_relevant_enemy':
            self._evidence_wait_since = None
        return row

    def _atomic_close(self, now):
        """Close a finite negative universe in one current-pose observation.

        Normal two-point slices cannot accumulate negative proof for a turret
        moving on every frame. This separately rate-limited frontier can close
        a small moving domain within strict work/time limits. A larger stable
        domain retains only its still-current rows across bounded attempts.
        Missing or blocked points keep the certificate open while the rest
        of the budget checks other points. A positive current-shell result
        stops this work immediately.
        """
        if now < self._atomic_at + ATOMIC_CLOSE_INTERVAL:
            return None
        loaded = self.frame['loaded']
        loaded_he = any(shell['index'] == loaded and shell.get('is_he')
                        for shell in self.frame['shells'])
        jobs = self._jobs(shell_index=loaded if loaded_he else None)
        if not jobs:
            return None
        if not self._optional_work_budget(now).atomic(self._work_actor()):
            return None
        self._atomic_at = now
        self._atomic_frame = None
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
        self._atomic_started, self._atomic_deadline = started, deadline
        self.evaluator.atomic_deadline = deadline
        self.evaluator.atomic_clock = self.atomic_clock
        # Include the possible HE comparison in this same budget universe;
        # it reuses real ray/component work after a completed negative review.
        budget_jobs = jobs + self._jobs('he_fallback', loaded if loaded_he else None)
        if not callable(begin) or not callable(fence) or not begin(self.frame, budget_jobs, now):
            self._atomic_receipt.update(getattr(self.evaluator, 'atomic_receipt', {}))
            self._atomic_receipt.setdefault('reason', 'atomic_observation_unavailable')
            return None
        self._atomic_frame = self.frame
        # All-or-nothing negative publication. The foreground/background map
        # is restored if even one object changes during this synchronous pass.
        jobs = sorted(jobs, key=lambda job: (
            0 if job[0][0] == self.frame['loaded'] else 1,
            _shell_rank(job[1]), self._intent_order(job[0]),
            repr(job[2]['key']), repr(job[3])))
        if loaded_he and len(jobs) > ATOMIC_CANDIDATES:
            # CURRENT full HE needs a complete enemy's point domain, not an
            # incomplete prefix of every enemy. Rotate whole target groups
            # between bounded attempts; unknown early actors cannot forever
            # prevent a later actor from receiving its same-pose review.
            cursor = self._atomic_target_cursor
            split = next((index + 1 for index in range(len(jobs) - 1, -1, -1)
                          if jobs[index][0][1] == cursor), 0)
            jobs = jobs[split:] + jobs[:split]
        positive = None
        for offset, job in enumerate(jobs):
            if self.atomic_clock() >= deadline or self._used['atomic'] >= ATOMIC_CANDIDATES:
                self._atomic_receipt['reason'] = 'atomic_frame_budget_exhausted'
                break
            row = self._current(job, require_line=True)
            if not self._reviewed(row, 'penetration'):
                row = self._evaluate(job, now, 'atomic')
            if loaded_he:
                self._atomic_target_cursor = job[0][1]
            if self._plannable(row):
                positive = row
                break
            if ('first_unresolved' not in self._atomic_receipt and (
                    row['armor'] != 'failed' or row['line'] != 'clear' or
                    row['mechanical'] != 'reachable')):
                self._atomic_receipt['first_unresolved'] = dict(
                    key=row['key'], reason=row.get('reason'), armor=row['armor'],
                    line=row['line'], mechanical=row['mechanical'])
            if self.frame.get('lane_missing'):
                break
            if (loaded_he and len(jobs) > ATOMIC_CANDIDATES and
                    (offset + 1 == len(jobs) or jobs[offset + 1][0][1] != job[0][1]) and
                    job[0][1] in self._loaded_he_fallback_targets(loaded)):
                # Spend the remainder of this SAME slice on current contact
                # ranking. This is one enemy's HE execution qualification,
                # never global failure, NEXT proof or a fresh work budget.
                break
        if not fence(self.frame):
            self.rows.clear()
            self._physical_review = None
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
        return (positive if positive is not None and
                positive['shell_index'] == self.frame['loaded'] and self._executable_current(positive)
                else None)

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
        weapon_identity = frame.get('weapon_identity', identity)
        combat_signature = frame.get('combat_signature')
        if self._identity is not None and (identity != self._identity or
                weapon_identity != self._weapon_identity or
                combat_signature != self._combat_signature):
            # A native siege descriptor changes every mechanical/trajectory
            # proof, but is not itself a different physical loaded cassette.
            # A changed admitted combat domain likewise retires geometric
            # evidence, not an already qualified reload transaction.
            # Retain only the target/sample intention and an already admitted
            # reload transaction for the same physical gun. Rows, trigger
            # proof, loading/NEXT plans and all geometry are still discarded.
            same_weapon = weapon_identity == self._weapon_identity
            same_geometry_identity = identity == self._identity and same_weapon
            authority = self.reload_authority if same_weapon else None
            selected = self.selected if same_weapon else None
            atomic_at = self._atomic_at
            next_edge_at = self._next_edge_at
            trials = self._single_point_trials
            trial_history = self._single_point_history
            he_observations = self._current_he_observations
            he_deferred = self._current_he_deferred
            he_execution = self._current_he_execution
            he_cursor = self.he_cursor
            recovery = (self.fallback, self._move_episode, self._move_kind)
            self.reset()
            self.reload_authority = authority
            self.selected = selected
            if same_weapon:
                # A siege/descriptor transition changes every geometric
                # proof, not an already qualified fallback or laying task.
                self.fallback, self._move_episode, self._move_kind = recovery
            if same_geometry_identity:
                # A changed shared-combat admission domain retires evidence,
                # not the rate limit on expensive speculative work or the
                # already completed ordinary-HE attempt on the same target.
                self._atomic_at = atomic_at
                self._next_edge_at = next_edge_at
                self._single_point_trials = trials
                self._single_point_history = trial_history
                self._current_he_observations = he_observations
                self._current_he_deferred = he_deferred
                self._current_he_execution = he_execution
                self.he_cursor = he_cursor
        self._identity = identity
        self._weapon_identity = weapon_identity
        self._combat_signature = combat_signature
        self.frame = frame
        admitted = set(_target_key(target) for target in frame.get('targets', ()))
        slots = set(shell['index'] for shell in frame.get('shells', ()))
        for key in list(self._single_point_history):
            if key[0] not in slots or key[1] not in admitted:
                self._single_point_history.pop(key, None)
        for index in list(self._single_point_trials):
            if index not in slots or self._single_point_trials[index]['target_key'] not in admitted:
                self._single_point_trials.pop(index, None)
        self.failure_domains = {}
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
            self._current_he_execution = None
        loaded = int(frame['loaded'])
        if self.loading_plan is not None and self.loading_plan['shell_index'] != loaded:
            self.loading_plan = None
        magazine = (loaded, int(frame['clip']))
        previous = self._magazine
        if previous is not None and (loaded != previous[0] or magazine[1] > previous[1]):
            # A genuinely different shell/clip gets a new current-contact
            # comparison without inheriting the previous trigger's ranking.
            self._current_he_observations.clear()
            self._current_he_deferred.clear()
            # A completed load retains the point already being laid. A
            # different loaded shell requires its own point and proof.
            if self.selected is not None and self.selected[0] != loaded:
                self.selected = None
                self._current_he_execution = None
        self._magazine = magazine
        authority = self.reload_authority
        if (authority is not None and (authority['identity'] != weapon_identity or
                authority['loaded'] != loaded or authority['clip'] != frame['clip'] or
                frame.get('reloading') and frame['clip'] <= 0)):
            self.reload_authority = None
        if frame.get('artillery'):
            return self._choose('unchanged', 'copied_artillery_owner')
        if frame.get('trigger_active'):
            return self._choose('trigger_active', 'physical_trigger_owns_tail',
                                self.trigger)
        if not any(amount > 0 for amount in frame.get('ammo', ())):
            self._current_he_observations.clear()
            self._current_he_deferred.clear()
            return self._choose('navigate', 'ammunition_exhausted')
        if not frame.get('targets'):
            self._current_he_observations.clear()
            self._current_he_deferred.clear()
            empty_clip = (int(frame.get('clip_size', 1)) > 1 and frame['clip'] <= 0 and
                          not frame.get('reloading'))
            if frame['ammo'][loaded] <= 0 or empty_clip:
                # No observed target can support a prior ranked plan.
                planned = (loaded if frame['ammo'][loaded] > 0 else
                           min(index for index, count in enumerate(frame['ammo']) if count > 0))
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
        continuing_he = self._continue_current_he(now)
        if continuing_he is not None:
            return continuing_he
        current = self._frontier(now)
        current_load = frame['ammo'][loaded] > 0 and (frame['clip'] > 0 or frame.get('reloading'))
        if current_load and self._single_point_failed(loaded):
            return self._ordinary_he_decision(loaded, now)
        if current is None and not any(row.get('armor') == 'passed'
                for row in self._rows_for('penetration', loaded)):
            current = self._atomic_close(now)
        if self._frame_invalid:
            return self._recover_incomplete(now, 'observation_changed_during_atomic_close')
        if current_load and self._single_point_failed(loaded):
            return self._ordinary_he_decision(loaded, now)
        is_magazine = int(frame.get('clip_size', 1)) > 1
        if frame['ammo'][loaded] <= 0:
            # Exhaustion is not a fabricated penetration failure. There is no
            # current round/clip to preserve when selecting stocked
            # ammunition for normal loading.
            groups = self._penetration_groups(self._jobs())
            planned, status, unused_proofs = self._ranked_penetration(groups)
            if (planned is None and status == 'no_verified_penetration' and
                    self._fallback_qualified(self._stocked_indices())):
                planned = self._best_he(plannable=True)
            index = (planned['shell_index'] if planned is not None else
                     min(shell['index'] for shell in frame['shells']
                         if frame['ammo'][shell['index']] > 0))
            return self._choose('reload_clip' if is_magazine else 'switch_shell',
                'current_ammunition_exhausted', planned, shell_index=index,
                early_reload=False)
        if is_magazine and frame['clip'] <= 0 and not frame.get('reloading'):
            groups = self._penetration_groups(self._jobs())
            planned, status, unused_proofs = self._ranked_penetration(groups)
            if (planned is None and status == 'no_verified_penetration' and
                    self._fallback_qualified(self._stocked_indices())):
                planned = self._best_he(plannable=True)
            index = planned['shell_index'] if planned is not None else loaded
            if frame['ammo'][index] <= 0:
                index = min((shell for shell in frame['shells']
                             if frame['ammo'][shell['index']] > 0), key=_shell_rank)['index']
            return self._choose('reload_clip', 'empty_clip', planned,
                                shell_index=index, early_reload=False)
        if current is not None:
            self._clear_fallback()
            return self._choose('aim', 'current_shell_verified', current)
        if any(self._executable(row) for row in self._rows_for('penetration', loaded, fresh_line=True)):
            # A proved plate can belong to a different gun target while the
            # original navigation is still moving or laying the hull. Keep
            # that positive evidence for ammunition/background decisions, but
            # do not grant a shot which the current command cannot consume.
            return self._choose('wait', 'current_shot_navigation_owned')
        observed_current = self._rows_for('penetration', loaded, fresh_line=True)
        loaded_he = bool(next((shell.get('is_he')
            for shell in frame['shells'] if shell['index'] == loaded), False))
        if loaded_he and self._loaded_he_fallback_targets(loaded):
            # Another enemy's stationary review cannot veto a positively
            # verified current HE contact on a fully reviewed enemy.
            if not self._failure_fenced((loaded,)):
                return self._recover_incomplete(now, 'observation_changed_before_fallback')
            self.reload_authority = None
            self.fallback = True
            return self._fallback_decision(loaded, is_magazine, now)
        physical_blocker = next((row for row in observed_current if row.get('line') in (
            'friendly_blocked', 'world_blocked', 'enemy_blocked', 'vehicle_blocked')), None)
        if (physical_blocker is not None and
                self._physical_review_pending(loaded, physical_blocker)):
            return self._recover_incomplete(now, 'stationary_alternatives_pending', observed_current)
        valid_pen = [row for row in self._rows_for('penetration', loaded, fresh_line=True)
                     if row.get('armor') == 'passed' and self._needs_firing_position(row)]
        if valid_pen:
            self.reload_authority = None
            candidate = min(valid_pen, key=lambda row: (
                self._intent_order(row['key']),
                0 if row.get('mechanical') == 'hull_laying' else 1,
                repr(row['target_key']), repr(row['sample'])))
            return self._choose('firing_position', 'current_penetration_obstructed',
                                candidate, movement_reason=candidate.get('reason'))
        planned_pen = [row for row in self._rows_for('penetration', loaded, plannable=True)
                       if not self._executable(row)]
        if planned_pen:
            # A real safe stationary turn exposes a penetrable current-round
            # point. Let the original hull actuator realise it before using
            # HE fallback; never promote its future pose into an aim/fire row.
            self.reload_authority = None
            candidate = min(planned_pen, key=self._penetration_order)
            return self._choose('firing_position', 'current_penetration_after_stationary_turn',
                                candidate, movement_reason=candidate.get('reason'))
        current_failed = self._all_failed((loaded,))
        if loaded_he:
            # Every physically loaded HE round owns its execution, including
            # a single-shot gun. NEXT may choose another load, but cannot
            # discard this round while choosing the following load.
            self.reload_authority = None
            if current_failed:
                if not self._failure_fenced((loaded,)):
                    return self._recover_incomplete(now, 'observation_changed_before_fallback')
                self.fallback = True
                return self._fallback_decision(loaded, is_magazine, now)
        elif self.reload_authority is not None:
            return self._early_reload_decision(loaded)
        if not loaded_he and current_failed:
            ranked = self._ranked_penetration(
                self._penetration_groups(self._jobs()), exclude=loaded)[0]
            if ranked is not None:
                if not self._failure_fenced((loaded,)):
                    return self._recover_incomplete(now, 'observation_changed_before_reload')
                self._clear_fallback()
                if is_magazine:
                    self._grant_early_reload(now, 'current_shell_all_armour_failed')
                    return self._early_reload_decision(loaded)
                return self._choose('switch_shell', 'current_shell_all_armour_failed',
                                    ranked, shell_index=ranked['shell_index'])
        if self.fallback and not loaded_he:
            alternative = self._best_penetration(exclude=loaded, plannable=True)
            if alternative is not None:
                self._clear_fallback()
                if is_magazine:
                    self._grant_early_reload(now, 'new_penetration_opportunity')
                    return self._early_reload_decision(loaded)
                return self._choose('switch_shell',
                                    'new_penetration_opportunity', alternative,
                                    shell_index=alternative['shell_index'])
            return self._fallback_decision(loaded, is_magazine, now)
        stocked = tuple(shell['index'] for shell in frame['shells']
                        if frame['ammo'][shell['index']] > 0)
        if not loaded_he and self._fallback_qualified(stocked):
            if not self._failure_fenced(stocked):
                return self._recover_incomplete(now, 'observation_changed_before_fallback')
            self.fallback = True
            return self._fallback_decision(loaded, is_magazine, now)
        rows = self._rows_for('penetration', None if current_failed and not is_magazine else loaded,
                              fresh_line=True)
        if any(row.get('stationary_progress') for row in rows):
            # A bounded multi-frame preview has no movement authority until
            # it produces physical evidence or a complete negative domain.
            return self._recover_incomplete(now, 'stationary_domain_review_pending')
        obstructed = [row for row in rows if self._needs_firing_position(row)]
        if obstructed:
            return self._choose('firing_position', 'unverified_points_obstructed',
                min(obstructed, key=lambda row: (self._intent_order(row['key']),
                                                repr(row['target_key']), repr(row['sample']))))
        if ('budget' in self._atomic_receipt.get('reason', '') and
                self._atomic_receipt.get('status') != 'all_failed'):
            return self._recover_incomplete(now, 'global_snapshot_budget_pending', rows)
        return self._recover_incomplete(now, 'penetration_evidence_incomplete', rows)

    def _ordinary_he_decision(self, loaded, now):
        """Use the loaded HE after its one-point-per-enemy penetration trial."""
        self.reload_authority = None
        is_magazine = int(self.frame.get('clip_size', 1)) > 1
        # The HE frontier owns the remaining foreground contact slots. Do
        # not spend them repeatedly on an old first point before it can
        # finish the finite domain or refresh its highest ranked contact.
        # Physical HE magazine ownership includes whitelisted HE. The
        # planning role never grants permission to discard a loaded cassette.
        self.fallback = True
        return self._fallback_decision(loaded, is_magazine, now)

    def _fallback_decision(self, loaded, is_magazine, now):
        loaded_he = bool(next((shell.get('is_he') for shell in self.frame['shells']
                             if shell['index'] == loaded), False))
        complete = (self._current_he_frontier(now, loaded) if loaded_he else
                    self._he_frontier(now))
        if not complete:
            return self._recover_incomplete(now, 'he_damage_comparison_pending',
                self._rows_for('he_fallback', loaded, fresh_line=True))
        # The current trigger's HE contact cannot overwrite the independent
        # ranked next-load plan, even when the same shell wins both searches.
        current = (self._best_current_he(loaded) if loaded_he else None)
        best = (current if loaded_he else self._best_he(plannable=True))
        if best is None and loaded_he:
            best = current
        # Preserve damage ranking across currently consumable points. A
        # navigation-owned candidate remains a positive global observation,
        # but cannot monopolise the loaded trigger over another legal point.
        runnable = (self._best_current_he(loaded, consumable=True) if loaded_he else None)
        if runnable is not None:
            # A current usable contact outranks a stale higher-damage hint
            # that would need another position or a pending native recheck.
            return self._choose_current_he('current_he_fallback_contact', runnable)
        if is_magazine and current is not None:
            if self._executable(current, 'he_fallback'):
                return self._choose_current_he('current_he_clip_fallback', runnable or current)
            return self._choose('firing_position', 'current_he_clip_fallback_after_stationary_turn',
                                current)
        if best is not None:
            if best['shell_index'] == loaded:
                if self._executable(best, 'he_fallback'):
                    return self._choose_current_he('he_fallback_contact', runnable or best)
                return self._choose('firing_position', 'he_fallback_after_stationary_turn', best)
            if is_magazine:
                self._grant_early_reload(now, 'he_fallback_plan')
                return self._early_reload_decision(loaded)
            return self._choose('switch_shell',
                                'he_fallback_plan', best,
                                shell_index=best['shell_index'])
        he_shells = [shell for shell in self.frame['shells']
                     if shell.get('is_he') and self.frame['ammo'][shell['index']] > 0]
        if not he_shells:
            return self._choose('navigate', 'no_he_or_verified_penetration')
        rows = self._rows_for('he_fallback', loaded if loaded_he else None, fresh_line=True)
        blocked = next((row for row in rows if self._needs_firing_position(row) and
                        isinstance(row.get('solution'), dict)), None)
        if blocked is not None:
            if loaded_he and self._physical_review_pending(loaded, blocked):
                return self._recover_incomplete(now, 'stationary_alternatives_pending', rows)
            return self._choose('firing_position', 'he_fallback_obstructed', blocked)
        jobs = self._jobs('he_fallback', loaded if loaded_he else None)
        if jobs and all(self._he_contact_failed(self._current(job, require_line=True))
                        for job in jobs):
            return self._choose('navigate', 'he_contact_domain_failed')
        return self._recover_incomplete(now, 'he_contact_evidence_incomplete', rows)

    @staticmethod
    def _he_contact_failed(row):
        # Only an explicit, complete native no-contact result may end this
        # engagement. None, pending work, a blocked ray or a future hull pose
        # is not an HE contact failure at the current physical position.
        return bool(row is not None and row.get('line') == 'clear' and
            row.get('mechanical') == 'reachable' and row.get('contact') is False and
            not row.get('review_pending') and not row.get('stationary_progress'))

    def _work_actor(self):
        return int(getattr(self.runtime, 'actor_id', 0))

    def _optional_work_budget(self, now):
        engine = getattr(self.runtime, 'engine', None)
        begin = getattr(engine, '_begin_evaluation_frame', None)
        if callable(begin):
            return begin(now)
        # Law-only consumers without a physical engine use this same class
        # as a single actor. No worker or foreground evidence is shared.
        budget = getattr(self, '_standalone_work_budget', None)
        if budget is None:
            budget = self._standalone_work_budget = EvaluationBudget()
        budget.begin(float(now), (self._work_actor(),))
        return budget

    def background(self, now):
        """One independent, fair all-shell/all-target frontier after control."""
        now = float(now)
        if (self.frame is None or self.frame.get('artillery') or self._frame_invalid or
                self._background_at == now):
            return self.next_shell
        allowance = self._optional_work_budget(now).background(
            self._work_actor(), self.background_budget)
        if not allowance:
            # Queue deferral is not a candidate observation. Preserve rows,
            # the fair point cursor and NEXT.
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
        if allowance > 1 and pending and self._penetration_hints:
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
            if self._used['background'] >= allowance:
                break
            if job is recheck:
                continue
            self.background_cursor = key
            current[job[0]] = self._evaluate(job, now, 'background')
        if not pending:
            self.background_cursor = None
        # An ordinary-HE trial can leave the penetration universe during this
        # pass. Its strategy disposition must not become a stale NEXT proof.
        self._refresh_ranked_next(self._penetration_groups(self._jobs(), current), exclude)
        self.decision['background_queries'] = self._used['background']
        return self.next_shell

    def navigation_result(self, receipt):
        """Record normal same-point recovery without ammunition authority."""
        self.navigation_receipt = dict(receipt or {})

    def lay_stalled(self, candidate, now):
        self._lay_recovery = candidate, now + ATOMIC_CLOSE_INTERVAL

    def admission_failed(self, candidate, reason, blocker=None):
        """A first-edge refusal invalidates only its point, never its tank.

        Point evidence is not a launched shell's result. A still-valid armour
        proof survives a new friendly/world obstruction and remains owned by
        same-point geometric recovery rather than ammunition fallback.
        """
        if not isinstance(candidate, dict):
            return
        row = self.rows.get(candidate.get('key'))
        if row is None or row.get('pose_stamp') != candidate.get('pose_stamp'):
            return
        if (reason == 'auto_world_blocked' and
                (blocker or {}).get('ray_stage') == 'scatter'):
            # This actual trigger was refused, but the native centre ray
            # and selected stationary aim point were not geometrically
            # disproved. The next trigger still requires a complete fresh
            # admission; do not invent a firing-position recovery or retire
            # the otherwise valid selected point on one scattered path.
            return
        classifications = dict(auto_friendly_lane='friendly_blocked',
            auto_friendly_splash='friendly_blocked', auto_world_blocked='world_blocked',
            auto_front_vehicle=('enemy_blocked' if (blocker or {}).get('hostile') is True else
                                'friendly_blocked' if (blocker or {}).get('hostile') is False else
                                'vehicle_blocked'), auto_lane_geometry_unknown='unknown',
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
                now = self.frame['observed_at']
                self._admission_blocks[row['key']]['retry_at'] = now + ATOMIC_CLOSE_INTERVAL
            invalidate = getattr(self.evaluator, 'invalidate_line', None)
            if callable(invalidate):
                invalidate(row['key'])
        if reason in ('auto_pose_changed', 'auto_target_pose_changed',
                       'auto_source_pose_changed', 'auto_shell_changed'):
            self.rows.pop(row['key'], None)
        # The real barrel can still be laying toward a valid current point.
        # This refusal spends nothing and keeps only that intention; the
        # next attempt still needs fresh geometry and full native admission.
        laying_current = (reason == 'auto_gun_laying' and
                          self.selected == candidate.get('key') and
                          self._executable_current(row, row.get('mode', 'penetration')))
        if self.selected == candidate.get('key') and not laying_current:
            self.selected = None
            self._current_he_execution = None

    def shot_committed(self, event, pending):
        # Hit, miss, zero damage and penetration results are deliberately not
        # inputs. Only the physical group's first/final commit bounds its lock.
        if int(event.get('burst_index', 0)) == 0:
            self._current_he_execution = None
            self._physical_review = None
            self.trigger = (pending.get('player_control') or {}).get('candidate')
            if self.trigger is None:
                self.trigger = self.decision.get('candidate')
            # A committed edge consumes its proof, not its target/sample
            # intention. The following trigger revalidates current geometry;
            # unrelated background work cannot rotate a stationary gun onto
            # another point merely because a shell was fired.
            if self.trigger is not None:
                self.selected = self.trigger['key']
            self.loading_plan = None
        if int(event.get('burst_index', 0)) + 1 >= int(event.get('burst_count', 1)):
            self.trigger = None
            self._evidence_wait_since = None
            self._current_he_observations.clear()
            self._current_he_deferred.clear()

    def apply_order(self, order, now=None):
        """Only replace attack intent; shared navigation still owns motion."""
        decision = self.decision
        if decision['action'] == 'unchanged':
            return order
        if decision['action'] == 'trigger_active':
            return dict(order or {}, fire_allowed=False)
        result = dict(order or {})
        if self.stationary_review_wait():
            return self._stationary_review_order(result)
        candidate = decision.get('candidate')
        if candidate is not None:
            target = candidate['target']
            solution = self.intent_solution(candidate)
            owner = getattr(getattr(self, 'runtime', None), 'combat_stop', None)
            if owner is not None and not owner.stop_allowed:
                # The complete admitted domain still informs ammo/armour
                # decisions. It does not donate an authored advance or
                # mission's target/facing to another policy candidate.
                # During travel only refine the already selected gun target.
                selected = (result.get('target_kind'), result.get('target_id'))
                if _target_key(target) != selected:
                    return dict(result, fire_allowed=False)
                result['aim_position'] = solution.get('point')
            else:
                result.update(target_id=target.get('network_id', target.get('id')),
                              target_kind=target.get('kind'),
                              aim_position=solution.get('point'),
                              face_position=target.get('position'))
            AttackPolicy._apply_native_range(result, solution)
        result['shell_index'] = (decision.get('shell_index', self.frame['loaded'])
                                 if self.frame is not None else result.get('shell_index'))
        if decision['action'] == 'aim':
            result['fire_allowed'] = not self.frame.get('reloading')
        else:
            result['fire_allowed'] = False
        return result

    def stationary_review_wait(self):
        return (self.decision.get('action') == 'wait' and
                self.decision.get('reason') in ('stationary_domain_review_pending',
                                              'stationary_alternatives_pending',
                                              'he_damage_comparison_pending') and
                self.frame is not None)

    def _stationary_review_order(self, order):
        # CombatStop owns the short stop before the driver runs. This late
        # shooting overlay cannot park the route or discard its target.
        result = dict(order or {}, aim_position=None, fire_allowed=False)
        result.pop('_player_attack_solution', None)
        return result

    def select_command(self, source, command, target, now):
        decision = self.decision
        if decision['action'] in ('unchanged', 'trigger_active'):
            return command, target
        result = dict(command)
        result['_player_attack'] = decision
        if self.stationary_review_wait():
            return self._stationary_review_order(result), target
        candidate = decision.get('candidate')
        if candidate is not None:
            selected = candidate['target']
            # The driver has already solved this frame for its selected
            # contact. A late shooting callback may refine that contact's
            # point, never silently retarget the solved hull movement.
            if (not isinstance(target, dict) or
                    _target_key(selected) != _target_key(target) or
                    result.get('target_id') is not None and result['target_id'] not in
                    (target.get('id'), target.get('network_id')) or
                    result.get('target_kind') is not None and
                    result['target_kind'] != target.get('kind')):
                result['fire_allowed'] = False
                result.pop('_player_attack_solution', None)
                return result, target
            solution = self.intent_solution(candidate)
            result.update(aim_position=solution.get('point'),
                          _player_attack_solution=solution)
            AttackPolicy._apply_native_range(result, solution)
        if decision['action'] != 'aim':
            result['fire_allowed'] = False
        elif self._executable(candidate, candidate.get('mode', 'penetration')):
            # The physical gate may have examined another sample. Replace its
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
            stationary_plan=self._stationary_status(candidate),
            stationary_review=dict(wait=self.stationary_review_wait(),
                since=self._evidence_wait_since,
                progress=tuple(sorted(set(row['stationary_progress_token']
                    for row in self.rows.values() if row.get('stationary_progress') and
                    row.get('stationary_progress_token') is not None)))),
            next_shell=self.next_shell, fallback=self.fallback,
            next_status=self.next_status, background_coverage=self.background_coverage,
            he_comparison=dict(self.he_comparison),
            proof_revocations=dict(self.proof_revocations), next_edge=dict(self.next_edge_receipt),
            loading_plan=(self.loading_plan or {}).get('key'),
            next_target=(self.next_plan or {}).get('target_key'),
            next_sample=(self.next_plan or {}).get('sample'),
            next_point=((self.next_plan or {}).get('solution') or {}).get('point'),
            next_proof=dict((name, self.next_plan.get(name)) for name in
                            ('mode', 'armor', 'line', 'mechanical', 'observed_at',
                             'penetration_threshold', 'expected_damage')) if self.next_plan else None,
            next_stationary_plan=self._stationary_status(self.next_plan),
            foreground_queries=self._used['foreground'],
            background_queries=self._used['background'],
            atomic=dict(self._atomic_receipt),
            native_cache=dict(getattr(self.evaluator, 'cache_observations', {})),
            trigger_refresh=dict(getattr(self.evaluator, 'trigger_refresh_receipt', {})),
            ammunition_validation=tuple(dict(shell=shell['index'],
                mode=ammunition_validation.shell_mode(shell),
                gun=shell.get('gun_identity'), identity=shell.get('shell_identity'))
                for shell in (self.frame or {}).get('shells', ())),
            ordinary_he_trials=tuple(dict(shell=key[0], target=trial['target_key'],
                sample=trial['sample'], failed=trial['failed']) for key, trial in
                sorted(self._single_point_history.items())),
            reload_authority=dict(self.reload_authority or {}),
            failure_domains=tuple(dict(shells=indices, **counts)
                for indices, counts in sorted(self.failure_domains.items())),
            navigation=dict(self.navigation_receipt or {}))

    @staticmethod
    def _stationary_status(row):
        plan = (row or {}).get('stationary_plan')
        if not isinstance(plan, dict):
            return None
        return dict((name, plan.get(name)) for name in (
            'status', 'armor', 'line', 'mechanical', 'reason',
            'contact', 'expected_damage'))


class NativeAttackEvaluator(object):
    """Bounded real-plate observations for each shared-control actor."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.owner = runtime.owner
        self.jobs = {}
        self.predictions = {}
        self.armour_rays = {}
        self.cache_observations = dict(armour_batches=0, armour_ray_reuses=0)
        self._identity = None
        self._at = None
        self._budgets = {}
        self._recovery_probe = None
        self.observations = {}
        self.atomic_receipt = {}
        self._atomic_predictions = {}
        self._atomic_prices = {}
        self._combat_signature = None
        self.atomic_clock = _WALL_CLOCK
        self.atomic_deadline = float('inf')
        self.stationary_planner = stationary_plan.StationaryPlanner(runtime)
        self.trigger_refresh_receipt = {}

    def _target_observation(self, raw, now, same_slice=False):
        """Read one native target without advancing a policy frontier."""
        target = self.runtime.target_entity(raw)
        row = dict(key=_target_key(raw), value=raw, entity=target,
                   samples=(), pose=None)
        observed = None
        try:
            signature, matrix, chassis = native_target_pose(self.owner, target)
            row.update(pose=signature, matrix=matrix, chassis=chassis,
                       sample_identity=(signature[:2], signature[6:]),
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
                elif same_slice and previous is not None and now == previous[0]:
                    # A final-edge reread is not another time measurement.
                    # Keep the velocity actually observed this slice. A
                    # changed pose without elapsed time remains unknown.
                    if position != previous[1]:
                        raise ValueError('target moved without an observation interval')
                    velocity = previous[2]
                else:
                    velocity = (0., 0., 0.)
            row['velocity'] = _point(velocity)
            observed = (now, position, row['velocity'])
        except (AttributeError, TypeError, ValueError, RuntimeError, KeyError, IndexError):
            row['velocity'] = None
        return row, observed

    def refresh_trigger_solution(self, candidate, now):
        """Recompute one selected intention, leaving exact fire proof to admission.

        This performs at most one ballistic prediction and two reads of the
        selected target pose. It does no world/armour work, ranking, sample
        search, or policy-clock mutation. TriggerAdmission proves the actual
        centre ray, armour/HE contact and scattered path from the result.
        """
        receipt = dict(status='pending', reason='intent_unavailable',
                       work=dict(predictions=0, world_chords=0, armour_batches=0))
        self.trigger_refresh_receipt = receipt
        try:
            runtime, physical = self.runtime, observation(self.runtime)
            gun = runtime.gun
            index, sample, mode = (int(candidate['shell_index']),
                                   candidate['sample'], candidate['mode'])
            target_key = _target_key(candidate['target'])
            key = (index, target_key, sample, mode)
            if (candidate['key'] != key or gun.shot_index != index or
                    gun.ammo[index] <= 0):
                return None
            raw = next((row for row in _combat_targets(runtime)
                        if row.get('alive', True) and _target_key(row) == target_key), None)
            if raw is None:
                return None
            entity = physical.source_entity()
            descriptor = entity.typeDescriptor
            pose = native_source_pose(runtime)
            identity = tuple(physical.weapon_identity()) + (id(descriptor.gun),)
            ammo, clip = tuple(gun.ammo), gun.clip
            combat_signature, scene = _combat_signature(runtime), self._scene_stamp()
            target, unused_observed = self._target_observation(raw, float(now), same_slice=True)
            if (sample not in target['samples'] or target.get('pose') is None or
                    target.get('velocity') is None):
                receipt['reason'] = 'target_geometry_unavailable'
                return None
            shot = gun.shots[index]
            shell = dict(index=index, shot=shot, signature=_shell_signature(index, shot))
            frame = dict(identity=identity, pose=pose, planning_pose=_planning_pose(pose),
                         origin=pose[2], body=pose[1], descriptor=descriptor)
            receipt['work']['predictions'] = 1
            predicted = self._prediction(frame, shell, target, sample)
            if predicted is None or predicted.get('unreachable'):
                receipt['reason'] = 'intercept_unavailable'
                return None
            # Target/model observations may enter native callbacks. Fence
            # the exact frame after computing the new intention as well as
            # during the unchanged prepare/validate launch transaction.
            current = next((row for row in _combat_targets(runtime)
                            if row.get('alive', True) and _target_key(row) == target_key), None)
            if (current is None or runtime.target_entity(current) is not target['entity'] or
                    native_target_pose(self.owner, target['entity'])[0] != target['pose'] or
                    native_source_pose(runtime) != pose or runtime.gun is not gun or
                    tuple(physical.weapon_identity()) + (id(physical.source_entity().typeDescriptor.gun),) != identity or
                    gun.shot_index != index or tuple(gun.ammo) != ammo or gun.clip != clip or
                    _shell_signature(index, gun.shots[index]) != shell['signature'] or
                    _combat_signature(runtime) != combat_signature or self._scene_stamp() != scene):
                receipt['reason'] = 'observation_changed'
                return None
            velocity = tuple(current.get('velocity', ()))
            if len(velocity) == 3 and _point(velocity) != target['velocity']:
                receipt['reason'] = 'observation_changed'
                return None
            receipt.update(status='refreshed', reason='same_intention', key=key,
                           source_pose=pose, target_pose=target['pose'])
            return dict(predicted['solution'], source_pose=pose, mode=mode)
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            receipt['reason'] = 'native_geometry_unavailable'
            return None

    def snapshot(self, now):
        runtime, owner = self.runtime, self.owner
        source = runtime.current_source()
        gun = runtime.gun
        entity = observation(runtime).source_entity()
        descriptor = entity.typeDescriptor
        origin, unused_direction = observation(runtime).mutable_shot_ray()
        origin = _point(origin)
        pose = native_source_pose(runtime, origin)
        body = pose[1]
        combat_signature = _combat_signature(runtime)
        identity = tuple(observation(runtime).weapon_identity()) + (id(descriptor.gun),)
        if identity != self._identity:
            self.jobs.clear()
            self.predictions.clear()
            self.armour_rays.clear()
            self.cache_observations = dict(armour_batches=0, armour_ray_reuses=0)
            self._identity = identity
        # Admission changes revoke policy authority, not identical physical
        # observations of a target that remains admitted. Domain pruning below
        # removes departed targets; every cache still checks its exact inputs.
        self._combat_signature = combat_signature
        targets, observations = [], {}
        for raw in _combat_targets(runtime):
            if not raw.get('alive', True):
                continue
            row, observed = self._target_observation(raw, now)
            if observed is not None:
                observations[row['key']] = observed
            targets.append(row)
        self.observations = observations
        shells = []
        vehicle_name = str(_field(descriptor.type, 'name', '') or '')
        nation = vehicle_name.split(':', 1)[0] if ':' in vehicle_name else None
        gun_identity = self._mounted_identity(nation, _field(descriptor.gun, 'name'))
        for index, shot in enumerate(gun.shots):
            try:
                piercing = float(combat_rules.range_piercing(shot, 0.))
                native_shell = combat_rules.legacy_shot(shot).get('shell') or {}
                shell_identity = self._mounted_identity(nation, native_shell.get('name'))
                validation = ammunition_validation.validation_mode(
                    gun_identity, shell_identity, native_shell.get('kind'))
                shells.append(dict(index=index, is_he=combat_rules.is_he(shot),
                                   piercing=piercing, shot=shot,
                                   gun_identity=gun_identity, shell_identity=shell_identity,
                                   validation_mode=validation,
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
        frame = dict(identity=identity,
            weapon_identity=tuple(observation(runtime).weapon_identity()),
            combat_signature=combat_signature,
            source=source, pose=pose, planning_pose=planning_pose,
            position=pose[0], body=body, origin=origin,
            descriptor=descriptor, entity=entity, loaded=int(gun.shot_index),
            ammo=tuple(gun.ammo), clip=int(gun.clip), clip_size=int(gun.clip_size),
            reloading=float(gun.reload_time) > 0.,
            limited_traverse=limited_traverse(descriptor),
            trigger_active=observation(runtime).trigger_active(),
            artillery='SPG' in (descriptor.type.tags or ()),
            targets=tuple(targets), shells=tuple(shells),
            scene=scene, observed_at=now)
        self._observe_lanes(frame)
        if self._at != now:
            self._at = now
            active = getattr(getattr(runtime, 'combat_stop', None),
                             'physical_recovery_active', None)
            recovery = (WORLD_CHORDS_PER_FRONTIER // 2 if callable(active) and active() else 0)
            self._budgets = dict(foreground=WORLD_CHORDS_PER_FRONTIER - recovery,
                                 recovery=recovery,
                                 background=WORLD_CHORDS_PER_FRONTIER)
        valid = set((shell['index'], target['key'], sample)
                    for shell in shells if frame['ammo'][shell['index']] > 0
                    for target in targets for sample in target['samples'] or (None,))
        target_poses = dict((target['key'], (target['pose'], target['velocity']))
                            for target in targets)
        signatures = dict((shell['index'], shell['signature']) for shell in shells)
        for key in list(self.armour_rays):
            if key not in valid:
                self.armour_rays.pop(key, None)
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

    @staticmethod
    def _mounted_identity(nation, name):
        if not nation or not name:
            return None
        name = str(name)
        if ':' in name:
            return name if name.split(':', 1)[0] == nation else None
        return nation + ':' + name

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
        # radius as the shared lane resolver before quantising outwards.
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
            if observation(self.runtime).owns_record(record) or record.get('tombstone') or not record.get('ready'):
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
                if alive and team != int(observation(self.runtime).actor_team):
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

    def point_recovery_probe(self, frame, candidate, destination, now):
        """Preview only the selected sample's future line, never a shot proof.

        A translated muzzle is a planning hypothesis. Real native alignment,
        ground attitude, armour, the final scattered barrel path and the
        source/target fencing must all be rechecked at the reached position.
        The separate cursor is bounded by the reserved recovery chord budget;
        no incomplete ray may become a clear destination.
        """
        pending = dict(status='pending', reason='native_recovery_proof_pending')
        if not isinstance(frame, dict) or not isinstance(candidate, dict):
            return pending
        key = candidate.get('key')
        try:
            shell = next(row for row in frame['shells']
                         if row['index'] == candidate['shell_index'])
            target = next(row for row in frame['targets']
                          if row['key'] == candidate['target_key'])
            sample = candidate['sample']
            if sample not in (target.get('samples') or ()):
                return dict(status='unknown', reason='sample_unavailable')
            position = frame['position']
            destination = _point(destination)
            delta = tuple(destination[i] - position[i] for i in range(3))
            origin = tuple(frame['origin'][i] + delta[i] for i in range(3))
            pose = frame['pose']
            projected_pose = (destination, pose[1], origin, pose[3],
                              pose[4], pose[5],
                              tuple(pose[6][i] + delta[i] for i in range(3)))
            projected_frame = dict(frame, position=destination, origin=origin,
                                   pose=projected_pose,
                                   planning_pose=_planning_pose(projected_pose),
                                   source=dict(frame['source'], position=destination,
                                               x=destination[0], y=destination[1],
                                               z=destination[2]))
            prediction_key = (shell['index'], target['key'], sample)
            previous = self.predictions.get(prediction_key)
            try:
                predicted = self._prediction(projected_frame, shell, target, sample)
            finally:
                if previous is None:
                    self.predictions.pop(prediction_key, None)
                else:
                    self.predictions[prediction_key] = previous
            if predicted is None:
                return dict(status='unknown', reason='future_geometry_unavailable')
            if predicted.get('unreachable'):
                return dict(status='blocked', reason='future_intercept_unreachable')
            if predicted['reach']['status'] == 'mechanical_limited':
                return dict(status='blocked', reason='future_pitch_unreachable')
            path = predicted['path']
            stamp = (key, destination, frame['identity'], frame['scene'],
                     frame['pose'][1], target['pose'], target.get('velocity'),
                     shell['signature'], tuple(path))
            progress = self._recovery_probe
            if progress is None or progress.get('stamp') != stamp:
                progress = self._recovery_probe = dict(stamp=stamp, cursor=0)
            available = self._budgets.get('recovery', 0)
            while progress['cursor'] < len(path) - 1 and available > 0:
                cursor = progress['cursor']
                first, last = path[cursor], path[cursor + 1]
                hit = self.owner._runtime.bigworld.wg_collideSegment(
                    self.owner._avatar.spaceID, self.owner._vector(first),
                    self.owner._vector(last), 128)
                available -= 1
                progress['cursor'] += 1
                if hit is not None:
                    self._recovery_probe = None
                    self._budgets['recovery'] = available
                    return dict(status='blocked', reason='future_world_blocked')
            self._budgets['recovery'] = available
            if progress['cursor'] < len(path) - 1:
                return pending
            if frame['lane_missing']:
                return dict(status='unknown', reason='future_lane_geometry_unavailable')
            verdict = self.runtime.geometry._bot_friendly_path_verdict(
                projected_frame['source'], path, 0.)
            if not isinstance(verdict, dict):
                return dict(status='unknown', reason='future_lane_unknown')
            if verdict.get('clear') is not True:
                return dict(status='blocked' if verdict.get('blocked') else 'unknown',
                            reason='future_lane_blocked' if verdict.get('blocked') else
                                   'future_lane_unknown')
            if not self.fence(frame):
                return dict(status='pending', reason='recovery_observation_changed')
            return dict(status='clear', reason='same_point_future_line_checked',
                        point=predicted['solution']['point'],
                        mechanical=predicted['reach']['status'])
        except (AttributeError, KeyError, IndexError, TypeError, ValueError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return dict(status='unknown', reason='recovery_native_unavailable')

    def scope_current(self, frame, proof):
        return stationary_scope.current(self.runtime, frame, proof)

    def stationary_plan_current(self, frame, proof):
        planner = getattr(self, 'stationary_planner', None)
        return planner is not None and planner.current(frame, proof)

    def _point_scope(self, frame, shell, target, predicted, result):
        proof = stationary_scope.assess(self.runtime, frame, shell, target, predicted)
        result.update(scope=proof['scope'], scope_reason=proof['reason'], scope_proof=proof)

    def begin_atomic(self, frame, jobs, now):
        self.atomic_receipt = dict(world_chords=0, armour_collision_batches=0,
            friendly_path_calls=0, world_budget=None, priced_candidates=0,
            priced_world_chords=0, world_query_limit=ATOMIC_WORLD_QUERIES,
            armour_batch_limit=ATOMIC_ARMOUR_BATCHES)
        self._atomic_predictions = {}
        self._atomic_prices = {}
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
            self._atomic_prices[key] = chords
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
            if _combat_signature(self.runtime) != frame.get('combat_signature'):
                return False
            if rows is not None:
                for row in rows:
                    plan = row.get('stationary_plan')
                    if plan is not None and not self.stationary_plan_current(frame, plan.get('proof')):
                        return False
                    if (row.get('scope') == 'excluded' and
                            not self.scope_current(frame, row.get('scope_proof'))):
                        return False
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
            observed = dict((_target_key(row), row) for row in _combat_targets(self.runtime)
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
                result = dict(unreachable=True, path=(), reason='no_reachable_intercept',
                              sample_point=sample_point)
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
                yaw=yaw, pitch=pitch, flight_time=flight, fire_range=maximum,
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

    def _armour_geometry(self, frame, shell, target, sample_point, direction, flight,
                         sample=None):
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
        # Direct contact observations without an admitted sample remain
        # uncached; they do not carry the full policy geometry identity.
        key = (shell['index'], target['key'], sample) if sample is not None else None
        stamp = ((frame['identity'], target['pose'], shell['signature'],
                  _point(first), _point(last)) if key is not None else None)
        cached = self.armour_rays.get(key) if key is not None else None
        if cached is not None and cached[0] == stamp:
            # These are the actual native Vector3 endpoints passed to the
            # collider, not rounded planning poses. A settling body can change
            # the mechanical proof while this exact collision stays identical.
            # Re-resolve penetration at the current range below; never carry
            # forward the old armour decision, lane or mechanical permission.
            hits = cached[1]
            self.cache_observations['armour_ray_reuses'] += 1
        else:
            hits = collide_vehicle_at_matrix(entity, target['matrix'], first, last,
                owner._runtime.math, chassis_matrix=target['chassis'])
            self.cache_observations['armour_batches'] += 1
            if hits and key is not None:
                self.armour_rays[key] = (stamp, hits)
            elif key is not None:
                self.armour_rays.pop(key, None)
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
        receipt = {}
        blast = owner._projectile_he_blast_contact(
            dict(shooter_kind='player'), record, entity, shot, impact, rolled,
            state=dict(velocity=direction, gravity=(0., 0., 0.), elapsed=0.),
            seed=geometry['seed'], receipt=receipt)
        if blast is not None:
            result.update(contact=True, expected_damage=float(blast['damage']),
                          he_contact=dict(blast))
        elif receipt.get('complete') is True and receipt.get('status') == 'complete_no_contact':
            result['contact'] = False
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
        reported = result
        try:
            owner, entity, shot = self.owner, target['entity'], shell['shot']
            if channel == 'atomic' and self.atomic_clock() >= self.atomic_deadline:
                self.atomic_receipt['reason'] = 'atomic_frame_budget_exhausted'
                result.update(review_pending=True, reason='atomic_frame_budget_exhausted')
                return result
            key = (shell['index'], target['key'], sample, mode)
            predicted = (self._atomic_predictions.get(key) if channel == 'atomic' else None)
            if predicted is None:
                predicted = self._prediction(frame, shell, target, sample)
            if predicted is None:
                return result
            # A different hull pose supplies a separate planning proof. It
            # cannot replace the observed barrel's mechanical/armour fields.
            # World and armour work below uses the same bounded frontier;
            # the native pivot helper has its own small, resumable budget.
            evaluated_frame = frame
            raw = predicted
            planner = getattr(self, 'stationary_planner', None)
            if (planner is not None and (predicted.get('unreachable') or
                    predicted['reach']['status'] != 'reachable')):
                if not predicted.get('unreachable'):
                    reported.update(mechanical=predicted['reach']['status'],
                        reason=predicted['reach']['reason'],
                        solution=dict(predicted['solution'], source_pose=frame['pose'], mode=mode))
                projection = planner.project(frame, shell, target, predicted, now, channel,
                    deadline=self.atomic_deadline if channel == 'atomic' else None)
                proof = projection.get('proof') if isinstance(projection, dict) else None
                if (isinstance(projection, dict) and projection.get('status') == 'proved' and
                        isinstance(proof, dict) and proof.get('proved') is True and
                        isinstance(projection.get('prediction'), dict) and
                        isinstance(projection.get('projected_frame'), dict)):
                    predicted = projection['prediction']
                    evaluated_frame = projection['projected_frame']
                    if (predicted.get('unreachable') or
                            (predicted.get('reach') or {}).get('status') != 'reachable'):
                        return reported
                    if 'line_region' not in predicted:
                        predicted = dict(predicted, line_region=self._lane_region(predicted['path']))
                    result = dict(status='proved', proof=proof, armor='unknown',
                        line='unknown', mechanical='reachable', contact=None,
                        expected_damage=None, reason='stationary_armour_pending')
                    reported.update(stationary_plan=result, reason='stationary_turn_planned',
                                    line_region=predicted['line_region'])
                elif isinstance(projection, dict):
                    reported['stationary_pending'] = projection.get('reason')
                    reported['stationary_progress'] = projection.get('progressing') is True
                    reported['stationary_progress_token'] = projection.get('progress_token')
            if channel == 'atomic':
                # Keep the actual observation cache separate from the priced
                # future ray. A later evaluation of this same atomic job
                # must never read a projected reachable pose as the actual
                # gun and publish its armour proof into the outer fire row.
                self._atomic_predictions[key] = raw
                chords = max(0, len(predicted['path']) - 1)
                previous_price = self._atomic_prices.get(key)
                if previous_price is None:
                    self.atomic_receipt['priced_candidates'] += 1
                    previous_price = 0
                self._atomic_prices[key] = chords
                self.atomic_receipt['priced_world_chords'] += chords - previous_price
                if len(self._atomic_predictions) == len(self._atomic_domain):
                    self.atomic_receipt['world_budget'] = self.atomic_receipt['priced_world_chords']
            if predicted.get('unreachable'):
                result.update(mechanical='mechanical_limited', reason=predicted['reason'])
                self._point_scope(frame, shell, target, predicted, result)
                return reported
            path, reach = predicted['path'], predicted['reach']
            solution = dict(predicted['solution'], source_pose=frame['pose'], mode=mode,
                            penetration_threshold=(None if mode == 'he_fallback' else
                                                   PENETRATION_FACTOR_65))
            sample_point, direction, flight = predicted['sample_point'], predicted['direction'], predicted['flight']
            result['mechanical'] = reach['status']
            result['solution'] = solution
            result['line_region'] = predicted['line_region']
            geometry = (frame['planning_pose'], target['pose'], shell['signature'],
                        target['velocity'], frame['identity'],
                        (evaluated_frame['position'], evaluated_frame['body'],
                         evaluated_frame['origin']) if predicted is not raw else None)
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
                return reported
            if job['blocked'] is not None:
                result.update(line='world_blocked', reason='world_blocked',
                              blocker=dict(point=job['blocked'], kind='world'))
                return reported
            if frame['lane_missing']:
                result.update(line='unknown', reason='lane_geometry_unavailable')
                return reported
            stamp = self.lane_stamp(frame, predicted['line_region'])
            cached = job['lane']
            if cached is not None and cached[0] == stamp:
                verdict = cached[1]
            else:
                verdict = self.runtime.geometry._bot_friendly_path_verdict(frame['source'], path, 0.)
                if channel == 'atomic':
                    self.atomic_receipt['friendly_path_calls'] += 1
                if isinstance(verdict, dict) and (verdict.get('clear') is True or
                        verdict.get('blocker_team') == frame['source']['team'] or
                        verdict.get('blocked') is True and
                        verdict.get('blocker_kind') in ('wreck', 'debris')):
                    job['lane'] = (stamp, verdict)
            if not isinstance(verdict, dict) or verdict.get('clear') is not True:
                friendly = isinstance(verdict, dict) and verdict.get('blocker_team') == frame['source']['team']
                known_static = (isinstance(verdict, dict) and verdict.get('blocked') is True and
                                verdict.get('blocker_kind') in ('wreck', 'debris'))
                result.update(line=('world_blocked' if known_static else
                                    'friendly_blocked' if friendly else 'unknown'),
                              reason=(verdict['blocker_kind'] + '_blocked' if known_static else
                                      'friendly_blocked' if friendly else 'lane_geometry_unavailable'),
                              blocker=dict(verdict or {}))
                return reported
            result['line'] = 'clear'
            if reach['status'] != 'reachable':
                result['reason'] = reach['reason']
                self._point_scope(frame, shell, target, predicted, result)
                return reported
            if job['armour'] is None:
                if channel == 'atomic':
                    if (self.atomic_clock() >= self.atomic_deadline or
                            self.atomic_receipt['armour_collision_batches'] >= ATOMIC_ARMOUR_BATCHES):
                        self.atomic_receipt['reason'] = 'atomic_armour_budget_exhausted'
                        result.update(review_pending=True, reason='atomic_armour_budget_exhausted')
                        return reported
                previous_batches = self.cache_observations['armour_batches']
                job['armour'] = self._armour_geometry(evaluated_frame, shell, target, sample_point,
                                                      direction, flight, sample=sample)
                if channel == 'atomic':
                    self.atomic_receipt['armour_collision_batches'] += (
                        self.cache_observations['armour_batches'] - previous_batches)
            if job['armour'] is None:
                result['reason'] = 'native_armour_unknown'
                return reported
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
            return reported
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return reported
