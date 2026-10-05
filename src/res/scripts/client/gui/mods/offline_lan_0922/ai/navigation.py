# -*- coding: utf-8 -*-
"""Terrain-aware hierarchical navigation for offline/LAN bots.

Strategic map annotations decide where a vehicle should fight. This module
connects those sparse anchors with a low-resolution A* path, while the battle
driver remains responsible for short-range steering around moving vehicles.
The implementation is engine-free; the caller supplies terrain and collision
probes so it can be tested outside the legacy client.
"""

from gui.mods.offline_lan_0922.worker_diagnostics import (
    observed, count as combat_count)

import heapq
import math
from collections import deque

from gui.mods.offline_lan_0922.ai.driver import (
	FIRST_CANDIDATE_OFFSET, WAYPOINT_ARRIVAL_RADIUS)
from gui.mods.offline_lan_0922.vehicle_physics import SLIP_THRESHOLD_TAN


SQRT_TWO = math.sqrt(2.0)
BAKED_FATAL_HAZARDS = 1 | 2
# A reviewed ford cell whose scoped depth limit admits it beyond the baked
# graph's ordinary navigable water limit. It stays passable when no dry route
# exists, but carries a large traction/risk cost and the controlled-ford
# discipline below, because such a ford is a hand-authored single-file
# corridor. Ordinary navigable water carries no hazard bit: the baker and
# bot_runtime.BOT_WATER_AVOID_DEPTH share one line, and penalising every
# puddle below it queued whole teams on the dry bank of a 20 cm ditch. A
# graph baked before that alignment still flags its shallow apron, which
# only makes these consumers more conservative.
BAKED_SHALLOW_WATER = 4
# Cache compact answers, not crossed-cell lists, in the 32-bit worker.
MAX_BAKED_CORRIDOR_CACHE = 2048
# Share only visited cells, never expand the complete graph in the x86 worker.
MAX_BAKED_SEARCH_EDGE_CACHE = 2048
BAKED_SHALLOW_WATER_PENALTY = 4.0
BAKED_EDGE_CLEARANCE_WEIGHT = 0.20
BAKED_FORMAT_NAME = 'offline-lan-0922-navgraph'
BAKED_FORMAT_VERSION = 2
# A bot whose global search is still queued holds briefly so a job that
# finishes within a frame or two does not produce a pointless creep. Beyond
# that grace it makes bounded, fully probed progress instead of standing
# still: the room-wide expansion budget is shared, so "pending" can last
# many seconds in a full room and an unbounded hold reads as a parked tank.
PENDING_PROGRESS_SECONDS = 0.6
BLOCKED_STEP_REPLAN_SECONDS = 1.0
BLOCKED_STEP_REPLAN_VERDICTS = 4
BLOCKED_STEP_EDGE_TTL = 12.0
BLOCKED_STEP_EDGE_PENALTY = 240.0
# A destroyed vehicle is permanent static geometry, so a search must prefer a
# real detour over the lane it occupies. The penalty stays soft, in the same
# class as the other edge penalties, so a single-lane choke keeps a connected
# graph and ends in an honest hold instead of an unplannable map.
STATIC_HULL_EDGE_PENALTY = 240.0
# LocalDriver deliberately owns short-lived contact recovery, but displacement
# alone cannot detect a tank that rocks or circles without advancing its route.
# Track progress towards the navigator's stable local target and, after a long
# grace, make only this bot avoid the unproductive edge for one replan.
MACRO_PROGRESS_METRES = 0.20
MACRO_STALL_SECONDS = 12.0
MACRO_TARGET_CHANGE_METRES = 2.0
MACRO_EDGE_TTL = 4.0
MACRO_EDGE_PENALTY = 240.0
PENDING_INTENT_PROGRESS_METRES = 0.20
# A controlled ford admits LocalDriver's first avoidance branch, and no wider.
CONTROLLED_SHALLOW_YAW_WINDOW = FIRST_CANDIDATE_OFFSET + 0.03
# The commit side sees an integrated hull yaw rather than the candidate the
# planner chose, so it asks for a closing component instead of a cone. Half a
# unit of cosine is sixty degrees: it tolerates a lagging hull while still
# refusing one that is drifting sideways. The independent cell check below
# keeps either angular gate bound to the ford cells A* actually selected.
CONTROLLED_SHALLOW_COMMIT_CLOSING = 0.5

SEARCH_EXPANSIONS_PER_SECOND = 960.0
MAX_SEARCH_EXPANSIONS_PER_FRAME = 96
SEARCH_CATCH_UP_FRAMES = 4
# One catch-up frame may spend four nominal frames of credit, so the rate holds
# down to 4 Hz render callbacks and one stall cannot spend an unbounded backlog.
MAX_SEARCH_EXPANSIONS_PER_CATCH_UP_FRAME = (
	MAX_SEARCH_EXPANSIONS_PER_FRAME * SEARCH_CATCH_UP_FRAMES)
MAX_SEARCH_CREDIT = float(MAX_SEARCH_EXPANSIONS_PER_CATCH_UP_FRAME)


def _distance_2d(first, second):
	dx = float(first[0]) - float(second[0])
	dz = float(first[2]) - float(second[2])
	return math.sqrt(dx * dx + dz * dz)


def _hull_covers_cell(centre_x, centre_z, half_extent,
		hull_x, hull_z, sine, cosine, half_length, half_width):
	"""Return whether a hull box overlaps one axis-aligned graph cell square.

	Testing the cell square rather than its centre matters: a 3.4 metre wide
	hull can sit entirely between the centres of a four-metre bake and cover
	neither of them while still blocking both.
	"""
	dx = float(hull_x) - float(centre_x)
	dz = float(hull_z) - float(centre_z)
	# The two cell axes, then the two hull axes: forward is (sin, cos) and the
	# side is (cos, -sin), matching this module's atan2(x, z) yaw convention.
	if abs(dx) > (half_extent + abs(sine) * half_length +
			abs(cosine) * half_width):
		return False
	if abs(dz) > (half_extent + abs(cosine) * half_length +
			abs(sine) * half_width):
		return False
	cell_radius = half_extent * (abs(sine) + abs(cosine))
	if abs(dx * sine + dz * cosine) > half_length + cell_radius:
		return False
	if abs(dx * cosine - dz * sine) > half_width + cell_radius:
		return False
	return True


class TerrainGrid(object):
	"""Lazy terrain graph. Cells and edges are probed only when A* needs them."""

	_NEIGHBOURS = (
		(-1, -1, SQRT_TWO), (0, -1, 1.0), (1, -1, SQRT_TWO),
		(-1, 0, 1.0),                         (1, 0, 1.0),
		(-1, 1, SQRT_TWO),  (0, 1, 1.0),  (1, 1, SQRT_TWO),
	)
	_NEIGHBOUR_BITS = dict(((dx, dz), 1 << index)
		for index, (dx, dz, unused_length) in enumerate(_NEIGHBOURS))
	_LINK_COUNTS = tuple(bin(mask).count('1') for mask in range(256))

	def __init__(self, ground_probe, obstacle_probe=None, bounds=None,
			cell_size=18.0, max_grade_up=0.48, max_grade_down=0.38,
			baked_graph=None):
		self.ground_probe = ground_probe
		self.obstacle_probe = obstacle_probe
		self.bounds = bounds
		self.cell_size = max(1.0, float(cell_size))
		self.prebaked = False
		self._baked_origin = (0.0, 0.0)
		self._baked_width = 0
		self._baked_height = 0
		self._baked_heights = ()
		self._baked_links = ()
		self._baked_hazards = ()
		self._baked_max_grade = 0.30
		if baked_graph is not None:
			self._install_baked_graph(baked_graph)
		self.max_grade_up = float(max_grade_up)
		self.max_grade_down = float(max_grade_down)
		# Weighted A* deliberately favours forward progress over a perfectly
		# shortest coarse-grid route. Every returned edge is still terrain-probed;
		# only the amount of side exploration changes.
		self.heuristic_weight = 1.70
		self._ground_cache = {}
		self._corridor_cache = {}
		self._edge_cache = {}
		self._segment_cache = {}
		self._slope_corridor_cache = {}
		self._failed_edges = {}
		self._static_hull_edges = {}
		self._static_hull_key = None
		self._static_hull_padding = None
		self.static_hull_revision = 0
		self._native_review_cells = set()
		self._native_review_seeds = set()
		self._native_review_cache = {}
		self._native_review_edges = self._native_review_cache
		self._native_proof_revision = 0
		self._proof_deferred = False
		self._live_join_targets = set()
		self._native_review_pending = None

	def _install_baked_graph(self, graph):
		if (graph.get('format') != BAKED_FORMAT_NAME or
				int(graph.get('version', -1)) != BAKED_FORMAT_VERSION):
			raise ValueError('unsupported baked navigation graph')
		width = int(graph.get('width', 0))
		height = int(graph.get('height', 0))
		heights = graph.get('heights_mm') or ()
		links = graph.get('links') or ()
		hazards = graph.get('hazards')
		origin = graph.get('origin') or ()
		if (width <= 0 or height <= 0 or len(origin) != 2 or
				len(heights) != width * height or len(links) != width * height or
				(hazards is not None and len(hazards) != width * height)):
			raise ValueError('invalid baked navigation graph')
		self.cell_size = max(1.0, float(graph.get('cell_size', 0.0)))
		self._baked_origin = (float(origin[0]), float(origin[1]))
		self._baked_width = width
		self._baked_height = height
		self._baked_heights = heights
		self._baked_links = links
		self._baked_hazards = hazards if hazards is not None else (0,) * (width * height)
		bake = graph.get('bake') if isinstance(graph.get('bake'), dict) else {}
		self._baked_max_grade = max(0.05, float(bake.get('max_grade', 0.30)))
		self.bounds = tuple(graph.get('bounds') or self.bounds or ()) or None
		self.prebaked = True
		self._baked_corridor_cache = {}
		self._baked_corridor_order = deque()
		self._baked_search_edge_cache = {}
		self._baked_search_edge_order = deque()

	def cell_for(self, point):
		origin_x, origin_z = self._baked_origin if self.prebaked else (0.0, 0.0)
		return (int(math.floor((float(point[0]) - origin_x) /
		                       self.cell_size + 0.5)),
		        int(math.floor((float(point[2]) - origin_z) /
		                       self.cell_size + 0.5)))

	# Four grid orientations name the shape a hull actually has to drive:
	# the direction the baked cells run furthest in is the passage, and the
	# span across it is the room the hull has to turn in.
	_CORRIDOR_AXES = ((1, 0), (1, 1), (0, 1), (-1, 1))
	CORRIDOR_SPAN_CELLS = 5

	def local_corridor(self, point):
		"""Return ``(axis_yaw, width)`` for the baked space around ``point``.

		``width`` is the free span in metres across the longest local axis.
		Returns ``None`` outside baked support, where there is no measured
		passage and the caller must not invent one.
		"""
		if not self.prebaked:
			return None
		cell = self.cell_for(point)
		if self._baked_index(cell) is None:
			return None
		cached = self._corridor_cache.get(cell)
		if cached is not None:
			return cached
		spans = []
		for axis_x, axis_z in self._CORRIDOR_AXES:
			step = math.hypot(axis_x, axis_z) * self.cell_size
			cells = 1
			for sign in (1, -1):
				for reach in range(1, self.CORRIDOR_SPAN_CELLS + 1):
					probe = (cell[0] + axis_x * reach * sign,
					         cell[1] + axis_z * reach * sign)
					if self._baked_index(probe) is None:
						break
					cells += 1
			spans.append(cells * step)
		longest = max(range(len(spans)), key=lambda index: spans[index])
		axis_x, axis_z = self._CORRIDOR_AXES[longest]
		result = (math.atan2(float(axis_x), float(axis_z)),
		          spans[(longest + 2) % len(self._CORRIDOR_AXES)])
		self._corridor_cache[cell] = result
		return result

	def hull_pose_clear(self, point, yaw, half_length, half_width):
		"""Report whether one chassis rectangle stands on baked cells.

		A ray answers whether a direction is drivable; it cannot answer
		whether a hull already standing here may rotate, because the corners
		that a turn sweeps are metres away from every ray it casts. Sample
		the real rectangle instead, so an in-place turn inside a gateway is
		refused for the geometry that actually stops it.
		"""
		if not self.prebaked:
			return True
		half_length = max(0.5, float(half_length))
		half_width = max(0.3, float(half_width))
		forward = (math.sin(float(yaw)), math.cos(float(yaw)))
		side = (math.cos(float(yaw)), -math.sin(float(yaw)))
		for along in (-half_length, 0.0, half_length):
			for across in (-half_width, 0.0, half_width):
				sample = (float(point[0]) + forward[0] * along +
				          side[0] * across,
				          0.0,
				          float(point[2]) + forward[1] * along +
				          side[1] * across)
				if self._baked_index(self.cell_for(sample)) is None:
					return False
		return True

	def point_for(self, cell, height):
		origin_x, origin_z = self._baked_origin if self.prebaked else (0.0, 0.0)
		return (origin_x + cell[0] * self.cell_size, float(height),
		        origin_z + cell[1] * self.cell_size)

	def _baked_index(self, cell):
		if not self.prebaked:
			return None
		x, z = cell
		if x < 0 or x >= self._baked_width or z < 0 or z >= self._baked_height:
			return None
		index = z * self._baked_width + x
		if self._baked_heights[index] is None:
			return None
		return index

	def _baked_flat_index(self, cell):
		if not self.prebaked:
			return None
		x, z = cell
		if x < 0 or x >= self._baked_width or z < 0 or z >= self._baked_height:
			return None
		return z * self._baked_width + x

	def _baked_cell_height(self, cell):
		index = self._baked_index(cell)
		if index is None:
			return None
		return float(self._baked_heights[index]) / 1000.0

	def near_baked_navigation(self, point, max_radius=1):
		"""Return whether a realised pose remains in the baked safe corridor."""
		if not self.prebaked:
			return True
		return self._nearest_baked_cell(
			self.cell_for(point), max(0, int(max_radius))) is not None

	def baked_hazard_near(self, point, max_radius=0):
		'''Return whether a pose is in shipped water/cliff risk, not an obstacle.'''
		if not self.prebaked or not self._baked_hazards:
			return False
		cell = self.cell_for(point)
		radius = max(0, int(max_radius))
		for z in range(cell[1] - radius, cell[1] + radius + 1):
			for x in range(cell[0] - radius, cell[0] + radius + 1):
				index = self._baked_flat_index((x, z))
				if (index is not None and
						int(self._baked_hazards[index]) & BAKED_FATAL_HAZARDS):
					return True
		return False

	def _nearest_baked_cell(self, cell, max_radius):
		if self._baked_index(cell) is not None:
			return cell
		best = None
		best_distance = None
		for radius in range(1, max(0, int(max_radius)) + 1):
			for z in range(cell[1] - radius, cell[1] + radius + 1):
				for x in range(cell[0] - radius, cell[0] + radius + 1):
					if max(abs(x - cell[0]), abs(z - cell[1])) != radius:
						continue
					candidate = (x, z)
					if self._baked_index(candidate) is None:
						continue
					distance = ((x - cell[0]) ** 2 + (z - cell[1]) ** 2)
					if best_distance is None or distance < best_distance:
						best = candidate
						best_distance = distance
			if best is not None:
				return best
		return None

	def _inside(self, x, z):
		if self.bounds is None:
			return True
		try:
			return (float(self.bounds[0]) <= x <= float(self.bounds[2]) and
			        float(self.bounds[1]) <= z <= float(self.bounds[3]))
		except Exception:
			# Invalid bounds must not silently disable the map-edge guard.
			return False

	def clear_negative_cache(self):
		"""Retry cells that may have missed while distant chunks streamed in."""
		for cache in (self._ground_cache, self._edge_cache):
			for key, value in list(cache.items()):
				if value is None:
					cache.pop(key, None)
		for key, value in list(self._segment_cache.items()):
			if not value:
				self._segment_cache.pop(key, None)

	def _layer(self, hint_y):
		return int(math.floor(float(hint_y) / 8.0 + 0.5))

	def _point_key(self, point):
		return (int(math.floor(float(point[0]) * 0.5 + 0.5)),
		        int(math.floor(float(point[2]) * 0.5 + 0.5)),
		        self._layer(point[1]))

	def _edge_cells_for_segment(self, start, end):
		edges = self._edge_keys_for_segment(start, end)
		return edges[0] if edges else None

	def _edge_keys_for_segment(self, start, end):
		start_cell = self.cell_for(start)
		end_cell = self.cell_for(end)
		if start_cell == end_cell:
			return ()
		x, z = start_cell
		target_x, target_z = end_cell
		dx = abs(target_x - x)
		dz = abs(target_z - z)
		step_x = 1 if x < target_x else -1
		step_z = 1 if z < target_z else -1
		error = dx - dz
		cells = [start_cell]
		while x != target_x or z != target_z:
			double_error = error * 2
			if double_error > -dz:
				error -= dz
				x += step_x
			if double_error < dx:
				error += dx
				z += step_z
			cells.append((x, z))
		return tuple(tuple(sorted((cells[index], cells[index + 1])))
		             for index in range(len(cells) - 1))

	def prune_failed_edges(self, now):
		for key, value in list(self._failed_edges.items()):
			if float(now) >= value[0]:
				self._failed_edges.pop(key, None)
		if len(self._failed_edges) > 128:
			ordered = sorted(self._failed_edges.items(), key=lambda item: item[1][0])
			for key, unused in ordered[:len(self._failed_edges) - 128]:
				self._failed_edges.pop(key, None)

	def trim_caches(self):
		for cache, limit in ((self._ground_cache, 4096),
		                     (self._edge_cache, 4096),
		                     (self._segment_cache, 4096)):
			while len(cache) > limit:
				try:
					cache.popitem()
				except Exception:
					break

	def _failed_edge_timed_penalty(self, key, now):
		value = self._failed_edges.get(key)
		if value is None:
			return 0.0
		if float(now) >= value[0]:
			self._failed_edges.pop(key, None)
			return 0.0
		return value[1]

	def _failed_edge_penalty(self, first_cell, second_cell, now):
		key = tuple(sorted((first_cell, second_cell)))
		# A published wreck never expires on a timer: it stays marked until the
		# hull leaves the roster.
		return max(self._static_hull_edges.get(key, 0.0),
		           self._failed_edge_timed_penalty(key, now))

	def set_static_hulls(self, hulls, clearance=0.0):
		"""Publish the destroyed hulls that now occupy baked navigation cells.

		A wreck is physical geometry that can be pushed. Marking the graph
		edges it currently occupies routes later searches
		around it, refuses the direct shortcut, and drops the cached paths that
		used to run through it. The caller's chassis half-width expands the box
		for centreline searches; native hull sweeps still check the final motion.
		Unchanged occupied edges do not invalidate routes again.

		Returns whether the published set changed.
		"""
		key = tuple(sorted(
			(int(hull[0]), round(float(hull[1]), 2), round(float(hull[2]), 2),
			 round(float(hull[3]), 3), round(float(hull[4]), 2),
			 round(float(hull[5]), 2))
			for hull in hulls or ()))
		padding = round(max(0.0, float(clearance)), 3)
		if key == self._static_hull_key and padding == self._static_hull_padding:
			return False
		self._static_hull_key = key
		self._static_hull_padding = padding
		edges = {}
		half_extent = self.cell_size * 0.5
		for unused_id, x, z, yaw, half_length, half_width in key:
			# Paths describe hull centres. A centreline skimming a wreck still
			# collides unless the travelling hull's width is included.
			half_length = max(0.5, half_length) + padding
			half_width = max(0.3, half_width) + padding
			sine = math.sin(yaw)
			cosine = math.cos(yaw)
			radius = math.sqrt(half_length * half_length +
			                   half_width * half_width)
			first = self.cell_for((x - radius, 0.0, z - radius))
			last = self.cell_for((x + radius, 0.0, z + radius))
			for cell_z in range(first[1], last[1] + 1):
				for cell_x in range(first[0], last[0] + 1):
					centre = self.point_for((cell_x, cell_z), 0.0)
					if not _hull_covers_cell(
							centre[0], centre[2], half_extent,
							x, z, sine, cosine, half_length, half_width):
						continue
					for step_z in (-1, 0, 1):
						for step_x in (-1, 0, 1):
							if step_x == 0 and step_z == 0:
								continue
							edges[tuple(sorted((
								(cell_x, cell_z),
								(cell_x + step_x, cell_z + step_z))))] = (
									STATIC_HULL_EDGE_PENALTY)
		# A shove changes the exact pose every tick, often without changing
		# any occupied graph edge. Only changed planning geometry retires paths.
		if edges == self._static_hull_edges:
			return False
		self.static_hull_revision += 1
		self._static_hull_edges = edges
		return True

	def segment_penalty(self, start, end, now):
		if not self._failed_edges and not self._static_hull_edges:
			return 0.0
		penalty = 0.0
		for key in self._edge_keys_for_segment(start, end):
			penalty = max(penalty,
			              self._failed_edge_penalty(key[0], key[1], now))
		return penalty

	def _baked_segment_cells(self, start, end, require_height=True):
		"""Return graph cells crossed by a straight segment, start included."""
		if not self.prebaked:
			return ()
		start_cell = (self._nearest_baked_cell(self.cell_for(start), 2)
					  if require_height else self.cell_for(start))
		end_cell = self.cell_for(end)
		lookup = self._baked_index if require_height else self._baked_flat_index
		if start_cell is None or lookup(start_cell) is None or lookup(end_cell) is None:
			return ()
		x, z = start_cell
		target_x, target_z = end_cell
		cells = [(x, z)]
		dx = abs(target_x - x)
		dz = abs(target_z - z)
		step_x = 1 if x < target_x else -1
		step_z = 1 if z < target_z else -1
		error = dx - dz
		while x != target_x or z != target_z:
			double_error = error * 2
			if double_error > -dz:
				error -= dz
				x += step_x
			if double_error < dx:
				error += dx
				z += step_z
			cells.append((x, z))
		return tuple(cells)

	def _baked_corridor(self, start, end):
		"""Share immutable directed link/hazard answers for one grid corridor.

		Baked traversal depends on the endpoint cells, not each observer's
		sub-cell position. Keep world bounds and short-distance checks in their
		callers, and never cache live failed-edge penalties or native probes.
		"""
		key = (self.cell_for(start), self.cell_for(end))
		cached = self._baked_corridor_cache.get(key)
		if cached is not None:
			return cached
		cells = self._baked_segment_cells(start, end)
		clear = bool(cells)
		hazards = 0 if cells else None
		for offset in range(1, len(cells)):
			cell = cells[offset]
			index = self._baked_index(cell)
			if index is None:
				clear, hazards = False, None
				break
			hazards |= int(self._baked_hazards[index])
			if clear and self._baked_edge_height(cells[offset - 1], cell) is None:
				clear = False
		result = (clear, hazards)
		if len(self._baked_corridor_cache) >= MAX_BAKED_CORRIDOR_CACHE:
			self._baked_corridor_cache.pop(self._baked_corridor_order.popleft())
		self._baked_corridor_cache[key] = result
		self._baked_corridor_order.append(key)
		return result

	def segment_has_baked_hazard(self, start, end, hazard_mask):
		"""Check cells entered by a shortcut without trapping a tank at its start."""
		if not self.prebaked:
			return False
		unused_clear, hazards = self._baked_corridor(start, end)
		# The summary excludes the occupied start cell so a tank can leave a ford.
		return hazards is None or bool(hazards & int(hazard_mask))

	def segment_has_motion_hazard(self, start, end, hazard_mask):
		"""Read motion hazards even where erosion removed the routing height.

		Use the occupied start cell, without snapping it to a nearby route.
		Skipping that first cell still permits escape from an existing hazard.
		"""
		cells = self._baked_segment_cells(start, end, require_height=False)
		if not cells:
			return True
		for cell in cells[1:]:
			index = self._baked_flat_index(cell)
			if index is None or int(self._baked_hazards[index]) & hazard_mask:
				return True
		return False

	def baked_hazard_cells(self, start, end, hazard_mask):
		"""Return entered hazard cells, or ``None`` for an invalid corridor."""
		if (not self.prebaked or
				self._baked_index(self.cell_for(start)) is None):
			return None
		cells = self._baked_segment_cells(start, end)
		if not cells:
			return None
		result = []
		# Match segment_has_baked_hazard: the occupied start cell is not a new
		# entry, so a tank already in a ford remains able to leave it.
		for cell in cells[1:]:
			index = self._baked_index(cell)
			if index is None:
				return None
			if int(self._baked_hazards[index]) & int(hazard_mask):
				result.append(cell)
		return tuple(result)

	def point_has_baked_hazard(self, point, hazard_mask):
		"""Return whether one realised pose occupies a baked hazard cell."""
		if not self.prebaked:
			return False
		index = self._baked_flat_index(self.cell_for(point))
		return bool(index is not None and
		            int(self._baked_hazards[index]) & int(hazard_mask))

	def dry_segment_clear(self, start, end, now):
		"""Prove one preferred direct segment without entering shallow water.

		Shallow cells remain linked for the weighted A* fallback.  This predicate
		is only for raw goals, smoothing and reactive shortcuts which have not
		been selected by that planner.
		"""
		if (self.prebaked and self._baked_corridor(start, end)[1] is None and
				_distance_2d(start, end) <= 24.0 and
				(self._baked_cell_height(self.cell_for(start)) is None or
				 tuple(end) in self._live_join_targets)):
			return (self.segment_penalty(start, end, now) <= 0.0 and
				self._inside(float(end[0]), float(end[2])) and
				self._live_baked_egress_clear(start, end))
		return (self.segment_penalty(start, end, now) <= 0.0 and
		        not self.segment_has_baked_hazard(
		            start, end, BAKED_SHALLOW_WATER) and
		        self.segment_clear(start, end))

	def path_has_penalty(self, path, now):
		if not self._failed_edges:
			return False
		for index in range(len(path) - 1):
			for key in self._edge_keys_for_segment(path[index], path[index + 1]):
				if self._failed_edge_timed_penalty(key, now) > 0.0:
					return True
		return False

	def path_crosses_static_hull(self, path):
		"""Return whether a planned path runs through a published wreck.

		This is separate from the timed failure above because a wreck does not
		expire. A caller retires a path once, when the hull set that invalidates
		it is newer than the plan; re-planning with the same wrecks in place is
		the best answer available even where the route still has to pass one.
		"""
		if not self._static_hull_edges:
			return False
		for index in range(len(path) - 1):
			for key in self._edge_keys_for_segment(path[index], path[index + 1]):
				if key in self._static_hull_edges:
					return True
		return False

	def path_has_edge_penalty(self, path, edge_penalties):
		if not edge_penalties:
			return False
		for index in range(len(path) - 1):
			if any(edge in edge_penalties for edge in
					self._edge_keys_for_segment(path[index], path[index + 1])):
				return True
		return False

	def _ground(self, x, z, hint_y):
		if not self._inside(x, z):
			return None
		if self.prebaked:
			return self._baked_cell_height(self.cell_for((x, hint_y, z)))
		key = (int(math.floor(x * 10.0 + 0.5)),
		       int(math.floor(z * 10.0 + 0.5)), self._layer(hint_y))
		if key in self._ground_cache:
			return self._ground_cache[key]
		try:
			height = self.ground_probe(float(x), float(z), float(hint_y))
			if height is not None:
				height = float(height)
		except Exception:
			height = None
		self._ground_cache[key] = height
		return height

	def segment_clear(self, start, end):
		"""Check continuous support and drivable grade, not just both endpoints."""
		# In a prebaked graph, rounding can map a raw point just beyond the
		# authored rectangle back onto the last valid edge cell. The cell is safe;
		# the out-of-bounds world pose is not. A hull already outside may still use
		# an inward segment, so constrain the destination rather than the start.
		if not self._inside(float(end[0]), float(end[2])):
			return False
		distance = _distance_2d(start, end)
		if distance < 0.25:
			return True
		if self.prebaked:
			# Only short joins from an unsupported cell bypass erosion. Test the
			# actual hull pose and both shoulders every time; never modify the bake.
			if self._baked_cell_height(self.cell_for(start)) is None:
				return self._live_baked_egress_clear(start, end)
			if not self._baked_corridor(start, end)[0]:
				# A diagonal can exceed the old 0.38 bake grade even when both
				# orthogonal ways round the same supported square are legal.
				# Merge only a bounded, dry square corridor with a fresh native
				# ground/collision proof inside the exact client's full-grip range.
				if self._supported_slope_corridor(start, end):
					return self._native_segment_clear(start, end, SLIP_THRESHOLD_TAN)
				if (self._baked_cell_height(self.cell_for(end)) is None and
						_distance_2d(start, end) <= 24.0 and
						tuple(end) in self._live_join_targets):
					return self._live_baked_egress_clear(start, end)
				return False
			return (not self._needs_native_review(start, end) or
			        self._native_segment_clear(start, end))
		start_key = self._point_key(start)
		end_key = self._point_key(end)
		key = (start_key, end_key)
		cached = self._segment_cache.get(key)
		if cached is not None:
			return bool(cached)
		steps = max(1, int(math.ceil(distance / (self.cell_size * 0.42))))
		start_y = self._ground(float(start[0]), float(start[2]), float(start[1]))
		if start_y is None:
			start_y = float(start[1])
		previous = (float(start[0]), start_y, float(start[2]))
		grounded_start = previous
		clear = True
		for index in range(1, steps + 1):
			fraction = float(index) / float(steps)
			x = float(start[0]) + (float(end[0]) - float(start[0])) * fraction
			z = float(start[2]) + (float(end[2]) - float(start[2])) * fraction
			horizontal = math.sqrt((x - previous[0]) ** 2 + (z - previous[2]) ** 2)
			y = self._ground(x, z, previous[1])
			if y is None:
				clear = False
				break
			delta = y - previous[1]
			# Ordinary route segments must be controllable in reverse too. A
			# physically possible slide is not a valid tank-navigation shortcut.
			reversible_grade = min(self.max_grade_up, self.max_grade_down)
			if abs(delta) > horizontal * reversible_grade:
				clear = False
				break
			current = (x, y, z)
			previous = current
		if clear and self.obstacle_probe is not None:
			try:
				revision = self._native_proof_revision
				blocked = self.obstacle_probe(grounded_start, previous, 2.15)
				if blocked == 'deferred' or revision != self._native_proof_revision:
					self._proof_deferred = True
					return False
				if blocked:
					clear = False
			except Exception:
				# Collision-query failure is unknown terrain, not proof that a
				# several-ton vehicle has a clear corridor.
				clear = False
		self._segment_cache[key] = bool(clear)
		self._segment_cache[(end_key, start_key)] = bool(clear)
		return clear

	def review_native_corridor(self, start, end):
		'''Retire coarse-only clearance around an observed static refusal.

		The 4 m bake can miss a doorway or a thin wall. Recheck this local
		region with the native hull-width corridor, including A* and smoothing;
		never turn a refusal into a guessed map-wide obstacle rectangle.
		'''
		if not self.prebaked or self.obstacle_probe is None:
			return False
		distance = _distance_2d(start, end)
		if distance <= 0.0:
			return False
		fraction = min(1.0, self.cell_size * 8.0 / distance)
		end = tuple(start[i] + (end[i] - start[i]) * fraction for i in range(3))
		cells = self._baked_segment_cells(start, end, require_height=False)
		before = len(self._native_review_cells)
		# Include the local escape fan: otherwise A* simply crosses the same
		# wall one cell outside the reviewed strip and rejoins behind it.
		for x, z in cells:
			if (x, z) in self._native_review_seeds:
				continue
			self._native_review_seeds.add((x, z))
			for dx in range(-8, 9):
				for dz in range(-8, 9):
					cell = (x + dx, z + dz)
					if self._baked_flat_index(cell) is not None:
						self._native_review_cells.add(cell)
		return len(self._native_review_cells) != before

	def _needs_native_review(self, start, end):
		return bool(self._native_review_cells and any(
			cell in self._native_review_cells for cell in
			self._baked_segment_cells(start, end, require_height=False)))

	def _supported_slope_corridor(self, start, end):
		"""Admit only dry diagonal stairs whose two reversible sides exist.

		The native proof still owns height continuity and hull collision. This
		bounded geometry predicate never opens missing cardinal links or holes.
		"""
		if (not callable(self.ground_probe) or
				not callable(self.obstacle_probe) or
				_distance_2d(start, end) > self.cell_size * 12.0):
			return False
		if (self._baked_cell_height(self.cell_for(end)) is not None and
				self.point_has_baked_hazard(end, 2)):
			return False
		key = (self.cell_for(start), self.cell_for(end))
		if key in self._slope_corridor_cache:
			return self._slope_corridor_cache[key]
		cells = self._baked_segment_cells(start, end, require_height=False)
		clear = bool(cells)
		for cell in cells:
			index = self._baked_index(cell)
			if index is None or self._baked_hazards[index]:
				clear = False
				break
		if clear:
			for first, last in zip(cells, cells[1:]):
				if self._baked_edge_height(first, last) is not None:
					continue
				if first[0] == last[0] or first[1] == last[1]:
					clear = False
					break
				corners = ((last[0], first[1]), (first[0], last[1]))
				for corner in corners:
					index = self._baked_index(corner)
					if (index is None or self._baked_hazards[index] or
							self._baked_edge_height(first, corner) is None or
							self._baked_edge_height(corner, last) is None or
							self._baked_edge_height(last, corner) is None or
							self._baked_edge_height(corner, first) is None):
						clear = False
						break
				if not clear:
					break
				# Every corner gradient must retain native full longitudinal grip.
				heights = [self._baked_cell_height(c) for c in
				           (first, corners[0], corners[1], last)]
				for centre, side_a, side_b in ((0, 1, 2), (1, 0, 3),
				                               (2, 0, 3), (3, 1, 2)):
					grade_sq = sum((heights[side] - heights[centre]) ** 2
					               for side in (side_a, side_b)) / self.cell_size ** 2
					if grade_sq > SLIP_THRESHOLD_TAN ** 2:
						clear = False
						break
				if not clear:
					break
		if len(self._slope_corridor_cache) >= MAX_BAKED_CORRIDOR_CACHE:
			self._slope_corridor_cache.clear()
		self._slope_corridor_cache[key] = clear
		return clear

	def invalidate_native_review(self):
		"""Retire collision receipts after geometry changes, preserving terrain."""
		self._native_proof_revision += 1
		self._native_review_cache.clear()
		self._segment_cache.clear()
		self._edge_cache.clear()

	def _probe_obstacle(self, start, end, width, native_capability=None, evidence=None):
		if native_capability is None:
			return self.obstacle_probe(start, end, width)
		return self.obstacle_probe(start, end, width, native_capability, evidence)


	def _live_baked_egress_clear(self, start, end, native_capability=None,
			evidence=None):
		"""Prove a real exit from an eroded occupied cell, without snapping it.

		Baked corridors may start at the nearest supported graph cell. Their
		native edge review must not turn the missing height of the *occupied*
		cell into a collision: that would reject every possible exit before
		calling the native probe. Check the original continuous segment instead.
		This is planning only; the driver and full hull sweep still own motion.
		"""
		if (not callable(self.ground_probe) or
				not callable(self.obstacle_probe) or
				self.segment_has_motion_hazard(
					start, end, 1 | BAKED_SHALLOW_WATER)):
			combat_count('nav_live_egress_hazard_or_unavailable')
			return False
		if (self._baked_cell_height(self.cell_for(end)) is not None and
				self.point_has_baked_hazard(end, 2)):
			return False
		distance = _distance_2d(start, end)
		# Edge erosion is advisory only for this bounded native-proved join.
		# Water remains a veto. Never fill missing baked heights or erase a
		# footprint globally: a wall, cliff or unsupported shoulder must fail
		# the actual support/width proof below on every use.
		if distance > 24.0:
			combat_count('nav_live_egress_requires_local_join')
			return False
		steps = max(1, int(math.ceil(distance / (self.cell_size * 0.42))))
		grade = SLIP_THRESHOLD_TAN
		lateral_x = (float(end[2]) - float(start[2])) / max(distance, 0.001)
		lateral_z = (float(start[0]) - float(end[0])) / max(distance, 0.001)
		for side in (-2.15, 2.15):
			shoulder_start = (start[0] + lateral_x * side, start[1],
				start[2] + lateral_z * side)
			shoulder_end = (end[0] + lateral_x * side, end[1],
				end[2] + lateral_z * side)
			if self.segment_has_motion_hazard(
					shoulder_start, shoulder_end, 1 | BAKED_SHALLOW_WATER):
				return False
		try:
			start_y = self.ground_probe(
				float(start[0]), float(start[2]), float(start[1]))
			if (start_y is None or math.isnan(float(start_y)) or
					math.isinf(float(start_y))):
				combat_count('nav_live_egress_missing_support')
				return False
			previous = (float(start[0]), float(start_y), float(start[2]))
			grounded_start = previous
			for index in range(1, steps + 1):
				fraction = float(index) / float(steps)
				x = float(start[0]) + (float(end[0]) - float(start[0])) * fraction
				z = float(start[2]) + (float(end[2]) - float(start[2])) * fraction
				# Use the existing native, same-layer, water-aware support probe.
				# _ground() deliberately reads only the bake in this grid.
				y = self.ground_probe(x, z, previous[1])
				if y is None or math.isnan(float(y)) or math.isinf(float(y)):
					combat_count('nav_live_egress_missing_support')
					return False
				y = float(y)
				run = math.hypot(x - previous[0], z - previous[2])
				if abs(y - previous[1]) > run * grade:
					combat_count('nav_live_egress_grade')
					return False
				for side in (-2.15, 2.15):
					shoulder = self.ground_probe(
						x + lateral_x * side, z + lateral_z * side, y)
					if (shoulder is None or math.isnan(float(shoulder)) or
							math.isinf(float(shoulder)) or
							abs(float(shoulder) - y) > abs(side) * grade):
						combat_count('nav_live_egress_shoulder')
						return False
				previous = (x, y, z)
			# Sweep from the actual hull position, never the snapped cell centre.
			# Do not cache a live exit as an immutable graph edge: doors and
			# wrecks can change between requests.
			revision = self._native_proof_revision
			blocked = self._probe_obstacle(
				grounded_start, previous, 2.15, native_capability, evidence)
			if blocked == 'deferred' or revision != self._native_proof_revision:
				return None
			if blocked:
				combat_count('nav_live_egress_obstacle')
				return False
		except Exception:
			combat_count('nav_live_egress_probe_failed')
			return False
		combat_count('nav_live_egress_clear')
		return True

	def _native_segment_clear(self, start, end, slope_limit=None):
		'''Prove an affected local segment without using cached baked heights.'''
		distance = _distance_2d(start, end)
		# Long shortcuts must use the bounded A* edges through this region.
		if distance > self.cell_size * 12.0:
			return False
		key = (self._point_key(start), self._point_key(end))
		grade_limit = min(self.max_grade_up, self.max_grade_down)
		if slope_limit is not None:
			grade_limit = min(float(slope_limit), SLIP_THRESHOLD_TAN)
			key += (grade_limit,)
		if key in self._native_review_cache:
			return self._native_review_cache[key]
		pending = self._native_review_pending
		exact_key = (tuple(start), tuple(end))
		if pending is not None and exact_key in pending:
			self._proof_deferred = True
			return False
		step_size = self.cell_size * 0.42
		if slope_limit is not None:
			step_size = min(1.0, step_size)
		steps = max(1, int(math.ceil(distance / step_size)))
		previous = None
		first = None
		clear = True
		try:
			for index in range(steps + 1):
				fraction = float(index) / steps
				x = start[0] + (end[0] - start[0]) * fraction
				z = start[2] + (end[2] - start[2]) * fraction
				hint = previous[1] if previous is not None else start[1]
				y = self.ground_probe(x, z, hint)
				if y is None or math.isnan(float(y)) or math.isinf(float(y)):
					if pending is not None:
						pending.add(exact_key)
					self._proof_deferred = True
					return False
				point = (x, float(y), z)
				if previous is not None and abs(point[1] - previous[1]) > (
						_distance_2d(point, previous) *
						grade_limit):
					clear = False
					break
				if first is None:
					first = point
				previous = point
			if clear:
				revision = self._native_proof_revision
				blocked = self.obstacle_probe(first, previous, 2.15)
				if blocked == 'deferred' or revision != self._native_proof_revision:
					self._proof_deferred = True
					return False
				clear = not blocked
		except Exception:
			if pending is not None:
				pending.add(exact_key)
			return False
		if len(self._native_review_cache) >= 4096:
			self._native_review_cache.pop(next(iter(self._native_review_cache)))
		self._native_review_cache[key] = bool(clear)
		return bool(clear)

	@staticmethod
	def shortcut_preserves_climb_approach(path, start_index, end_index,
			minimum_grade=0.10, minimum_turn=0.30):
		"""Keep the setup point before a steep path changes direction.

		A collision-free chord is not always a controllable tank manoeuvre. If a
		climb begins immediately after a bend, skipping the bend point makes the
		hull meet the slope diagonally. Flat corners and straight climbs remain
		eligible for smoothing.
		"""
		if end_index - start_index < 2:
			return True
		for index in range(start_index + 1, end_index):
			before = path[index - 1]
			pivot = path[index]
			after = path[index + 1]
			out_dx = float(after[0]) - float(pivot[0])
			out_dz = float(after[2]) - float(pivot[2])
			out_run = math.sqrt(out_dx * out_dx + out_dz * out_dz)
			if out_run <= 0.1:
				continue
			grade = (float(after[1]) - float(pivot[1])) / out_run
			if grade <= float(minimum_grade):
				continue
			in_dx = float(pivot[0]) - float(before[0])
			in_dz = float(pivot[2]) - float(before[2])
			if abs(in_dx) + abs(in_dz) <= 0.1:
				continue
			incoming = math.atan2(in_dx, in_dz)
			outgoing = math.atan2(out_dx, out_dz)
			turn = outgoing - incoming
			while turn > math.pi:
				turn -= math.pi * 2.0
			while turn < -math.pi:
				turn += math.pi * 2.0
			if abs(turn) > float(minimum_turn):
				return False
		return True

	@staticmethod
	def live_shortcut_preserves_climb_approach(current, path, start_index,
			end_index):
		"""Apply the climb-approach guard from the hull's live position."""
		if end_index < start_index:
			return True
		live_path = ((float(current[0]), float(current[1]),
		              float(current[2])),) + tuple(
			path[start_index:end_index + 1])
		return TerrainGrid.shortcut_preserves_climb_approach(
			live_path, 0, len(live_path) - 1)

	def _edge(self, cell, height, next_cell):
		if self.prebaked:
			return self._baked_edge_height(cell, next_cell)
		key = (cell, next_cell, self._layer(height))
		if key in self._edge_cache:
			return self._edge_cache[key]
		start = self.point_for(cell, height)
		point = self.point_for(next_cell, height)
		x = point[0]
		z = point[2]
		end_y = self._ground(x, z, height)
		if end_y is None:
			result = None
		else:
			end = (x, end_y, z)
			result = end_y if self.segment_clear(start, end) else None
		if self._proof_deferred:
			return 'deferred'
		self._edge_cache[key] = result
		return result

	def _baked_edge_height(self, cell, next_cell):
		index = self._baked_index(cell)
		next_index = self._baked_index(next_cell)
		if index is None or next_index is None:
			return None
		dx = next_cell[0] - cell[0]
		dz = next_cell[1] - cell[1]
		bit = self._NEIGHBOUR_BITS.get((dx, dz), 0)
		if not (int(self._baked_links[index]) & bit):
			return None
		return float(self._baked_heights[next_index]) / 1000.0

	def _baked_neighbours(self, cell):
		"""Read one cell's immutable link mask once per A* expansion."""
		index = self._baked_index(cell)
		if index is None:
			return
		mask = int(self._baked_links[index])
		for direction, (dx, dz, length) in enumerate(self._NEIGHBOURS):
			if not (mask & (1 << direction)):
				continue
			next_cell = (cell[0] + dx, cell[1] + dz)
			next_index = self._baked_index(next_cell)
			if next_index is not None:
				yield (dx, dz, length, next_cell,
				       float(self._baked_heights[next_index]) / 1000.0)

	def _baked_link_count(self, cell):
		"""Return the number of independently baked exits from one safe cell."""
		index = self._baked_index(cell)
		if index is None:
			return 0
		mask = int(self._baked_links[index]) & 0xff
		return self._LINK_COUNTS[mask]

	def _baked_search_edges(self, cell):
		"""Share immutable directed-edge inputs across this map's Bot searches.

		Eligible terrain carries distance cost without a slope comfort surcharge.
		Wrecks, expiring failures, per-Bot vetoes and avoid points
		are live search inputs and never enter this cache.
		"""
		cached = self._baked_search_edge_cache.get(cell)
		if cached is not None:
			combat_count('nav_baked_edges_reused')
			return cached
		combat_count('nav_baked_edges_built')
		edges = []
		for unused_dx, unused_dz, length_scale, next_cell, next_y in \
				self._baked_neighbours(cell):
			run = self.cell_size * length_scale
			edge_key = ((cell, next_cell) if cell < next_cell else
			            (next_cell, cell))
			edges.append((
				next_cell, next_y, run, 0.0,
				self._penalty(next_cell, None, False),
				self._penalty(next_cell, None, True), edge_key))
		cached = tuple(edges)
		self._baked_search_edge_cache[cell] = cached
		self._baked_search_edge_order.append(cell)
		while len(self._baked_search_edge_order) > MAX_BAKED_SEARCH_EDGE_CACHE:
			self._baked_search_edge_cache.pop(
				self._baked_search_edge_order.popleft(), None)
		return cached

	def _baked_clearance_penalty(self, cell):
		"""Prefer the middle of a proved corridor without inventing new links.

		Every baked link already includes the shipped vehicle-width, obstacle,
		water and grade checks.  A cell with exits on both sides therefore has
		more independently proved manoeuvring room than a cell along the edge.
		The small weight only breaks otherwise similar routes; an unavoidable
		one-cell passage remains usable because no link or hazard rule changes.
		"""
		if not self.prebaked:
			return 0.0
		missing = max(0, len(self._NEIGHBOURS) -
		              self._baked_link_count(cell))
		return (float(missing) * self.cell_size *
		        BAKED_EDGE_CLEARANCE_WEIGHT)

	def _baked_clearance_exposure(self, path):
		"""Return mean missing-link exposure along a realised path chord."""
		if not self.prebaked or not path:
			return 0.0
		cells = []
		if len(path) == 1:
			cell = self._nearest_baked_cell(self.cell_for(path[0]), 2)
			if cell is None:
				return None
			cells.append(cell)
		else:
			for start, end in zip(path, path[1:]):
				segment = self._baked_segment_cells(start, end)
				if not segment:
					return None
				if cells and cells[-1] == segment[0]:
					segment = segment[1:]
				cells.extend(segment)
		if not cells:
			return None
		missing = sum(len(self._NEIGHBOURS) -
		              self._baked_link_count(cell) for cell in cells)
		return float(missing) / float(len(cells))

	def shortcut_preserves_baked_clearance(self, path, start_index, end_index,
			maximum_exposure_increase=0.25):
		"""Do not smooth a centred proved path back onto a corridor edge."""
		if not self.prebaked or end_index - start_index < 2:
			return True
		original = self._baked_clearance_exposure(
			path[start_index:end_index + 1])
		shortcut = self._baked_clearance_exposure(
			(path[start_index], path[end_index]))
		if original is None or shortcut is None:
			return False
		return shortcut <= original + float(maximum_exposure_increase)

	def _penalty(self, cell, avoid_points, prefer_clearance=False):
		penalty = (self._baked_clearance_penalty(cell)
		           if prefer_clearance else 0.0)
		if self.prebaked:
			index = self._baked_index(cell)
			if (index is not None and
					int(self._baked_hazards[index]) & BAKED_SHALLOW_WATER):
				# Preserve a small traction preference for dry ground without
				# turning an easy ford into a strategic detour.
				penalty += self.cell_size * BAKED_SHALLOW_WATER_PENALTY
		if not avoid_points:
			return penalty
		point = self.point_for(cell, 0.0)
		x = point[0]
		z = point[2]
		for point in avoid_points:
			dx = x - float(point[0])
			dz = z - float(point[2])
			distance = math.sqrt(dx * dx + dz * dz)
			if distance < self.cell_size * 1.5:
				penalty += (self.cell_size * 1.5 - distance) * 3.0
		return penalty

	def safe_local_target(self, current, goal, now, avoid_points=None,
			side_preference=1.0, edge_penalties=None,
			minimum_offset=0.0, diagnostic=None):
		"""Choose one short, fully probed detour when the global search fails.

		This is deliberately not a direct-to-goal fallback. Every candidate must
		have supported ground, a safe grade, no deep water, no static collision and
		no remembered failed edge. Returning ``None`` means the only safe action is
		to stop and retry the global planner later.
		"""
		if diagnostic is not None:
			diagnostic.clear()
			diagnostic.update(at=float(now), current=tuple(current), goal=tuple(goal),
				attempted=0, missing_ground=0, failed_edge=0, shallow_or_unknown=0,
				corridor_rejected=0, private_edge=0, accepted=0, selected=None)
		dx = float(goal[0]) - float(current[0])
		dz = float(goal[2]) - float(current[2])
		if abs(dx) + abs(dz) < 0.1:
			return None
		desired_yaw = math.atan2(dx, dz)
		if self.prebaked and self._baked_cell_height(self.cell_for(current)) is None:
			cell = self.cell_for(current)
			candidates = []
			for oz in range(-2, 3):
				for ox in range(-2, 3):
					key = (cell[0] + ox, cell[1] + oz)
					y = self._baked_cell_height(key)
					if y is not None:
						point = self.point_for(key, y)
						if _distance_2d(current, point) > WAYPOINT_ARRIVAL_RADIUS:
							candidates.append((_distance_2d(current, point), point))
			# At most one nearby candidate receives a full native query per decision.
			for unused_distance, point in sorted(candidates)[:1]:
				candidate_yaw = math.atan2(point[0] - current[0], point[2] - current[2])
				delta = (candidate_yaw - desired_yaw + math.pi) % (2.0 * math.pi) - math.pi
				if abs(delta) < max(0.0, float(minimum_offset)):
					continue
				if (not self.path_has_edge_penalty((current, point), edge_penalties) and
						self.dry_segment_clear(current, point, now)):
					return point
		side = 1.0 if float(side_preference) >= 0.0 else -1.0
		offsets = (0.0, side * 0.45, -side * 0.45,
		           side * 0.85, -side * 0.85,
		           side * 1.30, -side * 1.30,
		           side * 1.75, -side * 1.75)
		distances = (self.cell_size * 0.78, self.cell_size * 0.52)
		best = None
		native_candidates = 0
		for distance in distances:
			for offset in offsets:
				if abs(offset) < max(0.0, float(minimum_offset)):
					continue
				yaw = desired_yaw + offset
				x = float(current[0]) + math.sin(yaw) * distance
				z = float(current[2]) + math.cos(yaw) * distance
				if diagnostic is not None:
					diagnostic['attempted'] += 1
				y = self._ground(x, z, float(current[1]))
				if y is None:
					# A streaming/eroded cell is unknown, not automatically a wall.
					# Prove a short actual-pose step without publishing graph terrain.
					if (self.prebaked and native_candidates < 3 and
							callable(self.obstacle_probe)):
						native_candidates += 1
						candidate = (x, float(current[1]), z)
						if (not self.path_has_edge_penalty((current, candidate), edge_penalties) and
								self._inside(x, z) and
								self._live_baked_egress_clear(current, candidate)):
							if len(self._live_join_targets) >= 64:
								self._live_join_targets.pop()
							self._live_join_targets.add(candidate)
							return candidate
					if diagnostic is not None:
						diagnostic['missing_ground'] += 1
					continue
				candidate = (x, y, z)
				# Preserve the predicate order and query count while retaining
				# the first rejection. These are receipts, never extra probes.
				reason = None
				if self.segment_penalty(current, candidate, now) > 0.0:
					reason = 'failed_edge'
				elif self.segment_has_baked_hazard(current, candidate, BAKED_SHALLOW_WATER):
					reason = 'shallow_or_unknown'
				elif not self.segment_clear(current, candidate):
					reason = 'corridor_rejected'
				if reason is not None:
					if diagnostic is not None:
						diagnostic[reason] += 1
					continue
				if (edge_penalties and any(
						edge in edge_penalties
						for edge in self._edge_keys_for_segment(
							current, candidate))):
					if diagnostic is not None:
						diagnostic['private_edge'] += 1
					continue
				if diagnostic is not None:
					diagnostic['accepted'] += 1
				cell = self.cell_for(candidate)
				score = (_distance_2d(candidate, goal) + abs(offset) * 3.5 +
					         self._penalty(cell, avoid_points, False) * 2.0)
				value = (score, abs(offset), candidate)
				if best is None or value[:2] < best[:2]:
					best = value
		selected = best[2] if best is not None else None
		if diagnostic is not None:
			diagnostic['selected'] = selected
		return selected

	def plan(self, start, goal, avoid_points=None, max_expansions=1600, now=0.0,
			prefer_clearance=True, edge_penalties=None,
			hard_edge_penalties=None):
		"""Return a supported path synchronously (mainly for tests/tools)."""
		search = self.begin_plan(
			start, goal, avoid_points, max_expansions, now, prefer_clearance,
			edge_penalties, hard_edge_penalties)
		while not search.done:
			search.step(256)
			if search.progress.get('deferred'):
				return None
		return None if search.progress.get('deferred') else search.result

	def begin_plan(self, start, goal, avoid_points=None, max_expansions=1600,
			now=0.0, prefer_clearance=False, edge_penalties=None,
			hard_edge_penalties=None, route_corridor=None):
		progress = {}
		return _TerrainSearch(self._plan_steps(
			start, goal, avoid_points, max_expansions, now,
			bool(prefer_clearance), edge_penalties, hard_edge_penalties,
			route_corridor, progress),
			self.static_hull_revision, progress)

	def _plan_steps(self, start, goal, avoid_points, max_expansions, now,
			prefer_clearance, edge_penalties, hard_edge_penalties,
			route_corridor=None, progress=None):
		if route_corridor is not None:
			first, last = route_corridor
			corridor_dx = last[0] - first[0]
			corridor_dz = last[2] - first[2]
			length_sq = corridor_dx * corridor_dx + corridor_dz * corridor_dz
			width_sq = (self.cell_size * 2.0) ** 2
		start_cell = self.cell_for(start)
		goal_cell = self.cell_for(goal)
		if self.prebaked:
			# The server advances a tactical waypoint at 13 metres. Keep snapping
			# within three four-metre cells so A* can never stop outside that radius.
			start_cell = self._nearest_baked_cell(start_cell, 3)
			goal_cell = self._nearest_baked_cell(goal_cell, 3)
			if start_cell is None or goal_cell is None:
				yield ()
				return
			start_y = self._baked_cell_height(start_cell)
		else:
			start_y = self._ground(float(start[0]), float(start[2]), float(start[1]))
			if start_y is None:
				start_y = float(start[1])
		frontier = []
		sequence = 0
		heapq.heappush(frontier, (0.0, sequence, start_cell, 0.0))
		came_from = {}
		cost_so_far = {start_cell: 0.0}
		heights = {start_cell: start_y}
		reached = None
		closest = start_cell
		closest_distance = math.sqrt(
			(start_cell[0] - goal_cell[0]) ** 2 +
			(start_cell[1] - goal_cell[1]) ** 2)
		expansions = 0
		while frontier and expansions < int(max_expansions):
			_unused_priority, _unused_sequence, current, queued_cost = heapq.heappop(frontier)
			# A better route may have reached this cell after an older heap entry
			# was queued. Expanding stale entries repeatedly exhausted the bounded
			# search on risk-weighted maps even though every destination was linked.
			if queued_cost != cost_so_far.get(current):
				continue
			expansions += 1
			combat_count('nav_astar_expansions')
			goal_distance = math.sqrt(
				(current[0] - goal_cell[0]) ** 2 +
				(current[1] - goal_cell[1]) ** 2)
			if goal_distance < closest_distance:
				closest = current
				closest_distance = goal_distance
			if current == goal_cell:
				reached = current
				break
			current_y = heights[current]
			if self.prebaked:
				neighbours = self._baked_search_edges(current)
			else:
				neighbours = self._NEIGHBOURS
			for edge in neighbours:
				if self.prebaked:
					(next_cell, next_y, run, unused_slope_cost,
					 plain_penalty, clearance_penalty, edge_key) = edge
					terrain_penalty = (clearance_penalty if prefer_clearance else
					                   plain_penalty)
				else:
					offset_x, offset_z, length_scale = edge
					next_cell = (current[0] + offset_x, current[1] + offset_z)
					self._proof_deferred = False
					next_y = self._edge(current, current_y, next_cell)
					while next_y == 'deferred':
						progress['deferred'] = True
						yield None
						self._proof_deferred = False
						next_y = self._edge(current, current_y, next_cell)
					progress.pop('deferred', None)
					if next_y is None:
						continue
					edge_key = tuple(sorted((current, next_cell)))
					if (hard_edge_penalties and
							edge_key in hard_edge_penalties):
						continue
					if offset_x and offset_z:
						# Do not squeeze diagonally across a blocked corner.
						if (self._edge(current, current_y,
						               (current[0] + offset_x, current[1])) is None or
						        self._edge(current, current_y,
						               (current[0], current[1] + offset_z)) is None):
							continue
					run = self.cell_size * length_scale
					terrain_penalty = 0.0
				if (hard_edge_penalties and
						edge_key in hard_edge_penalties):
					continue
				if avoid_points or not self.prebaked:
					terrain_penalty = self._penalty(
						next_cell, avoid_points, prefer_clearance)
				local_penalty = 0.0
				if edge_penalties:
					local_penalty = float(edge_penalties.get(edge_key, 0.0))
				failed_penalty = 0.0
				if self._failed_edges or self._static_hull_edges:
					failed_penalty = max(
						self._static_hull_edges.get(edge_key, 0.0),
						self._failed_edge_timed_penalty(edge_key, now))
				# Grade eligibility belongs to the graph/native edge check, not
				# a comfort surcharge that can turn a legal slope into a detour.
				new_cost = (cost_so_far[current] + run +
				            terrain_penalty + failed_penalty + local_penalty)
				if route_corridor is not None:
					# Authored legs express the desired corridor. Grade remains a
					# hard eligibility check; do not favour a flatter contour over
					# the user's legal descent. Deviation is a soft cost so a real
					# obstacle can still be bypassed without a second search.
					px, unused_y, pz = self.point_for(next_cell, next_y)
					fraction = (max(0.0, min(1.0,
						((px - first[0]) * corridor_dx +
						 (pz - first[2]) * corridor_dz) /
						length_sq)) if length_sq > 0.0 else 0.0)
					ox = px - first[0] - fraction * corridor_dx
					oz = pz - first[2] - fraction * corridor_dz
					new_cost += run * (ox * ox + oz * oz) / width_sq
				if next_cell not in cost_so_far or new_cost < cost_so_far[next_cell]:
					# An edge that cannot improve this search cannot enter its
					# result. Spend native queries only on admissible relaxations.
					if self.prebaked:
						start_point = self.point_for(current, current_y)
						end_point = self.point_for(next_cell, next_y)
						if self._needs_native_review(start_point, end_point):
							self._proof_deferred = False
							clear = self._native_segment_clear(start_point, end_point)
							while self._proof_deferred:
								progress['deferred'] = True
								yield None
								self._proof_deferred = False
								clear = self._native_segment_clear(start_point, end_point)
							progress.pop('deferred', None)
							if not clear:
								continue
					cost_so_far[next_cell] = new_cost
					came_from[next_cell] = current
					heights[next_cell] = next_y
					dx = next_cell[0] - goal_cell[0]
					dz = next_cell[1] - goal_cell[1]
					# A modest weighted heuristic keeps the old 32-bit client from
					# exploring a broad irrelevant front around long ridges.
					heuristic = (math.sqrt(dx * dx + dz * dz) * self.cell_size *
					             self.heuristic_weight)
					sequence += 1
					heapq.heappush(frontier,
					               (new_cost + heuristic, sequence, next_cell, new_cost))
			yield None
		if reached is None:
			if hard_edge_penalties and closest == start_cell:
				# A per-bot macro veto that leaves no forward progress is a real
				# failed route, not a sparse-anchor success at the start cell.
				yield ()
				return
			# Sparse strategic anchors are hand placed on a minimap. A point a few
			# metres inside a building footprint, cliff lip or water edge must not
			# invalidate an otherwise complete route. Use the nearest cell A* could
			# actually reach, but only within three coarse cells: a grossly wrong
			# anchor still fails instead of silently changing battle lanes.
			if closest_distance <= 3.0:
				reached = closest
			elif frontier and closest != start_cell:
				# The bounded search still has work, so return the safest progress it
				# has already proved instead of reporting a false hard failure. The next
				# request continues from that supported partial path.
				reached = closest
			else:
				yield ()
				return
		cells = [reached]
		while cells[-1] != start_cell:
			cells.append(came_from[cells[-1]])
		cells.reverse()
		if self.prebaked:
			path = [self.point_for(start_cell, start_y)]
		else:
			path = [(float(start[0]), start_y, float(start[2]))]
		for cell in cells[1:]:
			path.append(self.point_for(cell, heights[cell]))
		goal_y = self._ground(float(goal[0]), float(goal[2]), path[-1][1])
		goal_point = (float(goal[0]), goal_y if goal_y is not None else path[-1][1],
		              float(goal[2]))
		if (self.segment_clear(path[-1], goal_point) and
				not self.path_has_edge_penalty(
					(path[-1], goal_point), hard_edge_penalties)):
			path.append(goal_point)
		# Expose only the selected complete chain, never an exploration branch.
		progress['selected_path'] = tuple(path)
		progress['revision'] = int(progress.get('revision', 0)) + 1
		yield None
		yield self._smooth(
			tuple(path), now, prefer_clearance, hard_edge_penalties)

	@observed('nav.smooth')
	def _smooth(self, path, now=0.0, prefer_clearance=False,
			edge_penalties=None):
		if len(path) < 3:
			return path
		result = [path[0]]
		index = 0
		while index < len(path) - 1:
			furthest = min(len(path) - 1, index + 6)
			while furthest > index + 1:
				if ((not prefer_clearance or
					 self.shortcut_preserves_baked_clearance(
						 path, index, furthest)) and
						self.shortcut_preserves_climb_approach(
						path, index, furthest) and
						not (edge_penalties and any(
							edge in edge_penalties for edge in
							self._edge_keys_for_segment(
								path[index], path[furthest]))) and
						self.dry_segment_clear(
							path[index], path[furthest], now)):
					break
				furthest -= 1
			result.append(path[furthest])
			index = furthest
		return tuple(result)


class _TerrainSearch(object):
	"""Small resumable A* task so collision probes are spread across frames."""

	def __init__(self, generator, hull_revision, progress=None):
		self.progress = progress if progress is not None else {}
		self.steps = 0
		self.generator = generator
		self.hull_revision = hull_revision
		self.done = False
		self.result = None
		self.last_frame = None

	def proved_prefix(self, grid):
		return self.progress.get('selected_path', ()) if not self.done else ()


	def step(self, budget):
		if self.done:
			return True
		for _unused in range(max(1, int(budget))):
			try:
				value = next(self.generator)
				self.steps += 1
			except StopIteration:
				self.done = True
				self.result = ()
				break
			if self.progress.get('deferred'):
				break
			if value is not None:
				self.done = True
				self.result = value
				break
		return self.done


class TerrainNavigator(object):
	"""Shared strategic path cache plus per-bot path following and recovery."""

	def __init__(self, ground_probe, obstacle_probe=None, bounds=None,
			cell_size=18.0, baked_graph=None):
		self.grid = TerrainGrid(ground_probe, obstacle_probe, bounds, cell_size,
		                        baked_graph=baked_graph)
		self.paths = {}
		self.path_times = {}
		self.path_hull_revisions = {}
		self.searches = {}
		self.search_times = {}
		self.bot_states = {}
		self.bot_failed_edges = {}
		self.bot_macro_edges = {}
		self.bot_direct_progress = {}
		self.search_frame_time = None
		self.housekeeping_time = None
		self.search_next_key = None
		self.search_credit = 0.0
		self.search_frame_serial = 0
		self.search_processed_frame = -1
		self.search_frame_budget = MAX_SEARCH_EXPANSIONS_PER_FRAME
		self.search_frame_open = False
		self.search_auto_time = None
		# A bounded search returns its best fully-probed partial path. This keeps a
		# 29-bot room from waiting tens of seconds for 1600 expansions per job; the
		# continuation search starts after the bot reaches that safe endpoint.
		self.search_max_expansions = 128
		if self.grid.prebaked:
			self.search_max_expansions = 4096
		self.search_completed = 0
		self.search_failed = 0
		self.search_now = 0.0
		self.fallback_totals = {
			'pending': 0, 'safe_direct': 0,
			'safe_local': 0, 'reactive': 0}
		self.fallback_recovered = 0
		self.fallback_modes = {}

	def _set_fallback_mode(self, bot_id, mode):
		if mode is None or mode == 'safe_direct':
			# A real routed target ends the pending episode. A safe-local or
			# reactive step taken *while* a search is still queued must not,
			# or the hold grace would restart after every short step and the
			# bot would creep instead of driving.
			state = self.bot_states.get(int(bot_id))
			if state is not None:
				state.pop('pending_since', None)
		old_mode = self.fallback_modes.get(int(bot_id))
		if old_mode == mode:
			return
		if old_mode is not None and mode is None:
			self.fallback_recovered += 1
		if mode is None:
			self.fallback_modes.pop(int(bot_id), None)
		else:
			self.fallback_modes[int(bot_id)] = mode
			self.fallback_totals[mode] = self.fallback_totals.get(mode, 0) + 1

	def fallback_diagnostics(self, active_bot_ids=None, now=None):
		if active_bot_ids is not None:
			active_ids = set(int(value) for value in active_bot_ids)
			for bot_id in list(self.fallback_modes):
				if bot_id not in active_ids:
					self.fallback_modes.pop(bot_id, None)
		active = {
			'pending': 0, 'safe_direct': 0,
			'safe_local': 0, 'reactive': 0}
		for mode in self.fallback_modes.values():
			active[mode] = active.get(mode, 0) + 1
		return {
			'graph': {
				'source': 'baked' if self.grid.prebaked else 'runtime',
				'cell_mm': int(round(self.grid.cell_size * 1000.0)),
				'nodes': (sum(1 for value in self.grid._baked_heights
				              if value is not None) if self.grid.prebaked else 0),
			},
			'total': dict(self.fallback_totals),
			'active': active,
			'recovered': int(self.fallback_recovered),
			'search': {
				'pending': len(self.searches),
				'completed': int(self.search_completed),
				'failed': int(self.search_failed),
				'oldest_ms': int(max(0.0, self.search_now -
					min(self.search_times.values())) * 1000.0)
					if self.search_times else 0,
				'tick_age_ms': int(max(0.0, float(now) - self.search_now) * 1000.0)
					if now is not None else 0,
			},
			'blocked_step_replans': sum(
				int(state.get('blocked_step_replans', 0))
				for state in self.bot_states.values()),
			'macro_progress_replans': sum(
				int(state.get('macro_progress_replans', 0))
				for state in self.bot_states.values()) + sum(
				int(state.get('replans', 0))
				for state in self.bot_direct_progress.values()),
		}

	def invalidate_native_planning(self):
		"""Cancel receipts/jobs whose collision evidence belongs to old geometry."""
		self.grid.invalidate_native_review()
		for state in self.bot_states.values():
			self._clear_pending_prefix(state)
		self.searches.clear()
		self.search_times.clear()
		self.paths.clear()
		self.path_times.clear()
		self.path_hull_revisions.clear()


	@staticmethod
	def _clear_temporary_progress(state):
		for name in ('local_fallback_episode', 'temporary_visited_cells',
		             'temporary_visited_order', 'temporary_stalled'):
			state.pop(name, None)

	def _temporary_path_repeats(self, state, path, start=0):
		# Visited terrain is not forbidden. A proved prefix may retrace old
		# intermediate legs whenever its remaining chain reaches new terrain;
		# completed paths bypass this temporary-search check altogether.
		visited = state.get('temporary_visited_cells', ())
		return bool(state.get('temporary_stalled') and path and
			all(self.grid.cell_for(path[offset]) in visited
				for offset in range(start, len(path))))

	@staticmethod
	def _local_fallback_intent(goal, state):
		return (state.get('request_key'),
		        int(state.get('replan_generation', 0)), tuple(goal))

	def _local_fallback_passed(self, current, target, state):
		"""Consume a short leg crossed between decisions, within its local width.

		This only retires an old steering target. The next leg must still be
		proved from the actual hull pose, including support and native walls.
		"""
		origin = state.get('local_fallback_start')
		if origin is None:
			return False
		dx, dz = target[0] - origin[0], target[2] - origin[2]
		length = math.hypot(dx, dz)
		if length < 0.1:
			return False
		past_x, past_z = current[0] - target[0], current[2] - target[2]
		return bool(past_x * dx + past_z * dz >= 0.0 and
			abs(past_x * dz - past_z * dx) <= length * self.grid.cell_size)

	def _retained_local_fallback(self, bot_id, current, goal, now, state):
		"""Keep one proved short waypoint until reached or physically retired.

		A failed A* result can remain cached across many driver decisions. Moving
		the local endpoint with the hull on every one makes its two-metre escape
		an endlessly moving target and changes steering at coarse-cell borders.
		The issued leg owns steering across asynchronous path completion.
		Only realised progress renews its finite lease, never a new path receipt.
		"""
		target = state.get('local_fallback_target')
		intent_matches = state.get('local_fallback_intent') == self._local_fallback_intent(goal, state)
		if (target is not None and intent_matches and
				(_distance_2d(current, target) <= WAYPOINT_ARRIVAL_RADIUS or
				 self._local_fallback_passed(current, target, state))):
			state['local_completed_target'] = (tuple(target), self._local_fallback_intent(goal, state))
		if (target is not None and state.get('last_target', target) == target and
				intent_matches and
				_distance_2d(current, target) > WAYPOINT_ARRIVAL_RADIUS and
				not self._local_fallback_passed(current, target, state) and
				not self._bot_edges_penalized(bot_id, current, target, now)):
			revision = self.grid._native_proof_revision
			clear = self.grid.dry_segment_clear(current, target, now)
			deferred = revision != self.grid._native_proof_revision
			if not clear and not deferred:
				state['local_target_end_reason'] = 'unsafe'
			else:
				remaining = _distance_2d(current, target)
				best = state.get('local_target_best_distance', remaining)
				if best - remaining >= MACRO_PROGRESS_METRES:
					state['local_target_best_distance'] = remaining
					state['local_target_progress_at'] = float(now)
				if float(now) - float(state.get('local_target_progress_at', now)) < MACRO_STALL_SECONDS:
					if deferred:
						# Unknown proof pauses motion without yielding ownership to
						# another cached path or recording a fictional obstacle.
						state['navigation_status'] = 'pending'
						return tuple(current)
					self._observe_macro_progress(bot_id, state, current, goal, now)
					state['last_target'] = tuple(target)
					return tuple(target)
				state['local_target_end_reason'] = 'timeout'
				state['local_target_retired'] = (tuple(target), float(now) + MACRO_STALL_SECONDS)
			self._observe_macro_progress(bot_id, state, current, goal, now)
		if target is not None and state.get('last_target') == target:
			# Pending-path bridging must not resurrect a consumed local point.
			state.pop('last_target', None)
		state.pop('local_fallback_target', None)
		state.pop('local_fallback_intent', None)
		state.pop('local_fallback_start', None)
		state.pop('local_target_progress_at', None)
		state.pop('local_target_best_distance', None)
		state.pop('local_target_best_heading', None)
		return None

	def _remember_local_fallback(self, target, goal, state, start=None, now=None):
		if state.get('local_fallback_target') != tuple(target):
			state.pop('local_target_best_heading', None)
			state['local_target_progress_at'] = float(now if now is not None else state.get('macro_progress_at', 0.0))
			state['local_target_best_distance'] = _distance_2d(start, target) if start is not None else float('inf')
		state['local_fallback_target'] = tuple(target)
		state['local_fallback_intent'] = self._local_fallback_intent(goal, state)
		state['local_fallback_episode'] = self._local_fallback_intent(goal, state)
		state['local_fallback_start'] = tuple(start) if start is not None else None

	def retained_local_target(self, bot_id, current, goal, path_key, now, movement_intent=True, yaw=None):
		"""Let the runtime's direct shortcut respect an already issued local leg."""
		state = self.bot_states.get(int(bot_id))
		if state is None:
			return None
		planned = state.get('planned_goal') or goal
		if (not movement_intent or state.get('request_path_key') != tuple(path_key) or
				_distance_2d(planned, goal) >= self.grid.cell_size * 2.0):
			state.pop('local_fallback_target', None)
			return None
		target = state.get('local_fallback_target')
		if target is not None and yaw is not None:
			origin = state.get('local_fallback_start') or current
			heading = math.atan2(target[0] - origin[0], target[2] - origin[2])
			error = abs((heading - float(yaw) + math.pi) % (2.0 * math.pi) - math.pi)
			best = state.get('local_target_best_heading')
			if best is None or best - error >= 0.02:
				state['local_target_best_heading'] = error
				if best is not None:
					state['local_target_progress_at'] = float(now)
		return self._retained_local_fallback(bot_id, current, planned, now, state)

	def remember_runtime_target(self, bot_id, current, goal, target, now):
		"""Publish the final proved bypass, rather than its pre-offset A* vertex."""
		state = self.bot_states.get(int(bot_id))
		if state is not None:
			self._remember_local_fallback(target, state.get('planned_goal') or goal, state, current, now)
			state['last_target'] = tuple(target)

	def _local_fallback_origin(self, current, goal, state):
		completed = state.get('local_completed_target')
		if (completed is not None and completed[1] == self._local_fallback_intent(goal, state) and
				_distance_2d(current, completed[0]) <= self.grid.cell_size):
			return completed[0]
		target = state.get('local_fallback_target')
		if (target is not None and state.get('last_target', target) == target and
				state.get('local_fallback_intent') == self._local_fallback_intent(goal, state) and
				_distance_2d(current, target) <= WAYPOINT_ARRIVAL_RADIUS):
			# Arrival consumes a waypoint within a radius, not at its exact
			# centre. Start the next leg at that fixed waypoint; regenerating a
			# two-metre fan at the hull every 0.58 m can keep rounding into the
			# same baked cell forever. The realised connector is proved below.
			return tuple(target)
		return tuple(current)

	def _new_local_fallback(self, bot_id, current, origin, goal, now,
			avoid_points, state):
		fallback = self.grid.safe_local_target(
			origin, goal, now, avoid_points,
			1.0 if (int(bot_id) % 2) else -1.0,
			self._active_planning_edge_penalties(bot_id, now),
			0.0, diagnostic=state.setdefault('local_fallback', {}))
		if fallback is not None and self._temporary_path_repeats(state, (fallback,)):
			return tuple(current)
		connector_clear = True
		if fallback is not None and origin != tuple(current):
			connector_clear = bool(
				not self._bot_edges_penalized(bot_id, current, fallback, now) and
				self.grid.dry_segment_clear(current, fallback, now))
			if connector_clear and self.grid.prebaked:
				# Centre-to-centre baked edge receipts cannot prove the diagonal
				# from an off-centre hull still inside the arrival disk.
				try:
					revision = self.grid._native_proof_revision
					blocked = self.grid._probe_obstacle(current, fallback, 2.15,
						state.get('native_capability'))
					connector_clear = not blocked and revision == self.grid._native_proof_revision
				except Exception:
					connector_clear = False
		if not connector_clear:
			state.pop('local_fallback_target', None)
			state.pop('local_fallback_intent', None)
			state.pop('local_fallback_start', None)
			# The next leg is not admissible from the realised hull pose. Hold
			# for this decision, then retry from the hull on the next one.
			return tuple(current)
		if fallback is not None:
			retired = state.get('local_target_retired')
			if retired is not None and float(now) < retired[1] and _distance_2d(fallback, retired[0]) <= WAYPOINT_ARRIVAL_RADIUS:
				return None
			self._remember_local_fallback(fallback, goal, state, current, now)
		return fallback

	@staticmethod
	def _clear_pending_prefix(state):
		if state.get('last_target') == state.get('pending_prefix_target'):
			state.pop('last_target', None)
		for name in ('pending_prefix', 'pending_prefix_search',
		             'pending_prefix_intent', 'pending_prefix_index',
		             'pending_prefix_revision', 'pending_prefix_target',
		             'retired_prefix'):
			state.pop(name, None)

	def _retire_pending_prefix(self, state):
		# Losing a connector is not permission to replay this tree's old legs.
		# Retain the issued boundary across the independent local escape. A
		# completed route or a different search may still require a backtrack.
		path = state.get('pending_prefix')
		receipt = state.get('retired_prefix')
		if receipt is None and path:
			index = min(int(state.get('pending_prefix_index', 0)), len(path) - 1)
			receipt = (state.get('pending_prefix_search'),
				state.get('pending_prefix_intent'), tuple(path[index]))
		self._clear_pending_prefix(state)
		if receipt is not None:
			state['retired_prefix'] = receipt

	def _pending_search_target(self, bot_id, current, goal, now, state,
			search_key, lookahead_distance):
		"""Follow a selected dry route while its smoothing pass is pending.

		Exploration itself exposes no path. Once the search connects to its
		destination, keep any issued leg stable until arrival or a real veto.
		Only the owner of the private search may consume its local connector.
		"""
		search = self.searches.get(search_key)
		native_capability = state.get('native_capability')
		intent = self._local_fallback_intent(goal, state)
		retired = state.get('retired_prefix')
		if retired is not None and (retired[0] is not search or retired[1] != intent):
			state.pop('retired_prefix', None)
			retired = None
		if (state.get('pending_prefix_search') is not search or
				state.get('pending_prefix_intent') != intent):
			if retired is None:
				self._clear_pending_prefix(state)
		if (search is None or search.done or
				self._path_owner(search_key[0]) != int(bot_id)):
			# Shared route trees begin at the authored route anchor. Until they
			# finish, an early prefix can still lie behind this consuming hull.
			# Only the owner of a live-position search may drive its partial tree.
			return None
		path = state.get('pending_prefix')
		index = int(state.get('pending_prefix_index', 0))
		reached = bool(path and
			_distance_2d(current, path[-1]) <= WAYPOINT_ARRIVAL_RADIUS)
		if path is None or reached:
			revision = search.progress.get('revision', 0)
			if revision != state.get('pending_prefix_revision'):
				candidate = search.proved_prefix(self.grid)
				minimum_index = 0
				if retired is not None:
					if not candidate or retired[2] not in candidate:
						return None
					minimum_index = candidate.index(retired[2]) + 1
					if minimum_index >= len(candidate):
						return None
				# A popped A* node is an explored branch, not a chosen route.
				# At an issued tip, only extend its admitted parent chain. The
				# next heap branch can join tens of metres behind the hull; using
				# its nearest node sent Object 244 back across the slope. Keep
				# this reached tip while the live search proves an onward leg or
				# finishes a route (which may legitimately require a backtrack).
				if not reached or (candidate and path[-1] in candidate):
					path = candidate
				state['pending_prefix_search'] = search
				state['pending_prefix_intent'] = intent
				state['pending_prefix_revision'] = revision
				state['pending_prefix'] = path or None
				if path:
					index = max(minimum_index, self._path_entry_index(
						bot_id, current, path, now))
					if ((index == 0 and _distance_2d(current, path[0]) >
							self.grid.cell_size * 2.0) or
							(index == len(path) - 1 and _distance_2d(current, path[index]) >
							 WAYPOINT_ARRIVAL_RADIUS)):
						# Local motion may already have passed this young tree. A
						# legal return segment is not a reason to revisit its root;
						# wait for a proved onward leg near the actual hull instead.
						state['pending_prefix'] = None
						if state.get('last_target') in (path[0],
								state.get('pending_prefix_target')):
							state.pop('last_target', None)
						return None
			if not path:
				return None
		if self._temporary_path_repeats(state, path, index):
			# Keep the healthy search and its frame budget. A later prefix with
			# an onward leg can replace this exhausted local excursion immediately.
			state['pending_prefix'] = None
			if state.get('last_target') == state.get('pending_prefix_target'):
				state.pop('last_target', None)
			return None
		# A pending search has not selected a complete ford route. Its prefix
		# may use only dry edges; full A* completion owns shallow-water grants.
		connector_clear = (False if self._bot_edges_penalized(
			bot_id, current, path[index], now) else
			self.grid.dry_segment_clear(current, path[index], now))
		if connector_clear is None:
			return tuple(current)
		if not connector_clear:
			state['pending_prefix_index'] = index
			self._retire_pending_prefix(state)
			return None
		while (index + 1 < len(path) and
				_distance_2d(current, path[index]) <= WAYPOINT_ARRIVAL_RADIUS and
				self._planned_next_segment_clear(
					current, path, index, now, bot_id)):
			index += 1
		index = self._lookahead_index(
			current, path, index, search_key[0], now, lookahead_distance, bot_id)
		target = tuple(path[index])
		if (index + 1 < len(path) and
				_distance_2d(current, target) <= WAYPOINT_ARRIVAL_RADIUS):
			# The next edge can become inadmissible after A* proved this prefix,
			# or be unreachable from the hull's realised arrival offset. Issuing
			# the reached point again makes the adapter wait forever and prevents
			# the fully checked local fallback below from finding another exit.
			# Retire only this consumer's prefix, retaining the healthy search.
			state['pending_prefix_index'] = index
			self._retire_pending_prefix(state)
			return None
		state['pending_prefix_index'] = index
		state['pending_prefix_target'] = target
		self._remember_local_fallback(target, goal, state, current, now)
		state.pop('retired_prefix', None)
		state['last_target'] = target
		state['local_fallback_episode'] = intent
		state.pop('controlled_shallow_target', None)
		state['navigation_status'] = 'pending'
		state['target_is_terminal'] = False
		self._set_fallback_mode(bot_id, 'pending')
		return target

	def _path_entry_index(self, bot_id, current, path, now):
		"""Attach to the forward end of the occupied leg, not its old vertex."""
		best = min(range(len(path)), key=lambda index: _distance_2d(current, path[index]))
		best_distance = _distance_2d(current, path[best])
		for index in range(len(path) - 1):
			first, second = path[index:index + 2]
			dx, dz = second[0] - first[0], second[2] - first[2]
			length_sq = dx * dx + dz * dz
			if length_sq < 0.01:
				continue
			along = ((current[0] - first[0]) * dx +
				         (current[2] - first[2]) * dz) / length_sq
			if not 0.0 < along < 1.0:
				continue
			distance = math.hypot(current[0] - first[0] - along * dx,
				current[2] - first[2] - along * dz)
			if (distance >= best_distance or
					distance > 24.0 or
					(distance > WAYPOINT_ARRIVAL_RADIUS and
					 _distance_2d(current, second) > 24.0) or
					self.grid.segment_has_baked_hazard(current, second, BAKED_SHALLOW_WATER) or
					self._bot_edges_penalized(bot_id, current, second, now)):
				continue
			if index == 0 and distance <= WAYPOINT_ARRIVAL_RADIUS:
				# A hull already occupying the first leg has consumed its source.
				# The vector back to an asynchronous search origin is not an
				# incoming climb approach. Preserve every later real setup bend.
				clear = (self.grid.live_shortcut_preserves_climb_approach(
					current, path, 0, 1) and
					self.grid.dry_segment_clear(current, second, now))
			else:
				clear = self._planned_current_segment_clear(
					current, path, index + 1, now)
			if not clear:
				continue
			best, best_distance = index + 1, distance
		if (best == 0 and len(path) > 1 and
				_distance_2d(current, path[0]) <= min(8.0, self.grid.cell_size * 2.0) and
				not self._bot_edges_penalized(bot_id, current, path[1], now) and
				not self.grid.segment_has_baked_hazard(current, path[1], BAKED_SHALLOW_WATER) and
				self._planned_current_segment_clear(
					current, path, 1, now)):
			# A small sideways drift at a source does not require another A*.
			# Enter its first proved leg directly; a genuinely displaced hull
			# instead gets the live join below, never a return to the source.
			best = 1
		return best

	@observed('nav.fallback')
	def _safe_fallback_target(self, bot_id, current, goal, now, avoid_points, state):
		origin = self._local_fallback_origin(current, goal, state)
		retained = self._retained_local_fallback(bot_id, current, goal, now, state)
		if retained is not None:
			return retained
		return self._new_local_fallback(bot_id, current, origin, goal, now, avoid_points, state)

	def _fallback_target(self, bot_id, current, goal, now, avoid_points, state,
			allow_safe_local=True):
		"""Keep moving without treating an unproved long segment as drivable.

		A fully probed short waypoint is preferred after a conclusive A* failure.
		If none exists (or the search is merely pending), an unvetoed strategic goal
		remains steering intent for LocalDriver. A Bot's own reported edge veto must
		hold instead: LocalDriver can otherwise drive the long goal straight back
		through the rejected edge before the next planner result arrives.
		"""
		# A fallback replaces the route decision, not the ford the planner already
		# selected. Drop that ford only once it stops being a reachable safe edge.
		ford = state.get('controlled_shallow_target')
		if ford is not None and (
				_distance_2d(current, ford) <= WAYPOINT_ARRIVAL_RADIUS or
				self._bot_edges_penalized(bot_id, current, ford, now) or
				self.grid.segment_has_baked_hazard(
					current, ford, BAKED_FATAL_HAZARDS) or
				not self.grid.segment_clear(current, ford)):
			state.pop('controlled_shallow_target', None)
		if allow_safe_local:
			fallback = self._safe_fallback_target(
				bot_id, current, goal, now, avoid_points, state)
			if fallback is not None:
				state['last_target'] = tuple(fallback)
				state['navigation_status'] = 'safe'
				state['target_is_terminal'] = bool(
					_distance_2d(fallback, goal) <= WAYPOINT_ARRIVAL_RADIUS)
				self._set_fallback_mode(bot_id, 'safe_local')
				return tuple(fallback)
		if self._bot_edges_penalized(bot_id, current, goal, now):
			state['last_target'] = tuple(current)
			state['navigation_status'] = 'blocked'
			state['target_is_terminal'] = False
			self._set_fallback_mode(bot_id, 'reactive')
			return tuple(current)
		state['last_target'] = tuple(goal)
		state['navigation_status'] = 'blocked'
		state['target_is_terminal'] = False
		self._set_fallback_mode(bot_id, 'reactive')
		return tuple(goal)

	@observed('nav.pending')
	def _pending_target(self, bot_id, current, goal, now, state,
			avoid_points=None, allow_last_target=True,
			immediate_safe_local=False):
		"""Continue a proved local edge, else make bounded probed progress.

		Returning the hull's own position is a complete stop: the driver reads it
		as arrival and the order adapter suppresses steering entirely, so nothing
		times the wait out and nothing recovers from it. A queued global search is
		not evidence that standing still is safe, only that the strategic route is
		not known yet, so after a short grace this returns the same fully probed
		short waypoint a conclusive search failure would use. Every candidate
		still needs supported ground, a safe grade, no deep water, no static
		collision and no remembered failed edge; ``None`` from that search still
		means the only safe action is to hold.
		"""
		search_key = state.get('path_key')
		if search_key not in self.searches:
			search_key = state.get('request_key')
		prefix = self._pending_search_target(bot_id, current, goal, now, state, search_key, None)
		if prefix is not None:
			return prefix
		last_target = state.get('last_target')
		if allow_last_target and last_target is not None:
			last_target = tuple(last_target)
			shallow = self.grid.segment_has_baked_hazard(
				current, last_target, BAKED_SHALLOW_WATER)
			controlled = state.get('controlled_shallow_target')
			if (self.grid.segment_penalty(current, last_target, now) <= 0.0 and
					not self._bot_edges_penalized(
						bot_id, current, last_target, now) and
					self.grid.segment_clear(current, last_target) and
					(not shallow or controlled == last_target) and
					_distance_2d(current, last_target) >
					WAYPOINT_ARRIVAL_RADIUS):
				state['navigation_status'] = 'pending'
				state['target_is_terminal'] = False
				self._set_fallback_mode(bot_id, 'pending')
				return last_target
		started = state.get('pending_since')
		if started is None:
			started = float(now)
			state['pending_since'] = started
		if (goal is not None and
				(immediate_safe_local or
				 float(now) - float(started) >= PENDING_PROGRESS_SECONDS)):
			fallback = self._safe_fallback_target(
				bot_id, current, goal, now, avoid_points, state)
			if fallback is not None:
				state['last_target'] = tuple(fallback)
				state['navigation_status'] = 'pending'
				state['target_is_terminal'] = False
				self._set_fallback_mode(bot_id, 'safe_local')
				return tuple(fallback)
		state['last_target'] = tuple(current)
		state['navigation_status'] = 'pending'
		state['target_is_terminal'] = False
		self._set_fallback_mode(bot_id, 'pending')
		return tuple(current)

	@staticmethod
	def _target_advances_new_intent(current, target, goal):
		"""Whether an old local target remains useful for a new request."""
		if target is None or goal is None:
			return False
		to_target_x = float(target[0]) - float(current[0])
		to_target_z = float(target[2]) - float(current[2])
		to_goal_x = float(goal[0]) - float(current[0])
		to_goal_z = float(goal[2]) - float(current[2])
		if (to_target_x * to_goal_x + to_target_z * to_goal_z) <= 0.0:
			return False
		return (_distance_2d(target, goal) +
		        PENDING_INTENT_PROGRESS_METRES < _distance_2d(current, goal))

	def _reset_macro_progress(self, state, current, target, now, kind='path'):
		state['macro_progress_at'] = float(now)
		state['macro_progress_kind'] = kind
		state['macro_progress_position'] = tuple(current)
		state['macro_progress_target'] = (
			tuple(target) if target is not None else None)
		state['macro_progress_path_key'] = state.get('path_key')
		state['macro_progress_index'] = int(state.get('index', 0))
		state['macro_progress_prefix_search'] = state.get('pending_prefix_search')
		state['macro_progress_prefix_index'] = state.get('pending_prefix_index')

	def observe_direct_target(self, bot_id, current, goal, path_key, now,
			movement_intent=True):
		"""Return a bounded local escape when a proved direct edge stalls."""
		bot_id = int(bot_id)
		path_identity = tuple(path_key)
		state = self.bot_direct_progress.get(bot_id)
		if state is None:
			state = {'path_key': path_identity, 'target': tuple(goal),
			         'position': tuple(current), 'progress_at': float(now),
			         'replans': 0}
			self.bot_direct_progress[bot_id] = state
		if (state.get('path_key') != path_identity or
				_distance_2d(state.get('target', goal), goal) >
				MACRO_TARGET_CHANGE_METRES or not movement_intent or
				_distance_2d(current, goal) <= WAYPOINT_ARRIVAL_RADIUS):
			state['path_key'] = path_identity
			state['target'] = tuple(goal)
			state['position'] = tuple(current)
			state['progress_at'] = float(now)
			state.pop('escape_target', None)
			state.pop('escape_until', None)
			return None
		escape = state.get('escape_target')
		if escape is not None:
			escape = tuple(escape)
			if (float(now) < float(state.get('escape_until', now)) and
					_distance_2d(current, escape) > WAYPOINT_ARRIVAL_RADIUS and
					not self._bot_edges_penalized(
						bot_id, current, escape, now) and
					self.grid.dry_segment_clear(current, escape, now)):
				return escape
			state['target'] = tuple(goal)
			state['position'] = tuple(current)
			state['progress_at'] = float(now)
			state.pop('escape_target', None)
			state.pop('escape_until', None)
			return None
		target = tuple(state.get('target') or goal)
		reference = tuple(state.get('position') or current)
		progress = (_distance_2d(reference, target) -
		            _distance_2d(current, target))
		if progress >= MACRO_PROGRESS_METRES:
			state['target'] = tuple(goal)
			state['position'] = tuple(current)
			state['progress_at'] = float(now)
			return None
		if (float(now) - float(state.get('progress_at', now)) <
				MACRO_STALL_SECONDS):
			return None
		escape = self.grid.safe_local_target(
			current, goal, now, None,
			1.0 if (bot_id % 2) else -1.0,
			self._active_planning_edge_penalties(bot_id, now),
			FIRST_CANDIDATE_OFFSET, diagnostic=state.setdefault('local_fallback', {}))
		state['target'] = tuple(goal)
		state['position'] = tuple(current)
		state['progress_at'] = float(now)
		if escape is None:
			return None
		state['escape_target'] = tuple(escape)
		state['escape_until'] = float(now) + MACRO_EDGE_TTL
		state['replans'] = int(state.get('replans', 0)) + 1
		return tuple(escape)

	@observed('nav.macro_replan')
	def _start_macro_replan(self, bot_id, state, current, target, now):
		"""Reroute one bot without changing shared terrain or hazard state."""
		escape = self.grid.safe_local_target(
			current, target, now, None,
			1.0 if (int(bot_id) % 2) else -1.0,
			self._active_planning_edge_penalties(bot_id, now),
			FIRST_CANDIDATE_OFFSET, diagnostic=state.setdefault('local_fallback', {}))
		key = self.grid._edge_cells_for_segment(current, target)
		if key is None and escape is None:
			return False
		if escape is not None:
			state['macro_escape_target'] = tuple(escape)
			state['macro_escape_until'] = float(now) + MACRO_EDGE_TTL
		else:
			macro_edges = self.bot_macro_edges.setdefault(int(bot_id), {})
			macro_edges[key] = (
				float(now) + MACRO_EDGE_TTL, MACRO_EDGE_PENALTY)
		state['replan_generation'] = int(
			state.get('replan_generation', 0)) + 1
		state['macro_progress_replans'] = int(
			state.get('macro_progress_replans', 0)) + 1
		state['path_key'] = None
		state['index'] = 0
		state['recovery_start'] = tuple(current)
		state['replan_active'] = escape is None
		state['macro_replan_active'] = True
		state['pending_since'] = float(now) - PENDING_PROGRESS_SECONDS
		state.pop('controlled_shallow_target', None)
		self._cancel_bot_searches(bot_id)
		self._reset_macro_progress(state, current, target, now)
		return True

	def _finish_macro_replan(self, bot_id, state):
		self.bot_macro_edges.pop(int(bot_id), None)
		state.pop('macro_escape_target', None)
		state.pop('macro_escape_until', None)
		state['macro_replan_active'] = False
		state['replan_active'] = False
		state['recovery_start'] = None
		state['path_key'] = None
		state['index'] = 0
		self._cancel_bot_searches(bot_id)

	def _observe_macro_progress(self, bot_id, state, current, goal, now):
		"""Observe progress along the issued path target, not arbitrary motion."""
		target = state.get('last_target')
		fallback = bool(state.get('local_fallback_episode') ==
			self._local_fallback_intent(goal, state))
		if fallback:
			# A retry's new tree and each two-metre fallback are still the same
			# unfinished route. Count actual entry into new terrain, including a
			# necessary retreat, rather than renew the deadline when A* changes
			# its tip or a short waypoint is reached inside the same local loop.
			visited = state.setdefault('temporary_visited_cells', set())
			order = state.setdefault('temporary_visited_order', deque())
			cell = self.grid.cell_for(current)
			new_cell = cell not in visited
			if new_cell:
				visited.add(cell)
				order.append(cell)
				while len(order) > MAX_BAKED_SEARCH_EDGE_CACHE:
					visited.discard(order.popleft())
			if (new_cell or state.get('macro_progress_kind') != 'temporary' or
					_distance_2d(current, goal) <= WAYPOINT_ARRIVAL_RADIUS):
				state['temporary_stalled'] = False
				self._reset_macro_progress(state, current, goal, now, 'temporary')
			elif (not state.get('temporary_stalled') and
					float(now) - float(state.get('macro_progress_at', now)) >=
					MACRO_STALL_SECONDS):
				state['temporary_stalled'] = True
				state['macro_progress_replans'] = int(
					state.get('macro_progress_replans', 0)) + 1
			return bool(state.get('temporary_stalled'))
		kind = 'path'
		if (state.get('macro_replan_active') and
				state.get('macro_escape_target') is None and
				not self._active_macro_edge_penalties(bot_id, now)):
			self._finish_macro_replan(bot_id, state)
			self._reset_macro_progress(state, current, target, now, kind)
			return False
		if (target is None or
				_distance_2d(current, target) <= WAYPOINT_ARRIVAL_RADIUS or
				_distance_2d(current, goal) <= WAYPOINT_ARRIVAL_RADIUS):
			self._reset_macro_progress(state, current, target, now, kind)
			return False
		tracked_target = state.get('macro_progress_target')
		path_changed = not fallback and (
			state.get('macro_progress_path_key') != state.get('path_key') or
			int(state.get('macro_progress_index', 0)) !=
			int(state.get('index', 0)) or
			state.get('macro_progress_prefix_search') is not
			state.get('pending_prefix_search') or
			state.get('macro_progress_prefix_index') != state.get('pending_prefix_index'))
		if (tracked_target is None or path_changed or
				state.get('macro_progress_kind', 'path') != kind or
				_distance_2d(tracked_target, target) >
				MACRO_TARGET_CHANGE_METRES):
			self._reset_macro_progress(state, current, target, now, kind)
			return False
		reference = state.get('macro_progress_position') or current
		progress = (_distance_2d(reference, target) -
		            _distance_2d(current, target))
		state['macro_progress_target'] = tuple(target)
		if progress >= MACRO_PROGRESS_METRES:
			if state.get('macro_replan_active'):
				self._finish_macro_replan(bot_id, state)
			self._reset_macro_progress(state, current, target, now, kind)
			return False
		if (float(now) - float(state.get('macro_progress_at', now)) >=
				MACRO_STALL_SECONDS):
			cached = self.paths.get(state.get('path_key'))
			if cached and (self.grid.path_has_penalty(cached, now) is None or
					self.grid.segment_clear(current, target) is None):
				# The deadline can expire on the first deferred frame, before
				# next_target reaches its normal cached-path validation below.
				# Missing proof is not a reason to start a new escape/search.
				self._reset_macro_progress(state, current, target, now, kind)
				return False
			return self._start_macro_replan(
				bot_id, state, current, target, now)
		return False

	def bot_search_diagnostics(self, bot_id, current, now):
		"""Explain a wait without running more ground or collision probes."""
		state = self.bot_states.get(int(bot_id), {})
		request = state.get('request_key')
		searches = []
		for key, search in self.searches.items():
			if key != request and self._path_owner(key[0]) != int(bot_id):
				continue
			searches.append({
				'key': key,
				'start': getattr(search, 'progress', {}).get('start'),
				'goal': getattr(search, 'progress', {}).get('goal'),
				'expanded': int(getattr(search, 'progress', {}).get('revision', 0)),
				'native_refusal': getattr(search, 'progress', {}).get('native_refusal'),
				'age_ms': int(max(0.0, float(now) -
					self.search_times.get(key, float(now))) * 1000.0),
				'steps': int(getattr(search, 'steps', 0)),
				'last_step_age_ms': (int(max(0.0, float(now) -
					search.last_frame) * 1000.0)
					if search.last_frame is not None else None),
			})
		cell = self.grid.cell_for(current)
		prefix = state.get('pending_prefix') or ()
		prefix_index = int(state.get('pending_prefix_index', 0))
		return {
			'local_target': state.get('local_fallback_target'),
			'local_target_end_reason': state.get('local_target_end_reason'),
			'local_target_progress_age_ms': int(max(0.0, float(now) - float(state.get('local_target_progress_at', now))) * 1000.0),
			'current_cell': cell,
			'current_cell_height': self.grid._baked_cell_height(cell),
			'pending_ms': (int(max(0.0, float(now) -
				state['pending_since']) * 1000.0)
				if state.get('pending_since') is not None else 0),
			'searches': sorted(searches, key=lambda item: repr(item['key'])),
			'pending_prefix_start': (state['pending_prefix'][0]
				if state.get('pending_prefix') else None),
			'pending_prefix_target': state.get('pending_prefix_target'),
			'pending_prefix_index': prefix_index,
			'pending_prefix_length': len(prefix),
			'pending_prefix_near_target': prefix[
				max(0, prefix_index):max(0, prefix_index) + 3],
			'macro_progress_age_ms': int(max(0.0, float(now) -
				float(state.get('macro_progress_at', now))) * 1000.0),
			'macro_progress_kind': state.get('macro_progress_kind'),
			'macro_progress_replans': int(state.get('macro_progress_replans', 0)),
			'native_capability': (state['native_capability'][0]
				if state.get('native_capability') is not None else None),
			'path_native_refusal': getattr(self, 'path_native_refusals', {}).get(state.get('path_key')),
			'native_review_cells': len(self.grid._native_review_cells),
		}

	def _stationary_ingress_escape(self, bot_id, state, current, goal, now,
			movement_intent, avoid_points):
		"""Keep physical no-progress evidence across path and combat replans.

		An erased starting cell can repeatedly snap A* to the same nearby entry.
		Changing search keys or rotating the hull does not reach that entry. Give
		one fully checked short detour a bounded lease before selecting it again.
		This never changes shared terrain or bypasses the native motion veto.
		"""
		# This episode repairs entry from an erased cell. On ordinary supported
		# ground the macro progress monitor already owns the same stall; running
		# both creates competing temporary goals at the same deadline.
		if (self.grid.prebaked and
				self.grid._baked_cell_height(self.grid.cell_for(current)) is not None and
				not state.get('ingress_escape')):
			state.pop('ingress_progress', None)
			return None
		tracker = state.get('ingress_progress')
		if (tracker is None or not movement_intent or
				_distance_2d(current, goal) <= WAYPOINT_ARRIVAL_RADIUS or
				_distance_2d(current, tracker['position']) >= 1.0):
			state['ingress_progress'] = {'position': tuple(current), 'at': float(now)}
			state.pop('ingress_escape', None)
			return None
		escape = state.get('ingress_escape')
		if escape is not None:
			target = escape['target']
			if (float(now) < escape['until'] and
					_distance_2d(current, target) > WAYPOINT_ARRIVAL_RADIUS and
					self.grid.dry_segment_clear(current, target, now) and
					not self._bot_edges_penalized(bot_id, current, target, now)):
				return target
			state.pop('ingress_escape', None)
		if float(now) - tracker['at'] < MACRO_STALL_SECONDS:
			return None
		tracker['at'] = float(now)
		# Alternate the bounded escape fan after an unsuccessful lease. Use the
		# real strategic goal, rather than the repeatedly rejected entry point.
		attempt = int(state.get('ingress_replans', 0)) + 1
		state['ingress_replans'] = attempt
		target = self.grid.safe_local_target(
			current, goal, now, avoid_points,
			1.0 if (int(bot_id) + attempt) % 2 else -1.0,
			self._active_planning_edge_penalties(bot_id, now),
			FIRST_CANDIDATE_OFFSET, diagnostic=state.setdefault('local_fallback', {}))
		if target is not None:
			state['ingress_escape'] = {'target': tuple(target), 'until': float(now) + 8.0}
			return tuple(target)
		return None

	@staticmethod
	def _path_owner(path_key):
		try:
			kind = path_key[0]
			if kind in ('local', 'route_join', 'join', 'recovery', 'continue'):
				return int(path_key[1])
		except Exception:
			pass
		return None

	def _active_bot_edge_penalties(self, bot_id, now):
		if bot_id is None:
			return None
		failed = self.bot_failed_edges.get(int(bot_id))
		if not failed:
			return None
		result = {}
		for key, value in list(failed.items()):
			if float(now) >= float(value[0]):
				failed.pop(key, None)
			else:
				result[key] = float(value[1])
		if not failed:
			self.bot_failed_edges.pop(int(bot_id), None)
		return result or None

	def _active_macro_edge_penalties(self, bot_id, now):
		if bot_id is None:
			return None
		failed = self.bot_macro_edges.get(int(bot_id))
		if not failed:
			return None
		result = {}
		for key, value in list(failed.items()):
			if float(now) >= float(value[0]):
				failed.pop(key, None)
			else:
				result[key] = float(value[1])
		if not failed:
			self.bot_macro_edges.pop(int(bot_id), None)
		return result or None

	def _active_planning_edge_penalties(self, bot_id, now):
		result = dict(self._active_bot_edge_penalties(bot_id, now) or {})
		result.update(self._active_macro_edge_penalties(bot_id, now) or {})
		return result or None

	def _bot_edges_penalized(self, bot_id, start, end, now):
		"""True when this bot's own escalation covers any edge of the segment."""
		retired = self.bot_states.get(int(bot_id), {}).get('local_target_retired')
		if (retired is not None and float(now) < retired[1] and
				_distance_2d(end, retired[0]) <= WAYPOINT_ARRIVAL_RADIUS):
			return True
		penalties = self._active_planning_edge_penalties(bot_id, now)
		return bool(penalties and any(
			edge in penalties
			for edge in self.grid._edge_keys_for_segment(start, end)))

	def bot_segment_penalized(self, bot_id, start, end, now):
		"""Expose one Bot's live hard-contact edge veto to target admission."""
		return self._bot_edges_penalized(bot_id, start, end, now)

	def report_blocked_step(self, bot_id, current, target, now):
		"""Escalate a repeated contact or planner veto into a bot-local replan."""
		bot_id = int(bot_id)
		state = self.bot_states.get(bot_id)
		if state is None or target is None:
			return False
		try:
			target = tuple(target)
		except Exception:
			return False
		if _distance_2d(current, target) <= WAYPOINT_ARRIVAL_RADIUS:
			return False
		key = self.grid._edge_cells_for_segment(current, target)
		if key is None:
			return False
		now = float(now)
		if now < float(state.get('blocked_step_escalated_until', 0.0)):
			return False
		tracker = state.get('blocked_step_tracker')
		same_edge = bool(
			isinstance(tracker, dict) and tracker.get('key') == key and
			now - float(tracker.get('last_at', now)) <= 0.5 and
			_distance_2d(current, tracker.get('origin', current)) <=
			max(1.5, self.grid.cell_size * 0.5))
		if same_edge:
			tracker['count'] = int(tracker.get('count', 0)) + 1
			tracker['last_at'] = now
		else:
			tracker = {
				'key': key, 'count': 1, 'first_at': now,
				'last_at': now, 'origin': tuple(current)}
			state['blocked_step_tracker'] = tracker
		if (int(tracker['count']) < BLOCKED_STEP_REPLAN_VERDICTS or
				now - float(tracker['first_at']) < BLOCKED_STEP_REPLAN_SECONDS):
			return False
		failed = self.bot_failed_edges.setdefault(bot_id, {})
		failed[key] = (
			now + BLOCKED_STEP_EDGE_TTL, BLOCKED_STEP_EDGE_PENALTY)
		state['replan_generation'] = int(
			state.get('replan_generation', 0)) + 1
		state['blocked_step_replans'] = int(
			state.get('blocked_step_replans', 0)) + 1
		state['blocked_step_replan'] = True
		state['blocked_step_escalated_until'] = now + 2.0
		state['blocked_step_tracker'] = None
		state['path_key'] = None
		state['index'] = 0
		state['recovery_start'] = tuple(current)
		state['replan_active'] = True
		state['macro_replan_active'] = False
		self.bot_macro_edges.pop(bot_id, None)
		state.pop('macro_escape_target', None)
		state.pop('macro_escape_until', None)
		state.pop('controlled_shallow_target', None)
		self._cancel_bot_searches(bot_id)
		return True

	def report_blocked_plan(self, current, target):
		'''A stopped local driver still has to retire its stale baked corridor.'''
		if not self.grid.review_native_corridor(current, target):
			return False
		for key, path in list(self.paths.items()):
			if any(self.grid._needs_native_review(a, b)
			       for a, b in zip(path, path[1:])):
				self.paths.pop(key, None)
				self.path_times.pop(key, None)
				self.path_hull_revisions.pop(key, None)
		# In-flight searches may have already admitted edges through that wall.
		for search in self.searches.values():
			self._retire_pending_prefixes(search)
		self.searches.clear()
		self.search_times.clear()
		return True

	def _cache_key(self, path_key, goal):
		return (tuple(path_key), self.grid.cell_for(goal))

	@staticmethod
	def _prefers_baked_clearance(path_key):
		"""Prefer manoeuvring room during route travel and local rejoining."""
		try:
			kind = path_key[0]
		except Exception:
			return False
		if kind in ('route', 'route_join', 'join', 'recovery', 'local'):
			return True
		return (kind == 'continue' and len(path_key) > 3 and
		        path_key[3] in ('route', 'route_join'))

	def _trim_cache(self, now):
		if len(self.paths) <= 96:
			return
		ordered = sorted(self.path_times.items(), key=lambda item: item[1])
		for key, _timestamp in ordered[:len(ordered) - 80]:
			self.paths.pop(key, None)
			self.path_times.pop(key, None)
			self.path_hull_revisions.pop(key, None)

	def _retire_pending_prefixes(self, search):
		for state in self.bot_states.values():
			if state.get('pending_prefix_search') is search:
				self._clear_pending_prefix(state)


	def _finish_search(self, key, search, now):
		# A native callback may retire or replace this job while it is stepping.
		if self.searches.get(key) is not search:
			self._retire_pending_prefixes(search)
			return
		self._retire_pending_prefixes(search)
		path = search.result or ()
		self.searches.pop(key, None)
		self.search_times.pop(key, None)
		self.paths[key] = path
		self.path_times[key] = float(now)
		# A resumable search may have traversed a cell before a wreck appeared.
		# Stamp the revision it started with so that path still gets retired.
		self.path_hull_revisions[key] = search.hull_revision
		if path:
			combat_count('nav_search_completed')
			self.search_completed += 1
		else:
			combat_count('nav_search_failed')
			self.search_failed += 1

	def clear_blocked_contact(self, bot_id):
		"""End one physical-contact episode without removing a proved veto."""
		state = self.bot_states.get(int(bot_id))
		if state is None:
			return False
		changed = bool(
			state.get('blocked_step_tracker') is not None or
			state.get('hard_contact_episode') is not None)
		state['blocked_step_tracker'] = None
		state.pop('hard_contact_episode', None)
		return changed

	def report_hard_contact(self, bot_id, current, target,
			realised_yaw, now):
		"""Report a physical blocker against stable navigation intent.

		The driver deliberately remembers the realised hull heading so its
		short-range candidate fan widens after a collision.  That heading is
		not a stable navigation edge, however: a wedged hull can wag across a
		coarse-cell boundary forever and give ``report_blocked_step`` a new key
		on every attempt.  Prefer the current navigation target, whose first
		grid edge is stable, only while realised travel is closing on it.  A
		reverse recovery or a target inside the occupied cell instead pins the
		first realised direction for the lifetime of its own contact episode;
		it must never penalise the clear forward route for a rear collision.
		"""
		bot_id = int(bot_id)
		state = self.bot_states.get(bot_id)
		if state is None or target is None:
			return False
		try:
			target = tuple(target)
			origin_cell = self.grid.cell_for(current)
			target_cell = self.grid.cell_for(target)
			yaw = float(realised_yaw)
		except Exception:
			return False
		dx = float(target[0]) - float(current[0])
		dz = float(target[2]) - float(current[2])
		use_navigation_target = bool(
			self.grid._edge_cells_for_segment(current, target) is not None and
			math.sin(yaw) * dx + math.cos(yaw) * dz > 0.0)
		episode = state.get('hard_contact_episode')
		same_episode = bool(
			isinstance(episode, dict) and
			episode.get('origin_cell') == origin_cell and
			episode.get('target_cell') == target_cell and
			episode.get('target') == target and
			episode.get('uses_navigation_target') ==
			use_navigation_target)
		if not same_episode:
			report_target = target if use_navigation_target else None
			if report_target is None:
				# Two cell widths cross a rounded cell boundary even from a corner
				# and at a diagonal heading.  This point exists only to identify the
				# first reverse/recovery edge; it is never issued as a driving target.
				distance = max(1.0, float(self.grid.cell_size)) * 2.0
				report_target = (
					float(current[0]) + math.sin(yaw) * distance,
					float(current[1]),
					float(current[2]) + math.cos(yaw) * distance)
				if self.grid._edge_cells_for_segment(
						current, report_target) is None:
					return False
			episode = {
				'origin_cell': origin_cell,
				'target_cell': target_cell,
				'target': target,
				'report_target': report_target,
				'uses_navigation_target': use_navigation_target,
			}
			state['hard_contact_episode'] = episode
			state['blocked_step_tracker'] = None
		return self.report_blocked_step(
			bot_id, current, episode['report_target'], now)

	def report_blocked_corridor(self, bot_id, current, target,
			realised_yaw, now):
		"""Accumulate a terrain veto on one stable semantic route edge.

		A steep/world probe is sampled along the driver's realised heading,
		which may wag while the hull is stationary.  It is the same identity
		problem as a hard contact: when that heading still closes on the route
		target, pin the navigation first edge; when recovery travels away from
		it, pin a separate realised edge.  Reusing the episode state also keeps
		hard and terrain evidence for the same continuously blocked corridor
		from restarting one another's verdict count.
		"""
		return self.report_hard_contact(
			bot_id, current, target, realised_yaw, now)

	def request_replan(self, bot_id, current, now):
		"""Retire only this Bot's followers after one checked wait recovery."""
		bot_id = int(bot_id)
		self._cancel_bot_searches(bot_id)
		for key in list(self.paths):
			if self._path_owner(key[0]) == bot_id:
				self.paths.pop(key, None)
				self.path_times.pop(key, None)
				self.path_hull_revisions.pop(key, None)
		self.bot_direct_progress.pop(bot_id, None)
		self.fallback_modes.pop(bot_id, None)
		state = self.bot_states.get(bot_id)
		if state is None:
			return False
		for name in ('last_target', 'local_fallback_target', 'controlled_shallow_target',
				'macro_escape_target', 'macro_escape_until', 'pending_since'):
			state.pop(name, None)
		state.update(path_key=None, index=0, last_position=tuple(current),
			progress_time=float(now), recovery=0, recovery_until=0.0,
			recovery_start=tuple(current), replan_active=True,
			macro_replan_active=False, target_is_terminal=False,
			navigation_status='pending',
			replan_generation=int(state.get('replan_generation', 0)) + 1)
		self._reset_macro_progress(state, current, None, now)
		return True

	def _cancel_bot_searches(self, bot_id, keep_key=None, kind=None):
		"""Discard superseded private jobs without touching shared route plans."""
		bot_id = int(bot_id)
		for key in list(self.searches):
			try:
				path_key = key[0]
				owned = (isinstance(path_key, tuple) and len(path_key) > 1 and
				         path_key[0] in (
				             'local', 'route_join', 'join', 'recovery', 'continue') and
				         int(path_key[1]) == bot_id)
			except Exception:
				owned = False
			if (owned and key != keep_key and
					(kind is None or path_key[0] == kind)):
				combat_count('nav_search_superseded')
				self._retire_pending_prefixes(self.searches.get(key))
				self.searches.pop(key, None)
				self.search_times.pop(key, None)

	def _accrue_search_credit(self, elapsed):
		"""Earn elapsed credit and size this frame's expansion ceiling from it."""
		self.search_credit = min(
			MAX_SEARCH_CREDIT,
			self.search_credit +
			max(0.0, float(elapsed)) * SEARCH_EXPANSIONS_PER_SECOND)
		self.search_frame_budget = min(
			MAX_SEARCH_EXPANSIONS_PER_CATCH_UP_FRAME,
			max(MAX_SEARCH_EXPANSIONS_PER_FRAME, int(self.search_credit)))

	def begin_frame(self, elapsed):
		"""Accrue deterministic A* work once for one render callback.

		Search progress is paid with simulation elapsed rather than CPU wall time,
		so a given elapsed interval buys the same expansions at any frame rate.
		Credit is retained across frames up to a bounded catch-up reserve, and the
		rotating queue below preserves fairness between jobs.
		"""
		self.search_frame_serial += 1
		self.search_frame_open = True
		# Unknown/unloaded native columns are retried next callback, but all
		# Bots in this callback share the same failed exact-segment receipt.
		self.grid._native_review_pending = set()
		self._accrue_search_credit(elapsed)

	def end_frame(self):
		"""Close an explicit render-frame work budget."""
		self.search_frame_open = False
		self.grid._native_review_pending = None

	def _begin_automatic_frame(self, now):
		"""Keep direct TerrainNavigator users deterministic without a runtime."""
		now = float(now)
		if (self.search_auto_time is not None and
				abs(now - self.search_auto_time) < 0.000001):
			return
		# A direct caller has no preceding render callback from which to earn its
		# first credit. Give it one nominal 10 Hz slice; production always opens an
		# explicit frame with the real elapsed value.
		elapsed = (0.10 if self.search_auto_time is None else
		           max(0.0, now - self.search_auto_time))
		self.search_auto_time = now
		self.search_frame_serial += 1
		self.grid._native_review_pending = set()
		self._accrue_search_credit(elapsed)

	@observed('nav.search_batch')
	def _advance_searches(self, now):
		"""Give every pending A* task a deterministic fair frame share.

		The old on-demand scheduler handed the whole frame budget to whichever bots
		were updated first. With a 29-bot room, later join searches could therefore
		remain pending forever. This rotating queue gives every task one expansion
		before any task receives a second, and remembers the next task across frames.
		No branch reads CPU time, so identical elapsed/input produces identical
		paths on fast and slow machines.
		"""
		self.search_now = float(now)
		if not self.search_frame_open:
			self._begin_automatic_frame(now)
		if self.search_processed_frame == self.search_frame_serial:
			combat_count('nav_batch_already_processed')
			return
		self.search_processed_frame = self.search_frame_serial
		self.search_frame_time = float(now)
		keys = sorted(self.searches, key=lambda value: repr(value))
		if not keys:
			self.search_next_key = None
			return
		if self.search_next_key in keys:
			start = keys.index(self.search_next_key)
			queue = keys[start:] + keys[:start]
		else:
			queue = keys
		budget = min(
			max(0, int(self.search_credit)),
			max(0, int(self.search_frame_budget)))
		processed = 0
		combat_count('nav_batch_pending_jobs', len(queue))
		while budget > 0 and queue:
			key = queue.pop(0)
			search = self.searches.get(key)
			if search is None:
				continue
			search.step(1)
			search.last_frame = float(now)
			budget -= 1
			processed += 1
			if search.done:
				self._finish_search(key, search, now)
			elif not search.progress.get('deferred'):
				queue.append(key)
		self.search_credit = max(0.0, self.search_credit - processed)
		self.search_frame_budget = max(
			0, int(self.search_frame_budget) - processed)
		self.search_next_key = queue[0] if queue else None
		combat_count('nav_search_steps', processed)
		if queue and budget <= 0:
			combat_count('nav_batch_budget_exhausted')
		self._trim_cache(now)

	def tick(self, now):
		"""Advance shared path jobs once per render budget, even when bots hold."""
		self._advance_searches(now)
		if (self.housekeeping_time is None or
				float(now) - float(self.housekeeping_time) >= 1.0):
			self.housekeeping_time = float(now)
			self.grid.prune_failed_edges(now)
			for bot_id in list(self.bot_failed_edges):
				self._active_bot_edge_penalties(bot_id, now)
			for bot_id in list(self.bot_macro_edges):
				self._active_macro_edge_penalties(bot_id, now)
			self.grid.trim_caches()

	@observed('nav.path')
	def _path(self, path_key, start, goal, now, avoid_points, native_capability=None):
		key = self._cache_key(path_key, goal)
		owner = self._path_owner(path_key)
		if native_capability is not None and native_capability[0] != ('ignore_destructibles', 1):
			raise ValueError('unsupported navigation collision policy')
		if owner is not None:
			# Join and continuation keys include the Bot's current cell. A
			# pending safe-local fallback can therefore move into a new cell
			# and request a replacement before the old job finishes. Keep only
			# that Bot's current request of the same kind so stale jobs cannot
			# divide the navigator-wide expansion budget. A cached route_join and
			# its pending child join are separate stages of one live request, so a
			# different private kind must remain independent. Do this before a
			# cached-path return: revisiting a cached cell still supersedes a
			# pending same-kind job elsewhere.
			self._cancel_bot_searches(
				owner, keep_key=key, kind=path_key[0])
		if key in self.paths:
			path = self.paths[key]
			hard_edge_penalties = self._active_planning_edge_penalties(
				owner, now)
			# A probe can fail while distant chunks are still streaming. Successful
			# paths are permanent for the battle; failed ones get another chance.
			#
			# The one exception is a wreck published after this plan, which
			# retires it exactly once. A path replanned with the same hulls
			# already marked is the best answer the graph has, even where it
			# still has to run past one, so it must not be discarded and
			# researched again on every following tick.
			retired_by_hull = bool(
				self.path_hull_revisions.get(key) !=
				self.grid.static_hull_revision and
				self.grid.path_crosses_static_hull(path))
			if (path and not retired_by_hull and
					not self.grid.path_has_penalty(path, now) and
					not self.grid.path_has_edge_penalty(
						path, hard_edge_penalties)):
				self.path_times[key] = float(now)
				combat_count('nav_path_cached')
				self.path_hull_revisions[key] = self.grid.static_hull_revision
				return key, path
			if path:
				combat_count('nav_path_penalty_invalidated')
				del self.paths[key]
				self.path_times.pop(key, None)
				self.path_hull_revisions.pop(key, None)
			else:
				if float(now) - self.path_times.get(key, 0.0) < 8.0:
					combat_count('nav_failed_path_cooldown')
					return key, path
				combat_count('nav_failed_path_retry')
				del self.paths[key]
				self.path_times.pop(key, None)
				self.path_hull_revisions.pop(key, None)
				self.grid.clear_negative_cache()
		search = self.searches.get(key)
		if search is None:
			edge_penalties = self._active_planning_edge_penalties(owner, now)
			# A repeated local contact vetoes the edge for this Bot for its lease.
			# Keep it out of the graph as well as direct, cached and local targets:
			# otherwise A* can admit the expensive edge, smooth it back into a
			# shortcut, then restart the same rejected search on the next frame.
			hard_edge_penalties = edge_penalties
			penalized_direct = bool(
				edge_penalties and any(
					edge in edge_penalties
					for edge in self.grid._edge_keys_for_segment(start, goal)))
			# Most annotated segments are already open roads. Avoid invoking A*
			# when one continuous support/collision check proves the direct link.
			if (not penalized_direct and
					self.grid.dry_segment_clear(start, goal, now)):
				path = (tuple(start), tuple(goal))
				self.paths[key] = path
				self.path_times[key] = float(now)
				combat_count('nav_path_direct')
				self.path_hull_revisions[key] = (
					self.grid.static_hull_revision)
				return key, path
			# Moving tanks do not belong in a cached static terrain path. Including all
			# 28 peers made every expansion scan transient positions, permanently baked
			# traffic into shared paths, and multiplied probe cost. LocalDriver handles
			# moving OBBs every frame; A* only owns static terrain and remembered edges.
			search = self.grid.begin_plan(
				start, goal, avoid_points=None,
				max_expansions=self.search_max_expansions, now=now,
				prefer_clearance=self._prefers_baked_clearance(path_key),
				edge_penalties=edge_penalties,
				hard_edge_penalties=hard_edge_penalties,
				route_corridor=((tuple(start), tuple(goal))
				                if 'route' in path_key or 'route_join' in path_key
				                else None))
			self.searches[key] = search
			self.search_times[key] = float(now)
			combat_count('nav_search_created')
		else:
			combat_count('nav_search_retained')
		self._advance_searches(now)
		if key in self.paths:
			return key, self.paths[key]
		if not search.done:
			return key, None
		# _advance_searches normally caches completed jobs. This branch only covers
		# a test double or an externally completed task.
		self._finish_search(key, search, now)
		return key, self.paths[key]

	def _planned_next_segment_clear(self, current, path, index, now,
			bot_id=None):
		"""Keep an adjacent A* ford without inventing a shallow shortcut."""
		if index + 1 >= len(path):
			return False
		target = path[index + 1]
		# Consuming a reached setup is not a shortcut over an unreached bend.
		# The driver cannot approach a point inside its arrival radius any
		# further; give it the next checked edge so it can align for the climb.
		# Keep the tighter driver radius here, not the grid's lookahead radius.
		reached = _distance_2d(current, path[index]) <= WAYPOINT_ARRIVAL_RADIUS
		if ((not reached and
				 not self.grid.live_shortcut_preserves_climb_approach(
					 current, path, index, index + 1)) or
			(bot_id is not None and self._bot_edges_penalized(
				 bot_id, current, target, now)) or
				self.grid.segment_penalty(current, target, now) > 0.0 or
				not self.grid.segment_clear(current, target)):
			return False
		if not self.grid.segment_has_baked_hazard(
				current, target, BAKED_SHALLOW_WATER):
			return True
		# The offset from the realised hull pose may enter shallow water only
		# when the adjacent edge selected by A* is itself the planned ford.
		# Otherwise reaching one dry corner could skip the next dry corner and
		# turn their diagonal into an unplanned water shortcut.
		return self.grid.segment_has_baked_hazard(
			path[index], target, BAKED_SHALLOW_WATER)

	def _planned_current_segment_clear(self, current, path, index, now,
			selected_target=None):
		"""Keep following the adjacent A* ford selected on the prior frame."""
		if index <= 0 or index >= len(path):
			return False
		target = path[index]
		# An already selected ford has consumed its approach. Once the hull
		# passes that setup, the short vector back to it must not undo the
		# accepted climb. New targets still need the approach check below.
		if ((selected_target != target and
				 not self.grid.live_shortcut_preserves_climb_approach(
					 current, path, index - 1, index)) or
				self.grid.segment_penalty(current, target, now) > 0.0 or
				not self.grid.segment_clear(current, target)):
			return False
		if not self.grid.segment_has_baked_hazard(
				current, target, BAKED_SHALLOW_WATER):
			return True
		return self.grid.segment_has_baked_hazard(
			path[index - 1], target, BAKED_SHALLOW_WATER)

	@observed('nav.lookahead')
	def _lookahead_index(self, current, path, index, path_key, now,
			lookahead_distance, bot_id=None):
		"""Select a proved corridor point far enough ahead for current speed."""
		lookahead = int(index)
		if lookahead_distance is None:
			limit = min(len(path), index + 3)
			horizon = None
		else:
			limit = min(len(path), index + 7)
			horizon = max(
				self.grid.cell_size * 2.0, float(lookahead_distance))
		prefer_clearance = self._prefers_baked_clearance(path_key)
		edge_penalties = self._active_planning_edge_penalties(
			bot_id if bot_id is not None else self._path_owner(path_key), now)
		for candidate in range(index + 1, limit):
			if (horizon is not None and candidate > index + 1 and
					_distance_2d(current, path[candidate]) > horizon):
				break
			if ((not prefer_clearance or
					 self.grid.shortcut_preserves_baked_clearance(
						 path, index, candidate)) and
					self.grid.live_shortcut_preserves_climb_approach(
						current, path, index, candidate) and
					not self.grid.path_has_edge_penalty(
						(current, path[candidate]), edge_penalties) and
					self.grid.dry_segment_clear(
						current, path[candidate], now)):
				lookahead = candidate
			else:
				break
		return lookahead

	@observed('nav.next_target')
	def next_target(self, bot_id, current, goal, path_key, now,
			anchor=None, avoid_points=None, lookahead_distance=None,
			movement_intent=True):
		"""Return a terrain-safe local target, holding if no safe path is ready."""
		bot_id = int(bot_id)
		self.bot_direct_progress.pop(bot_id, None)
		# Search progress is a navigator-wide frame task, not a cache-miss side
		# effect. Once every active bot had a cached/partial path, _path() returned
		# before advancing unrelated join and continuation jobs, leaving the whole
		# room parked with an ever-growing pending queue.
		self.tick(now)
		state = self.bot_states.get(bot_id)
		if state is None:
			state = {'last_position': tuple(current), 'progress_time': float(now),
			         'path_key': None, 'index': 0, 'recovery': 0,
			         'recovery_until': 0.0, 'recovery_key': None,
			         'recovery_start': None, 'request_key': None,
			         'request_path_key': None, 'planned_goal': None,
			         'planned_at': 0.0, 'navigation_status': 'pending',
			         'target_is_terminal': False,
			         'replan_generation': 0, 'replan_active': False,
			         'macro_replan_active': False,
			         'macro_progress_replans': 0,
			         'macro_progress_at': float(now),
			         'macro_progress_position': tuple(current),
			         'macro_progress_target': None,
			         'macro_progress_path_key': None,
			         'macro_progress_index': 0,
			         'blocked_step_replans': 0,
			         'blocked_step_tracker': None,
			         'blocked_step_escalated_until': 0.0}
			self.bot_states[bot_id] = state
		if (state.get('blocked_step_replan') and
				not self._active_bot_edge_penalties(bot_id, now)):
			state.pop('blocked_step_replan', None)
			self._finish_macro_replan(bot_id, state)
			state.pop('last_target', None)
			self._reset_macro_progress(state, current, None, now)
		ingress = self._stationary_ingress_escape(
			bot_id, state, current, goal, now, movement_intent, avoid_points)
		if ingress is not None:
			state['last_target'] = ingress
			state['navigation_status'] = 'safe'
			state['target_is_terminal'] = False
			self._set_fallback_mode(bot_id, 'safe_local')
			return ingress
		path_identity = tuple(path_key)
		planned_goal = state.get('planned_goal')
		if (state.get('request_path_key') == path_identity and
				planned_goal is not None and
				_distance_2d(planned_goal, goal) < self.grid.cell_size * 2.0 and
				float(now) - float(state.get('planned_at', 0.0)) < 2.0):
			# A moving contact may cross a coarse cell every observation. Keep the
			# current terrain plan briefly instead of cancelling it before A* can
			# finish; aiming still uses the target's current live pose.
			goal = tuple(planned_goal)
		else:
			state['request_path_key'] = path_identity
			state['planned_goal'] = tuple(goal)
			state['planned_at'] = float(now)
		request_key = self._cache_key(path_key, goal)
		had_request = state.get('request_key') is not None
		request_changed = state.get('request_key') != request_key
		request_transition = bool(had_request and request_changed)
		allow_pending_last_target = True
		if request_changed:
			state.pop('local_fallback_target', None)
			state.pop('local_target_retired', None)
			state.pop('local_completed_target', None)
			combat_count('nav_request_changed' if had_request else
			             'nav_request_first')
			# A new route segment or combat target is not evidence that the previous
			# request stalled. A locally safe old target may bridge an asynchronous
			# search only when it still advances the new intent.
			allow_pending_last_target = self._target_advances_new_intent(
				current, state.get('last_target'), goal)
			if not allow_pending_last_target:
				state.pop('last_target', None)
			self._cancel_bot_searches(bot_id)
			state['request_key'] = request_key
			state['path_key'] = None
			state['index'] = 0
			state['last_position'] = tuple(current)
			state['progress_time'] = float(now)
			state['recovery'] = 0
			state['recovery_until'] = 0.0
			state['recovery_key'] = None
			state['recovery_start'] = None
			state['replan_active'] = False
			state['macro_replan_active'] = False
			self.bot_macro_edges.pop(bot_id, None)
			state.pop('macro_escape_target', None)
			state.pop('macro_escape_until', None)
			state.pop('pending_since', None)
			# A shallow-water grant belongs to the exact A* request that selected it.
			# The replacement request must prove its own ford before steering there.
			state.pop('controlled_shallow_target', None)
			self._reset_macro_progress(
				state, current, state.get('last_target'), now)
		if not movement_intent:
			state.pop('local_fallback_target', None)
		elif not request_changed:
			retained = self._retained_local_fallback(bot_id, current, goal, now, state)
			if retained is not None:
				state['navigation_status'] = 'pending' if retained == tuple(current) else 'safe'
				state['target_is_terminal'] = False
				return retained
		if not request_changed and movement_intent:
			self._observe_macro_progress(bot_id, state, current, goal, now)
		else:
			# A tactical throttle hold may retain a distant movement order. Keep its
			# route warm, but start any stall lease only after movement resumes.
			if state.get('macro_replan_active'):
				self._finish_macro_replan(bot_id, state)
			self._reset_macro_progress(
				state, current, state.get('last_target'), now)
		escape = state.get('macro_escape_target')
		if escape is not None:
			escape = tuple(escape)
			if (float(now) < float(state.get('macro_escape_until', now)) and
					_distance_2d(current, escape) > WAYPOINT_ARRIVAL_RADIUS and
					not self._bot_edges_penalized(
						bot_id, current, escape, now) and
					self.grid.dry_segment_clear(current, escape, now)):
				state.pop('controlled_shallow_target', None)
				state['last_target'] = escape
				state['navigation_status'] = 'safe'
				state['target_is_terminal'] = False
				self._set_fallback_mode(bot_id, None)
				return escape
			self._finish_macro_replan(bot_id, state)
			self._reset_macro_progress(
				state, current, state.get('last_target'), now)
		if (not state.get('macro_replan_active') and
				_distance_2d(current, state['last_position']) >= 2.0):
			state['last_position'] = tuple(current)
			state['progress_time'] = float(now)
			state['recovery'] = 0
			state['recovery_until'] = 0.0
			self._cancel_bot_searches(bot_id, kind='recovery')
			state['replan_active'] = False
			state['recovery_start'] = None
		plan_start = tuple(anchor or current)
		if anchor is not None:
			# Strategic route annotations are two-dimensional and LAN protocol v5
			# historically transported them with y=0.  Use the live vehicle layer as
			# the terrain-probe hint; otherwise elevated spawns make every shared
			# route search start below the map and fail before its first edge.
			plan_start = (float(plan_start[0]), float(current[1]),
			              float(plan_start[2]))
		# A lack of displacement is not proof that the static terrain edge is bad.
		# It is commonly a traffic jam, a tank-to-tank push, or LocalDriver turning
		# in place.  The former recovery path marked that edge globally, invalidated
		# every bot's shared route, and caused an expanding replan/failure storm.
		# LocalDriver already owns short-range stuck recovery; the terrain graph is
		# now changed only by actual terrain/collision probes.
		effective_key = tuple(path_key)
		if state.get('replan_active'):
			effective_key = (
				('recovery', bot_id,
				 int(state.get('replan_generation', 0))) +
				tuple(path_key))
			plan_start = tuple(state.get('recovery_start') or current)
		previous_path = self.paths.get(state.get('path_key'))
		key, path = self._path(effective_key, plan_start, goal, now,
		                       None)
		if path is None:
			if (self.grid.dry_segment_clear(current, goal, now) and
					not self._bot_edges_penalized(
						bot_id, current, goal, now)):
				state.pop('controlled_shallow_target', None)
				state['last_target'] = tuple(goal)
				state['navigation_status'] = 'safe'
				state['target_is_terminal'] = True
				self._set_fallback_mode(bot_id, 'safe_direct')
				return tuple(goal)
			return self._pending_target(
				bot_id, current, goal, now, state, avoid_points,
				allow_pending_last_target, request_transition)
		if not path:
			if (self.grid.dry_segment_clear(current, goal, now) and
					not self._bot_edges_penalized(
						bot_id, current, goal, now)):
				state.pop('controlled_shallow_target', None)
				state['last_target'] = tuple(goal)
				state['navigation_status'] = 'safe'
				state['target_is_terminal'] = True
				self._set_fallback_mode(bot_id, 'safe_direct')
				return tuple(goal)
			state['path_key'] = key
			return self._fallback_target(
				bot_id, current, goal, now, avoid_points, state, True)
		active_key = state.get('path_key')
		if active_key is not None and active_key != key:
			active_path = self.paths.get(active_key)
			if (active_path and
					not (self.path_hull_revisions.get(active_key) !=
					     self.grid.static_hull_revision and
					     self.grid.path_crosses_static_hull(active_path)) and
					not self.grid.path_has_penalty(active_path, now)):
				# A join/recovery/continuation path starts at this hull's real
				# position. Follow it to completion instead of replacing it with
				# the shared strategic path again on the next frame.
				key = active_key
				path = active_path
				self.path_times[key] = float(now)
		if state.get('path_key') != key:
			state['path_key'] = key
			state['index'] = self._path_entry_index(bot_id, current, path, now)
			self._clear_temporary_progress(state)
		index = min(int(state.get('index', 0)), len(path) - 1)
		following_selected_target = bool(
			active_key == key and previous_path is path and
			state.get('last_target') == path[index])
		# A cached path may be reacquired after combat or a lateral offset.
		# The closest vertex can lie behind a hull already on its outgoing
		# edge. Join forward from the real pose instead of reversing to that
		# vertex; never skip a bend without proving the replacement segment.
		passed_vertex = False
		# This projection is a join heuristic, not arrival at an active bend.
		# A hull beside its setup can be slightly past the outgoing edge's
		# perpendicular plane while still needing to reach the setup. Trying
		# that unchecked next edge then reacquiring the same cached join resets
		# progress and alternates neighbouring targets on a slope.
		if not following_selected_target and index + 1 < len(path):
			first, following = path[index], path[index + 1]
			dx, dz = following[0] - first[0], following[2] - first[2]
			passed_vertex = bool(
				(current[0] - first[0]) * dx +
				(current[2] - first[2]) * dz > 0.0 and
				_distance_2d(current, goal) < _distance_2d(first, goal))
			if (passed_vertex and self._planned_next_segment_clear(
					current, path, index, now, bot_id)):
				index += 1
				passed_vertex = False
		selected_target = None
		if (active_key == key and previous_path is path and
				state.get('last_target') == path[index]):
			selected_target = state.get('controlled_shallow_target')
		current_segment_shallow = self.grid.segment_has_baked_hazard(
			current, path[index], BAKED_SHALLOW_WATER)
		if (passed_vertex or
				self.grid.segment_penalty(current, path[index], now) > 0.0 or
				self._bot_edges_penalized(
					bot_id, current, path[index], now) or
				(current_segment_shallow and
				 not self._planned_current_segment_clear(
					 current, path, index, now,
					 selected_target)) or
				not self.grid.segment_clear(current, path[index])):
			join_key = ('join', bot_id, self.grid.cell_for(current)) + tuple(path_key)
			key, joined_path = self._path(join_key, current, goal, now, avoid_points)
			if joined_path is None:
				return self._pending_target(
					bot_id, current, goal, now, state, avoid_points,
					allow_pending_last_target, request_transition)
			if not joined_path:
				# The cached strategic path is unusable from this hull's actual
				# position and the join search has conclusively failed. Reuse the
				# same fully probed short fallback as a failed global search; if no
				# safe candidate exists, remain stopped and retry.
				state['path_key'] = key
				return self._fallback_target(
					bot_id, current, goal, now, avoid_points, state, True)
			path = joined_path
			state['path_key'] = key
			state['index'] = 0
			index = 0
		reach_radius = min(10.0, max(1.5, self.grid.cell_size * 0.55))
		while (index + 1 < len(path) and
		       _distance_2d(current, path[index]) < reach_radius and
		       self._planned_next_segment_clear(
			       current, path, index, now, bot_id)):
			index += 1
		# Look ahead only while every skipped piece is continuously supported.
		lookahead = self._lookahead_index(
			current, path, index, effective_key, now, lookahead_distance,
			bot_id)
		if (lookahead == len(path) - 1 and
				_distance_2d(current, path[lookahead]) < reach_radius and
				_distance_2d(path[lookahead], goal) > reach_radius):
			# A bounded A* may return a safe partial path. Reaching that endpoint
			# means "continue planning from here", not "the strategic goal is
			# complete" and not "wait four seconds until stall recovery".
			continue_key = (('continue', bot_id, self.grid.cell_for(current)) +
			                tuple(path_key))
			next_key, continued = self._path(
				continue_key, current, goal, now, avoid_points)
			if continued:
				path = continued
				state['path_key'] = next_key
				next_index = 0
				if (len(path) > 1 and
						self._planned_next_segment_clear(
						 current, path, 0, now, bot_id)):
					next_index = 1
				next_index = self._lookahead_index(
					current, path, next_index, continue_key, now,
					lookahead_distance, bot_id)
				state['index'] = next_index
				selected = tuple(path[next_index])
				state['last_target'] = selected
				if self.grid.segment_has_baked_hazard(
						current, selected, BAKED_SHALLOW_WATER):
					state['controlled_shallow_target'] = selected
				else:
					state.pop('controlled_shallow_target', None)
				state['navigation_status'] = 'safe'
				state['target_is_terminal'] = bool(
					_distance_2d(selected, goal) <= WAYPOINT_ARRIVAL_RADIUS)
				self._set_fallback_mode(bot_id, None)
				return selected
			if continued is None:
				return self._pending_target(
					bot_id, current, goal, now, state, avoid_points,
					allow_pending_last_target, request_transition)
			return self._fallback_target(
				bot_id, current, goal, now, avoid_points, state, True)
		selected = tuple(path[lookahead])
		if (_distance_2d(current, selected) <= WAYPOINT_ARRIVAL_RADIUS and
				_distance_2d(current, goal) > 15.0):
			# A cached path whose first usable edge has become blocked must not park
			# the hull on its own position until the four-second stall timer fires.
			return self._fallback_target(
				bot_id, current, goal, now, avoid_points, state, True)
		state['index'] = lookahead
		state['last_target'] = selected
		if self.grid.segment_has_baked_hazard(
				current, selected, BAKED_SHALLOW_WATER):
			state['controlled_shallow_target'] = selected
		else:
			state.pop('controlled_shallow_target', None)
		state['navigation_status'] = 'safe'
		state['target_is_terminal'] = bool(
			_distance_2d(selected, goal) <= WAYPOINT_ARRIVAL_RADIUS)
		self._set_fallback_mode(bot_id, None)
		return selected

	def target_is_terminal(self, bot_id):
		state = self.bot_states.get(int(bot_id))
		return bool(state is not None and state.get('target_is_terminal'))

	def _controlled_shallow_corridor_matches(self, current, target,
			travel_yaw):
		"""Keep a shallow exception inside the cells of the armed A* step."""
		try:
			distance = max(1.0, float(self.grid.cell_size))
			end = (
				float(current[0]) + math.sin(float(travel_yaw)) * distance,
				float(current[1]),
				float(current[2]) + math.cos(float(travel_yaw)) * distance,
			)
			planned_shallow = self.grid.baked_hazard_cells(
				current, target, BAKED_SHALLOW_WATER)
			committed_shallow = self.grid.baked_hazard_cells(
				current, end, BAKED_SHALLOW_WATER)
			if (not planned_shallow or committed_shallow is None or
					self.grid.segment_has_baked_hazard(
						current, target, BAKED_FATAL_HAZARDS) or
					self.grid.segment_has_baked_hazard(
						current, end, BAKED_FATAL_HAZARDS)):
				return False
			allowed = set(planned_shallow)
			return all(cell in allowed for cell in committed_shallow)
		except (AttributeError, IndexError, TypeError, ValueError,
				OverflowError):
			return False

	def controlled_shallow_step(self, bot_id, current, sample_yaw,
			maximum_yaw_error=CONTROLLED_SHALLOW_YAW_WINDOW):
		"""Admit only headings toward the A*-selected ford into a shallow cell."""
		state = self.bot_states.get(int(bot_id))
		if state is None:
			return False
		target = state.get('controlled_shallow_target')
		if target is None:
			return False
		dx = float(target[0]) - float(current[0])
		dz = float(target[2]) - float(current[2])
		if abs(dx) + abs(dz) < 0.1:
			return False
		difference = float(sample_yaw) - math.atan2(dx, dz)
		while difference > math.pi:
			difference -= math.pi * 2.0
		while difference < -math.pi:
			difference += math.pi * 2.0
		return (
			abs(difference) <= max(0.0, float(maximum_yaw_error)) and
			self._controlled_shallow_corridor_matches(
				current, target, sample_yaw))

	def controlled_shallow_committed(self, bot_id, current, travel_yaw):
		"""Admit a realised step while the hull still closes on the ford.

		``controlled_shallow_step`` exists for the planner's candidate fan,
		where the sampled yaw *is* the intended heading, so a tight cone around
		the ford bearing is the right question. The committed hull yaw is an
		integrated pose that lags the chosen candidate by however much traverse
		one step could deliver, so re-deriving admission from it vetoed the very
		rotation the planner had just asked for: the step was refused, the
		heading was banned, and the next tactical update selected the same ford
		again. Once A* has armed a ford, the commit side accepts a lagging hull
		only while it still closes on the target and its realised corridor enters
		no shallow cell outside that selected A* step. Fatal and invalid graph
		corridors are never admitted.
		"""
		state = self.bot_states.get(int(bot_id))
		if state is None:
			return False
		target = state.get('controlled_shallow_target')
		if target is None:
			return False
		dx = float(target[0]) - float(current[0])
		dz = float(target[2]) - float(current[2])
		length = math.sqrt(dx * dx + dz * dz)
		if length < 0.1:
			return False
		closing = (math.sin(float(travel_yaw)) * dx +
		           math.cos(float(travel_yaw)) * dz) / length
		return (
			closing > CONTROLLED_SHALLOW_COMMIT_CLOSING and
			self._controlled_shallow_corridor_matches(
				current, target, travel_yaw))

	@staticmethod
	def navigation_paused(current, requested_goal, selected_target,
			minimum_request_distance=15.0,
			hold_radius=WAYPOINT_ARRIVAL_RADIUS):
		"""True when pathfinding intentionally returned the current position."""
		return (_distance_2d(current, requested_goal) > float(minimum_request_distance) and
		        _distance_2d(current, selected_target) <= float(hold_radius))
