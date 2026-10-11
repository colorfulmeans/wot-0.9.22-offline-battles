"""Current-release driver sweeps through the actual CPython 2.7 frontier."""
from __future__ import print_function
import os,sys,imp,random,math,time,gc
sys.platform='linux';sys.dont_write_bytecode=True
root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0]=[os.path.join(root,'tools'),os.path.join(root,'src/res/scripts/client')]
import native_simulation_motion_fixture
from gui.mods.offline_lan_0922 import native_math
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
backend=imp.load_dynamic('offline_math_batch_native',sys.argv[1])
rng=random.Random(134232);driver=LocalDriver();checks=0
def reference():native_math._backend=None;native_math._attempted=True
def native():native_math._backend=backend;native_math._attempted=True
for case in range(1500):
 position=(rng.uniform(-10.,10.),rng.uniform(-2.,2.),rng.uniform(-10.,10.))
 yaw=rng.uniform(-math.pi,math.pi);length=rng.uniform(2.,5.);width=rng.uniform(1.,2.5)
 peers=[]
 for actor in range(30):
  p=dict(id=actor+1,position=(rng.uniform(-20.,20.),rng.uniform(-7.,7.),rng.uniform(-20.,20.)),
         yaw=rng.uniform(-math.pi,math.pi),half_length=rng.uniform(2.,5.),half_width=rng.uniform(1.,2.5),
         alive=bool(actor%3),velocity=(rng.choice((0.,.65,.6500001,1.)),0.,0.))
  peers.append(p)
 if case%10==0:peers[0].update(position=(position[0],position[1]+5.,position[2]),half_length=0.,half_width=None)
 distance=None if case%2 else rng.uniform(0.,15.)
 for revision in range(2):
  reference()
  expected=(driver._reference_reverse_blocked_by_vehicle(position,yaw,peers,length,width,distance),
            driver._reference_static_hull_ahead(position,yaw,peers,length,width),
            driver._reference_recovery_occupancy(position,yaw,-1.,peers,length,width),
            driver._reference_recovery_occupancy(position,yaw,1.,peers,length,width))
  native();before=native_math.snapshot()['driver_geometry']
  actual=(driver._reverse_blocked_by_vehicle(position,yaw,peers,length,width,distance),
          driver._static_hull_ahead(position,yaw,peers,length,width),
          driver._recovery_occupancy(position,yaw,-1.,peers,length,width),
          driver._recovery_occupancy(position,yaw,1.,peers,length,width))
  assert actual==expected,(case,revision,actual,expected)
  assert native_math.snapshot()['driver_geometry']==before+4,'operation silently fell back'
  checks+=4
  peers[0]['position']=(position[0]-math.sin(yaw)*3.,position[1],position[2]-math.cos(yaw)*3.)
class Trap(dict):
 def get(self,*args):raise AssertionError('native invoked mapping code')
assert backend.driver_geometry(0,(0.,0.,0.,0.,3.5,1.5,5.6),[Trap()],(.25,.5,.75,1.)) is None
refs=sys.getrefcount(peers[0])
for unused in range(100):driver._recovery_occupancy(position,yaw,1.,peers,length,width)
gc.collect();assert sys.getrefcount(peers[0])==refs
def measure(function):
 start=time.clock()
 for unused in range(2000):function()
 return (time.clock()-start)*1000/2000
reference();legacy=measure(lambda:driver._reference_recovery_occupancy(position,yaw,1.,peers,length,width))
native();current=measure(lambda:driver._recovery_occupancy(position,yaw,1.,peers,length,width))
print('Driver geometry parity:',checks,'comparisons; reference/native occupancy ms:',legacy,current)

from check_native_traffic_geometry import run as check_traffic_geometry
check_traffic_geometry(backend)

from check_native_traffic_crossing import run as check_crossing
check_crossing(backend)

from check_native_projectile_math import run as check_projectile_math
check_projectile_math(backend)

from check_native_projectile_spatial import run as check_projectile_spatial
check_projectile_spatial(backend)

from check_native_internal_mesh_cone import run as check_internal_mesh_cone
check_internal_mesh_cone(backend)

from check_native_projectile_cursor import run as check_projectile_cursor
check_projectile_cursor(backend)

from check_native_internal_mesh_queries import run as check_internal_mesh_queries
check_internal_mesh_queries(backend)

from check_native_driver_mesh_migration import run as check_driver_mesh_migration
check_driver_mesh_migration(backend)
