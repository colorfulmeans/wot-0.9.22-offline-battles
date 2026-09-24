# -*- coding: utf-8 -*-
"""Historical community SPG deployment positions, independent of combat routes.

The library proves bounded projection onto the shipped dry navigation graph,
NOT native firing arcs. Movement and actual shots retain their original probes.
No function in this module accepts enemy positions or reads the live scene.
"""
from __future__ import division

import hashlib
import math

from gui.mods.offline_lan_0922.ai.spg_positions_data import DATA

REVISION = DATA['revision']
GAME_VERSION = DATA['game_version']
ARRIVAL_RADIUS = 1.5  # Matches existing LocalDriver's terminal arrival radius.
ORDER_FIELDS = ('spg_position_id', 'spg_position_map', 'spg_position_revision')
_INDEX = dict((p['id'], p) for entry in DATA['maps'].values() for p in entry['positions'])


def map_status(map_name, mode='ctf'):
    if mode != 'ctf':
        return 'unsupported_mode'
    entry = DATA['maps'].get(map_name)
    if entry is None:
        return 'missing_map'
    if entry['source_status'] != 'sourced':
        return entry['source_status']
    return 'ready' if entry['positions'] else 'no_graph_safe_marker'


def lookup(map_name, position_id, team=None, revision=REVISION):
    if revision != REVISION or map_status(map_name) != 'ready':
        return None
    entry = DATA['maps'][map_name]
    point = _INDEX.get(position_id)
    if point is None or point not in entry['positions']:
        return None
    if team is not None and team != point['team']:
        return None
    return point


def _radius(bot):
    state = bot.get('state') or {}
    shape = state.get('collision_shape')
    try:
        radius = math.hypot(float(shape[0]), float(shape[1])) if shape else math.hypot(
            float(state.get('half_width', 2.0)), float(state.get('half_length', 4.5)))
        return radius if 0.0 < radius < 30.0 else 6.0
    except (TypeError, ValueError, IndexError):
        return 6.0


def choose(map_name, bot, reservations, round_id=0, mode='ctf'):
    """Choose once per round; reserve a dry parking slot on the actual spawn side.

    Reservations contain friendly slots only. Prefer another marked zone before
    another slot within an occupied zone. Distance/projection/jitter rank valid
    positions; they are local policy weights, not official matchmaker values.
    """
    if map_status(map_name, mode) != 'ready':
        return None
    entry = DATA['maps'][map_name]
    own_radius = _radius(bot)
    options = []
    for point in entry['positions']:
        if point['team'] != bot['team']:
            continue
        occupied_zone = 0
        permitted = True
        for reserved, radius in reservations:
            if reserved['team'] != bot['team']:
                continue
            separation = math.hypot(point['point'][0]-reserved['point'][0],
                                    point['point'][2]-reserved['point'][2])
            if separation < max(14.0, own_radius+radius+3.0):
                permitted = False
                break
            occupied_zone += reserved['marker_id'] == point['marker_id']
        if not permitted:
            continue
        seed = ('%s:%s:%s:%s' % (REVISION, round_id, bot['id'], point['id'])).encode('ascii')
        jitter = int(hashlib.sha256(seed).hexdigest()[:8], 16) / float(0xffffffff)
        score = (point['path_from_base_metres']*0.015 +
                 point['projection_metres']*0.20 + jitter*4.0)
        options.append((occupied_zone, score, point['id'], point))
    if not options:
        return None
    return min(options)[-1]


def reservation(bot, point):
    return point, _radius(bot)


def plan_matches_order(order):
    """All-or-nothing extension; forged/mixed coordinates never become goals."""
    present = [name in order for name in ORDER_FIELDS]
    if not any(present):
        return True
    if not all(present):
        return False
    try:
        point = lookup(order['spg_position_map'], order['spg_position_id'],
                       order.get('team'), order['spg_position_revision'])
        if point is None:
            return False
        goal = order.get('move_position')
        if isinstance(goal, dict):
            goal = tuple(goal[name] for name in ('x', 'y', 'z'))
        return len(goal) == 3 and all(
            abs(float(goal[i])-point['point'][i]) <= 0.001 for i in range(3))
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return False


def graph_accepts(map_name, point, graph):
    """Cheap one-time worker check of the installed graph at a library position.

    The offline build pins complete graph hashes. Runtime may narrow bounds or
    add shore hazards, so validate the actual installed dry patch as well. It
    does not claim to establish turret clearance or a complete firing lane.
    """
    entry = DATA['maps'].get(map_name)
    if not isinstance(graph, dict) or entry is None:
        return False
    try:
        if graph['map'] != map_name or graph['game_version'] != GAME_VERSION:
            return False
        width, height, size, origin = entry['grid']
        if (width != graph['width'] or height != graph['height'] or
                size != graph['cell_size'] or list(origin) != list(graph['origin'])):
            return False
        x, y, z = point['point']
        bounds = graph['bounds']
        if not bounds[0] <= x <= bounds[2] or not bounds[1] <= z <= bounds[3]:
            return False
        row, column = divmod(point['node'], width)
        if abs(graph['heights_mm'][point['node']]/1000.0-y) > 0.001:
            return False
        directions = graph['directions']
        for dz in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not 0 <= column+dx < width or not 0 <= row+dz < height:
                    return False
                index = (row+dz)*width+column+dx
                px, pz = origin[0]+(column+dx)*size, origin[1]+(row+dz)*size
                if (not bounds[0] <= px <= bounds[2] or not bounds[1] <= pz <= bounds[3]
                        or graph['heights_mm'][index] is None or not graph['links'][index]
                        or graph['hazards'][index] & 15):
                    return False
                if dx or dz:
                    bit = directions.index([dx, dz])
                    reverse = directions.index([-dx, -dz])
                    if (not graph['links'][point['node']] & (1 << bit) or
                            not graph['links'][index] & (1 << reverse) or
                            abs(graph['heights_mm'][index]/1000.0-y) >
                            size*math.hypot(dx, dz)*0.18):
                        return False
        return True
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return False
