"""Report 202714 BOT9: pitched rotation must query the occupied 3-D body.

Analytic geometry reproduces the adapter defect, not the complete native map.
"""
import math
import types
import unittest
from unittest import mock
import test_port_0922_battle_runtime as fixtures
from test_port_0922_world_collision import _Vector, _Strict1513Component
from gui.mods.offline_lan_0922 import native_world, tank_collision, world_collision


class SlopeRotationCompatibilityTests(unittest.TestCase):
    def scene(self):
        runtime = fixtures._runtime()
        runtime.math = types.SimpleNamespace(Vector3=_Vector)
        battle = fixtures.BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        bbox = ((-1.7, -.4, -3.5), (1.7, 1.8, 3.2), None)
        descriptor = _Strict1513Component(hull=_Strict1513Component(
            hitTester=types.SimpleNamespace(bbox=bbox)))
        battle._destructibles = types.SimpleNamespace(_vehicle_body_bbox=lambda unused: bbox)
        return runtime, battle, descriptor

    def test_rotating_rays_stay_parallel_to_the_measured_support_plane(self):
        for pitch, roll, start, end in (
                (.5006023335, .0561246412, -.2184827413, -.38),
                (.502435, .033785, -.28824, -.19507),
                (-.6, -.15, 1.4, 1.55), (.8, .3, -2., -2.15)):
            with self.subTest(pitch=pitch, roll=roll):
                runtime, battle, descriptor = self.scene()
                position = (-168.758, 1.380, 219.098)
                normal = tank_collision.pose_axes(start, pitch, roll)[1]
                rays = []
                def collide(unused_space, a, b, *unused, **kwargs):
                    da = sum((getattr(a, axis)-position[i])*normal[i]
                             for i, axis in enumerate(('x', 'y', 'z')))
                    db = sum((getattr(b, axis)-position[i])*normal[i]
                             for i, axis in enumerate(('x', 'y', 'z')))
                    rays.append((da, db))
                    # A ray at a fixed hull height is parallel to the world
                    # support plane, even as local pitch/roll change with yaw.
                    self.assertAlmostEqual(da, db, places=8)
                    self.assertLess(min(abs(da-h) for h in (.6, 1.1, 1.6)), 1.e-8)
                    return None
                import sys
                with mock.patch.dict(sys.modules, {'BigWorld': runtime.bigworld, 'Math': runtime.math}), \
                        mock.patch.object(native_world, 'run', return_value=None), \
                        mock.patch.object(world_collision, '_collide_horizontal', side_effect=collide), \
                        mock.patch.object(world_collision, '_lane_ground_ahead', return_value=None), \
                        mock.patch.object(world_collision, 'prepare_horizontal_collision_filter', return_value=None):
                    self.assertTrue(battle._native_world_rotation_is_clear(
                        position, start, end, descriptor, pitch=pitch, roll=roll,
                        include_static=True, follow_ground=True))
                self.assertGreaterEqual(len(rays), 18)

    def test_parallel_edge_roundoff_cannot_collapse_a_posed_chord(self):
        for side in (-1.7, 1.7):
            for noise in (-1.e-14, 1.e-14):
                end = world_collision._hull_pose_endpoint(
                    (side + noise, -3.5), (side, 3.2), 1.7, 3.5, 3.2)
                self.assertAlmostEqual(side, end[0])
                self.assertAlmostEqual(3.2, end[1])

    def test_stationary_rotation_keeps_native_solid_wall_veto_and_receipt(self):
        runtime, battle, descriptor = self.scene()
        trace = {}
        def blocked(*args, **kwargs):
            kwargs['trace'].update(reason='upper_lane', hit=(1., 2., 3.))
            return 'hard'
        with mock.patch.object(world_collision, 'check_horizontal_collision', side_effect=blocked):
            self.assertFalse(battle._native_world_rotation_is_clear(
                (0., 0., 0.), -.2, -.3, descriptor, pitch=.5, roll=.05,
                include_static=True, follow_ground=True, contact_trace=trace))
        self.assertEqual('upper_lane', trace['reason'])
        self.assertTrue(trace['posed_body'])
        self.assertTrue(trace['follow_ground'])
        self.assertIn('sweep_pitch', trace)
        self.assertIn('sweep_roll', trace)


if __name__ == '__main__':
    unittest.main()
