"""Persistent pure geometry for the streamed #1513 destructible sensor.

The sensor retains every native identity proof and effect/publication ledger.
Only validated numeric geometry is copied here; calls never invoke BigWorld.
"""
from __future__ import print_function

import types
try:
    _CHUNK_ID_TYPES = (int, long, float, bool)
except NameError:
    _CHUNK_ID_TYPES = (int, float, bool)

_owner = None
_disabled = False


def point(value):
    try:
        return float(value.x), float(value.y), float(value.z)
    except AttributeError:
        return tuple(float(value[index]) for index in range(3))


def pose(position, yaw, bbox, travel=0., motion_yaw=None, pitch=0., roll=0.):
    return (point(position), float(yaw), float(pitch), float(roll), float(travel),
            None if motion_yaw is None else float(motion_yaw),
            point(bbox[0]), point(bbox[1]))


def wire_key(value):
    return float(value[0]), int(value[1])


class Geometry(object):
    def __init__(self, backend, sensor):
        self.backend = backend
        self.handle = backend.destr_open()
        self.chunks = {}
        if self.handle is None:
            raise RuntimeError('Native destructible index was not created')
        try:
            catalog = sensor._destructible_catalog or {}
            bins = catalog.get('baked_shot_bins', {})
            self.update(4, tuple((cell, tuple(wire_key(key) for key in members))
                                for cell, members in bins.items()))
            for key, instance in sensor.__dict__.get(
                    'g_offh_destr_instances', {}).items():
                self.instance(sensor, key, instance)
        except Exception:
            self.close()
            raise

    def close(self):
        handle, self.handle = self.handle, None
        if handle is not None:
            self.backend.destr_close(handle)
        self.chunks.clear()

    def update(self, opcode, payload):
        if self.backend.destr_update(self.handle, opcode, payload) != 1:
            raise RuntimeError('Native destructible index mutation was rejected')

    def query(self, opcode, payload):
        return self.backend.destr_query(self.handle, opcode, payload)

    def instance(self, sensor, key, instance):
        kind = {'fragile': 0, 'structure': 1, 'falling': 2}[instance['kind']]
        if sensor._destructible_isolated_1513(*key):
            self.remove(*key)
            return
        bins = instance.get('bin_keys')
        if bins is None:
            bins = tuple(cell for cell, members in sensor.__dict__.get(
                'g_offh_destr_contact_bins', {}).items() if key in members)
        self.update(0, (wire_key(key), kind, instance['boxes'], bins))

    def remove(self, chunk_id, item_index=None):
        if item_index is None:
            self.update(3, float(chunk_id))
            self.chunks.pop(int(chunk_id), None)
        else:
            self.update(1, (float(chunk_id), int(item_index)))

    def _reference_chunk(self, sensor, chunk_id, registry, tree_type=None):
        current = self.chunks.get(int(chunk_id))
        if current is not None and current[0] is registry:
            return current[1]
        import AreaDestructibles
        if tree_type is None:
            tree_type = AreaDestructibles.DESTR_TYPE_TREE
        catalog_types = (AreaDestructibles.DESTR_TYPE_FRAGILE,
                         getattr(AreaDestructibles, 'DESTR_TYPE_STRUCTURE', None),
                         AreaDestructibles.DESTR_TYPE_FALLING_ATOM)
        items = {}
        indexes = []
        for name in ('bins', 'extended_bins'):
            bins = []
            for cell, values in registry.get(name, {}).items():
                rows = []
                for item in values:
                    index = int(item[0])
                    if index in items and items[index] != item:
                        raise RuntimeError('One streamed item has conflicting geometry')
                    items[index] = item
                    rows.append(index)
                bins.append((cell, tuple(rows)))
            indexes.append(tuple(bins))
        values = tuple((index, tuple(float(x) for x in item[1:4]),
                        int(item[4] == tree_type),
                        int(bool(sensor._normalized_filename(item[5]))),
                        int(bool(item[8]) and item[4] in catalog_types),
                        float(item[9])) for index, item in sorted(items.items()))
        self.update(2, (float(chunk_id), values, indexes[0], indexes[1]))
        self.chunks[int(chunk_id)] = registry, items
        return items


    def chunk(self, sensor, chunk_id, registry, tree_type=None):
        """Prepare and register a complete fresh chunk in one native call."""
        if type(chunk_id) not in _CHUNK_ID_TYPES:
            return self._reference_chunk(sensor, chunk_id, registry, tree_type)
        current = self.chunks.get(int(chunk_id))
        if current is not None and current[0] is registry:
            return current[1]
        # Keep the hot cache return above all expensive admission and input
        # preparation. Replaced Python mutation/query owners keep their path.
        ordinary_owner = (type(self) is Geometry and
            'update' not in self.__dict__ and 'query' not in self.__dict__ and
            Geometry.__dict__['update'] is _NATIVE_CHUNK_METHODS[0] and
            Geometry.__dict__['query'] is _NATIVE_CHUNK_METHODS[1])
        if (ordinary_owner and type(sensor) is types.ModuleType and
                type(registry) is dict and all(type(key) is str for key in registry)):
            pinned = getattr(sensor, '_NATIVE_FILENAME_LAW', None)
            if (type(pinned) is tuple and len(pinned) == 2 and
                    pinned[0] is sensor._normalized_filename and
                    pinned[1] is sensor._STRING_TYPES):
                import AreaDestructibles
                if type(AreaDestructibles) is types.ModuleType:
                    tree = AreaDestructibles.DESTR_TYPE_TREE if tree_type is None else tree_type
                    labels = (tree, AreaDestructibles.DESTR_TYPE_FRAGILE,
                              getattr(AreaDestructibles, 'DESTR_TYPE_STRUCTURE', None),
                              AreaDestructibles.DESTR_TYPE_FALLING_ATOM)
                    origins = registry.get('bins', {})
                    extended = registry.get('extended_bins', {})
                    if type(origins) is dict and type(extended) is dict:
                        prepared = self.query(8, (
                            float(chunk_id), tuple(origins.items()),
                            tuple(extended.items()), labels))
                        if prepared is not None:
                            items = dict(prepared)
                            self.chunks[int(chunk_id)] = registry, items
                            return items
        # Rejection has not changed the Store or invoked user conversions.
        return self._reference_chunk(sensor, chunk_id, registry, tree_type)


_NATIVE_CHUNK_METHODS = (Geometry.__dict__['update'], Geometry.__dict__['query'])


def reset():
    global _owner, _disabled
    owner, _owner = _owner, None
    _disabled = False
    if owner is not None:
        try:
            owner.close()
        except Exception:
            pass


def _fail(error):
    global _disabled
    reset()
    _disabled = True
    from gui.mods.offline_lan_0922 import native_math
    native_math._report_failure(error)


def _get(sensor):
    global _owner
    if _disabled:
        return None
    if _owner is None:
        from gui.mods.offline_lan_0922 import native_math
        backend = native_math._load()
        if backend is None or not hasattr(backend, 'destr_open'):
            return None
        try:
            _owner = Geometry(backend, sensor)
        except Exception as error:
            _fail(error)
    return _owner


def put_instance(sensor, key, instance):
    if _owner is not None:
        try:
            _owner.instance(sensor, key, instance)
        except Exception as error:
            _fail(error)


def drop(chunk_id, item_index=None):
    if _owner is not None:
        try:
            _owner.remove(chunk_id, item_index)
        except Exception as error:
            _fail(error)


def vehicle_box(sensor, position, yaw, bbox, travel, motion_yaw, pitch, roll):
    owner = _get(sensor)
    if owner is None:
        return None
    return owner.query(4, pose(position, yaw, bbox, travel, motion_yaw, pitch, roll))


def tree_sweep(sensor, start, start_yaw, end, end_yaw, minimum, maximum, pivot):
    owner = _get(sensor)
    if owner is None:
        return None
    return owner.query(5, (start, start_yaw, end, end_yaw, minimum, maximum, pivot))


def intersections(sensor, boxes, vehicle):
    owner = _get(sensor)
    if owner is None:
        return None
    indexes = owner.query(6, (vehicle, boxes))
    return None if indexes is None else [boxes[index] for index in indexes]


def baked_candidates(sensor, vehicle):
    owner = _get(sensor)
    if owner is None:
        return None
    rows = owner.query(3, vehicle)
    return None if rows is None else [(int(row[0]), int(row[1])) for row in rows]


def trees(sensor, chunk_id, registry, sweeps, tree_type, radius):
    owner = _get(sensor)
    if owner is None:
        return None
    items = owner.chunk(sensor, chunk_id, registry, tree_type)
    rows = owner.query(2, (float(chunk_id), sweeps, float(radius)))
    if rows is None:
        return None
    candidates, isolated = {}, set()
    for index in rows:
        identity = int(chunk_id), int(index), None
        if sensor._destructible_isolated_1513(chunk_id, index):
            isolated.add(identity)
        else:
            candidates[identity] = items[index]
    return candidates, isolated


def body(sensor, chunk_id, registry, position, yaw, speed, bbox, vehicle,
         prepared_pose=None):
    owner = _get(sensor)
    if owner is None:
        return None
    items = owner.chunk(sensor, chunk_id, registry)
    if prepared_pose is None:
        prepared_pose = pose(position, yaw, bbox)
    result = owner.query(1, (float(chunk_id), prepared_pose,
                             float(speed), vehicle))
    if result is None:
        return None
    return [items[index] for index in result[0]], result[1], bool(result[2])


def neighbourhood(sensor, area, position, sin_yaw, cos_yaw, speed, neighbours):
    """Batch only the pinned pure chunk mapper; custom test owners stay Python."""
    if not _chunk_mapper_1513(area):
        return None
    owner = _get(sensor)
    if owner is None:
        return None
    return owner.query(7, (point(position), float(sin_yaw), float(cos_yaw),
                           float(speed), int(bool(neighbours))))


def catalog(sensor, vehicle, contact=None):
    owner = _get(sensor)
    if owner is None:
        return None
    result = owner.query(0, (vehicle, contact))
    if result is None:
        return None
    instances = sensor.__dict__.get('g_offh_destr_instances', {})
    def candidate(row):
        identity = int(row[0]), int(row[1])
        instance = instances[identity]
        box = instance['boxes'][row[2]]
        return identity + (box[2] if instance['kind'] == 'structure' else None,
                           sensor._instance_descriptor_filename_1513(instance),
                           instance['kind'], instance['item_scale'], box[0])
    values = [candidate(row) for row in result[0]]
    groups = {}
    for row in result[1]:
        value = candidate(row)
        identity = value[:2]
        if identity not in groups:
            groups[identity] = [], instances[identity]['boxes']
        groups[identity][0].append((value, bool(row[3])))
    return values, groups, result[2], result[3], bool(result[4])


def refresh_baked(sensor):
    if _owner is not None:
        try:
            bins = (sensor._destructible_catalog or {}).get('baked_shot_bins', {})
            _owner.update(4, tuple((cell, tuple(wire_key(key) for key in members))
                                  for cell, members in bins.items()))
        except Exception as error:
            _fail(error)


def _chunk_mapper_1513(area):
    """Existing bytecode/constant identity gate for the pure #1513 mapper."""
    try:
        import DestructiblesCache
    except ImportError:
        return False
    mapper = getattr(DestructiblesCache, 'chunkIDFromPosition', None)
    indexes = getattr(DestructiblesCache, 'chunkIndexesFromPosition', None)
    wire = getattr(DestructiblesCache, 'chunkIDFromChunkIndexes', None)
    code = lambda f: getattr(f, 'func_code', getattr(f, '__code__', None))
    if (mapper is None or area.chunkIDFromPosition is not mapper or
            getattr(DestructiblesCache, '_INV_CHUNK_RANGE', None) != .01 or
            getattr(code(mapper), 'co_names', None) != (
                'chunkIDFromChunkIndexes', 'chunkIndexesFromPosition') or
            getattr(code(indexes), 'co_consts', None) != (None, 0, 2) or
            getattr(code(indexes), 'co_names', None) != (
                'int', 'math', 'floor', '_INV_CHUNK_RANGE') or
            getattr(code(wire), 'co_consts', None) != (None, 127, 8)):
        return False
    return True


def _chunk_vector_1513(math_module):
    # A Python replacement must retain its callbacks/rounding/errors. Only
    # the existing native Math.Vector3 constructor/index slots are bypassed.
    factory = getattr(math_module, 'Vector3', None)
    return (type(factory) is type and
            getattr(factory, '__module__', None) == 'Math' and
            getattr(factory, '__name__', None) == 'Vector3' and
            type(getattr(factory, '__init__', None)) is type(object.__init__) and
            type(getattr(factory, '__getitem__', None)) is type(object.__init__) and
            type(getattr(factory, '__new__', None)) is type(object.__new__))

def _chunk_environment_1513(area, math_module):
    import math
    import sys
    import types
    cache = sys.modules.get('DestructiblesCache')
    if any(type(module) is not types.ModuleType
           for module in (cache, area, math_module, math)):
        return False
    if (cache is None or getattr(cache, 'math', None) is not math or
            type(math.floor) is not types.BuiltinFunctionType or
            getattr(math.floor, '__name__', None) != 'floor' or
            getattr(cache, 'int', int) is not int):
        return False
    for name in ('chunkIDFromPosition', 'chunkIndexesFromPosition',
                 'chunkIDFromChunkIndexes'):
        function = getattr(cache, name, None)
        if type(function) is not types.FunctionType:
            return False
        namespace = getattr(function, 'func_globals',
                            getattr(function, '__globals__', None))
        if namespace is not cache.__dict__:
            return False
    return True


def required_chunks(sensor, area, math_module, sweep_boxes):
    """Batch the current mapper's numeric work, never a custom callback."""
    if (not _chunk_environment_1513(area, math_module) or
            not callable(getattr(area, 'chunkIDFromPosition', None)) or
            not _chunk_mapper_1513(area) or not _chunk_vector_1513(math_module)):
        return None
    from gui.mods.offline_lan_0922 import native_math
    result = native_math.call('destr_required_chunks', sweep_boxes,
        (sensor._SOLID_CONTACT_RADIUS_1513,
         sensor._DESTRUCTIBLE_CHUNK_METRES_1513))
    if result is None:
        return None
    return ('ready', 'pending', 'hard')[result[0]], result[1]
