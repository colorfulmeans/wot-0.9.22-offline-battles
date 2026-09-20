"""Always-on, structured evidence from the actual physics decision.

No per-session contact cap or debug switch. Identical consecutive payloads
may be coalesced for one second; every changed identity, pose or verdict is
written immediately. Diagnostic output never changes a physics decision.
"""
import json
import functools
import sys
import time

from gui.mods.offline_lan_0922.worker_diagnostics import observed

SCHEMA = 1
PREFIX = '[Offline LAN 0.9.22] PHYSICS '
_last = {}
_writer = None


def configure(writer=None):
    global _writer
    _writer = writer
    _last.clear()


def _native_description(value):
    try:
        return repr(value)
    except Exception:
        return '<%s: repr unavailable>' % type(value).__name__


_encoder = json.JSONEncoder(ensure_ascii=True, default=_native_description)
_compact_encoder = json.JSONEncoder(ensure_ascii=True, default=_native_description,
                                    separators=(',', ':'))


def encode(data, compact=False):
    """Keep native descriptor evidence readable in both report formats."""
    # Encoder options are immutable; encode() owns its per-call traversal and
    # circular-reference markers. Reuse the options, never a mutable payload
    # or a native object, across the many complete records in one frame.
    return (_compact_encoder if compact else _encoder).encode(data)


def observational(function):
    """Contain failures of a report-only boundary, never of simulation work."""
    @functools.wraps(function)
    def report(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:
            emit('diagnostic_error', {'report': function.__name__,
                                     'error': _native_description(error)})
            return False
    return report


@observed('physics.diagnostics')
def emit(event, data, key=None, now=None):
    try:
        stamp = time.time() if now is None else float(now)
        encoded = encode(data, compact=True)
        channel = (event, key)
        previous = _last.get(channel)
        repeats = 0
        if previous is not None and previous[0] == encoded:
            repeats = previous[2]+1
            if stamp-previous[1] < 1.0:
                _last[channel] = (encoded, previous[1], repeats)
                return
        _last[channel] = (encoded, stamp, 0)
        row = {'schema': SCHEMA, 'event': event, 'time': stamp,
               'wall_time': time.time(),
               'identical_repeats': repeats}
        # The complete payload was already encoded for repeat detection.
        # Reuse it verbatim instead of walking every native-query/contact
        # payload twice. This retains every field and writes immediately.
        line = PREFIX+encode(row, compact=True)[:-1]+',"data":'+encoded+'}'
        if _writer is not None:
            _writer(line)
        else:
            sys.stdout.write(line+'\n')
    except Exception:
        # The existing full client log still captures native exceptions. A
        # broken stream must never turn logging into a collision or a crash.
        pass
