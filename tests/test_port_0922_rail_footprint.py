"""Narrow rails must lift a track above an otherwise valid flat deck."""

import copy
import unittest

import test_port_0922_rollover_bridge as fixtures
from gui.mods.offline_lan_0922 import bot_runtime, vehicle_physics


class RailFootprintTests(unittest.TestCase):
    @staticmethod
    def surface(x, z, minimum, maximum, flat=None, **unused):
        height = 0.24 if 1.17 - 1e-8 <= x <= 1.23 else 0.0
        return height if minimum <= height <= maximum else None

    def test_single_24cm_rail_keeps_support_through_small_pose_changes(self):
        for dt in (1.0 / 30.0, 1.0 / 120.0):
            with self.subTest(dt=dt):
                battle, entity = fixtures.RolloverBridgeTests().battle()
                counts = []

                def query(*args, **kwargs):
                    counts.append(1)
                    return self.surface(*args, **kwargs)

                battle._suspension_ground_y = query
                # Allow the model origin to move about the true mass center
                # as the right track rises. The rail must remain inside the
                # current footprint to test steady support, not edge release.
                position = (-0.06, 0.0, 0.0)
                for unused in range(int(1.5 / dt)):
                    counts[:] = []
                    position = battle._update_vertical_motion(
                        entity, position, 0.0, dt)
                    # While support stays in the patch: 22 original contacts,
                    # four lateral columns and at most one fresh cached ray
                    # per spring. Missing support uses the older recovery grid.
                    self.assertLessEqual(len(counts), 72)
                self.assertGreater(position[1], 0.09)
                self.assertGreater(battle._local_roll, 0.05)
                self.assertTrue(any(row.get('point') for row in
                                    battle._local_footprint_contacts[2]))

    def test_prepared_broken_skin_filter_covers_every_patch_column(self):
        battle, entity = fixtures.RolloverBridgeTests().battle()
        bounds = []

        def prepare(points):
            bounds[:] = [min(p[0] for p in points), max(p[0] for p in points),
                         min(p[1] for p in points), max(p[1] for p in points)]

        def query(x, z, low, high, **kwargs):
            self.assertLessEqual(bounds[0], x)
            self.assertGreaterEqual(bounds[1], x)
            self.assertLessEqual(bounds[2], z)
            self.assertGreaterEqual(bounds[3], z)
            return self.surface(x, z, low, high)

        battle._local_suspension_params = vehicle_physics.derive_suspension_params(
            entity.typeDescriptor)
        battle._prepared_ground_filter = prepare
        battle._suspension_ground_y = query
        for yaw in (0.0, 0.7, 1.9):
            battle._local_suspension_ground_samples((0, 0, 0), yaw)

    def test_flat_player_and_bot_queries_are_bounded_and_params_are_immutable(self):
        battle, entity = fixtures.RolloverBridgeTests().battle()
        params = vehicle_physics.derive_suspension_params(entity.typeDescriptor)
        before = copy.deepcopy(params)
        calls = []

        def floor(x, z, low, high, flat=None, **unused):
            calls.append((x, z))
            return 0.0 if low <= 0.0 <= high else None

        battle._suspension_ground_y = floor
        position = (0.0, 0.0, 0.0)
        for unused in range(3):
            calls[:] = []
            position = battle._update_vertical_motion(
                entity, position, 0.0, 1.0 / 60.0)
            self.assertLessEqual(len(calls), 62)
        runtime = bot_runtime.BotRuntime(1, suspension_ground_probe=floor)
        state = dict(id=11, x=0.0, y=0.0, z=0.0, yaw=0.0,
                     terrain_pitch=0.0, roll=0.0, airborne=False)
        for unused in range(3):
            calls[:] = []
            self.assertEqual((0.0,) * 10,
                             runtime._suspension_ground_samples(state, params))
            self.assertLessEqual(len(calls), 50)
        self.assertEqual(before, params)

    def test_bot_uses_same_rail_support_and_caches_are_per_bot_and_round(self):
        battle, entity = fixtures.RolloverBridgeTests().battle()
        params = vehicle_physics.derive_suspension_params(entity.typeDescriptor)
        runtime = bot_runtime.BotRuntime(1, suspension_ground_probe=self.surface)
        state = dict(id=11, x=0.0, y=0.0, z=0.0, yaw=0.0,
                     terrain_pitch=0.0, roll=0.0, airborne=False)
        values = runtime._suspension_ground_samples(state, params)
        self.assertEqual((0.0,) * 5 + (0.24,) * 5, values)
        first = runtime._suspension_footprint_contacts[1][11][1]
        runtime._suspension_ground_samples(dict(state, id=12, x=10.0), params)
        second = runtime._suspension_footprint_contacts[1][12][1]
        self.assertIsNot(first, second)
        self.assertFalse(any(second))
        runtime.round_id = 2
        runtime._suspension_ground_samples(dict(state, x=10.0), params)
        self.assertEqual([11], list(runtime._suspension_footprint_contacts[1]))
        self.assertFalse(any(runtime._suspension_footprint_contacts[1][11][1]))

    def test_cached_rail_is_requeried_and_released_beyond_bridge_end(self):
        battle, entity = fixtures.RolloverBridgeTests().battle()

        def bridge(x, z, low, high, **kwargs):
            if z < 5.0:
                return self.surface(x, z, low, high, **kwargs)
            return -15.0 if low <= -15.0 <= high else None

        battle._suspension_ground_y = bridge
        position = (-0.06, 0.0, 0.0)
        for unused in range(90):
            position = battle._update_vertical_motion(entity, position, 0.0, 1.0 / 60)
        self.assertGreater(position[1], 0.09)
        position = (position[0], position[1], 12.0)
        for unused in range(120):
            position = battle._update_vertical_motion(entity, position, 0.0, 1.0 / 60)
        self.assertLess(position[1], -2.0)
        self.assertFalse(any(row.get('point') for row in
                             battle._local_footprint_contacts[2]))

    def test_mass_center_rotation_releases_rail_outside_current_footprint(self):
        battle, entity = fixtures.RolloverBridgeTests().battle()
        battle._suspension_ground_y = self.surface
        # This original edge-contact reproduction acquires the 24 cm rail,
        # then rotation about the mass center moves the track off its edge.
        position = (0.0, 0.0, 0.0)
        for unused in range(6):
            position = battle._update_vertical_motion(
                entity, position, 0.0, 1.0 / 30.0)
        params = battle._local_suspension_params
        points = vehicle_physics.suspension_world_points(
            params, position, 0.0, battle._local_pitch, battle._local_roll)
        self.assertGreater(position[1], 0.05)
        self.assertTrue(all(point[0] - params['footprint_half_width'] > 1.23
                            for point in points[5:]))
        self.assertEqual((0.0,) * 10,
                         battle._local_suspension_ground_samples(position, 0.0))
        self.assertFalse(any(battle._local_footprint_contacts[2][5:]))

    def test_player_contact_cache_resets_with_round_and_spring_identity(self):
        battle, entity = fixtures.RolloverBridgeTests().battle()
        battle._suspension_ground_y = self.surface
        battle._update_vertical_motion(entity, (0, 0, 0), 0.0, 1.0 / 60)
        previous = battle._local_footprint_contacts
        battle._start_message = {'round_id': 2}
        battle._local_suspension_ground_samples((10, 0, 0), 0.0)
        self.assertIsNot(previous, battle._local_footprint_contacts)
        self.assertFalse(any(battle._local_footprint_contacts[2]))
        previous = battle._local_footprint_contacts
        battle._local_suspension_params = vehicle_physics.derive_suspension_params(
            entity.typeDescriptor)
        battle._local_suspension_ground_samples((10, 0, 0), 0.0)
        self.assertIsNot(previous, battle._local_footprint_contacts)
        self.assertFalse(any(battle._local_footprint_contacts[2]))

    def test_highest_legal_candidate_wins_and_old_height_is_never_support(self):
        battle, entity = fixtures.RolloverBridgeTests().battle()
        params = vehicle_physics.derive_suspension_params(entity.typeDescriptor)
        spring = params['springs'][-1]
        cache = {}

        def layers(x, z, low, high):
            value = 0.1 if x < 1.3 else 0.3
            return value if low <= value <= high else None

        value = vehicle_physics.suspension_footprint_support(
            params, (1.35, 0.0), 0.0, None, 0.0, layers,
            point_height=0.0, spring=spring, reference_height=0.0,
            contact_cache=cache)
        self.assertEqual(0.3, value)
        self.assertEqual({'point'}, set(cache))
        value = vehicle_physics.suspension_footprint_support(
            params, (1.35, 0.0), None, (1.35, 0.0, 0.3), 0.0,
            lambda *args: None, point_height=0.0, spring=spring,
            reference_height=0.3, contact_cache=cache)
        self.assertIsNone(value)
        self.assertEqual({}, cache)
