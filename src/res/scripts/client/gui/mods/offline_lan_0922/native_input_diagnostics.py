"""Bounded observations; never coerce, hash or compare arbitrary inputs."""
from __future__ import print_function
import json
import math
import os
import sys

try:
    _NUMBERS = (int, long, bool, float)
    _STRINGS = (str, unicode)
except NameError:
    _NUMBERS = (int, bool, float)
    _STRINGS = (str,)
_METHODS = ('control_pose', 'driver_geometry')
_FIELDS = frozenset(('x', 'y', 'z', 'yaw', 'pitch', 'roll', 'aim_yaw',
    'turret_yaw', 'gun_pitch', 'speed', 'velocity', 'position', 'id',
    'network_id', 'kind', 'team', 'alive', 'half_length', 'half_width', 'shape', 'pos'))
_MAX_REPORTS, _MAX_COUNTERS = 16, 32
_MAX_DICT_ITEMS, _MAX_ITEMS, _MAX_NODES, _MAX_TEXT = 64, 8, 96, 80
_counts, _reported = {}, set()


def _type_name(value):
    kind = type(value)
    try:
        name = type.__dict__['__name__'].__get__(kind, type)
        namespace = type.__dict__['__dict__'].__get__(kind, type)
        module = namespace.get('__module__')
        if not any(type(name) is t for t in _STRINGS):
            return '<custom>'
        if not any(type(module) is t for t in _STRINGS):
            module = 'builtin'
        return module[:_MAX_TEXT] + '.' + name[:_MAX_TEXT]
    except Exception:
        return '<custom>'


def _describe(value, depth, budget):
    if budget[0] <= 0:
        return {'truncated': True}
    budget[0] -= 1
    kind = type(value)
    result = {'type': _type_name(value)}
    if any(kind is t for t in _NUMBERS):
        if kind is float:
            result['value'] = ('nonfinite' if math.isnan(value) or math.isinf(value) else value)
        else:
            result['value'] = (value if -9223372036854775808 <= value <= 9223372036854775807
                               else 'integer_outside_int64')
    elif any(kind is t for t in _STRINGS):
        result['length'] = len(value)
    elif kind is tuple or kind is list:
        result['length'] = len(value)
        if depth > 0:
            result['items'] = [_describe(item, depth - 1, budget) for item in value[:_MAX_ITEMS]]
    elif kind is dict:
        result['length'] = len(value)
        if depth <= 0:
            return result
        fields, other_keys, inspected = [], [], 0
        iterator = dict.iteritems(value) if hasattr(dict, 'iteritems') else iter(dict.items(value))
        for key, item in iterator:
            if inspected >= _MAX_DICT_ITEMS:
                break
            inspected += 1
            if any(type(key) is t for t in _STRINGS) and key in _FIELDS:
                fields.append((key, _type_name(key), item))
            elif len(other_keys) < _MAX_ITEMS:
                other_keys.append(_type_name(key))
        fields.sort(key=lambda row: (row[0], row[1]))
        result['fields'] = [{'name': name, 'key_type': key_type,
                             'input': _describe(item, depth - 1, budget)}
                            for name, key_type, item in fields]
        result['other_key_types'] = sorted(other_keys)
        result['scanned'] = inspected
        result['complete'] = inspected == len(value)
    return result


def _without_samples(value):
    if type(value) is dict:
        return dict((key, _without_samples(item)) for key, item in value.items() if key != 'value')
    if type(value) is list:
        return [_without_samples(item) for item in value]
    return value


def record(method, args, reason='unsupported_input', error=None):
    """Observe existing rejection; no retry, admission change or new callback."""
    if type(method) is not str or method not in _METHODS:
        return
    try:
        reason = reason[:_MAX_TEXT] if type(reason) is str else 'unknown'
        operation = None
        if (method == 'driver_geometry' and type(args) is tuple and args and
                any(type(args[0]) is t for t in _NUMBERS) and type(args[0]) is not float):
            operation = args[0]
            if not -2147483648 <= operation <= 2147483647:
                operation = None
        key = '%s:%s:%s' % (method, operation, reason)
        if key not in _counts and len(_counts) >= _MAX_COUNTERS:
            key = 'other'
        _counts[key] = _counts.get(key, 0) + 1
        if len(_reported) >= _MAX_REPORTS:
            return
        evidence = _describe(args, 4, [_MAX_NODES])
        error_type = _type_name(error) if error is not None else None
        signature = (method, operation, reason, error_type,
                     json.dumps(_without_samples(evidence), sort_keys=True))
        if signature in _reported:
            return
        callers, frame = [], None
        try:
            frame = sys._getframe(1)
            for unused in range(4):
                if frame is None:
                    break
                code = frame.f_code
                callers.append('%s:%s:%d' % (os.path.basename(code.co_filename),
                                             code.co_name, frame.f_lineno))
                frame = frame.f_back
        finally:
            del frame
        _reported.add(signature)
        sys.stdout.write('[Offline LAN 0.9.22] NATIVE INPUT FALLBACK %s\n' %
            json.dumps({'method': method, 'operation': operation, 'reason': reason,
                        'inputs': evidence, 'callers': callers, 'exception_type': error_type,
                        'count': _counts[key]}, sort_keys=True))
    except Exception:
        pass


def snapshot():
    return {'counts': dict(_counts), 'reports': len(_reported), 'report_limit': _MAX_REPORTS}
