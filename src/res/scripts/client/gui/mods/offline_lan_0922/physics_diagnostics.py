"""Always-on, structured evidence from the actual physics decision.

No per-session contact cap or debug switch. Identical consecutive payloads
may be coalesced for one second; every changed identity, pose or verdict is
written immediately. Diagnostic output never changes a physics decision.
"""
import json
import sys
import time

SCHEMA = 1
PREFIX = '[Offline LAN 0.9.22] PHYSICS '
_last = {}
_writer = None


def configure(writer=None):
    global _writer
    _writer = writer
    _last.clear()


def emit(event, data, key=None, now=None):
    try:
        stamp = time.time() if now is None else float(now)
        encoded = json.dumps(data, separators=(',', ':'),
                             ensure_ascii=True, default=repr)
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
               'identical_repeats': repeats, 'data': data}
        line = PREFIX+json.dumps(row, separators=(',', ':'),
                                ensure_ascii=True, default=repr)
        if _writer is not None:
            _writer(line)
        else:
            sys.stdout.write(line+'\n')
    except Exception:
        # The existing full client log still captures native exceptions. A
        # broken stream must never turn logging into a collision or a crash.
        pass
