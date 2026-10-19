"""Exercise real host-bridge railway filtering inside nav_query_run."""
from __future__ import print_function
import imp,operator,sys
bridge=imp.load_dynamic('offline_math_batch_native',sys.argv[1])
try:long_type=long
except NameError:long_type=int
class Vector(object):
    def __init__(self,x,y,z):self.x,self.y,self.z=x,y,z
for material in (73,long_type(73),85):
    for train in (False,True):
        calls=[]
        def policy(*surface):
            calls.append(surface)
            return surface[2]==33
        def ray(space,start,end,flags,keep):
            if start.x==end.x and start.z==end.z:return (Vector(start.x,0.,start.z),Vector(0.,1.,0.))
            surface=(material,0,33 if train else 34,32641)
            return (Vector(0.,.9,4.),Vector(0.,0.,-1.)) if keep(*surface) else None
        caps=(ray,None,Vector,operator.attrgetter('y'),bridge.nav_query_filter,1,0x50,False,policy,long_type)
        result=bridge.nav_query_run((0.,0.,0.,0.,0.,10.,18.,.48,.38,1.),caps,None)
        assert result[0]==(0 if train else 1),(material,train,result)
        assert calls,(material,train,'native bypassed owner classifier')
print('Native railway callback parity passed: int/long, ordinary props, solid trains')
