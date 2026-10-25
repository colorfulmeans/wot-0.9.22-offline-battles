"""Build a review-only profile from Default using shipping navigation geometry.

Run offline; never changes Default or applies the result to a running game.
Every shortened segment must retain dry support, clearance and climb approach.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'launcher'),str(ROOT/'src/res/scripts/client')]
from bot_tactics_store import contract, graph_data
from bot_tactics_inventory import DEFENSE_MAPS
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
from gui.mods.offline_lan_0922 import route_network


def distance(a,b):return math.hypot(a[0]-b[0],a[1]-b[1])


class Author:
    def __init__(self, graph):
        self.graph=graph
        self.grid=TerrainGrid(lambda *args:None,baked_graph=graph)
        self.cache={}

    def path(self,first,last):
        key=tuple(first[:2])+tuple(last[:2])
        if key in self.cache:return copy.deepcopy(self.cache[key])
        start=(first[0],0.,first[1]);end=(last[0],0.,last[1])
        path=self.grid.plan(start,end,max_expansions=len(self.grid._baked_heights)+1)
        target=self.grid._nearest_baked_cell(self.grid.cell_for(end),3)
        target_point=self.grid.point_for(target,self.grid._baked_cell_height(target)) if target is not None else None
        if not path or target_point is None or min(math.hypot(path[-1][0]-p[0],path[-1][2]-p[2]) for p in (end,target_point))>.01:
            raise ValueError('No complete navigation path')
        path=list(path)
        # Keep exact contract endpoints, with supported snapped approaches inside.
        if math.hypot(path[0][0]-start[0],path[0][2]-start[2])>.001:path.insert(0,start)
        else:path[0]=start
        if math.hypot(path[-1][0]-end[0],path[-1][2]-end[2])>.001:path.append(end)
        else:path[-1]=end
        chosen=[0];index=0
        while index<len(path)-1:
            furthest=index+1
            for j in range(len(path)-1,index+1,-1):
                # Limit deviation from the supported planner path, preserving bends.
                a,b=path[index],path[j];dx,dz=b[0]-a[0],b[2]-a[2];length=dx*dx+dz*dz
                deviation=0.
                for p in path[index+1:j]:
                    t=max(0.,min(1.,((p[0]-a[0])*dx+(p[2]-a[2])*dz)/length)) if length else 0.
                    deviation=max(deviation,math.hypot(p[0]-a[0]-t*dx,p[2]-a[2]-t*dz))
                if deviation>6.:continue
                if (self.grid.dry_segment_clear(a,b,0.) and
                    self.grid.shortcut_preserves_baked_clearance(path,index,j) and
                    self.grid.shortcut_preserves_climb_approach(path,index,j)):
                    furthest=j;break
            chosen.append(furthest);index=furthest
        points=[[round(path[i][0],4),round(path[i][2],4),0] for i in chosen]
        points[0]=list(first[:2])+[0];points[-1]=list(last[:2])+[0]
        if len(points)>16:raise ValueError('Preserving supported turns needs %d nodes (limit 16)'%len(points))
        self.cache[key]=points
        return copy.deepcopy(points)


def build(name='Route review 20261025', loader=graph_data, progress=print):
    profile=contract.default_profile(name);evidence=[]
    for map_name,entry in profile['maps'].items():
        graph=loader(map_name);author=Author(graph)
        def create(kind,identity,first,last):
            try:return author.path(first,last)
            except ValueError as error:
                evidence.append(dict(map=map_name,kind=kind,identity=identity,error=str(error)))
                return None
        for team in (1,2):
            base=graph['objective_bases'][team-1];enemy=graph['objective_bases'][2-team]
            peers=sorted([p for p in entry['positions'] if p['team']==team],key=lambda p:p['id'])
            for p in peers:
                path=p.get('travel') or create('deployment',p['id'],base,p['point'])
                if path:p['travel']=path
                # Directed connections avoid assuming downhill also permits uphill.
                for other in peers:
                    if p['id']==other['id']:continue
                    path=p.get('links',{}).get(other['id']) or create('relocation',p['id']+'->'+other['id'],p['point'],other['point'])
                    if path:p.setdefault('links',{})[other['id']]=path
            if any(r.get('purpose')=='spg_attack' and r['team']==team for r in entry['routes']):continue
            # An endgame route follows an already authored road, rather than
            # forcing a long arbitrary A* path into sixteen strategic nodes.
            candidates=[]
            for source in entry['default_routes']:
                if source['team']!=team or source.get('disabled') or source.get('class_tag','all')!='all':continue
                points=[list(base)+[0]]+[p[:2]+[0] for p in source['points'][1:-1]]+[list(enemy)+[0]]
                from bot_tactics_navigation import connection
                proofs=[connection(author.grid,graph,a,b) for a,b in zip(points,points[1:])]
                if all(p['connected'] for p in proofs):
                    candidates.append((sum(p['length'] for p in proofs),source['id'],points))
            path=min(candidates,key=lambda v:(v[0],v[1]))[2] if candidates else create('sortie',str(team),base,enemy)
            if path:entry['routes'].append(dict(id='spg_attack_%d'%team,label='SPG endgame attack',
                team=team,classes=['SPG'],slots=[],policy='preferred',capacity=3,weight=1.,purpose='spg_attack',points=path))
        if map_name in DEFENSE_MAPS:
            for route in entry['default_routes']+entry['routes']:
                if route.get('purpose')=='spg_attack' or route.get('disabled') or route.get('defense'):continue
                base=graph['objective_bases'][route['team']-1];points=route['points']
                # Reverse-travel divergence: the nearest approach to the own base
                # before the route turns away toward the spawn. Prefer existing nodes.
                projection=[]
                for i,(a,b) in enumerate(zip(points,points[1:])):
                    dx,dz=b[0]-a[0],b[1]-a[1];length=dx*dx+dz*dz
                    t=max(0.,min(1.,((base[0]-a[0])*dx+(base[1]-a[1])*dz)/length)) if length else 0.
                    point=[round(a[0]+t*dx,4),round(a[1]+t*dz,4),0]
                    projection.append((distance(point,base),i,t,point))
                unused,index,t,point=min(projection)
                candidates=[i for i in (index,index+1) if 0<i<len(points)-1 and not points[i][2] and
                    not contract.waiting_positions(points[i]) and distance(points[i],point)<=12.]
                if candidates:index=min(candidates,key=lambda i:distance(points[i],point))
                else:
                    if len(points)>=16:
                        candidates=[i for i in range(1,len(points)-1) if not points[i][2] and not contract.waiting_positions(points[i])]
                        if not candidates:
                            evidence.append(dict(map=map_name,kind='defense',identity=route['id'],error='No free intermediate node for base divergence'));continue
                        index=min(candidates,key=lambda i:distance(points[i],point))
                        path=create('defense',route['id'],points[index],base)
                        if path:route['defense']=dict(junction=route_network.ensure_nodes(route)[index],points=path)
                        continue
                    index+=1
                    # Do not duplicate an endpoint/wait: insert along its original segment.
                    if distance(point,points[index-1])<1. or distance(point,points[index])<1.:
                        a,b=points[index-1],points[index];point=[round(a[0]+.5*(b[0]-a[0]),4),round(a[1]+.5*(b[1]-a[1]),4),0]
                    route_network.insert_node(route,index,point)
                path=create('defense',route['id'],points[index],base)
                if path:route['defense']=dict(junction=route_network.ensure_nodes(route)[index],points=path)
        progress(map_name+' complete',flush=True)
    return contract.canonical(profile),evidence


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args()
    profile,evidence=build()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(contract.dumps(profile)+'\n',encoding='utf-8',newline='\n')
    args.output.with_suffix('.evidence.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('Unconfigured drafts:',len(evidence))
