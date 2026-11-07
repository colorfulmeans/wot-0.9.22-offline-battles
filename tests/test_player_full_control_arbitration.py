"""Final native-input arbitration through the complete foreground runtime.

The scene supplies flat support, component hit testers and an observed native
barrel actuator. The full copied planner/driver, new attack planner, control
wrapper, admission and physical shot transaction are not replaced. These are
consumer regressions, not Windows BigWorld physics acceptance.
"""
import unittest

import test_player_limited_traverse as fixtures


class FullControlArbitrationTests(unittest.TestCase):
    def scene(self, distance=190., clip=6, burst=3, speed=0.):
        scene = fixtures.TraverseScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(limits=None, tag='mediumTank', clip=clip,
                        burst=burst, bearing=0.)
        scene.pose(scene.target, (0., 0., distance))
        scene.runtime.attack_policy.reset()
        scene.rotator_enabled = True
        scene.battle._local_speed = speed
        return scene

    def advance_until(self, scene, predicate, frames=90):
        for unused in range(frames):
            row = scene.tick()
            self.assertIsNone(scene.control.last_control_failure, row)
            self.assertTrue(scene.control.active, row)
            if predicate(row):
                return row
        self.fail('foreground transition did not finish: %r' % scene.trace[-4:])

    def test_medium_range_current_shell_proof_stops_at_final_native_sender(self):
        for distance, speed in ((185., 0.), (189.256, -3.07),
                                (194.574, 3.64), (195., 0.)):
            with self.subTest(distance=distance, speed=speed):
                scene = self.scene(distance=distance, speed=speed)
                row = self.advance_until(scene, lambda result: result['action'] == 'aim')
                candidate = scene.runtime.attack_policy.decision['candidate']
                self.assertEqual('passed', candidate['armor'])
                self.assertEqual('clear', candidate['line'])
                self.assertEqual(scene.target.id, candidate['target']['engine_id'])
                self.assertEqual((0., 0., True), row['sender'], row)
                self.assertEqual('engage', scene.runtime._last_order['combat_mode'])

    def test_ready_lane_reaches_real_fire_transaction_without_shadow_gun_debit(self):
        scene = self.scene(clip=6, burst=3)
        before = list(scene.battle._gun_state.ammo)
        self.advance_until(scene, lambda result: bool(scene.launches()))
        self.assertEqual(1, len(scene.launches()))
        self.assertEqual(before[0] - 1, scene.battle._gun_state.ammo[0])
        self.assertEqual(5, scene.battle._gun_state.clip)
        self.assertEqual((0., 0., True), scene.trace[-1]['sender'])
        self.assertEqual(1, scene.control.shot_commits)

    def test_pending_native_geometry_cannot_retain_an_unproved_stationary_hold(self):
        scene = self.scene()
        scene.runtime.set_mission('attack', dict(position=(0., 0., 24.)))
        before = list(scene.battle._gun_state.ammo)

        def unavailable():
            raise RuntimeError('native world observation is pending')

        scene.on_probe = unavailable
        moving = 0
        for unused in range(50):
            row = scene.tick()
            self.assertIsNone(scene.control.last_control_failure, row)
            self.assertIsNone(scene.runtime.attack_policy.search_started)
            self.assertEqual(before, scene.battle._gun_state.ammo)
            moving += bool(row['sender'][0] or row['sender'][1])
        self.assertGreater(moving, 0, scene.trace[-4:])
        self.assertFalse(scene.launches())

    def test_reopened_lane_retires_the_firing_position_navigation_receipt(self):
        scene = self.scene(distance=60., clip=1, burst=1)
        scene.world = [((-100., -100., 5.), (100., 100., 15.))]
        self.advance_until(scene, lambda result: result['action'] == 'firing_position')
        policy = scene.runtime.attack_policy
        self.assertEqual('copied_ordinary_navigation', policy.navigation_receipt['owner'])
        self.assertIsNone(policy.search_started)
        scene.trigger.assert_not_called()

        scene.world = []
        scene.set_hull(.01)
        row = self.advance_until(scene, lambda result: result['action'] == 'aim')
        self.assertEqual((0., True), row['sender'][::2])
        self.assertFalse(policy.navigation_receipt)
        self.advance_until(scene, lambda result: scene.control.automatic_commits == 1)
        self.assertEqual(1, len(scene.launches()))

    def test_explicit_attack_destination_retains_motion_ownership_over_ready_lane(self):
        scene = self.scene()
        goal = (0., 0., 24.)
        scene.runtime.set_mission('attack', dict(position=goal))
        row = self.advance_until(scene, lambda result: result['action'] == 'aim')
        self.assertEqual(goal, scene.runtime._last_order.get('move_position'), row)
        self.assertTrue(row['sender'][0] or row['sender'][1], row)

    def test_dead_target_does_not_leave_a_stale_aim_hold_in_the_real_driver(self):
        scene = self.scene()
        self.advance_until(scene, lambda result: result['action'] == 'aim')
        scene.target.health = 0
        record = scene.battle._records['bot:%s' % scene.target.id]
        record['state'].update(health=0, alive=False)
        scene.runtime.set_mission('attack', dict(position=(0., 0., 24.)))
        row = self.advance_until(scene, lambda result:
            bool(result['sender'][0] or result['sender'][1]))
        self.assertNotEqual('aim', row['action'])
        self.assertIsNone(scene.runtime.attack_policy.decision.get('candidate'))


if __name__ == '__main__':
    unittest.main()
