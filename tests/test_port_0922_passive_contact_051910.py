"""Passive contact regressions from the gameplay-fixes 051910 report."""
import contextlib
import io
import math
import types
import unittest
from unittest import mock

import test_port_0922_bot_runtime as bots
import test_port_0922_battle_runtime as battle_tests
from gui.mods.offline_lan_0922 import tank_collision, world_collision


class PassiveContactTests(unittest.TestCase):
    setUp = bots.ShovedWreckTests.setUp
    tearDown = bots.ShovedWreckTests.tearDown
    _runtime = bots.ShovedWreckTests._runtime
    _wreck = bots.ShovedWreckTests._wreck

    def test_live_and_dead_shoves_use_physical_probe_not_route_water_or_grade(self):
        for alive in (True, False):
            runtime = self._runtime(clear=False)
            state = self._wreck(runtime)
            state['alive'] = alive
            runtime.contact_motion_probe = mock.Mock(return_value=True)
            runtime._clear = mock.Mock(side_effect=AssertionError('planner used for shove'))
            result = {'delta_velocity': (0.0, 2.0), 'correction': (0.0, .05)}
            if alive:
                runtime._apply_tank_contact_response(state, result, .1)
            else:
                runtime._apply_wreck_contact_response(state, result, .1)
            self.assertGreater(state['z'], 0.0)
            runtime.contact_motion_probe.assert_called_once()

    def test_passive_contact_still_stops_at_an_actual_world_wall(self):
        runtime = self._runtime()
        state = self._wreck(runtime)
        runtime.contact_motion_probe = lambda *unused: False
        runtime._apply_wreck_contact_response(state, {
            'delta_velocity': (0.0, 2.0), 'correction': (0.0, .05)}, .1)
        self.assertEqual((0.0, 0.0), (state['z'], state['push_z']))

    def test_dead_hull_keeps_falling_after_contact_and_neighbours_disappear(self):
        for dt in (1.0 / 30.0, 1.0 / 120.0):
            runtime = self._runtime(ground=-40.0)
            state = self._wreck(runtime)
            runtime.states = {11: state}
            runtime.contact_motion_probe = lambda *unused: True
            runtime._apply_wreck_contact_response(state, {
                'delta_velocity': (0.0, 2.0), 'correction': (0.0, .05)}, dt)
            start_z = state['z']
            self.assertTrue(state['airborne'])
            self.assertLess(state['y'], 0.0)
            velocity = state['push_z']
            for tick in range(int(1.0 / dt) - 1):
                runtime._resolve_tank_contacts((), tick * dt, dt)
            self.assertAlmostEqual(-.5 * self.module.vehicle_physics.GRAVITY, state['y'])
            self.assertGreater(state['z'], start_z)
            self.assertEqual(velocity, state['push_z'])
            self.assertEqual(0.0, state['speed'])
            for tick in range(int(3.0 / dt)):
                runtime._resolve_tank_contacts((), tick * dt, dt)
            self.assertEqual(-40.0, state['y'])
            self.assertFalse(state['airborne'])

    def test_shallow_drop_obeys_gravity_instead_of_snapping_to_lower_support(self):
        runtime = self._runtime(ground=-.3)
        state = self._wreck(runtime)
        runtime.contact_motion_probe = lambda *unused: True
        step = 1. / 120.
        runtime._apply_wreck_contact_response(state, {
            'delta_velocity': (0., 2.), 'correction': (0., .05)}, step)
        self.assertAlmostEqual(-.5 * self.module.vehicle_physics.GRAVITY * step * step,
                               state['y'])
        self.assertTrue(state['airborne'])

    def test_missing_support_releases_wreck_without_reverting_its_horizontal_pose(self):
        runtime = self._runtime(ground=None)
        state = self._wreck(runtime)
        runtime.contact_motion_probe = lambda *unused: True
        runtime._apply_wreck_contact_response(state, {
            'delta_velocity': (0.0, 2.0), 'correction': (0.0, .05)}, .1)
        self.assertGreater(state['z'], 0.0)
        self.assertLess(state['y'], 0.0)
        self.assertTrue(state['airborne'])

    def test_mass_weighted_response_survives_the_native_callback_for_wrecks(self):
        def shove(wreck_mass):
            runtime = self._runtime(clear=False)
            state = self._wreck(runtime)
            runtime.states = {11: state}
            state['mass'] = wreck_mass
            runtime._physics_params_for(11)['mass'] = wreck_mass
            runtime.contact_motion_probe = lambda *unused: True
            player = dict(id=1, team=1, vehicle='fake', alive=True,
                          x=0., y=0., z=-5., yaw=0., speed=9.,
                          effective_params=bots._effective_params_snapshot(mass=100575.))
            runtime._resolve_tank_contacts([player], 1., 1. / 30.)
            return state['push_z'], state['z']
        light = shove(23496.)
        heavy = shove(68000.)
        self.assertGreater(light[0], heavy[0])
        self.assertGreater(light[1], heavy[1])
        self.assertGreater(heavy[1], 0.)

    def test_airborne_body_has_no_static_track_hold_in_the_pair_solver(self):
        runtime = self._runtime(ground=None)
        state = self._wreck(runtime)
        state.update(airborne=True, y=1.)
        runtime.contact_motion_probe = lambda *unused: True
        driver = runtime.states[12]
        driver.update(x=0., y=1., z=-5., speed=.01, yaw=0.)
        runtime._resolve_tank_contacts((), 1., 1. / 30.)
        self.assertGreater(state['push_z'], 0.)

    def test_suspended_wreck_rotates_about_its_mass_center_while_falling(self):
        runtime = self._runtime(ground=None)
        state = self._wreck(runtime)
        physics = self.module.vehicle_physics
        descriptor = bots._suspension_descriptor()
        params = physics.derive_suspension_params(descriptor)
        params['center_of_mass_y'] = 1.2
        original_params = dict(params)
        runtime._descriptors[11] = descriptor
        runtime._suspension_params[11] = params
        runtime._suspension_ground_probe = lambda *unused, **kwargs: None
        state.update(y=10., airborne=True, pitch=.1, terrain_pitch=.1,
                     roll=.3, suspension_roll_velocity=.4)
        seen = []
        runtime.contact_motion_probe = lambda pose, *unused: seen.append(dict(pose)) or True
        center = dict(x=0., y=1.2, z=0.)
        before = physics.suspension_point_offset(center, state['pitch'], state['roll'])
        runtime._apply_wreck_contact_response(state, {
            'delta_velocity': (0., 0.), 'correction': (0., 0.)}, 1. / 30.)
        after = physics.suspension_point_offset(center, state['pitch'], state['roll'])
        self.assertAlmostEqual(before[0], state['x'] + after[0])
        self.assertAlmostEqual(before[2], state['z'] + after[2])
        self.assertLess(state['y'] + after[1], 10. + before[1])
        self.assertTrue(state['airborne'])
        self.assertEqual(state['roll'], seen[-1]['roll'])
        self.assertEqual(state['terrain_pitch'], seen[-1]['terrain_pitch'])
        self.assertEqual(original_params, params)

    def test_spring_wreck_cannot_settle_through_a_detached_turret(self):
        runtime = self._runtime(ground=None)
        state = self._wreck(runtime)
        descriptor = bots._suspension_descriptor()
        runtime._descriptors[11] = descriptor
        runtime._suspension_params[11] = self.module.vehicle_physics.derive_suspension_params(descriptor)
        runtime._suspension_ground_probe = lambda *unused, **kwargs: None
        runtime.contact_motion_probe = lambda *unused: True
        state.update(y=2., airborne=True, vertical_speed=-1.)
        runtime._turret_motion_probe = lambda before, after, desc: after['y'] >= before['y']
        runtime._apply_wreck_contact_response(state, {
            'delta_velocity': (0., 0.), 'correction': (0., 0.)}, .03)
        self.assertEqual(2., state['y'])

    def test_worker_preserves_human_pitch_and_roll_in_its_mass_solver(self):
        runtime = self._runtime()
        raw = dict(id=1, vehicle='fake', x=0., y=0., z=50., yaw=.3,
                   pitch=.4, roll=-.7, speed=0., alive=True,
                   effective_params=bots._effective_params_snapshot())
        captured = []
        original = self.module.tank_collision.resolve_pairs
        def solve(tanks, step):
            captured.extend(tanks)
            return original(tanks, step)
        with mock.patch.object(self.module.tank_collision, 'resolve_pairs', side_effect=solve):
            runtime._resolve_tank_contacts([raw], 1., .03)
        human = next(body for body in captured if body['kind'] == 'player')
        self.assertEqual((.4, -.7), (human['pitch'], human['roll']))


class ContactAdapterTests(unittest.TestCase):
    def test_native_passive_sweep_uses_real_hull_pose_and_never_crushes(self):
        engine = battle_tests._runtime()
        runtime = battle_tests.BattleRuntime(engine)
        descriptor = battle_tests._Descriptor()
        runtime._avatar = types.SimpleNamespace(spaceID=42)
        runtime._bots = types.SimpleNamespace(_descriptors={11: descriptor})
        state = dict(id=11, yaw=.6, pitch=.2, terrain_pitch=.15, roll=-.1)
        for status, clear in (('clear', True), ('hard', False), ('kinetic', False)):
            with mock.patch.object(runtime._bot_contact_motion_is_clear.__globals__['world_collision'], 'check_horizontal_collision',
                                   return_value=status) as probe:
                self.assertEqual(clear, runtime._bot_contact_motion_is_clear(
                    state, (2., 3., 4.), (2.3, 3., 4.4), .1))
            args, kwargs = probe.call_args
            self.assertIs(descriptor, args[6])
            self.assertEqual((True, False, None), args[9:12])
            self.assertEqual(.15, kwargs['pitch'])
            self.assertEqual(-.1, kwargs['roll'])
            self.assertFalse(kwargs['commit_enabled'])
            self.assertAlmostEqual(math.atan2(.3, .4), kwargs['motion_yaw'])


    def test_passive_sweep_retains_exact_catalog_collision_without_committing(self):
        runtime = battle_tests.BattleRuntime(battle_tests._runtime())
        runtime._avatar = types.SimpleNamespace(spaceID=42)
        runtime._bots = types.SimpleNamespace(_descriptors={11: battle_tests._Descriptor()})
        runtime._destructibles = types.SimpleNamespace(
            _catalog_motion_blocked=mock.Mock(return_value={'status': 'hard'}))
        state = dict(id=11, yaw=0., pitch=0., roll=0.,
                     _passive_contact_normal=(1., 0., 0.))
        world = runtime._bot_contact_motion_is_clear.__globals__['world_collision']
        with mock.patch.object(world, 'check_horizontal_collision', return_value='clear'):
            self.assertFalse(runtime._bot_contact_motion_is_clear(
                state, (0., 0., 0.), (0., 0., .1), .03))
        self.assertIsNone(state['_passive_contact_normal'])
        state['_passive_contact_normal'] = (1., 0., 0.)
        self.assertTrue(runtime._bot_contact_motion_is_clear(
            state, (0., 0., 0.), (0., 0., 0.), .03))
        self.assertIsNone(state['_passive_contact_normal'])
        call = runtime._destructibles._catalog_motion_blocked.call_args
        self.assertFalse(call.kwargs['kinetic_commit'])
        self.assertFalse(call.kwargs['commit_enabled'])
        self.assertIsNone(call.kwargs['kinetic_speed'])


class ContactPatchTests(unittest.TestCase):
    @staticmethod
    def proof():
        a = dict(x=-1., y=0., z=0., yaw=0., shape=(1., 2., 0., 2.))
        b = dict(a, x=1.)
        return dict(hit_point=(0., 1., 0.), contact_y_span=(0., 2.),
                    contact_normal=(-1., 0.), contact_bodies=(a, b),
                    local_vehicle='player', bot_vehicle='bot',
                    local_matrix=object(), bot_matrix=object())

    def test_vertical_seam_recovery_requires_both_plates_at_same_native_point(self):
        runtime = object.__new__(battle_tests.BattleRuntime)
        runtime._vector = tuple
        proof = self.proof()
        calls = []
        def plate(vehicle, matrix, point, normal, chassis_matrix=None):
            calls.append((vehicle, point))
            return ({'armor': 100. if vehicle == 'player' else 50., 'screened': False}
                    if abs(point[2]) >= .1 else None)
        runtime._native_ram_vehicle_armor = plate
        matched, unused_a, unused_b = runtime._native_ram_contact_plate_pair(proof)
        self.assertIsNotNone(matched)
        self.assertAlmostEqual(.12, abs(proof['armor_hit_point'][2]))
        self.assertEqual(calls[-1][1], calls[-2][1])
        self.assertTrue(all(tank_collision.body_contains_point(body, proof['armor_hit_point'])
                            for body in proof['contact_bodies']))

    def test_opposite_seams_never_mix_unrelated_player_and_bot_plates(self):
        runtime = object.__new__(battle_tests.BattleRuntime)
        runtime._vector = tuple
        proof = self.proof()
        def plate(vehicle, matrix, point, normal, chassis_matrix=None):
            available = point[2] > .1 if vehicle == 'player' else point[2] < -.1
            return {'armor': 100., 'screened': False} if available else None
        runtime._native_ram_vehicle_armor = plate
        matched, unused_a, unused_b = runtime._native_ram_contact_plate_pair(proof)
        self.assertIsNone(matched)
        self.assertNotIn('armor_hit_point', proof)

    def test_tangent_retries_cannot_leave_either_frozen_hull(self):
        proof = self.proof()
        proof['contact_bodies'][1]['z'] = -1.99
        points = tank_collision.ram_contact_sample_points(
            proof['hit_point'], proof['contact_y_span'],
            proof['contact_normal'], proof['contact_bodies'])
        lateral = [point for point in points if point[2] != 0.]
        self.assertTrue(lateral)
        self.assertTrue(all(point[2] < 0. for point in lateral))
        self.assertTrue(all(tank_collision.body_contains_point(body, point)
                            for point in lateral for body in proof['contact_bodies']))


if __name__ == '__main__':
    unittest.main()
