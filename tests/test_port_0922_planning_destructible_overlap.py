"""Airfield report geometry through the planning-only original-surface filter.

Catalog placements and probe rays are from report 20260922-153100. Native
callback ordering and ray hits are controlled; no Windows execution claimed.
"""
import copy
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import test_port_0922_bot_destructible_approach as approach_fixture
import test_port_0922_destructibles as fixture
from test_port_0922_destructibles import _Vector
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor


class PlanningDestructibleOverlapTests(unittest.TestCase):
    def setUp(self):
        self.cleanup = fixture.DestructiblesCompatibilityTests()
        self.cleanup.setUp()
        self.addCleanup(self.cleanup.tearDown)
        sensor.xrange = range

    def replay(self, case=0, blocker=None, budget=24,
               retained_index=None, absent_index=None, cold_index=None):
        catalog = json.loads((Path(__file__).resolve().parents[1] /
                              'destructibles/31_airfield.json').read_text())
        sensor.set_catalog(catalog)
        cases = (
            ((31869, 135), (31869, 104),
             (-279.5202941894531, .7200000286102295, -192.47972106933594),
             (-275.5202941894531, .8410000205039978, -188.47972106933594),
             (-279.2751770019531, .7274150252342224, -192.23460388183594)),
            ((31869, 80), (31869, 84),
             (-275.8500061035156, .7200000286102295, -170.0),
             (-275.8500061035156, .7200000286102295, -166.0),
             (-275.8500061035156, .7200000286102295, -169.78829956054688)),
        )
        first, overlapping, raw_start, raw_end, raw_hit = cases[case]
        # Represent the live-validated registry; geometry is the exact shipped
        # placement, not enlarged/nearby boxes invented to make the ray pass.
        sensor.g_offh_destr_instances = instances = {}
        sensor.g_offh_destr_contact_bins = bins = {}
        for identity in (first, overlapping):
            if cold_index is not None and identity == (
                    first, overlapping)[cold_index]:
                continue
            instances[identity] = copy.deepcopy(
                sensor._destructible_catalog['baked_instances'][identity])
            sensor._index_catalog_instance_1513(bins, identity, instances[identity])
        if retained_index is not None:
            identity = (first, overlapping)[retained_index]
            name = instances[identity]['filename']
            sensor._destructible_catalog['resources'][name][
                'retained_collision_boxes'] = frozenset((0,))
        start, end, point = map(lambda value: _Vector(*value),
                                (raw_start, raw_end, raw_hit))
        normal = _Vector(0, 0, -1)
        hit = (point, normal)
        candidates = sensor._catalog_candidate_on_ray_1513(
            point, start, end, allow_overlaps=True)
        self.assertEqual(set(instances), set(row[:2] for row in candidates))
        if cold_index is None:
            self.assertIsNone(sensor._catalog_candidate_on_ray_1513(point, start, end))
        query = mock.Mock()
        registrations = []

        def register(space, identity):
            self.assertIsNotNone(cold_index)
            self.assertEqual((first, overlapping)[cold_index], identity)
            registrations.append(identity)
            instances[identity] = copy.deepcopy(
                sensor._destructible_catalog['baked_instances'][identity])
            sensor._index_catalog_instance_1513(bins, identity, instances[identity])
            return instances[identity]

        def collide(space, ray_start, ray_end, flags, keep):
            # The arbitrary first callback is NOT the nearest returned hit.
            keep(107, 8, 57880, 1759484)
            for chunk, item in (overlapping, first):
                if absent_index is not None and (chunk, item) == (
                        first, overlapping)[absent_index]:
                    continue
                if keep(73, 0, item, chunk):
                    return hit
            if blocker is not None and keep(*blocker):
                return hit  # A hard surface inside both props' OBBs survives.
            return None

        query.side_effect = collide
        trace = {}
        with mock.patch.dict(sys.modules, {
                'BigWorld': types.SimpleNamespace(wg_collideSegment=query)}), \
                mock.patch.object(sensor, '_stock_crushable_1513',
                                  side_effect=AssertionError('planning used kinetics')), \
                mock.patch.object(sensor, '_stream_baked_shot_instance_1513',
                                  side_effect=register), \
                mock.patch.object(sensor, '_get_destr_authority',
                                  return_value=types.SimpleNamespace(
                                      is_destroyed=lambda *args: False,
                                      destroyed_keys=lambda *args: ())):
            result = sensor._catalog_soft_static_path(
                1, start, end, hit, 0.0, None,
                recast_budget=[budget], trace=trace, ignore_destructibles=True)
        query.registrations = registrations
        return result, trace, query

    def test_report_stove_fence_overlaps_are_shared_route_geometry(self):
        for case in (0, 1):
            with self.subTest(case=case):
                result, trace, query = self.replay(case)
                self.assertIs(True, result)
                self.assertEqual('soft', trace['classification'])
                self.assertEqual(2, len(trace['objects']))
                self.assertEqual(1, query.call_count)

    def test_hard_wall_inside_overlapping_boxes_is_not_skipped(self):
        for blocker in ((107, 8, 57880, 1759484), (5, 0, 999, 31869)):
            with self.subTest(blocker=blocker):
                result, trace, query = self.replay(blocker=blocker)
                self.assertIs(False, result)
                self.assertEqual('unidentified_backing_surface', trace['reason'])
                self.assertEqual(1, query.call_count)

    def test_destroyed_replacement_with_same_identity_stays_solid(self):
        result, trace, unused = self.replay(blocker=(87, 0, 135, 31869))
        self.assertIs(False, result)
        self.assertEqual('unidentified_backing_surface', trace['reason'])

    def test_permanent_replacement_base_still_blocks_the_route(self):
        result, trace, unused = self.replay(retained_index=0)
        self.assertIs(False, result)
        self.assertEqual('retained_destructible_collision', trace['reason'])

    def test_overlapping_retained_box_without_native_surface_does_not_veto(self):
        result, trace, unused = self.replay(retained_index=1, absent_index=1)
        self.assertIs(True, result)
        self.assertEqual('soft', trace['classification'])

    def test_registered_retained_box_does_not_hide_cold_fragile_candidate(self):
        result, trace, query = self.replay(
            retained_index=1, absent_index=1, cold_index=0)
        self.assertIs(True, result)
        self.assertEqual('soft', trace['classification'])
        self.assertEqual([(31869, 135)], query.registrations)
        self.assertEqual(1, query.call_count)

    def test_mixed_cold_overlap_defers_when_registration_budget_is_empty(self):
        result, trace, query = self.replay(
            retained_index=1, absent_index=1, cold_index=0, budget=0)
        self.assertEqual('deferred', result)
        self.assertEqual('identity_proof_deferred', trace['reason'])
        self.assertFalse(query.registrations)
        query.assert_not_called()

    def test_no_recast_budget_is_deferred_not_a_cached_hard_wall(self):
        result, trace, query = self.replay(budget=0)
        self.assertEqual('deferred', result)
        self.assertEqual('recast_budget', trace['reason'])
        query.assert_not_called()

    def test_planning_ignores_kinetics_but_physical_default_does_not(self):
        approach = approach_fixture.BotDestructibleApproachTests()
        approach.setUp()
        self.addCleanup(approach.doCleanups)
        with approach.scene(registered=True, health=1000000.0) as scene:
            start, end = _Vector(0, .7, 0), _Vector(0, .7, 10)
            hit = scene.bigworld.wg_collideSegment(1, start, end, 0)
            self.assertIs(False, sensor._catalog_soft_static_path(
                1, start, end, hit, 0.0, scene.descriptor))
            self.assertIs(True, sensor._catalog_soft_static_path(
                1, start, end, hit, 0.0, scene.descriptor,
                ignore_destructibles=True))

    def test_planning_ground_removes_even_low_destructible_roofs(self):
        approach = approach_fixture.BotDestructibleApproachTests()
        approach.setUp()
        self.addCleanup(approach.doCleanups)
        with approach.scene(registered=True, health=1000000.0) as scene:
            start, end = _Vector(0, 10, 4), _Vector(0, -2, 4)
            hit = scene.bigworld.wg_collideSegment(1, start, end, 0)
            support = sensor.planning_support_below_soft_roof(
                1, start, end, hit, 10.0, 0.0, None,
                recast_budget=[24], ignore_destructibles=True)
            self.assertAlmostEqual(0.0, support[0].y)

    def test_planning_ground_recast_keeps_the_felled_tree_filter(self):
        approach = approach_fixture.BotDestructibleApproachTests()
        approach.setUp()
        self.addCleanup(approach.doCleanups)
        with approach.scene(registered=True) as scene:
            sensor.g_offh_tree_state = {'native_committed': {(77, 1)}}
            original = scene.bigworld.wg_collideSegment

            def with_tree(space, start, end, flags, keep=None):
                hit = original(space, start, end, flags, keep)
                if abs(end.y - start.y) > 1e-8:
                    fraction = (2.0 - start.y) / (end.y - start.y)
                    if (0 <= fraction <= 1 and
                            (keep is None or keep(71, 0, 1, 77))):
                        point = start + (end - start).scale(fraction)
                        if hit is None or (point-start).length < (hit[0]-start).length:
                            return point, _Vector(0, 1, 0)
                return hit

            with mock.patch.object(scene.bigworld, 'wg_collideSegment',
                                   side_effect=with_tree):
                self.assertAlmostEqual(0.0, scene.battle._navigation_ground(0, 4, 0))


if __name__ == '__main__':
    unittest.main()
