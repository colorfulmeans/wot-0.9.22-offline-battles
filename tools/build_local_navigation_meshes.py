"""Restore retained 4 m maps and add only proved local passage meshes."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
MAPS=('04_himmelsdorf','86_himmelsdorf_winter')
REGIONS=((166,30,194,134),(178,138,230,234))


def build(name):
    raw=subprocess.check_output(['git','show','ca22f909:navgraphs/'+name+'.json'],cwd=ROOT)
    fine_raw=subprocess.check_output(['git','show','413724fe:navgraphs/'+name+'.json'],cwd=ROOT)
    graph=json.loads(raw);fine=json.loads(fine_raw)
    patches=[]
    for left,bottom,right,top in REGIONS:
        size=2.;width=int((right-left)/size)+1;height=int((top-bottom)/size)+1
        patch=dict(origin=[left,bottom],cell_size=size,width=width,height=height,
                   heights_mm=[],links=[],hazards=[])
        for z in range(height):
            for x in range(width):
                fx=int((left+x*size-fine['origin'][0])/size)
                fz=int((bottom+z*size-fine['origin'][1])/size)
                index=fz*fine['width']+fx
                mask=fine['links'][index]
                for bit,(dx,dz) in enumerate(fine['directions']):
                    if not (0<=x+dx<width and 0<=z+dz<height):mask &= ~(1<<bit)
                patch['heights_mm'].append(fine['heights_mm'][index])
                patch['links'].append(mask);patch['hazards'].append(fine['hazards'][index])
        patches.append(patch)
    graph['local_meshes']=patches
    graph['navigation_previous_sha256']=hashlib.sha256(fine_raw).hexdigest()
    graph['navigation_previous_sha256s']=[hashlib.sha256(raw).hexdigest()]
    graph['bake']['local_meshes']=dict(base_cell_size=4.,regions=REGIONS,
        local_cell_size=2.,base_geometry_unchanged=True,source_commit='413724fe',
        collision_edge_sample_metres=.25,geometry_provenance=fine['bake']['resolution_rebake']['collision_route_validation'])
    for field in ('cell_size','origin','width','height','heights_mm','links','hazards','routes','spawn_formations'):
        assert graph[field]==json.loads(raw)[field],field
    return graph


if __name__=='__main__':
    for name in MAPS:
        graph=build(name)
        (ROOT/'navgraphs'/ (name+'.json')).write_text(json.dumps(graph,separators=(',',':'))+'\n')
        print(name,'base',graph['width']*graph['height'],'local sampled',sum(p['width']*p['height'] for p in graph['local_meshes']))
    path=ROOT/'navgraphs/manifest.json';manifest=json.loads(path.read_bytes())
    for row in manifest['maps']:
        if row.get('map') in MAPS or row.get('file') in tuple(n+'.json' for n in MAPS):
            row['sha256']=hashlib.sha256((ROOT/'navgraphs'/row['file']).read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest,separators=(',',':'))+'\n')
