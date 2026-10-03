"""Support corrections must not turn short worker slices into launch impulses."""
import math
import unittest
from unittest import mock

from test_port_0922_bot_runtime import _load


class BotSupportLaunchTests(unittest.TestCase):
    def setUp(self):
        self.module = _load()

    def state(self, speed=3.5588, pitch=-0.02729):
        return dict(id=8, x=358.95, y=-0.18, z=-47.07, yaw=-0.21857,
                    speed=speed, half_length=3.0, vertical_speed=0.0,
                    airborne=False, grounded_once=True, terrain_pitch=pitch,
                    pitch=pitch, last_drive_pitch=pitch)

    def test_wz_support_bump_cannot_launch_hull_at_any_slice_length(self):
        for step in (0.0001, 1.0 / 120.0, 1.0 / 60.0, 0.04, 0.2):
            with self.subTest(step=step):
                support = [0.2929]
                runtime = self.module.BotRuntime(
                    1, physics_ground_probe=lambda *unused: support[0])
                state = self.state()
                runtime._update_vertical_motion(state, step)
                self.assertAlmostEqual(0.2929, state['y'])
                self.assertAlmostEqual(
                    -state['speed'] * math.tan(state['terrain_pitch']),
                    state['vertical_speed'])
                support[0] = -0.18
                peak = state['y']
                for unused in range(300):
                    runtime._update_vertical_motion(state, 1.0 / 60.0)
                    peak = max(peak, state['y'])
                self.assertLess(peak, 0.30)
                self.assertFalse(state['airborne'])
                self.assertAlmostEqual(-0.18, state['y'])

    def test_stationary_live_hull_and_wreck_get_no_impulse_from_support(self):
        for alive in (True, False):
            with self.subTest(alive=alive):
                runtime = self.module.BotRuntime(
                    1, physics_ground_probe=lambda *unused: 0.2929)
                state = self.state(speed=0.0)
                state['alive'] = alive
                runtime._update_vertical_motion(state, 0.0001)
                self.assertEqual(0.0, state['vertical_speed'])
                self.assertFalse(state['airborne'])

    def test_actual_uphill_travel_launches_forward_and_reverse(self):
        for speed, pitch in ((12.0, -0.2), (-12.0, 0.2)):
            for support in (None, -20.0):
                with self.subTest(speed=speed, support=support):
                    runtime = self.module.BotRuntime(
                        1, physics_ground_probe=lambda *unused: support)
                    state = self.state(speed, pitch)
                    state['last_drive_pitch'] = -pitch
                    runtime._update_vertical_motion(state, 0.04)
                    self.assertTrue(state['airborne'])
                    self.assertGreater(state['y'], -0.18)
                    self.assertAlmostEqual(
                        -speed * math.tan(pitch) -
                        self.module.vehicle_physics.GRAVITY * 0.04,
                        state['vertical_speed'])

    def test_corridor_slope_and_suspension_animation_cannot_launch_flat_hull(self):
        runtime = self.module.BotRuntime(
            1, physics_ground_probe=lambda *unused: -20.0)
        state = self.state(speed=12.0, pitch=0.0)
        state.update(last_drive_pitch=-0.6, pitch=-0.4,
                     suspension_pitch=-0.4, vertical_speed=28.374)
        runtime._update_vertical_motion(state, 0.04)
        self.assertTrue(state['airborne'])
        self.assertLess(state['y'], -0.18)
        self.assertLess(state['vertical_speed'], 0.0)

    def test_airborne_velocity_is_not_replaced_by_ground_tangent(self):
        runtime = self.module.BotRuntime(
            1, physics_ground_probe=lambda *unused: -20.0)
        state = self.state(speed=12.0, pitch=-0.2)
        state.update(y=8.0, airborne=True, vertical_speed=-7.0)
        runtime._update_vertical_motion(state, 0.04)
        self.assertAlmostEqual(-7.0 -
                               self.module.vehicle_physics.GRAVITY * 0.04,
                               state['vertical_speed'])

    def test_supported_downhill_motion_stays_grounded_in_both_directions(self):
        for speed, pitch in ((10.0, math.atan(0.25)),
                             (-10.0, -math.atan(0.25))):
            with self.subTest(speed=speed):
                runtime = self.module.BotRuntime(1)
                state = self.state(speed, pitch)
                for unused in range(50):
                    ground = state['y'] - 0.1
                    runtime._terrain_support = mock.Mock(
                        return_value=(ground, ground))
                    runtime._update_vertical_motion(state, 0.04)
                    self.assertFalse(state['airborne'])
                    self.assertAlmostEqual(ground, state['y'])
                    self.assertAlmostEqual(-2.5, state['vertical_speed'])


if __name__ == '__main__':
    unittest.main()
