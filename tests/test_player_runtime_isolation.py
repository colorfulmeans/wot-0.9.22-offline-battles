"""Foreground lifecycle and physical replicas must not need a Bot controller."""
import copy
import math
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixture
from gui.mods.offline_lan_0922 import (
    replica_physics, vehicle_fitting_context, vehicle_physics)


class ForbiddenBot(object):
    def __getattr__(self, name):
        raise AssertionError('foreground accessed BotRuntime.%s' % name)


class PlayerRuntimeIsolationTests(unittest.TestCase):
    setUp = fixture.BattleRuntimeContractTests.setUp

    def test_visible_startup_and_teardown_never_construct_bot_runtime(self):
        native = fixture._runtime()
        native.bigworld.defer_vehicle_entry = True
        battle = fixture.BattleRuntime(native)
        client = fixture._Client()
        start = dict(round_id=1, map='01_karelia', bot_authority_id=-1,
            players=[dict(id=1, team=1, slot=0, name='Player',
                          vehicle='ussr:R11_MS-1', health=500)], bots=[])
        with mock.patch.object(fixture.bot_runtime, 'BotRuntime',
                side_effect=AssertionError('foreground constructed BotRuntime')) as constructor:
            self.assertTrue(battle.start(dict(map='01_karelia',
                vehicle='ussr:R11_MS-1', name='Player'), start, client))
            native.bigworld.callbacks.pop(0)()
            native.bigworld.enter_pending_vehicle(battle._server.vehicle_id)
            native.bigworld.callbacks.pop(0)()
            self.assertEqual('running', battle.state, battle.error)
            self.assertIsNone(battle._bots)
            self.assertIsNone(battle._artillery)
            battle.stop(restore_account=False)
            constructor.assert_not_called()

    def test_visible_frame_cannot_tick_an_accidentally_retained_bot_object(self):
        native = fixture._runtime()
        native.bigworld.now = 1.0
        battle = fixture.BattleRuntime(native)
        battle.state, battle._battle_live = 'running', True
        battle._last_frame_time = .98
        battle._avatar = native.bigworld.avatar
        battle._last_snapshot = dict(players=[])
        update = mock.Mock(side_effect=AssertionError('visible Bot tick'))
        present = mock.Mock(side_effect=AssertionError('visible Bot pose owner'))
        battle._bots = types.SimpleNamespace(update=update, presentation_states=present)
        for name in ('_flush_pending_bot_create', '_flush_pending_entities',
                     '_drain_event_journal', '_maybe_send_battle_ready',
                     '_tick_critical_states', '_tick_drowning', '_drive_local',
                     '_update_target_outline', '_apply_authority_bot_poses',
                     '_update_spotting', '_schedule'):
            setattr(battle, name, mock.Mock())
        battle._frame()
        self.assertEqual('running', battle.state, battle.error)
        update.assert_not_called()
        present.assert_not_called()
        battle._drive_local.assert_called_once()
        battle._schedule.assert_called_once_with(0.0, battle._frame)

    def test_public_contact_history_survives_without_bot_runtime(self):
        battle = fixture.BattleRuntime(fixture._runtime())
        battle.client = fixture._Client()
        battle.state = 'running'
        battle._bots = ForbiddenBot()
        battle._sync = mock.Mock()
        raw = dict(id=11, x=2., y=0., z=3., yaw=.2, speed=1.,
                   alive=True, contact_push_acks=[])
        battle._records['bot:11'] = dict(kind='bot', network_id=11,
            state=dict(raw, mass=31000., collision_shape=(1.5, 3.5, 0., 1.)))
        snapshot = dict(round_id=1, server_tick=1, bots=[raw],
                        bot_state_revision=4, bot_state_time_us=1000000)
        before = copy.deepcopy(snapshot)
        self.assertTrue(battle.on_snapshot(snapshot))
        self.assertEqual(before, snapshot)
        self.assertEqual(2., battle._ram_bot_history[4][11]['x'])
        self.assertEqual(31000., battle._ram_bot_history[4][11]['mass'])
        self.assertEqual([(1000000, 4)], battle._ram_bot_history_index[11])
        battle._sync.snapshot.assert_called_once_with(snapshot)

    def test_contact_prediction_and_parameters_only_use_published_facts(self):
        native = fixture._runtime()
        battle = fixture.NativeBattleRuntime(native)
        battle.client, battle._avatar = fixture._Client(), native.bigworld.avatar
        battle._bots = ForbiddenBot()
        descriptor = fixture._Descriptor()
        descriptor.physics.update(weight=31000., enginePower=900.*735.49875)
        factors = fixture._plain_bot_factors(descriptor, crew_level=75)
        value = dict(wire=dict(crew_level=75), crew_roster=(),
                     factors={(id(descriptor), (), False, ()): factors})
        vehicle_fitting_context.register(descriptor, value)
        self.addCleanup(vehicle_fitting_context.clear)
        native.bigworld.entities[11] = fixture._Vehicle(
            11, descriptor, fixture._Vector(0., 0., 5.), (0., 0., 0.), {'health':500})
        shape = (1.5, 3.5, 0., 1.)
        state = dict(id=11, x=0., y=0., z=5., yaw=0., speed=0., team=1,
                     alive=True, collision_shape=shape, mass=31000.,
                     contact_push_acks=[], fitting=dict(crew_level=75))
        battle._records['bot:11'] = dict(engine_id=11, network_id=11,
            kind='bot', local=False, ready=True, state=state, presented_pose=dict(state))
        expected = vehicle_physics.derive_params(descriptor, factors=factors)
        self.assertEqual(expected, replica_physics.contact_params(state, descriptor))
        bodies = battle._contact_tanks((0.,0.,0.), shape, .04)
        self.assertEqual(1, len(bodies))
        self.assertEqual(31000., bodies[0]['mass'])
        self.assertIsNotNone(bodies[0]['contact_decel'])
        self.assertEqual(expected, battle._records['bot:11']['_contact_parameters'][1])
        self.assertTrue(battle._remember_ram_bot_snapshot(dict(bots=[state],
            bot_state_revision=1, bot_state_time_us=1000000)))
        battle._estimated_motion_time_us = lambda unused: 1100000
        with mock.patch.object(vehicle_physics, 'predict_contact_velocity',
                return_value=(.1, .2, .3)) as predict:
            result = battle._predict_bot_contact_velocity(11, state, shape, expected)
        self.assertEqual((.1, .2, .3), result)
        predict.assert_called_once()

    def test_shared_consumable_decision_uses_player_native_equipment_executor(self):
        from test_player_control_completion import CanonicalConsumableCompletionTests
        import test_port_0922_consumable_audit as consumables
        completion = CanonicalConsumableCompletionTests()
        self.addCleanup(completion.doCleanups)
        mounted = consumables.item('smallRepairkit', 4, tags=('repairkit',),
                                    reuseCount=-1, cooldownSeconds=90)
        unused, battle, player, entity, owner, control, sent, restore = completion.setup_equipment(mounted)
        critical = dict(devices=[dict(name='gunHealth', hp=0, max_hp=100, state='destroyed'),
                                dict(name='leftTrackHealth', hp=0, max_hp=100, state='destroyed')],
                        destroyed=['gunHealth', 'leftTrackHealth'],
                        crew_ko=['driver', 'loader1'])
        player.effective_params['critical']['devices'].extend([
            dict(name='gunHealth', max_hp=100, regen_hp=50),
            dict(name='leftTrackHealth', max_hp=100, regen_hp=50)])
        player.effective_params['critical']['activation_targets'] = [
            dict(index=82, name='gunHealth'), dict(index=83, name='leftTrackHealth')]
        player.critical = copy.deepcopy(critical)
        owner._records['player:1']['critical_state'] = critical
        entity.typeDescriptor.extras = {82: types.SimpleNamespace(name='gunHealth'),
                                       83: types.SimpleNamespace(name='leftTrackHealth')}
        before = copy.deepcopy(critical)
        engine = control.runtime.engine
        self.assertIsInstance(engine, fixture.bot_runtime.BotRuntime)
        self.assertNotIn('_poll_bot_equipments', type(engine).__dict__)
        shared_poll = fixture.bot_runtime.BotRuntime._poll_bot_equipments
        with mock.patch.object(fixture.bot_runtime.BotRuntime, '_poll_bot_equipments',
                autospec=True, side_effect=shared_poll) as poll, \
                mock.patch.object(fixture.bot_runtime.BotRuntime, '_apply_bot_equipment_effect',
                side_effect=AssertionError('player used Bot physical equipment executor')):
            completion.poll_equipment(control)
            self.assertFalse(sent)
            completion.poll_equipment(control)
        self.assertGreaterEqual(poll.call_count, 2)
        self.assertTrue(all(call[0][0] is engine for call in poll.call_args_list))
        self.assertEqual('gunHealth', sent[0]['selected'])
        self.assertTrue(player.equipment_intent_result['accepted'])
        self.assertNotIn('gunHealth', player.critical['destroyed'])
        self.assertIn('leftTrackHealth', player.critical['destroyed'])
        self.assertEqual(before, critical)

    def test_local_critical_factors_do_not_call_bot_fitting_readers(self):
        from gui.mods.offline_lan_0922 import bot_fittings
        battle = fixture.BattleRuntime(fixture._runtime())
        descriptor = fixture._Descriptor()
        factors = fixture._plain_bot_factors(descriptor, crew_level=75)
        factors['offline/engine_fire_factor'] = .63
        vehicle_fitting_context.register(descriptor, dict(
            wire=dict(crew_level=75), crew_roster=(),
            factors={(id(descriptor), (), False, ()): factors}))
        self.addCleanup(vehicle_fitting_context.clear)
        entity = fixture._Vehicle(7, descriptor, fixture._Vector(0., 0., 0.),
                                  (0., 0., 0.), {'health': 500})
        record = dict(local=True, kind='player', state={})
        with mock.patch.object(bot_fittings, 'context',
                side_effect=AssertionError('player used Bot fitting context')), \
                mock.patch.object(bot_fittings, 'battle_factors',
                side_effect=AssertionError('player used Bot battle factors')):
            self.assertTrue(battle._install_critical_equipment_effects(record, entity))
        self.assertEqual(.63, entity._fire_starting_chance_factor)

    def test_actor_neutral_support_pose_keeps_player_identity(self):
        raw = dict(id=2, x=1., y=2., z=3., yaw=.4, pitch=.2, roll=-.1,
                   suspension_pitch=.05)
        before = dict(raw)
        pose = vehicle_physics.collision_state_pose(raw, actor_key='player:2')
        self.assertEqual('player:2', pose['actor_key'])
        self.assertEqual('player:2', pose['chassis']['actor_key'])
        self.assertAlmostEqual(.15, pose['chassis']['pitch'])
        self.assertEqual(before, raw)
        for yaw in (-math.pi, -.4, 0., .8, math.pi):
            p, r = vehicle_physics.ground_pose_for_yaw(.2, -.1, 0., yaw)
            p, r = vehicle_physics.ground_pose_for_yaw(p, r, yaw, 0.)
            self.assertAlmostEqual(.2, p)
            self.assertAlmostEqual(-.1, r)


if __name__ == '__main__':
    unittest.main()
