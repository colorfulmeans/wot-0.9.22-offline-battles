"""Integrate one validated native destructible preparation batch in a copy."""
from pathlib import Path
import ast
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'src/res/scripts/client/gui/mods/offline_lan_0922/'
changed = []


def replace(text, old, new):
    assert text.count(old) == 1, ('unexpected source anchor', old[:120])
    return text.replace(old, new)


def edit(path, transform):
    target = ROOT / path
    before = target.read_text()
    after = transform(before)
    assert after != before, ('unchanged patch', path)
    target.write_text(after)
    changed.append(path)


def bridge(text):
    text = replace(text, 'PyObject *WOT_CDECL destr_open(PyObject *,PyObject *args) {',
        '#include "offline_destructible_prepare_python.inc"\n\n'
        'PyObject *WOT_CDECL destr_open(PyObject *,PyObject *args) {')
    anchor = 'PyObject *WOT_CDECL destr_query(PyObject *,PyObject *args) {'
    before, tail = text.split(anchor)
    start = '        if(op==0){require_sequence(v[2],2,true);'
    tail = replace(tail, start,
        '        if(op==8)return destructible_prepare_law::run(store.get(),v[2],profile);\n' + start)
    return before + anchor + tail


def sensor(text):
    return replace(text,
        "\treturn filename.replace('\\\\', '/').strip().lower()\n",
        "\treturn filename.replace('\\\\', '/').strip().lower()\n\n"
        "\n# Pinned only for native chunk-preparation truth-value projection.\n"
        "_NATIVE_FILENAME_LAW = (_normalized_filename, _STRING_TYPES)\n")


def adapter(text):
    original = ast.parse(text)
    text = replace(text, 'from __future__ import print_function\n',
        'from __future__ import print_function\n\nimport types\n'
        'try:\n    _CHUNK_ID_TYPES = (int, long, float, bool)\n'
        'except NameError:\n    _CHUNK_ID_TYPES = (int, float, bool)\n')
    text = replace(text,
        '    def chunk(self, sensor, chunk_id, registry, tree_type=None):',
        '    def _reference_chunk(self, sensor, chunk_id, registry, tree_type=None):')
    wrapper = '''
    def chunk(self, sensor, chunk_id, registry, tree_type=None):
        """Prepare and register a complete fresh chunk in one native call."""
        if type(chunk_id) not in _CHUNK_ID_TYPES:
            return self._reference_chunk(sensor, chunk_id, registry, tree_type)
        current = self.chunks.get(int(chunk_id))
        if current is not None and current[0] is registry:
            return current[1]
        # Keep the hot cache return above all expensive admission and input
        # preparation. Replaced Python mutation/query owners keep their path.
        ordinary_owner = (type(self) is Geometry and
            'update' not in self.__dict__ and 'query' not in self.__dict__ and
            Geometry.__dict__['update'] is _NATIVE_CHUNK_METHODS[0] and
            Geometry.__dict__['query'] is _NATIVE_CHUNK_METHODS[1])
        if (ordinary_owner and type(sensor) is types.ModuleType and
                type(registry) is dict and all(type(key) is str for key in registry)):
            pinned = getattr(sensor, '_NATIVE_FILENAME_LAW', None)
            if (type(pinned) is tuple and len(pinned) == 2 and
                    pinned[0] is sensor._normalized_filename and
                    pinned[1] is sensor._STRING_TYPES):
                import AreaDestructibles
                if type(AreaDestructibles) is types.ModuleType:
                    tree = AreaDestructibles.DESTR_TYPE_TREE if tree_type is None else tree_type
                    labels = (tree, AreaDestructibles.DESTR_TYPE_FRAGILE,
                              getattr(AreaDestructibles, 'DESTR_TYPE_STRUCTURE', None),
                              AreaDestructibles.DESTR_TYPE_FALLING_ATOM)
                    origins = registry.get('bins', {})
                    extended = registry.get('extended_bins', {})
                    if type(origins) is dict and type(extended) is dict:
                        prepared = self.query(8, (
                            float(chunk_id), tuple(origins.items()),
                            tuple(extended.items()), labels))
                        if prepared is not None:
                            items = dict(prepared)
                            self.chunks[int(chunk_id)] = registry, items
                            return items
        # Rejection has not changed the Store or invoked user conversions.
        return self._reference_chunk(sensor, chunk_id, registry, tree_type)


_NATIVE_CHUNK_METHODS = (Geometry.__dict__['update'], Geometry.__dict__['query'])

'''
    text = replace(text, '\n\ndef reset():', '\n' + wrapper + '\ndef reset():')
    def method(tree, name):
        owner = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'Geometry')
        return next(x for x in owner.body if isinstance(x, ast.FunctionDef) and x.name == name)
    old = method(original, 'chunk')
    new = method(ast.parse(text), '_reference_chunk')
    new.name = 'chunk'
    assert ast.dump(old) == ast.dump(new), 'original chunk law changed'
    return text


def checker(text):
    text = replace(text,
        "    assert set(op for (name,op) in backend.calls if name=='destr_query') == set(range(8))",
        "    assert set(op for (name,op) in backend.calls if name=='destr_query') == set(range(9))")
    anchor = "    assert set(op for (name,op) in backend.calls if name=='destr_update') == set(range(5))"
    return replace(text, anchor,
        "    # Retain independent coverage of the original typed update opcode.\n"
        "    legacy = backend.destr_open()\n"
        "    assert backend.destr_update(legacy,2,(22.,((0,(0.,0.,0.),1,1,0,0.),),(((0,0),(0,)),),())) == 1\n"
        "    assert backend.destr_close(legacy) == 1\n" + anchor + "\n"
        "    from check_native_destructible_prepare import run as check_prepare\n"
        "    check_prepare(raw)\n")


if __name__ == '__main__':
    assert len(sys.argv) == 2, 'usage: apply_native_destructible_prepare_migration.py MANIFEST'
    edit('native/offline_destructible_python.inc', bridge)
    edit(PREFIX + 'destructibles_sensor.py', sensor)
    edit(PREFIX + 'native_destructibles.py', adapter)
    edit('tools/check_native_destructibles.py', checker)
    changed.append('native/offline_math_batch_native.pyd')
    Path(sys.argv[1]).write_text(json.dumps(changed, indent=2) + '\n')
    print('Destructible preparation integration paths:', changed)
