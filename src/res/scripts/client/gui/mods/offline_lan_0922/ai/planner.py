# -*- coding: utf-8 -*-
"""Engine-free vehicle profiles and lineup/setup helpers.

This module is deliberately engine-free so its decisions can be tested on a
modern Python interpreter while the shipped client still imports it on its
Python 2 runtime. Runtime orders and combat decisions belong exclusively to
``vehicle_control``. No local director or alternative controller lives here.
"""

import hashlib
import math
import random

BATTLE_TIER_RADIUS = 2
MATCH_CLASSES = ('heavyTank', 'mediumTank', 'AT-SPG', 'lightTank', 'SPG')
CLASS_ROUTE_AFFINITY_WEIGHT = 42.0
ARTILLERY_ROUTE_REPEAT_PENALTY = 120.0

BOT_TIER_MODE_RANDOM = 'random'
BOT_TIER_MODE_SAME = 'same'
BOT_TIER_MODE_MINUS1_0 = 'minus1_0'
BOT_TIER_MODE_0_PLUS1 = '0_plus1'
BOT_TIER_MODE_MINUS1_PLUS1 = 'minus1_plus1'
BOT_TIER_MODE_MINUS2_0 = 'minus2_0'
BOT_TIER_MODE_0_PLUS2 = '0_plus2'
BOT_TIER_MODES = (
	BOT_TIER_MODE_RANDOM, BOT_TIER_MODE_SAME, BOT_TIER_MODE_MINUS1_0,
	BOT_TIER_MODE_0_PLUS1, BOT_TIER_MODE_MINUS1_PLUS1,
	BOT_TIER_MODE_MINUS2_0, BOT_TIER_MODE_0_PLUS2)


def _number(value, default=0.0):
	try:
		result = float(value)
		if math.isinf(result) or math.isnan(result):
			return float(default)
		return result
	except Exception:
		return float(default)


def vehicle_in_battle_tier_band(player_tier, candidate_tier):
	"""Admit the union of legal windows; bot_match_tiers chooses ONE window."""
	try:
		return abs(int(candidate_tier) - int(player_tier)) <= BATTLE_TIER_RADIUS
	except Exception:
		return False


def team_artillery_limit(team_size):
	"""Cap automatic artillery by total team size, including human slots."""
	team_size = max(0, int(team_size))
	return 0 if team_size <= 6 else min(3, (team_size - 4) // 3)


def select_bot_lineup(pool, count, spg_limit=None, fallback_candidates=()):
	"""Fill a team while enforcing an exact SPG cap.

	The caller subtracts human artillery from the total-team limit. ``AT-SPG`` is a tank destroyer
	in the legacy tags and does not consume the artillery quota.
	"""
	count = max(0, int(count))
	if spg_limit is None:
		spg_limit = team_artillery_limit(count)
	spg_limit = max(0, min(3, int(spg_limit)))
	pool = list(pool or ())
	if not pool or count <= 0:
		return []
	regular = []
	seen = set()
	for candidate in pool + list(fallback_candidates or ()):
		try:
			tags = candidate['tags']
			name = candidate['name']
		except Exception:
			continue
		if 'SPG' in tags or name in seen:
			continue
		seen.add(name)
		regular.append(candidate)
	result = []
	spg_count = 0
	regular_index = 0
	for index in range(count):
		candidate = pool[index % len(pool)]
		try:
			is_spg = 'SPG' in candidate['tags']
		except Exception:
			is_spg = False
		if is_spg and spg_count >= spg_limit:
			if not regular:
				continue
			candidate = regular[regular_index % len(regular)]
			regular_index += 1
			is_spg = False
		if is_spg:
			spg_count += 1
		result.append(candidate)
	return result


def vehicle_match_class(candidate):
	"""Return the exact legacy matchmaking class for a vehicle record."""
	try:
		tags = candidate['tags']
	except Exception:
		tags = ()
	for class_tag in MATCH_CLASSES:
		if class_tag in tags:
			return class_tag
	return 'mediumTank'


def choose_match_tiers(player_tier, mode_roll, side_roll=0.5,
		available_tiers=(), required_tiers=()):
	"""Select one contiguous window, including the known LAN humans first.

	The synthetic room has no public queue. Its random sampling is an offline
	policy, not Wargaming's queue-time algorithm or historical probabilities.
	Explicitly wide human selections stay a custom room, never a five-tier
	automatic expansion around the first connected player.
	"""
	player_tier = max(1, min(10, int(_number(player_tier, 1))))
	available = set(int(_number(value)) for value in
		(available_tiers or range(1, 11)) if 1 <= _number(value) <= 10)
	required = set(int(_number(value)) for value in
		(required_tiers or ()) if 1 <= _number(value) <= 10)
	required.add(player_tier)
	available.update(required)
	if max(required) - min(required) > 2:
		return tuple(sorted(required))
	preferred = 1 if _number(mode_roll) < 0.28 else (
		2 if _number(mode_roll) < 0.72 else 3)
	minimum = max(required) - min(required) + 1
	preferred = max(preferred, minimum)
	for width in range(preferred, minimum - 1, -1):
		windows = []
		for low in range(max(1, player_tier - width + 1),
				min(player_tier, 11 - width) + 1):
			window = tuple(range(low, low + width))
			if required.issubset(window) and set(window).issubset(available):
				windows.append(window)
		if windows:
			index = min(len(windows) - 1,
				int(max(0.0, min(1.0, _number(side_roll))) * len(windows)))
			return windows[index]
	return tuple(sorted(required))


def normalize_bot_tier_mode(value):
	"""Return one supported waiting-room Bot tier preset."""
	return value if value in BOT_TIER_MODES else BOT_TIER_MODE_RANDOM


def bot_match_tiers(player_tier, mode, mode_roll=0.5, side_roll=0.5,
					available_tiers=(), required_tiers=()):
	"""Resolve a host-selected tier preset against the available catalog."""
	try:
		player_tier = max(1, min(10, int(player_tier)))
	except Exception:
		player_tier = 1
	available = set()
	for value in (available_tiers or range(1, 11)):
		try:
			value = int(value)
		except Exception:
			continue
		if 1 <= value <= 10:
			available.add(value)
	available.add(player_tier)
	mode = normalize_bot_tier_mode(mode)
	if mode == BOT_TIER_MODE_RANDOM:
		return choose_match_tiers(
			player_tier, mode_roll, side_roll, available, required_tiers)
	desired = {
		BOT_TIER_MODE_SAME: (player_tier,),
		BOT_TIER_MODE_MINUS2_0: (player_tier - 2, player_tier - 1, player_tier),
		BOT_TIER_MODE_0_PLUS2: (player_tier, player_tier + 1, player_tier + 2),
		BOT_TIER_MODE_MINUS1_0: (player_tier - 1, player_tier),
		BOT_TIER_MODE_0_PLUS1: (player_tier, player_tier + 1),
		BOT_TIER_MODE_MINUS1_PLUS1: (
			player_tier - 1, player_tier, player_tier + 1),
	}[mode]
	return tuple(value for value in desired if value in available)


def vehicle_in_bot_tier_mode(player_tier, candidate_tier, mode):
	"""Whether a vehicle can fill the selected preset before template fill."""
	try:
		candidate_tier = int(candidate_tier)
	except Exception:
		return False
	if normalize_bot_tier_mode(mode) == BOT_TIER_MODE_RANDOM:
		return vehicle_in_battle_tier_band(player_tier, candidate_tier)
	return candidate_tier in bot_match_tiers(
		player_tier, mode, available_tiers=range(1, 11))


def select_vehicle_variety_pool(candidates, player_tier, max_unique,
		rng=None):
	"""Build a small texture-safe pool while preserving tiers and classes."""
	rng = rng or random
	max_unique = max(0, int(max_unique))
	if max_unique <= 0:
		return list(candidates or ())
	unique = []
	seen = set()
	for candidate in (candidates or ()):
		try:
			name = str(candidate['name'])
		except Exception:
			continue
		if name in seen:
			continue
		seen.add(name)
		unique.append(candidate)
	try:
		rng.shuffle(unique)
	except Exception:
		random.shuffle(unique)
	selected = []
	selected_names = set()

	def _take(options):
		for candidate in options:
			name = str(candidate['name'])
			if name not in selected_names:
				selected.append(candidate)
				selected_names.add(name)
				return True
		return False

	# Prefer one of each role at the selected tier, then fill any missing role
	# from a neighbouring tier. This keeps single-tier matches tactically varied.
	for class_tag in MATCH_CLASSES:
		if len(selected) >= max_unique:
			break
		exact = [candidate for candidate in unique
			if int(candidate.get('level', 0) or 0) == int(player_tier) and
			vehicle_match_class(candidate) == class_tag]
		if not _take(exact):
			_take([candidate for candidate in unique
				if vehicle_match_class(candidate) == class_tag])
	# Make every available tier representable before using the remaining slots.
	levels = sorted(set(int(candidate.get('level', 0) or 0)
		for candidate in unique))
	for level in levels:
		if len(selected) >= max_unique:
			break
		if any(int(candidate.get('level', 0) or 0) == level
				for candidate in selected):
			continue
		_take([candidate for candidate in unique
			if int(candidate.get('level', 0) or 0) == level])
	for candidate in unique:
		if len(selected) >= max_unique:
			break
		_take((candidate,))
	return selected


def shared_human_requirements(team_profiles):
	"""Return the per-profile maxima that a mirrored team template must hold."""
	representatives = {}
	required_counts = {}
	for profiles in (team_profiles or {}).values():
		team_counts = {}
		for profile in (profiles or ()):
			try:
				key = (int(profile.get('level', 0) or 0),
					vehicle_match_class(profile))
			except Exception:
				continue
			team_counts[key] = team_counts.get(key, 0) + 1
			representatives.setdefault(key, profile)
		for key, count in team_counts.items():
			required_counts[key] = max(required_counts.get(key, 0), count)
	result = []
	for key in sorted(required_counts):
		for unused in range(required_counts[key]):
			result.append(representatives[key])
	return result


def match_tier_slots(allowed_tiers, team_size):
	"""9.18 priorities: low/middle/top 7/5/3, or low/top 10/5 at 15.

	Largest-remainder scaling is only for the offline custom team sizes.
	Human reservations and an incomplete catalogue may relax these counts.
	"""
	levels = tuple(sorted(set(allowed_tiers)))
	if not levels or team_size <= 0:
		return []
	weights = {1: (15,), 2: (10, 5), 3: (7, 5, 3)}.get(
		len(levels), (1,) * len(levels))
	total = sum(weights)
	counts = [int(team_size) * weight // total for weight in weights]
	order = sorted(range(len(levels)), key=lambda index:
		(-(int(team_size) * weights[index] % total), index))
	for index in order[:int(team_size) - sum(counts)]:
		counts[index] += 1
	return [level for level, count in zip(levels, counts)
		for unused in range(count)]


def build_match_template(pool, team_size, player_candidate, allowed_tiers,
		rng=None, required_profiles=()):
	"""Share tier/class slots and a size-bounded SPG quota between teams.

	Reserve SPGs against tiers that actually contain artillery. Picking an
	arbitrary tier first and silently replacing a missing SPG with a medium
	used to lose the sole artillery slot. This does not classify unverified
	9.20.1 combat subroles from ad-hoc armour thresholds.
	"""
	rng = rng or random
	team_size = max(1, int(team_size))
	artillery_limit = team_artillery_limit(team_size)
	allowed = tuple(sorted(set(int(value) for value in allowed_tiers)))
	if not allowed:
		allowed = (int(player_candidate.get('level', 1) or 1),)
	usable = [candidate for candidate in (pool or ())
		if int(candidate.get('level', 0) or 0) in allowed]
	if not usable:
		usable = [player_candidate]
	required = list(required_profiles or (player_candidate,))[:team_size]
	tier_slots = match_tier_slots(allowed, team_size)
	rng.shuffle(tier_slots)
	result, usage = [], {}

	def take(choices):
		choices = list(choices)
		rng.shuffle(choices)
		candidate = min(choices, key=lambda value:
			usage.get(str(value.get('name', '')), 0))
		name = str(candidate.get('name', ''))
		usage[name] = usage.get(name, 0) + 1
		result.append(candidate)
		level = int(candidate.get('level', 0) or 0)
		if level in tier_slots:
			tier_slots.remove(level)
		elif tier_slots:
			tier_slots.pop()

	for profile in required:
		if (vehicle_match_class(profile) == 'SPG' and
				sum(vehicle_match_class(value) == 'SPG' for value in result) >= artillery_limit):
			# A human's chosen SPG remains theirs; it must not force an
			# automatic mirrored SPG into a small opposing team.
			choices = [candidate for candidate in usable
				if vehicle_match_class(candidate) != 'SPG']
			if choices:
				same_tier = [value for value in choices if int(value['level']) == int(profile['level'])]
				take(same_tier or choices)
			continue
		choices = [candidate for candidate in usable
			if int(candidate.get('level', 0) or 0) == int(profile['level'])
			and vehicle_match_class(candidate) == vehicle_match_class(profile)]
		take(choices or [profile])

	spg_count = sum(vehicle_match_class(value) == 'SPG' for value in result)
	spg_max = min(artillery_limit, spg_count + team_size - len(result))
	# Uniform within the size limit is a room choice, not a retail spawn rate.
	quota = spg_count + int(rng.random() * (max(0, spg_max-spg_count) + 1))
	quota = min(spg_max, quota)
	while spg_count < quota:
		choices = [candidate for candidate in usable
			if vehicle_match_class(candidate) == 'SPG'
			and int(candidate.get('level', 0) or 0) in tier_slots]
		if not choices:
			break
		take(choices)
		spg_count += 1

	regular_classes = ('heavyTank', 'mediumTank', 'AT-SPG', 'lightTank')
	regular = [candidate for candidate in usable
		if vehicle_match_class(candidate) != 'SPG']
	while len(result) < team_size:
		level = tier_slots[-1] if tier_slots else allowed[0]
		role = regular_classes[len(result) % len(regular_classes)]
		choices = [candidate for candidate in regular
			if int(candidate.get('level', 0) or 0) == level]
		preferred = [candidate for candidate in choices
			if vehicle_match_class(candidate) == role]
		choices = preferred or choices or regular
		if not choices:
			# Do not fill an impossible catalogue with 15 SPGs.
			if spg_count >= artillery_limit:
				break
			choices = usable
			spg_count += 1
		take(choices)
	return result


def remaining_match_template(template, human_profiles):
	"""Remove the closest template slot for each human already on a team."""
	remaining = list(template or ())
	for human in (human_profiles or ()):
		if not remaining:
			break
		human_tier = int(human.get('level', 0) or 0)
		human_class = vehicle_match_class(human)
		best_index = 0
		best_score = None
		for index, candidate in enumerate(remaining):
			candidate_tier = int(candidate.get('level', 0) or 0)
			candidate_class = vehicle_match_class(candidate)
			score = abs(candidate_tier - human_tier) * 3
			if candidate_class != human_class:
				score += 8
			if best_score is None or score < best_score:
				best_score = score
				best_index = index
		remaining.pop(best_index)
	return remaining


def bot_initially_visible(bot_team, player_team, spotting_enabled):
	"""Hide an enemy model before its first spotting update can run."""
	try:
		return (not bool(spotting_enabled) or
			int(bot_team) == int(player_team))
	except Exception:
		return not bool(spotting_enabled)


def entity_visible_to_minimap(entity):
	"""Expose a mock entity to the minimap only after its first spot."""
	return bool(getattr(entity, '_spot_visible', True))


def route_toward_enemy(route, team, bases):
	"""Orient a multi-point route from the own flag to the enemy flag."""
	result = dict(route or {})
	result['role_weights'] = dict(result.get('role_weights', {}) or {})
	points = list(result.get('waypoints', ()) or ())
	if len(points) < 2:
		result['waypoints'] = tuple(points)
		return result
	try:
		own = bases.get(int(team))
		enemy = bases.get(3 - int(team))
		if own is None or enemy is None:
			result['waypoints'] = tuple(points)
			return result
		def _distance(point, base):
			return ((float(point[0]) - float(base[0])) ** 2 +
				(float(point[1]) - float(base[1])) ** 2)
		forward = _distance(points[0], own) + _distance(points[-1], enemy)
		reverse = _distance(points[-1], own) + _distance(points[0], enemy)
		if reverse < forward:
			points.reverse()
		own_point = (float(own[0]), float(own[1]), 0)
		enemy_point = (float(enemy[0]), float(enemy[1]), 0)
		if _distance(points[0], own) > 1.0:
			points.insert(0, own_point)
		else:
			points[0] = own_point
		if _distance(points[-1], enemy) > 1.0:
			points.append(enemy_point)
		else:
			points[-1] = enemy_point
	except Exception:
		pass
	result['waypoints'] = tuple(points)
	return result


def _mapping_get(value, key, default=None):
	if not isinstance(value, dict):
		raise TypeError('Expected a plain mapping')
	return value.get(key, default)


def _attribute_or_key(value, key, default=None):
	if isinstance(value, dict):
		return value.get(key, default)
	return getattr(value, key, default)


def stable_seed(*parts):
	"""Return the same positive integer on Python 2 and Python 3."""
	text_parts = []
	for part in parts:
		try:
			text_parts.append(str(part))
		except Exception:
			text_parts.append('?')
	payload = '|'.join(text_parts).encode('utf-8')
	return int(hashlib.sha1(payload).hexdigest()[:8], 16) & 0x7fffffff


def make_personality(seed):
	"""Create only the retained route/setup preferences, not gunner skill."""
	rng = random.Random(int(seed))
	# Initial allocation has a stable seven-draw contract. Removing combat
	# fields must not reshuffle unrelated route choices or fitting distributions.
	draws = tuple(rng.random() for unused in range(7))
	traits = dict((name, 0.18 + draws[index] * 0.64)
		for name, index in (('aggression', 0), ('caution', 1),
		                    ('initiative', 4), ('adaptability', 5)))
	traits['aggression'] = max(0.05, min(0.95,
		traits['aggression'] + (0.5 - traits['caution']) * 0.22))
	traits['caution'] = max(0.05, min(0.95,
		traits['caution'] + (0.5 - traits['aggression']) * 0.12))
	traits['route_jitter'] = rng.uniform(-4.0, 4.0)
	return traits


def _tags_from_descriptor(descriptor):
	type_info = _attribute_or_key(descriptor, 'type', None)
	tags = _attribute_or_key(type_info, 'tags', ()) or ()
	try:
		return tuple(tags)
	except Exception:
		return ()


def _forward_speed(descriptor):
	physics = _attribute_or_key(descriptor, 'physics', {}) or {}
	limits = _mapping_get(physics, 'speedLimits', None)
	try:
		return abs(float(limits[0]))
	except Exception:
		return 0.0


def _primary_armor(component):
	if component is None:
		component = {}
	armor = _attribute_or_key(component, 'primaryArmor', 0.0)
	if isinstance(armor, (tuple, list)):
		return max([_number(item, 0.0) for item in armor] or [0.0])
	return _number(armor, 0.0)


def _middle_value(value, default=0.0):
	"""Return a representative value for scalar or min/max vehicle data."""
	if isinstance(value, (tuple, list)):
		values = [_number(item, default) for item in value]
		if values:
			return sum(values) / float(len(values))
	return _number(value, default)


def _shell_profiles(descriptor):
	"""Extract the small shell summary needed by the tactical planner."""
	gun = _attribute_or_key(descriptor, 'gun', {})
	if gun is None:
		gun = {}
	shots = _attribute_or_key(gun, 'shots', ()) or ()
	result = []
	try:
		iterator = enumerate(shots)
	except Exception:
		iterator = ()
	for index, shot in iterator:
		shell = _attribute_or_key(shot, 'shell', {})
		if shell is None:
			shell = {}
		kind = _attribute_or_key(shell, 'kind', '') or ''
		result.append({
			'index': int(index),
			'kind': str(kind),
			'name': _attribute_or_key(shell, 'name', ''),
			'penetration': _middle_value(
				_attribute_or_key(shell, 'piercingPower', 0.0), 0.0),
			'damage': _middle_value(
				_attribute_or_key(shell, 'damage', 0.0), 0.0),
			'speed': _number(
				_attribute_or_key(shot, 'speed', 0.0), 0.0),
		})
	return tuple(result)


def build_vehicle_profile(descriptor):
	"""Derive tactical roles from class tags plus available vehicle stats."""
	tags = _tags_from_descriptor(descriptor)
	class_tag = 'mediumTank'
	for candidate in ('heavyTank', 'mediumTank', 'lightTank', 'AT-SPG', 'SPG'):
		if candidate in tags:
			class_tag = candidate
			break

	role_defaults = {
		'heavyTank': {'brawler': 0.92, 'support': 0.55, 'flanker': 0.18,
		              'sniper': 0.20, 'scout': 0.05, 'artillery': 0.00},
		'mediumTank': {'brawler': 0.46, 'support': 0.76, 'flanker': 0.86,
		               'sniper': 0.48, 'scout': 0.42, 'artillery': 0.00},
		'lightTank': {'brawler': 0.10, 'support': 0.45, 'flanker': 0.72,
		              'sniper': 0.28, 'scout': 0.96, 'artillery': 0.00},
		'AT-SPG': {'brawler': 0.32, 'support': 0.78, 'flanker': 0.18,
		           'sniper': 0.92, 'scout': 0.08, 'artillery': 0.00},
		'SPG': {'brawler': 0.00, 'support': 0.10, 'flanker': 0.00,
		        'sniper': 0.16, 'scout': 0.00, 'artillery': 1.00},
	}
	roles = dict(role_defaults[class_tag])
	speed = _forward_speed(descriptor)
	hull = _attribute_or_key(descriptor, 'hull', {})
	turret = _attribute_or_key(descriptor, 'turret', {})
	armor = max(_primary_armor(hull), _primary_armor(turret))

	if speed >= 15.0:
		roles['flanker'] = min(1.0, roles['flanker'] + 0.12)
		roles['scout'] = min(1.0, roles['scout'] + 0.08)
	elif speed and speed < 9.0:
		roles['flanker'] = max(0.0, roles['flanker'] - 0.16)
	# All TDs share the sniper policy. Armour remains physical/profile data,
	# but does not turn an armoured TD into a short-range tactical subtype.
	if armor >= 120.0 and class_tag != 'AT-SPG':
		roles['brawler'] = min(1.0, roles['brawler'] + 0.18)
		roles['sniper'] = max(0.0, roles['sniper'] - 0.08)

	desired_ranges = {
		'heavyTank': (72.0, 260.0),
		'mediumTank': (135.0, 340.0),
		'lightTank': (175.0, 320.0),
		'AT-SPG': (255.0, 450.0),
		# The client proves a real shell trajectory before an SPG is reported
		# shootable.  These ranges therefore describe its battery role rather
		# than the old temporary 120 m direct-fire fallback.
		'SPG': (650.0, 1250.0),
	}
	desired_range, fire_range = desired_ranges[class_tag]

	dominant = 'support'
	dominant_score = -1.0
	for role_name, role_score in roles.items():
		if role_score > dominant_score:
			dominant = role_name
			dominant_score = role_score

	type_info = _attribute_or_key(descriptor, 'type', None)
	vehicle_name = _attribute_or_key(type_info, 'name', class_tag)
	from gui.mods.offline_lan_0922 import bot_fittings
	fitting = bot_fittings.context(descriptor)
	bot_tier = fitting['wire'].get('tier') if fitting is not None else None
	return {
		'bot_tier': bot_tier,
		'class_tag': class_tag,
		'vehicle_name': str(vehicle_name or class_tag),
		'roles': roles,
		'dominant_role': dominant,
		'desired_range': desired_range,
		'fire_range': fire_range,
		'speed': speed,
		'armor': armor,
		'burst_size': int((_attribute_or_key(_attribute_or_key(descriptor, 'gun', {}), 'burst', (1,)) or (1,))[0]),
		'clip_size': int((_attribute_or_key(_attribute_or_key(descriptor, 'gun', {}), 'clip', (1,)) or (1,))[0]),
		'gun_name': str(_attribute_or_key(
			_attribute_or_key(descriptor, 'gun', {}), 'name', '')),
		'shells': _shell_profiles(descriptor),
	}


def _distance_2d(first, second):
	dx = _number(first[0]) - _number(second[0])
	dz = _number(first[2]) - _number(second[2])
	return math.sqrt(dx * dx + dz * dz)


def _map_data_with_baked_routes(map_data, baked_routes):
	"""Combine current strategy with graph-validated locomotion waypoints."""
	if map_data is None or not isinstance(baked_routes, dict):
		return map_data
	result = dict(map_data)
	routes = {}
	for team in (1, 2):
		converted = []
		strategy_routes = dict(
			(route.get('id'), route) for route in
			map_data.get('routes', {}).get(team, ()) or ())
		values = baked_routes.get(str(team), baked_routes.get(team, ())) or ()
		for raw in values:
			if not isinstance(raw, dict):
				continue
			waypoints = []
			for point in raw.get('waypoints', ()) or ():
				try:
					waypoints.append((float(point[0]), float(point[1]),
					                  bool(point[2]) if len(point) > 2 else False))
				except Exception:
					continue
			if not waypoints:
				continue
			route = dict(raw)
			# Navigation graphs prove geometry. Strategy remains source data so a
			# map-guide update cannot be masked by metadata copied into an older
			# bake. Unknown custom route ids retain their baked fallback metadata.
			strategy = strategy_routes.get(raw.get('id'))
			if strategy is not None:
				for key in ('capacity', 'risk'):
					if key in strategy:
						route[key] = strategy[key]
				for key in ('role_weights', 'class_weights'):
					if key in strategy:
						route[key] = dict(strategy.get(key, {}) or {})
			route['role_weights'] = dict(
				route.get('role_weights', {}) or {})
			if 'class_weights' in route:
				route['class_weights'] = dict(
					route.get('class_weights', {}) or {})
			for tag in route.get('_editor_disabled_classes', ()):
				route.setdefault('class_weights', {})[tag] = 0.0
			route['waypoints'] = tuple(waypoints)
			converted.append(route)
		routes[team] = tuple(converted)
	if (not routes.get(1) or not routes.get(2)) and not baked_routes.get('_editor_allow_empty'):
		return map_data
	result['routes'] = routes
	# Baked routes already carry their team orientation and graph-validated
	# endpoints.  They must not be passed through the legacy static-base
	# orientation helper, which may insert two unvalidated points and exceed the
	# 16-waypoint LAN protocol boundary.
	result['_routes_are_baked'] = True
	return result
