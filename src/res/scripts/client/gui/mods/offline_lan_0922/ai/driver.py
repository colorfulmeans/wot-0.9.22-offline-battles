# -*- coding: utf-8 -*-
"""Engine-free short-range driver for offline battle bots.

The strategic director supplies a waypoint.  Callers supply ``direction_clear``
for the current collision/terrain query; this module chooses only throttle and
steering, so it is safe to exercise outside the BigWorld client.
"""

from gui.mods.offline_lan_0922.worker_diagnostics import observed

import math
import types as _types
from gui.mods.offline_lan_0922 import tank_collision, native_math


WAYPOINT_ARRIVAL_RADIUS = 1.5
# Route admission is a separate policy from the physical slope-grip curve.
NAVIGATION_MAX_GRADE = math.tan(math.radians(25.0))
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
RECOVERY_COMMIT_MINIMUM = 0.5


def recovery_probe_distance(half_length):
	"""Terrain reach of one bounded longitudinal escape."""
	return max(0.5, float(half_length)) * 1.6


def short_escape_remaining(command, position):
	"""Keep a cached straight escape bounded by its original checked endpoint."""
	if command.get('recovery_mode') not in ('short_forward_escape', 'short_reverse_escape'):
		return None
	origin = command.get('recovery_probe_origin')
	if origin is None:
		return None
	heading = float(command['recovery_probe_yaw'])
	travelled = ((position[0] - origin[0]) * math.sin(heading) +
		(position[2] - origin[2]) * math.cos(heading))
	return max(0.0, float(command['recovery_probe_length']) - travelled)


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


def _rear_laying_deferred(hull_yaw, target_yaw, minimum_yaw, maximum_yaw,
                         rear_turn, allow_rear_start):
    """The tactical cooldown gates both native and reference aim admission."""
    relative = _angle_delta(target_yaw, hull_yaw)
    margin = min(0.04, max(0.0, maximum_yaw-minimum_yaw)*0.25)
    return (not allow_rear_start and not rear_turn and
            not (minimum_yaw <= -math.pi + 0.1 and maximum_yaw >= math.pi - 0.1) and
            abs(relative) > math.pi * 0.5 and
            not minimum_yaw+margin <= relative <= maximum_yaw-margin)


def _reference_combat_hull_aim(hull_yaw, target_yaw, minimum_yaw, maximum_yaw,
		turn, throttle, recovery_mode, has_target=True,
		combat_mode=None, movement_intent=False, withdrawal_aim=False,
		rear_turn=0.0, allow_rear_start=True):
	"""Turn a limited-traverse hull until its gun can physically bear."""
	if _rear_laying_deferred(hull_yaw, target_yaw, minimum_yaw, maximum_yaw,
			rear_turn, allow_rear_start):
		return float(turn), float(throttle), False
	if movement_intent and combat_mode in ('artillery_deploy', 'artillery_relocate'):
		# Deployment keeps the current travel steering even for a rear threat.
		# A stationary firing area may lay the hull after physical arrival.
		return float(turn), float(throttle), False
	if not has_target or recovery_mode in ('avoid', 'blocked', 'reverse_turn',
			'pivot_recovery', 'forward_escape', 'short_forward_escape', 'short_reverse_escape',
			'contact_escape', 'wreck_push', 'friendly_yield',
			'nav_wait', 'physical_hold'):
		return float(turn), float(throttle), False
	limited = not (float(minimum_yaw) <= -math.pi + 0.1 and
	               float(maximum_yaw) >= math.pi - 0.1)
	relative = _angle_delta(target_yaw, hull_yaw)
	margin = min(0.04, max(0.0, maximum_yaw - minimum_yaw) * 0.25)
	rear_unreachable = (limited and
	                    (rear_turn or (allow_rear_start and abs(relative) > math.pi * 0.5)) and
	                    not minimum_yaw + margin <= relative <= maximum_yaw - margin)
	if rear_unreachable:
		# A retreat cannot preserve frontal armour or fire at a rear threat
		# which the installed turret cannot reach. Brake and lay the chassis.
		# Keep the admitted side across the +/-pi seam for this same target;
		# target jitter must not repeatedly reverse both hull and turret.
		center = (float(minimum_yaw) + float(maximum_yaw)) * 0.5
		delta = _angle_delta(target_yaw - center, hull_yaw)
		if rear_turn and abs(relative) > math.pi * 0.5 and delta * float(rear_turn) < 0.0:
			delta += math.copysign(2.0 * math.pi, float(rear_turn))
		return max(-1.0, min(1.0, delta / 0.58)), 0.0, True
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


def _reference_limited_traverse_target(relative, minimum, maximum, rear_turn=0.0):
	"""Clamp gun travel without reversing an ongoing rear hull-laying side.

	Callers retain the original bearing for alignment and fire admission.
	"""
	if (rear_turn and abs(relative) > math.pi * 0.5 and
	        not minimum <= relative <= maximum):
		return maximum if rear_turn > 0.0 else minimum
	return max(minimum, min(maximum, relative))


def _reference_gun_aligned(target_yaw, hull_yaw, turret_yaw, desired_pitch, gun_pitch,
		yaw_tolerance=0.06, pitch_tolerance=0.04):
	"""Require both rendered traverse and elevation to settle before firing."""
	abs_yaw = float(hull_yaw) + float(turret_yaw)
	yaw_error = abs(_angle_delta(target_yaw, abs_yaw))
	pitch_error = abs(float(desired_pitch) - float(gun_pitch))
	return (yaw_error <= float(yaw_tolerance) and
	        pitch_error <= float(pitch_tolerance))


def _reference_barrel_direction(yaw, pitch):
	"""Unit direction for BigWorld's negative-pitch-is-up convention."""
	horizontal = math.cos(float(pitch))
	return (math.sin(float(yaw)) * horizontal,
	        -math.sin(float(pitch)),
	        math.cos(float(yaw)) * horizontal)



# Engine state and installed descriptors stay with their existing callers.
# Each frontier transfers one complete aiming decision, with no retained state.
def combat_hull_aim(hull_yaw, target_yaw, minimum_yaw, maximum_yaw,
        turn, throttle, recovery_mode, has_target=True,
        combat_mode=None, movement_intent=False, withdrawal_aim=False,
        rear_turn=0.0, allow_rear_start=True):
    if _rear_laying_deferred(hull_yaw, target_yaw, minimum_yaw, maximum_yaw,
                            rear_turn, allow_rear_start):
        return float(turn), float(throttle), False
    if movement_intent and combat_mode in ('artillery_deploy', 'artillery_relocate'):
        return float(turn), float(throttle), False
    held = recovery_mode in ('avoid', 'blocked', 'reverse_turn',
        'pivot_recovery', 'forward_escape', 'short_forward_escape',
        'short_reverse_escape', 'contact_escape', 'wreck_push', 'friendly_yield',
        'nav_wait', 'physical_hold')
    mode = 1 if held else 2 if recovery_mode == 'reverse_withdraw' else 0
    result = native_math.call('driver_aim', 0,
        (hull_yaw, target_yaw, minimum_yaw, maximum_yaw, turn, throttle, rear_turn),
        (mode, int(bool(has_target)), int(combat_mode == 'engage'),
         int(bool(movement_intent)), int(bool(withdrawal_aim)),
         int(bool(allow_rear_start))))
    if result is not None:
        return result[0], result[1], bool(result[2])
    return _reference_combat_hull_aim(hull_yaw, target_yaw, minimum_yaw,
        maximum_yaw, turn, throttle, recovery_mode, has_target, combat_mode,
        movement_intent, withdrawal_aim, rear_turn, allow_rear_start)


def limited_traverse_target(relative, minimum, maximum, rear_turn=0.0):
    result = native_math.call('driver_aim', 1,
        (relative, minimum, maximum, rear_turn), ())
    if result is not None:
        return result
    return _reference_limited_traverse_target(relative, minimum, maximum, rear_turn)


def gun_aligned(target_yaw, hull_yaw, turret_yaw, desired_pitch, gun_pitch,
        yaw_tolerance=0.06, pitch_tolerance=0.04):
    result = native_math.call('driver_aim', 2,
        (target_yaw, hull_yaw, turret_yaw, desired_pitch, gun_pitch,
         yaw_tolerance, pitch_tolerance), ())
    if result is not None:
        return bool(result)
    return _reference_gun_aligned(target_yaw, hull_yaw, turret_yaw,
        desired_pitch, gun_pitch, yaw_tolerance, pitch_tolerance)


def barrel_direction(yaw, pitch):
    result = native_math.call('driver_aim', 3, (yaw, pitch), ())
    if result is not None:
        return result
    return _reference_barrel_direction(yaw, pitch)


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
			recovery_allowed=False, body=None):
		"""Hold a pending path, or back out once after proved local blockage.

		The caller owns evidence that the current support/last physical movement
		is unsafe; elapsed search time alone must not manufacture that evidence.
		Recovery only translates backwards through a checked complete hull sweep.
		Its deadline and distance never renew while the same path wait continues.
		"""
		state = self._state(bot_id, team_slot, position)
		state['collision_body'] = body
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
					length, width, remaining, body=state.get('collision_body')) is not None)
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

	def recovery_replan(self, bot_id, position, half_length):
		"""Bound follower retries by elapsed time and a new completed recovery."""
		state = self.states.get(bot_id)
		if state is None or state['recovery_count'] == 0:
			return False
		episode = state.get('recovery_replan_episode')
		if episode is None or _distance(position, episode['origin']) >= 2.0 * half_length + WAYPOINT_ARRIVAL_RADIUS:
			episode = dict(origin=tuple(position), at=state['clock'],
				count=state['recovery_count'], issued=False)
			state['recovery_replan_episode'] = episode
		issued_at = episode.get('issued_at', episode['at'])
		issued_count = episode.get('issued_count', episode['count'])
		if (state['clock'] - issued_at < 8.0 or
				state['recovery_count'] <= issued_count):
			return False
		episode['issued'] = True
		episode['issued_at'] = state['clock']
		episode['issued_count'] = state['recovery_count']
		return True

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

	@staticmethod
	def _failure_origin_matches(first, second):
		# Refusals belong to a local physical pose, including its surface layer.
		return sum((float(first[i]) - float(second[i])) ** 2
			for i in range(3)) <= 0.25 ** 2

	def remember_failure(self, bot_id, yaw, ttl=None, evidence=None):
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
		state.setdefault('real_failed_yaws', {})[self._yaw_key(yaw)] = state['clock'] + ttl
		key = self._yaw_key(yaw)
		records = state.setdefault('real_failure_evidence', {})
		previous = records.get(key)
		record = dict(evidence or {})
		record.update(yaw=float(yaw), created_at=state['clock'],
			expires_at=state['clock'] + ttl,
			renewed=bool(previous and previous['expires_at'] > state['clock']))
		# Preserve a live, local realised-contact witness when a later long
		# forecast reports the same bucket. The forecast still gets a receipt.
		keep_contact = bool(previous and previous['expires_at'] > state['clock'] and
			previous.get('source') != 'motion_forecast' and
			record.get('source') == 'motion_forecast' and
			previous.get('origin') is not None and record.get('origin') is not None and
			self._failure_origin_matches(previous['origin'], record['origin']))
		if not keep_contact:
			records[key] = record
		else:
			state['real_failed_yaws'][key] = previous['expires_at']
		record['preserved_contact'] = keep_contact
		history = state.setdefault('failure_receipts', [])
		history.append(dict(record))
		del history[:-16]

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


	def _short_failure_applies(self, state, position, yaw, distance):
		key = self._yaw_key(yaw)
		if state.get('real_failed_yaws', {}).get(key, 0.0) <= state['clock']:
			return False
		evidence = state.get('real_failure_evidence', {}).get(key) or {}
		origin = evidence.get('origin')
		# Legacy callers retain their actual-contact veto. Scoped forecasts
		# cannot suppress a fresh shorter proof or follow a tank elsewhere.
		if origin is not None and not self._failure_origin_matches(position, origin):
			return False
		if evidence.get('source') == 'motion_forecast':
			return float(evidence.get('distance', 0.0)) <= float(distance)
		return True

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
		"""Dispatch one reviewed probe arity without replaying engine effects."""
		target = getattr(direction_clear, 'im_func',
			getattr(direction_clear, '__func__', direction_clear))
		code = getattr(target, 'func_code', getattr(target, '__code__', None))
		count = 2 if maximum_distance is not None else 1
		variadic = False
		if code is not None:
			bound = getattr(direction_clear, 'im_self',
				getattr(direction_clear, '__self__', None))
			count = code.co_argcount - (1 if bound is not None else 0)
			variadic = bool(code.co_flags & 0x04)
		try:
			if count >= 3:
				result = bool(direction_clear(yaw, maximum_distance, drive_direction))
			elif (maximum_distance is not None and (count >= 2 or variadic)):
				result = bool(direction_clear(yaw, maximum_distance))
			else:
				result = bool(direction_clear(yaw))
		except Exception as error:
			self._last_direction_receipt = dict(reason='direction_callback_exception',
				exception_type=type(error).__name__, yaw=yaw, distance=maximum_distance)
			return False
		try:
			self._last_direction_receipt = dict(getattr(direction_clear, 'last_receipt', {}) or {})
		except Exception as error:
			self._last_direction_receipt = dict(reason='callback_receipt_unavailable',
				exception_type=type(error).__name__, clear=result)
		return result

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
			half_length, half_width, maximum_distance=None, body=None):
		distance = (max(0.0, float(half_length)) * 1.6 if maximum_distance is None
			else max(0.0, float(maximum_distance)))
		separated = []
		# A candidate pivot has not yet committed its new attitude. Only
		# refine translation along the actual frozen body's forward/back axis.
		pose_refinement = body is not None and abs(math.sin(yaw-body['yaw'])) < 1.e-9
		if pose_refinement:
			retained = []
			movement = (-math.sin(yaw)*distance, 0.0, -math.cos(yaw)*distance)
			for peer in neighbours or ():
				other = self.collision_body(peer)
				proof = {}
				if other is not None and (
					tank_collision.swept_body_separated(body, other, movement, proof) or
					(body.get('id') is not None and other.get('id') is not None and
					 body['id'] != other['id'] and
					 tank_collision.translation_fraction(body, (movement[0], movement[2]), [other]) >= 1.0)):
					separated.append(dict(peer=peer.get('id'), proof=proof,
						rule='physical_translation_clear'))
				else:
					retained.append(peer)
			neighbours = retained
		result = self._native_geometry(0, position, yaw, neighbours, half_length, half_width, distance)
		if result is not None:
			peer = neighbours[result] if result >= 0 else None
			blocker = (peer['id'] if isinstance(peer, dict) and peer.get('id') is not None
				else True) if result >= 0 else None
		else:
			blocker = self._reference_reverse_blocked_by_vehicle(position, yaw, neighbours,
				half_length, half_width, maximum_distance)
		self._last_reverse_receipt = dict(origin=tuple(position), yaw=float(yaw),
			body=body, separated=separated, pose_refinement=bool(pose_refinement),
			distance=distance, half_length=half_length, half_width=half_width,
			backend='native' if result is not None else 'reference', blocker=blocker,
			rule='full_sweep_except_initial_non_deepening_contact',
			result='vehicle_occupied' if blocker is not None else 'clear')
		return blocker

	@staticmethod
	def collision_body(state):
		"""Only use authoritative pose/shape; absent data keeps broad phase."""
		if not isinstance(state, dict):
			return None
		shape = state.get('collision_shape', state.get('shape'))
		position = state.get('position')
		if shape is None or position is None or any(state.get(k) is None for k in ('yaw', 'pitch', 'roll')):
			return None
		return dict(id=state.get('id'), x=position[0], y=position[1], z=position[2], shape=shape,
			yaw=state['yaw'], pitch=state['pitch'], roll=state['roll'])

	def _native_geometry(self, op, position, yaw, neighbours, half_length, half_width, amount):
		if not isinstance(neighbours, (tuple, list)):
			return None
		for name in ('_obb_overlap', '_neighbour_position'):
			method = getattr(self, name)
			original = getattr(LocalDriver, name)
			if getattr(method, 'im_func', getattr(method, '__func__', method)) is not getattr(
					original, 'im_func', getattr(original, '__func__', original)):
				return None
		from gui.mods.offline_lan_0922 import native_math
		return native_math.call('driver_geometry', op,
			(tuple(position) + (yaw, half_length, half_width, amount)),
			neighbours, RECOVERY_SWEEP_FRACTIONS)

	def _reference_reverse_blocked_by_vehicle(self, position, yaw, neighbours,
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
					if outward >= -1.0e-9:
						# The sweep includes the current hull. Its front/side
						# contact is not a new rear obstacle when every point
						# moves out or tangentially along that face. Centre
						# distance may stay constant in an exactly parallel
						# side hug; neither direction may be denied for that.
						# Centre approach cannot veto a non-deepening face.
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
			half_length, half_width, body=None):
		if body is not None and abs(math.sin(candidate_yaw-body['yaw'])) < 1.e-9:
			stationary = [peer for peer in neighbours or () if not peer.get('alive', True) or
				(peer.get('velocity') is not None and math.hypot(peer['velocity'][0], peer['velocity'][2]) <= .65)]
			return self._reverse_blocked_by_vehicle(position, candidate_yaw+math.pi,
				stationary, half_length, half_width, body=body) is not None
		result = self._native_geometry(1, position, candidate_yaw, neighbours,
			half_length, half_width, half_length * 1.6)
		if result is not None:
			return bool(result)
		return self._reference_static_hull_ahead(position, candidate_yaw, neighbours,
			half_length, half_width)

	def _reference_static_hull_ahead(self, position, candidate_yaw, neighbours,
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
		result = self._native_geometry(2, position, yaw, neighbours,
			half_length, half_width, direction * RECOVERY_YAW_OFFSET)
		if result is not None:
			return result
		return self._reference_recovery_occupancy(position, yaw, direction, neighbours,
			half_length, half_width)

	def _reference_recovery_occupancy(self, position, yaw, direction, neighbours,
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

	_paired_recovery_law = _recovery_occupancy
	_paired_geometry_law = _native_geometry

	@observed('driver.recovery')
	def _select_recovery_side(self, state, position, yaw, neighbours,
			half_length, half_width):
		"""Prefer the less occupied pivot arc, then use stable slot parity."""
		pair = None
		if (type(self) is LocalDriver and
				(type(position) is tuple or type(position) is list) and
				(type(neighbours) is tuple or type(neighbours) is list) and
				not any(name in self.__dict__ for name in
					('_recovery_occupancy', '_native_geometry')) and
				LocalDriver.__dict__['_recovery_occupancy'] is
				LocalDriver.__dict__['_paired_recovery_law'] and
				LocalDriver.__dict__['_native_geometry'] is
				LocalDriver.__dict__['_paired_geometry_law']):
			pair = self._native_geometry(10, position, yaw, neighbours,
				half_length, half_width, RECOVERY_YAW_OFFSET)
		if pair is None:
			negative = self._recovery_occupancy(
				position, yaw, -1.0, neighbours, half_length, half_width)
			positive = self._recovery_occupancy(
				position, yaw, 1.0, neighbours, half_length, half_width)
		else:
			negative, positive = pair
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

	def _partial_pivot(self, pose_clear, yaw, direction, rate, horizon):
		"""Prove a shorter arc and limit the command to its admitted angle."""
		if pose_clear is None or rate is None or float(rate) <= 0.0:
			return None
		for fraction in (0.5, 0.25, 0.125):
			extent = RECOVERY_YAW_OFFSET * fraction
			for side in (direction, -direction):
				if all(self._pose_fits(pose_clear, float(yaw) + side * extent * f)
						for f in RECOVERY_SWEEP_FRACTIONS):
					turn = side * min(1.0, extent / (float(rate) * max(0.001, float(horizon))))
					return dict(throttle=0.0, turn=turn, target_yaw=float(yaw) + side * extent,
						recovery_mode='partial_pivot_recovery', recovery_pivot_extent=extent)
		return None

	# Pin the current law without executing descriptors during admission.
	_candidate_rank_failure_law = _failure_penalty
	_candidate_rank_yaw_law = _yaw_key

	def _rank_yaw_candidates(self, state, desired_yaw):
		if (type(self) is LocalDriver and type(state) is dict and
				all(type(key) is str for key in state) and 'clock' in state and
				all(type(key) is str for key in self.__dict__) and
				'failure_ttl' in self.__dict__ and 'failure_ttl' not in LocalDriver.__dict__):
			def implementation(name):
				value = self.__dict__.get(name, LocalDriver.__dict__.get(name))
				if type(value) is _types.FunctionType:
					return value
				if type(value) is _types.MethodType:
					return getattr(value, 'im_func', getattr(value, '__func__', None))
				return None
			failed = state.get('failed_yaws')
			offsets = self.__dict__.get('_CANDIDATE_OFFSETS',
				LocalDriver.__dict__.get('_CANDIDATE_OFFSETS'))
			if (type(failed) is dict and (type(offsets) is tuple or type(offsets) is list) and
					implementation('_failure_penalty') is LocalDriver.__dict__['_candidate_rank_failure_law'] and
					implementation('_yaw_key') is LocalDriver.__dict__['_candidate_rank_yaw_law']):
				result = native_math.call('driver_geometry', 9,
					(desired_yaw, state['clock'], self.failure_ttl,
					 state.get('escape_side_until', 0.0), state.get('escape_side', 0.0),
					 math.pi, FAILED_YAW_BUCKET_COUNT), offsets, tuple(failed.items()))
				if result is not None:
					candidates, expired = result
					for key in expired:
						failed.pop(key, None)
					return candidates
		return self._reference_rank_yaw_candidates(state, desired_yaw)

	def _reference_rank_yaw_candidates(self, state, desired_yaw):
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
		return candidates

	@observed('driver.choose_yaw')
	def _choose_yaw(self, state, desired_yaw, direction_clear,
			position=None, neighbours=None,
			half_length=3.5, half_width=1.7, pose_clear=None):
		# Teammate proximity never replaces the route with a repulsion heading.
		# Crossing priority is coordinated separately; real contact owns overlap.
		candidates = self._rank_yaw_candidates(state, desired_yaw)
		# Probe in score order and return the first fully viable direction. Most
		# frames need one terrain ray set instead of probing all seven candidates.
		for unused_score, candidate in candidates:
			if ((pose_clear is None or pose_clear(candidate)) and
					self._clear(direction_clear, candidate) and
					not (position is not None and self._static_hull_ahead(
						position, candidate, neighbours,
						half_length, half_width, body=state.get('collision_body')))):
				state['steering_reason'] = (
					'route' if abs(_angle_delta(candidate, desired_yaw)) <= 0.05
					else 'obstacle')
				if state['steering_reason'] == 'obstacle':
					state['escape_side'] = 1.0 if _angle_delta(candidate, desired_yaw) > 0.0 else -1.0
					state['escape_side_until'] = state['clock'] + 2.5
				return candidate
		return None

	def _short_escape(self, state, position, yaw, speed, step, horizon,
			stopping_distance, neighbours, direction_clear, half_length, half_width):
		"""Choose a fresh straight escape independently of available pivot arcs."""
		minimum = max(0.5, float(stopping_distance or 0.0) +
			abs(float(speed)) * max(step, float(horizon)))
		probes = []
		state['short_escape_probes'] = probes
		sequence = state.get('short_escape_sample_sequence', 0) + 1
		state['short_escape_sample_sequence'] = sequence
		state['short_escape_sample'] = dict(sequence=sequence,
			sampled_at=state['clock'], origin=tuple(position), yaw=float(yaw),
			clock_basis='driver_elapsed_seconds', phase='candidate_selection')
		state.pop('short_escape_validation', None)
		for distance in (max(2.0, minimum), max(1.0, minimum), minimum):
			for sign in (-1.0, 1.0):
				heading = float(yaw) + (math.pi if sign < 0 else 0.0)
				# Long-ray/candidate failures cannot veto a fresh shorter proof.
				real_failure = self._short_failure_applies(state, position, heading, distance)
				clear = not real_failure and self._clear(direction_clear, heading, distance)
				proof = dict(self._last_direction_receipt) if not real_failure else {}
				blocker = self._reverse_blocked_by_vehicle(
					position, float(yaw) if sign < 0 else float(yaw) + math.pi,
					neighbours, half_length, half_width, maximum_distance=distance, body=state.get('collision_body')) if clear else None
				probes.append(dict(sign=sign, distance=distance, clear=clear,
					reason=('realized_failure' if real_failure else
						'vehicle_occupied' if blocker is not None else
						proof.get('reason') or ('clear' if clear else 'direction_callback_rejected')),
					probe_receipt=proof, vehicle_receipt=(dict(getattr(self,
						'_last_reverse_receipt', {})) if clear else None),
					sampled_at=state['clock'], sample_sequence=sequence,
					blocker=blocker, real_failure=real_failure,
					failure_evidence=dict(state.get('real_failure_evidence', {}).get(
						self._yaw_key(heading)) or {})))
				if clear and blocker is None:
					state['short_translation_escape'] = dict(start=tuple(position),
						yaw=float(yaw), sign=sign, distance=distance,
						until=state['clock'] + 4.0)
					return dict(throttle=sign * 1.0, turn=0.0, target_yaw=float(yaw),
						recovery_probe_distance=distance,
						recovery_probe_origin=tuple(position), recovery_probe_yaw=heading,
						recovery_probe_length=distance,
						recovery_mode='short_reverse_escape' if sign < 0 else 'short_forward_escape')
		return None

	@staticmethod
	def _finish_translation_escape(state, escape, position, reason, remaining):
		state['escape_terminal'] = dict(at=state['clock'],
			clock_basis='driver_elapsed_seconds', origin=escape['start'],
			position=tuple(position), reason=reason, remaining=remaining,
			sign=escape.get('sign', 1.0), distance=escape['distance'],
			recovery_time_before=state.get('recovery_time', 0.0))
		if reason == 'distance_completed':
			if state.get('recovery_time', 0.0) > 0.0:
				state['recovery_count'] = state.get('recovery_count', 0) + 1
			state['recovery_time'] = 0.0
			state['recovery_side'] = 0.0
			state['stuck_time'] = 0.0
			state['heading_progress_yaw'] = None

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
		validation = dict(sampled_at=state['clock'], origin=tuple(position),
			clock_basis='driver_elapsed_seconds', phase='retained_execution_check',
			remaining=remaining, yaw=heading,
			selection_sequence=state.get('short_escape_sample_sequence'),
			result='released')
		state['short_escape_validation'] = validation
		# Preserve the existing short-circuit order and query count. Record the
		# first owner that releases the manoeuvre, including non-query exits.
		reason = None
		if self._short_failure_applies(state, position, heading, remaining):
			reason = 'realized_failure'
		elif remaining <= 0.05:
			reason = 'distance_completed'
		elif state['clock'] >= escape['until']:
			reason = 'lease_expired'
		elif abs(_angle_delta(yaw, escape['yaw'])) > 0.30:
			reason = 'heading_changed'
		else:
			clear = self._clear(direction_clear, heading, remaining)
			validation['probe_receipt'] = dict(self._last_direction_receipt)
			if not clear:
				reason = validation['probe_receipt'].get('reason') or 'direction_callback_rejected'
			else:
				blocker = self._reverse_blocked_by_vehicle(position,
					yaw if sign < 0 else yaw + math.pi, neighbours,
					half_length, half_width, remaining, body=state.get('collision_body'))
				validation['vehicle_receipt'] = dict(getattr(self, '_last_reverse_receipt', {}))
				validation['blocker'] = blocker
				if blocker is not None:
					reason = 'vehicle_occupied'
		validation['reason'] = reason or 'clear'
		if reason is not None:
			self._finish_translation_escape(state, escape, position, reason, remaining)
			state.pop('short_translation_escape', None)
			return None
		validation['result'] = 'retained'
		return dict(throttle=sign * 1.0, turn=0.0, target_yaw=escape['yaw'],
			recovery_probe_distance=remaining,
			recovery_probe_origin=escape['start'], recovery_probe_yaw=heading,
			recovery_probe_length=escape['distance'],
			recovery_mode='short_reverse_escape' if sign < 0 else 'short_forward_escape')

	@staticmethod
	def short_escape_diagnostics(state):
		"""Describe observation age without recasting or changing a decision."""
		clock = state.get('clock')
		escape = state.get('short_translation_escape')
		result = dict(retained_escape_present=bool(escape),
			lease_unexpired=bool(escape and clock is not None and clock < escape['until']),
			observed_at=clock, clock_basis='driver_elapsed_seconds',
			freshness_basis='driver_step')
		for field, key in (('selection', 'short_escape_sample'),
				('execution_check', 'short_escape_validation')):
			sample = state.get(key)
			if sample is None or (field == 'selection' and
					'short_escape_probes' not in state):
				continue
			sample = dict(sample)
			age = max(0.0, clock - sample['sampled_at']) if clock is not None else None
			sample.update(age_seconds=age,
				historical=age > 1.0e-6 if age is not None else None)
			result[field] = sample
		return result

	def _retained_translation_escape(self, state, position, yaw, neighbours,
			direction_clear, half_length, half_width):
		"""Finish a checked straight exit before retrying an impossible pivot."""
		escape = state.get('translation_escape')
		if escape is None:
			return None
		distance = _distance(position, escape['start'])
		remaining = max(0.0, escape['distance'] - distance)
		# The execution owner checks at least this reach for forward_escape.
		# A 9 cm remainder must not repeatedly admit a command whose 50 cm
		# commitment reaches a wet edge. Fixed-endpoint short escapes retain
		# their separate endpoint law.
		probe_distance = max(RECOVERY_COMMIT_MINIMUM, remaining)
		if (remaining <= 0.05 or state['clock'] >= escape['until'] or
				abs(_angle_delta(yaw, escape['yaw'])) > 0.30 or
				self._failure_penalty(state, yaw) > 0.0 or
				not self._clear(direction_clear, yaw, probe_distance) or
				self._reverse_blocked_by_vehicle(position, yaw + math.pi,
					neighbours, half_length, half_width, remaining, body=state.get('collision_body')) is not None):
			self._finish_translation_escape(state, escape, position,
				'distance_completed' if remaining <= 0.05 else 'execution_rejected', remaining)
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
			progress_target=None, turn_speed_limit=None, arrival_radius=None,
			rotation_refused=False, recovery_goal=None, body=None,
			progress_identity=None):
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
		state['collision_body'] = body
		requested_target = tuple(target)
		# Cleared for every call, including arrival/hold/recovery early returns.
		state.pop('pedal_observation', None)
		alignment = state.get('alignment_target')
		previous_alignment = alignment
		release_reason = ('movement_hold' if not movement_intent else
			'reverse_motion' if float(speed) < -0.05 else
			'traverse_unavailable' if turn_speed_limit is None else
			'current_point_reached' if _distance(position, target) <= arrival else
			'local_leg_changed' if alignment is not None and
			_distance(alignment, target) > 2.0 else None)
		if release_reason is not None:
			state.pop('alignment_target', None)
			alignment = None
		# The retained point must own the heading as well as the brake.
		# Steering toward each rebased near point while waiting to align with
		# the old one makes the commanded heading chase the hull indefinitely.
		# The existing two-metre identity, movement and reverse guards above
		# still end this lease. The normal pose/world/peer checks below admit
		# the held heading; an avoidance choice cancels it as before.
		if alignment is not None:
			target = alignment
		state['alignment_observation'] = dict(requested=requested_target,
			resolved=tuple(target), retained=alignment is not None,
			previous=previous_alignment, reason=release_reason or
			('retained_heading' if alignment is not None else 'current_target'))
		step = max(0.0, float(dt))
		if not state.pop('traffic_waiting', False):
			state['traffic_wait_time'] = 0.0
		state['last_step'] = step
		state['clock'] += step
		# A moving enemy and a mechanical sub-action are not new journeys.
		# Only a different tactical owner may discard this progress episode.
		if state.get('progress_identity') != progress_identity:
			state.pop('objective_progress', None)
			state.pop('recovery_pocket', None)
			state.pop('recovery_replan_episode', None)
		state['progress_identity'] = progress_identity
		self._prune_failures(state)
		state['steering_age'] += step
		state['plan_age'] += step
		desired_yaw = _yaw_to(position, target)
		heading_error = abs(_angle_delta(desired_yaw, yaw))
		state['last_desired_yaw'] = desired_yaw
		target_distance = _distance(position, target)
		if not movement_intent:
			preserve_progress = progress_identity is not None and state.get('objective_progress') is not None
			state.pop('arrival_trace', None)
			state['native_translation_stalled'] = False
			state.pop('short_translation_escape', None)
			state.pop('translation_escape', None)
			if preserve_progress:
				# Pause an intentional firing hold, rather than either granting
				# new travel or counting the hold itself as a failed movement.
				state['objective_progress']['at'] += step
				state['objective_progress']['hold_paused_seconds'] = state['objective_progress'].get('hold_paused_seconds', 0.0) + step
				state['objective_progress'].update(hold_paused=True,
					translation_credit=False, alignment_credit=False,
					credit_age_seconds=state['clock'] - state['objective_progress']['at'])
				state['translation_progress_at'] = state.get('translation_progress_at', state['clock'] - step) + step
			else:
				state['translation_progress_at'] = state['clock']
				state.pop('objective_progress', None)
			if not preserve_progress:
				state.pop('recovery_replan_episode', None)
				state.pop('recovery_pocket', None)
				state.pop('short_escape_probes', None)
			# Cover/engagement orders intentionally stop within a tolerance. Do not
			# reinterpret that commanded hold as a stuck tank 1.8 seconds later.
			if not preserve_progress:
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
		# A proved steering waypoint is not the recovery task's identity.
		# Switching nearby bypass legs must not erase the native-refusal lease.
		pocket_goal = recovery_goal if recovery_goal is not None else (progress_target or target)
		pocket = state.get('recovery_pocket')
		if pocket is not None and (
				_distance(position, pocket['origin']) >= 2.0 * own_half_length + arrival or
				(progress_identity is None and _distance(pocket['goal'], pocket_goal) > 2.0)):
			state.pop('recovery_pocket', None)
			state.pop('short_escape_probes', None)
			pocket = None
		pocket_stalled = bool(pocket is not None and
			state['clock'] - pocket['at'] >= 8.0 and state['recovery_count'] >= 2)
		displacement = _distance((position[0], 0.0, position[2]),
		                         (state['last_position'][0], 0.0,
		                          state['last_position'][1]))
		if displacement >= 0.08 or 'translation_progress_at' not in state:
			state['translation_progress_at'] = state['clock']
		translation_stalled = state['clock'] - state['translation_progress_at'] >= 8.0
		# A nearby path connector is not arrival at the tactical destination.
		# Keep physical no-progress evidence across route/withdraw goal changes
		# after a realised native refusal. Neither an elapsed timer alone nor
		# reaching the actual destination may manufacture a recovery command.
		native_translation_stalled = bool(rotation_refused and translation_stalled and
			_distance(position, pocket_goal) > arrival)
		state['native_translation_stalled'] = native_translation_stalled
		# Local targets may alternate around a prop while the tank makes no
		# progress toward its actual order. Do not credit that orbit as travel.
		objective_stalled = False
		objective_advanced = False
		if progress_target is not None:
			progress = state.get('objective_progress')
			distance = _distance(position, progress_target)
			goal_changed = bool(progress_identity is None and progress is not None and
				_distance(progress.get('order_goal', progress['goal']), pocket_goal) > 2.0)
			if progress is None or goal_changed or (progress_identity is None and _distance(position, pocket_goal) <= arrival):
				reset_receipt = dict(at=state['clock'], position=tuple(position),
					previous_order=progress.get('order_goal') if progress else None,
					previous_goal=progress.get('goal') if progress else None,
					previous_credit_age=state['clock']-progress['at'] if progress else None,
					previous_credit_reason=progress.get('credit_reason') if progress else None,
					previous_travel_best=progress.get('travel_best') if progress else None,
					previous_alignment_best=progress.get('alignment_best') if progress else None,
					new_order=tuple(pocket_goal))
				progress = {'goal': tuple(progress_target), 'best': distance,
				            'identity': progress_identity,
				            'order_goal': tuple(pocket_goal), 'at': state['clock'],
				            'travel_origin': tuple(position), 'travel_best': 0.0,
				            'order_best': _distance(position, pocket_goal),
				            'connectors': [],
				            'reset_receipt': reset_receipt,
				            'credit_reason': 'new_order_or_destination',
				            'reset_reason': 'order_changed' if goal_changed else 'initial_or_arrived'}
				state['objective_progress'] = progress
			elif _distance(progress['goal'], progress_target) > 2.0:
				# A different local connector is not physical progress. Rebase
				# its incomparable distance without renewing this order's clock
				# or granting the same hull alignment a second time.
				# Preserve each connector's best distance and fixed alignment
				# anchor across revisits. An ELC-sized orbit between two proved
				# near points is not a fresh journey on every rebase.
				connectors = progress.setdefault('connectors', [])
				previous = dict((key, progress[key]) for key in
					('goal', 'best') if key in progress)
				revisited = None
				for index, connector in enumerate(connectors):
					if _distance(connector['goal'], progress_target) <= 2.0:
						revisited = connectors.pop(index)
						break
				connectors.append(previous)
				del connectors[:-16]
				progress.update(revisited or dict(goal=tuple(progress_target), best=distance))
				progress['local_rebases'] = progress.get('local_rebases', 0) + 1
				progress['reset_reason'] = ('revisited_connector_without_credit' if revisited
					else 'local_rebase_without_credit')
				if revisited is not None:
					progress['revisited_connectors'] = progress.get('revisited_connectors', 0) + 1
			# One order owns one physical progress frontier and alignment anchor.
			# New/revisited connectors cannot turn the same two-metre oscillation
			# into fresh travel or a fresh left/right turn every planning tick.
			origin = progress.setdefault('travel_origin', tuple(position))
			travel = _distance(position, origin)
			local_progress_admitted = progress_identity is not None or _distance(progress_target, pocket_goal) > 2.0
			# This frontier is local, not a global straight-line route metric.
			# Leaving the same vehicle-sized pocket starts fresh travel/turn
			# measurement, so a legitimate curved route may approach it again.
			departed = local_progress_admitted and travel >= 2.0 * own_half_length + arrival
			progress['pocket_departed'] = departed
			if departed:
				progress['previous_travel_origin'] = origin
				progress['travel_origin'] = tuple(position)
				progress['travel_best'] = 0.0
				progress.pop('alignment_yaw', None)
				progress.pop('alignment_best', None)
				travel = 0.0
			# Measure the same destination from both poses. Enemy translation
			# must never earn distance credit for a stationary chassis.
			order_anchor = progress.get('order_goal', pocket_goal)
			order_distance = _distance(position, order_anchor)
			travel_best = progress.setdefault('travel_best', travel)
			order_best = progress.setdefault('order_best', order_distance)
			new_travel = local_progress_admitted and travel >= travel_best + 0.08
			new_order_distance = order_distance + 0.08 <= order_best
			progress.update(travel_distance=travel, order_distance=order_distance,
				hold_paused=False, requested_order_goal=tuple(pocket_goal),
				local_progress_admitted=local_progress_admitted,
				translation_credit=bool(new_travel or new_order_distance or departed),
				alignment_credit=False)
			if new_travel or new_order_distance or departed:
				progress['travel_best'] = max(travel_best, travel)
				progress['order_best'] = min(order_best, order_distance)
				progress['at'] = state['clock']
				progress['credit_reason'] = ('left_local_pocket' if departed else
					'new_order_distance' if new_order_distance
					else 'new_travel_frontier')
				objective_advanced = True
			# The executed near endpoint can differ from the macro progress
			# point. Keep fixed per-point minima across revisits, so completing
			# a real dogleg is not undone by the older tactical-distance clock.
			# Selection/rebasing alone earns no credit, nor does moving a target.
			if local_progress_admitted:
				actions = progress.setdefault('action_points', [])
				action = next((item for item in actions
					if _distance(item['goal'], target) <= 2.0), None)
				if action is None:
					action = dict(goal=tuple(target), best=target_distance)
					actions.append(action)
					del actions[:-16]
				else:
					action_distance = _distance(position, action['goal'])
					if (displacement >= 0.08 and abs(float(speed)) > 0.05 and
							action_distance + 0.08 <= action['best']):
						action['best'] = action_distance
						progress['at'] = state['clock']
						progress['translation_credit'] = True
						progress['credit_reason'] = 'new_best_action_translation'
						objective_advanced = True
			# A connector's best distance and its current distance must use
			# the SAME fixed point. Native rebasing/steering may supply another
			# point within the existing 2 m identity tolerance without travel.
			distance = _distance(position, progress['goal'])
			progress['measured_distance'] = distance
			progress['steering_distance'] = _distance(position, progress_target)
			if distance + 0.08 <= progress['best']:
				objective_advanced = True
				progress['best'] = distance
				if (local_progress_admitted and displacement >= 0.08 and
						abs(float(speed)) > 0.05 and not (new_travel or new_order_distance or departed)):
					# A checked dogleg/mechanical action may approach its fixed
					# endpoint while moving away from the older tactical anchor.
					# Revisited connectors keep their old best; merely changing
					# the point or turning does not renew this translation clock.
					progress['at'] = state['clock']
					progress['translation_credit'] = True
					progress['credit_reason'] = 'new_best_local_translation'
				# Real translation earns distance credit, but must not grant
				# the same already-earned turn a fresh alignment anchor.
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
						progress['credit_reason'] = 'new_best_alignment'
						progress['alignment_credit'] = True
			objective_stalled = state['clock'] - progress['at'] >= 8.0
			progress['credit_age_seconds'] = state['clock'] - progress['at']
		# Starting recovery renews its retry clock, not arrival at the remote
		# objective. A close connector must not cancel the next recovery frame.
		retained_recovery = bool(state['recovery_time'] > 0.0 and
			_distance(position, pocket_goal) > arrival)
		state['arrival_trace'] = dict(local_distance=target_distance,
			goal_distance=_distance(position, pocket_goal), arrival_radius=arrival,
			objective_stalled=objective_stalled,
			objective_age=(state['clock']-state['objective_progress']['at']
				if progress_target is not None else None),
			translation_age=state['clock']-state['translation_progress_at'],
			rotation_refused=bool(rotation_refused),
			recovery_time_before=state['recovery_time'],
			retained_recovery=retained_recovery)
		if (target_distance <= arrival and not objective_stalled and
				not native_translation_stalled and not retained_recovery):
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
		if objective_stalled or native_translation_stalled:
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
					state['objective_progress']['credit_reason'] = 'recovery_retry'
					state['objective_progress']['credit_age_seconds'] = 0.0
				if rotation_refused and state.get('recovery_pocket') is None:
					state['recovery_pocket'] = dict(origin=tuple(position),
						at=state['clock'], goal=tuple(pocket_goal))
				if state.get('last_clear_yaw') is not None:
					state['failed_yaws'][self._yaw_key(state['last_clear_yaw'])] = (
						state['clock'] + self.failure_ttl)
				state['recovery_trigger'] = dict(at=state['clock'],
					clock_basis='driver_elapsed_seconds', origin=tuple(position),
					target=tuple(target), goal=tuple(pocket_goal),
					reason=('objective_timeout' if objective_stalled else
						'native_translation_timeout' if native_translation_stalled else 'local_stuck'),
					translation_age=state['clock']-state['translation_progress_at'],
					displacement=displacement, objective={key:value for key,value in
						(state.get('objective_progress') or {}).items() if key in (
						'goal', 'best', 'at', 'order_goal', 'order_best', 'order_distance',
						'travel_origin', 'travel_best', 'travel_distance', 'credit_reason',
						'credit_age_seconds', 'translation_credit', 'alignment_credit')})
				state['recovery_time'] = (
					self.recovery_seconds + timing_phase * 0.28)
				state['recovery_side'] = self._select_recovery_side(
					state, position, yaw, neighbours,
					own_half_length, own_half_width)

		if state['recovery_time'] > 0.0:
			state.pop('alignment_target', None)
			state['alignment_observation']['reason'] = 'recovery_owns_heading'
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
					own_half_length, own_half_width, body=state.get('collision_body'))
			if not reverse_clear or reverse_blocker is not None:
				if objective_stalled or translation_stalled or pocket_stalled:
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
							own_half_length, own_half_width, body=state.get('collision_body'))
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
						partial = self._partial_pivot(pose_clear, yaw, direction,
							turn_speed_limit, max(step, float(decision_horizon)))
						if partial is not None:
							return partial
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
				result = dict(throttle=0.0, turn=direction,
					target_yaw=recovery_yaw, recovery_mode='pivot_recovery')
				if reverse_blocker is not None:
					result['reverse_blocked_by'] = reverse_blocker
				return result
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
					own_half_length, own_half_width, body=state.get('collision_body'))):
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
		pedal_gates = []
		if avoiding:
			state.pop('alignment_target', None)
			state['alignment_observation']['reason'] = 'checked_avoidance_owns_heading'
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
					pedal_gates.append('retained_near_point_alignment')
				else:
					state.pop('alignment_target', None)
					state['alignment_observation']['reason'] = 'alignment_completed'
		if (target_distance <= max(8.0, own_half_length * 2.0) and
				abs(delta) > 0.45):
			# Both path corners and native-checked avoidance steps can be inside
			# the moving hull's turning circle. Align before driving either one.
			throttle = 0.0
			brake = True
			pedal_gates.append('near_corner_alignment')
		climb_grade = ((float(target[1]) - float(position[1])) /
		               max(0.1, target_distance))
		if abs(climb_grade) > SLOPE_ALIGNMENT_GRADE and abs(delta) > SLOPE_ALIGNMENT_TURN:
			# Enter genuinely steep uphill/downhill edges square to the slope. Full drive
			# while the hull is still turning makes it circle at the foot of the
			# climb and repeatedly invalidates the next terrain sample.
			throttle = 0.0
			brake = True
			pedal_gates.append('slope_entry_alignment')
		elif (abs(delta) > math.pi * 0.5 or
				(not avoiding and heading_error > math.pi * 0.5)):
			# A selected escape behind the hull needs a pivot too: forward drive
			# initially moves into the contact it is trying to leave. On a clear
			# route use the live goal as well as the held heading, so passing the
			# goal cannot delay braking until the steering lease expires. Side and
			# diagonal corners still retain forward progress while steering.
			throttle = 0.0
			brake = True
			pedal_gates.append('rear_heading_alignment')
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
					pedal_gates.append('destination_stopping_distance')
		elif not stop_at_target:
			state['braking_target'] = None
		state['pedal_observation'] = dict(clock=state['clock'],
			requested_target=requested_target, resolved_target=tuple(target),
			distance=target_distance, hull_yaw=float(yaw), desired_yaw=desired_yaw,
			chosen_yaw=chosen_yaw, delta=delta, speed=float(speed),
			turn_speed_limit=turn_speed_limit, avoiding=avoiding,
			alignment_target=state.get('alignment_target'), gates=pedal_gates,
			throttle=throttle, turn=turn, brake=brake, reason='drive_pedal_arbitration')
		return {
			'throttle': throttle,
			'brake': brake,
			'turn': turn,
			'target_yaw': chosen_yaw,
			'recovery_mode': 'avoid' if avoiding else 'drive',
		}
