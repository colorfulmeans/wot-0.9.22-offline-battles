"""Prove the added city bridge against exact terrain, collision and water."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src/res/scripts/client')]
import build_local_navigation_meshes as meshes
from build_windstorm_middle_mesh import REGION
from gui.mods.offline_lan_0922 import prebaked_navigation as pn
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid

CASES = (((94., -9., -172.), (148., -9., -150.)),
         ((98., -9., -174.), (144., -9., -146.)),
         ((100., -9., -168.), (142., -9., -154.)))


def verify(client, output, search_report=None):
    source = json.loads((ROOT/'navgraphs/84_winter.json').read_bytes())
    old = json.loads(subprocess.check_output(['git', 'show', '09b87889:navgraphs/84_winter.json'], cwd=ROOT))
    for field in ('cell_size', 'origin', 'width', 'height', 'heights_mm', 'hazards',
                  'routes', 'spawn_formations', 'spawn_anchors', 'objective_bases'):
        assert source[field] == old[field], field
    assert source['local_meshes'][:2] == old['local_meshes']
    expected = list(old['links'])
    for i, bit in source['bake']['local_meshes']['middle_bridge']['coarse_links_refined']:
        expected[i] &= ~(1 << bit)
    assert source['links'] == expected
    meshes.EXTRA_REGIONS = (REGION,)
    terrain, obstacles, legacy = meshes.geometry(client, '84_winter')
    graph = pn.with_shore_hazards(source)
    grid = TerrainGrid(lambda *a: None, baked_graph=graph)
    results = []
    paths = [(start, end, None) for a,b in CASES for start,end in ((a,b),(b,a))]
    if search_report:
        report = json.loads(Path(search_report).read_bytes())["current"]
        wanted = set((a[0],a[2],b[0],b[2]) for a,b in CASES)
        wanted |= set((c,d,a,b) for a,b,c,d in tuple(wanted))
        for row in report["native"]["paths"]:
            case = report["python"][row["case"]]
            a,b = case["start"],case["end"]
            if (a[0],a[1],b[0],b[1]) in wanted:
                paths.append(((a[0],-9.,a[1]),(b[0],-9.,b[1]),row["points"]))
        assert len(paths) == 12, "Both native bridge directions must be present"
    for start, end, supplied_path in paths:
        before = time.perf_counter()
        path = supplied_path if supplied_path is not None else grid.plan(start, end, max_expansions=20000)
        elapsed = (time.perf_counter()-before)*1000.
        assert path and math.hypot(path[-1][0]-end[0], path[-1][2]-end[2]) < 2., (start, end, path)
        length = sum(math.hypot(q[0]-p[0], q[2]-p[2]) for p, q in zip(path, path[1:]))
        assert length < math.hypot(end[0]-start[0], end[2]-start[2])*1.8+12., length
        samples, max_depth = 0, 0.
        for first, last in zip(path, path[1:]):
            assert grid.segment_clear(first, last)
            assert not grid.segment_has_motion_hazard(first, last, 13)
            distance = math.hypot(last[0]-first[0], last[2]-first[2])
            yaw = math.atan2(last[0]-first[0], last[2]-first[2])
            for n in range(max(1, int(math.ceil(distance/.25)))+1):
                t = n/max(1, int(math.ceil(distance/.25)))
                x, z = first[0]+(last[0]-first[0])*t, first[2]+(last[2]-first[2])*t
                y = legacy._ground_height(terrain, obstacles, x, z)
                assert y is not None
                for width in (1.2, 1.8, 2.15):
                    assert not obstacles.blocked(x, z, y, margin=width), ('collision', x, z, width)
                    for along in (-3.2, 0., 3.2):
                        for across in (-width, 0., width):
                            sx = x+math.sin(yaw)*along+math.cos(yaw)*across
                            sz = z+math.cos(yaw)*along-math.sin(yaw)*across
                            support = legacy._ground_height(terrain, obstacles, sx, sz)
                            assert support is not None, ('support', x, z, sx, sz, width)
                            depth = terrain.water_depth(sx, sz, support)
                            assert depth <= legacy.WATER_DEPTH_LIMIT, ('deep', x, z, sx, sz, width, depth)
                            max_depth = max(max_depth, depth)
                samples += 1
        results.append(dict(start=start, end=end, path=path, length=length,
                            plan_ms=elapsed, samples=samples, maximum_support_depth=max_depth,
                            search="native" if supplied_path is not None else "python"))
    patch = graph['local_meshes'][2]
    rejected = {1: 0, 8: 0}
    for i, mask in enumerate(patch['hazards']):
        p = (patch['origin'][0]+i%patch['width']*patch['cell_size'], 0., patch['origin'][1]+i//patch['width']*patch['cell_size'])
        for flag in rejected:
            if mask & flag:
                assert not pn.pose_is_safe(graph, p, hazard_mask=9)
                rejected[flag] += 1
    assert all(rejected.values())
    result = dict(cases=results, rejected=rejected, previous_meshes_unchanged=True,
                  routes_unchanged=True, native_gameplay_tested=False)
    Path(output).write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(dict(cases=len(results), samples=sum(r['samples'] for r in results),
        maximum_plan_ms=max(r['plan_ms'] for r in results), rejected=rejected)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--search-report')
    args = parser.parse_args()
    verify(args.client, args.output, args.search_report)
