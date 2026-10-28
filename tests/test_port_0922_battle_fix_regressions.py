"""v1.0.0 regressions: received spotting sources, 14s memory and wreck yaw."""
import copy
import math
import unittest
from unittest import mock

import test_port_0922_bot_runtime as fixtures
from lan_battle_server import SIMULATION_WORKER_AUTHORITY_ID as WORKER
from gui.mods.offline_lan_0922 import radio
from gui.mods.offline_lan_0922.bot_runtime import BotRuntime


class ReceivedSpottingAssistTests(unittest.TestCase):
    def setUp(self):
        self.state, _, _ = fixtures.ServerBotObservationRelayTests._server()
        self.clock = mock.patch('lan_battle_server.time.monotonic', return_value=100.0)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)

    def message(self, sources=(1,), direct=(1,), duration=10.0):
        message = fixtures.ServerBotObservationRelayTests._human_message(
            self.state.round_id, observer_ids=direct)
        row = message['contacts'][0]
        row.update(time_left=duration, visible=duration > 0, fresh=bool(direct))
        row['radio_recipients'] = [{
            'kind': 'human', 'id': 2, 'time_left': duration,
            'sources': [{'kind': 'human', 'id': identity, 'time_left': duration}
                        for identity in sources]}] if duration > 0 else []
        return message

    def accept(self, message):
        self.assertTrue(self.state.update_bot_observation(WORKER, message))

    def damage(self, amount=200):
        self.state._record_damage(('player', 2), ('bot', 11), amount, {})
        return self.state._statistics_row('player', 1)['damage_assisted_radio']

    def test_retreat_keeps_assist_until_received_source_expires(self):
        self.accept(self.message())
        self.now.return_value = 103.0
        self.accept(self.message(direct=(), duration=7.0))
        self.assertEqual(200, self.damage())
        self.now.return_value = 110.0
        self.assertEqual(200, self.damage())

    def test_unconnected_direct_observer_cannot_dilute_assist(self):
        # Both allies see the target; only player 1 provides player 2's intel.
        player_type = type(self.state.players[1])
        self.state.players[3] = player_type(3, None, ('127.0.0.1', 3), team=1, slot=2)
        self.accept(self.message(sources=(1,), direct=(1, 3)))
        self.assertEqual(200, self.damage())
        self.assertEqual(0, self.state._statistics_row('player', 3)['damage_assisted_radio'])

    def test_multiple_sources_keep_independent_deadlines(self):
        player_type = type(self.state.players[1])
        self.state.players[3] = player_type(3, None, ('127.0.0.1', 3), team=1, slot=2)
        message = self.message(sources=(1, 3), direct=(1, 3))
        message['contacts'][0]['radio_recipients'][0]['sources'][1]['time_left'] = 2.0
        self.accept(message)
        self.assertEqual(100, self.damage())
        self.now.return_value = 103.0
        self.assertEqual(300, self.damage())
        self.assertEqual(100, self.state._statistics_row('player', 3)['damage_assisted_radio'])

    def test_lost_radio_link_replaces_received_source_list(self):
        self.accept(self.message())
        disconnected = self.message(sources=(), direct=(1,))
        disconnected['contacts'][0]['radio_recipients'] = []
        self.accept(disconnected)
        self.assertEqual(0, self.damage())

    def test_self_observation_does_not_pay_another_observer(self):
        self.accept(self.message(sources=(1, 2), direct=(1, 2)))
        self.assertEqual(0, self.damage())
        self.accept(self.message(sources=(1, 2), direct=()))
        self.assertEqual(0, self.damage())

    def test_missing_provenance_fails_closed(self):
        message = self.message()
        del message['contacts'][0]['radio_recipients'][0]['sources']
        self.accept(message)
        self.assertEqual(0, self.damage())

    def test_invalid_source_batch_does_not_partially_replace_state(self):
        self.accept(self.message())
        for change in ({'id': 999}, {'kind': 'bot', 'id': 11},
                       {'time_left': 11.0}, {'time_left': float('nan')},
                       {'id': True}):
            message = self.message()
            message['contacts'][0]['radio_recipients'][0]['sources'][0].update(change)
            self.assertFalse(self.state.update_bot_observation(WORKER, message), change)
        self.assertEqual(200, self.damage())

    def test_wrong_round_and_dead_sources_do_not_receive_credit(self):
        self.accept(self.message())
        self.state.players[1].alive = False
        self.assertEqual(0, self.damage())
        message = self.message()
        message['round_id'] -= 1
        self.assertFalse(self.state.update_bot_observation(WORKER, message))


class SourceLeaseTests(unittest.TestCase):
    def test_each_source_is_reported_without_team_union_or_relay_hops(self):
        net = radio.RadioNetwork()
        a, b, c = ('human', 1), ('bot', 2), ('bot', 3)
        target = ('bot', 4)
        net.configure({a: (1, (0, 0, 0), 200), b: (1, (350, 0, 0), 200),
                       c: (1, (700, 0, 0), 200)}, 10.0)
        net.observe(b, target, 10.0, 14.0, {'x': 400})
        net.observe(c, target, 10.0, 10.0, {'x': 800})
        net.hidden(b, target)
        self.assertEqual(((b, 1.0),), net.sources(a, target, 23.0))
        self.assertEqual((), net.sources(a, target, 24.0))
        self.assertEqual((), net.sources(('bot', 99), target, 11.0))


class TeamMemoryTests(unittest.TestCase):
    def test_14_second_lease_survives_packing_until_exact_expiry(self):
        runtime = BotRuntime(1)
        key = (1, 'bot', 12)
        pose = dict(x=100.0, y=0.0, z=0.0, team=2)
        runtime._visible_target_poses[key] = pose
        runtime._radio_network.configure({('human', 1): (1, (0, 0, 0), 700),
                                          ('human', 2): (1, (0, 0, 0), 700)}, 10.0)
        runtime._radio_network.observe(('human', 1), key[1:], 10.0, 14.0, pose)
        runtime._radio_network.hidden(('human', 1), key[1:])
        runtime._renew_team_spot(key, 10.0, 14.0)
        self.assertEqual(14.0, runtime._team_spot_time_left(key, 10.0))
        self.assertEqual(1.0, runtime._team_spot_time_left(key, 23.0))
        packed = runtime._pack_observations({key: [False, set(), pose, set(), set()]}, 23.0)[0]
        self.assertEqual(1.0, packed['time_left'])
        self.assertEqual([{'kind': 'human', 'id': 1, 'time_left': 1.0}],
                         packed['radio_recipients'][1]['sources'])
        self.assertEqual(0.0, runtime._team_spot_time_left(key, 24.0))


class WreckYawTests(unittest.TestCase):
    def test_vertical_rejection_restores_both_world_angles(self):
        worker = BotRuntime(1)
        worker._physics_ground_probe = lambda *unused: 0.0
        worker._physics_params_for = lambda unused: None
        state = dict(id=11, x=0.0, y=0.0, z=0.0, yaw=0.0,
                     aim_yaw=0.7, turret_yaw=0.7, push_yaw=1.0,
                     collision_shape=(1.5, 3.5, -0.8, 2.0))
        def admit(*unused):
            worker._commit_wreck_yaw(state, 0.1)
            return True
        worker._try_wreck_swept_pose = admit
        worker._update_vertical_motion = lambda *unused: True
        self.assertFalse(worker._apply_wreck_contact_response(
            state, dict(delta_velocity=(0.0, 0.0), correction=(0.0, 0.0)), 0.1))
        self.assertEqual((0.0, 0.7, 0.7),
                         (state['yaw'], state['turret_yaw'], state['aim_yaw']))

    def test_both_rotation_owners_preserve_turret_local_pose(self):
        for coupled in (False, True):
            for blocked in (False, True):
                worker = BotRuntime(1)
                state = dict(id=11, x=0.0, y=0.0, z=0.0, alive=False,
                             half_length=3.5, half_width=1.7,
                             collision_shape=(1.5, 3.5, -0.8, 2.0), mass=25000.0)
                state.update(yaw=3.13, turret_yaw=0.7,
                             aim_yaw=math.atan2(math.sin(3.83), math.cos(3.83)),
                             gun_pitch=-0.2, push_yaw=1.0)
                before = copy.deepcopy(state)
                worker._contact_motion_bodies = lambda unused: []
                worker.motion_resolver = mock.Mock(return_value='clear')
                worker._passive_motion_status = mock.Mock(return_value='clear')
                worker._baked_pose_progress_clear = mock.Mock(return_value=True)
                worker._turret_pose_is_clear = mock.Mock(return_value=not blocked)
                worker._wreck_rotation_probe = mock.Mock(return_value=True)
                if coupled:
                    self.assertEqual(not blocked, worker._try_wreck_swept_pose(
                        state, (0.1, 0.1), 1.0, 0.1))
                else:
                    worker._advance_wreck_yaw(state, {}, 0.1)
                self.assertEqual(before['turret_yaw'], state['turret_yaw'])
                self.assertEqual(before['gun_pitch'], state['gun_pitch'])
                expected = math.atan2(math.sin(state['yaw'] + 0.7),
                                      math.cos(state['yaw'] + 0.7))
                self.assertAlmostEqual(expected, state['aim_yaw'])
                if blocked:
                    self.assertEqual(before['yaw'], state['yaw'])
                else:
                    self.assertNotEqual(before['yaw'], state['yaw'])


if __name__ == '__main__':
    unittest.main()
