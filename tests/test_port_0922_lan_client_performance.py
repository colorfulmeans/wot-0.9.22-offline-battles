import sys
from pathlib import Path
import unittest
from unittest import mock

sys.path.insert(0, str(
    Path(__file__).resolve().parents[1] / 'src' / 'res' / 'scripts' / 'client'))
from gui.mods.offline_lan_0922 import lan_client, offline_replay, snapshot_delta


class TransportPerformanceTests(unittest.TestCase):
    def client(self):
        return lan_client.LANClient(
            '127.0.0.1', 28782, 'P', 'ussr:MS-1', bigworld=mock.Mock())

    def test_worker_latency_diagnostic_is_opt_in_bounded_and_observational(self):
        from gui.mods.offline_lan_0922 import native_input_diagnostics as logs
        client = self.client()
        client.connected = True
        client.round_id, client.authority_epoch = 1, 1
        client.rtt_ms = 5.0
        pong = dict(type='worker_pong', round_id=1, authority_epoch=1,
                    client_time=99.8, _client_received_time=100.0, frame_ms=200.0)
        with mock.patch.object(logs, 'detailed_enabled', return_value=False), \
                mock.patch.object(logs, 'write_json_record') as writer:
            client._handle_message(pong)
            writer.assert_not_called()
            self.assertFalse(hasattr(client, '_worker_latency_log'))
        with mock.patch.object(logs, 'detailed_enabled', return_value=True), \
                mock.patch.object(logs, 'write_json_record') as writer, \
                mock.patch.object(lan_client, '_monotonic_time', return_value=100.05):
            client._handle_message(pong)
            client._handle_message(pong)
            self.assertEqual(1, writer.call_count)
            row = writer.call_args.args[1]
            self.assertEqual('WORKER LATENCY', writer.call_args.args[0])
            self.assertEqual(5., row['server_rtt_ms'])
            self.assertAlmostEqual(200., row['worker_relay_rtt_ms'])
            self.assertAlmostEqual(50., row['dispatch_delay_ms'])
            self.assertEqual(200, row['displayed_ping_ms'])
        with mock.patch.object(logs, 'detailed_enabled', return_value=True), \
                mock.patch.object(logs, 'write_json_record', side_effect=RuntimeError('log unavailable')), \
                mock.patch.object(lan_client, '_monotonic_time', return_value=116.):
            client._handle_message(dict(pong, client_time=115.9,
                                       _client_received_time=116., frame_ms=150.))
        self.assertEqual(150., client.worker_frame_ms)

    def test_nested_poll_costs_do_not_change_dispatch_or_expose_partial_totals(self):
        client = self.client()
        now = [100.0]
        seen = []

        def materialize(message):
            now[0] += 0.002
            return message

        def handle(message):
            now[0] += 0.003
            self.assertIsNone(client.transport_performance_snapshot())
            client._notify('snapshot', message)

        def capture(*unused):
            now[0] += 0.004

        def observer(kind, message):
            seen.append((kind, message['server_tick']))
            now[0] += 0.005

        client._handle_message = handle
        client.on_event = observer
        client._queue_message({'type': 'snapshot', 'server_tick': 7,
                               '_client_received_time': 99.0})
        with mock.patch.object(lan_client, '_TRANSPORT_PROFILE_CLOCK',
                               side_effect=lambda: now[0]), \
                mock.patch.object(lan_client, '_monotonic_time',
                                  side_effect=lambda: now[0]), \
                mock.patch.object(snapshot_delta, 'materialize',
                                  side_effect=materialize), \
                mock.patch.object(offline_replay, 'observe_wire',
                                  side_effect=capture):
            client._poll()
        result = client.transport_performance_snapshot()
        self.assertEqual([('snapshot', 7)], seen)
        for name, elapsed in [('poll', .014), ('materialize', .002),
                              ('handle', .012), ('notify', .009)]:
            self.assertEqual(1, result[name + '_calls'])
            self.assertAlmostEqual(elapsed, result[name + '_wall_seconds'])
        self.assertEqual(0, client._transport_performance.poll_depth)
        self.assertEqual(9, len(result))

    def test_failed_clock_or_counter_preserves_original_handler_exception(self):
        class CounterFailure(dict):
            def __setitem__(self, key, value):
                raise RuntimeError('diagnostic counter failed')

        for broken_clock in (False, True):
            with self.subTest(broken_clock=broken_clock):
                client = self.client()
                original = ValueError('original consumer failure')
                client._handle_message = mock.Mock(side_effect=original)
                client._transport_performance.values = CounterFailure(
                    client._transport_performance.values)
                client._queue_message({'type': 'events', 'events': []})
                clock = (mock.Mock(side_effect=RuntimeError('clock failed'))
                         if broken_clock else lambda: 1.0)
                with mock.patch.object(lan_client, '_TRANSPORT_PROFILE_CLOCK', clock):
                    with self.assertRaises(ValueError) as raised:
                        client._poll()
                self.assertIs(original, raised.exception)
                self.assertEqual(0, client._transport_performance.handle_depth)
                self.assertEqual(0, client._transport_performance.poll_depth)
                self.assertIsNone(client.transport_performance_snapshot())

    def test_invalid_clock_sample_marks_cost_unknown_until_new_generation(self):
        for ending in (float('nan'), float('inf'), -1.0, 9.0):
            with self.subTest(ending=ending):
                client = self.client()
                performance = client._transport_performance
                with mock.patch.object(lan_client, '_TRANSPORT_PROFILE_CLOCK',
                                       side_effect=[10.0, ending]):
                    started = performance.clock()
                    performance.finish('poll', started)
                self.assertIsNone(client.transport_performance_snapshot())
                with mock.patch.object(lan_client.threading, 'Thread'):
                    client.start()
                self.assertEqual(1, client.transport_performance_snapshot()['generation'])

    def test_failed_materialization_is_still_contained_and_measured(self):
        client = self.client()
        client._handle_message = mock.Mock()
        client._ignore_runtime_payload = mock.Mock()
        client._queue_message({'type': 'snapshot'})
        with mock.patch.object(snapshot_delta, 'materialize',
                               side_effect=snapshot_delta.SnapshotDeltaError('bad actors')):
            client._poll()
        result = client.transport_performance_snapshot()
        self.assertEqual(1, result['poll_calls'])
        self.assertEqual(1, result['materialize_calls'])
        self.assertEqual(0, result['handle_calls'])
        client._handle_message.assert_not_called()
        self.assertEqual('actor_materialization', client._snapshot_drop_reason)

    def test_nested_poll_preserves_messages_but_cannot_double_count_wall(self):
        client = self.client()
        seen = []

        def handle(message):
            seen.append(message['server_tick'])
            if message['server_tick'] == 1:
                client._queue_message({'type': 'events', 'server_tick': 2})
                client._poll()

        client._handle_message = handle
        client._queue_message({'type': 'events', 'server_tick': 1})
        client._poll()
        self.assertEqual([1, 2], seen)
        self.assertEqual([], client._pending)
        self.assertEqual(0, client._transport_performance.poll_depth)
        self.assertIsNone(client.transport_performance_snapshot())

    def test_reentrant_start_does_not_charge_new_transport(self):
        client = self.client()
        old = client._transport_performance
        client.on_event = mock.Mock()
        client._handle_message = lambda message: client._notify('snapshot', message)
        client._queue_message({'type': 'snapshot', '_client_received_time': 0.0})
        with mock.patch.object(lan_client.threading, 'Thread'), \
                mock.patch.object(offline_replay, 'observe_wire',
                                  side_effect=lambda *unused: client.start()):
            client._poll()
        result = client.transport_performance_snapshot()
        self.assertEqual(1, result['generation'])
        for name in ('poll', 'materialize', 'handle', 'notify'):
            self.assertEqual(0, result[name + '_calls'])
        self.assertEqual(1, old.values['poll_calls'])
        self.assertEqual(0, old.poll_depth)
        self.assertEqual(0, client._transport_performance.poll_depth)
        client.on_event.assert_called_once()


if __name__ == '__main__':
    unittest.main()
