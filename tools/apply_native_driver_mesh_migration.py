"""Apply reviewed integration anchors in a disposable validation checkout.

The workflow tests the complete CPython 2.7/x86 extension, then commits the
runtime integration and matching shipping binary together. Current engine
queries, policies, callback cadence and physical owners remain unchanged.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'src/res/scripts/client/gui/mods/offline_lan_0922/'

OLD_RANK = '''\t\tcandidates = []
\t\tfor offset in self._CANDIDATE_OFFSETS:
\t\t\tcandidate = desired_yaw + offset
\t\t\tscore = abs(offset) + self._failure_penalty(state, candidate)
\t\t\tif (state.get('escape_side_until', 0.0) > state['clock'] and
\t\t\t\t\tfloat(offset) * float(
\t\t\t\t\t\tstate.get('escape_side', 0.0)) < -0.01):
\t\t\t\t# Continue around the selected side before testing the mirror branch.
\t\t\t\t# The finite penalty still permits the other side when this fan is spent.
\t\t\t\tscore += 1.25
\t\t\tcandidates.append((score, candidate))
\t\tcandidates.sort(key=lambda item: item[0])'''

RANK_METHODS = '''\t# Pin the current law without executing descriptors during admission.
\t_candidate_rank_failure_law = _failure_penalty
\t_candidate_rank_yaw_law = _yaw_key

\tdef _rank_yaw_candidates(self, state, desired_yaw):
\t\tif (type(self) is LocalDriver and type(state) is dict and
\t\t\t\tall(type(key) is str for key in state) and 'clock' in state and
\t\t\t\tall(type(key) is str for key in self.__dict__) and
\t\t\t\t'failure_ttl' in self.__dict__ and 'failure_ttl' not in LocalDriver.__dict__):
\t\t\tdef implementation(name):
\t\t\t\tvalue = self.__dict__.get(name, LocalDriver.__dict__.get(name))
\t\t\t\tif type(value) is _types.FunctionType:
\t\t\t\t\treturn value
\t\t\t\tif type(value) is _types.MethodType:
\t\t\t\t\treturn getattr(value, 'im_func', getattr(value, '__func__', None))
\t\t\t\treturn None
\t\t\tfailed = state.get('failed_yaws')
\t\t\toffsets = self.__dict__.get('_CANDIDATE_OFFSETS',
\t\t\t\tLocalDriver.__dict__.get('_CANDIDATE_OFFSETS'))
\t\t\tif (type(failed) is dict and (type(offsets) is tuple or type(offsets) is list) and
\t\t\t\t\timplementation('_failure_penalty') is LocalDriver.__dict__['_candidate_rank_failure_law'] and
\t\t\t\t\timplementation('_yaw_key') is LocalDriver.__dict__['_candidate_rank_yaw_law']):
\t\t\t\tresult = native_math.call('driver_geometry', 9,
\t\t\t\t\t(desired_yaw, state['clock'], self.failure_ttl,
\t\t\t\t\t state.get('escape_side_until', 0.0), state.get('escape_side', 0.0),
\t\t\t\t\t math.pi, FAILED_YAW_BUCKET_COUNT), offsets, tuple(failed.items()))
\t\t\t\tif result is not None:
\t\t\t\t\tcandidates, expired = result
\t\t\t\t\tfor key in expired:
\t\t\t\t\t\tfailed.pop(key, None)
\t\t\t\t\treturn candidates
\t\treturn self._reference_rank_yaw_candidates(state, desired_yaw)

\tdef _reference_rank_yaw_candidates(self, state, desired_yaw):
''' + OLD_RANK + '''
\t\treturn candidates

'''

OLD_PAIR = '''\t\tnegative = self._recovery_occupancy(
\t\t\tposition, yaw, -1.0, neighbours, half_length, half_width)
\t\tpositive = self._recovery_occupancy(
\t\t\tposition, yaw, 1.0, neighbours, half_length, half_width)'''
NEW_PAIR = '''\t\tpair = None
\t\tif (type(self) is LocalDriver and
\t\t\t\t(type(position) is tuple or type(position) is list) and
\t\t\t\t(type(neighbours) is tuple or type(neighbours) is list) and
\t\t\t\tnot any(name in self.__dict__ for name in
\t\t\t\t\t('_recovery_occupancy', '_native_geometry')) and
\t\t\t\tLocalDriver.__dict__['_recovery_occupancy'] is
\t\t\t\tLocalDriver.__dict__['_paired_recovery_law'] and
\t\t\t\tLocalDriver.__dict__['_native_geometry'] is
\t\t\t\tLocalDriver.__dict__['_paired_geometry_law']):
\t\t\tpair = self._native_geometry(10, position, yaw, neighbours,
\t\t\t\thalf_length, half_width, RECOVERY_YAW_OFFSET)
\t\tif pair is None:
\t\t\tnegative = self._recovery_occupancy(
\t\t\t\tposition, yaw, -1.0, neighbours, half_length, half_width)
\t\t\tpositive = self._recovery_occupancy(
\t\t\t\tposition, yaw, 1.0, neighbours, half_length, half_width)
\t\telse:
\t\t\tnegative, positive = pair'''
DUAL_NATIVE = '''        if(op==10) {
            const auto counts=profile.run([&] {
                std::array<long,2> result={{0,0}};
                for(int side=0;side<2;++side) {
                    const double amount=(side==0?-1.:1.)*v[6];
                    for(const auto &p:peers)for(double f:fractions) {
                        if(driver_geometry_law::overlaps(
                                v[0],v[2],v[3]+amount*f,v[4],v[5],p)) {
                            if(result[side]==std::numeric_limits<long>::max())throw Unsupported();
                            ++result[side];
                        }
                    }
                }
                return result;
            });
            OwnedTuple out(2);
            out.set(0,int_new(counts[0]));out.set(1,int_new(counts[1]));
            return out.release();
        }
'''

VOLUME_WRAPPERS = '''

# Complete consumer frontiers preserve the old functions as error/override
# oracles. No query rebuilds or retains the mesh between calls.
_reference_volume_contains = contains
_reference_volume_intervals = intervals
_reference_volume_distance = distance


def _volume_laws():
    return _ray_laws() + _distance_laws() + (_line_hits, math.sqrt)


_PINNED_VOLUME_LAWS = _volume_laws()
_PINNED_VOLUME_CONE = intersects_cone


def _volume_input(mesh, stats=None):
    return (_query_input(mesh, stats, orientations=True) and
            all(key in mesh for key in ('closed', 'minimum', 'maximum')) and
            all(current is pinned for current, pinned in
                zip(_volume_laws(), _PINNED_VOLUME_LAWS)))


def _volume_geometry(mesh):
    return (mesh['vertices'], mesh['triangles'], mesh['bvh'],
            mesh['orientations'], mesh['closed'], mesh['minimum'], mesh['maximum'])


def contains(point, mesh):
    if _volume_input(mesh):
        result = _native_math.call('projectile_math', 5,
                                  _volume_geometry(mesh), (point, _EPS))
        if result is not None:
            return bool(result)
    return _reference_volume_contains(point, mesh)


_PINNED_VOLUME_CONTAINS = contains


def intervals(start, end, mesh, stats=None):
    if contains is _PINNED_VOLUME_CONTAINS and _volume_input(mesh, stats):
        result = _native_math.call('projectile_math', 6,
                                  _volume_geometry(mesh), (start, end, _EPS))
        if result is not None:
            values, tested = result
            if stats is not None and tested:
                stats['triangles'] = stats.get('triangles', 0) + tested
            return values
    return _reference_volume_intervals(start, end, mesh, stats)


def distance(point, mesh, stats=None):
    if contains is _PINNED_VOLUME_CONTAINS and _volume_input(mesh, stats):
        result = _native_math.call('projectile_math', 7,
                                  _volume_geometry(mesh), (point, _EPS))
        if result is not None:
            value, closest, vertex, tested, inside = result
            if stats is not None and tested:
                stats['triangles'] = stats.get('triangles', 0) + tested
            if inside:
                return 0.0, tuple(point)
            return value, mesh['vertices'][vertex] if vertex >= 0 else closest
    return _reference_volume_distance(point, mesh, stats)


def cone_entry_depth(mesh, apex, axis, depth, tangent):
    """Optional complete 14-step depth search; caller proved apex is outside."""
    if (intersects_cone is _PINNED_VOLUME_CONE and
            all(current is pinned for current, pinned in
                zip(_cone_laws(), _PINNED_CONE_LAWS)) and _query_input(mesh, None)):
        return _native_math.call('projectile_math', 8,
            (mesh['vertices'], mesh['triangles'], mesh['bvh']),
            (apex, axis, depth, tangent, _EPS))
    return None
'''

CONE_INSERT = '''\tif (apex_outside and type(primitive) is dict and
\t\t\tall(type(key) is str for key in primitive) and
\t\t\ttype(primitive.get('shape')) is str and primitive['shape'] == 'mesh' and
\t\t\t_primitive_intersects_cone is _PINNED_PRIMITIVE_CONE_LAW and
\t\t\tall(current is pinned for current, pinned in zip(
\t\t\t\t(_vector_subtract, _vector_dot, _vector_length, _vector_scale),
\t\t\t\t_PINNED_PRIMITIVE_CONE_NUMERICS)) and
\t\t\t(type(closest) is tuple or type(closest) is list) and len(closest) == 3 and
\t\t\tall(type(value) is float and -1.e6 <= value <= 1.e6 for value in closest)):
\t\tresult = _internal_geometry.internal_mesh.cone_entry_depth(
\t\t\tprimitive, apex, axis, depth, tangent)
\t\tif result is not None:
\t\t\treturn result[1] if result[0] else None
'''


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Missing or ambiguous reviewed anchor: ' + repr(old[:100]))
    return text.replace(old, new, 1)


def prepare():
    out = {}
    p = PREFIX + 'ai/driver.py'
    s = (ROOT / p).read_text()
    if 'def _rank_yaw_candidates' in s:
        raise RuntimeError('Integration is already applied; use the normal build/check commands')
    s = replace_once(s, '\nimport math\n', '\nimport math\nimport types as _types\n')
    s = replace_once(s, OLD_RANK, '\t\tcandidates = self._rank_yaw_candidates(state, desired_yaw)')
    s = replace_once(s, "\t@observed('driver.choose_yaw')\n", RANK_METHODS + "\t@observed('driver.choose_yaw')\n")
    s = replace_once(s, "\t@observed('driver.recovery')\n", '\t_paired_recovery_law = _recovery_occupancy\n\t_paired_geometry_law = _native_geometry\n\n' + "\t@observed('driver.recovery')\n")
    s = replace_once(s, OLD_PAIR, NEW_PAIR)
    out[p] = s
    p = 'native/offline_driver_geometry_python.inc'
    s = (ROOT / p).read_text()
    s = replace_once(s, '#include "offline_traffic_crossing_python.inc"', '#include "offline_traffic_crossing_python.inc"\n#include "offline_driver_candidates_python.inc"')
    s = replace_once(s, 'if(op<0 || op>2)throw Unsupported();', 'if(op==9) { profile.opcode(op); return driver_candidates_law::run(a[1],a[2],a[3],profile); }\n        if((op<0 || op>2) && op!=10)throw Unsupported();\n        profile.opcode(op);')
    s = replace_once(s, '        const long result=profile.run([&]()->long {', DUAL_NATIVE + '        const long result=profile.run([&]()->long {')
    out[p] = s
    p = 'native/offline_projectile_math_python.inc'
    s = (ROOT / p).read_text()
    s = replace_once(s, '#include "offline_internal_mesh_query_python.inc"', '#include "offline_internal_mesh_query_python.inc"\n#include "offline_internal_mesh_volume_python.inc"')
    s = replace_once(s, '        profile.opcode(op);', '        profile.opcode(op);\n        if (op >= 5 && op <= 8)\n            return internal_mesh_volume_law::run(op, values[1], values[2], profile);')
    out[p] = s
    p = PREFIX + 'internal_mesh.py'
    out[p] = (ROOT / p).read_text() + VOLUME_WRAPPERS
    p = PREFIX + 'internal_hit_layouts.py'
    s = (ROOT / p).read_text()
    pinned = '\n_PINNED_PRIMITIVE_CONE_LAW = _primitive_intersects_cone\n_PINNED_PRIMITIVE_CONE_NUMERICS = (_vector_subtract, _vector_dot, _vector_length, _vector_scale)\n\n\ndef _primitive_cone_entry('
    s = replace_once(s, '\ndef _primitive_cone_entry(', pinned)
    s = replace_once(s, '\tapex_outside = distance > 0.0000001\n', '\tapex_outside = distance > 0.0000001\n' + CONE_INSERT)
    out[p] = s
    p = PREFIX + 'native_math.py'
    s = (ROOT / p).read_text()
    s = replace_once(s, '\nimport math\n', '\nimport math\nfrom . import native_input_diagnostics as _input_diagnostics\n')
    a = "        _record_projectile_fallback(method, args, 'unsupported_input')"
    s = replace_once(s, a, a + "\n        _input_diagnostics.record(method, args, 'unsupported_input')")
    a = "        _record_projectile_fallback(method, args, 'exception_' + type(error).__name__)"
    s = replace_once(s, a, a + "\n        _input_diagnostics.record(method, args, 'exception', error)")
    out[p] = s
    p = PREFIX + 'native_control_core.py'
    s = (ROOT / p).read_text()
    s = replace_once(s, '\nimport copy\n', '\nimport copy\nfrom . import native_input_diagnostics as _native_input_diagnostics\n')
    old = "    if callable(operation):\n        result = operation(source)\n        if result is not None:\n            combat_count('frontier_pose_native')\n            return result\n        combat_count('frontier_pose_rejected')"
    new = "    if callable(operation):\n        try:\n            result = operation(source)\n        except Exception as error:\n            _native_input_diagnostics.record('control_pose', (source,), 'exception', error)\n            raise\n        if result is not None:\n            combat_count('frontier_pose_native')\n            return result\n        combat_count('frontier_pose_rejected')\n        _native_input_diagnostics.record('control_pose', (source,))"
    out[p] = replace_once(s, old, new)
    p = 'tools/check_native_driver_geometry.py'
    out[p] = (ROOT / p).read_text() + '\nfrom check_native_driver_mesh_migration import run as check_driver_mesh_migration\ncheck_driver_mesh_migration(backend)\n'
    for path, text in out.items():
        if path.endswith('.py'):
            compile(text, path, 'exec')
    return out


if __name__ == '__main__':
    changed = prepare()
    for path, text in changed.items():
        (ROOT / path).write_text(text, encoding='utf-8', newline='\n')
    manifest = sorted(changed) + ['native/offline_math_batch_native.pyd']
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'build/native-migration/changed-paths.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2) + '\n')
    print('Prepared integration; not committed:', ', '.join(manifest))
