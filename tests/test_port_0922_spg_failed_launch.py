"""M12 regression: terminal exact-path failures must release frozen laying."""

import unittest

import test_port_0922_artillery_controller as controller_fixture
import test_port_0922_bot_runtime as bot_fixture
import test_port_0922_battle_runtime as battle_fixture


class FailedLaunchTests(unittest.TestCase):
    def setUp(self):
        self.controller_module = controller_fixture._load()
        fixture = bot_fixture.BotRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.bot_module = fixture.module
        self.controller = self.controller_module.ArtilleryController()
        self.source = dict(id=11, x=0.0, y=0.0, z=0.0, yaw=0.0,
                           pitch=0.0, roll=0.0, speed=0.0, fire_seq=0,
                           critical={}, profile={'class_tag': 'SPG'})
        self.target = dict(kind='human', network_id=2, alive=True,
                           position=(0.0, 0.0, 200.0), speed=0.0)
        self.descriptor = bot_fixture._combat_descriptor(dispersion=0.03)
        self.descriptor.gun.pitchLimits = {'absolute': (-1.55, 0.15)}
        shot = self.descriptor.gun.shots[0]
        shot.update(speed=425.0, gravity=143.0, maxDistance=10000.0)
        self.gun = self.bot_module._BotGunState(self.descriptor)
        self.gun.elapsed = 10.0
        native = battle_fixture._runtime()
        self.battle = battle_fixture.BattleRuntime(native)
        native.bigworld.entities[10] = battle_fixture._Vehicle(
            10, battle_fixture._Descriptor(), battle_fixture._Vector(0, 0, 0),
            (0, 0, 0), {'health': 500})
        self.battle._records['bot:11'] = {'engine_id': 10}
        self.battle._artillery = self.controller
        self.battle._bot_direct_launch_origin = lambda *unused: (0.0, 0.0, 0.0)
        self.runtime = self.bot_module.BotRuntime(
            1, artillery_launch_probe=self.battle._bot_artillery_launch,
            artillery_launch_cancel=self.controller.cancel_launch,
            ballistic_solution_probe=self.controller.solution)
        self.runtime.round_id = 7

    def align(self, solution):
        self.source.update(aim_yaw=solution['yaw'], gun_pitch=solution['pitch'],
                           gun_aligned=True)

    def prove(self, now, probe):
        for index in range(100):
            self.controller.advance(now + index * 0.0001, 4, probe)

    def receipt(self, solution, now):
        return self.runtime._artillery_launch_receipt(
            self.source, self.target, self.descriptor, 0, self.gun, solution, now)

    def test_failed_low_arc_releases_intent_and_proves_high_before_firing(self):
        low = self.controller._candidates(
            self.source, self.target, self.descriptor, 0)[0]
        self.align(low)
        self.assertIsNone(self.receipt(low, 1.0))
        original = self.runtime._artillery_intents[11]
        self.prove(1.0, lambda first, second: second)
        self.assertIsNone(self.receipt(low, 1.05))
        self.assertEqual('world_blocked', self.source['_spg_launch_failure']['reason'])
        self.assertNotIn(11, self.runtime._artillery_intents)
        self.assertNotIn(11, self.runtime._artillery_reproofs)
        self.assertNotIn(11, self.controller._launch_keys)
        self.assertEqual(0, self.source['fire_seq'])
        self.assertIsNone(self.runtime._ballistic_solution(
            self.source, self.target, self.descriptor, 0, 1.06))
        self.prove(1.06, lambda first, second: None)
        high = self.runtime._ballistic_solution(
            self.source, self.target, self.descriptor, 0, 1.10)
        self.assertEqual('high', high['arc'])
        self.align(high)
        self.assertIsNone(self.receipt(high, 1.10))
        replacement = self.runtime._artillery_intents[11]
        self.assertEqual(original['fire_seq'], replacement['fire_seq'])
        expected = self.bot_module._dispersed_barrel_angles(
            11, 7, 1, high['yaw'], high['pitch'],
            self.bot_module._effective_shot_dispersion(
                self.gun, self.source, self.descriptor))
        self.assertEqual(expected, (replacement['shot_yaw'], replacement['shot_pitch']))
        self.prove(1.10, lambda first, second: None)
        receipt = self.receipt(high, 1.15)
        self.assertIsNotNone(receipt)
        self.assertTrue(self.runtime._fire(
            self.source, self.gun, 1.0, self.descriptor, launch_receipt=receipt))
        self.assertEqual(1, self.source['fire_seq'])

    def test_failure_after_target_motion_replans_without_blacklisting_current_low(self):
        low = self.controller._candidates(
            self.source, self.target, self.descriptor, 0)[0]
        self.align(low)
        self.assertIsNone(self.receipt(low, 2.0))
        self.prove(2.0, lambda first, second: second)
        self.target['position'] = (10.0, 0.0, 200.0)
        self.assertIsNone(self.receipt(low, 2.05))
        self.assertEqual({}, self.controller._rejected_arcs)
        self.assertIsNone(self.runtime._ballistic_solution(
            self.source, self.target, self.descriptor, 0, 2.06))
        self.prove(2.06, lambda first, second: None)
        fresh = self.runtime._ballistic_solution(
            self.source, self.target, self.descriptor, 0, 2.10)
        self.assertEqual('low', fresh['arc'])
        self.assertNotEqual(low['yaw'], fresh['yaw'])

    def test_pending_exact_work_keeps_frozen_intent_and_does_not_replan(self):
        low = self.controller._candidates(
            self.source, self.target, self.descriptor, 0)[0]
        self.align(low)
        self.assertIsNone(self.receipt(low, 3.0))
        intent = self.runtime._artillery_intents[11]
        self.controller.advance(3.01, 1, lambda first, second: None)
        self.assertIsNone(self.receipt(low, 3.02))
        self.assertIs(intent, self.runtime._artillery_intents[11])
        self.assertEqual({}, self.controller._rejected_arcs)

    def test_all_failed_families_remove_lane_until_motion_or_expiry(self):
        for arc in ('low', 'high'):
            self.controller.reject_launch_arc(
                self.source, self.target, 0, arc, self.target['position'], 4.0)
        self.assertEqual((True, None), self.controller.request(
            self.source, self.target, self.descriptor, 0, 4.01))
        other = dict(self.target, network_id=3)
        self.assertEqual((False, None), self.controller.request(
            self.source, other, self.descriptor, 0, 4.02))
        self.target['position'] = (2.0, 0.0, 200.0)
        self.assertEqual((False, None), self.controller.request(
            self.source, self.target, self.descriptor, 0, 4.03))
        self.prove(4.03, lambda first, second: None)
        self.assertIsNotNone(self.controller.solution(
            self.source, self.target, self.descriptor, 0, 4.08))
        self.controller.reject_launch_arc(
            self.source, self.target, 0, 'low', self.target['position'], 5.0)
        self.assertEqual((), self.controller._planning_key(
            self.source, self.target, 0, 7.51)[6])
        self.controller.reset()
        self.assertEqual({}, self.controller._rejected_arcs)

    def test_timeout_releases_hold_without_claiming_a_proved_world_blocker(self):
        low = self.controller._candidates(
            self.source, self.target, self.descriptor, 0)[0]
        self.align(low)
        self.assertIsNone(self.receipt(low, 8.0))
        self.controller.advance(48.01, 0, lambda first, second: None)
        self.assertIsNone(self.receipt(low, 48.02))
        self.assertEqual('timeout', self.source['_spg_launch_failure']['reason'])
        self.assertNotIn(11, self.runtime._artillery_intents)
        self.assertEqual({}, self.controller._rejected_arcs)

    def test_alternate_proof_survives_retry_cooldown_and_shot_clears_rejection(self):
        self.controller.reject_launch_arc(
            self.source, self.target, 0, 'low', self.target['position'], 10.0)
        self.controller.request(
            self.source, self.target, self.descriptor, 0, 10.01)
        key = next(iter(self.controller.queue.jobs))
        self.controller.advance(13.0, 1, lambda first, second: None)
        self.controller.request(
            self.source, self.target, self.descriptor, 0, 13.01)
        self.assertIn(key, self.controller.queue.jobs)
        self.assertEqual(1, self.controller.queue.jobs[key]['chord'])
        self.prove(13.02, lambda first, second: None)
        solution = self.controller.solution(
            self.source, self.target, self.descriptor, 0, 13.05)
        self.assertEqual('high', solution['arc'])
        self.source['fire_seq'] = 1
        self.assertEqual((), self.controller._planning_key(
            self.source, self.target, 0, 13.06)[6])

    def test_late_high_failure_does_not_restart_the_already_failed_low_family(self):
        self.controller.reject_launch_arc(
            self.source, self.target, 0, 'low', self.target['position'], 20.0)
        self.controller.request(
            self.source, self.target, self.descriptor, 0, 20.01)
        self.prove(23.0, lambda first, second: None)
        high = self.controller.solution(
            self.source, self.target, self.descriptor, 0, 23.02)
        self.align(high)
        self.assertIsNone(self.receipt(high, 23.03))
        self.prove(26.0, lambda first, second: second)
        self.assertIsNone(self.receipt(high, 26.02))
        self.assertEqual((True, None), self.controller.request(
            self.source, self.target, self.descriptor, 0, 26.03))
        self.assertEqual(('high', 'low'), self.controller._planning_key(
            self.source, self.target, 0, 26.03)[6])


if __name__ == '__main__':
    unittest.main()
