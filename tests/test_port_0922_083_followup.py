"""Regression cases reported against the published 0.8.3 build."""
import copy
import sys
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixtures
from test_port_0922_battle_runtime import _runtime
from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime
from gui.mods.offline_lan_0922.entities.native_remote_vehicle import set_engine_audible
from gui.mods.offline_lan_0922.account_rpc import data, economy
from test_port_0922_garage import SNAPSHOT
import test_port_0922_server_projectiles as projectile_fixtures
from gui.mods.offline_lan_0922 import (
    stun_mechanics, descriptor_donation, effective_params, lan_client,
    bot_runtime, critical_damage)


def stun_shell():
    return dict(stunRadius=8.0, stunDuration=20.0, stunFactor=1.0,
                guaranteedStunDuration=0.5, damageDurationCoeff=0.5,
                guaranteedStunEffect=0.75, damageEffectCoeff=0.25)


def stun_config():
    result = {name: (1.5 if stat in stun_mechanics.INCREASING_STATS else 0.8)
              for stat, name in stun_mechanics.STAT_CONFIG.items()}
    result['minStunDuration'] = 5.0
    return result


class Gameplay083Tests(unittest.TestCase):
    def test_he_hp_damage_selects_explosion_without_changing_penetration(self):
        fixture = fixtures.BattleRuntimeContractTests()
        for kind, result, damage, expected in (
                ('HIGH_EXPLOSIVE', 1, 100, 'hitFx'),
                ('HIGH_EXPLOSIVE', 2, 100, 'hitFx'),
                ('HIGH_EXPLOSIVE', 1, 0, 'resistedFx'),
                ('HIGH_EXPLOSIVE', 2, 0, 'resistedFx'),
                ('ARMOR_PIERCING', 1, 0, 'resistedFx'),
                ('ARMOR_PIERCING', 0, 0, 'ricochetFx')):
            with self.subTest(kind=kind, result=result, damage=damage):
                battle, target, attacker = fixture._blocked_hit_fixture(kind)
                event = dict(kind='bot_human_hit', world_pose=True, x=.5,
                             y=1., z=0., shell_index=0, shot_result=result,
                             damage=damage, source='shot', dead=False,
                             attack_reason=0, death_reason=0)
                self.assertTrue(battle._present_combat_hit(event, target, attacker, 11))
                self.assertEqual(expected, battle._avatar.terrainEffects.addNew.call_args.args[1])
                self.assertEqual(result, event['shot_result'])

    def test_live_and_default_shop_publish_the_price_that_the_account_charges(self):
        for mode in (economy.CAREER_DEVICE_REMOVAL, economy.SANDBOX_DEVICE_REMOVAL):
            snapshot = copy.deepcopy(SNAPSHOT)
            snapshot['deviceRemovalCost'] = dict(mode)
            shop = data.shop(selected_vehicle=snapshot)
            self.assertEqual({'gold': 10}, shop['paidRemovalCost'])
            self.assertEqual(shop['paidRemovalCost'], shop['defaults']['paidRemovalCost'])
            self.assertEqual({'crystal': 200}, shop['paidDeluxeRemovalCost'])

    def test_hidden_sound_owner_is_removed_and_reused_once_on_reveal(self):
        audition = types.SimpleNamespace(attachToModel=mock.Mock())
        detailed = types.SimpleNamespace(onEngineStart=object(), onStateChanged=object())
        links = detailed.onEngineStart, detailed.onStateChanged
        appearance = types.SimpleNamespace(engineAudition=audition,
                                           detailedEngineState=detailed,
                                           compoundModel=object())
        vehicle = types.SimpleNamespace(appearance=appearance, isAlive=lambda: True)
        self.assertTrue(set_engine_audible(vehicle, False))
        self.assertIsNone(appearance.engineAudition)
        self.assertIsNone(detailed.onEngineStart)
        self.assertTrue(set_engine_audible(vehicle, False))
        self.assertTrue(set_engine_audible(vehicle, True))
        self.assertIs(audition, appearance.engineAudition)
        self.assertEqual(links, (detailed.onEngineStart, detailed.onStateChanged))
        self.assertFalse(set_engine_audible(vehicle, True))
        audition.attachToModel.assert_called_once_with(appearance.compoundModel)
        set_engine_audible(vehicle, False)
        vehicle.isAlive = lambda: False
        self.assertFalse(set_engine_audible(vehicle, True))
        self.assertIsNone(appearance.engineAudition)

    def test_native_stun_component_survives_all_frozen_shot_boundaries(self):
        shot = types.SimpleNamespace(
            speed=720.0, gravity=9.81, maxDistance=1000.0,
            piercingPower=(53.0, 53.0),
            shell=types.SimpleNamespace(
                type=types.SimpleNamespace(name='HIGH_EXPLOSIVE', explosionRadius=8.0),
                caliber=155.0, damage=(1000.0, 150.0),
                stun=types.SimpleNamespace(**stun_shell())))
        projected = descriptor_donation.project_shot(shot)
        for canonicalize in (
                lan_client._strict_projectile_source_shot,
                effective_params._canonical_source_shot,
                projectile_fixtures._projectile_source_shot):
            self.assertEqual(stun_shell(), canonicalize(projected)['shell']['stun'])
        projected['shell']['stun']['stunDuration'] = float('nan')
        self.assertIsNone(lan_client._strict_projectile_source_shot(projected))

    def test_zero_hp_he_can_stun_and_resistance_reduces_duration(self):
        shell = dict(kind='HIGH_EXPLOSIVE', damage=[1000, 150], stun=stun_shell())
        duration, factors = stun_mechanics.impact(shell, 0, 8.0, stun_config())
        self.assertEqual(10.0, duration)
        self.assertLess(factors['vision'], 1.0)
        self.assertGreater(factors['reload'], 1.0)
        protected = stun_mechanics.impact(
            shell, 0, 1.0, stun_config(), {'stunResistanceDuration': 0.1})
        self.assertEqual(9.0, protected[0])
        self.assertIsNone(stun_mechanics.impact(shell, 1000, 8.01, stun_config()))
        self.assertIsNone(stun_mechanics.impact(
            dict(shell, kind='ARMOR_PIERCING'), 1000, 0, stun_config()))

    def test_worker_generates_stun_and_server_expires_its_stat_effects(self):
        state = projectile_fixtures._state()
        launch = projectile_fixtures._launch(is_he=True, splash_radius=8.0)
        launch['source_shot']['shell']['stun'] = stun_shell()
        self.assertTrue(projectile_fixtures._launch_authority(state, launch))
        now = state._server_time_ms()
        battle = BattleRuntime(_runtime())
        battle._config = {}
        battle._turret_server_time_ms = lambda unused: now
        effect = projectile_fixtures._effect(damage=0, shot_result=1)
        target = types.SimpleNamespace(typeDescriptor={'miscAttrs': {}})
        native = types.ModuleType('items.stun')
        native.g_cfg = stun_config()
        with mock.patch.dict(sys.modules, {'items.stun': native}):
            self.assertTrue(battle._projectile_stun_effect(
                effect, launch['source_shot'], {}, target, {'cursor_time': 1.0}, 0.0))
        self.assertIsNotNone(lan_client._strict_projectile_effect(effect))
        self.assertTrue(state.resolve_projectile(
            projectile_fixtures.SIMULATION_WORKER_AUTHORITY_ID,
            projectile_fixtures._resolve('1:p:1:1', direct=effect)))
        victim = state.players[2]
        self.assertEqual(effect['stun_factors'], victim.stun_factors)
        self.assertEqual(effect['stun_factors'], state._public_player(victim)['stun_factors'])
        self.assertEqual(1, state._expire_stuns(effect['stun_end_server_time_ms']))
        self.assertEqual({}, victim.stun_factors)

    def test_elapsed_stun_does_not_discard_late_valid_hp_damage(self):
        state = projectile_fixtures._state()
        self.assertTrue(projectile_fixtures._launch_authority(state, projectile_fixtures._launch()))
        victim = state.players[2]
        health = victim.health
        self.assertTrue(state.resolve_projectile(
            projectile_fixtures.SIMULATION_WORKER_AUTHORITY_ID,
            projectile_fixtures._resolve('1:p:1:1', direct=projectile_fixtures._effect(
                stun_end_server_time_ms=1))))
        self.assertEqual(health - 100, victim.health)
        self.assertEqual(0, victim.stun_end_server_time_ms)

    def test_stun_factors_survive_bot_combat_restore_and_affect_player_stats(self):
        factors = stun_mechanics.impact(
            dict(kind='HIGH_EXPLOSIVE', damage=[1000, 150], stun=stun_shell()),
            0, 0, stun_config())[1]
        state = dict(health=100, max_health=100, alive=True,
                     stun_end_server_time_ms=5000, stun_factors=factors)
        record = bot_runtime._combat_record(state)
        restored = dict(max_health=100)
        bot_runtime._apply_combat_record(restored, record)
        self.assertEqual(factors['reload'], stun_mechanics.factor(restored, 'reload'))
        vehicle = types.SimpleNamespace(_offlineStunFactors=factors)
        with mock.patch.object(critical_damage, '_crew_factor', return_value=1.0), \
                mock.patch.object(critical_damage, '_module_factor', return_value=1.0):
            self.assertEqual(factors['reload'], critical_damage.stat_factor(vehicle, 'reload'))
        record['stun_end_server_time_ms'] = 0
        bot_runtime._apply_combat_record(restored, record)
        self.assertEqual({}, restored['stun_factors'])
        self.assertEqual(1.0, stun_mechanics.factor(restored, 'reload'))


if __name__ == '__main__':
    unittest.main()
