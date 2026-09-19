"""Mission event boundaries and server -> receipt -> settlement regression."""
import copy
import json
from pathlib import Path
import tempfile
import types
import unittest

from test_port_0922_personal_campaign_battle import node, definition
from test_port_0922_postbattle import (
    BattleState, Player, _Socket, _latest_receipt, CLIENT_BUILD_0922,
    lan_server_module as server, lan_client_module as client, postbattle_store)
from gui.mods.offline_lan_0922 import personal_campaign_battle as policy
from gui.mods.offline_lan_0922 import mission_events


class MissionEventConditionsTests(unittest.TestCase):
    def setUp(self):
        self.conditions = json.loads((Path(__file__).parent /
            'fixtures/personal_mission_event_conditions_0922.json').read_text())
        self.receipt = dict(player_id=1, vehicle='ussr:medium', team=1, winner=1,
                            death_reason=-1, battle_mode='regular',
                            stats={'damage': 4000}, public_results=[], interactions=[])
        for target in range(2, 6):
            self.receipt['public_results'].append(dict(actor_kind='bot', actor_id=target,
                team=2, vehicle='ussr:medium'))
            self.receipt['interactions'].append(dict(target_kind='bot', target_id=target,
                damage=1000, damage_events=1, target_kills=1, death_reason=0,
                mission_events_complete=True, mission_events=[
                    ['critical', 1000, 1 << 16], ['damage', 120000, 1000, True],
                    ['kill', 180000, 0, True, 100.0]]))

    def check(self, condition, stage='main'):
        return policy._condition('postBattle', node(condition[stage]),
                                  policy._Facts(self.receipt, None))

    def test_four_operations_mt3_mt4_ht2_main_and_honours(self):
        for condition in self.conditions:
            for stage in ('main', 'add'):
                with self.subTest(name=condition['name'], stage=stage):
                    self.assertEqual((True, set()), self.check(condition, stage))

    def test_each_reported_condition_rejects_the_near_miss(self):
        for condition in self.conditions:
            with self.subTest(name=condition['name']):
                before = copy.deepcopy(self.receipt)
                for interaction in self.receipt['interactions']:
                    events = interaction['mission_events']
                    if condition['chain'] == 2:
                        events[-1][4] = 101.0
                    elif condition['number'] == 4:
                        events[1][3] = False
                    elif condition['operation'] <= 2:
                        events[1][1] = 120001
                    else:
                        events[-1][1] = 180001
                self.assertEqual((False, set()), self.check(condition))
                self.receipt = before

    def test_mt4_requires_actual_track_breaks_and_honours_needs_tracked_kill(self):
        for condition in self.conditions:
            if condition['chain'] != 3 or condition['number'] != 4:
                continue
            before = copy.deepcopy(self.receipt)
            for interaction in self.receipt['interactions']:
                interaction['mission_events'][0][2] = 1 << 12
            self.assertEqual((False, set()), self.check(condition))
            self.receipt = copy.deepcopy(before)
            for interaction in self.receipt['interactions']:
                interaction['mission_events'][-1][3] = False
            self.assertEqual((True, set()), self.check(condition))
            self.assertEqual((False, set()), self.check(condition, 'add'))
            self.receipt = before

    def test_legacy_or_truncated_history_never_completes_from_totals(self):
        for mode in ('legacy', 'truncated'):
            for row in self.receipt['interactions']:
                if mode == 'legacy':
                    for key in mission_events.FIELDS:
                        row.pop(key, None)
                else:
                    row.update(mission_events=[], mission_events_complete=False)
            for condition in self.conditions:
                with self.subTest(mode=mode, name=condition['name']):
                    self.assertIsNone(self.check(condition)[0])

    def test_friendly_target_events_are_excluded(self):
        for row in self.receipt['public_results']:
            row['team'] = 1
        for condition in self.conditions:
            self.assertEqual((False, set()), self.check(condition))


class MissionEventReceiptTests(unittest.TestCase):
    def state(self, path=None):
        state = BattleState(map_name='01_karelia', receipt_state_path=path)
        state.client_build, state.phase = CLIENT_BUILD_0922, 'battle'
        state.tick = int((server.PREBATTLE_SECONDS + 60) * server.TICK_HZ)
        first = Player(1, _Socket(), ('127.0.0.1', 1), name='Alice',
                       vehicle='ussr:R11_MS-1', team=1, account_key='a' * 32)
        second = Player(2, _Socket(), ('127.0.0.1', 2), name='Bob',
                        vehicle='ussr:R11_MS-1', team=2, account_key='b' * 32)
        first.x, second.x = 0., 100.
        state.players = {1: first, 2: second}
        state._freeze_round_participants((first, second))
        return state, first, second

    def test_server_restart_client_validation_and_exactly_once_mission_settlement(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'receipts.json')
            state, first, second = self.state(path)
            actor, target = ('player', 1), ('player', 2)
            tracked = {'destroyed': ['leftTrackHealth']}
            state._record_critical_damage(actor, target, {}, tracked)
            state._record_critical_damage(actor, target, tracked, tracked)
            # Repair then another admitted track break is a second event.
            state._record_critical_damage(actor, target, {}, tracked)
            second.alive, second.health, second.death_reason = False, 0, 0
            state._record_damage(actor, target, 240, tracked)
            state._record_frag('player', 1, 2, 'player', 2, distance=100.)
            state._increment_interaction(actor, target, 'stun_duration', 1.125)
            self.assertTrue(state._finish_battle(1, 'elimination'))
            receipt = _latest_receipt(state, first.account_key)
            history = receipt['interactions'][0]['mission_events']
            self.assertEqual([
                ['critical', 60000, 1 << 16], ['critical', 60000, 1 << 16],
                ['damage', 60000, 240, True], ['kill', 60000, 0, True, 100.]], history)
            self.assertTrue(client._valid_battle_receipt(receipt))
            restarted = BattleState(map_name='01_karelia', receipt_state_path=path)
            replay = _latest_receipt(restarted, first.account_key)
            self.assertEqual(receipt, replay)
            self.assertEqual(1.125, replay['interactions'][0]['stun_duration'])
            selections = {'personalMissionSelections': {'regular': [33]},
                          'personalMissionProgress': {}}
            quest = definition('<vehicleDamage><limittedTime>120</limittedTime>'
                               '<greaterOrEqual>1</greaterOrEqual></vehicleDamage>',
                               '<isAlive/>', minimum=1)
            vehicles = types.SimpleNamespace(VehicleDescr=lambda **unused:
                types.SimpleNamespace(type=types.SimpleNamespace(tags={'mediumTank'}, level=10)))
            calls = []
            def settle(row):
                result = policy.evaluate(selections, row, vehicles, lambda unused: quest)
                selections['personalMissionProgress'].update(result['completed'])
                calls.append(result['completed'])
                return {}
            store = postbattle_store.PostBattleStore(path=None)
            store._account_key = first.account_key
            store.set_progress_applier(settle)
            self.assertTrue(store.accept(replay))
            self.assertFalse(store.accept(replay))
            self.assertEqual([{'33': 2}], calls)
            # Old receipts retain missing evidence, including optional SPG
            # fields from before these counters were introduced.
            legacy = copy.deepcopy(receipt)
            for interaction in legacy['interactions']:
                for key in tuple(mission_events.FIELDS) + (
                        'damage_events', 'kills_assisted_stun', 'kills_assisted_track'):
                    interaction.pop(key, None)
            self.assertTrue(client._valid_battle_receipt(legacy))
            self.assertEqual(legacy, server._persisted_result_receipt(legacy))

    def test_pre_hit_immobilization_and_enemy_only_events(self):
        state, first, second = self.state()
        actor, target = ('player', 1), ('player', 2)
        tracked = {'destroyed': ['leftTrackHealth']}
        second.alive, second.health, second.critical = False, 0, tracked
        state._record_damage(actor, target, 100, {})
        state._record_critical_damage(actor, target, {}, tracked)
        state._record_frag('player', 1, 2, 'player', 2, distance=10.)
        events = state._receipt_interactions(actor)[0]['mission_events']
        self.assertFalse(events[0][3])
        self.assertFalse(events[-1][3])
        first.team = 2
        before = copy.deepcopy(events)
        state._record_damage(actor, target, 100, tracked)
        state._record_critical_damage(actor, target, {}, tracked)
        self.assertEqual(before, state._receipt_interactions(actor)[0]['mission_events'])

    def test_history_cap_is_bounded_and_explicitly_incomplete(self):
        state, first, second = self.state()
        for unused in range(mission_events.MAX_EVENTS + 1):
            state._record_damage(('player', 1), ('player', 2), 1, {})
        row = state._receipt_interactions(('player', 1))[0]
        self.assertEqual(mission_events.MAX_EVENTS, len(row['mission_events']))
        self.assertFalse(row['mission_events_complete'])
        self.assertTrue(mission_events.valid(row))
        self.assertTrue(state._finish_battle(1, 'elimination'))
        receipt = _latest_receipt(state, first.account_key)
        self.assertLess(len(json.dumps(receipt).encode('utf8')), server.MAX_LINE_BYTES)
        self.assertTrue(client._valid_battle_receipt(receipt))

    def test_malformed_histories_fail_both_receipt_readers(self):
        state, first, second = self.state()
        state._record_damage(('player', 1), ('player', 2), 1, {})
        state._finish_battle(1, 'elimination')
        receipt = _latest_receipt(state, first.account_key)
        for events in ([['kill', 1, 0, True, float('nan')]],
                       [['damage', True, 1, False]], [['damage', 1, 0, False]],
                       [['critical', 2, 1], ['critical', 1, 1]],
                       [['unsupported', 1, 1]]):
            with self.subTest(events=events):
                value = copy.deepcopy(receipt)
                value['interactions'][0]['mission_events'] = events
                self.assertFalse(client._valid_battle_receipt(value))
                with self.assertRaises(ValueError):
                    server._persisted_result_receipt(value)
                with self.assertRaises(ValueError):
                    postbattle_store._receipt(value)
