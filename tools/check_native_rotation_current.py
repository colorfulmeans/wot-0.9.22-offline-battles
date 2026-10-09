"""Actual CPython 2.7 parity for fused current-release rotation geometry."""
from __future__ import print_function
import sys,os,imp,random,math,time,gc
sys.platform='linux';sys.dont_write_bytecode=True
root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0]=[os.path.join(root,'tools'),os.path.join(root,'src/res/scripts/client')]
import native_simulation_motion_fixture
from gui.mods.offline_lan_0922 import native_math,tank_collision,bot_runtime
backend=imp.load_dynamic('offline_math_batch_native',sys.argv[1]);native_math._backend,native_math._attempted=backend,True
rng=random.Random(1022);checks=0
runtime=bot_runtime.BotRuntime.__new__(bot_runtime.BotRuntime)
for case in range(500):
 states={}
 for actor in range(1,31):
  span=12. if case%3==0 else 150.
  states[actor]=dict(id=actor,x=rng.uniform(-span,span),y=rng.uniform(-2.,2.),z=rng.uniform(-span,span),
                   yaw=rng.uniform(-math.pi,math.pi),collision_shape=(rng.uniform(1.,2.5),rng.uniform(2.,5.),-.8,2.))
 runtime.states=states;source=states[1];position=(source['x'],source['y'],source['z']);yaw=source['yaw'];target=yaw+rng.uniform(-.4,.4)
 supplied=[dict(position=(30.,0.,10.),shape=(1.5,3.5,-.8,2.),yaw=.5)]
 for revision in range(2):
  expected=tank_collision.rotation_fraction(position,yaw,target,source['collision_shape'],runtime._rotation_neighbours_for(source,supplied))
  actual=backend.rotation_current(position,yaw,target,source['collision_shape'],tuple(supplied),tuple(states.items()),1)
  assert actual is not None,'native projection rejected a current producer'
  assert abs(actual-expected)<=1.e-10,(case,actual,expected)
  assert actual==runtime._rotation_fraction_for(source,position,yaw,target,supplied)
  checks+=1;states[2]['x']+=2.;states[2]['yaw']+=.2
class Trap(dict):
 def get(self,*args):raise AssertionError('native invoked arbitrary mapping code')
assert backend.rotation_current(position,yaw,target,source['collision_shape'],(),((2,Trap()),),1) is None
refs=sys.getrefcount(source);pairs=tuple(states.items())
for unused in range(100):
 assert backend.rotation_current(position,yaw,target,source['collision_shape'],tuple(supplied),pairs,1) is not None
gc.collect();assert sys.getrefcount(source)==refs+1
start=time.clock()
for unused in range(1000):
 tank_collision.rotation_fraction(position,yaw,target,source['collision_shape'],runtime._rotation_neighbours_for(source,supplied))
legacy=(time.clock()-start)*1000/1000
start=time.clock()
for unused in range(1000):runtime._rotation_fraction_for(source,position,yaw,target,supplied)
native=(time.clock()-start)*1000/1000
print('Current rotation parity:',checks,'fresh rosters; reference/native ms per call:',legacy,native)
