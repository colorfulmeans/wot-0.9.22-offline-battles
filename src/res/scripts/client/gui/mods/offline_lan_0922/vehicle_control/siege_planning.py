"""One selected point's native hydraulic input in the ENABLED mode only.

Mode entry has no geometry gate. The ordinary finite-traverse attack owner
chooses/evaluates points and owns its bounded stationary plans. This adapter
only makes the flat-body hydraulic actuator pursue the same world launch ray
as the tilted-body gun source. It never traces a line, queries armour, scans
alternate targets, reads a future descriptor or grants trigger permission.
"""
from __future__ import division

import math

from .actor_observation import observation

from .. import shot_geometry
from ..gun_mechanics import _field
from .. import hull_aiming
from ..native_input_diagnostics import combat_detail, combat_detail_enabled
from .native_aim import (active_hydraulic_pose, hydraulic_reach,
                         NATIVE_ANGLE_TOLERANCE)


NATIVE_SOURCE_CALLS = 6
NATIVE_SOURCE_YAW_TOLERANCE = 1.e-6
NATIVE_SOURCE_PITCH_FALLBACK_TOLERANCE = 1.e-6


def _point(value):
    result = tuple(float(value[index]) for index in range(3))
    if any(math.isnan(v) or math.isinf(v) for v in result):
        raise ValueError('non-finite actual hydraulic input')
    return result


def _angle(value):
    return (float(value) + math.pi) % (2. * math.pi) - math.pi


def _direction(yaw, pitch):
    return (math.sin(yaw) * math.cos(pitch), -math.sin(pitch),
            math.cos(yaw) * math.cos(pitch))


class ActualSiegeAim(object):
    def __init__(self, runtime):
        self.runtime = runtime
        self.reset()

    def reset(self):
        self._lease = None
        self.receipt = dict(status='idle', reason='no_actual_hydraulic_point',
                            candidates=0, native_calls=0)

    def status(self):
        return dict(self.receipt)

    @staticmethod
    def _has_laying_lane(policy, row):
        if row.get('scope') == 'excluded':
            return False
        # A completed stationary plan can supply a clear lane for laying.
        # While classifying the stationary domain, keep unlaid points still.
        return row.get('line') == 'clear' or (
            row.get('line') == 'unknown' and
            not policy.stationary_review_wait() and
            policy._plannable(row, row.get('mode', 'penetration')))

    def _selected(self, frame, preferred):
        policy = self.runtime.attack_policy
        held = self.runtime.combat_stop.receipt.get('selected')
        preferred_key = (preferred or {}).get('key')
        if preferred_key is not None:
            current = policy.current_row(preferred, require_line=True)
            if (current is not None and current.get('pose_stamp') == preferred.get('pose_stamp') and
                    current.get('shell_index') == frame['loaded'] and
                    (held is None or current.get('target_key') == held) and
                    self._has_laying_lane(policy, current)):
                return current
        if held is None:
            return None
        # Continue with another point of the owned contact. Firing still
        # requires independent checks against the physical barrel.
        rows = policy._rows_for('penetration', frame['loaded'], fresh_line=True)
        rows = [row for row in rows if row.get('key') != preferred_key and
                row.get('target_key') == held and row.get('armor') != 'failed' and
                isinstance(row.get('solution'), dict) and policy._needs_firing_position(row) and
                self._has_laying_lane(policy, row)]
        return min(rows, key=policy._penetration_order) if rows else None

    def _motion_source(self, frame, hydraulic, solution, shell, trace=None):
        """At most six calls to the installed flat-body inverse contract."""
        owner, descriptor = self.runtime.owner, frame['descriptor']
        minimum, maximum = hull_aiming.absolute_pitch_limits(descriptor)
        correction = float(solution['hydraulic_pitch'])
        getter = getattr(owner._runtime, 'get_shot_angles', None)
        if not callable(getter):
            if trace is not None:
                trace['failure'] = 'native_getter_unavailable'
            return None
        body, position = hydraulic['body'], hydraulic['position']
        matrix = owner._runtime.math.Matrix()
        matrix.setRotateYPR(body)
        matrix.translation = owner._vector(position)
        current = observation(self.runtime).gun_angles()
        yaw, pitch = shot_geometry.world_direction_to_local_gun_angles(
            solution['direction'], *body)
        desired = (yaw, minimum + correction if correction < -1.e-9 else
                       maximum + correction if correction > 1.e-9 else
                       max(minimum, min(maximum, pitch)))
        local = [desired[0], desired[1]]
        origin = shot_geometry.shot_origin_and_direction(descriptor, position,
            body[0], body[1], body[2], current[0], current[1])[0]
        distance = min(100., max(5., float(_field(shell['shot'], 'speed')) * .12))
        source = _point(solution['point'])
        tolerance = 1.e-7
        best = None
        if trace is not None:
            trace.update(desired_angles=desired, current_angles=current, origin=origin,
                gun_pitch_limits=(minimum, maximum), desired_correction=correction,
                tolerance=tolerance, yaw_tolerance=NATIVE_SOURCE_YAW_TOLERANCE,
                pitch_fallback_tolerance=NATIVE_SOURCE_PITCH_FALLBACK_TOLERANCE, attempts=[])
        for attempt in range(NATIVE_SOURCE_CALLS):
            self.receipt['native_calls'] += 1
            actual = getter(descriptor, matrix, current, owner._vector(source))
            actual = float(actual[0]), float(actual[1])
            errors = _angle(desired[0] - actual[0]), desired[1] - actual[1]
            if any(math.isnan(v) or math.isinf(v) for v in errors):
                if trace is not None:
                    trace['attempts'].append(dict(point=source, nonfinite_angles=True))
                    trace['failure'] = 'nonfinite_angles'
                return None
            produced, reachable = hull_aiming.minimal_correction(
                actual[1], minimum, maximum, hydraulic['minimum'], hydraulic['maximum'])
            if trace is not None:
                trace['attempts'].append(dict(point=source, angles=actual,
                    angle_error=errors, correction=produced, within_limits=reachable,
                    correction_error=produced - correction))
            if reachable and abs(errors[0]) <= NATIVE_SOURCE_YAW_TOLERANCE:
                pitch_error = max(abs(errors[1]), abs(produced - correction))
                if pitch_error <= tolerance:
                    if trace is not None:
                        trace['accepted_with_yaw_tolerance'] = abs(errors[0]) > tolerance
                    return source
                if pitch_error <= NATIVE_SOURCE_PITCH_FALLBACK_TOLERANCE:
                    quality = pitch_error, abs(errors[0])
                    if best is None or quality < best[0]:
                        best = (quality, source, attempt)
            if attempt:
                local[0] = _angle(local[0] + errors[0])
                local[1] += errors[1]
            direction = shot_geometry.transform_vehicle_vector(_direction(*local), *body)
            source = tuple(origin[axis] + direction[axis] * distance for axis in range(3))
        # A rounded map-coordinate input may still lay the hydraulics.
        # Physical barrel and launch proofs use their own tolerances.
        if best is not None:
            if trace is not None:
                trace.update(accepted_with_pitch_tolerance=True, selected_attempt=best[2],
                             accepted_with_yaw_tolerance=best[0][1] > tolerance)
            return best[1]
        if trace is not None:
            trace['failure'] = 'attempts_exhausted'
        return None

    def _report_aim(self, stage, now, row, solution, hydraulic, reach, inverse=None):
        runtime = self.runtime
        plan = row.get('stationary_plan') or {}
        combat_detail(runtime, stage, runtime.actor_id, now, self.receipt['reason'],
            lambda: dict(point_key=row.get('key'), line=row.get('line'),
                mechanical=row.get('mechanical'), point=solution.get('point'),
                solution_needs_hull=solution.get('needs_hull'),
                hull_yaw=solution.get('hull_yaw'), reach=reach,
                flat_position=hydraulic['position'], flat_body=hydraulic['body'],
                hydraulic_correction=hydraulic['correction'],
                hydraulic_limits=(hydraulic['minimum'], hydraulic['maximum']),
                stationary_status=plan.get('status'), stationary_line=plan.get('line'),
                stationary_pending=row.get('stationary_pending'),
                stationary_progress=row.get('stationary_progress_token'),
                policy_reason=runtime.attack_policy.decision.get('reason'),
                episode=runtime.combat_stop.receipt.get('episode'),
                inverse=inverse))

    def candidate(self, frame, now, preferred=None):
        self._lease = None
        self.receipt = dict(status='pending', reason='actual_hydraulic_point_pending',
                            candidates=0, native_calls=0)
        try:
            if frame is None or frame.get('artillery') or frame.get('trigger_active'):
                self.receipt.update(status='held', reason='actual_hydraulic_owner_unavailable')
                return None
            hydraulic = active_hydraulic_pose(self.runtime, frame)
            if hydraulic is None:
                self.receipt.update(status='inactive', reason='hydraulics_not_currently_enabled')
                return None
            row = self._selected(frame, preferred)
            if not isinstance(row, dict) or row.get('shell_index') != frame['loaded']:
                return None
            target = next((value for value in frame['targets']
                           if value['key'] == row.get('target_key')), None)
            shell = next((value for value in frame['shells']
                          if value['index'] == frame['loaded']), None)
            if target is None or shell is None or shell.get('unavailable'):
                return None
            solution = dict(row.get('solution') or {})
            if (row.get('pose_stamp') != self.runtime.attack_policy._stamp(frame, shell, target) or
                    solution.get('target_pose') != target['pose']):
                return None
            planned = row.get('stationary_plan') or {}
            if (planned.get('status') == 'proved' and planned.get('line') == 'clear' and
                    planned.get('armor') in ('passed', 'failed') and
                    isinstance(planned.get('solution'), dict)):
                solution = dict(planned['solution'])
            direction = _point(solution['direction'])
            reach = hydraulic_reach(frame['descriptor'], direction, hydraulic['body'], hydraulic)
            if not reach.get('reachable') and not reach.get('needs_hull'):
                self.receipt.update(reason=reach['reason'])
                return None
            correction = (float(solution['hydraulic_pitch']) if solution.get('stationary_plan')
                          and 'hydraulic_pitch' in solution else reach['hydraulic_pitch'])
            needs_hull = bool(solution.get('needs_hull') or reach.get('needs_hull'))
            if (needs_hull and self.runtime.attack_policy.decision.get('reason') ==
                    'stationary_domain_review_pending'):
                self.receipt.update(reason='stationary_hull_review_pending')
                if combat_detail_enabled():
                    self._report_aim('siege_hull_review', now, row, solution, hydraulic, reach)
                return None
            limits = _field(_field(frame['descriptor'], 'gun'), 'turretYawLimits')
            turret = reach['local_yaw'] if limits is None else max(float(limits[0]),
                min(float(limits[1]), reach['local_yaw']))
            hull_yaw = solution.get('hull_yaw',
                _angle(hydraulic['body'][0] + _angle(reach['local_yaw'] - turret)))
            solution.update(siege_aim=True, needs_hull=needs_hull, hull_yaw=hull_yaw,
                needs_hydraulic=abs(correction - hydraulic['correction']) > NATIVE_ANGLE_TOLERANCE,
                hydraulic_pitch=correction, siege_correction=correction,
                reachable=False, source_verified=False)
            inverse = {} if combat_detail_enabled() else None
            source = self._motion_source(frame, hydraulic, solution, shell, inverse)
            if source is None:
                self.receipt.update(reason='actual_hydraulic_native_source_pending')
                if inverse is not None:
                    self._report_aim('siege_hydraulic_inverse', now, row, solution,
                                     hydraulic, reach, inverse)
                return None
            result = dict(row, solution=solution,
                mechanical='hull_laying' if needs_hull else 'hydraulic_laying')
            self._lease = dict(key=(shell['index'], target['key'], row['sample']),
                identity=frame['identity'], descriptor=frame['descriptor'],
                shell_signature=shell['signature'], flat_pose=(hydraulic['position'], hydraulic['body']),
                target=target['entity'], target_pose=target['pose'], velocity=target['velocity'],
                sample_value=solution['sample_value'], source=source)
            if self.hydraulic_point(result, solution['point']) is None:
                self._lease = None
                self.receipt.update(reason='actual_hydraulic_observation_changed')
                return None
            self.receipt.update(status='ready', reason='actual_enabled_hydraulic_input', candidates=1,
                target=target['key'], sample=row['sample'], shell=shell['index'],
                needs_hull=needs_hull, needs_hydraulic=solution['needs_hydraulic'])
            if inverse is not None:
                if inverse.get('accepted_with_pitch_tolerance'):
                    self._report_aim('siege_hydraulic_pitch_tolerance', now, row, solution,
                                     hydraulic, reach, inverse)
                elif inverse.get('accepted_with_yaw_tolerance'):
                    self._report_aim('siege_hydraulic_yaw_tolerance', now, row, solution,
                                     hydraulic, reach, inverse)
            return result
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            self.receipt.update(reason='actual_hydraulic_data_unavailable')
            return None

    def hydraulic_point(self, candidate, weapon_point):
        """Keep the flat input matched while the real hydraulic pose moves."""
        lease = self._lease
        if lease is None or not isinstance(candidate, dict) or weapon_point is None:
            return None
        try:
            from .attack_policy import native_target_pose, _shell_signature
            runtime, owner = self.runtime, self.runtime.owner
            key = candidate.get('shell_index'), candidate.get('target_key'), candidate.get('sample')
            solution = candidate.get('solution') or {}
            if (key != lease['key'] or solution.get('sample_value') != lease['sample_value'] or
                    solution.get('target_pose') != lease['target_pose']):
                return None
            if not any(value is not None and _point(weapon_point) == _point(value)
                       for value in (solution.get('point'), solution.get('source_point'))):
                return None
            entity = observation(runtime).source_entity()
            if (entity.typeDescriptor is not lease['descriptor'] or
                    getattr(entity, 'siegeState', hull_aiming.DISABLED) != hull_aiming.ENABLED or
                    lease['identity'] != tuple(observation(runtime).weapon_identity()) +
                                          (id(_field(entity.typeDescriptor, 'gun')),) or
                    int(runtime.gun.shot_index) != key[0] or runtime.gun.ammo[key[0]] <= 0 or
                    _shell_signature(key[0], runtime.gun.shots[key[0]]) != lease['shell_signature']):
                return None
            matrix = owner._runtime.math.Matrix(observation(runtime).hydraulic_state()['flat_matrix'])
            flat = (_point(matrix.translation), _point((matrix.yaw, matrix.pitch, matrix.roll)))
            if flat != lease['flat_pose']:
                return None
            current = next((target for target in runtime.visible_targets() if
                target.get('key', (target.get('kind'), target.get('network_id', target.get('id')))) == key[1]
                and target.get('alive', True)), None)
            if current is None or runtime.target_entity(current) is not lease['target']:
                return None
            if native_target_pose(owner, lease['target'])[0] != lease['target_pose']:
                return None
            velocity = tuple(current.get('velocity') or ())
            if len(velocity) == 3 and _point(velocity) != lease['velocity']:
                return None
            return tuple(lease['source'])
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return None
