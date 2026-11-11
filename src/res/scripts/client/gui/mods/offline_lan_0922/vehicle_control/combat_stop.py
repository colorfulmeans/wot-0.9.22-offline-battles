"""Separate shared attack intent from strategic route/task instructions.

The planner supplies an initial combat hint and retains task/navigation duties.
AttackPolicy owns a current point and its recovery; ordinary macro hints cannot
revoke them. Native geometry and the existing driver still own proof and motion.
"""
from __future__ import division

import copy
import math

from .actor_observation import observation
from .native_drive import capture_pivot_allows

from .. import siege_mechanics, shot_geometry, vehicle_physics
from .. import capture_orders
from ..ai.driver import WAYPOINT_ARRIVAL_RADIUS, gun_yaw_limits
from ..native_input_diagnostics import combat_detail, combat_detail_enabled
from .native_aim import NATIVE_ANGLE_TOLERANCE
from .target_selection import live_contact, ordinary_initial_key


MECHANICAL_STALL_SECONDS = 6.0
ROUTE_ATTACK_CONFIRM_SECONDS = 2.0
NO_HE_COOLDOWN_SECONDS = 5.0
ATTACK_OBSERVATION_GAP_SECONDS = .75
ATTACK_LOSS_GRACE_SECONDS = 1.0
RECOVERY_REOPEN_DISTANCE = .25
_COMBAT_MODES = ('engage', 'advance_contact', 'advance',
                 'base_defense', 'team_attack',
                 'team_return_base', 'team_defend_base', 'team_hold_position',
                 'team_back_to_base', 'team_attention_cell',
                 'team_follow')
_ORDINARY_MODES = ('route', 'advance', 'advance_contact', 'engage', 'team_attack')
_TRAVEL_MODES = ('base_defense', 'team_back_to_base', 'team_attention_cell',
                 'team_follow', 'team_attack', 'team_return_base',
                 'team_defend_base', 'team_hold_position')
_ROUTE_FIELDS = ('route_id', 'route_index', 'move_position', 'route_anchor', 'route_join')
_MOTION_FIELDS = ('combat_mode', 'move_position', 'face_position',
                  'throttle_override', 'stable_hull_face')


def _point(value):
    if isinstance(value, dict):
        return tuple(float(value[name]) for name in ('x', 'y', 'z'))
    return tuple(float(value[index]) for index in range(3))


def _distance(first, last):
    return math.hypot(float(first[0]) - float(last[0]),
                      float(first[2]) - float(last[2]))


def _angle(value):
    return (float(value) + math.pi) % (2. * math.pi) - math.pi


def _key(target):
    kind = target.get('kind', target.get('target_kind'))
    return ('human' if kind == 'player' else kind,
            target.get('network_id', target.get('id', target.get('target_id'))))


class CombatStop(object):
    def __init__(self, runtime):
        self.runtime = runtime
        self.reset()

    def reset(self):
        # Retire only our observation. Original route/traffic/recovery state
        # and an already submitted native siege transition are not ours.
        self._retire_physical_recovery('combat_task_reset',
            getattr(self.runtime, 'now', 0.))
        self.task_order = {}
        self.active = self.combat_owned = self.stop_allowed = False
        self.explicit_travel = False
        self.targets = ()
        self.signature = (False, ())
        self.pivot = None
        self.receipt = {}
        self.can_request_movement = False
        self._intent_target = None
        self._motion_order = None
        self._route_task = None
        self._episode = 0
        self._physical_recovery = None
        self._failed_recovery = None
        self._route_confirmation = None
        self.cooldown_until = float('-inf')
        self._route_attack = False
        self._last_attackable_at = None
        self._capture_lay = None
        self._capture_lay_retry = {}
        state = getattr(self.runtime, 'state', None)
        if state is not None:
            state.pop('_combat_movement_owner', None)

    def accept(self, order):
        """Observe candidates and task restrictions, without claiming motion.

        Evaluation admission is not movement admission. In particular a route
        hint must reach the native evaluator without becoming an enemy goal.
        Only resolve() can commit a new ordinary combat movement task.
        """
        runtime = self.runtime
        self.task_order = dict(order)
        visible = dict((_key(row), row) for row in runtime.visible_targets()
                       if live_contact(row) and row.get('visible', True))
        initial = order.get('initial_target_hint') or order
        hint = _key(dict(kind=initial.get('target_kind'), id=initial.get('target_id')))
        mode = order.get('combat_mode')
        state = runtime.state or {}
        retained = bool(self.combat_owned and mode in _ORDINARY_MODES + ('hold', 'base_capture', 'base_screen') and
                        self._intent_target in visible)
        selected = self._intent_target if retained else (min(visible,
            key=lambda key: ordinary_initial_key(state['position'], visible[key]))
            if hint in visible else hint)
        self.active = bool('fire' in runtime.features and
            (state.get('profile') or {}).get('class_tag') != 'SPG' and
            (mode in _COMBAT_MODES + ('route', 'hold', 'base_capture', 'base_screen') or retained) and
            visible and
            not order.get('empty_ammo') and not runtime._mission_brakes())
        mission = getattr(runtime, '_mission', None) or {}
        destination = mission.get('destination')
        explicit_travel = bool(mission.get('explicit') and destination is not None and
            _distance(state['position'], _point(destination)) > float(mission.get('radius', 2.)))
        if mission.get('explicit') and mission.get('action') == 'capture_base' and mission.get('capture_area'):
            # Capture arrives at the existing circle, not a new two-metre
            # point around its centre. Use the original current occupancy
            # rule: capture_started is historical and survives leaving it.
            explicit_travel = not (capture_orders.inside(state, mission['capture_area']) and
                                   not state.get('airborne', False))
        self.explicit_travel = explicit_travel
        self.active = bool(self.active and
            (mode not in _TRAVEL_MODES or mode == 'team_attack') and not explicit_travel)
        capture_travel = mode == 'base_capture' and order.get('throttle_override') != 0.
        automatic_approach = bool(capture_travel and order.get('capture_objective') and
            not order.get('capture_area') and not mission.get('explicit') and
            not order.get('team_command') and 'drive' in runtime.features and
            getattr(runtime, 'actor_kind', None) == 'human' and not runtime.siege_capable())
        if capture_travel:
            self.active = self.active and automatic_approach
        # A capture/parking hold may legitimately fire without donating its
        # translation to combat. Likewise fire-only control cannot move the
        # vehicle, but may operate the gun/mode after original admission.
        self.can_request_movement = bool(self.active and 'drive' in runtime.features and
            (mode in _ORDINARY_MODES or automatic_approach) and not order.get('parking_phase') and
            not order.get('capture_area') and not mission.get('capture_started') and
            not explicit_travel)
        self.combat_owned = bool(self.active and retained)
        self.stop_allowed = bool(self.combat_owned and self.can_request_movement)
        phase = self._physical_recovery
        if (not self.can_request_movement or phase is not None and (
                phase.get('target') not in visible or
                phase.get('shell_index') != runtime.gun.shot_index)):
            self._retire_physical_recovery('combat_task_handoff', runtime.now)
        if not self.can_request_movement:
            self._route_confirmation = None
        if not self.combat_owned:
            self._route_attack = False
            self._last_attackable_at = None
            self._intent_target = None
            self._motion_order = None
            self._route_task = dict((name, copy.deepcopy(order.get(name)))
                                    for name in _ROUTE_FIELDS)
            for name in ('move_position', 'route_anchor'):
                point = self._route_task.get(name)
                if point is not None:
                    self._route_task[name] = dict(zip(('x', 'y', 'z'), _point(point)))
            # An unadmitted inspection has no motion lease. Keep its finite
            # queue while the original route continues; pose changes must not
            # reset its first candidate on every callback.
        # All observed living enemies belong to the armour-validation domain.
        # Old score/focus/retaliation filters may not hide a penetrable target
        # or manufacture an all-enemy failure. Blocked geometry stays unknown,
        # separate from a proved plate failure inside AttackPolicy.
        # Domain order is initial-distance order. AttackPolicy prioritizes its
        # own current point without rewriting this shared observation domain.
        admitted = (sorted(visible, key=lambda key: ordinary_initial_key(
            state['position'], visible[key])) if self.active else [])
        self.targets = tuple(visible[key] for key in admitted)
        if self.capture_hold():
            self._observe_capture_lay(runtime.now)
        else:
            self._capture_lay = None
            self._capture_lay_retry.clear()
        # Priority is not a geometry/admission change. Reordering the same
        # original eligible enemies must not discard an otherwise current NEXT
        # proof. Committing movement must not invalidate its native evidence.
        self.signature = (self.active, tuple(sorted(admitted)))
        if not self.stop_allowed:
            self.pivot = None
            runtime._native_hull_laying = None
        self.receipt = dict(owner='shared_combat', mode=mode, active=self.active,
            stop_allowed=self.stop_allowed, combat_owned=self.combat_owned,
            selected=selected if self.active else None,
            initial_hint=hint, retained_attack_intent=bool(retained and self.active),
            admitted=tuple(admitted), excluded=(),
            status='continuing' if self.combat_owned else 'evaluating' if self.active else 'navigation',
            reason='retained_combat_task' if self.combat_owned else
                'candidate_evaluation_only' if self.active else 'navigation_owned',
            movement_owner='combat' if self.stop_allowed else 'task',
            episode=self._episode)
        self._publish_owner()
        return order

    def candidate_consumable(self, candidate):
        """A current executable point may propose a normal route handoff.

        This is a read-only permission check used by AttackPolicy's existing
        frontier. It neither selects another target nor grants a fire edge.
        """
        hint = self.task_order.get('initial_target_hint') or self.task_order
        primary = _key(dict(kind=hint.get('target_kind'), id=hint.get('target_id')))
        stationary_primary = bool(self.task_order.get('throttle_override') == 0. and
            _key(candidate.get('target') or {}) == primary and not self.explicit_travel)
        return bool(self.active and self.contains(candidate.get('target')) and
                    (self.can_request_movement or 'drive' not in self.runtime.features or
                     stationary_primary or self._capture_owns_aim(candidate)))

    def capture_hold(self):
        order, runtime = self.task_order, self.runtime
        area = order.get('capture_area')
        return bool(self.active and getattr(runtime, 'actor_kind', None) == 'human' and
                    'drive' in runtime.features and not self.explicit_travel and
                    area and order.get('combat_mode') in ('base_capture', 'engage') and
                    order.get('throttle_override') == 0. and not order.get('parking_phase') and
                    not runtime.state.get('airborne') and capture_orders.inside(runtime.state, area))

    def _capture_owns_aim(self, candidate):
        attempt = self._capture_lay
        return bool(attempt is not None and self.capture_hold() and
                    attempt['key'] == (candidate.get('shell_index'), candidate.get('target_key')))

    def capture_lay_target(self):
        attempt = self._capture_lay
        if attempt is not None and self.capture_hold():
            shell, target = attempt['key']
            if (shell == self.runtime.gun.shot_index and
                    any(_key(row) == target for row in self.targets)):
                return target
        return None

    def capture_can_lay(self, row):
        if row is None or row.get('line') != 'clear' or row.get('mechanical') != 'hull_laying':
            return False
        runtime = self.runtime
        key = row['shell_index'], row['target_key']
        refusal = row.get('stationary_pending') or ''
        if ('blocked' in refusal or 'actuator_unavailable' in refusal or
                runtime.now < self._capture_lay_retry.get(key, float('-inf'))):
            return False
        solution = self._lay_solution(row)
        if solution is None:
            return False
        params = observation(runtime).physical_params()
        if not params or not isinstance(params.get('rotationIsAroundCenter'), bool):
            # An original capture contact still has its existing native
            # per-step rotation guard. A new contact needs pivot geometry.
            hint = self.task_order.get('initial_target_hint') or self.task_order
            return row['target_key'] == (hint.get('target_kind'), hint.get('target_id'))
        if params['rotationIsAroundCenter']:
            return True
        if 'trackCenter' not in params or 'direction' not in solution:
            return False
        state = runtime.state
        yaw = state['yaw']
        low, high, limited = gun_yaw_limits(runtime.entity.typeDescriptor)
        if not limited:
            return False
        local_yaw = shot_geometry.world_direction_to_local_gun_angles(
            solution['direction'], yaw, state.get('pitch', 0.), state.get('roll', 0.))[0]
        delta = _angle(local_yaw - (low + high) * .5)
        offset = vehicle_physics.track_pivot_offset(params, 0., delta)
        position = tuple(state['position'])
        end = vehicle_physics.track_pivot_position(position, yaw, yaw + delta, offset)
        area = self.task_order['capture_area']
        centre = area['point']
        allowed = capture_pivot_allows(((centre['x'], centre['z']), area['radius']),
                                       position, end, offset, delta)
        if not allowed and combat_detail_enabled():
            combat_detail(runtime, 'capture_lay', runtime.actor_id, runtime.now,
                'circle_arc_exceeds_radius', lambda: dict(key=row['key'], position=position,
                    end=end, circle=area, delta=delta))
        return allowed

    def _observe_capture_lay(self, now):
        attempt = self._capture_lay
        if attempt is None:
            return
        if self.capture_lay_target() is None:
            self._capture_lay = None
            return
        decision = self.runtime.attack_policy.decision
        if decision['action'] not in ('firing_position', 'preaim', 'wait'):
            return
        state = self.runtime.state
        if abs(_angle(state['yaw'] - attempt['yaw'])) >= NATIVE_ANGLE_TOLERANCE:
            attempt.update(yaw=state['yaw'], progress_at=now)
        if (now < state.get('_native_rotation_refused_until', 0.) or
                now - attempt['progress_at'] >= MECHANICAL_STALL_SECONDS):
            self._capture_lay_retry[attempt['key']] = now + MECHANICAL_STALL_SECONDS
            self._capture_lay = None
            if combat_detail_enabled():
                runtime = self.runtime
                combat_detail(runtime, 'capture_lay', runtime.actor_id, now,
                    'native_rotation_refused' if now < state.get('_native_rotation_refused_until', 0.)
                    else 'no_rotation_progress', lambda: dict(key=attempt['key'], yaw=state['yaw']))

    def _proposal(self):
        policy = self.runtime.attack_policy
        decision = policy.decision
        candidate = decision.get('candidate')
        if candidate is None or not self.contains(candidate.get('target')):
            return None
        current = policy.current_row(candidate, require_line=True)
        if current is None:
            return None
        mode = current.get('mode', 'penetration')
        if policy._executable(current, mode):
            return current
        if decision.get('action') == 'preaim' and (
                current.get('route_he_contact') or mode == 'he_fallback' and current.get('he_route_review')):
            return current if self._route_attackable(current) else None
        if (decision.get('action') != 'firing_position' or
                not policy._needs_firing_position(current)):
            return None
        if self._lay_solution(current) is not None:
            return current
        # An already enabled hydraulic actuator has its own exact native
        # mechanical proof. Resolve that same point before asking it to take
        # the route: ownership must not be a prerequisite for this proof.
        # A blocked/unknown lane still needs a checked translated destination.
        runtime = self.runtime
        hydraulic = getattr(runtime, 'siege_aim', None)
        if (current.get('line') == 'clear' and
                current.get('mechanical') == 'mechanical_limited' and
                current.get('shell_index') == runtime.gun.shot_index and
                hydraulic is not None and runtime.siege_capable() and
                int(getattr(runtime.entity, 'siegeState', 0)) == siege_mechanics.ENABLED and
                not self.mode_pending()):
            motion = hydraulic.candidate(policy.frame, runtime.now, current)
            if (isinstance(motion, dict) and motion.get('key') == current.get('key') and
                    self.contains(motion.get('target')) and
                    motion.get('mechanical') in ('hydraulic_laying', 'hull_laying')):
                runtime._siege_aim_candidate = motion
                return current
        return None

    def _lay_solution(self, candidate):
        policy = self.runtime.attack_policy
        if candidate is None or candidate.get('shell_index') != self.runtime.gun.shot_index:
            return None
        solution = candidate.get('solution')
        if (candidate.get('line') == 'clear' and
                candidate.get('mechanical') == 'hull_laying' and isinstance(solution, dict)):
            return solution
        planned = policy._planned_evidence(candidate)
        if (planned is not None and (planned.get('solution') or {}).get('needs_hull') and
                policy._plannable(candidate, candidate.get('mode', 'penetration'))):
            return planned['solution']
        return None

    def _recovery_candidate(self):
        policy = self.runtime.attack_policy
        decision = policy.decision
        candidate = decision.get('candidate')
        if candidate is None or not self.contains(candidate.get('target')):
            return None
        current = policy.current_row(candidate, require_line=True)
        if current is None:
            return None
        if decision.get('action') == 'firing_position':
            # A real geometric refusal can request same-point recovery
            # without pretending its obstructed plate was penetrable.
            blocked = current.get('line') in ('friendly_blocked', 'world_blocked',
                                               'enemy_blocked', 'vehicle_blocked')
            # A speculative route hint with an unknown plate is not a
            # movement admission. A genuine native blocked row carries the
            # evaluator's current source and lane stamps; a previously
            # proved plate may also retain its current refusal.
            certified_block = bool(blocked and (current.get('armor') == 'passed' or
                current.get('pose_stamp') is not None and
                current.get('line_stamp') is not None))
            if (isinstance(current.get('solution'), dict) and
                    (certified_block or
                     current.get('armor') == 'passed' and policy._needs_firing_position(current) or
                     current.get('line') == 'clear' and current.get('mechanical') in
                        ('hull_laying', 'mechanical_limited'))):
                return current
        return None

    def _verified_shot(self):
        policy = self.runtime.attack_policy
        candidate = policy.decision.get('candidate')
        if (policy.decision.get('action') != 'aim' or candidate is None or
                not self.contains(candidate.get('target'))):
            return None
        current = policy.current_row(candidate, require_line=True)
        return candidate if policy._executable(
            current, candidate.get('mode', 'penetration')) else None

    def _mode_entry_target(self, order):
        """Admit the native mode protocol, not an unchecked recovery move."""
        runtime = self.runtime
        if (not runtime.siege_capable() or
                int(getattr(runtime.entity, 'siegeState', 0)) == siege_mechanics.ENABLED or
                not self.can_request_movement):
            return None
        mission = getattr(runtime, '_mission', None) or {}
        explicit = bool(not self.explicit_travel and (
            mission.get('explicit') and mission.get('action') == 'attack' and
                mission.get('destination') is None or
            order.get('team_command') in ('ATTACK', 'ATTACKENEMY', 'SUPPORTMEWITHFIRE')))
        if explicit:
            requested = order.get('combat_task_target') or {}
            key = _key(dict(kind=requested.get('target_kind'), id=requested.get('target_id')))
            return next((row for row in self.targets if _key(row) == key),
                        self.engagement_target(order))
        policy = runtime.attack_policy
        candidate = policy.decision.get('candidate')
        if candidate is None or not self.contains(candidate.get('target')):
            return None
        current = policy.current_row(candidate, require_line=True)
        if (current is not None and current.get('line') == 'clear' and
                current.get('shell_index') == runtime.gun.shot_index and
                current.get('mechanical') in ('reachable', 'hull_laying', 'mechanical_limited')):
            return current['target']
        return None

    def _reopened_lay(self, proposal):
        """Fence failure to its point; require positive current lay evidence."""
        failed = self._failed_recovery or {}
        previous = failed.get('review_candidate') or {}
        return bool(proposal is not None and proposal.get('line') == 'clear' and
            self._lay_solution(proposal) is not None and (
                proposal.get('key') != failed.get('key') or
                previous.get('line') in ('friendly_blocked', 'world_blocked',
                                         'enemy_blocked', 'vehicle_blocked')))

    def _route_requires_confirmation(self, order):
        mode = order.get('combat_mode')
        # The player's driving intervention is distinct from worker tactics
        # and the native siege mode request/echo protocol.
        return (self.can_request_movement and
                getattr(self.runtime, 'actor_kind', None) == 'human' and
                not self.runtime.siege_capable() and (
            mode in ('route', 'advance', 'advance_contact', 'base_capture') or
            mode == 'engage' and order.get('throttle_override') != 0. and
            order.get('move_position') is not None and
            _distance(self.runtime.state['position'], _point(order['move_position'])) >
                WAYPOINT_ARRIVAL_RADIUS))

    def can_review_route_attack(self):
        return self.can_request_movement and (
            self._route_attack or not self.combat_owned and
            self._route_requires_confirmation(self.task_order))

    def _confirmed_route_attack(self, candidate, now):
        previous = self._route_confirmation
        if candidate is None or candidate.get('key') is None:
            if previous is not None:
                self._record_route_confirmation(now, 'no_attackable_point', previous, None)
            self._route_confirmation = None
            return False
        # The same enemy and ammunition can remain attackable while the
        # selected sample follows a plate or moves to another proved plate.
        key = candidate['key']
        target = candidate['target']
        mode = 'he' if (candidate.get('shell') or {}).get('is_he') else key[-1]
        signature = (_key(target), target.get('engine_id'), self.runtime.gun,
                      key[0], mode)
        if (previous is None or previous[0] != signature or
                not 0. <= now - previous[2] <= ATTACK_OBSERVATION_GAP_SECONDS):
            if previous is not None:
                reason = 'candidate_changed' if previous[0] != signature else 'observation_gap'
                self._record_route_confirmation(now, reason, previous, key)
            previous = (signature, now, now)
        self._route_confirmation = (signature, previous[1], now)
        self.receipt.update(confirmation_since=previous[1],
                            confirmation_seconds=now - previous[1])
        return now - previous[1] >= ROUTE_ATTACK_CONFIRM_SECONDS

    def _record_route_confirmation(self, now, reason, previous, key):
        if combat_detail_enabled():
            runtime = self.runtime
            decision = runtime.attack_policy.decision
            combat_detail(runtime, 'route_attack_confirmation', runtime.actor_id, now, reason,
                lambda: dict(previous_target=previous[0][0], previous_shell=previous[0][3],
                    confirmed=previous[2] - previous[1], next_point=key, mode=self.task_order.get('combat_mode'),
                    action=decision.get('action'), decision=decision.get('reason')))

    def _route_attackable(self, candidate):
        if candidate is None or candidate.get('shell_index') != self.runtime.gun.shot_index:
            return False
        mode = candidate.get('mode', 'penetration')
        policy = self.runtime.attack_policy
        if policy._plannable(candidate, mode):
            return True
        if candidate.get('line') != 'clear':
            return False
        if candidate.get('route_he_contact') and candidate.get('mechanical') == 'reachable':
            return True
        # This proves the plate and the ideal lane even though the present
        # gun cannot lay there. The existing native actuator still has to
        # prove and execute the actual turn after the route hands over.
        refusal = candidate.get('stationary_pending') or ''
        proved = (candidate.get('contact') is True and candidate.get('expected_damage') is not None
                  if mode == 'he_fallback' else candidate.get('armor') == 'passed' or
                  candidate.get('route_he_contact') or candidate.get('route_he_damage', 0.) > 0.)
        return ('blocked' not in refusal and 'actuator_unavailable' not in refusal and
                candidate.get('mechanical') == 'hull_laying' and
                proved and
                self._lay_solution(candidate) is not None)

    def _route_lay_can_retry(self, proposal):
        failed = self._failed_recovery
        if failed is None or proposal.get('key') != failed['key']:
            return True
        if failed['reason'] in ('native_pivot_blocked', 'ordered_no_he'):
            # A real sustained reopening can be useful, after a completely
            # new confirmation interval. A single clear frame cannot reenter.
            return True
        target = proposal.get('target') or {}
        position = failed.get('target_position')
        return (_distance(self.runtime.state['position'], failed['position']) >=
                RECOVERY_REOPEN_DISTANCE or
                position is not None and target.get('position') is not None and
                _distance(target['position'], position) >= RECOVERY_REOPEN_DISTANCE)

    def resolve(self, order, now):
        """Commit one movement owner after the existing native policy runs."""
        if not self.active:
            return order
        runtime, policy = self.runtime, self.runtime.attack_policy
        if self.combat_owned and policy.decision.get('action') == 'navigate':
            # A completed no-shot/no-HE decision is terminal for this
            # engagement, not a parked combat task with a route-like label.
            return self._release_to_route(order, now,
                policy.decision.get('reason', 'combat_no_executable_contact'))
        proposal = self._proposal()
        verified_shot = self._verified_shot()
        target = proposal.get('target') if proposal is not None else None
        confirm_route = not self.combat_owned and self._route_requires_confirmation(order)
        mode_target = self._mode_entry_target(order) if not self.combat_owned else None
        if confirm_route:
            attackable = verified_shot
            if (attackable is None and self._route_attackable(proposal) and
                    self._route_lay_can_retry(proposal)):
                attackable = proposal
            if not self._confirmed_route_attack(attackable, now) or now < self.cooldown_until:
                return order
            target = attackable['target']
            self._retire_physical_recovery('confirmed_route_attack', now)
        elif not self.combat_owned:
            self._route_confirmation = None
            if now < self.cooldown_until:
                return order
            if target is None and mode_target is not None:
                target = mode_target
            if verified_shot is not None:
                self._retire_physical_recovery('verified_shot', now)
            elif target is not None and (self._failed_recovery is None or mode_target is not None or
                                         self._reopened_lay(proposal)):
                self._retire_physical_recovery('current_native_lay', now)
            elif self._failed_recovery is not None:
                # A changed pose only makes a fresh inspection useful. It
                # cannot certify a turn or reacquire the route by itself.
                target = None
            if target is None and self.can_request_movement:
                candidate = self._recovery_candidate()
                failed = self._failed_recovery or {}
                if candidate is None and failed.get('needs_review'):
                    candidate = failed.get('review_candidate')
                phase = self._physical_recovery
                if (phase is None and candidate is not None and
                        self.contains(candidate.get('target')) and
                        (failed.get('needs_review') or self._recovery_context_changed(candidate))):
                    self._physical_order(order, candidate['target'], now,
                        failed.get('reason') if failed.get('needs_review') else
                        policy.decision.get('reason', 'native_obstruction'), candidate)
                elif phase is not None:
                    contact = next((row for row in self.targets
                        if _key(row) == phase['target']), None)
                    if contact is not None:
                        self._physical_order(order, contact, now, phase['reason'])
                phase = self._physical_recovery
                if phase is not None and phase.get('goal') is not None:
                    target = next((row for row in self.targets
                        if _key(row) == phase['target']), None)
        if not self.combat_owned and target is not None:
            self._failed_recovery = None
            self.combat_owned = True
            self._route_attack = confirm_route
            self._last_attackable_at = now
            self._route_confirmation = None
            self._intent_target = _key(target)
            self._episode += 1
            if self._physical_recovery is not None:
                self._physical_recovery.update(admitted=True, episode=self._episode)
            self.receipt.update(status='admitted', reason='native_mode_entry' if mode_target is not None else
                'native_attack_proposal',
                episode=self._episode, admitted_at=now)
        if not self.combat_owned:
            return order
        # A temporary empty candidate is not a terminal task. Preserve the
        # accepted target and last movement phase while its proof refreshes.
        current = (self._physical_recovery.get('target')
                   if self._physical_recovery is not None and
                      verified_shot is None else
                   self.pivot.get('target_key') if self.pivot is not None and
                      verified_shot is None else policy.current_target_key())
        if current is not None and any(_key(row) == current for row in self.targets):
            self._intent_target = current
        target = next((row for row in self.targets if _key(row) == self._intent_target), None)
        if target is None:
            return order
        self.stop_allowed = bool(self.can_request_movement)
        self.receipt.update(combat_owned=True, stop_allowed=self.stop_allowed,
            selected=self._intent_target, movement_owner='combat' if self.stop_allowed else 'task')
        result = dict(order, aim_position=None, fire_allowed=False)
        if self.stop_allowed:
            result.update(target_kind=self._intent_target[0], target_id=self._intent_target[1])
            if self._motion_order is not None:
                result.update(copy.deepcopy(self._motion_order))
            else:
                result.update(combat_mode='engage', move_position=tuple(runtime.state['position']),
                              face_position=target['position'], throttle_override=0.)
        else:
            hint = self.task_order.get('initial_target_hint') or self.task_order
            primary = _key(dict(kind=hint.get('target_kind'), id=hint.get('target_id')))
            if (self.capture_hold() and proposal is not None and
                    proposal['target_key'] == self._intent_target and
                    (self.capture_can_lay(proposal) or
                     verified_shot is not None and self._capture_owns_aim(proposal))):
                key = proposal['shell_index'], proposal['target_key']
                if self._capture_lay is None or self._capture_lay['key'] != key:
                    self._capture_lay = dict(key=key, yaw=runtime.state['yaw'], progress_at=now)
                result.update(target_kind=key[1][0], target_id=key[1][1])
            elif (self._intent_target == primary and order.get('combat_mode') != 'base_capture' and
                    not order.get('capture_area') and
                    not order.get('parking_phase') and
                    (order.get('throttle_override') == 0. or 'drive' not in runtime.features)):
                result.update(target_kind=self._intent_target[0], target_id=self._intent_target[1])
        self._publish_owner()
        return result

    def finish(self, order):
        """Retain the final accepted movement, never its old firing proof."""
        if self.stop_allowed:
            self._motion_order = dict((name, copy.deepcopy(order.get(name)))
                                      for name in _MOTION_FIELDS if name in order)
        self._publish_owner()
        return order

    def _publish_owner(self):
        state = self.runtime.state
        if self.stop_allowed and self._route_task is not None:
            state['_combat_movement_owner'] = dict(owned=True, target=self._intent_target,
                                                  task_order=copy.deepcopy(self._route_task))
            # The shared native lay and its single physical recovery phase
            # replace the older independent rear-gun task. The actual driver
            # still computes hull controls and proves every physical move.
            for name in ('_rear_aim_episode', '_rear_hull_aim', '_rear_motion_lease',
                         '_rear_contact_refusal'):
                state.pop(name, None)
            state['_rear_motion_blocked'] = False
        else:
            state.pop('_combat_movement_owner', None)

    def _recovery_context(self, candidate=None):
        state = self.runtime.state
        candidate = candidate or {}
        key = _key(candidate.get('target') or {})
        target = next((row for row in self.targets if _key(row) == key), None)
        obstacle = candidate.get('blocker') or {}
        # This is a work invalidation token, never a movement/shot proof.
        # Ground-height settling does not restart the horizontal destination
        # list. Real route/target/blocker changes request another bounded pass.
        position = state['position']
        point = target.get('position') if target is not None else None
        return (candidate.get('key'), (position[0], position[2]),
            float(state.get('yaw', 0.)),
            (point[0], point[2], target.get('yaw')) if point is not None else None,
            candidate.get('line'), candidate.get('mechanical'),
            tuple((name, repr(obstacle.get(name))) for name in (
                'actor_key', 'blocker_kind', 'blocker_id', 'blocker_position', 'point')))

    def _recovery_context_changed(self, candidate=None):
        failed = self._failed_recovery
        if failed is None:
            return True
        return self._recovery_context(candidate) != failed.get('context')

    def _release_to_route(self, order, now, reason):
        """Return actual motion ownership and preserve the failed geometry."""
        if reason == 'ordered_no_he':
            self.cooldown_until = now + NO_HE_COOLDOWN_SECONDS
        phase = self._physical_recovery or {}
        failed_target = phase.get('target') or self._intent_target
        target = next((row for row in self.targets if _key(row) == failed_target), None)
        pivot = self.pivot or {}
        candidate = (phase.get('candidate') or pivot.get('candidate') or
                     self.runtime.attack_policy.decision.get('candidate'))
        self._failed_recovery = dict(position=tuple(self.runtime.state['position']),
            yaw=float(self.runtime.state.get('yaw', 0.)),
            target=failed_target, target_position=tuple(target['position']) if target else None,
            key=phase.get('key') or pivot.get('key'), reason=reason, at=now,
            episode=self._episode, context=self._recovery_context(candidate),
            needs_review=bool(not phase and pivot and candidate and candidate.get('key') is not None and
                              reason.startswith('native_pivot')),
            review_candidate=dict(candidate) if candidate else None)
        self._retire_physical_recovery(reason, now)
        self.pivot = self.runtime._native_hull_laying = None
        self.combat_owned = self.stop_allowed = False
        self._route_confirmation = None
        self._route_attack = False
        self._last_attackable_at = None
        self._intent_target = self._motion_order = None
        self.runtime._last_navigation = dict(action='firing_position',
            status='failed', reason=reason, owner='shared_combat',
            at=now, episode=self._episode)
        self.receipt.update(status='released', reason=reason,
            combat_owned=False, stop_allowed=False, movement_owner='task')
        if combat_detail_enabled():
            runtime = self.runtime
            combat_detail(runtime, 'combat_route_release', runtime.actor_id, now, reason,
                lambda: dict(episode=self._episode, point=(candidate or {}).get('key'),
                    pose=tuple(runtime.state['position']), route_index=self.task_order.get('route_index'),
                    reloading=bool((runtime.attack_policy.frame or {}).get('reloading'))))
        self._publish_owner()
        # The route was never replaced. Returning exactly its current task
        # order lets the original driver resume its saved route progress.
        return dict(self.task_order or order, fire_allowed=False)

    def physical_recovery_active(self):
        """Only this phase may consume the existing bounded mechanical law."""
        return bool(self.stop_allowed and self._physical_recovery is not None)

    def physical_recovery_pending(self):
        """Reserve query work for an inspection without donating the route."""
        return self._physical_recovery is not None

    def _retire_physical_recovery(self, reason, now):
        phase = getattr(self, '_physical_recovery', None)
        if phase is None:
            return
        state = self.runtime.state
        cancel = getattr(getattr(getattr(self.runtime, 'attack_policy', None),
                                 'evaluator', None), 'cancel_point_recovery', None)
        if callable(cancel):
            cancel()
        for name in ('_gun_angle_refusal', '_gun_angle_pivot_refusal'):
            if state.get(name) == phase['identity']:
                state.pop(name, None)
        self._physical_recovery = None

    @staticmethod
    def _physical_target_order(order, target):
        if (order.get('target_kind'), order.get('target_id')) != _key(target):
            return dict(order, target_kind=_key(target)[0], target_id=_key(target)[1],
                        face_position=target['position'], aim_position=None,
                        fire_allowed=False)
        return order if not order.get('fire_allowed') else dict(order, fire_allowed=False)

    def _physical_order(self, order, target, now, reason, selected=None):
        """Plan a bounded translation against the exact selected gun sample.

        The original forward/reverse angle owner must not choose a position
        independently. This owner asks the native evaluator whether the SAME
        shell, target and sample can see a candidate destination, then gives
        the ordinary driver only the checked destination. Arrival is not a
        firing proof: current-position evidence must be observed again.
        """
        runtime, policy = self.runtime, self.runtime.attack_policy
        phase = self._physical_recovery
        if phase is None:
            selected = selected or policy.decision.get('candidate')
            # The retained candidate owns its sample. A newer policy request
            # may already describe another point while this one is inspected.
            key = (selected or {}).get('key')
            if selected is None or key is None:
                return dict(self._stop(order, 'physical_point_unavailable', now,
                    tuple(runtime.state['position'])) if self.stop_allowed else order,
                    fire_allowed=False)
            anchor = tuple(runtime.state['position'])
            point = (selected.get('solution') or {}).get('point') or target['position']
            bearing = math.atan2(float(point[0]) - anchor[0],
                                 float(point[2]) - anchor[2])
            destinations = []
            for radius in (4., 8., 12.):
                for offset in (math.pi / 2., -math.pi / 2., .4, -.4, 0., math.pi):
                    yaw = bearing + offset
                    destinations.append((anchor[0] + math.sin(yaw) * radius,
                                         anchor[1], anchor[2] + math.cos(yaw) * radius))
            phase = self._physical_recovery = dict(started=now, episode=self._episode,
                admitted=bool(self.stop_allowed),
                position=anchor, reason=reason, target=_key(target),
                identity=runtime.engine._artillery_target_identity(target),
                key=key, sample=selected.get('sample'),
                shell_index=selected.get('shell_index'), mode=selected.get('mode'),
                candidate=dict(selected), destinations=tuple(destinations),
                cursor=0, goal=None, checking=False, ready=False,
                progress_at=now, best_distance=float('inf'))
            if self._failed_recovery is not None:
                self._failed_recovery['needs_review'] = False
        if phase.get('ready'):
            return dict(self._stop(order, 'same_point_geometry_verified', now),
                        fire_allowed=False)
        goal = phase.get('goal')
        position = tuple(runtime.state['position'])
        if goal is not None:
            distance = _distance(position, goal)
            if distance <= WAYPOINT_ARRIVAL_RADIUS:
                phase.update(goal=None, checking=True, arrived_at=now)
                self._motion_order = None
                return dict(self._stop(order, 'point_recovery_arrived_recheck', now),
                            fire_allowed=False)
            if distance < phase['best_distance'] - .25:
                phase.update(best_distance=distance, progress_at=now)
            if now - phase['progress_at'] >= MECHANICAL_STALL_SECONDS:
                return self._release_to_route(order, now, 'point_recovery_drive_stalled')
            runtime._last_navigation = dict(action='firing_position', status='moving',
                owner='same_point_recovery', key=phase['key'], goal=goal,
                at=now, episode=self._episode)
            return dict(order, combat_mode='gun_angle_adjust', move_position=goal,
                face_position=target['position'], throttle_override=None,
                arrival_radius=1., fire_allowed=False)
        if phase.get('checking'):
            if self.pivot is not None and 'handoff' not in self.pivot:
                # Loading withholds native actuator input; it does not
                # replace this already admitted same-point movement task.
                if policy.decision.get('action') in ('reload_clip', 'switch_shell'):
                    return dict(order, fire_allowed=False)
                return self._continue_laying(order, now)
            current = policy.decision.get('candidate') or {}
            row = policy.current_row(current, require_line=True) if current else None
            if (current.get('key') == phase['key'] and row is not None and
                    row.get('line') == 'clear' and
                    row.get('mechanical') == 'hull_laying'):
                # A real line after travel can still require normal in-place
                # hull laying. That actuator never selects another location.
                solution = row.get('solution')
                if isinstance(solution, dict):
                    laying = self._lay_order(order, target, solution, now, row)
                    if laying is not None:
                        return dict(laying, fire_allowed=False)
            if (policy.decision.get('action') in ('wait', 'preaim') and
                    now - phase['arrived_at'] < MECHANICAL_STALL_SECONDS):
                return dict(self._stop(order, 'point_recovery_native_recheck_pending', now),
                            fire_allowed=False)
            phase['checking'] = False
        if now - phase['started'] >= MECHANICAL_STALL_SECONDS and goal is None:
            return self._release_to_route(order, now, 'point_recovery_exhausted')
        probe = getattr(runtime, 'point_recovery_probe', None)
        ground = getattr(getattr(runtime, 'geometry', None), '_navigation_ground', None)
        grid = getattr(getattr(runtime.engine, 'navigator', None), 'grid', None)
        segment = getattr(grid, 'segment_clear', None)
        # Probe at most one usable candidate per control callback. An
        # unfinished native world path retains this same destination and
        # its cursor, rather than rechecking the first ray every tick.
        checked = 0
        while phase['cursor'] < len(phase['destinations']) and checked < 2:
            candidate_position = phase['destinations'][phase['cursor']]
            if callable(ground):
                height = ground(candidate_position[0], candidate_position[2])
                if height is None:
                    phase['cursor'] += 1
                    checked += 1
                    continue
                candidate_position = (candidate_position[0], float(height),
                                      candidate_position[2])
            if callable(segment) and not segment(position, candidate_position):
                phase['cursor'] += 1
                checked += 1
                continue
            verdict = (probe(phase['candidate'], candidate_position, now)
                       if callable(probe) else {'status': 'unknown'})
            status = (verdict or {}).get('status')
            if status == 'pending':
                break
            phase['cursor'] += 1
            checked += 1
            if status != 'clear':
                continue
            phase.update(goal=candidate_position, progress_at=now,
                         best_distance=_distance(position, candidate_position))
            runtime._last_navigation = dict(action='firing_position', status='checked',
                owner='same_point_recovery', key=phase['key'],
                goal=candidate_position, at=now, episode=self._episode)
            return dict(order, combat_mode='gun_angle_adjust',
                move_position=candidate_position, face_position=target['position'],
                throttle_override=None, arrival_radius=1., fire_allowed=False)
        if phase['cursor'] >= len(phase['destinations']):
            return self._release_to_route(order, now, 'point_recovery_no_checked_position')
        runtime._last_navigation = dict(action='firing_position', status='checking',
            owner='same_point_recovery', key=phase['key'],
            candidates=phase['cursor'], at=now, episode=self._episode)
        if not self.stop_allowed:
            return dict(order, fire_allowed=False)
        return dict(self._stop(order, 'point_recovery_probe_pending', now,
                               tuple(runtime.state['position'])),
                    stable_hull_face=True, fire_allowed=False)

    def physical_recovery_terminal(self, order, arrived):
        """A bounded recovery ends here; failure never becomes chase-enemy."""
        runtime, now = self.runtime, self.runtime.now
        if arrived:
            runtime._last_navigation = dict(status='arrived', action='firing_position',
                reason='physical_recovery_recheck', owner='shared_combat',
                at=now, episode=self._episode)
            self._motion_order = None
            phase = self._physical_recovery
            if phase is not None:
                phase.update(goal=None, arrived_at=now, checking=True)
            return dict(self._stop(order, 'physical_recovery_recheck', now),
                        fire_allowed=False)
        return self._release_to_route(order, now, 'physical_recovery_exhausted')

    def mission_handoff(self, now):
        """A new explicit travel task retires the previous combat-only hold.

        The copied laws understand their original base_defense priority, not
        the player's team_return_base task name. Hand over their temporary
        stopping/laying leases here; do not change routes, physical burst
        groups, ammo/reload transactions or normal in-combat recovery clocks.
        """
        state = self.runtime.state
        hold = state.pop('_magazine_followup', None)
        if hold is not None:
            state['_magazine_followup_terminal'] = dict(at=now,
                reason='priority_handoff', identity=hold['identity'],
                fire_seq=hold['fire_seq'])
        retired = tuple(name for name in ('_rear_aim_episode', '_rear_hull_aim',
            '_rear_motion_lease', '_rear_contact_refusal') if name in state)
        for name in retired:
            state.pop(name, None)
        state['_rear_motion_blocked'] = False
        if retired:
            state['_rear_motion_observation'] = dict(at=now,
                reason='player_mission_priority_handoff', retired=retired)

    def contains(self, target):
        return bool(self.active and isinstance(target, dict) and
                    _key(target) in tuple(_key(row) for row in self.targets))

    def engagement_target(self, order=None, target=None):
        if self.contains(target):
            return next(row for row in self.targets if _key(row) == _key(target))
        for intent in (order or {}, self.task_order,
                       self.task_order.get('initial_target_hint') or {}):
            identity = _key(dict(kind=intent.get('target_kind'), id=intent.get('target_id')))
            found = next((row for row in self.targets if _key(row) == identity or
                          intent.get('target_kind') is None and
                          intent.get('target_id') in (row.get('id'), row.get('network_id'))), None)
            if found is not None:
                return found
        return None

    def navigation_owns(self, order=None, task_only=False):
        order = order or {}
        mode = order.get('combat_mode')
        if (not self.combat_owned or mode in _TRAVEL_MODES and mode != 'team_attack' or
                order.get('empty_ammo') or self.runtime._mission_brakes()):
            return True
        return False

    def mode_pending(self):
        runtime = self.runtime
        states = ((runtime.state or {}).get('siege_state'),
                  getattr(getattr(runtime, 'entity', None), 'siegeState', None))
        return bool(any(state in (siege_mechanics.SWITCHING_ON, siege_mechanics.SWITCHING_OFF)
                        for state in states) or getattr(runtime, '_siege_pending', None) is not None or
                    observation(runtime).mode_pending())

    def waiting_for_siege(self):
        runtime = self.runtime
        return bool(self.combat_owned and runtime.siege_capable() and
                    (self.mode_pending() or
                     int(runtime.state.get('siege_state', 0)) != siege_mechanics.ENABLED or
                     int(getattr(runtime.entity, 'siegeState', 0)) != siege_mechanics.ENABLED))

    def _stop(self, order, reason, now, face=None):
        self.receipt.update(status='stopped', reason=reason, at=now)
        previous = self._motion_order or {}
        anchor = (previous.get('move_position') if previous.get('combat_mode') == 'engage' and
                  previous.get('throttle_override') == 0. else None)
        result = dict(order, move_position=anchor or tuple(self.runtime.state['position']),
                      throttle_override=0., combat_mode='engage')
        if face is not None:
            result['face_position'] = face
        return result

    def apply_order(self, order, now):
        """Supply only combat stop/release intent, before the original driver."""
        if not self.stop_allowed:
            return order
        runtime, policy = self.runtime, self.runtime.attack_policy
        decision = policy.decision
        action = decision.get('action')
        if self.waiting_for_siege():
            # Enter because the original BOT admitted combat, not because a
            # speculative future barrel or penetration plan happened to pass.
            return dict(self._stop(order, 'engagement_waits_native_siege', now,
                                   tuple(runtime.state['position'])),
                        stable_hull_face=True, fire_allowed=False, aim_position=None)
        if action == 'aim':
            candidate = self._verified_shot()
            if candidate is None:
                phase = self._physical_recovery
                target = next((row for row in self.targets
                    if phase is not None and _key(row) == phase['target']), None)
                if target is not None:
                    return self._physical_order(order, target, now, phase['reason'])
                return dict(order, fire_allowed=False)
            # The actual current-position native row, not a destination
            # preview, must establish a usable line before recovery succeeds.
            target = candidate['target']
            self._last_attackable_at = now
            identity = runtime.engine._artillery_target_identity(target)
            for name in ('_gun_angle_refusal', '_gun_angle_pivot_refusal'):
                if runtime.state.get(name) == identity:
                    runtime.state.pop(name, None)
            phase = self._physical_recovery
            if phase is not None and phase.get('key') == candidate.get('key'):
                if phase.get('ready') and now > phase.get('verified_at', now):
                    self._retire_physical_recovery('same_point_geometry_verified', now)
                else:
                    phase.update(ready=True, checking=False, verified_at=now)
                    runtime._last_navigation = dict(action='firing_position',
                        status='geometry_verified', owner='same_point_recovery',
                        key=phase['key'], at=now, episode=self._episode)
            else:
                self._retire_physical_recovery('verified_shot', now)
            self.pivot = runtime._native_hull_laying = None
            self._failed_recovery = None
            policy.navigation_result(None)
            return self._stop(order, 'verified_shot', now)
        if self._physical_recovery is not None:
            # The finite physical manoeuvre owns its destination until its
            # own terminal receipt. A newly sampled stationary plan cannot
            # seize it back and alternate native_lay / gun_angle every tick.
            target = next((row for row in self.targets
                if _key(row) == self._physical_recovery['target']), None)
            if target is not None:
                if self._physical_recovery.get('ready'):
                    phase = self._physical_recovery
                    if (action == 'firing_position' and
                            (decision.get('candidate') or {}).get('key') == phase['key']):
                        phase.update(ready=False, checking=True, arrived_at=now)
                    elif action == 'firing_position':
                        return self._release_to_route(order, now,
                            'same_point_request_changed')
                    elif (action in ('wait', 'preaim') and
                            (policy.frame or {}).get('reloading')):
                        return dict(self._stop(order, 'same_point_reload_wait', now),
                                    fire_allowed=False)
                    elif action in ('wait', 'preaim'):
                        # A prior real shot proof can expire before the next
                        # native trigger. Do not leave its "ready" bit parked
                        # forever if the next frame is no longer executable.
                        phase.update(ready=False, checking=True, arrived_at=now)
                    elif action not in ('firing_position', 'wait', 'preaim'):
                        return self._release_to_route(order, now,
                            'same_point_execution_unavailable')
                # A later sampled opponent may have replaced the policy's
                # gun hint while this exact-point move remains accepted.
                # Keep both the physical target and gun intent bound to its
                # original sample until a real terminal handoff.
                return self._physical_order(self._physical_target_order(order, target), target, now,
                    self._physical_recovery['reason'])
            return self._release_to_route(order, now, 'recovery_target_missing')
        # Load/trigger accounting does not replace an admitted movement
        # task. Its temporarily withheld actuator input is not a geometric
        # failure or a request to leave the native combat mode.
        if (self.pivot is not None and 'handoff' not in self.pivot and
                action in ('wait', 'preaim', 'firing_position')):
            continued = self._continue_laying(order, now)
            if continued is not None:
                return continued
        if self._route_attack:
            proposal = self._proposal()
            if self._route_attackable(proposal):
                self._last_attackable_at = now
            elif (action != 'trigger_active' and
                    not (policy.frame or {}).get('reloading') and
                    now - self._last_attackable_at >= ATTACK_LOSS_GRACE_SECONDS):
                return self._release_to_route(order, now, 'route_attack_opportunity_lost')
            elif action in ('wait', 'preaim'):
                return dict(self._stop(order, 'route_attack_recheck', now,
                    tuple(runtime.state['position'])), stable_hull_face=True,
                    fire_allowed=False, aim_position=None)
        if policy.stationary_review_wait():
            # Existing local recovery is not reset or restarted by a multi-
            # frame point review. Its unchanged consumer keeps its own lease.
            if ((self._motion_order is not None and
                    self._motion_order.get('combat_mode') != 'engage') or
                    runtime.state.get('_rear_aim_episode') or
                    runtime.state.get('_rear_motion_lease')):
                return order
            # A translational stop alone is not a stationary review: the
            # original live-target overlay otherwise replaces the face and
            # its unchanged driver turns the hull every tick. Freeze this
            # admitted combat hold's face *before* the original driver. Do
            # not clamp controls later or affect noncombat/active recovery.
            return dict(self._stop(order, 'stationary_domain_review_pending', now,
                                   tuple(runtime.state['position'])),
                        stable_hull_face=True, fire_allowed=False, aim_position=None)
        contact = self.engagement_target(order)
        motion = runtime.siege_aim_candidate(contact) if contact is not None else None
        motion = motion if (isinstance(motion, dict) and action in
            ('wait', 'preaim', 'firing_position')) else None
        if action != 'firing_position' and motion is None:
            return order
        candidate = motion or decision.get('candidate') or {}
        request = decision.get('move_request') or {}
        target = candidate.get('target') or request.get('target')
        if not self.contains(target):
            # Evidence belongs to its own target. Replacing a rejected
            # identity with the selected enemy must not launder a foreign
            # point, blocker or planned turn into a navigation instruction.
            if target is not None or candidate or request:
                return order
            target = self.engagement_target(order)
        if target is None:
            return order
        solution = candidate.get('solution') or request.get('solution') or {}
        mechanical = candidate.get('mechanical')
        stationary = None
        if (motion is None and mechanical in ('hull_laying', 'mechanical_limited') and
                candidate.get('stationary_plan') is not None and
                candidate.get('shell_index') == runtime.gun.shot_index):
            current = policy.current_row(candidate, require_line=True)
            planned = policy._planned_evidence(current)
            if (planned is not None and (planned.get('solution') or {}).get('needs_hull') and
                    policy._plannable(current, candidate.get('mode', 'penetration'))):
                stationary, solution = planned, planned['solution']
        can_lay = bool(motion is not None or stationary is not None or
            mechanical == 'hull_laying' and candidate.get('line') == 'clear' and
            candidate.get('shell_index') == runtime.gun.shot_index)
        if can_lay:
            result = self._lay_order(order, target, solution, now, candidate)
            if result is not None:
                return result
        elif self.pivot is not None:
            self.release_laying('native_pivot_lost_proof', now)
        if mechanical in ('hull_laying', 'mechanical_limited', 'hydraulic_laying'):
            return self._physical_order(order, target, now, decision.get('reason'))
        if candidate.get('line') in ('friendly_blocked', 'world_blocked',
                                    'enemy_blocked', 'vehicle_blocked'):
            return self._physical_order(order, target, now, decision.get('reason'))
        # Pending queries, absent points and armour failures have no physical
        # recovery authority. Keep the current combat anchor during review.
        return dict(self._stop(order, 'physical_recovery_not_proved', now),
                    fire_allowed=False)

    def release_laying(self, reason, now):
        if self.pivot is not None and 'handoff' not in self.pivot:
            self.pivot['handoff'] = dict(reason=reason, at=float(now),
                position=tuple(self.runtime.state['position']))

    def _continue_laying(self, order, now):
        """Refresh one admitted point, independently of global comparisons."""
        runtime, pivot = self.runtime, self.pivot
        target = next((row for row in self.targets
            if _key(row) == pivot.get('target_key')), None)
        if (target is None or pivot['gun'] is not runtime.gun or
                pivot['shell'] != runtime.gun.shot_index):
            return self._release_to_route(order, now, 'native_pivot_identity_changed')
        # The physical watchdog must run even when no global decision or
        # native query completes. Never refresh it merely for a new receipt.
        if now < runtime.state.get('_native_rotation_refused_until', 0.):
            return self._release_to_route(order, now, 'native_pivot_rotation_refused')
        policy = runtime.attack_policy
        retained = getattr(policy, 'retained_lay_candidate', None)
        motion = runtime.siege_aim_candidate(target)
        if (isinstance(motion, dict) and
                (pivot.get('key') is None or motion.get('key') == pivot.get('key'))):
            receipt = dict(status='clear', candidate=motion,
                solution=motion.get('solution'), mechanical='hydraulic_laying')
        elif callable(retained):
            receipt = retained(pivot.get('key'), now) or {}
        else:
            candidate = policy.decision.get('candidate')
            if (candidate is None or candidate.get('key') != pivot.get('key') or
                    _key(candidate.get('target') or {}) != pivot.get('target_key')):
                candidate = pivot.get('candidate')
            current = policy.current_row(candidate, require_line=True) if candidate else None
            solution = self._lay_solution(current)
            receipt = dict(status='clear' if solution is not None else 'pending',
                candidate=current, solution=solution)
        candidate = receipt.get('candidate') or {}
        solution = receipt.get('solution')
        status = receipt.get('status')
        if status in ('invalid', 'blocked'):
            if status == 'blocked' and candidate.get('key') == pivot.get('key'):
                pivot['candidate'] = dict(candidate)
                if (self._route_attack and candidate.get('line') in
                        ('world_blocked', 'friendly_blocked', 'enemy_blocked', 'vehicle_blocked')):
                    blocked_at = pivot.setdefault('blocked_at', now)
                    if (now - blocked_at < ATTACK_LOSS_GRACE_SECONDS and
                            now - pivot['progress_at'] < MECHANICAL_STALL_SECONDS):
                        return dict(self._stop(order, 'native_pivot_lane_recheck', now,
                            tuple(runtime.state['position'])), stable_hull_face=True,
                            fire_allowed=False, aim_position=None)
            return self._release_to_route(order, now, 'native_pivot_' + status)
        if status == 'clear':
            pivot.pop('blocked_at', None)
        mechanical = receipt.get('mechanical', candidate.get('mechanical'))
        if (isinstance(solution, dict) and mechanical in
                ('reachable', 'hull_laying', 'hydraulic_laying')):
            # A later policy comparison may name another target/sample.
            # Keep both the driver's contact and its face on this admitted
            # point; otherwise the ordinary target overlay restores the new
            # enemy's face after this owner has solved the old pivot.
            order = dict(self._physical_target_order(order, target),
                         aim_position=solution.get('point'), fire_allowed=False)
            if mechanical == 'reachable':
                self.pivot = runtime._native_hull_laying = None
                return dict(self._stop(order, 'native_lay_completed', now,
                    tuple(runtime.state['position'])), stable_hull_face=True,
                    fire_allowed=False)
            result = self._lay_order(order, target, solution, now, candidate)
            if result is not None:
                result.pop('stable_hull_face', None)
                return result
            return self._release_to_route(order, now, 'native_pivot_stalled')
        if now - pivot['progress_at'] >= MECHANICAL_STALL_SECONDS:
            return self._release_to_route(order, now, 'native_pivot_geometry_stalled')
        return dict(self._stop(order, 'native_pivot_geometry_pending', now,
            tuple(runtime.state['position'])), stable_hull_face=True,
            fire_allowed=False, aim_position=None)

    def _lay_order(self, order, target, solution, now, candidate=None):
        runtime, state = self.runtime, self.runtime.state
        handoff = (self.pivot or {}).get('handoff')
        if handoff is not None:
            if _distance(state['position'], handoff['position']) < WAYPOINT_ARRIVAL_RADIUS:
                return None
            self.pivot = runtime._native_hull_laying = None
        yaw = float(state['yaw'])
        desired_yaw = float(solution.get('hull_yaw', solution.get('yaw', yaw)))
        error = abs(_angle(desired_yaw - yaw))
        hydraulic = float(observation(runtime).hydraulic_state().get('pitch',
                                  state.get('suspension_pitch', 0.)))
        needs_hydraulic = bool(solution.get('needs_hydraulic'))
        desired_pitch = float(solution.get('hydraulic_pitch',
                                           solution.get('siege_correction', hydraulic)))
        pitch_error = abs(desired_pitch - hydraulic)
        identity = runtime.engine._artillery_target_identity(target)
        if self.pivot is None:
            self.pivot = dict(target=identity, gun=runtime.gun, shell=runtime.gun.shot_index,
                progress_at=float(now), progress_yaw=yaw, best_error=error,
                progress_pitch=hydraulic, best_pitch_error=pitch_error,
                target_key=_key(target), key=(candidate or {}).get('key'),
                candidate=dict(candidate or {}))
            runtime._native_hull_laying = self.pivot
        pivot = self.pivot
        if identity != pivot['target']:
            pivot.update(target=identity, best_error=error, best_pitch_error=pitch_error,
                         progress_yaw=yaw, progress_pitch=hydraulic)
        progressed = (abs(_angle(yaw - pivot['progress_yaw'])) >= NATIVE_ANGLE_TOLERANCE and
                      error < pivot['best_error'] - NATIVE_ANGLE_TOLERANCE or
                      needs_hydraulic and abs(hydraulic - pivot['progress_pitch']) >= NATIVE_ANGLE_TOLERANCE and
                      pitch_error < pivot['best_pitch_error'] - NATIVE_ANGLE_TOLERANCE)
        if progressed:
            pivot.update(best_error=min(error, pivot['best_error']),
                         best_pitch_error=min(pitch_error, pivot['best_pitch_error']),
                         progress_at=float(now), progress_yaw=yaw, progress_pitch=hydraulic)
        if (now < state.get('_native_rotation_refused_until', 0.) or
                now - pivot['progress_at'] >= MECHANICAL_STALL_SECONDS):
            self.release_laying('native_pivot_stalled', now)
            return None
        runtime._last_navigation = dict(status='aligning', action='firing_position',
            reason=solution.get('mechanical_reason'), owner='copied_combat_hull_aim')
        result = dict(self._stop(order, 'native_lay', now,
                              solution.get('point') or target['position']), fire_allowed=False)
        result.pop('stable_hull_face', None)
        return result
