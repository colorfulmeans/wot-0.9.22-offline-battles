"""Full-call incremental timings against the existing native-backed baseline.

Not a game/worker benchmark: the directions are controlled callbacks and the
meshes are analytic fixtures. Validate identical outputs before timing. The
baseline already uses its original C++ primitives, so ratios measure this
batch's incremental effect rather than crediting earlier migrations again.
"""
from __future__ import print_function
import imp
import json
import math
import os
import random
import struct
import sys
import time


def bits(value):
    if type(value) is float:
        return struct.pack('<d', value)
    if type(value) in (tuple,list):
        return type(value).__name__, tuple(bits(x) for x in value)
    if type(value) is dict:
        return dict((key,bits(x)) for key,x in value.items())
    return type(value).__name__,value


def main():
    if len(sys.argv)!=3:
        raise SystemExit('usage: benchmark_native_driver_mesh_migration.py HOST_EXTENSION OUTPUT_JSON')
    root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    baseline=os.environ['WOT_NATIVE_BASELINE']
    prefix='src/res/scripts/client/gui/mods/offline_lan_0922'
    sys.path[:0]=[os.path.join(root,'tools'),os.path.join(root,'src/res/scripts/client')]
    sys.dont_write_bytecode=True
    import native_simulation_motion_fixture
    from gui.mods.offline_lan_0922 import native_math
    from gui.mods.offline_lan_0922 import internal_mesh as current_mesh
    from gui.mods.offline_lan_0922 import internal_hit_layouts as current_layouts
    from gui.mods.offline_lan_0922.ai import driver as current_driver
    backend=imp.load_dynamic('offline_math_batch_native',sys.argv[1])
    native_math._backend,native_math._attempted=backend,True
    old_mesh=imp.load_source('_incremental_mesh_baseline',os.path.join(baseline,prefix,'internal_mesh.py'))
    old_driver=imp.load_source('_incremental_driver_baseline',os.path.join(baseline,prefix,'ai/driver.py'))
    old_layouts=imp.load_source('_incremental_layouts_baseline',os.path.join(baseline,prefix,'internal_hit_layouts.py'))
    old_mesh._native_math=current_mesh._native_math=native_math
    from check_native_internal_mesh_queries import fixtures
    shapes=fixtures(old_mesh)
    cube,plane=shapes[0],shapes[2]
    result={'baseline_native_enabled':True,'game_acceptance':False,
            'iterations':1000,'samples':7,'timings':{}}
    clock=time.clock

    def measure(name,old,new,iterations=1000):
        expected,actual=old(),new()
        assert bits(expected)==bits(actual),(name,expected,actual)
        values=[[],[]]
        # Alternate measurement order to avoid consistently crediting warmup.
        for sample in range(7):
            for index in ((0,1) if sample%2==0 else (1,0)):
                fn=(old,new)[index]
                started=clock()
                for unused in range(iterations):fn()
                values[index].append((clock()-started)/iterations)
        times=[sorted(v)[len(v)//2] for v in values]
        result['timings'][name]={'previous_native_seconds':times[0],
                                'current_native_seconds':times[1],
                                'ratio':times[0]/times[1], 'iterations':iterations}
        print('INCREMENTAL',name,result['timings'][name])

    for name,args in (('contains_inside',((.2,.1,.3),cube)),
                      ('contains_outside',((4.,0.,0.),cube))):
        measure(name,lambda args=args:old_mesh.contains(*args),
                     lambda args=args:current_mesh.contains(*args))
    for name,args in (('intervals_closed',((-3.,.2,.1),(3.,.2,.1),cube)),
                      ('intervals_open',((.2,.1,-3.),(.2,.1,3.),plane))):
        measure(name,lambda args=args:old_mesh.intervals(*args),
                     lambda args=args:current_mesh.intervals(*args))
    for name,args in (('distance_inside',((.2,.1,.3),cube)),
                      ('distance_surface',((.2,.1,3.),plane))):
        measure(name,lambda args=args:old_mesh.distance(*args),
                     lambda args=args:current_mesh.distance(*args))
    # The old layout consumer still performs fifteen native cone queries.
    # Its mesh queries have no containment phase once positive distance is known.
    point,axis,depth,tangent=(-3.,.2,.1),(1.,0.,0.),5.,.5
    record=old_mesh.distance(point,cube)
    measure('cone_depth_consumer',
        lambda:old_layouts._primitive_cone_entry({},cube,point,axis,depth,tangent,distance_record=record),
        lambda:current_layouts._primitive_cone_entry({},cube,point,axis,depth,tangent,distance_record=record),250)
    a,b=old_driver.LocalDriver(),current_driver.LocalDriver()
    def choose(owner,failures):
        state={'clock':10.,'failed_yaws':dict(failures),
               'escape_side_until':11.,'escape_side':1.}
        choice=owner._choose_yaw(state,.3,lambda angle:True)
        return choice,state
    for label,failures in (('clear',()),('remembered',((12,11.),(13,12.),(11,9.),(16,11.)))):
        measure('driver_choose_'+label,
                lambda failures=failures:choose(a,failures),
                lambda failures=failures:choose(b,failures))
    rng=random.Random(20261011)
    peers=[dict(id=i+1,position=(rng.uniform(-15.,15.),0.,rng.uniform(-15.,15.)),
                yaw=rng.uniform(-math.pi,math.pi),half_length=3.5,half_width=1.7)
           for i in range(30)]
    state_a=a._state(1,0,(0.,0.,0.));state_b=b._state(1,0,(0.,0.,0.))
    measure('driver_paired_recovery',
        lambda:a._select_recovery_side(state_a,(0.,0.,0.),.3,peers,3.5,1.7),
        lambda:b._select_recovery_side(state_b,(0.,0.,0.),.3,peers,3.5,1.7),250)
    with open(sys.argv[2],'w') as stream:
        json.dump(result,stream,indent=2,sort_keys=True)
        stream.write('\n')
    print('NATIVE_INCREMENTAL_BENCHMARK '+json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
