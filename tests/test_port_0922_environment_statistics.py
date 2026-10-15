"""Environmental result credit uses real transitions, never wreck cleanup."""
import unittest
from unittest import mock

from test_port_0922_server_projectiles import _state, _terminal_critical
from gui.mods.offline_lan_0922 import critical_statistics as statistics


def critical(name='ammoBayHealth', state='destroyed', crew=()):
    return dict(devices=[dict(name=name, hp=0 if state == 'destroyed' else 40,
                             max_hp=100, state=state)],
                destroyed=[name] if state == 'destroyed' else [],
                crew_ko=list(crew), fire=False, events=[])


class EnvironmentalStatisticsTests(unittest.TestCase):
    def server(self, team=2):
        state = _state()
        state.bot_states[13] = dict(id=13, team=team, alive=True, health=1000,
            max_health=1000, vehicle='china:Ch01_Type59', x=10., y=0., z=0.)
        state._remember_environment_push(('player', 1), ('bot', 13), 1)
        return state

    def test_drowning_counts_only_new_crew_not_terminal_module_cleanup(self):
        before = critical(crew=['driver'])
        after = _terminal_critical()
        after['crew_ko'] = ['commander', 'driver', 'gunner1', 'loader1']
        totals = {}
        mask = statistics.accumulate(totals, 13, 'drowning', before, after, crew_only=True)
        self.assertEqual((1 << 24) | (1 << 27) | (1 << 28), mask)
        self.assertEqual(3, len(totals))

    def test_coalesced_checkpoints_and_retries_credit_exactly_once(self):
        state = self.server()
        rows = dict(critical_totals=[[13, 'world_collision', 1 << 13, 2]])
        state._consume_environment_criticals(rows)
        state._consume_environment_criticals(rows)
        state._consume_environment_criticals(dict(critical_totals=[[13, 'world_collision', 1 << 13, 1]]))
        self.assertEqual(2, state._statistics_row('player', 1)['critical_hits'])
        self.assertEqual(1 << 13, state._statistics_interaction(('player', 1), ('bot', 13))['crits'])

    def test_unowned_transitions_cannot_be_claimed_by_a_later_pusher(self):
        state = self.server()
        state.environment_pushes.clear()
        rows = dict(critical_totals=[[13, 'world_collision', 1 << 13, 1]])
        state._consume_environment_criticals(rows)
        state._remember_environment_push(('player', 1), ('bot', 13), 2)
        state._consume_environment_criticals(rows)
        self.assertEqual(0, state._statistics_row('player', 1)['critical_hits'])

    def test_friendly_modules_do_not_become_enemy_critical_credit(self):
        state = self.server(team=1)
        state._consume_environment_criticals(dict(critical_totals=[[13, 'world_collision', 1 << 13, 1]]))
        self.assertEqual(1, state._statistics_row('player', 1)['team_crits'])
        self.assertEqual(0, state._statistics_row('player', 1)['critical_hits'])

    def test_recent_push_cannot_take_over_an_already_unowned_fire(self):
        state = self.server()
        state.bot_states[13]['critical'] = dict(fire=True)
        state._consume_environment_criticals(dict(environment_fires=[13],
            critical_totals=[[13, 'fire', 1 << 13, 1]]))
        self.assertEqual(0, state._statistics_row('player', 1)['critical_hits'])

    def test_last_fire_tick_preserves_owner_after_terminal_lineage_clear(self):
        state = self.server()
        state.environment_pushes.clear()
        state.bot_states[13].update(alive=False, health=0)
        state._consume_environment_criticals(dict(environment_fires=[13],
            critical_totals=[[13, 'fire', 1 << 13, 1]]), {13: ('player', 1)})
        self.assertEqual(1, state._statistics_row('player', 1)['critical_hits'])

    def test_player_drowning_uses_native_crew_bits_without_all_module_credit(self):
        state = _state()
        state._remember_environment_push(('player', 1), ('player', 2), 1)
        terminal = _terminal_critical()
        terminal['crew_ko'] = ['commander', 'driver', 'gunner1', 'loader1']
        event = dict(kind='health', damage=1000, dead=True, attack_reason=5, critical=terminal)
        state._attribute_environment_event(event, ('player', 2), {})
        self.assertEqual(4, state._statistics_row('player', 1)['critical_hits'])
        self.assertEqual(0x1b000000, state._statistics_interaction(('player', 1), ('player', 2))['crits'])

    def test_worker_records_actual_fall_before_terminal_cleanup(self):
        from gui.mods.offline_lan_0922 import bot_runtime
        from gui.mods.offline_lan_0922 import environment_modules
        runtime = bot_runtime.BotRuntime(1, impact_contacts_resolver=lambda *unused: [])
        state = dict(id=13, health=1000, max_health=1000, critical={}, alive=True)
        runtime._descriptors[13] = {}
        runtime._turn_speeds[13] = 0.
        with mock.patch.object(environment_modules, 'apply_impact', return_value=(1000, critical())), \
                mock.patch.object(bot_runtime, '_terminal_critical', return_value=_terminal_critical()):
            state['_landing_ground_observed'] = True
            runtime._apply_bot_fall_damage(state, 20.)
        self.assertEqual({(13, 'world_collision', 1 << 13): 1}, runtime._environment_critical_totals)
        self.assertFalse(state['alive'])

    def test_worker_fire_records_ammo_explosion_before_wreck_cleanup(self):
        from gui.mods.offline_lan_0922 import bot_runtime
        from test_port_0922_critical_damage import _strict_1513_descriptor
        runtime = bot_runtime.BotRuntime(1)
        runtime._descriptors[13] = _strict_1513_descriptor()
        payload = critical()
        payload.update(fire=True, destroyed=[], ammo_rack_death=False)
        payload['devices'][0].update(hp=1., state='critical')
        state = dict(id=13, health=1000, max_health=1000, critical=payload,
                     alive=True, _environment_fire=True)
        with mock.patch.object(runtime, '_bot_repair_factor', return_value=.57):
            runtime._advance_bot_critical(state, 1., 1., record_step=False, equipment_effects=())
        self.assertFalse(state['alive'])
        self.assertEqual({(13, 'fire', 1 << 13): 1}, runtime._environment_critical_totals)

    def test_worker_drowning_journal_contains_only_installed_crew(self):
        from gui.mods.offline_lan_0922 import bot_runtime
        from test_port_0922_critical_damage import _strict_1513_descriptor
        runtime = bot_runtime.BotRuntime(1)
        runtime._descriptors[13] = _strict_1513_descriptor()
        runtime._water_depth_probe = lambda position: 10.
        state = dict(id=13, health=1000, max_health=1000, critical={}, alive=True,
                     x=0., y=0., z=0.)
        with mock.patch.object(bot_runtime, '_water_sensor_level', return_value=2):
            self.assertTrue(runtime._advance_bot_drowning(state, 11.))
        self.assertEqual({(13, 'drowning', 1 << index): 1 for index in (24, 25, 28)},
                         runtime._environment_critical_totals)

    def test_player_fall_ignition_and_ammo_fire_keep_the_pusher_credit(self):
        from gui.mods.offline_lan_0922 import player_critical_mechanics as mechanics
        from test_port_0922_critical_damage import _strict_1513_descriptor
        state = _state()
        player = state.players[2]
        player.effective_params['critical'] = mechanics.project_profile(_strict_1513_descriptor())
        player.critical = dict(fire=False, destroyed=[], crew_ko=[], events=[],
            devices=[dict(name=name, hp=1., max_hp=100., state='critical')
                     for name in ('fuelTankHealth', 'ammoBayHealth')])
        state._remember_environment_push(('player', 1), ('player', 2), 1)
        unused, payload = mechanics.advance_impact(player, 20.,
            [dict(name='fuelTankHealth', weight=1.)], float(state.tick) / 30.)
        state._commit_player_environment_damage(player, 10, 3, critical=payload)
        self.assertEqual('player', player.fire_attacker_kind)
        self.assertEqual(1, player.fire_attacker_id)
        state.tick += 30
        state._tick_player_fire(1.)
        self.assertFalse(player.alive)
        self.assertEqual(2, state._statistics_row('player', 1)['critical_hits'])
        self.assertEqual((1 << 14) | (1 << 13),
            state._statistics_interaction(('player', 1), ('player', 2))['crits'])
