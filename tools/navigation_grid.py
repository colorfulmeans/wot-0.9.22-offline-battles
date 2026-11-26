"""Navigation grid construction and validation for the #1513 baker.

``bake_navigation_0922`` decodes the client's terrain, water and compiled
collision. This module samples the navigation grid from those fields, keeps
only reversible links, retains the component that serves both bases and
validates the result. It holds no Bot routes and reads no client resources.
"""

import heapq
import json
import math
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'src', 'res', 'scripts', 'client'))

from gui.mods.offline_lan_0922.ai.navigation import NAVIGABLE_WATER_DEPTH  # noqa: E402


FORMAT_NAME = 'offline-lan-0922-navgraph'
FORMAT_VERSION = 2
GAME_VERSION = '0.9.22.0.1-cn-1513'
# #1513 water the runtime calls navigable is plain ground; deeper water is a
# hazard cell.
WATER_DEPTH_LIMIT = NAVIGABLE_WATER_DEPTH
SHALLOW_WATER_THRESHOLD = NAVIGABLE_WATER_DEPTH


VEHICLE_HALF_WIDTH = 2.15
BRIDGE_OBSTACLE_MARGIN = 1.0
VEHICLE_CLEARANCE_HEIGHT = 2.40
LOCAL_OBSTACLE_MAX_HEIGHT = 0.65
VEHICLE_GROUND_CLEARANCE = LOCAL_OBSTACLE_MAX_HEIGHT
MAX_GRADE_UP = 0.38
MAX_GRADE_DOWN = 0.38
# Normal tank routes must be controllable in both directions.  A drop that can
# be slid down but not climbed back up is an emergency transition, not a route
# shortcut, so the retained graph uses the stricter directional limit.
MAX_GRADE = min(MAX_GRADE_UP, MAX_GRADE_DOWN)
EDGE_CLEARANCE_RADII = (3.0, 6.0)
HAZARD_WATER = 1
HAZARD_EDGE = 2
HAZARD_SHALLOW_WATER = 4
SHALLOW_WATER_COST_MULTIPLIER = 4.0

DIRECTIONS = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0),              (1, 0),
    (-1, 1),  (0, 1),     (1, 1),
)


def decode_png_rgba(png):
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("invalid PNG signature")
    position = 8
    width = height = None
    compressed = []
    while position < len(png):
        length = struct.unpack_from(">I", png, position)[0]
        kind = png[position + 4:position + 8]
        data = png[position + 8:position + 8 + length]
        position += length + 12
        if kind == b"IHDR":
            width, height, bit_depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", data)
            )
            if (bit_depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
                raise ValueError("unsupported height PNG encoding")
        elif kind == b"IDAT":
            compressed.append(data)
        elif kind == b"IEND":
            break
    if width is None or height is None:
        raise ValueError("PNG has no IHDR")
    raw = zlib.decompress(b"".join(compressed))
    bytes_per_pixel = 4
    stride = width * bytes_per_pixel
    rows = []
    previous = bytearray(stride)
    offset = 0
    for unused_y in range(height):
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset:offset + stride])
        offset += stride
        for index in range(stride):
            left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            above = previous[index]
            upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            if filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                estimate = left + above - upper_left
                left_error = abs(estimate - left)
                above_error = abs(estimate - above)
                corner_error = abs(estimate - upper_left)
                if left_error <= above_error and left_error <= corner_error:
                    predictor = left
                elif above_error <= corner_error:
                    predictor = above
                else:
                    predictor = upper_left
            elif filter_type == 0:
                predictor = 0
            else:
                raise ValueError("unsupported PNG filter %d" % filter_type)
            row[index] = (row[index] + predictor) & 255
        rows.append(row)
        previous = row
    return width, height, rows


def _primitive_sections(data):
    if data[:4] != b"\x65\x4e\xa1\x42":
        raise ValueError("invalid primitives magic")
    if len(data) < 8:
        raise ValueError("truncated primitives file")
    table_length = struct.unpack_from("<I", data, len(data) - 4)[0]
    position = len(data) - 4 - table_length
    section_offset = 4
    remaining = table_length
    sections = {}
    while remaining:
        if remaining < 24:
            raise ValueError("truncated primitives section table")
        section_length = struct.unpack_from("<I", data, position)[0]
        name_length = struct.unpack_from("<I", data, position + 20)[0]
        name_start = position + 24
        name = data[name_start:name_start + name_length].decode("utf-8")
        name_padding = (-name_length) % 4
        record_length = 24 + name_length + name_padding
        sections[name] = data[section_offset:section_offset + section_length]
        position += record_length
        remaining -= record_length
        section_offset += section_length + (-section_length) % 4
    return sections


def _bsp_triangles(section, material_names, material_flags):
    if len(section) < 16:
        raise ValueError("truncated BSP2 header")
    magic, triangle_count, unused_max_triangles, unused_node_count = struct.unpack_from(
        "<IIII", section, 0
    )
    if magic & 0x00FFFFFF != 0x00505342:
        raise ValueError("invalid BSP2 magic")
    required = 16 + triangle_count * 40
    if len(section) < required:
        raise ValueError("truncated BSP2 triangle array")
    triangles = []
    for index in range(triangle_count):
        offset = 16 + index * 40
        values = struct.unpack_from("<9f", section, offset)
        material_index = struct.unpack_from("<I", section, offset + 36)[0]
        material_name = (material_names[material_index]
                         if material_index < len(material_names) else "")
        collision_flags = int(material_flags.get(material_name, 0))
        if collision_flags & 16:  # TRIANGLE_NOCOLLIDE
            continue
        triangles.append((values[0:3], values[3:6], values[6:9]))
    return triangles


def _is_bridge_model(model_name):
    """Return whether a static model supplies a drivable bridge deck.

    Collision geometry alone cannot distinguish a road deck from a building
    roof. The stock assets do carry that semantic distinction in their model
    resource names, so keep surface extraction deliberately limited to bridge
    models instead of making arbitrary horizontal scenery traversable.
    """
    return "bridge" in str(model_name).lower()


class ObstacleField(object):

    def _mark_cell(self, cell_x, cell_z, minimum_y, maximum_y):
        key = (int(cell_x), int(cell_z))
        previous = self.cells.get(key)
        if previous is None:
            self.cells[key] = [float(minimum_y), float(maximum_y)]
        else:
            previous[0] = min(previous[0], float(minimum_y))
            previous[1] = max(previous[1], float(maximum_y))

    def _mark_surface(self, cell_x, cell_z, height):
        key = (int(cell_x), int(cell_z))
        previous = self.surface_cells.get(key)
        if previous is None or float(height) > previous:
            self.surface_cells[key] = float(height)

    @staticmethod
    def _walkable_triangle(triangle):
        first, second, third = triangle
        ax = second[0] - first[0]
        ay = second[1] - first[1]
        az = second[2] - first[2]
        bx = third[0] - first[0]
        by = third[1] - first[1]
        bz = third[2] - first[2]
        normal_x = ay * bz - az * by
        normal_y = az * bx - ax * bz
        normal_z = ax * by - ay * bx
        projected_area = abs(normal_y) * 0.5
        if projected_area <= 1e-6:
            return False, 0.0
        slope = math.hypot(normal_x, normal_z) / abs(normal_y)
        return slope <= MAX_GRADE, projected_area

    @staticmethod
    def _triangle_height(triangle, x, z):
        first, second, third = triangle
        denominator = ((second[2] - third[2]) * (first[0] - third[0]) +
                       (third[0] - second[0]) * (first[2] - third[2]))
        if abs(denominator) <= 1e-10:
            return None
        first_weight = (((second[2] - third[2]) * (x - third[0]) +
                         (third[0] - second[0]) * (z - third[2])) /
                        denominator)
        second_weight = (((third[2] - first[2]) * (x - third[0]) +
                          (first[0] - third[0]) * (z - third[2])) /
                         denominator)
        third_weight = 1.0 - first_weight - second_weight
        epsilon = 1e-7
        if (first_weight < -epsilon or second_weight < -epsilon or
                third_weight < -epsilon):
            return None
        return (first_weight * first[1] + second_weight * second[1] +
                third_weight * third[1])

    def _raster_surface_triangle(self, triangle):
        minimum_x = min(point[0] for point in triangle)
        maximum_x = max(point[0] for point in triangle)
        minimum_z = min(point[2] for point in triangle)
        maximum_z = max(point[2] for point in triangle)
        min_cell_x = int(math.floor(minimum_x / self.raster_size))
        max_cell_x = int(math.floor(maximum_x / self.raster_size))
        min_cell_z = int(math.floor(minimum_z / self.raster_size))
        max_cell_z = int(math.floor(maximum_z / self.raster_size))
        for cell_x in range(min_cell_x, max_cell_x + 1):
            x = (cell_x + 0.5) * self.raster_size
            for cell_z in range(min_cell_z, max_cell_z + 1):
                z = (cell_z + 0.5) * self.raster_size
                height = self._triangle_height(triangle, x, z)
                if height is not None:
                    self._mark_surface(cell_x, cell_z, height)

    def _bridge_deck_triangles(self, triangles):
        # A bridge model contains both the level deck and its drivable approach
        # ramps. Selecting only triangles near the dominant deck height leaves
        # a short gap at each bank, so the resulting graph contains an isolated
        # deck that tanks can never enter. The resource name already provides
        # the bridge semantic boundary; within it every tank-grade surface is
        # road, and _mark_surface keeps the highest surface where they overlap.
        candidates = set()
        for triangle in triangles:
            walkable, unused_projected_area = self._walkable_triangle(triangle)
            if not walkable:
                continue
            candidates.add(id(triangle))
        return candidates

    def surface_height(self, x, z):
        cell_x = int(math.floor(float(x) / self.raster_size))
        cell_z = int(math.floor(float(z) / self.raster_size))
        return self.surface_cells.get((cell_x, cell_z))


def _nearest_node(graph, point, max_distance=56.0):
    best = None
    best_distance = float(max_distance)
    width = graph["width"]
    origin_x, origin_z = graph["origin"]
    cell_size = graph["cell_size"]
    for index, height in enumerate(graph["heights_mm"]):
        if height is None:
            continue
        x = origin_x + (index % width) * cell_size
        z = origin_z + (index // width) * cell_size
        distance = math.hypot(x - point[0], z - point[1])
        if distance < best_distance:
            best_distance = distance
            best = index
    return best, best_distance


def _graph_path(graph, start, goal):
    width = graph["width"]
    height = graph["height"]
    cell_size = graph["cell_size"]
    links = graph["links"]
    queue = [(0.0, start)]
    costs = {start: 0.0}
    previous = {}
    while queue:
        cost, current = heapq.heappop(queue)
        if cost != costs.get(current):
            continue
        if current == goal:
            break
        x = current % width
        z = current // width
        mask = links[current]
        for direction_index, (dx, dz) in enumerate(DIRECTIONS):
            if not (mask & (1 << direction_index)):
                continue
            nx = x + dx
            nz = z + dz
            if nx < 0 or nx >= width or nz < 0 or nz >= height:
                continue
            neighbour = nz * width + nx
            new_cost = cost + cell_size * (math.sqrt(2.0) if dx and dz else 1.0)
            if new_cost < costs.get(neighbour, float("inf")):
                costs[neighbour] = new_cost
                previous[neighbour] = current
                heapq.heappush(queue, (new_cost, neighbour))
    if goal not in costs:
        return (), float("inf")
    path = [goal]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    return tuple(path), costs[goal]


def _connected_node_components(graph):
    remaining = set(index for index, value in enumerate(graph["heights_mm"])
                    if value is not None)
    components = []
    width = graph["width"]
    height = graph["height"]
    while remaining:
        root = remaining.pop()
        stack = [root]
        component = set((root,))
        while stack:
            current = stack.pop()
            x = current % width
            z = current // width
            for direction_index, (dx, dz) in enumerate(DIRECTIONS):
                if not (graph["links"][current] & (1 << direction_index)):
                    continue
                nx = x + dx
                nz = z + dz
                if nx < 0 or nx >= width or nz < 0 or nz >= height:
                    continue
                neighbour = nz * width + nx
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    component.add(neighbour)
                    stack.append(neighbour)
        components.append(component)
    components.sort(key=len, reverse=True)
    return components


def _connected_components(graph):
    return [len(component) for component in _connected_node_components(graph)]


def _nearest_node_in_component(graph, point, component):
    best = None
    best_distance = float("inf")
    width = graph["width"]
    origin_x, origin_z = graph["origin"]
    cell_size = graph["cell_size"]
    for index in component:
        x = origin_x + (index % width) * cell_size
        z = origin_z + (index // width) * cell_size
        distance = math.hypot(x - point[0], z - point[1])
        if distance < best_distance:
            best = index
            best_distance = distance
    return best, best_distance


def retain_base_component(graph, map_config, minimum_fraction=0.60):
    """Remove isolated ledges and pockets that cannot reach both team bases."""
    node_components = _connected_node_components(graph)
    if not node_components:
        raise ValueError("baked graph has no navigable nodes")
    source_components = [len(component) for component in node_components]
    source_nodes = sum(source_components)
    candidates = []
    for component in node_components:
        start, start_offset = _nearest_node_in_component(
            graph, map_config["bases"][0], component)
        goal, goal_offset = _nearest_node_in_component(
            graph, map_config["bases"][1], component)
        if start_offset <= 56.0 and goal_offset <= 56.0:
            candidates.append((-len(component), start_offset + goal_offset,
                               min(component), component, start, goal))
    if not candidates:
        raise ValueError("a team base has no nearby navigable node")
    # A tiny ledge can be a few metres closer to a boundary base than the road
    # network. Select one component that can serve both bases, then apply the
    # existing retained-fraction guard so an implausibly small shortcut cannot win.
    unused_size, unused_score, unused_root, retained, start, goal = min(candidates)
    retained_fraction = float(len(retained)) / float(source_nodes)
    if retained_fraction < float(minimum_fraction):
        raise ValueError("base graph component is unexpectedly small: %.1f%%" %
                         (retained_fraction * 100.0))
    width = graph["width"]
    height = graph["height"]
    for index in range(len(graph["heights_mm"])):
        if index not in retained:
            graph["heights_mm"][index] = None
            graph["links"][index] = 0
            continue
        x = index % width
        z = index // width
        mask = graph["links"][index]
        for direction_index, (dx, dz) in enumerate(DIRECTIONS):
            if not (mask & (1 << direction_index)):
                continue
            nx = x + dx
            nz = z + dz
            if (nx < 0 or nx >= width or nz < 0 or nz >= height or
                    nz * width + nx not in retained):
                mask &= ~(1 << direction_index)
        graph["links"][index] = mask
    graph["bake"].update({
        "source_components": len(source_components),
        "source_navigable_nodes": source_nodes,
        "retained_nodes": len(retained),
        "retained_fraction": round(retained_fraction, 5),
        "pruned_nodes": source_nodes - len(retained),
    })
    return retained


def _node_point(graph, index):
    width = graph["width"]
    return (
        graph["origin"][0] + (index % width) * graph["cell_size"],
        graph["origin"][1] + (index // width) * graph["cell_size"],
    )


def validate_graph(graph, map_config):
    components = _connected_components(graph)
    if not components:
        raise ValueError("baked graph has no navigable nodes")
    start, start_offset = _nearest_node(graph, map_config["bases"][0])
    goal, goal_offset = _nearest_node(graph, map_config["bases"][1])
    if start is None or goal is None:
        raise ValueError("a team base has no nearby navigable node")
    path, distance = _graph_path(graph, start, goal)
    if not path:
        raise ValueError("team bases are in disconnected components")
    anchor_offsets = []
    for anchor in map_config.get("anchors", ()):
        unused_node, offset = _nearest_node(graph, anchor)
        if unused_node is None:
            raise ValueError("anchor has no nearby navigable node: %r" % (anchor,))
        anchor_offsets.append(offset)
    maximum_anchor_offset = max(anchor_offsets or [0.0])
    if maximum_anchor_offset > 12.0:
        raise ValueError("anchor is too far from the retained graph: %.1f m" %
                         maximum_anchor_offset)
    navigable = sum(components)
    largest_fraction = float(components[0]) / float(navigable)
    if largest_fraction < 0.72:
        raise ValueError("largest graph component is unexpectedly small: %.1f%%" %
                         (largest_fraction * 100.0))
    return {
        "components": len(components),
        "largest_component": components[0],
        "largest_fraction": round(largest_fraction, 5),
        "base_offsets": [round(start_offset, 3), round(goal_offset, 3)],
        "base_path_nodes": len(path),
        "base_path_metres": round(distance, 3),
    }


def _ground_height(terrain, obstacles, x, z):
    terrain_height = terrain.height(x, z)
    surface_height = obstacles.surface_height(x, z)
    if terrain_height is None:
        return surface_height
    if surface_height is None:
        return terrain_height
    return max(float(terrain_height), float(surface_height))


def _segment_clear(terrain, obstacles, start, end):
    distance = math.hypot(end[0] - start[0], end[2] - start[2])
    steps = max(1, int(math.ceil(distance / 2.0)))
    previous = start
    for step in range(1, steps + 1):
        fraction = float(step) / float(steps)
        x = start[0] + (end[0] - start[0]) * fraction
        z = start[2] + (end[2] - start[2]) * fraction
        y = _ground_height(terrain, obstacles, x, z)
        if y is None or terrain.water_depth(x, z, y) > WATER_DEPTH_LIMIT:
            return False
        horizontal = math.hypot(x - previous[0], z - previous[2])
        if horizontal > 0.0:
            delta = y - previous[1]
            if (delta > horizontal * MAX_GRADE_UP or
                    delta < -horizontal * MAX_GRADE_DOWN):
                return False
        obstacle_margin = (BRIDGE_OBSTACLE_MARGIN
                           if obstacles.surface_height(x, z) is not None
                           else VEHICLE_HALF_WIDTH)
        if obstacles.blocked(x, z, y, margin=obstacle_margin):
            return False
        previous = (x, y, z)
    return True


def _has_safe_edge_clearance(terrain, obstacles, x, z, ground_y):
    """Reject cells whose hull shoulder can fall into water or off a steep lip.

    A route centre can be dry while collision avoidance places one track over a
    shoreline or cliff.  Sampling an eroded shoulder around every baked node
    gives the runtime driver room to deviate without relying on map-specific
    forbidden polygons.
    """
    directions = (
        (-1.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.0, 1.0),
        (-math.sqrt(0.5), -math.sqrt(0.5)),
        (math.sqrt(0.5), -math.sqrt(0.5)),
        (-math.sqrt(0.5), math.sqrt(0.5)),
        (math.sqrt(0.5), math.sqrt(0.5)),
    )
    # A bridge surface exists only where a decoded collision-mesh deck exists.
    # Use a one-metre shoulder here: the ordinary 3/6 m terrain erosion would
    # erase a narrow diagonal bridge, while accepting the centre cell alone can
    # place a route on the outer lip of the deck. At an approach ramp, ordinary
    # dry terrain may safely supply the missing shoulder.
    if obstacles.surface_height(x, z) is not None:
        maximum_drop = BRIDGE_OBSTACLE_MARGIN * MAX_GRADE
        for direction_x, direction_z in directions:
            sample_x = float(x) + direction_x * BRIDGE_OBSTACLE_MARGIN
            sample_z = float(z) + direction_z * BRIDGE_OBSTACLE_MARGIN
            sample_y = _ground_height(terrain, obstacles, sample_x, sample_z)
            if sample_y is None:
                return False
            if terrain.water_depth(sample_x, sample_z, sample_y) > WATER_DEPTH_LIMIT:
                return False
            if float(ground_y) - float(sample_y) > maximum_drop:
                return False
        return True
    radii = EDGE_CLEARANCE_RADII
    for radius in radii:
        maximum_drop = radius * MAX_GRADE
        for direction_x, direction_z in directions:
            sample_x = float(x) + direction_x * radius
            sample_z = float(z) + direction_z * radius
            sample_y = _ground_height(terrain, obstacles, sample_x, sample_z)
            if sample_y is None:
                return False
            if terrain.water_depth(sample_x, sample_z, sample_y) > WATER_DEPTH_LIMIT:
                return False
            if float(ground_y) - float(sample_y) > maximum_drop:
                return False
    return True


def bake_graph(map_name, bounds, bases, terrain, obstacles, cell_size=4.0,
               segment_clear=None):
    """Sample and link the navigation grid inside ``bounds``.

    ``terrain`` and ``obstacles`` are the decoded height, water and
    collision fields. Only reversible links are kept; the caller retains
    the base-serving component and validates the graph.
    """
    if segment_clear is None:
        segment_clear = _segment_clear
    width = int(math.ceil((bounds[2] - bounds[0]) / cell_size))
    height = int(math.ceil((bounds[3] - bounds[1]) / cell_size))
    origin_x = bounds[0] + cell_size * 0.5
    origin_z = bounds[1] + cell_size * 0.5
    heights = [None] * (width * height)
    hazards = [0] * (width * height)
    rejected_water = 0
    shallow_water = 0
    rejected_obstacle = 0
    rejected_edge = 0
    for z_index in range(height):
        z = origin_z + z_index * cell_size
        for x_index in range(width):
            x = origin_x + x_index * cell_size
            index = z_index * width + x_index
            ground = _ground_height(terrain, obstacles, x, z)
            if ground is None:
                continue
            water_depth = terrain.water_depth(x, z, ground)
            if water_depth > WATER_DEPTH_LIMIT:
                hazards[index] |= HAZARD_WATER
                rejected_water += 1
                continue
            if water_depth > SHALLOW_WATER_THRESHOLD:
                hazards[index] |= HAZARD_SHALLOW_WATER
                shallow_water += 1
            if not _has_safe_edge_clearance(terrain, obstacles, x, z, ground):
                hazards[index] |= HAZARD_EDGE
                rejected_edge += 1
                continue
            obstacle_margin = (BRIDGE_OBSTACLE_MARGIN
                               if obstacles.surface_height(x, z) is not None
                               else VEHICLE_HALF_WIDTH)
            if obstacles.blocked(x, z, ground, margin=obstacle_margin):
                rejected_obstacle += 1
                continue
            heights[index] = int(round(ground * 1000.0))
    links = [0] * (width * height)
    for z_index in range(height):
        for x_index in range(width):
            index = z_index * width + x_index
            if heights[index] is None:
                continue
            start = (origin_x + x_index * cell_size,
                     heights[index] / 1000.0,
                     origin_z + z_index * cell_size)
            for direction_index, (dx, dz) in enumerate(DIRECTIONS):
                nx = x_index + dx
                nz = z_index + dz
                if nx < 0 or nx >= width or nz < 0 or nz >= height:
                    continue
                neighbour = nz * width + nx
                if heights[neighbour] is None:
                    continue
                if dx and dz:
                    side_a = z_index * width + nx
                    side_b = nz * width + x_index
                    if heights[side_a] is None or heights[side_b] is None:
                        # A four-metre grid can represent a narrow diagonal
                        # bridge as one deck cell across. The sampled segment,
                        # grade, water and collision checks below are the
                        # authoritative safety test for two bridge endpoints.
                        if (obstacles.surface_height(start[0], start[2]) is None or
                                obstacles.surface_height(
                                    origin_x + nx * cell_size,
                                    origin_z + nz * cell_size) is None):
                            continue
                end = (origin_x + nx * cell_size,
                       heights[neighbour] / 1000.0,
                       origin_z + nz * cell_size)
                if segment_clear(terrain, obstacles, start, end):
                    links[index] |= 1 << direction_index
    # ``links`` are stored per source node and therefore support one-way edges.
    # Ordinary tanks must not intentionally use a one-way fall, though: retain
    # an edge only when the reverse traversal was independently validated too.
    reverse_directions = dict((direction, index)
                              for index, direction in enumerate(DIRECTIONS))
    for z_index in range(height):
        for x_index in range(width):
            index = z_index * width + x_index
            mask = links[index]
            for direction_index, (dx, dz) in enumerate(DIRECTIONS):
                if not (mask & (1 << direction_index)):
                    continue
                neighbour = (z_index + dz) * width + (x_index + dx)
                reverse_index = reverse_directions[(-dx, -dz)]
                if not (links[neighbour] & (1 << reverse_index)):
                    mask &= ~(1 << direction_index)
            links[index] = mask
    graph = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "game_version": GAME_VERSION,
        "map": map_name,
        "cell_size": float(cell_size),
        "bounds": list(bounds),
        "origin": [origin_x, origin_z],
        "width": width,
        "height": height,
        "directions": [list(direction) for direction in DIRECTIONS],
        "heights_mm": heights,
        "links": links,
        # Hazard cells are distinct from ordinary non-navigable obstacle cells.
        # Runtime rollback may reject water/cliff entry without treating every
        # building footprint as a fatal map edge.
        "hazards": hazards,
        "bases": [list(base) for base in bases],
        "bake": {
            "water_depth_limit": WATER_DEPTH_LIMIT,
            "shallow_water_threshold": SHALLOW_WATER_THRESHOLD,
            "shallow_water_cost_multiplier": SHALLOW_WATER_COST_MULTIPLIER,
            "vehicle_half_width": VEHICLE_HALF_WIDTH,
            "bridge_obstacle_margin": BRIDGE_OBSTACLE_MARGIN,
            "vehicle_clearance_height": VEHICLE_CLEARANCE_HEIGHT,
            "vehicle_ground_clearance": VEHICLE_GROUND_CLEARANCE,
            "max_grade": MAX_GRADE,
            "max_grade_up": MAX_GRADE_UP,
            "max_grade_down": MAX_GRADE_DOWN,
            "reversible_links": True,
            "edge_clearance_radii": list(EDGE_CLEARANCE_RADII),
            "terrain_chunks": len(terrain.chunks),
            "water_planes": len(terrain.waters),
            "model_shapes": len(obstacles.model_library.cache),
            "model_instances": obstacles.instance_count,
            "bridge_model_instances": obstacles.bridge_instance_count,
            "bridge_surface_triangles": obstacles.bridge_surface_triangle_count,
            "bridge_surface_cells": len(obstacles.surface_cells),
            "soft_model_instances": obstacles.soft_instance_count,
            "local_obstacle_instances": obstacles.local_instance_count,
            "local_obstacle_max_height": LOCAL_OBSTACLE_MAX_HEIGHT,
            "obstacle_raster_cells": len(obstacles.cells),
            "skipped_models": obstacles.skipped,
            "rejected_water_nodes": rejected_water,
            "shallow_water_nodes": shallow_water,
            "rejected_obstacle_nodes": rejected_obstacle,
            "rejected_edge_nodes": rejected_edge,
        },
    }
    return graph


def write_graph(path, graph):
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        os.makedirs(directory)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as output:
        json.dump(graph, output, sort_keys=True, separators=(",", ":"))
        output.write("\n")
    os.replace(temporary, path)
