"""Sparse identity, human replacement, locked defaults and wire capacities."""
import types
import unittest
from lan_battle_server import BattleState
from test_port_0922_server_team_size import _hello, _Connection
from gui.mods.offline_lan_0922 import lineup_slots, lan_client


ROWS = [dict(team=1, slot=0, enabled=False), dict(team=1, slot=3, enabled=True),
        dict(team=1, slot=14, enabled=True), dict(team=2, slot=6, enabled=True)]


class SparseLineupTests(unittest.TestCase):
    def test_disabled_difficulty_survives_server_environment_but_is_not_an_active_pin(self):
        import json
        import windows_server
        import bot_lineup_profiles as profiles
        from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
        store, name = profiles.create(profiles.empty_store(), 'Inactive presets')
        rows = [dict(team=1, slot=0, enabled=False, skill='elite'),
                dict(team=1, slot=14, enabled=True, skill='veteran'),
                dict(team=2, slot=6, enabled=True)]
        store = profiles.replace_assignments(store, name, rows)
        saved = profiles.runtime_assignments(json.loads(json.dumps(store)), name)
        wire = windows_server._bot_lineup_from_environment(
            {windows_server.SERVER_BOT_LINEUP_ENV: json.dumps(saved)})
        state = BattleState(bot_lineup=wire)
        self.assertEqual('elite', state.bot_lineup[0]['skill'])
        self.assertEqual({1: 1, 2: 1}, state.team_sizes)
        self.assertEqual([(1, 14), (2, 6)],
                         [(r['team'], r['slot']) for r in state._new_bot_roster()])
        self.assertEqual({(1, 14): 'veteran'},
                         BotRuntime._lineup_skill_pins({'bot_lineup': state.bot_lineup}))
        from unittest import mock
        import lan_battle_server as server_module
        diagnostic = server_module.battle_review_diagnostics
        with mock.patch.object(diagnostic, 'detailed_enabled', return_value=False), \
                mock.patch.object(diagnostic, 'validation_event') as event:
            state._new_bot_roster()
            event.assert_not_called()
        with mock.patch.object(diagnostic, 'detailed_enabled', return_value=True), \
                mock.patch.object(diagnostic, 'validation_event') as event:
            state._new_bot_roster()
            self.assertEqual([
                dict(team=1,slot=0,enabled=False,skill='elite'),
                dict(team=1,slot=14,enabled=True,skill='veteran')],
                event.call_args.kwargs['difficulty_presets'])
        with self.assertRaises(ValueError):
            BattleState(bot_lineup=[dict(team=1,slot=0,enabled=False,vehicle='usa:T1')])
        with self.assertRaises(ValueError):
            BattleState(bot_lineup=[dict(team=1,slot=0,enabled=False,skill='invalid')])

    def test_sparse_roster_keeps_original_ids_and_locked_defaults(self):
        state = BattleState(bot_lineup=ROWS, bot_skill_mode='brutal', bot_tier_mode='same')
        self.assertEqual({1: 2, 2: 1}, state.team_sizes)
        self.assertEqual('mixed', state.bot_skill_mode)
        self.assertEqual('random', state.bot_tier_mode)
        self.assertEqual([(1, 3, 4), (1, 14, 15), (2, 6, 22)],
                         [(r['team'], r['slot'], r['id']) for r in state._new_bot_roster()])
        self.assertTrue(state.lobby_message()['lineup_locked'])

    def test_humans_replace_sparse_slots_and_excess_is_refused(self):
        state = BattleState(bot_lineup=ROWS)
        humans = []
        for n in (1, 2):
            player, error = state.add_player(_Connection(), ('127.0.0.1', 1000+n), _hello(n, 1))
            self.assertIsNone(error)
            humans.append(player)
        self.assertEqual([3, 14], [p.slot for p in humans])
        player, error = state.add_player(_Connection(), ('127.0.0.1', 1003), _hello(3, 1))
        self.assertIsNone(player)
        self.assertEqual('team_full', error)
        self.assertEqual([(2, 6)], [(r['team'], r['slot']) for r in
                         state._new_bot_roster({(p.team, p.slot) for p in humans})])
        humans[0].connected = False
        state.lobby_message()
        self.assertEqual(3, humans[1].slot)
        self.assertEqual((True, None), state.select_team(humans[1].player_id, 2))
        self.assertEqual(6, humans[1].slot)

    def test_locked_requests_do_not_change_configuration(self):
        state = BattleState(bot_lineup=ROWS)
        host, error = state.add_player(_Connection(), ('127.0.0.1', 1001), _hello(1, 1))
        self.assertIsNone(error)
        self.assertFalse(state.set_team_size(host.player_id, 1, 15)[0])
        self.assertFalse(state.set_bot_tier_mode(host.player_id, 'same')[0])
        self.assertFalse(state.set_bot_skill_mode(host.player_id, 'brutal')[0])
        self.assertFalse(state.set_team_class(host.player_id, 1, 'random', False))
        self.assertEqual({1: 2, 2: 1}, state.team_sizes)

    def test_empty_team_rejects_start_and_zero_is_only_valid_on_explicit_wire(self):
        state = BattleState(bot_lineup=[dict(team=1,slot=0,enabled=True),
                                      dict(team=2,slot=0,enabled=False)])
        host, error = state.add_player(_Connection(), ('127.0.0.1', 1001), _hello(1, 1))
        self.assertIsNone(error)
        self.assertEqual((None, 'empty_lineup_team'), state.request_start(host.player_id))
        self.assertEqual('waiting', state.phase)
        self.assertEqual({1:1,2:0}, lan_client._team_sizes({'1':1,'2':0}, allow_empty=True))
        self.assertIsNone(lan_client._team_sizes({'1':1,'2':0}))

    def test_country_and_class_constraints_do_not_expand(self):
        row = dict(nation='usa', vehicle_class='SPG')
        self.assertTrue(lineup_slots.matches(row, dict(name='usa:T', tags=['SPG'])))
        self.assertFalse(lineup_slots.matches(row, dict(name='usa:T', tags=['heavyTank'])))
        self.assertFalse(lineup_slots.matches(row, dict(name='ussr:T', tags=['SPG'])))
        self.assertTrue(BattleState(bot_lineup=[dict(team=1,slot=3,enabled=True,**row)]).
                        _lineup_pins_vehicle(1,3,'usa:T','SPG'))

    def test_automatic_returns_original_fifteen_capacities(self):
        state = BattleState(bot_lineup=[])
        self.assertFalse(state.lineup_locked)
        self.assertEqual({1:15,2:15}, state.team_sizes)
        self.assertEqual(list(range(15)), state._team_slots(1))

    def test_empty_custom_room_still_allows_host_to_see_zero_capacities(self):
        state = BattleState(bot_lineup=[dict(team=1,slot=0,enabled=False),
                                      dict(team=2,slot=0,enabled=False)])
        host, error = state.add_player(_Connection(), ('127.0.0.1',1001), _hello(1,1))
        self.assertIsNone(error)
        self.assertEqual((0,-1),(host.team,host.slot))
        self.assertEqual((None,'empty_lineup_team'),state.request_start(host.player_id))

    def test_custom_room_does_not_replay_saved_difficulty_or_sparse_sizes(self):
        from gui.mods.offline_lan_0922.lan_session import LANSession
        from unittest import mock
        client=types.SimpleNamespace(lineup_locked=True,bot_skill_mode='mixed',
            set_bot_skill_mode=mock.Mock(),set_team_size=mock.Mock())
        owner=types.SimpleNamespace(client=client,_client_generation=1,
            _restored_skill_generation=None,_restored_team_sizes_generation=None,
            _restored_team_generation=1,_room_preferences={'team_sizes':{1:2,2:3},'bot_skill_mode':'brutal'},
            _is_local_host=lambda:True,_server_supports_team_size_selection=lambda:True,
            _save_room_preferences=mock.Mock())
        LANSession._restore_waiting_preferences(owner)
        self.assertEqual({1:15,2:15},owner._room_preferences['team_sizes'])
        client.set_bot_skill_mode.assert_not_called()
        client.set_team_size.assert_not_called()

    def test_native_assignment_respects_sparse_filtered_random_without_expansion(self):
        from test_port_0922_bot_lineup_integration import BotLineupIntegrationTests
        fixture=BotLineupIntegrationTests()
        results=[]
        for worker in (False,True):
            battle,descriptor=fixture._profile_exclusion_runtime(worker,'same',[],[
                dict(team=2,slot=14,enabled=True,nation='usa',vehicle_class='mediumTank')])
            battle._start_message['bots']=[dict(id=30,team=2,slot=14)]
            self.assertTrue(battle._prepare_bot_vehicle_assignments(descriptor))
            self.assertEqual({(2,14):'usa:Regular'},battle._bot_vehicle_assignments)
            results.append(battle._bot_vehicle_assignments)
            battle._start_message['bot_lineup'][0]['nation']='china'
            self.assertFalse(battle._prepare_bot_vehicle_assignments(descriptor))
        self.assertEqual(results[0],results[1])


if __name__ == '__main__':
    unittest.main()
