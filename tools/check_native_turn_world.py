"""Current supplied departing callbacks through the native world frontier."""
from __future__ import print_function
import sys,os,imp,gc
sys.dont_write_bytecode=True
here=os.path.dirname(os.path.abspath(__file__))
base=imp.load_source('turn_world_base',os.path.join(here,'check_native_world.py'))
backend,world=base.backend,base.world
checks=0
for grade in (-.6,0.,.6):
 for obstacle in ('clear','wall','beam'):
  for mode in ('reject','support','release'):
   arms=[]
   for native in (False,True):
    scene,queries=base.scene_for(grade=grade,wall=obstacle=='wall',beam=obstacle=='beam')
    calls=[]
    def departing(hit):
     calls.append((base.xyz(hit[0]),base.xyz(hit[1])))
     return False if mode=='reject' else hit[1].y>0. if mode=='support' else hit[1].z<0.
    owner=base.object_for(_avatar=base.object_for(spaceID=1),
        _runtime=base.object_for(bigworld=scene,math=base.math_module))
    trace={}
    result=world.check_horizontal_collision(scene,base.math_module,1,base.Vector(),
        .2,5.,base.descriptor,dt=.05,return_status=True,trace=trace,
        exact_footprint=True,departing_contact=departing,query_owner=owner if native else None)
    arms.append((result,queries,trace,calls))
   base.equal(arms[1],arms[0]);checks+=1
# An outside exact-footprint witness reenters the same owner/query on the GIL.
scene,queries=base.scene_for(wall=True)
owner=base.object_for(_avatar=base.object_for(spaceID=1),
    _runtime=base.object_for(bigworld=scene,math=base.math_module))
called=[]
def witness(hit):
 if not called:
  called.append(1)
  assert world.check_horizontal_collision(scene,base.math_module,1,base.Vector(30.,0.,30.),
      0.,0.,base.descriptor,dt=0.,return_status=True,query_owner=owner)=='clear'
 return False
world.check_horizontal_collision(scene,base.math_module,1,base.Vector(),0.,5.,base.descriptor,
    dt=.05,return_status=True,departing_contact=witness,query_owner=owner)
assert called==[1]
# Failure after entering a supplied capability contains this sweep, with no replay.
def failed(hit):
 raise RuntimeError('departing proof failed')
trace={}
assert world.check_horizontal_collision(scene,base.math_module,1,base.Vector(),0.,5.,base.descriptor,
    dt=.05,return_status=True,trace=trace,departing_contact=failed,query_owner=owner)=='hard'
assert trace['reason']=='native_world_error'
assert world.check_horizontal_collision(scene,base.math_module,1,base.Vector(30.,0.,30.),
    0.,0.,base.descriptor,dt=0.,return_status=True,query_owner=owner)=='clear'
# Original callback objects do not escape the synchronous call.
gc.collect();refs=sys.getrefcount(witness)
for unused in range(100):
 world.check_horizontal_collision(scene,base.math_module,1,base.Vector(),0.,5.,base.descriptor,
     dt=.05,return_status=True,departing_contact=witness,query_owner=owner)
gc.collect();assert sys.getrefcount(witness)==refs
print('Supplied turn-world callbacks passed:',checks,'ordered scenes; reentry, failure containment and owned refs')
