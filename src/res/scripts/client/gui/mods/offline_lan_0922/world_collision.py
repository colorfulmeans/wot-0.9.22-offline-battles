# -*- coding: utf-8 -*-
"""Dedented 0.8.2 horizontal world-collision law."""

from gui.mods.offline_lan_0922.collision_flags import VEHICLE_SKIP_FLAGS

from gui.mods.offline_lan_0922.worker_diagnostics import (
    observed, observed_ray)

from gui.mods.offline_lan_0922.destructibles_sensor import (
	_catalog_soft_static_path, _diagnostic_static_recast_1513,
	_try_destroy_solid_hit, _vehicle_hull_bbox, _vehicle_body_bbox, _descriptor_value,
	ground_collision_filter, horizontal_collision_filter,
	prepare_horizontal_collision_filter, collide_motion_segment)


_MAX_DRIVABLE_GRADIENT = 1.28
_MAX_DESCENDING_GRADIENT = 1.75
_MIN_DRIVABLE_HEIGHT_CHANGE = 0.15
_GROUND_HIT_EPSILON = 1.0e-3
_UNPREPARED_COLLISION_FILTER = object()


def _trace_collision_filter(collision_filter, trace):
    """Observe all native callback candidates without another query.

    Candidates are not asserted to be the nearest returned hit: the native
    callback supplies identity but no position or ordering guarantee.
    """
    if collision_filter is None or trace is None:
        return collision_filter
    candidates = []
    trace['native_surface_candidates'] = candidates
    trace['native_surface_columns'] = 'material,flags,item,chunk,keep'

    def observed_filter(*hit):
        keep = collision_filter(*hit)
        if len(hit) == 4:
            candidate = tuple(hit) + (bool(keep),)
            if candidate not in candidates:
                candidates.append(candidate)
        return keep
    return observed_filter


def _record_hard_contact(trace, reason, start, end, collision,
        ground_ahead=None, heights=()):
    """Copy existing query evidence; diagnostics must never change the verdict."""
    if trace is None:
        return
    try:
        def vector(value):
            return tuple(float(getattr(value, axis)) for axis in ('x', 'y', 'z'))
        trace.update(reason=reason, ray_start=vector(start), ray_end=vector(end),
                     hit=vector(collision[0]), normal=vector(collision[1]),
                     ground_ahead=ground_ahead, profile=list(heights))
    except Exception:
        trace['reason'] = reason
    if trace.get('space') is not None:
        from gui.mods.offline_lan_0922.destructibles_sensor import native_contact_evidence
        try:
            trace['identity_evidence'] = native_contact_evidence(trace['space'], start, end, collision[0])
            trace['identity_evidence_source'] = 'immediate_read_only_replay'
        except Exception as error:
            trace['identity_evidence_error'] = str(error)
    from gui.mods.offline_lan_0922 import physics_diagnostics
    physics_diagnostics.emit('world_contact', trace)


def _native_ray_successor(point, end, normal=None):
    """Advance along the ray by one representable native float32 coordinate.

    An absolute 1e-7 metre advance rounds back to the same BigWorld point at
    ordinary map coordinates. A grazing ray must advance across the face,
    not only along its tangent, or the native query returns the same plane
    again. This is numerical progress, not a body margin.
    """
    import struct
    values = (point.x, point.y, point.z)
    delta = end - point
    changes = (delta.x, delta.y, delta.z)
    contributions = changes
    if normal is not None:
        components = (normal.x, normal.y, normal.z)
        projected = tuple(changes[i]*components[i] for i in range(3))
        if any(projected):
            contributions = projected
    index = max(range(3), key=lambda i: abs(contributions[i]))
    if changes[index] == 0.0:
        return end
    value = values[index]
    sign = 1.0 if changes[index] > 0.0 else -1.0
    rounded = struct.unpack('f', struct.pack('f', value))[0]
    if rounded == 0.0:
        successor = sign * struct.unpack('f', struct.pack('I', 1))[0]
    else:
        bits = struct.unpack('I', struct.pack('f', rounded))[0]
        bits += 1 if (rounded > 0.0) == (sign > 0.0) else -1
        successor = struct.unpack('f', struct.pack('I', bits))[0]
    fraction = (successor - value) / changes[index]
    return point + delta.scale(min(1.0, fraction))


def _collide_horizontal(spaceID, start, end,
		collision_filter=_UNPREPARED_COLLISION_FILTER, departing_contact=None):
	"""Raycast while hiding only exact destructibles already marked broken."""
	import BigWorld
	broken_filter = collision_filter
	if broken_filter is _UNPREPARED_COLLISION_FILTER:
		broken_filter = horizontal_collision_filter(start, end)
	current = start
	while True:
		evidence = {}
		hit = collide_motion_segment(spaceID, current, end, broken_filter,
			BigWorld.wg_collideSegment, evidence=evidence)
		if hit is not None or evidence.get('queries') and len(evidence['queries']) > 1:
			from gui.mods.offline_lan_0922 import physics_diagnostics
			physics_diagnostics.emit('native_query', dict(evidence,
				space=spaceID, start=(current.x,current.y,current.z),
				end=(end.x,end.y,end.z), skip_flags=VEHICLE_SKIP_FLAGS,
				hit=None if hit is None else (hit[0].x,hit[0].y,hit[0].z),
				normal=None if hit is None or len(hit) < 2 else (hit[1].x,hit[1].y,hit[1].z),
				identity_source='callback_candidates_not_nearest_identity'))
		if hit is None or departing_contact is None or not departing_contact(hit):
			return hit
		remaining = end - hit[0]
		if remaining.length == 0.0:
			return None
		next_start = _native_ray_successor(
			hit[0], end, hit[1] if len(hit) > 1 else None)
		advance, direction = next_start-current, end-current
		if advance.x*direction.x + advance.y*direction.y + advance.z*direction.z <= 0.0:
			raise RuntimeError('native departure recast made no geometric progress')
		current = next_start
	# A bounded depenetration must still inspect every later surface.
	return hit


def _profile_gradient_limit(heights):
	try:
		return (_MAX_DESCENDING_GRADIENT
			if float(heights[-1]) < float(heights[0]) else
			_MAX_DRIVABLE_GRADIENT)
	except (IndexError, TypeError, ValueError):
		return _MAX_DRIVABLE_GRADIENT


def _drivable_ground_profile(heights, segment_length):
	"""Recognise a continuous, bounded slope in either travel direction.

	A flat profile is deliberately not terrain evidence: a horizontal wall on a
	level street must still reach the solid collision path. Abrupt rises and drops
	remain solid edges rather than becoming a blanket downhill bypass.
	"""
	try:
		values = [float(value) for value in heights]
		if len(values) < 2:
			return False
		segment = max(0.001, float(segment_length))
		for index in range(1, len(values)):
			delta = values[index] - values[index - 1]
			maximum_gradient = (_MAX_DESCENDING_GRADIENT
				if delta < 0.0 else _MAX_DRIVABLE_GRADIENT)
			if abs(delta) > segment * maximum_gradient:
				return False
		return True
	except Exception:
		return False


def _drivable_surface(collision, maximum_gradient=_MAX_DRIVABLE_GRADIENT):
	"""Require the actual horizontal hit, not just nearby ground, to be a slope."""
	try:
		normal = collision[1]
		length = (normal.x * normal.x + normal.y * normal.y +
			normal.z * normal.z) ** 0.5
		if length <= 0.0:
			return False
		minimum_normal_y = 1.0 / (1.0 +
			float(maximum_gradient) ** 2) ** 0.5
		return normal.y / length >= minimum_normal_y
	except (AttributeError, IndexError, TypeError, ZeroDivisionError):
		return False


@observed('motion.ground_profile')
def _ground_profile(spaceID, Math, pos, sx, sz, sin_y, cos_y, direction,
		look, segment_count=6, ground_plane=None,
		collision_filter=_UNPREPARED_COLLISION_FILTER):
	"""Sample the lane that produced a lower-hull hit."""
	segment = look / float(segment_count)
	heights = []
	for sample_index in range(segment_count + 1):
		distance = segment * sample_index
		x = sx + sin_y * distance * direction
		z = sz + cos_y * distance * direction
		ground = _ground_top(
			spaceID, Math, pos, x, z, look, ground_plane,
			collision_filter)
		if ground is None:
			return (), segment
		heights.append(ground)
	return heights, segment


def _hit_matches_ground_profile(collision, heights, segment_length,
		profile_x, profile_z, profile_sin, profile_cos, profile_direction):
	"""Return a coarse seam candidate; exact native top must confirm it."""
	try:
		values = [float(value) for value in heights]
		segment = float(segment_length)
		if len(values) < 2 or segment <= 0.0:
			return False
		point = collision[0]
		distance = float(profile_direction) * (
			(float(point.x) - float(profile_x)) * float(profile_sin) +
			(float(point.z) - float(profile_z)) * float(profile_cos))
		profile_length = segment * (len(values) - 1)
		if distance < 0.0 or distance > profile_length:
			return False
		index = min(len(values) - 2, int(distance / segment))
		fraction = (distance - index * segment) / segment
		ground_y = (values[index] +
			(values[index + 1] - values[index]) * fraction)
		return abs(float(point.y) - ground_y) <= _MIN_DRIVABLE_HEIGHT_CHANGE
	except (AttributeError, IndexError, TypeError, ValueError,
			ZeroDivisionError):
		return False


def _hit_matches_exact_ground_top(spaceID, Math, pos, collision, look,
		ground_plane=None,
		collision_filter=_UNPREPARED_COLLISION_FILTER):
	"""Confirm that a coarse-profile candidate is the native top at its XZ."""
	try:
		point = collision[0]
		top = _ground_top(
			spaceID, Math, pos, point.x, point.z, look, ground_plane,
			collision_filter)
		return (top is not None and
			abs(float(top) - float(point.y)) <=
			_GROUND_HIT_EPSILON)
	except (AttributeError, IndexError, TypeError, ValueError):
		return False


def _ground_exit_is_clear(spaceID, Math, pos, start, end, collision,
		look, ground_plane, collision_filter):
	"""Prove an outward terrain contact and query the rest of the same ray.

	A steeper drop beyond a supported slope is not a horizontal wall. Only an
	actual drivable top, crossed outward, earns this exception; a second native
	hit remains solid. In particular, a low wall behind the slope must not be
	hidden by the first terrain triangle or by the raised hull rays.
	"""
	if not _drivable_surface(collision, _MAX_DESCENDING_GRADIENT):
		return False
	delta = end - start
	length = delta.length
	if length <= _GROUND_HIT_EPSILON:
		return False
	normal = collision[1]
	outward = (delta.x * normal.x + delta.y * normal.y +
		delta.z * normal.z) / length
	if outward <= _GROUND_HIT_EPSILON:
		return False
	if not _hit_matches_exact_ground_top(
			spaceID, Math, pos, collision, look, ground_plane,
			collision_filter):
		return False
	remaining = end - collision[0]
	remaining_length = remaining.length
	if remaining_length <= _GROUND_HIT_EPSILON:
		return False
	recast_start = collision[0] + remaining.scale(
		_GROUND_HIT_EPSILON / remaining_length)
	return _collide_horizontal(
		spaceID, recast_start, end, collision_filter) is None


def _vehicle_motion_bounds(descriptor):
	"""Cover the chassis and mounted hull instead of only the narrow armour."""
	hull_box = _vehicle_hull_bbox(descriptor)
	if hull_box is None:
		return None
	chassis = _descriptor_value(descriptor, 'chassis')
	tester = _descriptor_value(chassis, 'hitTester')
	chassis_box = getattr(tester, 'bbox', None)
	hull_position = _descriptor_value(chassis, 'hullPosition')
	if chassis_box is None or hull_position is None:
		raise RuntimeError('#1513 chassis collision descriptor is unavailable')
	lower = tuple(min(float(chassis_box[0][i]),
		float(hull_box[0][i]) + float(hull_position[i])) for i in (0, 2))
	upper = tuple(max(float(chassis_box[1][i]),
		float(hull_box[1][i]) + float(hull_position[i])) for i in (0, 2))
	return lower[0], upper[0], -lower[1], upper[1]


def _vehicle_motion_extents(descriptor):
	bounds = _vehicle_motion_bounds(descriptor)
	if bounds is None:
		return None
	left, right, back, front = bounds
	return max(abs(left), abs(right)), back, front


class _RigidPose(tuple):
    def __new__(cls, pitch, roll, yaw=0.0, heights=None):
        from gui.mods.offline_lan_0922.collision_geometry import pose_axes
        axes = pose_axes(yaw, pitch, roll)
        value = tuple.__new__(cls, tuple(a[1] for a in axes))
        value.axes, value.yaw = axes, float(yaw)
        value.heights = heights
        return value


def _hull_pose_y(pitch, roll, yaw=0.0, heights=None):
    """Rigid pose with the legacy three height components for ground probes."""
    return _RigidPose(pitch, roll, yaw, heights)


def _body_probe_heights(descriptor):
    bbox = _vehicle_body_bbox(descriptor)
    if bbox is None:
        raise RuntimeError('native world body height descriptor is unavailable')
    low, high = float(bbox[0][1]), float(bbox[1][1])
    if high <= low:
        raise RuntimeError('native world body height descriptor is invalid')
    return low, (low+high)*0.5, high


def _normal_impact_speed(yaw, speed, collision):
    """Signed drive speed carrying only inward contact momentum."""
    import math
    normal = collision[1]
    length = math.sqrt(normal.x**2+normal.y**2+normal.z**2)
    if length <= 0.0:
        raise RuntimeError('native contact normal is degenerate')
    closing = max(0.0, -float(speed)*(math.sin(yaw)*normal.x+
                                    math.cos(yaw)*normal.z)/length)
    return -closing if speed < 0.0 else closing


def _hull_pose_endpoint(local_start, local_end, half_width,
		half_length_back, half_length_front, lateral_bounds=None):
	"""Stop pose extrapolation where a lane leaves the hull footprint."""
	start_right = float(local_start[0])
	start_forward = float(local_start[1])
	delta_right = float(local_end[0]) - start_right
	delta_forward = float(local_end[1]) - start_forward
	fraction = 1.0
	left, right = lateral_bounds or (-float(half_width), float(half_width))
	for start, delta, lower, upper in (
			(start_right, delta_right, left, right),
			(start_forward, delta_forward, -float(half_length_back),
				float(half_length_front))):
		if delta > 0.0:
			fraction = min(fraction, (upper - start) / delta)
		elif delta < 0.0:
			fraction = min(fraction, (lower - start) / delta)
	fraction = max(0.0, min(1.0, fraction))
	return (
		start_right + delta_right * fraction,
		start_forward + delta_forward * fraction)


@observed('motion.ground_top')
def _ground_top(spaceID, Math, pos, x, z, look, ground_plane=None,
		collision_filter=_UNPREPARED_COLLISION_FILTER):
	"""Return support below the occupied lane, not an overhead deck.

	The ceiling follows the posed upper hull ray, or the tangent plane of an
	already witnessed drivable hit. A sky-origin ray can select a gatehouse
	roof in one column and its road in the next, inventing a cliff. Horizontal
	lower and upper rays still own walls and beams inside the occupied lanes.

	``collision_filter`` is the sweep-wide broken-skin callback already prepared
	for the horizontal lanes.  Every ground column sampled by this sweep lies
	inside that envelope, and the callback still resolves each hit by its exact
	native identity against the live accepted ledger, so sharing it decides
	exactly what a per-column filter decides without rebuilding the candidate
	set for each of the sweep's ground rays.
	"""
	import BigWorld
	try:
		probe_down = max(
			5.0, float(look) * _MAX_DESCENDING_GRADIENT + 1.0)
		start_y = pos.y + 12.0
		if ground_plane is not None:
			px, py, pz, gradient_x, gradient_z = ground_plane
			start_y = min(start_y, py +
				(float(x) - px) * gradient_x +
				(float(z) - pz) * gradient_z)
		if start_y <= pos.y - probe_down:
			return None
		start = Math.Vector3(x, start_y, z)
		end = Math.Vector3(x, pos.y - probe_down, z)
		broken_filter = collision_filter
		if broken_filter is _UNPREPARED_COLLISION_FILTER:
			broken_filter = ground_collision_filter(x, z)
		ground = collide_motion_segment(spaceID, start, end, broken_filter,
			BigWorld.wg_collideSegment, 'native.motion.ground')
		return None if ground is None else float(ground[0].y)
	except (AttributeError, IndexError, TypeError, ValueError):
		return None


@observed('motion.ground_ahead')
def _lane_ground_ahead(spaceID, Math, pos, start_x, start_z,
		footprint_x, footprint_z, end_x, end_z, look, ground_plane=None,
		collision_filter=_UNPREPARED_COLLISION_FILTER, descending=False,
		support_start_y=None):
	"""Extend only support witnessed under the current hull footprint.

	A lower floor beyond a crest is not occupied by this horizontal sweep.
	Pulling its endpoint down to that floor creates an artificial diagonal
	through the cliff top and blocks departure in both travel directions.
	The under-hull trend still caps a nose-up ray against real walls ahead;
	vertical integration owns contact with a lower landing surface.
	"""
	import math
	start_ground = _ground_top(
		spaceID, Math, pos, start_x, start_z, look, ground_plane,
		collision_filter)
	footprint_ground = _ground_top(
		spaceID, Math, pos, footprint_x, footprint_z, look, ground_plane,
		collision_filter)
	if (start_ground is not None and support_start_y is not None and
			float(start_ground) < float(support_start_y) - _GROUND_HIT_EPSILON):
		# A floor below the posed chassis is not its support. This also applies
		# to outward corner lanes, whose clamped local endpoints coincide: they
		# have no descending pose trend even when a trench lies below them.
		# Pulling their end down to that floor invents a collision with the lip.
		return None
	if (start_ground is not None and footprint_ground is not None and
			(descending or float(footprint_ground) < float(start_ground))):
		# The ground may descend even while the hull lane rises. Before
		# extrapolating that descent, require the middle to agree with the
		# same support chord. Either a high crest or a low trench sample
		# breaks continuity; neither may bend the occupied ray into a lip.
		middle_ground = _ground_top(
			spaceID, Math, pos, (start_x + footprint_x) * 0.5,
			(start_z + footprint_z) * 0.5, look, ground_plane,
			collision_filter)
		if (middle_ground is None or
				abs(float(middle_ground) -
					(float(start_ground) + float(footprint_ground)) * 0.5) >
				_GROUND_HIT_EPSILON):
			return None
	try:
		inside_length = math.sqrt(
			(float(footprint_x) - float(start_x)) ** 2 +
			(float(footprint_z) - float(start_z)) ** 2)
		full_length = math.sqrt(
			(float(end_x) - float(start_x)) ** 2 +
			(float(end_z) - float(start_z)) ** 2)
		if (start_ground is not None and footprint_ground is not None and
				inside_length > 1.0e-6):
			extrapolated = (float(start_ground) +
				(float(footprint_ground) - float(start_ground)) *
				full_length / inside_length)
			return extrapolated
		inside_tops = [float(value) for value in (
			start_ground, footprint_ground) if value is not None]
		if inside_tops:
			inside_top = min(inside_tops)
			return inside_top
		return None
	except (TypeError, ValueError, OverflowError):
		return None


def _posed_ray(Math, pos, x1, z1, x2, z2, local_start, local_end,
        height, pose_y, ground_ahead=None):
    """Rotate the occupied body rigidly, then add this frame's translation.

    Ground estimates cannot lower a body corner or shear its footprint.
    """
    import math
    axes = getattr(pose_y, 'axes', None)
    if axes is None:
        # Legacy injected helpers are only a level-pose ABI. Production always
        # passes the complete orthonormal pose above.
        axes = ((1.0, pose_y[0], 0.0), (0.0, pose_y[1], 0.0), (0.0, pose_y[2], 1.0))
    yaw = getattr(pose_y, 'yaw', 0.0)
    sine, cosine = math.sin(yaw), math.cos(yaw)
    def point(x, z, local):
        flat_x = pos.x+cosine*local[0]+sine*local[1]
        flat_z = pos.z-sine*local[0]+cosine*local[1]
        offset = (x-flat_x, 0.0, z-flat_z)
        base = (pos.x, pos.y, pos.z)
        return Math.Vector3(*(base[i]+offset[i]+axes[0][i]*local[0]+
            axes[1][i]*height+axes[2][i]*local[1] for i in range(3)))
    return point(x1, z1, local_start), point(x2, z2, local_end)


def _supported_seam_is_clear(spaceID, Math, pos, collision, x1, z1, x2, z2,
		local_start, local_end, pose_y, extents, collision_filter):
	"""Cross a low support seam already straddled by the posed tracks.

	Paris reports have one track on a 0.6 m pavement and one on the street.
	The lowered longitudinal witness hits the pavement's vertical side and
	classifies it as a building. Require native support on both sides, a broad
	low top within the existing track plane, and a clear lifted body corridor.
	An upright tank approaching a wall has no such raised support plane.
	"""
	import math, BigWorld
	point, normal = collision[:2]
	if abs(normal.y) > 0.2:
		return False
	length = math.hypot(normal.x, normal.z)
	if length < 0.9:
		return False
	nx, nz = normal.x / length, normal.z / length
	hw, back, front = extents
	posed_top = (float(pos.y) + abs(pose_y[0]) * hw +
		max(-back * pose_y[2], front * pose_y[2]))
	if posed_top < point.y - _GROUND_HIT_EPSILON:
		return False
	tops = []
	for offset in (0.12, -0.12, -0.60):
		x, z = point.x + nx * offset, point.z + nz * offset
		start = Math.Vector3(x, pos.y + pose_y.heights[-1], z)
		end = Math.Vector3(x, pos.y - 3.0, z)
		hit = collide_motion_segment(spaceID, start, end, collision_filter,
			BigWorld.wg_collideSegment, 'native.motion.ground')
		if hit is None or len(hit) < 2 or not _drivable_surface(hit, 0.5):
			return False
		tops.append(float(hit[0].y))
	rise = max(tops[1:]) - tops[0]
	if (not 0.03 < rise <= 0.75 or abs(tops[1] - tops[2]) > 0.12 or
			min(tops[1:]) < point.y - _GROUND_HIT_EPSILON or
			max(tops[1:]) > posed_top + 0.075):
		return False
	for height in pose_y.heights:
		start, end = _posed_ray(Math, pos, x1, z1, x2, z2,
			local_start, local_end, height, pose_y)
		# Raise the same corridor by only the measured step. Never discard
		# the rest of the segment or the occupied upper hull heights.
		offset = Math.Vector3(0.0, rise, 0.0)
		if _collide_horizontal(spaceID, start + offset, end + offset,
				collision_filter) is not None:
			return False
	return True


def _raised_ray_has_wall(spaceID, Math, pos, x1, z1, x2, z2,
		local_start, local_end, pose_y, target_length,
		maximum_gradient=_MAX_DRIVABLE_GRADIENT, ground_profile=None,
		collision_filter=_UNPREPARED_COLLISION_FILTER,
		ground_ahead=None, trace=None, require_clear_exit=False,
		departing_contact=None):
	"""A drivable lower slope must not hide an independent wall above it."""
	for height in pose_y.heights[1:]:
		start, end = _posed_ray(
			Math, pos, x1, z1, x2, z2, local_start, local_end,
			height, pose_y, ground_ahead)
		collision = _collide_horizontal(
			spaceID, start, end, collision_filter, departing_contact)
		if collision is None:
			continue
		if (collision[0] - start).length >= target_length:
			continue
		if _drivable_surface(collision, maximum_gradient):
			if (not require_clear_exit or _ground_exit_is_clear(
					spaceID, Math, pos, start, end, collision,
					ground_profile[7], ground_profile[8], collision_filter)):
				continue
		if (not require_clear_exit and ground_profile is not None and
				_hit_matches_ground_profile(
					collision, ground_profile[0], ground_profile[1],
					ground_profile[2], ground_profile[3],
					ground_profile[4], ground_profile[5],
					ground_profile[6])):
			if _hit_matches_exact_ground_top(
					spaceID, Math, pos, collision, ground_profile[7],
					ground_profile[8], collision_filter):
				continue
		_record_hard_contact(trace, 'raised_wall', start, end, collision,
			ground_ahead)
		return True
	return False


@observed('motion.solid_recast')
def _solid_contact_cleared(spaceID, segment_start, segment_end, vel, td,
		collision_filter=_UNPREPARED_COLLISION_FILTER):
	"""Admit only a clear ray or a bounded chain of proved light props.

	#1513 keeps a destroyed fragile/module skin solid until its hide callback.
	After native authority has accepted the first contact, filter that exact
	original native key and query the complete ray, including its box interior.  The same read-only helper
	may classify following light props so the swept catalog commit can destroy
	them later in this tick.  Unknown geometry, a backing wall, an ambiguous OBB
	remains solid.
	"""
	import BigWorld
	recast = _collide_horizontal(
		spaceID, segment_start, segment_end, collision_filter)
	if recast is None:
		return True
	return _catalog_soft_static_path(
		spaceID, segment_start, segment_end, recast, vel, td,
		None)


@observed('motion.destroy_recast')
def _destroy_and_recast(spaceID, segment_start, segment_end, collision,
		yaw, vel, td, crush_state=None, allow_kinetic=False,
		kinetic_speed=None, commit_enabled=True,
		collision_filter=_UNPREPARED_COLLISION_FILTER):
	if crush_state is not None and crush_state[0]:
		# Another hull lane already obtained native authority for this copied-pose
		# step.  Classify this lane read-only so the delayed skin cannot cause a
		# second destroy attempt, while every unrelated solid still fails closed.
		cleared = _catalog_soft_static_path(
			spaceID, segment_start, segment_end, collision, vel, td,
			None)
		_diagnostic_static_recast_1513(cleared)
		return cleared is True
	# Revisit an already accepted hide skin before probing material again. This
	# keeps the 0.2 s native callback window out of the hot path and still
	# requires the exact accepted identity and a filtered query of the whole ray.
	cleared = _catalog_soft_static_path(
		spaceID, segment_start, segment_end, collision, vel, td,
		None, require_pending_first=True,
		allow_kinetic_first=allow_kinetic,
		kinetic_speed=kinetic_speed)
	if cleared is True:
		if crush_state is not None:
			crush_state[0] = True
		_diagnostic_static_recast_1513(True)
		return True
	if cleared in ('deferred', 'pending_hard'):
		_diagnostic_static_recast_1513(False)
		return False
	if cleared == 'kinetic':
		# This is planning evidence only.  The catalog commit seam still requires
		# the exact current hull plus this frame's physical travel before it may
		# apply the actual contact-speed gate.
		_diagnostic_static_recast_1513(False)
		return 'kinetic'
	if not commit_enabled:
		# A visible player may classify its native ray and submit a hull-sweep
		# proposal, but only the hidden worker may mutate native map state.
		_diagnostic_static_recast_1513(False)
		return False
	if not _try_destroy_solid_hit(
			spaceID, segment_start, collision[0], collision[1], yaw, vel, td):
		# A previously accepted fragile/module may remain in the native static
		# skin until #1513's hide callback.  Only that exact pending identity may
		# be filtered here; the complete ray still checks every other surface.
		# Active kinetic rejects, expired skins, falling bodies and unknown solids
		# remain authoritative.
		cleared = _catalog_soft_static_path(
			spaceID, segment_start, segment_end, collision, vel, td,
			None, require_pending_first=True,
			allow_kinetic_first=allow_kinetic,
			kinetic_speed=kinetic_speed)
		_diagnostic_static_recast_1513(cleared)
		return cleared if cleared == 'kinetic' else cleared is True
	if crush_state is not None:
		crush_state[0] = True
	cleared = _solid_contact_cleared(
		spaceID, segment_start, segment_end, vel, td,
		collision_filter)
	_diagnostic_static_recast_1513(cleared)
	return cleared is True


def _rigid_sweep_edges(space_id, Math, pos, yaw, vel, descriptor, dt,
        motion_yaw, pitch, roll, collision_filter, trace, departing_contact,
        crush_state, allow_kinetic, commit_enabled):
    """Check boundary segments missed by a single diagonal look-ahead chord.

    Every endpoint belongs to the actual start or end body. Translation of a
    convex body contains all these segments; none adds a collision margin.
    Support-facing contacts remain owned by the suspension solver.
    """
    from gui.mods.offline_lan_0922 import collision_geometry
    import math
    bbox = _vehicle_body_bbox(descriptor)
    if bbox is None:
        return 'clear'
    axes = collision_geometry.pose_axes(yaw, pitch, roll)
    heading = yaw if motion_yaw is None else motion_yaw
    travel = float(vel)*max(0.0, float(dt))
    if motion_yaw is not None:
        travel = abs(travel)
    offset = Math.Vector3(math.sin(heading)*travel, 0.0, math.cos(heading)*travel)
    low, high = bbox[:2]
    def point(x, y, z):
        return Math.Vector3(*(v+axes[0][i]*x+axes[1][i]*y+axes[2][i]*z
            for i, v in enumerate((pos.x, pos.y, pos.z))))
    segments = []
    for y in (low[1], (low[1]+high[1])*.5, high[1]):
        corners = [point(x,y,z) for x,z in (
            (low[0],low[2]), (high[0],low[2]), (high[0],high[2]), (low[0],high[2]))]
        for index, start in enumerate(corners):
            end = corners[(index+1)%4]
            segments.append((start+offset, end+offset))
            if travel:
                segments.append((start, start+offset))
    # Vertical edges cover thin beams between the sampled horizontal levels.
    for x in (low[0], high[0]):
        for z in (low[2], high[2]):
            start, end = point(x, low[1], z), point(x, high[1], z)
            segments.append((start, end))
            if travel:
                segments.append((start+offset, end+offset))
                segments.append((start, end+offset))
                segments.append((end, start+offset))
    kinetic = False
    pose = _hull_pose_y(pitch, roll, yaw, _body_probe_heights(descriptor))
    extents = (max(abs(low[0]), abs(high[0])), -low[2], high[2])
    for start, end in segments:
        hit = _collide_horizontal(space_id, start, end, collision_filter, departing_contact)
        if hit is None or _drivable_surface(hit):
            continue
        if (_drivable_surface(hit, _MAX_DESCENDING_GRADIENT) and
                offset.x*hit[1].x+offset.z*hit[1].z >= 0.0):
            continue
        if _hit_matches_exact_ground_top(space_id, Math, pos, hit,
                (end-start).length, collision_filter=collision_filter):
            continue
        def unposed(point):
            relative = (point.x-pos.x, point.y-pos.y, point.z-pos.z)
            right, forward = (collision_geometry.dot(axes[i], relative) for i in (0,2))
            return (right, forward), (pos.x+math.cos(yaw)*right+math.sin(yaw)*forward,
                                     pos.z-math.sin(yaw)*right+math.cos(yaw)*forward)
        local_start, flat_start = unposed(start)
        local_end, flat_end = unposed(end)
        if _supported_seam_is_clear(space_id, Math, pos, hit,
                flat_start[0], flat_start[1], flat_end[0], flat_end[1],
                local_start, local_end, pose, extents, collision_filter):
            continue
        impact = _normal_impact_speed(heading,
            vel if motion_yaw is None else abs(vel), hit)
        resolved = _destroy_and_recast(space_id, start, end, hit, heading, impact,
                descriptor, crush_state, allow_kinetic, None,
                commit_enabled, collision_filter)
        if resolved == 'kinetic':
            kinetic = True
        elif resolved is not True:
            _record_hard_contact(trace, 'rigid_sweep_boundary', start, end, hit)
            return 'hard'
    return 'kinetic' if kinetic else 'clear'


def check_horizontal_collision(bigworld, math_module, *args, **kwargs):
	"""Supply the engine modules formerly captured by the 0.8.2 closure."""
	import sys
	missing = object()
	old_bigworld = sys.modules.get('BigWorld', missing)
	old_math = sys.modules.get('Math', missing)
	sys.modules['BigWorld'] = bigworld
	sys.modules['Math'] = math_module
	try:
		return _check_horizontal_collision(*args, **kwargs)
	finally:
		if old_bigworld is missing:
			sys.modules.pop('BigWorld', None)
		else:
			sys.modules['BigWorld'] = old_bigworld
		if old_math is missing:
			sys.modules.pop('Math', None)
		else:
			sys.modules['Math'] = old_math


@observed('motion.world')
def _check_horizontal_collision(spaceID, pos, yaw, vel, td=None,
		airborne=False, dt=0.04, return_status=False,
		allow_kinetic=False, kinetic_speed=None, commit_enabled=True,
		motion_yaw=None, pitch=0.0, roll=0.0, trace=None,
		exact_footprint=False, departing_contact=None):
	import math, BigWorld, Math
	if trace is None:
		trace = {}
	try:
		hw = 1.5
		hl_front = 3.5
		hl_back = 3.5

		extents = _vehicle_motion_extents(td)
		if extents is not None:
			hw, hl_back, hl_front = extents
		bounds = _vehicle_motion_bounds(td)
		left, right = bounds[:2] if bounds is not None else (-hw, hw)

		if trace is not None:
			trace.clear()
			trace.update(space=spaceID, position=(pos.x, pos.y, pos.z), yaw=yaw, speed=vel,
				dt=dt, motion_yaw=motion_yaw, pitch=pitch, roll=roll,
				airborne=airborne, extents=(hw, hl_back, hl_front),
				lateral_bounds=(left, right), body_bbox=_vehicle_body_bbox(td))

		# The occupied hull and this frame's actual travel are the entire
		# collision sweep. A stationary turn already supplies its swept body.
		# Neither contact path has a proximity margin or a waiting interval.
		_ahead = (0.0 if exact_footprint else
			abs(float(vel)) * max(0.0, float(dt)))
		cos_y = math.cos(yaw)
		sin_y = math.sin(yaw)
		probe_heights = _body_probe_heights(td)
		pose_y = _hull_pose_y(pitch, roll, yaw, probe_heights)
		ground_plane = (
			float(pos.x), float(pos.y) + probe_heights[-1] * pose_y[1], float(pos.z),
			cos_y * pose_y[0] + sin_y * pose_y[2],
			-sin_y * pose_y[0] + cos_y * pose_y[2])
		lane_segments = []
		if motion_yaw is None:
			# Preserve the lane order, using both actual body edges separately.
			back_margin = -0.5 if vel > 0.0 else 0.5
			front_margin = ((hl_front + _ahead) if vel > 0.0 else
				-(hl_back + _ahead))
			direction = 1.0 if vel >= 0.0 else -1.0
			look = (hl_front if vel > 0.0 else hl_back) + _ahead
			target_len = abs(back_margin) + look
			for offset_x in (left, 0.0, right):
				sx = pos.x + cos_y * offset_x
				sz = pos.z - sin_y * offset_x
				x1 = sx + sin_y * back_margin
				z1 = sz + cos_y * back_margin
				x2 = sx + sin_y * front_margin
				z2 = sz + cos_y * front_margin
				lane_segments.append((
					x1, z1, x2, z2, target_len,
					sx, sz, sin_y, cos_y, direction, look))
		else:
			# The supplied yaw is already the true signed travel direction.
			# Sweep each real hull corner plus the centre line.  A diagonal
			# projection can leave a corner metres behind the old shared u=-0.5
			# start, while strict lateral/longitudinal motion merges back to three
			# lanes.
			motion_sin = math.sin(float(motion_yaw))
			motion_cos = math.cos(float(motion_yaw))
			perp_x, perp_z = motion_cos, -motion_sin
			right_u = motion_sin * cos_y - motion_cos * sin_y
			forward_u = motion_sin * sin_y + motion_cos * cos_y
			right_v = perp_x * cos_y - perp_z * sin_y
			forward_v = perp_x * sin_y + perp_z * cos_y
			projected = []
			for hull_right, hull_forward in (
					(left, -hl_back), (right, -hl_back),
					(right, hl_front), (left, hl_front)):
				corner_u = right_u * hull_right + forward_u * hull_forward
				corner_v = right_v * hull_right + forward_v * hull_forward
				projected.append((corner_v, corner_u, corner_u + _ahead))
			limits = []
			if right_u > 1.0e-9:
				limits.append(right / right_u)
			elif right_u < -1.0e-9:
				limits.append(left / right_u)
			if forward_u > 1.0e-9:
				limits.append(hl_front / forward_u)
			elif forward_u < -1.0e-9:
				limits.append(-hl_back / forward_u)
			center_front = min(limits) if limits else 0.0
			projected.append((0.0, -0.5, center_front + _ahead))
			merged = []
			for lane_v, start_u, end_u in sorted(projected):
				if merged and abs(lane_v - merged[-1][0]) <= 1.0e-7:
					previous_v, previous_start, previous_end = merged[-1]
					merged[-1] = (
						previous_v, min(previous_start, start_u),
						max(previous_end, end_u))
				else:
					merged.append((lane_v, start_u, end_u))
			for lane_v, start_u, end_u in merged:
				x1 = pos.x + perp_x * lane_v + motion_sin * start_u
				z1 = pos.z + perp_z * lane_v + motion_cos * start_u
				x2 = pos.x + perp_x * lane_v + motion_sin * end_u
				z2 = pos.z + perp_z * lane_v + motion_cos * end_u
				target_len = end_u - start_u
				lane_segments.append((
					x1, z1, x2, z2, target_len,
					x1, z1, motion_sin, motion_cos, 1.0, target_len))
		from gui.mods.offline_lan_0922 import collision_geometry
		body = collision_geometry.body_box((pos.x, pos.y, pos.z), yaw,
			_vehicle_body_bbox(td), pitch, roll)
		heading = yaw if motion_yaw is None else motion_yaw
		travel = _ahead * (-1.0 if vel < 0.0 and motion_yaw is None else 1.0)
		displacement = (math.sin(heading)*travel, 0.0, math.cos(heading)*travel)
		radius = tuple(sum(abs(axis[i]) for axis in body[1]) for i in range(3))
		minimum = tuple(body[0][i]-radius[i]+min(0.0, displacement[i]) for i in range(3))
		maximum = tuple(body[0][i]+radius[i]+max(0.0, displacement[i]) for i in range(3))
		_sweep_filter = prepare_horizontal_collision_filter(
			Math.Vector3(*minimum), Math.Vector3(*maximum))
		_sweep_filter = _trace_collision_filter(_sweep_filter, trace)
		_crush_state = [False]
		_kinetic_contact = False
		crush_yaw = yaw if motion_yaw is None else motion_yaw
		crush_velocity = vel if motion_yaw is None else abs(vel)

		for (x1, z1, x2, z2, target_len,
				profile_x, profile_z, profile_sin, profile_cos,
				profile_direction, profile_look) in lane_segments:
			start_dx, start_dz = x1 - pos.x, z1 - pos.z
			end_dx, end_dz = x2 - pos.x, z2 - pos.z
			local_start = (
				start_dx * cos_y - start_dz * sin_y,
				start_dx * sin_y + start_dz * cos_y)
			ray_local_end = (
				end_dx * cos_y - end_dz * sin_y,
				end_dx * sin_y + end_dz * cos_y)
			# Keep the footprint start, but stop pose growth at the first hull edge.
			# This chord is a conservative witness inside the swept hull volume;
			# extrapolating pitch/roll through look-ahead can pass over a real wall.
			local_end = _hull_pose_endpoint(
				local_start, ray_local_end, hw, hl_back, hl_front,
				lateral_bounds=(left, right))
			pose_clamped = (
				pose_y != (0.0, 1.0, 0.0) and
				(abs(local_end[0] - ray_local_end[0]) > 1.0e-9 or
				 abs(local_end[1] - ray_local_end[1]) > 1.0e-9))
			# Preserve continuous-slope wall coverage in either direction, but
			# do not let a lower floor under the leading edge turn a crest
			# departure into an artificial downward collision chord.
			descending_lane = (
				(local_end[0] - local_start[0]) * pose_y[0] +
				(local_end[1] - local_start[1]) * pose_y[2] < -1.0e-9)

			footprint_x = (pos.x + cos_y * local_end[0] +
				sin_y * local_end[1])
			footprint_z = (pos.z - sin_y * local_end[0] +
				cos_y * local_end[1])
			_ground_ahead = (
				_lane_ground_ahead(spaceID, Math, pos,
					x1, z1, footprint_x, footprint_z,
					x2, z2, target_len, ground_plane, _sweep_filter,
					descending=descending_lane,
					support_start_y=(pos.y + local_start[0] * pose_y[0] +
						local_start[1] * pose_y[2]))
				if pose_y[2] else None)
			
			# Spodní paprsek pro pevnou geometrii (0.6m nad zemí)
			start_bot, end_bot = _posed_ray(
				Math, pos, x1, z1, x2, z2, local_start, local_end,
				probe_heights[0], pose_y, _ground_ahead)
			col_bot = _collide_horizontal(
				spaceID, start_bot, end_bot, _sweep_filter, departing_contact)
			# A posed lane is longer than its flat XZ projection, and every
			# distance test below compares a 3-D ``.length``.  The prepared
			# sweep filter is keyed on the envelope's x/z bounds only, so
			# posing the ray in y keeps it valid.
			target_len = (end_bot - start_bot).length
			
			if col_bot is not None:
				d_bot = (col_bot[0] - start_bot).length
				if d_bot < target_len:
					# A lower ray may meet the slope itself. Admit it only when this
					# exact lane has a continuous non-flat ground profile and the
					# native contact normal is also a drivable surface. This handles
					# downhill terrain without hiding a wall merely located on a hill.
					_heights = ()
					_segment = 0.0
					_gradient_limit = _MAX_DESCENDING_GRADIENT
					_profile_plane = ground_plane
					if _drivable_surface(col_bot, _gradient_limit):
						# The native hit anchors a newly entered ramp even before the
						# body has pitched to match it. Keep the same 1.6 m occupied
						# upper-lane clearance above that actual surface.
						_point, _normal = col_bot[0], col_bot[1]
						_profile_plane = (
							float(_point.x), float(_point.y) + probe_heights[-1],
							float(_point.z),
							-float(_normal.x) / float(_normal.y),
							-float(_normal.z) / float(_normal.y))
					# A normal level-pose wall avoids the seven ground rays. A swept
					# chord whose endpoint height is clamped at the first hull edge can
					# meet terrain later, so that bounded case earns the existing profile.
					if (
							_drivable_surface(col_bot, _gradient_limit) or
							pose_clamped):
						_heights, _segment = _ground_profile(
							spaceID, Math, pos, profile_x, profile_z,
							profile_sin, profile_cos, profile_direction,
							profile_look, ground_plane=_profile_plane,
							collision_filter=_sweep_filter)
						_gradient_limit = _profile_gradient_limit(_heights)
						if (_heights and
								abs(float(_heights[-1]) -
									float(_heights[0])) >
								_MIN_DRIVABLE_HEIGHT_CHANGE and
								not _drivable_ground_profile(
									_heights, _segment)):
							# A descending lane can leave the actual surface before a
							# steeper drop farther ahead. Do not turn that lower ground
							# into a wall: prove the outward native top and a clear
							# remainder at every occupied hull height. Ascents, mixed
							# profiles and contacts entering terrain retain the limit.
							departing = (
								all(_heights[index] <= _heights[index - 1]
									for index in range(1, len(_heights))) and
								_ground_exit_is_clear(
									spaceID, Math, pos, start_bot, end_bot, col_bot,
									profile_look, _profile_plane, _sweep_filter))
							if departing:
								if _raised_ray_has_wall(
										spaceID, Math, pos, x1, z1, x2, z2,
										local_start, local_end, pose_y, target_len,
										_gradient_limit,
										(_heights, _segment, profile_x, profile_z,
										 profile_sin, profile_cos, profile_direction,
										 profile_look, _profile_plane),
										_sweep_filter, _ground_ahead, trace=trace,
										require_clear_exit=True,
										departing_contact=departing_contact):
									return 'hard' if return_status else True
								continue
							_record_hard_contact(trace, 'ground_profile', start_bot,
								end_bot, col_bot, _ground_ahead, _heights)
							return 'hard' if return_status else True
					_surface_is_ground = _drivable_surface(
						col_bot, _gradient_limit)
					if (not _surface_is_ground and
							pose_clamped and _hit_matches_ground_profile(
								col_bot, _heights, _segment,
								profile_x, profile_z,
								profile_sin, profile_cos,
								profile_direction)):
						_surface_is_ground = _hit_matches_exact_ground_top(
							spaceID, Math, pos, col_bot, profile_look,
							_profile_plane, _sweep_filter)
					if (_heights and
							_drivable_ground_profile(_heights, _segment) and
							_surface_is_ground):
						if _raised_ray_has_wall(
								spaceID, Math, pos, x1, z1, x2, z2,
								local_start, local_end, pose_y,
								target_len, _gradient_limit,
								(_heights, _segment,
								 profile_x, profile_z,
								 profile_sin, profile_cos,
								 profile_direction, profile_look, _profile_plane),
								_sweep_filter, _ground_ahead, trace=trace,
								departing_contact=departing_contact):
							return 'hard' if return_status else True
						continue
					if (not airborne and _supported_seam_is_clear(
							spaceID, Math, pos, col_bot, x1, z1, x2, z2,
							local_start, local_end, pose_y,
							(hw, hl_back, hl_front), _sweep_filter)):
						continue
					# Treat every occupied hull height as independent evidence.  The
					# previous distance-difference heuristic dropped the whole lane when
					# a low prop was followed by a farther upper wall, and could destroy
					# a lower prop even when an upper wall was nearer.  Sort the actual
					# contacts front-to-back; after the first native acceptance, later
					# heights use the same read-only exact-OBB recast path.
					_lane_hits = [(d_bot, start_bot, end_bot, col_bot)]
					for _height in probe_heights[1:]:
						_ray_start, _ray_end = _posed_ray(
							Math, pos, x1, z1, x2, z2,
							local_start, local_end, _height,
							pose_y, _ground_ahead)
						_ray_hit = _collide_horizontal(
							spaceID, _ray_start, _ray_end,
							_sweep_filter, departing_contact)
						if _ray_hit is None:
							continue
						_ray_distance = (_ray_hit[0] - _ray_start).length
						if _ray_distance < target_len:
							_lane_hits.append((_ray_distance, _ray_start,
								_ray_end, _ray_hit))
					_lane_hits.sort(key=lambda value: value[0])
					for _unused_distance, _ray_start, _ray_end, _ray_hit in _lane_hits:
						_resolve_args = (
							spaceID, _ray_start, _ray_end, _ray_hit,
							crush_yaw, _normal_impact_speed(crush_yaw, crush_velocity, col_bot), td, _crush_state, allow_kinetic,
							kinetic_speed)
						_resolved = _destroy_and_recast(*(
							_resolve_args + (commit_enabled, _sweep_filter)))
						if _resolved == 'kinetic':
							_kinetic_contact = True
						elif _resolved is not True:
							_record_hard_contact(trace, 'solid_lane', _ray_start,
								_ray_end, _ray_hit, _ground_ahead, _heights)
							return 'hard' if return_status else True
			if col_bot is None or d_bot >= target_len:
				# A suspended beam or upper wall may miss the 0.6 m ray entirely.
				# Probe the remaining hull heights even on a lower-ray miss; otherwise
				# three empty lower lanes could classify a real upper collision clear.
				_upper_hits = []
				for _height in probe_heights[1:]:
					_ray_start, _ray_end = _posed_ray(
						Math, pos, x1, z1, x2, z2,
						local_start, local_end, _height,
						pose_y, _ground_ahead)
					_ray_hit = _collide_horizontal(
							spaceID, _ray_start, _ray_end,
							_sweep_filter, departing_contact)
					if _ray_hit is None:
						continue
					_ray_distance = (_ray_hit[0] - _ray_start).length
					if _ray_distance < target_len:
						_upper_hits.append((_ray_distance, _ray_start,
							_ray_end, _ray_hit))
				_upper_hits.sort(key=lambda value: value[0])
				for _unused_distance, _ray_start, _ray_end, _ray_hit in _upper_hits:
					_resolve_args = (
						spaceID, _ray_start, _ray_end, _ray_hit,
						crush_yaw, _normal_impact_speed(crush_yaw, crush_velocity, _ray_hit), td, _crush_state, allow_kinetic,
						kinetic_speed)
					_resolved = _destroy_and_recast(*(
						_resolve_args + (commit_enabled, _sweep_filter)))
					if _resolved == 'kinetic':
						_kinetic_contact = True
					elif _resolved is not True:
						_record_hard_contact(trace, 'upper_lane', _ray_start,
							_ray_end, _ray_hit, _ground_ahead)
						return 'hard' if return_status else True
	except Exception:
		raise
	boundary_status = _rigid_sweep_edges(spaceID, Math, pos, yaw, vel, td,
			0.0 if exact_footprint else dt, motion_yaw, pitch, roll,
			_sweep_filter, trace, departing_contact, _crush_state,
			allow_kinetic, commit_enabled)
	if boundary_status == 'hard':
		return 'hard' if return_status else True
	_kinetic_contact = _kinetic_contact or boundary_status == 'kinetic'
	if return_status:
		return 'kinetic' if _kinetic_contact else 'clear'
	return bool(_kinetic_contact)
