"""Movable wreck attempts and longitudinal exits through production controls."""
import math
import unittest
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.ai.driver import combat_hull_aim
from gui.mods.offline_lan_0922.ai.traffic import TrafficCoordinator


class WreckContactRecoveryTests(unittest.TestCase):
    def test_moving_wreck_does_not_renew_a_stationary_bot_motor_budget(self):
        self.route()
        for unused in range(100):
            self.decide()
        self.peer['position'] = (0., 0., 9.1)
        commands = [self.decide() for unused in range(60)]
        self.assertNotEqual('wreck_push', commands[-1]['recovery_mode'])
        self.assertGreater(self.adapter.driver.states[1]['clock'], 0.)

    def test_real_forward_progress_survives_wreck_reference_refreshes(self):
        self.route()
        for frame in range(300):
            self.state['position'] = (0., 0., frame*.03)
            self.peer['position'] = (0., 0., frame*.03+8.)
            self.assertEqual('wreck_push', self.decide()['recovery_mode'])

    def test_amx_144634_wreck_motion_cannot_hide_own_stall(self):
        # Replay reported geometry and a proved one-metre corpse displacement.
        # Clear proof callbacks isolate recovery ownership, not engine physics.
        self.state.update(position=(93.910738935806,-1.465207695961,19.133250948984),
                          yaw=2.193431851522, half_width=1.256786942482,
                          half_length=2.462629079819,
                          collision_shape=(1.256786942482,2.462629079819,.003748,1.358249008656),
                          pose_clear=lambda yaw: True, push_pose_clear=lambda yaw: True)
        self.peer.update(id=21, team=1, position=(97.281170137582,-1.774807929993,15.715094941299),
                         yaw=1.928851197405, half_width=1.579941987991,
                         half_length=2.906608104706,
                         shape=(1.579941987991,2.906608104706,-.004689,1.528550028801))
        self.order.update(combat_mode='route', throttle_override=None,
                          move_position=(82.853,0.,-23.44))
        first = self.decide()
        self.assertEqual('wreck_push', first['recovery_mode'])
        for frame in range(160):
            if frame == 100:
                self.peer['position'] = (98.229316334064,-1.933077692986,15.3488074128)
                self.state['position'] = (93.95541539605,-1.468433022499,19.106468319677)
            command = self.decide()
        self.assertNotEqual('wreck_push', command['recovery_mode'])

    def test_failed_push_is_not_renewed_by_normal_recovery_progress(self):
        self.route()
        for unused in range(160):
            self.decide()
        self.state['position'] = (0., 0., .75)
        self.assertNotEqual('wreck_push', self.decide()['recovery_mode'])

    def test_missing_candidate_does_not_erase_failed_push(self):
        self.route()
        for unused in range(160):
            self.decide()
        self.state['neighbours'] = []
        self.decide()
        self.state['neighbours'] = [self.peer]
        self.assertNotEqual('wreck_push', self.decide()['recovery_mode'])

    def test_switching_wrecks_does_not_restart_spent_attempt(self):
        self.route()
        for unused in range(160):
            self.decide()
        other = dict(self.peer, id=3)
        self.state['neighbours'] = [other]
        self.assertEqual('wreck_push', self.decide()['recovery_mode'])
        self.state['neighbours'] = [self.peer]
        self.assertNotEqual('wreck_push', self.decide()['recovery_mode'])

    def test_leaving_jam_region_allows_a_new_encounter(self):
        self.route()
        for unused in range(160):
            self.decide()
        self.state.update(position=(0., 0., -30.), neighbours=[])
        self.decide()
        self.state.update(position=(0., 0., 0.), neighbours=[self.peer])
        self.assertEqual('wreck_push', self.decide()['recovery_mode'])

    def test_partial_attempt_survives_a_candidate_gap(self):
        self.route()
        for unused in range(100):
            self.decide()
        self.state['neighbours'] = []
        self.assertEqual('candidate_missing', self.decide()['wreck_push']['phase'])
        self.state['neighbours'] = [self.peer]
        for unused in range(60):
            command = self.decide()
        self.assertNotEqual('wreck_push', command['recovery_mode'])
        self.assertEqual('exhausted', command['wreck_push']['phase'])

    def test_wreck_evidence_does_not_leak_into_a_parked_command(self):
        self.route()
        self.assertIn('wreck_push', self.decide())
        self.order.update(combat_mode='hold', parking_phase='waiting', throttle_override=0.)
        self.assertNotIn('wreck_push', self.decide())

    def test_world_refusal_cannot_be_erased_by_small_recovery_motion(self):
        # Isolate checked physical recovery without an active engagement.
        self.order['target_id'] = None
        self.state['push_pose_clear'] = lambda yaw: False
        self.assertEqual('world_turn_refused', self.decide()['wreck_push']['phase'])
        self.state['position'] = (0., 0., .75)
        self.state['push_pose_clear'] = lambda yaw: True
        command = self.decide()
        self.assertNotEqual('wreck_push', command['recovery_mode'])
        self.assertEqual('exhausted', command['wreck_push']['phase'])

    def test_world_refused_push_hands_back_to_driver_without_fourteen_second_hold(self):
        # Isolate checked physical recovery without an active engagement.
        self.order['target_id'] = None
        self.state['push_pose_clear'] = lambda yaw: False
        before = dict(self.peer)
        command = self.decide()
        self.assertNotEqual('wreck_push', command['recovery_mode'])
        self.assertEqual(14., self.adapter._wreck_attempts[1]['elapsed'])
        self.assertEqual(before, self.peer)
        self.assertNotEqual('wreck_push', self.decide()['recovery_mode'])

    def test_amx_report_gap_keeps_forward_torque_and_steers_into_wreck(self):
        # Isolate checked physical recovery without an active engagement.
        self.order['target_id'] = None
        self.state.update(position=(-18.01417788982463,.26,29.474571555355627),
                          yaw=.6820790716546388,
                          collision_shape=(1.717499971,3.550543070,-.000231,1.906605959),
                          half_width=1.717499971,half_length=3.550543070)
        self.peer.update(id=16,position=(-11.336189464213899,.257637978,30.056638311277595),
                         yaw=-2.033644987963189,
                         shape=(1.656103015,3.676434994,.001999,1.715954006),
                         half_width=1.656103015,half_length=3.676434994)
        original_position=self.state['position']
        original_peer=dict(self.peer)
        for frame in range(100):
            # Reproduce the reported tiny longitudinal oscillation and tactical
            # engage/route changes without giving either body real progress.
            offset=.08 if frame%2 else -.08
            self.state['position']=(original_position[0]+math.sin(self.state['yaw'])*offset,
                                    .26,original_position[2]+math.cos(self.state['yaw'])*offset)
            self.order.update(combat_mode='route' if frame%2 else 'engage',
                              move_position=(-14.,.26,30.),throttle_override=None if frame%2 else 0.)
            command=self.decide()
            self.assertEqual('wreck_push',command['recovery_mode'])
            self.assertEqual(1.,command['throttle'])
            self.assertGreater(command['turn'],.1)
            self.assertGreater(command['recovery_probe_distance'],7.)
        self.assertEqual(original_peer,self.peer)
        self.assertGreater(self.adapter._wreck_attempts[1]['elapsed'],9.)

    def test_enemy_hull_ahead_does_not_replace_route_with_avoidance(self):
        self.route()
        for actor in (2,1000002):
            self.peer.update(id=actor,team=2,alive=True)
            command=self.decide()
            self.assertEqual(1.,command['throttle'])
            self.assertEqual(0.,command['turn'])
            self.assertEqual('drive',command['recovery_mode'])

    def test_live_ally_side_contact_retains_checked_avoidance(self):
        # Isolate checked physical recovery without an active engagement.
        self.order['target_id'] = None
        self.peer.update(alive=True,team=1)
        commands=[self.decide() for unused in range(40)]
        self.assertEqual({-1.,1.},set(c['throttle'] for c in commands))
        self.assertTrue(all(c['recovery_mode']=='contact_escape' for c in commands))

    def test_failed_driver_callback_restores_all_physical_neighbours(self):
        self.peer.update(alive=True,team=2)
        original=self.state['neighbours']
        def failed(*args):
            self.assertEqual([],self.state['neighbours'])
            raise RuntimeError('navigation failed')
        self.adapter.navigation_target=failed
        with self.assertRaisesRegex(RuntimeError,'navigation failed'):
            self.decide()
        self.assertIs(original,self.state['neighbours'])
        self.assertEqual([self.peer],self.state['neighbours'])

    def test_front_contact_uses_world_checked_push_turn_instead_of_wreck_avoidance(self):
        self.route()
        self.peer['position']=(0.,0.,6.99)
        self.state['pose_clear']=lambda yaw: False
        checked=[]
        def push_clear(yaw):
            checked.append(yaw)
            return True
        self.state['push_pose_clear']=push_clear
        commands=[self.decide() for unused in range(120)]
        self.assertTrue(any(c['turn']>0. for c in commands))
        self.assertTrue(any(c['turn']<0. for c in commands))
        self.assertTrue(all(c['throttle']==1. for c in commands))
        self.assertTrue(checked)
        self.state['push_pose_clear']=lambda yaw: False
        self.assertEqual(0.,self.decide()['turn'])

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

    def test_authored_wait_keeps_hull_aim_and_fire_without_contact_translation(self):
        self.order.update(combat_mode='hold',parking_phase='waiting')
        for unused in range(40):
            command=self.decide()
            self.assertEqual(0.,command['throttle'])
            self.assertFalse(command['movement_intent'])
            self.assertEqual(9,command['target_id'])
            self.assertTrue(command['fire_allowed'])
            self.assertNotEqual(0.,command['turn'])
            turn,throttle,active=combat_hull_aim(
                0.,math.pi/2,-.1,.1,command['turn'],command['throttle'],
                command['recovery_mode'],combat_mode='hold',movement_intent=False)
            self.assertTrue(active)
            self.assertNotEqual(0.,turn)
            self.assertEqual(0.,throttle)

    def test_wait_anchor_does_not_reverse_hull_on_target_loss(self):
        # Reported Foch: the anchor lies 0.4 m behind the already aimed hull.
        # The same rule applies to a queued vehicle and to either hull type.
        for phase in ('waiting', 'queue'):
            self.setUp()
            self.state.update(position=(-114.6, 58.1062, -290.2),
                              yaw=1.17, neighbours=[], pose_clear=lambda yaw: True)
            self.order.update(combat_mode='hold', parking_phase=phase,
                              move_position=(-114.183, 58.1062, -290.2396))
            self.order.update(target_id=None, aim_position=None,
                              face_position=None, fire_allowed=False)
            command = self.decide()
            self.assertEqual(0., command['turn'])
            self.assertEqual(1.17, command['target_yaw'])
            self.assertEqual(0., command['throttle'])
            self.assertFalse(command['movement_intent'])
            # Reacquisition remains free to aim through the rear hemisphere;
            # parking is not a hull-yaw lock or a firing prohibition.
            self.order.update(target_id=9, aim_position=(-300., 50., -400.),
                              face_position=(-300., 50., -400.), fire_allowed=True)
            command = self.decide()
            self.assertNotEqual(0., command['turn'])
            self.assertTrue(command['fire_allowed'])
            turn, throttle, active = combat_hull_aim(
                1.17, command['target_yaw'], -.1, .1,
                command['turn'], command['throttle'], command['recovery_mode'],
                combat_mode='hold', movement_intent=False)
            self.assertTrue(active)
            self.assertNotEqual(0., turn)
            self.assertEqual(0., throttle)
            # Another proof gap must not create a parking-facing turn.
            self.state['yaw'] = command['target_yaw']
            self.order.update(target_id=None, aim_position=None,
                              face_position=None, fire_allowed=False)
            self.assertEqual(0., self.decide()['turn'])

    def test_parked_explicit_facing_and_ordinary_arrival_still_turn(self):
        self.order.update(combat_mode='hold', parking_phase='waiting')
        self.assertNotEqual(0., self.decide()['turn'])
        self.order.update(parking_phase=None, target_id=None,
                          aim_position=None, face_position=None,
                          move_position=(.4, 0., -.1))
        self.state.update(neighbours=[], pose_clear=lambda yaw: True)
        self.assertNotEqual(0., self.decide()['turn'])

    def test_selected_enemy_hold_preempts_side_push_until_combat_releases(self):
        for team in (1, 2):
            self.setUp()
            self.peer.update(alive=False, team=team)
            commands = [self.decide() for unused in range(40)]
            self.assertTrue(all(c['recovery_mode']=='arrived' and
                                c['throttle']==0.0 for c in commands))
            self.assertTrue(all(c['fire_allowed'] and c['target_id']==9 for c in commands))
            self.order['target_id'] = None
            self.assertEqual('wreck_push', self.decide()['recovery_mode'])
        self.peer.update(alive=True, team=2)
        self.assertFalse(self.decide()['movement_intent'])
        self.assertEqual(0., self.decide()['throttle'])

    def test_rear_hull_requires_checked_forward_exit(self):
        # Isolate checked physical recovery without an active engagement.
        self.order['target_id'] = None
        rear = dict(self.peer, id=3, alive=True, position=(0., 0., -8.))
        self.state['neighbours'].append(rear)
        command = self.decide()
        self.assertEqual(1.0, command['throttle'])
        body = dict(self.state, position=self.state['position'], yaw=0.,
                    shape=self.state['collision_shape'], velocity=(0., 0., 0.))
        safe = TrafficCoordinator().safe_controls(body, command,
                    self.state['neighbours'], 1., lambda: 0.)
        self.assertEqual(1.0, safe['throttle'])

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
        self.assertEqual('wreck_push', commands[0]['recovery_mode'])
        first_push=next(c for c in commands if c['recovery_mode']=='wreck_push')
        self.assertEqual(0., first_push['turn'])
        self.assertTrue(all(c['throttle']==1.0 for c in commands if c['recovery_mode']=='wreck_push'))
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

    def test_only_real_wreck_motion_restarts_failed_attempt(self):
        self.route()
        for unused in range(160): self.decide()
        self.order['route_id'] = 'medium'
        self.assertNotEqual('wreck_push', self.decide()['recovery_mode'])
        self.peer['position'] = (0., 0., 9.1)
        self.assertEqual('wreck_push', self.decide()['recovery_mode'])

    def test_push_never_ignores_live_hull_or_world_blocker(self):
        self.route()
        live = dict(self.peer, id=3, team=1, alive=True, position=(0., 0., 7.))
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
        self.assertEqual('wreck_push', self.decide()['recovery_mode'])
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
        self.assertNotIn(1, self.adapter._wreck_history)


if __name__ == '__main__':
    unittest.main()
