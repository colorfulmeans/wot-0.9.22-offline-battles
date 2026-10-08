"""CPython 2.7 gate: every packaged client module matches this checkout."""
from __future__ import print_function
import marshal
import os
import sys
import types
import zipfile


def signature(value):
    if isinstance(value, types.CodeType):
        return tuple(signature(getattr(value, key)) for key in (
            'co_argcount', 'co_nlocals', 'co_stacksize', 'co_flags', 'co_code',
            'co_consts', 'co_names', 'co_varnames', 'co_name', 'co_freevars',
            'co_cellvars', 'co_firstlineno', 'co_lnotab'))
    if isinstance(value, tuple):
        return tuple(signature(item) for item in value)
    return value


root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
source = os.path.join(root, 'src', 'res', 'scripts', 'client')
expected = {}
for base, dirs, files in os.walk(source):
    for name in files:
        if name.endswith('.py'):
            path = os.path.join(base, name)
            member = os.path.relpath(path, os.path.join(root, 'src')).replace(os.sep, '/') + 'c'
            expected[member] = path
with zipfile.ZipFile(sys.argv[1]) as archive:
    assert archive.testzip() is None
    names = set(n for n in archive.namelist() if n.endswith('.pyc'))
    assert names == set(expected), 'Client bytecode inventory differs from source'
    for name, path in sorted(expected.items()):
        raw = archive.read(name)
        assert raw[:4] == b'\x03\xf3\r\n', name
        actual = marshal.loads(raw[8:])
        accepted = compile(open(path, 'rb').read(), actual.co_filename, 'exec')
        assert signature(actual) == signature(accepted), name
    assert 'res/gui/flash/lobby.swf' in archive.namelist(), 'Missing warehouse/shop style UI'
print('Current release client bytecode verified:', len(expected), 'modules')
