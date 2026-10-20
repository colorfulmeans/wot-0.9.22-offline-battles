"""Analytic ground planes expose stance lag and incorrect yaw-local slopes."""
import math
import unittest
from unittest import mock

from gui.mods.offline_lan_0922 import bot_runtime, vehicle_physics


class BasicSlopePoseTests(unittest.TestCase):
    def assert_on_plane(self, pitch, roll, yaw, gx, gz):
        for x, z in ((-1.5, -3.0), (-1.5, 3.0), (1.5, -3.0), (1.5, 3.0)):
            ox, oy, oz = vehicle_physics.suspension_point_offset(dict(x=x, y=0.0, z=z), pitch, roll)
            wx = math.cos(yaw)*ox + math.sin(yaw)*oz
            wz = -math.sin(yaw)*ox + math.cos(yaw)*oz
            self.assertAlmostEqual(gx*wx + gz*wz, oy, places=10)

    def test_exact_four_point_fit_aligns_both_tracks_at_every_heading(self):
        gx, gz = 0.18, 0.27
        probe = mock.Mock(side_effect=lambda x, z, y: 12.0 + gx*x + gz*z)
        for yaw in (0.0, math.pi/4, math.pi/2, math.pi, -math.pi/2):
            with self.subTest(yaw=yaw):
                pitch, roll = bot_runtime.slope_pose(probe, (0.0, 12.0, 0.0), yaw, 3.0, 1.5, exact=True)
                self.assert_on_plane(pitch, roll, yaw, gx, gz)
        self.assertEqual(20, probe.call_count)

    def test_tilted_samples_and_fit_share_the_physical_footprint(self):
        gx,gz=.18,.27
        for yaw in (0.,.7,1.6,-2.):
            receipt={}
            pitch,roll=bot_runtime.slope_pose(lambda x,z,y:12.+gx*x+gz*z,
                (0.,12.,0.),yaw,5.46,1.8,-.145,.08,exact=True,receipt=receipt)
            self.assert_on_plane(pitch,roll,yaw,gx,gz)
            for row,side,forward in zip(receipt['points'],(0.,0.,1.8,-1.8),(5.46,-5.46,0.,0.)):
                ox,oy,oz=vehicle_physics.suspension_point_offset(
                    dict(x=side,y=0.,z=forward),-.145,.08)
                self.assertAlmostEqual(ox*math.cos(yaw)+oz*math.sin(yaw),row['x'])
                self.assertAlmostEqual(-ox*math.sin(yaw)+oz*math.cos(yaw),row['z'])
                self.assertAlmostEqual(12.+oy,row['hint_y'])

    def test_long_hull_does_not_sample_an_unreached_ledge_for_its_pose(self):
        # TOG II: a horizontal 5.46 m front ray reaches z=44.97, while
        # the actual tilted support point is still before that ledge.
        receipt={}
        pose=bot_runtime.slope_pose(lambda x,z,y:2.705155 if z>=44.95 else 1.1,
            (174.81088,1.161663,39.54915),-.115769,5.46,1.8,-.145887,0.,
            exact=True,receipt=receipt)
        self.assertLess(receipt['points'][0]['z'],44.95)
        self.assertEqual((0.,0.),pose)

    def test_yaw_rebase_preserves_ground_normal_without_new_queries(self):
        gx, gz = 0.18, 0.27
        initial = bot_runtime.slope_pose(lambda x,z,y:gx*x+gz*z, (0,0,0), 0, 3, 1.5, exact=True)
        pitch, roll = initial
        previous = 0.0
        for yaw in (0.2, 0.7, 1.4, 2.8, -2.8, -1.0, 0.0):
            pitch, roll = bot_runtime.ground_pose_for_yaw(pitch, roll, previous, yaw)
            self.assert_on_plane(pitch, roll, yaw, gx, gz)
            previous = yaw
        self.assertAlmostEqual(initial[0], pitch)
        self.assertAlmostEqual(initial[1], roll)

    def case(self):
        runtime = bot_runtime.BotRuntime(1)
        state = dict(id=11,x=0.,y=0.,z=0.,yaw=math.pi/2,
            pitch=-math.atan(.25), terrain_pitch=-math.atan(.25), roll=0.,
            grounded_once=True,airborne=False,suspension_pitch=.04,
            _basic_slope_basis_yaw=0.,pose_sample=(0.,0.,0.),
            _slope_pose_target=(-math.atan(.25),0.))
        runtime._suspension_params[11] = None
        runtime._descriptors[11] = {}
        return runtime,state

    def test_rotation_and_attitude_commit_through_the_same_body_probe(self):
        runtime,state = self.case()
        runtime._turret_motion_probe = mock.Mock(return_value=True)
        runtime._ground_probe_at = mock.Mock(side_effect=AssertionError('unexpected ray'))
        self.assertTrue(runtime._reorient_basic_ground_pose(state))
        self.assertAlmostEqual(.04, state['pitch'])
        self.assertAlmostEqual(-math.atan(.25), state['roll'])
        before,after,unused = runtime._turret_motion_probe.call_args.args
        self.assertEqual(0., before['yaw'])
        self.assertEqual(math.pi/2, after['yaw'])
        self.assertAlmostEqual(0., after['chassis']['pitch'])
        self.assertEqual(0., state['pose_sample'][2])

    def test_blocked_body_pose_keeps_last_legal_yaw_and_attitude(self):
        runtime,state = self.case()
        runtime._turret_motion_probe = mock.Mock(return_value=False)
        self.assertFalse(runtime._reorient_basic_ground_pose(state))
        self.assertEqual(0., state['yaw'])
        self.assertEqual(0., state['roll'])

    def test_airborne_and_ten_spring_hulls_keep_their_physical_owner(self):
        for airborne,params in ((True,None),(False,{})):
            runtime,state = self.case()
            state['airborne'] = airborne
            runtime._suspension_params[11] = params
            runtime._turret_motion_probe = mock.Mock()
            self.assertFalse(runtime._reorient_basic_ground_pose(state))
            runtime._turret_motion_probe.assert_not_called()

    def test_missing_ground_does_not_create_a_plane_and_old_blend_is_retained(self):
        self.assertIsNone(bot_runtime.slope_pose(lambda *args: None, (0,0,0), 0, 3, 1.5, exact=True))
        self.assertEqual((.2,.3), bot_runtime.slope_pose(lambda *args: None, (0,0,0), 0, 3, 1.5, .2, .3))
        self.assertEqual((.1,.15), bot_runtime.slope_pose(lambda *args: 0, (0,0,0), 0, 3, 1.5, .2, .3))
