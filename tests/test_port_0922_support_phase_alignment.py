"""Select support from the accepted basic pose, never a second projected root."""
import contextlib
import io
import math
import unittest
from unittest import mock
import test_port_0922_contact_support_navigation as fixtures


class SupportPhaseAlignmentTests(unittest.TestCase):
    scene=fixtures.ContactSupportTests.scene

    def test_tog_handoff_does_not_refresh_from_a_longer_horizontal_footprint(self):
        runtime,state=self.scene(lambda x,z:2.705155 if z>=44.965 else 1.1)
        state.update(x=174.81088,y=1.161663,z=39.54915,yaw=-.115769,
            half_length=5.4622650146484375,half_width=1.438796043395996,
            pitch=-.08795634868640563,terrain_pitch=-.08795634868640563,
            roll=.004249469692594518,airborne=False,speed=0.,vertical_speed=0.,
            _basic_support_datum=.061663193667542)
        runtime._turret_motion_probe=mock.Mock(return_value=True)
        with contextlib.redirect_stdout(io.StringIO()):
            for tick in range(20):
                runtime._contact_now=1883.3+tick*.15
                runtime._update_slope_pose(state,force_sample=True)
                self.assertFalse(runtime._contact_edge_support_needed(state))
                self.assertEqual(5,sum(r['valid'] for r in runtime._basic_support_status(state)))
                self.assertFalse(state.get('_edge_support_active',False))
        self.assertTrue(runtime._turret_motion_probe.called)

        # A target accepted before the handback must obey the same proof on
        # its cached path; otherwise the next blended refresh recreates loss.
        state['pose_sample']=(state['x'],state['z'],state['yaw'])
        state['_slope_pose_target']=(0.,0.)
        before=(state['terrain_pitch'],state['roll'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(runtime._update_slope_pose(state))
        self.assertEqual(before,(state['terrain_pitch'],state['roll']))
        receipt=state['_slope_pose_refresh']
        self.assertEqual('proposed_footprint_loses_support',receipt['reason'])
        self.assertEqual(5,sum(r['valid'] for r in receipt['footprint_guard']['current']))
        self.assertLess(sum(r['valid'] for r in receipt['footprint_guard']['proposed']),5)

    def test_descent_longer_than_old_projection_span_settles_before_admission(self):
        runtime,state=self.scene(lambda x,z:-.4*z)
        state.update(z=3.01,y=0.,half_length=2.97797203064,half_width=1.60041105747,
                     speed=3.01/.18,vertical_speed=-6.,
                     terrain_pitch=math.atan(.4),pitch=math.atan(.4),
                     _support_mode_basis=(0.,0.,0.,0.,-.4))
        runtime._contact_now=1.
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(
                runtime,'_update_suspension_vertical_motion',side_effect=AssertionError('second timed solver')):
            self.assertFalse(runtime._integrate_vertical_motion(state,.18,(0.,0.,0.)))
        self.assertAlmostEqual(-1.204,state['y'])
        self.assertFalse(state.get('_edge_support_active',False))
        self.assertEqual('post_basic_settle',state['_support_mode_receipt']['selection_stage'])
        self.assertEqual(5,sum(row['valid'] for row in state['_support_mode_sample'][1]))

    def test_entry_and_exit_use_identical_actual_root_despite_old_plane(self):
        runtime,state=self.scene(lambda x,z:0.)
        state.update(x=1.,y=.7,_support_mode_basis=(0.,0.,0.,-.5,0.))
        runtime._contact_now=1.
        basic=runtime._basic_support_status(state)
        state['_edge_support_active']=True
        detailed=runtime._basic_support_status(state)
        self.assertEqual(basic,detailed)
        self.assertTrue(all(row['expected']==.7 for row in basic))

    def test_real_missing_footprint_point_still_enables_in_the_same_slice(self):
        runtime,state=self.scene(lambda x,z:None if z>3. else 0.)
        state.update(speed=0.,vertical_speed=0.)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(runtime._integrate_vertical_motion(state,.15,(0.,0.,0.)))
        self.assertTrue(state['_edge_support_active'])
        self.assertEqual(4,sum(row['valid'] for row in state['_support_mode_sample'][1]))

    def test_cliff_cannot_be_refitted_as_a_continuous_slope(self):
        runtime,state=self.scene(lambda x,z:0. if z<2. else -40.)
        state.update(speed=0.,vertical_speed=0.)
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(
                runtime,'_update_slope_pose',side_effect=AssertionError('cliff pose fit')):
            runtime._integrate_vertical_motion(state,.15,(0.,0.,0.))
        self.assertTrue(state['_edge_support_active'])
        self.assertEqual(0.,state['pitch'])

    def test_only_continuous_ground_can_refresh_a_stale_pose_before_selection(self):
        runtime,state=self.scene(lambda x,z:.4*z)
        state.update(speed=0.,vertical_speed=0.)
        with contextlib.redirect_stdout(io.StringIO()):
            runtime._integrate_vertical_motion(state,.15,(0.,0.,0.))
        self.assertFalse(state.get('_edge_support_active',False))
        self.assertAlmostEqual(-math.atan(.4),state['terrain_pitch'])
        self.assertTrue(state['_support_mode_receipt']['pose_refreshed'])

    def test_admission_does_not_spend_fall_dt_twice(self):
        runtime,state=self.scene(lambda x,z:-15.)
        state.update(speed=0.,vertical_speed=-10.,airborne=True)
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(
                runtime,'_update_suspension_vertical_motion',side_effect=AssertionError('double gravity')):
            runtime._integrate_vertical_motion(state,.1,(0.,0.,0.))
        self.assertTrue(state['_edge_support_active'])
        self.assertGreater(state['y'],-2.)
        self.assertLess(state['y'],-1.)


if __name__=='__main__':unittest.main()
