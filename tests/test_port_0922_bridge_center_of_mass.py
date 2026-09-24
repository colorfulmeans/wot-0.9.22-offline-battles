"""Bridge edge regressions from the September 25 KV-5 session."""
import math
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixtures
from gui.mods.offline_lan_0922 import bot_runtime, vehicle_physics
from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime


class BridgeCenterOfMassTests(unittest.TestCase):
    def test_first_slope_sample_preserves_player_and_bot_landing_normal(self):
        params = vehicle_physics.derive_suspension_params(
            fixtures._suspension_descriptor())
        for yaw in (0.0, 0.7):
            with self.subTest(yaw=yaw):
                def slope(x, z, low, high, *args, **kw):
                    height = -0.3 * x + 0.1 * z
                    return height if low <= height <= high else None
                battle = BattleRuntime(fixtures._runtime())
                battle._local_suspension_params = params
                battle._local_airborne = True
                battle._suspension_ground_y = slope
                bots = bot_runtime.BotRuntime(1, suspension_ground_probe=slope)
                state = dict(id=11, x=0., y=0., z=0., yaw=yaw,
                             terrain_pitch=0., roll=0., airborne=True)
                batches = (
                    battle._local_suspension_ground_samples((0., 0., 0.), yaw),
                    bots._suspension_ground_samples(state, params))
                for ground in batches:
                    plane = vehicle_physics.suspension_world_ground_plane(
                        params, ground, (0., 0., 0.), yaw, 0.35)
                    self.assertIsNotNone(plane)
                    self.assertAlmostEqual(-0.3, plane['gradient_x'])
                    self.assertAlmostEqual(0.1, plane['gradient_z'])

    def test_origin_sweep_keeps_wall_tangent_and_rechecks_corners(self):
        calls = []
        def wall(dx, dz):
            calls.append((dx, dz))
            return (dx <= 0.0, (-1.0, 0.0, 0.0))
        self.assertEqual((0.0, 0.3),
            vehicle_physics.resolve_suspension_origin_shift(
                0.0, (0.2, 0.3), wall))
        self.assertEqual([(0.2, 0.3), (0.0, 0.3)], calls)
        self.assertEqual((0.0, 0.0),
            vehicle_physics.resolve_suspension_origin_shift(
                0.0, (0.2, 0.3), lambda dx, dz: (False, (-1.0, 0.0, 0.0))))

    def test_player_and_bot_tumbling_origin_sweeps_keep_falling_at_a_wall(self):
        descriptor = fixtures._suspension_descriptor()
        for actor in ('player', 'bot'):
            with self.subTest(actor=actor):
                calls = []
                def wall(dx, dz):
                    calls.append((dx, dz))
                    return dx <= 1.0e-12
                if actor == 'player':
                    runtime = fixtures._runtime()
                    battle = BattleRuntime(runtime)
                    battle._avatar = runtime.bigworld.avatar
                    battle._local_fall_armed = battle._local_airborne = True
                    battle._local_pitch, battle._local_roll = 0.3, 0.4
                    battle._local_suspension_pitch_velocity = 0.2
                    battle._local_suspension_roll_velocity = 0.3
                    battle._local_vertical_speed = -5.0
                    battle._suspension_ground_y = lambda *args, **kw: None
                    def probe(entity, pos, yaw, speed, dt, **kw):
                        battle._local_world_collision_trace = dict(normal=(-1, 0, 0))
                        return wall(math.sin(yaw)*speed*dt, math.cos(yaw)*speed*dt)
                    battle._motion_is_clear = probe
                    entity = fixtures._Vehicle(10, descriptor, fixtures._Vector(),
                                               (0, 0, 0), {'health': 500})
                    after = battle._update_vertical_motion(entity, (0, 20, 0), 0, 0.02)
                    airborne = battle._local_airborne
                else:
                    state = dict(id=11, x=0., y=20., z=0., yaw=0., speed=0.,
                        vertical_speed=-5., terrain_pitch=0.3, roll=0.4,
                        suspension_pitch_velocity=0.2, suspension_roll_velocity=0.3,
                        airborne=True, grounded_once=True)
                    def probe(bot_id, pos, yaw, speed, desc, dt, now,
                              commit_enabled, motion_yaw=None):
                        state['_world_contact_trace'] = dict(normal=(-1, 0, 0))
                        return ('clear' if wall(math.sin(motion_yaw)*speed*dt,
                            math.cos(motion_yaw)*speed*dt) else 'hard')
                    runtime = bot_runtime.BotRuntime(1, motion_resolver=probe,
                        suspension_ground_probe=lambda *args: None,
                        physics_ground_probe=lambda *args: None)
                    runtime._descriptors[11] = descriptor
                    runtime._update_suspension_vertical_motion(state, 0.02,
                        vehicle_physics.derive_suspension_params(descriptor))
                    after = state['x'], state['y'], state['z']
                    airborne = state['airborne']
                self.assertGreaterEqual(len(calls), 2)
                self.assertAlmostEqual(0.0, after[0])
                self.assertLess(after[1], 20.0)
                self.assertLess(after[2], 0.0)
                self.assertTrue(airborne)

    def test_landing_uses_mass_center_impact_even_when_model_origin_is_rising(self):
        # A tilted origin can rise as the descending mass center hits a slope.
        # Its angular shift must not be counted again as sideways impact speed.
        descriptor = fixtures._suspension_descriptor()
        solved = dict(height=1.0, vertical_velocity=0.0, pitch=0.3, roll=0.4,
            pitch_velocity=0.0, roll_velocity=0.0, origin_shift=(0.2, 0.1),
            airborne=False, contact_count=10, rigid_contact_count=1,
            left_flying=False, right_flying=False, impact_speed=-16.0)
        plane = dict(center_x=0., center_z=0., center_y=0., gradient_x=0.5,
                     gradient_z=0., normal=(-0.4472135955, 0.894427191, 0.))
        runtime = fixtures._runtime()
        battle = BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        battle._local_fall_armed = battle._local_airborne = True
        battle._local_vertical_speed = 1.0
        battle._local_support_motion_pose = (0., 1., 0.)
        battle._local_suspension_ground_samples = lambda *args, **kw: (0.,)*10
        battle._local_suspension_pseudo_ground_samples = lambda *args, **kw: (None,)*12
        battle._motion_is_clear = lambda *args, **kw: True
        battle._apply_landing_impact = mock.Mock()
        entity = fixtures._Vehicle(10, descriptor, fixtures._Vector(),
                                   (0, 0, 0), {'health': 500})
        state = dict(id=11, x=0.2, y=1., z=0., yaw=0., speed=0.,
                     vertical_speed=1., airborne=True, grounded_once=True)
        bots = bot_runtime.BotRuntime(1)
        bots._suspension_ground_samples = lambda *args: (0.,)*10
        bots._suspension_pseudo_ground_samples = lambda *args: (None,)*12
        bots._apply_bot_landing_impact = mock.Mock()
        with mock.patch.object(vehicle_physics, 'damper_suspension_step',
                               return_value=solved), mock.patch.object(
                vehicle_physics, 'suspension_world_ground_plane', return_value=plane):
            battle._update_vertical_motion(entity, (0.2, 1., 0.), 0., 0.1)
            bots._update_suspension_vertical_motion(state, 0.1,
                vehicle_physics.derive_suspension_params(descriptor),
                suspension_motion_pose=(0., 1., 0.))
        self.assertEqual(1, battle._apply_landing_impact.call_count)
        self.assertEqual(1, bots._apply_bot_landing_impact.call_count)
        self.assertAlmostEqual(battle._apply_landing_impact.call_args[0][1],
                               bots._apply_bot_landing_impact.call_args[0][1])
    def test_exact_client_power_curve_anchors_set_the_hull_mass_center(self):
        descriptor = fixtures._suspension_descriptor()
        # Values independently recovered from physics_shared.pyc #1513:
        # hullCenter.y + hullPosition.y + shift * hullHeight.
        for ratio, shift in ((0.0, -0.15), (9.5, -0.15), (13.0, -0.2),
                             (21.0, -0.3), (30.0, -0.3)):
            descriptor.physics['enginePower'] = descriptor.physics['weight'] * ratio
            params = vehicle_physics.derive_suspension_params(descriptor)
            self.assertAlmostEqual(1.2 + shift * 1.6,
                                   params['center_of_mass_y'])

    def test_turning_unsupported_body_keeps_the_same_world_mass_center(self):
        descriptor = fixtures._suspension_descriptor()
        params = vehicle_physics.derive_suspension_params(descriptor)
        center = dict(x=0.0, y=params['center_of_mass_y'], z=0.0)
        before = dict(height=12.0, vertical_velocity=-3.0, pitch=0.3,
                      roll=-0.4, pitch_velocity=0.5, roll_velocity=-0.3)
        dt = 1.0 / 120.0
        after = vehicle_physics.damper_suspension_step(
            params, before, (None,) * 10, dt, (None,) * 12)
        old_offset = vehicle_physics.suspension_point_offset(
            center, before['pitch'], before['roll'])
        new_offset = vehicle_physics.suspension_point_offset(
            center, after['pitch'], after['roll'])
        for axis, horizontal in ((0, 0), (2, 1)):
            self.assertAlmostEqual(old_offset[axis],
                after['origin_shift'][horizontal] + new_offset[axis])
        expected_speed = (vehicle_physics._rigid_point_velocity(before, center) -
                          vehicle_physics.GRAVITY * dt)
        self.assertAlmostEqual(expected_speed,
                              vehicle_physics._rigid_point_velocity(after, center))

    def test_stopped_tipped_hull_outside_bridge_support_falls_without_driving(self):
        # The model origin is still 20 cm inboard, but its tipped mass center
        # is over the edge. The old solver hung from this track-origin pivot.
        for dt in (1.0 / 30.0, 1.0 / 120.0):
            for yaw in (0.0, 1.2):
                with self.subTest(dt=dt, yaw=yaw):
                    runtime = fixtures._runtime()
                    battle = BattleRuntime(runtime)
                    battle._avatar = runtime.bigworld.avatar
                    battle._local_fall_armed = True
                    battle._local_roll = -0.44
                    entity = fixtures._Vehicle(10, fixtures._suspension_descriptor(),
                        fixtures._Vector(), (yaw, 0, 0), {'health': 500})
                    sine, cosine = math.sin(yaw), math.cos(yaw)

                    def bridge(x, z, minimum, maximum, **kwargs):
                        inboard = cosine * x - sine * z < 0.0
                        if inboard and minimum <= 0.0 <= maximum:
                            return 0.0
                        return -30.0 if minimum <= -30.0 <= maximum else None

                    battle._suspension_ground_y = bridge
                    position = (-0.2 * cosine, -0.5, 0.2 * sine)
                    for unused in range(int(4.0 / dt)):
                        position = battle._update_vertical_motion(
                            entity, position, yaw, dt)
                        self.assertFalse(battle._local_support_rise_blocked)
                    self.assertLess(position[1], -10.0)

    def test_bot_falling_more_than_five_metres_does_not_rollback(self):
        params = vehicle_physics.derive_suspension_params(
            fixtures._suspension_descriptor())
        runtime = bot_runtime.BotRuntime(1,
            suspension_ground_probe=lambda *args: None,
            physics_ground_probe=lambda *args: None)
        state = dict(id=11, x=0.0, y=100.0, z=0.0, yaw=0.0,
                     speed=0.0, vertical_speed=-80.0, terrain_pitch=0.0,
                     roll=0.0, airborne=True, grounded_once=True)
        self.assertFalse(runtime._update_suspension_vertical_motion(
            state, 0.1, params, tick_pose=(0.0, 100.0, 0.0)))
        self.assertLess(state['y'], 92.0)
        self.assertTrue(state['airborne'])


if __name__ == '__main__':
    unittest.main()
