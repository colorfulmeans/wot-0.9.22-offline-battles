"""Move only unsafe retained Serene Coast slots onto nearby level ground."""
import argparse
import collections
import copy
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bake_navigation_0922 as baker
import build_local_navigation_meshes as geometry

ROOT = Path(__file__).resolve().parents[1]
MAX_SHIFT = 16.0
MAX_CENTRE_GRADE = math.tan(math.radians(6.0))
MAX_FOOTPRINT_GRADE = math.tan(math.radians(8.0))
MAX_HEIGHT_SPAN = 0.9


def footprint(pose, half_width, half_length, ground):
    x, unused_y, z, yaw = pose
    samples = []
    for along in (-half_length, -half_length / 2, 0., half_length / 2, half_length):
        row = []
        for across in (-half_width, 0., half_width):
            px = x + math.sin(yaw) * along + math.cos(yaw) * across
            pz = z + math.cos(yaw) * along - math.sin(yaw) * across
            row.append(ground(px, pz))
        samples.append(row)
    cross = [ground(x - 1., z), ground(x + 1., z),
             ground(x, z - 1.), ground(x, z + 1.)]
    if any(y is None for row in samples for y in row) or None in cross:
        return dict(clear=False, reason='missing_ground', samples=samples)
    centre_grade = math.hypot((cross[1]-cross[0])/2., (cross[3]-cross[2])/2.)
    grades = [abs(row[i+1]-row[i])/half_width for row in samples for i in (0, 1)]
    grades += [abs(samples[i+1][j]-samples[i][j])/(half_length/2.)
               for i in range(4) for j in range(3)]
    span = max(y for row in samples for y in row)-min(y for row in samples for y in row)
    return dict(clear=(centre_grade <= MAX_CENTRE_GRADE and
                      max(grades) <= MAX_FOOTPRINT_GRADE and span <= MAX_HEIGHT_SPAN),
                centre_slope_degrees=math.degrees(math.atan(centre_grade)),
                footprint_slope_degrees=math.degrees(math.atan(max(grades))),
                height_span=span, samples=samples)


def repair(graph, terrain, obstacles, legacy, envelope):
    result = copy.deepcopy(graph)
    hw, hl = envelope['half_width'], envelope['half_length']
    ground_cache = {}
    def ground(x, z):
        key = (x, z)
        if key not in ground_cache:
            ground_cache[key] = legacy._ground_height(terrain, obstacles, x, z)
        return ground_cache[key]
    size, width = graph['cell_size'], graph['width']
    def cell(x, z):
        ix = int(round((x-graph['origin'][0])/size))
        iz = int(round((z-graph['origin'][1])/size))
        return iz*width+ix if 0 <= ix < width and 0 <= iz < graph['height'] else None
    reverse = collections.defaultdict(list)
    for i, mask in enumerate(graph['links']):
        for bit, (dx, dz) in enumerate(graph['directions']):
            if mask & (1 << bit):
                reverse[i+dx+dz*width].append(i)
    reachable = {}
    for team in ('1', '2'):
        anchor = graph['spawn_anchors'][int(team)-1]
        start = cell(*anchor)
        seen = {start}; queue = collections.deque(seen)
        while queue:
            for other in reverse[queue.popleft()]:
                if other not in seen:
                    seen.add(other); queue.append(other)
        reachable[team] = seen
    def connected(pose, team):
        i = cell(pose[0], pose[2])
        return (i is not None and i in reachable[team] and
                graph['heights_mm'][i] is not None and not graph['hazards'][i] and
                bool(graph['links'][i]))
    all_slots = [(team, slot) for team in ('1', '2') for slot in range(15)]
    before = {(t, s): footprint(graph['spawn_formations'][t][s], hw, hl, ground)
              for t, s in all_slots}
    fixed = [(t, s, result['spawn_formations'][t][s]) for t, s in all_slots if before[t, s]['clear']]
    unsafe = [(t, s) for t, s in all_slots if not before[t, s]['clear']]
    candidates = {}
    for team, slot in unsafe:
        original = graph['spawn_formations'][team][slot]
        choices = []
        for dx in range(-16, 17, 2):
            for dz in range(-16, 17, 2):
                distance = math.hypot(dx, dz)
                if not 0. < distance <= MAX_SHIFT:
                    continue
                x, z = original[0]+dx, original[2]+dz
                y = ground(x, z)
                if y is None:
                    continue
                pose = [x, round(y, 4), z, original[3]]
                if not connected(pose, team) or not footprint(pose, hw, hl, ground)['clear']:
                    continue
                if baker.spawn_pose_blocked(obstacles, pose, hw, hl, legacy):
                    continue
                if any(math.hypot(x-p[0], z-p[2]) < baker.SPAWN_MINIMUM_SPACING or
                       baker.spawn_obbs_overlap(pose, p, hw, hl) for t, s, p in fixed):
                    continue
                choices.append((distance, pose))
        candidates[team, slot] = sorted(choices)
        if not choices:
            raise ValueError('No nearby level replacement: team %s slot %s' % (team, slot+1))
    # Keep every already level slot exact. Reconsider only the unsafe slots
    # when the nearest replacement conflicts with another replacement.
    def place(todo, selected):
        if not todo:
            return selected
        key = min(todo, key=lambda k: len(candidates[k]))
        for unused_distance, pose in candidates[key]:
            if any(math.hypot(pose[0]-p[0], pose[2]-p[2]) < baker.SPAWN_MINIMUM_SPACING or
                   baker.spawn_obbs_overlap(pose, p, hw, hl) for p in selected.values()):
                continue
            found = place([k for k in todo if k != key], selected | {key: pose})
            if found is not None:
                return found
        return None
    selected = place(unsafe, {})
    if selected is None:
        raise ValueError('No collision-free local formation repair')
    for (team, slot), pose in selected.items():
        result['spawn_formations'][team][slot] = pose
    failures = baker.spawn_clearance_failures(result['spawn_formations'], obstacles, envelope, legacy)
    if failures:
        raise ValueError(failures)
    audit = []
    for team, slot in all_slots:
        original = graph['spawn_formations'][team][slot]
        pose = result['spawn_formations'][team][slot]
        checked = footprint(pose, hw, hl, ground)
        if not checked['clear'] or not connected(pose, team):
            raise ValueError('Final slot failed full ground/connectivity audit')
        audit.append(dict(team=team, slot=slot+1, before=original, after=pose,
                          shift=math.hypot(pose[0]-original[0], pose[2]-original[2]),
                          ground_before=before[team, slot], ground_after=checked))
    if not selected:
        return result, audit
    result['validation']['spawn_level_ground_revalidation'] = dict(
        slots_checked=30, changes=[r for r in audit if r['shift']],
        maximum_shift_metres=MAX_SHIFT, centre_slope_limit_degrees=6.,
        footprint_slope_limit_degrees=8., height_span_limit_metres=MAX_HEIGHT_SPAN,
        vehicle_envelope=envelope, hard_and_soft_clearance=True,
        pairwise_clearance=True, directed_home_connection=True)
    previous = result.setdefault('navigation_previous_sha256s', [])
    previous.append(hashlib.sha256((ROOT/'navgraphs/47_canada_a.json').read_bytes()).hexdigest())
    return result, audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--client', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    geometry.EXTRA_REGIONS = ((-190, -345, -45, -240), (135, 255, 275, 355))
    terrain, obstacles, legacy = geometry.geometry(args.client, '47_canada_a')
    envelope = baker.representative_vehicle_chassis_envelope(args.client)
    graph = json.loads((ROOT/'navgraphs/47_canada_a.json').read_bytes())
    result, audit = repair(graph, terrain, obstacles, legacy, envelope)
    for key in graph:
        if key not in ('spawn_formations', 'validation', 'navigation_previous_sha256s'):
            assert result[key] == graph[key], key
    legacy.validate_graph(result, dict(bases=result['bases']))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'47_canada_a.json').write_bytes((json.dumps(result, sort_keys=True, separators=(',', ':'))+'\n').encode())
    (args.output/'audit.json').write_text(json.dumps(audit, indent=2))
    for row in audit:
        print(row['team'], row['slot'], row['shift'], row['after'], flush=True)


if __name__ == '__main__':
    main()
