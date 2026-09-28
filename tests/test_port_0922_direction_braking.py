"""Reports 220344/221207: distinguish W/S reversal from forced back-driving."""
import unittest
from unittest import mock

import test_port_0922_bot_runtime as bt
from test_port_0922_siege_braking import local_battle
from test_port_0922_bot_state_codec import _bot_state, STATIC
from test_port_0922_server_projectiles import lan_server_module as server
from gui.mods.offline_lan_0922 import vehicle_physics as physics, bot_state_codec


class LocalDirectionBrakeTests(unittest.TestCase):
    def test_live_input_latches_both_direction_changes_until_stopped(self):
        for sign in (-1., 1.):
            for neutral in (False, True):
                battle, entity = local_battle('sweden:S22_Strv_S1', 0, sign*20.)
                battle._local_physics.update(speedFwd=100./3.6, speedBwd=100./3.6)
                battle._sender.turn = 0.
                battle._local_direction_command = sign
                if neutral:
                    battle._sender.forward = 0.
                    with mock.patch('sys.stdout'):
                        battle._drive_local(.01)
                    self.assertFalse(battle._local_service_brake)
                battle._sender.forward = -sign
                for unused in range(200):
                    before = battle._local_speed
                    with mock.patch('sys.stdout'):
                        battle._drive_local(.01)
                    self.assertTrue(battle._local_service_brake)
                    self.assertLess(abs(battle._local_speed), abs(before))
                    if battle._local_speed == 0.:
                        break
                self.assertEqual(0., battle._local_speed)
                with mock.patch('sys.stdout'):
                    battle._drive_local(.01)
                self.assertFalse(battle._local_service_brake)
                self.assertGreater(battle._local_speed*-sign, 0.)

    def test_held_player_input_can_be_pushed_back_without_auto_brake(self):
        for sign in (-1., 1.):
            battle, entity = local_battle('sweden:S22_Strv_S1', 0, -sign*4.)
            battle._sender.forward = sign
            battle._sender.turn = 0.
            battle._local_direction_command = sign
            with mock.patch('sys.stdout'):
                battle._drive_local(.01)
            self.assertFalse(battle._local_service_brake)


class BotDirectionBrakeTests(unittest.TestCase):
    setUp = bt.ShovedWreckTests.setUp
    tearDown = bt.ShovedWreckTests.tearDown
    _runtime = bt.ShovedWreckTests._runtime

    def test_worker_uses_same_brake_for_own_direction_change_not_external_push(self):
        for sign in (-1., 1.):
            for forced in (False, True):
                runtime = self._runtime()
                runtime.states.pop(12)
                runtime.baked_graph = bt._flat_open_graph()
                runtime.adapter = bt._FixedAdapter(dict(throttle=-sign, turn=0., fire_allowed=False))
                state = runtime.states[11]
                state.update(speed=sign*4., _contact_forward_speed=sign*4. if forced else 0.,
                             grounded_once=True, _direction_command=0 if forced else sign)
                params = runtime._physics_params_for(11)
                params.update(speedFwd=100./3.6, speedBwd=100./3.6)
                with mock.patch('sys.stdout'):
                    runtime._update_once(.01, 1., [])
                self.assertIs(not forced, state['service_brake'])


class BrakePublicationTests(unittest.TestCase):
    def test_codec_server_containment_and_contact_prediction_keep_brake_intent(self):
        identity = dict(id=17, team=1, slot=0, name='test', max_health=1500)
        for active in (False, True):
            raw = _bot_state(service_brake=active, speed=10., movement_dir=-1., burst_next_index=1)
            decoded = bot_state_codec.decode_row(bot_state_codec.encode_row(raw), STATIC)
            normal = server.BattleState._sanitize_bot_state(decoded, identity, None)
            contained = server.BattleState._contained_bot_state(normal, identity, normal)
            self.assertIs(active, normal['service_brake'])
            self.assertIs(active, contained['service_brake'])
            params = dict(physics._DEFAULTS, speedFwd=30., speedBwd=30., brakeDecel=3.)
            state = dict(contained, yaw=0., pitch=0., roll=0.)
            step = physics.SERVER_PHYSICS_STEP
            predicted = physics.predict_contact_velocity(params, state, (1.5,3.5,0.,2.), 0., step, [])
            expected = physics.longitudinal_step(params,10.,-1.,False,0.,step,service_brake=active)
            self.assertAlmostEqual(expected, predicted[1])


if __name__ == '__main__':
    unittest.main()
