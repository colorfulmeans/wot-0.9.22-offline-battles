"""Accepted contact endpoints keep one physical support/velocity frame."""
import contextlib
import io
import math
import unittest
from unittest import mock
import test_port_0922_contact_support_navigation as contact_fixtures
vp=contact_fixtures.vp


class PostContactGroundingTests(unittest.TestCase):
    scene=contact_fixtures.ContactSupportTests.scene

    def test_contact_rollback_over_continuous_ground_does_not_create_airtime(self):
        # T54E1's sampled gap was .036898m after the forward move was clipped.
        for gap,travel in ((.03689825534820557,.534165994),(.04,.5),(.1,1.)):
            for sign in (-1.,1.):
                with self.subTest(gap=gap,sign=sign):
                    grade=gap/travel
                    runtime,state=self.scene(lambda x,z:grade*z*sign)
                    pitch=-math.atan(grade*sign)
                    state.update(y=gap,speed=5.237453883807595,
                        vertical_speed=0.,airborne=False,pitch=pitch,terrain_pitch=pitch)
                    runtime._contact_now=1.
                    rollback=(0.,gap,0.)
                    settled=(0.,gap,travel*sign)
                    runtime._apply_bot_landing_impact=mock.Mock()
                    with contextlib.redirect_stdout(io.StringIO()):
                        runtime._integrate_vertical_motion(state,0.,rollback,0.,settled)
                    self.assertFalse(state['airborne'])
                    self.assertAlmostEqual(0.,state['y'])
                    self.assertAlmostEqual(5.237453883807595,state['speed'])
                    self.assertFalse(state.get('_edge_support_active',False))
                    runtime._apply_bot_landing_impact.assert_not_called()

    def test_reverse_drive_can_brake_after_a_clipped_forward_contact(self):
        runtime,state=self.scene(lambda x,z:.1*z)
        state.update(y=.05,speed=5.237453883807595,vertical_speed=0.,airborne=False,
            pitch=-math.atan(.1),terrain_pitch=-math.atan(.1))
        with contextlib.redirect_stdout(io.StringIO()):
            runtime._integrate_vertical_motion(state,0.,(0.,.05,0.),0.,(0.,.05,.5))
        # The unchanged drive law must now own braking; no invented speed reset.
        from test_port_0922_vehicle_physics import VehiclePhysicsSuspensionTrialTests
        params=vp.derive_params(VehiclePhysicsSuspensionTrialTests._descriptor())
        speed=state['speed']
        following=vp._reference_longitudinal_step(params,speed,-1.,0.,
            state['terrain_pitch'],.1,airborne=state['airborne'],service_brake=True)
        self.assertLess(following,speed)

    def test_airborne_body_cannot_borrow_a_grounded_projection_reference(self):
        runtime,state=self.scene(lambda x,z:0.)
        state.update(y=.05,speed=5.,vertical_speed=-12.,airborne=True)
        runtime._apply_bot_landing_impact=mock.Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            runtime._integrate_vertical_motion(state,0.,(0.,.05,0.),0.,(0.,0.,.5))
        self.assertTrue(state['airborne'])
        self.assertEqual(.05,state['y'])
        self.assertEqual(-12.,state['vertical_speed'])
        runtime._apply_bot_landing_impact.assert_not_called()

    def test_real_drop_or_missing_ground_still_opens_detailed_support(self):
        for missing in (False,True):
            runtime,state=self.scene(lambda x,z:None if missing else (0. if z>=.25 else -15.))
            state.update(y=0.,speed=5.,vertical_speed=0.,airborne=False)
            with contextlib.redirect_stdout(io.StringIO()):
                runtime._integrate_vertical_motion(state,0.,(0.,0.,0.),0.,(0.,0.,.5))
            self.assertTrue(state['airborne'])
            self.assertTrue(state['_edge_support_active'])

    def test_short_real_step_is_not_a_continuous_contact_projection(self):
        runtime,state=self.scene(lambda x,z:0. if z>=.25 else -.5)
        state.update(y=0.,speed=5.,vertical_speed=0.,airborne=False)
        runtime._apply_bot_landing_impact=mock.Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            runtime._integrate_vertical_motion(state,0.,(0.,0.,0.),0.,(0.,0.,.5))
        self.assertTrue(state['airborne'])
        self.assertEqual(0.,state['y'])
        runtime._apply_bot_landing_impact.assert_not_called()


if __name__=='__main__':unittest.main()
