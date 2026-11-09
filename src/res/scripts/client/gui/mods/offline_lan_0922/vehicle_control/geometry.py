from __future__ import print_function

from gui.mods.offline_lan_0922.native_input_diagnostics import detailed_enabled

import json

import math

import sys

import time

from gui.mods.offline_lan_0922 import water_surfaces

from gui.mods.offline_lan_0922.native_navigation_query import (
    NAVIGABLE_WATER_DEPTH, NAVIGATION_MAX_GRADE)

from gui.mods.offline_lan_0922.vehicle_physics import ground_pose_for_yaw

from gui.mods.offline_lan_0922.entities.remote_vehicle import (
    PROJECTILE_VISUAL_START_MAX_DIFF, RemoteVehicleFactory,
    _collide_vehicle_evidence_at_matrix, prepare_vehicle_collision_at_matrix,
    _component_aim_angles, _native_ypr, _pose_components, collide_vehicle_at_matrix,
    encode_damage_sticker, pose_animation_writes,
    reset_pose_animation_writes,
    vehicle_blast_probe_points_at_matrix, vehicle_target_bounds_at_matrix)

from gui.mods.offline_lan_0922.projectile_runtime import (
    PROJECTILE_BROADPHASE_RADIUS, PROJECTILE_MAX_SUBSTEP_SECONDS, lerp3,
    ideal_reflection_velocity, ricochet_departure_origin,
    point_in_expanded_segment_bounds, point_segment_distance_sq,
    projectile_range_distance, trajectory_position)

from gui.mods.offline_lan_0922.collision_flags import VEHICLE_SKIP_FLAGS

from gui.mods.offline_lan_0922.native_world import readonly_queries

from gui.mods.offline_lan_0922.worker_diagnostics import (
    WorkerCombatDiagnostics, PROBE_KINDS, timed, call as timed_call, observed_ray,
    observed_call, observed)

from gui.mods.offline_lan_0922 import ballistics
from gui.mods.offline_lan_0922 import burst_mechanics
from gui.mods.offline_lan_0922 import combat_rules
from gui.mods.offline_lan_0922 import critical_damage
from gui.mods.offline_lan_0922 import descriptor_donation
from gui.mods.offline_lan_0922 import destructibles_compat
from gui.mods.offline_lan_0922 import device_damage
from gui.mods.offline_lan_0922 import effective_params
from gui.mods.offline_lan_0922 import equipment_mechanics
from gui.mods.offline_lan_0922 import gun_mechanics
from gui.mods.offline_lan_0922 import hull_aiming
from gui.mods.offline_lan_0922 import protocol_primitives as lan_protocol
from gui.mods.offline_lan_0922 import gc_sweep
from gui.mods.offline_lan_0922 import graphics_probe
from gui.mods.offline_lan_0922 import native_input_diagnostics
from gui.mods.offline_lan_0922 import physics_audit
from gui.mods.offline_lan_0922 import loadout as loadout_law
from gui.mods.offline_lan_0922 import world_census
from gui.mods.offline_lan_0922 import prebaked_destructibles
from gui.mods.offline_lan_0922 import prebaked_foliage
from gui.mods.offline_lan_0922 import prebaked_navigation
from gui.mods.offline_lan_0922 import native_mapping_mask
from gui.mods.offline_lan_0922 import native_math
from gui.mods.offline_lan_0922 import shot_geometry
from gui.mods.offline_lan_0922 import spotting
from gui.mods.offline_lan_0922 import tank_collision
from gui.mods.offline_lan_0922 import track_damage
from gui.mods.offline_lan_0922 import vehicle_stack
from gui.mods.offline_lan_0922 import vehicle_blacklist
from gui.mods.offline_lan_0922 import vehicle_configuration
from gui.mods.offline_lan_0922 import vehicle_physics
from gui.mods.offline_lan_0922 import water_geometry
from gui.mods.offline_lan_0922 import world_collision

SIGHT_COLLISION_FILTER_SECONDS = 0.25

OPTIONAL_WARNING_TEXT_LIMIT = 160

DESTRUCTIBLE_POSE_MAX_ANGLE_STEP = math.pi / 36.0

DESTRUCTIBLE_POSE_MAX_SWEEP_STEPS = 16

DESTRUCTIBLE_CONTACT_TOKEN_LIMIT = 64

BOT_WATER_ESCAPE_DEEPEN_EPSILON = 0.10

GROUND_PLANE_EPSILON = 0.35

_PROFILE_CLOCK = getattr(time, 'perf_counter', None)

_SUPPORT_PROFILE_CLOCK = _PROFILE_CLOCK

def _number(value, default=0.0):
    try:
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return float(default)
        return value
    except (TypeError, ValueError):
        return float(default)

def _angle_delta(current, target):
    return (target - current + math.pi) % (2.0 * math.pi) - math.pi

class _DestructibleSweepHitTester(object):
    """Expose one conservative interval bbox through the pinned sensor ABI."""

    def __init__(self, bbox):
        self.bbox = bbox

def _trig_interval_extrema(cosine_factor, sine_factor, start, end):
    """Return exact extrema of ``a*cos(angle) + b*sin(angle)`` on an interval."""
    start = float(start)
    end = float(end)
    if end < start:
        start, end = end, start
    values = [
        cosine_factor * math.cos(start) + sine_factor * math.sin(start),
        cosine_factor * math.cos(end) + sine_factor * math.sin(end),
    ]
    stationary = math.atan2(sine_factor, cosine_factor)
    first = int(math.ceil((start - stationary) / math.pi))
    last = int(math.floor((end - stationary) / math.pi))
    for offset in range(first, last + 1):
        angle = stationary + offset * math.pi
        values.append(
            cosine_factor * math.cos(angle) +
            sine_factor * math.sin(angle))
    return min(values), max(values)

def _destructible_rotation_interval_bbox(bbox, half_angle, pivot_offset=0.0):
    """Enclose every rotation of ``bbox`` within ``[-half_angle,+half_angle]``.

    The returned box is expressed in the midpoint hull frame.  Its horizontal
    bounds are analytical extrema over all four original corners, so the cover
    cannot open a gap between sampled yaws.  This is a swept-volume broadphase,
    not a finite ray approximation.
    """
    operation = getattr(native_math._load(), 'rotation_envelope', None)
    if callable(operation):
        result = native_math.call('rotation_envelope', bbox, half_angle, pivot_offset)
        if result is not None:
            return result
    return _reference_rotation_interval_bbox(bbox, half_angle, pivot_offset)

def _reference_rotation_interval_bbox(bbox, half_angle, pivot_offset=0.0):
    minimum, maximum = bbox[:2]
    half_angle = abs(float(half_angle))
    horizontal_x = []
    horizontal_z = []
    for local_x in (float(minimum[0]), float(maximum[0])):
        for local_z in (float(minimum[2]), float(maximum[2])):
            low, high = _trig_interval_extrema(
                local_x - pivot_offset, local_z, -half_angle, half_angle)
            horizontal_x.extend((low + pivot_offset, high + pivot_offset))
            low, high = _trig_interval_extrema(
                local_z, pivot_offset - local_x, -half_angle, half_angle)
            horizontal_z.extend((low, high))
    return (
        (min(horizontal_x), float(minimum[1]), min(horizontal_z)),
        (max(horizontal_x), float(maximum[1]), max(horizontal_z)),
    )

def _trig_linear_interval_minimum(a, b, start, end, drift):
    """Exact min of a*cos(theta)+b*sin(theta)+drift*t on t in [0,1]."""
    delta = end-start
    values = [a*math.cos(start)+b*math.sin(start),
              a*math.cos(end)+b*math.sin(end)+drift]
    radius = math.hypot(a, b)
    if abs(delta)*radius <= 1.0e-15:
        return min(values)
    rhs = -drift/(delta*radius)
    if -1.0 <= rhs <= 1.0:
        phase = math.atan2(-a, b)
        alpha = math.acos(rhs)
        lo, hi = min(start, end), max(start, end)
        for root in (phase+alpha, phase-alpha):
            first = int(math.ceil((lo-root)/(2.0*math.pi)))
            last = int(math.floor((hi-root)/(2.0*math.pi)))
            for cycle in range(first, last+1):
                angle = root+cycle*2.0*math.pi
                t = (angle-start)/delta
                if 0.0 <= t <= 1.0:
                    values.append(a*math.cos(angle)+b*math.sin(angle)+drift*t)
    return min(values)

def _rotation_departing_contact(position, bbox, start_yaw, end_yaw,
                                pitch=0.0, roll=0.0, previous_contacts=None,
                                translation=(0.0, 0.0), pivot_offset=0.0):
    if not callable(getattr(native_math._load(), 'rotation_departure', None)):
        return _reference_rotation_departing_contact(
            position, bbox, start_yaw, end_yaw, pitch, roll,
            previous_contacts, translation, pivot_offset)
    low, high = bbox[:2]
    pose_y = world_collision._hull_pose_y(pitch, roll)
    angles = (float(start_yaw), float(start_yaw) + _angle_delta(start_yaw, end_yaw))
    pivot = float(pivot_offset or 0.0)
    drivable_defaults = getattr(world_collision._drivable_surface, 'func_defaults',
        getattr(world_collision._drivable_surface, '__defaults__', None))
    gradient = drivable_defaults[0]
    def departing(collision):
        point, normal = collision[:2]
        result = native_math.call('rotation_departure', position, low, high,
            angles, pose_y, translation, pivot,
            (point.x, point.y, point.z), (normal.x, normal.y, normal.z),
            gradient)
        if result is None:
            return _reference_rotation_departing_contact(
                position, bbox, start_yaw, end_yaw, pitch, roll,
                previous_contacts, translation, pivot_offset)(collision)
        improves, inside = result
        if not improves or inside:
            return bool(improves)
        # Preserve the lazy exact-footprint witness and its engine query order.
        for old_point, old_normal in (previous_contacts()
                if callable(previous_contacts) else ()):
            alignment = (normal.x * old_normal.x + normal.y * old_normal.y +
                         normal.z * old_normal.z)
            difference = ((point.x - old_point.x) * normal.x +
                          (point.y - old_point.y) * normal.y +
                          (point.z - old_point.z) * normal.z)
            if alignment >= 0.9999 and abs(difference) <= 0.001:
                return True
        return False
    return departing

def _reference_rotation_departing_contact(position, bbox, start_yaw, end_yaw,
                                pitch=0.0, roll=0.0, previous_contacts=None,
                                translation=(0.0, 0.0), pivot_offset=0.0):
    """Permit only reduced penetration of a face already inside this body.

    A replacement can appear inside an occupied hull. Probing its enclosing
    yaw box then blocks both turn directions forever. Test the complete
    analytical corner sweep against that contact plane: the end must improve
    clearance, and no intermediate corner may go deeper than the start.
    The caller recasts after this individual hit to retain every other wall.
    """
    low, high = bbox[:2]
    pose_y = world_collision._hull_pose_y(pitch, roll)
    end_yaw = float(start_yaw) + _angle_delta(start_yaw, end_yaw)
    sine, cosine = math.sin(start_yaw), math.cos(start_yaw)
    pivot_offset = float(pivot_offset or 0.0)

    def departing(collision):
        point, normal = collision[:2]
        if normal.y < -0.2 or abs(pose_y[1]) < 0.1:
            return False
        dx, dy, dz = (point.x - position[0], point.y - position[1],
                      point.z - position[2])
        x, z = dx * cosine - dz * sine, dx * sine + dz * cosine
        y = (dy - x * pose_y[0] - z * pose_y[2]) / pose_y[1]
        inside = all(low[i] - 0.001 <= value <= high[i] + 0.001
                     for i, value in enumerate((x, y, z)))
        before, after, swept = [], [], []
        plane_travel = translation[0]*normal.x + translation[1]*normal.z
        # A non-centre track turn moves the chassis centre around the planted
        # track.  Folding that exact arc into each corner's trigonometric
        # coefficients lets an already occupied wall plane release when the
        # track-pivot turn reduces penetration.  Previously pivot turns disabled
        # this departing-contact proof entirely, so a hull that touched a wall
        # could have both A/D directions vetoed forever.
        pivot_constant = pivot_offset * (
            normal.x * cosine - normal.z * sine)
        for cx in (low[0], high[0]):
            for cy in (low[1], high[1]):
                for cz in (low[2], high[2]):
                    # Rotating around local X=pivot_offset is equivalent to
                    # rotating (cx-pivot_offset, cz) about the fixed pivot and
                    # adding the pivot's world-plane constant.
                    pivot_x = cx - pivot_offset
                    a = normal.x * pivot_x + normal.z * cz
                    b = normal.x * cz - normal.z * pivot_x
                    height = normal.y * (cx * pose_y[0] +
                                        cy * pose_y[1] + cz * pose_y[2])
                    before.append(a * cosine + b * sine +
                                  pivot_constant + height)
                    after.append(a * math.cos(end_yaw) +
                                 b * math.sin(end_yaw) + pivot_constant +
                                 height + plane_travel)
                    swept.append(_trig_linear_interval_minimum(
                        a, b, start_yaw, end_yaw, plane_travel) +
                        pivot_constant + height)
        support_slide = (world_collision._drivable_surface(collision) and
                         min(after) >= min(before) - 1.0e-8)
        improves = ((min(after) > min(before) + 1.0e-8 or support_slide) and
                    min(swept) >= min(before) - 1.0e-8)
        if not improves or inside:
            return improves
        # The enclosing interval lane can sit outside the old side while
        # still striking the same already-penetrated wall. Require another
        # native hit from the EXACT starting footprint to establish that
        # contact plane. An outside point alone cannot grant passage.
        for old_point, old_normal in (previous_contacts()
                if callable(previous_contacts) else ()):
            alignment = (normal.x * old_normal.x + normal.y * old_normal.y +
                         normal.z * old_normal.z)
            difference = ((point.x - old_point.x) * normal.x +
                          (point.y - old_point.y) * normal.y +
                          (point.z - old_point.z) * normal.z)
            if alignment >= 0.9999 and abs(difference) <= 0.001:
                return True
        return False
    return departing

def _destructible_posed_bbox(bbox, pitch=0.0, roll=0.0):
    """Enclose one height-posed body in its zero-yaw collision frame.

    #1513's horizontal lanes retain the complete yaw-only X/Z footprint and
    apply pitch/roll only to their height.  Pose that native collision shear
    once before the analytical yaw interval, so a rotating sweep keeps the
    raised nose/side without shrinking its horizontal coverage or applying
    pitch and roll twice in the catalog resolver.
    """
    minimum, maximum = bbox[:2]
    cos_pitch = math.cos(float(pitch))
    sin_pitch = math.sin(float(pitch))
    cos_roll = math.cos(float(roll))
    sin_roll = math.sin(float(roll))
    right_y = cos_pitch * sin_roll
    up_y = cos_pitch * cos_roll
    forward_y = -sin_pitch
    points = []
    for x in (float(minimum[0]), float(maximum[0])):
        for y in (float(minimum[1]), float(maximum[1])):
            for z in (float(minimum[2]), float(maximum[2])):
                points.append((
                    x,
                    right_y * x + up_y * y + forward_y * z,
                    z,
                ))
    return (
        tuple(min(point[axis] for point in points) for axis in range(3)),
        tuple(max(point[axis] for point in points) for axis in range(3)),
    )

def _destructible_sweep_descriptor(descriptor, bbox):
    """Retain kinetic inputs while replacing only the sensor's hull bbox."""
    physics = (descriptor.get('physics') if isinstance(descriptor, dict) else
               getattr(descriptor, 'physics', None))
    return {
        'physics': physics,
        'hull': {'hitTester': _DestructibleSweepHitTester(bbox)},
    }

def _destructible_world_sweep_descriptor(descriptor, bbox):
    """Expose one complete body envelope to the native world-lane probe.

    ``world_collision`` normally unions the mounted hull and chassis itself.
    A rotation slice has already done that work and analytically enlarged the
    result for every yaw in its interval, so present the same box as both
    components at a zero mount offset.  Native collision filtering still owns
    the ray: accepted 73--85 skins are skipped, while damaged-model 87--100
    BSPs and unrelated backing walls remain solid.
    """
    physics = (descriptor.get('physics') if isinstance(descriptor, dict) else
               getattr(descriptor, 'physics', None))
    hit_tester = _DestructibleSweepHitTester(bbox)
    return world_collision.PreparedBodySweep({
        'physics': physics,
        'hull': {'hitTester': hit_tester},
        'chassis': {
            'hitTester': hit_tester,
            'hullPosition': (0.0, 0.0, 0.0),
        },
    })

class _ProjectileCollisionAppearance(object):
    """Aim matrices frozen with one historical collision pose."""

    def __init__(self, math_module, descriptor, turret_yaw, gun_pitch):
        turret_yaw, gun_pitch = _component_aim_angles(
            descriptor, turret_yaw, gun_pitch)
        self.turretMatrix = math_module.Matrix()
        self.turretMatrix.setRotateYPR((float(turret_yaw), 0.0, 0.0))
        self.gunMatrix = math_module.Matrix()
        self.gunMatrix.setRotateYPR((0.0, float(gun_pitch), 0.0))

class _ProjectileCollisionTarget(object):
    """Read-only target view shared by armour and critical-hit geometry."""

    def __init__(self, source, descriptor, matrix, position, appearance,
                 math_module, chassis_matrix=None):
        self._source = source
        self.typeDescriptor = descriptor
        self.matrix = matrix
        self.position = position
        self.appearance = appearance
        self._math = math_module
        self._chassis_matrix = chassis_matrix

    def __getattr__(self, name):
        return getattr(self._source, name)

    def getComponents(self):
        if self.matrix is None:
            return ()
        components = _pose_components(self, self._math)
        if self._chassis_matrix is not None:
            # Interior consumers enter through inverse(body). The chassis
            # alone belongs to the separate hydraulic ground frame, just as
            # the exterior armour query does.
            to_chassis = self._math.Matrix(self._chassis_matrix)
            to_chassis.invert()
            to_chassis.preMultiply(self.matrix)
            components[0][1].preMultiply(to_chassis)
        return components

def _field(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)

def _xyz(value):
    if isinstance(value, dict):
        return (_number(value.get('x')), _number(value.get('y')),
                _number(value.get('z')))
    try:
        return (_number(value[0]), _number(value[1]), _number(value[2]))
    except (TypeError, IndexError):
        return (_number(getattr(value, 'x', 0.0)),
                _number(getattr(value, 'y', 0.0)),
                _number(getattr(value, 'z', 0.0)))


class SharedBattleGeometry(object):
    """Shared geometry callbacks; each actor binding supplies its own local state."""

    @staticmethod
    def _bounded_failure_reason(error, limit=OPTIONAL_WARNING_TEXT_LIMIT):
        """Return one single-line diagnostic safe for logs and the wire."""
        try:
            message = str(error)
        except Exception:
            message = error.__class__.__name__
        message = ' '.join(message.split())
        if not message:
            message = error.__class__.__name__
        return message[:max(1, int(limit))]

    def _optional_feature_enabled(self, feature):
        disabled = getattr(self, '_disabled_optional_features', None)
        if disabled is None:
            disabled = set()
            self._disabled_optional_features = disabled
        return str(feature) not in disabled

    def _warn_optional_failure(self, feature, error, disable=True):
        """Log one bounded warning per feature and round."""
        feature = str(feature)
        disabled = getattr(self, '_disabled_optional_features', None)
        if disabled is None:
            disabled = set()
            self._disabled_optional_features = disabled
        if disable:
            disabled.add(feature)
        reported = getattr(self, '_optional_failures_reported', None)
        if reported is None:
            reported = set()
            self._optional_failures_reported = reported
        if feature in reported:
            return False
        reported.add(feature)
        outcome = ('disabled for this round' if disable else
                   'degraded for this round')
        sys.stdout.write(
            '[Offline LAN 0.9.22] optional %s %s: %s\n' % (
                feature, outcome, self._bounded_failure_reason(error)))
        return True

    def _clock(self):
        function = getattr(self._runtime.bigworld, 'time', None)
        if callable(function):
            try:
                return float(function())
            except Exception:
                pass
        return time.time()

    def _server_entity(self, entity_id):
        """Resolve authority state without widening the stock AOI view."""
        if self._remote_factory is not None:
            entity = self._remote_factory.get(entity_id)
            if entity is not None:
                return entity
        return self._runtime.bigworld.entity(entity_id)

    @staticmethod
    def _destructible_drive_speed_cap(descriptor, physics, speed,
                                     travel_descriptor=None):
        """Keep powered contact eligibility independent of Siege gearing.

        The port already uses a drive cap to admit a powered exact contact
        which cannot accelerate through an intact prop. Using the active
        Siege limit here made that same vehicle unable to push over the prop
        in low gear. Read its mounted travel limit for this gate only; actual
        motion, impact speed, hull shape and native health/scale laws still
        belong to the active descriptor. Ordinary vehicles retain their
        effective cap, and an unavailable drive limit is never fabricated.
        """
        return vehicle_physics.destructible_drive_speed_cap(
            descriptor, physics, speed, travel_descriptor)

    def _bot_destructible_travel_descriptor(self, bot_id):
        pair = getattr(self._bots, '_descriptor_pairs', {}).get(int(bot_id))
        return pair[0] if pair is not None and pair[1] is not None else None

    def _vector(self, position):
        return self._runtime.math.Vector3(
            float(position[0]), float(position[1]), float(position[2]))

    def _ground_filter(self, x, z):
        context = getattr(self,'_stack_context',None)
        batch = context.get('queries') if context else None
        if batch is None:
            return self._ground_filter_impl(x, z)
        return batch.get('filter_prepare',('column',float(x),float(z)),
            self._ground_filter_impl,x,z)

    def _ground_filter_impl(self, x, z):
        """Build the #1513 fifth-argument filter for this ground column.

        Retail keeps a breakable destructible out of the vehicle's collision,
        so a crushed fence must not carry the suspension or the drive slope
        while its model waits for the hiding callback.
        """
        probe = getattr(
            self._destructibles, 'ground_collision_filter', None)
        if not callable(probe):
            return None
        # The worker already owns a synchronous collision-preparation scope.
        # Reuse its live per-cell member filter instead of rescanning the same
        # destructibles for every basic support/slope column. Custom providers
        # retain their original call path; the batch validates their identity.
        from gui.mods.offline_lan_0922 import destructibles_sensor
        scope = destructibles_sensor.__dict__.get('g_offh_destr_collision_preparation_scope')
        batch = (destructibles_sensor.ground_filter_batch_1513(probe)
                 if isinstance(scope,dict) else None)
        ground_filter = batch(x, z) if callable(batch) else probe(x, z)
        return ground_filter if callable(ground_filter) else None

    def _prepare_stack_target(self, state, entity):
        yaw = float(state.get('yaw',0.))
        matrix = self._ram_pose_matrix(_xyz(state),yaw,state.get('pitch',0.),state.get('roll',0.))
        chassis = self._ram_pose_matrix(_xyz(state),yaw,state.get('terrain_pitch',state.get('pitch',0.)),state.get('roll',0.))
        turret,gun = self._runtime.math.Matrix(),self._runtime.math.Matrix()
        turret.setRotateY(float(state.get('turret_yaw',state.get('aim_yaw',yaw)-yaw)))
        gun.setRotateX(float(state.get('gun_pitch',0.)))
        appearance = type('StackAim',(object,),{})()
        appearance.turretMatrix,appearance.gunMatrix = turret,gun
        target = vehicle_stack.CollisionPose(entity,appearance)
        prepared = prepare_vehicle_collision_at_matrix(target,matrix,self._runtime.math,chassis)
        return target,matrix,chassis,prepared

    def _stack_ground_hit(self, start, end, ground):
        context = getattr(self,'_stack_context',None)
        if not context:
            return ground
        batch = context.get('queries')
        if batch is None:
            from gui.mods.offline_lan_0922.support_queries import SupportQueries
            batch = context['queries'] = SupportQueries(_SUPPORT_PROFILE_CLOCK)
        return batch.call('roof_stage',self._stack_ground_hit_impl,start,end,ground)

    def _stack_ground_hit_impl(self, start, end, ground):
        context = getattr(self, '_stack_context', None)
        if not context:
            return ground
        x, top, z = _xyz(start)
        bottom = float(end.y)
        best = ground
        best_y = float(ground[0].y) if ground is not None else bottom
        for key, state, entity in context['candidates']:
            shape = state.get('collision_shape')
            if shape is None:
                shape = self._collision_shape(entity.typeDescriptor)
            dx, dz = x-state['x'], z-state['z']
            yaw = float(state.get('yaw', 0.0))
            if (abs(math.cos(yaw)*dx-math.sin(yaw)*dz) > shape[0]+0.5 or
                    abs(math.sin(yaw)*dx+math.cos(yaw)*dz) > shape[1]+0.5):
                continue
            try:
                batch = context.get('queries')
                if batch is None:
                    from gui.mods.offline_lan_0922.support_queries import SupportQueries
                    batch = context['queries'] = SupportQueries(_SUPPORT_PROFILE_CLOCK)
                pose_key = (key,id(entity),id(entity.typeDescriptor)) + tuple(
                    state.get(name) for name in ('x','y','z','yaw','pitch','roll',
                        'terrain_pitch','turret_yaw','aim_yaw','gun_pitch'))
                target,matrix,chassis,prepared = batch.get('matrix_prepare',pose_key,
                    self._prepare_stack_target,state,entity)
                hits = batch.get('roof',(pose_key,_xyz(start),_xyz(end)),
                    _collide_vehicle_evidence_at_matrix,target,matrix,start,end,self._runtime.math,
                    chassis_matrix=chassis,capture_query=False,prepared=prepared,diagnostic=batch)
                for hit in hits:
                    collision, normal = hit.collision, hit.worldNormal
                    if (collision.compName in ('gun','vehicleGun') or normal is None or
                            float(normal.y) <= 0.5):
                        continue
                    height = top-float(collision.dist)
                    actor = context['actor']
                    actor_shape = actor.get('collision_shape') or (0.0,0.0)
                    reach = (abs(math.sin(actor.get('pitch',0.0)))*actor_shape[1] +
                             abs(math.sin(actor.get('roll',0.0)))*actor_shape[0])
                    if height > actor['y']+reach+0.15:
                        continue
                    if not bottom <= height <= top or height <= best_y:
                        continue
                    best_y = height
                    best = (self._vector((x,height,z)), normal)
                    context['hits'].append((key, state, (x,height,z)))
                    context.setdefault('surfaces', []).append(dict(
                        carrier=list(key), point=(x,height,z), normal=_xyz(normal)))
                    # Keep the contact identity with the exact height query.
                    context['actor']['_stack_carrier'] = list(key)
                # Observe misses as well as admitted pressure. The previous
                # package logged only success, so it could not explain ejection.
                now = self._clock()
                log_times = getattr(self, '_stack_probe_times', None)
                if log_times is None:
                    log_times = self._stack_probe_times = {}
                pair = (context['actor'].get('kind','bot'),context['actor']['id'])+key
                if now >= log_times.get(pair,-1.e30):
                    log_times[pair] = now+1.
                    batch.call('probe_log',native_input_diagnostics.write_json_record,'VEHICLE STACK',dict(
                        phase='roof_probe', upper=list(pair[:2]),lower=list(key),
                        start=_xyz(start),end=_xyz(end),upper_pose=dict(
                            (name,context['actor'].get(name)) for name in
                            ('x','y','z','yaw','pitch','roll')),
                        lower_pose=dict((name,state.get(name)) for name in
                            ('x','y','z','yaw','pitch','roll')),
                        native_hits=[dict(component=h.collision.compName,
                            distance=h.collision.dist,
                            normal=_xyz(h.worldNormal) if h.worldNormal is not None else None)
                            for h in hits[:12]],
                        selected_carrier=context['actor'].get('_stack_carrier'),
                        selected_height=best_y if best is not None else None))
            except (AttributeError, IndexError, KeyError, TypeError, ValueError,
                    RuntimeError) as error:
                now = self._clock()
                if now >= getattr(self, '_stack_probe_log_at', -1.e30):
                    self._stack_probe_log_at = now+2.0
                    self._warn_optional_failure('vertical vehicle contact', error)
        return best

    def _collide_down(self, start, end, ground_filter):
        context = getattr(self,'_stack_context',None)
        batch = context.get('queries') if context else None
        if batch is None:
            ground = self._collide_static_down(start,end,ground_filter)
        else:
            batch.count('support_ray')
            batch.references.append(ground_filter)
            ground = batch.get('terrain',(_xyz(start),_xyz(end),id(ground_filter)),
                self._collide_static_down,start,end,ground_filter)
        return self._stack_ground_hit(start, end, ground)

    def _navigation_surface_observation(self, point, yaw):
        """Read a raw scene normal; never acquire or alter a support context.

        A raw surface can be a roof/object, not necessarily terrain. Preserve
        the witness and explicit query window rather than inventing flat ground.
        """
        start = (point[0], point[1]+8.0, point[2])
        end = (point[0], point[1]-30.0, point[2])
        result = dict(status='missing', ray_start=start, ray_end=end,
            source='raw_scene_surface', decision_input=False)
        hit = self._runtime.bigworld.wg_collideSegment(
            self._avatar.spaceID, self._vector(start), self._vector(end),
            VEHICLE_SKIP_FLAGS)
        if hit is None:
            return result
        position = tuple(float(hit[0][i]) for i in range(3))
        normal = tuple(float(hit[1][i]) for i in range(3))
        result.update(status='hit', hit=position, normal=normal)
        if normal[1] > 0.0001:
            angle = math.atan2(-(normal[0]*math.sin(yaw)+
                normal[2]*math.cos(yaw)), normal[1])
            result['directional_angle_degrees'] = math.degrees(angle)
        else:
            result['status'] = 'non_upward_surface'
        return result

    def _collide_static_down(self, start, end, ground_filter):
        """Vertical probe that skips the skin of an already broken item."""
        collide = getattr(self._destructibles, 'collide_motion_segment', None)
        if callable(collide):
            return collide(self._avatar.spaceID, start, end, ground_filter,
                           self._runtime.bigworld.wg_collideSegment,
                           'native.motion.ground')
        if ground_filter is None:
            return self._runtime.bigworld.wg_collideSegment(
                self._avatar.spaceID, start, end, VEHICLE_SKIP_FLAGS)
        return self._runtime.bigworld.wg_collideSegment(
            self._avatar.spaceID, start, end, VEHICLE_SKIP_FLAGS, ground_filter)

    def _ground_y(self, x, z, hint=0.0, allow_wide=False):
        """Find upward-facing support below rejected overhead surfaces.

        A gate underside can be inside the height band, or conceal a valid
        road while falling just outside it. Neither case is missing ground.
        Keep the existing near-hull range and a bounded layered query, so
        real bridge decks and slopes retain their previous placement.
        """
        ground_filter = self._ground_filter(x, z)
        start_y = float(hint) + 8.0
        end_y = float(hint) - 30.0
        for unused_layer in range(4):
            try:
                hit = self._collide_down(
                    self._vector((x, start_y, z)),
                    self._vector((x, end_y, z)), ground_filter)
                if hit is None:
                    break
                value = float(hit[0].y)
                if (-14.0 < value - float(hint) < 6.0 and
                        float(hit[1].y) > 0.0):
                    return value
                next_y = value - 0.05
                if not end_y < next_y < start_y:
                    break
                start_y = next_y
            except Exception:
                break
        if not allow_wide:
            return None
        from_y = max(1000.0, hint + 50.0)
        height = None
        for unused_layer in range(4):
            hit = self._collide_down(
                self._vector((x, from_y, z)),
                self._vector((x, -1000.0, z)), ground_filter)
            if hit is None:
                return None
            height = float(hit[0].y)
            below = self._collide_down(
                self._vector((x, height - 0.4, z)),
                self._vector((x, -1000.0, z)), ground_filter)
            if below is None or height - float(below[0].y) < 2.5:
                return height
            from_y = height - 0.4
        return height

    def _navigation_collision_filter(self, start, end):
        """Prepare planning geometry independently of physical crush permission."""
        prepare = getattr(self._destructibles,
                          'prepare_navigation_collision_filter', None)
        return prepare(start, end) if callable(prepare) else None

    def _collide_navigation(self, start, end, trace=None):
        """Plan against live geometry and release proved broken BSP skins."""
        collision_filter = self._navigation_collision_filter(start, end)
        if trace is not None:
            collision_filter = world_collision._trace_collision_filter(
                collision_filter, trace)
        collide = getattr(self._destructibles, 'collide_motion_segment', None)
        if callable(collide):
            # Merged original BSP keys may survive after an accepted prop is
            # hidden. Use the same bounded identity proof as physical motion;
            # intact neighbours, replacements and backing walls remain solid.
            return collide(self._avatar.spaceID, start, end, collision_filter,
                self._runtime.bigworld.wg_collideSegment,
                'native.navigation.ray')
        args = (self._avatar.spaceID, start, end, VEHICLE_SKIP_FLAGS)
        if collision_filter is not None:
            args += (collision_filter,)
        return observed_ray('native.navigation.ray',
                            self._runtime.bigworld.wg_collideSegment, *args)

    @staticmethod
    def _record_navigation_hit(trace, start, end, hit):
        """An incomplete diagnostic must never change a collision verdict."""
        trace.update(ray_start=_xyz(start), ray_end=_xyz(end))
        for index, name in ((0, 'hit'), (1, 'normal')):
            try:
                trace[name] = _xyz(hit[index])
            except (AttributeError, IndexError, TypeError, ValueError):
                pass

    @observed('navigation.height_columns')
    def _navigation_height_columns(self, x, z, low, high):
        """Enumerate static upward faces without choosing a navigation layer.

        Reuse the established navigation collision filter; no new BigWorld
        interface, support context, or actor/model collision exemption.
        """
        rows = []
        top = float(high)
        revision = getattr(getattr(self,'_destructibles',None),
            '_spatial_revision_1513',None)
        generation = ((self._avatar.spaceID,revision()) if callable(revision) else None)
        for unused in range(12):
            hit = self._collide_navigation(self._vector((x,top,z)),
                self._vector((x,float(low),z)))
            if hit is None:
                return dict(status='complete', surfaces=rows,generation=generation)
            p, n = _xyz(hit[0]), _xyz(hit[1])
            if p[1] > top+.001 or p[1] < low-.001:
                return dict(status='invalid_hit', surfaces=rows,generation=generation)
            if n[1] > .0001:
                rows.append(dict(point=p,normal=n,
                    navigation_water=self._water_depth(p)>NAVIGABLE_WATER_DEPTH))
            top = p[1]-.02
            if top <= low:
                return dict(status='complete',surfaces=rows,generation=generation)
        return dict(status='layer_limit',surfaces=rows,generation=generation)

    def _navigation_ground(self, x, z, hint_y=0.0):
        """Copy the 0.8.2 same-layer graph probe, including ford depth."""
        probe_top = float(hint_y) + 8.0
        probe_bottom = float(hint_y) - 18.0
        for unused_layer in range(3):
            try:
                ground_start = self._vector((x, probe_top, z))
                ground_end = self._vector((x, probe_bottom, z))
                hit = self._collide_navigation(ground_start, ground_end)
                if hit is None:
                    return None
                height = float(hit[0].y)
                normal_y = float(hit[1].y)
            except Exception:
                return None
            if (height <= float(hint_y) + 4.5 and
                    normal_y > 0.0):
                if self._water_depth((x, height, z)) > \
                        NAVIGABLE_WATER_DEPTH:
                    return None
                return height
            next_top = height - 0.05
            if not probe_bottom < next_top < probe_top:
                return None
            probe_top = next_top
        return None

    def _direction_probe(self, position, yaw, speed=0.0,
                         descriptor=None, maximum_distance=None,
                         corridor_half_width=None, native_capability=None,
                         body_pose=None):
        """Probe the admitted chassis corridor at two heights and distances."""
        if corridor_half_width is None:
            # Passive contact callers have no active-drive descriptor. They
            # supply the chassis projection across their displacement; ordinary
            # drive probes use the same admitted body as tank contact physics.
            try:
                corridor_half_width = (
                    self._collision_shape(descriptor)[0]
                    if descriptor is not None else 2.2)
            except (AttributeError, IndexError, TypeError, ValueError,
                    RuntimeError):
                return {'clear': False, 'collision': True,
                        'water': False, 'slope': 0.0}
        try:
            corridor_half_width = float(corridor_half_width)
        except (TypeError, ValueError):
            return {'clear': False, 'collision': True,
                    'water': False, 'slope': 0.0}
        if (corridor_half_width <= 0.0 or
                corridor_half_width != corridor_half_width or
                abs(corridor_half_width) == float('inf')):
            return {'clear': False, 'collision': True,
                    'water': False, 'slope': 0.0}
        x, y, z = _xyz(position)
        current_water = self._water_depth((x, y, z))
        wet_escape = current_water > NAVIGABLE_WATER_DEPTH
        far_distance = 20.0 if abs(float(speed or 0.0)) > 5.0 else 15.0
        if maximum_distance is not None:
            try:
                requested_distance = float(maximum_distance)
            except (TypeError, ValueError):
                return {'clear': False, 'collision': True,
                        'water': False, 'slope': 0.0}
            if (requested_distance != requested_distance or
                    abs(requested_distance) == float('inf')):
                return {'clear': False, 'collision': True,
                        'water': False, 'slope': 0.0}
            far_distance = min(
                far_distance, max(0.5, requested_distance))
        near_distance = min(8.0, far_distance)
        previous_y = y
        previous_distance = 0.0
        sine = math.sin(float(yaw))
        cosine = math.cos(float(yaw))
        lateral_x = cosine
        lateral_z = -sine
        # A banked body has different left/right support heights. Fixed world-Y
        # lanes can start inside that bank even when the forward exit is clear.
        # Construct the lanes in the occupied support plane, rather than pardon
        # a collision after it was returned. The existing grade/wall gates stay.
        def lateral_grade(normal):
            if normal is None:
                return 0.0
            normal = _xyz(normal)
            return (-(normal[0]*lateral_x+normal[2]*lateral_z)/normal[1]
                    if normal[1] > .0001 else 0.0)
        posed_lanes = body_pose is not None
        start_lateral_grade = 0.0
        if posed_lanes:
            from gui.mods.offline_lan_0922.tank_collision import pose_axes
            start_lateral_grade = lateral_grade(pose_axes(*body_pose)[1])
        end_lateral_grade = start_lateral_grade
        # Keep the sign of the steepest sampled grade.  ``longitudinal_step``
        # needs it to distinguish climbing from descending; taking ``abs``
        # here made every clear descent behave like an uphill pull.
        maximum_slope = 0.0
        # Match the continuous-slope admission used by navigation. The old
        # asymmetric 0.48/-0.38 gate rejected an already planned descent and
        # fed a false blocked edge into recovery. Keep the same two samples,
        # but let their vertical casts cover the whole admitted grade.
        grade_limit = NAVIGATION_MAX_GRADE
        for height, distance in (
                (0.7, near_distance), (1.5, far_distance)):
            nx = x + sine * distance
            nz = z + cosine * distance
            run = distance - previous_distance
            # A capped local edge can put both ray heights at the same XZ.
            # Reuse that support sample: a second native cast from a shifted
            # origin can differ by float32 rounding, and a zero-length segment
            # has no slope against which to compare even that tiny difference.
            next_y = previous_y
            if run > 0.0:
                probe_up = max(4.5, run * grade_limit + 0.02)
                probe_down = max(5.0, run * grade_limit + 0.02)
                ground_trace = {}
                try:
                    ground_start = self._vector((nx, previous_y + probe_up, nz))
                    ground_end = self._vector((nx, previous_y - probe_down, nz))
                    ground = (self._collide_navigation(ground_start, ground_end, ground_trace)
                              if descriptor is not None else self._collide_down(
                                  ground_start, ground_end, self._ground_filter(nx, nz)))
                except Exception:
                    return {'clear': False, 'collision': True,
                            'water': False, 'slope': 99.0,
                            'slope_valid': False, 'probe_failed': True,
                            'reason': 'planning_ground_query_failed'}
                if ground is None:
                    return {'clear': False, 'collision': False,
                            'water': False, 'slope': 99.0,
                            'slope_valid': False,
                            'reason': 'planning_ground_missing'}
                next_y = float(ground[0].y)
                if posed_lanes and len(ground) > 1:
                    end_lateral_grade = lateral_grade(ground[1])
                water_depth = self._water_depth((nx, next_y, nz))
                if (wet_escape and
                        water_depth > current_water +
                        BOT_WATER_ESCAPE_DEEPEN_EPSILON):
                    return {'clear': False, 'collision': False,
                            'water': True, 'slope': 0.0}
                if not wet_escape and water_depth > NAVIGABLE_WATER_DEPTH:
                    return {'clear': False, 'collision': False,
                            'water': True, 'slope': 0.0}
                delta = next_y - previous_y
                slope = delta / max(0.1, run)
                if abs(slope) > abs(maximum_slope):
                    maximum_slope = slope
                if abs(delta) > run * grade_limit:
                    self._record_navigation_hit(
                        ground_trace, ground_start, ground_end, ground)
                    ground_trace['previous_y'] = previous_y
                    return {'clear': False, 'collision': False,
                            'water': False, 'slope': slope,
                            'reason': 'planning_grade', 'native_trace': ground_trace}
            for offset in (-corridor_half_width, 0.0, corridor_half_width):
                ray_start = self._vector((
                    x + lateral_x * offset, y + height + offset*start_lateral_grade,
                    z + lateral_z * offset))
                ray_end = self._vector((
                    nx + lateral_x * offset, next_y + height + offset*end_lateral_grade,
                    nz + lateral_z * offset))
                collision_trace = {}
                try:
                    collision = (
                        self._collide_navigation(ray_start, ray_end, collision_trace)
                        if descriptor is not None else
                        self._runtime.bigworld.wg_collideSegment(
                            self._avatar.spaceID, ray_start, ray_end,
                            VEHICLE_SKIP_FLAGS))
                except Exception:
                    return {'clear': False, 'collision': True,
                            'water': False, 'slope': slope,
                            'reason': 'planning_probe_failed', 'probe_failed': True}
                if collision is not None:
                    self._record_navigation_hit(
                        collision_trace, ray_start, ray_end, collision)
                    collision_trace.update(body_pose=body_pose,
                        lane_offset=offset, lane_height=height,
                        start_lateral_grade=start_lateral_grade,
                        end_lateral_grade=end_lateral_grade,
                        posed_lanes=posed_lanes)
                    return {'clear': False, 'collision': True,
                            'water': False, 'slope': slope,
                            'reason': 'planning_collision', 'native_trace': collision_trace}
            previous_y = next_y
            previous_distance = distance
        result = {'clear': True, 'collision': False,
                  'water': False, 'slope': maximum_slope}
        if posed_lanes:
            result.update(body_pose=body_pose, posed_lanes=True,
                start_lateral_grade=start_lateral_grade,
                end_lateral_grade=end_lateral_grade)
        return result

    def _direction_world_receipt(self, position, travel_yaw, signed_speed,
                                 descriptor, maximum_distance=None):
        """Prove the exact flat-ground 3x3 hull corridor without mutation."""
        try:
            planning_params = vehicle_physics.derive_params(descriptor)
            bbox = self._destructibles._vehicle_hull_bbox(descriptor)
            minimum, maximum = bbox[:2]
            half_width = max(
                abs(float(minimum[0])), abs(float(maximum[0]))) - 0.1
            leading = (-float(minimum[2]) if signed_speed < 0.0 else
                       float(maximum[2]))
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None
        if half_width <= 0.0 or leading <= 0.0:
            return None
        x, y, z = _xyz(position)
        sine = math.sin(float(travel_yaw))
        cosine = math.cos(float(travel_yaw))
        lateral_x = cosine
        lateral_z = -sine
        # This is a containment proof, not a planning distance.  Fifteen metres
        # covers the hull, the <=3.5 m cache drift and an ordinary rendered
        # frame at the native speed limit. A local turn may shorten the receipt;
        # once it no longer contains the hull, motion falls back to the
        # authoritative world sweep.
        proof_distance = 15.0
        if maximum_distance is not None:
            try:
                requested_distance = float(maximum_distance)
            except (TypeError, ValueError):
                return False
            if (requested_distance != requested_distance or
                    abs(requested_distance) == float('inf')):
                return False
            proof_distance = min(
                proof_distance, max(0.5, requested_distance))
        planned_impact_speed = abs(float(signed_speed or 0.0))
        cap_speed = None
        if planning_params is not None:
            cap_speed = float(planning_params[
                'speedBwd' if signed_speed < 0.0 else 'speedFwd'])
        for offset in (-half_width, 0.0, half_width):
            sx = x + lateral_x * offset - sine * 0.5
            sz = z + lateral_z * offset - cosine * 0.5
            ex = x + lateral_x * offset + sine * proof_distance
            ez = z + lateral_z * offset + cosine * proof_distance
            for height in (0.6, 1.1, 1.6):
                ray_start = self._vector((sx, y + height, sz))
                ray_end = self._vector((ex, y + height, ez))
                try:
                    collision = self._runtime.bigworld.wg_collideSegment(
                        self._avatar.spaceID, ray_start, ray_end,
                        VEHICLE_SKIP_FLAGS)
                except Exception:
                    return False
                if collision is None:
                    continue
                soft_status = self._destructibles._catalog_soft_static_path(
                    self._avatar.spaceID, ray_start, ray_end, collision,
                    planned_impact_speed, descriptor,
                    recast_budget=self._soft_static_recast_budget,
                    allow_kinetic_first=True, kinetic_speed=cap_speed)
                if soft_status in (True, 'kinetic'):
                    continue
                if soft_status == 'deferred':
                    return 'deferred'
                return False
        return {
            'distance': proof_distance,
            'half_width': half_width,
            'leading': leading,
            'origin': (x, y, z),
            'yaw': float(travel_yaw),
            'direction': (-1 if signed_speed < 0.0 else 1),
        }

    def _navigation_slope_lane_is_clear(self, start, end, half_width,
                                         offset, hit, trace=None):
        """Recast a terrain-hit lane above its proved continuous support.

        This changes collision geometry only. The same 25-degree centre and
        shoulder limits remain; walls, gaps and unproved long lanes still veto.
        """
        from gui.mods.offline_lan_0922.native_navigation_query import NAVIGATION_MAX_GRADE
        dx, dz = float(end[0])-float(start[0]), float(end[2])-float(start[2])
        distance = math.hypot(dx,dz)
        if not 0.1 <= distance <= 24.0:
            return False
        try:
            if not world_collision._drivable_surface(hit, 1.75):
                return False
            point = _xyz(hit[0])
            exact = self._navigation_ground(point[0],point[2],point[1])
            if exact is None or abs(float(exact)-point[1]) > .01:
                return False
        except (AttributeError,IndexError,TypeError,ValueError):
            return False
        lateral_x,lateral_z = dz/distance,-dx/distance
        cache=[]
        if trace is not None:
            for row in trace.get('ground_samples', ()):
                cache.extend((tuple(row['start']),tuple(row['end'])))
            for row in trace.get('shoulder_samples', ()):
                if row.get('shoulder_y') is not None:
                    cache.append((row['position'][0],row['shoulder_y'],row['position'][1]))
        def ground(x,z,hint):
            for old_x,old_y,old_z in cache:
                if abs(x-old_x) <= 1.e-5 and abs(z-old_z) <= 1.e-5:
                    return float(old_y)
            return self._navigation_ground(x,z,hint)
        count=max(1,int(math.ceil(distance/1.68)))
        samples=[]
        proof=dict(offset=float(offset),hit=point,normal=_xyz(hit[1]),
                   verdict='support_rejected',samples=samples)
        if trace is not None:
            trace.setdefault('slope_lane_proofs',[]).append(proof)
        for i in range(count+1):
            t=float(i)/count
            x,z=float(start[0])+dx*t,float(start[2])+dz*t
            hint=float(start[1])+(float(end[1])-float(start[1]))*t
            centre=ground(x,z,hint)
            lane_x,lane_z=x+lateral_x*offset,z+lateral_z*offset
            height=centre if abs(offset)<1.e-9 else ground(lane_x,lane_z,hint)
            if centre is None or height is None:
                proof['verdict']='missing_support';return False
            centre,height=float(centre),float(height)
            if any(math.isnan(v) or math.isinf(v) for v in (centre,height)):
                return False
            if abs(height-centre) > abs(offset)*NAVIGATION_MAX_GRADE+1.e-6:
                proof['verdict']='shoulder_grade';return False
            if samples:
                run=distance/count
                if (abs(centre-samples[-1][3]) > run*NAVIGATION_MAX_GRADE+1.e-6 or
                        abs(height-samples[-1][1]) > run*NAVIGATION_MAX_GRADE+1.e-6):
                    proof['verdict']='longitudinal_grade';return False
            samples.append((lane_x,height,lane_z,centre))
        # Do not merely ignore the terrain hit. Check the entire supported
        # lane at both original occupied heights, including any backing wall.
        for first,second in zip(samples,samples[1:]):
            for height in (.9,1.6):
                ray_start=self._vector((first[0],first[1]+height,first[2]))
                ray_end=self._vector((second[0],second[1]+height,second[2]))
                obstruction=self._collide_navigation(ray_start,ray_end,trace)
                if obstruction is not None:
                    proof['verdict']='supported_lane_obstacle'
                    proof['blocking_hit']=_xyz(obstruction[0]);return False
        proof['verdict']='continuous_support_lane_clear'
        return True

    def _navigation_obstacle(self, start, end, half_width,
                             native_capability=None, trace=None):
        """Ignore original destructible materials; retain native hard geometry."""
        dx = float(end[0]) - float(start[0])
        dz = float(end[2]) - float(start[2])
        length = math.sqrt(dx * dx + dz * dz)
        if length < 0.1:
            return False
        lateral_x, lateral_z = dz / length, -dx / length
        if trace is not None:
            trace.update(capability=native_capability,
                         segment=(tuple(start), tuple(end)),
                         half_width=float(half_width))
        for offset in (-float(half_width), 0.0, float(half_width)):
            for height in (0.9, 1.6):
                ray_start = self._vector((
                    float(start[0]) + lateral_x * offset,
                    float(start[1]) + height,
                    float(start[2]) + lateral_z * offset))
                ray_end = self._vector((
                    float(end[0]) + lateral_x * offset,
                    float(end[1]) + height,
                    float(end[2]) + lateral_z * offset))
                # The initial traversal removes every original soft surface;
                # no catalog registration or physical recast can postpone it.
                hit = self._collide_navigation(ray_start, ray_end, trace)
                if hit is not None:
                    if self._navigation_slope_lane_is_clear(
                            start,end,half_width,offset,hit,trace):
                        break
                    if trace is not None:
                        trace.update(
                            ray_start=_xyz(ray_start), ray_end=_xyz(ray_end),
                            hit=_xyz(hit[0]), normal=_xyz(hit[1]))
                        trace.update(classification='hard', reason='native_hard_geometry')
                    return True
        if trace is not None:
            trace.update(classification='clear', reason='native_corridor_clear')
        return False

    def _water_depth(self, point, receipt=None):
        if receipt is not None:
            receipt.update(point=tuple(point), start=(point[0], point[1]+20., point[2]),
                           end=(point[0], point[1]-5., point[2]))
        config = getattr(self, '_config', None) or {}
        map_name = prebaked_navigation._short_map_name(config.get('map'))
        value = water_surfaces.depth(map_name, point, receipt)
        if value is not None:
            return value
        collide = getattr(self._runtime.bigworld, 'wg_collideWater', None)
        if not callable(collide):
            if receipt is not None:
                receipt['reason'] = 'native_water_unavailable'
            return -1.0
        try:
            value = observed_call('native.motion.water', collide,
                self._vector((point[0], point[1] + 20.0, point[2])),
                self._vector((point[0], point[1] - 5.0, point[2])), False)
        except Exception as error:
            if receipt is not None:
                receipt.update(reason='native_water_exception',
                    error=type(error).__name__ + ': ' + str(error)[:240])
            return -1.0
        if receipt is not None:
            receipt.update(raw_distance=value, reason='no_water_hit' if value is None or value < 0.0 else 'water_hit')
        if value is None or value < 0.0:
            return -1.0
        return 20.0 - float(value)

    def _barrel_under_water(self, point):
        """Mirror #1513's positive-distance barrel water gate."""
        collide = getattr(self._runtime.bigworld, 'wg_collideWater', None)
        if not callable(collide):
            return True
        try:
            start = self._vector(point)
            end = self._vector((
                float(point[0]), float(point[1]) + 0.1,
                float(point[2])))
            value = observed_call('native.weapon.water', collide, start, end, False)
            return value is not None and float(value) > 0.0
        except Exception:
            return True

    @staticmethod
    def _bot_barrel_point(source, descriptor):
        if not isinstance(source, dict):
            return None
        try:
            yaw = float(source.get('yaw', 0.0) or 0.0)
            turret_yaw = (float(source.get('turret_yaw'))
                          if 'turret_yaw' in source else
                          ((float(source.get('aim_yaw', yaw) or yaw) - yaw +
                            math.pi) % (2.0 * math.pi)) - math.pi)
            return shot_geometry.barrel_world_point(
                descriptor,
                (float(source.get('x')), float(source.get('y')),
                 float(source.get('z'))),
                yaw, float(source.get('pitch', 0.0) or 0.0),
                float(source.get('roll', 0.0) or 0.0),
                turret_yaw,
                float(source.get('gun_pitch', 0.0) or 0.0))
        except (KeyError, TypeError, ValueError, OverflowError):
            return None

    def _observed_vehicle_descriptor(self, target):
        kind = 'player' if target.get('kind') == 'human' else 'bot'
        network_id = target.get('network_id', target.get('id'))
        record = self._records.get('%s:%d' % (kind, int(network_id)))
        if not record or record.get('tombstone') or not record.get('ready'):
            return None
        entity = self._server_entity(record.get('engine_id'))
        if entity is None or not getattr(entity, 'isStarted', False):
            return None
        # Descriptors are static content. The entity's omniscient matrix,
        # reload, ammunition and current gun angles are never read here.
        return getattr(entity, 'typeDescriptor', None)

    def _observed_gun_origin(self, target):
        descriptor = self._observed_vehicle_descriptor(target)
        if descriptor is None:
            return None
        yaw = target.get('yaw', 0.0)
        origin, unused_direction = shot_geometry.shot_origin_and_direction(
            descriptor, _xyz(target.get('position', target)), yaw, target.get('pitch', 0.0),
            target.get('roll', 0.0), target.get(
                'turret_yaw', target.get('aim_yaw', yaw) - yaw),
            target.get('gun_pitch', 0.0))
        return origin

    def _tactical_ray_clear(self, start, end):
        return self._runtime.bigworld.wg_collideSegment(
            self._avatar.spaceID, self._vector(start),
            self._vector(end), 128) is None

    def _bot_incoming_lane(self, source, target):
        """Probe enemy gun -> own body, never infer it from the reverse ray."""
        try:
            own = dict(source, kind='bot', network_id=source['id'])
            descriptor = self._observed_vehicle_descriptor(own)
            origin = self._observed_gun_origin(target)
            if descriptor is None or origin is None:
                return None
            samples = shot_geometry.vehicle_aim_samples(descriptor)[:2]
            if not samples:
                return None
            return any(self._tactical_ray_clear(
                origin, shot_geometry.vehicle_aim_point(sample, source))
                for sample in samples)
        except Exception:
            return None

    def _local_body_pose(self):
        return self._local_pose_matrix or self._local_matrix

    def _projectile_vehicle_matrices(self, record, vehicle,
                                     ground_matrix=None):
        """Return body/chassis poses matching the projectile timeline.

        A hidden worker interpolates native Bot compounds for presentation,
        but ``_projectile_record_positions`` intentionally records the
        canonical simulation position. Mixing that position with the
        render-blended matrix makes broad phase and exact hit testing disagree
        for a moving target. Use the factory's unblended hydraulic body and
        ground matrices on the worker and retain the visible provider
        everywhere else.
        """
        canonical = vehicle.matrix if ground_matrix is None else ground_matrix
        if (self._worker_mode and record.get('native_remote') and
                self._remote_factory is not None):
            getter = getattr(
                self._remote_factory, 'projectile_collision_matrices', None)
            if callable(getter):
                matrices = getter(record.get('engine_id'), ground_matrix)
                if matrices is not None:
                    return matrices
            getter = getattr(
                self._remote_factory, 'projectile_collision_matrix', None)
            if callable(getter):
                body = getter(record.get('engine_id'))
                if body is not None:
                    return body, canonical
        return canonical, canonical

    @staticmethod
    def _projectile_plain_pose(position, state=None):
        """Copy a pose whose numeric fields were already canonicalized."""
        state = state if isinstance(state, dict) else {}
        yaw = state.get('yaw', 0.0)
        aim_yaw = state.get('aim_yaw', yaw)
        turret_yaw = state.get(
            'turret_yaw', _angle_delta(yaw, aim_yaw))
        return {
            'x': position[0], 'y': position[1],
            'z': position[2], 'yaw': yaw,
            'pitch': state.get('pitch', 0.0),
            'roll': state.get('roll', 0.0),
            'turret_yaw': turret_yaw,
            'gun_pitch': state.get('gun_pitch', 0.0),
            'siege_state': int(state.get('siege_state', 0) or 0),
        }

    def _sample_ground_plane(self, position, yaw, descriptor=None,
                             ground_probe=None):
        """Fit one continuous terrain plane under the local suspension."""
        ground = ground_probe or self._ground_y
        length = 5.0
        width = 3.0
        try:
            hit_tester = _field(_field(descriptor, 'hull', {}),
                                'hitTester', None)
            bbox = getattr(hit_tester, 'bbox', None)
            length = max(3.0, abs(float(bbox[0][2])) +
                         abs(float(bbox[1][2])))
            width = max(2.0, abs(float(bbox[0][0])) +
                        abs(float(bbox[1][0])))
        except (TypeError, ValueError, IndexError, AttributeError):
            pass
        half_length = length * 0.5
        half_width = width * 0.5
        sin_yaw, cos_yaw = math.sin(yaw), math.cos(yaw)
        front_y = ground(
            position[0] + sin_yaw * half_length,
            position[2] + cos_yaw * half_length, position[1])
        rear_y = ground(
            position[0] - sin_yaw * half_length,
            position[2] - cos_yaw * half_length, position[1])
        right_y = ground(
            position[0] + cos_yaw * half_width,
            position[2] - sin_yaw * half_width, position[1])
        left_y = ground(
            position[0] - cos_yaw * half_width,
            position[2] + sin_yaw * half_width, position[1])
        center_y = ground(
            position[0], position[2], position[1])
        if None in (front_y, rear_y, right_y, left_y, center_y):
            return None
        return vehicle_physics.sampled_ground_plane(
            front_y, rear_y, right_y, left_y, center_y,
            yaw, length, width, GROUND_PLANE_EPSILON)

    def _report_local_tree_motion(self, start, end, yaw, speed, dt,
                                  now, detail, stage='proposal',
                                  descriptor=None, start_yaw=None):
        """Keep missing tree contacts observable without native probes."""
        try:
            from gui.mods.offline_lan_0922.tree_diagnostics import (
                TreeContactDiagnostics)
            observer = getattr(self, '_local_tree_diagnostics', None)
            if observer is None:
                observer = TreeContactDiagnostics()
                self._local_tree_diagnostics = observer
            payload = observer.sample(
                self._destructibles, sys.modules.get(
                    'gui.mods.offline_lan_0922.destructibles_authority'),
                self._avatar.spaceID, start, end, yaw, speed, dt,
                now, detail, stage)
            if payload is not None:
                bbox_reader = getattr(self._destructibles, '_vehicle_hull_bbox', None)
                bbox = (bbox_reader(descriptor) if callable(bbox_reader) and
                        descriptor is not None else None)
                payload['hull_bbox'] = (tuple(tuple(float(corner[index])
                    for index in range(3)) for corner in bbox[:2])
                    if bbox is not None else None)
                payload['hull_corner_types'] = (tuple(type(corner).__name__
                    for corner in bbox[:2]) if bbox is not None else None)
                payload['start_yaw'] = start_yaw
                sys.stdout.write('[Offline LAN 0.9.22] LOCAL TREE %s\n' %
                                 json.dumps(payload))
        except Exception as error:
            # Evidence collection cannot change the already-decided contact.
            if not getattr(self, '_local_tree_diagnostic_error', False):
                self._local_tree_diagnostic_error = True
                try:
                    sys.stdout.write('[Offline LAN 0.9.22] LOCAL TREE '
                                     'diagnostic_error=%s\n' % error)
                except Exception:
                    pass

    def _tree_motion_proposal(
            self, start_position, start_yaw, end_position, end_yaw,
            speed, descriptor, now, dt):
        """Return the sensor's exact continuous tree-contact proposal."""
        clear = {
            'status': 'clear', 'token': None, 'accepted_now': False,
            'kinds': '-', 'requires_commit': False,
        }
        proposer = getattr(
            self._destructibles, '_tree_motion_proposal', None)
        if not callable(proposer):
            # Narrow injected adapters do not model native falling columns.
            return clear
        geometry = {}
        if vehicle_physics.track_pivot_from_poses(
                vehicle_physics.track_pivot_descriptor_params(descriptor),
                start_position, start_yaw, end_position, end_yaw):
            # Math.Vector3 stores float32. Keep the original double endpoints
            # through the pure tree geometry; vectors belong to native calls.
            geometry['geometry_positions'] = (
                tuple(start_position), tuple(end_position))
        detail = proposer(
            self._avatar.spaceID, self._vector(start_position),
            float(start_yaw), self._vector(end_position), float(end_yaw),
            float(speed), descriptor, now, dt=float(dt), **geometry)
        if not isinstance(detail, dict):
            # Keep legacy test seams inert.  The packaged sensor always
            # returns the typed dictionary validated below.
            return clear
        status = detail.get('status')
        if status not in ('clear', 'crushed', 'hard', 'pending'):
            raise RuntimeError('tree motion proposal returned invalid status')
        token = (self._destructible_contact_token(detail.get('token'))
                 if detail.get('token') is not None else None)
        requires_commit = bool(detail.get('requires_commit', False))
        if (detail.get('token') is not None and token is None) or (
                requires_commit and (status != 'crushed' or token is None)):
            raise RuntimeError('tree motion proposal lost its exact token')
        if token is not None and any(row[2] is not None for row in token):
            raise RuntimeError('tree motion proposal has a material token')
        self._report_local_tree_motion(
            start_position, end_position, end_yaw, speed, dt, now, detail,
            descriptor=descriptor, start_yaw=start_yaw)
        if status in ('pending', 'hard'):
            # Missing, ambiguous or isolated tree registry evidence is not a
            # hard-world contact. Both human and Bot motion still check the
            # independent native world and catalog before moving. Keep warming
            # exact identities rather than turning registry absence into a wall.
            # The tank may keep moving while
            # prewarming makes an exact identity available for a later frame.
            return clear
        return {
            'status': status,
            'token': token,
            'accepted_now': bool(detail.get('accepted_now', False)),
            'kinds': str(detail.get('kinds', 'tree')),
            'requires_commit': requires_commit,
        }

    def _destructible_pose_sweep(
            self, start_position, start_yaw, end_position, end_yaw,
            speed, descriptor, now, dt, commit_enabled=False,
            rotation_speed_cap=None, pitch=0.0, roll=0.0,
            drive_speed_cap=None):
        """Resolve the complete translating and rotating catalog hull sweep.

        Each slice is a fixed-orientation zonotope understood by the pinned
        sensor.  Its midpoint-frame bbox analytically encloses every rotated
        hull pose in the slice, so the union covers the continuous old-to-new
        pose instead of sampling a few rays or isolated endpoint rectangles.
        """
        clear = {
            'status': 'clear', 'token': None, 'accepted_now': False,
            'used_kinetic_speed': False, 'kinds': '-',
            'requires_commit': False, 'impact_speed': abs(float(speed)),
        }
        if self._destructibles is None:
            return clear
        bbox_reader = getattr(
            self._destructibles, '_vehicle_body_bbox', None)
        if not callable(bbox_reader):
            bbox_reader = getattr(
                self._destructibles, '_vehicle_hull_bbox', None)
        if not callable(bbox_reader):
            # Production always has the pinned typed sensor.  Preserve the old
            # no-rotation behavior for narrow injected adapters which predate
            # this seam rather than inventing a hull shape for them.
            return clear
        bbox = bbox_reader(descriptor)
        if bbox is None:
            return clear
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 2:
            # Narrow test/extension adapters may expose a dynamic attribute in
            # place of the pinned sensor function.  It is not hull evidence.
            return clear
        posed_bbox = _destructible_posed_bbox(bbox, pitch, roll)
        resolver_name = ('_catalog_motion_blocked' if commit_enabled else
                         '_catalog_motion_proposal')
        resolver = getattr(self._destructibles, resolver_name, None)
        if not callable(resolver):
            raise RuntimeError(
                'destructible pose-sweep resolver is unavailable')

        start = tuple(float(value) for value in start_position[:3])
        end = tuple(float(value) for value in end_position[:3])
        pivot_offset = vehicle_physics.track_pivot_from_poses(
            vehicle_physics.track_pivot_descriptor_params(descriptor),
            start, start_yaw, end, end_yaw)
        yaw_delta = _angle_delta(float(start_yaw), float(end_yaw))
        if abs(yaw_delta) <= 1.0e-8:
            return clear
        steps = int(math.ceil(
            abs(yaw_delta) / DESTRUCTIBLE_POSE_MAX_ANGLE_STEP))
        if not 1 <= steps <= DESTRUCTIBLE_POSE_MAX_SWEEP_STEPS:
            raise RuntimeError('destructible pose sweep exceeds its bound')
        duration = max(1.0e-6, float(dt))
        center_dx = end[0] - start[0]
        center_dy = end[1] - start[1]
        center_dz = end[2] - start[2]
        center_distance = math.sqrt(
            center_dx * center_dx + center_dz * center_dz)
        corner_radius = max(math.sqrt(
            float(local_x) * float(local_x) +
            float(local_z) * float(local_z))
            for local_x in (posed_bbox[0][0], posed_bbox[1][0])
            for local_z in (posed_bbox[0][2], posed_bbox[1][2]))
        if rotation_speed_cap is None:
            rotation_kinetic_speed = None
        else:
            try:
                rotation_speed_cap = abs(float(rotation_speed_cap))
            except (TypeError, ValueError, OverflowError):
                raise RuntimeError(
                    'destructible rotation speed cap is invalid')
            if (math.isnan(rotation_speed_cap) or
                    math.isinf(rotation_speed_cap)):
                raise RuntimeError(
                    'destructible rotation speed cap is invalid')
            rotation_kinetic_speed = rotation_speed_cap * corner_radius
            if rotation_speed_cap > 0.0 and drive_speed_cap is not None:
                try:
                    drive_speed_cap = abs(float(drive_speed_cap))
                except (TypeError, ValueError, OverflowError):
                    raise RuntimeError('destructible drive speed cap is invalid')
                if math.isnan(drive_speed_cap) or math.isinf(drive_speed_cap):
                    raise RuntimeError('destructible drive speed cap is invalid')
                # Powered pivot contact has the same crush eligibility as
                # powered translation. The old angular-edge-only cap could
                # never reach the health gate of a prop that forward drive
                # crushes from rest, so every rejected first turn repeated.
                # This is gate evidence only: the sensor still requires exact
                # contact, and geometry, real speed and receipts use the actual
                # frame motion below. Native replacement BSPs remain blocking.
                rotation_kinetic_speed = max(
                    rotation_kinetic_speed, drive_speed_cap)
        angular_edge_speed = abs(yaw_delta) * corner_radius / duration
        impact_magnitude = min(200.0, math.sqrt(
            max(abs(float(speed)), center_distance / duration) ** 2 +
            angular_edge_speed ** 2))
        impact_speed = (-impact_magnitude
                        if float(speed) < 0.0 else impact_magnitude)
        if impact_magnitude <= 1.0e-8:
            return clear

        token = set()
        kinds = set()
        accepted_now = False
        used_kinetic_speed = False
        requires_commit = False
        saw_crushed = False
        saw_soft = False
        saw_approach = False
        saw_kinetic = False
        saw_pending = False
        saw_hard = False
        for index in range(steps):
            lower = float(index) / float(steps)
            upper = float(index + 1) / float(steps)
            middle = (lower + upper) * 0.5
            slice_start = tuple(
                start[axis] + (end[axis] - start[axis]) * lower
                for axis in range(3))
            slice_end = tuple(
                start[axis] + (end[axis] - start[axis]) * upper
                for axis in range(3))
            slice_yaw = float(start_yaw) + yaw_delta * middle
            interval_bbox = _destructible_rotation_interval_bbox(
                posed_bbox, abs(yaw_delta) * 0.5 / float(steps), pivot_offset)
            if pivot_offset:
                # The interval box encloses the whole arc around the held
                # track, in the exact midpoint chassis frame.
                slice_start = vehicle_physics.track_pivot_position(
                    start, start_yaw, slice_yaw, pivot_offset)
                slice_end = slice_start
            sweep_descriptor = _destructible_sweep_descriptor(
                descriptor, interval_bbox)
            move_x = slice_end[0] - slice_start[0]
            move_z = slice_end[2] - slice_start[2]
            move_distance = math.sqrt(move_x * move_x + move_z * move_z)
            motion_yaw = (math.atan2(move_x, move_z)
                          if move_distance > 1.0e-8 else None)
            # Geometry needs the realised centre travel, while kinetic
            # classification needs the faster rotating hull edge.  Choosing a
            # duration whose product with impact speed equals centre travel
            # preserves that path without adding a proximity skin.
            slice_dt = (move_distance / impact_magnitude
                        if move_distance > 1.0e-8 else 0.0)
            if commit_enabled:
                detail = resolver(
                    self._avatar.spaceID, self._vector(slice_start),
                    slice_yaw, impact_speed, sweep_descriptor, now,
                    dt=slice_dt, kinetic_speed=rotation_kinetic_speed,
                    return_detail=True,
                    kinetic_commit=True, commit_enabled=True,
                    motion_yaw=motion_yaw,
                    travel_reach=move_distance)
            else:
                detail = resolver(
                    self._avatar.spaceID, self._vector(slice_start),
                    slice_yaw, impact_speed, sweep_descriptor, now,
                    dt=slice_dt, kinetic_speed=rotation_kinetic_speed,
                    motion_yaw=motion_yaw,
                    travel_reach=move_distance)
            if isinstance(detail, bool):
                detail = {'status': 'hard' if detail else 'clear'}
            elif isinstance(detail, str):
                detail = {'status': detail}
            if not isinstance(detail, dict):
                raise RuntimeError(
                    'destructible pose-sweep detail is unavailable')
            status = detail.get('status')
            if status not in (
                    'clear', 'crushed', 'soft', 'hard', 'approach',
                    'kinetic', 'pending'):
                raise RuntimeError(
                    'destructible pose sweep returned an invalid status')
            parsed_token = self._destructible_contact_token(
                detail.get('token'))
            if parsed_token is not None:
                token.update(parsed_token)
            raw_kinds = str(detail.get('kinds', '-'))
            kinds.update(value for value in raw_kinds.split(',')
                         if value and value != '-')
            accepted_now = accepted_now or bool(
                detail.get('accepted_now', False))
            used_kinetic_speed = used_kinetic_speed or bool(
                detail.get('used_kinetic_speed', False))
            requires_commit = requires_commit or bool(
                detail.get('requires_commit', False))
            saw_crushed = saw_crushed or status == 'crushed'
            saw_soft = saw_soft or status == 'soft'
            saw_approach = saw_approach or status == 'approach'
            saw_kinetic = saw_kinetic or status == 'kinetic'
            saw_pending = saw_pending or status == 'pending'
            saw_hard = saw_hard or status == 'hard'
            if saw_hard:
                # A hard backing body still blocks the pose, but an exact
                # fragile token from this or an earlier slice must be
                # committed and propagated before the tank stops.
                break

        status = ('hard' if saw_hard else
                  'pending' if saw_pending else
                  'kinetic' if saw_kinetic else
                  'crushed' if saw_crushed else
                  'soft' if saw_soft else
                  'approach' if saw_approach else 'clear')
        return {
            'status': status,
            'token': tuple(sorted(token, key=lambda row: (
                row[0], row[1], -1 if row[2] is None else row[2]))) or None,
            'accepted_now': accepted_now,
            'used_kinetic_speed': used_kinetic_speed,
            'kinds': ','.join(sorted(kinds)) or '-',
            'requires_commit': requires_commit,
            'impact_speed': impact_speed,
            '_pending': saw_pending,
        }

    def _turret_motion_is_clear(self, start_pose, end_pose, descriptor):
        """Use the room's published turret geometry for every moving hull."""
        obstacles = getattr(self, '_detached_turret_obstacles', None)
        if obstacles is None:
            return True
        return not obstacles.sweep_blocks(
            start_pose, end_pose, descriptor, self._turret_server_time_ms())

    @timed('bot.world_rotation')
    @readonly_queries
    def _native_world_rotation_is_clear(
            self, position, start_yaw, end_yaw, descriptor,
            pitch=None, roll=None, record_local=True, pivot_offset=0.0,
            contact_trace=None, include_static=False, translation=(0.0, 0.0),
            follow_ground=False):
        """Recast every rotating body slice against the live native BSP.

        The catalog owns each destructible's original shape.  Once a structure
        module or a retained-collision fragile is destroyed, however, #1513
        may replace it with a different compiled BSP which can extend outside
        the old catalog OBB.  Therefore even a catalog ``clear`` must ask the
        native world before accepting an in-place turn, or a corner can rotate
        into that replacement and become trapped on the following frame.

        Each midpoint descriptor analytically encloses the complete yaw
        interval.  Probing it in both longitudinal directions covers the
        occupied front and rear halves.  ``commit_enabled=False`` makes this a
        read-only recast through the ordinary broken-skin filter, preserving
        both backing walls and damaged-model materials.
        """
        active_reader = getattr(
            self._destructibles, 'native_replacement_bsp_active', None)
        if (not include_static and not pivot_offset and
                math.hypot(*translation) <= 1.0e-9 and
                callable(active_reader) and not active_reader()):
            # Before the first accepted retained replacement there is no
            # damaged BSP to find.  The ordinary catalog/baked guards own live
            # objects without paying for two native sweeps per slice.
            return True
        if pitch is None:
            pitch = self._local_pitch
        if roll is None:
            roll = self._local_roll
        bbox_reader = getattr(
            self._destructibles, '_vehicle_body_bbox', None)
        if not callable(bbox_reader):
            bbox_reader = getattr(
                self._destructibles, '_vehicle_hull_bbox', None)
        if not callable(bbox_reader):
            # Production always exposes the typed body reader.  Keep narrow
            # test/extension adapters on their established catalog-only seam.
            return True
        bbox = bbox_reader(descriptor)
        if (not isinstance(bbox, (list, tuple)) or len(bbox) < 2):
            return True
        yaw_delta = _angle_delta(float(start_yaw), float(end_yaw))
        if abs(yaw_delta) <= 1.0e-8:
            return True
        steps = int(math.ceil(
            abs(yaw_delta) / DESTRUCTIBLE_POSE_MAX_ANGLE_STEP))
        if not 1 <= steps <= DESTRUCTIBLE_POSE_MAX_SWEEP_STEPS:
            raise RuntimeError(
                'native world rotation sweep exceeds its bound')
        # Unlike the catalog box test, native lanes read only bbox X/Z and
        # pose their fixed 0.6/1.1/1.6 m heights themselves. Baking Y into the
        # box and zeroing pitch/roll discards that pose entirely, putting a
        # raised track's collision rays through the slope below its body.
        sweep_pitch = pitch
        sweep_roll = roll
        # All equal-angle slices share this exact local envelope. Only their
        # world pose changes; never retain a native collision answer here.
        interval_bbox = _destructible_rotation_interval_bbox(
            bbox, abs(yaw_delta) * 0.5 / float(steps), pivot_offset)
        sweep_descriptor = _destructible_world_sweep_descriptor(
            descriptor, interval_bbox)
        slice_travel = (translation[0]/steps, translation[1]/steps)
        travel_length = math.hypot(*slice_travel)
        previous_contacts = []
        previous_checked = [False]

        def read_previous_contacts():
            if not previous_checked[0]:
                previous_checked[0] = True
                actual_descriptor = _destructible_world_sweep_descriptor(descriptor, bbox)
                for direction in (1.0e-6, -1.0e-6):
                    previous_trace = {}
                    world_collision.check_horizontal_collision(
                        self._runtime.bigworld, self._runtime.math,
                        self._avatar.spaceID, self._vector(position),
                        start_yaw, direction, actual_descriptor, False, 0.0,
                        True, False, None, commit_enabled=False,
                        pitch=pitch, roll=roll, trace=previous_trace,
                        exact_footprint=True, motion_yaw=start_yaw,
                        query_owner=self)
                    if 'hit' in previous_trace and 'normal' in previous_trace:
                        previous_contacts.append((self._vector(previous_trace['hit']),
                                                  self._vector(previous_trace['normal'])))
            return previous_contacts

        for index in range(steps):
            lower = float(index) / float(steps)
            upper = float(index + 1) / float(steps)
            middle = (lower + upper) * 0.5
            slice_yaw = float(start_yaw) + yaw_delta * middle
            if follow_ground:
                sweep_pitch, sweep_roll = ground_pose_for_yaw(
                    pitch, roll, start_yaw, slice_yaw)
            slice_position = vehicle_physics.track_pivot_position(
                position, start_yaw, slice_yaw, pivot_offset)
            slice_position = (slice_position[0]+translation[0]*lower,
                              slice_position[1], slice_position[2]+translation[1]*lower)
            slice_start_yaw = float(start_yaw) + yaw_delta * lower
            slice_end_yaw = float(start_yaw) + yaw_delta * upper
            slice_start_position = vehicle_physics.track_pivot_position(
                position, start_yaw, slice_start_yaw, pivot_offset)
            slice_start_position = (
                slice_start_position[0] + translation[0] * lower,
                slice_start_position[1],
                slice_start_position[2] + translation[1] * lower)
            departing = _rotation_departing_contact(
                slice_start_position, bbox, slice_start_yaw, slice_end_yaw,
                pitch, roll, read_previous_contacts, slice_travel,
                pivot_offset=pivot_offset)
            for probe_speed in ((travel_length,) if travel_length else (1.0e-6, -1.0e-6)):
                trace = {}
                world_status = world_collision.check_horizontal_collision(
                    self._runtime.bigworld, self._runtime.math,
                    self._avatar.spaceID, self._vector(slice_position),
                    slice_yaw, probe_speed, sweep_descriptor, False, 1.0 if travel_length else 0.0,
                    True, False, None, commit_enabled=False,
                    pitch=sweep_pitch, roll=sweep_roll,
                    trace=trace, exact_footprint=not travel_length,
                    # A stationary rotation is also a fully posed body sweep.
                    # Powered look-ahead rays retain unpitched X/Z and can cut
                    # through the supporting bank after the hull follows it.
                    motion_yaw=math.atan2(*slice_travel) if travel_length else slice_yaw,
                    departing_contact=departing, query_owner=self)
                if isinstance(world_status, bool):
                    world_status = 'hard' if world_status else 'clear'
                if world_status != 'clear':
                    if contact_trace is not None:
                        contact_trace.update(trace)
                        contact_trace.update(pivot_offset=pivot_offset,
                            start_yaw=start_yaw, end_yaw=end_yaw,
                            sweep_yaw=slice_yaw, sweep_pitch=sweep_pitch,
                            sweep_roll=sweep_roll, follow_ground=bool(follow_ground),
                            posed_body=True)
                    if record_local:
                        self._local_world_collision_trace = trace
                        self._local_motion_kinds = 'world'
                        self._local_motion_status = 'hard'
                    return False
        return True

    def _complete_bot_tree_contact(
            self, proposal, start, start_yaw, end, end_yaw,
            descriptor, speed, now, dt, commit_enabled, world_status):
        """Commit a realised worker sweep, never a navigation candidate."""
        if proposal.get('status') in ('pending', 'hard'):
            return world_status
        if not proposal.get('requires_commit') or not commit_enabled:
            return world_status
        committer = getattr(self._destructibles, 'commit_tree_contacts', None)
        if not callable(committer):
            raise RuntimeError('worker tree contact boundary is unavailable')
        token = proposal.get('token')
        committed = committer(
            self._avatar.spaceID, token, self._vector(start), start_yaw,
            self._vector(end), end_yaw, speed, descriptor, now,
            dt=dt, publish=True)
        committed_token = (self._destructible_contact_token(
            committed.get('token')) if isinstance(committed, dict) else None)
        key = tuple(token)
        if (not isinstance(committed, dict) or
                committed.get('status') != 'crushed' or
                committed_token is None or
                not set(token).issubset(set(committed_token))):
            # An exact, realised tree sweep has already passed world/catalog
            # checks. Keep its original geometry for bounded idle retries;
            # presentation or publication latency must not freeze the hull.
            if not isinstance(committed, dict) or committed.get('status') != 'hard':
                self._bot_tree_contacts_pending.setdefault(key, (
                    self._avatar.spaceID, tuple(start), start_yaw,
                    tuple(end), end_yaw, descriptor, speed, dt,
                    (self._start_message or {}).get('round_id'), now))
            else:
                self._bot_tree_contacts_pending.pop(key, None)
            return world_status
        self._bot_tree_contacts_pending.pop(key, None)
        return 'crushed'

    def _probe_bot_local_motion(self, bot_id, position, body_yaw, travel_yaw,
                                distance, descriptor, step, now):
        """Preview a local action through its authoritative, non-committing sweep.

        Rotations prove the requested stationary arc, not only its first frame.
        This is a candidate proof, not a committed moving-body prediction.
        Straight local exits prove their
        requested displacement, with the actual front/rear body envelope.
        """
        state = getattr(self._bots, 'states', {}).get(int(bot_id), {})
        # This module's helper takes (current, target); BotRuntime's
        # similarly named helper takes the opposite argument order.
        delta = _angle_delta(body_yaw, travel_yaw)
        if distance is not None and min(abs(delta), abs(abs(delta)-math.pi)) > .02:
            return dict(clear=None, proved=False, reason='local_sweep_not_aligned',
                at=now, origin=tuple(position), body_yaw=body_yaw,
                requested_yaw=travel_yaw, distance=distance, commit_enabled=False,
                source='authoritative_body_sweep')
        from gui.mods.offline_lan_0922 import arena_boundary
        bounds = self._arena_bounds
        length, width = state.get('half_length',3.5),state.get('half_width',1.7)
        end = position if distance is None else (position[0]+math.sin(travel_yaw)*distance,
            position[1],position[2]+math.cos(travel_yaw)*distance)
        boundary_clear = (arena_boundary.rotation_clear(bounds,position,body_yaw,travel_yaw,length,width)
            if distance is None else arena_boundary.progress_clear(bounds,position,body_yaw,
                                                                  end,body_yaw,length,width))
        if not boundary_clear:
            return dict(clear=False,proved=True,reason='arena_boundary',at=now,
                origin=tuple(position),requested_yaw=travel_yaw,distance=distance,
                source='authoritative_body_sweep',commit_enabled=False)
        missing = object()
        fields = ('_rotation_contact_trace', '_world_contact_trace', 'movement_dir', 'rotation_dir')
        saved = dict((k,state.get(k,missing)) for k in fields)
        old_kind = self._bot_motion_kinds.get(int(bot_id),missing)
        receipt = dict(at=now, origin=tuple(position), body_yaw=body_yaw,
            requested_yaw=travel_yaw, distance=distance, commit_enabled=False,
            source='authoritative_body_sweep')
        try:
            params_reader = getattr(self._bots, '_physics_params_for', None)
            params = (params_reader(bot_id) if callable(params_reader) else
                      vehicle_physics.derive_params(descriptor))
            dt = max(.001, float(step))
            if distance is None:
                cap = max(float(params['rotSpd']),
                    abs(getattr(self._bots,'_turn_speeds',{}).get(bot_id,0.)))
                # The native sweep owns at most sixteen five-degree slices.
                # Cover even a wrapped half-turn with <= three sixty-degree
                # chunks instead of truncating or exceeding that native bound.
                chunks = max(1, int(math.ceil(abs(delta)/(math.pi/3.0))))
                clear = True
                receipt.update(proof_scope='requested_rotation_arc',
                               requested_delta=delta, checked_chunks=0,
                               planned_chunks=chunks)
                for index in range(chunks):
                    first = body_yaw+delta*index/chunks
                    last = body_yaw+delta*(index+1)/chunks
                    receipt['checked_yaw'] = last
                    receipt['checked_chunks'] = index+1
                    clear = self._resolve_bot_rotation(bot_id, position, first,
                        last, descriptor, max(dt,abs(last-first)/max(.001,cap)),
                        now, cap, commit_enabled=False)
                    if clear is not True:
                        break
                receipt['trace'] = state.get('_rotation_contact_trace')
                status = 'commit_required' if clear is None else 'clear' if clear else 'hard'
            else:
                sign = 1. if math.cos(delta) >= 0. else -1.
                state['movement_dir'], state['rotation_dir'] = int(sign), 0
                speed = sign*float(params['speedFwd' if sign>0 else 'speedBwd'])
                dt = max(.001,float(distance)/max(.001,abs(speed)))
                # An aligned throttle action uses the same signed driving
                # sweep as BotRuntime's committed motion. Supplying motion_yaw
                # selects the passive-displacement law, which also recasts the
                # old opposite half and destination perimeter. A side contact
                # behind a reversing hull then vetoed every otherwise clear
                # driving exit (T28 Concept and SU-122A report fixtures).
                receipt.update(motion_law='signed_drive',
                    checked_yaw=body_yaw if sign > 0. else body_yaw+math.pi,
                    checked_speed=speed, checked_dt=dt)
                status = self._resolve_bot_motion(bot_id, position, body_yaw,
                    speed, descriptor, dt, now, commit_enabled=False)
                clear = (None if status == 'commit_required' else
                         status in ('clear','crushed','approach','soft'))
                receipt['trace'] = state.get('_world_contact_trace')
            receipt.update(status=status, clear=(True if clear is None else bool(clear)),
                proved=clear is not None,
                reason=('local_sweep_commit_required' if clear is None else
                        'local_sweep_clear' if clear else 'local_sweep_blocked'))
            return receipt
        finally:
            # Candidate inspection must not replace the realised action's
            # collision diagnostics or publish destruction/impact effects.
            for key,value in saved.items():
                if value is missing: state.pop(key,None)
                else: state[key]=value
            if old_kind is missing: self._bot_motion_kinds.pop(int(bot_id),None)
            else: self._bot_motion_kinds[int(bot_id)]=old_kind

    @timed('bot.physics.rotation')
    def _resolve_bot_rotation(
            self, bot_id, position, start_yaw, end_yaw, descriptor, dt, now,
            rotation_speed_cap, pivot_offset=0.0, translation=(0.0, 0.0),
            commit_enabled=True):
        """Keep a Bot's complete pivot outside live and damaged structures."""
        # Further split the captured rotation cost only in the test entry.
        # Admission, query order and realised contact ownership stay identical.
        diagnostic = (getattr(self, '_combat_diagnostics', None)
                      if native_input_diagnostics.detailed_enabled() else None)
        if diagnostic is not None:
            diagnostic.count('rotation.realised' if commit_enabled else
                             'rotation.preview')
        end_position = vehicle_physics.track_pivot_position(
            position, start_yaw, end_yaw, pivot_offset)
        end_position = (end_position[0]+translation[0], end_position[1],
                        end_position[2]+translation[1])
        bot_state = getattr(self._bots, 'states', {}).get(int(bot_id), {})
        bot_state.pop('_rotation_contact_trace', None)
        pitch = _number(bot_state.get(
            'terrain_pitch', bot_state.get('pitch')))
        roll = _number(bot_state.get('roll'))
        drive_speed_cap = (self._destructible_drive_speed_cap(
            descriptor, vehicle_physics.descriptor_drive_limits(descriptor), 0.0,
            self._bot_destructible_travel_descriptor(bot_id))
            if rotation_speed_cap else None)
        detail = timed_call(diagnostic, 'rotation.catalog_probe',
            self._destructible_pose_sweep,
            position, start_yaw, end_position, end_yaw, 0.0,
            descriptor, now, dt,
            rotation_speed_cap=rotation_speed_cap,
            drive_speed_cap=drive_speed_cap,
            pitch=pitch, roll=roll)
        status = detail.get('status')
        if status not in (
                'clear', 'crushed', 'soft', 'hard', 'approach',
                'kinetic', 'pending'):
            raise RuntimeError(
                'bot rotation resolver returned an invalid status')
        self._bot_motion_kinds[int(bot_id)] = str(detail.get('kinds', '-'))
        if not commit_enabled and detail.get('requires_commit', False):
            return None  # Only the realised action may publish this contact.
        if bool(detail.get('requires_commit', False)):
            proposal_token = self._destructible_contact_token(
                detail.get('token'))
            if proposal_token is None:
                raise RuntimeError(
                    'bot rotation proposal lost its exact token')
            detail = timed_call(diagnostic, 'rotation.catalog_commit',
                self._destructible_pose_sweep,
                position, start_yaw, end_position, end_yaw, 0.0,
                descriptor, now, dt, commit_enabled=True,
                rotation_speed_cap=rotation_speed_cap,
                drive_speed_cap=drive_speed_cap,
                pitch=pitch, roll=roll)
            committed_token = self._destructible_contact_token(
                detail.get('token'))
            if (committed_token is None or
                    not set(proposal_token).issubset(set(committed_token))):
                raise RuntimeError(
                    'bot rotation commit lost its proposal token')
            status = detail.get('status')
            if status not in (
                    'clear', 'crushed', 'soft', 'hard', 'approach',
                    'kinetic', 'pending'):
                raise RuntimeError(
                    'bot rotation commit returned an invalid status')
            self._bot_motion_kinds[int(bot_id)] = str(
                detail.get('kinds', '-'))
        if status not in ('clear', 'crushed', 'approach'):
            bot_state['_rotation_contact_trace'] = dict(
                reason='destructible_rotation',status=status,
                kinds=detail.get('kinds'),position=position,
                start_yaw=start_yaw,end_yaw=end_yaw,pitch=pitch,roll=roll,
                sampled_at=now)
            return False
        contact_trace = dict(sampled_at=now,pitch=pitch,roll=roll)
        clear = timed_call(diagnostic, 'rotation.native_probe',
            self._native_world_rotation_is_clear,
            position, start_yaw, end_yaw, descriptor,
            pitch=pitch, roll=roll, record_local=False,
            pivot_offset=pivot_offset, contact_trace=contact_trace,
            include_static=True, translation=translation,
            follow_ground=bool(bot_state.get('grounded_once') and not bot_state.get('airborne')
                and not bot_state.get('_edge_support_active')))
        if not clear:
            self._bot_motion_kinds[int(bot_id)] = 'world'
            bot_state['_rotation_contact_trace'] = contact_trace
        elif bot_state.get('alive', True):
            tree = self._tree_motion_proposal(
                position, start_yaw, end_position, end_yaw,
                0.0, descriptor, now, dt)
            clear = self._complete_bot_tree_contact(
                tree, position, start_yaw, end_position, end_yaw,
                descriptor, 0.0, now, dt, commit_enabled, 'clear') in ('clear', 'crushed')
        return clear

    @timed('bot.physics.translation')
    def _resolve_bot_motion(self, bot_id, position, yaw, speed,
                            descriptor, dt, now, commit_enabled=True,
                            motion_yaw=None):
        """Resolve Bot contact: static world first, then exact catalog."""
        diagnostic = getattr(self, '_combat_diagnostics', None)
        pos = self._vector(position)
        bot_state = getattr(self._bots, 'states', {}).get(int(bot_id), {})
        # Evidence only: candidate probes cannot apply HP. BotRuntime consumes
        # the primary realised hard contact before trying alternate headings.
        bot_state.pop('_world_contact_trace', None)
        if detailed_enabled():
            bot_state.pop('_passive_world_diagnostic_trace', None)
        airborne = bool(bot_state.get('airborne', False))
        movement_dir = int(bot_state.get('movement_dir', 0))
        rotation_dir = int(bot_state.get('rotation_dir', 0))
        turn_speed = getattr(
            self._bots, '_turn_speeds', {}).get(int(bot_id), 0.0)
        # Reuse a contained exact receipt when available. While its bounded
        # optimisation queue is pending, the complete dual-height, three-lane
        # native corridor from this same authority tick is sufficient; queue
        # pressure is not a physical collision and must not freeze the pose.
        corridor_reusable = getattr(
            self._bots, 'motion_world_corridor_reusable', None)
        if not callable(corridor_reusable):
            corridor_reusable = getattr(
                self._bots, 'motion_world_receipt_reusable', None)
        travel_yaw = (
            float(motion_yaw) if motion_yaw is not None else
            float(yaw) if speed >= 0.0 else float(yaw) + math.pi)
        contact_end = (
            float(position[0]) + math.sin(travel_yaw) * abs(speed) * dt,
            float(position[1]),
            float(position[2]) + math.cos(travel_yaw) * abs(speed) * dt)
        if not self._turret_motion_is_clear(
                vehicle_physics.collision_state_pose(
                    bot_state, position, yaw, 'bot:%d' % bot_id),
                vehicle_physics.collision_state_pose(
                    bot_state, contact_end, yaw, 'bot:%d' % bot_id), descriptor):
            self._bot_motion_kinds[int(bot_id)] = 'detached_turret'
            bot_state['_world_contact_trace'] = dict(reason='detached_turret',
                sampled_at=now, position=tuple(position), yaw=yaw, speed=speed,
                dt=dt, commit_enabled=commit_enabled)
            return 'hard'
        pose_pitch = _number(bot_state.get(
            'terrain_pitch', bot_state.get('pitch')))
        pose_roll = _number(bot_state.get('roll'))
        destructible_motion = {
            'pitch': pose_pitch,
            'roll': pose_roll,
        }
        if motion_yaw is not None:
            destructible_motion['motion_yaw'] = float(motion_yaw)
        tree = {'status': 'clear', 'requires_commit': False}
        if self._destructibles is not None and not airborne:
            tree = self._tree_motion_proposal(
                position, yaw, contact_end, yaw, speed, descriptor, now, dt)
            if tree.get('status') in ('pending', 'hard'):
                self._bot_motion_kinds[int(bot_id)] = 'tree_registry'
                tree = {'status': 'clear', 'requires_commit': False}
        if (commit_enabled and self._destructibles is not None and not airborne and
                movement_dir * float(speed) > 0.0 and rotation_dir == 0 and
                abs(turn_speed) <= 0.01 and callable(corridor_reusable) and
                corridor_reusable(
                    bot_id, position, travel_yaw, speed, now, dt) and
                not self._destructibles._catalog_hull_contact(
                    pos, yaw, speed, descriptor, dt,
                    **destructible_motion)):
            if diagnostic is not None:
                diagnostic.count('motion_world_reused')
            return self._complete_bot_tree_contact(
                tree, position, yaw, contact_end, yaw,
                descriptor, speed, now, dt, commit_enabled, 'clear')
        if diagnostic is not None:
            diagnostic.count('motion_world_fallback')
            if airborne:
                diagnostic.count('motion_world_airborne')
            elif movement_dir * float(speed) <= 0.0:
                diagnostic.count('motion_world_coast_or_reverse')
            elif rotation_dir != 0 or abs(turn_speed) > 0.01:
                diagnostic.count('motion_world_turning')
        allow_crush_drive = (
            not airborne and
            movement_dir * float(speed) > 0.0)
        kinetic_speed = None
        if allow_crush_drive:
            params = vehicle_physics.descriptor_drive_limits(descriptor)
            kinetic_speed = self._destructible_drive_speed_cap(
                descriptor, params, speed,
                self._bot_destructible_travel_descriptor(bot_id))
        contact_trace = {}
        world_status = world_collision.check_horizontal_collision(
            self._runtime.bigworld, self._runtime.math,
            self._avatar.spaceID, pos, yaw, speed, descriptor, airborne, dt,
            True, allow_crush_drive, kinetic_speed,
            commit_enabled=commit_enabled,
            pitch=pose_pitch, roll=pose_roll,
            motion_yaw=motion_yaw, trace=contact_trace, query_owner=self)
        if isinstance(world_status, bool):
            world_status = 'hard' if world_status else 'clear'
        self._bot_motion_kinds[int(bot_id)] = '-'
        if world_status == 'hard':
            bot_state['_world_contact_trace'] = dict(contact_trace,
                sampled_at=now, source='native_world', commit_enabled=commit_enabled)
            return 'hard'
        if self._destructibles is None:
            if detailed_enabled() and world_status != 'clear':
                bot_state['_passive_world_diagnostic_trace'] = dict(contact_trace,
                    source='native_world_without_catalog', status=world_status)
            return 'clear' if world_status == 'clear' else 'hard'
        if airborne:
            if detailed_enabled() and world_status != 'clear':
                bot_state['_passive_world_diagnostic_trace'] = dict(contact_trace,
                    source='native_world_airborne', status=world_status)
            return 'clear' if world_status == 'clear' else 'hard'
        # A native kinetic result is only a forward candidate.  Always hand it
        # to the catalog's exact contact seam; its ``approach`` result keeps a
        # nearby but non-contact prop clear without granting a destroy.
        if commit_enabled:
            detail = self._destructibles._catalog_motion_blocked(
                self._avatar.spaceID, pos, yaw, speed, descriptor, now,
                dt=dt, kinetic_speed=kinetic_speed, return_detail=True,
                kinetic_commit=allow_crush_drive,
                commit_enabled=True, **destructible_motion)
        else:
            # Use the existing mutation-free transaction proposal. Disabling
            # a commit is not evidence that its crushable contact is solid.
            detail = self._destructibles._catalog_motion_proposal(
                self._avatar.spaceID, pos, yaw, speed, descriptor, now,
                dt=dt, kinetic_speed=kinetic_speed, **destructible_motion)
        if isinstance(detail, bool):
            detail = {'status': 'hard' if detail else 'clear'}
        elif isinstance(detail, str):
            detail = {'status': detail}
        if not isinstance(detail, dict):
            raise RuntimeError('bot motion resolver detail is unavailable')
        status = detail.get('status')
        if status not in ('clear', 'crushed', 'soft', 'hard', 'approach'):
            raise RuntimeError(
                'bot motion resolver returned an invalid status')
        self._bot_motion_kinds[int(bot_id)] = str(detail.get('kinds', '-'))
        if status == 'hard':
            bot_state['_world_contact_trace'] = dict(reason='catalog_hard',
                sampled_at=now, position=tuple(position), yaw=yaw, speed=speed,
                dt=dt, commit_enabled=commit_enabled, catalog={key:detail.get(key)
                    for key in ('status', 'kinds', 'reason', 'token', 'requires_commit')})
            return 'hard'
        if not commit_enabled and detail.get('requires_commit', False):
            bot_state['_world_contact_trace'] = dict(reason='catalog_commit_required',
                sampled_at=now, position=tuple(position), yaw=yaw, speed=speed,
                dt=dt, commit_enabled=False, catalog={key:detail.get(key)
                    for key in ('status', 'kinds', 'token', 'requires_commit')})
            return 'commit_required'
        used_kinetic_speed = bool(detail.get('used_kinetic_speed', False))
        accepted_now = bool(detail.get('accepted_now', False))
        if detailed_enabled() and motion_yaw is not None:
            bot_state['_passive_world_diagnostic_trace'] = dict(
                source='realised_passive_catalog', status=status,
                speed=speed, kinetic_speed=kinetic_speed,
                allow_crush_drive=allow_crush_drive,
                accepted_now=accepted_now, used_kinetic_speed=used_kinetic_speed,
                token=detail.get('token'), requires_commit=detail.get('requires_commit'))
        if used_kinetic_speed and not (
                accepted_now and status == 'crushed' and
                detail.get('token')):
            raise RuntimeError('bot cap-crush receipt is inconsistent')
        if accepted_now and status in ('clear', 'approach', 'soft'):
            raise RuntimeError('bot contact receipt is inconsistent')
        if status == 'approach':
            return self._complete_bot_tree_contact(
                tree, position, yaw, contact_end, yaw,
                descriptor, speed, now, dt, commit_enabled, 'clear')
        if accepted_now:
            # The catalog has committed this exact contact. Check the new BSP
            # now so a real replacement wall blocks on the very same frame.
            after = world_collision.check_horizontal_collision(
                self._runtime.bigworld, self._runtime.math,
                self._avatar.spaceID, pos, yaw, speed,
                descriptor, airborne, dt, True,
                allow_crush_drive, kinetic_speed, commit_enabled=False,
                pitch=pose_pitch, roll=pose_roll,
                motion_yaw=motion_yaw, trace=contact_trace, query_owner=self)
            if after is True or after not in (False, 'clear', 'kinetic'):
                bot_state['_world_contact_trace'] = contact_trace
                self._bot_motion_kinds[int(bot_id)] = 'world'
                return 'hard'
        if status in ('clear', 'crushed'):
            return self._complete_bot_tree_contact(
                tree, position, yaw, contact_end, yaw,
                descriptor, speed, now, dt, commit_enabled, status)
        if detailed_enabled():
            bot_state['_passive_world_diagnostic_trace'] = dict(reason='catalog_' + status,
                sampled_at=now, position=tuple(position), yaw=yaw, speed=speed,
                dt=dt, commit_enabled=commit_enabled,
                native_status=world_status, native_contact=contact_trace,
                catalog={key: detail.get(key) for key in
                         ('status', 'kinds', 'reason', 'token', 'requires_commit')})
        return status

    @staticmethod
    def _collision_shape(descriptor):
        """Return the current 0.8.2 chassis hit-tester body."""
        return tank_collision.chassis_shape(descriptor)

    def _ram_pose_matrix(self, position, yaw, pitch=0.0, roll=0.0):
        matrix = self._runtime.math.Matrix()
        matrix.setRotateYPR((float(yaw), float(pitch), float(roll)))
        matrix.translation = self._vector(position)
        return matrix

    @staticmethod
    def _destructible_contact_token(value):
        """Canonicalise one exact destructible identity set for the LAN ledger."""
        if (not isinstance(value, (list, tuple)) or
                not 1 <= len(value) <= DESTRUCTIBLE_CONTACT_TOKEN_LIMIT):
            return None
        result = set()
        for raw in value:
            if not isinstance(raw, (list, tuple)) or len(raw) != 3:
                return None
            try:
                chunk_id = int(raw[0])
                item_index = int(raw[1])
                mat_kind = None if raw[2] is None else int(raw[2])
            except (TypeError, ValueError, OverflowError):
                return None
            if chunk_id < 0 or item_index < 0:
                return None
            result.add((chunk_id, item_index, mat_kind))
        return tuple(sorted(
            result, key=lambda row: (
                row[0], row[1], -1 if row[2] is None else row[2])))

    def _sight_collision_filter(self):
        """Return the broken-skin filter every spotting ray shares.

        A destroyed fence keeps its native skin in the world for the rest of
        the round, so an unfiltered mask-128 ray goes on treating it as cover.
        The filter is rebuilt on a short interval rather than per ray:
        spotting is the highest-volume ray consumer in the worker, and the
        callback resolves each hit against the live ledger anyway, so the only
        staleness is a fence that keeps blocking for at most one interval
        after it breaks.
        """
        if self._destructibles is None:
            return None
        now = self._clock()
        if (self._sight_filter_built_at is not None and
                now - self._sight_filter_built_at <
                SIGHT_COLLISION_FILTER_SECONDS and
                now >= self._sight_filter_built_at):
            return self._sight_filter
        probe = getattr(self._destructibles, 'sight_collision_filter', None)
        if not callable(probe):
            self._sight_filter = None
            self._sight_filter_built_at = now
            return None
        try:
            prepared = probe()
        except Exception:
            prepared = None
        self._sight_filter = prepared if callable(prepared) else None
        self._sight_filter_built_at = now
        return self._sight_filter

    def _spot_geometry(self, observer, target, observer_descriptor=None,
                       target_descriptor=None, fired_recently=False):
        """One native port to the six exact vehicle visibility checkpoints."""
        source_position = observer.get('position') or _xyz(observer)
        target_position = target.get('position') or _xyz(target)
        starts = spotting.vehicle_check_points(
            observer_descriptor, observer, observer=True,
            phase=int(max(0, self._turret_server_time_ms()) / 2000))
        ends = spotting.vehicle_check_points(target_descriptor, target)
        broken_filter = self._sight_collision_filter()
        collide_sight = getattr(self._destructibles, 'collide_sight_segment', None)
        report = getattr(self._destructibles, 'report_sight_contact', None)
        best_cover = None
        for start_point in starts:
            start = self._vector(start_point)
            for end_point in ends:
                end = self._vector(end_point)
                if callable(collide_sight):
                    hit = collide_sight(self._avatar.spaceID, start, end,
                        broken_filter, self._runtime.bigworld.wg_collideSegment)
                else:
                    args = (self._avatar.spaceID, start, end, 128)
                    if broken_filter is not None:
                        args += (broken_filter,)
                    hit = self._runtime.bigworld.wg_collideSegment(*args)
                if (hit is not None and
                        (hit[0] - start).length + spotting.SIGHT_END_TOLERANCE <
                        (end - start).length):
                    if callable(report):
                        report(self._avatar.spaceID, start, end, hit)
                    continue
                cover = self._foliage_camouflage_bonus(
                    source_position, target_position, fired_recently,
                    start_point, end_point)
                best_cover = cover if best_cover is None else min(best_cover, cover)
                if best_cover <= 0.0:
                    return {'line_of_sight': True, 'foliage_bonus': 0.0}
        return {'line_of_sight': best_cover is not None,
                'foliage_bonus': best_cover or 0.0}

    def _bot_visibility(self, source, target, fired_recently=False):
        descriptors = []
        for state in (source, target):
            kind = 'player' if state.get('kind') == 'human' else 'bot'
            actor = state.get('network_id', state.get('id', 0))
            record = self._records.get('%s:%s' % (kind, actor))
            entity = self._server_entity(record['engine_id']) if record else None
            descriptors.append(getattr(entity, 'typeDescriptor', None))
        return self._spot_geometry(source, target, descriptors[0], descriptors[1],
                                   fired_recently)

    def _bot_aim_context(self, source, target):
        """Keep candidate ownership on the current source/target records."""
        if not isinstance(source, dict):
            return None
        receipt = dict(at=self._last_frame_time, source=source.get('id'),
                       reason='target_unavailable')
        source['_aim_context_receipt'] = receipt
        if not isinstance(target, dict) or not target.get('alive', True):
            return None
        try:
            source_key = 'bot:%d' % int(source['id'])
            kind = 'player' if target.get('kind') == 'human' else 'bot'
            target_key = '%s:%d' % (
                kind, int(target.get('network_id', target.get('id'))))
        except (KeyError, TypeError, ValueError, OverflowError):
            receipt['reason'] = 'identity_invalid'
            return None
        receipt.update(source_key=source_key, target_key=target_key)
        source_record = self._records.get(source_key)
        target_record = self._records.get(target_key)
        receipt['records'] = [dict(present=row is not None,
            tombstone=row.get('tombstone') if row is not None else None,
            ready=row.get('ready') if row is not None else None)
            for row in (source_record, target_record)]
        if (source_record is None or target_record is None or
                source_record.get('tombstone') or
                target_record.get('tombstone') or
                not source_record.get('ready') or
                not target_record.get('ready')):
            receipt['reason'] = 'record_unavailable'
            return None
        source_entity = self._server_entity(source_record.get('engine_id'))
        target_entity = self._server_entity(target_record.get('engine_id'))
        receipt['entities_started'] = [bool(row is not None and getattr(row, 'isStarted', False))
                                       for row in (source_entity, target_entity)]
        if not all(receipt['entities_started']):
            receipt['reason'] = 'native_entity_unavailable'
            return None
        descriptor = getattr(target_entity, 'typeDescriptor', None)
        source_descriptor = getattr(source_entity, 'typeDescriptor', None)
        if descriptor is None or source_descriptor is None:
            receipt.update(reason='descriptor_unavailable', descriptors_present=[source_descriptor is not None, descriptor is not None])
            return None
        candidates = source_record.setdefault('bot_aim_targets', {})
        entry = candidates.get(target_key)
        geometry_ready = tuple(
            _field(_field(_field(descriptor, name), 'hitTester'),
                   'bbox') is not None for name in ('hull', 'turret'))
        if (entry is None or entry['record'] is not target_record or
                entry['descriptor'] is not descriptor or
                entry['geometry_ready'] != geometry_ready):
            entry = {'record': target_record, 'descriptor': descriptor,
                     'samples': shot_geometry.ordered_vehicle_aim_samples(descriptor),
                     'geometry_ready': geometry_ready,
                     'cursor': 0, 'selected': None}
            candidates[target_key] = entry
        receipt.update(reason='ready', selected=entry['selected'], cursor=entry['cursor'], geometry_ready=geometry_ready)
        return source_record, source_descriptor, entry

    def _bot_aim_point(self, source, target):
        """Project the selected part at the supplied, visibility-owned pose."""
        if not isinstance(source, dict):
            return None
        receipt = dict(at=self._last_frame_time, reason='context_unavailable')
        source['_aim_point_receipt'] = receipt
        try:
            context = self._bot_aim_context(source, target)
            receipt['context'] = dict(source.get('_aim_context_receipt') or {})
            receipt['lane'] = dict(source.get('_aim_candidate_receipt') or {})
            if context is None:
                return None
            entry = context[2]
            sample = entry['selected']
            if sample is None:
                receipt['reason'] = 'selection_missing'
                return None
            receipt.update(reason='selected', sample=sample)
            return {
                'aim_position': shot_geometry.vehicle_aim_point(sample, target),
                # Replacing an entity or descriptor invalidates a solved shot,
                # even when the replacement happens to have the same bbox.
                'aim_token': (id(entry['record']), id(entry['descriptor']),
                              sample),
            }
        except Exception as error:
            receipt.update(reason='point_exception', exception=type(error).__name__)
            return None

    def _bot_aim_damage_score(self, descriptor, entry, source, target,
                              origin, point):
        """Rank a tested sample with the existing #1513 armour resolver.

        The midpoint penetration/damage rolls make this an advisory nominal
        estimate. It neither samples nor commits the real projectile's RNG.
        """
        try:
            target_descriptor = entry['descriptor']
            for name in ('chassis', 'hull', 'turret', 'gun'):
                tester = _field(_field(target_descriptor, name), 'hitTester')
                if not callable(getattr(tester, 'localHitTest', None)):
                    return None
            yaw = target.get('yaw', 0.0)
            matrix = self._runtime.math.Matrix()
            matrix.setRotateYPR((yaw, target.get('pitch', 0.0),
                                 target.get('roll', 0.0)))
            position = self._vector(_xyz(target.get('position', target)))
            matrix.translation = position
            appearance = _ProjectileCollisionAppearance(
                self._runtime.math, target_descriptor,
                target.get('turret_yaw', target.get('aim_yaw', yaw) - yaw),
                target.get('gun_pitch', 0.0))
            proxy = _ProjectileCollisionTarget(
                None, target_descriptor, matrix, position, appearance,
                self._runtime.math)
            collisions = collide_vehicle_at_matrix(
                proxy, matrix, self._vector(origin), self._vector(point),
                self._runtime.math)
            if not collisions:
                return None
            shot = self._descriptor_shot(descriptor, source.get('shell_index', 0))
            distance = math.sqrt(sum((point[i] - origin[i]) ** 2 for i in range(3)))
            contact = combat_rules.resolve_armor_contact(
                shot, distance, collisions, penetration_factor=1.0)
            if contact is None:
                return None
            if contact['layer'] != 'structural' and not combat_rules.is_he(shot):
                return 0.0
            nominal = combat_rules.he_nominal_armor(collisions, target_descriptor)
            rolled_damage = combat_rules.shell_damage_roll(
                shot, random_gauss=lambda mean, unused_sigma: mean)
            return float(combat_rules.damage(
                shot, contact['result'], nominal,
                rolled_damage=rolled_damage))
        except Exception:
            return None

    def _bot_firing_lane(self, source, target):
        """Select a real exposed part with at most two static rays per job."""
        receipt = dict(at=self._last_frame_time, target_kind=target.get('kind'),
            target_id=target.get('network_id', target.get('id')),
            checks=[], selected=None, reason='context_unavailable')
        source['_aim_candidate_receipt'] = receipt
        profile = source.get('profile')
        profile = profile if isinstance(profile, dict) else {}
        if str(profile.get('class_tag') or '') == 'SPG':
            receipt['reason'] = 'artillery_owner'
            if self._artillery is None or self._bots is None:
                return False
            descriptor = self._bots._descriptors.get(int(source.get('id')))
            shell_index = max(0, int(source.get('shell_index', 0) or 0))
            ready, solution = self._artillery.request(
                source, target, descriptor, shell_index, self._clock())
            return bool(ready and solution is not None)
        entry = None
        try:
            context = self._bot_aim_context(source, target)
            if context is None:
                return False
            record, descriptor, entry = context
            samples = entry['samples']
            if not samples:
                receipt['reason'] = 'no_samples'
                return False
            pose_key = (id(descriptor), self._last_frame_time,
                        source.get('fire_seq', 0)) + tuple(source.get(name, 0.0)
                for name in ('x', 'y', 'z', 'yaw', 'pitch', 'roll',
                             'aim_yaw', 'turret_yaw', 'gun_pitch'))
            cached = record.get('bot_lane_origin')
            origin = cached[1] if cached and cached[0] == pose_key else None
            if origin is None:
                origin = self._bot_direct_launch_origin(
                    source, descriptor, source.get('shell_index', 0),
                    int(source.get('fire_seq', 0)) + 1, 0.0, 0.0, 0.0)
                if origin is None:
                    entry['selected'] = None
                    receipt['reason'] = 'launch_origin_unavailable'
                    return False
                record['bot_lane_origin'] = (pose_key, origin)
            selected = entry['selected']
            attempts = [selected] if selected is not None else []
            # Keep a still-clear part stable. On blockage, rotate through the
            # remaining bbox samples across the existing bounded lane jobs.
            visited = 0
            while len(attempts) < 2 and visited < len(samples):
                index = entry['cursor'] % len(samples)
                entry['cursor'] = (index + 1) % len(samples)
                visited += 1
                if samples[index] not in attempts:
                    attempts.append(samples[index])
            entry['selected'] = None
            # Neither end of this lane is its own blocker. Both are alive,
            # so neither is in the wreck view either; keep the exclusion
            # structural so a later predicate cannot strand every gunner.
            wreck_rows = self._bot_lane_wreck_rows()
            lane_ends = (record, entry['record'])
            best = None
            best_score = None
            exposed = None
            mechanical = receipt['checks']
            mechanical_fallback = None
            reach_probe = getattr(self._bots, 'bot_aim_point_reachable', None)
            for sample in attempts:
                point = shot_geometry.vehicle_aim_point(sample, target)
                check = dict(sample=sample, point=point, reachable=None, reason='world_blocked')
                mechanical.append(check)
                hit = self._runtime.bigworld.wg_collideSegment(
                    self._avatar.spaceID, self._vector(origin),
                    self._vector(point), 128)
                if hit is not None:
                    continue
                if self._wreck_blocks_bot_path(
                        wreck_rows, (origin, point), lane_ends):
                    check['reason'] = 'wreck_blocked'
                    continue
                reachable = (reach_probe(
                    source, target, descriptor, origin, point)
                    if callable(reach_probe) else None)
                check.update(reachable=reachable, reason=(
                    'mechanically_unreachable' if reachable is False else 'exposed'))
                if callable(reach_probe):
                    check['mechanical'] = source.get('_aim_reachability_receipt')
                if reachable is False:
                    # Keep an exposed fallback for bounded gun-angle recovery,
                    # but it cannot displace a reachable existing candidate.
                    if mechanical_fallback is None:
                        mechanical_fallback = sample
                    continue
                score = self._bot_aim_damage_score(
                    descriptor, entry, source, target, origin, point)
                if exposed is None:
                    exposed = sample
                # A part the armour resolver proved cannot be hurt is never a
                # deliberate choice at any competence, only a last resort
                # when nothing else in this job was clear.
                if score == 0.0:
                    continue
                if best is None or (score is not None and
                        best_score is not None and score > best_score):
                    best, best_score = sample, score
                # Missing material evidence cannot authorize a weak-spot
                # claim. Preserve the exposed-part behaviour in that case.
                if score is None:
                    break
            entry['selected'] = (best if best is not None else
                exposed if exposed is not None else mechanical_fallback)
            receipt.update(selected=entry['selected'], cursor=entry['cursor'],
                reason='selected' if best is not None or exposed is not None else
                       'mechanical_relocation_required' if mechanical_fallback is not None else 'blocked')
            return entry['selected'] is not None
        except Exception as error:
            receipt.update(reason='query_failed', error=type(error).__name__)
            if entry is not None:
                entry['selected'] = None
            return False
        return False

    def _bot_lane_rows(self, source_id, accept, prefilter=None):
        """Return the hulls one bot's shell could meet, with their poses.

        Every bot lane question - an ally on the parabola, a wreck across
        the aim ray - needs the same record skips, so one builder owns them.
        ``accept(record, state, vehicle)`` selects which hulls the question
        is about, and an optional ``prefilter(record, state)`` rejects one
        before its entity is resolved at all.  A ``source_id`` of ``None``
        keeps every bot, for a view whose consumers apply their own
        identity exclusions.
        """
        rows = []
        for record in self._records.values():
            if record.get('tombstone') or not record.get('ready'):
                continue
            if self._worker_mode and record.get('local'):
                continue
            if source_id is not None and record.get('kind') == 'bot':
                try:
                    if int(record.get('network_id')) == source_id:
                        continue
                except (TypeError, ValueError):
                    continue
            state = record.get('state') or {}
            if prefilter is not None and not prefilter(record, state):
                continue
            vehicle = self._server_entity(record.get('engine_id'))
            if vehicle is None or not getattr(vehicle, 'isStarted', False):
                continue
            if not accept(record, state, vehicle):
                continue
            position = (tuple(self._local_position)
                        if record.get('local') else
                        _xyz(getattr(vehicle, 'position', state)))
            rows.append((record, vehicle, position))
        return tuple(rows)

    def _wreck_lane_evidence(self, record, vehicle, points, blocked):
        """Observe the existing lane/model and projectile poses; never requery."""
        if not detailed_enabled():
            return
        from gui.mods.offline_lan_0922.native_input_diagnostics import battle_review_record
        def build():
            state = record.get('state') or {}
            native_aim, error = None, None
            try:
                appearance = vehicle.appearance
                turret = self._runtime.math.Matrix(appearance.turretMatrix)
                gun = self._runtime.math.Matrix(appearance.gunMatrix)
                native_aim = [float(turret.yaw), float(gun.pitch)]
            except Exception as failure:
                error = type(failure).__name__
            return dict(actor=record.get('network_id'), blocked=bool(blocked),
                ray_start=list(_xyz(points[0])), ray_end=list(_xyz(points[-1])),
                state=dict((key, state.get(key)) for key in
                    ('yaw', 'aim_yaw', 'turret_yaw', 'gun_pitch')),
                projectile_pose=record.get('projectile_collision_pose'),
                native_aim=native_aim, native_aim_error=error,
                native_aim_source='appearance_matrix_providers')
        battle_review_record(
            self, 'wreck_firing_lane', record.get('engine_id'),
            self._last_frame_time, build, interval=2.0, limit=256)

    def _bot_lane_row_contact(self, rows, points, splash_radius=0.0,
                              exclude=()):
        """Return the first supplied hull one bot shell path contacts.

        One broad phase and one body/ground pose dispatch, matching the
        projectile resolver, so a pose contract cannot be corrected for
        allies and missed for wrecks.  A native collision failure
        propagates to the caller, which decides what an unproved lane means.
        """
        terminal = points[-1]
        broadphase_sq = PROJECTILE_BROADPHASE_RADIUS ** 2
        for record, vehicle, position in rows:
            # Identity, never equality: two records with the same fields are
            # two vehicles, and a dict compare would walk both of them.
            if any(record is excluded for excluded in exclude):
                continue
            blocked = bool(
                splash_radius > 0.0 and
                sum((position[index] - terminal[index]) ** 2
                    for index in range(3)) <= splash_radius ** 2)
            tested = blocked
            if not blocked:
                for first, second in zip(points, points[1:]):
                    if (not point_in_expanded_segment_bounds(
                            position, first, second,
                            PROJECTILE_BROADPHASE_RADIUS) or
                            point_segment_distance_sq(
                                position, first, second) > broadphase_sq):
                        continue
                    start = self._vector(first)
                    end = self._vector(second)
                    tested = True
                    if (record.get('local') and
                            self._local_matrix is not None):
                        collisions = collide_vehicle_at_matrix(
                            vehicle, self._local_body_pose(), start, end,
                            self._runtime.math,
                            chassis_matrix=self._local_matrix)
                    elif record.get('native_remote'):
                        body_matrix, chassis_matrix = \
                            self._projectile_vehicle_matrices(
                                record, vehicle)
                        collisions = collide_vehicle_at_matrix(
                            vehicle, body_matrix, start, end,
                            self._runtime.math,
                            chassis_matrix=chassis_matrix)
                    else:
                        collide = getattr(
                            vehicle, 'collideSegmentExt', None)
                        collisions = (collide(start, end)
                                      if callable(collide) else ())
                    if collisions:
                        blocked = True
                        break
            if tested and not (record.get('state') or {}).get('alive', True):
                self._wreck_lane_evidence(record, vehicle, points, blocked)
            if blocked:
                return record, vehicle, position
        return None

    def _bot_friendly_path_verdict(
            self, source, path, splash_radius=0.0):
        """Reject shell obstructions, with escape metadata only for allies."""
        try:
            source_id = int(source.get('id'))
            source_team = int(source.get('team'))
            points = tuple(tuple(float(value) for value in point[:3])
                           for point in path)
            splash_radius = float(splash_radius)
        except (AttributeError, TypeError, ValueError, IndexError,
                OverflowError):
            return {'clear': False}
        if (len(points) < 2 or splash_radius < 0.0 or
                math.isnan(splash_radius) or math.isinf(splash_radius) or
                any(math.isnan(value) or math.isinf(value)
                    for point in points for value in point)):
            return {'clear': False}

        def is_ally(unused_record, state):
            try:
                return int(state.get('team')) == source_team
            except (TypeError, ValueError):
                return False

        def is_live(record, unused_state, vehicle):
            return self._record_alive(record, vehicle)

        try:
            # Candidate lanes may predate a wreck or its final shoved pose.
            # Recheck the frozen dispersed path for both direct guns and
            # SPGs. Dead hulls need no splash clearance or ally escape order.
            source_record = self._records.get('bot:%d' % source_id)
            if self._wreck_blocks_bot_path(
                    self._bot_lane_wreck_rows(), points, (source_record,)):
                return {'clear': False}
            contact = self._bot_lane_row_contact(
                self._bot_lane_rows(source_id, is_live, prefilter=is_ally),
                points, splash_radius=splash_radius)
        except Exception:
            return {'clear': False}
        if contact is None:
            return {'clear': True}
        record, vehicle, position = contact
        try:
            shape = tank_collision.chassis_shape(
                vehicle.typeDescriptor)
            blocker_radius = math.hypot(shape[0], shape[1])
        except Exception:
            fallback = tank_collision.DEFAULT_SHAPE
            blocker_radius = math.hypot(fallback[0], fallback[1])
        return {
            'clear': False,
            'blocker_kind': record.get('kind'),
            'blocker_id': record.get('network_id'),
            'blocker_team': source_team,
            'blocker_position': position,
            'blocker_radius': blocker_radius,
        }

    def _bot_lane_wreck_rows(self):
        """Materialise this frame's dead hulls once for every lane probe.

        Up to ``MAX_WORKER_SHOT_LANE_PAIRS_PER_FRAME`` pairs probe in one
        frame and every one of them meets the same wrecks, so rebuilding the
        record view per probe was the whole added cost. ``bot_lane_origin``
        beside this already reuses one frame the same way. Retiring on the
        record revision as well keeps a roster edit from being missed, and a
        death that lands mid-frame is admitted on the next one - far inside
        the ``SHOT_LANE_SECONDS`` window the verdict itself is cached for.
        """
        key = (self._last_frame_time, self._records_revision)
        cached = self._bot_lane_wreck_rows_cache
        if cached is not None and cached[0] == key:
            return cached[1]

        def is_wreck(record, unused_state, vehicle):
            return not self._record_alive(record, vehicle)

        rows = self._bot_lane_rows(None, is_wreck)
        self._bot_lane_wreck_rows_cache = (key, rows)
        return rows

    def _wreck_blocks_bot_path(self, rows, points, lane_ends=()):
        """Test dead hulls and landed turrets on supplied shell segments."""
        if rows and self._bot_lane_row_contact(
                rows, points, exclude=lane_ends) is not None:
            return True
        obstacles = self._detached_turret_obstacles
        if obstacles is None:
            return False
        # Reuse the resolver's accepted rest poses on the current server
        # clock. A future landing cannot obstruct a present lane proof.
        server_time_ms = self._turret_server_time_ms()
        return any(obstacles.block_distance(
            self._vector(first), self._vector(second), server_time_ms)
            is not None for first, second in zip(points, points[1:]))

    def _bot_friendly_firing_lane(
            self, source, unused_target, descriptor, shell_index, launch):
        """Check hulls and debris on the frozen direct-shell parabola."""
        try:
            source_id = int(source.get('id'))
            fire_seq = int(launch.get('fire_seq'))
            launch_shell_index = int(launch.get('shell_index'))
            shot_yaw = float(launch.get('shot_yaw'))
            shot_pitch = float(launch.get('shot_pitch'))
            flight_time = float(launch.get('flight_time'))
            origin = tuple(float(launch['origin'][index])
                           for index in range(3))
        except (AttributeError, KeyError, TypeError, ValueError, IndexError,
                OverflowError):
            return {'clear': False}
        if (fire_seq != int(source.get('fire_seq', 0)) + 1 or
                launch_shell_index != int(shell_index) or
                flight_time <= 0.0 or
                flight_time > ballistics.PROJECTILE_MAX_FLIGHT_SECONDS or
                any(math.isnan(value) or math.isinf(value) for value in (
                    shot_yaw, shot_pitch, flight_time) + origin)):
            return {'clear': False}
        try:
            shot = self._descriptor_shot(descriptor, shell_index)
            speed = float(_field(shot, 'speed'))
            gravity = abs(float(_field(shot, 'gravity')))
            maximum = float(_field(shot, 'maxDistance'))
            splash_radius = float(combat_rules.he_radius(shot))
        except (AttributeError, TypeError, ValueError, IndexError,
                OverflowError):
            return {'clear': False}
        if (speed <= 0.0 or gravity <= 0.0 or maximum <= 0.0 or
                speed * flight_time > maximum + 1e-6):
            return {'clear': False}
        path = ballistics.ballistic_path(
            # Protocol shot pitch is positive-up; the pure helper follows the
            # rendered BigWorld negative-is-up convention.
            origin, shot_yaw, -shot_pitch, speed, gravity, flight_time,
            PROJECTILE_MAX_SUBSTEP_SECONDS)
        return self._bot_friendly_path_verdict(
            source, path, splash_radius)

    def _bot_direct_launch_origin(
            self, source, descriptor, unused_shell_index,
            unused_fire_seq, unused_shot_yaw, unused_shot_pitch,
            unused_flight_time):
        """Freeze the physical shell at the gun pivot, before any wall.

        HP_gunFire remains the cosmetic flash/tracer origin. The pivot is the
        same #1513 transform that player gun rotation uses for a shot, so a
        barrel through cover cannot spawn a physical shell beyond that cover.
        """
        try:
            source_id = int(source.get('id'))
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None
        barrel = self._bot_barrel_point(source, descriptor)
        if barrel is None or self._barrel_under_water(barrel):
            return None
        source_record = self._records.get('bot:%s' % source_id)
        if source_record is None:
            return None
        source_entity = self._server_entity(source_record.get('engine_id'))
        if (source_entity is None or
                not getattr(source_entity, 'isStarted', False)):
            return None
        try:
            pose = self._projectile_plain_pose((
                _number(source.get('x')), _number(source.get('y')),
                _number(source.get('z'))), source)
            origin, unused_direction = shot_geometry.shot_origin_and_direction(
                descriptor, (pose['x'], pose['y'], pose['z']),
                pose['yaw'], pose['pitch'], pose['roll'],
                pose['turret_yaw'], pose['gun_pitch'])
        except Exception:
            return None
        return origin

    def _bot_artillery_planning_origin(self, source, descriptor):
        """Use the same gun pivot for SPG planning and launch proof."""
        return self._bot_direct_launch_origin(
            source, descriptor, 0, 0, 0.0, 0.0, 0.0)

    def _bot_artillery_aim_samples(self, source, target):
        """Reuse native model parts only after the legacy SPG point is refused."""
        context = self._bot_aim_context(source, target)
        if context is None:
            return ()
        entry = context[2]
        return tuple(((id(entry['record']), id(entry['descriptor']), sample),
                      shot_geometry.vehicle_aim_point(sample, target))
                     for sample in entry['samples'])

    def _bot_artillery_status(self, source, target, shell_index, now):
        return self._artillery.status(source, target, shell_index, now)

    def _bot_ballistic_solution(self, source, target, descriptor,
                                shell_index, now):
        """Return only a completed SPG arc; pending/blocked stays unshootable."""
        if self._artillery is None or target is None:
            return None
        return self._artillery.solution(
            source, target, descriptor, shell_index, now)

    def _bot_artillery_launch(
            self, source, target, descriptor, shell_index, fire_seq,
            shot_yaw, shot_pitch, flight_time, now):
        """Prove the exact dispersed SPG path from its physical gun pivot."""
        if (self._artillery is None or not isinstance(source, dict) or
                not isinstance(target, dict)):
            return None
        try:
            bot_id = int(source.get('id'))
        except (TypeError, ValueError, OverflowError):
            return None
        record = self._records.get('bot:%s' % bot_id)
        if record is None:
            return None
        entity = self._server_entity(record.get('engine_id'))
        if (entity is None or not getattr(entity, 'isStarted', False) or
                getattr(entity, 'typeDescriptor', None) is None):
            return None
        origin = self._bot_direct_launch_origin(
            source, descriptor, shell_index, fire_seq,
            shot_yaw, shot_pitch, flight_time)
        if origin is None:
            return None
        ready, receipt = self._artillery.request_launch(
            source, target, descriptor, int(shell_index), int(fire_seq),
            origin, float(shot_yaw), float(shot_pitch),
            float(flight_time), float(now))
        if ready and receipt is None:
            failure = self._artillery.status(
                source, target, int(shell_index), now).get('launch') or {}
            if failure.get('state') == 'failed':
                self._artillery.reject_launch_arc(
                    source, target, int(shell_index),
                    source.get('_artillery_arc') if
                    failure.get('reason') == 'world_blocked' else None,
                    source.get('_artillery_planned_target'), now)
                return dict(failure, launch_failed=True,
                            fire_seq=int(fire_seq), shell_index=int(shell_index))
        return receipt if ready and isinstance(receipt, dict) else None

    def _bot_artillery_friendly_lane(
            self, source, unused_target, descriptor, shell_index, receipt):
        """Check SPG shell obstructions and live allies near the HE terminal."""
        try:
            raw_path = receipt.get('path')
            if not isinstance(raw_path, (list, tuple)) or len(raw_path) < 2:
                return {'clear': False}
            path = []
            for raw in raw_path:
                point = tuple(float(raw[index]) for index in range(3))
                if any(math.isnan(value) or math.isinf(value)
                       for value in point):
                    return {'clear': False}
                path.append(point)
        except (AttributeError, TypeError, ValueError, IndexError,
                OverflowError):
            return {'clear': False}
        try:
            shot = self._descriptor_shot(descriptor, shell_index)
            splash_radius = float(combat_rules.he_radius(shot))
            if (math.isnan(splash_radius) or math.isinf(splash_radius) or
                    splash_radius < 0.0):
                return {'clear': False}
        except (AttributeError, TypeError, ValueError, IndexError,
                OverflowError):
            return {'clear': False}
        return self._bot_friendly_path_verdict(
            source, path, splash_radius)

    def _bot_artillery_cancel(self, source):
        """Discard bounded arc work for a cancelled frozen SPG intent."""
        if self._artillery is None or not isinstance(source, dict):
            return False
        return bool(self._artillery.cancel_launch(source))

    def _artillery_arc_probe(self, start, end):
        """Check one budgeted SPG chord against scenery and retained wrecks."""
        hit = self._runtime.bigworld.wg_collideSegment(
            self._avatar.spaceID, self._vector(start), self._vector(end), 128)
        try:
            finish = _xyz(hit[0]) if hit is not None else _xyz(end)
        except Exception:
            return False
        # A ground hit near the target may be accepted by the arc queue;
        # a wreck before it must reject this candidate even near the target.
        if self._wreck_blocks_bot_path(
                self._bot_lane_wreck_rows(), (_xyz(start), finish)):
            return False
        return finish if hit is not None else None

    @staticmethod
    def _record_alive(record, entity):
        state = record.get('state') or {}
        if 'alive' in state:
            return bool(state.get('alive')) and int(
                state.get('health', 1) or 0) > 0
        alive = getattr(entity, 'isAlive', None)
        return bool(alive() if callable(alive) else alive)

    def _foliage_camouflage_bonus(self, observer, target, fired_recently,
                                  start=None, end=None):
        if (self._foliage is None or not self._optional_feature_enabled(
                'foliage camouflage')):
            return 0.0
        try:
            if start is not None and end is not None:
                return self._foliage.camouflage_bonus(
                    observer, target, fired_recently, start=start, end=end)
            return self._foliage.camouflage_bonus(
                observer, target, fired_recently)
        except Exception as error:
            self._foliage = None
            self._warn_optional_failure('foliage camouflage', error)
            return 0.0

    def _turret_server_time_ms(self, now=None):
        """Use the projectile clock, including historical chord timestamps."""
        if (self._projectile_server_time_ms is None or
                self._projectile_server_local_time is None):
            return -1
        if now is None:
            now = self._clock()
        return max(0, int(self._projectile_server_time_ms + 1000.0 *
                          (float(now) - self._projectile_server_local_time)))

    @staticmethod
    def _descriptor_shot(descriptor, shell_index=None):
        shots = tuple(descriptor.gun.shots or ())
        if shell_index is None:
            shell_index = getattr(descriptor, 'activeGunShotIndex', 0)
        index = max(0, min(int(shell_index), max(0, len(shots) - 1)))
        return shots[index] if shots else {}
