"""A stationary firing hold must not permanently plug friendly traffic."""
import math
import collections
import unittest
from unittest import mock

from test_port_0922_traffic import body, command
from gui.mods.offline_lan_0922.ai.traffic import (
    TrafficCoordinator, PARKED_JAM_SECONDS, PARKED_YIELD_SECONDS,
)
from gui.mods.offline_lan_0922.ai.driver import combat_hull_aim
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922 import vehicle_physics


def hold(own):
    return dict(command(own['yaw']), throttle=0., recovery_mode='arrived',
                movement_intent=False, combat_mode='artillery_hold',
                fire_allowed=True, target_id=99)


class ParkedTrafficTests(unittest.TestCase):
    def setUp(self):
        self.traffic = TrafficCoordinator()
        self.mover = body(25, 0., 0., speed=0.)
        self.parked = body(29, 0., 7., speed=0.)
        self.move = dict(command(), movement_intent=True)

    def tick(self, now, clear=lambda *args: True, extras=(), order=None):
        self.traffic.adjust(25, self.mover, self.move, [self.parked], now, clear)
        return self.traffic.adjust(
            29, self.parked, order or hold(self.parked),
            [self.mover] + list(extras), now, clear)

    def prime(self, clear=lambda *args: True, extras=()):
        self.assertEqual(hold(self.parked), self.tick(0., clear, extras))
        return self.tick(PARKED_JAM_SECONDS, clear, extras)

    def test_parked_artillery_makes_actual_forward_progress_then_resumes_aiming(self):
        first = self.prime()
        self.assertGreater(first['throttle'], 0.)
        self.assertEqual('friendly_yield', first['recovery_mode'])
        self.assertFalse(first['fire_allowed'])
        self.assertEqual(99, first['target_id'])
        position = self.parked['position'][2]
        speed = 0.
        modes = []
        for step in range(1, 91):
            order = self.tick(PARKED_JAM_SECONDS + step / 30.)
            modes.append(order.get('traffic_mode'))
            speed = vehicle_physics.longitudinal_step(
                dict(vehicle_physics._DEFAULTS), speed, order['throttle'],
                order['turn'], 0., 1. / 30.)
            position += speed / 30.
            self.parked.update(position=(0., 0., position), velocity=(0., 0., speed))
        self.assertGreater(position, 7.45)
        self.assertIn('friendly_yield', modes)
        self.assertIsNone(modes[-1])
        self.assertEqual(hold(self.parked), self.tick(5.))

    def test_stationary_episode_has_one_fixed_deadline(self):
        self.prime()
        for now in (2., 3., 4., 5.):
            self.assertEqual('friendly_yield', self.tick(now)['traffic_mode'])
        for now in (PARKED_JAM_SECONDS + PARKED_YIELD_SECONDS, 10., 30.):
            self.assertEqual(hold(self.parked), self.tick(now))
        # Only physical separation, not another decision refresh, rearms it.
        self.mover['position'] = (0., 0., -20.)
        self.tick(31.)
        self.mover['position'] = (0., 0., 0.)
        self.assertEqual(hold(self.parked), self.tick(32.))
        self.assertEqual('friendly_yield', self.tick(34.)['traffic_mode'])

    def test_checked_reverse_clears_a_parked_hull_behind_requester(self):
        self.parked['position'] = (0., 0., -7.)
        self.move.update(throttle=0., recovery_mode='blocked', reverse_blocked_by=29)
        order = self.prime()
        self.assertLess(order['throttle'], 0.)
        self.assertEqual(0., order['turn'])

    def test_explicit_rear_sweep_request_can_clear_a_hull_before_contact(self):
        self.parked['position'] = (0., 0., -10.)
        self.move.update(throttle=0., recovery_mode='blocked', reverse_blocked_by=29)
        self.assertLess(self.prime()['throttle'], 0.)

    def test_explicit_driver_blocker_request_also_clears_a_stalled_route_tank(self):
        self.parked['position'] = (0., 0., -7.)
        route = dict(command(), movement_intent=True)
        self.move.update(throttle=0., recovery_mode='blocked', reverse_blocked_by=29)
        order = self.tick(0., order=route)
        self.assertEqual('friendly_yield', order['traffic_mode'])
        self.assertLess(order['throttle'], 0.)
        # Ordinary route/recovery changes cannot reset the finite manoeuvre.
        for now in (1., 2., 3.):
            route['recovery_mode'] = 'reverse_turn' if now == 2. else 'drive'
            self.assertEqual('friendly_yield', self.tick(now, order=route)['traffic_mode'])
        for now in (PARKED_YIELD_SECONDS, 8., 12.):
            self.assertEqual(route, self.tick(now, order=route))

    def test_route_pair_without_proved_reverse_request_keeps_its_own_controls(self):
        route = dict(command(), movement_intent=True)
        for now in (0., 2., 5.):
            self.assertEqual(route, self.tick(now, order=route))

    def test_two_blocked_route_tanks_cannot_yield_to_each_other_simultaneously(self):
        self.parked['position'] = (0., 0., -7.)
        self.move.update(throttle=0., recovery_mode='blocked', reverse_blocked_by=29)
        route = dict(command(), throttle=0., movement_intent=True,
                     recovery_mode='blocked', reverse_blocked_by=25)
        first = self.tick(0., order=route)
        self.assertEqual('friendly_yield', first['traffic_mode'])
        second = self.traffic.adjust(
            25, self.mover, self.move, [self.parked], .1, lambda *args: True)
        self.assertNotEqual('friendly_yield', second.get('traffic_mode'))

    def test_route_clearance_request_keeps_full_front_and_rear_hull_veto(self):
        self.parked['position'] = (0., 0., -7.)
        self.move.update(throttle=0., recovery_mode='blocked', reverse_blocked_by=29)
        route = dict(command(), movement_intent=True)
        rear = body(30, 0., -15., speed=0.)
        self.assertEqual(route, self.tick(0., extras=[rear], order=route))

    def test_front_and_rear_hulls_or_static_terrain_veto_the_entire_escape(self):
        forward = body(31, 0., 15., speed=0.)
        self.assertEqual(hold(self.parked), self.prime(extras=[forward]))
        self.traffic = TrafficCoordinator()
        self.assertEqual(hold(self.parked), self.prime(clear=lambda *args: False))
        # A new obstruction entering an active corridor stops the manoeuvre.
        self.traffic = TrafficCoordinator()
        self.prime()
        stopped = self.tick(2., extras=[forward])
        self.assertEqual((0., 0.), (stopped['throttle'], stopped['turn']))

    def test_two_holds_a_moving_neighbour_and_twenty_cm_gap_do_not_start_yield(self):
        self.move = hold(self.mover)
        self.assertEqual(hold(self.parked), self.prime())
        self.move = dict(command(), movement_intent=True)
        self.traffic = TrafficCoordinator()
        self.mover['velocity'] = (0., 0., 2.)
        self.assertEqual(hold(self.parked), self.prime())
        self.traffic = TrafficCoordinator()
        self.mover.update(velocity=(0., 0., 0.), position=(0., 0., -.2))
        self.assertEqual(hold(self.parked), self.prime())

    def test_dead_enemy_separate_level_and_stale_orders_cannot_request_clearance(self):
        for changes in ({'alive': False}, {'team': 2}, {'position': (0., 6., 0.)}):
            with self.subTest(changes=changes):
                self.traffic = TrafficCoordinator()
                self.mover = body(25, 0., 0., speed=0.)
                self.mover.update(changes)
                self.mover['shape'] = self.parked['shape'] = (1.5, 3.5, -.8, 2.)
                self.assertEqual(hold(self.parked), self.prime())
        self.mover = body(25, 0., 0., speed=0.)
        self.traffic = TrafficCoordinator()
        self.tick(0.)
        self.assertEqual(hold(self.parked), self.traffic.adjust(
            29, self.parked, hold(self.parked), [self.mover], 3., lambda *args: True))

    def test_side_contact_uses_safe_translation_without_rotating_or_reaiming(self):
        self.parked['position'] = (3., 0., 0.)
        order = self.prime()
        self.assertGreater(order['throttle'], 0.)
        turn, throttle, aiming = combat_hull_aim(
            0., math.pi / 2., -.1, .1, order['turn'], order['throttle'],
            order['recovery_mode'], True)
        self.assertEqual((0., order['throttle'], False), (turn, throttle, aiming))
        self.assertEqual((3., 0., 0.), self.parked['position'])

    def test_physical_hold_and_removed_requester_release_the_override(self):
        self.prime()
        physical = dict(hold(self.parked), recovery_mode='physical_hold')
        self.assertEqual(physical, self.tick(2., order=physical))
        self.traffic = TrafficCoordinator()
        self.prime()
        self.traffic.forget(25)
        self.assertEqual({}, self.traffic._parked)

    def test_departed_or_arrived_requester_cannot_leave_a_latched_jam(self):
        self.tick(0.)
        self.traffic.adjust(29, self.parked, hold(self.parked), [], 1., lambda *args: True)
        self.assertEqual({}, self.traffic._jams)
        self.assertEqual(hold(self.parked), self.tick(2.))
        self.assertEqual('friendly_yield', self.tick(4.)['traffic_mode'])
        self.move.update(recovery_mode='arrived', throttle=0.)
        self.assertEqual(hold(self.parked), self.tick(4.1))

    def test_adapter_keeps_the_identity_of_the_blocked_reverse_corridor(self):
        adapter = BotAdapter('test', 1)
        state = dict(id=25, team=1, slot=0, position=(0., 0., 0.),
                     yaw=0., speed=0., dt=.1, neighbours=[])
        strategic = dict(move_position=(0., 0., 40.), combat_mode='route')
        with mock.patch.object(adapter.driver, 'drive', return_value=dict(
                throttle=0., turn=0., target_yaw=0., recovery_mode='blocked',
                reverse_blocked_by=29)):
            result = adapter.decide_with_order(state, strategic, lambda *args: True)
        self.assertEqual(29, result['reverse_blocked_by'])


class RuntimeTrafficJamTests(unittest.TestCase):
    # Reuse only the engine stubs / flat ground, retaining the production
    # adapter, neighbour snapshots, traffic coordinator and copied physics.
    from test_port_0922_separation_progress import SeparationProgressTests as _fixture
    setUp = _fixture.setUp
    tearDown = _fixture.tearDown

    def test_route_tank_and_parked_artillery_leave_the_spawn_queue(self):
        from test_port_0922_separation_progress import _flat_graph, runtime_fixtures
        runtime = self.module.BotRuntime(
            1, descriptor_resolver=lambda unused: runtime_fixtures._combat_descriptor(),
            direction_probe=lambda *unused: dict(clear=True, collision=False, slope=0.),
            ground_probe=lambda *unused: 0., physics_ground_probe=lambda *unused: 0.,
            spawn_resolver=lambda team, slot: ((0., 0., 7. * slot), 0.),
            baked_graph=_flat_graph(), control_seconds=.1,
            visibility_probe=lambda *unused: False, firing_lane_probe=lambda *unused: False)
        runtime.battle_start(dict(
            round_id=1, map='01_karelia', bot_authority_id=1,
            bots=[dict(id=slot + 25, team=1, slot=slot, name='Fixture', vehicle='fake',
                       profile=dict(class_tag='heavyTank', dominant_role='brawler',
                                    roles=dict(brawler=1.), shells=[],
                                    desired_range=200, fire_range=500)) for slot in range(2)]))
        runtime.adapter.navigation_target = (
            lambda bot_id, position, target, strategic, state: target)
        runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[
            dict(id=25, move_position=(0., 0., 30.), face_position=(0., 0., 30.),
                 combat_mode='route', fire_allowed=False),
            dict(id=26, move_position=(0., 0., 7.), face_position=(0., 0., 100.),
                 combat_mode='artillery_hold', throttle_override=0., fire_allowed=False),
        ]))
        modes = collections.Counter()
        for frame in range(1, 451):
            runtime.update(1. / 30., frame / 30.)
            modes[runtime._decision_cache.get(26, (0, 0, 0, {}))[3].get('traffic_mode')] += 1
        self.assertGreater(modes['friendly_yield'], 0)
        self.assertGreater(runtime.states[25]['z'], 10.)
        self.assertGreater(runtime.states[26]['z'], 12.)
        self.assertGreater(modes[None], modes['friendly_yield'])


if __name__ == '__main__':
    unittest.main()
