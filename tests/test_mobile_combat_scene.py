"""The optional scene uses legal racks and preserves both 15-slot lineups."""
import collections
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import bot_tactics, mobile_combat_test as scene
from gui.mods.offline_lan_0922.bot_runtime import _BotAmmoState
from gui.mods.offline_lan_0922.native_weapons import _ammo_row
from server.lan_battle_server import BattleState


class MobileCombatSceneTests(unittest.TestCase):
    def test_selected_vehicle_replaces_matching_slot_in_each_15_vehicle_team(self):
        room = BattleState(mobile_test=True)
        self.assertTrue(room.lineup_locked)
        for team in (1, 2):
            roster = [row['vehicle'] for row in room.bot_lineup if row['team'] == team]
            self.assertEqual(15, len(roster))
            self.assertEqual(4, collections.Counter(roster)[scene.ELC])
            self.assertEqual(4, collections.Counter(roster)[scene.PFM])
            player = SimpleNamespace(player_id=1, requested_team=team, team=team, slot=0,
                                     vehicle=scene.BATCHAT)
            self.assertEqual([(player, team, 14)], room._waiting_assignment_plan([player]))
        self.assertEqual(scene.MAP, room.map_name)

    def test_scene_routes_survive_the_round_payload(self):
        profile = bot_tactics.effective_round(scene.tactics(), scene.MAP)
        settings = profile['maps'][scene.MAP]
        routes = settings['routes']
        for team in (1, 2):
            assigned = {slot for route in routes if route['team'] == team
                        and route['policy'] == 'fixed' for slot in route['slots']}
            self.assertEqual(set(range(10)) | {11, 12}, assigned)
            authored = [row['id'] for row in settings['positions'] if row['team'] == team]
            self.assertEqual(2, len(authored))
            self.assertIn('spg_%d_west_fields' % team, authored)
            self.assertNotIn('spg_%d_east_ridge' % team, authored)

    def test_actual_mounted_identity_drives_the_fixed_inventory(self):
        gun, rounds = scene.LOADOUTS[scene.TYPE4]
        mounted = dict(gun=dict(name=gun, maxAmmo=40, shots=[
            dict(shell=dict(name=name)) for name, _ in reversed(rounds)]))
        with patch.dict(os.environ, {scene.ENV: '0', 'WOT_OFFLINE_DIAGNOSTICS': '1'}):
            self.assertIsNone(scene.ammunition(mounted, scene.TYPE4))
        with patch.dict(os.environ, {scene.ENV: '1', 'WOT_OFFLINE_DIAGNOSTICS': '1'}):
            self.assertEqual([20, 20], scene.ammunition(mounted, scene.TYPE4))
            mounted['gun']['name'] = 'wrong gun'
            with self.assertRaises(ValueError):
                scene.ammunition(mounted, scene.TYPE4)

    def test_bot_scene_inventory_reaches_the_native_weapon_owner(self):
        tactics = bot_tactics.effective_round(scene.tactics(), scene.MAP)
        gun, rounds = scene.LOADOUTS[scene.TYPE4]
        shells = [dict(name=name, index=index, kind='HIGH_EXPLOSIVE')
                  for index, (name, _) in enumerate(rounds)]
        descriptor = dict(gun=dict(name=gun, maxAmmo=40, shots=[
            dict(shell=shell) for shell in shells]))
        profile = dict(bot_tactics.effective(tactics, 1, 'heavyTank', 11),
                       vehicle_name=scene.TYPE4, class_tag='heavyTank',
                       gun_name=gun, bot_tier='veteran', shells=shells)
        with patch.dict(os.environ, {scene.ENV: '1', 'WOT_OFFLINE_DIAGNOSTICS': '1'}):
            categories, inventory, loaded, *_ = _ammo_row(_BotAmmoState(descriptor, profile))
        self.assertEqual(((0, 1), (20, 20), 0), (categories, inventory, loaded))
