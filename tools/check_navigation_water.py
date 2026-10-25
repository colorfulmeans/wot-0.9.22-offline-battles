"""Audit all refreshed water layers and compare complete shipping C++ searches."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_navigation_resolution import write_native_input


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--native-executable',type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    for path in sorted(Path('navgraphs').glob('*.json')):
        new=json.loads(path.read_bytes())
        if 'heights_mm' not in new:continue
        old=json.loads(subprocess.check_output(['git','show',args.baseline_ref+':'+path.as_posix()]))
        for key in ('routes','spawn_formations','spawn_anchors','bases','objective_bases','bounds',
                    'cell_size','origin','width','height'):
            assert old.get(key)==new.get(key),(path.stem,key)
        assert new['bake']['water_depth_limit']==new['bake']['shallow_water_threshold']==1.2
        receipts=new['bake']['water_policy_rebake']
        before_layers=[old]+old.get('local_meshes',[])
        after_layers=[new]+new.get('local_meshes',[])
        assert len(before_layers)<=len(after_layers)
        # Later screenshot-local meshes do not replace a water-rebaked layer.
        # Keep every original receipt comparison, then validate the additive
        # layers separately using their exact-client measurement contract.
        extra=after_layers[len(before_layers):]
        if extra:
            meta=new['bake']['local_meshes']
            assert meta['base_geometry_unchanged'] is True
            assert meta['water_depth_limit']==1.2
            assert meta['source']=='exact_0922_client_compiled_geometry'
            assert meta['collision_edge_sample_metres']==.25
            assert meta['measured_local_cells']==sum(len(p['heights_mm']) for p in new['local_meshes'])
            from gui.mods.offline_lan_0922.navigation_graph_schema import validate_graph
            validate_graph(new,path.stem)
        for before,after,receipt in zip(before_layers,after_layers,[receipts['base']]+receipts['local_layers']):
            assert receipt['cells_measured']==len(after['heights_mm'])
            assert all(h is None or h==after['heights_mm'][i] for i,h in enumerate(before['heights_mm']))
            assert all(v&after['links'][i]==v for i,v in enumerate(before['links']))
            changed=[i for i in range(len(after['heights_mm'])) if any(
                before[k][i]!=after[k][i] for k in ('heights_mm','links','hazards'))]
            assert changed==receipt['changed_indices'],(path.stem,'incomplete change receipt')
        cases=set()
        for routes in new['routes'].values():
            for route in routes:
                cases.update((tuple(a[:2]),tuple(b[:2])) for a,b in zip(route['waypoints'],route['waypoints'][1:]))
        # Include the actual adopted, class-specific defaults, independently
        # of the original coarse route sketches retained in the graph.
        from gui.mods.offline_lan_0922 import bot_tactics
        for route in bot_tactics.default_map(path.stem).get('default_routes',()):
            if not route.get('disabled'):
                cases.update((tuple(a[:2]),tuple(b[:2])) for a,b in zip(route['points'],route['points'][1:]))
        cases=sorted(cases)
        result=dict(map=path.stem,cases=len(cases),native_gameplay_tested=False)
        if args.native_executable:
            for name,graph in (('before',old),('after',new)):
                filename=args.output/(path.stem+'-'+name+'.txt')
                write_native_input(filename,graph,cases)
                proof=json.loads(subprocess.check_output([str(args.native_executable.resolve()),str(filename.resolve()),'--complete']))
                if proof['partial_or_empty']:
                    raise AssertionError((path.stem,name,proof['incomplete_cases']))
                result[name]=proof
        results.append(result)
        print(path.stem,len(cases),'retained route/default segments verified',flush=True)
    assert len(results)==41
    (args.output/'report.json').write_text(json.dumps(results,indent=2)+'\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
