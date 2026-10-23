"""Current Python physical owner versus fused C++ world-query frontiers.

Both arms retain the same shipping geometry primitives and source-derived drive
block. Exact full states, reports, ordered engine queries and committed effects
are compared. Analytic fixtures do not establish embedded-game performance.
"""
from __future__ import print_function
import os,sys,imp,copy,time,json
sys.platform='linux'
tools=os.path.dirname(os.path.abspath(__file__));sys.path.insert(0,tools)
check=imp.load_source('motion_check_pipeline',tools+'/check_native_simulation_motion.py')
scene_module=imp.load_source('simulation_motion_scene',tools+'/native_simulation_motion_fixture.py')
from gui.mods.offline_lan_0922 import native_math,bot_runtime as bot
from gui.mods.offline_lan_0922.native_engine_query import EngineQuery
extension=sys.argv[1]
backend=imp.load_dynamic('offline_math_batch_native',extension)
class Legacy(object):
 def __getattr__(self,name):
  if name in ('world_run_native', 'rotation_envelope', 'rotation_departure', 'contact_ground'):raise AttributeError(name)
  return getattr(backend,name)
drive=check.reference_drive(bot)
original_ray=EngineQuery._ray
def uncached_ray(self,*args):
 # Compare every requested engine frontier before testing the production
 # reuse policy. Legacy dispatch has no EngineQuery cache to disable.
 scopes=self._ray_scopes
 self._ray_scopes=[]
 try:return original_ray(self,*args)
 finally:self._ray_scopes=scopes

def check_reused_queries(actual,expected,label):
 # Reuse may omit only an earlier identical, unfiltered ray. Retain the
 # complete relative order of every actual frontier, including effects.
 index=0;seen=[];omitted=0
 for row in expected:
  if index<len(actual) and row==actual[index]:
   index+=1
  else:
   assert row[0]=='wg_collideSegment' and len(row[1])==5 and not row[1][4], (label,'unexpected omission',row)
   assert row in seen, (label,'new geometry omitted',row)
   omitted+=1
  seen.append(row)
 assert index==len(actual), (label,'reordered or additional queries',index,len(actual))
 return omitted

results=[]
for case in ['movement','wall','wreck','landing','fatal_landing','airborne_wall','drowning','overturn','new_siege','motion_trace']:
 arms=[]
 for selected,reuse in ((Legacy(),False),(backend,False),(backend,True)):
  EngineQuery._ray=original_ray if reuse else uncached_ray
  scene=scene_module.HostScene(case,native_library='');check.setup(scene,case,bot)
  native_math._backend,native_math._attempted=selected,True
  commands=dict((a,(1.,(a%3-1)*.15,0.)) for a in scene.runtime.states)
  scene.frontier_log[:]=[];start=time.clock();states=[];reports=[]
  for frame in range(4):
   scene.now=.2*(frame+1);scene.frame_index=frame
   reports.append(check.run_reference(scene,bot,commands,.2,scene.now,drive))
   states.append(copy.deepcopy(scene.runtime.states))
  elapsed=(time.clock()-start)*1000
  if selected is backend:
   assert native_math.snapshot()['world_failures']==0
   assert native_math.snapshot()['world_run_native']>0
  arms.append((states,reports,check.engine_queries(scene),scene.effect_log,elapsed))
 EngineQuery._ray=original_ray
 try:
  for i in range(4):check.near(arms[1][i],arms[0][i],case+'/'+str(i))
  for i in (0,1,3):check.near(arms[2][i],arms[1][i],case+'/reuse/'+str(i))
  omitted=check_reused_queries(arms[2][2],arms[1][2],case+'/reuse/queries')
 except AssertionError as e:
  print('DIFFERENCE',case,str(e)[:1500]);raise
 print('PASS',case,'legacy/native ms/4frames',round(arms[0][4],3),round(arms[1][4],3))
 results.append(dict(case=case,legacy_ms=arms[0][4],native_ms=arms[1][4],
                     reused_ms=arms[2][4],reused_rays=omitted))
print(json.dumps(dict(ok=True,cases=len(results),states_per_case=116,results=results),sort_keys=True))
