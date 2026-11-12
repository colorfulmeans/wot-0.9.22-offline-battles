"""Transport contracts for the shared movement owner, not combat admission.

These cases exercise the real worker publication/sender/server boundaries.
The supplied receipt is the output of the separately tested shared controller;
it is not evidence that a native attack or movement was executed.
"""
import copy
import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'server'),
               str(ROOT / 'src/res/scripts/client')]

import bot_state_rows
import test_port_0922_bot_runtime as bot_fixture
from gui.mods.offline_lan_0922 import bot_state_codec as codec
from gui.mods.offline_lan_0922.authority_worker import AuthorityWorkerLANClient
from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime
from gui.mods.offline_lan_0922.bot_runtime import BotRuntime, _server_order_signature


def receipt(**changes):
    result = dict(owned=True, target=('bot', 12), task_order=dict(
        route_id='class_mt_rim_east', route_index=1,
        move_position=dict(x=30.24, y=0., z=120.102),
        route_anchor=dict(x=-26., y=.286, z=118.), route_join=False))
    result.update(changes)
    return result


def table(owner=None, bot_id=11):
    return [dict(id=bot_id, owner=receipt() if owner is None else owner)]


class CombatMovementReceiptTests(unittest.TestCase):
    def server(self):
        server, unused, unused_socket = bot_fixture.ServerBotStateRevisionTests._server()
        return server

    def publication(self, server, owners=None, **changes):
        message = bot_state_rows.publication(
            bot_fixture.ServerBotStateRevisionTests._publication(server, 1.))
        if owners is not None:
            message['combat_movement_owners'] = owners
        message.update(changes)
        return message

    def admit(self, server, message):
        return server.update_bot_states(
            bot_fixture.SIMULATION_WORKER_AUTHORITY_ID, message)

    def test_legal_full_publication_preserves_original_route_and_target(self):
        server = self.server()
        source = table()
        self.assertTrue(self.admit(server, self.publication(server, source)))
        expected = json.loads(json.dumps(receipt()))
        self.assertEqual(expected, server.bot_states[11].get('_combat_movement_owner'))
        source[0]['owner']['task_order']['move_position']['x'] = 900.
        self.assertEqual(30.24, server.bot_states[11]['_combat_movement_owner']
                         ['task_order']['move_position']['x'])

    def test_missing_empty_or_false_full_publication_releases_previous_owner(self):
        for next_table in (None, [], table(dict(owned=False))):
            with self.subTest(next_table=next_table):
                server = self.server()
                self.assertTrue(self.admit(server, self.publication(server, table())))
                self.assertIn('_combat_movement_owner', server.bot_states[11])
                self.assertTrue(self.admit(server, self.publication(server, next_table)))
                self.assertNotIn('_combat_movement_owner', server.bot_states[11])

    def test_unavailable_checkpoint_keeps_owner_until_valid_release(self):
        server = self.server()
        self.assertTrue(self.admit(server, self.publication(server, table())))
        before = copy.deepcopy(server.bot_states[11]['_combat_movement_owner'])
        self.assertTrue(self.admit(server, self.publication(server, [], rows=[[11]])))
        self.assertEqual(before, server.bot_states[11]['_combat_movement_owner'])
        self.assertTrue(self.admit(server, self.publication(server, [])))
        self.assertNotIn('_combat_movement_owner', server.bot_states[11])

    def test_peer_release_and_unavailable_checkpoint_are_actor_local(self):
        server = self.server()
        server.bot_manifest.append(dict(server.bot_manifest[0], id=13, slot=2))
        server.bot_states[13] = copy.deepcopy(server.bot_states[11])
        server.bot_states[13].update(id=13, slot=2)
        rows = bot_state_rows.rows([dict(server.bot_states[actor], combat_seq=0)
                                   for actor in (11, 13)])
        owners = table() + table(receipt(target=('human', 2)), bot_id=13)
        self.assertTrue(self.admit(server, self.publication(server, owners, rows=rows)))
        retained = copy.deepcopy(server.bot_states[13]['_combat_movement_owner'])
        rows = bot_state_rows.rows([dict(server.bot_states[11], combat_seq=0)]) + [[13]]
        self.assertTrue(self.admit(server, self.publication(server, [], rows=rows)))
        self.assertNotIn('_combat_movement_owner', server.bot_states[11])
        self.assertEqual(retained, server.bot_states[13]['_combat_movement_owner'])
        self.assertEqual(['human', 2], retained['target'])

    def test_wrong_round_authority_or_incomplete_rows_cannot_release_owner(self):
        server = self.server()
        self.assertTrue(self.admit(server, self.publication(server, table())))
        before = copy.deepcopy(server.bot_states[11]['_combat_movement_owner'])
        self.assertFalse(self.admit(server, self.publication(
            server, [], round_id=server.round_id + 1)))
        self.assertFalse(server.update_bot_states(1, self.publication(server, [])))
        self.assertFalse(self.admit(server, self.publication(server, [], rows=[])))
        self.assertFalse(self.admit(server, self.publication(server, [], rows=[[11, 0]])))
        self.assertEqual(before, server.bot_states[11]['_combat_movement_owner'])

    def test_dead_full_checkpoint_releases_even_if_receipt_claims_owned(self):
        server = self.server()
        self.assertTrue(self.admit(server, self.publication(server, table())))
        self.assertIn('_combat_movement_owner', server.bot_states[11])
        # Death is a canonical server combat transition, not this advisory
        # receipt's authority to mutate the damage ledger.
        server.bot_states[11].update(health=0, alive=False, display_health=0)
        dead = dict(server.bot_states[11], health=0, alive=False, display_health=0,
                    combat_seq=server.bot_states[11]['combat_ack_seq'])
        message = self.publication(server, table(), rows=bot_state_rows.rows([dead]))
        self.assertTrue(self.admit(server, message))
        self.assertFalse(server.bot_states[11]['alive'])
        self.assertNotIn('_combat_movement_owner', server.bot_states[11])

    def test_canonical_death_releases_even_with_unavailable_pose(self):
        server = self.server()
        self.assertTrue(self.admit(server, self.publication(server, table())))
        previous = server.bot_states[11]
        previous.update(health=0, alive=False, display_health=0)
        self.assertTrue(self.admit(server, self.publication(server, table(), rows=[[11]])))
        self.assertFalse(server.bot_states[11]['alive'])
        self.assertNotIn('_combat_movement_owner', server.bot_states[11])
        self.assertIn('_combat_movement_owner', previous)

    def test_bad_receipt_table_cannot_fabricate_release_or_block_pose(self):
        for invalid in ({}, table() * 31, table() + table(),
                        table(receipt(target=('bot', True))),
                        table(receipt(task_order=dict(move_position=[float('nan'), 0., 0.])))):
            with self.subTest(invalid=invalid):
                server = self.server()
                self.assertTrue(self.admit(server, self.publication(server, table())))
                before = copy.deepcopy(server.bot_states[11]['_combat_movement_owner'])
                message = self.publication(server, invalid)
                message['rows'] = bot_state_rows.rows([dict(
                    server.bot_states[11], x=12.,
                    combat_seq=server.bot_states[11]['combat_ack_seq'])])
                self.assertTrue(self.admit(server, message))
                self.assertEqual(12., server.bot_states[11]['x'])
                self.assertEqual(before, server.bot_states[11]['_combat_movement_owner'])

    def test_schema_copies_only_route_fields_and_keeps_optional_none(self):
        raw = receipt(task_order=dict(route_id=None, route_index=None,
            move_position=(1., 2., 3.), route_anchor=None, route_join=None,
            combat_mode='engage', fire_allowed=True, target_id=99),
            internal_cache=dict(not_wire=object()))
        result = codec.normalize_combat_movement_owner(raw)
        self.assertEqual(dict(owned=True, target=['bot', 12], task_order=dict(
            route_id=None, route_index=None, move_position=dict(x=1., y=2., z=3.),
            route_anchor=None, route_join=None)), result)
        self.assertIn('internal_cache', raw)
        self.assertTrue(raw['task_order']['fire_allowed'])
        self.assertEqual(result, json.loads(json.dumps(result)))

    def test_both_senders_and_battle_bridge_carry_detached_receipts(self):
        worker = AuthorityWorkerLANClient('127.0.0.1', 28782)
        worker.ready = True
        worker.phase = 'battle'
        worker.round_id = 7
        worker.bot_authority_id = worker.player_id
        sent = []
        worker._send = lambda message, **unused: sent.append(message) or True
        worker._send_preencoded_trusted = worker._send
        for method in ('send_bot_state', 'send_projected_bot_state'):
            owner_table = table()
            edge = (dict(edge_sample_time_us=40000, edge_revision=1)
                    if method == 'send_projected_bot_state' else {})
            self.assertTrue(getattr(worker, method)(
                bot_state_rows.rows([dict(id=11)]),
                combat_movement_owners=owner_table, **edge))
            owner_table[0]['owner']['task_order']['move_position']['x'] = 500.
            self.assertEqual(30.24, sent[-1]['combat_movement_owners'][0]
                             ['owner']['task_order']['move_position']['x'])
        bridge = types.SimpleNamespace(client=worker, _worker_mode=False)
        self.assertTrue(BattleRuntime._send_bot_message(bridge, dict(
            type='bot_state', rows=bot_state_rows.rows([dict(id=11)]),
            edge_sample_time_us=40000, edge_revision=1,
            combat_movement_owners=table())))
        self.assertEqual(json.loads(json.dumps(table())), sent[-1]['combat_movement_owners'])

    def test_worker_projection_and_edge_signature_do_not_alias_local_owner(self):
        state = dict(id=11, alive=True, _combat_movement_owner=receipt())
        runtime = types.SimpleNamespace(_equipment_publication_edge=lambda unused: ())
        baseline = BotRuntime._current_publication_edge_signature(runtime, [state], [], [])
        projected = codec.project_combat_movement_owners([state])
        self.assertEqual(json.loads(json.dumps(table())), projected)
        state['_combat_movement_owner']['task_order']['route_index'] = 2
        changed = BotRuntime._current_publication_edge_signature(runtime, [state], [], [])
        self.assertNotEqual(baseline, changed)
        self.assertEqual(1, projected[0]['owner']['task_order']['route_index'])
        state.pop('_combat_movement_owner')
        released = BotRuntime._current_publication_edge_signature(runtime, [state], [], [])
        self.assertNotEqual(changed, released)
        self.assertEqual([], codec.project_combat_movement_owners([state]))
        state.update(alive=False, _combat_movement_owner=receipt())
        self.assertEqual([], codec.project_combat_movement_owners([state]))

    def runtime_fixture(self):
        fixture = bot_fixture.BotRuntimeTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.runtime.battle_start(fixture.start)
        return fixture.runtime

    def test_real_publication_loop_exports_the_controller_output_once(self):
        # The motion fixture deliberately has no combat factory. Supply the
        # controller's output at that boundary and retain the real BotRuntime
        # update/projection path; this is not an attack-admission test.
        runtime = self.runtime_fixture()
        state = runtime.states[11]
        state['_combat_movement_owner'] = receipt(task_order=dict(
            route_id='safe-2', route_index=0, move_position=(8., 0., 0.),
            route_anchor=(8., 0., 0.), route_join=False))
        expected = codec.project_combat_movement_owners([state])
        messages = runtime.update(.04, 1.)
        publications = [row for row in messages if row.get('type') == 'bot_state']
        self.assertTrue(publications)
        self.assertEqual(expected, publications[-1]['combat_movement_owners'])
        state['_combat_movement_owner']['task_order']['route_index'] = 9
        self.assertEqual(0, publications[-1]['combat_movement_owners'][0]
                         ['owner']['task_order']['route_index'])

    def test_server_echo_cannot_rewind_or_resurrect_local_movement_owner(self):
        runtime = self.runtime_fixture()
        state = runtime.states[11]
        current = receipt(target=('human', 2))
        state['_combat_movement_owner'] = copy.deepcopy(current)
        echoed = bot_fixture._snapshot_bot(_combat_movement_owner=receipt())
        runtime.apply_snapshot(dict(round_id=5, server_tick=1, bots=[echoed]))
        self.assertEqual(current, state['_combat_movement_owner'])
        state.pop('_combat_movement_owner')
        runtime.apply_snapshot(dict(round_id=5, server_tick=2, bots=[echoed]))
        self.assertNotIn('_combat_movement_owner', state)

    def test_initial_hint_changes_do_not_invalidate_driving_order_signature(self):
        order = dict(id=11, combat_mode='route', move_position=(30., 0., 20.),
                     initial_target_hint=dict(kind='bot', id=12))
        first = _server_order_signature(order)
        self.assertEqual(first, _server_order_signature(dict(
            order, initial_target_hint=dict(kind='bot', id=13))))
        for changes in (dict(move_position=(40., 0., 20.)),
                        dict(combat_mode='engage', target_kind='bot', target_id=12),
                        dict(combat_task_target=['bot', 13])):
            self.assertNotEqual(first, _server_order_signature(dict(order, **changes)))


if __name__ == '__main__':
    unittest.main()
