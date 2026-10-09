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
extension=sys.argv[1]
backend=imp.load_dynamic('offline_math_batch_native',extension)
class Legacy(object):
 def __getattr__(self,name):
  if name=='world_run_native':raise AttributeError(name)
  return getattr(backend,name)
drive=check.reference_drive(bot)
results=[]
for case in ['movement','wall','wreck','landing','fatal_landing','airborne_wall','drowning','overturn','new_siege','motion_trace']:
 arms=[]
 for selected in (Legacy(),backend):
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
 try:
  for i in range(4):check.near(arms[1][i],arms[0][i],case+'/'+str(i))
 except AssertionError as e:
  print('DIFFERENCE',case,str(e)[:1500]);raise
 print('PASS',case,'legacy/native ms/4frames',round(arms[0][4],3),round(arms[1][4],3))
 results.append(dict(case=case,legacy_ms=arms[0][4],native_ms=arms[1][4]))
print(json.dumps(dict(ok=True,cases=len(results),states_per_case=116,results=results),sort_keys=True))
