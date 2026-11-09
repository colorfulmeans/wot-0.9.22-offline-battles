# -*- coding: utf-8 -*-
"""Shared decision-to-physical-engine boundary for human and BOT actors."""
from __future__ import print_function

import math

from .. import bot_runtime as shared_runtime


def _angle(value):
    return (float(value) + math.pi) % (2. * math.pi) - math.pi


class SharedEngineControl(object):
    def _clear_actor_controls(self):
        """Retire per-actor decisions, never the native physical trigger tail."""
        for control in tuple(getattr(self, '_actor_controls', {}).values()):
            if getattr(control, 'actor_kind', None) == 'bot':
                control.close()
        # A foreground engine is an I/O facade already registered by its
        # binding before battle_start installs the physical observations.
        self._actor_controls = dict((actor_id, control)
            for actor_id, control in getattr(self, '_actor_controls', {}).items()
            if getattr(control, 'actor_kind', None) != 'bot')
        self._control_launch_proofs = {}

    def _control_for(self, state):
        actor_id = int(state['id'])
        controls = getattr(self, '_actor_controls', None)
        if controls is None:
            return None
        control = controls.get(actor_id)
        if (control is not None and getattr(control, 'actor_kind', None) == 'bot' and
                control._binding() != control._identity):
            control.close()
            del controls[actor_id]
            control = None
        if control is None and self._control_factory is not None:
            control = self._control_factory(self, actor_id)
            controls[actor_id] = control
        return control

    def _siege_desired(self, state, command, target):
        control = self._control_for(state)
        if control is not None:
            return control.siege_desired(state, command, target)
        return self._physical_siege_desired(state, command, target)

    def _cadenced_ballistic_solution(self, state, target, descriptor,
                                     shell_index, now, force=False):
        runtime = self._control_for(state)
        if runtime is None:
            return self._physical_cadenced_ballistic_solution(state, target, descriptor, shell_index, now, force)
        if (state.get('profile') or {}).get('class_tag') != 'SPG':
            candidate = runtime.current_attack_candidate(state, target, for_aim=True)
            if candidate is not None and int(candidate['shell_index']) == int(shell_index):
                # The new direct owner sampled the real native turret and
                # measured motion. Reconstructing that point from the Bot
                # record here would project a different part/lead; the old
                # record is an observation, not this selected aim intention.
                solution = dict(candidate['solution'])
                solution['_origin'] = tuple(solution['origin'])
                solution['arc'] = 'low'
                identity = self._artillery_target_identity(target)
                reachable = self._world_solution_reachable(
                    state, descriptor, solution['yaw'], solution['pitch'])
                if not reachable:
                    state['_gun_angle_refusal'] = identity
                else:
                    state.pop('_gun_angle_refusal', None)
                if reachable:
                    (state.get('_gun_angle_rejected') or {}).pop(identity, None)
                state['_gun_solution_receipt'] = dict(at=now, target=identity,
                    shell_index=int(shell_index), origin=solution['_origin'],
                    aim_position=solution['aim_position'],
                    world_yaw=solution['yaw'], world_pitch=solution['pitch'],
                    reason=candidate.get('mechanical'), owner='native_player_candidate')
                signature = self._ballistic_solution_signature(
                    state, target, descriptor, shell_index)
                self._ballistic_solution_cache[state['id']] = (
                    signature, now + shared_runtime.LOCAL_ACTION_SECONDS, solution)
                return solution, True
            laying = runtime.siege_aim_candidate(target)
            if laying is not None and int(laying['shell_index']) == int(shell_index):
                # The active hydraulic actuator follows the same current
                # point as an ordinary finite-traverse gun. This is input
                # only, not a future-mode or actual firing certificate.
                solution = dict(laying['solution'])
                solution.update(_origin=tuple(solution['origin']), arc='low',
                                _player_motion_only=True)
                return solution, True
            if runtime.combat_stop.active:
                self._ballistic_solution_cache.pop(state['id'], None)
                return None, False
            return self._physical_cadenced_ballistic_solution(
                state, target, descriptor, shell_index, now, force)
        # The native rotator consumes an installed source asynchronously. A
        # newly solved point cannot replace its own unconsumed proposal every
        # frame, otherwise a moving contact can never meet the copied 1e-7
        # physical alignment gate. This is an input lease, never launch proof:
        # the original exact-arc and target-motion reproof remain mandatory.
        signature = self._ballistic_solution_signature(state, target, descriptor, shell_index)
        reproof = self._artillery_reproofs.get(state['id']) or {}
        proof_epoch = (reproof.get('created'), reproof.get('attempts', 0))
        pose = self._artillery_source_pose(state)[:6]
        proposal = getattr(runtime, '_native_artillery_proposal', None)
        intent = self._active_artillery_intent(state, target, descriptor, shell_index, now)
        if intent is not None:
            runtime._native_artillery_proposal = None
            return self._physical_cadenced_ballistic_solution(
                state, target, descriptor, shell_index, now, True)
        if proposal is not None:
            anchor = proposal['pose']
            moved = math.sqrt(sum((pose[index] - anchor[index]) ** 2 for index in range(3)))
            rotated = any(abs(_angle(pose[index] - anchor[index])) > .001 for index in range(3, 6))
            valid = (target is not None and signature == proposal['signature'] and
                     proof_epoch == proposal['proof_epoch'] and now <= proposal['until'] and
                     moved <= .05 and not rotated)
            if valid:
                solution = dict(proposal['solution'])
                self._ballistic_solution_cache[state['id']] = (
                    signature, now + shared_runtime.LOCAL_ACTION_SECONDS, solution)
                return solution, True
            runtime._native_artillery_proposal = None
        solution, fresh = self._physical_cadenced_ballistic_solution(
            state, target, descriptor, shell_index, now, True)
        if isinstance(solution, dict) and target is not None:
            runtime._native_artillery_proposal = dict(signature=signature, pose=pose,
                proof_epoch=proof_epoch, solution=dict(solution),
                until=now + shared_runtime.ARTILLERY_INTENT_SECONDS)
        return solution, fresh

    def _direct_aim_matches(self, state, target, solution):
        runtime = self._control_for(state)
        if runtime is None:
            return self._physical_direct_aim_matches(state, target, solution)
        candidate = runtime.current_attack_candidate(state, target)
        if candidate is not None:
            selected = candidate['solution']
            matches = bool(isinstance(solution, dict) and
                solution.get('_aim_token') == selected.get('_aim_token') and
                solution.get('aim_position') == selected.get('aim_position') and
                solution.get('_origin') == selected.get('origin'))
            if not matches:
                self._ballistic_solution_cache.pop(int(state['id']), None)
            return matches
        if runtime.combat_stop.active:
            return False
        return self._physical_direct_aim_matches(state, target, solution)

    def _apply_blocked_direct_aim(self, source, command, target, now, probe_budget=None):
        runtime = self._control_for(source)
        if runtime is None:
            return self._physical_apply_blocked_direct_aim(source, command, target, now, probe_budget)
        if runtime.combat_stop.explicit_travel:
            # The copied BOT recognizes base_defense as a hull-priority
            # handoff, but does not know player-only team_* mission names.
            # Keep the already solved original navigation controls intact;
            # do not donate a gun target to its later rear-hull laying law.
            # This is not a blanket gate on ordinary authored advance.
            return dict(command, fire_allowed=False, aim_position=None), None
        contact = target
        command, target = self._physical_apply_blocked_direct_aim(
            source, command, target, now, probe_budget)
        contact = target if target is not None else contact
        if not runtime.combat_stop.active:
            return command, target
        policy = runtime.attack_policy
        command, target = runtime.consume_gun_handoff(source, command, target, now)
        command, target = policy.select_command(source, command, target, now)
        if not runtime._siege_fire_ready():
            # A newly ready point cannot reopen fire while the mode request
            # is still braking, transitioning or waiting for its native echo.
            command = dict(command, fire_allowed=False)
        if runtime._mission_brakes():
            # Arrival settling/terminal commands own the input boundary. They
            # cannot donate the hull actuator back to an otherwise valid gun
            # target later in the copied loop.
            return dict(command, fire_allowed=False), None
        if policy.decision['action'] == 'unchanged':
            return command, target
        candidate = runtime.current_attack_candidate(source, target, for_aim=True)
        if candidate is None:
            # Match the contact for which the original driver solved this
            # frame. A later motion-only candidate cannot change its target.
            laying = (runtime.siege_aim_candidate(contact)
                      if contact is not None else None)
            if laying is not None:
                return dict(command, fire_allowed=False,
                    aim_position=laying['solution']['point'],
                    _player_motion_only=True), laying['target']
            # Strategic contacts may steer navigation, but cannot publish a
            # second direct aim point while the player policy awaits proof.
            # The copied mode switch uses that contact before the gun can lay.
            return dict(command, fire_allowed=False, aim_position=None,
                        _player_siege_contact=target if target is not None else contact), None
        context = runtime.geometry._bot_aim_context(source, target)
        sample = candidate['solution'].get('sample_value')
        if context is not None and sample is not None:
            context[2]['selected'] = sample
        return command, target

    def _shot_clear(self, source, target, now, force=False,
                    probe_budget=None, lane_key=None, distance_cache=None):
        runtime = self._control_for(source)
        if runtime is None:
            return self._physical_shot_clear(source, target, now, force, probe_budget, lane_key, distance_cache)
        candidate = runtime.current_attack_candidate(source, target)
        if candidate is not None:
            # The new direct-fire owner proves the selected curved shell path,
            # not the old centre-to-centre straight advisory. It does not grant
            # a shot: the unchanged native first-edge admission still checks
            # the actual current scattered parabola, friends and target pose.
            context = runtime.geometry._bot_aim_context(source, target)
            sample = candidate['solution'].get('sample_value')
            if context is None or sample is None:
                return False
            context[2]['selected'] = sample
            key = lane_key if lane_key is not None else self._shot_los_key(source, target)
            self._shot_los_cache[key] = (float(now), True)
            return True
        return self._physical_shot_clear(
            source, target, now, force, probe_budget, lane_key, distance_cache)
