"""Equipment effects must reach damage/perception, not just the fitting UI."""
import contextlib
import io
import types
import unittest
from unittest import mock

import test_port_0922_critical_damage as critical_fixture
from test_port_0922_server_projectiles import _state, _update_player_input
from gui.mods.offline_lan_0922 import bot_fittings, bot_runtime, crew_battle
from gui.mods.offline_lan_0922 import critical_damage, device_damage, effective_params as wire
from gui.mods.offline_lan_0922 import environment_modules, loadout, player_critical_mechanics


class EquipmentSkillEffectsTests(unittest.TestCase):
    def test_native_bot_perception_receives_relay_designated_and_last_effort(self):
        from gui.mods.offline_lan_0922.native_control_core import NativeControl
        descriptor = critical_fixture._descriptor()
        profile = dict(invisibility_moving=(0, 1), invisibility_still=(0, 1),
                       has_camouflage_net=False)
        owner = object.__new__(NativeControl)
        owner.runtime = types.SimpleNamespace(_descriptors={1: descriptor},
            _vision_ranges={1: (330, 330, None)},
            _spotting_profile=lambda source, tick: ((0.1, 0.1), 1.0, profile),
            _source_radio_range=lambda source, tick: 700)
        source = dict(id=1, kind='bot', critical={})
        with mock.patch.object(bot_fittings, 'skill_count', return_value=1), \
                mock.patch.object(bot_fittings, 'skill_level', return_value=100), \
                mock.patch.object(bot_runtime, '_critical_factor', return_value=1.0):
            values, last, designated = owner._project_actor_config(source, 1)
        self.assertTrue(last)
        self.assertTrue(designated)
        self.assertEqual(0.1, values[16])
        self.assertEqual(bot_runtime.spotting.SPOT_MEMORY_SECONDS + 2, values[17])
        self.assertEqual(2, values[18])

    def test_bot_controlled_impact_reads_living_driver_and_keeps_liner_factor(self):
        descriptor = critical_fixture._descriptor()
        descriptor.miscAttrs['antifragmentationLiningFactor'] = 1.3
        for level in (0, 50, 100):
            with mock.patch.object(bot_fittings, 'skill_level', return_value=level):
                profile = bot_runtime._bot_ram_profile(descriptor, {'crew_ko': []})
            self.assertAlmostEqual(level * 0.0015, profile['ramming_bonus'])
            self.assertEqual(1.3, profile['spall_coefficient'])

    def test_bot_shot_freezes_deadeye_from_current_carrier_state(self):
        for count in (0, 1):
            with mock.patch.object(bot_fittings, 'skill_count', return_value=count), \
                    mock.patch('gui.mods.offline_lan_0922.descriptor_donation.project_shot') as project:
                bot_fittings.project_shot(object(), {'shell': {}}, {'crew_ko': ['gunner']})
            self.assertEqual(bool(count), project.call_args.kwargs['deadeye'])

    def test_liner_changes_the_real_crew_roll_for_shots_and_explosions(self):
        scene = critical_fixture.CriticalDamageTests()
        scene.setUp()
        for explosion in (False, True):
            for factor, injured in ((1.0, True), (0.8, True), (0.75, False),
                                    (0.7, False), (0.5, False)):
                descriptor = critical_fixture._descriptor()
                descriptor.miscAttrs['crewChanceToHitFactor'] = factor
                target = types.SimpleNamespace(id=999, health=500,
                    typeDescriptor=descriptor, position=object(), matrix=object(),
                    getComponents=lambda: ())
                collision = (1.0, 1.0, critical_fixture._Material(
                    'commanderHealth', chance=0.4), None)
                with mock.patch.dict('sys.modules', {'BigWorld': scene.bigworld, 'Math': scene.math}), \
                        mock.patch('random.uniform', return_value=5000.0), \
                        mock.patch('random.random', return_value=0.31) as roll, \
                        contextlib.redirect_stdout(io.StringIO()):
                    damage, payload, delta = critical_damage.propose_direct(
                        target, (collision,), object(), object(), 100,
                        {'kind': 'ARMOR_PIERCING', 'damage': (100, 5000)}, 2,
                        penetrated=True, by_explosion=explosion, with_delta=True)
                self.assertEqual(injured, 'commander' in delta['crew_ko'])
                roll.assert_called_once()

    def test_intuition_keeps_reload_progress_and_inventory_and_does_not_reroll(self):
        descriptor = critical_fixture._descriptor()
        gun = types.SimpleNamespace(clip_size=1, burst_count=1,
            elapsed=4.0, reload_duration=10.0, shell_index=lambda value: value)
        ammo = object.__new__(bot_runtime._BotAmmoState)
        ammo.shell_count = 2
        ammo.categories = {0: 'standard', 1: 'premium'}
        ammo.remaining, ammo.loaded, ammo.next = [5, 7], 0, 0
        ammo.plan_pending, ammo.reload_pending = False, True
        burst = types.SimpleNamespace(active=False)
        with mock.patch.object(bot_fittings, 'skill_count', return_value=2), \
                mock.patch.object(bot_runtime.random, 'random', return_value=0.1) as roll:
            self.assertTrue(bot_runtime._bot_intuition({}, descriptor, gun, ammo, burst, 1))
            self.assertFalse(bot_runtime._bot_intuition({}, descriptor, gun, ammo, burst, 1))
        roll.assert_called_once()
        self.assertEqual([5, 7], ammo.remaining)
        self.assertEqual((1, 1, True), (ammo.loaded, ammo.next, ammo.reload_pending))
        self.assertEqual((4.0, 10.0), (gun.elapsed, gun.reload_duration))

    def test_intuition_does_not_roll_for_magazines_bursts_or_initial_loading(self):
        gun = types.SimpleNamespace(clip_size=2, burst_count=1)
        ammo = types.SimpleNamespace(plan_pending=False)
        burst = types.SimpleNamespace(active=False)
        with mock.patch.object(bot_fittings, 'skill_count') as count:
            self.assertFalse(bot_runtime._bot_intuition({}, None, gun, ammo, burst, 1))
            gun.clip_size, gun.burst_count = 1, 2
            self.assertFalse(bot_runtime._bot_intuition({}, None, gun, ammo, burst, 1))
            gun.burst_count, ammo.plan_pending = 1, True
            self.assertFalse(bot_runtime._bot_intuition({}, None, gun, ammo, burst, 1))
        count.assert_not_called()

    def test_all_four_liners_preserve_native_crew_protection_in_player_handoff(self):
        for protection in (0.8, 0.75, 0.7, 0.5):
            descriptor = critical_fixture._strict_1513_descriptor()
            descriptor.miscAttrs.crewChanceToHitFactor = protection
            profile = player_critical_mechanics.project_profile(descriptor)
            canonical = wire._canonical_critical(profile)
            restored = player_critical_mechanics.descriptor_from_profile(canonical)
            self.assertEqual(protection, device_damage._misc_factor(
                restored, 'crewChanceToHitFactor'))

    def test_protection_wire_rejects_invalid_values_and_does_not_alias(self):
        profile = player_critical_mechanics.project_profile(
            critical_fixture._strict_1513_descriptor())
        canonical = wire._canonical_critical(profile)
        profile['protection']['crewChanceToHitFactor'] = 0.5
        self.assertEqual(1.0, canonical['protection']['crewChanceToHitFactor'])
        for bad in (True, -0.1, 1.1, float('inf'), float('nan')):
            profile['protection']['crewChanceToHitFactor'] = bad
            self.assertIsNone(wire._canonical_critical(profile))

    def test_suspension_reduces_only_proved_track_transmitted_hull_loss(self):
        descriptor = critical_fixture._strict_1513_descriptor()
        descriptor.miscAttrs.vehicleByChassisDamageFactor = 0.5
        for name in ('leftTrackHealth', 'rightTrackHealth'):
            self.assertEqual(150, environment_modules.suspension_hull_damage(
                300, descriptor, [dict(name=name, weight=1.0)], (0, 1, 0)))
        for contacts in ([], [dict(name='gunHealth', weight=1.0)],
                         [dict(name='engineHealth', weight=1.0)]):
            self.assertEqual(300, environment_modules.suspension_hull_damage(
                300, descriptor, contacts, (0, 1, 0)))
        for normal in (None, (0, -1, 0), (1, 0, 0)):
            self.assertEqual(300, environment_modules.suspension_hull_damage(
                300, descriptor, [dict(name='leftTrackHealth', weight=1.0)], normal))

    def test_server_landing_uses_installed_suspension_once_and_deduplicates(self):
        state = _state()
        player = state.players[1]
        descriptor = critical_fixture._strict_1513_descriptor()
        descriptor.miscAttrs.vehicleByChassisDamageFactor = 0.5
        player.effective_params['critical'] = player_critical_mechanics.project_profile(descriptor)
        self.assertTrue(_update_player_input(state, 1, up_cosine=1.0))
        message = dict(type='landing_observation', round_id=1,
            authority_epoch=state.authority_epoch, observation_seq=1,
            input_seq=player.input_seq, impact_speed=20.0,
            contact_normal=[0, 1, 0],
            module_contacts=[dict(name='leftTrackHealth', weight=1.0)])
        before = player.health
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(state.submit_landing_observation(1, message))
        expected = int(round(player.max_health * 0.3 * 0.5))
        self.assertEqual(expected, before - player.health)
        hp = player.health
        state.submit_landing_observation(1, message)
        self.assertEqual(hp, player.health)

    def test_recon_uses_native_destroyed_coefficient_without_double_normal_bonus(self):
        original = mock.Mock()
        crew = types.SimpleNamespace(_skillProcessors={'commander_eagleEye': original})
        factors = loadout._collect_battle_crew_factors(crew)
        config = types.SimpleNamespace(distanceFactorPerLevelWhenDeviceWorking=0.0002,
                                      distanceFactorPerLevelWhenDeviceDestroyed=0.002)
        crew._skillProcessors['commander_eagleEye'](crew, 0, 100, 10, True, False, config)
        original.assert_called_once()
        ratio = crew_battle.from_native(factors)['damaged_optics_recon_ratio']
        self.assertAlmostEqual(1.22 / 1.022, ratio)
        descriptor = critical_fixture._strict_1513_descriptor()
        self.assertEqual(1.0, device_damage.module_stat_factor(
            {}, set(), descriptor, 'vision', damaged_optics_recon_ratio=ratio))
        self.assertAlmostEqual(0.25 * ratio, device_damage.module_stat_factor(
            {}, {'surveyingDeviceHealth'}, descriptor, 'vision',
            damaged_optics_recon_ratio=ratio))
        self.assertEqual(0.5, device_damage.module_stat_factor(
            {'surveyingDeviceHealth': 40}, set(), descriptor, 'vision',
            damaged_optics_recon_ratio=ratio))

    def test_injured_recon_does_not_donate_a_destroyed_optics_bonus(self):
        crew = types.SimpleNamespace(_skillProcessors={})
        factors = loadout._collect_battle_crew_factors(crew)
        crew._skillProcessors['commander_eagleEye'](
            crew, 0, 100, 0, False, False, types.SimpleNamespace())
        self.assertEqual(1.0, crew_battle.from_native(factors)['damaged_optics_recon_ratio'])

    def test_fire_directive_factor_survives_wire_without_claiming_a_retail_burn_law(self):
        factors = crew_battle.from_native({'healthBurnPerSecLossFraction': 1.215})
        self.assertEqual(1.215, crew_battle.canonical(factors)['fire_decay_factor'])
        target = types.SimpleNamespace(typeDescriptor=critical_fixture._strict_1513_descriptor(),
                                       id=1, actor_kind='player')
        with mock.patch('gui.mods.offline_lan_0922.native_input_diagnostics.validation_event') as emit:
            critical_damage.report_fire_model(target, factors['fire_decay_factor'])
        data = emit.call_args.kwargs
        self.assertTrue(data['skill_applied'])
        self.assertIsNone(data['native_health_burn_per_second'])
        self.assertEqual(1.215, data['native_decay_factor'])

    def test_fire_diagnostic_missing_target_never_enters_native_player_lookup(self):
        with mock.patch.object(critical_damage, '_device_td', side_effect=AssertionError('native lookup')), \
                mock.patch('gui.mods.offline_lan_0922.native_input_diagnostics.validation_event') as emit:
            critical_damage.report_fire_model(types.SimpleNamespace(), 0.57)
        self.assertIsNone(emit.call_args.kwargs['native_health_burn_per_second'])

    def test_bot_skill_projection_uses_physical_roles_and_surviving_carriers(self):
        descriptor = types.SimpleNamespace(type=types.SimpleNamespace(
            crewRoles=[('commander', 'radioman'), ('loader',), ('loader',)]))
        crew = [types.SimpleNamespace(skills=('radioman_retransmitter', 'gunner_sniper')),
                types.SimpleNamespace(skills=('loader_intuition',)),
                types.SimpleNamespace(skills=('loader_intuition',))]
        value = dict(crew=crew, crew_roster=('commander', 'loader', 'loader1'))
        items = types.ModuleType('items')
        items.tankmen = types.SimpleNamespace(TankmanDescr=lambda raw: raw)
        try:
            bot_fittings.register(descriptor, value)
            with mock.patch.dict('sys.modules', {'items': items}):
                self.assertEqual(2, bot_fittings.skill_count(descriptor, 'loader_intuition'))
                self.assertEqual(1, bot_fittings.skill_count(
                    descriptor, 'loader_intuition', {'crew_ko': ['loader']}))
                self.assertEqual(0, bot_fittings.skill_count(descriptor, 'gunner_sniper'))
                self.assertEqual(100, bot_fittings.skill_level(descriptor, 'radioman_retransmitter'))
                self.assertEqual(0, bot_fittings.skill_level(
                    descriptor, 'radioman_retransmitter', {'crew_ko': ['commander']}))
        finally:
            bot_fittings._CONTEXTS.pop(id(descriptor), None)


if __name__ == '__main__':
    unittest.main()
