"""Bounded observations; never coerce, hash or compare arbitrary inputs."""
from __future__ import print_function
import json
import math
import os
import sys
import time

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

# Detailed geometry histories are opt-in and bounded independently of errors
# and lifecycle messages. Never use this budget for gameplay or wire events.
DETAIL_ENV = 'WOT_OFFLINE_DIAGNOSTICS'
DETAIL_LABELS = frozenset(('SPG FIRE GATE', 'BOT MOTION', 'BOT SLOPE POSE', 'BOT SUPPORT MODE',
    'SUPPORT QUERY PERF', 'BOT GUN SOLUTION', 'BOT SLOPE', 'BOT HEIGHT LINKS',
    'BOT ROUTE CONNECTION', 'STACK CONTACT DECISION', 'BOT SEARCH JOB',
    'PROJECTILE INTERFACE', 'BOT NAV CHOICE', 'BOT EDGE DYNAMICS',
    'BOT LOCAL HANDOFF', 'BOT MOTION PRESENT', 'BOT RECOVERY COMMIT',
    'BOT SUPPORT RECOVERY', 'BOT SUPPORT REJECTION', 'BOT VERTICAL SUPPORT',
    'LOCAL ATTITUDE CHART', 'LOCAL EDGE SUPPORT', 'LOCAL SUPPORT DECISION',
    'RAM CONTACT GEOMETRY', 'RAM TRACK CONTACT', 'RICOCHET SURFACE EVIDENCE',
    'VEHICLE STACK', 'WRECK POSE'))
DETAIL_WINDOW_BYTES = 2 * 1024 * 1024
DETAIL_SESSION_BYTES = 32 * 1024 * 1024
DETAIL_RECORD_BYTES = 256 * 1024
_detail_budget = {'start': None, 'window': 0, 'session': 0, 'dropped': 0,
                  'notice': False}
_detail_round = None
_turret_pose_counts = {}
_validation_last = {}
_validation_counts = {}


def validation_change(stage, key, fingerprint=None, **values):
    if not detailed_enabled():
        return
    identity = (stage, key)
    signature = json.dumps(values if fingerprint is None else fingerprint,
                           sort_keys=True, separators=(',', ':'))
    if _validation_last.get(identity) == signature:
        return
    if identity not in _validation_last and len(_validation_last) >= 4096:
        if not _validation_last.get('capacity_reported'):
            _validation_last['capacity_reported'] = True
            validation_event('validation_capacity', limit=4096)
        return
    _validation_last[identity] = signature
    validation_event(stage, **values)


def validation_event(stage, **values):
    """Diagnostic-entry evidence; a failed probe is an explicit result."""
    if not detailed_enabled():
        return
    try:
        _validation_counts[stage] = _validation_counts.get(stage, 0) + 1
        values.update(schema=1, stage=stage, pid=os.getpid(),
                      round=_detail_round, wall_time=time.time())
        write_json_record('VALIDATION', values)
    except Exception as error:
        sys.stdout.write('[Offline LAN 0.9.22] VALIDATION ERROR stage=%s type=%s\n' %
                         (stage, type(error).__name__))


def _pose_matrix(provider):
    if provider is None:
        return dict(available=False, reason='missing_provider')
    try:
        import Math
        matrix = Math.Matrix(provider)
        return dict(available=True, yaw=float(matrix.yaw),
                    pitch=float(matrix.pitch), roll=float(matrix.roll))
    except Exception as error:
        return dict(available=False, error=type(error).__name__, message=str(error)[:240])


def _read_pose_matrix(owner, name):
    try:
        return _pose_matrix(getattr(owner, name, None))
    except Exception as error:
        return dict(available=False, error=type(error).__name__, message=str(error)[:240])


def turret_pose(stage, entity, avatar=None, appearance=None):
    """Observe death/model boundaries without restoring or rotating anything."""
    if not detailed_enabled() or entity is None:
        return
    try:
        key = (id(entity), str(stage))
        if len(_turret_pose_counts) >= 256 and key not in _turret_pose_counts:
            return
        count = _turret_pose_counts.get(key, 0)
        if count >= 4:
            return
        _turret_pose_counts[key] = count + 1
        row = dict(stage=stage, entity=getattr(entity, 'id', None),
                   entity_identity=id(entity), health=getattr(entity, 'health', None),
                   crew_active=getattr(entity, 'isCrewActive', None),
                   gun_angles_packed=getattr(entity, 'gunAnglesPacked', None),
                   round=_detail_round, wall_time=time.time())
        if appearance is None:
            appearance = getattr(entity, 'appearance', None)
        row['appearance_identity'] = id(appearance)
        matrices = {}
        for name in ('turretMatrix', 'gunMatrix'):
            matrices[name] = _read_pose_matrix(appearance, name)
        row['model_matrices'] = matrices
        row['hull_world'] = _read_pose_matrix(entity, 'matrix')
        row['detached_turret'] = bool(getattr(entity, 'isTurretDetached', False))
        # HP_gunFire is the same pinned node used by live muzzle queries.
        # Observe its world matrix to distinguish a stale rotator from a
        # rebuilt compound that actually points somewhere else.
        try:
            model = getattr(entity, 'model', None)
            if model is not None:
                # Damaged compounds need not retain HP_gunFire. Read the
                # turret/gun nodes independently so one missing node cannot
                # suppress the rest of the post-refresh evidence.
                nodes = {}
                for name in ('HP_turretJoint', 'HP_gunJoint', 'HP_gunFire'):
                    try:
                        nodes[name] = _pose_matrix(model.node(name))
                    except Exception as error:
                        nodes[name] = dict(available=False, error=type(error).__name__,
                                           message=str(error)[:240])
                row['world_nodes'] = nodes
            else:
                row['world_nodes'] = dict(available=False, reason='missing_model')
        except Exception as error:
            row['barrel_world_unavailable'] = type(error).__name__
        if avatar is not None and getattr(avatar, 'playerVehicleID', None) == row['entity']:
            try:
                rotator = getattr(avatar, 'gunRotator', None)
                row['local_rotator'] = dict(
                    turret_yaw=float(rotator.turretYaw), gun_pitch=float(rotator.gunPitch))
            except Exception as error:
                row['local_rotator'] = dict(available=False, error=type(error).__name__,
                    message=str(error)[:240])
        write_json_record('TURRET DEATH POSE', row)
    except Exception as error:
        # Diagnostics must never interrupt a health or model callback.
        validation_event('turret_probe_failed', probe_stage=stage,
                         error=type(error).__name__, message=str(error)[:240])


def observe_refresh_frames(bigworld, entity, appearance, avatar=None):
    """Observe subsequent engine frames, fenced to this round/entity/model."""
    if not detailed_enabled():
        return
    round_id = _detail_round
    identity = getattr(entity, 'id', None)
    model = getattr(entity, 'model', None)
    def sample(index):
        if (_detail_round != round_id or bigworld.entity(identity) is not entity or
                getattr(entity, 'appearance', None) is not appearance or
                getattr(entity, 'model', None) is not model):
            validation_event('turret_probe_cancelled', entity=identity, frame=index)
            return
        turret_pose('after_model_frame_%d' % index, entity, avatar, appearance)
        if index < 3:
            bigworld.callback(0.0, lambda: sample(index+1))
    bigworld.callback(0.0, lambda: sample(1))


def detailed_enabled():
    return os.environ.get(DETAIL_ENV) == '1'


def team_killer_receipt(stage, **values):
    """One-shot event chain; never inspect models or influence arena state."""
    if not detailed_enabled():
        return
    try:
        values['stage'] = stage
        write_json_record('TEAM KILLER', values)
    except Exception:
        pass


def _detail_window():
    now = time.time()
    budget = _detail_budget
    if budget['start'] is None or now < budget['start'] or now-budget['start'] >= 60.0:
        if budget['dropped']:
            sys.stdout.write('[Offline LAN 0.9.22] DIAGNOSTIC LIMIT dropped=%s session_bytes=%s\n' %
                             (budget['dropped'], budget['session']))
        budget.update(start=now, window=0, dropped=0, notice=False,
                      window_closed=False)
    return budget


def _detail_dropped(budget):
    budget['dropped'] += 1
    if not budget['notice']:
        sys.stdout.write('[Offline LAN 0.9.22] DIAGNOSTIC LIMIT detailed records suppressed; key events remain enabled\n')
        budget['notice'] = True


def detail_record_ready():
    """Cheap admission before constructing or encoding diagnostic histories.

    Once a byte ceiling rejects a record, close that window/session rather
    than repeatedly encoding records to try to consume its last few bytes.
    An individually oversized record does not close an otherwise free budget.
    """
    if not detailed_enabled():
        return False
    budget = _detail_window()
    if (budget.get('window_closed') or budget.get('session_closed') or
            budget['window'] >= DETAIL_WINDOW_BYTES or
            budget['session'] >= DETAIL_SESSION_BYTES):
        _detail_dropped(budget)
        return False
    return True


def _detail_admitted(encoded):
    budget = _detail_window()
    # Include worst-case JSON fragment escaping and framing in the bound.
    size = len(encoded) * 2 + ((len(encoded)+2999)//3000) * 240
    if len(encoded) > DETAIL_RECORD_BYTES:
        _detail_dropped(budget)
        return False
    if (budget['window']+size > DETAIL_WINDOW_BYTES or
            budget['session']+size > DETAIL_SESSION_BYTES):
        budget['window_closed'] = budget['window']+size > DETAIL_WINDOW_BYTES
        budget['session_closed'] = budget['session']+size > DETAIL_SESSION_BYTES
        _detail_dropped(budget)
        return False
    budget['window'] += size
    budget['session'] += size
    return True


def _write_record(payload):
    write_json_record('NATIVE INPUT FALLBACK', payload)


def write_json_record(label, payload):
    """Keep every engine stdout line below its 8 KiB truncation boundary."""
    global _record_sequence
    detail = label in DETAIL_LABELS
    if detail and not detail_record_ready():
        return
    encoded = json.dumps(payload, separators=(',', ':'))
    if detail and not _detail_admitted(encoded):
        return
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
        global _detail_round
        if phase == 'round_start' and round_id != _detail_round:
            _turret_pose_counts.clear()
            _validation_last.clear()
            _validation_counts.clear()
            _detail_round = round_id
            _detail_budget.clear()
            _detail_budget.update(start=None, window=0, session=0,
                                  dropped=0, notice=False)
        payload = snapshot()
        payload['validation_events'] = dict(_validation_counts)
        payload.update(schema=1, pid=os.getpid(), phase=phase, round=round_id)
        write_json_record('NATIVE INPUT SUMMARY', payload)
    except Exception:
        pass
