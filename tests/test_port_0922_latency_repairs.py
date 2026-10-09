"""Captured worker latency classes: publication, queue fairness and gaps."""
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixture
from gui.mods.offline_lan_0922 import bot_runtime


class LatencyRepairsTests(unittest.TestCase):
    def test_countdown_native_commit_retains_frozen_publication_until_live(self):
        from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
        battle = fixture.BattleRuntime(fixture._runtime())
        battle._worker_mode = True
        battle._battle_live = False
        battle.client = types.SimpleNamespace(send_destructible=mock.Mock(return_value=True))
        state = {'publish_pending': {}, 'canonical_published': set()}
        with mock.patch.object(sensor, '_event_sink', battle._report_destructible):
            self.assertFalse(sensor._publish_tree_once_1513(
                state, 1, (22, 37, None), fixture._Vector(1., 2., 3.), .4, 8.))
            battle.client.send_destructible.assert_not_called()
            self.assertIn((22, 37), state['publish_pending'])
            self.assertNotIn((22, 37), state['canonical_published'])
            frozen = state['publish_pending'][(22, 37)]
            battle._battle_live = True
            self.assertTrue(sensor._publish_tree_once_1513(
                state, 1, (22, 37, None), (90., 80., 70.), 2., 20.))
            self.assertEqual({}, state['publish_pending'])
            self.assertIn((22, 37), state['canonical_published'])
            event = battle.client.send_destructible.call_args.args[0]
            self.assertEqual((1., 2., 3.), (event['x'], event['y'], event['z']))
            self.assertTrue(sensor._publish_tree_once_1513(
                state, 1, (22, 37, None), (0., 0., 0.), 0., 0.))
            battle.client.send_destructible.assert_called_once()
            self.assertIsNotNone(frozen)

    def test_countdown_catalog_receipt_is_published_before_contact_acceptance(self):
        from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
        import test_port_0922_server_projectiles as server_fixture
        state = server_fixture._state(players=1)
        live_tick = state.tick
        state.tick = 0
        self.assertFalse(state._combat_accepting())
        runtime = fixture._runtime()
        battle = fixture.BattleRuntime(runtime)
        battle._worker_mode = True
        battle._battle_live = False
        wire = []
        def send(event):
            message = dict(event, type='destructible', round_id=state.round_id)
            wire.append(message)
            state.report_destructible(server_fixture.SIMULATION_WORKER_AUTHORITY_ID, message)
            return True  # Actual transport admission does not mean server acceptance.
        battle.client = types.SimpleNamespace(send_destructible=send)
        with mock.patch.object(sensor, '_event_sink', battle._report_destructible), \
                mock.patch.object(sensor, 'g_offh_destr_catalog_published', set(), create=True), \
                mock.patch.object(sensor, 'g_offh_destr_catalog_publish_pending', {}, create=True):
            self.assertFalse(sensor._publish_catalog_once_1513(
                'fragile', 7, 11, (1., 2., 3.), .4, 8.))
            self.assertEqual([], wire)
            battle._battle_live = True
            state.tick = live_tick
            self.assertTrue(sensor._publish_catalog_once_1513(
                'fragile', 7, 11, (90., 80., 70.), 2., 20.))
            self.assertIn(('fragile', 7, 11, None), state.destructibles)
            contact = server_fixture._player_destructible_contact(seq=1, token=[[7, 11, None]])
            self.assertTrue(server_fixture._update_player_input(
                state, 1, destructible_contacts=[contact]))
            self.assertTrue(state.report_player_destructible_contact_result(
                server_fixture.SIMULATION_WORKER_AUTHORITY_ID, {
                    'type': 'player_destructible_contact_result', 'round_id': state.round_id,
                    'player_id': 1, 'contact_seq': 1, 'accepted': True, 'token': [[7, 11, None]]}))
            self.assertEqual({}, state.players[1].destructible_contacts)

    def test_verdict_retry_never_replays_physical_commit_and_round_fences_cache(self):
        runtime = fixture._runtime()
        battle = fixture.BattleRuntime(runtime)
        battle._worker_mode = True
        battle._avatar = runtime.bigworld.avatar
        battle._start_message = {'round_id': 7}
        sender = mock.Mock(return_value=True)
        battle.client = types.SimpleNamespace(send_player_destructible_contact_result=sender)
        commit = mock.Mock(return_value={'status': 'crushed', 'token': ((22, 37, None),)})
        battle._destructibles = types.SimpleNamespace(
            trusted_tree_identity_status_1513=lambda *unused: 'tree',
            commit_trusted_tree_contacts_1513=commit)
        player = {'id': 2, 'destructible_contacts': [{
            'seq': 3, 'x': 1., 'y': 2., 'z': 3., 'yaw': .25,
            'speed': 8., 'dt': .04, 'end_x': 1.0792, 'end_y': 2.,
            'end_z': 3.31, 'end_yaw': .25, 'token': [[22, 37, None]],
        }]}
        self.assertEqual(1, battle._resolve_player_destructible_contacts([player], 1.))
        self.assertEqual(0, battle._resolve_player_destructible_contacts([player], 1.1))
        self.assertEqual(1, battle._resolve_player_destructible_contacts([player], 1.3))
        self.assertEqual(1, commit.call_count)
        self.assertEqual(2, sender.call_count)
        battle._start_message = {'round_id': 8}
        self.assertEqual(1, battle._resolve_player_destructible_contacts([player], 2.))
        self.assertEqual(2, commit.call_count)

    def test_selected_lanes_rotate_without_increasing_native_budget(self):
        probes = []
        runtime = bot_runtime.BotRuntime(1, firing_lane_probe=lambda source, target: (
            probes.append(source['id']) or True))
        runtime.states = dict((actor, dict(id=actor, team=1, alive=True,
            x=0., y=0., z=0.)) for actor in range(1, 13))
        runtime.states[99] = dict(id=99, team=2, alive=True, x=10., y=0., z=0.)
        keys = [(actor, 'bot', 99) for actor in range(1, 13)]
        runtime._prepare_shot_lane_work = lambda *unused: None
        runtime._shot_lane_live_records = lambda key, *unused: (
            runtime.states[key[0]], dict(id=99, network_id=99, kind='bot',
                position=(10., 0., 0.)), (1, 'bot', 99))
        for cycle in range(3):
            runtime._shot_lane_work = list(keys)
            runtime._shot_lane_work_set = set(keys)
            runtime._shot_los_cache.clear()
            runtime._shot_los_deadlines.clear()
            budget = [4]
            runtime._service_shot_lane_work(1. + cycle, 1. + cycle,
                {(1, 'bot', 99): True}, [], {}, set(),
                dict((key, 0) for key in keys), budget)
            self.assertEqual(0, budget[0])
        self.assertEqual(list(range(1, 13)), probes)

    def test_between_callback_cpu_separates_main_thread_work_from_wall_gap(self):
        wall, cpu = [0.], [1.]
        diagnostic = fixture._FrameDiagnostics(clock=lambda: wall[0],
            cpu_clock=lambda: cpu[0], writer=lambda unused: None)
        frame = diagnostic.begin(0., 0.)
        wall[0], cpu[0] = .01, 1.005
        diagnostic.finish(frame, 0., .01, .01, {}, {}, {'role': 'guest'})
        cpu[0], wall[0] = 1.007, .51
        diagnostic.begin(.51, .51)
        diagnostic.flush()
        measured = diagnostic.snapshot()['between_callbacks_cpu']
        self.assertEqual(1, measured['samples'])
        self.assertAlmostEqual(2., measured['avg_ms'])
        self.assertAlmostEqual(500., measured['matched_wall_avg_ms'])
        self.assertFalse(measured['gpu_measured'])
