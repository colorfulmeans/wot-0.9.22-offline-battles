"""Budgeted exact collision checks for automatic foreground direct-fire lanes."""
from __future__ import division

import math
from collections import OrderedDict

from ..entities.remote_vehicle import (
    _blast_bbox_bounds, _component_value, collide_vehicle_at_matrix,
    turret_is_attached, vehicle_target_bounds_at_matrix)
from ..shot_geometry import inverse_transform_vehicle_vector, segment_box_entry_distance


CHECKS_PER_DECISION = 2
MAX_CACHE = 512


def _point(value):
    return tuple(float(value[i]) for i in range(3))


def _pose(matrix, basis):
    return tuple(_point(matrix.applyPoint(point)) for point in basis)


def _inside_chord(a, b, bounds):
    entry = segment_box_entry_distance(a, b, bounds)
    if entry is None:
        return None
    delta = tuple(b[i] - a[i] for i in range(3))
    length = math.sqrt(sum(value*value for value in delta))
    exit_distance = length - segment_box_entry_distance(b, a, bounds)
    # Preserve grazing contacts and numerical boundary hits.
    lo, hi = max(0., entry - .001), min(length, exit_distance + .001)
    return (tuple(a[i] + delta[i]*lo/length for i in range(3)),
            tuple(a[i] + delta[i]*hi/length for i in range(3)))


class FiringLane(object):
    def __init__(self):
        self.cache = OrderedDict()
        self.actors = {}
        self.begin(None)

    def begin(self, now):
        self.now = now
        self.segments = 0
        self.native_calls_upper = 0
        self.pending_since = None if now is None else getattr(self, 'pending_since', None)

    def receipt(self):
        return dict(lane_segments=self.segments, lane_native_calls_upper=self.native_calls_upper,
                    lane_wait_seconds=max(0., self.now - self.pending_since)
                    if self.now is not None and self.pending_since is not None else 0.)

    def _query(self, key, ttl, count, run):
        now = self.now
        cached = self.cache.get(key)
        if cached is not None and now is not None and 0. <= now - cached[0] <= ttl:
            return 'blocked' if cached[1] else 'clear'
        if self.segments >= CHECKS_PER_DECISION:
            return 'pending'
        self.segments += 1
        self.native_calls_upper += count
        blocked = bool(run())
        if key in self.cache:
            del self.cache[key]
        self.cache[key] = (now, blocked)
        if len(self.cache) > MAX_CACHE:
            self.cache.popitem(last=False)
        return 'blocked' if blocked else 'clear'

    def _actor_key(self, actor, pose):
        previous = self.actors.get(actor)
        if previous is not None and previous[0] == pose:
            return previous[1]
        # A pose that moves away and later returns still needs a fresh proof.
        generation = object()
        self.actors[actor] = (pose, generation)
        return generation

    def _vehicles(self, owner, target, path):
        math_module = owner._runtime.math
        matrix = math_module.Matrix
        basis = tuple(math_module.Vector3(*point) for point in
                      ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (0., 0., 1.)))
        for record in owner._records.values():
            if record.get('local') or record.get('tombstone') or not record.get('ready'):
                continue
            other = owner._server_entity(record.get('engine_id'))
            if other is None or other.id == target.id or not other.isStarted:
                continue
            alive = other.isAlive()
            if alive and int((record.get('state') or {}).get('team', 0)) != int(owner.client.team):
                continue
            blocker = dict(id=other.id, kind='ally' if alive else 'wreck')
            if record.get('native_remote'):
                body, chassis = owner._projectile_vehicle_matrices(record, other)
            else:
                body, chassis = other.matrix, None
            bounds = vehicle_target_bounds_at_matrix(other, body, math_module, chassis_matrix=chassis)
            if bounds is None:
                return 'unknown', dict(blocker, reason='missing_bounds')
            parts = ('chassis', 'hull', 'turret', 'gun') if turret_is_attached(other) else ('chassis', 'hull')
            actor_key = None
            actor = ('vehicle', other.id)
            def pose_key():
                return (id(other), other.id, id(other.typeDescriptor), alive,
                    _pose(matrix(body), basis),
                    _pose(matrix(chassis if chassis is not None else body), basis), parts,
                    float(matrix(other.appearance.turretMatrix).yaw) if len(parts) == 4 else None,
                    float(matrix(other.appearance.gunMatrix).pitch) if len(parts) == 4 else None)
            for index, (a, b) in enumerate(zip(path, path[1:])):
                segment = _inside_chord(a, b, bounds)
                if segment is None:
                    continue
                if actor_key is None:
                    for name in parts:
                        component = _component_value(other.typeDescriptor, name)
                        tester = _component_value(component, 'hitTester')
                        if (_blast_bbox_bounds(_component_value(tester, 'bbox')) is None or
                                not callable(getattr(tester, 'localHitTest', None))):
                            return 'unknown', dict(blocker, reason='missing_native_geometry', component=name)
                    actor_key = self._actor_key(actor, pose_key())
                status = self._query((actor_key, a, b), 1. if alive else 4., len(parts),
                    lambda: collide_vehicle_at_matrix(other, body, owner._vector(segment[0]),
                        owner._vector(segment[1]), math_module, chassis_matrix=chassis))
                if status != 'clear':
                    return status, dict(blocker, reason='native_contact' if status == 'blocked'
                                        else 'lane_budget', chord=index)
            if actor_key is None and actor in self.actors:
                self._actor_key(actor, pose_key())
        return 'clear', None

    def _debris(self, owner, path):
        debris = getattr(owner, '_detached_turret_obstacles', None)
        if debris is None or not debris.active():
            return 'clear', None
        server_time = owner._turret_server_time_ms()
        ready = tuple(debris._ready(server_time))
        for turret in ready:
            row = turret['row']
            actor = ('debris', row['actor_kind'], row['actor_id'])
            signature = (row.get('motion_seq', 0), turret['rest'], turret['attitude'],
                         tuple(id(part[1]) for part in turret['components']))
            actor_key = self._actor_key(actor, signature)
            for index, (a, b) in enumerate(zip(path, path[1:])):
                segment = _inside_chord(a, b, turret['target_bounds'])
                if segment is None:
                    continue
                status = self._query((actor_key, a, b), 4., len(turret['components']),
                    lambda: self._turret_hit(owner, turret, segment))
                if status != 'clear':
                    return status, dict(kind='detached_turret', id=row['actor_id'], chord=index,
                        reason='native_contact' if status == 'blocked' else 'lane_budget')
        return 'clear', None

    @staticmethod
    def _turret_hit(owner, turret, segment):
        local = [inverse_transform_vehicle_vector(
            tuple(point[i] - turret['rest'][i] for i in range(3)), *turret['attitude'])
            for point in segment]
        for unused_name, component, offset, unused_bounds in turret['components']:
            a, b = (owner._vector(tuple(point[i] - offset[i] for i in range(3))) for point in local)
            if component.hitTester.localHitTest(a, b):
                return True
        return False

    def check(self, owner, target, path):
        if not path or len(path) < 2:
            return 'unknown', dict(reason='missing_path')
        try:
            status, blocker = self._vehicles(owner, target, path)
            if status == 'clear':
                status, blocker = self._debris(owner, path)
        except (AttributeError, TypeError, ValueError, IndexError, KeyError,
                RuntimeError, OverflowError):
            return 'unknown', dict(reason='native_lane_unavailable')
        if status == 'pending' and self.pending_since is None:
            self.pending_since = self.now
        return status, blocker
