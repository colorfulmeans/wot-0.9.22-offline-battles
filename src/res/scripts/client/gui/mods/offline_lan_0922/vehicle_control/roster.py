# -*- coding: utf-8 -*-
"""Battle setup data shared by native actor bindings.

Only roster/profile and initial route-catalog allocation live here. Regular
battles subsequently install the authored Default lottery in
bot_tactics_runtime.assign_initial_routes. There is no runtime contact memory,
waypoint cursor, target selector, order generator or controller fallback.
"""
from ..ai import maps as bot_ai_maps
from ..ai.planner import (stable_seed, build_vehicle_profile, make_personality,
    _map_data_with_baked_routes, _number, route_toward_enemy,
    CLASS_ROUTE_AFFINITY_WEIGHT, ARTILLERY_ROUTE_REPEAT_PENALTY)
from ..bot_tactics import DEFAULT_ROUTE_PRIORITY


class BattleRoster(object):
	"""Initial vehicle/catalog records; no contact or runtime decision API."""

	def __init__(self, map_name, battle_seed, bases=None, bounds=None,
	             baked_routes=None):
		self.map_name = bot_ai_maps.normalize_map_name(map_name)
		self.battle_seed = stable_seed(battle_seed, self.map_name)
		self.map_data = _map_data_with_baked_routes(
			bot_ai_maps.get_tactical_map(self.map_name), baked_routes)
		self._routes_are_baked = bool(
			self.map_data is not None and
			self.map_data.get('_routes_are_baked', False))
		self.bases = {}
		self.bounds = bounds
		if self.map_data is not None:
			self.bases.update(self.map_data.get('bases', {}))
			self.bounds = self.map_data.get('bounds', self.bounds)
		# The live arena definition is authoritative. Static tactical data only
		# supplies a fallback for tests or incomplete legacy DataSections.
		self.bases.update(dict(bases or {}))
		self.agents = {}
		self.route_usage = {}
		self.artillery_route_usage = {}

	def register(self, bot_id, team, descriptor, display_name='Bot'):
		return self.register_profile(
			bot_id, team, build_vehicle_profile(descriptor), display_name)

	def register_profile(self, bot_id, team, profile, display_name='Bot'):
		"""Register serialized profile data on either client or LAN server."""
		bot_id = int(bot_id)
		agent = self.agents.get(bot_id)
		if agent is not None:
			return agent
		profile = dict(profile or {})
		profile['roles'] = dict(profile.get('roles', {}) or {})
		profile['shells'] = tuple(profile.get('shells', ()) or ())
		seed = stable_seed(self.battle_seed, bot_id, display_name,
		                   profile.get('vehicle_name'))
		agent = {
			'id': bot_id,
			'team': int(team),
			'profile': profile,
			'personality': make_personality(seed),
			'seed': seed,
			'route': None,
		}
		agent['route'] = self._assign_route(agent)
		self.agents[bot_id] = agent
		return agent

	def _routes_for(self, team):
		if self.map_data is None:
			return ()
		return self.map_data.get('routes', {}).get(int(team), ()) or ()

	def _assign_route(self, agent):
		# Shared route geometry supplies a template; each class has three slots.
		routes = tuple(r for r in self._routes_for(agent['team'])
		               if not r.get('_editor_source') and
		               agent['profile'].get('class_tag') not in r.get('_editor_disabled_classes', ()))
		if not routes:
			return None
		profile = agent['profile']
		is_artillery = profile.get('class_tag') == 'SPG'
		# Capacities are a lane distribution contract, not a soft preference.
		# Without this gate a strongly specialised lineup can all choose the same
		# corridor even though the map advertises several viable approaches. SPGs
		# stage on a rear route anchor and therefore do not consume a front-line
		# lane slot.
		if not is_artillery:
			open_routes = []
			for route in routes:
				key = (agent['team'], route.get('id'), profile.get('class_tag'))
				capacity = 3
				if int(self.route_usage.get(key, 0)) < capacity:
					open_routes.append(route)
			if not open_routes:return None
			routes = tuple(open_routes)
		personality = agent['personality']
		best = None
		best_score = -1e18
		best_priority = -1
		for route in routes:
			role_weights = route.get('role_weights', {})
			risk = _number(route.get('risk', 0.5), 0.5)
			if is_artillery:
				# Prefer an explicit battery route, then the least exposed early
				# segment. The server chooses the exact graph-validated rear anchor.
				key = (agent['team'], route.get('id'))
				score = (_number(role_weights.get('artillery', 0.0)) *
				         100.0 - risk * 24.0 -
				         int(self.artillery_route_usage.get(key, 0)) *
				         ARTILLERY_ROUTE_REPEAT_PENALTY)
			else:
				score = 0.0
				for role_name, vehicle_score in profile['roles'].items():
					score += (vehicle_score *
					          _number(role_weights.get(role_name, 0.0)) * 18.0)
				class_weights = route.get('class_weights', {}) or {}
				score += (_number(class_weights.get(
					profile.get('class_tag'), 0.0)) *
					CLASS_ROUTE_AFFINITY_WEIGHT)
				score += risk * personality['aggression'] * 16.0
				score -= risk * personality['caution'] * 13.0
				score += personality['initiative'] * risk * 5.0
				score += personality['route_jitter']
				key = (agent['team'], route.get('id'), profile.get('class_tag'))
				used = int(self.route_usage.get(key, 0))
				capacity = 3
				score -= (float(used) / float(capacity)) * 28.0
				if used >= capacity:
					score -= 34.0
			priority = 0 if is_artillery else int((route.get('class_priorities') or {}).get(profile.get('class_tag'), DEFAULT_ROUTE_PRIORITY))
			if (priority, score) > (best_priority, best_score):
				best_priority = priority
				best_score = score
				best = route
		if best is not None:
			if is_artillery:
				key = (agent['team'], best.get('id'))
				self.artillery_route_usage[key] = int(
					self.artillery_route_usage.get(key, 0)) + 1
			else:
				key = (agent['team'], best.get('id'), profile.get('class_tag'))
				self.route_usage[key] = int(
					self.route_usage.get(key, 0)) + 1
			if self._routes_are_baked:
				result = dict(best)
				result['role_weights'] = dict(
					best.get('role_weights', {}) or {})
				if 'class_weights' in best:
					result['class_weights'] = dict(
						best.get('class_weights', {}) or {})
				result['waypoints'] = tuple(
					tuple(point) for point in
					best.get('waypoints', ()) or ())
				return result
			return route_toward_enemy(best, agent['team'], self.bases)
		return None
