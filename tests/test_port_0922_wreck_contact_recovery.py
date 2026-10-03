"""Movable wreck attempts and longitudinal exits through production controls."""
import math
import unittest
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.ai.driver import combat_hull_aim
from gui.mods.offline_lan_0922.ai.traffic import TrafficCoordinator


class WreckContactRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.adapter = BotAdapter('04_himmelsdorf', 1)
        self.peer = dict(id=2, team=2, alive=False, position=(2.99, 0., 0.),
                         yaw=0., shape=(1.5, 3.5, -.8, 2.),
                         half_width=1.5, half_length=3.5, velocity=(0., 0., 0.))
        self.state = dict(id=1, slot=0, team=1, position=(0., 0., 0.),
                          yaw=0., speed=0., dt=.1, half_width=1.5,
                          half_length=3.5, neighbours=[self.peer],
                          collision_shape=(1.5, 3.5, -.8, 2.),
                          pose_clear=lambda yaw: False)
        self.order = dict(target_id=9, aim_position=(100., 0., 0.),
                          face_position=(100., 0., 0.),
                          move_position=(0., 0., 0.), combat_mode='engage',
                          fire_allowed=True, throttle_override=0.)

    def decide(self, clear=lambda *args: True):
        return self.adapter.decide_with_order(self.state, self.order, clear)

    def route(self):
        self.peer['position'] = (0., 0., 8.)
        self.state['pose_clear'] = lambda yaw: True
        self.order.update(combat_mode='route', throttle_override=None,
                          move_position=(0., 0., 100.), route_id='heavy', route_index=2)

    def test_side_hug_tries_both_gears_for_wreck_enemy_and_friend(self):
        for alive, team in ((False, 1), (False, 2), (True, 1), (True, 2)):
            self.setUp()
            self.peer.update(alive=alive, team=team)
            commands = [self.decide() for unused in range(40)]
            self.assertEqual({-.72, .72}, set(c['throttle'] for c in commands))
            for command in commands:
                self.assertEqual('contact_escape', command['recovery_mode'])
                self.assertEqual(0., command['turn'])
                self.assertTrue(command['movement_intent'])
                self.assertTrue(command['fire_allowed'])
                self.assertEqual(9, command['target_id'])
                self.assertEqual((100., 0., 0.), command['aim_position'])
                self.assertEqual((0., command['throttle'], False), combat_hull_aim(
                    0., math.pi/2, -.1, .1, command['turn'], command['throttle'],
                    command['recovery_mode'], combat_mode='engage', movement_intent=True))

    def test_rear_hull_requires_checked_forward_exit(self):
        rear = dict(self.peer, id=3, alive=True, position=(0., 0., -8.))
        self.state['neighbours'].append(rear)
        command = self.decide()
        self.assertEqual(.72, command['throttle'])
        body = dict(self.state, position=self.state['position'], yaw=0.,
                    shape=self.state['collision_shape'], velocity=(0., 0., 0.))
        safe = TrafficCoordinator().safe_controls(body, command,
                    self.state['neighbours'], 1., lambda: 0.)
        self.assertEqual(.72, safe['throttle'])

    def test_world_denial_never_creates_unchecked_translation(self):
        command = self.decide(lambda *args: False)
        self.assertEqual(0., command['throttle'])

    def test_other_floor_and_removed_contact_preserve_tactical_hold(self):
        for where in ((2.99, 10., 0.), (10., 0., 0.)):
            self.peer['position'] = where
            command = self.decide()
            self.assertFalse(command['movement_intent'])
            self.assertEqual(0., command['throttle'])

    def test_front_wreck_push_is_bounded_then_normal_navigation_resumes(self):
        self.route()
        commands = [self.decide() for unused in range(160)]
        self.assertNotEqual('wreck_push', commands[0]['recovery_mode'])
        first_push=next(c for c in commands if c['recovery_mode']=='wreck_push')
        self.assertEqual(0., first_push['turn'])
        self.assertTrue(any(c['turn'] > 0. for c in commands if c['recovery_mode']=='wreck_push'))
        self.assertTrue(any(c['turn'] < 0. for c in commands if c['recovery_mode']=='wreck_push'))
        self.assertNotEqual('wreck_push', commands[-1]['recovery_mode'])
        self.assertEqual((.4, .72, False), combat_hull_aim(
            0., 2., -.1, .1, .4, .72, 'wreck_push', combat_mode='engage', movement_intent=True))

    def test_order_and_yaw_jitter_cannot_restart_failed_wreck_attempt(self):
        self.route()
        for frame in range(160):
            self.state['yaw'] = .005 if frame%2 else -.005
            self.order['move_position'] = (.1 if frame%2 else -.1, 0., 100.)
            command = self.decide()
        self.assertNotEqual('wreck_push', command['recovery_mode'])

    def test_moved_wreck_and_new_route_allow_fresh_attempt(self):
        self.route()
        for unused in range(160): self.decide()
        self.peer['position'] = (0., 0., 9.1)
        self.assertNotEqual('wreck_push', self.decide()['recovery_mode'])
        for unused in range(65): command=self.decide()
        self.assertEqual('wreck_push', command['recovery_mode'])
        for unused in range(160): self.decide()
        self.order['route_id'] = 'medium'
        self.assertNotEqual('wreck_push', self.decide()['recovery_mode'])
        for unused in range(65): command=self.decide()
        self.assertEqual('wreck_push', command['recovery_mode'])

    def test_push_never_ignores_live_hull_or_world_blocker(self):
        self.route()
        live = dict(self.peer, id=3, alive=True, position=(0., 0., 7.))
        self.state['neighbours'].append(live)
        self.assertNotEqual('wreck_push', self.decide()['recovery_mode'])
        self.state['neighbours'].remove(live)
        self.assertNotEqual('wreck_push', self.decide(lambda *args: False)['recovery_mode'])

    def test_navigation_evidence_is_published_even_during_push(self):
        self.route()
        calls=[]
        def navigation(bot, position, target, strategic, state):
            calls.append(bot)
            return position
        self.adapter.navigation_target=navigation
        self.assertNotEqual('wreck_push', self.decide()['recovery_mode'])
        for unused in range(65): command=self.decide()
        self.assertEqual('wreck_push', command['recovery_mode'])
        self.assertEqual([1]*66, calls)

    def test_forget_removes_all_recovery_memory(self):
        self.decide()
        self.route()
        self.decide()
        self.adapter.forget(1)
        self.assertNotIn(1, self.adapter._contact_peers)
        self.assertNotIn(1, self.adapter._contact_attempts)
        self.assertNotIn(1, self.adapter._wreck_attempts)


if __name__ == '__main__':
    unittest.main()
