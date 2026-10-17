"""Synchronous preparation reuse must not cache physical world results."""
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixtures
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
from gui.mods.offline_lan_0922 import native_destructibles as geometry


class WorkerQueryReuseTests(unittest.TestCase):
    def test_support_columns_share_live_member_preparation_in_the_worker_scope(self):
        battle = fixtures.BattleRuntime(fixtures._runtime())
        battle._destructibles = sensor
        callback = mock.Mock(return_value=True)
        with mock.patch.dict(sensor.__dict__, {
                'g_offh_destr_runtime_space': 1,
                'g_offh_destr_spatial_revision': 0,
                'g_offh_destr_contact_bins': {(0, 0): {(22, 7)}},
                'g_offh_tree_state': {'native_committed': set()},
                'g_offh_destr_spatial_mutation_batch': {}}), mock.patch.object(
                sensor, '_live_broken_collision_filter_1513', return_value=callback) as prepare:
            with sensor.collision_preparation_scope_1513():
                for index in range(100):
                    self.assertIs(callback,battle._ground_filter_impl(1.+index*.001,2.))
                self.assertEqual(1,prepare.call_count)
                sensor.g_offh_destr_spatial_revision += 1
                self.assertIs(callback,battle._ground_filter_impl(1.,2.))
                self.assertEqual(2,prepare.call_count)
            with sensor.collision_preparation_scope_1513():
                battle._ground_filter_impl(1.,2.)
            self.assertEqual(3,prepare.call_count)

    def test_custom_ground_provider_keeps_its_original_calls(self):
        battle = fixtures.BattleRuntime(fixtures._runtime())
        provider = mock.Mock(return_value=None)
        battle._destructibles = types.SimpleNamespace(
            ground_collision_filter=provider,
            ground_filter_batch_1513=sensor.ground_filter_batch_1513)
        for index in range(10):
            self.assertIsNone(battle._ground_filter_impl(1.,2.))
        self.assertEqual(10,provider.call_count)

    def test_only_identical_pure_chunk_mapping_is_reused(self):
        owner = mock.Mock()
        owner.query.return_value = (22,22,())
        area = types.SimpleNamespace(chunkIDFromPosition=mock.Mock())
        p = types.SimpleNamespace(x=1.,y=2.,z=3.)
        with mock.patch.object(geometry,'_chunk_mapper_1513',return_value=True), \
                mock.patch.object(geometry,'_get',return_value=owner), \
                mock.patch.dict(sensor.__dict__,{'g_offh_destr_runtime_space':1}):
            with sensor.collision_preparation_scope_1513():
                for index in range(100):
                    self.assertEqual((22,22,()),geometry.neighbourhood(
                        sensor,area,p,0.,1.,0.,True))
                self.assertEqual(1,owner.query.call_count)
                p.x += .001
                geometry.neighbourhood(sensor,area,p,0.,1.,0.,True)
                geometry.neighbourhood(sensor,area,p,0.,1.,-1.,True)
                sensor.g_offh_destr_runtime_space=2
                geometry.neighbourhood(sensor,area,p,0.,1.,-1.,True)
                self.assertEqual(4,owner.query.call_count)
            geometry.neighbourhood(sensor,area,p,0.,1.,-1.,True)
            self.assertEqual(5,owner.query.call_count)

    def test_unavailable_mapping_is_retried_in_the_same_scope(self):
        owner = mock.Mock()
        owner.query.side_effect = [None,(22,22,())]
        area = types.SimpleNamespace(chunkIDFromPosition=mock.Mock())
        with mock.patch.object(geometry,'_chunk_mapper_1513',return_value=True), \
                mock.patch.object(geometry,'_get',return_value=owner):
            with sensor.collision_preparation_scope_1513():
                self.assertIsNone(geometry.neighbourhood(sensor,area,(0.,0.,0.),0.,1.,0.,True))
                self.assertEqual((22,22,()),geometry.neighbourhood(sensor,area,(0.,0.,0.),0.,1.,0.,True))
        self.assertEqual(2,owner.query.call_count)

    def test_landing_receipts_correlate_events_without_changing_submissions(self):
        battle = fixtures.BattleRuntime(fixtures._runtime())
        entity = types.SimpleNamespace(typeDescriptor=types.SimpleNamespace(maxHealth=7000))
        battle._clock = mock.Mock(side_effect=[1.,1.04])
        with mock.patch.object(fixtures.battle_runtime_module.native_input_diagnostics,
                               'write_json_record') as write:
            first = battle._apply_fall_damage(entity,18.641)
            second = battle._apply_fall_damage(entity,11.711)
        self.assertGreater(first,second)
        self.assertEqual([18.641,11.711],battle._pending_landing_impacts)
        rows=[call.args[1] for call in write.call_args_list
              if call.args[0]=='PLAYER LANDING IMPACT']
        self.assertEqual([1,2],[row['diagnostic_sequence'] for row in rows])
        self.assertAlmostEqual(40.,rows[1]['previous_gap_ms'])
        self.assertEqual(first,rows[1]['previous_impact']['damage'])


if __name__ == '__main__':
    unittest.main()
