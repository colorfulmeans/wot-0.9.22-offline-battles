"""Compare all Windstorm route segments and recorded bridge exits in both searches.

Compile tools/benchmark_navigation_resolution.cpp with native/offline_navigation.cpp
and native/offline_async_worker.cpp, then pass the executable to this checker.
This measures native search work, not live BigWorld collision or frame rate.
"""
from pathlib import Path
import argparse
import sys,json,subprocess,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p)for p in ('tools','launcher','src/res/scripts/client')]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--native-executable',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--baseline-ref', default='346ae477')
args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
from check_navigation_resolution import write_native_input
from gui.mods.offline_lan_0922 import prebaked_navigation as pn
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
from gui.mods.offline_lan_0922 import bot_tactics
old=json.loads(subprocess.check_output(['git','show',args.baseline_ref+':navgraphs/84_winter.json'],cwd=ROOT));new=json.loads((ROOT/'navgraphs/84_winter.json').read_bytes())
pairs=set()
for routes in old['routes'].values():
 for route in routes:
  p=route['waypoints']
  for a,b in zip(p,p[1:]):pairs.add((tuple(a[:2]),tuple(b[:2])));pairs.add((tuple(b[:2]),tuple(a[:2])))
for r in bot_tactics.default_map('84_winter')['default_routes']:
 if r.get('disabled'):continue
 for a,b in zip(r['points'],r['points'][1:]):pairs.add((tuple(a[:2]),tuple(b[:2])));pairs.add((tuple(b[:2]),tuple(a[:2])))
for a,b in (((126.7290046558638,-276.07781896536494),(129.8382110595703,-276.3371276855469)),((120.,-280.),(200.,-244.)),((126.,-278.),(194.,-250.))):pairs.update(((a,b),(b,a)))
north_cases=(((282.,250.),(216.,210.)),((282.,220.),(272.,220.)),
            ((280.3538467765204,219.5717056753799),(279.8748731288322,219.7151777800562)),
            ((280.3538467765204,219.5717056753799),(217.724,216.479)),
            ((279.912,248.157),(217.724,216.479)),
            ((280.3538467765204,219.5717056753799),(277.0672636779235,220.55617109769526)))
shoal_cases=(((306.,189.),(264.,189.)),)
for a,b in north_cases+shoal_cases:
 pairs.update(((a,b),(b,a)))
cases=sorted(pairs);out={}
for name,g in (('baseline',old),('current',new)):
 graph=pn.with_shore_hazards(g);grid=TerrainGrid(lambda*a:None,baked_graph=graph);rows=[]
 for a,b in cases:
  start=time.perf_counter();p=grid.plan((a[0],-9.,a[1]),(b[0],-9.,b[1]),max_expansions=4096);ms=(time.perf_counter()-start)*1000
  reached=bool(p)and __import__('math').hypot(p[-1][0]-b[0],p[-1][2]-b[1])<8.
  rows.append(dict(start=a,end=b,reached=reached,ms=ms))
 inp=args.output/(name+'-native-input.txt');write_native_input(inp,graph,cases)
 native=json.loads(subprocess.check_output([str(args.native_executable.resolve()),str(inp.resolve()),'--paths']))
 if name=='current':
  import math
  local_cases=set(north_cases+shoal_cases)|{(b,a)for a,b in north_cases+shoal_cases}
  for row in native['paths']:
   a,b=cases[row['case']]
   if (a,b)not in local_cases:continue
   path=row['points']
   length=sum(math.hypot(q[0]-p[0],q[2]-p[2])for p,q in zip(path,path[1:]))
   assert path and length<math.hypot(b[0]-a[0],b[1]-a[1])*1.8+12.,('native_remote_detour',a,b,length)
   if (a,b) in set(shoal_cases)|{(q,p)for p,q in shoal_cases}:
    assert length<50. and all(185<=p[2]<=193 for p in path),('native_shoal_detour',a,b,path)
   else:
    assert all(198<=p[0]<=314 and 186<=p[2]<=278 for p in path),('native_left_bridge_region',a,b)
   for first,last in zip(path,path[1:]):
    assert not grid.segment_has_motion_hazard(first,last,13),('native_commit_hazard',a,b,first,last)
    steps=max(1,int(math.ceil(math.hypot(last[0]-first[0],last[2]-first[2])/.25)))
    for step in range(steps+1):
     point=tuple(first[k]+(last[k]-first[k])*step/steps for k in range(3))
     assert pn.pose_is_safe(graph,point,hazard_mask=9),('native_final_pose_hazard',a,b,point)
 out[name]=dict(cases=len(cases),python=rows,native=native)
 new_cases=set(shoal_cases)|{(b,a)for a,b in shoal_cases}
 incomplete=native.get('incomplete_cases',())
 if name=='baseline':
  # The new shoal is intentionally blocked in the old graph. Keep those
  # failures visible, but require every pre-existing route to finish.
  assert all(cases[r['case']] in new_cases for r in incomplete),(name,incomplete)
  assert all(r['reached'] or (r['start'],r['end']) in new_cases for r in rows),(name,'existing_route_failed')
  out[name]['expected_old_shoal_failures']=list(incomplete)
 else:
  assert not native['partial_or_empty'],(name,incomplete)
  assert all(r['reached']for r in rows),(name,[r for r in rows if not r['reached']])
 print(name,len(cases),{k:v for k,v in native.items()if k!='paths'},flush=True)
(args.output/'report.json').write_bytes(json.dumps(out,indent=2).encode())
