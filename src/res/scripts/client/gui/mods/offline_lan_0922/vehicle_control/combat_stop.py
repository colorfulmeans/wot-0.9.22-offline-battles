"""Separate shared attack intent from strategic route/task instructions.

The planner supplies an initial combat hint and retains task/navigation duties.
AttackPolicy owns a current point and its recovery; ordinary macro hints cannot
revoke them. Native geometry and the existing driver still own proof and motion.
"""
from __future__ import division

import copy
import math

from .actor_observation import observation

from .. import siege_mechanics
from .. import capture_orders
from ..ai.driver import WAYPOINT_ARRIVAL_RADIUS
from .native_aim import NATIVE_ANGLE_TOLERANCE
from .target_selection import live_contact, ordinary_initial_key


MECHANICAL_STALL_SECONDS = 6.0
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
        phase = self._physical_recovery
        if (phase is not None and phase.get('kind') == 'friendly' and
                runtime.engine._friendly_repositions.get(runtime.actor_id) is not phase['marker']):
            # The original friendly consumer records its own arrival/timeout.
            # Observe that terminal before considering another candidate; a
            # timeout must not manufacture a fresh escape every callback.
            terminal = runtime.state.get('_friendly_reposition_last_terminal') or {}
            previous = terminal.get('marker') or {}
            if (previous.get('identity') == phase['marker'].get('identity') and
                    previous.get('started_at') == phase['marker'].get('started_at') and
                    terminal.get('outcome') == 'timeout'):
                self.physical_recovery_terminal(order, False)
            else:
                self._physical_recovery = None
                self._motion_order = None
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
        if mode == 'base_capture' and order.get('throttle_override') != 0.:
            self.active = False
        # A capture/parking hold may legitimately fire without donating its
        # translation to combat. Likewise fire-only control cannot move the
        # vehicle, but may operate the gun/mode after original admission.
        self.can_request_movement = bool(self.active and 'drive' in runtime.features and
            mode in _ORDINARY_MODES and not order.get('parking_phase') and
            not order.get('capture_area') and not mission.get('capture_started') and
            not explicit_travel)
        self.combat_owned = bool(self.active and retained)
        self.stop_allowed = bool(self.combat_owned and self.can_request_movement)
        if not self.stop_allowed:
            self._retire_physical_recovery('combat_task_handoff', runtime.now)
        if not self.combat_owned:
            self._intent_target = None
            self._motion_order = None
            self._route_task = dict((name, copy.deepcopy(order.get(name)))
                                    for name in _ROUTE_FIELDS)
            for name in ('move_position', 'route_anchor'):
                point = self._route_task.get(name)
                if point is not None:
                    self._route_task[name] = dict(zip(('x', 'y', 'z'), _point(point)))
            self._physical_recovery = None
        # All observed living enemies belong to the armour-validation domain.
        # Old score/focus/retaliation filters may not hide a penetrable target
        # or manufacture an all-enemy failure. Blocked geometry stays unknown,
        # separate from a proved plate failure inside AttackPolicy.
        # Domain order is initial-distance order. AttackPolicy prioritizes its
        # own current point without rewriting this shared observation domain.
        admitted = (sorted(visible, key=lambda key: ordinary_initial_key(
            state['position'], visible[key])) if self.active else [])
        self.targets = tuple(visible[key] for key in admitted)
        # Priority is not a geometry/admission change. Reordering the same
        # original eligible enemies must not restart the all-enemy eight-
        # second search or discard an otherwise current NEXT proof.
        # Committing movement must not invalidate the very native evidence
        # which authorized it, or reset the same all-enemy search next tick.
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
                     stationary_primary))

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
        if policy._plannable(current, mode):
            return current
        if decision.get('action') == 'firing_position':
            # These are the existing native recovery requests, not a new
            # shootability gate. A proved physical path with a limited gun,
            # or a real friendly blocker, can request laying/repositioning
            # before there is an executable shot or a penetration result.
            if (isinstance(current.get('solution'), dict) and
                    (current.get('armor') == 'passed' and policy._needs_firing_position(current) or
                     current.get('line') == 'friendly_blocked' or
                     current.get('line') == 'clear' and current.get('mechanical') in
                        ('hull_laying', 'mechanical_limited'))):
                return current
        if (decision.get('action') == 'search_penetration' and
                policy.search_authority is not None):
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

    def resolve(self, order, now):
        """Commit one movement owner after the existing native policy runs."""
        if not self.active:
            return order
        runtime, policy = self.runtime, self.runtime.attack_policy
        proposal = self._proposal()
        verified_shot = self._verified_shot()
        mission = getattr(runtime, '_mission', None) or {}
        explicit_attack = bool(not self.explicit_travel and (
            mission.get('explicit') and mission.get('action') == 'attack' and
                mission.get('destination') is None or
            order.get('team_command') in ('ATTACK', 'ATTACKENEMY', 'SUPPORTMEWITHFIRE')))
        target = proposal.get('target') if proposal is not None else None
        requested = order.get('combat_task_target') or {}
        if explicit_attack and requested:
            requested_key = _key(dict(kind=requested.get('target_kind'), id=requested.get('target_id')))
            target = next((row for row in self.targets if _key(row) == requested_key), None)
        elif target is None and explicit_attack:
            target = self.engagement_target(order)
        if (not self.combat_owned and self._failed_recovery is not None and
                verified_shot is None and not (
                    policy.decision.get('action') == 'search_penetration' and
                    policy.search_authority is not None) and
                not self._recovery_context_changed()):
            # An expired physical move cannot reacquire the very same route
            # on every callback, even when an initial/explicit attack hint
            # still names this enemy. A new executable shot remains admissible.
            target = None
        if not self.combat_owned and target is not None:
            if self._failed_recovery is not None:
                # The old target-only mechanical cooldown describes the
                # failed physical context, not a newly proved shot/search or
                # a materially changed source/target pose. Leaving it active
                # would instantly reject the new task and latch its new pose
                # as failed without ever attempting that pose.
                rejected = runtime.state.get('_gun_angle_rejected') or {}
                rejected.pop(self._failed_recovery.get('identity'), None)
            self._failed_recovery = None
            self.combat_owned = True
            self._intent_target = _key(target)
            self._episode += 1
            self.receipt.update(status='admitted', reason='explicit_attack' if explicit_attack else
                'native_attack_proposal', episode=self._episode, admitted_at=now)
        if not self.combat_owned:
            return order
        # A temporary empty candidate is not a terminal task. Preserve the
        # accepted target and last movement phase while its proof refreshes.
        current = (self._physical_recovery.get('target')
                   if self._physical_recovery is not None and
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
            if (self._intent_target == primary and
                    (order.get('throttle_override') == 0. or 'drive' not in runtime.features)):
                # The existing stationary task may lay its own primary gun
                # inside its capture/parking constraints. This is a native
                # policy proposal, not the macro hint taking translation.
                # Another gun target still needs the controls-preserving
                # handoff after the driver; it cannot acquire a hull turn.
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

    def _recovery_context_changed(self):
        failed = self._failed_recovery
        if failed is None:
            return True
        if _distance(self.runtime.state['position'], failed['position']) >= WAYPOINT_ARRIVAL_RADIUS:
            return True
        poses = dict((_key(target), tuple(target['position'])) for target in self.targets)
        if set(poses) != set(failed['targets']):
            return True
        return any(_distance(position, failed['targets'][key]) >= WAYPOINT_ARRIVAL_RADIUS
                   for key, position in poses.items())

    def physical_recovery_active(self):
        """Only this phase may consume the existing bounded mechanical law."""
        return bool(self.stop_allowed and self._physical_recovery is not None and
                    self._physical_recovery.get('kind') != 'friendly')

    def bind_physical_recovery(self, marker):
        """Remember the exact physical lease created by this combat phase."""
        if self.physical_recovery_active():
            self._physical_recovery['marker'] = marker

    def _retire_physical_recovery(self, reason, now):
        phase = getattr(self, '_physical_recovery', None)
        if phase is None:
            return
        state = self.runtime.state
        marker = phase.get('marker')
        if (phase.get('kind') == 'friendly' and marker is not None and
                self.runtime.engine._friendly_repositions.get(self.runtime.actor_id) is marker):
            state['_friendly_reposition_event'] = dict(at=now, outcome=reason,
                marker=dict(marker))
            self.runtime.engine._clear_friendly_reposition(self.runtime.actor_id)
        elif marker is not None and state.get('_gun_angle_adjustment') is marker:
            state['_gun_angle_last_terminal'] = dict(
                state.get('_gun_angle_handoff') or {}, reason=reason,
                sampled_at=now, episode=phase['episode'])
            state.pop('_gun_angle_adjustment', None)
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

    def _physical_lay_at_new_position(self, order, target, now):
        """A current native plan at a reached new pose may finish recovery.

        Candidate churn, a changed yaw at the same ground position, and
        pending line evidence do not finish the checked physical manoeuvre.
        The existing arrival tolerance and native laying proof are reused.
        """
        runtime, policy = self.runtime, self.runtime.attack_policy
        phase = self._physical_recovery
        if (now < runtime.state.get('_native_rotation_refused_until', 0.) or
                _distance(runtime.state['position'], phase['position']) < WAYPOINT_ARRIVAL_RADIUS):
            return None
        candidate = policy.decision.get('candidate')
        if (candidate is None or _key(candidate.get('target') or {}) != phase['target'] or
                candidate.get('shell_index') != runtime.gun.shot_index):
            return None
        current = policy.current_row(candidate, require_line=True)
        if current is None:
            return None
        planned = policy._planned_evidence(current)
        if (planned is not None and (planned.get('solution') or {}).get('needs_hull') and
                policy._plannable(current, candidate.get('mode', 'penetration'))):
            solution = planned['solution']
        elif current.get('mechanical') == 'hull_laying' and current.get('line') == 'clear':
            solution = current.get('solution')
        else:
            return None
        if not isinstance(solution, dict):
            return None
        self._retire_physical_recovery('native_lay_proved_at_new_position', now)
        self.pivot = runtime._native_hull_laying = None
        self._motion_order = None
        return self._lay_order(order, target, solution, now)

    def _physical_order(self, order, target, now, reason):
        """Delegate a proved physical refusal, never a speculative pursuit."""
        runtime = self.runtime
        if self._physical_recovery is None:
            self._physical_recovery = dict(started=now, episode=self._episode,
                position=tuple(runtime.state['position']), reason=reason,
                target=_key(target),
                identity=runtime.engine._artillery_target_identity(target))
        identity = runtime.engine._artillery_target_identity(target)
        runtime.state['_gun_angle_refusal'] = identity
        if (self.pivot or {}).get('handoff') is not None:
            runtime.state['_gun_angle_pivot_refusal'] = identity
        runtime._last_navigation = dict(status='waiting', action='firing_position',
            reason=reason, owner='copied_gun_angle_recovery',
            episode=self._episode, started=self._physical_recovery['started'])
        # This is the admitted stationary anchor entering the existing finite
        # forward/reverse recovery. Its consumer alone chooses a checked goal.
        return self._physical_target_order(order, target)

    def physical_recovery_terminal(self, order, arrived):
        """A bounded recovery ends here; failure never becomes chase-enemy."""
        runtime, now = self.runtime, self.runtime.now
        phase = self._physical_recovery or {}
        self._physical_recovery = None
        self.pivot = runtime._native_hull_laying = None
        if arrived:
            runtime._last_navigation = dict(status='arrived', action='firing_position',
                reason='physical_recovery_arrived', owner='shared_combat',
                at=now, episode=self._episode)
            self._motion_order = None
            return dict(self._stop(order, 'physical_recovery_arrived', now),
                        fire_allowed=False)
        self._failed_recovery = dict(position=tuple(runtime.state['position']),
            targets=dict((_key(target), tuple(target['position'])) for target in self.targets),
            at=now, episode=self._episode, identity=phase.get('identity'))
        runtime._last_navigation = dict(status='failed', action='firing_position',
            reason='physical_recovery_exhausted', owner='shared_combat',
            at=now, episode=self._episode, started=phase.get('started'))
        self.combat_owned = self.stop_allowed = False
        self._intent_target = self._motion_order = None
        self.receipt.update(status='released', reason='physical_recovery_exhausted',
            combat_owned=False, stop_allowed=False, movement_owner='task')
        self._publish_owner()
        return dict(self.task_order, fire_allowed=False)

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
            return dict(self._stop(order, 'engagement_waits_native_siege', now),
                        fire_allowed=False, aim_position=None)
        if action == 'aim':
            candidate = self._verified_shot()
            if candidate is None:
                phase = self._physical_recovery
                target = next((row for row in self.targets
                    if phase is not None and _key(row) == phase['target']), None)
                if target is not None:
                    if phase.get('kind') == 'friendly':
                        return self._physical_target_order(order, target)
                    return self._physical_order(order, target, now, phase['reason'])
                return dict(order, fire_allowed=False)
            # A current verified replacement point completes THIS target's
            # combat lane recovery. Do not cancel unrelated or unproved
            # navigation leases, nor wait for a fictitious timeout to stop.
            target = candidate['target']
            marker = runtime.engine._friendly_repositions.get(runtime.actor_id)
            if marker is not None and marker.get('target_id') == target.get('id'):
                runtime.state['_friendly_reposition_event'] = dict(at=now,
                    outcome='native_lane_reopened', marker=dict(marker))
                runtime.engine._clear_friendly_reposition(runtime.actor_id)
                runtime.engine._decision_cache.pop(runtime.actor_id, None)
            identity = runtime.engine._artillery_target_identity(target)
            for name in ('_gun_angle_refusal', '_gun_angle_pivot_refusal'):
                if runtime.state.get(name) == identity:
                    runtime.state.pop(name, None)
            self._retire_physical_recovery('verified_shot', now)
            self.pivot = runtime._native_hull_laying = None
            self._physical_recovery = self._failed_recovery = None
            return self._stop(order, 'verified_shot', now)
        if self._physical_recovery is not None:
            # The finite physical manoeuvre owns its destination until its
            # own terminal receipt. A newly sampled stationary plan cannot
            # seize it back and alternate native_lay / gun_angle every tick.
            target = next((row for row in self.targets
                if _key(row) == self._physical_recovery['target']), None)
            if target is not None:
                if self._physical_recovery.get('kind') == 'friendly':
                    runtime._last_navigation = dict(status='waiting', action='firing_position',
                        reason='friendly_lane', owner='copied_friendly_reposition',
                        episode=self._episode, started=self._physical_recovery['started'])
                    return self._physical_target_order(order, target)
                laid = self._physical_lay_at_new_position(order, target, now)
                if laid is not None:
                    return laid
                return self._physical_order(order, target, now,
                    self._physical_recovery['reason'])
        if policy.stationary_review_wait():
            # Existing local recovery is not reset or restarted by a multi-
            # frame point review. Its unchanged consumer keeps its own lease.
            if ((self._motion_order is not None and
                    self._motion_order.get('combat_mode') != 'engage') or
                    getattr(runtime, '_move_episode', None) or
                    runtime.engine._friendly_repositions.get(runtime.actor_id) or
                    runtime.state.get('_gun_angle_adjustment') or
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
            result = self._lay_order(order, target, solution, now)
            if result is not None:
                return result
        elif self.pivot is not None:
            self.release_laying('native_pivot_lost_proof', now)
        if candidate.get('line') == 'friendly_blocked':
            # Adapt a current native blocker into the EXISTING friendly law.
            # Its deadline, manoeuvre and failure exit are not duplicated here.
            if runtime.actor_id not in runtime.engine._friendly_repositions:
                runtime.engine._mark_friendly_reposition(runtime.state,
                    dict(order, target_id=target['id']), target,
                    dict(fire_seq=int(runtime.state.get('fire_seq', 0)) + 1,
                         shot_yaw=solution.get('yaw', runtime.state['aim_yaw'])),
                    request.get('blocker') or candidate.get('blocker') or {}, now)
            marker = runtime.engine._friendly_repositions.get(runtime.actor_id)
            if marker is not None:
                self._physical_recovery = dict(kind='friendly', marker=marker,
                    started=marker['started_at'], episode=self._episode,
                    position=tuple(runtime.state['position']), reason='friendly_lane',
                    target=_key(target), identity=runtime.engine._artillery_target_identity(target))
                self.pivot = runtime._native_hull_laying = None
            runtime._last_navigation = dict(status='waiting', action='firing_position',
                reason='friendly_lane', owner='copied_friendly_reposition')
            return order
        if mechanical in ('hull_laying', 'mechanical_limited', 'hydraulic_laying'):
            return self._physical_order(order, target, now, decision.get('reason'))
        if runtime.state.get('_gun_angle_adjustment') is not None:
            # A provisional ordinary point does not complete the original
            # mechanical manoeuvre. Changing this combat hold to advance
            # would make its unchanged consumer retire it as a new task.
            # Keep its original lease until that consumer reaches a terminal
            # state; verified aim and genuine task handoffs still exit above.
            runtime._last_navigation = dict(status='waiting', action='firing_position',
                reason=decision.get('reason'), owner='copied_gun_angle_recovery')
            return dict(order, fire_allowed=False)
        if candidate.get('line') in ('world_blocked', 'enemy_blocked', 'vehicle_blocked'):
            return self._physical_order(order, target, now, decision.get('reason'))
        # Pending queries, absent points and armour failures have no physical
        # recovery authority. Keep the current combat anchor while the one
        # policy reviews them; only its qualified search may request motion.
        return dict(self._stop(order, 'physical_recovery_not_proved', now),
                    fire_allowed=False)

    def release_laying(self, reason, now):
        if self.pivot is not None and 'handoff' not in self.pivot:
            self.pivot['handoff'] = dict(reason=reason, at=float(now),
                position=tuple(self.runtime.state['position']))

    def _lay_order(self, order, target, solution, now):
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
                progress_pitch=hydraulic, best_pitch_error=pitch_error)
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
        return dict(self._stop(order, 'native_lay', now,
                              solution.get('point') or target['position']), fire_allowed=False)
