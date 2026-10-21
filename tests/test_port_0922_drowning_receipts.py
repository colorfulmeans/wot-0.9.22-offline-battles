"""Report 172717: observe water without changing the drowning rule."""
import json
import types
import unittest
from unittest import mock
import test_port_0922_battle_runtime as fixture


class DrowningReceiptTests(unittest.TestCase):
    def setUp(self):
        self.battle = fixture.BattleRuntime(fixture._runtime())
        self.entity = fixture._Vehicle(10, fixture._Descriptor(), fixture._Vector(),
                                      (0, 0, 0), {'health': 500})
        self.battle._runtime.bigworld.entities[10] = self.entity
        self.battle._worker_mode = True
        self.sender = mock.Mock(return_value=True)
        self.battle.client = types.SimpleNamespace(round_id=1,
            is_bot_authority=lambda: True, send_player_environment=self.sender)
        self.battle._records = {'player:1': dict(kind='player', network_id=1,
            engine_id=10, local=False, state=dict(health=500, alive=True,
            input_seq=12, x=0., y=0., z=0., yaw=0., pitch=0., roll=0.))}
        self.rows = []
        self.log = mock.patch.object(fixture.battle_runtime_module.native_input_diagnostics,
            'write_json_record', side_effect=lambda tag, row: self.rows.append((tag, row)))
        self.log.start()
        self.addCleanup(self.log.stop)

    def sample(self, depth=3.):
        self.battle._runtime.bigworld.wg_collideWater = mock.Mock(return_value=20.-depth)
        with mock.patch.object(fixture.battle_runtime_module.critical_damage,
                               'propose_drowning', return_value={'events': []}):
            return self.battle._publish_player_environment(.3, 1.)

    def test_receipt_contains_actual_ray_body_bounds_and_result_without_extra_query(self):
        self.assertTrue(self.sample())
        self.battle._runtime.bigworld.wg_collideWater.assert_called_once()
        row = next(row for tag, row in self.rows if row['stage']=='sample')
        proof = row['sample']
        self.assertEqual('water_hit', proof['water']['reason'])
        self.assertEqual(17., proof['water']['raw_distance'])
        self.assertEqual(3., proof['depth_above_bottom'])
        self.assertEqual(2, row['level'])
        self.assertAlmostEqual(1.6, proof['hull_height'])
        self.assertIn('body_pose', proof)
        self.assertIn('input_pose', proof)
        self.assertEqual(12, row['input_seq'])
        self.assertEqual(1, row['sample_seq'])
        self.assertEqual('ready', row['proposal_status'])
        json.dumps(self.rows)

    def test_proposal_failure_is_logged_and_water_envelope_is_unchanged(self):
        self.battle._runtime.bigworld.wg_collideWater = lambda *args: 17.
        with mock.patch.object(fixture.battle_runtime_module.critical_damage,
                'propose_drowning', side_effect=RuntimeError('native roster missing')):
            self.assertTrue(self.battle._publish_player_environment(.3, 1.))
        self.sender.assert_called_once_with([dict(player_id=1, input_seq=12, level=2)], 1)
        row=next(row for tag,row in self.rows if row['stage']=='sample')
        self.assertEqual('exception',row['proposal_status'])
        self.assertIn('native roster missing',row['proposal_error'])

    def test_missing_geometry_records_why_row_was_not_sent(self):
        self.entity.typeDescriptor.hull.hitTester.bbox = None
        self.assertTrue(self.sample())
        row=next(row for tag,row in self.rows if row['stage']=='sample')
        self.assertEqual('hull_geometry_unavailable',row['sample']['reason'])
        self.sender.assert_called_once_with([],1)
        self.battle._runtime.bigworld.wg_collideWater.assert_not_called()

    def test_native_water_exception_and_no_hit_remain_existing_safe_sentinel(self):
        for result in [None,-1.,RuntimeError('water failed')]:
            with self.subTest(result=result):
                probe=mock.Mock(side_effect=result) if isinstance(result,Exception) else mock.Mock(return_value=result)
                self.battle._runtime.bigworld.wg_collideWater=probe
                proof={}
                self.assertEqual(-1.,self.battle._water_depth((1.,2.,3.),proof))
                self.assertIn(proof['reason'],('native_water_exception','no_water_hit'))
                probe.assert_called_once()

    def test_missing_entity_pose_dead_and_sender_have_terminal_receipts(self):
        record=self.battle._records['player:1']
        cases=[('entity_unavailable',mock.patch.object(self.battle,'_server_entity',return_value=None)),
               ('pose_unavailable',mock.patch.object(self.battle,'_projectile_record_pose',return_value=None))]
        for reason,patch in cases:
            self.rows[:]=[];self.battle._drowning_diagnostics.clear()
            with patch:self.battle._publish_player_environment(.3,2.)
            self.assertTrue(any(row['reason']==reason for tag,row in self.rows))
        record['state']['alive']=False
        self.battle._publish_player_environment(.3,4.)
        self.assertTrue(any(row['reason']=='canonical_dead' for tag,row in self.rows))
        self.battle.client.send_player_environment=None
        self.assertFalse(self.battle._publish_player_environment(.3,6.))
        self.assertTrue(any(row['reason']=='sender_unavailable' for tag,row in self.rows))

    def test_send_failure_keeps_sequence_and_logs_recovery(self):
        self.sender.return_value=False
        self.assertFalse(self.sample())
        self.assertEqual(0,self.battle._player_environment_seq)
        self.assertTrue(any(row['reason']=='batch_not_sent' for tag,row in self.rows))
        self.sender.return_value=True
        self.assertTrue(self.sample())
        self.assertEqual(1,self.battle._player_environment_seq)
        self.assertTrue(any(row['reason']=='batch_sent' for tag,row in self.rows))

    def test_identical_logs_are_bounded_but_level_changes_are_immediate(self):
        for now in [1.,1.1,1.2]:self.battle._log_drowning('sample',1,now,'classified',level=2)
        self.assertEqual(1,len(self.rows))
        self.battle._log_drowning('sample',1,1.3,'classified',level=0)
        self.assertEqual(2,len(self.rows))
        self.battle._log_drowning('sample',1,3.4,'classified',level=0)
        self.assertEqual(3,len(self.rows))

    def test_failed_log_writer_cannot_change_sample_or_submission(self):
        with mock.patch.object(fixture.battle_runtime_module.native_input_diagnostics,
                'write_json_record',side_effect=RuntimeError('diagnostic sink')):
            self.assertTrue(self.sample())
        self.assertEqual(1,self.sender.call_count)


if __name__=='__main__':unittest.main()
