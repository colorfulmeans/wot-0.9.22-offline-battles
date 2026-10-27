# -*- coding: utf-8 -*-
"""Keep live engine effects on the caller while C++ runs the world law."""
import functools
from .worker_diagnostics import observed


def readonly_queries(function):
    """Share raw static rays only across one synchronous read-only sweep.

    Nested sweeps are isolated. Every world operation must also explicitly
    disable commits before it can borrow this scope; normal driving cannot.
    """
    @functools.wraps(function)
    def invoke(owner, *args, **kwargs):
        missing = object()
        previous = getattr(owner, '_readonly_world_rays', missing)
        owner._readonly_world_rays = {}
        try:
            return function(owner, *args, **kwargs)
        finally:
            if previous is missing:
                del owner._readonly_world_rays
            else:
                owner._readonly_world_rays = previous
    return invoke


@observed('motion.world_bridge')
def run(module, spaceID, pos, yaw, vel, td=None, airborne=False, dt=0.04,
        return_status=False, allow_kinetic=False, kinetic_speed=None,
        commit_enabled=True, motion_yaw=None, pitch=0.0, roll=0.0,
        trace=None, exact_footprint=False, departing_contact=None, query_owner=None):
    from . import native_math
    if not native_math.world_available():
        return None
    import BigWorld, Math
    query = None
    backend = native_math._load()
    if query_owner is not None and hasattr(backend, 'world_run_native'):
        from .native_engine_query import EngineQuery
        query = getattr(query_owner, '_native_world_query', None)
        if query is not None:
            try:
                query._live()
            except RuntimeError:
                query = None
        if query is None:
            query = EngineQuery(query_owner, backend)
            query_owner._native_world_query = query
        if query._runtime.bigworld is not BigWorld or query._runtime.math is not Math or query._space != spaceID:
            raise RuntimeError('World query owner does not match its live engine')
    bounds, heights = module._vehicle_motion_geometry(td)
    if bounds is None:
        bounds = (-1.5, 1.5, 3.5, 3.5)
    left, right, back, front = bounds
    if trace is not None:
        trace.clear()
        trace.update(position=(pos.x, pos.y, pos.z), yaw=yaw, speed=vel,
                     dt=dt, motion_yaw=motion_yaw, pitch=pitch, roll=roll,
                     airborne=airborne,
                     extents=(max(abs(left), abs(right)), back, front),
                     lateral_bounds=(left, right))
    # C++ validates and assembles the flat law input without intermediate
    # Python concatenations or copying immutable descriptor geometry.
    snapshot = ((pos.x, pos.y, pos.z, yaw, vel, dt, pitch, roll,
                 0.0 if motion_yaw is None else motion_yaw), bounds, heights,
                (motion_yaw is not None, airborne, exact_footprint,
                 departing_contact is not None))
    hits = {}
    state = [module._UNPREPARED_COLLISION_FILTER, departing_contact]
    crush = [False]
    V = Math.Vector3
    from . import destructibles_sensor
    ground_provider = module.ground_collision_filter
    ground_batch = destructibles_sensor.ground_filter_batch_1513(ground_provider)
    dispatch = _WorldDispatch((module, query, state, V, pos, yaw, bounds,
        heights, motion_yaw, spaceID, vel, td, crush, allow_kinetic,
        kinetic_speed, commit_enabled, trace, hits, ground_batch, ground_provider,
        BigWorld)).dispatch
    # An exception propagates. Replaying the law could repeat destruction.
    scope = query.begin_ray_scope(reuse_readonly=not commit_enabled) if query is not None else None
    try:
        status = native_math.world_run(snapshot, dispatch, query,
            (module._WORLD_SOFT_RECAST_BUDGET, module._GROUND_HIT_EPSILON, module._MAX_DRIVABLE_GRADIENT))
    finally:
        if scope is not None:
            query.end_ray_scope(scope)
    if status is None:
        return None
    if return_status:
        return ('clear', 'hard', 'kinetic')[status]
    return status != 0


def xyz(v):
    return (v.x, v.y, v.z)


class _WorldDispatch(object):
    """One solve owns its effects; the callback implementation is shared."""
    def __init__(self, values):
        self.values = values

    @observed('motion.world_dispatch')
    def dispatch(self, op, rows):
        (module, query, state, V, pos, yaw, bounds, heights, motion_yaw,
         spaceID, vel, td, crush, allow_kinetic, kinetic_speed, commit_enabled,
         trace, hits, ground_batch, ground_provider, BigWorld) = self.values
        if query is not None:
            query._live()
        if op == 1:
            a, b = rows[0]
            state[0] = module._trace_collision_filter(
                module.prepare_horizontal_collision_filter(V(*a), V(*b)), trace)
            return state[0] if query is not None else None
        if op == 8:
            result = bool(state[1](rows[0]))
            query._live()
            return result
        if op == 7:
            a, unused_end, unused_flags = rows[0]
            provider = (ground_batch if ground_batch is not None and
                        module.ground_collision_filter is ground_provider else
                        module.ground_collision_filter)
            return provider(a[0], a[2])
        if op == 2:
            v = rows[0]
            state[1] = module._translation_departing_contact(
                pos, yaw, bounds, v[3:6], v[0], v[1], heights,
                dy=v[2], pose_axes=(v[6:9], v[9:12], v[12:15])
                if motion_yaw is not None else None)
            return None
        if op == 5:
            a, b, handle = rows[0]
            if query is not None:
                query.invalidate_ray_scope()
            result = module._destroy_and_recast(
                spaceID, V(*a), V(*b), handle if query is not None else hits[handle], yaw, vel, td,
                crush, allow_kinetic, kinetic_speed, commit_enabled, state[0])
            if query is not None:
                query._live()
            return (2 if result == 'kinetic' else 1 if result is True else 0,)
        if op == 6:
            a, b, handle, reason, ground_ahead, profile = rows[0]
            module._record_hard_contact(
                trace, ('', 'raised_wall', 'ground_profile', 'solid_lane', 'upper_lane')[reason],
                V(*a), V(*b), handle if query is not None else hits[handle], ground_ahead, profile)
            return None
        result = []
        stopped = False
        for a, b, flags in rows:
            if stopped or flags & 4:
                result.append((None, None, 0, a, b))
                if op == 4 and flags & 1:
                    stopped = True
                continue
            start, end = V(*a), V(*b)
            if op == 3:
                hit = module._collide_horizontal(spaceID, start, end, state[0],
                                                 state[1] if flags & 1 else None)
            else:
                collision_filter = state[0]
                if collision_filter is module._UNPREPARED_COLLISION_FILTER:
                    collision_filter = module.ground_collision_filter(a[0], a[2])
                try:
                    hit = module.collide_motion_segment(
                        spaceID, start, end, collision_filter,
                        BigWorld.wg_collideSegment, 'native.motion.ground')
                except (AttributeError, IndexError, TypeError, ValueError):
                    hit = None
            if hit is None:
                result.append((None, None, 0, xyz(start), xyz(end)))
                if op == 4 and flags & 1:
                    stopped = True
            else:
                handle = len(hits) + 1
                hits[handle] = hit
                normal = xyz(hit[1]) if len(hit) > 1 else (0.0, 0.0, 0.0)
                result.append((xyz(hit[0]), normal, handle, xyz(start), xyz(end)))
        return tuple(result)
