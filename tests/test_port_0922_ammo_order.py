"""Saved shell slots stay ordered without changing physical shot indices."""

import copy
import itertools
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as runtime_tests
from gui.mods.offline_lan_0922 import combat_rules, gun_mechanics


class GarageAmmoOrderTests(unittest.TestCase):
    def _fixture(self, order=(303, 101, 202), counts=(5, 6, 7)):
        runtime = runtime_tests._runtime()
        battle = runtime_tests.BattleRuntime(runtime)
        descriptor = runtime_tests._Descriptor()
        base = descriptor.gun.shots[0]
        descriptor.gun.shots = []
        for compact, kind in ((101, 'ARMOR_PIERCING'),
                              (202, 'ARMOR_PIERCING_CR'),
                              (303, 'HIGH_EXPLOSIVE')):
            shot = copy.deepcopy(base)
            shot.shell.compactDescr = compact
            shot.shell.kind = kind
            descriptor.gun.shots.append(shot)
        quantities = dict(zip((101, 202, 303), counts))
        item = types.SimpleNamespace(shells=[
            types.SimpleNamespace(intCD=compact, count=quantities[compact])
            for compact in order], equipment=None)
        battle._garage_item = lambda: item
        state = gun_mechanics.GunState(
            descriptor, ammo_layout=battle._local_ammo_layout())
        battle._gun_state = state
        battle._avatar = runtime.bigworld.avatar
        battle._server = types.SimpleNamespace(vehicle_id=10)
        battle._present_equipments = lambda: None
        # #1513 AmmoController.setShells appends only when a compact
        # descriptor is first seen. Repeated updates never reorder slots.
        order_seen, ammo_seen = [], {}

        def update(unused_vehicle, compact, quantity, in_clip, unused_time):
            if compact not in ammo_seen:
                order_seen.append(compact)
            ammo_seen[compact] = (quantity, in_clip)

        battle._avatar.updateVehicleAmmo = update
        return battle, descriptor, state, order_seen, ammo_seen

    def test_every_saved_order_survives_account_retirement_and_updates(self):
        for order in itertools.permutations((101, 202, 303)):
            with self.subTest(order=order):
                battle, descriptor, state, observed, quantities = (
                    self._fixture(order))
                battle._garage_item = lambda: None
                self.assertEqual(order, battle._local_shell_order())
                self.assertTrue(battle._apply_initial_garage_shell(state))
                self.assertTrue(battle._publish_ammo_state(state))
                self.assertEqual(list(order), observed)
                self.assertEqual(order[0], battle._avatar.last_setting[2])
                self.assertEqual(
                    [101, 202, 303],
                    [shot.shell.compactDescr for shot in state.shots])
                self.assertEqual(tuple(descriptor.gun.shots), state.shots)
                self.assertEqual([5, 6, 7], state.ammo)
                self.assertFalse(battle._publish_ammo_state(state))
                battle._publish_ammo_state(state, force=True)
                self.assertEqual(list(order), observed)

    def test_empty_first_slot_stays_visible_but_does_not_load(self):
        battle, descriptor, state, observed, quantities = self._fixture(
            counts=(5, 6, 0))
        self.assertTrue(battle._apply_initial_garage_shell(state))
        battle._publish_ammo_state(state)
        self.assertEqual([303, 101, 202], observed)
        self.assertEqual((0, 0), quantities[303])
        self.assertEqual(0, state.shot_index)
        self.assertEqual(101, battle._avatar.last_setting[2])

    def test_reordered_he_keeps_physical_type_index_and_round_debit(self):
        battle, descriptor, state, observed, quantities = self._fixture()
        battle._apply_initial_garage_shell(state)
        self.assertEqual(2, state.shot_index)
        self.assertTrue(combat_rules.is_he(
            battle._descriptor_shot(descriptor, state.shot_index)))
        state.clip = 1
        state.reload_time = 0.0
        self.assertTrue(state.commit_fire())
        self.assertEqual([5, 6, 6], state.ammo)
        battle._publish_ammo_state(state)
        self.assertEqual([303, 101, 202], observed)
        self.assertEqual((6, 0), quantities[303])

        # The stock slot input carries intCD, not its position in the HUD.
        battle._sender = types.SimpleNamespace(send_current=mock.Mock())
        battle._roll_loader_intuition = lambda: False
        battle._publish_reload_event = mock.Mock()
        self.assertTrue(battle.change_vehicle_setting(
            battle._runtime.constants.VEHICLE_SETTING.CURRENT_SHELLS, 101))
        self.assertEqual(0, state.shot_index)
        self.assertFalse(combat_rules.is_he(
            battle._descriptor_shot(descriptor, state.shot_index)))
        self.assertEqual([303, 101, 202], observed)

    def test_no_garage_preserves_descriptor_order_and_selection(self):
        battle, descriptor, state, observed, quantities = self._fixture()
        battle._garage_loadout = None
        battle._garage_item = lambda: None
        state.shot_index = 1
        self.assertFalse(battle._apply_initial_garage_shell(state))
        battle._publish_ammo_state(state)
        self.assertEqual([101, 202, 303], observed)
        self.assertEqual(1, state.shot_index)
