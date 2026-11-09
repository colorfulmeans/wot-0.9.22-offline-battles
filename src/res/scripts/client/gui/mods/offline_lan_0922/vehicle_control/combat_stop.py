"""Separate shared attack intent from strategic route/task instructions.

The planner supplies an initial combat hint and retains task/navigation duties.
AttackPolicy owns a current point and its recovery; ordinary macro hints cannot
revoke them. Native geometry and the existing driver still own proof and motion.
"""
from __future__ import division

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
_STOP_MODES = ('engage', 'advance_contact', 'advance')
_ORDINARY_MODES = ('route', 'advance', 'advance_contact', 'engage')
_TRAVEL_MODES = ('base_defense', 'team_back_to_base', 'team_attention_cell',
                 'team_follow', 'team_attack', 'team_return_base',
                 'team_defend_base', 'team_hold_position')


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
        self.task_order = {}
        self.active = self.combat_owned = self.stop_allowed = False
        self.explicit_travel = False
        self.targets = ()
        self.signature = (False, ())
        self.pivot = None
        self.receipt = {}

    def accept(self, order):
        """Accept task authority without giving ordinary hints a second gun."""
        runtime = self.runtime
        self.task_order = dict(order)
        visible = dict((_key(row), row) for row in runtime.visible_targets()
                       if live_contact(row) and row.get('visible', True))
        hint = _key(dict(kind=order.get('target_kind'), id=order.get('target_id')))
        mode = order.get('combat_mode')
        state = runtime.state or {}
        current_target = getattr(runtime.attack_policy, 'current_target_key', None)
        current = current_target() if callable(current_target) else None
        retained = bool(self.combat_owned and mode in _ORDINARY_MODES and current in visible)
        selected = current if retained else (min(visible,
            key=lambda key: ordinary_initial_key(state['position'], visible[key]))
            if hint in visible else hint)
        self.active = bool('fire' in runtime.features and
            (state.get('profile') or {}).get('class_tag') != 'SPG' and
            (mode in _COMBAT_MODES or retained) and selected in visible and
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
        self.active = bool(self.active and mode not in _TRAVEL_MODES and not explicit_travel)
        # A capture/parking hold may legitimately fire without donating its
        # translation to combat. Likewise fire-only control cannot move the
        # vehicle, but may operate the gun/mode after original admission.
        self.combat_owned = bool(self.active)
        self.stop_allowed = bool(self.combat_owned and 'drive' in runtime.features and
            (mode in _STOP_MODES or retained) and not order.get('parking_phase') and
            not order.get('capture_area') and not mission.get('capture_started') and
            not explicit_travel)
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
        self.signature = (self.active, tuple(sorted(admitted)), self.stop_allowed)
        if not self.stop_allowed:
            self.pivot = None
            runtime._native_hull_laying = None
        self.receipt = dict(owner='shared_combat', mode=mode, active=self.active,
            stop_allowed=self.stop_allowed, combat_owned=self.combat_owned,
            selected=selected if self.active else None,
            initial_hint=hint, retained_attack_intent=bool(retained and self.active),
            admitted=tuple(admitted), excluded=(),
            status='admitted' if self.active else 'navigation',
            reason='observed_living_enemies' if self.active else 'navigation_owned')
        if retained and self.stop_allowed:
            # Reconstruct only this existing combat hold. The current point
            # is freshly evaluated below; neither an old aim coordinate nor
            # old launch permission is carried across the boundary. Route
            # metadata and genuine travel/mission commands remain untouched.
            target = visible[selected]
            return dict(order, target_kind=selected[0], target_id=selected[1],
                combat_mode='engage', move_position=tuple(state['position']),
                face_position=target['position'], aim_position=None,
                throttle_override=0., fire_allowed=False)
        return order

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
        for intent in (order or {}, self.task_order):
            identity = _key(dict(kind=intent.get('target_kind'), id=intent.get('target_id')))
            found = next((row for row in self.targets if _key(row) == identity or
                          intent.get('target_kind') is None and
                          intent.get('target_id') in (row.get('id'), row.get('network_id'))), None)
            if found is not None:
                return found
        return None

    def navigation_owns(self, order=None, task_only=False):
        order = order or {}
        if (not self.combat_owned or order.get('combat_mode') in _TRAVEL_MODES or
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
        result = dict(order, move_position=tuple(self.runtime.state['position']),
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
            candidate = decision.get('candidate') or {}
            current = policy.current_row(candidate, require_line=True)
            if not self.contains(candidate.get('target')) or not policy._executable(
                    current, candidate.get('mode', 'penetration')):
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
            self.pivot = runtime._native_hull_laying = None
            return self._stop(order, 'verified_shot', now)
        if policy.stationary_review_wait():
            # Existing local recovery is not reset or restarted by a multi-
            # frame point review. Its unchanged consumer keeps its own lease.
            if (runtime.engine._friendly_repositions.get(runtime.actor_id) or
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
            runtime._last_navigation = dict(status='waiting', action='firing_position',
                reason='friendly_lane', owner='copied_friendly_reposition')
            return order
        identity = runtime.engine._artillery_target_identity(target)
        if mechanical in ('hull_laying', 'mechanical_limited', 'hydraulic_laying'):
            runtime.state['_gun_angle_refusal'] = identity
            if (self.pivot or {}).get('handoff') is not None:
                runtime.state['_gun_angle_pivot_refusal'] = identity
            runtime._last_navigation = dict(status='waiting', action='firing_position',
                reason=decision.get('reason'), owner='copied_gun_angle_recovery')
            return dict(order, fire_allowed=False)
        if runtime.state.get('_gun_angle_adjustment') is not None:
            # A provisional ordinary point does not complete the original
            # mechanical manoeuvre. Changing this combat hold to advance
            # would make its unchanged consumer retire it as a new task.
            # Keep its original lease until that consumer reaches a terminal
            # state; verified aim and genuine task handoffs still exit above.
            runtime._last_navigation = dict(status='waiting', action='firing_position',
                reason=decision.get('reason'), owner='copied_gun_angle_recovery')
            return dict(order, fire_allowed=False)
        runtime._last_navigation = dict(status='waiting', action='firing_position',
            reason=decision.get('reason'), owner='copied_ordinary_navigation')
        # Only release an attack-owned hold; preserve authored advance,
        # route waypoints and every original recovery destination verbatim.
        return runtime._resume_firing_approach(order, target)

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
