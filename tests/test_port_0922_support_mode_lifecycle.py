"""Temporary five-point support ownership and admitted landing damage."""
import contextlib
import io
import unittest
from unittest import mock
import test_port_0922_contact_support_navigation as fixtures
from gui.mods.offline_lan_0922 import environment_modules as em


class SupportLifecycleTests(unittest.TestCase):
    scene = fixtures.ContactSupportTests.scene
    def test_each_of_five_points_can_enable_without_a_vehicle_contact(self):
        for missing in range(5):
            with self.subTest(missing=missing):
                runtime,state=self.scene(lambda x,z:0.)
                state.pop('_contact_dynamics')
                replies=[0.]*5;replies[missing]=None
                with mock.patch.object(runtime,'_ground_probe_at',side_effect=replies), contextlib.redirect_stdout(io.StringIO()):
                    self.assertIsNotNone(runtime._suspension_params_for(11))
                self.assertTrue(state['_edge_support_active'])
                self.assertEqual(4,sum(p['valid'] for p in state['_support_mode_sample'][1]))

    def test_all_points_restore_releases_without_resetting_pose_or_velocity(self):
        runtime,state=self.scene(lambda x,z:0.)
        with mock.patch.object(runtime,'_ground_probe_at',return_value=None), contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNotNone(runtime._suspension_params_for(11))
        state.update(airborne=False,vertical_speed=.2,speed=7.,
            suspension_pitch_velocity=.1,suspension_roll_velocity=.2)
        retained={k:state[k] for k in ('x','y','z','yaw','pitch','roll','speed','vertical_speed',
            'suspension_pitch_velocity','suspension_roll_velocity')}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(runtime._release_detailed_support(state))
            self.assertIsNone(runtime._suspension_params_for(11))
        self.assertNotIn(11,runtime._suspension_params)
        self.assertEqual(retained,{k:state[k] for k in retained})

    def test_one_missing_point_or_uncommitted_airborne_pose_keeps_detailed(self):
        for airborne in (False,True):
            runtime,state=self.scene(lambda x,z:0.)
            state.update(_edge_support_active=True,airborne=airborne)
            with mock.patch.object(runtime,'_ground_probe_at',side_effect=([0.]*5 if airborne else [0.,0.,None,0.,0.])), contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(runtime._release_detailed_support(state))
            self.assertTrue(state['_edge_support_active'])

    def test_contact_impulse_survives_rebound_and_zero_time_final_projection(self):
        vp=fixtures.vp
        for final_airborne in (False,True):
            for before_airborne in (False,True):
                solved=dict(airborne=final_airborne,impact_speed=-19.5)
                self.assertEqual(-19.5,vp.suspension_impact_velocity(before_airborne,-19.,solved))
        self.assertIsNone(vp.suspension_impact_velocity(False,0.,dict(airborne=False,impact_speed=None)))
        self.assertEqual(-19.,vp.suspension_impact_velocity(True,-19.,dict(airborne=False,impact_speed=None)))

    def test_normal_slope_has_five_valid_points(self):
        import math
        runtime,state=self.scene(lambda x,z:.1*z)
        state['terrain_pitch']=-math.atan(.1)
        state['pitch']=state['terrain_pitch']
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(runtime._suspension_params_for(11))
        self.assertEqual(5,sum(p['valid'] for p in state['_support_mode_sample'][1]))

    def test_tip_fall_reports_impact_and_keeps_detail_with_missing_support(self):
        import test_port_0922_bot_runtime as bots
        self.module=bots._load()
        runtime,state,unused=bots.BotRuntimeTests._suspension_case(
            self,lambda x,z:0. if x <= -.3 else -20.)
        state.update(alive=True,collision_shape=(1.5,3.5,-.5,2.),speed=0.,movement_dir=0)
        runtime.states={11:state}
        runtime._apply_bot_landing_impact=mock.Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            for tick in range(200):
                runtime._contact_now=tick*.05
                runtime._update_vertical_motion(state,.05,(state['x'],state['y'],state['z']),state['yaw'])
            self.assertTrue(any(c.args[1]>19. for c in runtime._apply_bot_landing_impact.call_args_list))
            self.assertTrue(state['_edge_support_active'])
            self.assertTrue(any(not p['valid'] for p in runtime._basic_support_status(state)))
            self.assertFalse(runtime._release_detailed_support(state))

    def test_pending_landing_commits_before_support_is_released(self):
        runtime,state=self.scene(lambda x,z:0.)
        state.update(_edge_support_active=True,airborne=False)
        events=[]
        runtime._turret_motion_probe=mock.Mock(return_value=True)
        runtime._turret_state_pose=lambda unused:dict(x=0.,y=0.,z=0.,yaw=0.)
        def integrate(*args):
            runtime._turret_pending_landing_impacts.append((19.5,True,(),(0.,1.,0.),True))
            return False
        runtime._integrate_vertical_motion=integrate
        runtime._apply_bot_landing_impact=lambda *args:events.append('impact')
        release=runtime._release_detailed_support
        def handoff(state):
            events.append('handoff')
            return release(state)
        runtime._release_detailed_support=handoff
        with contextlib.redirect_stdout(io.StringIO()):
            runtime._update_vertical_motion(state,.05)
        self.assertEqual(['impact','handoff'],events)
        self.assertFalse(state.get('_edge_support_active',False))

    def test_observed_ground_without_selected_witness_still_queries_modules(self):
        runtime,state=self.scene(lambda x,z:0.)
        state.update(health=1000,max_health=1000,_landing_ground_observed=True)
        runtime.impact_contacts_resolver=mock.Mock(return_value=[dict(name='engineHealth',weight=1.)])
        with mock.patch.object(em,'apply_impact',return_value=(0,None)) as apply, contextlib.redirect_stdout(io.StringIO()):
            damage=runtime._apply_bot_fall_damage(state,19.5)
        self.assertGreater(damage,0)
        self.assertLess(state['health'],1000)
        runtime.impact_contacts_resolver.assert_called_once()
        self.assertEqual([dict(name='engineHealth',weight=1.)],apply.call_args.args[2])


if __name__=='__main__':unittest.main()
