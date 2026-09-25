"""Reconstructed landing loads and physical-to-critical adapter regressions."""
import copy
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import critical_damage, impact_damage, vehicle_physics
import test_port_0922_vehicle_physics as physics_fixture
import test_port_0922_critical_damage as critical_fixture
import test_port_0922_battle_runtime as battle_fixture
import test_port_0922_bot_runtime as bot_fixture


class ImpactLoadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = physics_fixture.VehiclePhysicsSuspensionTrialTests()
        self.fixture.setUp()
        self.params = self.fixture.params

    def solve(self, sides=('left', 'right'), height=0.0, speed=-20.0, dt=0.03):
        ground = tuple(0.0 if row['side'] in sides else None
                       for row in self.params['springs'])
        return vehicle_physics.damper_suspension_step(
            self.params, self.fixture._state(
                height=height, vertical_velocity=speed), ground, dt,
            (None,) * len(self.params['pseudo_contacts']))

    def test_balanced_track_contacts_share_the_load_equally(self):
        solved = self.solve()
        self.assertAlmostEqual(0.5, solved['impact_track_loads'][0])
        self.assertAlmostEqual(0.5, solved['impact_track_loads'][1])

    def test_single_track_contact_never_loads_the_airborne_track(self):
        for side, expected in (('left', (1.0, 0.0)),
                               ('right', (0.0, 1.0))):
            with self.subTest(side=side):
                self.assertEqual(expected, self.solve((side,))['impact_track_loads'])

    def test_final_substep_touch_records_only_the_contacted_track(self):
        solved = self.solve(('left',), height=1.1, speed=-9.5, dt=0.1)
        self.assertGreater(solved['contact_count'], 0)
        self.assertLess(solved['impact_speed'], -vehicle_physics.FALL_SAFE_SPEED)
        self.assertEqual((1.0, 0.0), solved['impact_track_loads'])

    def test_belly_contact_does_not_invent_track_load(self):
        pseudo = tuple(row['y'] + 0.02 if row['kind'] == 'body' else None
                       for row in self.params['pseudo_contacts'])
        solved = vehicle_physics.damper_suspension_step(
            self.params, self.fixture._state(vertical_velocity=-20.0),
            (None,) * len(self.params['springs']), 0.03, pseudo)
        self.assertGreater(solved['touched_contact_count'], 0)
        self.assertEqual((0.0, 0.0), solved['impact_track_loads'])

    def test_hull_load_reduces_the_budget_given_to_tracks(self):
        pseudo = tuple(row['y'] + 0.02 if row['kind'] == 'body' else None
                       for row in self.params['pseudo_contacts'])
        solved = vehicle_physics.damper_suspension_step(
            self.params, self.fixture._state(vertical_velocity=-20.0),
            (0.0,) * len(self.params['springs']), 0.03, pseudo)
        self.assertGreater(sum(solved['impact_track_loads']), 0.0)
        self.assertLess(sum(solved['impact_track_loads']), 1.0)

    def test_zero_time_and_no_contact_produce_no_impact_load(self):
        self.assertEqual((0.0, 0.0), self.solve(dt=0.0)['impact_track_loads'])
        self.assertEqual((0.0, 0.0), self.solve(())['impact_track_loads'])

    def test_reporting_impulses_does_not_change_projected_motion(self):
        ground, pseudo = self.fixture._plane_samples(self.params)
        before = self.fixture._state(height=-0.5, vertical_velocity=-20.0,
                                     pitch=0.1, roll=0.2)
        old, observed = copy.deepcopy(before), copy.deepcopy(before)
        loads = {}
        old_keys = vehicle_physics._project_suspension_limits(
            self.params, old, ground, pseudo)
        new_keys = vehicle_physics._project_suspension_limits(
            self.params, observed, ground, pseudo, impact_impulses=loads)
        self.assertEqual(old_keys, new_keys)
        self.assertEqual(old, observed)
        self.assertTrue(loads)


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

    def test_supported_compression_does_not_submit_a_landing(self):
        self.runtime._descriptors[self.state['id']] = self.suspension_descriptor
        self.state.update(airborne=False, vertical_speed=-1.0)
        self.runtime._apply_bot_landing_impact = mock.Mock()
        self.assertFalse(self.runtime._update_vertical_motion(self.state, 0.03))
        self.runtime._apply_bot_landing_impact.assert_not_called()
        self.assertEqual(1000, self.state['health'])
        self.assertEqual([], self.state['critical']['devices'])
