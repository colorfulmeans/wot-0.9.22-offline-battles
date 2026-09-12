"""Physical contact survives the asynchronous human/worker boundary."""
import math
import unittest

from test_port_0922_tank_collision import tank_collision, _tank
from gui.mods.offline_lan_0922 import tank_contact_ledger as ledger
from gui.mods.offline_lan_0922 import bot_state_codec
import test_port_0922_bot_runtime as bot_tests


class ContactLedgerTests(unittest.TestCase):
    def test_mass_weighted_reciprocal_impulse_survives_a_late_worker(self):
        for human_mass, bot_mass in ((10000, 100000), (100000, 10000), (25000, 25000)):
            with self.subTest(human=human_mass, bot=bot_mass):
                human = _tank(1001, 0, 0, mass=human_mass, vz=10)
                bot = _tank(11, 0, 5, mass=bot_mass)
                result = tank_collision.resolve_tank(human, [bot])
                bot_delta = result['responses'][0][1]
                human_delta = result['delta_velocity']
                self.assertAlmostEqual(0, human_mass * human_delta[1] + bot_mass * bot_delta[1])
                self.assertAlmostEqual(human_mass * 10 / (human_mass + bot_mass), bot_delta[1])
                sent = {}
                ledger.record(sent, 11, (bot_delta[0] * bot_mass, bot_delta[1] * bot_mass))
                # While the worker has not seen the frame, its presented Bot
                # already carries the pending reciprocal velocity locally.
                human['vz'] += human_delta[1]
                bot['vz'] += ledger.pending(sent, 11, [], 1)[1] / bot_mass
                again = tank_collision.resolve_tank(human, [bot])
                self.assertAlmostEqual(0, again['delta_velocity'][1])

    def test_coalescing_retries_and_reordering_preserve_only_unseen_momentum(self):
        sent = {}
        ledger.record(sent, 11, (1, 2))
        first = list(sent[11])
        ledger.record(sent, 11, (-0.5, 3))
        latest = sent[11]
        self.assertEqual((0.5, 5), ledger.unseen(latest, None))
        self.assertEqual((-0.5, 3), ledger.unseen(latest, first))
        self.assertEqual((0, 0), ledger.unseen(first, latest))
        self.assertEqual((0, 0), ledger.unseen(latest, latest))
        self.assertEqual((0, 0), ledger.pending(sent, 11, [[1] + latest[1:]], 1))

    def test_bot_velocity_and_acknowledgement_roundtrip_atomically(self):
        state = {'id': 11, 'speed': 3, 'push_x': 2.4, 'push_z': -1.3,
                 'contact_push_acks': [[1, 8, 2.4, -1.3]]}
        decoded = bot_state_codec.decode_row(bot_state_codec.encode_row(state), {})
        for key in ('speed', 'push_x', 'push_z', 'contact_push_acks'):
            self.assertEqual(state[key], decoded[key])

    def test_malformed_checkpoint_cannot_poison_a_round(self):
        for value in (None, [[11, 1, float('nan'), 0]], [[11, True, 0, 0]],
                      [[11, 1, 0, 0], [11, 2, 0, 0]], [[11, 1, float('inf'), 0]]):
            with self.assertRaises((ValueError, TypeError, OverflowError)):
                ledger.normalize(value)


class WorkerContactLedgerTests(unittest.TestCase):
    setUp = bot_tests.ShovedWreckTests.setUp
    tearDown = bot_tests.ShovedWreckTests.tearDown
    _runtime = bot_tests.ShovedWreckTests._runtime
    def test_receipt_moves_bot_without_a_current_overlap_or_armour_proof(self):
        runtime = self._runtime()
        state = runtime.states[11]
        state.update(x=0, y=0, z=0, yaw=0, speed=0, push_x=0, push_z=0)
        runtime.states.pop(12)
        runtime._player_collision_profile = lambda raw: {
            'mass': 100000, 'shape': tank_collision.DEFAULT_SHAPE, 'ram_profile': {}}
        human = {'id': 1, 'x': 100, 'y': 0, 'z': 100, 'yaw': 0,
                 'tank_pushes': [[11, 1, 0, 4 * state['mass']]], 'team': 1}
        runtime._resolve_tank_contacts([human], 1.0, .1)
        self.assertGreater(state['z'], .3)
        self.assertEqual([[1, 1, 0., 4 * state['mass']]], state['contact_push_acks'])
        speed_after = state['push_z']
        runtime._resolve_tank_contacts([human], 1.1, .1)
        self.assertLess(state['push_z'], speed_after)
        self.assertEqual([[1, 1, 0., 4 * state['mass']]], state['contact_push_acks'])

class ServerContactRelayTests(unittest.TestCase):
    def test_server_relays_cumulative_momentum_without_reset_on_replay(self):
        from test_port_0922_server_projectiles import _state, _gun_checkpoint
        state = _state(players=1)
        state.bot_states[11] = {'id': 11, 'alive': True}
        player = state.players[1]
        def send(rows):
            return state.update_input(1, {
                'type': 'input', 'round_id': state.round_id,
                'input_seq': player.input_processed_seq + 1,
                'pose_time_us': state._logical_motion_time_us(),
                'forward': 1, 'turn': 0, 'speed': 0,
                'x': player.x, 'y': player.y, 'z': player.z,
                'yaw': 0, 'pitch': 0, 'roll': 0, 'fire_seq': 0,
                'aim_yaw': 0, 'gun_pitch': 0,
                'shell_index': 0, 'next_shell_index': 0,
                'shell_change_pending': False,
                'gun_checkpoint': _gun_checkpoint(), 'tank_pushes': rows})
        latest = [11, 4, 150000, -50000]
        self.assertTrue(send([latest]))
        self.assertEqual([latest], state._public_player(player)['tank_pushes'])
        self.assertTrue(send([[11, 1, 30000, 0]]))
        self.assertEqual([latest], state._public_player(player)['tank_pushes'])
