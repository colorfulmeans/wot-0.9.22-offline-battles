"""Reconstructed landing loads and physical-to-critical adapter regressions."""
import copy
from pathlib import Path
import random
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import critical_damage, impact_damage, vehicle_physics
import test_port_0922_critical_damage as critical_fixture
import test_port_0922_battle_runtime as battle_fixture
import test_port_0922_bot_runtime as bot_fixture


class LandingTrackDamageTests(unittest.TestCase):
    @staticmethod
    def vehicle():
        return types.SimpleNamespace(
            id=1, health=1000, typeDescriptor=critical_fixture._descriptor(),
            devices_hp={'leftTrackHealth': 100.0, 'rightTrackHealth': 100.0,
                        'engineHealth': 80.0},
            _destroyed_devices=set(), _critical_devices={'engineHealth'},
            _crew_ko={'loader1'}, is_on_fire=False, _ammo_rack_death=False,
            _offline_proposal_only=True)

    def test_same_budget_breaks_single_track_but_splits_on_two_tracks(self):
        single, balanced = self.vehicle(), self.vehicle()
        one = critical_damage.apply_landing_tracks(single, 150.0, (1.0, 0.0))
        two = critical_damage.apply_landing_tracks(balanced, 150.0, (0.5, 0.5))
        self.assertEqual({'leftTrackHealth'}, single._destroyed_devices)
        self.assertEqual(100.0, single.devices_hp['rightTrackHealth'])
        self.assertEqual(25.0, balanced.devices_hp['leftTrackHealth'])
        self.assertEqual(25.0, balanced.devices_hp['rightTrackHealth'])
        self.assertEqual(set(), balanced._destroyed_devices)
        self.assertTrue(all(event['cause'] == 'world_collision'
                            for event in one['events'] + two['events']))
        self.assertEqual(80.0, single.devices_hp['engineHealth'])
        self.assertEqual({'loader1'}, single._crew_ko)

    def test_safe_speed_or_unproved_contacts_never_spend_module_hp(self):
        for speed, loads in ((vehicle_physics.FALL_SAFE_SPEED, (1.0, 0.0)),
                             (20.0, None), (20.0, (0.0, 0.0))):
            vehicle = self.vehicle()
            before = dict(vehicle.devices_hp)
            budget = vehicle_physics.fall_damage(1000, speed)
            self.assertIsNone(critical_damage.apply_landing_tracks(
                vehicle, budget, loads))
            self.assertEqual(before, vehicle.devices_hp)

    def test_another_impact_restarts_the_destroyed_track_repair_pool(self):
        vehicle = self.vehicle()
        vehicle.devices_hp['leftTrackHealth'] = 40.0
        vehicle._destroyed_devices = {'leftTrackHealth'}
        critical_damage.apply_landing_tracks(vehicle, 20.0, (1.0, 0.0))
        self.assertEqual(0.0, vehicle.devices_hp['leftTrackHealth'])
        self.assertEqual({'leftTrackHealth'}, vehicle._destroyed_devices)

    def test_belly_share_does_not_get_redistributed_to_the_tracks(self):
        self.assertEqual([('leftTrackHealth', 30.0), ('rightTrackHealth', 60.0)],
                         impact_damage.track_losses(150.0, (0.2, 0.4),
                             {'leftTrackHealth': 100, 'rightTrackHealth': 100}))

    def test_invalid_loads_are_rejected_without_partial_damage(self):
        for loads in ((True, 0.0), (10 ** 400, 0), (0.6, 0.6),
                      (float('nan'), 0.0), (-0.1, 1.0), 'left'):
            vehicle = self.vehicle()
            with self.assertRaises(ValueError):
                critical_damage.apply_landing_tracks(vehicle, 150, loads)
            self.assertEqual(100.0, vehicle.devices_hp['leftTrackHealth'])

    def test_player_queues_loads_without_changing_hp_or_modules(self):
        runtime = battle_fixture._runtime()
        battle = battle_fixture.BattleRuntime(runtime)
        entity = battle_fixture._Vehicle(
            10, battle_fixture._Descriptor(), battle_fixture._Vector(),
            (0, 0, 0), {'health': 500})
        battle._apply_landing_impact(entity, 20.0, True, (0.75, 0.0))
        self.assertEqual(500, entity.health)
        self.assertEqual([{'impact_speed': 20.0, 'track_loads': (0.75, 0.0)}],
                         battle._pending_landing_impacts)
        battle._sender = types.SimpleNamespace(send_current=lambda: True)
        battle.client = types.SimpleNamespace(send_landing_observation=mock.Mock(
            return_value=1))
        self.assertTrue(battle._flush_landing_observation())
        battle.client.send_landing_observation.assert_called_once_with(
            20.0, (0.75, 0.0))


class LandingCrewDamageTests(unittest.TestCase):
    ROSTER = ('commander', 'driver', 'gunner1', 'loader1', 'loader2', 'radioman1')

    def test_budget_uses_full_health_and_real_seats_without_rounding_up(self):
        for budget, maximum, expected in ((166, 1000, 0), (167, 1000, 1),
                                           (359, 1000, 2), (359, 1780, 1)):
            casualties = impact_damage.crew_casualties(
                budget, maximum, self.ROSTER, rng=random.Random(130449))
            self.assertEqual(expected, len(casualties))
            self.assertTrue(set(casualties).issubset(self.ROSTER))

    def test_first_impact_can_hit_every_real_seat_instead_of_always_commander(self):
        rng = random.Random(130449)
        casualties = [impact_damage.crew_casualties(
            359, 1780, self.ROSTER, rng=rng)[0] for unused in range(60)]
        self.assertEqual(set(self.ROSTER), set(casualties))

    def test_numbered_seats_are_sampled_once_and_existing_injuries_are_excluded(self):
        rng = mock.Mock()
        rng.sample.return_value = ['loader2', 'radioman1']
        self.assertEqual(['loader2', 'radioman1'], impact_damage.crew_casualties(
            400, 1000, self.ROSTER, ('gunner1',), rng=rng))
        rng.sample.assert_called_once_with(
            ['commander', 'driver', 'loader1', 'loader2', 'radioman1'], 2)
        # A real RNG must also never duplicate seats, even when the budget
        # exceeds the remaining healthy crew.
        result = impact_damage.crew_casualties(
            1000, 1000, self.ROSTER, ('gunner1',), rng=random.Random(130449))
        self.assertEqual(set(self.ROSTER) - {'gunner1'}, set(result))
        self.assertEqual(len(result), len(set(result)))
        self.assertEqual([], impact_damage.crew_casualties(
            1000, 1000, self.ROSTER, self.ROSTER))
        self.assertEqual([], impact_damage.crew_casualties(1000, 1000, ()))

    def test_safe_and_unmeasured_landings_do_not_injure_crew(self):
        for budget, loads in ((0, (1, 0)), (0, (0, 0)), (500, None)):
            vehicle = LandingTrackDamageTests.vehicle()
            before = copy.deepcopy(critical_damage._state(vehicle))
            self.assertIsNone(critical_damage.apply_landing_damage(
                vehicle, budget, loads, 1000, self.ROSTER))
            self.assertEqual(before, critical_damage._state(vehicle))

    def test_belly_impact_injures_combined_role_seat_without_inventing_modules(self):
        vehicle = LandingTrackDamageTests.vehicle()
        vehicle.typeDescriptor.type.crewRoles = (
            ('commander', 'gunner', 'loader'), ('driver',))
        vehicle._crew_ko = set()
        before = dict(vehicle.devices_hp)
        payload = critical_damage.apply_landing_damage(
            vehicle, 600, (0, 0), 1000, ('commander', 'driver'),
            rng=types.SimpleNamespace(sample=lambda seats, count: seats[:count]))
        self.assertEqual(before, vehicle.devices_hp)
        self.assertEqual({'commander'}, vehicle._crew_ko)
        self.assertEqual(frozenset(('commander', 'gunner', 'loader')),
                         vehicle._crew_impaired)
        self.assertEqual(['commander', 'driver'], payload['crew_roster'])
        self.assertEqual([{'kind': 'crew', 'name': 'commander',
                           'state': 'destroyed', 'cause': 'world_collision'}],
                         payload['events'])
        self.assertFalse(payload['fire'])
        self.assertFalse(payload['ammo_rack_death'])


class BotLandingDamageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = bot_fixture.BotRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.runtime, self.state, unused = self.fixture._suspension_case(
            lambda unused_x, unused_z: 0.0)
        self.state.update(health=1000, max_health=1000, alive=True,
                          critical={'crew_roster': ['commander', 'driver'],
                                    'crew_ko': [], 'devices': []})
        self.suspension_descriptor = self.runtime._descriptors[self.state['id']]
        self.runtime._descriptors[self.state['id']] = critical_fixture._descriptor()

    def test_bot_landing_commits_track_state_and_preserves_real_crew_roster(self):
        damage = self.runtime._apply_bot_fall_damage(self.state, 15.0, (1.0, 0.0))
        self.assertEqual(150, damage)
        self.assertEqual(850, self.state['health'])
        self.assertEqual(['leftTrackHealth'], self.state['critical']['destroyed'])
        self.assertEqual(['commander', 'driver'],
                         self.state['critical']['crew_roster'])
        self.assertEqual([], self.state['critical']['crew_ko'])

    def test_bot_turret_sweep_stages_contact_loads_without_early_damage(self):
        pending = []
        self.runtime._turret_pending_landing_impacts = pending
        self.runtime._apply_bot_landing_impact(self.state, 15.0, True, (0.0, 1.0))
        self.assertEqual([(15.0, True, (0.0, 1.0))], pending)
        self.assertEqual(1000, self.state['health'])
        self.assertEqual([], self.state['critical']['devices'])
        self.runtime._turret_pending_landing_impacts = None
        self.runtime._apply_bot_landing_impact(self.state, *pending[0])
        self.assertEqual(['rightTrackHealth'], self.state['critical']['destroyed'])

    def test_human_and_bot_landings_share_hp_tracks_and_numbered_crew_law(self):
        import test_port_0922_landing_critical as landing_fixture
        from gui.mods.offline_lan_0922 import player_critical_mechanics

        descriptor = self.runtime._descriptors[self.state['id']]
        descriptor.type.crewRoles = (
            ('commander',), ('driver',), ('gunner',), ('loader',),
            ('loader',), ('radioman',))
        roster = list(LandingCrewDamageTests.ROSTER)
        self.state['critical']['crew_roster'] = roster
        human = landing_fixture.LandingCriticalServerTests()
        human.setUp()
        human.player.max_health = human.player.health = 1000
        human.player.effective_params['critical'] = \
            player_critical_mechanics.project_profile(descriptor)
        sample_patch = mock.patch.object(
            impact_damage.random, 'sample',
            side_effect=lambda seats, count: seats[-count:])
        sample_patch.start()
        self.addCleanup(sample_patch.stop)
        for unused_index in range(2):
            human.next_input()
            self.assertTrue(human.submit(human.observation((0.2, 0.1))))
            self.runtime._apply_bot_fall_damage(self.state, 20, (0.2, 0.1))
            self.assertEqual(human.player.health, self.state['health'])
            self.assertEqual(human.player.alive, self.state['alive'])
            for key in ('crew_ko', 'crew_roster', 'devices', 'destroyed', 'fire'):
                self.assertEqual(human.player.critical[key],
                                 self.state['critical'][key], key)
        self.assertEqual(['loader2', 'radioman1'], self.state['critical']['crew_ko'])

    def test_last_bot_crew_landing_death_retains_hull_health(self):
        descriptor = self.runtime._descriptors[self.state['id']]
        descriptor.type.crewRoles = (('commander', 'gunner'), ('driver',))
        self.state['critical']['crew_ko'] = ['commander']
        damage = self.runtime._apply_bot_fall_damage(self.state, 30, (0, 0))
        self.assertEqual(600, damage)
        self.assertEqual((400, 400, False, 3), (
            self.state['health'], self.state['display_health'],
            self.state['alive'], self.state['death_reason']))
        self.assertEqual(['commander', 'driver'], self.state['critical']['crew_ko'])
        self.assertEqual(0, self.state['speed'])

    def test_supported_compression_does_not_submit_a_landing(self):
        self.runtime._descriptors[self.state['id']] = self.suspension_descriptor
        self.state.update(airborne=False, vertical_speed=-1.0)
        self.runtime._apply_bot_landing_impact = mock.Mock()
        self.assertFalse(self.runtime._update_vertical_motion(self.state, 0.03))
        self.runtime._apply_bot_landing_impact.assert_not_called()
        self.assertEqual(1000, self.state['health'])
        self.assertEqual([], self.state['critical']['devices'])
