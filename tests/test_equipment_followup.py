"""Real consumer boundaries for the November equipment follow-up."""
import os
import math
import types
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import bot_fittings, bot_runtime, loadout
from gui.mods.offline_lan_0922 import battle_runtime, equipment_mechanics as em
from gui.mods.offline_lan_0922 import equipment_test, roof_crush_test
from gui.mods.offline_lan_0922.bot_fitting_data import PLANS
from test_port_0922_equipment_mechanics import _equipment


def item(name, **kwargs):
    return em.EquipmentState(em.project_equipment(_equipment(name, 1, 101, **kwargs)))


class FollowupTests(unittest.TestCase):
    def test_wreck_governor_stops_on_stall_and_rearms_only_after_real_motion(self):
        owner = object.__new__(bot_runtime.BotRuntime)
        owner.states = {2:dict(alive=False, x=0., z=0.)}
        state = dict(speed=0., _governor_push_evidence=dict(peer_id=2, in_contact=True))
        owner._equipment_now = 0.
        self.assertTrue(owner._bot_governor_request(state))
        owner._equipment_now = 2.
        self.assertFalse(owner._bot_governor_request(state))
        owner._equipment_now = 10.
        self.assertFalse(owner._bot_governor_request(state))
        owner.states[2]['yaw'] = 1.2  # Rotation alone does not reset the stall.
        self.assertFalse(owner._bot_governor_request(state))
        owner.states[2]['x'] = .2
        self.assertTrue(owner._bot_governor_request(state))
        state['_governor_push_evidence'] = {}
        self.assertFalse(owner._bot_governor_request(state))
        self.assertNotIn('_governor_push_progress', state)

    def test_bot_governor_waits_for_continuous_uphill_simulation_time(self):
        owner = object.__new__(bot_runtime.BotRuntime)
        state = dict(speed=3., terrain_pitch=-math.radians(5))
        owner._equipment_now = 10.
        self.assertFalse(owner._bot_governor_request(state))
        owner._equipment_now = 11.9
        self.assertFalse(owner._bot_governor_request(state))
        owner._equipment_now = 12.
        self.assertTrue(owner._bot_governor_request(state))
        # Every interruption switches off immediately and restarts the wait.
        for patch in (dict(speed=0.), dict(terrain_pitch=0.),
                      dict(terrain_pitch=math.radians(5)), dict(speed=-3.),
                      dict(airborne=True), dict(terrain_pitch=float('nan')),
                      dict(critical={'destroyed':['engineHealth']})):
            stopped = dict(state, **patch)
            self.assertFalse(owner._bot_governor_request(stopped))
            self.assertNotIn('_governor_uphill_since', stopped)
            restarted = dict(stopped, speed=3., terrain_pitch=-.1,
                             airborne=False, critical=None)
            self.assertFalse(owner._bot_governor_request(restarted))
            owner._equipment_now += 2.
            self.assertTrue(owner._bot_governor_request(restarted))
        self.assertTrue(owner._bot_governor_wanted(
            dict(speed=-3., terrain_pitch=math.radians(5))))
        self.assertFalse(owner._bot_governor_wanted(
            dict(speed=3., pitch=-.1, suspension_pitch=-.1)))
        owner._equipment_now = 0.
        self.assertFalse(owner._bot_governor_request(state))

    def test_bot_native_crew_calculation_receives_actual_food_and_fuel(self):
        descriptor = types.SimpleNamespace()
        bot_fittings.register(descriptor, dict(wire={'crew_level':100}, crew_roster=('driver',),
                                               consumables=(123, 456)))
        with mock.patch.object(loadout, 'attribute_factors', return_value={'engine/power':1.1}) as native:
            bot_fittings.native_factors(descriptor, equipments=(123,456))
            self.assertEqual((123, 456), native.call_args.kwargs['equipments'])

    def test_changing_bot_consumables_does_not_reuse_old_factor_cache(self):
        descriptor = types.SimpleNamespace()
        context = dict(wire={'crew_level':100}, crew_roster=('driver',), consumables=())
        bot_fittings.register(descriptor, context)
        with mock.patch.object(loadout, 'attribute_factors', side_effect=[{'engine/power':1.}, {'engine/power':1.1}]) as native:
            self.assertEqual(1., bot_fittings.native_factors(descriptor)['engine/power'])
            self.assertEqual(1.1, bot_fittings.native_factors(descriptor, equipments=(456,))['engine/power'])
            self.assertEqual(1., bot_fittings.native_factors(descriptor)['engine/power'])
            self.assertEqual(2, native.call_count)

    def test_player_fuel_is_not_applied_twice_but_governor_remains_switchable(self):
        owner = object.__new__(battle_runtime.BattleRuntime)
        fuel = item('gasoline105', enginePowerFactor=1.1)
        governor = item('removedRpmLimiter', enginePowerFactor=1.1, engineHpLossPerSecond=1.5)
        owner._equipment_state = (fuel, governor)
        self.assertEqual(1., owner._active_engine_power_factor())
        governor.active = True
        self.assertEqual(1.1, owner._active_engine_power_factor())

    def test_bot_governor_does_not_mutate_or_compound_cached_power(self):
        owner = object.__new__(bot_runtime.BotRuntime)
        governor = item('removedRpmLimiter', enginePowerFactor=1.1, engineHpLossPerSecond=1.5)
        governor.active = True
        owner._equipment_states = {1:(governor,)}
        owner._descriptors = {}
        base = {'powerW':1000.}
        self.assertAlmostEqual(1100., owner._governor_physics(1, base)['powerW'])
        self.assertEqual(1000., base['powerW'])
        governor.active = False
        self.assertIs(base, owner._governor_physics(1, base))

    def test_diagnostic_scenarios_cannot_be_enabled_in_normal_mode(self):
        with mock.patch.dict(os.environ, {'WOT_OFFLINE_DIAGNOSTICS':'0',
                equipment_test.ENV:'1', roof_crush_test.ENV:'1'}):
            self.assertFalse(equipment_test.enabled())
            self.assertFalse(roof_crush_test.enabled())

    def test_every_equipment_scene_vehicle_has_a_real_fitting(self):
        self.assertEqual(15, len(equipment_test.VEHICLES))
        for name in equipment_test.VEHICLES:
            self.assertIn(name, PLANS)
