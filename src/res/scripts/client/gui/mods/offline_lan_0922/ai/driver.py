# -*- coding: utf-8 -*-
"""Engine-free short-range driver for offline battle bots.

The strategic director supplies a waypoint.  Callers supply ``direction_clear``
for the current collision/terrain query; this module chooses only throttle and
steering, so it is safe to exercise outside the BigWorld client.
"""

from gui.mods.offline_lan_0922.worker_diagnostics import observed

import math
from gui.mods.offline_lan_0922 import tank_collision


WAYPOINT_ARRIVAL_RADIUS = 1.5
SLOPE_ALIGNMENT_GRADE = math.tan(math.radians(22.5))
SLOPE_ALIGNMENT_TURN = math.radians(45.0)
NAVIGATION_WAIT_RECOVERY_SECONDS = 4.0
TRAFFIC_WAIT_LEASE_SECONDS = 1.5
# First avoidance branch of the steering fan.
FIRST_CANDIDATE_OFFSET = 0.42
# Fifteen-degree circular buckets centre both the +/-pi seam and cardinal yaws.
FAILED_YAW_BUCKET_COUNT = 24
# Bot slots are team-local and the LAN roster has exactly fifteen per team.
BOT_TEAM_SLOT_COUNT = 15
# Seven is coprime with fifteen, so consecutive formation slots visit every
# timing bucket without clustering adjacent tanks at one end of the window.
RECOVERY_TIMING_STRIDE = 7
RECOVERY_YAW_OFFSET = 0.85
RECOVERY_SWEEP_FRACTIONS = (0.25, 0.50, 0.75, 1.0)


def recovery_probe_distance(half_length):
	"""Terrain reach of one bounded longitudinal escape."""
	return max(0.5, float(half_length)) * 1.6


def _angle_delta(target, current):
	value = float(target) - float(current)
	while value > math.pi:
		value -= math.pi * 2.0
	while value < -math.pi:
		value += math.pi * 2.0
	return value


def _yaw_to(first, second):
	return math.atan2(float(second[0]) - float(first[0]),
	                  float(second[2]) - float(first[2]))


def _distance(first, second):
	dx = float(first[0]) - float(second[0])
	dz = float(first[2]) - float(second[2])
	return math.sqrt(dx * dx + dz * dz)


def _team_slot(value):
	"""Return one explicit stable team-local formation slot."""
	try:
		slot = int(value)
	except (TypeError, ValueError, OverflowError):
		raise ValueError('bot team slot is invalid')
	if slot < 0 or slot >= BOT_TEAM_SLOT_COUNT:
		raise ValueError('bot team slot is outside 0..14')
	return slot


def _recovery_timing_phase(team_slot):
	"""Uniform per-team recovery timing independent of steering side."""
	slot = _team_slot(team_slot)
	bucket = (slot * RECOVERY_TIMING_STRIDE) % BOT_TEAM_SLOT_COUNT
	return (float(bucket) + 0.5) / float(BOT_TEAM_SLOT_COUNT)


def _component_value(component, name, default=None):
	if component is None:
		return default
	if isinstance(component, dict):
		return component.get(name, default)
	return getattr(component, name, default)


def gun_yaw_limits(descriptor):
	"""Return installed gun yaw limits in radians plus a limited-arc flag."""
	gun = _component_value(descriptor, 'gun')
	turret = _component_value(descriptor, 'turret')
	limits = _component_value(gun, 'turretYawLimits')
	if limits is None:
		limits = _component_value(turret, 'yawLimits')
	minimum = -math.pi
	maximum = math.pi
	try:
		minimum = float(limits[0])
		maximum = float(limits[1])
		if abs(minimum) > math.pi + 0.1 or abs(maximum) > math.pi + 0.1:
			minimum = math.radians(minimum)
			maximum = math.radians(maximum)
	except Exception:
		minimum = -math.pi
		maximum = math.pi
	limited = not (minimum <= -math.pi + 0.1 and maximum >= math.pi - 0.1)
	return minimum, maximum, limited


def combat_hull_aim(hull_yaw, target_yaw, minimum_yaw, maximum_yaw,
		turn, throttle, recovery_mode, has_target=True,
		combat_mode=None, movement_intent=False, withdrawal_aim=False):
	"""Turn a limited-traverse hull until its gun can physically bear."""
	if not has_target or recovery_mode in ('avoid', 'blocked', 'reverse_turn',
			'pivot_recovery', 'forward_escape', 'short_forward_escape', 'short_reverse_escape',
			'contact_escape', 'wreck_push', 'friendly_yield',
			'nav_wait', 'physical_hold'):
		return float(turn), float(throttle), False
	if recovery_mode == 'reverse_withdraw':
		# Only a short, physically admitted backing command may lay a fixed
		# gun without stopping the escape. Long withdrawals retain steering.
		relative = _angle_delta(target_yaw, hull_yaw)
		center = (float(minimum_yaw) + float(maximum_yaw)) * 0.5
		if (withdrawal_aim and float(throttle) < 0.0 and
				abs(relative-center) <= 0.35 and
				not (minimum_yaw <= -math.pi + 0.1 and maximum_yaw >= math.pi - 0.1)):
			if minimum_yaw + 0.02 <= relative <= maximum_yaw - 0.02:
				return 0.0, float(throttle), False
			return -max(-0.5, min(0.5, (relative-center)/0.58)), float(throttle), True
		return float(turn), float(throttle), False
	if movement_intent and combat_mode != 'engage':
		# A target can remain visible while a TD retreats or follows a route.
		# Laying its fixed gun must not stop that move or reverse its safe turn.
		# Explicit engagement still owns its mature stop-and-aim behaviour;
		# a tactical firing hold may aim once the planner has ended movement.
		return float(turn), float(throttle), False
	limited = not (float(minimum_yaw) <= -math.pi + 0.1 and
	               float(maximum_yaw) >= math.pi - 0.1)
	if not limited:
		return float(turn), float(throttle), False
	relative = _angle_delta(target_yaw, hull_yaw)
	minimum_yaw, maximum_yaw = float(minimum_yaw), float(maximum_yaw)
	margin = min(0.04, max(0.0, maximum_yaw - minimum_yaw) * 0.25)
	if minimum_yaw + margin <= relative <= maximum_yaw - margin:
		# A firing hold must not hand the hull back to an incompatible armour
		# angle and immediately push the target outside this same arc again.
		# Travel and recovery keep their normal steering owner.
		return (0.0 if abs(float(throttle)) <= 0.01 else float(turn),
		        float(throttle), False)
	# Aim inside the installed interval, including asymmetric and fixed guns.
	# A zero-width gun must not create an inverted artificial margin interval.
	center = (minimum_yaw + maximum_yaw) * 0.5
	hull_delta = _angle_delta(target_yaw - center, hull_yaw)
	aim_turn = max(-1.0, min(1.0, hull_delta / 0.58))
	return aim_turn, 0.0, True


def gun_aligned(target_yaw, hull_yaw, turret_yaw, desired_pitch, gun_pitch,
		yaw_tolerance=0.06, pitch_tolerance=0.04):
	"""Require both rendered traverse and elevation to settle before firing."""
	abs_yaw = float(hull_yaw) + float(turret_yaw)
	yaw_error = abs(_angle_delta(target_yaw, abs_yaw))
	pitch_error = abs(float(desired_pitch) - float(gun_pitch))
	return (yaw_error <= float(yaw_tolerance) and
	        pitch_error <= float(pitch_tolerance))


def barrel_direction(yaw, pitch):
	"""Unit direction for BigWorld's negative-pitch-is-up convention."""
	horizontal = math.cos(float(pitch))
	return (math.sin(float(yaw)) * horizontal,
	        -math.sin(float(pitch)),
	        math.cos(float(yaw)) * horizontal)


class LocalDriver(object):
	"""Stateful local steering keyed by bot id and a stable team-local slot.

	``direction_clear(absolute_yaw)`` must return whether a short vehicle-length
	segment in that direction is drivable.  It may raise; a failed probe is
	treated as blocked.
	"""
	_CANDIDATE_OFFSETS = (
		0.0, FIRST_CANDIDATE_OFFSET, -FIRST_CANDIDATE_OFFSET,
		0.78, -0.78, 1.18, -1.18, 1.55, -1.55)
	gun_yaw_limits = staticmethod(gun_yaw_limits)
	combat_hull_aim = staticmethod(combat_hull_aim)
	gun_aligned = staticmethod(gun_aligned)
	barrel_direction = staticmethod(barrel_direction)

	def __init__(self, stuck_seconds=1.8, recovery_seconds=0.85,
			failure_ttl=2.0):
		self._probe_takes_distance = True
		self.stuck_seconds = max(0.4, float(stuck_seconds))
		self.recovery_seconds = max(0.25, float(recovery_seconds))
		self.failure_ttl = max(0.25, float(failure_ttl))
		self.states = {}

	@staticmethod
	def resolve_order_positions(position, aim_position, move_position, face_position):
		"""Resolve optional tactical targets without mistaking travel for a hold."""
		stop_without_route = aim_position is None and move_position is None
		if stop_without_route:
			aim_position = position
		elif aim_position is None:
			# Server route orders intentionally omit an aim target until an enemy is
			# spotted.  Use the route target for facing, but do not apply idle braking.
			aim_position = move_position
		if move_position is None:
			move_position = aim_position
		if face_position is None:
			face_position = move_position
		return aim_position, move_position, face_position, stop_without_route

	def forget(self, bot_id):
		self.states.pop(bot_id, None)

	def wait_for_traffic(self, bot_id, elapsed=None):
		"""Suppress brief right-of-way waits without masking a deadlock forever.

		``elapsed`` is the physical contact interval this lease covers. Callers
		outside ``drive`` must supply it because ``last_step`` is refreshed only
		when the planner runs.
		"""
		state = self.states.get(bot_id)
		if state is None:
			return False
		state['traffic_waiting'] = True
		if elapsed is None:
			elapsed = state.get('last_step', 0.0)
		state['traffic_wait_time'] += max(0.0, float(elapsed))
		if state['traffic_wait_time'] <= TRAFFIC_WAIT_LEASE_SECONDS:
			state['stuck_time'] = 0.0
			state['recovery_time'] = 0.0
			state['recovery_side'] = 0.0
		return True

	def end_navigation_wait(self, bot_id):
		state = self.states.get(bot_id)
		if state is not None:
			state.pop('navigation_wait', None)

	def wait_for_navigation(self, bot_id, team_slot, position, yaw, speed, dt,
			neighbours, direction_clear, half_length=3.5, half_width=1.7,
			recovery_allowed=False):
		"""Hold a pending path, or back out once after proved local blockage.

		The caller owns evidence that the current support/last physical movement
		is unsafe; elapsed search time alone must not manufacture that evidence.
		Recovery only translates backwards through a checked complete hull sweep.
		Its deadline and distance never renew while the same path wait continues.
		"""
		state = self._state(bot_id, team_slot, position)
		step = max(0.0, float(dt))
		state['last_step'] = step
		state['clock'] += step
		self._prune_failures(state)
		# A short pending search pauses ordinary driving; it does not erase
		# accumulated movement, a committed avoidance side or a recovery lease.
		# Repeated path waits otherwise reset a wedged hull before it can finish
		# backing out. Only this independent wait episode earns elapsed time.
		wait = state.get('navigation_wait')
		if wait is None:
			wait = {'age': 0.0, 'active': False, 'completed': False}
			state['navigation_wait'] = wait
		wait['age'] += step
		diagnostic = {
			'clock': state['clock'], 'source': 'navigation_wait',
			'desired_yaw': None, 'chosen_yaw': float(yaw),
			'old_yaw': state.get('steering_yaw'),
			'steering_reason': state.get('steering_reason'),
			'recovery_mode': 'nav_wait', 'reason': 'awaiting_path',
			'candidates': [], 'wait_age': wait['age'],
			'recovery_allowed': bool(recovery_allowed),
		}
		state['decision_diagnostic'] = diagnostic
		result = {
			'throttle': 0.0, 'brake': True, 'turn': 0.0,
			'target_yaw': float(yaw), 'recovery_mode': 'nav_wait',
		}
		if wait['completed']:
			diagnostic['reason'] = 'recovery_completed'
			return result
		phase = state['recovery_timing_phase']
		if not wait['active']:
			if (not recovery_allowed or
					wait['age'] < NAVIGATION_WAIT_RECOVERY_SECONDS + phase * 0.42 or
					abs(float(speed)) > 0.35):
				return result
			wait.update(active=True, elapsed=0.0, origin=tuple(position))
			# This separately proved backout now owns recovery. Ordinary driving
			# resumes from its realised endpoint when the new path is available.
			state['recovery_time'] = 0.0
			state['recovery_side'] = 0.0
			state['stuck_time'] = 0.0
			state['steering_yaw'] = None
			state['heading_progress_yaw'] = None
			state['braking_target'] = None
			state['alignment_target'] = None
		else:
			wait['elapsed'] += step
		length = max(0.5, float(half_length))
		width = max(0.3, float(half_width))
		distance = recovery_probe_distance(length)
		travelled = _distance(position, wait['origin'])
		finished = (wait['elapsed'] >= self.recovery_seconds + phase * 0.28 or
			travelled >= distance)
		reverse_yaw = float(yaw) + math.pi
		remaining = max(0.0, distance - travelled)
		if not finished:
			finished = (
				self._failure_penalty(state, reverse_yaw) > 0.0 or
				not self._clear(direction_clear, reverse_yaw, remaining,
					drive_direction=-1.0) or
				self._reverse_blocked_by_vehicle(position, yaw, neighbours,
					length, width, remaining) is not None)
		if finished:
			wait['completed'] = True
			diagnostic['reason'] = 'recovery_finished_or_rear_denied'
			# Invalidate only this bot's local path/search after the manoeuvre (or
			# an unsafe rear). Keep failed-edge evidence and emit exactly once.
			result['navigation_replan'] = True
			return result
		result.update(throttle=-1.0, brake=False, recovery_mode='reverse_turn',
			navigation_recovery=True)
		diagnostic.update(source='recovery', reason='navigation_reverse',
			recovery_mode='reverse_turn')
		return result

	def _state(self, bot_id, team_slot, position):
		team_slot = _team_slot(team_slot)
		state = self.states.get(bot_id)
		if state is None:
			state = {
				'team_slot': team_slot,
				'last_position': (float(position[0]), float(position[2])),
				'stuck_time': 0.0,
				'recovery_time': 0.0,
				'recovery_count': 0,
				'recovery_side': 0.0,
				'steering_yaw': None,
				'steering_reason': 'route',
				'steering_age': 999.0,
				'plan_age': 999.0,
				'recovery_timing_phase': _recovery_timing_phase(team_slot),
				'clock': 0.0,
				'failed_yaws': {},
				'escape_side': 0.0,
				'escape_side_until': 0.0,
				'last_desired_yaw': None,
				'heading_progress_yaw': None,
				'best_heading_error': None,
				'traffic_waiting': False,
				'traffic_wait_time': 0.0,
				'last_step': 0.0,
				'braking_target': None,
			}
			self.states[bot_id] = state
		elif state['team_slot'] != team_slot:
			raise ValueError('bot team slot changed during battle')
		return state

	def _fallback_recovery_side(self, state):
		parity = int(state['team_slot']) + int(state['recovery_count'])
		return 1.0 if parity & 1 else -1.0

	def _yaw_key(self, yaw):
		turn = math.pi * 2.0
		from_anchor = (float(yaw) + math.pi) % turn
		bucket = int(math.floor(
			from_anchor * FAILED_YAW_BUCKET_COUNT / turn + 0.5))
		return bucket % FAILED_YAW_BUCKET_COUNT

	def remember_failure(self, bot_id, yaw, ttl=None):
		"""Temporarily penalize a direction after a caller-observed bad path.

		Use this when a terrain probe was clear but later movement establishes that
		the direction is a ditch, steep lip, or another unusable local route.
		"""
		state = self.states.get(bot_id)
		if state is None:
			return
		if ttl is None:
			ttl = self.failure_ttl
		ttl = max(0.1, float(ttl))
		state['failed_yaws'][self._yaw_key(yaw)] = state['clock'] + ttl
		desired = state.get('last_desired_yaw')
		offset = _angle_delta(yaw, desired) if desired is not None else 0.0
		if abs(offset) >= 0.10:
			side = 1.0 if offset > 0.0 else -1.0
		else:
			# Adjacent formation slots choose opposite initial sides, then keep it
			# while widening the escape angle. This avoids left/right grinding at a
			# broad obstacle without making a finite failure TTL a permanent bias.
			side = self._fallback_recovery_side(state)
		state['escape_side'] = side
		state['escape_side_until'] = (
			state['clock'] + min(2.0, max(0.8, ttl)))
		state['steering_yaw'] = None
		state['plan_age'] = 999.0

	def _failure_penalty(self, state, yaw):
		key = self._yaw_key(yaw)
		expires = state['failed_yaws'].get(key)
		if expires is None:
			return 0.0
		if expires <= state['clock']:
			state['failed_yaws'].pop(key, None)
			return 0.0
		return 3.0 + (expires - state['clock']) / self.failure_ttl

	def _prune_failures(self, state):
		failed = state['failed_yaws']
		for key, expires in list(failed.items()):
			if expires <= state['clock']:
				failed.pop(key, None)
		if len(failed) > 32:
			ordered = sorted(failed.items(), key=lambda item: item[1])
			for key, unused in ordered[:len(failed) - 32]:
				failed.pop(key, None)

	def _neighbour_position(self, neighbour):
		if isinstance(neighbour, dict):
			return neighbour.get('position') or neighbour.get('pos')
		return neighbour

	def _clear(self, direction_clear, yaw, maximum_distance=None,
			drive_direction=1.0):
		"""Ask one probe about a heading, optionally over a bounded distance.

		A recovery manoeuvre travels a hull length, not the fifteen to twenty
		metre travel horizon the ordinary drive candidates are ranked over.
		Probes that predate the bounded form keep the unbounded answer.
		"""
		# A candidate behind the current hull may be a forward route after a
		# pivot. Only an explicit backing command may use reverse-drive limits.
		# Inspect Python callbacks before calling; a TypeError in their body
		# must not execute a native query twice under a guessed legacy arity.
		target = getattr(direction_clear, 'im_func',
			getattr(direction_clear, '__func__', direction_clear))
		code = getattr(target, 'func_code', getattr(target, '__code__', None))
		if code is not None:
			bound = getattr(direction_clear, 'im_self',
				getattr(direction_clear, '__self__', None))
			argument_count = code.co_argcount - (1 if bound is not None else 0)
			if argument_count >= 3:
				try:
					return bool(direction_clear(yaw, maximum_distance, drive_direction))
				except Exception:
					return False
		if maximum_distance is not None and self._probe_takes_distance:
			try:
				return bool(direction_clear(yaw, maximum_distance))
			except TypeError:
				self._probe_takes_distance = False
			except Exception:
				return False
		try:
			return bool(direction_clear(yaw))
		except Exception:
			return False

	@staticmethod
	def _pose_fits(pose_clear, yaw):
		if pose_clear is None:
			return True
		try:
			return bool(pose_clear(yaw))
		except Exception:
			return False

	def _obb_overlap(self, first, first_yaw, first_length, first_width,
				 second, second_yaw, second_length, second_width):
		"""2D rectangle SAT, using yaw convention atan2(x, z)."""
		axes = ((math.sin(first_yaw), math.cos(first_yaw)),
		        (math.cos(first_yaw), -math.sin(first_yaw)),
		        (math.sin(second_yaw), math.cos(second_yaw)),
		        (math.cos(second_yaw), -math.sin(second_yaw)))
		forward_a = (math.sin(first_yaw), math.cos(first_yaw))
		side_a = (math.cos(first_yaw), -math.sin(first_yaw))
		forward_b = (math.sin(second_yaw), math.cos(second_yaw))
		side_b = (math.cos(second_yaw), -math.sin(second_yaw))
		dx = float(second[0]) - float(first[0])
		dz = float(second[2]) - float(first[2])
		for axis in axes:
			distance = abs(dx * axis[0] + dz * axis[1])
			radius_a = (abs(forward_a[0] * axis[0] + forward_a[1] * axis[1]) * first_length +
			            abs(side_a[0] * axis[0] + side_a[1] * axis[1]) * first_width)
			radius_b = (abs(forward_b[0] * axis[0] + forward_b[1] * axis[1]) * second_length +
			            abs(side_b[0] * axis[0] + side_b[1] * axis[1]) * second_width)
			if distance > radius_a + radius_b:
				return False
		return True

	@observed('driver.reverse_contacts')
	def _reverse_blocked_by_vehicle(self, position, yaw, neighbours,
			half_length, half_width, maximum_distance=None):
		"""Reject a blind reverse whose reachable hull sweep is occupied.

		``direction_clear`` answers for terrain and static world geometry only.
		In a spawn line-up every tank reaches the stuck threshold within about a
		second of every other one, so an unchecked reverse recovery drives each
		hull straight into the one behind it and the whole formation grinds.
		"""
		reverse_distance = (max(0.0, float(half_length)) * 1.6
			if maximum_distance is None else max(0.0, float(maximum_distance)))
		# Translating an OBB along its longitudinal axis sweeps one exact longer
		# OBB. Sampling only the final pose misses a hull at the current or an
		# intermediate reachable position.
		sweep = (
			float(position[0]) - math.sin(float(yaw)) * reverse_distance * 0.5,
			float(position[1]),
			float(position[2]) - math.cos(float(yaw)) * reverse_distance * 0.5)
		sweep_length = half_length + reverse_distance * 0.5
		for neighbour in neighbours or ():
			other = self._neighbour_position(neighbour)
			if other is None:
				continue
			try:
				if abs(float(other[1]) - float(position[1])) > 5.0:
					continue
			except Exception:
				pass
			other_yaw = 0.0
			other_length = half_length
			other_width = half_width
			if isinstance(neighbour, dict):
				other_yaw = float(neighbour.get('yaw', 0.0) or 0.0)
				other_length = float(
					neighbour.get('half_length', half_length) or half_length)
				other_width = float(
					neighbour.get('half_width', half_width) or half_width)
			try:
				contact = tank_collision._obb_overlap(
					position[0], position[2], yaw, (half_width, half_length),
					other[0], other[2], other_yaw, (other_width, other_length))
				if contact[2] >= -1.0e-9:
					back_x, back_z = -math.sin(yaw), -math.cos(yaw)
					outward = back_x*contact[0] + back_z*contact[1]
					away = back_x*(position[0]-other[0]) + back_z*(position[2]-other[2])
					if outward >= -1.0e-9 and away >= -1.0e-9:
						# The sweep includes the current hull. Its front/side
						# contact is not a new rear obstacle when every point
						# moves out or tangentially along that face. Centre
						# distance may stay constant in an exactly parallel
						# side hug; neither direction may be denied for that.
						# At an offset prefer the nearer end of the overlap.
						# Other peers still veto the complete swept corridor.
						continue
				if self._obb_overlap(
						sweep, float(yaw), sweep_length, half_width,
						other, other_yaw, other_length, other_width):
					# Name the hull that owns the blockage. A wedged tank whose
					# only escape is occupied by a team mate is a queue the
					# caller can resolve; an anonymous veto is not.
					if isinstance(neighbour, dict) and neighbour.get('id') is not None:
						return neighbour['id']
					return True
			except Exception:
				continue
		return None

	def _static_hull_ahead(self, position, candidate_yaw, neighbours,
			half_length, half_width):
		"""Reject a candidate occupied by a wreck or a stationary living hull.

		Moving traffic retains crossing coordination and contact physics. A
		parked gun or stopped player cannot be assumed to clear the route: choose
		a hull-checked branch around it instead of repeatedly driving into it.

		The reach matches the reverse check: this is the space the hull is
		about to enter, not a long-range forecast, so a wreck further along the
		route never withdraws a heading that is still usable.
		"""
		reach = half_length * 1.6
		sweep = (
			float(position[0]) + math.sin(candidate_yaw) * reach * 0.5,
			float(position[1]),
			float(position[2]) + math.cos(candidate_yaw) * reach * 0.5)
		sweep_length = half_length + reach * 0.5
		for neighbour in neighbours or ():
			if not isinstance(neighbour, dict):
				continue
			if neighbour.get('alive', True):
				velocity = neighbour.get('velocity')
				if velocity is None or math.hypot(velocity[0], velocity[2]) > 0.65:
					continue
			other = self._neighbour_position(neighbour)
			if other is None:
				continue
			try:
				if abs(float(other[1]) - float(position[1])) > 5.0:
					continue
			except Exception:
				pass
			try:
				other_yaw = float(neighbour.get('yaw', 0.0) or 0.0)
				other_length = float(
					neighbour.get('half_length', half_length) or half_length)
				other_width = float(
					neighbour.get('half_width', half_width) or half_width)
				if self._obb_overlap(
						sweep, float(candidate_yaw), sweep_length, half_width,
						other, other_yaw, other_length, other_width):
					return True
			except Exception:
				continue
		return False

	def _recovery_occupancy(self, position, yaw, direction, neighbours,
			half_length, half_width):
		"""Count occupied sampled poses in one in-place recovery turn."""
		occupied = 0
		for neighbour in neighbours or ():
			other = self._neighbour_position(neighbour)
			if other is None:
				continue
			try:
				if abs(float(other[1]) - float(position[1])) > 5.0:
					continue
			except Exception:
				pass
			other_yaw = 0.0
			other_length = half_length
			other_width = half_width
			if isinstance(neighbour, dict):
				try:
					other_yaw = float(neighbour.get('yaw', 0.0) or 0.0)
					other_length = float(
						neighbour.get('half_length', half_length) or half_length)
					other_width = float(
						neighbour.get('half_width', half_width) or half_width)
				except (TypeError, ValueError, OverflowError):
					continue
			for fraction in RECOVERY_SWEEP_FRACTIONS:
				candidate_yaw = (
					float(yaw) + float(direction) *
					RECOVERY_YAW_OFFSET * fraction)
				try:
					if self._obb_overlap(
							position, candidate_yaw,
							half_length, half_width,
							other, other_yaw, other_length, other_width):
						occupied += 1
				except Exception:
					continue
		return occupied

	@observed('driver.recovery')
	def _select_recovery_side(self, state, position, yaw, neighbours,
			half_length, half_width):
		"""Prefer the less occupied pivot arc, then use stable slot parity."""
		negative = self._recovery_occupancy(
			position, yaw, -1.0, neighbours, half_length, half_width)
		positive = self._recovery_occupancy(
			position, yaw, 1.0, neighbours, half_length, half_width)
		if negative < positive:
			return -1.0
		if positive < negative:
			return 1.0
		return self._fallback_recovery_side(state)

	def _pivot_side_fits(self, pose_clear, yaw, direction):
		"""Report whether the hull can sweep one in-place turn.

		``direction_clear`` answers about a heading; it cannot answer about a
		rotation, because the corners a turn sweeps are metres away from every
		ray it casts. Inside a gateway, an alley or a bridge underpass those
		corners are already at the walls, so an unchecked turn only grinds
		them and the column behind never moves.
		"""
		if pose_clear is None:
			return True
		for fraction in RECOVERY_SWEEP_FRACTIONS:
			if not self._pose_fits(
					pose_clear,
					float(yaw) + float(direction) *
					RECOVERY_YAW_OFFSET * float(fraction)):
				return False
		return True

	@observed('driver.choose_yaw')
	def _choose_yaw(self, state, desired_yaw, direction_clear,
			position=None, neighbours=None,
			half_length=3.5, half_width=1.7, pose_clear=None):
		# Teammate proximity never replaces the route with a repulsion heading.
		# Crossing priority is coordinated separately; real contact owns overlap.
		candidates = []
		for offset in self._CANDIDATE_OFFSETS:
			candidate = desired_yaw + offset
			score = abs(offset) + self._failure_penalty(state, candidate)
			if (state.get('escape_side_until', 0.0) > state['clock'] and
					float(offset) * float(
						state.get('escape_side', 0.0)) < -0.01):
				# Continue around the selected side before testing the mirror branch.
				# The finite penalty still permits the other side when this fan is spent.
				score += 1.25
			candidates.append((score, candidate))
		candidates.sort(key=lambda item: item[0])
		# Probe in score order and return the first fully viable direction. Most
		# frames need one terrain ray set instead of probing all seven candidates.
		for unused_score, candidate in candidates:
			if ((pose_clear is None or pose_clear(candidate)) and
					self._clear(direction_clear, candidate) and
					not (position is not None and self._static_hull_ahead(
						position, candidate, neighbours,
						half_length, half_width))):
				state['steering_reason'] = (
					'route' if abs(_angle_delta(candidate, desired_yaw)) <= 0.05
					else 'obstacle')
				return candidate
		return None

	def _short_escape(self, state, position, yaw, speed, step, horizon,
			stopping_distance, neighbours, direction_clear, half_length, half_width):
		"""Choose a fresh straight escape independently of available pivot arcs."""
		minimum = max(0.5, float(stopping_distance or 0.0) +
			abs(float(speed)) * max(step, float(horizon)))
		for distance in (max(2.0, minimum), max(1.0, minimum), minimum):
			for sign in (-1.0, 1.0):
				heading = float(yaw) + (math.pi if sign < 0 else 0.0)
				if (self._failure_penalty(state, heading) <= 0.0 and
						self._clear(direction_clear, heading, distance) and
						self._reverse_blocked_by_vehicle(
							position, float(yaw) if sign < 0 else float(yaw) + math.pi,
							neighbours, half_length, half_width, maximum_distance=distance) is None):
					state['short_translation_escape'] = dict(start=tuple(position),
						yaw=float(yaw), sign=sign, distance=distance,
						until=state['clock'] + 4.0)
					return dict(throttle=sign * 1.0, turn=0.0, target_yaw=float(yaw),
						recovery_probe_distance=distance,
						recovery_mode='short_reverse_escape' if sign < 0 else 'short_forward_escape')
		return None

	def _retained_short_escape(self, state, position, yaw, neighbours,
			direction_clear, half_length, half_width):
		escape = state.get('short_translation_escape')
		if escape is None:
			return None
		sign = escape['sign']
		heading = escape['yaw'] + (math.pi if sign < 0 else 0.0)
		travelled = ((position[0]-escape['start'][0])*math.sin(heading) +
			(position[2]-escape['start'][2])*math.cos(heading))
		remaining = max(0.0, escape['distance'] - travelled)
		if (remaining <= 0.05 or state['clock'] >= escape['until'] or
				abs(_angle_delta(yaw, escape['yaw'])) > 0.30 or
				self._failure_penalty(state, heading) > 0.0 or
				not self._clear(direction_clear, heading, remaining) or
				self._reverse_blocked_by_vehicle(position,
					yaw if sign < 0 else yaw + math.pi, neighbours,
					half_length, half_width, remaining) is not None):
			state.pop('short_translation_escape', None)
			return None
		return dict(throttle=sign * 1.0, turn=0.0, target_yaw=escape['yaw'],
			recovery_probe_distance=remaining,
			recovery_mode='short_reverse_escape' if sign < 0 else 'short_forward_escape')

	def _retained_translation_escape(self, state, position, yaw, neighbours,
			direction_clear, half_length, half_width):
		"""Finish a checked straight exit before retrying an impossible pivot."""
		escape = state.get('translation_escape')
		if escape is None:
			return None
		distance = _distance(position, escape['start'])
		remaining = max(0.0, escape['distance'] - distance)
		if (remaining <= 0.05 or state['clock'] >= escape['until'] or
				abs(_angle_delta(yaw, escape['yaw'])) > 0.30 or
				self._failure_penalty(state, yaw) > 0.0 or
				not self._clear(direction_clear, yaw, remaining) or
				self._reverse_blocked_by_vehicle(position, yaw + math.pi,
					neighbours, half_length, half_width, remaining) is not None):
			state.pop('translation_escape', None)
			return None
		return dict(throttle=1.0, turn=0.0, target_yaw=escape['yaw'],
			recovery_mode='forward_escape', recovery_probe_distance=remaining)

	@observed('driver.drive')
	def drive(self, bot_id, team_slot, position, yaw, speed, dt, target,
			neighbours, direction_clear, velocity=None,
			half_length=3.5, half_width=1.7,
			movement_intent=True, stopping_distance=None,
			stop_at_target=True, decision_horizon=0.0, pose_clear=None,
			progress_target=None, turn_speed_limit=None, arrival_radius=None):
		"""Return ``throttle``, ``turn``, ``target_yaw`` and ``recovery_mode``.

		``team_slot`` is the explicit stable 0..14 formation slot. It must not be
		inferred from a network entity id because those numbering schemes differ.
		All timing uses the complete supplied interval.  The authority caller
		already advances vehicle physics in bounded substeps; throwing away the
		planner's remaining wall time would leave recovery and route leases
		permanently behind after every slow callback.
		"""
		arrival = WAYPOINT_ARRIVAL_RADIUS if arrival_radius is None else max(0.1, float(arrival_radius))
		state = self._state(bot_id, team_slot, position)
		alignment = state.get('alignment_target')
		if (not movement_intent or float(speed) < -0.05 or
				turn_speed_limit is None or
				(alignment is not None and _distance(alignment, target) > 2.0)):
			state.pop('alignment_target', None)
		step = max(0.0, float(dt))
		if not state.pop('traffic_waiting', False):
			state['traffic_wait_time'] = 0.0
		state['last_step'] = step
		state['clock'] += step
		self._prune_failures(state)
		state['steering_age'] += step
		state['plan_age'] += step
		desired_yaw = _yaw_to(position, target)
		heading_error = abs(_angle_delta(desired_yaw, yaw))
		state['last_desired_yaw'] = desired_yaw
		target_distance = _distance(position, target)
		if not movement_intent:
			state.pop('short_translation_escape', None)
			state.pop('translation_escape', None)
			state['translation_progress_at'] = state['clock']
			state.pop('objective_progress', None)
			# Cover/engagement orders intentionally stop within a tolerance. Do not
			# reinterpret that commanded hold as a stuck tank 1.8 seconds later.
			state['stuck_time'] = 0.0
			state['recovery_time'] = 0.0
			state['recovery_side'] = 0.0
			state['steering_yaw'] = None
			state['heading_progress_yaw'] = None
			state['braking_target'] = None
			return {
				'throttle': 0.0,
				'turn': 0.0,
				'target_yaw': float(yaw),
				'recovery_mode': 'arrived',
			}
		own_half_length = max(0.5, float(half_length))
		own_half_width = max(0.3, float(half_width))
		displacement = _distance((position[0], 0.0, position[2]),
		                         (state['last_position'][0], 0.0,
		                          state['last_position'][1]))
		if displacement >= 0.08 or 'translation_progress_at' not in state:
			state['translation_progress_at'] = state['clock']
		translation_stalled = state['clock'] - state['translation_progress_at'] >= 8.0
		# Local targets may alternate around a prop while the tank makes no
		# progress toward its actual order. Do not credit that orbit as travel.
		objective_stalled = False
		objective_advanced = False
		if progress_target is not None:
			progress = state.get('objective_progress')
			distance = _distance(position, progress_target)
			if (progress is None or _distance(progress['goal'], progress_target) > 2.0 or
					distance <= arrival):
				progress = {'goal': tuple(progress_target), 'best': distance,
				            'at': state['clock']}
				state['objective_progress'] = progress
			elif distance + 0.08 <= progress['best']:
				objective_advanced = True
				progress['best'] = distance
				progress['at'] = state['clock']
				progress.pop('alignment_yaw', None)
				progress.pop('alignment_best', None)
			elif distance + 0.002 < progress['best']:
				# Slow uphill travel can take longer than the local stuck timeout
				# to accumulate 8 cm. Credit its direction while the independent
				# best-distance clock still bounds sub-threshold oscillation.
				objective_advanced = True
			# A deliberate brake-and-align can outlast the distance lease on
			# a slow chassis. Credit actual new hull angles against ONE anchor
			# per objective-progress episode. Changing local targets must not
			# renew this anchor and disguise an endless left/right orbit.
			if (state.get('alignment_target') is not None and
					state['recovery_time'] <= 0.0):
				if progress.get('alignment_yaw') is None:
					progress['alignment_yaw'] = _yaw_to(position, state['alignment_target'])
					progress['alignment_best'] = abs(_angle_delta(progress['alignment_yaw'], yaw))
				else:
					error = abs(_angle_delta(progress['alignment_yaw'], yaw))
					if error + 0.002 < progress['alignment_best']:
						progress['alignment_best'] = error
						progress['at'] = state['clock']
			objective_stalled = state['clock'] - progress['at'] >= 8.0
		if target_distance <= arrival and not objective_stalled:
			state.pop('short_translation_escape', None)
			# Reaching a waypoint is a stop, not a request to drive north: atan2(0, 0)
			# is zero and previously produced full throttle until the next order tick.
			state['stuck_time'] = 0.0
			state['recovery_time'] = 0.0
			state['recovery_side'] = 0.0
			state['steering_yaw'] = None
			state['heading_progress_yaw'] = None
			state['last_position'] = (
				float(position[0]), float(position[2]))
			state['braking_target'] = None
			return {
				'throttle': 0.0,
				'turn': 0.0,
				'target_yaw': float(yaw),
				'recovery_mode': 'arrived',
			}

		translation = self._retained_translation_escape(state, position, yaw,
			neighbours, direction_clear, own_half_length, own_half_width)
		if translation is not None:
			return translation
		translation = self._retained_short_escape(state, position, yaw,
			neighbours, direction_clear, own_half_length, own_half_width)
		if translation is not None:
			return translation
		# Credit only a new best alignment with a fixed heading anchor. Comparing
		# adjacent samples lets a stationary left/right oscillation repeatedly
		# earn back the stuck time from its previous half-cycle. Keep small goal
		# changes out of this measurement so waypoint jitter is not hull progress.
		progress_yaw = state['heading_progress_yaw']
		heading_progress = False
		if (displacement >= 0.08 or progress_yaw is None or
				abs(_angle_delta(desired_yaw, progress_yaw)) > 0.12):
			state['heading_progress_yaw'] = desired_yaw
			state['best_heading_error'] = heading_error
		else:
			progress_error = abs(_angle_delta(progress_yaw, yaw))
			if progress_error + 0.002 < state['best_heading_error']:
				state['best_heading_error'] = progress_error
				heading_progress = True

		# Accumulate translation between planner samples, preserving real slow
		# travel. A continuous turn may earn heading credit until it aligns;
		# revisiting an angle already reached cannot renew that credit.
		if displacement >= 0.08:
			state['last_position'] = (
				float(position[0]), float(position[2]))
			state['stuck_time'] = 0.0
		elif heading_progress or objective_advanced:
			state['stuck_time'] = max(0.0, state['stuck_time'] - step)
		else:
			state['stuck_time'] += step

		timing_phase = state['recovery_timing_phase']
		threshold = self.stuck_seconds + timing_phase * 0.42
		if objective_stalled:
			state['stuck_time'] = max(state['stuck_time'], threshold)
		if state['recovery_time'] > 0.0:
			state['recovery_time'] = max(0.0, state['recovery_time'] - step)
			if state['recovery_time'] == 0.0:
				state['recovery_count'] += 1
				state['recovery_side'] = 0.0
				state['stuck_time'] = 0.0
				state['heading_progress_yaw'] = None
		else:
			if state['stuck_time'] >= threshold:
				if progress_target is not None:
					state['objective_progress']['at'] = state['clock']
				if state.get('last_clear_yaw') is not None:
					state['failed_yaws'][self._yaw_key(state['last_clear_yaw'])] = (
						state['clock'] + self.failure_ttl)
				state['recovery_time'] = (
					self.recovery_seconds + timing_phase * 0.28)
				state['recovery_side'] = self._select_recovery_side(
					state, position, yaw, neighbours,
					own_half_length, own_half_width)

		if state['recovery_time'] > 0.0:
			# Keep one side for the whole episode. Geometry separates an asymmetric
			# local jam; team-local slot parity breaks an exact tie without coupling
			# steering to the timing phase. Never reverse blindly: at a cliff or
			# shoreline the space behind can be the unsafe side that caused the stall.
			direction = state.get('recovery_side', 0.0)
			if direction not in (-1.0, 1.0):
				direction = self._select_recovery_side(
					state, position, yaw, neighbours,
					own_half_length, own_half_width)
				state['recovery_side'] = direction
			recovery_yaw = float(yaw) + direction * RECOVERY_YAW_OFFSET
			# The escape is one bounded backing manoeuvre, so rank it over the
			# distance it travels. Ranking it over the fifteen to twenty metre
			# travel horizon rejects the rear of every gateway and alley on the
			# map and leaves an in-place turn as the only recovery in exactly
			# the places where a hull cannot turn.
			escape_distance = own_half_length * 1.6
			reverse_yaw = float(yaw) + math.pi
			reverse_clear = (self._failure_penalty(state, reverse_yaw) <= 0.0 and
				self._clear(direction_clear, reverse_yaw, escape_distance))
			reverse_blocker = None
			if reverse_clear:
				reverse_blocker = self._reverse_blocked_by_vehicle(
					position, yaw, neighbours,
					own_half_length, own_half_width)
			if not reverse_clear or reverse_blocker is not None:
				if objective_stalled or translation_stalled:
					# A slope may permit a short straight exit while rejecting
					# the full backing sweep. Prefer proved translation after
					# eight seconds without progress, even if a pivot still fits.
					# Repeated pivots alone cannot clear an erased ingress cell.
					escape = self._short_escape(state, position, yaw, speed, step,
						decision_horizon, stopping_distance, neighbours, direction_clear,
						own_half_length, own_half_width)
					if escape is not None:
						return escape
				if self._failure_penalty(state, float(yaw)) > 0.0:
					escape = self._short_escape(state, position, yaw, speed, step,
						decision_horizon, stopping_distance, neighbours, direction_clear,
						own_half_length, own_half_width)
					if escape is not None:
						return escape
				if not self._pivot_side_fits(pose_clear, yaw, direction):
					mirrored = -direction
					if self._pivot_side_fits(pose_clear, yaw, mirrored):
						state['recovery_side'] = direction = mirrored
						recovery_yaw = float(yaw) + direction * RECOVERY_YAW_OFFSET
					else:
						forward_blocker = self._reverse_blocked_by_vehicle(
							position, float(yaw) + math.pi, neighbours,
							own_half_length, own_half_width)
						if (forward_blocker is None and
								self._failure_penalty(state, float(yaw)) <= 0.0 and self._clear(
								direction_clear, float(yaw), escape_distance)):
							state['translation_escape'] = dict(start=tuple(position), yaw=float(yaw),
								distance=escape_distance, until=state['clock'] + 20.0)
							return {'throttle': 1.0, 'turn': 0.0,
								'target_yaw': float(yaw), 'recovery_mode': 'forward_escape'}
						# A long hull may have room to translate out of a side
						# contact without room for the full backing manoeuvre.
						# Recheck a short straight sweep on every decision; retain
						# braking/cadence distance and the final native hull veto.
						escape = self._short_escape(state, position, yaw, speed, step,
							decision_horizon, stopping_distance, neighbours, direction_clear,
							own_half_length, own_half_width)
						if escape is not None:
							return escape
						# Neither translation nor rotation fits. Hold the
						# pose instead of grinding the corners, and publish the
						# hull that owns the escape so the queue can clear it.
						blocked = {
							'throttle': 0.0,
							'turn': 0.0,
							'target_yaw': float(yaw),
							'recovery_mode': 'blocked',
				'brake': True,
						}
						if reverse_blocker is not None:
							blocked['reverse_blocked_by'] = reverse_blocker
						if forward_blocker is not None:
							blocked['forward_blocked_by'] = forward_blocker
						return blocked
				return {
					'throttle': 0.0,
					'turn': direction,
					'target_yaw': recovery_yaw,
					'recovery_mode': 'pivot_recovery',
				}
			# Reverse recovery is an explicit reverse command. The traverse law flips
			# steering from that command immediately, not from signed velocity.
			recovery_turn = -direction
			recovery_target = recovery_yaw
			# Steering while reversing rotates the hull through the recovery offset,
			# so the rear sweeps every heading between the straight reverse and its
			# mirrored offset. In a gateway or alley narrower than that arc the
			# manoeuvre parks the hull across the passage and blocks the whole
			# column behind it. Keep the escape and drop the turn.
			for fraction in RECOVERY_SWEEP_FRACTIONS:
				if ((pose_clear is not None and not pose_clear(
						float(yaw) + direction * RECOVERY_YAW_OFFSET * fraction)) or
						self._failure_penalty(state, float(yaw) + math.pi +
							direction * RECOVERY_YAW_OFFSET * fraction) > 0.0 or
						not self._clear(
						direction_clear,
						float(yaw) + math.pi +
						direction * RECOVERY_YAW_OFFSET * fraction,
						escape_distance)):
					recovery_turn = 0.0
					recovery_target = float(yaw)
					break
			return {
				'throttle': -1.0,
				'turn': recovery_turn,
				'target_yaw': recovery_target,
				'recovery_mode': 'reverse_turn',
			}

		chosen_yaw = None
		old_yaw = state.get('steering_yaw')
		steering_reason = state.get('steering_reason', 'route')
		# Keep a clear avoidance branch long enough for the hull to pass the wall,
		# while retaining the shorter cadence for an unobstructed route heading.
		# Replanning a symmetric left/right choice every few frames made bots wag
		# in front of flat walls without committing to either exit.
		# The reason belongs to the original selection: motion past a nearby goal
		# must not promote a held route heading into a fresh avoidance lease.
		hold_seconds = 0.35 if steering_reason == 'route' else 1.20
		if (old_yaw is not None and state['plan_age'] < hold_seconds and
				abs(_angle_delta(desired_yaw, old_yaw)) < 2.15 and
				self._failure_penalty(state, old_yaw) <= 0.0 and
				(pose_clear is None or pose_clear(old_yaw)) and
				self._clear(direction_clear, old_yaw) and
				not self._static_hull_ahead(
					position, old_yaw, neighbours,
					own_half_length, own_half_width)):
			chosen_yaw = old_yaw
		if chosen_yaw is None:
			chosen_yaw = self._choose_yaw(
				state, desired_yaw, direction_clear, position, neighbours,
				own_half_length, own_half_width, pose_clear)
			state['plan_age'] = 0.0
		if chosen_yaw is None:
			# No forward ray is usable.  Start a timed recovery on the next tick
			# rather than issuing an unsafe blind turn.
			state['stuck_time'] = max(state['stuck_time'], threshold)
			return {
				'throttle': 0.0,
				'turn': 0.0,
				'target_yaw': float(yaw),
				'recovery_mode': 'blocked',
				'brake': True,
			}
		state['last_clear_yaw'] = chosen_yaw

		# Retain a selected side for a short time. This removes left/right flip
		# flop while the per-frame hard terrain veto remains active above.
		old_yaw = state['steering_yaw']
		if old_yaw is None or abs(_angle_delta(chosen_yaw, old_yaw)) > 0.04:
			state['steering_yaw'] = chosen_yaw
			state['steering_age'] = 0.0

		delta = _angle_delta(chosen_yaw, yaw)
		turn = max(-1.0, min(1.0, delta / 0.58))
		brake = False
		# This branch commands forward drive. Signed speed can still be negative
		# while braking a recovery or sliding downhill; steering remains forward.
		avoiding = state['steering_reason'] != 'route'
		throttle = 1.0
		if avoiding:
			state.pop('alignment_target', None)
		elif turn_speed_limit is not None and float(turn_speed_limit) > 0.0 and float(speed) >= -0.05:
			# Use the installed traverse rate rather than driving a circle
			# around a nearby navigation point. Retain the alignment at zero
			# speed until the hull actually faces the point; coasting is not
			# sufficient to stop a heavy tank before its next corner.
			radius = max(1.0, abs(float(speed))) / float(turn_speed_limit)
			if (target_distance <= max(8.0, 2.0 * radius) and abs(delta) > 0.30):
				state['alignment_target'] = tuple(target)
			if state.get('alignment_target') is not None:
				if abs(delta) > 0.12:
					throttle = 0.0
					brake = True
				else:
					state.pop('alignment_target', None)
		if (target_distance <= max(8.0, own_half_length * 2.0) and
				abs(delta) > 0.45):
			# Both path corners and native-checked avoidance steps can be inside
			# the moving hull's turning circle. Align before driving either one.
			throttle = 0.0
			brake = True
		climb_grade = ((float(target[1]) - float(position[1])) /
		               max(0.1, target_distance))
		if abs(climb_grade) > SLOPE_ALIGNMENT_GRADE and abs(delta) > SLOPE_ALIGNMENT_TURN:
			# Enter genuinely steep uphill/downhill edges square to the slope. Full drive
			# while the hull is still turning makes it circle at the foot of the
			# climb and repeatedly invalidates the next terrain sample.
			throttle = 0.0
			brake = True
		elif (abs(delta) > math.pi * 0.5 or
				(not avoiding and heading_error > math.pi * 0.5)):
			# A selected escape behind the hull needs a pivot too: forward drive
			# initially moves into the contact it is trying to leave. On a clear
			# route use the live goal as well as the held heading, so passing the
			# goal cannot delay braking until the steering lease expires. Side and
			# diagonal corners still retain forward progress while steering.
			throttle = 0.0
			brake = True
		if stop_at_target and not avoiding and stopping_distance is not None:
			try:
				brake_distance = max(0.0, float(stopping_distance))
				reaction_distance = (abs(float(speed)) *
				                     max(0.0, float(decision_horizon)))
			except (TypeError, ValueError, OverflowError):
				brake_distance = 0.0
				reaction_distance = 0.0
			target_key = (round(float(target[0]), 2),
			              round(float(target[2]), 2))
			if state.get('braking_target') not in (None, target_key):
				state['braking_target'] = None
			if (target_distance <= arrival +
					brake_distance + reaction_distance):
				state['braking_target'] = target_key
			if state.get('braking_target') == target_key:
				# Releasing the throttle uses the same copied coast law that
				# produced ``stopping_distance``. If tuning or a slope leaves the
				# hull stopped short, release the latch and approach again.
				if (abs(float(speed)) <= 0.35 and
						target_distance > arrival + (0.5 if arrival_radius is None else 0.0)):
					state['braking_target'] = None
				else:
					throttle = 0.0
					brake = True
		elif not stop_at_target:
			state['braking_target'] = None
		return {
			'throttle': throttle,
			'brake': brake,
			'turn': turn,
			'target_yaw': chosen_yaw,
			'recovery_mode': 'avoid' if avoiding else 'drive',
		}
