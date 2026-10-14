import types
import unittest
from unittest import mock

from test_port_0922_server_projectiles import _state, _terminal_critical, TICK_HZ
from gui.mods.offline_lan_0922 import environment_push, postmortem_causes


class EnvironmentAttributionTests(unittest.TestCase):
    def test_stationary_victim_and_head_on_ambiguity(self):
        self.assertEqual(0, environment_push.initiator((2, 0), (0, 0), (-1, 0)))
        self.assertEqual(1, environment_push.initiator((0, 0), (-2, 0), (-1, 0)))
        self.assertIsNone(environment_push.initiator((2, 0), (-2, 0), (-1, 0)))
        self.assertIsNone(environment_push.initiator((0, 2), (0, 0), (-1, 0)))

    def test_native_contact_rows_share_the_push_broadphase(self):
        from gui.mods.offline_lan_0922 import bot_runtime, tank_collision
        runtime = bot_runtime.BotRuntime(1)
        first = dict(id=11, team=1, slot=0, alive=True, x=0., y=0., z=0.,
            yaw=0., mass=25000., speed=1., collision_shape=tank_collision.DEFAULT_SHAPE)
        second = dict(first, id=12, z=3., speed=0.)
        runtime.states = {11:first, 12:second}
        rows = [(actor,(0.,0.),(0.,0.),0.,True,True,(),()) for actor in (11,12)]
        with mock.patch.object(tank_collision, 'contact_roster', return_value=rows), \
                mock.patch.object(runtime, '_apply_tank_contact_response'), \
                mock.patch.object(tank_collision, 'build_spatial_index', wraps=tank_collision.build_spatial_index) as index:
            self.assertEqual([], runtime._resolve_tank_contacts([],1.,.04))
        index.assert_called_once()

    def test_friendly_fall_counts_team_damage_and_blue_without_enemy_damage(self):
        state = _state()
        state.players[2].team = 1
        state._remember_environment_push(('player', 1), ('player', 2))
        state._commit_player_environment_damage(state.players[2], 10, 3)
        event = next(event for event in state.pending_events if event.get('push_attributed'))
        self.assertEqual(1, event['attacker'])
        self.assertEqual(3, event['attack_reason'])
        self.assertEqual(10, state._statistics_row('player', 1)['team_damage'])
        self.assertEqual(0, state._statistics_row('player', 1)['damage_dealt'])
        self.assertTrue(state.players[1].team_killer)
        self.assertEqual(0, state.players[1].frags)

    def test_enemy_fall_kill_preserves_environment_cause(self):
        state = _state()
        state._remember_environment_push(('player', 1), ('player', 2))
        state._commit_player_environment_damage(state.players[2], state.players[2].health, 3)
        self.assertEqual(1, state.players[1].frags)
        self.assertEqual(3, state.players[2].death_reason)
        self.assertEqual(1, state.players[2].death_attacker_id)
        self.assertGreater(state._statistics_row('player', 1)['damage_dealt'], 0)

    def test_contact_expires_and_replayed_sequence_does_not_refresh_it(self):
        state = _state()
        state._remember_environment_push(('player', 1), ('player', 2), 7)
        state.tick += 4 * TICK_HZ
        self.assertFalse(state._remember_environment_push(('player', 1), ('player', 2), 7))
        self.assertIsNone(state._environment_pusher(('player', 2)))
        state._commit_player_environment_damage(state.players[2], 10, 3)
        self.assertNotIn('attacker', state.pending_events[-1])

    def test_drowning_holds_the_confirmed_entry_pusher_for_its_countdown(self):
        state = _state()
        state._maybe_finish_battle = mock.Mock(return_value=False)
        state._remember_environment_push(('player', 1), ('player', 2), 1)
        self.assertEqual(('player', 1), state._environment_pusher(('player', 2), hazard=True))
        state.tick += 11 * TICK_HZ
        state.player_environment[2] = dict(
            observed_tick=state.tick, level=2, drowning_critical=_terminal_critical())
        state.player_drowning_seconds[2] = 10.0
        self.assertEqual(1, state._tick_player_drowning(1.0))
        event = next(event for event in state.pending_events if event.get('push_attributed'))
        self.assertEqual(5, event['death_reason'])
        self.assertEqual(1, event['attacker'])
        self.assertEqual(1, state.players[1].frags)
        self.assertNotIn(('player', 2), state.environment_pushes)

    def test_postmortem_templates_preserve_colors_and_leave_shots_unchanged(self):
        panel = types.SimpleNamespace(_BasePostmortemPanel__messages={
            'DEATH_FROM_FIRE': ('fire', (1, 2)),
            'DEATH_FROM_DEVICE_EXPLOSION_AT_FIRE': ('old fire', (3, 4)),
            'DEATH_FROM_DEVICE_EXPLOSION_AT_SHOT': ('shot', (5, 6)),
        })
        postmortem_causes.populate_templates(panel)
        messages = panel._BasePostmortemPanel__messages
        self.assertEqual(('弹药架因燃烧而爆炸', (3, 4)), messages['DEATH_FROM_DEVICE_EXPLOSION_AT_FIRE'])
        self.assertEqual(('弹药架因坠落而损毁', (3, 4)), messages['DEATH_FROM_DEVICE_EXPLOSION_AT_WORLD_COLLISION'])
        self.assertEqual(('shot', (5, 6)), messages['DEATH_FROM_DEVICE_EXPLOSION_AT_SHOT'])


class EnvironmentPresentationTests(unittest.TestCase):
    def test_fuel_recovery_uses_repair_notice_and_not_a_new_damage_voice(self):
        from test_port_0922_battle_runtime import _runtime, BattleRuntime, _Vehicle, _Descriptor, _Vector
        runtime = _runtime()
        battle = BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        entity = _Vehicle(10, _Descriptor(), _Vector(), (0, 0, 0), {'health': 500})
        runtime.bigworld.entities[10] = entity
        runtime.constants.DAMAGE_INFO_INDICES['DEVICE_REPAIRED_TO_CRITICAL'] = 37
        with mock.patch.object(battle, '_critical_extra_index', return_value=7):
            battle._present_critical(dict(engine_id=10, local=True), [dict(
                kind='device', name='fuelTankHealth', old_state='destroyed',
                state='critical', cause='fire')], 0)
        self.assertEqual([(10, 37, 7, 0, 0)], battle._avatar.damage_info)

    def test_friendly_push_damage_reaches_the_native_damage_log(self):
        from test_port_0922_battle_runtime import _runtime, BattleRuntime, _pack_damage
        runtime = _runtime()
        battle = BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        battle._avatar.playerVehicleID = 10
        battle._synchronise_player_identity(10)
        attacker = dict(engine_id=10, local=True, kind='player', network_id=1, state=dict(team=1))
        victim = dict(engine_id=11, local=False, kind='bot', network_id=2, state=dict(team=1))
        event = dict(kind='bot_hit', source='environment', attack_reason=3,
            death_reason=0, damage=10, dead=False, attacker=1, push_attributed=True)
        battle._validate_combat_event_contract(event)
        self.assertTrue(battle._present_combat_feedback(event, victim, attacker))
        self.assertEqual(_pack_damage(10, 3), battle._avatar.battle_events[0][0]['details'])
        self.assertEqual([], battle._avatar.shot_results)
