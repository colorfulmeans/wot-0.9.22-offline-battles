"""Ordinary slope-angle recovery through the production solver and driver."""
import contextlib
import io
import math
import unittest
import test_port_0922_bot_runtime as harness


class GunAngleRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.runtime = self.fixture.module.BotRuntime(1)
        self.state = dict(id=11, slot=1, team=2, x=0., y=0., z=0., yaw=0.,
                          pitch=.45, roll=0., profile={'class_tag': 'mediumTank'},
                          route={'id': 'lane', 'waypoints': [(0., -40.), (0., 90.)]})
        self.target = dict(id=28, network_id=28, kind='bot', alive=True,
                           position=(0., 0., 150.))
        self.targets = {28: self.target}
        self.order = dict(target_id=28, combat_mode='engage', move_position=(0., 0., 0.),
                          aim_position=self.target['position'], fire_allowed=True,
                          route_id='lane', route_index=1, fire_range=400.)

    def tearDown(self):
        self.fixture.tearDown()

    def refuse(self):
        descriptor = harness._combat_descriptor()
        self.assertIsNone(self.runtime._local_ballistic_solution(
            self.state, self.target, descriptor, 0))
        self.assertEqual(('bot', 28), self.state['_gun_angle_refusal'])

    def order_at(self, now, clear=lambda *unused: True):
        return self.runtime._gun_angle_order(self.state, self.order, self.targets, now, clear)

    def test_real_pitch_refusal_adjusts_once_then_resumes_forward_node(self):
        self.refuse()
        self.assertEqual((0., 0., 0.), self.order_at(0.)['move_position'])
        calls = []
        move = self.order_at(2., lambda *args: calls.append(args) or True)
        self.assertEqual((0., 0., 8.), move['move_position'])
        self.assertEqual(.70, move['throttle_override'])
        self.state['z'] = 3.
        self.assertEqual(move['move_position'], self.order_at(4.)['move_position'])
        self.assertEqual(1, len(calls))
        resumed = self.order_at(6.)
        self.assertEqual('route', resumed['combat_mode'])
        self.assertEqual((0., 0., 90.), resumed['move_position'])
        self.assertIsNone(resumed['target_id'])
        self.assertTrue(self.runtime._gun_angle_rejected(self.state, ('bot', 28), 7.))
        self.assertFalse(self.runtime._gun_angle_rejected(self.state, ('bot', 28), 14.))

    def test_friendly_lane_yield_uses_seventy_percent_and_expires(self):
        self.runtime._friendly_repositions[11] = dict(
            target_id=28, destination=(0., 0., 10.), deadline=5.,
            fire_range=400., shell_index=0)
        order, expired = self.runtime._friendly_reposition_order(self.state, self.targets, 2.)
        self.assertFalse(expired)
        self.assertEqual(.70, order['throttle_override'])
        self.assertFalse(order['fire_allowed'])
        self.assertEqual((None, True), self.runtime._friendly_reposition_order(self.state, self.targets, 5.))

    def test_real_reachable_pose_ends_adjustment_without_relaxing_limits(self):
        self.refuse()
        self.order_at(0.)
        self.state['pitch'] = 0.
        self.assertIsNotNone(self.runtime._local_ballistic_solution(
            self.state, self.target, harness._combat_descriptor(), 0))
        self.assertEqual(self.order, self.order_at(1.))
        self.assertNotIn('_gun_angle_adjustment', self.state)

    def test_missing_muzzle_is_not_mechanical_refusal(self):
        self.refuse()
        self.runtime._exact_shot_origin = lambda *unused: None
        self.assertIsNone(self.runtime._local_ballistic_solution(
            self.state, self.target, harness._combat_descriptor(), 0))
        self.assertNotIn('_gun_angle_refusal', self.state)
        self.assertEqual(self.order, self.order_at(0.))

    def test_waiting_approach_and_spg_are_unchanged(self):
        self.refuse()
        for phase in ('waiting', 'queue', 'approach'):
            self.order['parking_phase'] = phase
            self.assertEqual(self.order, self.order_at(10.))
        self.order.pop('parking_phase')
        self.state['profile']['class_tag'] = 'SPG'
        self.assertEqual(self.order, self.order_at(10.))
        self.assertNotIn('_gun_angle_adjustment', self.state)

    def test_existing_movement_and_retreat_are_preserved(self):
        self.refuse()
        self.order['move_position'] = (0., 0., 50.)
        self.assertEqual(self.order, self.order_at(0.))
        self.order['move_position'] = (0., 0., 3.)
        self.state['speed'] = 2.
        self.assertEqual(self.order, self.order_at(0.))
        self.state['speed'] = 0.
        self.order['move_position'] = (0., 0., 0.)
        for mode in ('route', 'advance', 'under_fire_withdraw', 'low_health_retreat'):
            self.order['combat_mode'] = mode
            self.assertEqual(self.order, self.order_at(0.))

    def test_target_switch_cannot_renew_absolute_deadline(self):
        self.refuse()
        self.order_at(0.)
        other = dict(self.target, id=29, network_id=29)
        self.targets[29] = other
        self.order['target_id'] = 29
        self.runtime._local_ballistic_solution(self.state, other, harness._combat_descriptor(), 0)
        self.assertEqual('route', self.order_at(6.)['combat_mode'])

    def test_blocked_candidates_do_not_loop_and_reverse_keeps_enemy_facing(self):
        self.refuse()
        self.order_at(0.)
        probes = []
        self.assertEqual('route', self.order_at(2., lambda *args: probes.append(args) or False)['combat_mode'])
        self.assertEqual(2, len(probes))
        self.state.pop('_gun_angle_rejected')
        self.order_at(10.)
        move = self.order_at(12., lambda yaw, distance: yaw > 1.)
        self.assertEqual('withdraw', move['combat_mode'])
        self.assertEqual(.70, move['throttle_override'])
        self.assertAlmostEqual(-8., move['move_position'][2])
        self.assertEqual(self.target['position'], move['face_position'])

    def test_shared_candidate_budget_has_no_per_bot_deadline_extension(self):
        self.refuse()
        self.order_at(0.)
        self.runtime._gun_angle_candidate_tick = 2.
        self.order_at(2., lambda *unused: self.fail('budget already used'))
        self.assertEqual('route', self.order_at(6.)['combat_mode'])

    def test_reload_or_unfinished_slew_without_angle_refusal_do_not_adjust(self):
        self.state.update(pitch=0., gun_aligned=False, reload=20.)
        self.assertIsNotNone(self.runtime._local_ballistic_solution(
            self.state, self.target, harness._combat_descriptor(), 0))
        self.assertEqual(self.order, self.order_at(0.))
        self.assertNotIn('_gun_angle_adjustment', self.state)

    def test_failed_pair_feedback_preserves_visible_target_and_other_shooters(self):
        runtime = self.runtime
        self.state['_gun_angle_rejected'] = {('human', 2): 9.}
        runtime.states[11] = self.state
        runtime._radio_network = type('Radio', (), {
            'actors': {}, 'contact': lambda *unused: (10., True)})()
        key = (2, 'human', 2)
        runtime._renew_team_spot(key, 1.)
        pose = dict(x=0., y=0., z=100., position=(0., 0., 100.), team=1)
        runtime._visible_target_poses[key] = pose
        aggregate = {key: (True, {11, 12}, dict(pose), set(), {11, 12})}
        record = runtime._pack_observations(aggregate, 1.)[0]
        self.assertTrue(record['visible'])
        self.assertEqual([11, 12], record['visible_by_bot_ids'])
        self.assertEqual([12], record['shootable_by_bot_ids'])
        self.assertEqual([11, 12], runtime._pack_observations(aggregate, 9.)[0]['shootable_by_bot_ids'])

    def test_production_update_moves_off_unreachable_combat_hold(self):
        descriptor = harness._combat_descriptor()
        runtime = self.fixture.module.BotRuntime(
            1, descriptor_resolver=lambda unused: descriptor,
            direction_probe=lambda *unused: dict(clear=True, slope=0.),
            ground_probe=lambda *unused: 0., physics_ground_probe=lambda *unused: 0.,
            spawn_resolver=lambda *unused: ((0., 0., 0.), 0.),
            visibility_probe=lambda *unused: True, firing_lane_probe=lambda *unused: True,
            baked_graph=harness._flat_open_graph())
        runtime.battle_start(self.fixture.start)
        state = runtime.states[11]
        runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[dict(
            self.order, id=11, team=2, target_kind='human', target_id=2)]))
        player = harness._admit_player(dict(id=2, team=1, alive=True, x=0., y=-80., z=100.))
        with contextlib.redirect_stdout(io.StringIO()):
            for frame in range(1, 101):
                runtime.update(.05, frame * .05, players=[player])
        self.assertGreater(math.hypot(state['x'], state['z']), 1.)
        self.assertEqual(0, state['fire_seq'])
        self.assertIsNotNone(state.get('_gun_angle_adjustment'))
        player['y'] = 0.
        with contextlib.redirect_stdout(io.StringIO()):
            for frame in range(101, 161):
                runtime.update(.05, frame * .05, players=[player])
        self.assertGreater(state['fire_seq'], 0)
        self.assertNotIn('_gun_angle_adjustment', state)


if __name__ == '__main__':
    unittest.main()
