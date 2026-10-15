"""Environmental critical checkpoints reach native in-battle feedback once."""
import copy
import unittest

import test_port_0922_environment_statistics as statistics_fixture
from test_port_0922_environment_statistics import critical
from test_port_0922_battle_runtime import BattleRuntime, _runtime


class EnvironmentCriticalFeedbackTests(unittest.TestCase):
    def server(self):
        return statistics_fixture.EnvironmentalStatisticsTests().server()

    def battle(self):
        runtime = _runtime()
        battle = BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        battle._avatar.playerVehicleID = 10
        battle._synchronise_player_identity(10)
        battle._records = {
            'player:1': dict(engine_id=10, local=True, kind='player',
                             network_id=1, state=dict(team=1, health=1000, alive=True)),
            'bot:13': dict(engine_id=23, local=False, kind='bot',
                          network_id=13, state=dict(team=2, health=0, alive=False)),
        }
        return battle, runtime

    def events(self, state):
        return [event for event in state.pending_events
                if event.get('kind') == 'environment_critical']

    def test_reported_ammo_explosion_and_three_criticals_emit_native_crits(self):
        for masks in ((8192,), (2, 262144, 134217728)):
            with self.subTest(masks=masks):
                state = self.server()
                state._consume_environment_criticals(dict(critical_totals=[
                    [13, 'world_collision', bit, 1] for bit in masks]))
                events = self.events(state)
                self.assertEqual(1, len(events))
                self.assertEqual(len(masks), events[0]['critical_count'])
                battle, runtime = self.battle()
                before = copy.deepcopy(battle._records)
                events[0]['event_id'] = '1:3:0'
                message = dict(events=events)
                self.assertTrue(battle.on_events(message))
                self.assertTrue(battle.on_events(message))
                native = runtime.bigworld.avatar.battle_events
                self.assertEqual(1, len(native))
                self.assertEqual([6], [row['eventType'] for row in native[0]])
                unpack = runtime.battle_feedback_common.BATTLE_EVENT_TYPE.unpackCrits
                self.assertEqual((len(masks), 3, 127, 0), unpack(native[0][0]['details']))
                self.assertEqual(before, battle._records)
                self.assertEqual([], runtime.bigworld.avatar.shot_results)

    def test_duplicate_older_and_coalesced_checkpoints_do_not_repeat_feedback(self):
        state = self.server()
        for total in (2, 2, 1, 3):
            state._consume_environment_criticals(dict(
                critical_totals=[[13, 'world_collision', 8192, total]]))
        self.assertEqual([2, 1], [event['critical_count'] for event in self.events(state)])
        self.assertEqual(3, state._statistics_row('player', 1)['critical_hits'])

    def test_drowning_crew_and_environment_fire_keep_native_causes(self):
        for cause, mask, reason in (('drowning', 1 << 24, 5),
                                    ('fire', 8192, 1)):
            with self.subTest(cause=cause):
                state = self.server()
                state._consume_environment_criticals(dict(
                    environment_fires=[13], critical_totals=[[13, cause, mask, 1]]),
                    fire_owners={13: ('player', 1)})
                event = self.events(state)[0]
                battle, runtime = self.battle()
                event['event_id'] = '1:4:0'
                battle.on_events(dict(events=[event]))
                details = runtime.bigworld.avatar.battle_events[0][0]['details']
                self.assertEqual(reason, details >> 8 & 255)

    def test_unowned_transition_is_not_claimed_by_later_push(self):
        state = self.server()
        state.environment_pushes.clear()
        progress = dict(critical_totals=[[13, 'world_collision', 8192, 1]])
        state._consume_environment_criticals(progress)
        state._remember_environment_push(('player', 1), ('bot', 13), 2)
        state._consume_environment_criticals(progress)
        self.assertEqual([], self.events(state))

    def test_zero_hull_damage_player_transition_is_not_lost_or_double_presented(self):
        state = self.server()
        state._remember_environment_push(('player', 1), ('player', 2), 1)
        event = dict(kind='health', source='environment', damage=0,
                     health=1000, dead=False, attack_reason=3, death_reason=0,
                     critical=critical())
        state._attribute_environment_event(event, ('player', 2), {})
        self.assertEqual(1, self.events(state)[0]['critical_count'])
        self.assertTrue(event['critical_feedback_separate'])
        battle, runtime = self.battle()
        event['critical']['events'] = [dict(kind='device', name='ammoBayHealth',
                                          old_state='normal', state='destroyed')]
        self.assertFalse(battle._present_combat_feedback(event,
            battle._records['bot:13'], battle._records['player:1'], 3))
        self.assertEqual([], runtime.bigworld.avatar.battle_events)

    def test_worker_friendly_and_other_players_do_not_get_outgoing_enemy_crit_ribbons(self):
        state = self.server()
        state._consume_environment_criticals(dict(
            critical_totals=[[13, 'world_collision', 8192, 1]]))
        for mode in ('worker', 'friendly', 'other'):
            battle, runtime = self.battle()
            if mode == 'worker':
                battle._worker_mode = True
            elif mode == 'friendly':
                battle._records['bot:13']['state']['team'] = 1
            else:
                battle._records['player:1']['local'] = False
            event = dict(self.events(state)[0], event_id='1:5:0')
            battle.on_events(dict(events=[event]))
            self.assertEqual([], runtime.bigworld.avatar.battle_events)

    def test_pending_native_target_delays_feedback_and_keeps_its_entity_reference(self):
        state = self.server()
        state._consume_environment_criticals(dict(
            critical_totals=[[13, 'world_collision', 8192, 1]]))
        battle, runtime = self.battle()
        target = battle._records.pop('bot:13')
        battle._pending_bot_creates['bot:13'] = target
        event = dict(self.events(state)[0], event_id='1:6:0')
        battle.on_events(dict(events=[event]))
        self.assertEqual([], runtime.bigworld.avatar.battle_events)
        self.assertTrue(battle._pending_event_references('bot:13'))
        battle._pending_bot_creates.pop('bot:13')
        battle._records['bot:13'] = target
        battle._drain_event_journal()
        self.assertEqual(1, len(runtime.bigworld.avatar.battle_events))
        self.assertIn('1:6:0', battle._applied_event_ids)

    def test_attributed_enemy_fall_still_reports_after_losing_spotting(self):
        state = self.server()
        state._consume_environment_criticals(dict(
            critical_totals=[[13, 'world_collision', 8192, 1]]))
        battle, runtime = self.battle()
        battle._combat_target_is_spotted = lambda record: False
        battle.on_events(dict(events=[dict(self.events(state)[0], event_id='1:7:0')]))
        self.assertEqual(6, runtime.bigworld.avatar.battle_events[0][0]['eventType'])

    def test_received_friendly_environment_critical_uses_native_received_event(self):
        battle, runtime = self.battle()
        battle._records['player:1']['local'] = False
        battle._records['bot:13']['local'] = True
        battle._records['bot:13']['state']['team'] = 1
        event = dict(kind='environment_critical', source='environment',
            push_attributed=True, cause='world_collision', critical_count=3,
            critical_mask=2, attacker=1, target_bot=13, event_id='1:8:0')
        battle.on_events(dict(events=[event]))
        self.assertEqual([9], [row['eventType']
            for row in runtime.bigworld.avatar.battle_events[0]])

    def test_native_count_does_not_wrap_and_invalid_feedback_cannot_stop_later_events(self):
        state = self.server()
        state._queue_environment_critical_feedback(
            ('player', 1), ('bot', 13), 'world_collision', 8192, 65536)
        self.assertEqual([65535, 1], [event['critical_count'] for event in self.events(state)])
        battle, runtime = self.battle()
        event = self.events(state)[1]
        invalid = [dict(event, critical_count=value, event_id='1:9:%d' % index)
                   for index, value in enumerate((True, 0, 65536))]
        battle.on_events(dict(events=invalid + [dict(event, event_id='1:9:3')]))
        self.assertEqual(1, len(runtime.bigworld.avatar.battle_events))
        self.assertIn('1:9:3', battle._applied_event_ids)


if __name__ == '__main__':
    unittest.main()
