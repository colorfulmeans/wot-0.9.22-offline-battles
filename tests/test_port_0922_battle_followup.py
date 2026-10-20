import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
sys.path.insert(0, str(ROOT / 'server'))
from gui.mods.offline_lan_0922 import battle_shell_tooltip
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
from gui.mods.offline_lan_0922.lan_client import LANClient
from gui.mods.offline_lan_0922.authority_worker import AuthorityWorkerLANClient
from gui.mods.offline_lan_0922.account_rpc import postbattle_store
from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime
from lan_battle_server import BattleState
from test_port_0922_postbattle import _receipt, _packed_vehicle
from test_port_0922_battle_runtime import _runtime


class FollowupTests(unittest.TestCase):
    def test_receipt_projects_received_breakdown_to_native_result(self):
        receipt = _receipt()
        receipt['stats'].update(BattleState._receipt_statistics({
            'hits_received': 7, 'piercings_received': 2,
            'no_damage_direct_hits_received': 4, 'explosion_hits_received': 3}))
        for row in receipt.get('public_results', ()):
            if row.get('actor_kind') == 'player' and row.get('actor_id') == receipt['player_id']:
                row['stats'] = dict(receipt['stats'])
        full = _packed_vehicle(receipt)
        self.assertEqual([7, 2, 4, 3], [full[name] for name in (
            'directHitsReceived', 'piercingsReceived',
            'noDamageDirectHitsReceived', 'explosionHitsReceived')])

    def test_tooltip_uses_hovered_shell_and_installed_gun(self):
        a, b = [types.SimpleNamespace(compactDescr=n) for n in (1, 2)]
        vehicle = types.SimpleNamespace(gun=types.SimpleNamespace(shots=[
            {'shell': a, 'speed': 760}, {'shell': b, 'speed': 1120}]))
        text = '{HEADER}HE{/HEADER}\n/{BODY}damage 500{/BODY}'
        result = battle_shell_tooltip.append_speed(text, b, vehicle)
        self.assertIn('1120', result)
        self.assertNotIn('760', result)
        self.assertIn('damage 500', result)
        self.assertEqual(1, result.count('{BODY}'))
        self.assertEqual(text, battle_shell_tooltip.append_speed(
            text, types.SimpleNamespace(compactDescr=3), vehicle))
        self.assertIsInstance(battle_shell_tooltip.append_speed(
            text.encode(), a, vehicle), bytes)

    def test_spg_direct_damage_uses_penetration_voice_and_keeps_physical_result(self):
        for tag, shell, damage, result, explosion in (
                ('SPG', 'HIGH_EXPLOSIVE', 80, 1, False),
                ('SPG', 'HIGH_EXPLOSIVE', 0, 1, False),
                ('SPG', 'HIGH_EXPLOSIVE', 80, 2, False),
                ('AT-SPG', 'HIGH_EXPLOSIVE', 80, 1, False),
                ('SPG', 'ARMOR_PIERCING', 80, 1, False)):
            runtime = _runtime()
            battle = BattleRuntime(runtime)
            battle._avatar = runtime.bigworld.avatar
            battle._avatar.playerVehicleID = 10
            battle._synchronise_player_identity(10)
            battle._server_entity = lambda unused: types.SimpleNamespace(
                typeDescriptor=types.SimpleNamespace(type=types.SimpleNamespace(tags=(tag,))))
            runtime.constants.SHELL_TYPES_INDICES = {'HIGH_EXPLOSIVE': 1, 'ARMOR_PIERCING': 2}
            battle._feedback_shell_fields = lambda *unused: (runtime.constants.SHELL_TYPES_INDICES[shell], False)
            event = {'kind': 'bot_hit', 'damage': damage, 'shot_result': result,
                     'source': 'shot', 'attack_reason': 0}
            battle._present_combat_feedback(event,
                {'engine_id': 11, 'local': False, 'kind': 'bot', 'state': {'team': 2}},
                {'engine_id': 10, 'local': True, 'kind': 'player', 'state': {'team': 1}})
            flags = battle._avatar.shot_results[0][0] >> 32
            self.assertEqual(explosion, bool(flags & runtime.constants.VEHICLE_HIT_FLAGS.ATTACK_IS_EXTERNAL_EXPLOSION))
            self.assertEqual(result, event['shot_result'])

    def test_ping_requires_worker_main_loop_and_rejects_old_authority(self):
        state = BattleState()
        worker_messages, replies = [], []
        worker = types.SimpleNamespace(connected=True, offer_reliable=lambda m: worker_messages.append(m) or True)
        player = types.SimpleNamespace(player_id=1, connected=True, offer_reliable=lambda m: replies.append(m) or True)
        state.players[1] = player
        state.simulation_worker = worker
        self.assertTrue(state.request_worker_ping(player, {'seq': 1, 'client_time': 10.0}))
        self.assertEqual([], replies)
        client = AuthorityWorkerLANClient('localhost', 28782)
        client._send = lambda message: state.resolve_worker_ping(worker, message)
        client._handle_message(worker_messages.pop())
        self.assertEqual('worker_pong', replies[0]['type'])
        self.assertEqual(10.0, replies[0]['client_time'])
        self.assertTrue(state.request_worker_ping(player, {'seq': 2, 'client_time': 11.0}))
        state.authority_epoch += 1
        client._handle_message(worker_messages.pop())
        self.assertEqual(1, len(replies))

    def test_worker_ping_reports_simulation_wait_and_stale_response(self):
        client = LANClient('localhost', 28782, 'Tester', 'ussr:R11_MS-1')
        client.connected = True
        client.round_id, client.authority_epoch = 1, 2
        client._worker_ping_started = 10.0
        client._handle_message({'type': 'worker_pong', 'round_id': 1,
            'authority_epoch': 2, 'seq': 1, 'client_time': 10.0,
            'frame_ms': 100.0, '_client_received_time': 10.240})
        self.assertEqual((100, False), client.worker_ping_display(10.25))
        self.assertAlmostEqual(240.0, client.worker_rtt_ms)
        self.assertEqual((999, True), client.worker_ping_display(14.0))


class FixedDestructibleIdentityTests(unittest.TestCase):
    def test_murovanka_list_already_reserves_the_empty_slot(self):
        catalog = json.loads((ROOT / 'destructibles/11_murovanka.json').read_text())
        sensor.set_catalog(catalog)
        try:
            prepared = sensor._destructible_catalog
            self.assertIn((32124, 7), prepared['excluded_instances'])
            self.assertIn('gaf001_woodfence', prepared['baked_instances'][(32124, 8)]['filename'])
            self.assertFalse(hasattr(sensor, '_commit_proved_chunk_layout_1513'))
            self.assertFalse(hasattr(sensor, '_recover_contacted_model_slot_1513'))
        finally:
            sensor.set_catalog(None)
