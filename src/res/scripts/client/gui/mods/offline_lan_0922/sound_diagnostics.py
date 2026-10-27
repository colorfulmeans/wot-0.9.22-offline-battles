# -*- coding: utf-8 -*-
"""Diagnostic-entry-only sound call receipts; preserve native calls and owners."""
import json
import sys
import time
import traceback
from collections import deque

from gui.mods.offline_lan_0922.native_input_diagnostics import detailed_enabled

_HOOKS = []
_SEEN = set()
_SERIAL = 0
_BUSY = False
MAX_CALLS = 256
_RECENT = deque(maxlen=64)
_PARENTS = []
_STREAMS = []
_OBJECT_TYPES = set()
_COVERAGE = []
_EVENT_NAMES = set()
_MUSIC_INSTALLED = False
try:
    _NUMBERS = (bool, int, long, float)
    _STRINGS = (basestring,)
except NameError:
    _NUMBERS = (bool, int, float)
    _STRINGS = (str,)


def _scalar(value):
    if value is None or isinstance(value, _NUMBERS + _STRINGS):
        return value[:180] if isinstance(value, _STRINGS) else value
    return {'type': type(value).__name__, 'object_id': id(value)}


def event_id(name):
    """WWISE's case-insensitive FNV-1 short ID; bank membership is separate."""
    if not isinstance(name, _STRINGS):return None
    try:raw = bytearray(name.lower().encode('ascii'))
    except (UnicodeError, AttributeError):return None
    value = 2166136261
    for byte in raw:value = ((value * 16777619) ^ byte) & 0xffffffff
    return value


class _ErrorStream(object):
    def __init__(self, stream):
        self.original = stream
        self.pending = ''

    def __getattr__(self, name):return getattr(self.original, name)

    def write(self, text):
        result = self.original.write(text)
        try:
            if not isinstance(text, _STRINGS):return result
            self.pending = (self.pending + text)[-8192:]
            if '\n' in self.pending:
                lines = self.pending.split('\n');self.pending = lines.pop()
                for line in lines:
                    if '[SOUND_ERROR]' in line or 'Sound fail:' in line:
                        # Report-time scanning also captures native writes which
                        # bypass Python streams entirely.
                        self.original.write('[Offline LAN 0.9.22] SOUND CALL ' + json.dumps(
                            dict(stage='native_error', wall=time.time(), error=line[:1000],
                                 recent=list(_RECENT))) + '\n')
        except Exception:
            pass
        return result


def _emit(record):
    try:
        sys.stdout.write('[Offline LAN 0.9.22] SOUND CALL ' + json.dumps(record) + '\n')
    except Exception:
        pass


def _music_context(owner):
    """Read #1513's Python playback owner; never replace its native sound."""
    result = {}
    try:
        sound = getattr(owner, '_MusicEvent__event', None)
        result.update(event_id=getattr(owner, '_MusicEvent__eventID', None),
                      muted=getattr(owner, '_MusicEvent__muted', None),
                      sound=_scalar(sound))
        if sound is not None:
            result.update(name=_scalar(sound.name), playing=_scalar(sound.isPlaying))
    except Exception as error:
        result['unavailable'] = type(error).__name__
    return result


def _install_music_owner():
    global _MUSIC_INSTALLED
    if _MUSIC_INSTALLED:
        return
    module = sys.modules.get('MusicControllerWWISE')
    owner = getattr(getattr(module, 'MusicController', None), 'MusicEvent', None)
    if owner is None:
        return
    _MUSIC_INSTALLED = True
    for name in ('replace', 'play', 'stop', 'mute', 'destroy'):
        _wrap(owner, name, 'MusicController.MusicEvent.' + name, True)
    for name in ('init', 'destroy', 'stopMusic'):
        _wrap(module.MusicController, name, 'MusicController.' + name, True)
    _emit(dict(stage='playback_owner_coverage', owner='MusicController.MusicEvent',
        native_identity_preserved=True, bank_coverage='Python requests only; engine auto-load is not observed'))


def _controller_context():
    module = sys.modules.get('MusicControllerWWISE')
    controller = getattr(module, 'g_musicController', None)
    return dict(controller=_scalar(controller), events=[_music_context(event)
        for event in getattr(controller, '_MusicController__musicEvents', ())])


def _wrap(owner, name, label, skip_self):
    original = getattr(owner, name, None)
    if not callable(original):
        if len(_COVERAGE)<128:_COVERAGE.append(dict(method=label,status='not_exposed'))
        return
    if any(o is owner and n == name for o,n,unused,unused2 in _HOOKS):
        return
    def traced(*args, **kwargs):
        global _SERIAL, _BUSY
        if _BUSY or not detailed_enabled():return original(*args, **kwargs)
        record = None
        summary = None
        try:
            _BUSY = True
            _install_music_owner()
            values = [_scalar(v) for v in args[int(skip_self):int(skip_self)+4]]
            named = dict((str(k)[:60], _scalar(v)) for k,v in list(kwargs.items())[:8])
            music = (_music_context(args[0]) if args and
                     label.startswith('MusicController.MusicEvent.') else None)
            key = (label, json.dumps(values), json.dumps(sorted(named.items())),
                   music.get('name') if music else None)
            _SERIAL += 1
            summary = dict(call=_SERIAL, method=label, args=values, wall=time.time(),
                parent=_PARENTS[-1] if _PARENTS else None,
                receiver=id(args[0]) if skip_self and args else None,
                event_ids=[dict(name=v,id=event_id(v)) for v in values if isinstance(v,_STRINGS)])
            if music is not None:
                summary['music'] = music
                if isinstance(music.get('name'), _STRINGS):
                    summary['event_ids'].append(dict(name=music['name'], id=event_id(music['name'])))
            lifecycle = (label.startswith('MusicController.') and
                         not label.startswith('MusicController.MusicEvent.') or
                         label in ('SoundGroups.unloadAll', 'SoundGroups.preloadSoundGroups'))
            if lifecycle:
                summary['controller_state'] = _controller_context()
            _RECENT.append(summary)
            for event in summary['event_ids']:
                if event['name'] not in _EVENT_NAMES and len(_EVENT_NAMES)<4096:
                    _EVENT_NAMES.add(event['name'])
                    _emit(dict(summary,stage='event_definition'))
            # First distinct calls plus a continuing sampled timeline: repeated
            # playback remains observable after the first-call budget fills.
            if lifecycle or key not in _SEEN and len(_SEEN) < MAX_CALLS or _SERIAL % 64 == 0:
                if len(_SEEN)<MAX_CALLS:_SEEN.add(key)
                stack = traceback.extract_stack(limit=7)[:-1]
                record = dict(summary,stage='begin',kwargs=named,
                    wall=time.time(),role='worker' if __import__('os').environ.get('OFFLINE_LAN_0922_CLIENT_MODE') == 'simulation_worker' else 'visible',
                    caller=[[row[0].replace('\\','/').rsplit('/',2)[-1],row[1],row[2]] for row in stack[-5:]])
                _emit(record)
        except Exception:
            record = None
        finally:
            _BUSY = False
        token = _SERIAL
        _PARENTS.append(token)
        try:
            result = original(*args, **kwargs)
        except BaseException as error:
            try:_emit(dict(record or summary or {},stage='raised',wall=time.time(),
                error_type=type(error).__name__,error=str(error)[:240]))
            except Exception:pass
            raise
        finally:
            _PARENTS.pop()
        if type(result).__name__ in ('PySound', 'PySoundObject'):
            try:_instrument_type(type(result))
            except Exception:pass
        if record:
            try:
                returned = dict(record,stage='returned',wall=time.time(),result=_scalar(result))
                if music is not None:returned['music'] = _music_context(args[0])
                if lifecycle:returned['controller_state'] = _controller_context()
                _emit(returned)
            except Exception:pass
        return result
    try:
        setattr(owner,name,traced)
    except (AttributeError,TypeError):
        if len(_COVERAGE)<128:_COVERAGE.append(dict(method=label,status='readonly'))
        return
    _HOOKS.append((owner,name,original,traced))
    if len(_COVERAGE)<128:_COVERAGE.append(dict(method=label,status='installed'))


def _instrument_type(owner):
    if owner in _OBJECT_TYPES:return
    _OBJECT_TYPES.add(owner)
    methods = [name for name in ('play','stop','event','setCallback','releaseMatrix')
               if callable(getattr(owner,name,None))]
    before = len(_HOOKS)
    for name in methods:_wrap(owner,name,owner.__name__+'.'+name,True)
    _emit(dict(stage='object_coverage',type=owner.__name__,methods=methods,
        installed=len(_HOOKS)-before, limitation='native_readonly_methods' if methods and len(_HOOKS)==before else None))


def install():
    if not detailed_enabled():return 0
    _install_music_owner()
    module = sys.modules.get('SoundGroups')
    owner = getattr(module,'SoundGroups',None)
    for name in ('getSound2D','playSound2D','getSound3D','playSound3D','playSoundPos',
                 'WWgetSound','WWgetSoundObject','WWgetSoundCallback','WWgetSoundPos',
                 'playCameraOriented','getCameraOriented','loadSoundBank','unLoadSoundBank',
                 'unloadAll','preloadSoundGroups'):
        if owner is not None:_wrap(owner,name,'SoundGroups.'+name,True)
    # Verified #1513 SoundGroups consumers call these module functions directly.
    wwise = sys.modules.get('WWISE')
    for name in ('WW_eventGlobal','WW_eventGlobalSync','WW_getSound','WW_getSoundObject','WW_getSoundCallback',
                 'WW_getSoundPos','WG_loadSoundBank','WG_unLoadSoundBank'):
        if wwise is not None:_wrap(wwise,name,'WWISE.'+name,False)
    for name in ('stdout','stderr'):
        stream=getattr(sys,name)
        if not isinstance(stream,_ErrorStream):
            wrapped=_ErrorStream(stream);_STREAMS.append((name,stream,wrapped));setattr(sys,name,wrapped)
    _emit(dict(stage='installed',hooks=len(_HOOKS),limit=MAX_CALLS,
        recent_limit=64,repeat_stride=64,coverage=list(_COVERAGE),
        policy='calls_objects_banks_errors_and_report_scan'))
    return len(_HOOKS)


def remove():
    global _SERIAL, _MUSIC_INSTALLED
    while _HOOKS:
        owner,name,original,traced=_HOOKS.pop()
        if getattr(owner,name,None) is traced:setattr(owner,name,original)
    _SEEN.clear();_SERIAL=0
    _RECENT.clear();_PARENTS[:]=[];_OBJECT_TYPES.clear();_COVERAGE[:]=[];_EVENT_NAMES.clear()
    _MUSIC_INSTALLED = False
    while _STREAMS:
        name,original,wrapped=_STREAMS.pop()
        if getattr(sys,name) is wrapped:setattr(sys,name,original)
