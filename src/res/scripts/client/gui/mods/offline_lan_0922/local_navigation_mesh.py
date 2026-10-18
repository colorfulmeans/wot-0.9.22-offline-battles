"""Small additive navigation meshes; the parent grid keeps its metre scale."""
import math


class LocalMeshes(object):
    def __init__(self, grid, patches):
        self.grid = grid
        self.patches = patches
        self.points = {}
        self.indices = {}
        self.edges = {}
        self.keys = []
        heights, links, hazards = list(grid._baked_heights), list(grid._baked_links), list(grid._baked_hazards)
        for number, patch in enumerate(patches):
            keys = []
            for i, height in enumerate(patch['heights_mm']):
                x = patch['origin'][0] + i % patch['width'] * patch['cell_size']
                z = patch['origin'][1] + i // patch['width'] * patch['cell_size']
                base = grid.cell_for((x, 0., z))
                base_point = grid.point_for(base, 0.)
                if (height is not None and grid._baked_index(base) is not None and
                        abs(base_point[0]-x) < 1.e-6 and abs(base_point[2]-z) < 1.e-6 and
                        abs(grid._baked_cell_height(base)-height/1000.) < .01):
                    key = base
                else:
                    key = (-number-1, i)
                    self.indices[key] = len(heights)
                    self.points[key] = (x, float(height or 0)/1000., z)
                    heights.append(height); links.append(patch['links'][i]); hazards.append(patch['hazards'][i])
                keys.append(key)
            self.keys.append(keys)
            for i, mask in enumerate(patch['links']):
                if patch['heights_mm'][i] is None:
                    continue
                first = keys[i]
                for bit, (dx, dz, unused) in enumerate(grid._NEIGHBOURS):
                    if not mask & (1 << bit):
                        continue
                    nx, nz = i % patch['width']+dx, i // patch['width']+dz
                    if not (0 <= nx < patch['width'] and 0 <= nz < patch['height']):
                        raise ValueError('local mesh edge leaves its bounds')
                    j = nz*patch['width']+nx
                    if patch['heights_mm'][j] is None:
                        raise ValueError('local mesh edge has no support')
                    self.edges.setdefault(first, set()).add(keys[j])
        grid._baked_heights = heights
        grid._baked_links = links
        grid._baked_hazards = hazards

    def cell(self, point):
        for i, patch in enumerate(self.patches):
            x = (float(point[0])-patch['origin'][0])/patch['cell_size']
            z = (float(point[2])-patch['origin'][1])/patch['cell_size']
            if 0 <= x <= patch['width']-1 and 0 <= z <= patch['height']-1:
                return self.keys[i][int(math.floor(z+.5))*patch['width']+int(math.floor(x+.5))]
        return None

    def touches(self, start, end):
        # Segment/AABB clipping avoids a map-wide sampling loop.
        for patch in self.patches:
            low, high = 0., 1.
            for axis, origin, count in ((0, patch['origin'][0], patch['width']),
                                        (2, patch['origin'][1], patch['height'])):
                a, delta = float(start[axis]), float(end[axis])-float(start[axis])
                last = origin+(count-1)*patch['cell_size']
                if abs(delta) < 1.e-9:
                    if not origin <= a <= last:
                        high = -1.; break
                else:
                    first, second = sorted(((origin-a)/delta, (last-a)/delta))
                    low, high = max(low, first), min(high, second)
            if low <= high:
                return True
        return False

    def crossed(self, start, end, require_height=True):
        distance = math.hypot(end[0]-start[0], end[2]-start[2])
        step = min(p['cell_size'] for p in self.patches)*.42
        count = max(1, int(math.ceil(distance/step)))
        result = []
        for i in range(count+1):
            point = (start[0]+(end[0]-start[0])*i/count, 0., start[2]+(end[2]-start[2])*i/count)
            cell = self.cell(point)
            if cell is None:
                cell = self.grid.cell_for(point)
            if not result or cell != result[-1]:
                result.append(cell)
        if require_height:
            result[0] = self.grid._nearest_baked_cell(result[0], 2)
            result = [c for i,c in enumerate(result) if i == 0 or c != result[i-1]]
        lookup = self.grid._baked_index if require_height else self.grid._baked_flat_index
        if any(c is None or lookup(c) is None for c in result):
            return ()
        return tuple(result)

    def nearest(self, cell, radius):
        point = self.points[cell]
        patch = self.patches[-cell[0]-1]
        scale = patch['cell_size']
        limit = max(0, int(radius))*self.grid.cell_size
        reach = int(math.ceil(limit/scale))
        x, z = cell[1] % patch['width'], cell[1] // patch['width']
        choices = []
        for dz in range(-reach, reach+1):
            for dx in range(-reach, reach+1):
                if not (0 <= x+dx < patch['width'] and 0 <= z+dz < patch['height']):
                    continue
                key = self.keys[-cell[0]-1][(z+dz)*patch['width']+x+dx]
                if self.grid._baked_index(key) is not None:
                    choices.append((dx*dx+dz*dz, key))
        return min(choices)[1] if choices else None

    def near_point(self, point, radius):
        cell = self.cell(point)
        if cell is None:
            return None
        if self.grid._baked_index(cell) is not None:
            return cell
        return self.nearest(cell, radius) if cell in self.points else None

    def wire(self):
        return tuple((p['origin'][0], p['origin'][1], p['cell_size'], p['width'], p['height'],
                      tuple(p['heights_mm']), tuple(p['links']), tuple(p['hazards'])) for p in self.patches)
