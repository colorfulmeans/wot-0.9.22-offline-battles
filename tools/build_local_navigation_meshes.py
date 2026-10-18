"""Restore retained 4 m maps and add only proved local passage meshes."""
import hashlib
import json
from pathlib import Path
import subprocess
import argparse
import math

ROOT=Path(__file__).resolve().parents[1]
MAPS=('04_himmelsdorf','86_himmelsdorf_winter')
REGIONS=((166,30,194,134),(178,138,230,234))
# Screenshot 2026-10-18 185012: eight circled passages. The third is
# already inside the retained northern patch; the other seven are local only.
EXTRA_REGIONS=((-42,136,14,192),(74,118,132,178),(-88,-84,-32,-26),
               (34,-82,90,-22),(-208,-194,-152,-136),(-40,-176,16,-120),
               (308,-230,366,-172))
CIRCLED_PASSAGES=((( -38,158),(10,152)),((108,172),(122,122)),
    ((184,156),(224,202)),((-84,-58),(-36,-66)),((56,-26),(70,-78)),
    ((-194,-142),(-164,-184)),((-36,-140),(12,-142)),((334,-180),(330,-224)))


def geometry(client, name):
    """Decode exact-client terrain/collision without rebaking the main grid."""
    import bake_navigation_0922 as baker
    original=baker.refine_terrain_edges
    original_obstacles=baker.compiled_navigation_obstacles
    try:
        baker.compiled_navigation_obstacles=lambda c,v,l:original_obstacles(c,v,l,precise_regions=EXTRA_REGIONS)
        baker.refine_terrain_edges=lambda graph,terrain,obstacles,legacy:(terrain,obstacles,legacy)
        return baker.bake_map_graph(client,name,existing_graph={'map':name})
    finally:
        baker.refine_terrain_edges=original
        baker.compiled_navigation_obstacles=original_obstacles


def bake_patch(region, terrain, obstacles, legacy):
    import bake_navigation_0922 as baker
    left,bottom,right,top=region;size=1.
    width=int((right-left)/size)+1;height=int((top-bottom)/size)+1
    patch=dict(origin=[left,bottom],cell_size=size,width=width,height=height,
               heights_mm=[None]*(width*height),links=[0]*(width*height),hazards=[0]*(width*height))
    for i in range(width*height):
        x=left+i%width*size;z=bottom+i//width*size
        y=legacy._ground_height(terrain,obstacles,x,z)
        if y is None:continue
        if terrain.water_depth(x,z,y)>legacy.WATER_DEPTH_LIMIT:continue
        if not legacy._has_safe_edge_clearance(terrain,obstacles,x,z,y):continue
        margin=legacy.BRIDGE_OBSTACLE_MARGIN if obstacles.surface_height(x,z) is not None else legacy.VEHICLE_HALF_WIDTH
        if obstacles.blocked(x,z,y,margin=margin):continue
        patch['heights_mm'][i]=int(round(y*1000.))
    for i,y in enumerate(patch['heights_mm']):
        if y is None:continue
        x,z=i%width,i//width
        for bit,(dx,dz) in enumerate(legacy.DIRECTIONS):
            nx,nz=x+dx,z+dz
            if not (0<=nx<width and 0<=nz<height):continue
            j=nz*width+nx
            if patch['heights_mm'][j] is None:continue
            if dx and dz and (patch['heights_mm'][z*width+nx] is None or patch['heights_mm'][nz*width+x] is None):continue
            start=(left+x*size,y/1000.,bottom+z*size)
            end=(left+nx*size,patch['heights_mm'][j]/1000.,bottom+nz*size)
            if baker._resolution_segment_clear(terrain,obstacles,start,end,legacy,legacy._segment_clear):
                patch['links'][i]|=1<<bit
    for i,mask in enumerate(patch['links']):
        for bit,(dx,dz) in enumerate(legacy.DIRECTIONS):
            if mask&(1<<bit):
                j=i+dx+dz*width;reverse=legacy.DIRECTIONS.index((-dx,-dz))
                if not patch['links'][j]&(1<<reverse):patch['links'][i]&=~(1<<bit)
    return patch


def verify_passages(graph, terrain, obstacles, legacy):
    import bake_navigation_0922 as baker
    from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
    grid=TerrainGrid(lambda *args:None,baked_graph=graph)
    records=[]
    for number,(a,b) in enumerate(CIRCLED_PASSAGES):
        for first,last in ((a,b),(b,a)):
            path=grid.plan((first[0],1.1,first[1]),(last[0],1.1,last[1]),max_expansions=20000)
            target=grid._nearest_baked_cell(grid.cell_for((last[0],1.1,last[1])),3)
            end=grid.point_for(target,grid._baked_cell_height(target)) if target is not None else None
            if not path or end is None or math.hypot(path[-1][0]-end[0],path[-1][2]-end[2])>4.:
                raise ValueError('circled passage %d did not reach its target'%(number+1))
            length=sum(math.hypot(y[0]-x[0],y[2]-x[2]) for x,y in zip(path,path[1:]))
            if length>math.hypot(last[0]-first[0],last[1]-first[1])*1.8+12.:
                raise ValueError('circled passage %d still takes a remote detour'%(number+1))
            for x,y in zip(path,path[1:]):
                if not baker._resolution_segment_clear(terrain,obstacles,x,y,legacy,legacy._segment_clear):
                    raise ValueError('circled passage %d path fails physical clearance: %r %r'%(number+1,x,y))
            records.append(dict(passage=number+1,start=first,end=last,length=round(length,4),
                path=path,collision_sample_metres=.25,half_width=legacy.VEHICLE_HALF_WIDTH))
    return records


def build(name, client, contexts=None):
    if not client:raise ValueError('the exact client is required for all local patches')
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
    if client:
        terrain,obstacles,legacy=geometry(client,name)
        if contexts is not None:contexts[name]=(terrain,obstacles,legacy)
        for region in EXTRA_REGIONS:
            patches.append(bake_patch(region,terrain,obstacles,legacy))
            print(name,'proved local region',region,flush=True)
    graph['local_meshes']=patches
    graph['navigation_previous_sha256']=hashlib.sha256(fine_raw).hexdigest()
    graph['navigation_previous_sha256s']=[hashlib.sha256(raw).hexdigest()]
    previous=(ROOT/'navgraphs'/(name+'.json')).read_bytes()
    old=json.loads(previous)
    graph['navigation_previous_sha256s']+=old.get('navigation_previous_sha256s',[])+[hashlib.sha256(previous).hexdigest()]
    graph['navigation_previous_sha256s']=sorted(set(graph['navigation_previous_sha256s']))
    graph['bake']['local_meshes']=dict(base_cell_size=4.,regions=REGIONS,
        local_cell_size=2.,base_geometry_unchanged=True,source_commit='413724fe',
        collision_edge_sample_metres=.25,geometry_provenance=fine['bake']['resolution_rebake']['collision_route_validation'])
    if client:
        graph['bake']['local_meshes'].update(additional_regions=EXTRA_REGIONS,
            additional_cell_size=1.,circled_passages=CIRCLED_PASSAGES,
            node_half_width=legacy.VEHICLE_HALF_WIDTH,all_new_edges_collision_sample_metres=.25,
            local_collision_policy='body_height_clipped_triangles_against_original_2.15m_disk')
    for field in ('cell_size','origin','width','height','heights_mm','links','hazards','routes','spawn_formations'):
        assert graph[field]==json.loads(raw)[field],field
    return graph


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client',required=True)
    args=parser.parse_args()
    contexts={}
    graphs=[build(name,args.client,contexts) for name in MAPS]
    # Seasonal artwork can alter a few wall samples. Publish only edges proved
    # on BOTH maps, while retaining each map's own measured ground heights.
    for patches in zip(*(g['local_meshes'] for g in graphs)):
        for i in range(patches[0]['width']*patches[0]['height']):
            mask=patches[0]['links'][i]&patches[1]['links'][i]
            supported=all(p['heights_mm'][i] is not None for p in patches)
            for patch in patches:
                patch['links'][i]=mask if supported else 0
                if not supported:patch['heights_mm'][i]=None
    for graph in graphs:
        name=graph['map']
        graph['bake']['local_meshes']['seasonal_topology']='intersection_of_independently_proved_links'
        graph['bake']['local_meshes']['circled_passage_validation']=verify_passages(graph,*contexts[name])
    for graph in graphs:
        name=graph['map']
        (ROOT/'navgraphs'/ (name+'.json')).write_bytes((json.dumps(graph,separators=(',',':'))+'\n').encode('utf-8'))
        print(name,'base',graph['width']*graph['height'],'local sampled',sum(p['width']*p['height'] for p in graph['local_meshes']))
    path=ROOT/'navgraphs/manifest.json';manifest=json.loads(path.read_bytes())
    for row in manifest['maps']:
        if row.get('map') in MAPS or row.get('file') in tuple(n+'.json' for n in MAPS):
            row['sha256']=hashlib.sha256((ROOT/'navgraphs'/row['file']).read_bytes()).hexdigest()
    path.write_bytes((json.dumps(manifest,indent=2)+'\n').encode('utf-8'))
