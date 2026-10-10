"""Rear threats must be reachable before a limited turret resumes tactics."""
import math
import sys
import unittest
import types
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.ai import driver
import test_port_0922_bot_runtime as harness


class RearLimitedAimTests(unittest.TestCase):
    def aim(self, bearing, mode='withdraw', recovery='reverse_withdraw',
            limits=(-math.pi / 2, math.pi / 2), rear_turn=0, has_target=True):
        return driver.combat_hull_aim(
            0, bearing, limits[0], limits[1], -.2, -1, recovery,
            has_target, combat_mode=mode, movement_intent=True,
            rear_turn=rear_turn)

    def test_t110e4_rear_threat_brakes_withdrawal_and_lays_hull(self):
        for mode in ('withdraw', 'low_health_retreat', 'under_fire_withdraw',
                     'crossfire_withdraw', 'advance', 'flank', 'route'):
            with self.subTest(mode=mode):
                self.assertEqual((1., 0., True), self.aim(2.9, mode))
                self.assertEqual((-1., 0., True), self.aim(-2.9, mode))

    def test_same_rear_target_keeps_side_across_pi_seam(self):
        turn, throttle, active = self.aim(math.pi - .001)
        self.assertEqual((1., 0., True), (turn, throttle, active))
        for bearing in (-math.pi + .001, math.pi - .002, -math.pi + .003):
            turn, throttle, active = self.aim(bearing, rear_turn=turn)
            self.assertEqual((1., 0., True), (turn, throttle, active))
            self.assertEqual(math.pi / 2, driver.limited_traverse_target(
                bearing, -math.pi / 2, math.pi / 2, turn))

    def test_rear_target_converges_and_does_not_fire_at_clamped_stop(self):
        yaw, prior = 0., 0.
        for frame in range(100):
            target = math.pi + (.001 if frame % 2 else -.001)
            turn, throttle, active = driver.combat_hull_aim(
                yaw, target, -math.pi / 2, math.pi / 2, 0, -1,
                'reverse_withdraw', True, combat_mode='withdraw',
                movement_intent=True, rear_turn=prior)
            if not active:
                self.assertLessEqual(abs(driver._angle_delta(target, yaw)), math.pi / 2)
                break
            self.assertEqual(0., throttle)
            self.assertGreater(turn, 0)
            prior = turn
            yaw += turn * .04
        else:
            self.fail('rear hull laying did not converge')
        self.assertFalse(driver.gun_aligned(math.pi, 0, math.pi / 2, 0, 0))

    def test_reachable_rear_target_with_wide_turret_keeps_withdrawal(self):
        self.assertEqual((-.2, -1., False), self.aim(
            2.9, limits=(-3., 3.)))

    def test_full_turret_keeps_reverse_and_normal_wrap(self):
        self.assertEqual((-.2, -1., False), self.aim(
            3.1, limits=(-math.pi, math.pi)))

    def test_forward_fixed_gun_retreat_retains_existing_route_owner(self):
        self.assertEqual((-.2, -1., False), self.aim(
            1., limits=(-.1, .1)))

    def test_fixed_and_asymmetric_rear_arcs_use_shared_rule(self):
        for limits in ((0., 0.), (-.1, .1), (.2, .8)):
            self.assertEqual((1., 0., True), self.aim(2.9, limits=limits))

    def test_physical_and_navigation_recovery_keep_control(self):
        for recovery in ('avoid', 'blocked', 'reverse_turn', 'pivot_recovery',
                         'forward_escape', 'short_forward_escape',
                         'short_reverse_escape', 'contact_escape', 'wreck_push',
                         'friendly_yield', 'nav_wait', 'physical_hold'):
            self.assertEqual((-.2, -1., False), self.aim(2.9, recovery=recovery))

    def test_lost_target_does_not_turn_toward_last_known_enemy(self):
        self.assertEqual((-.2, -1., False), self.aim(2.9, has_target=False))

    def test_new_target_chooses_its_own_shortest_side(self):
        self.assertEqual((-1., 0., True), self.aim(-2.9, rear_turn=0))

    def test_reachable_target_uses_its_exact_bearing(self):
        self.assertEqual(-.5, driver.limited_traverse_target(
            -.5, -math.pi / 2, math.pi / 2, 1))


class RearTraverseRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.runtime = self.fixture.runtime
        self.runtime.battle_start(self.fixture.start)
        self.descriptor = harness._combat_descriptor(
            turret_yaw_limits=(-math.pi / 2, math.pi / 2), turret_speed=1.)
        self.runtime._descriptors[11] = self.descriptor
        self.runtime._gun_yaw_limits[11] = (-math.pi / 2, math.pi / 2, True)
        self.state = self.runtime.states[11]
        self.state.update(x=0., y=0., z=0., yaw=0., pitch=0., roll=0.,
                          turret_yaw=math.pi / 2, aim_yaw=math.pi / 2,
                          gun_pitch=0., _rear_hull_aim=(('human', 2), 1.))

    def tearDown(self):
        self.fixture.tearDown()

    def aim(self, native=False, target_id=2):
        bearing = -math.pi + .001
        target = dict(id=target_id, network_id=target_id, kind='human', alive=True,
                      position=(math.sin(bearing) * 100., 0., math.cos(bearing) * 100.))
        command = {'_ballistic_solution': dict(
            aim_position=target['position'], yaw=bearing, pitch=0., flight_time=1.)}
        weapons = None
        tick = None
        if native:
            weapons = mock.Mock()
            weapons.configure_aim_from_descriptor.return_value = False
            def after_motion(*unused):
                self.state['gun_aligned'] = True
                return ()
            weapons.after_motion.side_effect = after_motion
            self.runtime._native_simulation = types.SimpleNamespace(weapons=weapons)
            tick = {}
        self.runtime._update_gun_aim(self.state, command, target, .1, weapon_tick=tick)
        return weapons

    def test_python_slew_holds_selected_stop_and_keeps_fire_denied(self):
        self.aim()
        self.assertAlmostEqual(math.pi / 2, self.state['turret_yaw'])
        self.assertFalse(self.state['gun_aligned'])

    def test_native_slew_receives_same_stop_but_exact_alignment_stays_denied(self):
        weapons = self.aim(native=True)
        self.assertEqual(math.pi / 2, weapons.aim_input.call_args[0][0])
        self.assertFalse(self.state['gun_aligned'])
        self.assertLess(self.state['_diagnostic_aim_intent']['turret_yaw'], -3.)

    def test_changed_target_does_not_inherit_previous_traverse_side(self):
        self.aim(target_id=3)
        self.assertLess(self.state['turret_yaw'], math.pi / 2)

    def test_runtime_brakes_reverse_for_rear_target_and_clears_lock_on_loss(self):
        runtime = self.fixture.module.BotRuntime(
            1, descriptor_resolver=lambda unused: self.descriptor,
            direction_probe=lambda *unused: dict(clear=True, slope=0.),
            ground_probe=lambda *unused: 0., physics_ground_probe=lambda *unused: 0.,
            spawn_resolver=lambda *unused: ((0., 0., 0.), 0.),
            visibility_probe=lambda *unused: True,
            firing_lane_probe=lambda *unused: True,
            baked_graph=harness._flat_open_graph())
        runtime.battle_start(self.fixture.start)
        order = dict(id=11, team=2, combat_mode='under_fire_withdraw',
                     target_kind='human', target_id=2, move_position=(0., 0., -20.),
                     aim_position=(.1, 0., -100.), face_position=(.1, 0., -100.),
                     fire_range=500., fire_allowed=True, throttle_override=None)
        runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[order]))
        player = harness._admit_player(dict(
            id=2, team=1, alive=True, x=.1, y=0., z=-100.))
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            runtime.update(.05, .05, players=[player])
        state = runtime.states[11]
        self.assertTrue(state['hull_aiming'])
        self.assertGreater(state['yaw'], 0.)
        self.assertEqual(0, state['movement_dir'])
        self.assertEqual(('human', 2), state['_rear_hull_aim'][0])
        self.assertEqual(0, state['fire_seq'])
        order.update(target_kind=None, target_id=None, fire_allowed=False)
        runtime._apply_orders(dict(bot_order_revision=2, bot_orders=[order]))
        with contextlib.redirect_stdout(io.StringIO()):
            runtime.update(.05, .5, players=[])
        self.assertNotIn('_rear_hull_aim', state)


if __name__ == '__main__':
    unittest.main()
