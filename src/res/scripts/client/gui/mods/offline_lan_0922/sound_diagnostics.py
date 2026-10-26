# -*- coding: utf-8 -*-
"""Diagnostic-entry-only sound call receipts; preserve native calls and owners."""
import json
import sys
import time
import traceback

from gui.mods.offline_lan_0922.native_input_diagnostics import detailed_enabled

_HOOKS = []
_SEEN = set()
_SERIAL = 0
_BUSY = False
MAX_CALLS = 256


def _scalar(value):
    try:
        strings = (basestring,)
    except NameError:
        strings = (str,)
    if value is None or isinstance(value, (bool, int, float) + strings):
        return value[:180] if isinstance(value, strings) else value
    return {'type': type(value).__name__}


def _emit(record):
    try:
        sys.stdout.write('[Offline LAN 0.9.22] SOUND CALL ' + json.dumps(record) + '\n')
    except Exception:
        pass


def _wrap(owner, name, label, skip_self):
    original = getattr(owner, name, None)
    if not callable(original) or any(o is owner and n == name for o,n,unused,unused2 in _HOOKS):
        return
    def traced(*args, **kwargs):
        global _SERIAL, _BUSY
        if _BUSY or len(_SEEN)>=MAX_CALLS or not detailed_enabled():return original(*args, **kwargs)
        record = None
        try:
            _BUSY = True
            values = [_scalar(v) for v in args[int(skip_self):int(skip_self)+4]]
            named = dict((str(k)[:60], _scalar(v)) for k,v in list(kwargs.items())[:8])
            key = (label, json.dumps(values,sort_keys=True), json.dumps(named,sort_keys=True))
            if key not in _SEEN and len(_SEEN) < MAX_CALLS:
                _SEEN.add(key);_SERIAL += 1
                stack = traceback.extract_stack(limit=7)[:-1]
                record = dict(call=_SERIAL,stage='begin',method=label,args=values,kwargs=named,
                    wall=time.time(),role='worker' if __import__('os').environ.get('OFFLINE_LAN_0922_CLIENT_MODE') == 'simulation_worker' else 'visible',
                    caller=[[row[0].replace('\\','/').rsplit('/',2)[-1],row[1],row[2]] for row in stack[-5:]])
                _emit(record)
        except Exception:
            record = None
        finally:
            _BUSY = False
        try:
            result = original(*args, **kwargs)
        except BaseException:
            if record:_emit(dict(record,stage='raised',wall=time.time()))
            raise
        if record:
            try:_emit(dict(record,stage='returned',wall=time.time(),result=_scalar(result)))
            except Exception:pass
        return result
    try:
        setattr(owner,name,traced)
    except (AttributeError,TypeError):return
    _HOOKS.append((owner,name,original,traced))


def install():
    if not detailed_enabled():return 0
    module = sys.modules.get('SoundGroups')
    owner = getattr(module,'SoundGroups',None)
    for name in ('getSound2D','playSound2D','getSound3D','playSound3D','playSoundPos',
                 'WWgetSound','WWgetSoundObject','loadSoundBank','unLoadSoundBank'):
        if owner is not None:_wrap(owner,name,'SoundGroups.'+name,True)
    # Verified #1513 SoundGroups consumers call these module functions directly.
    wwise = sys.modules.get('WWISE')
    for name in ('WW_eventGlobal',):
        if wwise is not None:_wrap(wwise,name,'WWISE.'+name,False)
    _emit(dict(stage='installed',hooks=len(_HOOKS),limit=MAX_CALLS,policy='first_distinct_calls_no_extra_playback'))
    return len(_HOOKS)


def remove():
    global _SERIAL
    while _HOOKS:
        owner,name,original,traced=_HOOKS.pop()
        if getattr(owner,name,None) is traced:setattr(owner,name,original)
    _SEEN.clear();_SERIAL=0
