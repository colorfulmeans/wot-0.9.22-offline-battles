"""Check the reported exit and two-way bridge paths against exact client BSP."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src/res/scripts/client')]
import build_local_navigation_meshes as meshes
from build_windstorm_bridge_mesh import REGION
from gui.mods.offline_lan_0922 import prebaked_navigation as pn
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid


def verify(client, output, baseline):
    raw = (ROOT/'navgraphs/84_winter.json').read_bytes()
    source = json.loads(raw)
    old = json.loads(subprocess.check_output(
        ['git', 'show', baseline+':navgraphs/84_winter.json'], cwd=ROOT))
    for field in ('cell_size', 'origin', 'width', 'height', 'heights_mm',
                  'hazards', 'routes', 'spawn_formations', 'spawn_anchors', 'objective_bases'):
        assert source[field] == old[field], field
    expected_links = list(old['links'])
    regions = source['bake']['local_meshes']['regions']
    for index, bit in source['bake']['local_meshes']['refined_coarse_links']:
        expected_links[index] &= ~(1 << bit)
        x = source['origin'][0]+index%source['width']*source['cell_size']
        z = source['origin'][1]+index//source['width']*source['cell_size']
        assert any(left-4 <= x <= right+4 and bottom-4 <= z <= top+4
                   for left, bottom, right, top in regions)
    assert expected_links == source['links']
    meshes.EXTRA_REGIONS = (REGION,)
    terrain, obstacles, legacy = meshes.geometry(client, '84_winter')
    graph = pn.with_shore_hazards(source)
    grid = TerrainGrid(lambda *args: None, baked_graph=graph)
    origin = (126.7290046558638, -8.950407028198242, -276.07781896536494)
    yaw, distance = 1.654004054630426, 3.1200008771171768
    end = (origin[0]+math.sin(yaw)*distance, origin[1], origin[2]+math.cos(yaw)*distance)
    cases = [(origin, end), ((120., -9., -280.), (200., -9., -244.)),
             ((126., -9., -278.), (194., -9., -250.)),
             ((127., -9., -276.), (190., -9., -250.))]
    records = []
    for number, (a, b) in enumerate(cases):
        for start, finish in ((a, b), (b, a)):
            before = time.perf_counter()
            path = (start, finish) if number == 0 else grid.plan(start, finish, max_expansions=20000)
            elapsed = (time.perf_counter()-before)*1000.
            assert path and math.hypot(path[-1][0]-finish[0], path[-1][2]-finish[2]) < 2.
            samples = []
            for first, last in zip(path, path[1:]):
                assert not grid.segment_has_motion_hazard(first, last, 1|4|8), (first, last)
                assert grid.segment_clear(first, last), (first, last)
                steps = max(1, int(math.ceil(math.hypot(last[0]-first[0], last[2]-first[2])/.25)))
                for step in range(steps+1):
                    point = tuple(first[k]+(last[k]-first[k])*step/steps for k in range(3))
                    x, z = point[0], point[2]
                    ground = legacy._ground_height(terrain, obstacles, x, z)
                    assert ground is not None and terrain.water_depth(x, z, ground) <= legacy.WATER_DEPTH_LIMIT
                    assert pn.pose_is_safe(graph, point, hazard_mask=1|8), point
                    for half_width in (1.2, 1.8, 2.15):
                        assert not obstacles.blocked(x, z, ground, margin=half_width), (point, half_width)
                    samples.append(point)
            records.append(dict(case=number, start=start, end=finish, path=path,
                                samples=len(samples), plan_ms=round(elapsed, 4)))
    # Confirm rejection is not globally removed around the new bridge patch.
    rejected = {1: 0, 8: 0}
    patch = graph['local_meshes'][0]
    for i, hazard in enumerate(patch['hazards']):
        point = (patch['origin'][0]+i%patch['width'], 0., patch['origin'][1]+i//patch['width'])
        for flag in rejected:
            if hazard & flag:
                assert not pn.pose_is_safe(graph, point, hazard_mask=1|8)
                rejected[flag] += 1
    assert all(rejected.values())
    result = dict(map='84_winter', graph_sha256=hashlib.sha256(raw).hexdigest(),
                  baseline=baseline, coarse_heights_hazards_unchanged=True, routes_unchanged=True,
                  refined_coarse_links=len(source['bake']['local_meshes']['refined_coarse_links']),
                  native_gameplay_tested=False, exact_client_geometry=True,
                  sample_spacing_metres=.25, half_widths=[1.2, 1.8, 2.15],
                  two_way_cases=records, rejected_water_and_shore_cells=rejected)
    Path(output).write_bytes(json.dumps(result, indent=2).encode())
    print(json.dumps(dict(cases=len(records), samples=sum(r['samples'] for r in records),
                         rejected=rejected, output=output)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--baseline', default='346ae477')
    args = parser.parse_args()
    verify(args.client, args.output, args.baseline)
