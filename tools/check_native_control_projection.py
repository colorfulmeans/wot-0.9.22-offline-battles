"""Real CPython 2.7 pose boundary and batched observation projection contracts."""
from __future__ import print_function
import gc, imp, os, random, sys, time
from check_native_simulation_control import load_sources

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
facade, unused_driver, unused_traffic = load_sources(os.path.join(root,'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import native_math
backend = imp.load_dynamic('offline_math_batch_native', sys.argv[1])
native_math._backend, native_math._attempted = backend, True
rng = random.Random(2026101201)
for index in range(1000):
    source = dict((name,rng.uniform(-10.,10.)) for name in facade._POSE_NAMES[:-1])
    if index % 2: source['position'] = (1.,-0.,3.)
    if index % 3: source['velocity'] = (1.,2.,3.)
    source['ignored_metadata'] = {'crew': [], 'extra': object()}
    wire = dict((name.decode('ascii'),value) for name,value in source.items())
    expected = facade._reference_pose(wire)
    assert facade._pose(wire) == expected
    assert backend.control_pose(wire) is None
    assert 'ignored_metadata' in wire

class Converted(object):
    def __float__(self): return 4.25
source = {u'x': Converted(), u'y': 0., u'z': 3.}
assert facade._pose(source) == facade._reference_pose(source)

checks = 0
for index in range(1000):
    rows=[]
    for actor in range(index % 31):
        mask=rng.randrange(2048)
        values=tuple(rng.uniform(-10.,10.) for unused in range(13))
        position=(float(actor),-0.,3.)
        if index % 2: position=list(position)
        rows.append(((1,actor),(0,actor+30),float(index),12.,(position,values,mask)))
    expected=tuple(tuple(row[:4])+(facade._pose_dict(row[4]),) for row in rows)
    actual=backend.control_observation_rows(tuple(rows))
    assert actual is not None and actual == expected
    assert tuple(facade._observation_rows(backend,tuple(rows))) == expected
    for a,b in zip(actual,rows):
        assert a[0] is b[0] and a[1] is b[1]
        if type(b[4][0]) is tuple: assert a[4]['position'] is b[4][0]
    checks += len(rows)

class Trap(list):
    def __iter__(self): raise AssertionError('native iteration')
assert backend.control_observation_rows(Trap()) is None
assert backend.control_observation_rows(((0,0,0,0,((),(),0)),)) is None
row=((1,1),(0,2),3.,12.,((1.,2.,3.),tuple(float(i) for i in range(13)),2047))
rows=(row,)*30
refs=sys.getrefcount(row)
for unused in range(1000):
    actual=backend.control_observation_rows(rows)
del actual
gc.collect()
assert sys.getrefcount(row)==refs
original=facade._pose_dict
try:
    facade._pose_dict=lambda row: {'override':True}
    assert tuple(facade._observation_rows(backend,(row,)))[0][4]=={'override':True}
finally:
    facade._pose_dict=original
assert tuple(facade._observation_rows(backend,iter((row,)))) == (
    tuple(row[:4])+(facade._pose_dict(row[4]),),)
iterator=iter(facade._observation_rows(backend,(row,(0,0,0,0,((),(),2047)))))
assert next(iterator)==tuple(row[:4])+(facade._pose_dict(row[4]),)
try:
    next(iterator)
    raise AssertionError('invalid reference row did not retain its error')
except (IndexError, ValueError):
    pass
def reference():
    return tuple(tuple(r[:4])+(facade._pose_dict(r[4]),) for r in rows)
def current(): return facade._observation_rows(backend,rows)
assert current()==reference()
samples=[[],[]]
for index in range(7):
    for owner in ((0,1) if index % 2 else (1,0)):
        fn=(reference,current)[owner]; start=time.clock()
        for unused in range(2000): fn()
        samples[owner].append((time.clock()-start)*1000./2000.)
print('Control projection conformance: 1000 Unicode poses,',checks,
      'observation rows, ownership, rejection, override and generator fallback passed')
print('Complete 30-row preparation median ms reference/native:',
      sorted(samples[0])[3],sorted(samples[1])[3])
