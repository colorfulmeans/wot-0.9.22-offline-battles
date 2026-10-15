"""Actual CPython 2.7 bridge parity for current release math and projection."""
from __future__ import print_function
import imp, os, sys, types, random, math, timeit, gc, copy
sys.dont_write_bytecode = True
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
client = os.path.join(root, 'src', 'res', 'scripts', 'client')
for name in ('gui', 'gui.mods', 'gui.mods.offline_lan_0922'):
    package = types.ModuleType(name)
    package.__path__ = [os.path.join(client, *name.split('.'))]
    sys.modules[name] = package
from gui.mods.offline_lan_0922 import native_math, vehicle_physics as physics
from gui.mods.offline_lan_0922.native_control_core import _pose_dict, _CONTACT_KEYS, _reference_pose
backend = imp.load_dynamic('offline_math_batch_native', sys.argv[1])
native_math._backend, native_math._attempted = backend, True
rng = random.Random(1000)
checks = 0
def near(a, b):
    global checks
    if isinstance(b, (tuple, list)):
        assert len(a) == len(b)
        for x,y in zip(a,b): near(x,y)
    elif math.isinf(b):
        assert a == b, (a,b)
    else:
        assert abs(a-b) <= 2.e-10*max(1.,abs(b)), (a,b)
    checks += 1
params = dict(mass=45000.,powerW=600000.,nativePowerRatio=1.,
    speedFwd=16.,speedBwd=7.,specificFriction=.6867,brakeDecel=8.,
    rotSpd=.7,terrainResist=(.8,1.,1.5))
def coast_reference(p, speed, pitch, steering, epsilon, step):
    if abs(speed)<=epsilon:return 0.
    distance=0.
    for unused in range(4096):
        next_speed=physics._reference_longitudinal_step(p,speed,0.,bool(steering),pitch,step)
        if math.isnan(next_speed) or math.isinf(next_speed):return float('inf')
        if abs(next_speed)<=epsilon:return distance+abs(next_speed)*step
        if abs(next_speed)>=abs(speed):return float('inf')
        distance+=abs(next_speed)*step;speed=next_speed
    return float('inf')
for case in range(4000):
    p=dict(params,mass=rng.uniform(8000.,180000.),powerW=rng.uniform(1.e5,2.e6),
        nativePowerRatio=rng.uniform(.25,1.5),brakeDecel=rng.uniform(.1,15.))
    speed=rng.uniform(-40.,70.);pitch=rng.uniform(-1.3,1.3)
    throttle=rng.choice((-1.,-.5,0.,.2,1.));steering=rng.uniform(-1.,1.)
    dt=rng.choice((0.,.005,.0333333333333,.1,.2));terrain=rng.choice((-3,-1,0,1,2))
    air=case%11==0;hand=case%7==0;service=case%5==0
    row=(speed,throttle,steering,pitch,dt,air,terrain,hand,service)
    actual=physics._release_drive(0,p,row);assert actual is not None
    near(actual,physics._reference_longitudinal_step(p,*row))
    row=(rng.uniform(-2.,2.),steering,speed,dt,terrain,throttle)
    actual=physics._release_drive(1,p,row);assert actual is not None
    near(actual,physics._traverse_step(p,*row))
    row=(1.8,speed,steering,dt,throttle,pitch)
    actual=physics._release_drive(3,p,row);assert actual is not None
    near(actual,physics._reference_contact_traverse(p,*row))
    if case%10==0:
        row=(speed,pitch,bool(case%3),.1,1./30.)
        actual=physics._release_drive(2,p,row);assert actual is not None
        near(actual,coast_reference(p,*row))

def project_reference(rows,templates):
    contacts=[];lookup={}
    for row,template in zip(rows,templates):
        target=dict(template)
        if row[4] is not None:target.update(_pose_dict(row[4]))
        flags=row[1]
        target.update(visible=bool(flags&1),direct_visible=bool(flags&2),fresh_visible=bool(flags&4))
        contacts.append(target)
        if target['visible']:lookup[target['id']]=target
    return contacts,lookup
for case in range(300):
    source=dict(x=rng.uniform(-300.,300.),y=rng.uniform(-20.,20.),z=rng.uniform(-300.,300.),
        yaw=rng.uniform(-3.2,3.2),speed=rng.uniform(-20.,50.))
    for name in _CONTACT_KEYS[:10]:
        if case%3==0:source[name]=None if case%7==0 and name not in ('x','y','z') else rng.random()
    if case%4==0:source['position']=[1.,2.,3.]
    if case%5==0:source['velocity']=[.3,.5,.7]
    actual=backend.control_pose(source);assert actual is not None
    assert actual==_reference_pose(source),(actual,_reference_pose(source))
    checks += 1
assert backend.control_pose({'position':True}) is None
assert backend.control_pose({'x':None}) is None
for case in range(80):
    rows=[];templates=[]
    for actor in range(30):
        pose=((1.,2.,3.),tuple(rng.random() for unused in range(13)),rng.randrange(2048))
        if actor%13==0:pose=None
        rows.append(((1,actor),rng.randrange(8),0.,0.,pose))
        templates.append(dict(id=actor,team=1,vehicle='test',health=1000,nested={'owner':actor}))
    source=copy.deepcopy(templates);rows=tuple(rows);templates=tuple(templates)
    actual=backend.contact_materialize(rows,templates,_CONTACT_KEYS,(True,False))
    assert actual is not None
    contacts,lookup=list(actual[0]),dict(actual[1])
    expected,wanted=project_reference(rows,templates)
    assert contacts==expected and lookup==wanted and list(templates)==source
    for target in contacts:
        assert target is not templates[target['id']]
        assert target['nested'] is templates[target['id']]['nested']
        if target['visible']:assert lookup[target['id']] is target
    checks += 30
# Mutable tuning and descriptor changes must reach the native law immediately.
saved = physics.POWER_FACTOR
try:
    for factor in (.25, 1.5, .8):
        physics.POWER_FACTOR = factor
        params['powerW'] = 400000. * factor
        actual = physics._release_drive(0, params, (5.,1.,.4,.1,.033,False,0,False,False))
        assert actual is not None
        near(actual, physics._reference_longitudinal_step(params,5.,1.,.4,.1,.033))
finally:
    physics.POWER_FACTOR = saved
params['powerW'] = 600000.

class Trap(dict):
    def __getitem__(self, key):
        raise AssertionError('native guard invoked user code')
assert backend.control_pose(Trap(x=1.)) is None
assert backend.contact_materialize(rows, (Trap(templates[0]),)+templates[1:], _CONTACT_KEYS, (True,False)) is None
assert backend.contact_materialize(rows, templates[:-1], _CONTACT_KEYS, (True,False)) is None
assert physics._release_drive(0, dict(params,mass=0.), (1.,1.,0.,0.,.1,False,0,False,False)) is None
assert physics._release_drive(0, params, (float('nan'),1.,0.,0.,.1,False,0,False,False)) is None
assert physics._release_drive(0, params, (1.,1.,0.,0.,.1,False,3,False,False)) is None
# Allocation/copy ownership is synchronous, including rejection paths.
del actual, contacts, lookup, expected, wanted, target
before = tuple(sys.getrefcount(item) for item in templates)
for unused in range(1000):
    projected = backend.contact_materialize(rows,templates,_CONTACT_KEYS,(True,False))
    assert projected is not None
    del projected
    assert backend.contact_materialize(rows,templates[:-1],_CONTACT_KEYS,(True,False)) is None
gc.collect()
assert before == tuple(sys.getrefcount(item) for item in templates)
checks += 1009

def timing(call,count=2000):
    began=timeit.default_timer()
    for unused in range(count):call()
    return (timeit.default_timer()-began)*1000/count
print('Longitudinal ms/call reference/native:',timing(lambda:physics._reference_longitudinal_step(params,12.,1.,.5,.15,.033)),timing(lambda:physics.longitudinal_step(params,12.,1.,.5,.15,.033)))
print('Coast integral ms/call reference/native:',timing(lambda:coast_reference(params,12.,.05,False,.1,1./30.),200),timing(lambda:physics.native_stopping_distance(params,12.,.05,False,.1,1./30.),200))
print('30-contact batch ms/call reference/native:',timing(lambda:project_reference(rows,templates),500),timing(lambda:backend.contact_materialize(rows,templates,_CONTACT_KEYS,(True,False)),500))
print('Release math and contact projection parity passed:',checks)
