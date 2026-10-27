"""Refine the circled Siegfried town gaps without changing authored roads."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src/res/scripts/client')]
import build_local_navigation_meshes as meshes

# The four circled groups, including their connecting street entrances.
REGIONS=((42,42,274,184),(150,-94,330,78),(30,-122,176,16),(-12,8,56,104))
# A two metre centre falls on the adjacent wall at this authored corner.
# Keep one metre precision only in this 16x18m pocket, not the entire town.
CORNER=(74,-76,90,-58)
POINT=(80.8441,-67.0406)


def build(client,output):
    from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
    from gui.mods.offline_lan_0922 import prebaked_navigation as pn
    raw=(ROOT/'navgraphs/14_siegfried_line.json').read_bytes()
    graph=json.loads(raw)
    if graph.get('local_meshes'):raise ValueError('Expected the reviewed coarse source')
    meshes.EXTRA_REGIONS=REGIONS+(CORNER,)
    terrain,obstacles,legacy=meshes.geometry(client,'14_siegfried_line')
    ground=terrain.height(*POINT)
    if ground is None or obstacles.blocked(POINT[0],POINT[1],ground,margin=legacy.VEHICLE_HALF_WIDTH):
        raise ValueError('The authored corner is not physically supported')
    patches=[meshes.bake_patch(CORNER,terrain,obstacles,legacy)]
    for i,region in enumerate(REGIONS):
        patches.append(meshes.bake_patch(region,terrain,obstacles,legacy,cell_size=2.))
        print('Town region',i+1,'sampled',flush=True)
    graph['local_meshes']=patches
    grid=TerrainGrid(lambda *args:None,baked_graph=pn.with_shore_hazards(graph))
    cell=grid._local_meshes.cell((POINT[0],ground,POINT[1]))
    if cell is None or grid._baked_index(cell) is None:raise ValueError('Corner still has no sampled support')
    cases=(((84.9976,-106.2274),POINT),(POINT,(108.7587,-27.6317)))
    proof=[]
    for a,b in cases:
        for first,last in ((a,b),(b,a)):
            path=grid.plan((first[0],0.,first[1]),(last[0],0.,last[1]),max_expansions=100000)
            if not path or math.hypot(path[-1][0]-last[0],path[-1][2]-last[1])>4.:
                raise ValueError('Corner approach has no complete path')
            cost=sum(math.hypot(y[0]-x[0],y[2]-x[2]) for x,y in zip(path,path[1:]))
            if cost>math.dist(first,last)*1.8+12.:raise ValueError('Corner still detours')
            proof.append(dict(start=first,end=last,length=round(cost,4)))
    graph['bake']['local_meshes']=dict(regions=REGIONS,corner_region=CORNER,
        base_cell_size=4.,local_cell_size=2.,corner_cell_size=1.,
        base_geometry_unchanged=True,node_half_width=legacy.VEHICLE_HALF_WIDTH,
        collision_edge_sample_metres=.25,corner_validation=proof,
        water_depth_limit=legacy.WATER_DEPTH_LIMIT,
        measured_local_cells=sum(len(p['heights_mm']) for p in patches),
        source='exact_0922_client_compiled_geometry',
        local_collision_policy='body_height_clipped_triangles_against_original_2.15m_disk')
    previous=set(graph.get('navigation_previous_sha256s',()))
    previous.add(hashlib.sha256(raw).hexdigest())
    graph['navigation_previous_sha256s']=sorted(previous)
    for field in ('origin','width','height','cell_size','heights_mm','links','hazards',
                  'routes','spawn_formations','objective_bases','spawn_anchors'):
        assert graph[field]==json.loads(raw)[field],field
    Path(output).write_text(json.dumps(graph,separators=(',',':'))+'\n',encoding='utf8',newline='\n')
    print('Candidate ready:',output,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();build(args.client,args.output)
