"""Prove north bridge/bank paths on exact geometry, including full hull support."""
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
from build_windstorm_north_mesh import REGION, ORIGIN, YAW, BASELINE
from gui.mods.offline_lan_0922 import prebaked_navigation as pn
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid

SHAPES = (('narrow', 1.2, 3.2),
          ('reported_emil', 1.300434947013855, 2.9308600425720215),
          ('medium', 1.8, 3.2), ('wide', 2.15, 3.2))


def verify(client, output):
    raw = (ROOT/'navgraphs/84_winter.json').read_bytes()
    source = json.loads(raw)
    old = json.loads(subprocess.check_output(['git', 'show', BASELINE+':navgraphs/84_winter.json'], cwd=ROOT))
    for key in ('cell_size', 'origin', 'width', 'height', 'heights_mm', 'hazards',
                'routes', 'spawn_formations', 'spawn_anchors', 'objective_bases'):
        assert source[key] == old[key], key
    assert source['local_meshes'][0] == old['local_meshes'][0]
    expected = list(old['links'])
    for index, bit in source['bake']['local_meshes']['north_bridge']['coarse_links_refined']:
        expected[index] &= ~(1 << bit)
    assert expected == source['links']
    meshes.EXTRA_REGIONS = (REGION,)
    terrain, obstacles, legacy = meshes.geometry(client, '84_winter')
    graph = pn.with_shore_hazards(source)
    grid = TerrainGrid(lambda *a: None, baked_graph=graph)
    cases = []
    for distance in (.5, 3.4308600425720215):
        end = (ORIGIN[0]+math.sin(YAW)*distance, ORIGIN[1], ORIGIN[2]+math.cos(YAW)*distance)
        cases.append(('recorded_exit_'+str(distance), ORIGIN, end, True))
    cases += [('bridge', (282., -12., 250.), (216., -11., 210.), False),
              ('bank', (282., -15., 220.), (272., -15., 220.), False),
              ('reported_route', ORIGIN, (217.724, -11., 216.479), False),
              ('reported_authored_leg', (279.912, -12., 248.157), (217.724, -11., 216.479), False),
              ('bank_to_mouth', ORIGIN, (276., -12., 244.), False),
              ('south_shoal', (306., -14., 189.), (264., -14., 189.), False),
              ('shoal_east_approach', (390., -10., 238.), (306., -14., 189.), False),
              ('shoal_heavy_west_exit', (264., -14., 189.), (201.8841, -11., 207.3365), False),
              ('shoal_medium_west_exit', (264., -14., 189.), (201.668, -11., 208.1516), False)]
    records = []
    for name, a, b, direct in cases:
        for start, finish in ((a, b), (b, a)):
            before = time.perf_counter()
            path = (start, finish) if direct else grid.plan(start, finish, max_expansions=20000)
            elapsed = (time.perf_counter()-before)*1000.
            assert path and math.hypot(path[-1][0]-finish[0], path[-1][2]-finish[2]) < 2., (name, path)
            length = sum(math.hypot(q[0]-p[0], q[2]-p[2]) for p, q in zip(path, path[1:]))
            assert length < math.hypot(finish[0]-start[0], finish[2]-start[2])*1.8+12., (name, 'remote_detour', length)
            assert name == 'shoal_east_approach' or all(REGION[0]-4 <= p[0] <= REGION[2]+4 and
                       REGION[1]-4 <= p[2] <= REGION[3]+4 for p in path), (name, 'left_local_region')
            count, maximum_depth = 0, 0.
            for first, last in zip(path, path[1:]):
                assert grid.segment_clear(first, last), (name, first, last)
                assert not grid.segment_has_motion_hazard(first, last, 13), (name, first, last)
                distance = math.hypot(last[0]-first[0], last[2]-first[2])
                steps = max(1, int(math.ceil(distance/.25)))
                yaw = math.atan2(last[0]-first[0], last[2]-first[2])
                for n in range(steps+1):
                    x, z = first[0]+(last[0]-first[0])*n/steps, first[2]+(last[2]-first[2])*n/steps
                    y = legacy._ground_height(terrain, obstacles, x, z)
                    assert y is not None
                    assert pn.pose_is_safe(graph, (x, y, z), hazard_mask=9), (name, x, z)
                    for vehicle, width, half_length in SHAPES:
                        assert not obstacles.blocked(x, z, y, margin=width), (name, 'collision', x, z, width)
                        # Sample a full 6.4 m chassis support rectangle, including
                        # longitudinal ends and both actual-width shoulders.
                        for along in (-half_length, 0., half_length):
                            for across in (-width, 0., width):
                                sx = x+math.sin(yaw)*along+math.cos(yaw)*across
                                sz = z+math.cos(yaw)*along-math.sin(yaw)*across
                                ground = legacy._ground_height(terrain, obstacles, sx, sz)
                                assert ground is not None, (name, 'support', sx, sz, width)
                                depth = terrain.water_depth(sx, sz, ground)
                                assert depth <= legacy.WATER_DEPTH_LIMIT, (name, 'deep_support', x, z, sx, sz, width, depth)
                                maximum_depth = max(maximum_depth, depth)
                    count += 1
            records.append(dict(name=name, start=start, end=finish, path=path, samples=count,
                                plan_ms=elapsed, maximum_support_water_depth=maximum_depth))
    rejected = {1: 0, 8: 0}
    patch = graph['local_meshes'][1]
    for i, flag in enumerate(patch['hazards']):
        point = (patch['origin'][0]+i%patch['width'], 0., patch['origin'][1]+i//patch['width'])
        for mask in rejected:
            if flag & mask:
                assert not pn.pose_is_safe(graph, point, hazard_mask=9)
                rejected[mask] += 1
    assert all(rejected.values())
    result = dict(graph_sha256=hashlib.sha256(raw).hexdigest(), baseline=BASELINE,
                  south_mesh_unchanged=True, routes_unchanged=True, native_gameplay_tested=False,
                  sample_spacing_metres=.25, half_widths=[1.2, 1.8, 2.15], chassis_length=6.4,
                  vehicle_shapes=SHAPES,
                  cases=records, rejected_water_and_shore_cells=rejected)
    Path(output).write_bytes(json.dumps(result, indent=2).encode())
    print(json.dumps(dict(cases=len(records), samples=sum(r['samples'] for r in records),
                         maximum_support_water_depth=max(r['maximum_support_water_depth'] for r in records), rejected=rejected)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    verify(args.client, args.output)
