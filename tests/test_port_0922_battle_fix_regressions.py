"""Received spotting sources, 14s memory and bounded review diagnostics."""
import unittest
from unittest import mock

import test_port_0922_bot_runtime as fixtures
from lan_battle_server import SIMULATION_WORKER_AUTHORITY_ID as WORKER
from gui.mods.offline_lan_0922 import radio
from gui.mods.offline_lan_0922 import native_control_core as control
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

    def test_diagnostics_capture_accepted_deadlines_and_actual_shares(self):
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diag
        with mock.patch.dict(diag.os.environ, {diag.DETAIL_ENV: '1'}), \
                mock.patch.object(diag, 'detail_record_ready', return_value=True), \
                mock.patch.object(diag, 'write_json_record') as write:
            self.accept(self.message(direct=(), duration=7.0))
            self.assertEqual(201, self.damage(201))
            rows = [call.args[1] for call in write.call_args_list]
            accepted = next(row for row in rows if row['stage'] == 'server_radio_accepted')
            self.assertEqual(107.0, accepted['leases'][0]['sources'][0]['deadline'])
            credit = next(row for row in rows if row['stage'] == 'server_radio_credit')
            self.assertEqual([{'actor': ('player', 1), 'amount': 201}], credit['credits'])
            self.assertFalse(credit['direct_self_spot'])
            self.assertEqual(7.0, credit['candidates'][0]['remaining'])
            self.now.return_value = 108.0
            self.damage(201)
            expired = write.call_args[0][1]
            self.assertEqual('expired', expired['candidates'][0]['reason'])
            self.assertEqual([], expired['credits'])

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

    def test_bot_observer_and_bot_shooter_use_the_same_received_source_contract(self):
        for bot_id in (12, 13):
            self.state.bot_manifest.append(dict(id=bot_id, team=1, slot=bot_id - 12,
                                                name='Ally', vehicle='ussr:R11_MS-1'))
            self.state.bot_states[bot_id] = dict(id=bot_id, team=1, alive=True,
                                                 health=1000, max_health=1000)
        for receiver in (('human', 2), ('bot', 13)):
            message = self.message(sources=(1,), direct=(1,))
            contact = message['contacts'][0]
            contact['visible_by_bot_ids'] = [12]
            contact['radio_recipients'][0].update(kind=receiver[0], id=receiver[1])
            contact['radio_recipients'][0]['sources'].append(
                dict(kind='bot', id=12, time_left=10.0))
            self.accept(message)
            attacker = ('player' if receiver[0] == 'human' else 'bot', receiver[1])
            self.assertEqual([('player', 1), ('bot', 12)],
                             self.state._radio_assisters(attacker, ('bot', 11), 2))
            contact.update(fresh=False, visible_by_bot_ids=[], visible_by_player_ids=[])
            self.accept(message)
            self.assertEqual([('player', 1), ('bot', 12)],
                             self.state._radio_assisters(attacker, ('bot', 11), 2))


class SourceLeaseTests(unittest.TestCase):
    def test_removed_target_cannot_recover_old_sources_when_it_rejoins(self):
        runtime = BotRuntime(1)
        net = runtime._radio_network
        source, target = ('human', 1), ('human', 2)
        actors = {source: (1, (0, 0, 0), 200), target: (2, (100, 0, 0), 200)}
        net.configure(actors, 1.0)
        runtime._track_human_observer_lifecycle([dict(id=1), dict(id=2)], 1.0)
        net.observe(source, target, 1.0, 10.0, {'x': 100})
        self.assertEqual(((source, 10.0),), net.sources(source, target, 1.0))
        runtime._track_human_observer_lifecycle([dict(id=1)], 2.0)
        net.configure(actors, 3.0)
        self.assertEqual((), net.sources(source, target, 3.0))


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
    def test_native_observation_bridge_does_not_shorten_the_worker_lease(self):
        runtime = BotRuntime(1)
        owner = control.NativeControl.__new__(control.NativeControl)
        owner.runtime, owner.backend = runtime, object()
        owner._sources = {(0, 1): dict(team=1)}
        owner._old_radio = radio.RadioNetwork()
        owner.observations = lambda: (((0, 1), (1, 12), 10.0, 14.0,
                                        control._pose(dict(x=100.0, y=0.0, z=0.0))),)
        owner._sync_events()
        self.assertEqual(24.0, runtime._spot_until[(1, 'bot', 12)])

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



class BattleReviewDiagnosticsTests(unittest.TestCase):
    def test_disabled_diagnostics_do_not_build_or_retain_payload(self):
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diag
        owner = type('Owner', (), {'round_id': 1})()
        with mock.patch.dict(diag.os.environ, {}, clear=True):
            build = mock.Mock(side_effect=AssertionError('must stay lazy'))
            diag.battle_review_record(owner, 'test', 'target', 1.0, build)
        self.assertFalse(build.called)
        self.assertFalse(hasattr(owner, '_battle_review_records'))

    def test_bounds_reset_on_round_and_logging_failure_is_contained(self):
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diag
        owner = type('Owner', (), {'round_id': 1})()
        with mock.patch.dict(diag.os.environ, {diag.DETAIL_ENV: '1'}), \
                mock.patch.object(diag, 'detail_record_ready', return_value=True), \
                mock.patch.object(diag, 'write_json_record') as write:
            build = mock.Mock(return_value={'value': 42})
            for now in (1.0, 1.5, 2.0, 3.0):
                diag.battle_review_record(owner, 'test', 'target', now, build,
                                         interval=1.0, limit=2)
            self.assertEqual(2, build.call_count)
            owner.round_id = 2
            diag.battle_review_record(owner, 'test', 'target', 4.0, build,
                                     interval=1.0, limit=2)
            self.assertEqual(3, build.call_count)
            self.assertEqual(2, write.call_args[0][1]['round'])
            for key in range(150):
                diag.battle_review_record(owner, 'test', key, 5.0, lambda: {})
            self.assertLessEqual(len(owner._battle_review_records[1]), 128)
            write.side_effect = RuntimeError('broken stdout')
            diag.battle_review_record(owner, 'failure', 1, 6.0, lambda: {})

    def test_budget_rejection_does_not_inspect_payload(self):
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diag
        owner = type('Owner', (), {'round_id': 1})()
        with mock.patch.dict(diag.os.environ, {diag.DETAIL_ENV: '1'}), \
                mock.patch.object(diag, 'detail_record_ready', return_value=False):
            build = mock.Mock(side_effect=AssertionError('budget closed'))
            diag.battle_review_record(owner, 'test', 'target', 1.0, build)
            self.assertFalse(build.called)


    def test_model_probe_records_refresh_and_eight_dead_frames_without_writes(self):
        import ast
        import types
        from pathlib import Path
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diag
        compat_path = Path(control.__file__).with_name('compat.py')
        tree = ast.parse(compat_path.read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == '_observe_battle_model_pose')
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]),
                     str(compat_path), 'exec'), namespace)
        observe = namespace['_observe_battle_model_pose']
        matrix = types.SimpleNamespace(yaw=0.98, pitch=0.006, roll=0.0,
                                       translation=(1.0, 2.0, 3.0))
        model = types.SimpleNamespace(matrix=matrix, node=lambda name: matrix)
        appearance = types.SimpleNamespace(turretMatrix=matrix, gunMatrix=matrix)
        vehicle = types.SimpleNamespace(id=2, appearance=appearance, health=219,
            model=model, filter=None, isTurretDetached=False, gunAngles=0)
        appearance._CompoundAppearance__vehicle = vehicle
        appearance._CompoundAppearance__filter = None
        appearance._CompoundAppearance__currentDamageState = types.SimpleNamespace(modelState='alive')
        clock = [0.0]
        owner = types.SimpleNamespace(_battle_active=True,
            _battle_server_time_origin=100.0,
            _runtime=types.SimpleNamespace(
                bigworld=types.SimpleNamespace(time=lambda: clock[0]),
                math=types.SimpleNamespace(Matrix=lambda value: value)))
        with mock.patch.dict(diag.os.environ, {diag.DETAIL_ENV: '1'}), \
                mock.patch.object(diag, 'detail_record_ready', return_value=True), \
                mock.patch.object(diag, 'write_json_record') as write:
            observe(owner, appearance, 'effects_tick')
            self.assertEqual(0, write.call_count)
            vehicle.health = 0
            clock[0] = 1.0
            observe(owner, appearance, 'refresh_before')
            matrix.yaw = 0.0  # Model replacement can disagree with prior controls.
            observe(owner, appearance, 'refresh_after')
            for frame in range(20):
                clock[0] += 0.2
                observe(owner, appearance, 'effects_tick')
            rows = [call.args[1] for call in write.call_args_list]
            self.assertEqual(1, sum(row['stage'] == 'model_last_alive' for row in rows))
            self.assertEqual(8, sum(row['stage'] == 'model_effects_tick' for row in rows))
            self.assertEqual(0.98, next(row for row in rows if
                row['stage'] == 'model_last_alive')['turret']['yaw'])
            self.assertEqual(0.0, next(row for row in rows if
                row['stage'] == 'model_refresh_after')['turret']['yaw'])
            self.assertEqual(0.0, matrix.yaw)
            before = write.call_count
            vehicle.appearance = object()
            observe(owner, appearance, 'refresh_after')
            self.assertEqual(before, write.call_count)
            owner._battle_active = False
            observe(owner, appearance, 'refresh_after')
            self.assertEqual(before, write.call_count)


if __name__ == '__main__':
    unittest.main()
