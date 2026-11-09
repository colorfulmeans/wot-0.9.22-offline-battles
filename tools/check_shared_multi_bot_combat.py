#!/usr/bin/env python3
"""Measure real shared BOT combat in an explicitly analytic native world.

The no-enemy control and mixed AP/HE engagement use the same worker runtime,
physical reference integration, roster and observation fixtures. Native BSP
and component geometry are counted analytic box operations, not Windows mesh
costs. This is a workload/control benchmark, never an estimate of game FPS.
"""
import argparse
import collections
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from shared_multi_bot_scene import MultiBotScene


class DiagnosticSink(object):
    def write(self, value):
        return len(value)
    def flush(self):
        pass


def identity():
    files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard',
        'src/res/scripts/client/gui/mods/offline_lan_0922'], cwd=str(ROOT), text=True).splitlines()
    digest = hashlib.sha256()
    for name in sorted(files):
        path = ROOT / name
        if path.is_file():
            digest.update(name.encode('utf-8') + b'\0' + path.read_bytes() + b'\0')
    diff = subprocess.check_output(['git', 'diff', 'HEAD', '--',
        'src/res/scripts/client/gui/mods/offline_lan_0922'], cwd=str(ROOT))
    return dict(head=subprocess.check_output(['git', 'rev-parse', 'HEAD'],
        cwd=str(ROOT), text=True).strip(), runtime_sha256=digest.hexdigest(),
        runtime_files=len(files), runtime_dirty=bool(diff),
        runtime_diff_sha256=hashlib.sha256(diff).hexdigest(),
        fixture_sha256=hashlib.sha256((ROOT/'tests/shared_multi_bot_scene.py').read_bytes()).hexdigest())


def distribution(values, multiplier=1.):
    values = sorted(value * multiplier for value in values)
    if not values:
        return dict(total=0., mean=0., median=0., p95=0., maximum=0.)
    return dict(total=sum(values), mean=statistics.mean(values),
        median=statistics.median(values), p95=values[max(0, int(math.ceil(len(values)*.95))-1)],
        maximum=max(values))


def workload(frames, actors):
    channels = ('foreground', 'background', 'atomic', 'trigger', 'control', 'other')
    kinds = ('candidate', 'world', 'component', 'strategic_lane', 'visibility',
             'he_blast', 'he_surface_world', 'he_surface_component')
    rows = {}
    for kind in kinds:
        rows[kind] = dict(total=sum(value for frame in frames
            for (actor, channel, key), value in frame['counts'].items() if key == kind),
            per_frame=distribution([sum(value for (actor, channel, key), value
                in frame['counts'].items() if key == kind) for frame in frames]))
    per_actor = {}
    for actor in actors:
        per_actor[str(actor)] = {
            channel: {kind: dict(total=sum(frame['counts'].get((actor, channel, kind), 0)
                for frame in frames), max_per_frame=max([frame['counts'].get((actor, channel, kind), 0)
                    for frame in frames] or [0])) for kind in (
                        'candidate', 'world', 'component', 'he_blast',
                        'he_surface_world', 'he_surface_component')}
            for channel in channels}
    by_channel = {channel: dict(total=sum(value for frame in frames
        for (actor, name, kind), value in frame['counts'].items()
        if name == channel and kind == 'candidate'),
        frame_max=max([sum(value for (actor, name, kind), value in frame['counts'].items()
            if name == channel and kind == 'candidate') for frame in frames] or [0]))
        for channel in channels}
    return dict(queries=rows, candidate_channels=by_channel, per_actor=per_actor)


def run_case(actors, frames, warmup, enemies, schedule):
    scene = MultiBotScene()
    try:
        with contextlib.redirect_stdout(DiagnosticSink()):
            scene.setUp()
            scene.configure_workers(actors, enemies=enemies, diverse=True, schedule=schedule)
            step = .1 if schedule == 'worker10' else .05
            for unused in range(warmup):
                scene.step(step)
            warmup_shots = len(scene.launches_observed)
            warmup_batches = {actor: binding.attack_policy.evaluator.cache_observations['armour_batches']
                             for actor, binding in scene.engine._actor_controls.items()}
            warmup_evaluation_time = dict(scene.evaluation_seconds)
            for unused in range(frames):
                scene.step(step)
        measured = scene.frames[warmup:]
        launches = scene.launches_observed[warmup_shots:]
        result = dict(name='mixed_ap_he_engagement' if enemies else 'no_enemy_control',
            actors=actors, active_teams=2 if enemies else 1, targets_per_actor=(
                sorted(set(len(binding.combat_targets()) for binding in scene.engine._actor_controls.values()))),
            native_simulation_extension_enabled=scene.engine._native_simulation is not None,
            worker_gun_class=type(scene.engine._gun_states[scene.actor_ids[0]]).__name__,
            schedule=schedule, simulated_step_seconds=step,
            control_hz=(10 if schedule == 'worker10' else 20),
            schedule_entry=('BotRuntime.update with real WORKER_CONTROL_SECONDS' if schedule == 'worker10'
                            else 'stress: _run_update_once refresh_control=True every .05s'),
            warmup_frames=warmup, measured_frames=frames,
            warmup_shots=warmup_shots, measured_shots=len(launches),
            measured_shots_by_actor=dict(collections.Counter(row['id'] for row in launches)),
            measured_shots_by_shell=dict(collections.Counter(row['shell_index'] for row in launches)),
            total_shots=len(scene.launches_observed),
            total_shots_by_actor=dict(collections.Counter(row['id'] for row in scene.launches_observed)),
            wall_ms=distribution([row['wall'] for row in measured], 1000.),
            cpu_ms=distribution([row['cpu'] for row in measured], 1000.),
            cold_wall_ms=distribution([row['wall'] for row in scene.frames[:warmup]], 1000.),
            evaluation_wall_ms=sum(value-warmup_evaluation_time.get(key, 0.)
                for key, value in scene.evaluation_seconds.items())*1000.,
            armour_batches=sum(binding.attack_policy.evaluator.cache_observations['armour_batches']
                - warmup_batches.get(actor, 0) for actor, binding in scene.engine._actor_controls.items()),
            workload=workload(measured, scene.actor_ids),
            final_actor_state={},
            max_actor_atomic_candidates=max(row['actors'][actor]['atomic_evaluations']
                for row in measured for actor in row['actors']),
            max_actor_atomic_world=max(row['actors'][actor]['atomic_world']
                for row in measured for actor in row['actors']),
            max_actor_atomic_armour=max(row['actors'][actor]['atomic_armor']
                for row in measured for actor in row['actors']))
        for actor, binding in scene.engine._actor_controls.items():
            candidate = binding.attack_policy.decision.get('candidate') or {}
            result['final_actor_state'][str(actor)] = dict(team=binding.actor_team,
                target=(candidate.get('target') or {}).get('network_id'),
                action=binding.attack_policy.decision.get('action'),
                reason=binding.attack_policy.decision.get('reason'),
                last_fire_failure=binding._last_fire_failure,
                search_started=binding.attack_policy.search_started,
                ammo=list(binding.gun.ammo), initial_ammo=scene.initial_ammo[actor],
                clip=binding.gun.clip, reload_seconds=binding.gun.reload_time,
                route=binding.state['route']['id'])
        receipts = [frame['work_budget'] for frame in measured if frame.get('work_budget')]
        waiting_runs = collections.Counter()
        longest_wait = 0
        for frame in measured:
            receipt = frame.get('work_budget')
            if receipt is None:
                raise AssertionError('physical owner did not expose the shared work budget')
            background = sum(value for (actor, channel, kind), value in frame['counts'].items()
                             if channel == 'background' and kind == 'candidate')
            if background > 8:
                raise AssertionError(('actual background candidate limit exceeded', background))
            for actor in scene.actor_ids:
                for channel, limit in (('foreground', 2), ('background', 2), ('atomic', 48)):
                    if frame['counts'].get((actor, channel, 'candidate'), 0) > limit:
                        raise AssertionError(('per-actor candidate limit exceeded', actor, channel))
                if actor in receipt['background_waiting']:
                    waiting_runs[actor] += 1
                    longest_wait = max(longest_wait, waiting_runs[actor])
                else:
                    waiting_runs[actor] = 0
        result['work_budget'] = dict(
            scope='one outer control callback, including all late physical slices',
            background_candidate_limit=8,
            max_background_granted=max([row['background_used'] for row in receipts] or [0]),
            max_atomic_actors=max([len(set(actor for (actor, channel, kind), value
                in frame['counts'].items() if channel == 'atomic' and kind == 'candidate' and value))
                for frame in measured] or [0]),
            background_actors_served=sorted(set(actor for row in receipts for actor in row['background_grants'])),
            longest_contiguous_background_wait_callbacks=longest_wait)
        if receipts:
            if result['work_budget']['max_background_granted'] > 8 or result['work_budget']['max_atomic_actors'] > 1:
                raise AssertionError('whole-roster optional-work budget exceeded')
            if enemies and set(result['work_budget']['background_actors_served']) != set(scene.actor_ids):
                raise AssertionError('not every active combat actor received optional-work service')
            if longest_wait > int(math.ceil(actors/4.)):
                raise AssertionError(('background requester starved', longest_wait))
        # Exactly match all authoritative ammunition debits to actual launch
        # records. A positive fire intent is never counted as a shot.
        for actor in scene.actor_ids:
            debits = collections.Counter(row['shell_index'] for row in scene.launches_observed if row['id'] == actor)
            actual = scene.engine._ammo_states[actor].remaining
            expected = [count-debits.get(slot, 0) for slot, count in enumerate(scene.initial_ammo[actor])]
            if list(actual) != expected:
                raise AssertionError(('unmatched native ammunition debit', actor, expected, actual))
        if enemies and not launches:
            raise AssertionError('engagement did not commit any native launch')
        if not enemies and (scene.launches_observed or result['workload']['queries']['candidate']['total']):
            raise AssertionError('no-enemy control performed combat work')
        result['ammo_accounting_verified'] = True
        return result
    finally:
        scene.doCleanups()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actors', type=int, default=29)
    parser.add_argument('--frames', type=int, default=60)
    parser.add_argument('--warmup', type=int, default=10)
    parser.add_argument('--schedule', choices=('stress20', 'worker10'), default='stress20')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 6 <= args.actors <= 29 or args.frames < 20 or args.warmup < 0:
        parser.error('use 6..29 actors, at least 20 measured frames, and nonnegative warmup')
    source = identity()
    cases = []
    for enemies in (False, True):
        result = run_case(args.actors, args.frames, args.warmup, enemies, args.schedule)
        cases.append(result)
        print('%s: %.3f ms wall mean, %.3f ms CPU mean, %s launches, %s armor batches' % (
            result['name'], result['wall_ms']['mean'], result['cpu_ms']['mean'],
            result['measured_shots'], result['armour_batches']), file=sys.stderr, flush=True)
    after = identity()
    report = dict(schema='shared-multi-bot-combat-v1', source_before=source,
        source_after=after, source_unchanged_during_run=source == after,
        environment=dict(python=platform.python_version(), architecture=platform.machine(),
                         logical_cpus=os.cpu_count()),
        scope='Real production shared controllers, native worker trigger/gun/ammo and reference motion; analytic visibility, flat ground, component boxes and rendered poses.',
        measured_pipeline='Shared server planner (1 Hz) plus full BotRuntime authority update; native pose fixture publication and result serialization excluded.',
        limitations=['Not a Windows BigWorld or GPU/FPS measurement.',
            'No real BSP or vehicle meshes: component and world calls are counted analytic geometry operations.',
            'No projectile flight/damage world integration; launches and native ammunition debits are real.',
            'Per-actor work limits do not establish a shared whole-roster wall-time budget.'],
        cases=cases, comparison=dict(
            engagement_extra_wall_ms=cases[1]['wall_ms']['mean']-cases[0]['wall_ms']['mean'],
            engagement_wall_ratio=cases[1]['wall_ms']['mean']/cases[0]['wall_ms']['mean']))
    payload = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding='utf-8')
    else:
        print(payload)
    return 0


if __name__ == '__main__':
    sys.exit(main())
