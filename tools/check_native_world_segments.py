"""Fused Vector3 boundary retains float32 engine queries and failure laws."""
from __future__ import print_function
import os, sys, imp, time, gc
sys.dont_write_bytecode = True
here = os.path.dirname(os.path.abspath(__file__))
base = imp.load_source('world_segment_base', os.path.join(here, 'check_native_world.py'))
sys.path.insert(0, here)
from native_motion_frontier_fixture import FloatVector
from gui.mods.offline_lan_0922 import native_engine_query
original = native_engine_query.EngineQuery

class CountedQuery(original):
    legacy = False
    def __init__(self, *args):
        self.counts = dict(vector=0, xyz=0, segment=0)
        original.__init__(self, *args)
        if self.legacy:
            self.capabilities = self.capabilities[:19]
    def _invoke(self, function, *args):
        name = ('vector' if function is self._vector else
                'xyz' if function is self._xyz else
                'segment' if getattr(function, '__name__', '') == '_segment' else None)
        if name:
            self.counts[name] += 1
        return original._invoke(self, function, *args)

class Legacy(CountedQuery):
    legacy = True

checks, removed, rays = 0, 0, 0
math_module = base.object_for(Vector3=FloatVector)
try:
    for config, arguments, speed in base.cases:
        arms = []
        for implementation in (Legacy, CountedQuery):
            native_engine_query.EngineQuery = implementation
            scene, queries = base.scene_for(**config)
            owner = base.object_for(_avatar=base.object_for(spaceID=1),
                _runtime=base.object_for(bigworld=scene, math=math_module))
            args = dict(arguments, query_owner=owner)
            trace = {}
            status = base.world.check_horizontal_collision(scene, math_module,
                1, FloatVector(), .0, speed, base.descriptor,
                return_status=True, trace=trace, **args)
            arms.append((status, queries, trace, owner._native_world_query.counts))
        base.equal(arms[1][:3], arms[0][:3])
        old, new = arms[0][3], arms[1][3]
        count = new['segment']
        assert old['segment'] == 0
        assert old['vector']-new['vector'] == 2*count
        assert old['xyz']-new['xyz'] == 2*count
        removed += 3*count
        rays += count
        checks += 1
    # A failed Vector3 constructor still rejects this operation without replay.
    calls = []
    def failed_vector(*unused):
        calls.append(1)
        raise RuntimeError('segment vector failed')
    scene, queries = base.scene_for()
    owner = base.object_for(_avatar=base.object_for(spaceID=1),
        _runtime=base.object_for(bigworld=scene, math=base.object_for(Vector3=failed_vector)))
    trace = {}
    assert base.world.check_horizontal_collision(scene, owner._runtime.math,
        1, FloatVector(), 0., 5., base.descriptor, dt=.05,
        return_status=True, trace=trace, query_owner=owner) == 'hard'
    assert trace['reason'] == 'native_world_error' and not queries
    # No capabilities survive teardown or a synchronous sweep.
    native_engine_query.EngineQuery = CountedQuery
    scene, queries = base.scene_for()
    owner = base.object_for(_avatar=base.object_for(spaceID=1),
        _runtime=base.object_for(bigworld=scene, math=math_module))
    base.world.check_horizontal_collision(scene, math_module, 1, FloatVector(),
        0., 5., base.descriptor, dt=.05, return_status=True, query_owner=owner)
    query = owner._native_world_query
    gc.collect()
    refs = sys.getrefcount(query.capabilities)
    for unused in range(100):
        base.world.check_horizontal_collision(scene, math_module, 1, FloatVector(),
            0., 5., base.descriptor, dt=.05, return_status=True, query_owner=owner)
    gc.collect()
    assert refs == sys.getrefcount(query.capabilities)
    timings = []
    for implementation in (Legacy, CountedQuery):
        native_engine_query.EngineQuery = implementation
        owner = base.object_for(_avatar=base.object_for(spaceID=1),
            _runtime=base.object_for(bigworld=scene, math=math_module))
        start = time.clock()
        for unused in range(1000):
            base.world.check_horizontal_collision(scene, math_module, 1, FloatVector(),
                0., 5., base.descriptor, dt=.05, return_status=True, query_owner=owner)
            del queries[:]
        timings.append((time.clock()-start)*1000./1000.)
    print('Fused segment parity:', checks, 'float32 scenes;', rays,
          'segments;', removed, 'Python boundaries removed; guards and owned refs')
    print('World sweep reference/fused host ms per call:', timings)
    # Compare the fused 20-slot contract against the explicit pinned-skin
    # contract. Filters and engine rays are identical in both modes.
    from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
    saved_catalog, saved_trees = sensor._destructible_catalog, getattr(sensor, 'g_offh_tree_state', None)
    class SkinChecked(original):
        fast_skin = True
        def __init__(self, *args, **kwargs):
            original.__init__(self, *args, **kwargs)
            self.skin_calls = 0
            caps = list(self.capabilities)
            assert caps[20] == 1
            skin = caps[8]
            def counted_skin(*arguments):
                self.skin_calls += 1
                return skin(*arguments)
            caps[8] = counted_skin
            self.capabilities = tuple(caps if self.fast_skin else caps[:20])
    class SkinLegacy(SkinChecked):
        fast_skin = False
    sensor._destructible_catalog = {}
    sensor.g_offh_tree_state = {'native_committed': set(((22, 1),))}
    removed_skins = 0
    try:
        for surface in (None, (0, 0, 3, 22), (87, 128, 3, 22),
                        (71, 0, 3, 22), (71, 128, 3, 22)):
            for config, arguments, speed in base.cases:
                arms = []
                for implementation in (SkinLegacy, SkinChecked):
                    native_engine_query.EngineQuery = implementation
                    scene, queries = base.scene_for(**config)
                    collide = scene.wg_collideSegment
                    def filtered_ray(space, start, end, mask, *filters):
                        if surface is not None and filters:
                            assert filters[0](*surface)
                        return collide(space, start, end, mask, *filters)
                    scene.wg_collideSegment = filtered_ray
                    owner = base.object_for(_avatar=base.object_for(spaceID=1),
                        _runtime=base.object_for(bigworld=scene, math=math_module))
                    args = dict(arguments, query_owner=owner)
                    trace = {}
                    result = base.world.check_horizontal_collision(scene, math_module,
                        1, FloatVector(), 0., speed, base.descriptor,
                        return_status=True, trace=trace, **args)
                    arms.append((result, queries, trace, owner._native_world_query.skin_calls))
                base.equal(arms[0][:3], arms[1][:3])
                if surface is not None and surface[0] == 71:
                    assert arms[0][3] == arms[1][3]
                else:
                    removed_skins += arms[0][3] - arms[1][3]
        assert removed_skins > 0
        print('Pinned skin prefilter parity: 125 scenes;', removed_skins,
              'no-op callbacks removed; relevant surfaces, rays and verdicts retained')
    finally:
        sensor._destructible_catalog, sensor.g_offh_tree_state = saved_catalog, saved_trees
finally:
    native_engine_query.EngineQuery = original
