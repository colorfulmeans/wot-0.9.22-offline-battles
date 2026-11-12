# -*- coding: utf-8 -*-
"""Shared decision loop bound to one native foreground vehicle.

The shared planner owns decisions, not a second vehicle simulation. Observed
roster rows are private snapshots; the native foreground battle remains the
only owner of pose, gun clocks, ammunition, criticals and physical projectiles.
No message returned by the foreground engine facade is published as Bot authority.
"""
from __future__ import print_function

import copy
import json
import math
import time

from .. import equipment_mechanics
from .. import shot_geometry
from .. import siege_mechanics
from ..entities.remote_vehicle import (
    collide_vehicle_at_matrix, vehicle_target_bounds_at_matrix)
from ..projectile_runtime import (
    PROJECTILE_BROADPHASE_RADIUS, point_in_expanded_segment_bounds,
    point_segment_distance_sq)
from .attack_policy import (
    AttackPolicy, _planning_pose, native_geometry_complete, native_source_pose)
from .. import bot_runtime as shared_runtime
from .. import spg_positions
from .. import bot_tactics
from ..ai import driver as shared_driver
from ..ai import traffic as shared_traffic
from ..artillery_controller import ArtilleryController
from .geometry import SharedBattleGeometry
from .strategy import BotPlanner
from .native_aim import NATIVE_ANGLE_TOLERANCE
from .settling import foreground_motion
from .mission_control import MissionControl
from .combat_stop import CombatStop, MECHANICAL_STALL_SECONDS
from .siege_planning import ActualSiegeAim
from .combat_control import CombatControl, _point, _angle, _distance, _field
from ..native_input_diagnostics import combat_detail, combat_detail_enabled
from .actor_observation import PlayerObservation
from .target_selection import nominal_armor


# The original LAN authority builds full-roster strategic orders every 30
# ticks at 30 Hz. Foreground tactical input and native safety proofs continue
# every physical frame; only the complete roster assignment has this cadence.
STRATEGY_SECONDS = 1.0
PLAYER_PROFILE_SECONDS = 30.0
PLAYER_PROFILE_STAGES = (
    'player_observe', 'player_attack', 'player_strategy', 'player_traffic',
    'player_shared_control', 'player_refresh', 'player_post')
_PROFILE_CLOCK = getattr(time, 'perf_counter', None)
if _PROFILE_CLOCK is None:
    _PROFILE_CLOCK = time.clock

try:
    _INTEGER_TYPES = (int, long)
except NameError:
    _INTEGER_TYPES = (int,)








def _clip_wreck_chord(first, last, bounds):
    """Restrict the precise wreck test to the coarse envelope's overlap."""
    if bounds is None:
        return first, last
    entry = shot_geometry.segment_box_entry_distance(first, last, bounds)
    if entry is None:
        return None
    tail = shot_geometry.segment_box_entry_distance(last, first, bounds)
    if tail is None:
        return first, last
    delta = tuple(last[axis] - first[axis] for axis in range(3))
    length = math.sqrt(sum(value * value for value in delta))
    # Preserve grazing contacts on the boundaries of the envelope.
    lo = max(0., entry - .001) / length
    hi = min(length, length - tail + .001) / length
    return (tuple(first[axis] + delta[axis] * lo for axis in range(3)),
            tuple(first[axis] + delta[axis] * hi for axis in range(3)))




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
        self._release = None
        self.clear_aim()

    def clear_aim(self):
        self.point = self.source_point = self.target = self.solution = None
        self.motion_point = None
        self.verified = False

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
            self.clear_aim()

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

    def preaim(self, candidate):
        """Lay the active hydraulic gun without granting a firing proof.

        The already-enabled native actuator follows the policy's current
        point. No future mode, armour or lane certificate admits this input;
        a shot still needs the actual barrel and native inverse to converge.
        """
        if not self.runtime._live() or not self.owned():
            return False
        solution = candidate.get('solution') or {}
        point = solution.get('source_point')
        if point is None or not solution.get('siege_aim'):
            return False
        self.target = candidate.get('target')
        self.point = _point(solution['point'])
        self.motion_point = _point(point)
        self.source_point = self.solution = None
        self.verified = False
        return True


class _ForegroundGeometry(SharedBattleGeometry):
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

    def _wreck_blocks_bot_path(self, rows, points, lane_ends=(), receipt=None):
        """An envelope hit only selects the chord for native component tests."""
        radius = PROJECTILE_BROADPHASE_RADIUS
        radius_sq = radius ** 2
        chords = tuple(zip(points, points[1:]))
        for record, vehicle, position in rows:
            if any(record is excluded for excluded in lane_ends):
                continue
            nearby = [(first, last) for first, last in chords
                      if point_in_expanded_segment_bounds(position, first, last, radius)
                      and point_segment_distance_sq(position, first, last) <= radius_sq]
            if not nearby:
                continue
            if not native_geometry_complete(vehicle):
                raise ValueError('Missing attached wreck collision geometry')
            if record.get('local') and self._local_matrix is not None:
                body, chassis = self._local_body_pose(), self._local_matrix
            else:
                body, chassis = self._projectile_vehicle_matrices(record, vehicle)
            math_module = self._runtime.math
            bounds = vehicle_target_bounds_at_matrix(
                vehicle, body, math_module, chassis_matrix=chassis,
                require_complete=True)
            for first, last in nearby:
                segment = _clip_wreck_chord(first, last, bounds)
                if segment is None:
                    continue
                if collide_vehicle_at_matrix(
                        vehicle, body, self._vector(segment[0]), self._vector(segment[1]),
                        math_module, chassis_matrix=chassis):
                    self._wreck_lane_evidence(record, vehicle, points, True)
                    if receipt is not None:
                        receipt.update(self._wreck_blocker_receipt(record, vehicle, position))
                    return True
            self._wreck_lane_evidence(record, vehicle, points, False)
        # Landed turrets remain separate obstacles on the server clock.
        return SharedBattleGeometry._wreck_blocks_bot_path(self, (), points, lane_ends, receipt)

    def _bot_direct_launch_origin(self, source, descriptor, shell_index,
                                  fire_seq, yaw, pitch, flight_time=0.):
        if int(source.get('id', 0)) == self.player_runtime.actor_id:
            return _point(self.player_runtime.owner._mutable_shot_ray()[0])
        return SharedBattleGeometry._bot_direct_launch_origin(
            self, source, descriptor, shell_index, fire_seq, yaw, pitch, flight_time)


class _PlayerBehaviorEngine(shared_runtime.BotRuntime):
    """Override ownership boundaries; execute the complete copied algorithm."""
    def __init__(self, runtime, **kwargs):
        self.player_runtime = runtime
        shared_runtime.BotRuntime.__init__(self, runtime.actor_id, **kwargs)
        self._actor_controls[runtime.actor_id] = runtime

    def controlled_states(self):
        state = self.states.get(self.player_runtime.actor_id)
        return (state,) if state is not None else ()

    def _ordered_states(self):
        # SPG reservations, radio/lanes and cohort placement use this roster.
        # Only controlled_states() limits actual actor execution. Peer rows
        # remain private observations; the returned worker wire is never sent.
        return shared_runtime.BotRuntime._ordered_states(self)

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
        shared_runtime._clear_critical_parts_tick_cache(state)
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
        return shared_runtime.BotRuntime._update_bot_siege_intent(
            self, state, command, target, step)


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
        runtime = self.player_runtime
        owner = runtime.owner
        stabilised = getattr(owner, '_local_stabilised_pose', owner._local_body_pose)
        body = owner._runtime.math.Matrix(stabilised())
        correction = float(getattr(owner, '_local_siege_aim_pitch', 0.))
        state['terrain_pitch'] = float(getattr(owner, '_local_terrain_pitch', body.pitch))
        state['suspension_pitch'] = correction
        state['pitch'], state['roll'] = float(body.pitch), float(body.roll)
        if int(getattr(runtime.entity, 'siegeState', 0)) == siege_mechanics.ENABLED:
            # Hydraulic pitch on a rolled chassis also changes the gun
            # basis yaw. Keep the route yaw on the physical chassis.
            state['_gun_aim_body'] = (float(body.yaw), state['pitch'], state['roll'])
            if combat_detail_enabled():
                combat_detail(runtime, 'siege_aim_pose', runtime.actor_id, runtime.now,
                    runtime.combat_stop._episode, lambda: dict(
                        siege_state=siege_mechanics.ENABLED, chassis_yaw=state['yaw'],
                        aim_body=state['_gun_aim_body'], hydraulic_pitch=correction))
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






    def _log_motion_stall(self, state, command, throttle, turn, path_clear,
                          motion_probe, now, pose_frozen=False,
                          traffic_input=None, traffic_output=None):
        shared_runtime.BotRuntime._log_motion_stall(
            self, state, command, throttle, turn, path_clear, motion_probe, now,
            pose_frozen, traffic_input, traffic_output)
        self.player_runtime._accept_controls(
            command, throttle, turn, path_clear, motion_probe, now)

    def _update_gun_aim(self, state, command, target, step, weapon_tick=None):
        if command.get('_siege_aim_deferred'):
            self.player_runtime.weapon.clear_aim()
            return shared_runtime.BotRuntime._update_gun_aim(
                self, state, command, target, step, weapon_tick)
        # Retain the full copied law and every recovery/intention transition.
        # Only its actuator's predicted angles are replaced by native feedback.
        shadow = dict(state)
        result = shared_runtime.BotRuntime._update_gun_aim(
            self, shadow, command, target, step, weapon_tick)
        for key, value in shadow.items():
            if key.startswith('_') or key in ('desired_gun_pitch', 'hull_aiming'):
                state[key] = value
        intention = shadow.get('_diagnostic_aim_intent') or {}
        runtime = self.player_runtime
        tail_active = getattr(runtime.owner, '_local_player_burst', None) is not None
        if 'fire' in runtime.features and runtime.active and not tail_active:
            navigation_owned = runtime.siege_navigation_owns(command)
            laying = None if navigation_owned else runtime.siege_aim_candidate(target)
            if navigation_owned:
                target = None
                runtime._siege_aim_candidate = None
                runtime.siege_aim.reset()
            if (laying is not None and
                    runtime.current_attack_candidate(state, target, for_aim=True) is None):
                runtime.weapon.preaim(laying)
            else:
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
        if runtime.controller is None:
            combat_detail(runtime, 'auto_trigger_context', runtime.actor_id, runtime.now,
                'controller_unavailable', lambda: dict(shell=state.get('shell_index')))
            return False
        candidate = runtime.attack_policy.decision.get('candidate')
        solution = (candidate or {}).get('solution') or runtime.weapon.solution
        context = runtime.prepare_trigger_context(
            state, runtime.weapon.target, solution, launch_receipt)
        if context is None:
            return False
        controller = runtime.controller
        trigger_shell = runtime.gun.shot_index
        accepted = controller.issue_automatic_trigger(context, runtime.now)
        if not accepted:
            runtime._discard_trigger_next_shell(context.get('load_plan'))
        runtime._sync_weapon_observation()
        if combat_detail_enabled():
            reason = 'accepted' if accepted else controller.last_fire_failure or 'native_trigger_no_receipt'
            combat_detail(runtime, 'auto_native_trigger', runtime.actor_id, runtime.now, reason,
                lambda: dict(candidate=(candidate or {}).get('key'), shell=trigger_shell,
                    loaded_after=runtime.gun.shot_index,
                    trigger=controller.trigger_sequence, shot_seq=runtime._last_committed_shot_seq,
                    pending=bool(getattr(runtime.owner, '_local_fire_intent', None)),
                    native_gate=(runtime.owner._native_shot_gate_observation()
                                 if reason == 'native_trigger_no_receipt' else None)))
        return bool(accepted)


class FullPlayerRuntime(MissionControl, CombatControl):
    """One complete local planner and one native input owner per human tank."""
    def __init__(self, battle, controller=None):
        self.owner = self.battle = battle
        self.actor_kind = 'human'
        self.physical = PlayerObservation(self)
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
        self._init_mission_state()
        self._requested_shell = None
        self._equipment_views = {}
        self._equipment_pending = {}
        self._owned_governor = None
        self._siege_pending = None
        self._recent_projectiles = {}
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
        self._strategic_result = None
        self._strategic_due = 0.
        self._strategic_contact_signature = None
        self._last_committed_shot_seq = 0
        self._profile_window = None
        self.combat_stop = CombatStop(self)
        self.siege_aim = ActualSiegeAim(self)
        self._siege_aim_candidate = None

    @property
    def gun(self):
        return self.owner._gun_state

    @property
    def state(self):
        return self.engine.states.get(self.actor_id) if self.engine is not None else None



















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
        self.actor_id = shared_runtime.BotRuntime._human_planner_id(battle.client.player_id)
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
            bounds=bounds, arena_bounds=bounds,
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
        self.attack_policy = AttackPolicy(self, ordered=not self.siege_capable(), ordered_he=True)
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
        self._start_mission_lifecycle(mission)
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
        if getattr(self, 'artillery_selection', None) is not None:
            self.artillery_selection.reset()
        self._artillery_ammo = None
        self.combat_stop.reset()
        self.siege_aim.reset()
        self._siege_aim_candidate = None
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
        self._native_hull_laying = None
        self._cancel_mission(reason)
        self._strategic_due = 0.
        self._profile_window = None
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
            from ..ai.planner import build_vehicle_profile
            profile = build_vehicle_profile(descriptor)
        tag = profile.get('class_tag') or next((tag for tag in bot_tactics.CLASSES if tag in tags), 'unknown')
        profile['class_tag'] = tag
        shape = shared_runtime._collision_shape(descriptor)
        half_length, half_width = shared_runtime._hull_dimensions(descriptor)
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
                agent = self.engine.adapter.roster.register_profile(
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
        self._observe_loading_completion()
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
            if now - observed_input['at'] > shared_traffic.ORDER_FRESH_SECONDS:
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
            # Match the original observer's strategic lane lifetime. The
            # 0.2s firing cache is not a one-hertz target-admission clock:
            # using it here can miss every clear-lane publication forever.
            fresh_lane = lane is not None and 0. <= now - lane[0] <= (
                shared_runtime.SHOT_LANE_REFRESH_SECONDS + self.engine._control_seconds + 1.e-9)
            clear = fresh_lane and lane[1]
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
                armor=nominal_armor(target),
                shootable_by_bot_ids=sorted(set(peers + ([self.actor_id] if clear else []))),
                threatened_bot_ids=threatened,
                # A current negative receipt is a known blocked lane, not an
                # unfinished observation that may renew a stationary hold.
                pending_lane_by_bot_ids=[] if fresh_lane else [self.actor_id]))
        self.planner.report_contacts(contacts, known, now)
        # A peer's certified firing lane can disappear inside the one-second
        # strategic interval. Replan that *change* immediately so copied
        # target coordination does not continue relying on a stale ally; native
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
        order = self._accept_task_order(order, now)
        self.engine._apply_orders(dict(bot_orders=[order], bot_order_revision=int(result.get('revision', 0))))
        return order


    def observe_team_observation(self, message, now):
        """Consume accepted public peer lane evidence without owning a peer.

        The server already relays these exact fields to foreground clients.
        They support the copied target assignment, never this player's
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
                until=float(now) + min(remaining, shared_runtime.SHOT_LANE_SECONDS),
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
        return self.mission_team_orders(rows)

    def _mission_ready(self):
        return self.engine is not None or self.attach()

    def _mission_unavailable_reason(self):
        return 'player_unavailable'

    def _mission_bounds(self):
        return getattr(self.owner, '_arena_bounds', None)

    def _mission_manifest(self):
        return self._manifest

    def _mission_motion(self):
        return foreground_motion(self.owner)

    def _mission_battle_result(self):
        result = getattr(self.owner, '_battle_result', None)
        if result is None:
            result = (getattr(self.owner, '_last_snapshot', None) or {}).get('battle_result')
        return result

    def _release_mission_inputs(self):
        self.weapon.close()
        self._neutral_drive()

    def _acquire_mission_inputs(self):
        return self.weapon.bind()


    def _send_drive(self):
        if not self.active or 'drive' not in self.features:
            return
        sender = self.owner._sender
        command = self.guard_mission_controls(self._last_order)
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
        # identify which foreground/shared operation dominates the render frame.
        stages = getattr(self.owner, '_local_frame_stages', None)
        marker = _PROFILE_CLOCK() if stages is not None else None
        self._observe(now)
        marker = self._profile_stage(stages, marker, 'player_observe')
        if not self.state['alive']:
            self.stop('actor_destroyed')
            return self.status()
        if not self._advance_mission_retry(now):
            return self.status()
        # The foreground owns an independent one-actor quota. Its following
        # engine.update uses the same callback id and cannot refill it.
        self.engine._begin_evaluation_frame(now)
        marker = self._profile_stage(stages, marker, 'player_attack')
        self._planner_order(now)
        marker = self._profile_stage(stages, marker, 'player_strategy')
        self._observe_traffic(now)
        self.geometry._artillery.advance(now, 4, self.geometry._artillery_arc_probe)
        marker = self._profile_stage(stages, marker, 'player_traffic')
        # The common engine owns navigation, physical recovery, traffic,
        # hull aiming, firing gates and route handoffs. This binding advances
        # only its foreground actor and never asks a BOT worker to decide.
        self.engine.update(float(dt), float(now), list(self._players))
        marker = self._profile_stage(stages, marker, 'player_shared_control')
        # Only the foreground actor may have changed in this shared control
        # slice. Preserve the native-source correction without re-reading,
        # re-registering and re-serializing every unrelated public peer.
        self._observe_local(now)
        self._sync_weapon_observation()
        self._sync_equipments()
        marker = self._profile_stage(stages, marker, 'player_refresh')
        if self.active and self.generation == token and self._binding() == self._identity:
            self._send_drive()
            if self._live(token) and 'fire' in self.features and (
                    self.combat_stop.active or
                    (self.state.get('profile') or {}).get('class_tag') == 'SPG'):
                self._apply_shell_intent()
            if not self._live(token):
                return self.status()
            self._observe_mission(now)
            if self._live(token) and 'fire' in self.features:
                if self.combat_stop.active and not self.combat_stop.waiting_for_siege():
                    self._prepare_next_shell(now)
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
        self._artillery_ammo = None
        if self.active and self.gun is gun:
            pending = self.owner._local_player_burst or self.owner._local_fire_intent
            name = 'NEXT_SHELLS' if code == getattr(settings, 'NEXT_SHELLS', None) else 'CURRENT_SHELLS'
            self._manual_shell = (gun, pending, name)
            if name == 'CURRENT_SHELLS':
                self.attack_policy.load_started(gun.shot_index)
            self._record_shell('manual', name, gun.pending_index if name == 'NEXT_SHELLS'
                               else gun.shot_index, True, 'manual_input', force=True)






    def authorize_trigger(self, context, entity, gun, shot_ray):
        if not self.active or 'fire' not in self.features or self._binding() != self._identity:
            return 'automatic_control_unavailable'
        if self._mission_brakes():
            return 'mission_owns_stopped_input'
        if entity is not self.entity or gun is not self.gun:
            return 'native_weapon_owner_changed'
        if (not context.get('artillery') and
                (not self.combat_stop.active or
                 not self.combat_stop.contains(context.get('target')))):
            return 'original_combat_not_admitted'
        if not self._siege_fire_ready():
            return 'siege_mode_not_ready'
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
        position = dict(self.combat_stop.receipt)
        siege_aim = self.siege_aim.status()
        gun, state = self.gun, self.state
        first_edge = self.controller.last_fire_failure
        key = (policy['phase'], policy['reason'], policy['shell'], policy['target'],
               policy['sample'], policy['next_shell'], policy['next_target'], policy['next_sample'],
               policy['next_status'], policy['background_coverage'],
               state.get('gun_aligned'), self.weapon.verified, gun.shot_index, gun.pending_index,
               self._last_committed_shot_seq, (self._shell_receipt or {}).get('at'),
               state.get('siege_state'), state.get('_siege_intent'),
               policy['line'], policy['mechanical'], first_edge,
               navigation.get('owner'), navigation.get('reason'),
               position.get('episode_id'), position.get('status'), position.get('reason'),
               siege_aim.get('status'), siege_aim.get('reason'))
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
            siege_route=siege_route, siege_aim=siege_aim, firing_position=position,
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
        if receipt.get('source') == 'foreground_enemy_translation':
            # A legacy collision receipt cannot acquire an enemy or start a
            # combat stop. The original observer/planner admits combat.
            return
        if rotation_refused:
            receipt['rotation_refused'] = True
        self._last_navigation = receipt
        self.engine._decision_cache.pop(self.actor_id, None)
        self.engine._motion_probe_cache.pop(self.actor_id, None)
        if not rotation_refused:
            self.engine._invalidate_realised_motion(self.actor_id, heading, 'foreground_contact')
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
                self._artillery_shot_committed(event, committed)
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
        player_id = getattr(getattr(self.owner, 'client', None), 'player_id', None)
        if (event.get('shooter_kind') == 'player' and
                player_id is not None and event.get('shooter_id') == player_id):
            self.artillery_shot_terminal(event)
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

    def trigger_terminated(self, context):
        self._discard_trigger_next_shell(context.get('load_plan'))

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
