"""Exact static-query reuse, including effects and native owner lifetimes."""
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import native_engine_query as engine
from gui.mods.offline_lan_0922.collision_flags import VEHICLE_SKIP_FLAGS


class WorldRayReuseTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.revision = 0
        self.hit = None
        self.error = None
        def collide(*args):
            self.calls.append(args)
            if self.error:
                raise self.error
            return self.hit
        self.vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        self.owner = types.SimpleNamespace(_avatar=types.SimpleNamespace(spaceID=1),
            _runtime=types.SimpleNamespace(bigworld=types.SimpleNamespace(
                wg_collideSegment=collide), math=types.SimpleNamespace(Vector3=self.vector)),
            _generation=2, _bots=types.SimpleNamespace(round_id=3))
        self.backend = types.SimpleNamespace(engine_query_filter=lambda *args: None)
        self.query = engine.EngineQuery(self.owner, self.backend)
        self.start, self.end = self.vector(0., 2., 0.), self.vector(0., -10., 0.)
        self.patch = mock.patch.object(engine.sensor, '_spatial_revision_1513',
                                       side_effect=lambda: self.revision)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def ray(self, collision_filter=None, ground=True):
        return self.query._ray(self.start, self.end, collision_filter, ground)

    def test_hit_and_miss_each_reuse_one_native_query(self):
        for value in (None, (self.vector(0., 0., 0.), self.vector(0., 1., 0.))):
            self.calls[:] = []
            self.hit = value
            scope = self.query.begin_ray_scope()
            try:
                self.assertIs(value, self.ray())
                self.assertIs(value, self.ray())
                self.assertEqual(1, len(self.calls))
            finally:
                self.query.end_ray_scope(scope)
            self.ray()
            self.assertEqual(2, len(self.calls))

    def test_distinct_geometry_filter_and_query_kind_cannot_alias(self):
        scope = self.query.begin_ray_scope()
        try:
            self.ray()
            self.start.x = .000001
            self.ray()
            first, second = lambda *args: False, lambda *args: False
            self.ray(first)
            self.ray(second)
            self.ray(second, ground=False)
            self.assertEqual(5, len(self.calls))
        finally:
            self.query.end_ray_scope(scope)

    def test_revision_and_explicit_effect_both_invalidate(self):
        scope = self.query.begin_ray_scope()
        try:
            self.ray()
            self.revision += 1
            self.ray()
            self.query.invalidate_ray_scope()
            self.ray()
            self.assertEqual(3, len(self.calls))
        finally:
            self.query.end_ray_scope(scope)

    def test_filtered_ray_must_rebuild_native_candidate_context(self):
        # NativeFilter is one callable over different thread-local exclusion
        # sets. Replaying a raw hit would omit candidate collection and let
        # the subsequent skin/recast stage use another query's evidence.
        scope = self.query.begin_ray_scope()
        try:
            collision_filter = self.backend.engine_query_filter
            self.ray(collision_filter)
            self.ray(collision_filter)
            self.assertEqual(2, len(self.calls))
            self.assertEqual({}, scope)
        finally:
            self.query.end_ray_scope(scope)

    def test_failure_is_not_cached_as_a_miss(self):
        scope = self.query.begin_ray_scope()
        try:
            self.error = ValueError('temporarily unavailable')
            self.assertIs(self.query.unavailable, self.ray())
            self.error = None
            self.assertIsNone(self.ray())
            self.assertEqual(2, len(self.calls))
        finally:
            self.query.end_ray_scope(scope)

    def test_cached_hit_still_checks_round_and_owner(self):
        scope = self.query.begin_ray_scope()
        try:
            self.ray()
            self.owner._bots.round_id += 1
            self.assertIs(self.query.failed, self.ray())
            with self.assertRaisesRegex(RuntimeError, 'owner changed'):
                self.query.raise_failure()
        finally:
            self.query.end_ray_scope(scope)

    def test_nested_scope_and_effect_do_not_reuse_parent_results(self):
        outer = self.query.begin_ray_scope()
        self.ray()
        inner = self.query.begin_ray_scope()
        try:
            self.ray()
            self.query.invalidate_ray_scope()
        finally:
            self.query.end_ray_scope(inner)
        self.ray()
        self.query.end_ray_scope(outer)
        self.assertEqual(3, len(self.calls))
        self.assertEqual([], self.query._ray_scopes)

    def test_other_skip_masks_are_not_cached(self):
        self.query._skip_flags = VEHICLE_SKIP_FLAGS | 0x80
        scope = self.query.begin_ray_scope()
        try:
            self.ray()
            self.ray()
            self.assertEqual(2, len(self.calls))
        finally:
            self.query.end_ray_scope(scope)

    def test_changed_revision_during_callback_cannot_publish_cache(self):
        original = self.query._native_ray
        def mutating(*args):
            self.revision += 1
            return original(*args)
        self.query._native_ray = mutating
        scope = self.query.begin_ray_scope()
        try:
            self.ray()
            self.ray()
            self.assertEqual({}, scope)
            self.assertEqual(2, len(self.calls))
        finally:
            self.query.end_ray_scope(scope)

    def test_cache_is_bounded(self):
        scope = self.query.begin_ray_scope()
        try:
            for n in range(300):
                self.start.x = float(n)
                self.ray()
            self.assertLessEqual(len(scope), 256)
        finally:
            self.query.end_ray_scope(scope)

    def test_signed_zero_endpoint_is_not_rounded_into_another_ray(self):
        scope = self.query.begin_ray_scope()
        try:
            self.ray()
            self.start.x = -0.
            self.ray()
            self.assertEqual(2, len(self.calls))
        finally:
            self.query.end_ray_scope(scope)

    def test_native_world_scope_closes_after_exception(self):
        from gui.mods.offline_lan_0922 import native_world, world_collision
        self.owner._native_world_query = self.query
        def fail(snapshot, dispatch, query, tuning):
            self.ray()
            self.ray()
            raise RuntimeError('world operation failed')
        with mock.patch.dict(sys.modules, {
                'BigWorld': self.owner._runtime.bigworld,
                'Math': self.owner._runtime.math}), \
                mock.patch('gui.mods.offline_lan_0922.native_math.world_available', return_value=True), \
                mock.patch('gui.mods.offline_lan_0922.native_math._load', return_value=
                    types.SimpleNamespace(world_run_native=lambda: None)), \
                mock.patch('gui.mods.offline_lan_0922.native_math.world_run', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'world operation failed'):
                native_world.run(world_collision, 1, self.start, 0., 0.,
                                 query_owner=self.owner)
        self.assertEqual(1, len(self.calls))
        self.assertEqual([], self.query._ray_scopes)


if __name__ == '__main__':
    unittest.main()
