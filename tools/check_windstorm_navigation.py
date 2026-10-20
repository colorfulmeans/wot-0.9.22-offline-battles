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
args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
from check_navigation_resolution import write_native_input
from gui.mods.offline_lan_0922 import prebaked_navigation as pn
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
from gui.mods.offline_lan_0922 import bot_tactics
old=json.loads(subprocess.check_output(['git','show','346ae477:navgraphs/84_winter.json'],cwd=ROOT));new=json.loads((ROOT/'navgraphs/84_winter.json').read_bytes())
pairs=set()
for routes in old['routes'].values():
 for route in routes:
  p=route['waypoints']
  for a,b in zip(p,p[1:]):pairs.add((tuple(a[:2]),tuple(b[:2])));pairs.add((tuple(b[:2]),tuple(a[:2])))
for r in bot_tactics.default_map('84_winter')['default_routes']:
 if r.get('disabled'):continue
 for a,b in zip(r['points'],r['points'][1:]):pairs.add((tuple(a[:2]),tuple(b[:2])));pairs.add((tuple(b[:2]),tuple(a[:2])))
for a,b in (((126.7290046558638,-276.07781896536494),(129.8382110595703,-276.3371276855469)),((120.,-280.),(200.,-244.)),((126.,-278.),(194.,-250.))):pairs.update(((a,b),(b,a)))
cases=sorted(pairs);out={}
for name,g in (('baseline',old),('current',new)):
 graph=pn.with_shore_hazards(g);grid=TerrainGrid(lambda*a:None,baked_graph=graph);rows=[]
 for a,b in cases:
  start=time.perf_counter();p=grid.plan((a[0],-9.,a[1]),(b[0],-9.,b[1]),max_expansions=4096);ms=(time.perf_counter()-start)*1000
  reached=bool(p)and __import__('math').hypot(p[-1][0]-b[0],p[-1][2]-b[1])<8.
  rows.append(dict(start=a,end=b,reached=reached,ms=ms))
 inp=args.output/(name+'-native-input.txt');write_native_input(inp,graph,cases)
 native=json.loads(subprocess.check_output([str(args.native_executable.resolve()),str(inp.resolve())]))
 out[name]=dict(cases=len(cases),python=rows,native=native)
 assert not native['partial_or_empty'],(name,native)
 assert all(r['reached']for r in rows),(name,[r for r in rows if not r['reached']])
 print(name,len(cases),native,flush=True)
(args.output/'report.json').write_bytes(json.dumps(out,indent=2).encode())
