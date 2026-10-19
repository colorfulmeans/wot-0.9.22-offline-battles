"""Mask solid railway stock in retained graphs without rebaking roads."""
import argparse,copy,hashlib,json,math,sys,types,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src/res/scripts/client')]
import bake_navigation_0922 as baker
from gui.mods.offline_lan_0922.scenery_policy import railway_vehicle_resource


def railway_geometry(client,name):
    with zipfile.ZipFile(Path(client)/'res/packages'/(name+'.pkg')) as z:
        unused,compiled=baker._compiled_models(z.read('spaces/'+name+'/space.bin'))
    bsmo=compiled.sections['BSMO']._data;strings=compiled.sections['BWST'];bsm=compiled.sections['BSMI']
    ids=list(bsm.model_ids());data=bsm._data
    selected=[i for i,m in enumerate(ids) if railway_vehicle_resource(strings.get(bsmo['models_colliders'][m]['bsp_section_name_fnv']))]
    sections=dict(compiled.sections)
    sections['BSMI']=types.SimpleNamespace(_data=dict(transforms=[data['transforms'][i] for i in selected],visibility_masks=[data['visibility_masks'][i] for i in selected]),model_ids=lambda:iter(ids[i] for i in selected))
    legacy=baker._legacy_baker();vfs=baker.PackageVFS(str(Path(client)/'res/packages'))
    try:field=baker.compiled_navigation_obstacles(types.SimpleNamespace(sections=sections),vfs,legacy)
    finally:vfs.close()
    return field,legacy,len(selected)


def mask_layer(layer,directions,field,legacy):
    width,height=layer['width'],layer['height'];size=layer['cell_size'];origin=layer['origin'];heights=layer['heights_mm'];links=layer['links']
    def point(i):return (origin[0]+i%width*size,heights[i]/1000.,origin[1]+i//width*size)
    # Conservative broad phase only: exact height/disk checks still decide.
    if not hasattr(field,'railway_query_cells'):
        radius=int(math.ceil(legacy.VEHICLE_HALF_WIDTH/field.raster_size))
        field.railway_query_cells=set((x+dx,z+dz) for x,z in field.cells
            for dx in range(-radius,radius+1) for dz in range(-radius,radius+1))
    def railway_blocked(x,z,y,margin):
        key=(int(math.floor(x/field.raster_size)),int(math.floor(z/field.raster_size)))
        return key in field.railway_query_cells and field.blocked(x,z,y,margin=margin)
    removed=set(i for i,y in enumerate(heights) if y is not None and railway_blocked(*((point(i)[0],point(i)[2],point(i)[1])),margin=legacy.VEHICLE_HALF_WIDTH))
    oldlinks=list(links)
    extent=(min(x for x,z in field.cells)*field.raster_size-legacy.VEHICLE_HALF_WIDTH-size*2,
            max(x for x,z in field.cells)*field.raster_size+legacy.VEHICLE_HALF_WIDTH+size*3,
            min(z for x,z in field.cells)*field.raster_size-legacy.VEHICLE_HALF_WIDTH-size*2,
            max(z for x,z in field.cells)*field.raster_size+legacy.VEHICLE_HALF_WIDTH+size*3) if field.cells else None
    for i in removed:heights[i]=None;links[i]=0
    checks=0
    for i,mask in enumerate(oldlinks):
        if heights[i] is None:continue
        px,py,pz=point(i)
        if extent is None or not(extent[0]<=px<=extent[1] and extent[2]<=pz<=extent[3]):continue
        x,z=i%width,i//width
        for bit,(dx,dz) in enumerate(directions):
            if not mask&(1<<bit):continue
            nx,nz=x+dx,z+dz;j=nz*width+nx
            blocked=not(0<=nx<width and 0<=nz<height) or heights[j] is None
            if not blocked and dx and dz:blocked=z*width+nx in removed or nz*width+x in removed
            if not blocked:
                a,b=point(i),point(j);steps=max(1,int(math.ceil(size*math.hypot(dx,dz)/.25)))
                for step in range(steps+1):
                    f=step/steps;checks+=1
                    if railway_blocked(a[0]+(b[0]-a[0])*f,a[2]+(b[2]-a[2])*f,a[1]+(b[1]-a[1])*f,margin=legacy.VEHICLE_HALF_WIDTH):blocked=True;break
            if blocked:links[i]&=~(1<<bit)
    return dict(removed_nodes=len(removed),removed_node_indices=sorted(removed),removed_directed_links=sum(bin(a).count('1')-bin(b).count('1') for a,b in zip(oldlinks,links)),sample_checks=checks)


def repair(graph,field,legacy):
    result=copy.deepcopy(graph);directions=[tuple(v) for v in graph['directions']]
    report=[mask_layer(layer,directions,field,legacy) for layer in [result]+result.get('local_meshes',[])]
    assert result['routes']==graph['routes']
    previous=(graph.get('bake',{}).get('railway_obstacles') or {}).get('layers',[])
    if previous and len(previous)!=len(report):raise ValueError('railway layer layout changed')
    if previous:
        if all(not r['removed_nodes'] and not r['removed_directed_links'] for r in report):
            return result
        for row,old in zip(report,previous):
            row['removed_node_indices']=sorted(set(row['removed_node_indices'])|set(old['removed_node_indices']))
            row['removed_nodes']=len(row['removed_node_indices'])
            row['removed_directed_links']+=old['removed_directed_links']
    result['bake']['navigation_collision_policy']=baker.NAVIGATION_COLLISION_POLICY
    result['bake']['railway_obstacles']=dict(policy=baker.NAVIGATION_COLLISION_POLICY,layers=report,routes_preserved=True,unrelated_geometry_preserved=True)
    result['bake']['railway_obstacles']['validation']=legacy.validate_graph(result,dict(bases=result['bases']))
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--client',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True);summary=[]
    for p in sorted((ROOT/'destructibles').glob('*.json')):
        data=json.loads(p.read_text());resources=data.get('resources',{})
        if not isinstance(resources,dict) or not any(railway_vehicle_resource(k) for k in resources):continue
        name=p.stem;print('BEGIN',name,flush=True);field,legacy,instances=railway_geometry(args.client,name)
        original=(ROOT/'navgraphs'/p.name).read_bytes();graph=repair(json.loads(original),field,legacy)
        if graph!=json.loads(original):
            previous=graph.get('navigation_previous_sha256s',[]);graph['navigation_previous_sha256s']=sorted(set(previous+[hashlib.sha256(original).hexdigest()]))
        (out/p.name).write_text(json.dumps(graph,separators=(',',':'))+'\n',encoding='utf-8')
        info=dict(map=name,instances=instances,**graph['bake']['railway_obstacles']);summary.append(info);print('PASS',name,'layers',[(r['removed_nodes'],r['removed_directed_links']) for r in info['layers']],flush=True)
        (out/'railway-validation.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')

if __name__=='__main__':main()
