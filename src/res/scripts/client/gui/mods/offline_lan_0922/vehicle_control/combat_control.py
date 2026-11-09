# -*- coding: utf-8 -*-
"""One automatic combat decision owner shared by every controlled actor.

Bindings supply observed physical state and native inputs. This module never
advances a gun, moves an entity or delegates to a retired player/BOT policy.
"""
from __future__ import print_function

import math

from .actor_observation import observation

from .. import bot_runtime as shared_runtime
from .. import capture_orders, siege_mechanics
from ..ai import driver as shared_driver
from .combat_stop import MECHANICAL_STALL_SECONDS
from .native_aim import NATIVE_ANGLE_TOLERANCE

def _point(value):
    if isinstance(value, dict):
        return tuple(float(value[name]) for name in ('x', 'y', 'z'))
    try:
        return tuple(float(value[index]) for index in range(3))
    except (TypeError, IndexError):
        return float(value.x), float(value.y), float(value.z)

def _angle(value):
    return (float(value) + math.pi) % (2. * math.pi) - math.pi

def _distance(first, second):
    return math.hypot(first[0] - second[0], first[2] - second[2])

def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)

class CombatControl(object):
    """Per-actor state lives on the binding, never in module globals."""

    def prepare_trigger_context(self, state, target, solution, launch_receipt=None):
        """Select one first-edge intention; physical bindings prove/commit it."""
        if (not self._live() or self._mission_brakes() or
                'fire' not in self.features or not state.get('gun_aligned') or
                not self._siege_fire_ready()):
            return None
        candidate = self.attack_policy.decision.get('candidate')
        artillery = (state.get('profile') or {}).get('class_tag') == 'SPG'
        load_plan = None
        if not artillery:
            policy = self.attack_policy
            if (not self.combat_stop.active or policy.decision['action'] != 'aim' or
                    candidate is None or not self.combat_stop.contains(candidate.get('target'))):
                return None
            token = self.generation
            load_plan = self._apply_next_shell(at_trigger=True)
            if not self._live(token):
                return None
            # Motion integration and native gun laying happen after the
            # policy selected this intention. Refresh that same sample at
            # the final physical pose; the old row is not a launch proof.
            solution = policy.evaluator.refresh_trigger_solution(candidate, self.now)
            if (solution is None or not self._live(token) or
                    policy.decision.get('candidate') is not candidate or
                    policy.decision.get('action') != 'aim' or
                    not self.combat_stop.contains(candidate.get('target'))):
                return None
        elif launch_receipt is not None:
            intent = self.engine._artillery_intents.get(state['id']) or {}
            planned = intent.get('solution')
            if isinstance(planned, dict):
                observed = target or {}
                speed, yaw = float(observed.get('speed', 0.)), float(observed.get('yaw', 0.))
                solution = dict(planned, point=tuple(planned['aim_position']),
                    velocity=observed.get('velocity') or
                        (math.sin(yaw) * speed, 0., math.cos(yaw) * speed))
        return dict(target=target, candidate=candidate, solution=solution,
            source_pose=self.pose_stamp(), artillery=artillery,
            load_plan=load_plan, load_epoch=self._manual_shell_epoch,
            artillery_receipt=launch_receipt)

    @property
    def confirmed_facing(self):
        return (self._last_order.get('confirmed_facing') or
                (self.state or {}).get('_confirmed_facing'))

    @property
    def capture_pivot_circle(self):
        return (self._last_order.get('capture_pivot_circle') or
                (self.state or {}).get('_capture_pivot_circle'))

    def current_source(self):
        return self.state

    def visible_targets(self):
        return self._targets

    def combat_targets(self):
        """The shared controller's live combat domain in stable review order."""
        visible = dict(((row.get('kind'), row.get('network_id')), row)
                       for row in self.visible_targets() if row.get('alive', True))
        return tuple(visible[key] for key in
            ((row.get('kind'), row.get('network_id')) for row in self.combat_stop.targets)
            if self.combat_stop.active and key in visible)

    def _stationary_review_wait(self):
        decision = self.attack_policy.decision
        return (decision.get('action') == 'wait' and
                decision.get('reason') == 'stationary_domain_review_pending')

    def siege_aim_candidate(self, target=None):
        """Current enabled-mode actuator input, never a mode-entry gate."""
        candidate = self._siege_aim_candidate
        if (candidate is None or not self._live() or self._mission_brakes() or
                self._stationary_review_wait() or
                self.attack_policy.decision.get('action') not in
                    ('aim', 'preaim', 'wait', 'firing_position') or
                int(getattr(self.entity, 'siegeState', 0)) != siege_mechanics.ENABLED or
                self._siege_pending is not None or
                not self.combat_stop.combat_owned or not self.combat_stop.contains(candidate.get('target'))):
            return None
        if target is not None and (target.get('kind'), target.get('network_id')) != (
                candidate['target'].get('kind'), candidate['target'].get('network_id')):
            return None
        return candidate

    def hydraulic_aim_point(self, entity):
        """A matched flat-body actuator input, separate from the shot inverse.

        The native gun source is resolved against the actual tilted body.
        Feeding that inverse back through the uncorrected hydraulic body
        creates a second pitch goal. Keep both native consumers on the same
        proved target without granting a projected point fire authority.
        """
        if (entity is not self.entity or not self._live() or
                'fire' not in self.features or self._mission_brakes() or
                self._stationary_review_wait() or
                not self.weapon.owned() or self.state is None or
                self._siege_pending is not None or
                int(getattr(entity, 'siegeState', 0)) != siege_mechanics.ENABLED or
                not self.combat_stop.combat_owned):
            return None
        candidate = self.current_attack_candidate(self.state, self.weapon.target, for_aim=True)
        if candidate is None:
            candidate = self.siege_aim_candidate(self.weapon.target)
        return self.siege_aim.hydraulic_point(candidate, self.weapon.point)

    def siege_capable(self):
        # The active native siege child need not repeat the outer composite's
        # hasSiegeMode flag. Retain the installed physical capability across
        # descriptor swaps instead of mistaking that child for an ordinary TD.
        pairs = getattr(self.engine, '_descriptor_pairs', None) or {}
        pair = pairs.get(self.actor_id)
        if pair is not None and len(pair) == 2 and pair[1] is not None:
            return True
        for descriptor in (getattr(self.entity, 'typeDescriptor', None),
                           observation(self).installed_descriptor()):
            if _field(descriptor, 'hasSiegeMode', False):
                return True
            try:
                if siege_mechanics.descriptor_pair(descriptor)[1] is not None:
                    return True
            except (AttributeError, TypeError, ValueError):
                pass
        return False

    def siege_navigation_owns(self, order, task_only=False):
        return bool(self.siege_capable() and
                    self.combat_stop.navigation_owns(order, task_only=task_only))

    def _refresh_siege_aim(self, now):
        # Mode ownership is independent of this input. Only the current
        # enabled descriptor may move its native hydraulic actuator.
        self._siege_aim_candidate = None
        if (self._siege_pending is not None or
                int(getattr(self.entity, 'siegeState', 0)) != siege_mechanics.ENABLED):
            self.siege_aim.reset()
            return
        if (self._mission_brakes() or self._stationary_review_wait() or
                not self.combat_stop.combat_owned or
                self.attack_policy.decision.get('action') not in
                    ('aim', 'preaim', 'wait', 'firing_position')):
            return
        frame = self.attack_policy.frame
        if frame is None or frame.get('artillery'):
            return
        preferred = self.attack_policy.decision.get('candidate')
        self._siege_aim_candidate = self.siege_aim.candidate(frame, now, preferred)

    def siege_desired(self, state, command, target):
        """Mode follows the existing combat/navigation owner, never aim proof."""
        current = int(state.get('siege_state', siege_mechanics.DISABLED))
        pending = self._siege_pending
        if pending is not None:
            return bool(pending['enabled'])
        if current in (siege_mechanics.SWITCHING_ON, siege_mechanics.SWITCHING_OFF):
            return current == siege_mechanics.SWITCHING_ON
        if 'fire' in self.features:
            if self.combat_stop.navigation_owns(command):
                return False
            # The policy may legitimately withhold its firing target while
            # armour/mechanical evidence is pending.  That is not a loss of
            # the already selected visible contact, nor a navigation handoff.
            contact = self.combat_stop.engagement_target(command, target)
            return contact is not None
        # Auto-drive-only keeps the original BOT rule.  Combat-owned local
        # movement above is deliberately not reclassified by this distance.
        destination = (command.get('control_trace') or {}).get('strategic_move_position')
        if destination is not None:
            command = dict(command, move_position=destination)
        return shared_runtime.BotRuntime._physical_siege_desired(state, command, target)

    def current_attack_candidate(self, source, target, for_aim=False):
        policy = self.attack_policy
        if (policy is None or not self.combat_stop.active or not self._live() or
                source.get('id') != self.actor_id or not isinstance(target, dict) or
                not self.combat_stop.contains(target) or
                (source.get('profile') or {}).get('class_tag') == 'SPG' or
                policy.decision.get('action') not in
                    (('aim', 'preaim', 'firing_position') if for_aim else ('aim',))):
            return None
        candidate, frame = policy.decision.get('candidate'), policy.frame
        if not candidate or not frame or frame['loaded'] != int(self.gun.shot_index):
            return None
        selected = candidate['target']
        if ((selected.get('kind'), selected.get('network_id')) !=
                (target.get('kind'), target.get('network_id'))):
            return None
        mode = candidate.get('mode', 'penetration')
        row = policy.current_row(candidate)
        if (row is None or row.get('pose_stamp') != candidate.get('pose_stamp') or
                row.get('line_stamp') != candidate.get('line_stamp')):
            return None
        planned = (policy._planned_evidence(row) if for_aim and
                   row.get('mechanical') in ('hull_laying', 'mechanical_limited') and
                   policy._plannable(row, mode) else None)
        if planned is not None and not (planned.get('solution') or {}).get('needs_hull'):
            planned = None
        intention = planned or row
        if ((not for_aim and not policy._executable(row, mode)) or
                (for_aim and (not isinstance(intention.get('solution'), dict) or
                    (row.get('mechanical') not in ('reachable', 'hull_laying') and
                     planned is None) or
                    intention.get('line') != 'clear' and policy.decision['action'] != 'preaim'))):
            return None
        if policy.decision['action'] == 'firing_position' and (
                (row.get('mechanical') != 'hull_laying' and planned is None) or
                self._last_navigation.get('owner') != 'copied_combat_hull_aim'):
            return None
        if planned is not None:
            # This detached view supplies a safe turn's future direction to
            # the native aiming law. The policy row keeps its actual blocked
            # line/mechanical limitation/unknown armour. The fire entrance
            # above can never accept this planning-only view.
            return dict(row, solution=dict(planned['solution'], _player_motion_only=True),
                        _player_stationary_motion=True)
        return row

    def _gun_handoff_preserves_controls(self, candidate, command):
        """Prove a gun-only target cannot change the already solved BOT input.

        Capture/parking and fire-only control may keep a different admitted
        gun target from their navigation target. The original hull law still
        runs later, so evaluate that same pure law before donating the target.
        A limited gun outside its actual arc never gains a new turn here.
        """
        owner, state = self.combat_stop, self.state
        if (not owner.active or not owner.combat_owned or owner.stop_allowed or
                owner.explicit_travel or self._mission_brakes() or
                not owner.contains(candidate.get('target')) or
                not self.attack_policy._executable(candidate, candidate.get('mode', 'penetration'))):
            return False
        task = owner.task_order
        if 'drive' in self.features and (task.get('throttle_override') != 0. or
                _distance(_point(task.get('move_position') or state['position']),
                          state['position']) > shared_driver.WAYPOINT_ARRIVAL_RADIUS):
            return False
        if (not command or command.get('movement_intent', True) or
                abs(float(command.get('throttle', 0.))) > .01 or
                any(state.get(name) for name in ('_gun_angle_adjustment',
                    '_rear_aim_episode', '_rear_hull_aim', '_rear_motion_lease')) or
                self.actor_id in self.engine._friendly_repositions):
            return False
        descriptor = self.engine._descriptors.get(self.actor_id, {})
        limits = self.engine._gun_yaw_limits.get(self.actor_id)
        if limits is None:
            limits = shared_driver.gun_yaw_limits(descriptor)
        minimum, maximum, limited = limits
        target = candidate['target']
        point = target['position']  # the copied live-target overlay uses this centre
        dx, dz = point[0] - state['x'], point[2] - state['z']
        distance = math.hypot(dx, dz)
        yaw = math.atan2(dx, dz) if distance > .1 else state['yaw']
        if limited:
            pitch = -math.atan2(point[1] + 1. - state['y'], max(.5, distance))
            signature = self.engine._ballistic_solution_signature(
                state, target, descriptor, state.get('shell_index', 0))
            cached = self.engine._ballistic_solution_cache.get(self.actor_id)
            if cached is not None and cached[0] == signature:
                yaw, pitch = cached[2]['yaw'], cached[2]['pitch']
            local = self.engine._local_gun_angles_for_world(state, yaw, pitch)
            if local is None:
                return False
            yaw = state['yaw'] + local[0]
        turn, throttle = float(command.get('turn', 0.)), float(command.get('throttle', 0.))
        proposed = shared_driver.combat_hull_aim(
            state['yaw'], yaw, minimum, maximum, turn, throttle,
            command.get('recovery_mode', 'drive'),
            not command.get('empty_ammo') and command.get('combat_mode') != 'base_defense' and
                not command.get('parking_phase'),
            combat_mode=command.get('combat_mode'),
            movement_intent=command.get('movement_intent', True),
            rear_turn=0., allow_rear_start=not state.get('_rear_motion_blocked', False))
        return bool(not proposed[2] and abs(proposed[0] - turn) <= 1.e-12 and
                    abs(proposed[1] - throttle) <= 1.e-12)

    def attack_candidate_consumable(self, candidate):
        owner = self.combat_stop
        target = candidate.get('target') or {}
        selected = (owner.task_order.get('target_kind'), owner.task_order.get('target_id'))
        if owner.stop_allowed or (target.get('kind'), target.get('network_id')) == selected:
            return True
        return self._gun_handoff_preserves_controls(candidate, self._last_order)

    def prepare_gun_handoff(self, now):
        """Record the gun intention before the original driver consumes its task."""
        self._gun_handoff = None
        candidate = self.attack_policy.decision.get('candidate')
        owner = self.combat_stop
        if (self.attack_policy.decision.get('action') != 'aim' or candidate is None or
                owner.stop_allowed or not self.attack_candidate_consumable(candidate)):
            return
        original = (owner.task_order.get('target_kind'), owner.task_order.get('target_id'))
        selected = candidate['target']
        if (selected.get('kind'), selected.get('network_id')) != original:
            self._gun_handoff = dict(at=now, generation=self.generation,
                original=original, candidate=candidate['key'])

    def consume_gun_handoff(self, source, command, target, now):
        """Refine only the gun after proving the original movement is unchanged."""
        lease = getattr(self, '_gun_handoff', None)
        candidate = self.attack_policy.decision.get('candidate')
        if (lease is None or lease['at'] != now or lease['generation'] != self.generation or
                candidate is None or lease['candidate'] != candidate['key'] or
                target is None or lease['original'] !=
                    (target.get('kind'), target.get('network_id')) or
                command.get('target_id') not in (target.get('id'), target.get('network_id')) or
                command.get('target_kind') not in (None, target.get('kind'))):
            return command, target
        selected = candidate['target']
        current = self.current_attack_candidate(source, selected)
        if current is None or not self._gun_handoff_preserves_controls(current, command):
            # This is an execution refusal, never an armour/geometry failure.
            # The next frontier can consume the original target instead of
            # retaining an impossible aim until a shot which cannot happen.
            self.attack_policy.selected = None
            self.attack_policy._choose('wait', 'gun_target_handoff_refused')
            self._gun_handoff = None
            return dict(command, fire_allowed=False), target
        return dict(command, target_id=selected.get('network_id', selected.get('id')),
            target_kind=selected.get('kind'), stable_hull_face=True), selected

    def _observe_attack_lay(self, state, target, intention, now):
        policy = self.attack_policy
        if policy is None or policy.decision['reason'] == 'no_relevant_enemy':
            self._attack_lay = None
            return
        if policy.decision['action'] != 'aim' or target is None:
            return
        if state['gun_aligned']:
            self._attack_lay = None
            return
        candidate = policy.decision['candidate']
        if candidate is None:
            return
        desired_yaw, desired_pitch = intention.get('turret_yaw'), intention.get('gun_pitch')
        error = (max(abs(_angle(state['turret_yaw'] - desired_yaw)),
                     abs(state['gun_pitch'] - desired_pitch))
                 if desired_yaw is not None and desired_pitch is not None else float('inf'))
        progress = self._attack_lay
        position = state['position']
        if progress is None or _distance(progress['position'], position) >= .25:
            self._attack_lay = dict(best=error, progressed_at=now,
                                    verified=self.weapon.verified, position=position)
        elif (error < progress['best'] - NATIVE_ANGLE_TOLERANCE or
                self.weapon.verified and not progress['verified']):
            progress.update(best=error, progressed_at=now, verified=self.weapon.verified)
        elif now - progress['progressed_at'] >= MECHANICAL_STALL_SECONDS:
            policy.lay_stalled(candidate, now)
            self._attack_lay = None

    def _suspend_attack(self):
        """Retire only the new shooting policy when original navigation owns."""
        if self._owned_next_shell is not None:
            self._release_next_shell('original_navigation', required=False)
        if self.attack_policy.decision.get('reason') != 'original_navigation':
            self.attack_policy.reset()
        self.attack_policy.decision = dict(action='unchanged',
            reason='original_navigation', candidate=None)
        self._move_episode = None
        self._siege_aim_candidate = None
        self.siege_aim.reset()
        if self._last_navigation.get('action') in ('search_penetration', 'firing_position'):
            self._last_navigation = {}

    def _accept_controls(self, command, throttle, turn, path_clear, motion_probe, now):
        order = dict(command, throttle=float(throttle), turn=float(turn), path_clear=bool(path_clear))
        if self._mission_brakes():
            order.update(throttle=0., turn=0., brake=True, fire_allowed=False,
                         movement_intent=False)
            self.state['hull_aiming'] = False
            self.state.pop('_confirmed_facing', None)
            order.pop('confirmed_facing', None)
        elif self.state.get('hull_aiming') and not abs(throttle) > .01:
            order['confirmed_facing'] = dict(
                state='turning' if abs(turn) > 1.e-7 else 'settling',
                owner='copied_combat_hull_aim', at=now)
        else:
            order.pop('confirmed_facing', None)
        area = (self._mission or {}).get('capture_area')
        if area and capture_orders.inside(self.state, area) and not self.state.get('airborne'):
            center = area['point']
            order['capture_pivot_circle'] = ((center['x'], center['z']), area['radius'])
        else:
            order.pop('capture_pivot_circle', None)
        self._last_order = order
        if self.combat_stop.stop_allowed and self.attack_policy is not None:
            action = self.attack_policy.decision['action']
            if action in ('search_penetration', 'firing_position'):
                navigation = dict(self._last_navigation, action=action, at=now,
                    position=tuple(self.state['position']), path_clear=bool(path_clear),
                    throttle=order['throttle'], turn=order['turn'],
                    recovery=order.get('recovery_mode'))
                if 'drive' not in self.features or self._mission_brakes():
                    navigation.update(status='refused', reason='drive_authority_unavailable')
                elif not path_clear:
                    navigation.update(status='blocked', reason='copied_motion_probe')
                elif abs(order['throttle']) > .01 or abs(order['turn']) > .01:
                    navigation.update(status='accepted')
                episode = self._move_episode
                if episode is not None:
                    navigation['displacement'] = _distance(episode['source'], self.state['position'])
                self.attack_policy.navigation_result(navigation)

    def _observe_loading_completion(self):
        """Retire one load's switch limit only on actual native readiness."""
        if self.gun.reload_time <= 0.:
            self._loading_switch = None

    def _record_shell(self, event, setting, requested, accepted, reason, force=False, plan=None):
        gun = self.gun
        self._shell_receipt = dict(event=event, setting=setting, requested=requested,
            accepted=bool(accepted), reason=reason, loaded=int(gun.shot_index),
            pending=gun.pending_index, clip=int(gun.clip), reload=float(gun.reload_time),
            plan=(plan or {}).get('key'), proof_at=(plan or {}).get('observed_at'),
            shot_seq=self._last_committed_shot_seq, at=self.now)
        if self.controller is not None and (force or self.now - self._shell_log_at >= .25):
            if event in ('queue_release', 'queue_unavailable') and self.attack_policy is not None:
                self._shell_receipt['next_review'] = self.attack_policy.next_review_details(plan, reason)
            self._shell_log_at = self.now
            self.controller.record('shell_transition', **self._shell_receipt)

    def _release_next_shell(self, reason='control_released', required=True, at_trigger=False):
        lease = self._owned_next_shell
        if lease is None:
            return
        if lease.get('releasing'):
            return
        gun = lease['gun']
        if (self._binding() != lease['identity'] or self.gun is not gun or
                gun.pending_index != lease['index']):
            self._owned_next_shell = None
            return
        # NEXT only changes the future load. An accepted physical trigger and
        # the load already in progress retain their native ownership.
        if observation(self).trigger_active():
            self._owned_next_shell = None
            return
        if observation(self).fire_intent_active():
            self._owned_next_shell = None
            return
        if int(gun.ammo[int(gun.shot_index)]) <= 0:
            self._owned_next_shell = None
            return
        lease['releasing'] = True
        try:
            self._shell_setting('NEXT_SHELLS', int(gun.shot_index))
        finally:
            lease['releasing'] = False
        if self._owned_next_shell is not lease:
            return
        if (self._binding() == lease['identity'] and self.gun is gun and
                gun.pending_index == lease['index']):
            # A refused setter is not a cleanup receipt. The lifecycle owner
            # retries this exact obligation; it must not cancel a later manual
            # selection or a replacement gun when that retry eventually runs.
            self._record_shell('queue_release', 'NEXT_SHELLS', lease['index'], False,
                               reason, force=at_trigger, plan=lease.get('plan'))
            if required:
                raise RuntimeError('owned_next_shell_release_pending')
            return
        self._owned_next_shell = None
        if self.gun is gun and self._binding() == lease['identity']:
            self._record_shell('queue_release', 'NEXT_SHELLS', lease['index'], True,
                               reason, force=at_trigger, plan=lease.get('plan'))

    def _apply_next_shell(self, at_trigger=False):
        if (not self._live() or self._mission_brakes() or 'fire' not in self.features or
                not self.combat_stop.active):
            return
        if (observation(self).trigger_active() or
                observation(self).fire_intent_active()):
            return
        gun = self.gun
        manual = self._manual_shell
        if (manual is not None and manual[0] is gun and
                (manual[2] == 'NEXT_SHELLS' or manual[1] is not None)):
            return
        if at_trigger and min(gun.clip, gun.ammo[int(gun.shot_index)]) > gun.burst_count:
            return
        lease = self._owned_next_shell
        if lease is not None and (lease['gun'] is not gun or
                lease['identity'] != self._identity or gun.pending_index != lease['index']):
            self._owned_next_shell = lease = None
        if gun.pending_index is not None and lease is None:
            # A manually queued shell is a real input, not a policy suggestion.
            return
        policy = self.attack_policy
        frame = policy.frame
        stale_frame = (frame is None or policy._frame_invalid or
                       frame['loaded'] != gun.shot_index or frame['ammo'] != tuple(gun.ammo))
        if at_trigger:
            # Current-shot approval is independent of this bounded ranking.
            plan, reason = ((None, 'observation_changed') if stale_frame else
                            policy.refresh_next_at_trigger(self.now))
            index = plan['shell_index'] if plan is not None else None
        else:
            index, plan, reason = policy.next_shell, policy.next_plan, policy.next_status
            if plan is not None and stale_frame:
                return
            if plan is not None and not policy._plannable(policy.current_row(plan), plan['mode']):
                index, plan, reason = None, None, 'candidate_expired'
        if index is None:
            if lease is not None:
                self._release_next_shell(reason, required=False, at_trigger=at_trigger)
            elif at_trigger:
                self._record_shell('queue_unavailable', 'NEXT_SHELLS', None, False, reason, force=True)
            return
        index = int(index)
        if index < 0 or index >= len(gun.ammo) or gun.ammo[index] <= 0:
            return
        if index == int(gun.shot_index):
            if lease is not None:
                self._release_next_shell('ranked_current_shell', required=False, at_trigger=at_trigger)
            return plan if self._live() and gun.pending_index is None else None
        if gun.ammo[int(gun.shot_index)] <= 0 and gun.reload_time > 0.:
            return
        if gun.pending_index == index:
            lease['plan'] = plan
            return plan
        token = self.generation
        epoch = self._manual_shell_epoch
        loaded_before = int(gun.shot_index)
        lease = dict(index=index, gun=gun, identity=self._identity, generation=token, plan=plan)
        self._owned_next_shell = lease
        accepted = self._shell_setting('NEXT_SHELLS', index)
        if not self._live(token):
            # Native setters can call Stop before completing their own write.
            if (self._manual_shell_epoch == epoch and
                    self._binding() == lease['identity'] and gun.pending_index == index):
                self._owned_next_shell = lease
                self._release_next_shell()
            elif self._owned_next_shell is lease:
                self._owned_next_shell = None
            return
        if not accepted or gun.pending_index != index:
            if self._owned_next_shell is lease:
                self._owned_next_shell = None
        if self._manual_shell_epoch != epoch or self.gun is not gun:
            return
        applied = accepted and (gun.pending_index == index or
                                gun.shot_index == index != loaded_before)
        if applied and gun.shot_index != loaded_before:
            policy.load_started(int(gun.shot_index), plan)
        self._record_shell('queue', 'NEXT_SHELLS', index, applied,
                           'ranked_plan' if applied else 'native_setting_refused',
                           force=at_trigger, plan=plan)
        return plan if applied else None

    def _apply_shell_intent(self):
        if not self._live() or self._mission_brakes() or 'fire' not in self.features:
            return
        if (not self.combat_stop.active and
                (self.state.get('profile') or {}).get('class_tag') != 'SPG'):
            return
        decision = self.attack_policy.decision
        action = decision.get('action')
        if action not in ('switch_shell', 'reload_clip'):
            return
        if (observation(self).trigger_active() or
                observation(self).fire_intent_active()):
            return
        gun = self.gun
        reloading = float(gun.reload_time) > 0.
        manual = self._manual_shell
        if manual is not None and manual[0] is gun and (reloading or manual[2] == 'NEXT_SHELLS'):
            return
        # Stock CURRENT may restart an ordinary load (or transfer progress
        # with Intuition). Only the policy's proved replacement for this
        # single-shot load may exercise that input, once during the load.
        # Admission follows the current replacement proof below, not a second
        # list of policy reason labels. Ordinary HE and fallback transitions
        # need the same loading-time input as other proved replacements.
        if reloading and (action != 'switch_shell' or gun.clip_size > 1 or
                gun.burst_count > 1 or self._loading_switch is gun or
                decision.get('candidate') is None and gun.ammo[gun.shot_index] > 0):
            return
        index = decision.get('shell_index')
        lease = self._owned_next_shell
        if self.gun.pending_index is not None and (lease is None or
                lease['gun'] is not self.gun or lease['index'] != self.gun.pending_index):
            return
        token = self.generation
        if index is not None and int(index) != int(self.gun.shot_index):
            index = int(index)
            if not 0 <= index < len(gun.ammo) or gun.ammo[index] <= 0:
                return
            frame = self.attack_policy.frame
            if frame is not None and not self.attack_policy.evaluator.fence(frame):
                return
            candidate = decision.get('candidate')
            if candidate is not None:
                current = self.attack_policy.current_row(candidate)
                if not self.attack_policy._plannable(current, candidate.get('mode', 'penetration')):
                    return
                fence = getattr(self.attack_policy.evaluator, 'fence_next', None)
                if callable(fence) and not fence(frame, (current,), False):
                    return
            setting = 'CURRENT_SHELLS'
            accepted = self._shell_setting(setting, index)
            applied = bool(accepted and gun.shot_index == index)
        elif action == 'reload_clip' and not reloading:
            if decision.get('candidate') is None and lease is not None:
                # A pending comparison may already have cleared the policy
                # plan while its older native NEXT lease is still installed.
                # R must not promote that stale queue before the background
                # cleanup later in this frame. Manual queues are fenced above.
                self._release_next_shell('partial_reload_plan_pending', required=False)
                if (not self._live(token) or self.gun is not gun or
                        self._owned_next_shell is not None or gun.pending_index is not None):
                    return
            if gun.clip >= gun.clip_size and gun.pending_index is None:
                # A full cassette of the same shell has no native R action.
                # Keep the qualified reload while the background seeks a
                # proved replacement; never fake a reload or spam refusals.
                return
            setting = 'RELOAD_PARTIAL_CLIP'
            accepted = self._shell_setting(setting)
            applied = bool(accepted and gun.clip == 0 and gun.reload_time > 0.)
        else:
            return
        if not self._live(token) or self.gun is not gun:
            return
        if applied and setting == 'CURRENT_SHELLS' and gun.reload_time > 0.:
            self._loading_switch = gun
        if applied:
            self.attack_policy.load_started(int(gun.shot_index), decision.get('candidate'))
        self._record_shell('setting', setting, index, applied, decision['reason'],
                           plan=decision.get('candidate'))

    def _siege_fire_ready(self):
        """Automatic first edges require the physically enabled combat mode.

        A level target can be geometrically reachable with travel's zero
        elevation. That does not bypass engagement's native mode transition.
        Already committed trigger tails remain owned by the native gun.
        """
        if not self.siege_capable():
            return True
        physical = observation(self)
        return bool(physical.native_siege_state() == siege_mechanics.ENABLED and
            int((self.state or {}).get('siege_state', 0)) == siege_mechanics.ENABLED and
            self._siege_pending is None and
            not physical.mode_pending())

    def attack_search_drive_available(self):
        mission = self._mission or {}
        return bool(self.combat_stop.stop_allowed and not self._mission_brakes() and
                    self._implicit_retry is None and not mission.get('capture_started') and
                    not (mission.get('explicit') and mission.get('destination') is not None))

    def _move_order(self, order, now):
        """The admitted armour search; ordinary recovery remains the BOT law."""
        if not self.combat_stop.stop_allowed:
            return order
        decision = self.attack_policy.decision
        action = decision.get('action')
        if action == 'firing_position':
            self._move_episode = None
            return order
        if action != 'search_penetration':
            deadline = (self._move_episode or {}).get('deadline')
            if deadline is not None and now >= deadline:
                self.attack_policy.navigation_result(dict(self._last_navigation,
                    action='search_penetration', status='expired', at=now))
            elif (self.attack_policy.navigation_receipt or {}).get('action') in (
                    'firing_position', 'search_penetration'):
                self.attack_policy.navigation_result(None)
            if self._last_navigation.get('action') in ('firing_position', 'search_penetration'):
                self._last_navigation = {}
            self._move_episode = None
            return order
        request = decision.get('move_request') or {}
        identity = request.get('episode_id')
        if not self.attack_search_drive_available():
            self._last_navigation = dict(action=action, episode_id=identity, at=now,
                status='refused', reason='drive_authority_unavailable')
            self.attack_policy.navigation_result(self._last_navigation)
            return order
        target = request.get('target') or (decision.get('candidate') or {}).get('target')
        if not self.combat_stop.contains(target):
            target = self.combat_stop.engagement_target(order)
        if target is None:
            return order
        source = self.state['position']
        episode = self._move_episode
        if episode is None or episode['identity'] != identity:
            retry = self._move_retry
            if retry is not None and retry['identity'] == identity and now < retry['until'] and _distance(source, retry['source']) < 2.:
                return order
            episode = self._move_episode = dict(identity=identity, source=tuple(source),
                deadline=None, cursor=0, goal=None, tried=[], target=dict(target))
        episode['deadline'] = request.get('deadline')
        if episode['deadline'] is not None and now >= episode['deadline']:
            self._last_navigation = dict(status='timeout', reason='firing_position_exhausted',
                                         action=action, fallback='ordinary_navigation')
            self._move_retry = dict(identity=identity, source=tuple(source), until=now + 1.)
            self._move_episode = None
            self.attack_policy.navigation_result(self._last_navigation)
            return order
        goal = episode.get('goal')
        if goal is not None and _distance(source, goal) < 1.5:
            episode['tried'].append(goal)
            episode['goal'] = goal = None
        attempted = False
        if goal is None:
            # These are requests, not invented reachable receipts. The copied
            # navigator proves and executes the route; native sweeps own the
            # next physical move and report failed candidate edges normally.
            target_position = _point(target['position'])
            bearing = math.atan2(target_position[0] - source[0], target_position[2] - source[2])
            offsets = (math.pi / 2., -math.pi / 2., math.pi / 4., -math.pi / 4., math.pi)
            cursor = episode['cursor']
            if cursor < len(offsets) * 2:
                attempted = True
                distance = 8. if cursor < len(offsets) else 16.
                yaw = bearing + offsets[cursor % len(offsets)]
                candidate = (episode['source'][0] + math.sin(yaw) * distance,
                             source[1], episode['source'][2] + math.cos(yaw) * distance)
                episode['cursor'] += 1
                ground = self.geometry._navigation_ground(candidate[0], candidate[2])
                if ground is not None:
                    candidate = (candidate[0], float(ground), candidate[2])
                    if self.engine.navigator.grid.segment_clear(source, candidate):
                        episode['goal'] = goal = candidate
        self._last_navigation = dict(
            status='moving' if goal is not None else 'path_refused' if attempted else 'searching',
            action=action, episode_id=identity, attempted=attempted, at=now,
            goal=goal, candidates=episode['cursor'])
        self.attack_policy.navigation_result(self._last_navigation)
        episode['deadline'] = request.get('deadline')
        self._last_navigation['deadline'] = episode['deadline']
        if goal is None:
            return self._resume_firing_approach(order, target)
        result = dict(order, move_position=goal, throttle_override=None,
                      fire_allowed=False, combat_mode='player_' + action)
        return result

    def _release_native_hull_laying(self, reason, now):
        self.combat_stop.release_laying(reason, now)

    def _ordinary_firing_order(self, order, now):
        return self.combat_stop.apply_order(order, now)

    def _resume_firing_approach(self, order, target):
        # Keep existing route, traffic and recovery control when it
        # already has a destination. Release only an attack-owned stop.
        position = self.state['position']
        goal = order.get('move_position') or position
        if ('drive' not in self.features or self._mission_brakes() or
                order.get('parking_phase') or order.get('empty_ammo') or
                order.get('combat_mode') == 'base_defense' or
                order.get('throttle_override') != 0. and _distance(_point(goal), position) > 1.):
            return order
        return self.engine._gun_angle_combat_order(self.state,
            dict(order, aim_position=target['position'], face_position=target['position']))

    def _accept_combat_order(self, order, now):
        """Apply the same combat owner after the shared strategic order."""
        artillery = (self.state.get('profile') or {}).get('class_tag') == 'SPG'
        if artillery and 'fire' in self.features:
            from .artillery_selection import ArtillerySelection
            if getattr(self, 'artillery_selection', None) is None:
                self.artillery_selection = ArtillerySelection()
            order = self.artillery_selection.select(self, order, now)
        order = self.combat_stop.accept(order)
        self._gun_handoff = None
        if 'fire' in self.features:
            if self.combat_stop.active or artillery:
                if self.combat_stop.waiting_for_siege():
                    self.attack_policy.decision = dict(action='wait',
                        reason='engagement_waits_native_siege', candidate=None)
                else:
                    self.attack_policy.update(now)
                self.prepare_gun_handoff(now)
                self._refresh_siege_aim(now)
                order = self.attack_policy.apply_order(order, now)
                order = self.combat_stop.apply_order(order, now)
                if self.combat_stop.stop_allowed:
                    order = self._move_order(order, now)
            else:
                self._suspend_attack()
        order = self._mission_guard_order(order, now)
        if self.siege_navigation_owns(order):
            # Mode debounce must not keep the last enemy's hydraulic input
            # alive after navigation has already accepted control. The normal
            # gun law may still publish its own hull-forward resting source.
            self._siege_aim_candidate = None
            self.siege_aim.reset()
        return order
