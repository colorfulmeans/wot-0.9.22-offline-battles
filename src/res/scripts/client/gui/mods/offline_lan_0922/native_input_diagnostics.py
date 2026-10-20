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
_METHODS = ('control_pose', 'driver_geometry', 'destr_required_chunks', 'destr_prepare', 'destr_box_geometry')
_FIELDS = frozenset(('x', 'y', 'z', 'yaw', 'pitch', 'roll', 'aim_yaw',
    'turret_yaw', 'gun_pitch', 'speed', 'velocity', 'position', 'id',
    'network_id', 'kind', 'team', 'alive', 'half_length', 'half_width', 'shape', 'pos'))
_MAX_REPORTS, _MAX_COUNTERS = 16, 32
_MAX_DICT_ITEMS, _MAX_ITEMS, _MAX_NODES, _MAX_TEXT = 64, 8, 96, 80
_counts, _reported = {}, set()
_reports_by_method, _record_sequence = {}, 0


def _write_record(payload):
    write_json_record('NATIVE INPUT FALLBACK', payload)


def write_json_record(label, payload):
    """Keep every engine stdout line below its 8 KiB truncation boundary."""
    global _record_sequence
    encoded = json.dumps(payload, separators=(',', ':'))
    if len(encoded) <= 6000:
        sys.stdout.write('[Offline LAN 0.9.22] %s %s\n' % (label, encoded))
        return
    _record_sequence += 1
    parts = (len(encoded) + 2999) // 3000
    pid = os.getpid()
    for index in range(parts):
        piece = encoded[index * 3000:(index + 1) * 3000]
        sys.stdout.write('[Offline LAN 0.9.22] %s PART %s\n' % (label,
            json.dumps({'schema': 1, 'pid': pid, 'record': _record_sequence,
                'part': index + 1, 'parts': parts, 'data': piece},
                separators=(',', ':'))))


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


def _describe(value, depth, budget, max_items=_MAX_ITEMS):
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
            result['items'] = [_describe(item, depth - 1, budget, max_items)
                               for item in value[:max_items]]
            result['complete'] = len(result['items']) == len(value)
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
                             'input': _describe(item, depth - 1, budget, max_items)}
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


def structural_signature(value):
    """Canonicalize owned plain descriptions without the Python 2 encoder.

    Callers supply sanitized descriptions, never arbitrary native inputs.
    Ordering log keys is unnecessary and sort_keys forces CPython 2.7's
    reference-cycle-producing Python encoder on every diagnostic record.
    """
    if type(value) is dict:
        return tuple((key, structural_signature(item))
                     for key, item in sorted(value.items()))
    if type(value) in (list, tuple):
        return tuple(structural_signature(item) for item in value)
    return value


def record(method, args, reason='unsupported_input', error=None):
    """Observe existing rejection; no retry, admission change or new callback."""
    if type(method) is not str or method not in _METHODS:
        return
    try:
        reason = reason[:_MAX_TEXT] if type(reason) is str else 'unknown'
        operation = None
        if (method in ('driver_geometry', 'destr_box_geometry') and type(args) is tuple and args and
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
        if method == 'destr_prepare' and _reports_by_method.get(method, 0) >= 4:
            return
        # A swept hull nests boxes, axes and numeric points. The normal pose
        # depth omits those coordinates, making chunk rejection unreplayable.
        chunk_query = method in ('destr_required_chunks', 'destr_prepare', 'destr_box_geometry')
        evidence = _describe(args, 7 if chunk_query else 4,
            [4096 if chunk_query else _MAX_NODES], 64 if chunk_query else _MAX_ITEMS)
        error_type = _type_name(error) if error is not None else None
        signature = (method, operation, reason, error_type,
                     structural_signature(_without_samples(evidence)))
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
        _reports_by_method[method] = _reports_by_method.get(method, 0) + 1
        profile = {'control_pose': ('control_pose', -1),
                   'destr_prepare': ('destr_query', 8),
                   'destr_required_chunks': ('destr_query', 9)}.get(method)
        if method == 'driver_geometry':
            profile = (method, operation if operation in (0, 1, 9, 10) else -1)
        elif method == 'destr_box_geometry':
            profile = (method, operation if operation in (0, 1, 2, 3) else -1)
        _write_record({'method': method, 'operation': operation, 'reason': reason,
                        'native_profile': {'family': profile[0], 'opcode': profile[1]},
                        'inputs': evidence, 'callers': callers, 'exception_type': error_type,
                        'count': _counts[key]})
    except Exception:
        pass


def snapshot():
    return {'counts': dict(_counts), 'reports': len(_reported), 'report_limit': _MAX_REPORTS}


def log_summary(phase, round_id):
    """Cumulative process counters remain visible after the evidence quota."""
    try:
        payload = snapshot()
        payload.update(schema=1, pid=os.getpid(), phase=phase, round=round_id)
        write_json_record('NATIVE INPUT SUMMARY', payload)
    except Exception:
        pass
