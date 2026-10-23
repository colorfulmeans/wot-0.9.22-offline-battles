"""Capture the unproved native boundary without changing a physical result."""
import copy
import contextlib
import io
import json
from pathlib import Path
import types
import unittest
from unittest import mock
import test_port_0922_drowning_receipts as water_fixture
from gui.mods.offline_lan_0922 import physics_audit, vehicle_physics as vp
from gui.mods.offline_lan_0922.worker_diagnostics import WorkerCombatDiagnostics


class NativeWaterContextTests(water_fixture.DrowningReceiptTests):
    def test_native_miss_has_complete_secondary_results_but_sends_original_level(self):
        world = self.battle._runtime.bigworld
        world.graphicsSettings = lambda: [('RENDER_PIPELINE', 1), ('WATER_QUALITY', 3)]
        world.wg_collideWater = mock.Mock(side_effect=[-1., -1., 201.])
        self.assertTrue(self.battle._publish_player_environment(.3, 1.))
        self.sender.assert_called_once_with([dict(player_id=1, input_seq=12, level=0)], 1)
        row = next(row for tag, row in self.rows if row['reason']=='observation_ready')
        env = row['query_environment']
        self.assertEqual('diagnostic_only', env['scope'])
        self.assertEqual({'RENDER_PIPELINE':1, 'WATER_QUALITY':3}, env['graphics'])
        self.assertEqual([-1.,201.], [p['raw_distance'] for p in env['probes']])
        self.assertEqual(3, world.wg_collideWater.call_count)
        self.assertEqual(-1., row['sample']['water']['raw_distance'])
        json.dumps(self.rows)

    def test_suppressed_log_does_not_repeat_secondary_rays(self):
        world = self.battle._runtime.bigworld
        world.wg_collideWater = mock.Mock(return_value=-1.)
        self.battle._publish_player_environment(.3, 1.)
        self.assertEqual(3, world.wg_collideWater.call_count)
        self.battle._publish_player_environment(.3, 1.3)
        self.assertEqual(4, world.wg_collideWater.call_count)
        self.battle._publish_player_environment(.3, 3.1)
        self.assertEqual(7, world.wg_collideWater.call_count)

    def test_secondary_errors_do_not_drop_original_observation(self):
        world = self.battle._runtime.bigworld
        world.wg_collideWater = mock.Mock(side_effect=[-1.,RuntimeError('reverse'),RuntimeError('wide')])
        self.assertTrue(self.battle._publish_player_environment(.3, 1.))
        row = next(row for tag,row in self.rows if row['reason']=='observation_ready')
        self.assertEqual(['exception','exception'], [p['status'] for p in row['query_environment']['probes']])
        self.assertEqual(0,row['level'])

    def test_context_contains_engine_camera_and_avatar_space_without_native_objects(self):
        world=types.SimpleNamespace(player=lambda:types.SimpleNamespace(id=-1,spaceID=3,position=(5,6,7)),
            camera=lambda:types.SimpleNamespace(position=(8,9,10)),graphicsSettings=lambda:[],
            entity=lambda ident:types.SimpleNamespace(spaceID=4,position=(11,12,13)))
        row=physics_audit.water_context(world,types.SimpleNamespace(spaceID=3),(1,2,3),tuple,entity_id=1000)
        self.assertEqual(3,row['avatar_space'])
        self.assertEqual((8.,9.,10.),row['camera_position'])
        self.assertEqual([],row['errors'])
        self.assertEqual(4,row['sample_entity']['space'])
        json.dumps(row)

    def test_missing_worker_sample_entity_is_an_expected_diagnostic_status(self):
        world=types.SimpleNamespace(player=lambda:types.SimpleNamespace(id=-1,spaceID=3,position=(5,6,7)),
            camera=lambda:types.SimpleNamespace(position=(8,9,10)),graphicsSettings=lambda:[],
            entity=lambda ident:None)
        row=physics_audit.water_context(world,types.SimpleNamespace(spaceID=3),(1,2,3),tuple,entity_id=1000)
        self.assertEqual(dict(id=1000,status='not_present'),row['sample_entity'])
        self.assertEqual([],row['errors'])
        self.assertEqual(3,row['avatar_space'])
        json.dumps(row)


class SupportProjectionAuditTests(unittest.TestCase):
    def setUp(self):
        self.row=json.loads((Path(__file__).parent/'fixtures/report182526-edge-input.json').read_text())

    def test_recorded_solver_replay_locates_the_projection_without_changing_it(self):
        q=self.row['input']; frozen=copy.deepcopy(q)
        stages=[]
        plain=vp._reference_damper_suspension_step(q['params'],q['state'],q['ground'],q['dt'],
            q['pseudo_ground'],q['support_vertical_speed'])
        traced=vp._reference_damper_suspension_step(q['params'],q['state'],q['ground'],q['dt'],
            q['pseudo_ground'],q['support_vertical_speed'],diagnostics=stages)
        self.assertEqual(plain,traced)
        self.assertEqual(frozen,q)
        first=stages[0]
        self.assertGreater(first['projection_delta']['height'],1.5)
        iterations=first['constraint_iterations']
        self.assertTrue(any(row.get('selected') for row in iterations))
        self.assertEqual('residual_heave',iterations[-1]['terminal'])
        self.assertTrue(all('denominator' in hit and 'key' in hit for row in iterations
            for hit in row.get('selected',[])))
        json.dumps(stages)

    def test_contact_rows_distinguish_origin_plane_from_real_contact_location(self):
        q=self.row['input']
        proof=vp.suspension_contact_receipt(q['params'],q['state'],q['ground'],q['pseudo_ground'],
            self.row['position'],self.row['yaw'],self.row['previous_plane'])
        pseudo=next(r for r in proof['constraints'] if r['family']=='pseudo' and r['index']==17)
        self.assertGreater(pseudo['penetration'],1.6)
        self.assertLess(pseudo['point_plane_residual'],-2.9)
        self.assertNotEqual(pseudo['point_plane_height'],pseudo['origin_plane_height'])
        json.dumps(proof)

    def test_sparse_capture_contains_measured_inner_stages_and_finishes_all_windows(self):
        ticks=iter(i*.001 for i in range(100000))
        trace=WorkerCombatDiagnostics.audit_sample(lambda:next(ticks))
        self.assertEqual((32,3,30.),(trace.detail_stride,trace.maximum_captures,trace.cooldown_seconds))
        selected=0
        for frame in range(1,100):
            trace.begin_frame(frame,frame*.1,'audit')
            trace.begin_control()
            if trace.detail_active:selected+=1
            trace.actor(9);trace.phase('bot.motion_plan');trace.phase('bot.integrate')
            trace.actor(None);trace.finish_frame()
        self.assertGreater(selected,0)
        self.assertLess(selected,10)
        complete=[]
        for frame,now in enumerate((31.,62.,93.,124.,155.,186.,217.),100):
            trace.begin_frame(frame,now,'audit');trace.begin_control();trace.finish_frame()
            complete.extend(trace.drain_completed())
        self.assertEqual(3,len(complete))
        self.assertFalse(trace.active)
        self.assertTrue(complete[0]['actors'])

    def test_stall_episode_survives_owner_changes_and_closes_on_real_departure(self):
        command=dict(combat_mode='route',move_position=(3.,0.,4.))
        driver=dict(recovery_count=13,objective_progress=dict(credit_reason='new_best_alignment'))
        row=physics_audit.motion_episode(None,(0.,0.,0.),1.,command,driver)
        frozen=copy.deepcopy(row)
        second=physics_audit.motion_episode(row,(1.,0.,1.),4.,dict(command,combat_mode='engage'),driver)
        self.assertEqual(frozen,row)
        self.assertEqual(1.,second['started'])
        self.assertEqual(['route','engage'],[r['mode'] for r in second['transitions']])
        for index in range(40):
            second=physics_audit.motion_episode(second,(1.,0.,1.),5.+index,command,driver)
        self.assertEqual(32,len(second['transitions']))
        self.assertGreater(second['dropped'],0)
        departed=physics_audit.motion_episode(second,(20.,0.,0.),50.,command,driver)
        self.assertEqual(50.,departed['started'])
        self.assertEqual('left_diagnostic_pocket',departed['previous_terminal']['terminal'])
        json.dumps(departed)

    def test_motion_episode_failure_cannot_interrupt_final_motion_receipt(self):
        import test_port_0922_complete_navigation_receipts as fixture
        f=fixture.RuntimeReceiptTests();f.setUp()
        try:
            runtime=f.runtime;state=runtime.states[11]
            state['_motion_stall_log']=((state['x'],state['y'],state['z']),-10.)
            output=io.StringIO()
            with contextlib.redirect_stdout(output), mock.patch.object(physics_audit,
                    'motion_episode',side_effect=RuntimeError('diagnostic failure')):
                runtime._log_motion_stall(state,{},0.,0.,False,{},3.)
                runtime._finish_motion_stall(state,False,False,
                    (state['x'],state['y'],state['z']),3.)
            self.assertIn('diagnostic failure',output.getvalue())
            self.assertIn('after_contacts_and_support',output.getvalue())
        finally:
            f.tearDown()


if __name__=='__main__': unittest.main()
