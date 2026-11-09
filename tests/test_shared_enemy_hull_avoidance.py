"""Enemy hulls obstruct movement without becoming cooperative traffic peers."""
import copy
import math
import unittest
from unittest import mock

import test_port_0922_bot_runtime as harness


class EnemyHullAvoidanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
        from gui.mods.offline_lan_0922.ai.traffic import TrafficCoordinator
        self.Adapter = BotAdapter
        self.Coordinator = TrafficCoordinator

    @staticmethod
    def body(actor, team=1, x=0., z=0., speed=0., yaw=0.):
        return dict(id=actor, team=team, alive=True, position=(x, 0., z),
                    yaw=yaw, pitch=0., roll=0.,
                    velocity=(math.sin(yaw)*speed, 0., math.cos(yaw)*speed),
                    shape=(1.5, 3.5, -.8, 2.), half_length=3.5, half_width=1.5)

    @staticmethod
    def order():
        return dict(combat_mode='route', target_id=None,
                    move_position=(0., 0., 50.), fire_range=500.,
                    throttle_override=None, fire_allowed=False)

    def drive(self, actor, peer, adapter=None, now=1.):
        adapter = adapter or self.Adapter('01_karelia', 7)
        state = self.body(actor)
        state.update(slot=0, speed=0., dt=.1, now=now, neighbours=[peer],
                     pose_clear=lambda yaw: True)
        before = copy.deepcopy(state['neighbours'])
        neighbours = state['neighbours']
        result = adapter.decide_with_order(state, self.order(), lambda *a: True)
        self.assertIs(neighbours, state['neighbours'])
        self.assertEqual(before, state['neighbours'])
        return result, adapter

    def test_bot_and_player_route_avoid_the_same_stationary_enemy_hull(self):
        for actor in (11, 1000001):
            for peer_id in (22, 1000002):
                with self.subTest(actor=actor, peer=peer_id):
                    ally, unused = self.drive(actor, self.body(peer_id, z=9.))
                    enemy, unused = self.drive(actor, self.body(peer_id, team=2, z=9.))
                    for key in ('throttle', 'turn', 'target_yaw', 'recovery_mode'):
                        self.assertEqual(ally[key], enemy[key], key)
                    self.assertEqual('avoid', enemy['recovery_mode'])
                    self.assertNotEqual(0., enemy['target_yaw'])
                    self.assertEqual(self.order()['move_position'], enemy['move_position'])
                    self.assertIsNone(enemy['target_id'])

    def test_repeated_enemy_observation_keeps_the_selected_clear_branch(self):
        peer = self.body(22, team=2, z=9.)
        first, adapter = self.drive(11, peer)
        self.assertEqual('avoid', first['recovery_mode'])
        for tick in range(1, 10):
            result, unused = self.drive(11, peer, adapter, now=1.+tick*.1)
            self.assertEqual(first['target_yaw'], result['target_yaw'])
            self.assertEqual(self.order()['move_position'], result['move_position'])

    def test_distant_and_off_path_enemies_do_not_divert_the_authored_route(self):
        for x, z in ((0., 50.), (10., 9.), (0., -9.)):
            with self.subTest(position=(x, z)):
                result, unused = self.drive(11, self.body(22, team=2, x=x, z=z))
                self.assertEqual(('drive', 0., 1.),
                    (result['recovery_mode'], result['turn'], result['throttle']))

    def test_predictive_braking_includes_enemy_bot_and_human_without_new_lease(self):
        for actor in (11, 1000001):
            for peer_id in (22, 1000002):
                own = self.body(actor, speed=12.)
                peer = self.body(peer_id, team=2, z=12.)
                coordinator = self.Coordinator()
                command = dict(self.order(), throttle=1., turn=0.,
                               target_yaw=0., recovery_mode='drive', movement_intent=True)
                before = copy.deepcopy((own, peer, command))
                self.assertEqual(command, coordinator.adjust(
                    actor, own, command, [peer], 1., lambda *a: True))
                result = coordinator.safe_controls(own, command, [peer], 1., lambda: 20.)
                self.assertEqual((0., True, peer_id),
                    (result['throttle'], result['brake'], result['forward_blocked_by']))
                self.assertEqual({}, coordinator._pairs)
                self.assertEqual({}, coordinator._parked)
                self.assertEqual({}, coordinator._jams)
                self.assertEqual(before, (own, peer, command))

    def test_enemy_behind_does_not_brake_forward_but_blocks_reverse(self):
        own = self.body(11, speed=0.)
        peer = self.body(22, team=2, z=-7.05)
        coordinator = self.Coordinator()
        command = dict(throttle=1., turn=0., movement_intent=True)
        self.assertEqual(command, coordinator.safe_controls(
            own, command, [peer], 1., lambda: 0.))
        reverse = coordinator.safe_controls(own, dict(command, throttle=-1.),
            [peer], 1., lambda: 0.)
        self.assertEqual((0., True, 22),
            (reverse['throttle'], reverse['brake'], reverse['reverse_blocked_by']))

    def test_enemy_off_corridor_or_on_other_level_does_not_brake(self):
        own = self.body(11, speed=12.)
        coordinator = self.Coordinator()
        command = dict(throttle=1., turn=0., movement_intent=True)
        for peer in (self.body(22, team=2, x=6., z=12.),
                     self.body(22, team=2, z=100.),
                     dict(self.body(22, team=2, z=12.), position=(0., 10., 12.))):
            self.assertEqual(command, coordinator.safe_controls(
                own, command, [peer], 1., lambda: 20.))

    def test_final_pivot_sweep_cannot_turn_through_enemy(self):
        own = self.body(11)
        peer = self.body(22, team=2, x=3.1)
        result = self.Coordinator().safe_controls(own,
            dict(throttle=0., turn=1., movement_intent=True), [peer], 1., lambda: 0.)
        self.assertEqual(0., result['turn'])
        self.assertTrue(result['rotation_safety']['blocked'])
        self.assertEqual([22], [p['id'] for p in result['rotation_safety']['peers']])

    def test_enemy_cannot_request_a_friendly_parked_yield(self):
        own = self.body(11)
        peer = self.body(22, team=2, z=-7.05)
        coordinator = self.Coordinator()
        requester = dict(throttle=1., turn=0., movement_intent=True,
                         combat_mode='route', recovery_mode='blocked',
                         forward_blocked_by=11)
        held = dict(throttle=0., turn=0., movement_intent=False,
                    combat_mode='engage', recovery_mode='arrived')
        for now in (1., 3., 5.):
            coordinator._orders[22] = (now, requester)
            self.assertEqual(held, coordinator.adjust(
                11, own, held, [peer], now, lambda *a: True))
        self.assertEqual({}, coordinator._parked)
        self.assertEqual({}, coordinator._pairs)
        self.assertEqual({}, coordinator._jams)

    def test_planning_rotation_includes_enemy_for_bot_and_player_origins(self):
        from gui.mods.offline_lan_0922 import native_math
        for actor in (11, 1000001):
            for peer_kind in ('worker', 'visible'):
                with self.subTest(actor=actor, peer_kind=peer_kind):
                    runtime = self.fixture.module.BotRuntime(1)
                    own = dict(id=actor, team=1, x=0., y=0., z=0., yaw=0.,
                               collision_shape=(1.5, 3.5, -.8, 2.))
                    peer = self.body(22, team=2, x=3.1)
                    runtime.states = {actor: own}
                    supplied = [peer]
                    if peer_kind == 'worker':
                        runtime.states[22] = dict(id=22, team=2, x=3.1, y=0., z=0.,
                            yaw=0., collision_shape=peer['shape'])
                        supplied = []
                    with mock.patch.object(native_math, '_load', return_value=None):
                        fraction = runtime._planning_rotation_fraction_for(
                            own, (0., 0., 0.), 0., .4, supplied)
                    self.assertLess(fraction, 1.)


if __name__ == '__main__':
    unittest.main()
