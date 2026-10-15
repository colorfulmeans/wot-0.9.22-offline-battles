"""Bot support must stay on its road beneath an unrelated upper deck."""
import contextlib
import io
import math
import sys
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixture


class BotSupportLayerTests(unittest.TestCase):
    # Captured Highway T71 heights. The collision planes below are an
    # analytic reproduction of the layer gap, not the native map mesh.
    FLOOR = -11.103339195251465
    DECK = -5.151131629943848

    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        mounted = mock.patch.dict(sys.modules, {
            'CurrentVehicle': fixture._mounted_current_vehicle_module()})
        mounted.start()
        self.addCleanup(mounted.stop)
        self.runtime = fixture._runtime()
        self.battle = fixture.BattleRuntime(self.runtime)
        self.addCleanup(self.battle.stop, show_login=False)
        self.assertTrue(self.battle.start({
            'map': '01_karelia', 'vehicle': 'ussr:R11_MS-1',
            'name': 'Player'}, fixture._minimal_start(), fixture._Client()))
        for unused in range(8):
            if self.battle.state == 'running':
                break
            self.assertTrue(self.runtime.bigworld.callbacks)
            self.runtime.bigworld.callbacks.pop(0)()
        self.assertEqual('running', self.battle.state, self.battle.error)
        self.bots = self.battle._bots

    def collision_planes(self, floor, deck=None):
        def collide(space, start, end, skip_flags, ground_filter=None):
            if start.y <= end.y:
                return None
            surfaces = [(floor(start.x, start.z), 1.0, 8)]
            if deck is not None:
                surfaces.extend(((deck, 1.0, 0x4980),
                                 (deck - 0.2, -1.0, 0x4980)))
            for height, normal, flags in sorted(surfaces, reverse=True):
                if flags & skip_flags or not end.y <= height <= start.y:
                    continue
                if ground_filter is not None and not ground_filter(
                        flags >> 8, flags & 255, 0, 0):
                    continue
                return (fixture._Vector(start.x, height, start.z),
                        fixture._Vector(0, normal, 0))
            return None
        self.runtime.bigworld.wg_collideSegment = collide

    def state(self, y=None):
        return dict(id=14, x=0.0, y=self.FLOOR if y is None else y,
                    z=0.04, yaw=0.0, speed=0.4, half_length=2.4026,
                    half_width=1.47996, vertical_speed=0.0, airborne=False,
                    grounded_once=True, last_drive_pitch=0.0,
                    terrain_pitch=0.0, pitch=0.0, roll=0.0)

    def test_falling_bot_below_bridge_never_reacquires_overhead_deck(self):
        for alive in (True, False):
            with self.subTest(alive=alive):
                self.collision_planes(lambda x, z: self.FLOOR, self.DECK)
                state = self.state(y=self.DECK - 0.7)
                state.update(alive=alive, health=1000 if alive else 0, max_health=1000,
                    airborne=True, vertical_speed=-3., speed=0.,
                    terrain_pitch=0., pitch=0., roll=0., last_drive_pitch=0.)
                state['_basic_fall_origin_y'] = state['y']+.2
                old = (state['x'], state['y'], state['z'])
                self.assertFalse(self.bots._integrate_vertical_motion(state, .1, tick_pose=old))
                self.assertLess(state['y'], old[1])
                self.assertLess(state['vertical_speed'], -3.)
                self.assertTrue(state['airborne'])
                land = mock.Mock(return_value=0)
                with mock.patch.object(self.bots, '_apply_bot_landing_impact', land):
                    for unused in range(30):
                        before = (state['x'], state['y'], state['z'])
                        self.assertFalse(self.bots._integrate_vertical_motion(state, .1, tick_pose=before))
                self.assertAlmostEqual(self.FLOOR, state['y'])
                self.assertFalse(state['airborne'])
                land.assert_called_once()

    def test_transient_missing_floor_is_caught_after_crossing_its_height(self):
        for alive in (True,False):
            with self.subTest(alive=alive):
                self.collision_planes(lambda x,z:self.FLOOR, self.DECK)
                state=self.state(self.FLOOR+.2)
                state.update(alive=alive,airborne=True,vertical_speed=-20.,speed=0.)
                with mock.patch.object(self.bots,'_physics_ground_limit_probe',return_value=None), \
                     mock.patch.object(self.bots,'_physics_ground_probe',return_value=None):
                    self.bots._integrate_vertical_motion(state,.1)
                self.assertLess(state['y'],self.FLOOR-.1)
                land=mock.Mock(return_value=0)
                with mock.patch.object(self.bots,'_apply_bot_landing_impact',land):
                    for unused in range(5):
                        self.bots._integrate_vertical_motion(state,.1)
                self.assertAlmostEqual(self.FLOOR,state['y'])
                self.assertFalse(state['airborne'])
                land.assert_called_once()
                self.assertNotIn('_basic_fall_origin_y',state)

    def test_airborne_seam_can_rejoin_proved_continuous_rising_ground(self):
        self.collision_planes(lambda x,z:self.FLOOR+x*.25)
        state=self.state(self.FLOOR+.05)
        state.update(x=1.,z=0.,airborne=True,vertical_speed=-2.,speed=5.,
            _basic_fall_origin_y=self.FLOOR+.05)
        land=mock.Mock(return_value=0)
        with mock.patch.object(self.bots,'_apply_bot_landing_impact',land):
            self.assertFalse(self.bots._integrate_vertical_motion(state,.1,
                tick_pose=(0.,self.FLOOR,0.)))
        self.assertAlmostEqual(self.FLOOR+.25,state['y'])
        self.assertFalse(state['airborne'])
        self.assertTrue(state['_basic_continuous_support'])
        land.assert_not_called()

    def test_long_external_sweep_rejoins_continuous_ground(self):
        # The report's NC31 travelled farther than the former 7.5 m proof
        # budget. Missing that proof must not discard a real hillside floor.
        self.collision_planes(lambda x, z: self.FLOOR + x * .13)
        state = self.state(self.FLOOR + .05)
        state.update(x=12., z=0., airborne=True, vertical_speed=-7.,
                     speed=60., _basic_fall_origin_y=self.FLOOR + .05)
        land = mock.Mock(return_value=0)
        with mock.patch.object(self.bots, '_apply_bot_landing_impact', land):
            self.assertFalse(self.bots._integrate_vertical_motion(
                state, .2, tick_pose=(0., self.FLOOR, 0.)))
        self.assertAlmostEqual(self.FLOOR + 12. * .13, state['y'])
        self.assertFalse(state['airborne'])
        self.assertTrue(state['_basic_continuous_support'])
        land.assert_not_called()

    def test_long_external_sweep_cannot_prove_an_abrupt_raised_deck(self):
        self.collision_planes(lambda x, z: self.FLOOR if x < 6. else self.FLOOR + 1.56)
        state = self.state(self.FLOOR + .05)
        state.update(x=12., z=0., airborne=True, vertical_speed=-7.,
                     speed=60., _basic_fall_origin_y=self.FLOOR + .05)
        self.bots._integrate_vertical_motion(
            state, .2, tick_pose=(0., self.FLOOR, 0.))
        self.assertFalse(state['_basic_continuous_support'])
        self.assertTrue(state['airborne'])
        self.assertLess(state['y'], self.FLOOR)

    def test_rejected_uphill_settle_restores_pre_horizontal_pose(self):
        self.collision_planes(lambda x, z: self.FLOOR + x * .25)
        state = self.state()
        state.update(x=1., z=0.)
        old = (0., self.FLOOR, 0.)
        with mock.patch.object(self.bots, '_turret_motion_probe', return_value=False):
            self.assertTrue(self.bots._update_vertical_motion(state, .1, tick_pose=old))
        self.assertEqual(old, (state['x'], state['y'], state['z']))
        self.assertFalse(state['airborne'])
        self.assertNotIn('_basic_fall_origin_y', state)

    def test_rejected_landing_restores_crossed_floor_interval(self):
        self.collision_planes(lambda x, z: self.FLOOR, self.DECK)
        state = self.state(self.FLOOR - .15)
        state.update(airborne=True, vertical_speed=-2., speed=0.,
                     _basic_fall_origin_y=self.FLOOR + .2)
        old = (state['x'], state['y'], state['z'])
        with mock.patch.object(self.bots, '_turret_motion_probe', return_value=False):
            self.assertTrue(self.bots._update_vertical_motion(state, .1, tick_pose=old))
        self.assertEqual(self.FLOOR + .2, state['_basic_fall_origin_y'])
        self.assertTrue(state['airborne'])
        with mock.patch.object(self.bots, '_turret_motion_probe', return_value=True), \
                mock.patch.object(self.bots, '_apply_bot_landing_impact'):
            self.assertFalse(self.bots._update_vertical_motion(state, .1, tick_pose=old))
        self.assertAlmostEqual(self.FLOOR, state['y'])
        self.assertFalse(state['airborne'])

    def test_continuous_downhill_stays_supported_without_repeated_landings(self):
        self.collision_planes(lambda x,z:self.FLOOR-x*.25)
        state=self.state();state.update(x=0.,z=0.,speed=5.,yaw=math.pi*.5)
        land=mock.Mock(return_value=0)
        with mock.patch.object(self.bots,'_apply_bot_landing_impact',land):
            for unused in range(30):
                before=(state['x'],state['y'],state['z'])
                state['x']+=.5
                self.assertFalse(self.bots._integrate_vertical_motion(state,.1,tick_pose=before))
                self.assertAlmostEqual(self.FLOOR-state['x']*.25,state['y'])
                self.assertFalse(state['airborne'])
                self.bots._update_slope_pose(state)
        land.assert_not_called()
        self.assertAlmostEqual(math.atan(.25),state['terrain_pitch'],places=2)

    def test_live_bot_support_ignores_bridge_above_its_drivable_road(self):
        self.collision_planes(lambda x, z: self.FLOOR, self.DECK)
        state = self.state()
        # Exercise the callback supplied by actual BattleRuntime startup.
        # The old broad ground query saw the upper deck within its +6 m band
        # and rolled this clear 4 cm move back on every subsequent tick.
        for unused in range(10):
            old_pose = (state['x'], state['y'], state['z'] - 0.04)
            self.assertFalse(self.bots._integrate_vertical_motion(
                state, 0.1, tick_pose=old_pose))
            self.assertEqual(self.FLOOR, state['y'])
            self.assertFalse(state['airborne'])
            self.assertGreater(state['z'], old_pose[2])
            state['z'] += 0.04

    def test_attitude_uses_lower_road_and_bridge_top_still_supports(self):
        gradient = 0.15
        self.collision_planes(lambda x, z: self.FLOOR + z * gradient,
                              self.DECK)
        under = self.state()
        self.bots._integrate_vertical_motion(under, 0.1)
        self.assertTrue(self.bots._update_slope_pose(under))
        # The pose smoother approaches the sampled road grade; a flat bridge
        # above it must not replace that grade with zero.
        self.assertLess(under['terrain_pitch'], 0.0)
        self.assertGreaterEqual(under['terrain_pitch'], -math.atan(gradient))
        for grounded in (False, True):
            top = self.state(self.DECK)
            top['grounded_once'] = grounded
            self.assertFalse(self.bots._integrate_vertical_motion(top, 0.1))
            self.assertEqual(self.DECK, top['y'])
            self.assertFalse(top['airborne'])

    def test_real_raised_body_keeps_the_vertical_contact_rejection(self):
        self.collision_planes(lambda x, z: self.FLOOR + 1.2)
        state = self.state()
        old_pose = (0.0, self.FLOOR, 0.0)
        self.assertTrue(self.bots._integrate_vertical_motion(
            state, 0.1, tick_pose=old_pose))
        self.assertEqual(old_pose, (state['x'], state['y'], state['z']))
        self.assertEqual(0.0, state['speed'])

    def test_spawn_finds_lower_ground_and_driving_off_an_edge_still_falls(self):
        self.collision_planes(lambda x, z: self.FLOOR)
        spawn = self.state(self.FLOOR + 0.5)
        spawn['grounded_once'] = False
        self.assertFalse(self.bots._integrate_vertical_motion(spawn, 0.1))
        self.assertEqual(self.FLOOR, spawn['y'])
        self.assertTrue(spawn['grounded_once'])
        self.collision_planes(lambda x, z: self.FLOOR - 20.0)
        state = self.state()
        self.assertFalse(self.bots._integrate_vertical_motion(state, 0.1))
        self.assertTrue(state['airborne'])
        self.assertLess(state['y'], self.FLOOR)
        self.assertGreater(state['y'], self.FLOOR - 1.0)


if __name__ == '__main__':
    unittest.main()
