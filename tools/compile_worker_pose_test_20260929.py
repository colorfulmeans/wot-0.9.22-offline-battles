#!/usr/bin/env python2
"""Compile the two reviewed modules and test their real CPython 2.7 code objects.
No native BigWorld, Windows gameplay, FPS, or whole-Bot-loop result is claimed.
"""
from __future__ import print_function
import copy
import hashlib
import imp
import io
import json
import math
import marshal
import os
import random
import shutil
import struct
import sys
import types
import zipfile

ROOT = 'src/res/scripts/client/gui/mods/offline_lan_0922/'
OUTPUT = 'compiled-worker-pose-test'
NAMES = ('vehicle_physics.py', 'bot_runtime.py')

def stable(value):
    if isinstance(value, types.CodeType):
        return ('code', value.co_argcount, value.co_nlocals, value.co_stacksize,
                value.co_flags, value.co_code, value.co_names, value.co_varnames,
                value.co_freevars, value.co_cellvars, value.co_firstlineno,
                value.co_lnotab, tuple(stable(v) for v in value.co_consts))
    if isinstance(value, tuple):
        return tuple(stable(v) for v in value)
    return value

def child(code, name):
    return next(c for c in code.co_consts
                if isinstance(c, types.CodeType) and c.co_name == name)

def physics(code, name):
    module = types.ModuleType(name)
    exec(code, module.__dict__)
    return module

def sampler(code, module, optimized):
    env = {'__builtins__': __builtins__, 'math': math, 'vehicle_physics': module,
           'SUSPENSION_GROUND_PLANE_EPSILON': 0.35}
    env['_number'] = types.FunctionType(child(code, '_number'), env,
                                         '_number', (0.0,))
    env['_position'] = types.FunctionType(child(code, '_position'), env)
    cls = child(code, 'BotRuntime')
    attrs = {}
    for name in ('_suspension_ground_samples', '_suspension_pseudo_ground_samples'):
        defaults = (None, None, 0.0, None) if optimized else (None, None, 0.0)
        attrs[name] = types.FunctionType(child(cls, name), env, name, defaults)
    name = '_suspension_world_ground_plane'
    defaults = (0.0, 0.0, None) if optimized else (0.0, 0.0)
    attrs[name] = staticmethod(types.FunctionType(child(cls, name), env, name, defaults))
    return type('CompiledSampler', (object,), attrs)

class N(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

def fixture(module):
    descriptor = N(physics={'weight': 51410., 'enginePower': 485000.,
                            'speedLimits': (10., 3.67)},
        chassis=N(rotationSpeed=.4,
                  hitTester=N(bbox=((-1.5, 0., -3.5), (1.5, 1., 3.5))),
                  hullPosition=(0., .6, 0.)),
        hull=N(hitTester=N(bbox=((-1.4, 0., -3.), (1.4, 1.5, 3.)))))
    return module.derive_suspension_params(descriptor)

class Probe(object):
    def __init__(self, scenario, gx, gz, center, revision):
        self.scenario, self.gx, self.gz = scenario, gx, gz
        self.center, self.revision, self.calls = center, revision, []
    def __call__(self, x, z, low, high, flat=None):
        self.calls.append((x, z, low, high, flat))
        dx, dz = x-self.center[0], z-self.center[1]
        height = self.gx*dx+self.gz*dz
        if self.scenario == 'ledge' and dx > 0:
            return None
        if self.scenario == 'bridge' and abs(dx) > .95:
            height -= 3.
        if self.scenario == 'rubble':
            height += .15*math.sin(2*x)*math.cos(z)
        if self.scenario == 'void':
            return None
        if self.scenario == 'changed_world' and self.revision:
            height -= .45
        if self.scenario == 'stepped':
            height += .22 if dz > 0 else -.1
        if not low <= height <= high:
            return None
        ny = 1./math.sqrt(1.+self.gx*self.gx+self.gz*self.gz)
        if flat is not None and height > flat+.01 and ny >= .995:
            return None
        return height

def batch(cls, p, params, state, probe, optimized, probe_height=None, sweep=0.):
    obj = cls()
    obj._suspension_ground_value = probe
    pos = (state['x'], state['y'], state['z'])
    pitch = state.get('terrain_pitch', state.get('pitch', 0.))
    roll = state.get('roll', 0.)
    gradient = (probe.gx, probe.gz)
    kwargs = {}
    if optimized:
        packet = p.suspension_sample_pose(params, pos, state['yaw'], pitch, roll)
        kwargs['sample_pose'] = packet
    ground = obj._suspension_ground_samples(state, params, probe_height, gradient, sweep, **kwargs)
    pseudo = obj._suspension_pseudo_ground_samples(state, params, probe_height, gradient, sweep, **kwargs)
    args = (params, ground, pos, state['yaw'], pitch, roll)
    if optimized:
        args += (packet['spring_offsets'],)
    return ground, pseudo, obj._suspension_world_ground_plane(*args)

def equal(a, b, label):
    if a != b:
        raise AssertionError('%s\noriginal=%r\ncandidate=%r' % (label, a, b))

def main():
    assert sys.version_info[:2] == (2, 7), sys.version
    if not os.path.isdir(OUTPUT):
        os.makedirs(OUTPUT)
    for name in ('gui', 'gui.mods', 'gui.mods.offline_lan_0922'):
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package
        if '.' in name:
            parent, leaf = name.rsplit('.', 1)
            setattr(sys.modules[parent], leaf, package)
    diag = types.ModuleType('gui.mods.offline_lan_0922.worker_diagnostics')
    diag.observed = lambda *a, **k: (lambda fn: fn)
    sys.modules[diag.__name__] = diag
    sys.modules['gui.mods.offline_lan_0922'].worker_diagnostics = diag
    archive = zipfile.ZipFile('baseline-payload.wotmod')
    originals, candidates, receipts = {}, {}, {}
    for name in NAMES:
        payload = archive.read('res/scripts/client/gui/mods/offline_lan_0922/' + name + 'c')
        equal(payload[:4], imp.get_magic(), 'bytecode magic')
        original = marshal.loads(payload[8:])
        source = open('baseline-source/' + name, 'rb').read()
        rebuilt = compile(source, original.co_filename, 'exec', 0, True)
        equal(stable(original), stable(rebuilt), 'baseline code reproduction ' + name)
        text = open(ROOT + name, 'rb').read()
        candidate = compile(text, original.co_filename, 'exec', 0, True)
        binary = imp.get_magic() + struct.pack('<I', 0) + marshal.dumps(candidate)
        open(OUTPUT + '/' + name + 'c', 'wb').write(binary)
        open(OUTPUT + '/' + name, 'wb').write(text)
        equal(stable(marshal.loads(binary[8:])), stable(candidate), 'marshal roundtrip')
        originals[name], candidates[name] = original, candidate
        receipts[name] = {'source_sha256': hashlib.sha256(text).hexdigest(),
                          'pyc_sha256': hashlib.sha256(binary).hexdigest(),
                          'original_bytecode_reproduced': True}
    base = physics(originals['vehicle_physics.py'], 'original_physics')
    new = physics(candidates['vehicle_physics.py'], 'candidate_physics')
    old_cls = sampler(originals['bot_runtime.py'], base, False)
    new_cls = sampler(candidates['bot_runtime.py'], new, True)
    params = fixture(base)
    equal(params, fixture(new), 'descriptor parameters')
    rng = random.Random(922096)
    scenarios = ['flat','slope','ledge','bridge','rubble','void','changed_world','stepped']
    totals = {'cases': 600, 'batches': 0, 'query_arguments_checked': 0,
              'solver_comparisons': 0}
    for case in range(600):
        scenario = scenarios[case % len(scenarios)]
        pitch, roll = rng.uniform(-.65,.65), rng.uniform(-.6,.6)
        if case % 13 == 0:
            roll = rng.uniform(1.45,2.9)
        pitchv, rollv = rng.uniform(-.3,.3), rng.uniform(-.4,.4)
        posed = base.suspension_pose_params(params,pitch,roll,pitchv,rollv,.12,rng.uniform(-3.,3.))
        s = {'x':rng.uniform(-200,200),'z':rng.uniform(-200,200),'y':rng.uniform(.15,1.2),
             'yaw':rng.uniform(-math.pi,math.pi),'terrain_pitch':pitch,'pitch':pitch,'roll':roll,
             'airborne':case%7==0,'vertical_velocity':rng.uniform(-2.,1.)}
        left, right = copy.deepcopy(s), copy.deepcopy(s)
        center = (s['x'], s['z'])
        gx = 0. if scenario in ('flat','bridge','void','changed_world') else rng.uniform(-.18,.18)
        gz = 0. if scenario in ('flat','bridge','void','changed_world') else rng.uniform(-.18,.18)
        for revision in range(3):
            if revision == 2:
                for st in (left, right):
                    st['x']+=.27; st['z']-=.18; st['yaw']+=.12; st['terrain_pitch']+=.015
            p1, p2 = Probe(scenario,gx,gz,center,revision), Probe(scenario,gx,gz,center,revision)
            height = s['y']+.05 if case%3==0 else None
            sweep = .18 if case%4==0 else 0.
            a = batch(old_cls,base,posed,left,p1,False,height,sweep)
            b = batch(new_cls,new,posed,right,p2,True,height,sweep)
            equal(p1.calls,p2.calls,'query sequence')
            equal(a,b,'sample and plane results')
            equal(left,right,'contact memory')
            totals['batches']+=1; totals['query_arguments_checked']+=len(p1.calls)
            for dt in (0.,1./60.,.086011,.2):
                state = {'height':left['y'],'vertical_velocity':left['vertical_velocity'],
                         'pitch':left['terrain_pitch'],'roll':left['roll'],
                         'pitch_velocity':pitchv,'roll_velocity':rollv}
                equal(base.damper_suspension_step(posed,state,a[0],dt,a[1]),
                      new.damper_suspension_step(posed,state,b[0],dt,b[1]), 'solver outputs')
                totals['solver_comparisons']+=1
            if a[2] is not None:
                left['_suspension_ground_plane']=copy.deepcopy(a[2])
                right['_suspension_ground_plane']=copy.deepcopy(b[2])
    receipt = {'result':'PASS','python':sys.version,'magic_hex':imp.get_magic().encode('hex'),
               'baseline_commit':'3fdd95a28fcc18fe38499b2c66a4cbbab34ac0f3',
               'run_id':os.environ.get('GITHUB_RUN_ID'), 'modules':receipts, 'tests':totals,
               'scope':'Real original/candidate Python 2.7 code objects; compiled sampler adapters and pure solver on synthetic terrain. No full Bot loop, native BigWorld, Windows gameplay, or FPS test.'}
    open(OUTPUT+'/bytecode-test-receipt.json','w').write(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print(json.dumps(receipt,indent=2,sort_keys=True))

if __name__ == '__main__':
    main()
