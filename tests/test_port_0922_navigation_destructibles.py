"""All bot route planners ignore proved destructibles without destroying them."""
import copy
import math
import sys
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
    def capability(scene, speed=10.0, mass=None):
        mass = float(scene.descriptor.physics['weight'] if mass is None else mass)
        return (('stock1513', mass, speed), mass, speed)

    def blocked(self, scene, capability=None, trace=None):
        return scene.battle._navigation_obstacle(
            (0, 0, 0), (0, 0, 10), 2.15, capability, trace)

    def test_stock_crushable_house_agrees_with_direction_probe(self):
        with self.fixture.scene(registered=True) as scene:
            capability = self.capability(scene)
            self.assertFalse(self.blocked(scene, capability))
            self.assertTrue(scene.battle._direction_probe(
                (0, 0, 0), 0, 0, scene.descriptor, 4.0,
                native_capability=capability)['clear'])

    def test_forward_and_reverse_planning_share_destructible_clearance(self):
        with self.fixture.scene(registered=True, health=120.0) as scene:
            forward = self.capability(scene, 20.0)
            reverse = self.capability(scene, -10.0)
            self.assertFalse(self.blocked(scene, forward))
            self.assertFalse(self.blocked(scene, reverse))
            for capability, expected in ((forward, True), (reverse, True)):
                # The world ray is identical; the hull's requested gear differs.
                result = scene.battle._direction_probe(
                    (0, 0, 0), 0, 0, scene.descriptor, 4.0,
                    native_capability=capability)
                self.assertEqual(expected, result['clear'])

    def test_siege_planner_uses_the_same_mounted_travel_cap_as_contact(self):
        with self.fixture.scene(registered=True, health=120.0,
                                speed_cap=5.0 / 3.6) as scene:
            capability = self.capability(scene, 20.0)
            self.assertFalse(self.blocked(scene, capability))
            self.assertTrue(scene.battle._direction_probe(
                (0, 0, 0), 0, 0, scene.descriptor, 4.0,
                native_capability=capability)['clear'])

    def test_turning_and_reversing_do_not_treat_soft_house_as_hard_wall(self):
        from gui.mods.offline_lan_0922.ai.driver import LocalDriver

        # The house is behind the hull but ahead of the requested route. A
        # forward route first pivots toward it; a reverse recovery sees the
        # same route geometry even though physical crushing uses its gear.
        with self.fixture.scene(registered=True, health=120.0) as scene:
            samples = []

            def clear(yaw, maximum_distance=None, drive_direction=1.0):
                capability = self.capability(
                    scene, -10.0 if drive_direction < 0.0 else 20.0)
                sample = scene.battle._direction_probe(
                    (0, 0, 0), yaw, 0.0, scene.descriptor,
                    4.0 if maximum_distance is None else maximum_distance,
                    native_capability=capability)
                samples.append((yaw, drive_direction, sample))
                return bool(sample.get('clear') and not sample.get('deferred'))

            driver = LocalDriver()
            pivot = driver.drive(
                11, 0, (0, 0, 0), math.pi, 0.0, 0.1,
                (0, 0, 20), (), clear, stop_at_target=False)
            self.assertEqual(0.0, pivot['target_yaw'])
            self.assertEqual('drive', pivot['recovery_mode'])
            self.assertEqual(0.0, pivot['throttle'])
            self.assertTrue(samples[0][2]['clear'])
            self.assertGreater(samples[0][1], 0.0)
            aligned = driver.drive(
                11, 0, (0, 0, 0), 0.0, 0.0, 0.1,
                (0, 0, 20), (), clear, stop_at_target=False)
            self.assertGreater(aligned['throttle'], 0.0)

            recovery = LocalDriver()
            state = recovery._state(11, 0, (0, 0, 0))
            state.update(recovery_time=1.0, recovery_side=1.0)
            samples[:] = []
            command = recovery.drive(
                11, 0, (0, 0, 0), math.pi, 0.0, 0.1,
                (0, 0, 20), (), clear, stop_at_target=False)
            self.assertLess(samples[0][1], 0.0)
            self.assertTrue(samples[0][2]['clear'])
            self.assertLess(command['throttle'], 0.0)
            self.assertEqual('reverse_turn', command['recovery_mode'])

    def test_heavy_and_light_native_edges_have_identical_clearance(self):
        with self.fixture.scene(registered=True, health=150.0) as scene:
            nav = TerrainNavigator(lambda *unused: 0.0,
                scene.battle._navigation_obstacle,
                baked_graph=bot_fixture._flat_open_graph())
            start, goal = (0.0, 0.0, 0.0), (0.0, 0.0, 20.0)
            nav.grid.review_native_corridor(start, goal)
            heavy = self.capability(scene, 10.0, 29084.0)
            light = self.capability(scene, 10.0, 12110.0)
            scene.battle._soft_static_recast_budget[:] = [100]
            self.assertTrue(nav.grid.segment_clear(start, goal, heavy))
            self.assertTrue(nav.grid.segment_clear(start, goal, light))
            calls = len(scene.rays)
            self.assertTrue(nav.grid.segment_clear(start, goal, heavy))
            self.assertEqual(calls, len(scene.rays))

    def test_route_clearance_does_not_require_a_vehicle_capability(self):
        with self.fixture.scene(registered=True) as scene:
            for capability in (None, (), (('invalid',), 10000.0, 10.0),
                               (('stock1513', 0.0, 10.0), 0.0, 10.0)):
                self.assertFalse(self.blocked(scene, capability))

    def test_unknown_surface_and_backing_wall_remain_hard(self):
        for kwargs in ({'unknown': True}, {'backing_z': 3.0}):
            with self.subTest(kwargs=kwargs):
                with self.fixture.scene(registered=True, **kwargs) as scene:
                    self.assertTrue(self.blocked(scene, self.capability(scene)))

    def test_soft_prop_recast_preserves_already_felled_tree_filter(self):
        for accepted, replacement, backing in (
                (True, False, None), (False, False, None),
                (True, True, None), (True, False, 3.0)):
            with self.subTest(accepted=accepted, replacement=replacement,
                              backing=backing):
                with self.fixture.scene(registered=True, backing_z=backing) as scene:
                    sensor.g_offh_tree_state = {
                        'native_committed': {(77, 1)} if accepted else set()}
                    original = scene.bigworld.wg_collideSegment

                    def with_tree(space, start, end, flags, keep=None):
                        if abs(end.z - start.z) > 1e-8:
                            fraction = (1.0 - start.z) / (end.z - start.z)
                            if (0 <= fraction <= 1 and (keep is None or
                                    keep(87 if replacement else 71, 0, 1, 77))):
                                return (start + (end - start).scale(fraction),
                                        approach_fixture._Vector(0, 0, -1))
                        return original(space, start, end, flags, keep)

                    with mock.patch.object(scene.bigworld, 'wg_collideSegment',
                                           side_effect=with_tree):
                        self.assertEqual(not accepted or replacement or
                                         backing is not None,
                                         self.blocked(scene, trace={}))

    def test_unproved_catalog_contact_is_not_exempted(self):
        with self.fixture.scene(registered=True) as scene:
            with mock.patch.object(sensor, '_planning_catalog_candidate_1513',
                                   return_value=None):
                self.assertTrue(self.blocked(scene, self.capability(scene)))

    def test_recast_budget_defers_then_retries_without_destruction(self):
        with self.fixture.scene(registered=True) as scene:
            capability = self.capability(scene)
            scene.battle._soft_static_recast_budget = [0]
            before = len(scene.rays)
            self.assertEqual('deferred', self.blocked(scene, capability))
            self.assertEqual(1, len(scene.rays) - before)
            scene.battle._soft_static_recast_budget[0] = 24
            self.assertFalse(self.blocked(scene, capability))

    def test_cold_candidate_registration_shares_existing_budget(self):
        with self.fixture.scene() as scene:
            capability = self.capability(scene)
            scene.battle._soft_static_recast_budget = [0]
            self.assertEqual('deferred', self.blocked(scene, capability))
            self.assertNotIn((22, 0), getattr(sensor, 'g_offh_destr_instances', {}))
            scene.battle._soft_static_recast_budget[0] = 24
            self.assertFalse(self.blocked(scene, capability))
            self.assertIn((22, 0), sensor.g_offh_destr_instances)

    def test_trace_reuses_actual_ray_and_material_proof_without_more_queries(self):
        with self.fixture.scene(registered=True, health=120.0) as scene:
            capability = self.capability(scene)
            before = len(scene.rays)
            self.assertFalse(self.blocked(scene, capability))
            ordinary_queries = len(scene.rays) - before
            before = len(scene.rays)
            trace = {}
            self.assertFalse(self.blocked(scene, capability, trace))
            self.assertEqual(ordinary_queries, len(scene.rays) - before)
            self.assertEqual('soft', trace['classification'])
            self.assertEqual('proved_original_materials_only', trace['reason'])
            self.assertEqual(capability, trace['capability'])
            self.assertEqual((22, 0, 73), trace['objects'][0]['identity'])
            self.assertIn('bldaf_001_vhouse1.model', trace['objects'][0]['model'].lower())
            self.assertIn('hit', trace)
            self.assertIn('ray_start', trace)
            self.assertLessEqual(len(trace['objects']), 4)
            self.assertLessEqual(len(trace.get('native_surface_candidates', ())), 16)
            scene.battle._soft_static_recast_budget[:] = [0]
            trace = {}
            self.assertEqual('deferred', self.blocked(
                scene, self.capability(scene, 20.0), trace))
            self.assertEqual('deferred', trace['classification'])
            self.assertEqual('recast_budget', trace['reason'])

    def test_cached_path_survives_deferred_recheck_and_resumes_same_object(self):
        with self.fixture.scene(registered=True) as scene:
            capability = self.capability(scene)
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
                    return nav.next_target(27, start, goal, request, now,
                                           native_capability=capability)
                finally:
                    nav.end_frame()

            self.assertEqual(goal, target(0.0, 24))
            self.assertEqual(goal, target(0.1, 24))
            state = nav.bot_states[27]
            key = state['path_key']
            path = nav.paths[key]
            original_index = state['index']
            original_target = state['last_target']
            nav.grid.invalidate_native_review()
            for now in (13.0, 14.0, 27.0):
                self.assertEqual(start, target(now, 0))
                self.assertIs(path, nav.paths[key])
                self.assertFalse(nav.searches)
                self.assertEqual('pending', state['navigation_status'])
                self.assertEqual(original_index, state['index'])
                self.assertEqual(original_target, state['last_target'])
                self.assertEqual(0, state['macro_progress_replans'])
            self.assertEqual(goal, target(27.1, 24))
            self.assertIs(path, nav.paths[key])
            # Kinetic health is a physical contact detail and does not alter
            # the shared static road geometry or retire its cached path.
            cache = sys.modules['AreaDestructibles'].g_cache
            original = cache.getDescByFilename
            def hardened(name):
                value = copy.deepcopy(original(name))
                value['modules'][73]['health'] = 1000000.0
                return value
            with mock.patch.object(cache, 'getDescByFilename', side_effect=hardened):
                nav.grid.invalidate_native_review()
                self.assertEqual(goal, target(27.2, 24))
                self.assertIs(path, nav.paths.get(key))
