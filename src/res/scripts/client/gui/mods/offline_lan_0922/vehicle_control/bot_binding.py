# -*- coding: utf-8 -*-
"""Bind the shared automatic controller to one worker-owned vehicle.

This module observes the existing worker gun, ammunition and body. It does
not create a second simulation, a local PlayerAvatar, or a second decision
implementation. Explicit shell inputs are translated to the same native
weapon owners which advance and commit the worker's physical rounds.
"""
from __future__ import division

import math

from .. import hull_aiming, siege_mechanics
from ..gun_mechanics import _field
from ..native_input_diagnostics import combat_detail, combat_detail_enabled
from .attack_policy import AttackPolicy
from .combat_control import CombatControl
from .combat_stop import CombatStop
from .mission_control import MissionControl
from .native_aim import hydraulic_body
from .siege_planning import ActualSiegeAim


def _point(value):
    result = tuple(float(value[index]) for index in range(3))
    if any(math.isnan(item) or math.isinf(item) for item in result):
        raise ValueError('non-finite worker physical observation')
    return result


class _BotGunObservation(object):
    """The common policy's read-only vocabulary over one native gun owner."""

    def __init__(self, runtime, native):
        self.runtime, self.native = runtime, native
        self.last_scatter = None

    @property
    def shots(self):
        return tuple(_field(_field(self.runtime.source_descriptor(), 'gun'),
                            'shots', ()) or ())

    @property
    def ammo(self):
        return self.runtime._native_ammo().remaining

    @property
    def shot_index(self):
        return self.runtime.physical_shell_request()

    @property
    def pending_index(self):
        return self.runtime._queued_shell

    @property
    def reload_time(self):
        return float(self.native.remaining(self.runtime.reload_factor()))

    @property
    def reload_duration(self):
        return float(self.native.duration(self.runtime.reload_factor()))

    @property
    def reload(self):
        return float(self.native.reload_full) * self.runtime.reload_factor()

    @property
    def clip(self):
        return int(self.native.clip)

    @property
    def clip_size(self):
        return int(self.native.clip_size)

    @property
    def burst_count(self):
        return int(self.native.burst_count)

    @property
    def burst_interval(self):
        return float(self.native.burst_interval)

    @property
    def base_dispersion(self):
        return float(self.native.fully_aimed_dispersion)

    @property
    def dispersion(self):
        return self.runtime.native_dispersion_angle()

    @property
    def loadout(self):
        return self.native.loadout

    def can_fire(self, battle_live=True):
        return bool(battle_live and self.native.ready(self.runtime.reload_factor()) and
                    self.native.clip > 0 and not self.runtime.trigger_active() and
                    self.runtime._native_ammo().can_fire())

    def scatter(self, direction, perfect_accuracy=False, gauss=None,
                dispersion_angle=None, uniform=None):
        """Use the physical worker's deterministic draw for this exact edge.

        The foreground admission helper supplies replayable random callbacks.
        A worker already owns its draw by round/actor/trigger/round-index, so
        those callbacks must not introduce a second source of randomness.
        """
        from ..bot_runtime import _dispersed_barrel_angles
        state = self.runtime.state
        if state is None:
            raise ValueError('worker source state is unavailable')
        engine = self.runtime.engine
        simulation = getattr(engine, '_native_simulation', None)
        sampler = (simulation.weapons.scattered_angles if simulation is not None
                   else _dispersed_barrel_angles)
        descriptor = self.runtime.source_descriptor()
        sequence = int(state.get('fire_seq', 0)) + 1
        dispersion = (self.runtime.native_dispersion_angle()
                      if dispersion_angle is None else float(dispersion_angle))
        yaw, pitch = sampler(self.runtime.actor_id, engine.round_id, sequence,
            state['aim_yaw'], state['gun_pitch'], dispersion, 0, sequence,
            base_direction=engine._dispersal_base_direction(state, descriptor))
        self.last_scatter = (sequence, yaw, pitch)
        horizontal = math.cos(pitch)
        # The physical launch protocol's pitch is positive-up.
        direction.x = math.sin(yaw) * horizontal
        direction.y = math.sin(pitch)
        direction.z = math.cos(yaw) * horizontal
        direction.normalise()
        return direction


class _BotAimObservation(object):
    """Observe native laying without taking ownership of its actuator."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.target = self.point = self.solution = None

    @property
    def verified(self):
        return bool(self.owned() and (self.runtime.state or {}).get('gun_aligned'))

    def owned(self):
        return bool(self.runtime._live() and self.runtime.source_entity() is not None)

    def observe(self, command, target):
        self.target = target
        self.solution = (command.get('_player_attack_solution') or
                         command.get('_ballistic_solution'))
        self.point = ((self.solution or {}).get('point') or
                      (self.solution or {}).get('aim_position') or
                      command.get('aim_position'))


class BotControlBinding(MissionControl, CombatControl):
    """One decision state, bound to one actor in the real worker runtime."""

    actor_kind = 'bot'

    def __init__(self, battle, engine, actor_id):
        self.owner = self.battle = self.geometry = battle
        self.engine = engine
        self.actor_id = int(actor_id)
        self.physical = self
        self.runtime = self
        self.controller = None
        self.navigation = self
        # Strategic orders still originate in the one shared planner. A
        # server-published order carries its complete admission evidence.
        self.planner = getattr(engine, 'control_planner', None)
        self.features = set(('drive', 'fire'))
        self.active, self.closed = True, False
        self.generation = int(getattr(battle, '_generation', 0))
        self.control_generation = self.generation
        self.now = float(getattr(battle, '_last_frame_time', 0.))
        self._identity = self._binding()
        self._gun_observation = None
        self._targets = ()
        self._init_mission_state()
        self._last_order = {}
        self._last_navigation = {}
        self._last_fire_failure = None
        self._gun_handoff = None
        self._attack_lay = None
        self._native_hull_laying = None
        self._siege_pending = None
        self._siege_aim_candidate = None
        self._owned_next_shell = None
        self._queued_shell = None
        self._manual_shell_epoch = 0
        self._manual_shell = None
        self._loading_switch = None
        self._shell_intent = None
        self._shell_receipt = None
        self._shell_log_at = float('-inf')
        self._last_committed_shot_seq = int((self.state or {}).get('fire_seq', 0))
        self._trigger_context = None
        self._trigger_proposal = None
        self.trigger_admission = None
        self._first_edge_pending = False
        self._support_blocked = False
        self._mission_support_known = False
        self._after_native_at = None
        self._availability = 'not_observed'
        self.weapon = _BotAimObservation(self)
        self.combat_stop = CombatStop(self)
        self.siege_aim = ActualSiegeAim(self)
        self.attack_policy = AttackPolicy(self)
        ammo = self.engine._ammo_states.get(self.actor_id)
        if (ammo is not None and int(ammo.next) != int(ammo.loaded) and
                not (ammo.reload_pending and self.gun.clip == 0)):
            # Outside a full reload the next type is still a queued input.
            self._queued_shell = int(ammo.next)
            ammo.stage(ammo.loaded, False)

    @property
    def state(self):
        state = self.engine.states.get(self.actor_id)
        if state is not None:
            # `position` is the shared controller's derived observation, not
            # a second physical position or a write to the integration axes.
            state['position'] = _point((state['x'], state['y'], state['z']))
        return state

    @property
    def entity(self):
        return self.source_entity()

    @property
    def entity_id(self):
        record = self.source_record()
        return record.get('engine_id') if record is not None else None

    @property
    def gun(self):
        native = self.engine._gun_states.get(self.actor_id)
        if native is None:
            raise ValueError('worker native gun is unavailable')
        observed = self._gun_observation
        if observed is None or observed.native is not native:
            observed = self._gun_observation = _BotGunObservation(self, native)
        return observed

    @property
    def actor_team(self):
        state = self.state
        if state is None:
            raise ValueError('worker source team is unavailable')
        return int(state['team'])

    @property
    def own_record_key(self):
        return 'bot:%s' % self.actor_id

    def source_record(self):
        return self.owner._records.get(self.own_record_key)

    def owns_record(self, record):
        own = self.source_record()
        return bool(own is not None and record.get('engine_id') == own.get('engine_id'))

    def source_entity(self):
        record = self.source_record()
        if record is None or record.get('tombstone') or not record.get('ready'):
            return None
        entity = self.owner._server_entity(record.get('engine_id'))
        return entity if entity is not None and getattr(entity, 'isStarted', False) else None

    def source_descriptor(self):
        descriptor = self.engine._descriptors.get(self.actor_id)
        if descriptor is None:
            raise ValueError('worker installed descriptor is unavailable')
        return descriptor

    def installed_descriptor(self):
        pair = (getattr(self.engine, '_descriptor_pairs', None) or {}).get(self.actor_id)
        return pair[0] if pair is not None and pair[0] is not None else self.source_descriptor()

    def target_entity(self, row):
        engine_id = row.get('engine_id')
        if engine_id is None:
            kind = row.get('kind')
            kind = 'player' if kind in ('human', 'player') else kind
            identity = row.get('network_id', row.get('id'))
            record = self.owner._records.get('%s:%s' % (kind, identity))
            engine_id = (record or {}).get('engine_id')
        return self.owner._server_entity(engine_id) if engine_id is not None else None

    def mutable_shot_ray(self):
        if self.source_entity() is None:
            raise ValueError('worker source entity is unavailable')
        state, descriptor = self.state, self.source_descriptor()
        origin = self.engine._exact_shot_origin(state, descriptor, self.gun.shot_index)
        direction = self.engine._exact_shot_direction(state, descriptor)
        if origin is None or direction is None:
            raise ValueError('worker physical gun ray is unavailable')
        return _point(origin), _point(direction)

    def gun_angles(self):
        state = self.state
        return float(state['turret_yaw']), float(state['gun_pitch'])

    def source_pose(self, origin=None):
        if self.source_entity() is None:
            raise ValueError('worker source entity is unavailable')
        state, descriptor = self.state, self.source_descriptor()
        if origin is None:
            origin = self.mutable_shot_ray()[0]
        position = _point(state['position'])
        body = _point((state['yaw'], state['pitch'], state['roll']))
        return (position, body, _point(origin), self.gun_angles(),
                id(descriptor), id(_field(descriptor, 'gun')), position)

    def weapon_identity(self):
        native = self.engine._gun_states.get(self.actor_id)
        if native is None:
            raise ValueError('worker native gun is unavailable')
        return self.generation, id(native)

    def physical_motion(self):
        state = self.state
        critical = state.get('critical') if state is not None else None
        # A fresh worker snapshot can carry an explicit empty damage record.
        if not isinstance(critical, dict) or (critical and 'destroyed' not in critical):
            raise ValueError('worker native critical observation is unavailable')
        if not isinstance(state.get('airborne'), bool):
            raise ValueError('worker native support observation is unavailable')
        if not critical and combat_detail_enabled():
            combat_detail(self, 'bot_stationary_critical', self.actor_id, self.now,
                'canonical_empty', lambda: dict(position=state['position'],
                    siege_state=state['siege_state'], destroyed=[]))
        return (tuple(sorted(str(name) for name in critical.get('destroyed', ()))),
                state['airborne'], float(state['speed']),
                float(self.engine._turn_speeds.get(self.actor_id, 0.)),
                float(state['vertical_speed']), int(state['siege_state']))

    def physical_params(self):
        return self.engine._physics_params_for(self.actor_id)

    def support_plane(self):
        return (self.state or {}).get('_suspension_ground_plane')

    def support_rise_blocked(self):
        return bool(self._support_blocked)

    def record_support(self, blocked):
        self._support_blocked = bool(blocked)
        self._mission_support_known = True

    def trigger_active(self):
        trigger = self.engine._burst_states.get(self.actor_id)
        return bool(trigger is not None and trigger.active)

    def fire_intent_active(self):
        return bool(self._first_edge_pending)

    def native_dispersion_angle(self):
        from ..bot_runtime import _effective_shot_dispersion
        native = self.engine._gun_states.get(self.actor_id)
        if native is None:
            raise ValueError('worker native gun is unavailable')
        return _effective_shot_dispersion(native, self.state, self.source_descriptor())

    def native_siege_state(self):
        # Native worker integration owns this mode. Its rendered Vehicle
        # can still display the preceding publication during the same slice.
        return int((self.state or {}).get('siege_state', siege_mechanics.DISABLED))

    def mode_pending(self):
        state = self.state or {}
        return bool(int(state.get('siege_state', siege_mechanics.DISABLED)) in
                    (siege_mechanics.SWITCHING_ON, siege_mechanics.SWITCHING_OFF) or
                    self._siege_pending is not None)

    def hydraulic_state(self):
        state, descriptor = self.state, self.source_descriptor()
        config = hull_aiming.pitch_params(descriptor)
        if (config is None or not config['isAvailable'] or not config['isEnabled'] or
                int(state.get('siege_state', 0)) != siege_mechanics.ENABLED):
            return dict(flat_matrix=None, pitch=0.)
        correction = float(state.get('suspension_pitch', 0.))
        body = (float(state['yaw']), float(self.engine._terrain_pitch(state)),
                float(state['roll']))
        position = _point(state['position'])
        # Worker integration already publishes the corrected body pose.
        # Invert its measured offset to obtain the flat actuator basis; do
        # not read the hidden observer PlayerAvatar's hydraulic matrix.
        mounted, unused = hydraulic_body(position, body, correction, config['centerZ'])
        flat = tuple(position[axis] * 2. - mounted[axis] for axis in range(3))
        matrix = self.owner._runtime.math.Matrix()
        matrix.setRotateYPR(body)
        matrix.translation = self.owner._vector(flat)
        return dict(flat_matrix=matrix, pitch=correction)

    def control_current(self, control):
        return control is self and self._live()

    def _binding(self):
        return (int(getattr(self.owner, '_generation', 0)),
                self.engine.round_id, id(self.engine), self.actor_id)

    def _live(self, token=None):
        state = self.state
        return bool(self.active and not self.closed and
                    (token is None or token == self.generation) and
                    self._binding() == self._identity and state is not None and
                    state.get('alive', False) and not self.engine.finished and
                    self._implicit_retry is None)

    def pose_stamp(self):
        return self.source_pose()

    def _mission_ready(self):
        state = self.state
        return bool(self.active and not self.closed and
                    self._binding() == self._identity and state is not None and
                    state.get('alive', False) and not self.engine.finished and
                    self.source_entity() is not None)

    def _mission_unavailable_reason(self):
        return 'native_actor_unavailable'

    def _mission_bounds(self):
        return self._defense_context().get('arena_bounds')

    def _mission_manifest(self):
        return self.engine.control_manifest

    def _defense_context(self):
        return self.engine.control_defense_context()

    def _mission_battle_result(self):
        return self._defense_context().get('battle_result')

    def _mission_motion(self):
        if not self._mission_support_known:
            return None
        state = self.state
        try:
            return dict(speed=state['speed'],
                turn_speed=self.engine._turn_speeds[self.actor_id],
                pitch=state['pitch'], roll=state['roll'],
                pitch_speed=state['suspension_pitch_velocity'],
                roll_speed=state['suspension_roll_velocity'],
                vertical_speed=state['vertical_speed'],
                lateral_speed=(state['air_lateral_x'], state['air_lateral_z']),
                position=(state['x'], state['y'], state['z']), yaw=state['yaw'],
                airborne=state['airborne'], support_rise_blocked=self._support_blocked,
                overturn_level=state['_overturn_level'])
        except (KeyError, TypeError):
            return None

    def _release_mission_inputs(self):
        # The worker keeps executing physics and accepted native burst tails.
        # Only this actor's automatic input proposal is retired.
        self.weapon.target = self.weapon.point = self.weapon.solution = None
        self._last_order = self.guard_mission_controls(self._last_order)

    def _acquire_mission_inputs(self):
        return self._mission_ready()

    def _native_ammo(self):
        ammo = self.engine._ammo_states.get(self.actor_id)
        if ammo is None:
            raise ValueError('worker native ammunition is unavailable')
        return ammo

    def reload_factor(self):
        from ..bot_runtime import _critical_factor
        return _critical_factor(self.state, self.source_descriptor(), 'reload')

    def physical_shell_request(self):
        """Supply the committed plan during a full reload."""
        ammo = self._native_ammo()
        return int(ammo.next if ammo.reload_pending and self.gun.clip == 0 else ammo.loaded)

    def _publish_weapon(self):
        state, gun, ammo = self.state, self.gun, self._native_ammo()
        self._observe_loading_completion()
        ammo.publish(state)
        if self._queued_shell is not None:
            state['next_shell_index'] = int(self._queued_shell)
        state.update(clip=gun.clip, clip_size=gun.clip_size,
            reload_time=gun.reload_time, reload_duration=gun.reload_duration,
            ammo_magazine_started=gun.native.reload_kind == 'intra')

    def _shell_setting(self, name, index=None):
        """Translate a common input to the existing native weapon owners.

        The native proxy setters/restore command update the same gun and
        ammunition objects advanced by NativeWeapons.prepare. No timer is
        ticked and no round is consumed here.
        """
        if not self._live() or self.trigger_active() or self.fire_intent_active():
            return False
        gun, ammo = self.gun.native, self._native_ammo()
        if name not in ('NEXT_SHELLS', 'CURRENT_SHELLS', 'RELOAD_PARTIAL_CLIP'):
            return False
        selected = None
        if index is not None:
            try:
                selected = int(index)
            except (TypeError, ValueError, OverflowError):
                return False
            if not 0 <= selected < len(ammo.remaining) or ammo.remaining[selected] <= 0:
                return False
        if name in ('NEXT_SHELLS', 'CURRENT_SHELLS') and selected is None:
            return False
        if name == 'NEXT_SHELLS' and ammo.remaining[ammo.loaded] > 0:
            self._queued_shell = None if selected == int(ammo.loaded) else selected
            self._publish_weapon()
            return True
        if name == 'NEXT_SHELLS':
            # Exhausted stock cannot produce an edge that promotes NEXT.
            name = 'CURRENT_SHELLS'
        if name == 'CURRENT_SHELLS':
            self._queued_shell = None
            if gun.clip == 0 and ammo.reload_pending:
                ammo.stage(selected, False)
                self._publish_weapon()
                return int(ammo.next) == selected
            if selected == int(ammo.loaded):
                ammo.stage(selected, False)
                self._publish_weapon()
                return True
            from ..bot_runtime import _bot_intuition
            burst = self.engine._burst_states.get(self.actor_id)
            if burst is None:
                raise ValueError('worker native trigger owner is unavailable')
            ready = bool(gun.ready(self.reload_factor()) and gun.clip > 0)
            # Retain the actual installed crew perk, not the retired AI aim
            # tier. This is one input event, never a roll on every tick.
            instant = _bot_intuition(self.state, self.source_descriptor(), gun,
                                     ammo, burst, selected)
            ammo.restore(dict(ammo_remaining=list(ammo.remaining),
                shell_index=selected, next_shell_index=selected,
                ammo_reload_pending=not (instant and ready)))
            if not instant:
                gun.require_full_reload()
                gun.elapsed = 0.
            elif ready:
                gun.clip = min(int(gun.clip_size), int(ammo.remaining[selected]))
            self._publish_weapon()
            return int(ammo.loaded) == selected
        if gun.clip_size <= 1 or ammo.remaining[ammo.loaded] <= 0:
            return False
        pending = self._queued_shell
        if pending is None and (gun.clip >= gun.clip_size or
                                gun.clip <= 0 and gun.remaining(self.reload_factor()) > 0.):
            return False
        selected = int(ammo.loaded) if pending is None else pending
        if ammo.remaining[selected] <= 0:
            return False
        self._queued_shell = None
        ammo.restore(dict(ammo_remaining=list(ammo.remaining), shell_index=selected,
            next_shell_index=selected, ammo_reload_pending=True))
        gun.require_full_reload()
        gun.elapsed = 0.
        self._publish_weapon()
        return gun.clip == 0 and gun.remaining(self.reload_factor()) > 0.

    def observe(self, now, targets):
        self.now = float(now)
        if not self._live():
            self._targets = ()
            self._availability = ('mission_retry' if self._implicit_retry is not None
                                  else 'native_actor_unavailable')
            return False
        values = targets.values() if isinstance(targets, dict) else targets or ()
        visible = []
        for raw in values:
            if (not isinstance(raw, dict) or not raw.get('alive', True) or
                    not raw.get('visible', True) or int(raw.get('team', 0)) == self.actor_team):
                continue
            row = dict(raw)
            kind = row.get('kind')
            record_kind = 'player' if kind in ('human', 'player') else kind
            identity = row.get('network_id', row.get('id'))
            record = self.owner._records.get('%s:%s' % (record_kind, identity))
            if record is not None:
                if record.get('tombstone') or not (record.get('state') or {}).get('alive', True):
                    continue
                row['engine_id'] = record.get('engine_id')
            if row.get('position') is None:
                row['position'] = _point((row['x'], row['y'], row['z']))
            row['kind'] = 'human' if kind == 'player' else kind
            row['network_id'] = identity
            visible.append(row)
        self._targets = tuple(visible)
        available = bool(self._live() and self.source_entity() is not None and
                         self.actor_id in self.engine._gun_states and
                         self.actor_id in self.engine._ammo_states)
        self._availability = 'ready' if available else 'native_actor_unavailable'
        return available

    def refine_order(self, order, targets, now):
        self.now = float(now)
        if not self._advance_mission_retry(now):
            self._availability = 'native_actor_unavailable'
            self.combat_stop.reset()
            return dict(order, fire_allowed=False, aim_position=None,
                move_position=self.state['position'], throttle_override=0.,
                control_pending=self._availability)
        if not self.observe(now, targets):
            self.combat_stop.reset()
            return self._mission_guard_order(dict(order, fire_allowed=False,
                aim_position=None, control_pending=self._availability), now)
        return self._accept_task_order(dict(order), now)

    def after_control(self, command, target, now):
        self.now = float(now)
        # Native prepare can complete a load and fire again in this same
        # slice. Observe readiness before first-edge admission, not only
        # after the shot has already started the following reload.
        self._observe_loading_completion()
        self.weapon.observe(command, target)
        self._accept_controls(command, command.get('throttle', 0.),
            command.get('turn', 0.), command.get('path_clear', True), None, now)
        self._observe_attack_lay(self.state, target,
            self.state.get('_diagnostic_aim_intent') or {}, self.now)

    def after_native_update(self, now):
        self.now = float(now)
        if self._after_native_at == self.now:
            return
        self._after_native_at = self.now
        if not self._advance_mission_retry(now) or not self._live():
            return
        self._publish_weapon()
        artillery = (self.state.get('profile') or {}).get('class_tag') == 'SPG'
        if self.combat_stop.active or artillery:
            self._apply_shell_intent()
        self._observe_mission(now)
        if not self._live():
            return
        if self.combat_stop.active and not self.combat_stop.waiting_for_siege():
            self._prepare_next_shell(self.now)

    def _admission(self):
        if self.trigger_admission is None:
            from .trigger_admission import TriggerAdmission
            self.trigger_admission = TriggerAdmission(self)
        return self.trigger_admission

    def prepare_trigger(self, state, target, ballistic_solution,
                        launch_receipt=None, now=None):
        """Prove one first edge using the foreground's shared transaction.

        This method never arms or debits a weapon. The physical runtime uses
        the returned exact launch, calls ``validate_trigger`` at its final
        pre-commit boundary, and owns every subsequent burst edge itself.
        """
        if now is None:
            now = self.now
        self.now = float(now)
        if not self._live() or state is not self.state:
            return dict(status='rejected', reason='auto_owner_changed')
        if self.trigger_active():
            return dict(status='rejected', reason='auto_tail_not_admissible')
        try:
            from .. import bot_fittings
            context = self.prepare_trigger_context(
                state, target, ballistic_solution, launch_receipt)
            if context is None:
                return dict(status='pending', reason='auto_policy_pending')
            entity, gun = self.source_entity(), self.gun
            if entity is None:
                return dict(status='pending', reason='auto_source_unavailable')
            context.update(automatic=True, generation=self.control_generation,
                           shell_index=gun.shot_index)
            sequence = int(state.get('fire_seq', 0)) + 1
            if launch_receipt is not None and (
                    launch_receipt.get('fire_seq') != sequence or
                    launch_receipt.get('shell_index') != gun.shot_index):
                return dict(status='pending', reason='auto_artillery_launch_changed')
            source_shot = bot_fittings.project_shot(
                self.source_descriptor(), gun.shots[gun.shot_index], state.get('critical'))
            raw_ray = self.mutable_shot_ray()
            verdict = self._admission().prepare(
                context, entity, gun, raw_ray, self.native_dispersion_angle(),
                source_shot, self.now, range_origin=state['position'],
                artillery_launch=launch_receipt)
            if verdict['status'] != 'ready':
                return verdict
            token = verdict['token']
            scatter = (gun.last_scatter if launch_receipt is None else
                (launch_receipt['fire_seq'], launch_receipt['shot_yaw'],
                 launch_receipt['shot_pitch']))
            if scatter is None or scatter[0] != sequence:
                return dict(status='pending', reason='auto_scatter_unavailable')
            proof = token['proof']
            proposal = dict(verdict, context=context, entity=entity, gun=gun,
                source_shot=source_shot, shell_index=gun.shot_index,
                fire_seq=sequence, shot_yaw=scatter[1], shot_pitch=scatter[2],
                gravity=proof['gravity'], max_distance=proof['maximum'],
                range_origin=proof['range_origin'],
                flight_time=proof['solution']['flight_time'],
                artillery_receipt=launch_receipt)
            # The native commit callback may run synchronously inside begin.
            # Stage the shared intention before that callback, without making
            # it a physical trigger or prematurely dropping its proof.
            self._trigger_context = context
            self._trigger_proposal = proposal
            return proposal
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError):
            return dict(status='pending', reason='auto_geometry_unavailable')

    def validate_trigger(self, proposal, now):
        if (proposal is not self._trigger_proposal or
                proposal.get('context') is not self._trigger_context):
            return 'auto_candidate_changed'
        state = self.state
        if (state is None or int(state.get('fire_seq', 0)) + 1 !=
                proposal.get('fire_seq')):
            return 'auto_sequence_changed'
        return self._admission().validate(proposal.get('token'),
            proposal['context'], proposal['entity'], proposal['gun'], now,
            launch=proposal)

    def trigger_started(self, proposal):
        """Mark an armed first edge; a real commit alone accepts the proof."""
        if proposal is not self._trigger_proposal:
            return False
        self._first_edge_pending = True
        return True

    def shot_committed(self, event, pending=None):
        """Feed real commit edges back to the policy without simulating them."""
        sequence = int(event.get('shot_seq', event.get('fire_seq', 0)))
        if sequence <= self._last_committed_shot_seq:
            return
        self._last_committed_shot_seq = sequence
        context = self._trigger_context or {}
        pending = pending or dict(player_control=context)
        self.attack_policy.shot_committed(event, pending)
        self._artillery_shot_committed(event, sequence)
        proposal = self._trigger_proposal
        if proposal is not None and sequence == proposal['fire_seq']:
            self._admission().committed(proposal['token'])
            self._trigger_proposal = None
            self._first_edge_pending = False
        final = int(event.get('burst_index', 0)) + 1 >= int(event.get('burst_count', 1))
        if final:
            self._first_edge_pending = False
            gun = self.gun
            if gun.clip == 0 and gun.reload_time > 0.:
                ammo = self._native_ammo()
                queued = self._queued_shell
                if queued is None and ammo.remaining[ammo.loaded] <= 0:
                    # The actual ammunition owner has already selected its
                    # stocked fallback at the final debit. Promote that
                    # input at the same full-load edge, not a later ready tick.
                    queued = int(ammo.next)
                if queued is not None and 0 <= queued < len(ammo.remaining) and ammo.remaining[queued] > 0:
                    # The shot receipt still belongs to the consumed type.
                    # Prepare promotes the plan when the full load completes.
                    ammo.stage(queued, False)
                self._queued_shell = None
                plan = context.get('load_plan')
                lease = self._owned_next_shell
                if (plan is None and lease is not None and lease['gun'] is gun and
                        lease['index'] == gun.shot_index):
                    plan = lease.get('plan')
                self.attack_policy.load_started(gun.shot_index, plan)
            self._trigger_context = None
        self._publish_weapon()

    def fire_rejected(self, reason, *unused):
        self._last_fire_failure = str(reason)
        self._first_edge_pending = False
        proposal = self._trigger_proposal
        if proposal is not None and self._last_committed_shot_seq < proposal['fire_seq']:
            self._trigger_proposal = None
            self._trigger_context = None
            admission = self._admission()
            if admission.terminal_reason(reason):
                admission.rejected(reason)
            else:
                # Retain the unconsumed native draw for a later attempt.
                admission.deferred(reason)

    def close(self):
        if self.closed:
            return
        self._release_next_shell('control_released', required=False)
        self._cancel_mission('control_released')
        self.active, self.closed = False, True
        self.control_generation += 1
        self.attack_policy.reset()
        self.combat_stop.reset()
        self.siege_aim.reset()
        selection = getattr(self, 'artillery_selection', None)
        if selection is not None:
            selection.reset()
        self._targets = ()
        # Physical trigger tails remain in the native worker; retiring a
        # controller is not a new terminal gun reason.

    def status(self):
        return dict(actor_kind='bot', actor_id=self.actor_id, active=self._live(),
            availability=self._availability, attack=self.attack_policy.status(),
            combat_stop=dict(self.combat_stop.receipt),
            shell=dict(self._shell_receipt or {}),
            navigation=dict(self._last_navigation), mission=self.mission_status())
