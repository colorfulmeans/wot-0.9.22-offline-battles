"""One foreground owner for ordinary firing-position recovery.

The policy owns *why* a move is needed.  This object owns the lifetime of an
ordinary attempt and delegates each existing local manoeuvre exactly once.
The copied navigator, driver, traffic guards and native actuators still own
all path and physical movement decisions.  The armour-search eight-second
episode is deliberately absent from this module.
"""
from __future__ import division

import math

from .. import siege_mechanics
from ..projectile_runtime import PROJECTILE_BROADPHASE_RADIUS
from .copied import bot_runtime as laws
from .copied.ai.driver import WAYPOINT_ARRIVAL_RADIUS
from .copied.ai.navigation import MACRO_PROGRESS_METRES
from .native_aim import NATIVE_ANGLE_TOLERANCE


# Moved from FullPlayerRuntime's native pivot observation, not a new global
# search timeout.  Copied mechanical/friendly/navigation leases keep theirs.
MECHANICAL_STALL_SECONDS = 6.0
_PROTECTED_MODES = ('base_defense', 'low_health_retreat',
                    'magazine_reload_retreat', 'withdraw')
_ATTACK_MODES = ('engage', 'advance_contact', 'support_hold', 'cover_hold',
                 'cover_peek', 'gun_angle_adjust', 'friendly_lane_reposition')


def _point(value):
    if isinstance(value, dict):
        return tuple(float(value[name]) for name in ('x', 'y', 'z'))
    return tuple(float(value[index]) for index in range(3))


def _distance(first, last):
    return math.hypot(float(first[0]) - float(last[0]),
                      float(first[2]) - float(last[2]))


def _angle(value):
    return (float(value) + math.pi) % (2. * math.pi) - math.pi


def _target_key(target):
    kind = target.get('kind')
    return ('human' if kind == 'player' else kind,
            target.get('network_id', target.get('id')))


class EngagementPosition(object):
    """Lifecycle above the existing player-local movement laws.

    ``apply_order`` runs before the copied physical control loop.  The three
    copied manoeuvre hooks delegate back here, so they cannot silently start
    another attempt after a terminal handoff.  Mode exit is a native request
    owned by FullPlayerRuntime; this owner only fences its completion.
    """

    def __init__(self, runtime):
        self.runtime = runtime
        self.sequence = 0
        self.episode = None
        self.terminal = None
        self.pivot = None
        self.task_order = None
        self.receipt = {}
        self.contact_witness = None
        self._mission = None

    @property
    def active(self):
        return self.episode is not None and self.terminal is None

    @property
    def suppressed(self):
        return self.terminal is not None

    @property
    def exit_required(self):
        return self.suppressed and not self._travel_stable()

    def _managed(self):
        runtime = self.runtime
        return bool('fire' in runtime.features and runtime.state is not None and
                    (runtime.state.get('profile') or {}).get('class_tag') != 'SPG')

    def _mission_key(self):
        runtime = self.runtime
        return (getattr(runtime, 'generation', None),
                (getattr(runtime, '_mission', None) or {}).get('id'))

    def _travel_stable(self):
        runtime = self.runtime
        state = runtime.state or {}
        owner = runtime.owner
        entity = getattr(runtime, 'entity', None)
        return bool(int(state.get('siege_state', siege_mechanics.DISABLED)) ==
                    siege_mechanics.DISABLED and
                    int(getattr(entity, 'siegeState', siege_mechanics.DISABLED)) ==
                    siege_mechanics.DISABLED and
                    getattr(runtime, '_siege_pending', None) is None and
                    getattr(owner, '_local_siege_pending', None) is None and
                    getattr(owner, '_local_siege_braking', None) is None)

    def _clear_local_laws(self):
        """Retire tactical leases, never reset the real navigation/driver."""
        runtime = self.runtime
        self.pivot = None
        runtime._native_hull_laying = None
        engine, state = runtime.engine, runtime.state
        if engine is None or state is None:
            return
        engine._clear_friendly_reposition(runtime.actor_id)
        for name in ('_gun_angle_adjustment', '_gun_angle_pivot_refusal',
                     '_rear_aim_episode', '_rear_hull_aim', '_rear_motion_lease',
                     '_rear_contact_refusal', '_magazine_followup'):
            state.pop(name, None)
        state['_rear_motion_blocked'] = False
        state['local_combat_manoeuvre'] = False
        engine._decision_cache.pop(runtime.actor_id, None)

    def reset(self):
        self._clear_local_laws()
        self.episode = self.terminal = self.contact_witness = None
        self.task_order = None
        self.receipt = {}
        self._mission = self._mission_key()
        # In particular, do not cancel an already submitted native mode
        # transition.  Its sequence-fenced observer remains in FullRuntime.

    def remember_task(self, order):
        identity = self._mission_key()
        if self._mission is not None and self._mission != identity:
            self.reset()
        self._mission = identity
        self.task_order = dict(order)

    def _scope(self):
        runtime = self.runtime
        targets = {}
        for target in getattr(runtime, '_targets', ()):
            if target.get('alive', True) and target.get('position') is not None:
                targets[_target_key(target)] = (
                    _point(target['position']), float(target.get('yaw', 0.)))
        position = _point(runtime.state['position'])
        return dict(position=position, targets=targets,
                    lines=self._line_scope(position, targets))

    def _line_scope(self, position, targets):
        """Observe existing collision revisions; perform no new lane query.

        A demolished wall or a departed friendly must be able to rearm a
        travel-mode siege vehicle even though its zero-pitch gun cannot yet
        publish an actual executable shot.  Do not use the whole observation
        timestamp/descriptor as a revision: those would rearm every frame.
        """
        frame = getattr(self.runtime.attack_policy, 'frame', None) or {}
        radius = PROJECTILE_BROADPHASE_RADIUS
        regions = tuple((min(position[0], target[0][0]) - radius,
                         max(position[0], target[0][0]) + radius,
                         min(position[2], target[0][2]) - radius,
                         max(position[2], target[0][2]) + radius)
                        for target in targets.values())
        blockers = {}
        for row in frame.get('blockers', ()):
            # NativeAttackEvaluator's existing lane frontier already froze
            # complete component matrices for these allies/wrecks.
            if not isinstance(row, (tuple, list)) or len(row) != 9:
                continue
            point, pose = row[7], row[8]
            if not any(x0 <= point[0] <= x1 and z0 <= point[2] <= z1
                       for x0, x1, z0, z1 in regions):
                continue
            blockers[row[2]] = (row[3:7], pose[0:2] + pose[6:], pose[2:6])
        debris = frame.get('debris')
        # An unavailable debris provider deliberately stamps every attack
        # frontier unknown with observed_at. Unknown is not a physical change.
        if not isinstance(debris, (tuple, list)):
            debris = None
        return dict(scene=frame.get('scene'), missing=frame.get('lane_missing'),
                    blockers=blockers, debris=debris)

    @staticmethod
    def _line_scope_changed(previous, current):
        if any(previous.get(key) != current.get(key) for key in ('scene', 'missing', 'debris')):
            return True
        old, new = previous['blockers'], current['blockers']
        if set(old) != set(new):
            return True
        for key in old:
            before, after = old[key], new[key]
            if before[:2] != after[:2]:
                return True
            for first, last in zip(before[2], after[2]):
                if (any(abs(float(first[0][axis]) - float(last[0][axis])) >= MACRO_PROGRESS_METRES
                        for axis in range(3)) or
                        any(abs(_angle(first[axis] - last[axis])) >= NATIVE_ANGLE_TOLERANCE
                            for axis in (1, 2, 3))):
                    return True
        return False

    def _scope_changed(self, previous):
        current = self._scope()
        if self._line_scope_changed(previous['lines'], current['lines']):
            return True
        if _distance(previous['position'], current['position']) >= WAYPOINT_ARRIVAL_RADIUS:
            return True
        old, new = previous['targets'], current['targets']
        if set(old) != set(new):
            return True
        # A descriptor swap or hydraulic/barrel jitter is not a new place.
        # Use the navigator's existing positional tolerance, and observed
        # target-body rotation rather than its independently animated gun.
        return any(_distance(old[key][0], new[key][0]) >= WAYPOINT_ARRIVAL_RADIUS or
                   abs(_angle(old[key][1] - new[key][1])) >= NATIVE_ANGLE_TOLERANCE
                   for key in old)

    def _native_shot_ready(self):
        policy = self.runtime.attack_policy
        decision = policy.decision
        candidate = decision.get('candidate')
        if decision.get('action') != 'aim' or candidate is None:
            return False
        current = policy.current_row(candidate, require_line=True)
        return bool(policy._executable(current, candidate.get('mode', 'penetration')))

    def _start(self, now):
        if self.episode is not None:
            return
        self.sequence += 1
        self.episode = dict(id=self.sequence, started_at=float(now), phase='ordinary',
                            scope=self._scope(), gun=self.runtime.gun,
                            friendly_deadline=None, mechanical_start=None,
                            driver_seen=self._driver_recovery_key(
                                self._driver_state().get('recovery_trigger')),
                            driver_recovery=None)
        self.receipt = dict(action='firing_position', status='started', at=float(now),
                            episode_id=self.sequence, lifecycle_owner='player_engagement')

    def _publish(self, status, reason, now, owner='copied_ordinary_navigation', **fields):
        identity = ((self.episode or {}).get('id') or
                    (self.terminal or {}).get('episode_id'))
        self.receipt = dict(action='firing_position', status=status, reason=reason,
                            owner=owner, lifecycle_owner='player_engagement',
                            episode_id=identity, at=float(now))
        self.receipt.update(fields)
        self.runtime._last_navigation = dict(self.receipt)
        return self.receipt

    def _fail(self, reason, evidence, now):
        if not self.active:
            return
        episode = self.episode
        self.terminal = dict(episode_id=episode['id'], started_at=episode['started_at'],
                             at=float(now), reason=reason, evidence=dict(evidence or {}),
                             scope=self._scope(), phase='exit')
        self.episode = None
        self.contact_witness = None
        self._clear_local_laws()
        self.terminal['phase'] = 'exit' if self.exit_required else 'route'
        self._publish('timeout' if 'timeout' in reason or 'stalled' in reason else 'failed',
                      reason, now, terminal=True, phase=self.terminal['phase'],
                      evidence=dict(evidence or {}))
        self.runtime.attack_policy.navigation_result(dict(self.receipt))

    def _driver_state(self):
        adapter = getattr(self.runtime.engine, 'adapter', None)
        driver = getattr(adapter, 'driver', None)
        return (getattr(driver, 'states', {}) or {}).get(self.runtime.actor_id) or {}

    @staticmethod
    def _driver_recovery_key(receipt):
        if not isinstance(receipt, dict):
            return None
        return (receipt.get('at'), receipt.get('reason'),
                tuple(receipt.get('origin') or ()), tuple(receipt.get('goal') or ()))

    def _observe_completed_driver_recovery(self, now):
        """End only after the existing timeout recovery really completed.

        A safe global path can still end at a native contact. In that case
        there need not be an A* no-path event. The original driver owns its
        progress clock and bounded backout; this owner observes its completion
        instead of running a second timeout or interrupting a live recovery.
        """
        episode = self.episode
        driver = self._driver_state()
        receipt = driver.get('recovery_trigger') or {}
        identity = self._driver_recovery_key(receipt)
        if identity is not None and identity != episode['driver_seen']:
            episode['driver_seen'] = identity
            if receipt.get('reason') in ('objective_timeout', 'native_translation_timeout'):
                episode['driver_recovery'] = dict(receipt=dict(receipt),
                    count=int(driver.get('recovery_count', 0)),
                    position=tuple(self.runtime.state['position']))
        recovery = episode.get('driver_recovery')
        if recovery is None:
            return False
        if _distance(self.runtime.state['position'], recovery['position']) >= WAYPOINT_ARRIVAL_RADIUS:
            episode['driver_recovery'] = None
            return False
        if (int(driver.get('recovery_count', 0)) > recovery['count'] and
                float(driver.get('recovery_time', 0.)) <= 0.):
            evidence = dict(recovery['receipt'], completed_count=driver['recovery_count'],
                            completed_clock=driver.get('clock'),
                            position=tuple(self.runtime.state['position']))
            self._fail('navigation_recovery_stalled', evidence, now)
            return True
        return False

    def observe(self, now):
        """Consume completed original leases, not mere pending/path age."""
        if not self._managed():
            return
        if self.terminal is not None:
            self.terminal['phase'] = 'exit' if self.exit_required else 'route'
            return
        if self.episode is None:
            return
        state = self.runtime.state
        started = self.episode['started_at']
        mechanical = state.get('_gun_angle_last_terminal') or {}
        if (float(mechanical.get('sampled_at', float('-inf'))) >= started and
                mechanical.get('reason') in ('bounded_attempt_complete', 'relocation_stalled')):
            self._fail(mechanical['reason'], mechanical, now)
            return
        friendly = state.get('_friendly_reposition_last_terminal') or {}
        if (float(friendly.get('at', float('-inf'))) >= started and
                friendly.get('outcome') == 'timeout'):
            self._fail('friendly_position_timeout', friendly, now)
            return
        if self._observe_completed_driver_recovery(now):
            return
        navigator = self.runtime.engine.navigator
        navigation = navigator.bot_states.get(self.runtime.actor_id) or {}
        events = navigation.get('local_target_events') or ()
        for event in reversed(events):
            if float(event.get('at', float('-inf'))) < started:
                break
            if event.get('reason') == 'timeout':
                self._fail('navigation_local_timeout', event, now)
                return
        selection = navigation.get('local_selection') or {}
        fallback = navigation.get('local_fallback') or {}
        path_key = navigation.get('path_key')
        completed_failure = (path_key in navigator.paths and
                             navigator.paths[path_key] == [])
        if (navigation.get('navigation_status') == 'blocked' and
                float(selection.get('at', float('-inf'))) >= started and
                selection.get('outcome') == 'no_candidate' and
                completed_failure and fallback.get('attempted', 0) > 0 and
                not fallback.get('missing_ground') and not fallback.get('shallow_or_unknown') and
                not getattr(navigator.grid, '_proof_deferred', False)):
            # This is the completed navigator's bounded no-route/no-local-leg
            # receipt, not a single collision probe or an unfinished A* job.
            self._fail('navigation_no_firing_route', selection, now)

    def _protected(self, order):
        runtime = self.runtime
        mission = getattr(runtime, '_mission', None) or {}
        return bool(order.get('parking_phase') or order.get('empty_ammo') or
                    order.get('combat_mode') in _PROTECTED_MODES or
                    runtime._mission_brakes() or mission.get('capture_started') or
                    mission.get('explicit') and mission.get('destination') is not None)

    def _tag(self, order, phase):
        identity = ((self.episode or {}).get('id') or
                    (self.terminal or {}).get('episode_id'))
        # Stable fields take part in the copied order identity. Never attach
        # now/age or a diagnostic receipt, which would flush it every frame.
        return dict(order, _player_position_episode=identity,
                    _player_position_phase=phase)

    def _route_order(self, order, now):
        runtime = self.runtime
        result = dict(self.task_order or order)
        if not self._protected(result) and result.get('combat_mode') in _ATTACK_MODES:
            bot = runtime._planner_bot()
            if bot is not None:
                route, index, move, anchor, join = runtime.planner._route(bot, now)
                result.update(route_id=route, route_index=index, move_position=move,
                              face_position=move, route_anchor=anchor, route_join=join,
                              combat_mode='route', throttle_override=None)
                runtime.planner._apply_authored_route_order(result, bot, move, now)
        result.update(target_id=None, target_kind=None, aim_position=None, fire_allowed=False)
        if self.exit_required:
            result.update(move_position=tuple(runtime.state['position']),
                          throttle_override=0., throttle=0., turn=0., brake=True,
                          movement_intent=False)
        phase = 'exit' if self.exit_required else 'route'
        self._publish('exiting' if self.exit_required else 'handed_back',
                      self.terminal['reason'], now, phase=phase, terminal=True)
        return self._tag(result, phase)

    def guard_command(self, command, target=None, now=None):
        """Fence the late copied attack overlay after native drive solving."""
        if not self._managed() or not self.suppressed:
            return None
        result = dict(command, target_id=None, target_kind=None, aim_position=None,
                      fire_allowed=False)
        result.pop('_player_attack_solution', None)
        result.pop('_player_siege_contact', None)
        if self.exit_required:
            result.update(throttle=0., turn=0., brake=True, movement_intent=False)
        self.runtime.state['hull_aiming'] = False
        return self._tag(result, 'exit' if self.exit_required else 'route'), None

    def contact(self, receipt):
        """Accept a witnessed enemy translation veto, never nearby enemies."""
        if not isinstance(receipt, dict) or not self._managed() or self.suppressed:
            return False
        peer = receipt.get('peer')
        if not isinstance(peer, dict):
            peer = dict(kind=receipt.get('peer_kind'), network_id=receipt.get('peer_id'),
                        team=receipt.get('team'), position=receipt.get('peer_position'),
                        alive=receipt.get('enemy_blocking') is True)
        if (receipt.get('source') != 'foreground_enemy_translation' or
                receipt.get('enemy_blocking') is not True or
                not isinstance(peer, dict) or not peer.get('alive', False) or
                peer.get('kind') not in ('bot', 'player', 'human') or
                peer.get('network_id', peer.get('id')) is None or
                peer.get('team') not in (1, 2) or
                peer.get('team') == self.runtime.state.get('team') or
                receipt.get('fraction', 1.) >= 1. or
                receipt.get('attempted_heading') is None):
            return False
        self.contact_witness = dict(receipt, peer=dict(peer))
        return True

    def apply_order(self, order, now):
        """Return an ordinary-owned order, or None for other attack actions."""
        if not self._managed():
            return None
        self.observe(now)
        runtime = self.runtime
        policy = runtime.attack_policy
        decision = policy.decision
        action = decision.get('action')
        if self.suppressed:
            if not self.exit_required and (self._native_shot_ready() or
                    action in ('search_penetration', 'reload_clip', 'switch_shell', 'retreat') or
                    self._scope_changed(self.terminal['scope'])):
                self.terminal = None
                self.receipt = {}
            else:
                return self._route_order(order, now)
        if action == 'aim':
            if self.active:
                self._clear_local_laws()
                self.episode = self.contact_witness = None
            return None
        preview = getattr(runtime, '_siege_motion_candidate', None)
        preview = preview if (isinstance(preview, dict) and
                              action in ('wait', 'preaim', 'firing_position') and
                              (preview.get('solution') or {}).get('future_reachable')) else None
        if self._protected(order) or 'drive' not in runtime.features:
            if self.active:
                self._clear_local_laws()
                self.episode = None
            return None
        if policy.stationary_review_wait():
            if self.active:
                # The policy's existing bounded evidence wait owns the stop.
                # Suspend old tactical manoeuvres without creating an attempt
                # or renewing/releasing their original progress clocks.
                self.episode['phase'] = 'stationary_review'
                self._publish('checking', decision['reason'], now,
                              'player_stationary_review')
                return self._tag(order, 'stationary_review')
            return None
        witness = self.contact_witness
        if witness is not None:
            peer = witness['peer']
            key = _target_key(peer)
            current = next((row for row in runtime._targets if _target_key(row) == key), None)
            if (current is None or _distance(runtime.state['position'], witness['position']) >=
                    WAYPOINT_ARRIVAL_RADIUS):
                self.contact_witness = witness = None
        if action in ('wait', 'preaim') and witness is not None and not self.active:
            self._start(now)
            self.episode['phase'] = 'contact_verify'
        if preview is None and action in ('wait', 'preaim', 'firing_position'):
            waiting_mode = self._await_mode_validation(order, now)
            if waiting_mode is not None:
                return waiting_mode
        if action != 'firing_position' and preview is None:
            if self.active and action in ('wait', 'preaim'):
                self.release_laying('native_pivot_lost_proof', now)
                if self.episode['phase'] == 'contact_verify':
                    self._publish('checking', 'witnessed_enemy_blocks_travel', now)
                    return self._tag(dict(order, move_position=tuple(runtime.state['position']),
                        throttle_override=0., fire_allowed=False), 'contact_verify')
                # Evidence refresh does not renew/erase a pending manoeuvre.
                return self._tag(order, self.episode['phase'])
            if self.active:
                self._clear_local_laws()
                self.episode = None
            return None
        self._start(now)
        candidate = decision.get('candidate') or {}
        request = decision.get('move_request') or {}
        if preview is not None:
            candidate = preview
        target = candidate.get('target') or request.get('target')
        if not isinstance(target, dict):
            target = next((row for row in runtime._targets if
                           row.get('network_id') == order.get('target_id') and
                           row.get('kind') == order.get('target_kind')), None)
            target = target or next(iter(runtime._targets), None)
        if target is None:
            self._clear_local_laws()
            self.episode = None
            return None
        solution = candidate.get('solution') or request.get('solution') or {}
        mechanical = candidate.get('mechanical')
        stationary = None
        if (preview is None and mechanical in ('hull_laying', 'mechanical_limited') and
                candidate.get('stationary_plan') is not None and
                candidate.get('shell_index') == runtime.gun.shot_index):
            current = policy.current_row(candidate, require_line=True)
            planned = policy._planned_evidence(current)
            if (planned is not None and
                    current.get('mechanical') in ('hull_laying', 'mechanical_limited') and
                    (planned.get('solution') or {}).get('needs_hull') is True and
                    policy._plannable(current, candidate.get('mode', 'penetration'))):
                # The actual muzzle can be blocked while the proved safe
                # stationary turn has a clear firing lane. Only borrow that
                # future solution for motion; never rewrite the actual row.
                stationary, solution = planned, planned['solution']
        can_lay = (preview is not None or stationary is not None or
                   mechanical == 'hull_laying' and candidate.get('line') == 'clear' and
                   candidate.get('shell_index') == runtime.gun.shot_index)
        if can_lay:
            lay = self._lay_order(order, candidate, target, solution, now, preview is not None)
            if lay is not None:
                return lay
        else:
            self.release_laying('native_pivot_lost_proof', now)
        if candidate.get('line') == 'friendly_blocked':
            self.episode['phase'] = 'friendly'
            active = runtime.engine._friendly_repositions.get(runtime.actor_id)
            if active is None:
                command = dict(order, target_id=target['id'])
                launch = dict(fire_seq=int(runtime.state.get('fire_seq', 0)) + 1,
                              shot_yaw=solution.get('yaw', runtime.state['aim_yaw']))
                active = self.mark_friendly_reposition(runtime.state, command, target, launch,
                    request.get('blocker') or candidate.get('blocker') or {}, now)
            self._publish('waiting', 'friendly_lane', now, 'copied_friendly_reposition')
            if active:
                return self._tag(order, 'friendly')
        else:
            # A different lane/target cannot reset the same ordinary attempt.
            # Its old friendly lease must not override the new point's owner.
            runtime.engine._clear_friendly_reposition(runtime.actor_id)
        handoff = (self.pivot or {}).get('handoff')
        mechanical_phase = mechanical in ('hull_laying', 'mechanical_limited', 'siege_projected')
        self.episode['phase'] = 'mechanical' if mechanical_phase and handoff is None else 'ordinary'
        if self.episode['phase'] == 'mechanical':
            # This refusal comes from the policy's actual per-point mechanical
            # result.  The old late centre-point solver cannot be relied on to
            # seed it: direct aiming correctly withholds that unproved point.
            # Admit the existing bounded angle law instead of releasing its
            # hold before it can select a checked relocation.
            runtime.state['_gun_angle_refusal'] = runtime.engine._artillery_target_identity(target)
            self._publish('waiting', decision.get('reason'), now,
                          'copied_gun_angle_recovery')
            return self._tag(dict(order, move_position=tuple(runtime.state['position']),
                face_position=target['position'], throttle_override=0.,
                combat_mode='engage', fire_allowed=False), 'mechanical')
        if mechanical_phase and handoff is not None:
            # The failed native pivot already yielded movement. Do not issue
            # another stationary rear-aim lease before it actually translates.
            runtime.state['_gun_angle_pivot_refusal'] = runtime.engine._artillery_target_identity(target)
        self._publish('waiting', handoff['reason'] if handoff else decision.get('reason'), now,
                      pivot_handoff=dict(handoff) if handoff else None)
        return self._tag(self._resume_approach(order, target), self.episode['phase'])

    def release_laying(self, reason, now):
        if self.pivot is not None and 'handoff' not in self.pivot:
            self.pivot['handoff'] = dict(reason=reason, at=float(now),
                                        position=tuple(self.runtime.state['position']))

    def _await_mode_validation(self, order, now):
        """Do not lose an admitted native transition at descriptor rebinding.

        Keeping its stationary lifetime is not keeping the old aim proof.
        There is deliberately no point/trajectory returned here.  Once the
        native mode is stable, actual verification shares the existing laying
        stall allowance instead of receiving a fresh one every pending scan.
        """
        if (not self.active or self.pivot is None or not self.pivot.get('projected') or
                'handoff' in self.pivot):
            return None
        runtime = self.runtime
        mode = int(runtime.state.get('siege_state', siege_mechanics.DISABLED))
        switching = bool(mode in (siege_mechanics.SWITCHING_ON, siege_mechanics.SWITCHING_OFF) or
                         getattr(runtime, '_siege_pending', None) is not None or
                         getattr(runtime.owner, '_local_siege_pending', None) is not None)
        if not switching and mode != siege_mechanics.ENABLED:
            return None
        if switching:
            phase, reason = 'siege_transition', 'siege_precheck_waits_native_mode'
        else:
            if not self.pivot['stable_started']:
                self.pivot.update(stable_started=True, progress_at=float(now))
            if now - self.pivot['progress_at'] >= MECHANICAL_STALL_SECONDS:
                self.release_laying('native_pivot_stalled', now)
                self.episode['phase'] = 'ordinary'
                return None
            phase, reason = 'siege_verify', 'siege_actual_pose_validation_pending'
        self.episode['phase'] = phase
        self._publish('switching' if switching else 'checking', reason, now,
                      'native_siege_transition' if switching else 'native_siege_validation')
        return self._tag(dict(order, move_position=tuple(runtime.state['position']),
            throttle_override=0., fire_allowed=False), phase)

    def _lay_order(self, order, candidate, target, solution, now, projected):
        runtime, state = self.runtime, self.runtime.state
        handoff = (self.pivot or {}).get('handoff')
        if handoff is not None:
            if _distance(state['position'], handoff['position']) < WAYPOINT_ARRIVAL_RADIUS:
                return None
            self.pivot = runtime._native_hull_laying = None
        yaw = float(state['yaw'])
        desired_yaw = float(solution.get('hull_yaw', solution.get('yaw', yaw)))
        error = abs(_angle(desired_yaw - yaw))
        hydraulic = float(getattr(runtime.owner, '_local_siege_aim_pitch',
                                  state.get('suspension_pitch', 0.)))
        desired_pitch = float(solution.get('siege_correction', hydraulic))
        pitch_error = abs(desired_pitch - hydraulic)
        identity = runtime.engine._artillery_target_identity(target)
        mode = int(state.get('siege_state', siege_mechanics.DISABLED))
        switching = bool(mode in (siege_mechanics.SWITCHING_ON, siege_mechanics.SWITCHING_OFF) or
                         getattr(runtime, '_siege_pending', None) is not None or
                         getattr(runtime.owner, '_local_siege_pending', None) is not None)
        if self.pivot is None:
            self.pivot = dict(target=identity, gun=runtime.gun, shell=runtime.gun.shot_index,
                progress_at=float(now), progress_yaw=yaw, best_error=error,
                progress_pitch=hydraulic, best_pitch_error=pitch_error,
                projected=bool(projected),
                stable_started=not projected or mode == siege_mechanics.ENABLED and not switching)
            runtime._native_hull_laying = self.pivot
        pivot = self.pivot
        if identity != pivot['target']:
            # A new target/point changes the error origin, not elapsed time.
            pivot.update(target=identity, best_error=error, best_pitch_error=pitch_error,
                         progress_yaw=yaw, progress_pitch=hydraulic)
        if projected and (mode != siege_mechanics.ENABLED or switching):
            self.episode['phase'] = 'siege_transition'
            self._publish('switching', 'siege_precheck_waits_native_mode', now,
                          'native_siege_transition')
            return self._tag(dict(order, move_position=tuple(state['position']),
                throttle_override=0., fire_allowed=False), 'siege_transition')
        if not pivot['stable_started']:
            pivot.update(stable_started=True, progress_at=float(now))
        progressed = (abs(_angle(yaw - pivot['progress_yaw'])) >= NATIVE_ANGLE_TOLERANCE and
                      error < pivot['best_error'] - NATIVE_ANGLE_TOLERANCE or
                      projected and abs(hydraulic - pivot['progress_pitch']) >= NATIVE_ANGLE_TOLERANCE and
                      pitch_error < pivot['best_pitch_error'] - NATIVE_ANGLE_TOLERANCE)
        if progressed:
            pivot.update(best_error=min(error, pivot['best_error']),
                         best_pitch_error=min(pitch_error, pivot['best_pitch_error']),
                         progress_at=float(now), progress_yaw=yaw, progress_pitch=hydraulic)
        if (now < state.get('_native_rotation_refused_until', 0.) or
                now - pivot['progress_at'] >= MECHANICAL_STALL_SECONDS):
            self.release_laying('native_pivot_stalled', now)
            return None
        self.episode['phase'] = 'native_lay'
        self._publish('aligning', solution.get('mechanical_reason',
                      'siege_projected_laying' if projected else 'yaw_limit'), now,
                      'copied_combat_hull_aim')
        return self._tag(dict(order, move_position=tuple(state['position']),
            face_position=solution.get('point') or target['position'], throttle_override=0.,
            combat_mode='engage', fire_allowed=False), 'native_lay')

    def _resume_approach(self, order, target):
        runtime = self.runtime
        position = runtime.state['position']
        goal = order.get('move_position') or position
        if (self._protected(order) or 'drive' not in runtime.features or
                order.get('throttle_override') != 0. and _distance(_point(goal), position) > 1.):
            return order
        return runtime.engine._gun_angle_combat_order(runtime.state,
            dict(order, aim_position=target['position'], face_position=target['position']))

    def gun_angle_order(self, state, order, targets, now, direction_clear):
        engine = self.runtime.engine
        if not self._managed():
            return laws.BotRuntime._gun_angle_order(engine, state, order, targets, now, direction_clear)
        if (self.runtime.attack_policy.stationary_review_wait() or
                not self.active or self.episode['phase'] not in ('mechanical', 'ordinary')):
            return order
        previous = state.get('_gun_angle_adjustment')
        result = laws.BotRuntime._gun_angle_order(engine, state, order, targets, now, direction_clear)
        marker = state.get('_gun_angle_adjustment')
        if marker is not None:
            if self.episode['mechanical_start'] is None:
                self.episode['mechanical_start'] = marker['start']
            elif previous is None:
                marker['start'] = min(marker['start'], self.episode['mechanical_start'])
        self.observe(now)
        if self.suppressed:
            return self._route_order(result, now)
        return self._tag(result, self.episode['phase'])

    def mark_friendly_reposition(self, state, command, target, launch, verdict, now):
        engine = self.runtime.engine
        if self._managed() and (self.runtime.attack_policy.stationary_review_wait() or
                               not self.active or self.episode['phase'] != 'friendly'):
            return False
        result = laws.BotRuntime._mark_friendly_reposition(
            engine, state, command, target, launch, verdict, now)
        if self._managed() and result:
            marker = engine._friendly_repositions.get(self.runtime.actor_id)
            deadline = self.episode['friendly_deadline']
            if marker is not None:
                if deadline is None:
                    self.episode['friendly_deadline'] = marker['deadline']
                else:
                    marker['deadline'] = min(marker['deadline'], deadline)
        return result

    def friendly_reposition_order(self, state, targets, now):
        engine = self.runtime.engine
        if not self._managed():
            return laws.BotRuntime._friendly_reposition_order(engine, state, targets, now)
        if (self.runtime.attack_policy.stationary_review_wait() or
                not self.active or self.episode['phase'] != 'friendly'):
            return None, False
        result, expired = laws.BotRuntime._friendly_reposition_order(engine, state, targets, now)
        self.observe(now)
        if self.suppressed:
            # The current server order has already been installed. Return its
            # recovered task through the normal decide_with_order consumer.
            order = engine._server_orders.get(self.runtime.actor_id) or {}
            return self._route_order(order, now), False
        return result, expired

    def rear_laying_order(self, state, order, targets, now):
        if self._managed():
            # Direct-fire policy already selected the point and the explicit
            # ordinary pivot owner is above. Never start the old centre-point
            # rear or magazine-followup stop underneath that decision.
            for name in ('_rear_aim_episode', '_rear_hull_aim', '_rear_motion_lease',
                         '_rear_contact_refusal', '_magazine_followup'):
                state.pop(name, None)
            state['_rear_motion_blocked'] = bool(self.runtime.attack_policy.stationary_review_wait() or
                                                self.suppressed or self.active and
                                                self.episode['phase'] != 'native_lay')
            return order
        return laws.BotRuntime._rear_laying_order(self.runtime.engine, state, order, targets, now)

    def navigation_result(self, receipt, now):
        """Observe ordinary physical feedback without starting armour search."""
        if not isinstance(receipt, dict) or receipt.get('action') != 'firing_position':
            return receipt
        self.observe(now)
        if self.suppressed:
            result = dict(self.receipt, terminal=True,
                          phase='exit' if self.exit_required else 'route')
        else:
            result = dict(receipt, lifecycle_owner='player_engagement',
                          episode_id=(self.episode or {}).get('id'))
        self.receipt = result
        self.runtime._last_navigation = dict(result)
        return result
