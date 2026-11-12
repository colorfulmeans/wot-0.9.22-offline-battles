"""Canonical capture observations reach the foreground through real snapshots.

Capture ownership is produced by the server's existing one-Hz law. A client
cannot replace that receipt with its newer instantaneous circle membership.
"""
import copy
import json
import unittest

import test_port_0922_server_capture as capture
from gui.mods.offline_lan_0922 import snapshot_delta


class SnapshotSocket(object):
    def __init__(self):
        self.messages = []

    def sendall(self, payload):
        self.messages.append(json.loads(payload.decode('utf8')))


class ForegroundCaptureObservationTests(unittest.TestCase):
    def scene(self):
        state = capture.ServerCaptureTests()._state()
        state._next_bot_planner_tick = 1000000
        state.bot_authority_id = 1
        viewer = capture._player(1, 1, 200., 0.)
        viewer.conn = SnapshotSocket()
        invader = capture._player(2, 2, 0., 0.)
        state.players = {1: viewer, 2: invader}
        self.assertTrue(capture.ServerCaptureTests._capture_tick(state))
        return state, viewer, invader

    def receive(self, state, viewer, baseline=None):
        before = len(viewer.conn.messages)
        state.tick_once(1. / capture.TICK_HZ)
        messages = [message for message in viewer.conn.messages[before:]
                    if message.get('type') == 'snapshot']
        self.assertEqual(1, len(messages))
        return snapshot_delta.decode(messages[0], baseline)

    def test_real_tick_publishes_the_existing_bot_capture_producer(self):
        state, viewer, unused = self.scene()
        expected = state._bot_defense_context()
        snapshot, unused_baseline = self.receive(state, viewer)
        self.assertEqual(state.round_id, snapshot['round_id'])
        self.assertEqual(json.loads(json.dumps(expected)), snapshot['defense'])
        self.assertEqual([dict(kind='human', id=2, points=1)],
                         snapshot['defense']['contributors']['1'])
        self.assertEqual(snapshot['rules']['bases'],
                         snapshot['defense']['states'])

    def test_loading_checkpoint_does_not_infer_points_from_spawn_positions(self):
        state = capture.ServerCaptureTests()._state()
        state.phase, state.tick = 'loading', 0
        state.bot_authority_id = state.bot_manifest_authority_id = 1
        state.players[2] = capture._player(2, 2, 0., 0.)
        message = state.loading_snapshot()
        self.assertIsNotNone(message)
        self.assertEqual(state.round_id, message['round_id'])
        self.assertEqual([], message['defense']['contributors']['1'])
        self.assertEqual([], message['defense']['bases']['1'])
        self.assertEqual(0, message['defense']['states']['1']['points'])
        self.assertEqual({}, state.capture_contributors[1])

    def test_capture_membership_changes_only_when_the_server_commits_it(self):
        state, viewer, invader = self.scene()
        first, baseline = self.receive(state, viewer)
        expected = copy.deepcopy(first['defense'])
        invader.x = 150.
        # Newer position is public, but the next capture-law tick has not run.
        second, baseline = self.receive(state, viewer, baseline)
        self.assertEqual(150., next(row for row in second['players']
                                  if row['id'] == 2)['x'])
        self.assertEqual(expected, second['defense'])
        state.tick = (int(round(capture.PREBATTLE_SECONDS * capture.TICK_HZ))
                      + int(round(capture.TICK_HZ)) - 1)
        third, unused_baseline = self.receive(state, viewer, baseline)
        self.assertEqual([], third['defense']['contributors']['1'])
        self.assertEqual([], third['defense']['bases']['1'])
        self.assertEqual(0, third['defense']['states']['1']['points'])
        self.assertEqual(expected, first['defense'])
        self.assertEqual(expected, second['defense'])

    def test_snapshot_decode_does_not_let_local_policy_mutate_server_receipts(self):
        state, viewer, unused = self.scene()
        first, baseline = self.receive(state, viewer)
        expected = copy.deepcopy(first['defense'])
        first['defense']['contributors']['1'][0]['points'] = 999
        first['defense']['capture_bases']['1'][0]['radius'] = 1.
        second, unused_baseline = self.receive(state, viewer, baseline)
        self.assertEqual(expected, second['defense'])
        self.assertEqual(1, state.capture_contributors[1]['human:2'])
        self.assertEqual(50., state._bot_defense_context()['capture_bases']['1'][0]['radius'])


if __name__ == '__main__':
    unittest.main()
