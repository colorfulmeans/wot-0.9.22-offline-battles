"""Small native trees, realised recovery failures and finite firing holds."""
import math
import contextlib
import io
import sys
import unittest
from unittest import mock

import test_port_0922_airfield_spawn as spawn_fixture
from test_port_0922_server_bot_ai import BotPlanner
from gui.mods.offline_lan_0922.ai.driver import LocalDriver, RECOVERY_YAW_OFFSET
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor


class AirfieldFollowupTests(unittest.TestCase):
    def setUp(self):
        self.scene = spawn_fixture.AirfieldSpawnTests()
        self.scene.setUp()
        self.addCleanup(self.scene.doCleanups)

    def test_positive_small_tree_health_is_not_a_motion_size_filter(self):
        for health in (1, 3, 5, 10):
            with self.subTest(health=health), self.scene.tree_scene() as (
                    battle, desc, unused, calls):
                cache = sys.modules['AreaDestructibles'].g_cache
                with mock.patch.object(cache, 'getDescByFilename',
                        return_value={'type': 1, 'health': health, 'mass': 20}):
                    self.assertEqual('crushed', battle._resolve_bot_motion(
                        8, (0., 0., -2.), 0., 20., desc, .2, 1.))
                    self.assertEqual(1, len(calls))
            sensor.g_offh_tree_state = {}

    def test_player_tree_contract_accepts_the_same_health_three_identity(self):
        with self.scene.tree_scene() as (battle, desc, unused, calls):
            cache = sys.modules['AreaDestructibles'].g_cache
            with mock.patch.object(cache, 'getDescByFilename',
                    return_value={'type': 1, 'health': 3, 'mass': 20}):
                battle._worker_mode = False
                detail = battle._tree_motion_proposal(
                    (0., 0., -2.), 0., (0., 0., 2.), 0., 20., desc, 1., .2)
                self.assertTrue(detail['requires_commit'])
                result = sensor.commit_tree_contacts(1, detail['token'],
                    battle._vector((0., 0., -2.)), 0.,
                    battle._vector((0., 0., 2.)), 0., 20., desc, 1., dt=.2)
                self.assertEqual('crushed', result['status'])
                self.assertEqual(1, len(calls))

    def test_nonpositive_and_unrammable_tree_sentinels_remain_excluded(self):
        for health in (-2, 0, 40000):
            with self.subTest(health=health), self.scene.tree_scene() as (
                    battle, desc, unused, calls):
                cache = sys.modules['AreaDestructibles'].g_cache
                with mock.patch.object(cache, 'getDescByFilename',
                        return_value={'type': 1, 'health': health, 'mass': 20}):
                    self.assertEqual('clear', battle._resolve_bot_motion(
                        8, (0., 0., -2.), 0., 20., desc, .2, 1.))
                    self.assertEqual([], calls)
            sensor.g_offh_tree_state = {}

    def drive(self, driver, pose=lambda yaw: False):
        return driver.drive(17, 1, (0., 0., 0.), 0., 0., .1,
            (0., 0., -20.), [], lambda *unused: True, pose_clear=pose)

    def test_real_reverse_failure_selects_the_checked_forward_exit(self):
        driver = LocalDriver()
        driver._state(17, 1, (0., 0., 0.)).update(recovery_time=.85)
        driver.remember_failure(17, math.pi, 5.)
        self.assertEqual('forward_escape', self.drive(driver)['recovery_mode'])
        driver.remember_failure(17, 0., 5.)
        self.assertEqual('blocked', self.drive(driver)['recovery_mode'])

    def test_failed_curved_reverse_retains_only_the_straight_exit(self):
        driver = LocalDriver()
        driver._state(17, 1, (0., 0., 0.)).update(recovery_time=.85, recovery_side=1.)
        driver.remember_failure(17, math.pi + RECOVERY_YAW_OFFSET*.5, 5.)
        command = self.drive(driver, lambda yaw: True)
        self.assertLess(command['throttle'], 0.)
        self.assertEqual(0., command['turn'])

    def test_realised_low_lip_failure_changes_the_next_runtime_command(self):
        from test_port_0922_driver_recovery_feedback import DriverRecoveryFeedbackTests
        case = DriverRecoveryFeedbackTests()
        case.setUp()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                runtime, scene, commands, unused = case._runtime()
                self.assertTrue(scene.probe((0., 0., 0.), math.pi)['clear'])
                runtime.update(.1, 1.)
                self.assertEqual('reverse_turn', commands[-1]['recovery_mode'])
                self.assertEqual(0., runtime.states[11]['z'])
                runtime.update(.1, 1.1)
                self.assertEqual('forward_escape', commands[-1]['recovery_mode'])
                self.assertGreater(runtime.states[11]['z'], 0.)
        finally:
            case.tearDown()

    def test_two_real_failed_runtime_exits_do_not_repeat_a_powered_sweep(self):
        from test_port_0922_driver_recovery_feedback import DriverRecoveryFeedbackTests
        case = DriverRecoveryFeedbackTests()
        case.setUp()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                runtime, scene, commands, unused = case._runtime(closed_front=True)
                for frame in range(3):
                    runtime.update(.1, 1.+frame*.1)
                self.assertEqual('blocked', commands[-1]['recovery_mode'])
                self.assertEqual(0., commands[-1]['throttle'])
                self.assertEqual(0., runtime.states[11]['z'])
        finally:
            case.tearDown()

    def test_confirmed_house_blockage_stops_aim_without_canceling_route_or_reproof(self):
        from test_port_0922_driver_recovery_feedback import DriverRecoveryFeedbackTests
        case = DriverRecoveryFeedbackTests()
        case.setUp()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                runtime, unused, unused_commands, unused_desc = case._runtime()
            source = runtime.states[11]
            target = dict(kind='bot', network_id=6, position=(0., 0., 180.))
            command = dict(target_id=6, target_kind='bot', fire_allowed=True,
                aim_position=target['position'], move_position=(0., 0., -15.))
            key = runtime._shot_los_key(source, target)
            runtime._shot_los_cache[key] = (10., False)
            blocked, gun_target = runtime._apply_blocked_direct_aim(
                source, command, target, 10.1)
            self.assertIsNone(gun_target)
            self.assertIsNone(blocked['target_id'])
            self.assertNotIn('aim_position', blocked)
            self.assertEqual(command['move_position'], blocked['move_position'])
            self.assertEqual(6, command['target_id'])
            proofs = []
            runtime.firing_lane_probe = lambda *unused: proofs.append(1) or True
            self.assertIsNone(runtime._apply_blocked_direct_aim(
                source, command, target, 10.3, [0])[1])
            self.assertEqual([], proofs)
            budget = [1]
            self.assertIs(target, runtime._apply_blocked_direct_aim(
                source, command, target, 10.3, budget)[1])
            self.assertEqual([1], proofs)
            self.assertEqual([0], budget)
            runtime.firing_lane_probe = lambda *unused: True
            self.assertTrue(runtime._shot_clear(source, target, 10.2, force=True))
            cleared, gun_target = runtime._apply_blocked_direct_aim(
                source, command, target, 10.2)
            self.assertIs(target, gun_target)
            self.assertTrue(cleared['fire_allowed'])
            runtime._shot_los_cache[key] = (10., False)
            self.assertIs(target, runtime._apply_blocked_direct_aim(
                source, command, target, 30.)[1])
            source['profile']['class_tag'] = 'SPG'
            self.assertIs(target, runtime._apply_blocked_direct_aim(
                source, command, target, 10.1)[1])
        finally:
            case.tearDown()


class FiringHoldTests(unittest.TestCase):
    def setUp(self):
        self.planner = BotPlanner()
        self.bot = dict(id=20, state=dict(x=-143., y=1.1, z=275.,
                        fire_seq=2, reload_time=0., ammo_remaining=[10, 0, 0],
                        shell_index=0))
        self.goal = dict(x=-100., y=1.1, z=275.)
        self.anchor = dict(x=-180., y=1.1, z=275.)

    def order(self, now, mode='support_hold'):
        order = dict(combat_mode=mode, throttle_override=0.,
                     target_id=6, target_kind='bot', fire_allowed=True)
        self.planner._release_unproductive_firing_hold(
            order, self.bot, self.goal, self.anchor, now)
        return order

    def test_ready_unfired_hold_resumes_a_route_leg_with_a_finite_lease(self):
        self.assertEqual('support_hold', self.order(1.)['combat_mode'])
        moved = self.order(9.)
        self.assertEqual('route', moved['combat_mode'])
        self.assertEqual(self.goal, moved['move_position'])
        self.assertTrue(moved['fire_allowed'])
        self.assertEqual('route', self.order(10.)['combat_mode'])
        self.assertEqual('support_hold', self.order(13.)['combat_mode'])

    def test_reloading_shots_and_deliberate_cover_holds_do_not_trigger(self):
        self.order(1.)
        self.bot['state']['reload_time'] = 20.
        self.assertEqual('support_hold', self.order(30.)['combat_mode'])
        self.bot['state']['reload_time'] = 0.
        self.order(31.)
        self.bot['state']['fire_seq'] += 1
        self.assertEqual('support_hold', self.order(38.)['combat_mode'])
        self.assertEqual('cover_hold', self.order(50., 'cover_hold')['combat_mode'])
        self.assertEqual('low_health_defend', self.order(60., 'low_health_defend')['combat_mode'])

    def test_real_commander_hold_resumes_its_authored_route_and_resets_on_target_loss(self):
        from test_port_0922_server_bot_ai import _bot, _route, _state
        bot = _bot(20, 1, 0, _route('lane', [(0, 0, False),
                   (0, 100, False)]), 'mediumTank')
        bot['state'] = _state(20, 1, 0, 0)
        focus = dict(id=6, target_kind='bot', visible=True,
                     shootable_by_bot_ids=[20], position=dict(x=0., y=0., z=180.))
        first = self.planner._order_for(bot, 0, 1, focus, [focus], 1.)
        self.assertEqual('engage', first['combat_mode'])
        moved = self.planner._order_for(bot, 0, 1, focus, [focus], 9.)
        self.assertEqual('route', moved['combat_mode'])
        self.assertGreater(moved['move_position']['z'], 0.)
        self.planner._order_for(bot, 0, 1, None, [], 10.)
        self.assertNotIn(20, self.planner._firing_holds)
        renewed = self.planner._order_for(bot, 0, 1, focus, [focus], 30.)
        self.assertEqual('engage', renewed['combat_mode'])


if __name__ == '__main__':
    unittest.main()
