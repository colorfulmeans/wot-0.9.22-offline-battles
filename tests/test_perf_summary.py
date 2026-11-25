"""The PERF summarizer turns in-game PERF windows into a comparable baseline."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('perf_summary', ROOT / 'tools/perf_summary.py')
perf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(perf)

PREFIX = '2026-11-25 19:40:00.000: INFO: [Offline LAN 0.9.22] PERF '


def summary(round_id, phase, role, samples, seconds, gap, python=(1, 2, 3, 4),
            over=(0, 0, 0), caps=0, map_name='02_malinovka'):
    return PREFIX + (
        'summary v=3 window=1 round=%s map=%s phase=%s role=%s probe_timing=off '
        'samples=%d seconds=%.3f fps=%.2f authority_frames=0 gap_ms_avg_max=1.000/2.000 '
        'raw_dt_ms_avg_max=1.000/2.000 exec_ms_avg_max=1.000/2.000 '
        'offframe_ms_avg_max=0.000/0.000 outside_ms_avg_max=1.000/2.000 '
        'gap_ms_p50_p95_p99_max=%s python_ms_p50_p95_p99_max=%s '
        'outside_ms_p50_p95_p99_max=1.000/2.000/3.000/4.000 '
        'distribution_kept_dropped=%d/0 over_50_67_100=%d/%d/%d sim_caps=%d '
        'clock_regress=0') % (
            round_id, map_name, phase, role, samples, seconds, samples / seconds,
            '/'.join('%.3f' % value for value in gap),
            '/'.join('%.3f' % value for value in python), samples,
            over[0], over[1], over[2], caps)


def stages(bots_update=(0.0, 0.0), sync=(0.5, 1.0)):
    values = dict((name, (0.0, 0.0)) for name in perf.STAGES)
    values['bots_update'] = bots_update
    values['sync'] = sync
    return PREFIX + 'stages_ms_avg_max ' + ' '.join(
        '%s=%.3f/%.3f' % (name, values[name][0], values[name][1]) for name in perf.STAGES)


def worker(steps=None, catchup=None, max_step=None, visibility=(None, None)):
    def show(value):
        return 'None' if value is None else '%s' % value
    return PREFIX + (
        'worker control_steps=%s catchup=%s debt_callbacks=0 control_debt_ms=0.0 '
        'max_control_step_ms=%s astar_pending=0 astar_credit=384.0 '
        'astar_budget_remaining=384.0 astar_budget_exhausted=0 astar_completed=3.0 '
        'astar_failed=0.0 visibility_queue_depth_max=%s/%s visibility_oldest_ms_max=0/0 '
        'shot_lane_pending_max=0/2 shot_lane_oldest_due_ms_max=0/0 '
        'shot_lane_completed_deferred=0/0 pose_writes_skips=1/1 aim_writes_skips=1/1') % (
            show(steps), show(catchup), show(max_step),
            show(visibility[0]), show(visibility[1]))


def session(lines):
    return '\n'.join(lines) + '\n'


WORKER_LOG = session([
    summary(1, 'prebattle', 'worker', 300, 5.0, (9, 30, 70, 170)),
    stages(),
    worker(0, 0, 0.0),
    summary(1, 'live', 'worker', 900, 30.0, (10, 20, 30, 40), over=(3, 2, 1), caps=1),
    stages(bots_update=(20.0, 170.0)),
    worker(180, 180, 190.5, (2, 5)),
    summary(1, 'live', 'worker', 600, 30.0, (10, 60, 80, 120), over=(5, 4, 3), caps=3),
    stages(bots_update=(10.0, 120.0)),
    worker(120, 60, 150.0, (1, 3)),
    summary(2, 'live', 'worker', 1500, 30.0, (8, 12, 14, 16), map_name='04_himmelsdorf'),
    stages(bots_update=(4.0, 30.0)),
    worker(90, 0, 40.0, (0, 0)),
])
CLIENT_LOG = session([
    summary(1, 'live', 'guest', 1680, 30.0, (17, 21, 24, 41)),
    stages(),
    worker(),
    summary(1, 'live', 'guest', 1650, 30.0, (17, 22, 26, 45)),
    stages(),
    worker(),
])


def scene(result, round_id, role):
    for row in result['scenes']:
        if row['round'] == round_id and row['role'] == role:
            return row
    raise AssertionError('no scene %s/%s' % (round_id, role))


class LogFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.worker_log = os.path.join(self.directory.name, 'offline-worker-python.log')
        self.client_log = os.path.join(self.directory.name, 'offline-player-python.log')
        with open(self.worker_log, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(WORKER_LOG)
        with open(self.client_log, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(CLIENT_LOG)


class SummaryTests(LogFixture):
    def test_live_windows_are_grouped_by_round_map_and_role(self):
        result = perf.summarize([self.worker_log, self.client_log])
        keys = [(row['round'], row['map'], row['role']) for row in result['scenes']]
        self.assertEqual([('1', '02_malinovka', 'guest'), ('1', '02_malinovka', 'worker'),
                          ('2', '04_himmelsdorf', 'worker')], keys)
        self.assertEqual(2, scene(result, '1', 'worker')['windows'])

    def test_rate_is_weighted_by_time_and_percentiles_use_window_medians(self):
        row = scene(perf.summarize([self.worker_log]), '1', 'worker')
        self.assertEqual(25.0, row['fps'])
        self.assertEqual(1.0, row['minutes'])
        self.assertEqual(40.0, row['frame_ms_p95'])
        self.assertEqual(55.0, row['frame_ms_p99'])
        self.assertEqual(120.0, row['frame_ms_max'])
        self.assertEqual(60.0, row['worst_window_frame_ms_p95'])

    def test_hitches_and_simulation_caps_are_per_minute(self):
        row = scene(perf.summarize([self.worker_log]), '1', 'worker')
        self.assertEqual(8.0, row['over_50_per_min'])
        self.assertEqual(4.0, row['over_100_per_min'])
        self.assertEqual(4.0, row['sim_caps_per_min'])

    def test_stage_costs_are_weighted_by_callbacks(self):
        row = scene(perf.summarize([self.worker_log]), '1', 'worker')
        self.assertEqual(16.0, row['stage_bots_update_avg_ms'])
        self.assertEqual(170.0, row['stage_bots_update_max_ms'])
        self.assertEqual(0.5, row['stage_sync_avg_ms'])

    def test_worker_control_load_and_queues(self):
        result = perf.summarize([self.worker_log, self.client_log])
        row = scene(result, '1', 'worker')
        self.assertEqual(5.0, row['control_steps_per_s'])
        self.assertEqual(4.0, row['catchup_per_s'])
        self.assertEqual(190.5, row['max_control_step_ms'])
        self.assertEqual(5.0, row['visibility_queue_depth_max'])
        self.assertEqual(2.0, row['shot_lane_pending_max'])
        client = scene(result, '1', 'guest')
        self.assertIsNone(client['control_steps_per_s'])
        self.assertIsNone(client['max_control_step_ms'])

    def test_byte_range_reads_only_the_new_part_of_a_growing_log(self):
        old = os.path.getsize(self.worker_log)
        with open(self.worker_log, 'a', encoding='utf-8', newline='\n') as stream:
            stream.write(session([
                summary(3, 'live', 'worker', 600, 30.0, (10, 11, 12, 13), map_name='35_steppes'),
                stages(), worker(60, 0, 20.0, (0, 0))]))
        result = perf.summarize(['%s@%d:' % (self.worker_log, old)])
        self.assertEqual([('3', '35_steppes')], [(row['round'], row['map'])
                                                 for row in result['scenes']])
        bounded = perf.summarize(['%s@0:%d' % (self.worker_log, old)])
        self.assertNotIn('3', [row['round'] for row in bounded['scenes']])

    def test_a_report_zip_supplies_client_and_worker_logs(self):
        report = os.path.join(self.directory.name, 'wot-error-report.zip')
        with zipfile.ZipFile(report, 'w') as archive:
            archive.writestr('hidden-worker.log', WORKER_LOG)
            archive.writestr('visible-client.log', CLIENT_LOG)
            archive.writestr('server.log', summary(9, 'live', 'server', 1, 1.0, (1, 1, 1, 1)))
        roles = sorted(set(row['role'] for row in perf.summarize([report])['scenes']))
        self.assertEqual(['guest', 'worker'], roles)
        with self.assertRaises(ValueError):
            perf.read_source(report + '@0:10')

    def test_a_window_never_collects_lines_from_the_next_log(self):
        report = os.path.join(self.directory.name, 'split-report.zip')
        with zipfile.ZipFile(report, 'w') as archive:
            archive.writestr('visible-client.log', session([
                summary(1, 'live', 'guest', 600, 30.0, (17, 21, 24, 41))]))
            archive.writestr('hidden-worker.log', session([
                stages(bots_update=(50.0, 90.0)),
                summary(1, 'live', 'worker', 600, 30.0, (10, 20, 30, 40)),
                stages(bots_update=(5.0, 9.0))]))
        result = perf.summarize([report])
        self.assertIsNone(scene(result, '1', 'guest')['stage_bots_update_avg_ms'])
        self.assertEqual(5.0, scene(result, '1', 'worker')['stage_bots_update_avg_ms'])

    def test_rounds_that_share_a_label_are_pooled_as_one_scene(self):
        result = perf.summarize([self.worker_log], {'1': 'repeat', '2': 'repeat'})
        self.assertEqual(2, len(result['scenes']))
        with open(self.worker_log, 'a', encoding='utf-8', newline='\n') as stream:
            stream.write(session([
                summary(10, 'live', 'worker', 900, 30.0, (10, 20, 30, 40)),
                stages(), worker(60, 0, 20.0, (0, 0))]))
        pooled = perf.summarize([self.worker_log], {'1': 'repeat', '10': 'repeat'})
        self.assertEqual(['1,10', '2'], [row['round'] for row in pooled['scenes']])
        self.assertEqual(3, pooled['scenes'][0]['windows'])
        self.assertEqual(round(2400.0 / 90.0, 2), pooled['scenes'][0]['fps'])

    def test_labels_name_rounds_in_the_rendered_tables(self):
        result = perf.summarize([self.worker_log, self.client_log],
                                {'1': 'malinovka-15v15'})
        text = perf.render(result)
        self.assertIn('| malinovka-15v15 | worker |', text)
        self.assertIn('bots_update 16/170', text)
        self.assertIn('04_himmelsdorf round 2', text)


class CompareAndCommandTests(LogFixture):
    def test_compare_marks_each_metric_better_or_worse(self):
        base = perf.summarize([self.worker_log], {'1': 'a', '2': 'b'})
        candidate = json.loads(json.dumps(base))
        candidate['scenes'][0]['fps'] = 30.0
        candidate['scenes'][0]['frame_ms_p95'] = 50.0
        text = perf.compare(base, candidate)
        self.assertIn('| a | worker | fps | 25 | 30 | 5 | better |', text)
        self.assertIn('| a | worker | frame p95 ms | 40 | 50 | 10 | worse |', text)
        self.assertIn('| b | worker | fps | 50 | 50 | 0 | same |', text)

    def test_main_writes_json_and_rejects_malformed_labels(self):
        output = os.path.join(self.directory.name, 'baseline.json')
        with mock.patch('sys.stdout', new=io.StringIO()) as printed:
            self.assertEqual(0, perf.main([self.worker_log, '--label', '1=malinovka-15v15',
                                           '--json', output]))
        self.assertIn('Hidden worker control', printed.getvalue())
        with open(output, encoding='utf-8') as stream:
            saved = json.load(stream)
        self.assertEqual(perf.SCHEMA, saved['schema'])
        self.assertEqual('malinovka-15v15', saved['scenes'][0]['label'])
        with mock.patch('sys.stdout', new=io.StringIO()) as printed:
            self.assertEqual(0, perf.main(['--compare', output, output]))
        self.assertIn('| same |', printed.getvalue())
        with mock.patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
            perf.main([self.worker_log, '--label', 'malinovka'])


if __name__ == '__main__':
    unittest.main()
