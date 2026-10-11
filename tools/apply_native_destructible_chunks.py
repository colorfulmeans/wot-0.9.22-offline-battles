"""Install one validated native chunk-planning frontier, without packaging.

Used by the isolated validation job after it snapshots the unchanged baseline.
Keep the original mapper/callback path intact for unreviewed or replaced laws.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
CLIENT = 'src/res/scripts/client/gui/mods/offline_lan_0922/'
changed = []


def edit(path, before, after):
    target = ROOT / path
    text = target.read_text()
    if text.count(before) != 1:
        raise RuntimeError('Expected exactly one unchanged anchor: ' + path)
    target.write_text(text.replace(before, after))
    if path not in changed:
        changed.append(path)


def main():
    edit('native/offline_destructible_python.inc',
        '#define WOT_DESTRUCTIBLE_METHODS \\\n',
        '#include "offline_destructible_chunks_python.inc"\n\n'
        '#define WOT_DESTRUCTIBLE_METHODS \\\n'
        '    {"destr_required_chunks",destr_required_chunks,1,"Current swept-hull chunk planning."}, \\\n')
    edit(CLIENT + 'native_math.py', "'driver_aim': 0,", "'destr_required_chunks': 0, 'driver_aim': 0,")
    # Retain the exact reviewed mapper admission already used by neighbourhood.
    path = CLIENT + 'native_destructibles.py'
    old = (ROOT / path).read_text()
    start = old.index('    try:\n        import DestructiblesCache', old.index('def neighbourhood('))
    stop = old.index('    owner = _get(sensor)', start)
    guard = old[start:stop]
    guard_function = ('\n\ndef _chunk_mapper_1513(area):\n'
        '    """Existing bytecode/constant identity gate for the pure #1513 mapper."""\n' +
        guard.replace('return None', 'return False') + '    return True\n')
    edit(path, guard, '    if not _chunk_mapper_1513(area):\n        return None\n')
    target = ROOT / path
    target.write_text(target.read_text() + guard_function + '''

def _chunk_vector_1513(math_module):
    # A Python replacement must retain its callbacks/rounding/errors. Only
    # the existing native Math.Vector3 constructor/index slots are bypassed.
    factory = getattr(math_module, 'Vector3', None)
    return (type(factory) is type and
            getattr(factory, '__module__', None) == 'Math' and
            getattr(factory, '__name__', None) == 'Vector3' and
            type(getattr(factory, '__init__', None)) is type(object.__init__) and
            type(getattr(factory, '__getitem__', None)) is type(object.__init__) and
            type(getattr(factory, '__new__', None)) is type(object.__new__))

def _chunk_environment_1513():
    import math
    import sys
    import types
    cache = sys.modules.get('DestructiblesCache')
    if (cache is None or getattr(cache, 'math', None) is not math or
            type(math.floor) is not types.BuiltinFunctionType or
            getattr(math.floor, '__name__', None) != 'floor' or
            getattr(cache, 'int', int) is not int):
        return False
    for name in ('chunkIDFromPosition', 'chunkIndexesFromPosition',
                 'chunkIDFromChunkIndexes'):
        function = getattr(cache, name, None)
        namespace = getattr(function, 'func_globals',
                            getattr(function, '__globals__', None))
        if namespace is not cache.__dict__:
            return False
    return True


def required_chunks(sensor, area, math_module, sweep_boxes):
    """Batch the current mapper's numeric work, never a custom callback."""
    if (not callable(getattr(area, 'chunkIDFromPosition', None)) or
            not _chunk_mapper_1513(area) or not _chunk_vector_1513(math_module) or
            not _chunk_environment_1513()):
        return None
    from gui.mods.offline_lan_0922 import native_math
    result = native_math.call('destr_required_chunks', sweep_boxes,
        (sensor._SOLID_CONTACT_RADIUS_1513,
         sensor._DESTRUCTIBLE_CHUNK_METRES_1513))
    if result is None:
        return None
    return ('ready', 'pending', 'hard')[result[0]], result[1]
''')
    edit(CLIENT + 'destructibles_sensor.py',
         'def _tree_motion_required_chunks_1513(sweep_boxes):',
         'def _reference_tree_motion_required_chunks_1513(sweep_boxes):')
    anchor = '\ndef prewarm_tree_registry(spaceID, pos, yaw, td=None, now=None,'
    adapter = '''
_PINNED_TREE_CHUNK_LAWS_1513 = (_box_xz_bounds, _tree_motion_axis_samples_1513)


def _tree_motion_required_chunks_1513(sweep_boxes):
	"""Plan the same chunk set before the unchanged registry/effect owners."""
	import AreaDestructibles
	import Math
	# There is no geometric computation for an empty builtin sweep. Avoid
	# admission/FFI work while keeping the original mapper availability rule.
	if type(sweep_boxes) in (tuple, list) and not sweep_boxes:
		return ('pending' if callable(getattr(
			AreaDestructibles, 'chunkIDFromPosition', None)) else 'hard'), ()
	if ((_box_xz_bounds, _tree_motion_axis_samples_1513) ==
			_PINNED_TREE_CHUNK_LAWS_1513):
		result = _native_geometry.required_chunks(
			_native_sensor, AreaDestructibles, Math, sweep_boxes)
		if result is not None:
			combat_count('destructible_required_chunks_native')
			return result
	combat_count('destructible_required_chunks_reference')
	return _reference_tree_motion_required_chunks_1513(sweep_boxes)

'''
    edit(CLIENT + 'destructibles_sensor.py', anchor, '\n' + adapter + anchor)
    path = 'tools/check_native_destructibles.py'
    target = ROOT / path
    # This script already runs the actual persistent-index contracts. Append
    # the new stateless contract without replacing any established group.
    suffix = ("\nif __name__ == '__main__':\n"
              '    from check_native_destructible_chunks import run as check_chunks\n'
              '    check_chunks(native_math._backend.backend)\n')
    target.write_text(target.read_text() + suffix)
    changed.append(path)
    changed.append('native/offline_math_batch_native.pyd')
    output = Path(sys.argv[1])
    output.write_text(json.dumps(changed, indent=2) + '\n')
    print('Integrated stateless swept-hull chunk planning:', changed)


if __name__ == '__main__':
    main()
