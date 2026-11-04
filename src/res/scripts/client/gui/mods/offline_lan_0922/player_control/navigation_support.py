"""Visible-player surface evidence; static routing heights are not support.

Each controller owns its own local links and per-observation native budget.
Remote authored geometry remains baked; only the realised hull can establish
a local floor, including a floor below the graph's bridge deck.
"""
from __future__ import division
import math
from ..ai.local_height import LocalHeightLinks, MAX_COLUMNS, RADIUS


class PlayerHeightSupport(object):
    def __init__(self, grid, ground, columns):
        self.grid = grid
        self.ground = ground if callable(ground) else None
        self.columns = columns if callable(columns) else None
        self.links = LocalHeightLinks(self._column) if self.columns is not None else None
        self.origin = None
        self.sample = None
        self.native_queries = 0
        self.ground_queries = 0
        self.ground_cache = {}
        self.receipt = dict(status='not_sampled')
        if self.links is not None:
            grid.local_height_links = self.links

    def begin(self, position, now):
        sample = (tuple(position), float(now))
        if self.sample == sample:
            return
        self.sample, self.origin = sample, tuple(position)
        self.native_queries = self.ground_queries = 0
        self.ground_cache = {}
        self.receipt = dict(status='sampled', origin=self.origin)
        if self.links is not None:
            self.links.begin(self.origin, now=float(now))

    def close(self):
        self.origin = self.sample = None
        self.ground_cache.clear()
        if self.links is not None:
            self.links.origin = None
            self.links._column_history.clear()

    def _column(self, x, z, low, high):
        # Column enumeration and the legacy native ground seam share one
        # bounded budget. Repeated policy/drive calls cannot refill it.
        if self.native_queries >= MAX_COLUMNS:
            return dict(status='query_budget', surfaces=[])
        self.native_queries += 1
        return self.columns(x, z, low, high)

    def _native_ground(self, point, hint):
        key = (float(point[0]), float(point[1]), float(hint))
        if key in self.ground_cache:
            return self.ground_cache[key]
        value = None
        if self.ground is not None and self.native_queries < MAX_COLUMNS:
            self.native_queries += 1
            self.ground_queries += 1
            try:
                value = self.ground(key[0], key[1], key[2])
                value = None if value is None else float(value)
                if value is not None and (math.isnan(value) or math.isinf(value)):
                    value = None
            except Exception:
                value = None
        self.ground_cache[key] = value
        return value

    def inspect(self, target, authored=True):
        if self.links is None or self.origin is None:
            return 'unscoped', tuple(target)
        target = tuple(target)
        if authored:
            self.links.authored.add(target)
        status, resolved = self.links.inspect(self.origin, target)
        self.receipt = dict(status=status, origin=self.origin, target=target,
                            resolved=resolved)
        return status, resolved

    def height(self, point, hint, strict=False):
        point = (float(point[0]), float(point[1]))
        inside = getattr(self.grid, '_inside', None)
        if callable(inside) and not inside(*point):
            self.receipt = dict(status='outside_bounds', target=point)
            return None
        local = (self.origin is not None and math.hypot(
            point[0] - self.origin[0], point[1] - self.origin[2]) <= RADIUS)
        if not local:
            value = self.grid._ground(point[0], point[1], hint)
            self.receipt = dict(status='baked_geometry' if value is not None else
                'routing_geometry_unavailable', target=(point[0], value, point[1]), origin=self.origin)
            return value
        if self.links is not None:
            occupied = math.hypot(point[0] - self.origin[0], point[1] - self.origin[2]) < .01
            # The occupied pose is the root, never a baked/native topmost
            # height. Elsewhere the old native probe only supplies a search
            # band; continuous column evidence still decides the floor.
            requested = float(hint)
            if not strict and not occupied:
                native = self._native_ground(point, hint)
                if native is not None:
                    requested = native
            elif not strict:
                requested = self.origin[1]
            status, resolved = self.inspect((point[0], requested, point[1]), not strict)
            if status == 'connected' or (status == 'other_surface' and not strict):
                return resolved[1]
            # Unknown/incomplete/budget/wet evidence cannot establish arrival
            # by silently falling back to the baked deck.
            return None
        if self.ground is not None:
            value = self._native_ground(point, hint)
            self.receipt = dict(status='native_ground' if value is not None else
                'native_ground_unavailable', target=(point[0], value, point[1]), origin=self.origin)
            return value
        # Pure-data test grids without native seams remain useful geometry;
        # the supported client always supplies both native seams above.
        return self.grid._ground(point[0], point[1], hint)

    def snapshot(self):
        result = dict(self.receipt, native_queries=self.native_queries,
                      native_budget=MAX_COLUMNS, ground_queries=self.ground_queries)
        if self.links is not None:
            result['columns'] = self.links.queries if self.origin is not None else 0
            result['generation'] = self.links.generation if self.origin is not None else None
            result['links'] = [dict((key, row[key]) for key in (
                'target', 'status', 'resolved', 'unknown_reason') if key in row)
                for row in self.links.receipts[-4:]]
        return result
