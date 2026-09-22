"""Shared navigation must honor stock soft obstacles without destroying them."""
import copy
import types
import unittest
from unittest import mock

import test_port_0922_bot_destructible_approach as approach_fixture
import test_port_0922_bot_runtime as bot_fixture
from test_port_0922_navigation import TerrainNavigator
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor


class NavigationSoftObstacleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = approach_fixture.BotDestructibleApproachTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    @staticmethod
    def profiles(scene, values):
        scene.battle._bots = types.SimpleNamespace(
            navigation_crush_profiles=lambda: values)

    @staticmethod
    def blocked(scene):
        return scene.battle._navigation_obstacle((0, 0, 0), (0, 0, 10), 2.15)

    def test_stock_crushable_house_agrees_with_direction_probe(self):
        with self.fixture.scene(registered=True) as scene:
            self.profiles(scene, ((scene.descriptor, 10.0),))
            self.assertFalse(self.blocked(scene))
            self.assertTrue(scene.battle._direction_probe(
                (0, 0, 0), 0, 0, scene.descriptor, 4.0)['clear'])

    def test_one_slow_siege_profile_keeps_shared_edge_hard(self):
        with self.fixture.scene(registered=True) as scene:
            # Exact UDES siege speed cap; fixture mass/health are controlled.
            # A shared graph intentionally cannot grant the faster Bot's pass
            # to the low-speed mode, even while the active mode is travel.
            self.profiles(scene, ((scene.descriptor, 10.0),
                                  (scene.descriptor, 5.0 / 3.6)))
            self.assertTrue(self.blocked(scene))

    def test_one_light_profile_cannot_inherit_heavy_vehicle_proof(self):
        with self.fixture.scene(registered=True) as scene:
            light = copy.deepcopy(scene.descriptor)
            light.physics['weight'] = 100.0
            self.profiles(scene, ((scene.descriptor, 10.0), (light, 10.0)))
            self.assertTrue(self.blocked(scene))

    def test_missing_roster_or_invalid_profile_keeps_contact_hard(self):
        with self.fixture.scene(registered=True) as scene:
            for values in (None, (), ((None, 10.0),)):
                self.profiles(scene, values)
                self.assertTrue(self.blocked(scene))

    def test_unknown_surface_and_backing_wall_remain_hard(self):
        for kwargs in ({'unknown': True}, {'backing_z': 3.0},
                       {'health': 1000000.0}):
            with self.subTest(kwargs=kwargs):
                with self.fixture.scene(registered=True, **kwargs) as scene:
                    self.profiles(scene, ((scene.descriptor, 10.0),))
                    self.assertTrue(self.blocked(scene))

    def test_ambiguous_catalog_contact_is_not_exempted(self):
        with self.fixture.scene(registered=True) as scene:
            self.profiles(scene, ((scene.descriptor, 10.0),))
            with mock.patch.object(sensor, '_planning_catalog_candidate_1513',
                                   return_value=None):
                self.assertTrue(self.blocked(scene))

    def test_recast_budget_defers_then_retries_without_destruction(self):
        with self.fixture.scene(registered=True) as scene:
            self.profiles(scene, ((scene.descriptor, 10.0),))
            scene.battle._soft_static_recast_budget = [0]
            before = len(scene.rays)
            self.assertEqual('deferred', self.blocked(scene))
            self.assertEqual(1, len(scene.rays) - before)
            scene.battle._soft_static_recast_budget[0] = 24
            self.assertFalse(self.blocked(scene))

    def test_cold_candidate_registration_shares_existing_budget(self):
        with self.fixture.scene() as scene:
            self.profiles(scene, ((scene.descriptor, 10.0),))
            scene.battle._soft_static_recast_budget = [0]
            self.assertEqual('deferred', self.blocked(scene))
            self.assertNotIn((22, 0), getattr(
                sensor, 'g_offh_destr_instances', {}))
            scene.battle._soft_static_recast_budget[0] = 24
            self.assertFalse(self.blocked(scene))
            self.assertIn((22, 0), sensor.g_offh_destr_instances)

    def test_cached_path_survives_deferred_recheck_and_resumes_same_object(self):
        with self.fixture.scene(registered=True) as scene:
            self.profiles(scene, ((scene.descriptor, 10.0),))
            nav = TerrainNavigator(lambda *unused: 0.0,
                scene.battle._navigation_obstacle,
                baked_graph=bot_fixture._flat_open_graph())
            start, goal = (0.0, 0.0, 0.0), (0.0, 0.0, 20.0)
            request = ('route_join', 27, 'soft_scene')
            nav.grid.review_native_corridor(start, goal)

            def target(now, budget):
                scene.battle._soft_static_recast_budget[:] = [budget]
                nav.begin_frame(0.1)
                try:
                    return nav.next_target(27, start, goal, request, now)
                finally:
                    nav.end_frame()

            self.assertEqual(goal, target(0.0, 24))
            self.assertEqual(goal, target(0.1, 24))
            key = nav._cache_key(request, goal)
            path = nav.paths[key]
            state = nav.bot_states[27]
            original_index = state['index']
            original_target = state['last_target']
            nav.grid.invalidate_native_review()
            # Include a first unknown frame after the macro deadline, then
            # repeated exhausted frames. No fake collision result is used.
            for now in (13.0, 14.0, 27.0):
                self.assertEqual(start, target(now, 0))
                self.assertIs(path, nav.paths[key])
                self.assertFalse(nav.searches)
                self.assertEqual('pending', state['navigation_status'])
                self.assertEqual(original_index, state['index'])
                self.assertEqual(original_target, state['last_target'])
                self.assertEqual(0, state['macro_progress_replans'])
                self.assertFalse(state['replan_active'])
            self.assertEqual(goal, target(27.1, 24))
            self.assertIs(path, nav.paths[key])
            self.assertFalse(nav.searches)

            # A definite stock-physics rejection still retires the old path;
            # only the temporary absence of a receipt preserves it.
            light = copy.deepcopy(scene.descriptor)
            light.physics['weight'] = 100.0
            self.profiles(scene, ((light, 10.0),))
            nav.grid.invalidate_native_review()
            self.assertNotEqual(goal, target(27.2, 24))
            self.assertIsNot(path, nav.paths.get(key))


class NavigationCrushRosterTests(unittest.TestCase):
    def setUp(self):
        self.fixture = bot_fixture.BotRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.runtime = self.fixture.runtime
        self.travel = bot_fixture._combat_descriptor()
        self.travel.physics.update(weight=10000.0, speedLimits=(20.0, 10.0))
        self.siege = copy.deepcopy(self.travel)
        self.siege.physics['speedLimits'] = (5.0 / 3.6, 5.0 / 3.6)
        self.composite = types.SimpleNamespace(
            defaultVehicleDescr=self.travel, siegeVehicleDescr=self.siege,
            hasSiegeMode=True)
        self.runtime.descriptor_resolver = lambda unused: self.composite

    def test_full_manifest_publishes_both_modes_once_and_reuses_tuple(self):
        self.assertIsNone(self.runtime.navigation_crush_profiles())
        self.runtime.battle_start(self.fixture.start)
        profiles = self.runtime.navigation_crush_profiles()
        self.assertEqual({10.0, 5.0 / 3.6}, {v[1] for v in profiles})
        self.assertEqual({id(self.travel), id(self.siege)},
                         {id(v[0]) for v in profiles})
        for unused in range(20):
            self.assertIs(profiles, self.runtime.navigation_crush_profiles())

    def test_mode_switch_keeps_shared_profile_set_and_native_cache(self):
        self.runtime.battle_start(self.fixture.start)
        profiles = self.runtime.navigation_crush_profiles()
        invalidate = mock.Mock()
        self.runtime.navigator.invalidate_native_planning = invalidate
        self.runtime._install_bot_descriptor(11, self.runtime.states[11], 2)
        self.assertIs(profiles, self.runtime.navigation_crush_profiles())
        invalidate.assert_not_called()

    def test_descriptor_replacement_invalidates_cached_native_proofs(self):
        self.runtime.battle_start(self.fixture.start)
        invalidate = mock.Mock()
        self.runtime.navigator.invalidate_native_planning = invalidate
        replacement = copy.deepcopy(self.travel)
        replacement.physics['weight'] = 8000.0
        self.runtime._descriptor_pairs[11] = (replacement, self.siege)
        self.runtime._install_bot_descriptor(11, self.runtime.states[11], 0)
        invalidate.assert_called_once_with()
        self.assertIn(replacement,
                      [v[0] for v in self.runtime.navigation_crush_profiles()])

    def test_new_round_rebuilds_roster_and_does_not_keep_old_profiles(self):
        self.runtime.battle_start(self.fixture.start)
        old = self.runtime.navigation_crush_profiles()
        self.runtime.descriptor_resolver = lambda unused: self.travel
        self.runtime.battle_start(dict(self.fixture.start, round_id=6))
        self.assertEqual(((self.travel, 10.0),),
                         self.runtime.navigation_crush_profiles())
        self.assertIsNot(old, self.runtime.navigation_crush_profiles())

    def test_authority_manifest_replaces_profiles_before_reusing_paths(self):
        manifest = self.runtime.battle_start(self.fixture.start)[0]['bots']
        self.runtime.battle_start(dict(
            self.fixture.start, bot_authority_id=2))
        replacement = copy.deepcopy(self.travel)
        replacement.physics['weight'] = 8000.0
        self.runtime.descriptor_resolver = lambda unused: replacement
        invalidate = mock.Mock()
        self.runtime.navigator.invalidate_native_planning = invalidate
        self.runtime.battle_start(dict(self.fixture.start, bot_manifest=manifest))
        self.assertEqual(((replacement, 10.0),),
                         self.runtime.navigation_crush_profiles())
        self.assertGreater(invalidate.call_count, 0)

    def test_missing_physics_cannot_use_derive_defaults_as_clearance(self):
        self.travel.physics.pop('weight')
        self.runtime.battle_start(self.fixture.start)
        self.assertIsNone(self.runtime.navigation_crush_profiles())

    def test_partial_roster_revokes_published_proofs(self):
        self.runtime.battle_start(self.fixture.start)
        invalidate = mock.Mock()
        self.runtime.navigator.invalidate_native_planning = invalidate
        self.runtime.states[12] = {'id': 12}
        self.runtime._refresh_navigation_crush_profiles()
        self.assertIsNone(self.runtime.navigation_crush_profiles())
        invalidate.assert_called_once_with()
