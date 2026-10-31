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

    def test_dead_source_keeps_delivered_credit_until_expiry_but_not_disconnect(self):
        self.accept(self.message())
        self.state.players[1].alive = False
        self.assertEqual(200, self.damage())
        self.accept(self.message(direct=(), duration=7.0))
        self.assertEqual(400, self.damage())
        self.state.players[1].connected = False
        self.assertEqual(400, self.damage())
        self.state.players[1].connected = True
        self.now.return_value = 110.0
        self.assertEqual(400, self.damage())
        message = self.message()
        message['round_id'] -= 1
        self.assertFalse(self.state.update_bot_observation(WORKER, message))

    def test_dead_shooter_own_memory_does_not_hide_external_assist(self):
        self.accept(self.message(sources=(1, 2), direct=()))
        self.state.players[2].alive = False
        self.assertEqual(200, self.damage())

    def test_dead_recipient_is_not_admitted_as_a_live_radio_receiver(self):
        self.state.players[2].alive = False
        self.accept(self.message(direct=()))
        self.assertEqual(0, self.damage())

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
    def test_death_radio_damage_cannot_erase_information_already_delivered(self):
        net = radio.RadioNetwork()
        source, receiver, target = ('human', 1), ('bot', 2), ('bot', 9)
        net.configure({source: (1, (0, 0, 0), 100),
                       receiver: (1, (150, 0, 0), 100)}, 0.0)
        net.observe(source, target, 0.0, 10.0, {'x': 90})
        # Last Effort remains in the active roster but terminal crew/radio
        # damage shrinks the current link before its short window expires.
        net.configure({source: (1, (0, 0, 0), 0),
                       receiver: (1, (150, 0, 0), 100)}, 1.0, retiring=(source,))
        self.assertFalse(net.connected(source, receiver))
        self.assertEqual(((source, 9.0),), net.sources(receiver, target, 1.0))

    def test_death_preserves_only_previous_receivers_and_original_expiry(self):
        net = radio.RadioNetwork()
        source, friend, newcomer, target = ('human', 1), ('bot', 2), ('bot', 3), ('bot', 9)
        actors = {source: (1, (0, 0, 0), 100), friend: (1, (50, 0, 0), 100),
                  newcomer: (1, (1000, 0, 0), 100)}
        net.configure(actors, 1.0)
        net.observe(source, target, 1.0, 14.0, {'x': 100})
        net.hidden(source, target)
        dead = {friend: actors[friend], newcomer: (1, (0, 0, 0), 100)}
        net.configure(dead, 2.0, retiring=(source,))
        self.assertEqual(((source, 13.0),), net.sources(friend, target, 2.0))
        self.assertTrue(net.contact(friend, target, 2.0)[0] > 0)
        self.assertEqual((), net.sources(newcomer, target, 2.0))
        self.assertFalse(net.connected(friend, source))
        net.configure(dead, 14.0, retiring=(source,))
        self.assertEqual(((source, 1.0),), net.sources(friend, target, 14.0))
        net.configure(dead, 15.0, retiring=(source,))
        self.assertEqual((), net.sources(friend, target, 15.0))

    def test_disconnect_retires_dead_source_and_bot_memory_uses_same_contract(self):
        net = radio.RadioNetwork()
        source, receiver, target = ('bot', 1), ('human', 2), ('bot', 9)
        actors = {source: (1, (0, 0, 0), 100), receiver: (1, (50, 0, 0), 100)}
        net.configure(actors, 0.0)
        net.observe(source, target, 0.0, 10.0, {'x': 90})
        net.configure({receiver: actors[receiver]}, 1.0, retiring=(source,))
        self.assertEqual(((source, 9.0),), net.sources(receiver, target, 1.0))
        net.configure({receiver: actors[receiver]}, 2.0)
        self.assertEqual((), net.sources(receiver, target, 2.0))

    def test_relay_is_not_cascaded_and_refresh_removes_an_unavailable_donor(self):
        net = radio.RadioNetwork()
        a, b, c = ('human', 1), ('human', 2), ('human', 3)
        actors = {a: (1, (0, 0, 0), 100, .1), b: (1, (190, 0, 0), 100, .1),
                  c: (1, (395, 0, 0), 100, .1)}
        net.configure(actors, 0.0)
        self.assertAlmostEqual(110.0, net.actors[a][2])
        self.assertAlmostEqual(110.0, net.actors[b][2])
        self.assertAlmostEqual(100.0, net.actors[c][2])
        actors[b] = actors[b][:3] + (0.0,)
        net.configure(actors, 1.0)
        self.assertAlmostEqual(100.0, net.actors[a][2])

    def test_last_effort_uses_predeath_crew_and_does_not_reopen_or_acquire_targets(self):
        import copy
        params = fixtures._effective_params_snapshot()
        params['crew']['members'] = [dict(instance='commander', roles=['commander', 'radioman'],
            skills=[dict(name='radioman_lasteffort', active=True, enabled=True, level=100.0)])]
        params['skills']['last_effort'] = True
        params['crew']['dynamic_spotting']['crew'] = ['commander']
        for duration in (2.0, 5.0):
            snapshot = copy.deepcopy(params)
            snapshot['battle_booster'] = dict(compact_descr=11003,
                skill_overrides=dict(last_effort_duration=duration))
            worker = BotRuntime(1, descriptor_resolver=lambda unused: fixtures._combat_descriptor(),
                visibility_probe=lambda *unused: self.fail('corpse acquired a new LOS'))
            worker.states = {identity: dict(id=identity, team=2, alive=True, x=0., y=0.,
                z=100., health=100, max_health=100) for identity in (11, 12)}
            alive = dict(id=1, team=1, alive=True, x=0., y=0., z=0.,
                         critical={'crew_ko': []}, effective_params=snapshot)
            worker._track_human_observer_lifecycle([alive], 1.0)
            worker._human_direct_targets[1] = set((('bot', 11),))
            dead = dict(alive, alive=False, critical={'crew_ko': ['commander']})
            worker._track_human_observer_lifecycle([dead], 2.0)
            self.assertEqual(2.0+duration, worker._human_vengeance_until[1])
            aggregate = {}
            worker._append_human_observations([dead], 2.1, aggregate, {})
            self.assertEqual({1}, aggregate[(1, 'bot', 11)][3])
            self.assertEqual(set(), aggregate[(1, 'bot', 12)][3])
            worker._track_human_observer_lifecycle([dead], 2.0+duration)
            self.assertNotIn(1, worker._human_vengeance_until)
            worker._track_human_observer_lifecycle([dead], 8.0)
            self.assertNotIn(1, worker._human_vengeance_until)

    def test_last_effort_does_not_arm_for_prior_knockout_or_first_seen_dead(self):
        params = fixtures._effective_params_snapshot()
        params['crew']['members'] = [dict(instance='commander', roles=['commander', 'radioman'], skills=[
            dict(name='radioman_lasteffort', active=True, enabled=True, level=100.0)])]
        params['skills']['last_effort'] = True
        params['crew']['dynamic_spotting']['crew'] = ['commander']
        alive = dict(id=1, alive=True, critical={'crew_ko': ['commander']}, effective_params=params)
        dead = dict(alive, alive=False)
        for first_dead in (False, True):
            runtime = BotRuntime(1)
            if not first_dead:
                runtime._track_human_observer_lifecycle([alive], 1.0)
            runtime._track_human_observer_lifecycle([dead], 2.0)
            self.assertNotIn(1, runtime._human_vengeance_until)

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
    def test_model_round_uses_network_identity_instead_of_clock_origin(self):
        import types
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diag
        client = types.SimpleNamespace(round_id=7)
        owner = types.SimpleNamespace(_battle_network_client=client, _battle_server_time_origin=-1.0)
        with mock.patch.dict(diag.os.environ, {diag.DETAIL_ENV: '1'}), \
                mock.patch.object(diag, 'detail_record_ready', return_value=True), \
                mock.patch.object(diag, 'write_json_record') as write:
            diag.battle_review_record(owner, 'model', 1, 1.0, lambda: {}, limit=1)
            self.assertEqual(7, write.call_args[0][1]['round'])
            client.round_id = 8
            diag.battle_review_record(owner, 'model', 1, 2.0, lambda: {}, limit=1)
            self.assertEqual(8, write.call_args[0][1]['round'])
            self.assertEqual(2, write.call_count)

    def test_priority_events_survive_bulk_exhaustion_and_keep_their_own_byte_limit(self):
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diag
        owner = type('Owner', (), {'round_id': 1})()
        with mock.patch.dict(diag.os.environ, {diag.DETAIL_ENV: '1'}), \
                mock.patch.object(diag, 'detail_record_ready', return_value=False), \
                mock.patch.object(diag, 'write_json_record') as write:
            diag.battle_review_record(owner, 'death', 1, 1.0, lambda: {'alive': False}, priority=True)
            self.assertEqual('BATTLE REVIEW EVENT', write.call_args[0][0])
            owner._battle_review_records[2][0] = diag.REVIEW_PRIORITY_BYTES
            diag.battle_review_record(owner, 'death', 2, 2.0, lambda: {}, priority=True)
            self.assertEqual(2, write.call_count)
            self.assertEqual('BATTLE REVIEW LIMIT', write.call_args[0][0])

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
            self.assertLessEqual(len(owner._battle_review_records[1]['test']), 64)
            before = write.call_count
            diag.battle_review_record(owner, 'independent_stage', 'batch', 6.0, lambda: {})
            self.assertEqual(before+1, write.call_count)
            write.side_effect = RuntimeError('broken stdout')
            diag.battle_review_record(owner, 'failure', 1, 6.0, lambda: {})
            for stage in range(30):
                diag.battle_review_record(owner, str(stage), 1, 7.0, lambda: {})
            self.assertLessEqual(len(owner._battle_review_records[1]), 32)

    def test_budget_rejection_does_not_inspect_payload(self):
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diag
        owner = type('Owner', (), {'round_id': 1})()
        with mock.patch.dict(diag.os.environ, {diag.DETAIL_ENV: '1'}), \
                mock.patch.object(diag, 'REVIEW_STAGE_BYTES', 0):
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


    def test_existing_frame_samples_corpses_when_effects_lod_stops(self):
        import ast
        import types
        from pathlib import Path
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diag
        path = Path(control.__file__).with_name('compat.py')
        functions = [node for node in ast.parse(path.read_text(encoding='utf8')).body
                     if isinstance(node, ast.FunctionDef) and node.name in
                     ('_observe_battle_model_pose', 'sample_pending_battle_models')]
        namespace = {}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)
        matrix = types.SimpleNamespace(yaw=0.4, pitch=0.1, roll=0., translation=(0., 0., 0.))
        model = types.SimpleNamespace(matrix=matrix, node=lambda unused: matrix)
        appearance = types.SimpleNamespace(turretMatrix=matrix, gunMatrix=matrix)
        vehicle = types.SimpleNamespace(id=2, appearance=appearance, health=0, model=model, filter=None)
        appearance._CompoundAppearance__vehicle = vehicle
        appearance._CompoundAppearance__filter = None
        appearance._CompoundAppearance__currentDamageState = types.SimpleNamespace(modelState='destroyed')
        clock = [1.0]
        owner = types.SimpleNamespace(_battle_active=True, _model_lifecycle_histories={},
            _runtime=types.SimpleNamespace(math=types.SimpleNamespace(Matrix=lambda value: value),
                bigworld=types.SimpleNamespace(time=lambda: clock[0], entity=lambda identity: vehicle)))
        with mock.patch.dict(diag.os.environ, {diag.DETAIL_ENV: '1'}), \
                mock.patch.object(diag, 'detail_record_ready', return_value=True), \
                mock.patch.object(diag, 'write_json_record') as write:
            namespace['_observe_battle_model_pose'](owner, appearance, 'refresh_after')
            for unused in range(20):
                clock[0] += .2
                namespace['sample_pending_battle_models'](owner)
            self.assertEqual(8, sum(call.args[1]['stage'] == 'model_frame_tick'
                                    for call in write.call_args_list))
            self.assertEqual({}, owner._battle_model_pose_pending)
            namespace['_observe_battle_model_pose'](owner, appearance, 'refresh_after')
            owner._model_lifecycle_histories = {}  # A different battle generation.
            before = write.call_count
            namespace['sample_pending_battle_models'](owner)
            self.assertEqual(before, write.call_count)
            self.assertEqual({}, owner._battle_model_pose_pending)


if __name__ == '__main__':
    unittest.main()
