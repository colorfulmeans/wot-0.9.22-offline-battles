"""Load native geometry and the background navigation/spotting workers."""
from __future__ import print_function

import os
import sys
import json
import math

# Standalone native conformance tools also load this adapter by filename.
# Observation is optional outside the client package, never a new dependency
# for loading an otherwise usable numeric backend.
try:
    from gui.mods.offline_lan_0922 import native_input_diagnostics as _input_diagnostics
except ImportError:
    _input_diagnostics = None


MODULE_NAME = 'offline_math_batch_native'
_backend = None
_attempted = sys.platform != 'win32'
_calls = {'destr_required_chunks': 0, 'driver_aim': 0, 'driver_geometry': 0, 'projectile_math': 0, 'projectile_spatial': 0, 'translation_fraction': 0, 'translation_contacts': 0, 'slide_translation': 0,
          'rotation_fraction': 0, 'contact_roster': 0, 'world_run': 0, 'world_run_native': 0, 'rotation_current': 0, 'rotation_envelope': 0, 'rotation_departure': 0, 'release_suspension_step': 0}
_fallbacks = 0
_reported_failure = False
_world_failures = 0
_reported_world_failure = False
_projectile_fallback_counts = {}
_projectile_fallback_reported = set()
try:
    _PLAIN_SCALARS = (int, long, bool, float)
except NameError:
    _PLAIN_SCALARS = (int, bool, float)


def _input_description(value, depth=3, values=True):
    """Bounded builtin-only evidence; never invoke an input's user methods."""
    kind = type(value)
    result = {'type': kind.__module__ + '.' + kind.__name__}
    if kind in _PLAIN_SCALARS and values:
        result['value'] = ('nonfinite' if kind is float and
                           (math.isnan(value) or math.isinf(value)) else value)
    elif kind is tuple or kind is list:
        result['length'] = len(value)
        if depth > 0:
            result['items'] = [_input_description(item, depth-1, values)
                               for item in value[:3]]
    elif kind is dict:
        result['length'] = len(value)
    return result


def _record_projectile_fallback(method, args, reason):
    if method not in ('projectile_math', 'projectile_spatial'):
        return
    try:
        operation = args[0] if args and type(args[0]) in _PLAIN_SCALARS else None
        key = '%s:%s:%s' % (method, operation, reason)
        if key not in _projectile_fallback_counts and len(_projectile_fallback_counts) >= 32:
            key = 'other'
        _projectile_fallback_counts[key] = _projectile_fallback_counts.get(key, 0) + 1
        # Aggregate inside an existing observation scope; no extra callbacks.
        from gui.mods.offline_lan_0922.worker_diagnostics import count
        count('native.' + key + '.fallback')
    except Exception:
        pass
    try:
        evidence = _input_description(args)
        signature = (method, operation, reason,
                     json.dumps(_input_description(args, values=False), sort_keys=True))
        if signature in _projectile_fallback_reported or len(_projectile_fallback_reported) >= 16:
            return
        _projectile_fallback_reported.add(signature)
        stack = []
        frame = sys._getframe(2)
        for unused in range(4):
            if frame is None:
                break
            stack.append('%s:%s:%s' % (os.path.basename(frame.f_code.co_filename),
                         frame.f_code.co_name, frame.f_lineno))
            frame = frame.f_back
        del frame
        sys.stdout.write('[Offline LAN 0.9.22] NATIVE PROJECTILE FALLBACK %s\n' %
            json.dumps({'method': method, 'operation': operation, 'reason': reason,
                        'inputs': evidence, 'callers': stack,
                        'count': _projectile_fallback_counts.get(key, 0)}, sort_keys=True))
    except Exception:
        pass


def projectile_fallback_snapshot():
    """Detached counters for diagnostic consumers and tests."""
    return dict(_projectile_fallback_counts)


def _load():
    global _backend, _attempted
    if _backend is not None or _attempted:
        return _backend
    _attempted = True
    path = os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                        'mods', '0.9.22.0.1', MODULE_NAME + '.pyd')
    try:
        import imp
        _backend = imp.load_dynamic(MODULE_NAME, path)
        sys.modules[MODULE_NAME] = _backend
    except Exception as error:
        _report_failure(error)
    return _backend


def _report_failure(error):
    global _reported_failure
    if not _reported_failure:
        _reported_failure = True
        sys.stdout.write('[Offline LAN 0.9.22] native computation unavailable '
                         'for an operation; using Python: %s\n' % error)


def call(method, *args):
    """Read borrowed inputs under the GIL, with no serialization or queues."""
    global _fallbacks
    backend = _load()
    if backend is None:
        if method == 'contact_roster':
            _fallbacks += 1
        return None
    try:
        result = getattr(backend, method)(*args)
        if result is not None:
            if not _calls[method]:
                sys.stdout.write('[Offline LAN 0.9.22] native geometry '
                                 'active: %s\n' % method)
            _calls[method] += 1
            return result
        _report_failure('unsupported geometry input')
        _record_projectile_fallback(method, args, 'unsupported_input')
        if _input_diagnostics is not None:
            _input_diagnostics.record(method, args, 'unsupported_input')
    except Exception as error:
        _report_failure(error)
        _record_projectile_fallback(method, args, 'exception_' + type(error).__name__)
        if _input_diagnostics is not None:
            _input_diagnostics.record(method, args, 'exception', error)
    _fallbacks += 1
    return None


def projectile_math(operation, vectors, scalars):
    """Fixed-arity hot frontier without generic dispatch or repeated loading."""
    global _fallbacks
    backend = _backend
    if backend is None:
        backend = _load()
    if backend is None:
        return None
    try:
        result = backend.projectile_math(operation, vectors, scalars)
        if result is not None:
            calls = _calls['projectile_math']
            if not calls:
                sys.stdout.write('[Offline LAN 0.9.22] native computation '
                                 'active: projectile_math\n')
            _calls['projectile_math'] = calls + 1
            return result
        _report_failure('unsupported projectile input')
        _record_projectile_fallback('projectile_math', (operation, vectors, scalars),
                                    'unsupported_input')
    except Exception as error:
        _report_failure(error)
        _record_projectile_fallback('projectile_math', (operation, vectors, scalars),
                                    'exception_' + type(error).__name__)
    _fallbacks += 1
    return None


def snapshot():
    """Return cumulative counters for diagnostics and caller benchmarks."""
    result = dict(_calls)
    result.update(loaded=_backend is not None, fallbacks=_fallbacks,
                  world_failures=_world_failures)
    return result


def thread_cpu_seconds():
    """Read this thread's CPU clock without affecting native availability."""
    operation = getattr(_load(), 'thread_cpu_seconds', None)
    if not callable(operation):
        return None
    try:
        return operation()
    except Exception:
        return None


def window_state():
    """Passive focus/minimized/known tuple, or unknown on other hosts."""
    operation = getattr(_load(), 'window_state', None)
    if not callable(operation):
        return None
    try:
        return operation()
    except Exception:
        return None


def report_world_failure(error):
    """Count rejected motion operations without disabling or replaying them."""
    global _world_failures, _reported_world_failure
    _world_failures += 1
    if not _reported_world_failure:
        _reported_world_failure = True
        try:
            sys.stdout.write('[Offline LAN 0.9.22] native world operation '
                             'failed; blocking this motion without replay: '
                             '%s\n' % error)
        except Exception:
            pass


def contact_roster(tanks, owner_ids, dt, previous_ram_contacts):
    """Synchronously compute frozen roster geometry; never call the engine."""
    return call('contact_roster', tanks, owner_ids, dt,
                list(previous_ram_contacts or ()))


def world_available():
    backend = _load()
    return backend is not None and hasattr(backend, 'world_run')


def world_run(snapshot, dispatcher, query=None, tuning=None):
    """Never replay a world operation after an engine callback has started."""
    global _fallbacks
    backend = _load()
    if backend is None or not hasattr(backend, 'world_run'):
        _fallbacks += 1
        return None
    # Callback exceptions propagate unchanged. The extension returns None only
    # for an unsupported snapshot before invoking the dispatcher at all.
    result = (backend.world_run_native(snapshot, dispatcher, query.capabilities, tuning)
              if query is not None else backend.world_run(snapshot, dispatcher))
    if query is not None:
        query.raise_failure()
    if result is None:
        _fallbacks += 1
        _report_failure('unsupported world input before engine dispatch')
        return None
    if result not in (0, 1, 2):
        raise RuntimeError('Native world stage failed after engine dispatch')
    if not _calls['world_run']:
        sys.stdout.write('[Offline LAN 0.9.22] native computation '
                         'active: world_run\n')
    _calls['world_run'] += 1
    if query is not None:
        _calls['world_run_native'] += 1
    return result
