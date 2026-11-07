# -*- coding: utf-8 -*-
"""Complete copied decision loop bound to one foreground vehicle.

The copied planner owns decisions, not a second vehicle simulation. Observed
roster rows are private snapshots; the native foreground battle remains the
only owner of pose, gun clocks, ammunition, criticals and physical projectiles.
No message returned by the copied worker loop is published as Bot authority.
"""
from __future__ import print_function

import copy
import json
import math
import time

from .. import equipment_mechanics
from .. import shot_geometry
from .. import siege_mechanics
from .attack_policy import AttackPolicy, _planning_pose, native_source_pose
from .copied import bot_runtime as copied_runtime
from .copied import spg_positions
from .copied import bot_tactics
from .copied import capture_orders
from .copied.ai import driver as copied_driver
from .copied.ai import traffic as copied_traffic
from .copied.artillery_controller import ArtilleryController
from .copied.battle_geometry import CopiedBattleGeometry
from .copied.server_bot_ai import BotPlanner
from .native_aim import NATIVE_ANGLE_TOLERANCE
from .settling import HaltObservation


# The original LAN authority builds full-roster strategic orders every 30
# ticks at 30 Hz. Foreground tactical input and native safety proofs continue
# every physical frame; only the complete roster assignment has this cadence.
STRATEGY_SECONDS = 1.0
MECHANICAL_STALL_SECONDS = 6.0
PLAYER_PROFILE_SECONDS = 30.0
PLAYER_PROFILE_STAGES = (
    'player_observe', 'player_attack', 'player_strategy', 'player_traffic',
    'player_copied', 'player_refresh', 'player_post')
_PROFILE_CLOCK = getattr(time, 'perf_counter', None)
if _PROFILE_CLOCK is None:
    _PROFILE_CLOCK = time.clock

try:
    _INTEGER_TYPES = (int, long)
except NameError:
    _INTEGER_TYPES = (int,)


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


def _plain_order(order):
    """Keep the journal bounded; full plans stay in their copied owners."""
    names = ('id', 'combat_mode', 'recovery_mode', 'target_id', 'target_kind',
             'route_id', 'route_index', 'move_position', 'face_position',
             'aim_position', 'throttle', 'turn', 'brake', 'fire_allowed',
             'shell_index', 'movement_intent', 'path_clear', 'confirmed_facing',
             'capture_pivot_circle', 'team_command', 'team_command_id')
    return dict((name, order[name]) for name in names if name in order)


def _player_bootstrap_actor(record, actor_id, descriptor, position, yaw, entity):
    """Create a new private Bot actor, never restore a human wire snapshot.

    The live player row is not a Bot authority manifest. In particular the
    server's public player row contains next_shell_index without the Bot's
    ammunition inventory/reload checkpoint, and its equipment slots are not
    the Bot's fixed three-slot contract. Those and all other native systems
    are observed after the copied decision loop is constructed. Only the
    required identity, spawn and native hull facts enter this bootstrap.
    """
    human = record.get('state') or {}
    vehicle = (record.get('vehicle') or human.get('vehicle') or
               getattr(getattr(descriptor, 'type', None), 'name', None))
    if not vehicle:
        raise RuntimeError('native_vehicle_name_unavailable')
    return dict(id=actor_id, team=int(record.get('team', human.get('team', 0))),
        slot=int(human.get('slot', record.get('slot', 0))),
        name=human.get('name', record.get('name', 'Player')),
        vehicle=vehicle, x=position[0], y=position[1], z=position[2],
        yaw=yaw, health=int(getattr(entity, 'health', human.get('health', 0))),
        max_health=int(getattr(descriptor, 'maxHealth',
                               human.get('max_health', 1))),
        alive=bool(entity.isAlive()))


class _GunObservation(object):
    """Read through the real gun, never advance its reload/burst twice."""
    def __init__(self, runtime):
        self.runtime = runtime

    @property
    def gun(self):
        return self.runtime.gun

    @property
    def dispersion(self):
        return float(self.runtime.owner._native_dispersion_angle())

    @property
    def fully_aimed_dispersion(self):
        return float(self.gun.base_dispersion)

    @property
    def current_dispersion_factor(self):
        return self.dispersion / self.fully_aimed_dispersion

    @property
    def reload_kind(self):
        return 'intra' if self.gun.clip_size > 1 and self.gun.clip > 0 else 'full'

    @property
    def reload_full(self):
        return self.gun.reload

    @property
    def reload_intra(self):
        return self.gun.clip_reload

    @property
    def elapsed(self):
        return max(0., self.gun.reload_duration - self.gun.reload_time)

    @property
    def clip(self):
        return int(self.gun.clip)

    @clip.setter
    def clip(self, value):
        if int(value) != int(self.gun.clip):
            raise RuntimeError('copied_loop_attempted_native_clip_write')

    @property
    def clip_size(self):
        return int(self.gun.clip_size)

    @property
    def shell_count(self):
        return len(self.gun.shots)

    @property
    def _burst_remaining(self):
        return int(self.gun._burst_remaining)

    @property
    def loadout(self):
        return self.gun.loadout

    @property
    def burst_count(self):
        return self.gun.burst_count

    @property
    def burst_interval(self):
        return self.gun.burst_interval

    def ready(self, unused_factor=1.):
        return bool(self.gun.can_fire())

    def remaining(self, unused_factor=1.):
        return float(self.gun.reload_time)

    def duration(self, unused_factor=1.):
        return float(self.gun.reload_duration)

    def shell_index(self, index):
        return max(0, min(int(index), len(self.gun.shots) - 1))

    def tick(self, unused_step):
        return None

    def tick_dispersion(self, *unused_args, **unused_kwargs):
        return None

    def rescale_reload(self, unused_factor):
        return None

    def complete_reload(self, *unused_args):
        return None


class _AmmoObservation(object):
    def __init__(self, runtime):
        self.runtime = runtime
        # The canonical foreground input path owns the intuition roll too.
        self.plan_pending = True

    @property
    def remaining(self):
        return list(self.runtime.gun.ammo)

    @property
    def loaded(self):
        return int(self.runtime.gun.shot_index)

    @property
    def next(self):
        pending = self.runtime.gun.pending_index
        return self.loaded if pending is None else int(pending)

    @property
    def reload_pending(self):
        # NEXT is only a future selection. A ready current magazine remains
        # usable while another shell is queued; conversely reloading the same
        # shell is still a real physical lock even though both indices match.
        gun = self.runtime.gun
        return (float(gun.reload_time) > 0. or int(gun._burst_remaining) > 0 or
                getattr(self.runtime.owner, '_local_player_burst', None) is not None)

    def stage(self, index, completed=False, full=False):
        # Selection is an input intention. Only the foreground gun can settle
        # it, and the new attack policy decides when abandoning a load is legal.
        self.runtime._requested_shell = int(index)
        return self.loaded

    def planned_rounds(self):
        return self.remaining[self.next]

    def can_fire(self, continuation=False):
        return (self.remaining[self.loaded] > 0 and int(self.runtime.gun.clip) > 0 and
                (continuation or not self.reload_pending))

    def publish(self, state):
        state.update(shell_index=self.loaded, next_shell_index=self.next,
                     ammo_remaining=self.remaining,
                     ammo_empty=not any(self.remaining),
                     ammo_reload_pending=self.reload_pending)

    def consume_loaded(self):
        raise RuntimeError('copied_loop_attempted_native_ammunition_debit')


class _TriggerObservation(object):
    """A view of the real physical group; it cannot own or cancel an edge."""
    def __init__(self, runtime):
        self.runtime = runtime

    @property
    def active(self):
        return getattr(self.runtime.owner, '_local_player_burst', None) is not None

    @property
    def time_left(self):
        value = getattr(self.runtime.owner, '_local_player_burst', None) or {}
        clock = value.get('clock') or value.get('trigger')
        return float(getattr(clock, 'time_left', 0.))

    def publish(self, state):
        value = getattr(self.runtime.owner, '_local_player_burst', None) or {}
        clock = value.get('clock') or value.get('trigger')
        if clock is not None:
            # This is a private observation, not a wire checkpoint. A native
            # catch-up callback can expose the committed second shell while
            # another shell is already overdue. TriggerClock.publish correctly
            # refuses such a mid-drain wire snapshot; observing its real
            # frontier must neither publish nor terminate the controller.
            state.update(burst_active=bool(clock.active),
                         burst_group_seq=int(clock.group_seq),
                         burst_count=int(clock.count),
                         burst_next_index=int(clock.next_index),
                         burst_interval=float(clock.interval),
                         burst_time_left=float(clock.time_left),
                         burst_shell_index=int(clock.shell_index))
        else:
            state.update(burst_active=bool(value),
                         burst_group_seq=int(value.get('group_seq', 0)),
                         burst_count=int(value.get('count', 0)),
                         burst_next_index=int(value.get('committed', 0)),
                         burst_time_left=0.)


class _EquipmentObservation(equipment_mechanics.EquipmentState):
    """Run the unchanged kit policy on a detached canonical checkpoint."""
    def __init__(self, runtime, equipment):
        self.runtime = runtime
        self.original = equipment
        for name in equipment_mechanics.EquipmentState.__slots__:
            setattr(self, name, getattr(equipment, name))

    @property
    def view(self):
        return self

    def sync(self):
        for name in ('uses_left', 'active'):
            setattr(self, name, getattr(self.original, name))
        clock = getattr(self.runtime.owner, '_clock', None)
        native_now = float(clock() if callable(clock) else self.runtime.now)
        self.ready_at = self.runtime.engine._equipment_now + max(
            0., float(self.original.ready_at) - native_now)
        pending = self.runtime._equipment_pending.get(int(self.contract['id']))
        if pending is not None and pending.get('action') == 'set_rpm_limiter':
            # A submitted on/off intent can precede the canonical snapshot.
            # Keep only this observation of our request so that the unchanged
            # governor policy can issue the opposite intent without waiting
            # for an obsolete echo. It never changes the native equipment.
            self.active = bool(pending['active'])

    def _result(self, effect):
        if effect is not None:
            effect = dict(effect)
            effect['_player_equipment_id'] = int(self.view.contract['id'])
        return effect

    def activate(self, *args, **kwargs):
        if (not self.runtime.active or
                self.runtime._equipment_signature() != self.runtime._equipment_snapshot):
            return None
        if (self.contract['kind'] == 'rpm_limiter' and self.original.active and
                self.runtime._owned_governor != int(self.contract['id'])):
            # Manual input owns this toggle. Observing it is not adopting its
            # lifecycle; even the detached policy ledger must stay active.
            self.active = True
            return None
        return self._result(equipment_mechanics.EquipmentState.activate(self, *args, **kwargs))

    def poll_bot(self, *args, **kwargs):
        return self._result(equipment_mechanics.EquipmentState.poll_bot(self, *args, **kwargs))


class _NativeAimInput(object):
    """Bind movement input and separately certify the native gun source."""
    def __init__(self, runtime):
        self.runtime = runtime
        self.saved = None
        self.bound_source = None
        self.point = self.source_point = self.target = self.solution = None
        self.motion_point = None
        self.verified = False
        self._release = None

    def shot_point(self):
        point = self.source_point or self.motion_point
        return self.runtime.owner._vector(point) if point is not None else None

    def owned(self):
        if self.saved is None or self.bound_source is None or self._release is None:
            return False
        rotator = self.runtime.owner._avatar.gunRotator
        return (self.saved[0] is rotator and not self._release.get('releasing') and
                getattr(rotator, '_VehicleGunRotator__shotPointSourceFunctor', None) is self.bound_source and
                bool(rotator.clientMode))

    def bind(self):
        if self.saved is not None:
            return self.owned()
        runtime, battle = self.runtime, self.runtime.owner
        generation = runtime.generation
        rotator = battle._avatar.gunRotator
        source = getattr(rotator, '_VehicleGunRotator__shotPointSourceFunctor', None)
        saved = (rotator, source, bool(rotator.clientMode))
        origin, direction = battle._mutable_shot_ray()
        origin, direction = _point(origin), _point(direction)
        self.point = tuple(origin[index] + 100. * direction[index] for index in range(3))
        self.motion_point = self.point
        bound = self.shot_point
        lease = dict(mode_touched=False, releasing=False)
        self.saved, self.bound_source, self._release = saved, bound, lease
        battle._avatar.autoAim(None)
        if not runtime.active or runtime.generation != generation:
            self._release_lease(saved, bound, lease)
            return False
        rotator.shotPointSourceFunctor = bound
        if not runtime.active or runtime.generation != generation:
            self._release_lease(saved, bound, lease)
            return False
        lease['mode_touched'] = True
        rotator.clientMode = True
        if not runtime.active or runtime.generation != generation:
            self._release_lease(saved, bound, lease)
            return False
        return True

    def close(self):
        if self.saved is None:
            return
        self._release_lease(self.saved, self.bound_source, self._release)

    def _release_lease(self, saved, bound, lease):
        if lease.get('releasing'):
            return
        if self._release is not None and self._release is not lease:
            return
        # A setter can call Stop before committing its own side effect. The
        # captured install lease, not just self.saved, remains the authority
        # to undo that exact delayed write after the setter returns.
        self.saved, self.bound_source, self._release = saved, bound, lease
        rotator, saved_source, saved_mode = saved
        lease['releasing'] = True
        try:
            current = getattr(rotator, '_VehicleGunRotator__shotPointSourceFunctor', None)
            if current is bound:
                rotator.shotPointSourceFunctor = saved_source
                current = getattr(rotator, '_VehicleGunRotator__shotPointSourceFunctor', None)
            # Source and mode restoration are separate obligations. If mode
            # restoration raises, keep the lease for the next release retry
            # even though the source has already been restored successfully.
            if current is saved_source and lease['mode_touched'] and bool(rotator.clientMode) != saved_mode:
                rotator.clientMode = saved_mode
        finally:
            lease['releasing'] = False
        if self._release is lease:
            self.saved = self.bound_source = self._release = None
            self.source_point = self.point = self.target = self.solution = None
            self.motion_point = None
            self.verified = False

    def aim(self, state, target, command, intention):
        runtime = self.runtime
        token, bound = runtime.generation, self.bound_source
        if not runtime._live(token) or not self.owned():
            return False
        self.target = target
        self.solution = (command.get('_ballistic_solution') or
            (runtime.attack_policy.decision.get('candidate') or {}).get('solution'))
        solution = command.get('_ballistic_solution') or {}
        point = solution.get('point', command.get('aim_position'))
        self.point = _point(point) if point is not None else None
        # A previous target's accepted inverse is never input for this point.
        self.source_point = self.motion_point = None
        self.verified = False
        resting = target is None and intention.get('owner') == 'hull_forward_rest'
        if (target is None and not resting) or (self.point is None and not resting):
            return False
        battle = runtime.owner
        getter = getattr(battle._runtime, 'get_shot_angles', None)
        if not callable(getter):
            return False
        desired = (intention.get('turret_yaw'), intention.get('gun_pitch'))
        if None in desired:
            return False
        descriptor = runtime.entity.typeDescriptor
        # Copied artillery fire admission intentionally requires an exact
        # world-ballistic barrel (1e-7). Letting its native source settle at
        # ordinary float32 tolerance would deadlock that unchanged proof.
        # Ordinary tanks use the observed #1513 native-angle precision.
        type_tags = getattr(getattr(descriptor, 'type', None), 'tags', ()) or ()
        tolerance = 1.e-7 if 'SPG' in type_tags else NATIVE_ANGLE_TOLERANCE
        stabilised = getattr(battle, '_local_stabilised_pose', battle._local_body_pose)
        body = battle._runtime.math.Matrix(stabilised())
        basis = float(body.yaw), float(body.pitch), float(body.roll)
        rotator = battle._avatar.gunRotator
        current = (float(rotator.turretYaw), float(rotator.gunPitch))
        origin = _point(battle._mutable_shot_ray()[0])
        local = [float(desired[0]), float(desired[1])]
        source = self.point
        shot_speed = float(_field(runtime.gun.shots[runtime.gun.shot_index], 'speed'))
        distance = min(100., max(5., shot_speed * .12))
        if resting:
            # Rest is the copied gun law's real local intention, not a ground
            # route waypoint or the last enemy's fixed world point. Bind its
            # current chassis-relative direction through the same native
            # point solver, while keeping fire alignment false below.
            direction = (math.sin(local[0]) * math.cos(local[1]),
                         -math.sin(local[1]), math.cos(local[0]) * math.cos(local[1]))
            world = shot_geometry.transform_vehicle_vector(direction, *basis)
            source = tuple(origin[index] + world[index] * distance for index in range(3))
            self.point, self.solution = source, None
        best_error = float('inf')
        for attempt in range(6):
            try:
                actual_yaw, actual_pitch = getter(descriptor, body, current, battle._vector(source))
                dy = _angle(desired[0] - float(actual_yaw))
                dp = float(desired[1]) - float(actual_pitch)
            except (AttributeError, TypeError, ValueError, RuntimeError, ArithmeticError):
                return False
            if (not runtime._live(token) or self.bound_source is not bound or
                    not self.owned()):
                return False
            if any(math.isnan(error) or math.isinf(error) for error in (dy, dp)):
                return False
            error = max(abs(dy), abs(dp))
            if error < best_error:
                self.motion_point = tuple(source)
                best_error = error
            if error <= tolerance:
                self.source_point, self.verified = tuple(source), True
                return True
            if attempt:
                local[0] = _angle(local[0] + dy)
                local[1] += dp
            direction = (math.sin(local[0]) * math.cos(local[1]),
                         -math.sin(local[1]), math.cos(local[0]) * math.cos(local[1]))
            world = shot_geometry.transform_vehicle_vector(direction, *basis)
            source = tuple(origin[index] + world[index] * distance for index in range(3))
        # The best fresh source may move the gun. It cannot approve a shot.
        return False


class _ForegroundGeometry(CopiedBattleGeometry):
    """Copied geometry with local record aliases and independent AI caches."""
    # These are native observation objects, not behavior-method delegation.
    OBSERVATIONS = frozenset((
        '_runtime', '_avatar', '_config', '_remote_factory', '_destructibles',
        '_foliage', '_detached_turret_obstacles', '_local_matrix',
        '_local_pose_matrix', '_local_position', '_last_frame_time',
        '_local_pitch', '_local_roll', '_start_message',
        '_projectile_server_time_ms', '_projectile_server_local_time',
        '_arena_bounds', '_spawn_planner', '_navigation_graph',
        '_physics_params', '_stack_context', '_stack_probe_times',
        '_stack_probe_log_at', '_local_effective_params', '_local_hull_dimensions',
        '_world_collision', '_world_geometry', '_space_id'))

    def __init__(self, runtime):
        self.player_runtime = runtime
        self._records = {}
        self._records_revision = 0
        self._bots = None
        self._worker_mode = False
        self._sight_filter = None
        self._sight_filter_built_at = -1.
        self._disabled_optional_features = set()
        self._optional_failures_reported = set()
        self._bot_lane_wreck_rows_cache = None
        self._bot_motion_kinds = {}
        self._bot_tree_contacts_pending = {}
        self._combat_diagnostics = None
        self._local_motion_kinds = []
        self._local_motion_status = None
        self._local_tree_diagnostic_error = None
        self._local_tree_diagnostics = []
        self._local_world_collision_trace = None
        self._soft_static_recast_budget = 0
        self._artillery = ArtilleryController(
            origin_resolver=self._bot_artillery_planning_origin,
            aim_samples_resolver=self._bot_artillery_aim_samples)

    def __getattr__(self, name):
        if name in self.OBSERVATIONS:
            return getattr(self.player_runtime.owner, name)
        raise AttributeError(name)

    def sync(self, records):
        previous = self._records
        current = {}
        for key, raw in records.items():
            old = previous.get(key)
            if old is not None and old.get('engine_id') == raw.get('engine_id'):
                old.update(raw)
                record = old
            else:
                record = dict(raw)
            current[key] = record
        self._records = current
        self._records_revision += 1

    def _server_entity(self, entity_id):
        return self.player_runtime.owner._server_entity(entity_id)

    def _bot_direct_launch_origin(self, source, descriptor, shell_index,
                                  fire_seq, yaw, pitch, flight_time=0.):
        if int(source.get('id', 0)) == self.player_runtime.actor_id:
            return _point(self.player_runtime.owner._mutable_shot_ray()[0])
        return CopiedBattleGeometry._bot_direct_launch_origin(
            self, source, descriptor, shell_index, fire_seq, yaw, pitch, flight_time)


class _PlayerBehaviorEngine(copied_runtime.BotRuntime):
    """Override ownership boundaries; execute the complete copied algorithm."""
    def __init__(self, runtime, **kwargs):
        self.player_runtime = runtime
        copied_runtime.BotRuntime.__init__(self, runtime.actor_id, **kwargs)

    def controlled_states(self):
        state = self.states.get(self.player_runtime.actor_id)
        return (state,) if state is not None else ()

    def _ordered_states(self):
        # SPG reservations, radio/lanes and cohort placement use this roster.
        # Only controlled_states() limits actual actor execution. Peer rows
        # remain private observations; the returned worker wire is never sent.
        return copied_runtime.BotRuntime._ordered_states(self)

    def spg_roster_states(self):
        rows = list(self._ordered_states())
        known = set(row['id'] for row in rows)
        for public in self.player_runtime._public_roster():
            if public['kind'] == 'bot' and public['network_id'] not in known:
                # This approved I/O seam is consumed only by SPG membership
                # and deployment counts, never a spatial query or actuator.
                rows.append(dict(public, id=public['network_id']))
        return rows

    def _ensure_native_simulation(self):
        return None

    def _bounded_burst_step(self, maximum):
        # The physical foreground scheduler already advances these edges.
        # Subdividing against its unadvanced read-only clock would spin at 1ns.
        return max(0., float(maximum))

    def _advance_active_burst(self, *unused_args, **unused_kwargs):
        return 0

    def _terminate_active_trigger(self, *unused_args, **unused_kwargs):
        return False

    def _advance_bot_critical(self, state, step, now, record_step=True,
                              advance_fire=True, equipment_effects=None):
        copied_runtime._clear_critical_parts_tick_cache(state)
        state['_factor_consumables'] = self._factor_consumables(state['id'])
        if record_step and 'consumables' in self.player_runtime.features:
            self._poll_bot_equipments(state, self._descriptors[state['id']])
        return False

    def _apply_bot_equipment_effect(self, state, descriptor, effect, strict=True):
        return self.player_runtime._equipment_request(effect, descriptor)

    def _advance_bot_drowning(self, *unused_args, **unused_kwargs):
        return False

    def _advance_bot_overturn(self, *unused_args, **unused_kwargs):
        return False

    def _advance_bot_siege(self, state, step):
        return int(state.get('siege_state', 0)) in (
            siege_mechanics.SWITCHING_ON, siege_mechanics.SWITCHING_OFF)

    def _update_bot_siege_intent(self, state, command, target, step):
        contact = command.pop('_player_siege_contact', None)
        target = target if target is not None else contact
        if self._advance_bot_siege(state, step):
            # The native request owns the transition until a stable echo.
            # The copied bot's reversal needs its own simulated countdown,
            # which the foreground actor never starts or advances.
            command['fire_allowed'] = False
            state['_siege_intent'] = self._siege_desired(state, command, target)
            state['_siege_intent_elapsed'] = 0.0
            return True
        return copied_runtime.BotRuntime._update_bot_siege_intent(
            self, state, command, target, step)

    @staticmethod
    def _siege_desired(state, command, target):
        # The adapter carries the effective travel destination alongside the
        # local point it can drive to now. Pending paths and short corners
        # can both be close to the hull while long travel still owns motion.
        destination = (command.get('control_trace') or {}).get('strategic_move_position')
        if destination is not None:
            command = dict(command, move_position=destination)
        return copied_runtime.BotRuntime._siege_desired(state, command, target)

    def _set_bot_siege_state(self, state, siege_state, duration=0., transition_total=None):
        desired = int(siege_state) in (siege_mechanics.ENABLED, siege_mechanics.SWITCHING_ON)
        if int(siege_state) == int(state.get('siege_state', 0)):
            return False
        return self.player_runtime._siege_request(desired)

    def _update_vertical_motion(self, state, *unused_args, **unused_kwargs):
        return bool(state.get('_foreground_support_blocked', False))

    def _guard_realised_pose(self, *unused_args, **unused_kwargs):
        return False

    def _update_slope_pose(self, *unused_args, **unused_kwargs):
        return False

    def _resolve_tank_contacts(self, *unused_args, **unused_kwargs):
        return []

    def _update_hydraulic_suspension(self, state, descriptor, world_yaw,
                                    world_pitch, elapsed, motion_probe=None):
        # The native foreground actuator consumes track_world and owns the
        # hydraulic body matrix. A second predicted pitch here would aim
        # through a pose that the real barrel has not reached yet.
        owner = self.player_runtime.owner
        stabilised = getattr(owner, '_local_stabilised_pose', owner._local_body_pose)
        body = owner._runtime.math.Matrix(stabilised())
        correction = float(getattr(owner, '_local_siege_aim_pitch', 0.))
        state['terrain_pitch'] = float(getattr(owner, '_local_terrain_pitch', body.pitch))
        state['suspension_pitch'] = correction
        state['pitch'], state['roll'] = float(body.pitch), float(body.roll)
        return correction

    def _contacts_for(self, source, players, now, team_spotted=None,
                      visibility_tick=None, processed_bot_ids=None):
        contacts = []
        for observed in self.player_runtime.visible_targets():
            target = dict(observed)
            contacts.append(target)
            key = (source['team'], target['kind'], target['network_id'])
            self._visible_target_poses[key] = dict(target)
            self._renew_team_spot(key, now)
            if team_spotted is not None:
                team_spotted[key] = True
        return contacts, dict((target['id'], target) for target in contacts)

    def _aimed_target(self, state, target, now):
        runtime = self.player_runtime
        if ('fire' in runtime.features and runtime.attack_policy is not None and
                (state.get('profile') or {}).get('class_tag') != 'SPG'):
            # The new point/penetration policy owns direct-fire aim. Reapplying
            # the old Bot-tier's periodic aim bias here creates a second,
            # different target that a zero-traverse hull can never satisfy
            # simultaneously. Artillery retains the complete copied owner.
            return target
        return copied_runtime.BotRuntime._aimed_target(self, state, target, now)

    def _cadenced_ballistic_solution(self, state, target, descriptor,
                                     shell_index, now, force=False):
        if (state.get('profile') or {}).get('class_tag') != 'SPG':
            runtime = self.player_runtime
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
                    signature, now + copied_runtime.LOCAL_ACTION_SECONDS, solution)
                return solution, True
            if 'fire' in runtime.features:
                self._ballistic_solution_cache.pop(state['id'], None)
                return None, False
            return copied_runtime.BotRuntime._cadenced_ballistic_solution(
                self, state, target, descriptor, shell_index, now, force)
        # The native rotator consumes an installed source asynchronously. A
        # newly solved point cannot replace its own unconsumed proposal every
        # frame, otherwise a moving contact can never meet the copied 1e-7
        # physical alignment gate. This is an input lease, never launch proof:
        # the original exact-arc and target-motion reproof remain mandatory.
        signature = self._ballistic_solution_signature(state, target, descriptor, shell_index)
        reproof = self._artillery_reproofs.get(state['id']) or {}
        proof_epoch = (reproof.get('created'), reproof.get('attempts', 0))
        pose = self._artillery_source_pose(state)[:6]
        proposal = getattr(self, '_native_artillery_proposal', None)
        intent = self._active_artillery_intent(state, target, descriptor, shell_index, now)
        if intent is not None:
            self._native_artillery_proposal = None
            return copied_runtime.BotRuntime._cadenced_ballistic_solution(
                self, state, target, descriptor, shell_index, now, True)
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
                    signature, now + copied_runtime.LOCAL_ACTION_SECONDS, solution)
                return solution, True
            self._native_artillery_proposal = None
        solution, fresh = copied_runtime.BotRuntime._cadenced_ballistic_solution(
            self, state, target, descriptor, shell_index, now, True)
        if isinstance(solution, dict) and target is not None:
            self._native_artillery_proposal = dict(signature=signature, pose=pose,
                proof_epoch=proof_epoch, solution=dict(solution),
                until=now + copied_runtime.ARTILLERY_INTENT_SECONDS)
        return solution, fresh

    def _direct_aim_matches(self, state, target, solution):
        candidate = self.player_runtime.current_attack_candidate(state, target)
        if candidate is not None:
            selected = candidate['solution']
            matches = bool(isinstance(solution, dict) and
                solution.get('_aim_token') == selected.get('_aim_token') and
                solution.get('aim_position') == selected.get('aim_position') and
                solution.get('_origin') == selected.get('origin'))
            if not matches:
                self._ballistic_solution_cache.pop(int(state['id']), None)
            return matches
        if 'fire' in self.player_runtime.features:
            return False
        return copied_runtime.BotRuntime._direct_aim_matches(self, state, target, solution)

    def _apply_blocked_direct_aim(self, source, command, target, now, probe_budget=None):
        command, target = copied_runtime.BotRuntime._apply_blocked_direct_aim(
            self, source, command, target, now, probe_budget)
        if 'fire' not in self.player_runtime.features:
            return command, target
        policy = self.player_runtime.attack_policy
        command, target = policy.select_command(source, command, target, now)
        if self.player_runtime._mission_brakes():
            # Arrival settling/terminal commands own the input boundary. They
            # cannot donate the hull actuator back to an otherwise valid gun
            # target later in the copied loop.
            return dict(command, fire_allowed=False), None
        if policy.decision['action'] == 'unchanged':
            return command, target
        candidate = self.player_runtime.current_attack_candidate(source, target, for_aim=True)
        if candidate is None:
            # Strategic contacts may steer navigation, but cannot publish a
            # second direct aim point while the player policy awaits proof.
            # The copied mode switch uses that contact before the gun can lay.
            return dict(command, fire_allowed=False, aim_position=None,
                        _player_siege_contact=target), None
        context = self.player_runtime.geometry._bot_aim_context(source, target)
        sample = candidate['solution'].get('sample_value')
        if context is not None and sample is not None:
            context[2]['selected'] = sample
        return command, target

    def _shot_clear(self, source, target, now, force=False,
                    probe_budget=None, lane_key=None, distance_cache=None):
        runtime = self.player_runtime
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
        return copied_runtime.BotRuntime._shot_clear(
            self, source, target, now, force, probe_budget, lane_key, distance_cache)

    def _log_motion_stall(self, state, command, throttle, turn, path_clear,
                          motion_probe, now, pose_frozen=False,
                          traffic_input=None, traffic_output=None):
        copied_runtime.BotRuntime._log_motion_stall(
            self, state, command, throttle, turn, path_clear, motion_probe, now,
            pose_frozen, traffic_input, traffic_output)
        self.player_runtime._accept_controls(
            command, throttle, turn, path_clear, motion_probe, now)

    def _update_gun_aim(self, state, command, target, step, weapon_tick=None):
        # Retain the full copied law and every recovery/intention transition.
        # Only its actuator's predicted angles are replaced by native feedback.
        shadow = dict(state)
        result = copied_runtime.BotRuntime._update_gun_aim(
            self, shadow, command, target, step, weapon_tick)
        for key, value in shadow.items():
            if key.startswith('_') or key in ('desired_gun_pitch', 'hull_aiming'):
                state[key] = value
        intention = shadow.get('_diagnostic_aim_intent') or {}
        runtime = self.player_runtime
        tail_active = getattr(runtime.owner, '_local_player_burst', None) is not None
        if 'fire' in runtime.features and runtime.active and not tail_active:
            runtime.weapon.aim(state, target, command, intention)
        rotator = runtime.owner._avatar.gunRotator
        state['turret_yaw'] = float(rotator.turretYaw)
        state['gun_pitch'] = float(rotator.gunPitch)
        state['aim_yaw'] = _angle(state['yaw'] + state['turret_yaw'])
        desired_yaw, desired_pitch = intention.get('turret_yaw'), intention.get('gun_pitch')
        state['gun_aligned'] = bool(not tail_active and target is not None and runtime.weapon.verified and
            desired_yaw is not None and desired_pitch is not None and
            abs(_angle(state['turret_yaw'] - desired_yaw)) <= NATIVE_ANGLE_TOLERANCE and
            abs(state['gun_pitch'] - desired_pitch) <= NATIVE_ANGLE_TOLERANCE)
        runtime._observe_attack_lay(state, target, intention, self.player_runtime.now)
        return result

    def _direct_launch_preview(self, state, descriptor, shell_index, gun_state,
                               ballistic_solution, burst_edge=None):
        # This is an advisory current barrel only. TriggerAdmission checks the
        # exact frozen native scattered ray at first-edge commit.
        runtime = self.player_runtime
        origin, direction = runtime.owner._mutable_shot_ray()
        origin, direction = _point(origin), _point(direction)
        shot = runtime.gun.shots[int(shell_index)]
        speed = float(_field(shot, 'speed'))
        velocity = tuple(value * speed for value in direction)
        return dict(origin=origin, velocity=velocity, shot_yaw=math.atan2(direction[0], direction[2]),
                    shot_pitch=math.asin(max(-1., min(1., direction[1]))),
                    gravity=abs(float(_field(shot, 'gravity'))),
                    max_distance=float(_field(shot, 'maxDistance')),
                    flight_time=(ballistic_solution or {}).get('flight_time', 0.),
                    shell_index=int(shell_index), fire_seq=int(state.get('fire_seq', 0)) + 1)

    def _fire(self, state, gun_state, reload_factor, descriptor,
              launch_receipt=None, ammo_state=None, launch_preview=None,
              launch_time_us=None):
        runtime = self.player_runtime
        if (not runtime._live() or runtime._mission_brakes() or
                'fire' not in runtime.features or not state.get('gun_aligned')):
            return False
        if runtime.controller is None:
            return False
        candidate = runtime.attack_policy.decision.get('candidate')
        solution = (candidate or {}).get('solution') or runtime.weapon.solution
        artillery = (state.get('profile') or {}).get('class_tag') == 'SPG'
        load_plan = None
        if not artillery:
            policy = runtime.attack_policy
            if policy.decision['action'] != 'aim' or candidate is None:
                return False
            token = runtime.generation
            load_plan = runtime._apply_next_shell(at_trigger=True)
            if not runtime._live(token):
                return False
            # Rebind the exact observed barrel at this edge. The ideal path
            # cache deliberately excludes lay, but admission still fences it.
            pose = native_source_pose(runtime)
            solution = candidate['solution']
            if _planning_pose(pose) == _planning_pose(solution['source_pose']):
                solution = dict(solution, source_pose=pose)
        if artillery and launch_receipt is not None:
            intent = self._artillery_intents.get(state['id']) or {}
            planned = intent.get('solution')
            if isinstance(planned, dict):
                target = runtime.weapon.target or {}
                speed, yaw = float(target.get('speed', 0.)), float(target.get('yaw', 0.))
                solution = dict(planned, point=tuple(planned['aim_position']),
                    velocity=target.get('velocity') or
                        (math.sin(yaw) * speed, 0., math.cos(yaw) * speed))
        context = dict(target=runtime.weapon.target, candidate=candidate,
                       solution=solution,
                       source_pose=runtime.pose_stamp(),
                       artillery=artillery,
                       load_plan=load_plan, load_epoch=runtime._manual_shell_epoch,
                       artillery_receipt=launch_receipt)
        accepted = runtime.controller.issue_automatic_trigger(context, runtime.now)
        runtime._sync_weapon_observation()
        return bool(accepted)


class FullPlayerRuntime(object):
    """One complete local planner and one native input owner per human tank."""
    def __init__(self, battle, controller=None):
        self.owner = self.battle = battle
        self.controller = controller
        self.engine = self.planner = self.geometry = self.attack_policy = None
        self.weapon = _NativeAimInput(self)
        self.navigation = self
        self.features = set()
        self.active = self.closed = False
        self.generation = 0
        self.actor_id = None
        self.entity = self.entity_id = None
        clock = getattr(battle, '_clock', None)
        self.now = float(clock() if callable(clock) else getattr(battle, '_last_frame_time', 0.))
        self._identity = None
        self._targets, self._players = (), ()
        self._observed_records = {}
        self._manifest = []
        self._last_order = {}
        self._last_navigation = {}
        self._last_fire_failure = None
        self._mission = None
        self._mission_sequence = 0
        self._move_episode = None
        self._move_retry = None
        self._requested_shell = None
        self._equipment_views = {}
        self._equipment_pending = {}
        self._owned_governor = None
        self._siege_pending = None
        self._recent_projectiles = {}
        self._damage_events = set()
        self._reload_retreat = None
        self._shell_intent = None
        self._owned_next_shell = None
        self._manual_shell_epoch = 0
        self._manual_shell = None
        self._loading_switch = None
        self._shell_receipt = None
        self._shell_log_at = float('-inf')
        self._attack_lay = None
        self._attack_log_key = None
        self._attack_log_at = float('-inf')
        self._equipment_snapshot = None
        self._traffic_observed = {}
        self._traffic_inputs = {}
        self._team_shooter_observations = {}
        self._native_hull_laying = None
        self._mission_halt = HaltObservation()
        self._implicit_retry = None
        self._implicit_failures = 0
        self._strategic_result = None
        self._strategic_due = 0.
        self._strategic_contact_signature = None
        self._last_committed_shot_seq = 0
        self._profile_window = None

    @property
    def gun(self):
        return self.owner._gun_state

    @property
    def state(self):
        return self.engine.states.get(self.actor_id) if self.engine is not None else None

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

    def current_attack_candidate(self, source, target, for_aim=False):
        policy = self.attack_policy
        if (policy is None or 'fire' not in self.features or not self._live() or
                source.get('id') != self.actor_id or not isinstance(target, dict) or
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
                row.get('line_stamp') != candidate.get('line_stamp') or
                (not for_aim and not policy._executable(row, mode)) or
                (for_aim and (not isinstance(row.get('solution'), dict) or
                    row.get('mechanical') not in ('reachable', 'hull_laying') or
                    row.get('line') != 'clear' and policy.decision['action'] != 'preaim'))):
            return None
        if policy.decision['action'] == 'firing_position' and (
                row.get('mechanical') != 'hull_laying' or
                self._last_navigation.get('owner') != 'copied_combat_hull_aim'):
            return None
        return row

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

    def target_entity(self, row):
        return self.owner._server_entity(row.get('engine_id'))

    def _public_roster(self):
        """Same-round identity facts are separate from spatial observations."""
        own_player = int(self.owner.client.player_id)
        roster = {}
        snapshots = (self.owner._start_message,
                     getattr(self.owner, '_last_snapshot', None) or
                     getattr(self.owner.client, 'last_snapshot', None) or {})
        fields = ('id', 'team', 'alive', 'health', 'max_health', 'name',
                  'vehicle', 'profile', 'class_tag', 'slot', 'participating')
        for snapshot in snapshots:
            if snapshot.get('round_id') != self.owner._start_message.get('round_id'):
                continue
            for name, kind in (('players', 'human'), ('bot_manifest', 'bot'), ('bots', 'bot')):
                for raw in snapshot.get(name) or ():
                    if not isinstance(raw, dict) or not raw.get('id'):
                        continue
                    identity = int(raw['id'])
                    if kind == 'human' and identity == own_player:
                        continue
                    key = kind, identity
                    row = roster.setdefault(key, dict(kind=kind, network_id=identity,
                                                      world_pose=False, visible=False))
                    row.update((key, copy.deepcopy(raw[key])) for key in fields if key in raw)
                    if 'profile' not in row:
                        row['profile'] = dict(class_tag=row.get('class_tag', 'unknown'))
                    if row.get('health') == 0:
                        row['alive'] = False
        for row in list(self.engine.states.values()) + list(self._players):
            if row.get('id') == self.actor_id and row.get('kind') == 'bot':
                continue
            key = row['kind'], row['network_id']
            observed = dict(row)
            if row['kind'] == 'human':
                observed['id'] = row['network_id']
            if not (roster.get(key) or {}).get('alive', True):
                observed.update(alive=False, health=0)
            roster[key] = observed
        return tuple(roster[key] for key in sorted(roster))

    def _public_allies(self):
        """Keep public team identities without inventing an unobserved pose."""
        own_team = (self.state or {}).get('team')
        return tuple(row for row in self._public_roster() if row.get('team') == own_team)

    @staticmethod
    def _server_route(route):
        """Publish the copied Bot's (x, z, hold) route without XYZ confusion."""
        if not isinstance(route, dict):
            return route
        result = dict(route)
        for name in ('waypoints', 'points'):
            if name not in result:
                continue
            converted = []
            for point in result[name]:
                if isinstance(point, dict):
                    # A peer already supplied the canonical public format.
                    converted.append(dict(point))
                else:
                    # Copied BotRuntime._prepare_user_routes stores only map
                    # horizontal coordinates and the terminal hold flag.
                    if len(point) not in (2, 3):
                        raise ValueError('invalid copied Bot route waypoint')
                    converted.append(dict(x=float(point[0]), y=0.,
                        z=float(point[1]), hold=bool(point[2]) if len(point) > 2 else False))
            result[name] = converted
        return result

    def _binding(self):
        battle = self.owner
        server = getattr(battle, '_server', None)
        entity_id = getattr(server, 'vehicle_id', None)
        entity = battle._server_entity(entity_id) if entity_id is not None else None
        return (getattr(battle, '_generation', None),
                battle._start_message.get('round_id'),
                getattr(battle.client, 'player_id', None), entity_id, id(entity), id(self.gun),
                id(battle._avatar.gunRotator))

    def attach(self):
        if self.engine is not None:
            return self._identity == self._binding()
        battle = self.owner
        clock = getattr(battle, '_clock', None)
        if callable(clock):
            self.now = float(clock())
        self._identity = self._binding()
        self.entity_id = self._identity[3]
        self.entity = battle._server_entity(self.entity_id)
        if self.entity is None or self.gun is None or not self.entity.isAlive():
            return False
        message = dict(battle._start_message)
        # Identity ordering must agree on every foreground client. Native
        # entity creation order and which human happens to be local are not
        # traffic-priority inputs.
        self.actor_id = copied_runtime.BotRuntime._human_planner_id(battle.client.player_id)
        self.geometry = _ForegroundGeometry(self)
        geometry = self.geometry
        graph = battle._navigation_graph
        bounds = getattr(battle, '_arena_bounds', None) or graph.get('bounds')
        descriptor = self.entity.typeDescriptor
        local = next((row for row in battle._records.values() if row.get('local')), None)
        if local is None:
            raise RuntimeError('local_vehicle_record_unavailable')
        self._local_record_key = next(key for key, row in battle._records.items() if row is local)
        position, yaw = battle.local_pose()
        own_raw = _player_bootstrap_actor(
            local, self.actor_id, descriptor, position, yaw, self.entity)
        # This is a new private planner instance, not a restored Bot authority.
        message.pop('bot_manifest', None)
        message.pop('bot_orders', None)
        message.pop('bot_order_revision', None)
        message.update(bot_authority_id=self.actor_id, bots=[own_raw], players=[])
        kwargs = dict(descriptor_resolver=lambda unused_name: descriptor,
            player_descriptor_resolver=battle._resolve_player_descriptor,
            direction_probe=geometry._direction_probe,
            visibility_probe=geometry._bot_visibility,
            firing_lane_probe=geometry._bot_firing_lane,
            incoming_lane_probe=geometry._bot_incoming_lane,
            friendly_lane_probe=geometry._bot_friendly_firing_lane,
            direct_launch_origin_probe=geometry._bot_direct_launch_origin,
            direct_aim_point_probe=geometry._bot_aim_point,
            artillery_aim_samples_probe=geometry._bot_artillery_aim_samples,
            ballistic_solution_probe=geometry._bot_ballistic_solution,
            artillery_launch_probe=geometry._bot_artillery_launch,
            artillery_friendly_lane_probe=geometry._bot_artillery_friendly_lane,
            artillery_launch_cancel=geometry._bot_artillery_cancel,
            artillery_status_probe=geometry._bot_artillery_status,
            spawn_resolver=lambda unused_team, unused_slot: (tuple(position), yaw),
            ground_probe=geometry._navigation_ground,
            physics_ground_probe=battle._support_column,
            obstacle_probe=geometry._navigation_obstacle,
            navigation_surface_probe=geometry._navigation_surface_observation,
            navigation_height_columns=geometry._navigation_height_columns,
            bounds=bounds, arena_bounds=bounds, cover_probe=geometry._sample_bot_cover,
            turret_motion_probe=geometry._turret_motion_is_clear,
            rotation_resolver=geometry._resolve_bot_rotation,
            local_sweep_probe=geometry._probe_bot_local_motion,
            world_receipt_probe=geometry._direction_world_receipt,
            water_depth_probe=geometry._water_depth,
            baked_graph=graph, native_motion=True)
        self.engine = _PlayerBehaviorEngine(self, **kwargs)
        geometry._bots = self.engine
        self.engine.battle_start(message)
        self.engine._equipment_now = self.now
        self.engine._pending_manifest = None
        self.engine._manifest_sent = True
        self.engine._gun_states[self.actor_id] = _GunObservation(self)
        self.engine._ammo_states[self.actor_id] = _AmmoObservation(self)
        self.engine._burst_states[self.actor_id] = _TriggerObservation(self)
        self.planner = BotPlanner()
        self.planner.reset(message.get('round_id'))
        self.planner.tactics = self.engine._bot_tactics
        self.planner.tactics_map = self.engine._navigation_map_name
        self.planner._travel_graph_cache[self.planner.tactics_map] = spg_positions._Graph(graph, graph['bounds'])
        self.attack_policy = AttackPolicy(self)
        self._observe(self.now)
        return True

    def start(self, features, mission=None):
        if self.closed or not self.attach():
            return False
        self.generation += 1
        token = self.generation
        self.features = set(features) & set(('drive', 'fire', 'consumables'))
        self.active = True
        self._strategic_due = 0.
        self._profile_window = None
        if (mission is None and self._mission is not None and
                self._mission['status'] != 'running' and not self._mission.get('holding')):
            # A new activation does not inherit a retired command's hold.
            self._mission = None
        if 'fire' in self.features and not self.weapon.bind():
            return False
        if not self.active or self.generation != token or self._binding() != self._identity:
            return False
        if mission is not None:
            self.set_mission(mission.get('action'), mission)
        return True

    def stop(self, reason='manual'):
        self.generation += 1
        self.active = False
        self._neutral_drive()
        self.weapon.close()
        self._release_next_shell(reason=reason)
        if self.attack_policy is not None:
            self.attack_policy.reset()
        self._loading_switch = self._shell_receipt = self._attack_lay = None
        self._manual_shell = None
        self._attack_log_key = None
        self._attack_log_at = float('-inf')
        self._shell_log_at = float('-inf')
        if not self.release_governor():
            raise RuntimeError('owned_governor_release_pending')
        if self._siege_pending is not None:
            callback = self._siege_pending.get('callback')
            cancel = getattr(self.owner, '_cancel_player_control_siege', None)
            if callable(cancel):
                cancel(callback)
            self._siege_pending = None
        self._move_episode = None
        self._native_hull_laying = None
        self._implicit_retry = None
        self._strategic_due = 0.
        self._profile_window = None
        if self._mission is not None and self._mission['status'] == 'running':
            self._mission.update(status='cancelled', phase='cancelled', reason=reason)
        if self._mission is not None:
            self._mission['holding'] = False
        return True

    def close(self):
        self.stop('closed')
        self.closed = True
        if self.engine is not None:
            self.engine.close()
        if self.geometry is not None:
            self.geometry._artillery.reset()

    def pose_stamp(self):
        state = self.state or {}
        return (self._identity, tuple(state.get(key) for key in
                ('x', 'y', 'z', 'yaw', 'pitch', 'roll', 'turret_yaw', 'gun_pitch')),
                id(self.entity.typeDescriptor), int(self.gun.shot_index))

    def _row(self, record, local=False):
        entity = self.owner._server_entity(record.get('engine_id'))
        if entity is None or not record.get('ready') or record.get('tombstone'):
            return None
        # Identity/liveness can be known without pose. Hidden enemy geometry is
        # not consumed even if the transport retains its last or worker pose.
        team = int(record.get('team', (record.get('state') or {}).get('team', 0)))
        own_team = int((self.state or {}).get('team', team))
        if not local and team != own_team and not record.get('spot_visible', False):
            return None
        raw = dict(record.get('state') or {})
        if isinstance(record.get('critical_state'), dict):
            raw['critical'] = copy.deepcopy(record['critical_state'])
        if local:
            position, yaw = self.owner.local_pose()
            stabilised = getattr(self.owner, '_local_stabilised_pose', self.owner._local_body_pose)
            matrix = self.owner._runtime.math.Matrix(stabilised())
        else:
            matrix = getattr(entity, 'matrix', None)
            if matrix is None or not getattr(entity, 'isStarted', False):
                return None
            position = _point(matrix.translation)
            yaw = float(matrix.yaw)
        if matrix is None:
            return None
        position = _point(position)
        kind = 'bot' if record.get('kind') == 'bot' else 'human'
        network_id = int(record.get('network_id', raw.get('id', 0)))
        identity = self.actor_id if local else (network_id if kind == 'bot' else self.engine._human_planner_id(network_id))
        descriptor = entity.typeDescriptor
        tags = getattr(getattr(descriptor, 'type', None), 'tags', ())
        profile = dict(raw.get('profile') or {})
        if not profile:
            from .copied.ai.planner import build_vehicle_profile
            profile = build_vehicle_profile(descriptor)
        tag = profile.get('class_tag') or next((tag for tag in bot_tactics.CLASSES if tag in tags), 'unknown')
        profile['class_tag'] = tag
        shape = copied_runtime._collision_shape(descriptor)
        half_length, half_width = copied_runtime._hull_dimensions(descriptor)
        raw.update(id=identity, network_id=self.actor_id if local else network_id,
                   engine_id=record['engine_id'], team=team, kind='bot' if local else kind,
                   position=position, x=position[0], y=position[1], z=position[2],
                   yaw=float(yaw), pitch=float(matrix.pitch), roll=float(matrix.roll),
                   profile=profile, class_tag=tag, world_pose=True,
                   half_length=half_length, half_width=half_width,
                   collision_shape=shape,
                   visible=True, fresh_visible=True, direct_visible=True,
                   alive=bool(entity.isAlive()), health=int(getattr(entity, 'health', raw.get('health', 0))),
                   max_health=int(getattr(descriptor, 'maxHealth', raw.get('max_health', 0))))
        if local:
            rotator = self.owner._avatar.gunRotator
            raw.update(turret_yaw=float(rotator.turretYaw), gun_pitch=float(rotator.gunPitch),
                       speed=float(self.owner._local_speed),
                       terrain_pitch=float(getattr(self.owner, '_local_terrain_pitch', matrix.pitch)),
                       airborne=bool(getattr(self.owner, '_local_airborne', False)),
                       siege_state=int(getattr(entity, 'siegeState', 0)),
                       _foreground_support_blocked=bool(getattr(
                           self.owner, '_local_support_rise_blocked', False)))
        return raw

    def _observe_local(self, now):
        """Refresh the one native actor without replaying all peer geometry."""
        local_record = self.owner._records.get(self._local_record_key)
        if local_record is None:
            raise RuntimeError('local_vehicle_record_retired')
        local = self._row(local_record, True)
        if local is None:
            raise RuntimeError('local_vehicle_pose_unavailable')
        # Preserve copied tactical state; overwrite only observed physical keys.
        physical = ('x', 'y', 'z', 'position', 'yaw', 'pitch', 'roll', 'turret_yaw',
                    'gun_pitch', 'speed', 'terrain_pitch', 'airborne', 'alive', 'health',
                    'max_health', 'critical', 'siege_state', 'siege_time_left_ms',
                    'siege_transition_total_ms', 'stun_end_server_time_ms',
                    'combat_revision', 'engine_id', 'world_pose',
                    '_foreground_support_blocked')
        self.state.update((key, local[key]) for key in physical if key in local)
        # The copied vertical integrator never runs for the foreground actor.
        # Latch an actually accepted native ground plane instead of leaving
        # the private planner forever at its ungrounded spawn checkpoint.
        if not self.state.get('grounded_once', False):
            plane = getattr(self.owner, '_local_ground_plane', None)
            if not local['airborne'] and isinstance(plane, dict):
                self.state['grounded_once'] = True
        self.state['now'] = float(now)
        self.state['kind'], self.state['network_id'] = 'bot', self.actor_id
        self.state['aim_yaw'] = _angle(local['yaw'] + local['turret_yaw'])
        self.entity = self.owner._server_entity(self.entity_id)
        self._observe_siege(local_record, local)
        self.engine._descriptors[self.actor_id] = self.entity.typeDescriptor
        self.engine._turn_speeds[self.actor_id] = float(getattr(self.owner, '_local_turn_speed', 0.))
        self.engine._contact_now = float(now)
        estimate = getattr(self.owner, '_projectile_estimated_server_time', None)
        server_now = estimate(now) if callable(estimate) else None
        if server_now is not None:
            self.engine._observe_bot_stun(self.state, local, server_now)
        return local_record, local

    def _observe(self, now):
        local_record, local = self._observe_local(now)
        records, targets, players, peers = {}, [], [], {}
        own_alias = dict(local_record, kind='bot', network_id=self.actor_id, state=dict(self.state))
        records['bot:%d' % self.actor_id] = own_alias
        for key, record in self.owner._records.items():
            if record.get('local'):
                continue
            row = self._row(record)
            if row is None:
                continue
            records[key] = record
            if row['kind'] == 'bot':
                previous = self.engine.states.get(row['id'])
                if previous is not None:
                    previous.update(row)
                    row = previous
                peers[row['id']] = row
                entity = self.target_entity(row)
                self.engine._descriptors[row['id']] = entity.typeDescriptor
                agent = self.engine.adapter.director.register_profile(
                    row['id'], row['team'], row['profile'], row.get('name', 'Bot'))
                # Published canonical route metadata outranks a local lottery;
                # absent peer route stays unknown to the spatial planner.
                if isinstance(row.get('route'), dict):
                    agent['route'] = row['route']
            else:
                players.append(dict(row, id=row['network_id']))
            if row['alive'] and row['team'] != self.state['team']:
                targets.append(row)
        for key in list(self.engine.states):
            if key != self.actor_id and key not in peers:
                self.engine.states.pop(key, None)
                self.engine._descriptors.pop(key, None)
        self.engine.states.update(peers)
        self._targets, self._players = tuple(targets), tuple(players)
        self.engine._contact_players = list(players)
        self.geometry.sync(records)
        self._observed_records = records
        self._sync_weapon_observation()
        self._sync_equipments()
        self._manifest = []
        for row in self.engine.states.values():
            raw = dict(row)
            if 'route' in raw:
                raw['route'] = self._server_route(raw['route'])
            self._manifest.append(raw)

    def _sync_weapon_observation(self):
        if self.state is None:
            return
        gun = self.gun
        if gun.reload_time <= 0.:
            self._loading_switch = None
        self.engine._ammo_states[self.actor_id].publish(self.state)
        self.engine._burst_states[self.actor_id].publish(self.state)
        self.state.update(clip=int(gun.clip), clip_size=int(gun.clip_size),
                          reload_time=float(gun.reload_time),
                          reload_duration=float(gun.reload_duration),
                          ammo_magazine_started=gun.clip_size > 1 and 0 < gun.clip < gun.clip_size)
        # The native allocator sequence may advance on a rejected launch.
        # Only shot_committed is a physical shot receipt.
        self.state['fire_seq'] = self._last_committed_shot_seq

    def _observe_traffic(self, now):
        """Project public peer inputs into the unchanged local coordinator.

        A peer's zero speed is not a request to move. Only published input
        flags admit this projection. The returned peer controls are discarded;
        preview sweeps cannot move, fire or publish for another actor.
        """
        engine, coordinator = self.engine, self.engine._traffic_coordinator
        neighbours = engine._player_neighbours(self._players)
        bodies, spatial_index = engine._traffic_snapshot(neighbours)
        local = bodies[self.actor_id]
        nearby = set(body['id'] for body in engine._neighbours_for(
            self.state, neighbours, spatial_index, bodies))
        rows = list(engine.states.values()) + [dict(row,
            id=engine._human_planner_id(row['network_id'])) for row in self._players]
        observed = {}
        for row in rows:
            identity = row['id']
            if (identity == self.actor_id or not row.get('alive', True) or
                    row.get('team') != self.state['team'] or identity not in nearby):
                continue
            body = bodies[identity]
            if 'movement_dir' in row:
                throttle = float(row['movement_dir'])
            elif 'moving_forward' in row and 'moving_backward' in row:
                throttle = float(bool(row['moving_forward'])) - float(bool(row['moving_backward']))
            else:
                continue
            if 'rotation_dir' in row:
                turn = float(row['rotation_dir'])
            else:
                turn = float(bool(row.get('turning_right'))) - float(bool(row.get('turning_left')))
            command = dict(throttle=throttle, turn=turn,
                brake=bool(row.get('service_brake', False)),
                movement_intent=bool(throttle or turn))
            # Do not manufacture tactical modes or checked reverse-blocker
            # identities that the peer never published.
            for name in ('combat_mode', 'recovery_mode', 'parking_phase',
                         'forward_blocked_by', 'reverse_blocked_by'):
                if name in row:
                    command[name] = row[name]
            record = next((value for value in self._observed_records.values()
                           if value.get('engine_id') == row.get('engine_id')), {})
            snapshot = (getattr(self.owner.client, 'last_snapshot', None) or
                        getattr(self.owner, '_last_snapshot', None) or {})
            if row['kind'] == 'human' and row.get('input_seq') is not None:
                # Every accepted human input advances its own sequence. A
                # fresh snapshot of somebody else cannot renew this input.
                source_token = ('human_input', row.get('engine_id'), row['input_seq'])
            else:
                source_token = (getattr(self.owner.client, '_snapshot_accepted_time', None),
                    snapshot.get('round_id'), snapshot.get('server_tick', snapshot.get('tick')),
                    snapshot.get('bot_state_revision'), row.get('input_seq'),
                    id(record.get('state')), tuple(sorted(command.items())))
            observed_input = self._traffic_inputs.get(identity)
            if (observed_input is None or observed_input['token'] != source_token or
                    now < observed_input['at']):
                observed_input = self._traffic_inputs[identity] = dict(token=source_token, at=now)
            # The transport's monotonic accepted-time is a progress token, not
            # a timestamp in BigWorld's clock domain. An unchanged raw input
            # cannot be renewed by merely rendering it again on another frame.
            if now - observed_input['at'] > copied_traffic.ORDER_FRESH_SECONDS:
                continue
            peers = engine._neighbours_for(row, neighbours, spatial_index, bodies)
            entity = self.target_entity(row)
            if entity is None:
                continue
            saved_state = engine.states.get(identity)
            saved_descriptor = engine._descriptors.get(identity)
            engine.states[identity] = dict(row)
            engine._descriptors[identity] = entity.typeDescriptor
            missing_proof = [False]
            def clear(heading, distance=None):
                try:
                    proof = self.geometry._probe_bot_local_motion(identity,
                        body['position'], body['yaw'], heading, distance,
                        entity.typeDescriptor, 1. / 30., now)
                except (ValueError, TypeError, RuntimeError, AttributeError):
                    proof = None
                if not isinstance(proof, dict) or not proof.get('proved'):
                    missing_proof[0] = True
                    return True
                return bool(proof['clear'])
            fields = ('_pairs', '_held', '_orders', '_jams', '_parked')
            saved_coordinator = dict((name, copy.deepcopy(getattr(coordinator, name))) for name in fields)
            try:
                coordinator.adjust(identity, body, command, peers, now, clear)
                if missing_proof[0]:
                    # The original coordinator accepts a boolean callback.
                    # An unknown native receipt must not become a false proof
                    # that both exits are blocked, nor a speculative lease.
                    for name, value in saved_coordinator.items():
                        setattr(coordinator, name, value)
                    coordinator._orders[identity] = (now, dict(command))
                params = engine._physics_params_for(identity)
                if params is not None:
                    coordinator.safe_controls(body, command, peers, now,
                        lambda: engine._traffic_stopping_distance(
                            row.get('speed', 0.), params,
                            row.get('terrain_pitch', row.get('pitch', 0.)), abs(turn) > .01))
                order_receipt = coordinator._orders.get(identity)
                if order_receipt is not None:
                    coordinator._orders[identity] = (observed_input['at'], order_receipt[1])
                observed[identity] = dict(at=observed_input['at'], input=dict(command),
                    geometric_proof=not missing_proof[0])
            finally:
                if saved_state is None:
                    engine.states.pop(identity, None)
                else:
                    engine.states[identity] = saved_state
                if saved_descriptor is None:
                    engine._descriptors.pop(identity, None)
                else:
                    engine._descriptors[identity] = saved_descriptor
        self._traffic_observed = observed

    def _sync_equipments(self):
        raw = getattr(self.owner, '_equipment_states', None)
        if raw is None:
            raw = getattr(self.owner, '_equipment_state', ())
        values = raw.values() if isinstance(raw, dict) else raw or ()
        self._equipment_snapshot = self._equipment_signature()
        views = []
        for item in values:
            if not hasattr(item, 'contract'):
                continue
            identity = int(item.contract['id'])
            view = self._equipment_views.get(identity)
            if view is None or view.contract != item.contract:
                view = _EquipmentObservation(self, item)
                self._equipment_views[identity] = view
            else:
                view.original = item
            pending = self._equipment_pending.get(identity)
            if pending is not None:
                echoed = int(getattr(self.owner, '_equipment_result_logged_seq', 0))
                if echoed >= int(pending['sequence']):
                    self._equipment_pending.pop(identity, None)
                    if (pending.get('action') == 'set_rpm_limiter' and
                            pending.get('active') and not item.active and
                            self._owned_governor == identity):
                        self._owned_governor = None
            view.sync()
            views.append(view)
        self.engine._equipment_states[self.actor_id] = tuple(views)
        self.engine._refresh_equipment_passives(self.actor_id)
        # The bootstrap temporarily published a Bot equipment ledger. Replace
        # its private wire view on this very first native observation as well,
        # not only after the first copied decision-loop tick.
        self.engine._publish_equipment_state(self.state)

    def _equipment_signature(self):
        raw = getattr(self.owner, '_equipment_states', None)
        if raw is None:
            raw = getattr(self.owner, '_equipment_state', ())
        values = raw.values() if isinstance(raw, dict) else raw or ()
        return (getattr(self.owner, '_equipment_revision', None),
                tuple(sorted(id(item) for item in values)))

    def _equipment_request(self, effect, descriptor):
        token = self.generation
        if (not self.active or 'consumables' not in self.features or
                self._binding() != self._identity or
                self._equipment_signature() != self._equipment_snapshot):
            return False
        equipment_id = int(effect['_player_equipment_id'])
        item = self._equipment_views[equipment_id]
        action = effect.get('action')
        if action == 'set_rpm_limiter':
            enabled = bool(effect.get('active'))
            if not enabled and self._owned_governor != equipment_id:
                return False
            extra = int(enabled)
        else:
            extra = 1
            selected = effect.get('selected')
            if selected in ('None', ''):
                selected = None
            if not selected and effect.get('clearStun') and not effect.get('repairAll'):
                # #1513 still encodes a real crew extra for a stun-only small
                # medkit. A missing descriptor extra is not an invented slot.
                extras = getattr(descriptor, 'extras', ())
                values = extras.values() if hasattr(extras, 'values') else extras
                selected = next((getattr(value, 'name', None) for value in values
                    if getattr(value, 'name', None) in (
                        'commanderHealth', 'gunnerHealth', 'driverHealth',
                        'radiomanHealth', 'loaderHealth')), None)
                if selected is None:
                    return self._equipment_unavailable(equipment_id, 'native_crew_extra_unavailable')
            if selected:
                try:
                    extra = int(self.owner._critical_extra_index(descriptor, selected))
                except (RuntimeError, ValueError, TypeError, AttributeError):
                    return self._equipment_unavailable(equipment_id, 'native_critical_extra_unavailable')
        activation = equipment_id | (extra << 16)
        revision = getattr(self.owner, '_equipment_revision', None)
        pending = self._equipment_pending.get(equipment_id)
        if pending is not None and pending.get('activation') == activation and pending.get('revision') == revision:
            return False
        if not self.active or 'consumables' not in self.features:
            return False
        previous_governor = self._owned_governor
        if action == 'set_rpm_limiter' and extra:
            # A synchronous native callback may Stop before the call returns.
            # Install the release owner before crossing that callback boundary.
            self._owned_governor = equipment_id
        accepted = self.owner._activate_equipment_intent(activation)
        valid = self.active and self.generation == token and self._binding() == self._identity
        if accepted and valid:
            self._equipment_pending[equipment_id] = dict(revision=revision, activation=activation,
                sequence=accepted, action=action, active=bool(extra), at=self.now)
            if action == 'set_rpm_limiter':
                self._owned_governor = equipment_id if extra else None
        elif not accepted and valid and action == 'set_rpm_limiter' and extra:
            self._owned_governor = previous_governor
        return bool(accepted)

    def _equipment_unavailable(self, equipment_id, reason):
        if self.controller is not None:
            self.controller.record('consumable_unavailable', equipment=equipment_id, reason=reason)
        return False

    def release_governor(self):
        identity = self._owned_governor
        if identity is None:
            return True
        result = self.owner._activate_equipment_intent(int(identity))
        if result:
            self._owned_governor = None
            self._equipment_pending[identity] = dict(
                revision=getattr(self.owner, '_equipment_revision', None),
                activation=identity, sequence=result, action='set_rpm_limiter',
                active=False, at=self.now)
        return bool(result)

    def _observe_siege(self, record, local):
        token = self._siege_pending
        if token is None:
            return
        observer = getattr(self.owner, '_player_control_siege_observer', None)
        if not isinstance(observer, dict) or observer.get('callback') is not token['callback']:
            # A newer manual/native request owns its own brake and lock. Only
            # retire our observer; never cancel that replacement's operation.
            if self._siege_pending is token:
                self._siege_pending = None
            return
        sequence = token.get('sequence')
        echoed = (record.get('state') or {}).get('input_seq')
        state = int(local['siege_state'])
        if (sequence is None or isinstance(echoed, bool) or
                not isinstance(echoed, _INTEGER_TYPES) or echoed < sequence or
                state in (siege_mechanics.SWITCHING_ON, siege_mechanics.SWITCHING_OFF) or
                record.get('presented_siege_state') != state or
                getattr(self.owner, '_local_siege_pending', None) is not None):
            return
        # BattleRuntime already accepted the stable, sequence-fenced echo
        # and released the physical lock. Stable mismatch is its canonical
        # rejection path; both outcomes retire only this completed observer.
        self._siege_pending = None
        cancel = getattr(self.owner, '_cancel_player_control_siege', None)
        if callable(cancel):
            cancel(token['callback'])

    def _siege_request(self, desired):
        if (not self._live() or self._mission_brakes() or self._siege_pending is not None or
                getattr(self.owner, '_local_siege_pending', None) is not None or
                getattr(self.owner, '_local_siege_braking', None) is not None or
                int(getattr(self.entity, 'siegeState', 0)) in
                    (siege_mechanics.SWITCHING_ON, siege_mechanics.SWITCHING_OFF)):
            return False
        token = dict(enabled=bool(desired), generation=self.generation)
        def submitted(sequence, enabled, reason=None):
            if self._siege_pending is token:
                token.update(sequence=sequence, reason=reason)
                if reason is not None:
                    self._siege_pending = None
        token['callback'] = submitted
        self._siege_pending = token
        accepted = self.owner._request_player_control_siege(bool(desired), submitted)
        if not accepted and self._siege_pending is token:
            self._siege_pending = None
        return bool(accepted)

    def _planner_order(self, now):
        states = list(self.engine.states.values())
        known = self.planner.known_targets(states, self._players)
        contacts = []
        for target in self._targets:
            key = self.engine._shot_los_key(self.state, target)
            lane = self.engine._shot_los_cache.get(key)
            clear = lane is not None and lane[1] and 0. <= now - lane[0] <= copied_runtime.SHOT_LANE_SECONDS
            team_key = (self.state['team'], target['kind'], target['network_id'])
            team_receipt = self._team_shooter_observations.get(team_key)
            peers, threatened = [], []
            if team_receipt is not None:
                if now <= team_receipt['until']:
                    peers = [identity for identity in team_receipt['shooters']
                        if identity != self.actor_id and identity in self.engine.states and
                        self.engine.states[identity].get('alive', True) and
                        self.engine.states[identity].get('team') == self.state['team']]
                    threatened = list(team_receipt['threatened'])
                else:
                    self._team_shooter_observations.pop(team_key, None)
            contacts.append(dict(observing_team=self.state['team'],
                target_kind=target['kind'], target_id=target['network_id'],
                target_team=target['team'], visible=True, fresh=True,
                time_left=1., x=target['x'], y=target['y'], z=target['z'],
                health=target['health'], max_health=target['max_health'],
                class_tag=target.get('class_tag'),
                shootable_by_bot_ids=sorted(set(peers + ([self.actor_id] if clear else []))),
                threatened_bot_ids=threatened,
                pending_lane_by_bot_ids=[] if clear else [self.actor_id]))
        self.planner.report_contacts(contacts, known, now)
        # A peer's certified firing lane can disappear inside the one-second
        # strategic interval. Replan that *change* immediately so copied
        # flanking decisions do not continue relying on a stale ally; native
        # target tracking and ordinary motion never trigger a global rebuild.
        contact_signature = tuple((row['observing_team'], row['target_kind'],
            row['target_id'], tuple(identity for identity in
                row['shootable_by_bot_ids'] if identity != self.actor_id),
            tuple(row['threatened_bot_ids'])) for row in contacts)
        if (self._strategic_result is None or now >= self._strategic_due or
                now < self._strategic_due - STRATEGY_SECONDS or
                contact_signature != self._strategic_contact_signature):
            # Full-roster assignment originally ran at one hertz on the LAN
            # authority. A foreground render callback must not rerun both
            # teams' global planning dozens of times for one player input.
            self._strategic_result = self.planner.build_orders(
                self._manifest, states, self._players, now,
                defense=self._defense_context(), team_orders=self._team_orders(now))
            self._strategic_due = float(now) + STRATEGY_SECONDS
            self._strategic_contact_signature = contact_signature
        result = self._strategic_result
        orders = result.get('orders') or ()
        order = next((dict(value) for value in orders if int(value.get('id', 0)) == self.actor_id), None)
        if order is None:
            raise RuntimeError('complete_local_planner_returned_no_player_order')
        order = self._mission_order(order, now)
        self._observe_mission(now)
        if 'fire' in self.features:
            order = self.attack_policy.apply_order(order, now)
            if self.attack_policy.decision['action'] == 'aim':
                self.engine._clear_friendly_reposition(self.actor_id)
            order = self._move_order(order, now)
            order = self._reload_order(order, now)
        order = self._mission_guard_order(order, now)
        self.engine._apply_orders(dict(bot_orders=[order], bot_order_revision=int(result.get('revision', 0))))
        return order

    def observe_team_observation(self, message, now):
        """Consume accepted public peer lane evidence without owning a peer.

        The server already relays these exact fields to foreground clients.
        They support the copied group/flanker election, never this player's
        native trigger admission. Target positions still come only from this
        client's current visible entities, not from hidden worker state.
        """
        if (not isinstance(message, dict) or self.engine is None or
                self._binding() != self._identity or
                message.get('round_id') != self.owner._start_message.get('round_id')):
            return False
        changed = False
        for contact in message.get('contacts') or ():
            if not isinstance(contact, dict):
                continue
            try:
                team, identity = int(contact['observing_team']), int(contact['target_id'])
                kind = contact['target_kind']
                remaining = float(contact['time_left'])
                shooters = tuple(int(value) for value in contact['shootable_by_bot_ids'])
                threatened = tuple(int(value) for value in contact.get('threatened_bot_ids') or ())
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if (team not in (1, 2) or kind not in ('bot', 'human') or identity <= 0 or
                    math.isnan(remaining) or math.isinf(remaining) or
                    any(value <= 0 for value in shooters + threatened)):
                continue
            key = team, kind, identity
            if not contact.get('visible') or remaining <= 0.:
                changed = self._team_shooter_observations.pop(key, None) is not None or changed
                continue
            self._team_shooter_observations[key] = dict(
                until=float(now) + min(remaining, copied_runtime.SHOT_LANE_SECONDS),
                shooters=shooters, threatened=threatened, observed=float(now))
            changed = True
        return changed

    def _defense_context(self):
        message = self.owner._start_message
        snapshot = getattr(self.owner, '_last_snapshot', None)
        if snapshot is None:
            snapshot = getattr(self.owner.client, 'last_snapshot', None)
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        canonical = (snapshot.get('defense') if
                     snapshot.get('round_id') == message.get('round_id') else None)
        canonical = canonical if isinstance(canonical, dict) else None
        result = copy.deepcopy(canonical or {})
        for key in ('capture_bases', 'base_capture', 'base_captures', 'battle_result'):
            if key in snapshot:
                result[key] = snapshot[key]
            elif key in message:
                result[key] = message[key]
        result['arena_bounds'] = tuple(self.owner._arena_bounds)
        spawn = getattr(self.owner, '_spawn_planner', None)
        if 'capture_bases' not in result and spawn is not None:
            bases = getattr(spawn, 'capture_bases', None)
            if bases is not None:
                result['capture_bases'] = bases
        if 'bases' not in result and spawn is not None:
            bases = getattr(spawn, 'bases', None)
            if bases is not None:
                result['bases'] = bases
        capture = ((getattr(self.owner, '_rules_state', None) or {}).get('bases') or
                   (snapshot.get('rules') or {}).get('bases') or
                   snapshot.get('capture') or snapshot.get('base_capture'))
        if isinstance(capture, dict) and 'states' not in result:
            result['states'] = capture
        contributors = (canonical or {}).get('contributors')
        result['contributors_known'] = isinstance(contributors, dict)
        if isinstance(contributors, dict):
            remapped = {}
            for team in (1, 2):
                rows = []
                for raw in contributors.get(str(team), contributors.get(team, ())) or ():
                    if not isinstance(raw, dict):
                        continue
                    row = dict(raw)
                    if row.get('kind') == 'human' and row.get('id') == self.owner.client.player_id:
                        row.update(kind='bot', id=self.actor_id)
                    rows.append(row)
                remapped[str(team)] = rows
            result['contributors'] = remapped
        if not result.get('capture_bases'):
            points = self.owner._navigation_graph.get('objective_bases') or ()
            radii = self.owner._navigation_graph.get('objective_base_radii')
            result['capture_bases'] = dict((str(team), [dict(x=float(point[0]),
                z=float(point[1]), radius=float(radii[team - 1]) if radii is not None else 50.)])
                for team, point in enumerate(points, 1))
        for name in ('capture_bases', 'bases'):
            raw_bases = result.get(name)
            if not isinstance(raw_bases, dict):
                continue
            normalized = {}
            for team in (1, 2):
                values = []
                points = raw_bases.get(str(team), raw_bases.get(team, ())) or ()
                if isinstance(points, dict):
                    points = [points]
                elif (isinstance(points, (list, tuple)) and len(points) >= 2 and
                      not isinstance(points[0], (list, tuple, dict))):
                    points = [points]
                for index, raw in enumerate(points):
                    if isinstance(raw, dict):
                        point = raw.get('point', raw)
                        x, z = float(point['x']), float(point['z'])
                        y, radius = float(point.get('y', 0.)), float(raw.get('radius', 50.))
                        identity = raw.get('id', '%d:%d' % (team, index))
                    else:
                        x, z = float(raw[0]), float(raw[-1])
                        y, radius, identity = 0., 50., '%d:%d' % (team, index)
                    values.append(dict(id=identity, x=x, y=y, z=z, radius=radius))
                normalized[str(team)] = values
            result[name] = normalized
        result.setdefault('bases', copy.deepcopy(result.get('capture_bases', {})))
        return result

    def _team_orders(self, now):
        snapshot = getattr(self.owner, '_last_snapshot', None) or {}
        rows = snapshot.get('team_commands') or snapshot.get('team_orders') or ()
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            # Canonical orders addressed to real Bots remain context. A player
            # mission below is bound to our private actor identity explicitly.
            result.append(dict(row))
        mission = self._mission
        if mission is not None and mission['status'] == 'running':
            names = dict(attack='ATTACK', return_base='BACKTOBASE', hold_position='STOP')
            command = names.get(mission['action'])
            if command is not None and 'position' not in mission['payload']:
                result.append(dict(command_id=mission['id'], command=command,
                    team=self.state['team'], recipient_bot_ids=[self.actor_id],
                    issued_tick=int(mission['started'] * 1000.),
                    expires_tick=int(mission['deadline'] * 1000.)))
        return result

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
        if 'fire' in self.features and self.attack_policy is not None:
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

    def _send_drive(self):
        if not self.active or 'drive' not in self.features:
            return
        if self._implicit_retry is not None:
            self._neutral_drive()
            return
        sender = self.owner._sender
        command = self._last_order
        sender.forward = float(command.get('throttle', 0.))
        sender.turn = float(command.get('turn', 0.))
        sender.handbrake = bool(command.get('brake', False))
        sender.send_current()

    def _neutral_drive(self):
        sender = getattr(self.owner, '_sender', None)
        if sender is not None and 'drive' in self.features:
            sender.forward = sender.turn = 0
            sender.handbrake = False
            sender.send_current()

    @staticmethod
    def _profile_stage(stages, previous, name):
        if stages is None:
            return previous
        stamp = _PROFILE_CLOCK()
        stages[name] = stages.get(name, 0.) + max(0., stamp - previous)
        return stamp

    def _profile_capture(self, stages, now):
        """Append player-only details to the existing optional error-report log.

        Full-roster Bot source files and the shared native frame-profiler ABI
        stay untouched. The recorder is inert without battle diagnostics.
        """
        if stages is None:
            return
        window = self._profile_window
        if window is None or now < window['since']:
            window = dict(since=float(now), samples=0,
                sums=dict((name, 0.) for name in PLAYER_PROFILE_STAGES),
                maxima=dict((name, 0.) for name in PLAYER_PROFILE_STAGES))
            self._profile_window = window
        window['samples'] += 1
        for name in PLAYER_PROFILE_STAGES:
            duration = max(0., float(stages.get(name, 0.)))
            window['sums'][name] += duration
            window['maxima'][name] = max(window['maxima'][name], duration)
        elapsed = float(now) - window['since']
        if elapsed < PLAYER_PROFILE_SECONDS:
            return
        samples = window['samples']
        report = dict(seconds=round(elapsed, 2), frames=samples,
            avg_ms=dict((name, round(window['sums'][name]*1000./samples, 3))
                for name in PLAYER_PROFILE_STAGES),
            max_ms=dict((name, round(window['maxima'][name]*1000., 3))
                for name in PLAYER_PROFILE_STAGES),
            parent='battle_local')
        print('[Offline LAN 0.9.22] PLAYER LOOP PERF ' +
              json.dumps(report, separators=(',', ':'), sort_keys=True))
        self._profile_window = None

    def update(self, dt, now):
        self.now = float(now)
        if not self.active:
            return self.status()
        if self._binding() != self._identity:
            self.stop('identity_changed')
            return self.status()
        if 'fire' in self.features and self._implicit_retry is None and not self.weapon.owned():
            self.stop('native_aim_owner_changed')
            return self.status()
        token = self.generation
        # These are inclusive subsets of BattleRuntime's existing `local`
        # phase. Their only purpose is to make the next user error report
        # identify which copied-player operation dominates the render frame.
        stages = getattr(self.owner, '_local_frame_stages', None)
        marker = _PROFILE_CLOCK() if stages is not None else None
        self._observe(now)
        marker = self._profile_stage(stages, marker, 'player_observe')
        if not self.state['alive']:
            self.stop('actor_destroyed')
            return self.status()
        if self._implicit_retry is not None and now >= self._implicit_retry['at']:
            self._implicit_retry = None
            self._mission = None
            if 'fire' in self.features and not self.weapon.bind():
                return self.status()
        if 'fire' in self.features:
            self.attack_policy.update(now)
        marker = self._profile_stage(stages, marker, 'player_attack')
        self._planner_order(now)
        marker = self._profile_stage(stages, marker, 'player_strategy')
        self._observe_traffic(now)
        self.geometry._artillery.advance(now, 4, self.geometry._artillery_arc_probe)
        marker = self._profile_stage(stages, marker, 'player_traffic')
        # This is the unchanged complete copy, including navigation, recovery,
        # traffic, hull aiming, firing gates, cover queue and route handoffs.
        outgoing = self.engine.update(float(dt), float(now), list(self._players))
        for message in outgoing:
            if message.get('type') == 'bot_observation' and message.get('affordances'):
                self.planner.report_affordances(message['affordances'],
                    self.planner.known_bots(self._manifest, list(self.engine.states.values())),
                    self.planner.known_targets(list(self.engine.states.values()), self._players), now)
        marker = self._profile_stage(stages, marker, 'player_copied')
        # Only the foreground actor may have changed in this copied control
        # slice. Preserve the native-source correction without re-reading,
        # re-registering and re-serializing every unrelated public peer.
        self._observe_local(now)
        self._sync_weapon_observation()
        self._sync_equipments()
        marker = self._profile_stage(stages, marker, 'player_refresh')
        if self.active and self.generation == token and self._binding() == self._identity:
            self._send_drive()
            if self._live(token) and 'fire' in self.features:
                self._apply_shell_intent()
            if not self._live(token):
                return self.status()
            self._observe_mission(now)
            if self._live(token) and 'fire' in self.features:
                self.attack_policy.background(now)
                self._apply_next_shell()
                self._record_attack(now)
        self._profile_stage(stages, marker, 'player_post')
        self._profile_capture(stages, now)
        return self.status()

    def _live(self, token=None):
        return (self.active and (token is None or token == self.generation) and
                self._binding() == self._identity and self._implicit_retry is None)

    def _shell_setting(self, name, index=None):
        settings = getattr(getattr(self.owner._runtime, 'constants', None), 'VEHICLE_SETTING', None)
        code = getattr(settings, name, None)
        if code is None:
            return False
        value = 0
        if index is not None:
            shots = self.gun.shots
            if index < 0 or index >= len(shots):
                return False
            value = _field(_field(shots[index], 'shell', {}), 'compactDescr')
            if value is None:
                return False
        return self.owner.change_vehicle_setting(code, value)

    def observe_manual_shell_setting(self, code, gun):
        settings = getattr(self.owner._runtime.constants, 'VEHICLE_SETTING', None)
        if code is None or code not in (getattr(settings, 'CURRENT_SHELLS', None),
                                       getattr(settings, 'NEXT_SHELLS', None)):
            return
        # The native input path can choose the same index as an automatic
        # lease. Comparing indices alone would mistake it for our setting.
        self._manual_shell_epoch += 1
        self._owned_next_shell = None
        if self.active and self.gun is gun:
            pending = self.owner._local_player_burst or self.owner._local_fire_intent
            name = 'NEXT_SHELLS' if code == getattr(settings, 'NEXT_SHELLS', None) else 'CURRENT_SHELLS'
            self._manual_shell = (gun, pending, name)
            if name == 'CURRENT_SHELLS':
                self.attack_policy.load_started(gun.shot_index)
            self._record_shell('manual', name, gun.pending_index if name == 'NEXT_SHELLS'
                               else gun.shot_index, True, 'manual_input', force=True)

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
        if getattr(self.owner, '_local_player_burst', None) is not None:
            self._owned_next_shell = None
            return
        if getattr(self.owner, '_local_fire_intent', None) is not None:
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
        if not self._live() or self._mission_brakes() or 'fire' not in self.features:
            return
        if (getattr(self.owner, '_local_player_burst', None) is not None or
                getattr(self.owner, '_local_fire_intent', None) is not None):
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
            if plan is not None and not policy._executable(policy.current_row(plan), plan['mode']):
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

    def _reload_order(self, order, now):
        decision = self.attack_policy.decision
        if decision.get('action') != 'reload_clip' or not decision.get('early_reload'):
            self._reload_retreat = None
            return order
        if self.gun.reload_time > 0. or self.gun.clip <= 0:
            return order
        episode = self._reload_retreat
        if episode is None:
            episode = self._reload_retreat = dict(started=now, ready=False,
                loaded=int(self.gun.shot_index), clip=int(self.gun.clip), generation=self.generation)
        if episode['ready']:
            return order
        bot = self._planner_bot()
        if bot is None:
            return order
        own_position = dict(zip(('x', 'y', 'z'), self.state['position']))
        if 'drive' not in self.features or (self._mission or {}).get('capture_started'):
            # With no drive authority, or while actually contributing capture,
            # the original planner's reload-in-place rule is the only actuator.
            episode.update(ready=True, reason='native_stationary_reload')
            return dict(order, fire_allowed=False, throttle_override=0.)
        target = (decision.get('candidate') or {}).get('target') or {}
        focus = next((contact for contact in self.planner._contacts.get(self.state['team'], {}).values()
                      if contact.get('id') == target.get('network_id') and
                      contact.get('target_kind') == target.get('kind')), None)
        # Reuse the original cover lease, route retreat endpoint, progress
        # timeout and arrival terminal. Do not invent a second retreat driver.
        if (focus is not None and self.actor_id in self.planner._cover_states and
                self.planner._apply_cover_order(order, bot, focus,
                    self.planner._personality(self.actor_id), now, urgent=True)):
            mode = str(order.get('combat_mode', ''))
            if mode in ('cover_hide', 'cover_hold') or now - episode['started'] >= 10.:
                episode.update(ready=True, reason='copied_cover_attempt_complete')
            return dict(order, fire_allowed=False)
        anchor = order.get('move_position') or own_position
        anchor = dict(zip(('x', 'y', 'z'), _point(anchor)))
        retreat = self.planner._retreat_point(bot, anchor)
        face = (focus or {}).get('position') or order.get('face_position') or anchor
        face = dict(zip(('x', 'y', 'z'), _point(face)))
        result = dict(order, fire_allowed=False)
        self.planner._apply_retreat_order(result, bot, retreat, face, now,
            'magazine_reload_retreat', 'magazine_reload_hold')
        phase = (self.planner._retreat_states.get(self.actor_id) or {}).get('phase')
        if phase in ('hold', 'resume'):
            episode.update(ready=True, reason='copied_retreat_attempt_complete')
        return result

    def _apply_shell_intent(self):
        if not self._live() or self._mission_brakes() or 'fire' not in self.features:
            return
        decision = self.attack_policy.decision
        action = decision.get('action')
        if action not in ('switch_shell', 'reload_clip'):
            return
        if (getattr(self.owner, '_local_player_burst', None) is not None or
                getattr(self.owner, '_local_fire_intent', None) is not None):
            return
        gun = self.gun
        reloading = float(gun.reload_time) > 0.
        manual = self._manual_shell
        if manual is not None and manual[0] is gun and (reloading or manual[2] == 'NEXT_SHELLS'):
            return
        # Stock CURRENT may restart an ordinary load (or transfer progress
        # with Intuition). Only the policy's proved replacement for this
        # single-shot load may exercise that input, once during the load.
        if reloading and (action != 'switch_shell' or gun.clip_size > 1 or
                gun.burst_count > 1 or self._loading_switch is gun or
                decision.get('reason') not in ('current_shell_all_armour_failed',
                                               'current_ammunition_exhausted') or
                decision.get('candidate') is None and gun.ammo[gun.shot_index] > 0):
            return
        if decision.get('early_reload') and not (self._reload_retreat or {}).get('ready'):
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
            setting = 'CURRENT_SHELLS'
            accepted = self._shell_setting(setting, index)
            applied = bool(accepted and gun.shot_index == index)
        elif action == 'reload_clip' and not reloading:
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

    def authorize_trigger(self, context, entity, gun, shot_ray):
        if not self.active or 'fire' not in self.features or self._binding() != self._identity:
            return 'automatic_control_unavailable'
        if self._mission_brakes():
            return 'mission_owns_stopped_input'
        if entity is not self.entity or gun is not self.gun:
            return 'native_weapon_owner_changed'
        if not self.weapon.owned():
            return 'native_aim_owner_changed'
        if context.get('source_pose') != self.pose_stamp():
            return 'source_pose_changed'
        if not self.weapon.verified or not self.state.get('gun_aligned'):
            return 'native_gun_not_aligned'
        return None

    def _record_attack(self, now):
        if self.controller is None or now - self._attack_log_at < STRATEGY_SECONDS:
            return
        policy = self.attack_policy.status()
        navigation = policy['navigation'] or {}
        gun, state = self.gun, self.state
        first_edge = self.controller.last_fire_failure
        key = (policy['phase'], policy['reason'], policy['shell'], policy['target'],
               policy['sample'], policy['next_shell'], policy['next_target'], policy['next_sample'],
               policy['next_status'], policy['background_coverage'],
               state.get('gun_aligned'), self.weapon.verified, gun.shot_index, gun.pending_index,
               self._last_committed_shot_seq, (self._shell_receipt or {}).get('at'),
               state.get('siege_state'), state.get('_siege_intent'),
               policy['line'], policy['mechanical'], first_edge,
               navigation.get('owner'), navigation.get('reason'))
        if key == self._attack_log_key:
            return
        self._attack_log_key, self._attack_log_at = key, now
        intention = state.get('_diagnostic_aim_intent') or {}
        siege_route = None
        if state.get('_siege_intent') is not None:
            route = self._last_order.get('control_trace') or {}
            siege_route = dict(position=tuple(state['position']),
                destination=route.get('strategic_move_position'),
                local_target=route.get('local_target'),
                movement_intent=self._last_order.get('movement_intent'))
        admission = getattr(self.controller, 'trigger_admission', None)
        receipt = getattr(admission, 'receipt', {})
        edge_detail = dict(status=receipt.get('status'), blocker=receipt.get('blocker')) if (
            first_edge and receipt.get('reason') == first_edge) else None
        self.controller.record('attack_transition', policy=policy, setting=self._shell_receipt,
            loaded=gun.shot_index, queued=gun.pending_index, clip=gun.clip, stock=list(gun.ammo),
            reload=gun.reload_time, aligned=bool(state.get('gun_aligned')),
            shot_seq=self._last_committed_shot_seq, source_verified=self.weapon.verified,
            siege_state=state.get('siege_state'), siege_intent=state.get('_siege_intent'),
            siege_route=siege_route,
            source_point=self.weapon.source_point or self.weapon.motion_point,
            actual=(state['turret_yaw'], state['gun_pitch']),
            desired=(intention.get('turret_yaw'), intention.get('gun_pitch')),
            first_edge=first_edge, first_edge_detail=edge_detail)

    def drive_contact(self, position, heading, dt, static, contact=None):
        if self.engine is None or not self.active:
            return
        now = self.now
        state = self.state
        rotation_refused = heading is None
        receipt = dict(contact or {}, position=tuple(position),
                       heading=None if rotation_refused else float(heading),
                       at=now, static=bool(static))
        if rotation_refused:
            receipt['rotation_refused'] = True
        self._last_navigation = receipt
        self.engine._decision_cache.pop(self.actor_id, None)
        self.engine._motion_probe_cache.pop(self.actor_id, None)
        if not rotation_refused:
            self.engine._invalidate_realised_motion(self.actor_id, heading, 'foreground_contact')
            if self._move_episode is not None and static:
                self._move_episode['goal'] = None
        goal = self._last_order.get('move_position')
        if goal is not None and not rotation_refused:
            self.engine.navigator.report_hard_contact(self.actor_id, position, goal, heading, now)
        driver = getattr(self.engine.adapter, 'driver', None)
        remember = getattr(driver, 'remember_failure', None)
        if callable(remember) and not rotation_refused:
            remember(self.actor_id, heading, None, receipt)
        if receipt.get('rotation_blocked') or receipt.get('rotation_refused'):
            turn = self._last_order.get('turn', 0.)
            if abs(turn) > .01:
                side = 1 if turn > 0. else -1
                state.setdefault('_blocked_rotations', {})[side] = (
                    tuple(position), state['yaw'], side * abs(float(dt)), now + 2.)
                state['_native_rotation_refused_until'] = now + 2.
        self.attack_policy.navigation_result(receipt)

    def attacked(self, attacker_engine_id, event=None):
        if self.planner is None:
            return
        event = dict(event or {})
        record = next((row for row in self.owner._records.values()
                       if row.get('engine_id') == attacker_engine_id), None)
        if record is not None and not event.get('cosmetic_only'):
            key = event.get('event_id')
            if key is not None and key in self._damage_events:
                return False
            kind = 'human' if record.get('kind') == 'player' else record.get('kind')
            accepted = self.planner.report_damage(self.actor_id, kind,
                int(record['network_id']), event.get('damage', 0), self.now)
            if accepted:
                self.state['_foreground_last_attacker'] = (kind, int(record['network_id']), self.now)
                self.engine._decision_cache.pop(self.actor_id, None)
                if key is not None:
                    self._damage_events.add(key)
            return accepted
        return False

    def shot_committed(self, event, pending):
        try:
            committed = int(event['shot_seq'])
        except (KeyError, TypeError, ValueError):
            committed = 0
        if committed > self._last_committed_shot_seq:
            self._last_committed_shot_seq = committed
            final = int(event.get('burst_index', 0)) + 1 >= int(event.get('burst_count', 1))
            manual = self._manual_shell
            if manual is not None and final:
                pending_manual = self._manual_shell[1]
                if (pending_manual is None or
                        pending_manual is not pending and pending_manual is not pending.get('player_burst')):
                    self._manual_shell = None
            if self.active and self.attack_policy is not None:
                self.attack_policy.shot_committed(event, pending)
                gun = self.gun
                if final and gun is not None and gun.clip == 0 and gun.reload_time > 0.:
                    burst = pending.get('player_burst') or {}
                    context = (pending.get('player_control') or burst.get('player_control') or
                               getattr(self.controller, 'trigger_context', None) or {})
                    plan = None
                    lease = self._owned_next_shell
                    if context.get('gun') is gun and context.get('load_epoch') == self._manual_shell_epoch:
                        plan = context.get('load_plan')
                    if (plan is None and manual is None and lease is not None and
                            lease['gun'] is gun and lease['index'] == gun.shot_index):
                        plan = lease.get('plan')
                    self.attack_policy.load_started(int(gun.shot_index), plan)
                    if lease is not None and gun.pending_index != lease['index']:
                        self._owned_next_shell = None
                    loaded_plan = self.attack_policy.loading_plan
                    self._record_shell('load_committed', None, int(gun.shot_index), True,
                        'automatic_plan' if loaded_plan is not None else
                        'manual_selection' if manual is not None else 'native_reload',
                        force=True, plan=loaded_plan)
        self._sync_weapon_observation()
        identity = event.get('projectile_id')
        if identity is not None:
            self._recent_projectiles[identity] = dict(status='committed',
                trigger=pending.get('burst_group_seq'), shell=event.get('shell_index'), at=self.now)

    def shot_hit(self, event):
        # Results do not upgrade ammunition or grant new search deadlines.
        identity = event.get('projectile_id')
        row = self._recent_projectiles.get(identity)
        if row is not None:
            row.update(combat_observed=True, at=self.now)
        if event.get('killed'):
            self.engine._decision_cache.pop(self.actor_id, None)
        return row

    def shot_terminal(self, event):
        identity = event.get('projectile_id')
        row = self._recent_projectiles.get(identity)
        if row is not None:
            row.update(status='terminal', at=self.now, hit_vehicle=event.get('hit_vehicle'))
        if len(self._recent_projectiles) > 128:
            completed = sorted((key for key, value in self._recent_projectiles.items()
                                if value['status'] == 'terminal'),
                               key=lambda key: self._recent_projectiles[key]['at'])
            for key in completed[:len(self._recent_projectiles) - 128]:
                self._recent_projectiles.pop(key, None)
        return row

    def fire_rejected(self, reason, *unused_args):
        self._last_fire_failure = str(reason)

    def mission_preflight(self, kind, payload=None):
        from .commands import MISSIONS
        if kind not in MISSIONS:
            return 'unknown_mission'
        payload = payload or {}
        raw = payload.get('position')
        if raw is None and 'x' in payload and 'z' in payload:
            raw = (payload['x'], payload.get('y', 0.), payload['z'])
        if raw is not None:
            try:
                point = _point(raw)
                if any(math.isnan(value) or math.isinf(value) for value in point):
                    return 'invalid_destination'
            except (ValueError, TypeError, IndexError, KeyError, AttributeError):
                return 'invalid_destination'
            bounds = getattr(self.owner, '_arena_bounds', None)
            if bounds is not None and (point[0] < bounds[0] or point[0] > bounds[2] or
                                       point[2] < bounds[1] or point[2] > bounds[3]):
                return 'destination_outside_arena'
        try:
            radius = float(payload.get('radius', 2.))
            timeout = float(payload.get('timeout', 600.))
            if any(math.isnan(value) or math.isinf(value) or value <= 0.
                   for value in (radius, timeout)):
                return 'invalid_mission_parameters'
        except (ValueError, TypeError, OverflowError):
            return 'invalid_mission_parameters'
        return None

    def set_mission(self, kind, payload=None):
        reason = self.mission_preflight(kind, payload)
        if reason is not None:
            return dict(status='rejected', reason=reason)
        if self.engine is None and not self.attach():
            return dict(status='failed', reason='player_unavailable')
        from .commands import MISSIONS
        if kind not in MISSIONS:
            return dict(status='rejected', reason='unknown_mission')
        payload = dict(payload or {})
        self._mission_sequence += 1
        self._strategic_due = 0.
        self._mission = dict(id=payload.get('command_id', 'player-mission-%d' % self._mission_sequence),
            action=kind, status='running', phase='travelling', reason=None, explicit=True,
            started=float(payload.get('requested_at', self.now)),
            deadline=float(payload.get('requested_at', self.now)) + float(payload.get('timeout', 600.)),
            payload=payload, progress=0., holding=False)
        self._mission_halt = HaltObservation()
        self._implicit_retry = None
        self._implicit_failures = 0
        self._move_episode = self._reload_retreat = None
        self.engine._clear_friendly_reposition(self.actor_id)
        self.state.pop('_gun_angle_adjustment', None)
        if kind == 'hold_position' and not ('position' in payload or 'x' in payload and 'z' in payload):
            self._mission['hold_point'] = tuple(self.state['position'])
        if 'position' in payload:
            self._mission['destination'] = _point(payload['position'])
        self._mission['radius'] = float(payload.get('radius', 2.))
        self.engine._decision_cache.pop(self.actor_id, None)
        return self.mission_status()

    def _mission_order(self, order, now):
        mission = self._mission
        if mission is None and order.get('combat_mode') == 'base_capture' and self._implicit_retry is None:
            self._mission_sequence += 1
            mission = self._mission = dict(id='auto-capture-%d' % self._mission_sequence,
                action='capture_base', explicit=False, payload={}, status='running',
                phase='capture_travel', reason='copied_route_capture_handoff',
                progress=0., holding=False, started=now, deadline=now + 600.)
        if mission is None or mission['status'] != 'running' and not mission.get('holding'):
            return order
        payload, kind = mission['payload'], mission['action']
        empty = bool(self.gun.ammo) and not any(int(value) > 0 for value in self.gun.ammo)
        if empty and kind == 'attack':
            kind = mission['action'] = 'capture_base'
            mission.update(phase='capture_travel', reason='ammunition_exhausted', holding=False)
            mission.pop('destination', None)
        defense = self._defense_context()
        if kind == 'capture_base':
            target = self.planner._capture_target(defense, self.state['team'])
            if target is None:
                mission.update(status='failed', phase='failed', reason='capture_circle_unavailable')
                self._retire_implicit(now)
                return order
            mission.update(capture_area=target, destination=_point(target['point']))
            inside = capture_orders.inside(self.state, target) and not self.state.get('airborne', False)
            if inside:
                mission['capture_started'] = True
            # Preserve the full copied emergency-defence handoff for an
            # implicit approach until this player actually starts capturing.
            if (not mission['explicit'] and not mission.get('capture_started') and
                    order.get('combat_mode') == 'base_defense'):
                mission['phase'] = 'defending'
                return order
            result = dict(order)
            self.planner._apply_base_capture_order(result, self._planner_bot(), target)
            result['capture_area'] = target
            return capture_orders.constrain(result, self.state)
        destination = None
        if 'position' in payload:
            destination = _point(payload['position'])
        elif 'x' in payload and 'z' in payload:
            destination = (float(payload['x']), self.state['y'], float(payload['z']))
        if kind in ('return_base', 'defend_base'):
            bases = (defense.get('capture_bases') or {}).get(str(self.state['team'])) or ()
            if not bases:
                mission.update(status='failed', phase='failed', reason='home_circle_unavailable')
                return order
            destination = _point(bases[0])
            if kind == 'defend_base':
                mission['radius'] = float(bases[0]['radius'])
        if kind == 'hold_position':
            destination = destination or tuple(mission.setdefault('hold_point', self.state['position']))
        if destination is not None:
            result = dict(order, move_position=destination, face_position=destination,
                          throttle_override=None, combat_mode='team_' + kind,
                          parking_phase=None, route_join=False)
            mission['destination'] = destination
            distance = _distance(self.state['position'], destination)
            radius = mission.get('radius', 2.)
            if distance <= radius:
                result.update(move_position=destination, throttle_override=0.,
                              combat_mode='engage' if result.get('target_id') is not None else 'hold')
            mission.setdefault('initial_distance', distance)
            return result
        if kind == 'attack' and order.get('combat_mode') == 'base_capture':
            mission.update(action='capture_base', phase='capture_travel',
                           reason='copied_route_capture_handoff')
            return self._mission_order(order, now)
        return order

    def _planner_bot(self):
        return next((bot for bot in self.planner._alive_bots(
            self._manifest, list(self.engine.states.values()), self.planner.tactics)
            if bot['id'] == self.actor_id), None)

    def _mission_guard_order(self, order, now):
        """External mission ownership constrains goals, never drive physics."""
        mission = self._mission
        if mission is None:
            return order
        if mission['status'] in ('failed', 'cancelled'):
            return dict(order, move_position=tuple(self.state['position']),
                        throttle_override=0., fire_allowed=False, combat_mode='hold')
        if mission['action'] == 'capture_base' and mission.get('capture_area'):
            if not mission['explicit'] and mission['phase'] == 'defending' and not mission.get('capture_started'):
                return order
            return capture_orders.constrain(dict(order, capture_area=mission['capture_area']), self.state)
        if mission['action'] in ('attack', 'return_base', 'hold_position', 'defend_base') and mission.get('destination'):
            destination = mission['destination']
            inside = _distance(self.state['position'], destination) <= mission.get('radius', 2.)
            if not inside:
                return dict(order, move_position=destination, throttle_override=None,
                            combat_mode='team_' + mission['action'], parking_phase=None,
                            route_join=False)
            if mission['action'] != 'defend_base' or mission.get('holding'):
                return dict(order, move_position=destination, throttle_override=0.,
                            combat_mode='engage' if order.get('target_id') is not None else 'hold')
        return order

    def _mission_brakes(self):
        mission = self._mission
        return bool(mission is not None and
            (mission['status'] in ('failed', 'cancelled') or
             mission.get('phase') == 'arriving'))

    def attack_search_drive_available(self):
        mission = self._mission or {}
        return bool('drive' in self.features and not self._mission_brakes() and
                    self._implicit_retry is None and not mission.get('capture_started') and
                    not (mission.get('explicit') and mission.get('destination') is not None))

    def _observe_mission(self, now):
        mission = self._mission
        if mission is None or mission['status'] != 'running':
            return
        if now >= mission['deadline']:
            mission.update(status='failed', phase='failed', reason='deadline')
            self._retire_implicit(now)
            return
        result = getattr(self.owner, '_battle_result', None)
        if result is None:
            result = (getattr(self.owner, '_last_snapshot', None) or {}).get('battle_result')
        if isinstance(result, dict):
            self.finish_battle(result, now)
            return
        destination = mission.get('destination')
        if mission['action'] == 'capture_base' and mission.get('capture_area'):
            inside = (capture_orders.inside(self.state, mission['capture_area']) and
                      not self.state.get('airborne', False))
            if mission['phase'] != 'defending' or mission.get('capture_started'):
                mission['phase'] = 'capturing' if inside else 'capture_travel'
            if inside:
                mission['capture_started'] = True
            native = (self._defense_context().get('states') or {}).get(str(3 - self.state['team'])) or {}
            mission['progress'] = max(0., min(1., float(native.get('points', 0.)) / 100.))
            mission['holding'] = inside
            return
        if destination is None:
            mission['phase'] = 'attacking' if self._last_order.get('target_id') is not None else 'travelling'
            return
        distance = _distance(self.state['position'], destination)
        initial = max(float(mission.get('initial_distance', distance)), mission.get('radius', 2.))
        mission['progress'] = max(0., min(1., 1. - distance / initial))
        if distance > mission.get('radius', 2.):
            self._mission_halt = HaltObservation()
            mission['phase'], mission['holding'] = 'travelling', False
            return
        mission['phase'] = 'arriving'
        if self._mission_halt.observe(self.owner, now):
            if mission['action'] in ('return_base', 'hold_position', 'attack'):
                mission.update(status='completed', phase='holding',
                    reason='supported_stopped_arrival', holding=True, progress=1.)
            elif mission['action'] == 'defend_base':
                mission.update(phase='defending', holding=True, progress=1.)

    def _retire_implicit(self, now):
        mission = self._mission
        if mission is None or mission['explicit'] or mission['status'] not in ('failed', 'cancelled'):
            return False
        if self._implicit_retry is not None:
            return True
        self._implicit_failures += 1
        self._implicit_retry = dict(at=now + min(30., 5. * self._implicit_failures),
                                   failures=self._implicit_failures)
        self._move_episode = None
        self.engine._clear_friendly_reposition(self.actor_id)
        self.weapon.close()
        self._neutral_drive()
        return True

    def mission_status(self):
        mission = self._mission
        if mission is None:
            return dict(id=None, action=None, status='idle', phase='idle', progress=0., holding=False)
        result = dict((key, mission[key]) for key in ('id', 'action', 'status', 'phase',
                    'reason', 'explicit', 'progress', 'holding', 'destination') if key in mission)
        if mission.get('destination') is not None:
            point = mission['destination']
            result['goal'] = (point[0], point[2])
        if self._implicit_retry is not None:
            result['retry_at'] = self._implicit_retry['at']
        return result

    def finish_battle(self, result, now):
        mission = self._mission
        if mission is not None and mission['status'] == 'running':
            captured = (mission['action'] == 'capture_base' and mission.get('capture_started') and
                        result.get('reason') == 'base captured' and
                        int(result.get('winner', 0)) == int(self.state['team']) and
                        int(result.get('base_team', 0)) == 3 - int(self.state['team']))
            mission.update(status='completed' if captured else 'cancelled',
                phase='captured' if captured else 'cancelled',
                reason='base_captured' if captured else 'battle_finished_before_objective',
                holding=False)
        return self.mission_status()

    def _move_order(self, order, now):
        """Preserve ordinary copied handoffs; bind only the new armour search."""
        decision = self.attack_policy.decision
        action = decision.get('action')
        observation = self._native_hull_laying
        if observation is not None:
            handoff = observation.get('handoff')
            if (action not in ('firing_position', 'wait', 'preaim') or
                    observation['gun'] is not self.gun or
                    observation['shell'] != self.gun.shot_index or
                    handoff is not None and _distance(self.state['position'],
                        handoff['position']) >= copied_driver.WAYPOINT_ARRIVAL_RADIUS):
                self._native_hull_laying = None
            elif action != 'firing_position':
                self._release_native_hull_laying('native_pivot_lost_proof', now)
        if action == 'firing_position':
            self._move_episode = None
            return self._ordinary_firing_order(order, now)
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
            if action == 'retreat' and decision['reason'] == 'no_he_or_verified_penetration':
                return self._unusable_ammo_retreat(order, now)
            return order
        request = decision.get('move_request') or {}
        identity = request.get('episode_id')
        if not self.attack_search_drive_available():
            self._last_navigation = dict(action=action, episode_id=identity, at=now,
                status='refused', reason='drive_authority_unavailable')
            self.attack_policy.navigation_result(self._last_navigation)
            return order
        target = request.get('target') or (decision.get('candidate') or {}).get('target')
        if target is None:
            target = next(iter(self._targets), None)
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
        observation = self._native_hull_laying
        if observation is not None and 'handoff' not in observation:
            # Rechecking a line at the same position cannot interrupt the
            # drive that the previous failed pivot just handed back.
            observation['handoff'] = dict(reason=reason, at=now,
                                          position=tuple(self.state['position']))

    def _ordinary_firing_order(self, order, now):
        """Bind new per-point evidence to the copied existing manoeuvre owner.

        A friend, a mechanical limit, and a world obstruction are different
        facts. None is a licence to replace the full old navigation/recovery
        chain with the new eight-second armour-search destination generator.
        """
        decision = self.attack_policy.decision
        candidate = decision.get('candidate') or {}
        request = decision.get('move_request') or {}
        target = request.get('target') or candidate.get('target')
        if not isinstance(target, dict):
            target = next((row for row in self._targets if
                           row['network_id'] == order.get('target_id') and
                           row['kind'] == order.get('target_kind')), None)
            target = target or next(iter(self._targets), None)
            if target is None:
                self._release_native_hull_laying('native_pivot_lost_proof', now)
                return order
        solution = candidate.get('solution') or request.get('solution') or {}
        mechanical = candidate.get('mechanical')
        protected = bool(order.get('parking_phase') or order.get('empty_ammo') or
            order.get('combat_mode') in ('base_defense', 'low_health_retreat',
                'magazine_reload_retreat', 'withdraw'))
        can_lay_hull = (mechanical == 'hull_laying' and candidate.get('line') == 'clear' and
                        candidate['shell_index'] == self.gun.shot_index and not protected)
        if not can_lay_hull:
            self._release_native_hull_laying('native_pivot_lost_proof', now)
        if candidate.get('line') == 'friendly_blocked':
            blocker = request.get('blocker') or candidate.get('blocker') or {}
            active = self.engine._friendly_repositions.get(self.actor_id)
            # The original owner must observe and expire its existing lease.
            # Re-marking at the exact deadline would otherwise renew it before
            # _friendly_reposition_order can publish its bounded fallback.
            if active is None and not protected and 'drive' in self.features:
                command = dict(order, target_id=target['id'])
                launch = dict(fire_seq=int(self.state.get('fire_seq', 0)) + 1,
                              shot_yaw=solution.get('yaw', self.state['aim_yaw']))
                active = self.engine._mark_friendly_reposition(
                    self.state, command, target, launch, blocker, now)
            self._last_navigation = dict(status='waiting', action='firing_position',
                reason='friendly_lane', owner='copied_friendly_reposition')
            if active or protected:
                return order
            return self._resume_firing_approach(order, target)
        if can_lay_hull:
            identity = self.engine._artillery_target_identity(target)
            observation = self._native_hull_laying
            yaw = float(self.state['yaw'])
            error = abs(_angle(solution.get('yaw', yaw) - yaw))
            if observation is None or ('handoff' not in observation and observation['target'] != identity):
                observation = self._native_hull_laying = dict(target=identity, gun=self.gun,
                    shell=self.gun.shot_index, progress_at=now, progress_yaw=yaw, best_error=error)
            if 'handoff' not in observation:
                if (abs(_angle(yaw - observation['progress_yaw'])) >= NATIVE_ANGLE_TOLERANCE and
                        error < observation['best_error'] - NATIVE_ANGLE_TOLERANCE):
                    observation.update(best_error=error, progress_at=now, progress_yaw=yaw)
                if ('drive' not in self.features or
                        now < self.state.get('_native_rotation_refused_until', 0.) or
                        now - observation['progress_at'] >= MECHANICAL_STALL_SECONDS):
                    self._release_native_hull_laying('native_pivot_stalled', now)
                else:
                    # The copied combat_hull_aim pivots a stationary engagement.
                    self._last_navigation = dict(status='aligning', action='firing_position',
                        reason=solution.get('mechanical_reason'), owner='copied_combat_hull_aim')
                    return dict(order, move_position=tuple(self.state['position']),
                        face_position=target['position'], throttle_override=0.,
                        combat_mode='engage', fire_allowed=False)
        handoff = (self._native_hull_laying or {}).get('handoff')
        self._last_navigation = dict(status='waiting', action='firing_position',
            reason=handoff['reason'] if handoff else decision.get('reason'),
            owner='copied_ordinary_navigation')
        if handoff is not None:
            self._last_navigation['pivot_handoff'] = dict(handoff)
        return order if protected else self._resume_firing_approach(order, target)

    def _unusable_ammo_retreat(self, order, now):
        mission = self._mission or {}
        if ('drive' not in self.features or self._mission_brakes() or
                mission.get('explicit') and mission.get('action') != 'attack' or
                mission.get('capture_started') or order.get('parking_phase') or
                order.get('combat_mode') == 'base_defense'):
            return order
        bot = self._planner_bot()
        if bot is None:
            return order
        position = self.state['position']
        anchor = dict(zip(('x', 'y', 'z'), _point(
            order.get('_route_position') or order.get('move_position') or position)))
        retreat = order.get('_turnback_position') or self.planner._retreat_point(bot, anchor)
        face = dict(zip(('x', 'y', 'z'), _point(order.get('face_position') or position)))
        result = dict(order, fire_allowed=False)
        return self.planner._apply_retreat_order(result, bot, retreat, face, now,
                                                'withdraw', 'unusable_ammunition_hold')

    def _resume_firing_approach(self, order, target):
        # Keep existing route, cover, traffic and recovery control when it
        # already has a destination. Release only an attack-owned stop.
        position = self.state['position']
        goal = order.get('move_position') or position
        if ('drive' not in self.features or self._mission_brakes() or
                order.get('parking_phase') or order.get('empty_ammo') or
                order.get('combat_mode') in ('base_defense', 'low_health_retreat',
                    'magazine_reload_retreat', 'withdraw') or
                order.get('throttle_override') != 0. and _distance(_point(goal), position) > 1.):
            return order
        return self.engine._gun_angle_combat_order(self.state,
            dict(order, aim_position=target['position'], face_position=target['position']))

    def status(self):
        state = self.state or {}
        policy = self.attack_policy.status() if self.attack_policy is not None else {}
        target = self.weapon.target
        aim = dict(target=target.get('engine_id') if isinstance(target, dict) else None,
                   point=self.weapon.point, source_verified=self.weapon.verified,
                   shot_point_source=('verified' if self.weapon.verified else
                       'motion_only' if self.weapon.motion_point is not None else 'none'),
                   aligned=bool(state.get('gun_aligned')), failure=self._last_fire_failure,
                   action=policy.get('action'), reason=policy.get('reason'))
        return dict(active=self.active, order=_plain_order(self._last_order), aim=aim,
                    attack=policy, shell_setting=self._shell_receipt,
                    target=aim['target'], navigation=dict(self._last_navigation),
                    mission=self.mission_status())
