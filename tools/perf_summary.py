"""Summarize in-game PERF windows into a comparable performance baseline.

The visible client and the hidden worker each write a PERF window about every
30 seconds (the first after 5 seconds). This reads those lines from error
report ZIPs or log files, optionally a byte range of a growing log, keeps the
live-phase windows and reports, per round and role, the render-callback rate,
frame-interval and Python-callback percentiles, hitches per minute, stage
costs, worker control load and queues, and the busiest worker stages.

Usage:
  python tools/perf_summary.py SOURCE [SOURCE ...] [--label ROUND=NAME] [--json OUT]
  python tools/perf_summary.py --compare BASE.json CANDIDATE.json

SOURCE is a report ZIP, a log file, or LOG@START:END for a byte range.
"""
import argparse
import json
import re
import statistics
import sys
import zipfile

SCHEMA = 1
_PERF = re.compile(r'\[Offline LAN 0\.9\.22\] PERF (\w+) ?(.*)$')
_REPORT_LOGS = ('visible-client.log', 'hidden-worker.log')
STAGES = ('house', 'sync', 'critical', 'drown', 'prewarm', 'transition', 'local',
          'outline', 'bots_update', 'bot_present', 'bot_events', 'spot', 'lock',
          'schedule', 'diag_emit')
WORKER_MAXIMA = (
    ('max_control_step_ms', 'max_control_step_ms'),
    ('control_debt_ms', 'control_debt_ms_max'),
    ('astar_pending', 'astar_pending_max'),
)
WORKER_PAIR_MAXIMA = (
    ('visibility_queue_depth_max', 'visibility_queue_depth_max'),
    ('visibility_oldest_ms_max', 'visibility_oldest_ms_max'),
    ('shot_lane_pending_max', 'shot_lane_pending_max'),
    ('shot_lane_oldest_due_ms_max', 'shot_lane_oldest_due_ms_max'),
)
COMPARE_FIELDS = (
    ('fps', 'fps', 1),
    ('frame_ms_p95', 'frame p95 ms', -1),
    ('frame_ms_p99', 'frame p99 ms', -1),
    ('over_100_per_min', '>100 ms/min', -1),
    ('python_ms_p95', 'python p95 ms', -1),
    ('stage_bots_update_avg_ms', 'bots_update avg ms', -1),
    ('max_control_step_ms', 'max control step ms', -1),
)


def _value(text):
    if text in ('None', ''):
        return None
    try:
        return float(text)
    except ValueError:
        return text


def parse_fields(text):
    """Split ``key=value`` tokens; ``a/b`` values become tuples."""
    fields = {}
    for token in text.split():
        key, separator, raw = token.partition('=')
        if not separator:
            continue
        if '/' in raw:
            fields[key] = tuple(_value(part) for part in raw.split('/'))
        else:
            fields[key] = _value(raw)
    return fields


def parse_windows(lines):
    """Return one dict per PERF summary window, with its following lines."""
    windows, current = [], None
    for line in lines:
        if '] PERF ' not in line:
            continue
        match = _PERF.search(line)
        if not match:
            continue
        kind, rest = match.group(1), match.group(2).strip()
        if kind == 'summary':
            current = {'summary': parse_fields(rest)}
            windows.append(current)
        elif current is not None and kind in (
                'stages_ms_avg_max', 'worker', 'projectile_avg_max',
                'thread_cpu', 'details_ms_avg_max'):
            current[kind] = parse_fields(rest)
    return windows


def _decode(data):
    return data.decode('utf-8', 'replace').splitlines()


def read_source(source):
    """Return one list of text lines per log in a report ZIP, a log, or ``LOG@START:END``.

    Each log is kept separate so a window never collects another log's lines.
    """
    path, start, end = source, None, None
    range_match = re.match(r'^(.*)@(\d*):(\d*)$', source)
    if range_match:
        path = range_match.group(1)
        start = int(range_match.group(2)) if range_match.group(2) else None
        end = int(range_match.group(3)) if range_match.group(3) else None
    if zipfile.is_zipfile(path):
        if start is not None or end is not None:
            raise ValueError('byte ranges apply to log files, not reports: %s' % source)
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            return [_decode(archive.read(name)) for name in _REPORT_LOGS if name in names]
    with open(path, 'rb') as stream:
        if start:
            stream.seek(start)
        data = stream.read() if end is None else stream.read(max(0, end - (start or 0)))
    return [_decode(data)]


def _pair(fields, key, index):
    value = fields.get(key)
    if isinstance(value, tuple) and len(value) > index:
        return value[index]
    return None


def _numbers(values):
    return [value for value in values if isinstance(value, float)]


def _median(values):
    values = _numbers(values)
    return statistics.median(values) if values else None


def _maximum(values):
    values = _numbers(values)
    return max(values) if values else None


def _round(value, digits=3):
    return None if value is None else round(value, digits)


def summarize_scene(windows):
    """Aggregate the live windows of one round and role."""
    summaries = [window['summary'] for window in windows]
    seconds = sum(summary.get('seconds') or 0.0 for summary in summaries)
    samples = sum(summary.get('samples') or 0.0 for summary in summaries)
    minutes = seconds / 60.0 if seconds else None
    result = {
        'windows': len(windows),
        'minutes': _round(minutes, 2),
        'fps': _round(samples / seconds if seconds else None, 2),
        'frame_ms_p50': _round(_median(_pair(s, 'gap_ms_p50_p95_p99_max', 0) for s in summaries)),
        'frame_ms_p95': _round(_median(_pair(s, 'gap_ms_p50_p95_p99_max', 1) for s in summaries)),
        'frame_ms_p99': _round(_median(_pair(s, 'gap_ms_p50_p95_p99_max', 2) for s in summaries)),
        'frame_ms_max': _round(_maximum(_pair(s, 'gap_ms_p50_p95_p99_max', 3) for s in summaries)),
        'worst_window_frame_ms_p95': _round(_maximum(
            _pair(s, 'gap_ms_p50_p95_p99_max', 1) for s in summaries)),
        'python_ms_p50': _round(_median(_pair(s, 'python_ms_p50_p95_p99_max', 0) for s in summaries)),
        'python_ms_p95': _round(_median(_pair(s, 'python_ms_p50_p95_p99_max', 1) for s in summaries)),
        'python_ms_max': _round(_maximum(_pair(s, 'python_ms_p50_p95_p99_max', 3) for s in summaries)),
        'outside_ms_p95': _round(_median(_pair(s, 'outside_ms_p50_p95_p99_max', 1) for s in summaries)),
    }
    for index, threshold in enumerate((50, 67, 100)):
        count = sum(_pair(s, 'over_50_67_100', index) or 0.0 for s in summaries)
        result['over_%d_per_min' % threshold] = _round(count / minutes if minutes else None, 2)
    caps = sum(summary.get('sim_caps') or 0.0 for summary in summaries)
    result['sim_caps_per_min'] = _round(caps / minutes if minutes else None, 2)
    for stage in STAGES:
        weighted, total, maximum = 0.0, 0.0, None
        for window in windows:
            stages = window.get('stages_ms_avg_max') or {}
            average, peak = _pair(stages, stage, 0), _pair(stages, stage, 1)
            count = window['summary'].get('samples') or 0.0
            if isinstance(average, float):
                weighted += average * count
                total += count
            if isinstance(peak, float):
                maximum = peak if maximum is None else max(maximum, peak)
        result['stage_%s_avg_ms' % stage] = _round(weighted / total if total else None)
        result['stage_%s_max_ms' % stage] = _round(maximum)
    cpu_weighted, cpu_total = 0.0, 0.0
    for window in windows:
        cpu = window.get('thread_cpu') or {}
        average, count = _pair(cpu, 'cpu_ms_avg_max', 0), _pair(cpu, 'samples', 0)
        if isinstance(average, float) and isinstance(count, float):
            cpu_weighted += average * count
            cpu_total += count
    result['thread_cpu_avg_ms'] = _round(cpu_weighted / cpu_total if cpu_total else None)
    workers = [window.get('worker') or {} for window in windows]
    steps = _numbers(worker.get('control_steps') for worker in workers)
    catchups = _numbers(worker.get('catchup') for worker in workers)
    result['control_steps_per_s'] = _round(sum(steps) / seconds if steps and seconds else None, 2)
    result['catchup_per_s'] = _round(sum(catchups) / seconds if catchups and seconds else None, 2)
    for key, name in WORKER_MAXIMA:
        result[name] = _round(_maximum(worker.get(key) for worker in workers))
    for key, name in WORKER_PAIR_MAXIMA:
        result[name] = _round(_maximum(_pair(worker, key, 1) for worker in workers))
    exhausted = _numbers(worker.get('astar_budget_exhausted') for worker in workers)
    result['astar_budget_exhausted'] = sum(exhausted) if exhausted else None
    projectiles = [window.get('projectile_avg_max') or {} for window in windows]
    result['projectiles_active_max'] = _round(_maximum(_pair(p, 'active', 1) for p in projectiles))
    return result


def _round_order(round_id):
    return (0, int(round_id), '') if round_id.isdigit() else (1, 0, round_id)


def summarize(sources, labels=None, phase='live'):
    labels = labels or {}
    scenes = {}
    windows = [window for source in sources for lines in read_source(source)
               for window in parse_windows(lines)]
    for window in windows:
        summary = window['summary']
        if summary.get('phase') != phase:
            continue
        round_id = summary.get('round')
        round_id = '%d' % round_id if isinstance(round_id, float) else str(round_id)
        map_name = str(summary.get('map'))
        # Rounds that share a label are repeats of one scene and are pooled.
        label = labels.get(round_id, '%s round %s' % (map_name, round_id))
        key = (label, map_name, str(summary.get('role')))
        entry = scenes.setdefault(key, {'rounds': set(), 'windows': []})
        entry['rounds'].add(round_id)
        entry['windows'].append(window)
    rows = []
    for (label, map_name, role), entry in sorted(
            scenes.items(), key=lambda item: (min(item[1]['rounds'], key=_round_order),
                                              item[0][2])):
        row = {'round': ','.join(sorted(entry['rounds'], key=_round_order)),
               'map': map_name, 'role': role, 'label': label}
        row.update(summarize_scene(entry['windows']))
        rows.append(row)
    return {'schema': SCHEMA, 'sources': list(sources), 'phase': phase, 'scenes': rows}


def _cell(value):
    if value is None:
        return '-'
    if isinstance(value, float):
        return ('%.2f' % value).rstrip('0').rstrip('.')
    return str(value)


def _table(headers, rows):
    lines = ['| ' + ' | '.join(headers) + ' |',
             '|' + '|'.join('---' for unused in headers) + '|']
    lines.extend('| ' + ' | '.join(_cell(value) for value in row) + ' |' for row in rows)
    return '\n'.join(lines)


def render(result):
    scenes = result['scenes']
    frame = _table(
        ('scene', 'role', 'min', 'fps', 'frame p50/p95/p99 ms', 'frame max ms',
         '>50 ms/min', '>100 ms/min', 'python p95 ms'),
        [(s['label'], s['role'], s['minutes'], s['fps'],
          '/'.join(_cell(s[k]) for k in ('frame_ms_p50', 'frame_ms_p95', 'frame_ms_p99')),
          s['frame_ms_max'], s['over_50_per_min'], s['over_100_per_min'], s['python_ms_p95'])
         for s in scenes])
    stages = []
    for scene in scenes:
        ranked = sorted(((scene['stage_%s_avg_ms' % name] or 0.0, name) for name in STAGES),
                        reverse=True)[:4]
        stages.append((scene['label'], scene['role'], ', '.join(
            '%s %s/%s' % (name, _cell(scene['stage_%s_avg_ms' % name]),
                          _cell(scene['stage_%s_max_ms' % name]))
            for unused, name in ranked)))
    worker_rows = [s for s in scenes if s['control_steps_per_s'] is not None]
    worker = _table(
        ('scene', 'control steps/s', 'catch-ups/s', 'max step ms', 'sim caps/min',
         'A* pending max', 'A* budget exhausted', 'visibility depth/oldest ms',
         'shot lane pending/oldest ms'),
        [(s['label'], s['control_steps_per_s'], s['catchup_per_s'], s['max_control_step_ms'],
          s['sim_caps_per_min'], s['astar_pending_max'], s['astar_budget_exhausted'],
          '%s/%s' % (_cell(s['visibility_queue_depth_max']), _cell(s['visibility_oldest_ms_max'])),
          '%s/%s' % (_cell(s['shot_lane_pending_max']), _cell(s['shot_lane_oldest_due_ms_max'])))
         for s in worker_rows])
    return '\n\n'.join((
        'Frame pacing (live phase)\n\n' + frame,
        'Busiest stages, avg/max ms per callback\n\n' + _table(('scene', 'role', 'stages'), stages),
        'Hidden worker control\n\n' + worker))


def compare(base, candidate):
    """Return a Markdown table of deltas for scenes present in both runs."""
    def keyed(result):
        return dict(((scene['label'], scene['role']), scene) for scene in result['scenes'])

    before, after = keyed(base), keyed(candidate)
    rows = []
    for key in sorted(set(before) & set(after)):
        for field, title, better in COMPARE_FIELDS:
            old, new = before[key].get(field), after[key].get(field)
            if old is None or new is None:
                continue
            delta = new - old
            verdict = 'same' if abs(delta) < 1e-9 else (
                'better' if delta * better > 0 else 'worse')
            rows.append((key[0], key[1], title, old, new, _round(delta, 3), verdict))
    return _table(('scene', 'role', 'metric', 'base', 'candidate', 'delta', ''), rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('sources', nargs='*')
    parser.add_argument('--label', action='append', default=[],
                        help='ROUND=NAME label for a round, e.g. 1=malinovka-15v15')
    parser.add_argument('--json', help='write the summary JSON here')
    parser.add_argument('--compare', nargs=2, metavar=('BASE', 'CANDIDATE'))
    args = parser.parse_args(argv)
    if args.compare:
        with open(args.compare[0], encoding='utf-8') as stream:
            base = json.load(stream)
        with open(args.compare[1], encoding='utf-8') as stream:
            candidate = json.load(stream)
        print(compare(base, candidate))
        return 0
    if not args.sources:
        parser.error('give at least one report, log or LOG@START:END source')
    labels = {}
    for item in args.label:
        round_id, separator, name = item.partition('=')
        if not separator or not name:
            parser.error('labels look like ROUND=NAME: %s' % item)
        labels[round_id] = name
    result = summarize(args.sources, labels)
    if args.json:
        with open(args.json, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write('\n')
    print(render(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
