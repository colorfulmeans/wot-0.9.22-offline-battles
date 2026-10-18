"""Compare selected grids using preserved routes and the shipping C++ search."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import time

import bake_navigation_0922 as baker

MAPS = ('04_himmelsdorf', '86_himmelsdorf_winter')
NARROWS = (((182.606, 43.685), (175.887, 87.135)),
           ((175.887, 87.135), (180.55, 116.688)))


def route_cases(graph):
    pairs = set()
    for routes in graph['routes'].values():
        for route in routes:
            points = route['waypoints']
            pairs.update((tuple(a[:2]), tuple(b[:2]))
                         for a, b in zip(points, points[1:]))
    for a, b in NARROWS:
        pairs.update(((a, b), (b, a)))
    return sorted(pairs)


def inspect(graph, cases):
    legacy = baker._legacy_baker()
    rows = []
    for start, end in cases:
        first, offset_a = legacy._nearest_node(graph, start)
        last, offset_b = legacy._nearest_node(graph, end)
        before = time.perf_counter()
        path, distance = legacy._graph_path(graph, first, last)
        rows.append(dict(start=start, end=end, connected=bool(path),
                         length=distance, nodes=len(path),
                         snap_offsets=[offset_a, offset_b],
                         reference_ms=(time.perf_counter()-before)*1000))
    return rows


def write_native_input(path, graph, cases):
    header = [graph['width'], graph['height']] + list(graph['origin']) + [
        graph['cell_size'], graph['bake']['max_grade']] + graph['bounds']
    rows = [' '.join(map(str, header))]
    for h, links, hazard in zip(graph['heights_mm'], graph['links'], graph['hazards']):
        rows.append('%s %s %s' % (-999999 if h is None else h/1000., links, hazard))
    rows.append(str(len(cases)))
    for a, b in cases:
        rows.append(' '.join(map(str, a+b)))
    path.write_text('\n'.join(rows)+'\n', encoding='ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--native-executable', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = dict(native_gameplay_tested=False, maps={})
    for name in MAPS:
        raw = subprocess.check_output(['git', 'show', args.baseline_ref+':navgraphs/'+name+'.json'])
        old = json.loads(raw)
        new = json.loads(Path('navgraphs', name+'.json').read_bytes())
        from rebake_navigation_resolution import GAMEPLAY_FIELDS
        for key in GAMEPLAY_FIELDS:
            assert old.get(key) == new.get(key), (name, key)
        cases = route_cases(old)
        report['maps'][name] = {}
        for tag, graph in [('4m', old), ('2m', new)]:
            rows = inspect(graph, cases)
            assert all(row['connected'] for row in rows), (name, tag)
            native_input = args.output/(name+'-'+tag+'.txt')
            write_native_input(native_input, graph, cases)
            item = dict(cells=graph['width']*graph['height'], routes=rows,
                        reversible_links=True)
            # Check every directed graph edge, not only sampled route paths.
            for index, mask in enumerate(graph['links']):
                for bit, (dx, dz) in enumerate(graph['directions']):
                    if mask & (1 << bit):
                        neighbor = index + dx + dz*graph['width']
                        reverse = graph['directions'].index([-dx, -dz])
                        assert graph['links'][neighbor] & (1 << reverse)
            if args.native_executable:
                item['native'] = json.loads(subprocess.check_output([
                    str(args.native_executable.resolve()), str(native_input.resolve())]))
            report['maps'][name][tag] = item
        print(name, 'all', len(cases), 'preserved route cases connected in both grids')
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
