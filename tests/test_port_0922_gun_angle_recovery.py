"""Native pitch refusal and the unified same-point physical recovery.

The former independent _gun_angle_order and its forward/reverse destination
search were removed. These checks exercise the native solver, the one shared
CombatStop translation task and BOT projectile path without reintroducing
the retired order consumer or accepting an old proof as permission to fire.
"""
import contextlib
import io
import math
import unittest

import test_port_0922_bot_runtime as harness
from test_player_combat_stop import Scene


class NativeGunAndPointRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.runtime = self.fixture.module.BotRuntime(1)
        self.state = dict(id=11, slot=1, team=2, x=0., y=0., z=0., yaw=0.,
            pitch=.45, roll=0., profile={'class_tag': 'mediumTank'},
            route={'id': 'lane', 'waypoints': [(0., -40.), (0., 90.)]})
        self.target = dict(id=28, network_id=28, kind='bot', alive=True,
                           position=(0., 0., 150.))

    def scene(self, statuses=None, admitted=True):
        scene = Scene(admitted=admitted)
        scene.raw_order.update(combat_mode='route', target_id=None,
            target_kind=None, move_position=(20., 0., -30.),
            throttle_override=None, aim_position=None, fire_allowed=False)
        scene.candidate.update(key=(0, ('bot', 2), 0, 'penetration'), sample=0)
        statuses = list(statuses or ())
        scene.probes = []

        def native_future_probe(candidate, destination, now):
            scene.probes.append((candidate['key'], tuple(destination), now))
            return dict(status=statuses.pop(0) if statuses else 'clear',
                        fire_permission=False)

        scene.runtime.point_recovery_probe = native_future_probe
        return scene

    def test_native_pitch_refusal_never_creates_an_independent_destination_owner(self):
        descriptor = harness._combat_descriptor()
        self.assertIsNone(self.runtime._local_ballistic_solution(
            self.state, self.target, descriptor, 0))
        self.assertEqual(('bot', 28), self.state['_gun_angle_refusal'])
        self.assertFalse(hasattr(self.runtime, '_gun_angle_order'))
        self.assertNotIn('_gun_angle_adjustment', self.state)

    def test_real_reachable_pose_clears_old_mechanical_refusal(self):
        descriptor = harness._combat_descriptor()
        self.runtime._local_ballistic_solution(self.state, self.target, descriptor, 0)
        self.state['pitch'] = 0.
        self.assertIsNotNone(self.runtime._local_ballistic_solution(
            self.state, self.target, descriptor, 0))
        self.assertNotIn('_gun_angle_refusal', self.state)
        self.assertNotIn('_gun_angle_adjustment', self.state)

    def test_missing_native_muzzle_is_not_mechanical_refusal(self):
        descriptor = harness._combat_descriptor()
        self.runtime._local_ballistic_solution(self.state, self.target, descriptor, 0)
        self.runtime._exact_shot_origin = lambda *unused: None
        self.assertIsNone(self.runtime._local_ballistic_solution(
            self.state, self.target, descriptor, 0))
        self.assertNotIn('_gun_angle_refusal', self.state)
        self.assertNotIn('_gun_angle_adjustment', self.state)

    def test_reload_or_unfinished_barrel_slew_does_not_generate_a_position(self):
        descriptor = harness._combat_descriptor()
        self.state.update(pitch=0., gun_aligned=False, reload=20.)
        self.assertIsNotNone(self.runtime._local_ballistic_solution(
            self.state, self.target, descriptor, 0))
        scene = self.scene()
        scene.candidate.update(mechanical='reachable', line='clear', armor='unknown')
        scene.decide('wait', candidate=False, reason='native_barrel_slewing')
        result = scene.apply(0.)
        self.assertEqual('engage', result['combat_mode'])
        self.assertIsNone(scene.owner._physical_recovery)

    def test_checked_selected_sample_creates_exactly_one_bounded_goal(self):
        scene = self.scene()
        result = scene.apply(0.)
        phase = scene.owner._physical_recovery
        self.assertEqual('gun_angle_adjust', result['combat_mode'])
        self.assertEqual(phase['goal'], result['move_position'])
        self.assertNotEqual(scene.target['position'], phase['goal'])
        self.assertEqual(scene.candidate['key'], phase['key'])
        self.assertEqual(scene.candidate['key'], scene.probes[0][0])
        self.assertFalse(result['fire_allowed'])

    def test_pending_native_ray_cannot_select_an_unchecked_goal(self):
        scene = self.scene(['pending', 'blocked', 'clear'])
        result = scene.apply(0.)
        phase = scene.owner._physical_recovery
        self.assertEqual('engage', result['combat_mode'])
        self.assertIsNone(phase['goal'])
        self.assertEqual(0, phase['cursor'])
        result = scene.apply(.1)
        self.assertEqual('gun_angle_adjust', result['combat_mode'])
        self.assertEqual(2, phase['cursor'])
        self.assertEqual(3, len(scene.probes))
        self.assertFalse(result['fire_allowed'])

    def test_blocked_native_destinations_return_route_without_enemy_chase(self):
        scene = self.scene(['blocked'] * 40)
        for tick in range(30):
            result = scene.apply(tick * .1)
            if not scene.owner.stop_allowed:
                break
        self.assertEqual('route', result['combat_mode'])
        self.assertEqual((20., 0., -30.), result['move_position'])
        total = len(scene.probes)
        self.assertLessEqual(total, 18)
        for tick in range(30, 35):
            self.assertEqual('route', scene.apply(tick * .1)['combat_mode'])
        self.assertEqual(total, len(scene.probes))

    def test_wait_and_new_stationary_plan_keep_existing_physical_goal(self):
        scene = self.scene()
        scene.apply(0.)
        phase = scene.owner._physical_recovery
        goal = phase['goal']
        scene.stationary()
        scene.decide('wait', candidate=False, reason='native_query_pending')
        for now in (.1, .2, .3):
            result = scene.apply(now)
            self.assertEqual(goal, result['move_position'])
            self.assertIs(phase, scene.owner._physical_recovery)
            self.assertEqual(0., phase['started'])

    def test_real_arrival_requires_fresh_geometry_after_movement(self):
        scene = self.scene()
        scene.apply(0.)
        phase = scene.owner._physical_recovery
        scene.position(phase['goal'])
        stopped = scene.apply(.1)
        self.assertEqual('engage', stopped['combat_mode'])
        self.assertTrue(phase['checking'])
        self.assertFalse(stopped['fire_allowed'])

    def test_material_source_motion_reopens_a_failed_point_task(self):
        scene = self.scene(['blocked'] * 40)
        for tick in range(30):
            scene.apply(tick * .1)
            if not scene.owner.stop_allowed:
                break
        self.assertFalse(scene.owner.stop_allowed)
        scene.position((.4, 0., 0.))
        self.assertEqual('route', scene.apply(3.)['combat_mode'])
        scene.position((1., 0., 0.))
        scene.apply(3.1)
        self.assertTrue(scene.owner.stop_allowed)

    def test_real_priority_travel_does_not_receive_combat_translation(self):
        for mode in ('team_return_base', 'withdraw', 'base_defense'):
            with self.subTest(mode=mode):
                scene = self.scene()
                scene.apply(0.)
                scene.raw_order['combat_mode'] = mode
                result = scene.apply(.1)
                self.assertEqual(mode, result['combat_mode'])
                self.assertEqual((20., 0., -30.), result['move_position'])
                self.assertIsNone(scene.owner._physical_recovery)
                self.assertFalse(scene.owner.stop_allowed)

    def test_spg_keeps_its_separate_artillery_owner(self):
        scene = self.scene(admitted=False)
        scene.state['profile']['class_tag'] = 'SPG'
        scene.candidate.update(mechanical='hull_laying', line='clear')
        scene.decide('firing_position')
        result = scene.apply(0.)
        self.assertEqual('route', result['combat_mode'])
        self.assertIsNone(scene.owner._physical_recovery)

    def test_friendly_lane_reposition_uses_full_throttle_and_expires(self):
        self.runtime._friendly_repositions[11] = dict(
            target_id=28, target_kind='bot', destination=(0., 0., 10.), deadline=5.,
            fire_range=400., shell_index=0)
        order, expired = self.runtime._friendly_reposition_order(
            self.state, {28: self.target}, 2., self.runtime._server_orders.get(11, {}))
        self.assertFalse(expired)
        self.assertEqual(1.0, order['throttle_override'])
        self.assertFalse(order['fire_allowed'])
        self.assertEqual((None, True), self.runtime._friendly_reposition_order(
            self.state, {28: self.target}, 5., self.runtime._server_orders.get(11, {})))

    def test_failed_pair_feedback_does_not_hide_other_shooters_or_visible_contact(self):
        runtime = self.runtime
        self.state['_gun_angle_rejected'] = {('human', 2): 9.}
        runtime.states[11] = self.state
        runtime._radio_network = type('Radio', (), {
            'summaries': lambda unused, pairs, now, include_sources=False: tuple(
                (10., True, ()) if include_sources else (10., True) for pair in pairs),
            'actors': {}, 'contact': lambda *unused: (10., True)})()
        key = (2, 'human', 2)
        runtime._renew_team_spot(key, 1.)
        pose = dict(x=0., y=0., z=100., position=(0., 0., 100.), team=1)
        runtime._visible_target_poses[key] = pose
        aggregate = {key: (True, {11, 12}, dict(pose), set(), {11, 12})}
        record = runtime._pack_observations(aggregate, 1.)[0]
        self.assertTrue(record['visible'])
        self.assertEqual([11, 12], record['visible_by_bot_ids'])
        self.assertEqual([11, 12], record['shootable_by_bot_ids'])
        self.assertEqual([11, 12], runtime._pack_observations(aggregate, 9.)[0]['shootable_by_bot_ids'])

    def test_actual_bot_update_does_not_reintroduce_retired_order_or_fake_shot(self):
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
        initial = tuple((state['x'], state['y'], state['z']))
        runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[dict(
            id=11, team=2, target_kind='human', target_id=2,
            combat_mode='engage', move_position=(0., 0., 0.),
            aim_position=(0., -80., 100.), fire_allowed=True,
            fire_range=400., throttle_override=0.)]))
        player = harness._admit_player(dict(id=2, team=1, alive=True,
                                           x=0., y=-80., z=100.))
        with contextlib.redirect_stdout(io.StringIO()):
            for frame in range(1, 101):
                runtime.update(.05, frame * .05, players=[player])
        self.assertEqual(0, state['fire_seq'])
        self.assertNotIn('_gun_angle_adjustment', state)
        self.assertFalse(hasattr(runtime, '_gun_angle_order'))
        self.assertEqual(initial[1], state['y'])
        # A reachable native aim may be reconsidered after a real target
        # pose change, not after a removed independent destination timer.
        player['y'] = 0.
        with contextlib.redirect_stdout(io.StringIO()):
            for frame in range(101, 161):
                runtime.update(.05, frame * .05, players=[player])
        self.assertGreater(state['fire_seq'], 0)


if __name__ == '__main__':
    unittest.main()
