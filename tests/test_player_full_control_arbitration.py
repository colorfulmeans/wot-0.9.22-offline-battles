"""Final native-input arbitration through the complete foreground runtime.

The scene supplies flat support, component hit testers and an observed native
barrel actuator. The shared planner/driver, attack planner, control
wrapper, admission and physical shot transaction are not replaced. These are
consumer regressions, not Windows BigWorld physics acceptance.
"""
import unittest
import math
from unittest import mock

import test_player_limited_traverse as fixtures


class FullControlArbitrationTests(unittest.TestCase):
    def scene(self, distance=190., clip=6, burst=3, speed=0., cold_start=False):
        scene = fixtures.TraverseScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        if cold_start:
            # This helper normally schedules an isolated shot-fixture
            # admission. A cold-loop regression must start before that
            # helper; all actual planner/lane consumers remain production.
            with mock.patch.object(scene, 'admit', return_value=None):
                scene.configure(limits=None, tag='mediumTank', clip=clip,
                                burst=burst, bearing=0.)
        else:
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

    @staticmethod
    def original_order(scene):
        return next(order for order in scene.runtime._strategic_result['orders']
                    if order['id'] == scene.runtime.actor_id)

    def test_medium_range_proof_preserves_the_original_movement_owner(self):
        for distance, speed in ((185., 0.), (189.256, -3.07),
                                (194.574, 3.64), (195., 0.)):
            with self.subTest(distance=distance, speed=speed):
                scene = self.scene(distance=distance, speed=speed)
                row = self.advance_until(scene, lambda result: result['action'] == 'aim')
                candidate = scene.runtime.attack_policy.decision['candidate']
                self.assertEqual('passed', candidate['armor'])
                self.assertEqual('clear', candidate['line'])
                self.assertEqual(scene.target.id, candidate['target']['engine_id'])
                original = self.original_order(scene)
                self.assertEqual(('bot', scene.target.id),
                    original['tactical_evidence']['selection']['selected'])
                # Strategy still carries the route. The proved current shot,
                # not the initial hint, owns the accepted physical stop.
                self.assertEqual('route', original['combat_mode'])
                self.assertIsNone(original.get('target_id'))
                self.assertTrue(scene.runtime.combat_stop.combat_owned)
                self.assertEqual((0., 0., True), row['sender'], row)
                self.assertEqual('engage', scene.runtime._last_order['combat_mode'])

    def test_ready_lane_reaches_real_fire_transaction_without_shadow_gun_debit(self):
        # This scene specifically tests a firing hold. Distant authored
        # advance is covered above and must keep its original movement owner.
        scene = self.scene(distance=60., clip=6, burst=3)
        before = list(scene.battle._gun_state.ammo)
        self.advance_until(scene, lambda result: bool(scene.launches()))
        self.assertEqual(1, len(scene.launches()))
        self.assertEqual(before[0] - 1, scene.battle._gun_state.ammo[0])
        self.assertEqual(5, scene.battle._gun_state.clip)
        self.assertEqual((0., 0., True), scene.trace[-1]['sender'])
        self.assertEqual(1, scene.control.shot_commits)

    def test_return_base_after_real_first_shot_releases_combat_hold_but_not_physical_tail(self):
        scene = self.scene(distance=60., clip=6, burst=3)
        runtime, gun = scene.runtime, scene.battle._gun_state
        initial_ammo = tuple(gun.ammo)
        self.advance_until(scene, lambda result: bool(scene.launches()))
        self.assertEqual(1, len(scene.launches()))
        self.assertIsNotNone(runtime.state.get('_magazine_followup'))
        tail = scene.battle._local_player_burst
        self.assertIsNotNone(tail)
        ammo_after_first = tuple(gun.ammo)
        remaining = gun._burst_remaining

        runtime.set_mission('return_base', dict(timeout=180.))
        self.assertNotIn('_magazine_followup', runtime.state)
        self.assertEqual('priority_handoff', runtime.state['_magazine_followup_terminal']['reason'])
        self.assertIs(tail, scene.battle._local_player_burst)
        self.assertEqual(remaining, gun._burst_remaining)
        self.assertEqual(ammo_after_first, tuple(gun.ammo))

        row = scene.tick()
        self.assertIsNone(scene.control.last_control_failure, row)
        self.assertEqual('team_return_base', runtime._last_order['combat_mode'])
        self.assertEqual((0., 0., -45.), runtime._last_order['move_position'])
        self.assertNotEqual('combat_hold',
                            runtime._last_order['control_trace']['action_owner'])
        self.assertFalse(runtime.combat_stop.active)
        self.assertEqual('original_combat_not_admitted', runtime.authorize_trigger(
            dict(source_pose=runtime.pose_stamp()), scene.entity, gun, None))
        self.assertIs(tail, scene.battle._local_player_burst)

        # Completing an already committed descriptor burst is a physical
        # transaction, not permission to start another engagement/trigger.
        scene.advance(.01)
        scene.advance(.1)
        self.assertEqual([0, 1, 2], [launch['burst_index'] for launch in scene.launches()])
        self.assertEqual(initial_ammo[0] - 3, gun.ammo[0])
        self.assertIsNone(scene.battle._local_player_burst)
        self.assertEqual(3, scene.control.shot_commits)
        self.assertEqual(1, scene.trigger.call_count)
        row = scene.tick()
        self.assertEqual('team_return_base', runtime._last_order['combat_mode'])
        self.assertNotEqual('combat_hold',
                            runtime._last_order['control_trace']['action_owner'])

    def test_explicit_travel_does_not_recreate_rear_laying_or_reverse_its_route_turn(self):
        # A real rear target must still trigger the unchanged BOT laying law
        # before the player hands the hull to a new explicit travel task.
        # Both signs matter: an assertion that the vehicle merely turns would
        # miss the enemy's opposing turn stealing the destination's input.
        for bearing in (-2.4, 2.4):
            for kind in ('return_base', 'defend_base', 'attack',
                         'hold_position', 'capture_base'):
                with self.subTest(bearing=bearing, mission=kind):
                    scene = fixtures.TraverseScene()
                    scene.setUp()
                    self.addCleanup(scene.doCleanups)
                    scene.configure(limits=(-.2, .2), tag='AT-SPG', clip=1,
                                    burst=1, bearing=bearing)
                    runtime = scene.runtime
                    scene.battle._gun_state.reload_time = 30.
                    goal = (-math.copysign(40., bearing), 0., 40.)
                    bases = scene.battle._spawn_planner.capture_bases
                    for team in ('1', '2'):
                        bases[team] = [dict(x=goal[0], z=goal[2], radius=6.)]
                    for unused in range(3):
                        scene.tick()
                    self.assertTrue(runtime.state['hull_aiming'])
                    self.assertIsNotNone(runtime.state.get('_rear_aim_episode'))
                    self.assertLess(scene.trace[-1]['sender'][1] * goal[0], 0.)

                    payload = dict(timeout=180.)
                    if kind in ('attack', 'hold_position'):
                        payload['position'] = goal
                    runtime.set_mission(kind, payload)
                    self.assertNotIn('_rear_aim_episode', runtime.state)
                    expected_mode = 'base_capture' if kind == 'capture_base' else 'team_' + kind
                    for frame in range(12):
                        row = scene.tick()
                        self.assertIsNone(scene.control.last_control_failure, row)
                        self.assertFalse(runtime.combat_stop.active, row)
                        self.assertFalse(runtime.state['hull_aiming'], row)
                        for name in ('_rear_aim_episode', '_rear_hull_aim',
                                     '_rear_motion_lease'):
                            self.assertNotIn(name, runtime.state, row)
                        order = runtime._last_order
                        self.assertEqual(expected_mode, order['combat_mode'], row)
                        self.assertEqual(goal, order['move_position'], row)
                        self.assertNotEqual('combat_hold',
                            order['control_trace']['action_owner'], row)
                        self.assertGreaterEqual(row['sender'][1] * goal[0], 0., row)
                        if frame == 0:
                            self.assertGreater(row['sender'][1] * goal[0], 0., row)
                    scene.trigger.assert_not_called()

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

    def test_visible_blocked_target_enters_review_without_authorizing_a_shot(self):
        scene = self.scene(distance=60., clip=1, burst=1, cold_start=True)
        scene.world = [((-100., -100., 5.), (100., 100., 15.))]
        policy = scene.runtime.attack_policy
        with mock.patch.object(policy, 'update', wraps=policy.update) as evaluate:
            for unused in range(50):
                row = scene.tick()
                self.assertIsNone(scene.control.last_control_failure, row)
                original = self.original_order(scene)
                selection = original['tactical_evidence']['selection']
                self.assertEqual(('bot', scene.target.id), selection['selected'])
                self.assertEqual('initial_distance_armor', selection['selection_law'])
                self.assertIsNone(scene.runtime._last_order.get('target_id'), row)
                self.assertEqual('route', original['combat_mode'])
                self.assertEqual('route', scene.runtime._last_order['combat_mode'])
                self.assertFalse(scene.runtime.combat_stop.combat_owned)
                self.assertEqual({scene.target.id}, {target['network_id']
                    for target in scene.runtime.combat_targets()})
                self.assertNotIn(row['action'], ('aim', 'search_penetration'))
                self.assertFalse(scene.runtime._last_order['fire_allowed'])
                self.assertIsNone(policy.search_started)
            self.assertGreater(evaluate.call_count, 0)
        self.assertEqual(['eligible'],
            [candidate['reason'] for candidate in selection['candidates']])
        self.assertFalse(selection['candidates'][0]['local_lane'])
        self.assertEqual('firing_position', policy.decision['action'])
        self.assertFalse(policy.navigation_receipt,
            'candidate-only review cannot publish an accepted combat movement')
        scene.trigger.assert_not_called()

    def test_reopened_lane_retires_the_firing_position_navigation_receipt(self):
        scene = self.scene(distance=60., clip=1, burst=1)
        # First acquire a shared target through passive native LOS, then
        # verify that actual reopening retires only its recovery receipt.
        scene.battle._gun_state.reload_time = 10.
        self.advance_until(scene, lambda result: result['action'] == 'aim')
        original = self.original_order(scene)
        self.assertEqual(('bot', scene.target.id),
                         original['tactical_evidence']['selection']['selected'])
        scene.trigger.assert_not_called()

        scene.world = [((-100., -100., 5.), (100., 100., 15.))]
        scene.set_hull(.01)
        self.advance_until(scene, lambda result:
            result['action'] == 'firing_position' and
            scene.runtime._last_order['combat_mode'] == 'advance_contact')
        policy = scene.runtime.attack_policy
        original = self.original_order(scene)
        self.assertEqual(('bot', scene.target.id),
                         original['tactical_evidence']['selection']['selected'])
        # The native obstruction can arrive before the next macro sampling
        # interval. Neither a cached assigned hint nor a freshly pending hint
        # owns the movement task or supplies the current blocked-ray proof.
        self.assertIn(original['tactical_evidence']['selection']['outcome'],
                      ('assigned', 'evaluation_pending'))
        self.assertEqual('initial_hint',
                         original['tactical_evidence']['selection']['owner'])
        self.assertEqual('world_blocked', policy.decision['candidate']['line'])
        self.assertEqual('route', original['combat_mode'])
        self.assertTrue(scene.runtime.combat_stop.combat_owned)
        self.assertEqual(scene.target.id, scene.runtime._last_order['target_id'])
        self.assertIsNone(policy.search_started)
        scene.trigger.assert_not_called()

        scene.world = []
        scene.set_hull(.02)
        scene.battle._gun_state.reload_time = 0.
        row = self.advance_until(scene, lambda result: result['action'] == 'aim')
        self.assertEqual((0., True), row['sender'][::2])
        self.assertFalse(policy.navigation_receipt)
        self.advance_until(scene, lambda result: scene.control.automatic_commits == 1)
        self.assertEqual(1, len(scene.launches()))

    def test_explicit_attack_destination_retains_motion_ownership_over_ready_lane(self):
        scene = self.scene()
        goal = (0., 0., 24.)
        scene.runtime.set_mission('attack', dict(position=goal))
        row = self.advance_until(scene, lambda result:
            self.original_order(scene)['tactical_evidence']['selection']['selected'] ==
            ('bot', scene.target.id) and
            bool(result['sender'][0] or result['sender'][1]))
        self.assertEqual(goal, scene.runtime._last_order.get('move_position'), row)
        self.assertEqual('team_attack', scene.runtime._last_order['combat_mode'])
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
