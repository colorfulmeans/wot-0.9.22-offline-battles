"""Final-pose support ownership and reproducible full-support diagnostics."""
import contextlib
import copy
import io
import json
import unittest
from unittest import mock

import test_port_0922_contact_support_navigation as fixtures
import test_port_0922_vehicle_physics as physics_fixture
from gui.mods.offline_lan_0922 import vehicle_physics as vp


class SupportReplayTests(unittest.TestCase):
    scene = fixtures.ContactSupportTests.scene

    def test_runtime_defers_release_through_translation_and_contact_corrections(self):
        fixture=fixtures.bots.BotRuntimeTests()
        fixture.setUp()
        try:
            runtime=fixture.runtime
            runtime.battle_start(fixture.start)
            state=runtime.states[11]
            state.update(x=0.,y=0.,z=0.,grounded_once=True,
                _edge_support_active=True,airborne=False)
            runtime._physics_ground_probe=lambda x,z,h:0. if x>=0. else -8.
            events=[]
            original=runtime._release_detailed_support
            def vertical(body,*args,**kwargs):
                if args[0]>0.:
                    body['x']=3.
                self.assertTrue(body['_support_release_after_contacts'])
                self.assertFalse(original(body))
                events.append('provisional')
                return False
            def contacts(*args):
                state['x']=0.
                self.assertTrue(state['_support_release_after_contacts'])
                events.append('contacts')
                return []
            def release(body):
                self.assertNotIn('_support_release_after_contacts',body)
                events.append('final_release')
                return original(body)
            with mock.patch.object(runtime,'_update_vertical_motion',side_effect=vertical), \
                 mock.patch.object(runtime,'_guard_realised_pose',return_value=False), \
                 mock.patch.object(runtime,'_resolve_tank_contacts',side_effect=contacts), \
                 mock.patch.object(runtime,'_release_detailed_support',side_effect=release), \
                 contextlib.redirect_stdout(io.StringIO()):
                runtime.update(.04,1.)
            self.assertIn('final_release',events)
            self.assertLess(events.index('contacts'),events.index('final_release'))
            self.assertTrue(state['_edge_support_active'])
            self.assertNotIn('_support_release_after_contacts',state)
        finally:
            fixture.tearDown()

    def test_provisional_five_points_cannot_close_before_final_contact_pose(self):
        runtime,state=self.scene(lambda x,z:0. if x>=0. else -8.)
        state.update(x=3.,_edge_support_active=True,
                     _support_release_after_contacts=True,airborne=False)
        with mock.patch.object(runtime,'_basic_support_status',
                side_effect=AssertionError('provisional release queried ground')):
            self.assertFalse(runtime._release_detailed_support(state))
        # Contact correction returns the body to the lip, matching report 151509.
        state['x']=0.
        state.pop('_support_release_after_contacts')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(runtime._release_detailed_support(state))
        self.assertTrue(state['_edge_support_active'])
        self.assertLess(sum(p['valid'] for p in runtime._basic_support_status(state)),5)

    def test_final_five_points_close_and_preserve_the_realised_pose_and_velocity(self):
        runtime,state=self.scene(lambda x,z:0.)
        state.update(_edge_support_active=True,airborne=False,
                     speed=2.,vertical_speed=-.1)
        expected={k:state[k] for k in ('x','y','z','yaw','speed','vertical_speed')}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(runtime._release_detailed_support(state))
        self.assertFalse(state.get('_edge_support_active',False))
        self.assertEqual(expected,{k:state[k] for k in expected})

    def test_full_numeric_replay_survives_json_and_separates_force_from_projection(self):
        params=vp.derive_suspension_params(physics_fixture.VehiclePhysicsSuspensionTrialTests._exact_client_descriptor())
        before=physics_fixture.VehiclePhysicsSuspensionTrialTests._state(height=-.2,pitch=.2,roll=-.4,vertical_velocity=-2.)
        ground,pseudo=physics_fixture.VehiclePhysicsSuspensionTrialTests._plane_samples(params)
        actual=vp._reference_damper_suspension_step(params,before,ground,.04,pseudo)
        snapshot=copy.deepcopy((params,before,ground,pseudo,actual))
        with mock.patch.object(vp,'_native_suspension_step',
                side_effect=AssertionError('diagnostic native query')):
            receipt=vp.suspension_replay_receipt(params,before,ground,.04,pseudo,0.,actual)
        self.assertTrue(receipt['terminal_matches'])
        self.assertTrue(receipt['stages'])
        restored=json.loads(json.dumps(receipt))
        inp=restored['input']
        replay=vp._reference_damper_suspension_step(inp['params'],inp['state'],
            inp['ground'],inp['dt'],inp['pseudo_ground'],inp['support_vertical_speed'])
        self.assertEqual(actual,replay)
        for row in receipt['stages']:
            for key in vp._SUSPENSION_RESULT_KEYS[:6]:
                self.assertAlmostEqual(row['projected'][key]-row['free'][key],
                                       row['projection_delta'][key])
        self.assertEqual(snapshot,(params,before,ground,pseudo,actual))

    def test_diagnostic_replay_disagreement_is_visible_and_never_replaces_actual(self):
        params=vp.derive_suspension_params(physics_fixture.VehiclePhysicsSuspensionTrialTests._exact_client_descriptor())
        before=physics_fixture.VehiclePhysicsSuspensionTrialTests._state();g,p=physics_fixture.VehiclePhysicsSuspensionTrialTests._plane_samples(params)
        actual=vp._reference_damper_suspension_step(params,before,g,.02,p)
        actual['height']+=1.
        receipt=vp.suspension_replay_receipt(params,before,g,.02,p,0.,actual)
        self.assertFalse(receipt['terminal_matches'])
        self.assertEqual(1.,receipt['terminal_delta']['height'])
        with mock.patch.object(vp,'_reference_damper_suspension_step',side_effect=ValueError('trace')):
            failed=vp.suspension_replay_receipt(params,before,g,.02,p,0.,actual)
        self.assertIn('ValueError',failed['replay_error'])
        self.assertEqual(actual,receipt['actual'])

    def test_abnormal_admission_is_diagnostic_and_includes_large_projection(self):
        before=physics_fixture.VehiclePhysicsSuspensionTrialTests._state()
        self.assertFalse(vp.suspension_abnormal_step(before,dict(before)))
        for after in (dict(before,height=2.),dict(before,pitch=1.),dict(before,roll=-1.)):
            self.assertTrue(vp.suspension_abnormal_step(before,after))
        tilted=dict(before,roll=1.)
        self.assertTrue(vp.suspension_abnormal_step(tilted,dict(tilted)))

    def test_each_cached_action_keeps_selected_goal_and_final_outcome(self):
        runtime,state=self.scene(lambda x,z:0.)
        state['speed']=0.
        base=dict(recovery_mode='avoid',combat_mode='base_defense',
            move_position=(4.,0.,0.),control_trace=dict(strategic_move_position=(100.,0.,0.)))
        for i,command in enumerate((base,base,dict(base,move_position=(0.,0.,4.)),base)):
            runtime._record_execution_window(state,command,0.,1.,float(i))
            runtime._finish_motion_stall(state,False,False,(0.,0.,0.),float(i))
        actions=state['_execution_window']['actions']
        self.assertEqual(3,len(actions))
        self.assertEqual(2,actions[0]['samples'])
        self.assertEqual((4.,0.,0.),actions[0]['goal'])
        self.assertEqual((0.,0.,4.),actions[1]['goal'])
        self.assertEqual(0.,actions[-1]['outcome']['displacement'])
        self.assertEqual((100.,0.,0.),actions[-1]['strategic_goal'])

    def test_action_history_is_bounded_and_carries_omission_count(self):
        runtime,state=self.scene(lambda x,z:0.)
        for i in range(50):
            runtime._record_execution_window(state,dict(move_position=(i,0.,0.)),0.,1.,i*.01)
        row=state['_execution_window']
        self.assertEqual(32,len(row['actions']))
        self.assertEqual(18,row['actions_dropped'])


if __name__=='__main__': unittest.main()
