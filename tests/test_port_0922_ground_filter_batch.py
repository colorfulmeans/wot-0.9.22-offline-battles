import unittest
import sys
import types
from unittest import mock
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
from gui.mods import offline_lan_0922 as package


class GroundFilterBatchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(sensor.__dict__, {
            'g_offh_destr_runtime_space': 1, 'g_offh_destr_spatial_revision': 0,
            'g_offh_destr_contact_bins': {(0, 0): {(22, 7)}},
            'g_offh_tree_state': {'native_committed': set()},
            'g_offh_destr_spatial_mutation_batch': {}, 'g_offh_destr_broken_cache': {},
            'g_offh_destr_speculative': set()})
        patcher.start(); self.addCleanup(patcher.stop)

    def test_repeated_samples_in_one_column_share_filter_preparation(self):
        with mock.patch.object(sensor, '_live_broken_collision_filter_1513', return_value=object()) as prepare:
            batch = sensor.ground_filter_batch_1513(sensor.ground_collision_filter)
            self.assertIs(batch(1., 2.), batch(2., 3.))
        prepare.assert_called_once()

    def test_spatial_mutation_invalidates_the_operation_local_filter(self):
        with mock.patch.object(sensor, '_live_broken_collision_filter_1513', side_effect=lambda *args: object()):
            batch = sensor.ground_filter_batch_1513(sensor.ground_collision_filter)
            before = batch(1., 2.)
            sensor.g_offh_destr_spatial_revision += 1
            self.assertIsNot(before, batch(1., 2.))

    def test_unpublished_mutations_cannot_reuse_a_stale_member_set(self):
        with mock.patch.object(sensor, '_live_broken_collision_filter_1513', side_effect=lambda *args: object()):
            batch = sensor.ground_filter_batch_1513(sensor.ground_collision_filter)
            before = batch(1., 2.)
            sensor.g_offh_destr_spatial_mutation_batch = {'bin_keys': {(0, 0)}}
            after = batch(1., 2.)
            self.assertIsNot(before, after)
            self.assertIsNot(after, batch(1., 2.))

    def test_accepted_destruction_is_live_even_with_a_shared_callback(self):
        keys = set()
        authority = types.ModuleType('gui.mods.offline_lan_0922.destructibles_authority')
        authority.destroyed_keys = lambda chunk: keys
        with mock.patch.dict(sys.modules, {authority.__name__: authority}), \
                mock.patch.object(package, 'destructibles_authority', authority, create=True):
            batch = sensor.ground_filter_batch_1513(sensor.ground_collision_filter)
            callback = batch(1., 2.)
            self.assertTrue(callback(73, 0, 7, 22))
            keys.add((7, None))
            self.assertIs(callback, batch(2., 3.))
            self.assertFalse(callback(73, 0, 7, 22))
            self.assertTrue(callback(105, 8, 700, 500))

    def test_custom_provider_retains_its_original_call_path(self):
        self.assertIsNone(sensor.ground_filter_batch_1513(lambda x, z: None))

    def test_distinct_world_operations_share_preparation_only_inside_update(self):
        with mock.patch.object(sensor, '_live_broken_collision_filter_1513', side_effect=lambda *args: object()):
            with sensor.collision_preparation_scope_1513():
                a = sensor.ground_filter_batch_1513(sensor.ground_collision_filter)(1., 2.)
                b = sensor.ground_filter_batch_1513(sensor.ground_collision_filter)(2., 3.)
                self.assertIs(a, b)
                sensor.g_offh_destr_spatial_revision += 1
                c = sensor.ground_filter_batch_1513(sensor.ground_collision_filter)(2., 3.)
                self.assertIsNot(a, c)
            self.assertIsNot(c, sensor.ground_filter_batch_1513(sensor.ground_collision_filter)(2., 3.))

    def test_scope_restores_outer_preparation_after_exception(self):
        with sensor.collision_preparation_scope_1513():
            outer = sensor.g_offh_destr_collision_preparation_scope
            with self.assertRaises(ValueError):
                with sensor.collision_preparation_scope_1513():
                    self.assertIsNot(outer, sensor.g_offh_destr_collision_preparation_scope)
                    raise ValueError('interrupted update')
            self.assertIs(outer, sensor.g_offh_destr_collision_preparation_scope)
        self.assertIsNone(sensor.g_offh_destr_collision_preparation_scope)

    def test_horizontal_sweeps_in_the_same_bins_share_the_live_filter(self):
        point = lambda x, z: types.SimpleNamespace(x=x, z=z)
        with mock.patch.dict(sensor.__dict__, {'_destructible_catalog': {}}), \
                mock.patch.object(sensor, '_contact_members_for_bounds_1513', return_value={(22, 7)}) as members, \
                mock.patch.object(sensor, '_live_broken_collision_filter_1513', side_effect=lambda *args: object()):
            with sensor.collision_preparation_scope_1513():
                first = sensor.prepare_horizontal_collision_filter(point(.1, .2), point(7.8, 7.9))
                second = sensor.prepare_horizontal_collision_filter(point(.2, .3), point(7.7, 7.8))
                self.assertIs(first, second)
                members.assert_called_once()
                sensor.g_offh_destr_spatial_revision += 1
                self.assertIsNot(first, sensor.prepare_horizontal_collision_filter(point(.1, .2), point(7.8, 7.9)))

    def test_horizontal_scope_rejects_dirty_overlapping_bins_and_replaced_trees(self):
        point = lambda x, z: types.SimpleNamespace(x=x, z=z)
        with mock.patch.dict(sensor.__dict__, {'_destructible_catalog': {}}), \
                mock.patch.object(sensor, '_contact_members_for_bounds_1513', return_value={(22, 7)}), \
                mock.patch.object(sensor, '_live_broken_collision_filter_1513', side_effect=lambda *args: object()):
            with sensor.collision_preparation_scope_1513():
                first = sensor.prepare_horizontal_collision_filter(point(1, 1), point(2, 2))
                sensor.g_offh_destr_spatial_mutation_batch = {'bin_keys': {(99, 99)}}
                self.assertIs(first, sensor.prepare_horizontal_collision_filter(point(1, 1), point(2, 2)))
                sensor.g_offh_destr_spatial_mutation_batch = {'bin_keys': {(0, 0)}}
                self.assertIsNot(first, sensor.prepare_horizontal_collision_filter(point(1, 1), point(2, 2)))
                sensor.g_offh_destr_spatial_mutation_batch = {}
                sensor.g_offh_tree_state['native_committed'] = {(50, 9)}
                self.assertIsNot(first, sensor.prepare_horizontal_collision_filter(point(1, 1), point(2, 2)))

    def test_empty_tree_ledger_stays_live_in_an_existing_filter(self):
        trees = set()
        authority = types.ModuleType('gui.mods.offline_lan_0922.destructibles_authority')
        authority.destroyed_keys = lambda chunk: set()
        with mock.patch.dict(sys.modules, {authority.__name__: authority}), \
                mock.patch.object(package, 'destructibles_authority', authority, create=True):
            callback = sensor._live_broken_collision_filter_1513({(22, 7)}, trees)
            self.assertTrue(callback(71, 0, 9, 50))
            trees.add((50, 9))
            self.assertFalse(callback(71, 0, 9, 50))
            self.assertTrue(callback(87, 0, 9, 50))
