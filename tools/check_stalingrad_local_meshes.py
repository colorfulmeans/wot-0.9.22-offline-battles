"""Exercise refined city route edges through the compiled worker search."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src/res/scripts/client')]
from check_navigation_resolution import write_native_input
from build_stalingrad_local_meshes import PASSAGES
from gui.mods.offline_lan_0922 import bot_tactics,prebaked_navigation as pn


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-executable',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--map',choices=('92_stalingrad','14_siegfried_line'),default='92_stalingrad')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    graph=pn.with_shore_hazards(json.loads((ROOT/('navgraphs/'+args.map+'.json')).read_text()))
    passages=PASSAGES if args.map=='92_stalingrad' else [
        (tuple(row['start']),tuple(row['end'])) for row in graph['bake']['local_meshes']['corner_validation']]
    pairs=set()
    for first,last in passages:pairs.update(((tuple(first),tuple(last)),(tuple(last),tuple(first))))
    entry=bot_tactics.default_profile()['maps'][args.map]
    for route in entry['default_routes']+entry['routes']:
        if route.get('disabled'):continue
        for a,b in zip(route['points'],route['points'][1:]):
            pairs.update(((tuple(a[:2]),tuple(b[:2])),(tuple(b[:2]),tuple(a[:2]))))
    cases=sorted(pairs);path=args.output/'native-input.txt'
    write_native_input(path,graph,cases)
    report=json.loads(subprocess.check_output([str(args.native_executable.resolve()),str(path.resolve()),'--paths']))
    assert report['partial_or_empty']==0,report['incomplete_cases']
    returned={r['case']:r for r in report.pop('paths')}
    for a,b in passages:
        for start,end in ((a,b),(b,a)):
            points=returned[cases.index((tuple(start),tuple(end)))]['points']
            cost=sum(math.hypot(y[0]-x[0],y[2]-x[2]) for x,y in zip(points,points[1:]))
            assert cost < math.dist(start,end)*1.8+12.,(start,end,cost)
    report.update(map=args.map,unique_route_and_passage_edges=len(cases),all_reviewed_passages_local=True,
        local_samples=sum(p['width']*p['height'] for p in graph['local_meshes']),native_physics_tested=False)
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
