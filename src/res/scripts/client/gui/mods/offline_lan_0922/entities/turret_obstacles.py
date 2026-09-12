# -*- coding: utf-8 -*-
"""Collision and worker-owned vehicle support for detached turret poses.

The native turret and gun hit testers remain separate. Their descriptor boxes
bound vehicle contact and navigation; shells still use the exact hit testers.
Every query uses the accepted rest pose and server clock, never a local arc.
"""

import copy
import math

from gui.mods.offline_lan_0922 import destructibles_sensor
from gui.mods.offline_lan_0922 import shot_geometry
from gui.mods.offline_lan_0922 import turret_detachment


_ROTATION_SLICE = math.pi / 36.0
_CONTACT_EPSILON = 1.0e-7


def _finite(value):
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise ValueError('detached turret geometry is not finite')
    return value


def _xyz(value):
    if hasattr(value, 'x'):
        return (_finite(value.x), _finite(value.y), _finite(value.z))
    if len(value) != 3:
        raise ValueError('detached turret geometry needs three coordinates')
    return tuple(_finite(value[index]) for index in range(3))


def _add(left, right):
    return tuple(left[axis] + right[axis] for axis in range(3))


def _subtract(left, right):
    return tuple(left[axis] - right[axis] for axis in range(3))


def _scale(vector, scale):
    return tuple(value * scale for value in vector)


def _dot(left, right):
    return sum(left[axis] * right[axis] for axis in range(3))


def component_bounds(component):
    """Read a loaded descriptor box without substituting guessed dimensions."""
    tester = getattr(component, 'hitTester', None)
    bbox = getattr(tester, 'bbox', None)
    try:
        lower, upper = _xyz(bbox[0]), _xyz(bbox[1])
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        raise ValueError('detached turret component bounds are unavailable')
    if any(lower[axis] >= upper[axis] for axis in range(3)):
        raise ValueError('detached turret component bounds are empty')
    return lower, upper


def _corners(bounds, offset=(0.0, 0.0, 0.0)):
    lower, upper = bounds
    return tuple((x + offset[0], y + offset[1], z + offset[2])
                 for x in (lower[0], upper[0])
                 for y in (lower[1], upper[1])
                 for z in (lower[2], upper[2]))


def turret_components(descriptor):
    """Return the two descriptor components below the detached turret root."""
    turret = getattr(descriptor, 'turret', None)
    gun = getattr(descriptor, 'gun', None)
    try:
        gun_position = _xyz(turret.gunPosition)
    except (AttributeError, IndexError, TypeError, ValueError):
        raise ValueError('detached turret gun mount is unavailable')
    components = []
    for name, component, offset in (
            ('turret', turret, (0.0, 0.0, 0.0)),
            ('gun', gun, gun_position)):
        tester = getattr(component, 'hitTester', None)
        if not callable(getattr(tester, 'localHitTest', None)):
            raise ValueError('detached turret hit tester is unavailable')
        components.append((name, component, offset, component_bounds(component)))
    return tuple(components)


def rest_on_component_bounds(flight, attitude, spin, components):
    """Place the final rotated turret/gun underside on the accepted contact."""
    result = copy.deepcopy(flight)
    if not result.get('landed'):
        return result
    rest_attitude = turret_detachment.rest_attitude(
        attitude, spin, result['duration'])
    lowest = min(shot_geometry.transform_vehicle_vector(
        corner, *rest_attitude)[1]
        for unused_name, unused_component, offset, bounds in components
        for corner in _corners(bounds, offset))
    rest = _xyz(result['rest'])
    contact = _xyz(result['contact'])
    result['rest'] = (rest[0], contact[1] - lowest, rest[2])
    return result


def _world_box(bounds, offset, position, attitude):
    lower, upper = bounds
    center = tuple((lower[axis] + upper[axis]) * 0.5 + offset[axis]
                   for axis in range(3))
    center = _add(position, shot_geometry.transform_vehicle_vector(
        center, *attitude))
    half_axes = []
    for axis in range(3):
        local = [0.0, 0.0, 0.0]
        local[axis] = (upper[axis] - lower[axis]) * 0.5
        half_axes.append(shot_geometry.transform_vehicle_vector(
            local, *attitude))
    return center, tuple(half_axes)


def _boxes_world_bounds(boxes):
    """Enclose the supplied component boxes in one world AABB."""
    lower = None
    upper = None
    for center, half_axes in boxes:
        for index in range(1 << len(half_axes)):
            point = center
            for axis, half in enumerate(half_axes):
                point = (_add(point, half) if (index >> axis) & 1
                         else _subtract(point, half))
            if lower is None:
                lower = list(point)
                upper = list(point)
                continue
            for axis in range(3):
                if point[axis] < lower[axis]:
                    lower[axis] = point[axis]
                elif point[axis] > upper[axis]:
                    upper[axis] = point[axis]
    if lower is None:
        return None
    return tuple(lower), tuple(upper)


def _segment_distance_squared(point, start, end):
    direction = _subtract(end, start)
    delta = _subtract(point, start)
    length_squared = _dot(direction, direction)
    ratio = (max(0.0, min(1.0, _dot(delta, direction) / length_squared))
             if length_squared > 0.0 else 0.0)
    closest = _subtract(delta, _scale(direction, ratio))
    return _dot(closest, closest)


def _read_pose(pose):
    position = tuple(_finite(pose[name]) for name in ('x', 'y', 'z'))
    attitude = tuple(_finite(pose.get(name, 0.0))
                     for name in ('yaw', 'pitch', 'roll'))
    return position, attitude


def _moving_components(descriptor):
    chassis = getattr(descriptor, 'chassis', None)
    hull = getattr(descriptor, 'hull', None)
    try:
        hull_position = _xyz(chassis.hullPosition)
    except (AttributeError, IndexError, TypeError, ValueError):
        raise ValueError('moving vehicle hull mount is unavailable')
    return (('chassis', component_bounds(chassis), (0.0, 0.0, 0.0)),
            ('hull', component_bounds(hull), hull_position))


def _component_sweeps(bounds, offset, start, end):
    """Cover the continuous translated and rotated box without contact rays.

    Fixed orientation uses its exact four-generator swept zonotope. For a
    changing Euler pose, a bounded angular slice adds the analytic maximum
    displacement of any descriptor corner from its midpoint orientation.
    Translation stays exact within each slice. This includes pitch and roll.
    """
    start_position, start_attitude = start
    end_position, end_attitude = end
    travel = _subtract(end_position, start_position)
    deltas = tuple((end_attitude[axis] - start_attitude[axis] + math.pi) %
                   (2.0 * math.pi) - math.pi for axis in range(3))
    rotation = sum(abs(value) for value in deltas)
    steps = max(1, int(math.ceil(rotation / _ROTATION_SLICE)))
    radius = max(math.sqrt(_dot(corner, corner))
                 for corner in _corners(bounds, offset))
    # Every vector differs by at most 2*r*sin(theta/2), with theta bounded
    # by the sum of the three Euler rotations from the slice midpoint.
    padding = 2.0 * radius * math.sin(rotation / (4.0 * steps))
    boxes = []
    for index in range(steps):
        middle = (float(index) + 0.5) / steps
        attitude = tuple(start_attitude[axis] + deltas[axis] * middle
                         for axis in range(3))
        position = _add(start_position, _scale(travel, middle))
        center, axes = _world_box(bounds, offset, position, attitude)
        axes = axes + (_scale(travel, 0.5 / steps),)
        if padding > 0.0:
            axes += ((padding, 0.0, 0.0), (0.0, padding, 0.0),
                     (0.0, 0.0, padding))
        boxes.append((center, axes))
    return tuple(boxes)


def _box_gap(box, obstacle, normal):
    distance = _dot(_subtract(box[0], obstacle[0]), normal)
    radius = sum(abs(_dot(axis, normal)) for axis in box[1] + obstacle[1])
    return distance - radius


def _leaves_overlap(initial, final, sweeps, obstacle):
    """Permit a gradual exit along the first contact's shallowest face.

    Checking the entire sweep's support prevents a tank from crossing through
    the far face merely because its endpoint happens to lie outside the box.
    A rotation that may deepen contact remains blocked; straight retreat is
    exact and needs no invented contact margin.
    """
    generators = initial[1] + obstacle[1]
    delta = _subtract(initial[0], obstacle[0])
    motion = _subtract(final[0], initial[0])
    candidates = []
    for left in range(len(generators)):
        for right in range(left + 1, len(generators)):
            axis = destructibles_sensor._vector_cross(
                generators[left], generators[right])
            length = math.sqrt(_dot(axis, axis))
            if length <= 1.0e-8:
                continue
            axis = _scale(axis, 1.0 / length)
            facing = _dot(delta, axis)
            if facing < 0.0 or (abs(facing) <= _CONTACT_EPSILON and
                                _dot(motion, axis) < 0.0):
                axis = _scale(axis, -1.0)
            candidates.append((_box_gap(initial, obstacle, axis), axis))
    if not candidates:
        return False
    initial_gap, normal = max(candidates, key=lambda value: value[0])
    if _box_gap(final, obstacle, normal) > initial_gap + _CONTACT_EPSILON:
        return all(_box_gap(sweep, obstacle, normal) >=
                   initial_gap - _CONTACT_EPSILON for sweep in sweeps)

    # A turret can become solid while a hull is already below it. Its
    # shallowest separating face then points down into the ground. Requiring
    # improvement on that face alone vetoes every horizontal escape, even a
    # one-centimetre retreat that never increases penetration.
    #
    # Admit tangential escape only from this overhead contact, preserving its
    # entire vertical support and an outward horizontal face throughout the
    # sweep. New contacts still block in sweep_blocks, and a turn that deepens
    # the overhead overlap remains blocked.
    if (normal[1] >= 0.0 or
            abs(normal[1]) <= max(abs(normal[0]), abs(normal[2])) or
            any(_box_gap(sweep, obstacle, normal) <
                initial_gap - _CONTACT_EPSILON for sweep in sweeps)):
        return False
    # Suspension and final-pose guards may recheck the unchanged pose after
    # the horizontal slice. Holding an existing overhead overlap cannot make
    # it worse; vetoing that no-op would reset the drivetrain before it can
    # take the next outward step.
    if final == initial:
        return True
    for gap, axis in candidates:
        if abs(axis[1]) > _CONTACT_EPSILON:
            continue
        if (_box_gap(final, obstacle, axis) > gap + _CONTACT_EPSILON and
                all(_box_gap(sweep, obstacle, axis) >=
                    gap - _CONTACT_EPSILON for sweep in sweeps)):
            return True
    return False


def vehicle_support_boxes(descriptor, pose, attached=True):
    """Use the loaded component boxes in their chassis/body/turret frames."""
    boxes = []
    for name, bounds, offset in _moving_components(descriptor):
        position, attitude = _read_pose(pose.get(name, pose))
        boxes.append(_world_box(bounds, offset, position, attitude))
    if attached:
        position, attitude = _read_pose(pose.get('hull', pose))
        hull_offset = _xyz(descriptor.chassis.hullPosition)
        turret_offset = _xyz(descriptor.hull.turretPositions[0])
        turret_yaw = float(pose.get('aim_yaw', pose['yaw'])) - pose['yaw']
        turret_angle = (turret_yaw, 0.0, 0.0)
        turret_mount = _add(hull_offset, turret_offset)
        gun_angle = (0.0, float(pose.get('gun_pitch', 0.0)), 0.0)
        for component, offset, local_angle in (
                (descriptor.turret, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
                (descriptor.gun, _xyz(descriptor.turret.gunPosition), gun_angle)):
            center, axes = _world_box(component_bounds(component),
                                      (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), local_angle)
            center = _add(turret_mount, shot_geometry.transform_vehicle_vector(
                _add(center, offset), *turret_angle))
            center = _add(position, shot_geometry.transform_vehicle_vector(center, *attitude))
            axes = tuple(shot_geometry.transform_vehicle_vector(
                shot_geometry.transform_vehicle_vector(axis, *turret_angle), *attitude)
                         for axis in axes)
            boxes.append((center, axes))
    return tuple(boxes)


def vertical_contact_interval(box, support):
    """Exact translations along world Y for which two convex boxes overlap.

    Intersect SAT slabs along all face/edge axes. Unlike an AABB roof, the
    upper endpoint lies on the rotated support, including a sloping hull.
    """
    generators = box[1] + support[1]
    delta = _subtract(box[0], support[0])
    low, high = -float('inf'), float('inf')
    for i, left in enumerate(generators):
        for right in generators[i + 1:]:
            axis = destructibles_sensor._vector_cross(left, right)
            radius = sum(abs(_dot(part, axis)) for part in generators)
            separation = _dot(delta, axis)
            if abs(axis[1]) < 1e-10:
                if abs(separation) > radius + _CONTACT_EPSILON:
                    return None
                continue
            a = (-radius - separation) / axis[1]
            b = (radius - separation) / axis[1]
            low, high = max(low, min(a, b)), min(high, max(a, b))
            if low > high:
                return None
    return None if math.isinf(high) else (low, high)


def update_vehicle_support(row, components, bodies, previous_ms, now_ms, collide):
    """Stop a descending throw on a current vehicle, or drop it when shed.

    Only the worker calls this. The result is a revision of the same wreck,
    used by both collision and presentation. No native rigid-body API or
    guessed turret dimensions are involved.
    """
    created = row['created_time_ms']
    elapsed = max(0.0, (now_ms - created) / 1000.0)
    previous = max(0.0, (previous_ms - created) / 1000.0)
    flight = row['flight']
    start = turret_detachment.pose_at(flight, row['attitude'], row['spin'], previous)
    end = turret_detachment.pose_at(flight, row['attitude'], row['spin'], elapsed)
    held = row.get('support_key')
    landed = elapsed >= flight['duration']
    # Ascending throws must not catch their own source hull.
    if not held and not landed and end[0][1] > start[0][1]:
        return None
    sweeps = tuple(sweep
                   for unused_name, unused_component, offset, bounds in components
                   for sweep in _component_sweeps(bounds, offset, start, end))
    def near(box, support):
        return all(abs(box[0][i] - support[0][i]) <=
                   sum(abs(axis[i]) for axis in box[1] + support[1]) + _CONTACT_EPSILON
                   for i in range(3))
    contact_bodies = []
    for key, boxes in bodies:
        if not held:
            hit = any(near(sweep, support) and
                      destructibles_sensor._boxes_intersect(sweep, support)
                      for sweep in sweeps for support in boxes)
            if not hit:
                continue
        contact_bodies.append((key, boxes))
    if not contact_bodies and not held:
        return None
    # Find the first occupied part of this tick's arc rather than letting a
    # fast descending turret pass through a roof between disjoint endpoints.
    contact_time = elapsed
    if not held and not landed and previous < elapsed:
        low, high = previous, elapsed
        for unused in range(18):
            mid = (low + high) * 0.5
            middle = turret_detachment.pose_at(flight, row['attitude'], row['spin'], mid)
            hit = any(destructibles_sensor._boxes_intersect(sweep, support)
                      for unused_name, unused_component, offset, bounds in components
                      for sweep in _component_sweeps(bounds, offset, start, middle)
                      for unused_key, boxes in contact_bodies for support in boxes)
            if hit:
                high = mid
            else:
                low = mid
        contact_time = high
        end = turret_detachment.pose_at(flight, row['attitude'], row['spin'], contact_time)
    lifting = []
    for key, boxes in contact_bodies:
        for unused_name, unused_component, offset, bounds in components:
            box = _world_box(bounds, offset, *end)
            for support in boxes:
                interval = vertical_contact_interval(box, support)
                if interval is None:
                    continue
                # A held turret follows the roof vertically while its X/Z
                # stays free: driving out from underneath sheds it.
                if held == key or interval[0] <= _CONTACT_EPSILON <= interval[1] + _CONTACT_EPSILON:
                    lifting.append((interval[1], key))
    result = copy.deepcopy(row)
    if lifting:
        lift, support_key = max(lifting)
        rest = (end[0][0], end[0][1] + lift, end[0][2])
        if (held == support_key and
                max(abs(rest[i] - flight['rest'][i]) for i in range(3)) < 1e-6):
            return None
        result['attitude'] = tuple(end[1])
        result['spin'] = (0.0, 0.0, 0.0)
        result['support_key'] = support_key
        result['flight'] = {
            'origin': rest, 'velocity': (0.0, 0.0, 0.0),
            'segments': [{'origin': rest, 'velocity': (0.0, 0.0, 0.0),
                          'start': 0.0, 'duration': 0.0}],
            'duration': 0.0, 'rest': rest, 'contact': rest,
            'impact_velocity': (0.0, 0.0, 0.0), 'energy': 0.0,
            'landed': True, 'rest_attitude': tuple(end[1]),
        }
    elif held:
        # The supporting vehicle has left. Resume the existing gravity law
        # from this rest pose; never leave a permanent floating obstacle.
        resumed = turret_detachment.resolve_flight(
            end[0], (0.0, 0.0, 0.0), collide, clearance=0.0)
        resumed = rest_on_component_bounds(resumed, end[1], (0.0, 0.0, 0.0), components)
        result['attitude'], result['spin'] = end[1], (0.0, 0.0, 0.0)
        result['flight'] = resumed
        result['support_key'] = None
    else:
        return None
    result['motion_seq'] = row.get('motion_seq', 0) + 1
    result['motion_time_ms'] = int(now_ms)
    result['created_time_ms'] = int(now_ms)
    return result


class DetachedTurretObstacles(object):
    """Own the newest server-accepted geometry for one battle round."""

    def __init__(self, math_module, log=None):
        self._math = math_module
        self._log = log
        self._turrets = {}

    def active(self):
        return len(self._turrets)

    def add(self, key, row, descriptor):
        previous = self._turrets.get(key)
        if previous is not None and row.get('motion_seq', 0) <= previous['row'].get('motion_seq', 0):
            return False
        flight = row['flight']
        if not flight.get('landed'):
            self._turrets.pop(key, None)
            return previous is not None
        components = turret_components(descriptor)
        rest = _xyz(flight['rest'])
        attitude = tuple(flight.get('rest_attitude') or turret_detachment.rest_attitude(
            row['attitude'], row['spin'], flight['duration']))
        radius = max(math.sqrt(_dot(corner, corner))
                     for unused_name, unused_component, offset, bounds in components
                     for corner in _corners(bounds, offset))
        boxes = tuple(_world_box(bounds, offset, rest, attitude)
                      for unused_name, unused_component, offset, bounds in components)
        actor_id = int(row['actor_id'])
        namespace = 0 if row['actor_kind'] == 'bot' else 1
        hulls = []
        for index, box in enumerate(boxes):
            points = destructibles_sensor._tree_xz_zonotope_hull_1513(box)
            # Grid's static-hull contract uses a yaw rectangle. Project all
            # eight 3-D corners into that frame, including pitch and roll.
            local = [shot_geometry.inverse_transform_vehicle_vector(
                (point[0] - rest[0], 0.0, point[1] - rest[2]),
                attitude[0], 0.0, 0.0) for point in points]
            x0, x1 = min(point[0] for point in local), max(point[0] for point in local)
            z0, z1 = min(point[2] for point in local), max(point[2] for point in local)
            center = shot_geometry.transform_vehicle_vector(
                ((x0 + x1) * 0.5, 0.0, (z0 + z1) * 0.5), attitude[0])
            hulls.append((-(actor_id * 4 + namespace * 2 + index + 1),
                          rest[0] + center[0], rest[2] + center[2], attitude[0],
                          (z1 - z0) * 0.5, (x1 - x0) * 0.5))
        self._turrets[key] = {
            'row': copy.deepcopy(row), 'components': components, 'rest': rest,
            'attitude': attitude, 'radius': radius, 'boxes': boxes,
            'target_bounds': _boxes_world_bounds(boxes),
            'hulls': tuple(hulls),
            'settles_at_ms': (_finite(row['created_time_ms']) +
                              1000.0 * _finite(flight['duration'])),
        }
        return True

    def _ready(self, server_time_ms):
        now = _finite(server_time_ms)
        return (turret for turret in self._turrets.values()
                if now >= turret['settles_at_ms'])

    def block_distance(self, start, end, server_time_ms, start_time_ms=None):
        origin, finish = _xyz(start), _xyz(end)
        length = math.sqrt(_dot(_subtract(finish, origin),
                                _subtract(finish, origin)))
        nearest = None
        end_time = _finite(server_time_ms)
        start_time = end_time if start_time_ms is None else _finite(start_time_ms)
        if start_time > end_time:
            raise ValueError('detached turret chord clock runs backwards')
        for turret in self._ready(server_time_ms):
            if _segment_distance_squared(turret['rest'], origin, finish) > \
                    turret['radius'] ** 2:
                continue
            local_start = shot_geometry.inverse_transform_vehicle_vector(
                _subtract(origin, turret['rest']), *turret['attitude'])
            local_end = shot_geometry.inverse_transform_vehicle_vector(
                _subtract(finish, turret['rest']), *turret['attitude'])
            for unused_name, component, offset, unused_bounds in turret['components']:
                try:
                    collisions = component.hitTester.localHitTest(
                        self._math.Vector3(*_subtract(local_start, offset)),
                        self._math.Vector3(*_subtract(local_end, offset)))
                    for collision in collisions or ():
                        distance = _finite(collision[0])
                        if 0.0 <= distance <= length and (
                                nearest is None or distance < nearest):
                            hit_time = start_time + (end_time - start_time) * (
                                distance / length if length > 0.0 else 0.0)
                            if hit_time < turret['settles_at_ms']:
                                continue
                            nearest = distance
                except Exception as error:
                    if callable(self._log):
                        self._log('detached turret hit test failed', error)
        return nearest

    def target_entry_distance(self, start, end, server_time_ms):
        """Return where a cursor ray first enters a landed turret's bounds.

        #1513 DetachedTurret.__init__ enables targetFullBounds and sets
        targetCaps = [1]. This local bounds approximation uses only settled
        turrets, matching the accepted pose used by the obstacle queries;
        it does not establish the shipped native picker's selection rule.
        """
        nearest = None
        for turret in self._ready(server_time_ms):
            distance = shot_geometry.segment_box_entry_distance(
                start, end, turret['target_bounds'])
            if distance is not None and (nearest is None or
                                         distance < nearest):
                nearest = distance
        return nearest

    def sweep_blocks(self, start_pose, end_pose, descriptor, server_time_ms):
        ready = tuple(self._ready(server_time_ms))
        if not ready:
            return False
        for name, bounds, offset in _moving_components(descriptor):
            # Hydraulic bodies use a different frame from their chassis.
            # Ordinary vehicles keep the shared root pose contract.
            start = _read_pose(start_pose.get(name, start_pose))
            end = _read_pose(end_pose.get(name, end_pose))
            initial = _world_box(bounds, offset, *start)
            final = _world_box(bounds, offset, *end)
            sweeps = _component_sweeps(bounds, offset, start, end)
            moving_radius = max(math.sqrt(_dot(corner, corner))
                                for corner in _corners(bounds, offset))
            for turret in ready:
                if (start_pose.get('actor_key') is not None and
                        turret['row'].get('support_key') == start_pose['actor_key']):
                    continue
                if _segment_distance_squared(
                        turret['rest'], start[0], end[0]) > \
                        (turret['radius'] + moving_radius) ** 2:
                    continue
                for obstacle in turret['boxes']:
                    if not any(destructibles_sensor._boxes_intersect(
                            sweep, obstacle) for sweep in sweeps):
                        continue
                    if (destructibles_sensor._boxes_intersect(initial, obstacle) and
                            _leaves_overlap(initial, final, sweeps, obstacle)):
                        continue
                    return True
        return False

    def navigation_hulls(self, server_time_ms):
        return tuple(hull for turret in self._ready(server_time_ms)
                     if not turret['row'].get('support_key')
                     for hull in turret['hulls'])

    def clear(self):
        count = len(self._turrets)
        self._turrets.clear()
        return count
