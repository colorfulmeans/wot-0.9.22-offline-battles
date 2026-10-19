"""Revalidate retained railway-map spawn slots without rebaking navigation."""
import argparse, collections, copy, hashlib, json, math, sys, zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import repair_railway_navigation_0922 as railway
import bake_navigation_0922 as baker


def repair_spawns(graph, obstacles, envelope, legacy):
    result = copy.deepcopy(graph)
    width, size = graph['width'], graph['cell_size']
    half_width, half_length = envelope['half_width'], envelope['half_length']
    reverse = collections.defaultdict(list)
    for i, mask in enumerate(graph['links']):
        if graph['heights_mm'][i] is None:
            continue
        x, z = i % width, i // width
        for bit, (dx, dz) in enumerate(graph['directions']):
            if mask & (1 << bit):
                nx, nz = x+dx, z+dz
                if 0 <= nx < width and 0 <= nz < graph['height']:
                    reverse[nz*width+nx].append(i)
    def cell(pose):
        x = int(round((pose[0]-graph['origin'][0])/size))
        z = int(round((pose[2]-graph['origin'][1])/size))
        return z*width+x
    nodes = [[graph['origin'][0]+i%width*size, y/1000.,
              graph['origin'][1]+i//width*size] for i,y in enumerate(graph['heights_mm'])
             if y is not None and not graph['hazards'][i] and graph['links'][i]]
    reachable = {}
    for team in ('1','2'):
        anchor = graph['spawn_anchors'][int(team)-1]
        point = min(nodes, key=lambda p:(p[0]-anchor[0])**2+(p[2]-anchor[1])**2)
        seen = {cell(point)}; queue = collections.deque(seen)
        while queue:
            for other in reverse[queue.popleft()]:
                if other not in seen:
                    seen.add(other); queue.append(other)
        reachable[team] = seen
    all_poses = [(team, slot, pose) for team, poses in result['spawn_formations'].items()
                 for slot,pose in enumerate(poses)]
    def clear(pose, team, slot):
        return (cell(pose) in reachable[team] and
            not baker.spawn_pose_blocked(obstacles, pose, half_width, half_length, legacy) and
            all((t == team and s == slot) or
                (math.hypot(pose[0]-p[0],pose[2]-p[2]) >= baker.SPAWN_MINIMUM_SPACING and
                 not baker.spawn_obbs_overlap(pose,p,half_width,half_length))
                for t,s,p in all_poses))
    changes = []
    for team, slot, original in list(all_poses):
        if clear(original, team, slot):
            continue
        candidates = sorted(nodes, key=lambda p:((p[0]-original[0])**2+(p[2]-original[2])**2,p))
        chosen = next((p+[original[3]] for p in candidates
            if math.hypot(p[0]-original[0],p[2]-original[2]) <= baker.SPAWN_MAXIMUM_PROJECTION
            and clear(p+[original[3]],team,slot)), None)
        if chosen is None:
            raise ValueError('%s team %s slot %s: no fully verified replacement' % (graph['map'],team,slot))
        result['spawn_formations'][team][slot] = chosen
        all_poses = [(t,s,chosen if (t,s)==(team,slot) else p) for t,s,p in all_poses]
        changes.append(dict(team=team,slot=slot,before=original,after=chosen))
    failures = baker.spawn_clearance_failures(result['spawn_formations'],obstacles,envelope,legacy)
    assert not failures, failures
    assert all(cell(p) in reachable[t] for t,s,p in all_poses)
    result['validation']['spawn_railway_revalidation'] = dict(
        slots_checked=len(all_poses), changes=changes, vehicle_envelope=envelope,
        hard_and_soft_clearance=True, pairwise_clearance=True,
        directed_home_connection=True)
    result['validation'].update(
        spawn_vehicle_half_width_metres=half_width,
        spawn_vehicle_half_length_metres=half_length,
        spawn_vehicle_bounds_source=envelope['source'],
        spawn_vehicle_width_source=envelope['width_source'],
        spawn_vehicle_length_source=envelope['length_source'],
        spawn_vehicle_resources_scanned=envelope['resources_scanned'],
        spawn_soft_destructible_obb_clearance=True,
        spawn_minimum_spacing_metres=min(math.hypot(a[2][0]-b[2][0],a[2][2]-b[2][2])
            for index,a in enumerate(all_poses) for b in all_poses[index+1:] if a[0]==b[0]),
        spawn_minimum_team_separation_metres=min(math.hypot(a[2][0]-b[2][0],a[2][2]-b[2][2])
            for index,a in enumerate(all_poses) for b in all_poses[index+1:] if a[0]!=b[0]),
        spawn_projection_reference='retained slot before railway revalidation',
        spawn_maximum_projection_metres=max([0.]+[
            math.hypot(row['after'][0]-row['before'][0],row['after'][2]-row['before'][2])
            for row in changes]))
    result.setdefault('navigation_previous_sha256s',[]).append(hashlib.sha256(
        json.dumps(graph,sort_keys=True,separators=(',',':')).encode()).hexdigest())
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--client',required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    envelope=baker.representative_vehicle_chassis_envelope(args.client)
    vfs=baker.PackageVFS(str(Path(args.client)/'res/packages'));legacy=baker._legacy_baker()
    report=[]
    try:
        for path in sorted((railway.ROOT/'navgraphs').glob('*.json')):
            graph=json.loads(path.read_text())
            if not graph.get('bake',{}).get('railway_obstacles'):
                continue
            print('Checking '+path.stem,flush=True)
            with zipfile.ZipFile(Path(args.client)/'res/packages'/(path.stem+'.pkg')) as z:
                unused,compiled=baker._compiled_models(z.read('spaces/'+path.stem+'/space.bin'))
            field=baker.compiled_navigation_obstacles(compiled,vfs,legacy)
            result=repair_spawns(graph,field,envelope,legacy)
            result['navigation_previous_sha256s'][-1] = hashlib.sha256(path.read_bytes()).hexdigest()
            for key in ('routes','heights_mm','links','hazards','local_meshes'):
                assert result.get(key)==graph.get(key),key
            validation=legacy.validate_graph(result,dict(bases=result['bases']))
            (args.output/path.name).write_text(json.dumps(result,sort_keys=True,separators=(',',':'))+'\n')
            row=dict(map=path.stem,spawn=result['validation']['spawn_railway_revalidation'],routes=validation)
            report.append(row);print(path.stem+' changed '+str(len(row['spawn']['changes'])),flush=True)
    finally:
        vfs.close()
        (args.output/'validation.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':main()
