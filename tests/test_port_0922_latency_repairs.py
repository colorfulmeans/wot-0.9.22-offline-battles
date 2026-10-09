"""Captured worker latency classes: publication, queue fairness and gaps."""
import types
import io
import sys
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixture
from gui.mods.offline_lan_0922 import bot_runtime


class LatencyRepairsTests(unittest.TestCase):
    def test_hit_diagnostic_names_bot_and_player_targets(self):
        battle = fixture.BattleRuntime(fixture._runtime())
        output = io.StringIO()
        with mock.patch('sys.stdout', output):
            for event in ({'target_bot': 25}, {'target': 1}):
                event.update(event_id='1:20:1', projectile_id='1:b:3:4',
                             damage=0, shot_result=0)
                battle._report_effect('armour_hit', 'armorRicochet', 14,
                    (1., 2., 3.), (0., 0., 1.), event=event)
        self.assertIn('target=bot:25 damage=0 result=0', output.getvalue())
        self.assertIn('target=player:1 damage=0 result=0', output.getvalue())

    def test_custom_chunk_mapper_is_not_replaced_by_native_batch(self):
        from gui.mods.offline_lan_0922 import native_destructibles as geometry
        owner = types.SimpleNamespace(query=mock.Mock())
        cache = types.SimpleNamespace(chunkIDFromPosition=lambda position: 22)
        with mock.patch.dict(sys.modules, {'DestructiblesCache': cache}), \
                mock.patch.object(geometry, '_get', return_value=owner):
            self.assertIsNone(geometry.neighbourhood(None, types.SimpleNamespace(
                chunkIDFromPosition=cache.chunkIDFromPosition),
                fixture._Vector(), 0., 1., 3., True))
        owner.query.assert_not_called()

    def test_grazing_ricochet_clears_plate_after_wire_rounding(self):
        from gui.mods.offline_lan_0922.projectile_runtime import (
            ideal_reflection_velocity, ricochet_departure_origin)
        import struct
        # Near-parallel travel at this map coordinate rounded the previous
        # direction-only nudge back onto the plate in the x86 engine.
        impact = (65.24, 1.06, 104.22)
        incoming = (-0.001, 0., 1000.)
        for normal in ((1., 0., 0.), (-3., 0., 0.)):
            reflected = ideal_reflection_velocity(incoming, normal)
            origin = ricochet_departure_origin(impact, reflected, normal)
            f32 = lambda v: struct.unpack('f', struct.pack('f', v))[0]
            old_x = impact[0] + reflected[0] / 1000. * .002
            self.assertEqual(f32(impact[0]), f32(old_x))
            self.assertGreater(f32(origin[0]), f32(impact[0]))
            self.assertEqual(impact[1:], origin[1:])
            self.assertAlmostEqual(.002, origin[0] - impact[0])

    def test_chassis_feedback_does_not_call_nonexistent_stock_sticker_owner(self):
        battle = fixture.BattleRuntime(fixture._runtime())
        target = fixture._Vehicle(10, fixture._Descriptor(), fixture._Vector(),
                                  (0., 0., 0.), {'health': 500})
        battle._runtime.bigworld.entities[10] = target
        target.appearance.addDamageSticker = mock.Mock(
            side_effect=KeyError('chassis'))
        decoder = types.SimpleNamespace(decodeSegment=lambda *unused: (
            'chassis', 17, fixture._Vector(0., 0., -1.),
            fixture._Vector(0., 0., 1.)))
        with mock.patch.dict(sys.modules, {'VehicleEffects':
                types.SimpleNamespace(DamageFromShotDecoder=decoder)}):
            self.assertFalse(battle._present_damage_sticker(
                {'damage_sticker': 123}, {'engine_id': 10}))
        target.appearance.addDamageSticker.assert_not_called()

    def test_sticker_uses_resolved_plate_after_penetrated_track(self):
        battle = fixture.BattleRuntime(fixture._runtime())
        descriptor = fixture._Descriptor()
        descriptor.hull.hitTester.localHitTest = lambda *unused: [object()]
        target = fixture._Vehicle(10, descriptor, fixture._Vector(),
                                  (0., 0., 0.), {'health': 500})
        battle._runtime.vehicles.g_cache.shotEffects[3]['targetStickers'] = {
            'armorResisted': 17, 'armorPierced': 29}
        hits = [types.SimpleNamespace(dist=.13, compName='vehicleChassis'),
                types.SimpleNamespace(dist=.38, compName='vehicleHull')]
        decoder = types.SimpleNamespace(decodeSegment=lambda *unused: (
            'hull', 29, fixture._Vector(0., 0., -1.),
            fixture._Vector(0., 0., 1.)))
        with mock.patch.dict(sys.modules, {'VehicleEffects':
                types.SimpleNamespace(DamageFromShotDecoder=decoder)}), \
                mock.patch.object(fixture.battle_runtime_module,
                                  'encode_damage_sticker', return_value=123) as encode:
            self.assertEqual(123, battle._projectile_damage_sticker(
                {}, target, descriptor.gun.shots[0], fixture._Vector(),
                fixture._Vector(0., 0., 2.), hits, 2, historic=True,
                contact={'component': 'vehicleHull', 'distance': .38}))
            self.assertEqual('vehicleHull', encode.call_args.args[4])
            encode.reset_mock()
            self.assertIsNone(battle._projectile_damage_sticker(
                {}, target, descriptor.gun.shots[0], fixture._Vector(),
                fixture._Vector(0., 0., 2.), hits, 1, historic=True,
                contact={'component': 'vehicleChassis', 'distance': .13}))
            encode.assert_not_called()

    def test_bot_launch_age_uses_only_simulation_clock(self):
        battle = fixture.BattleRuntime(fixture._runtime())
        descriptor = fixture._Descriptor()
        battle._runtime.bigworld.entities[10] = fixture._Vehicle(
            10, descriptor, fixture._Vector(), (0., 0., 0.), {'health': 500})
        battle._records = {'bot:7': {'engine_id': 10, 'kind': 'bot',
            'network_id': 7, 'ready': True, 'state': {'team': 1}}}
        battle._bots = types.SimpleNamespace(_sample_time_us=260000)
        battle._clock = lambda: 5000.
        battle.client = types.SimpleNamespace(authority_epoch=4,
            send_projectile_launch=mock.Mock(return_value=3))
        output = io.StringIO()
        with mock.patch('sys.stdout', output):
            self.assertTrue(battle._launch_bot_projectile({
                'id': 7, 'fire_seq': 3, 'shell_index': 0,
                'shot_yaw': 0., 'shot_pitch': 0., 'shot_origin': (0., 1.5, 0.),
                'launch_time_us': 240000, 'launch_pose': (0.,)*6,
                'profile': {'class_tag': 'mediumTank'}}, 3))
        self.assertIn('simulation_age_ms=20.000', output.getvalue())
        self.assertNotIn('frozen_age_ms', output.getvalue())

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
