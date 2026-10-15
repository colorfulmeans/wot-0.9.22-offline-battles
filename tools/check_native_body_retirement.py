"""Run with CPython 2.7 and a WOT_HOST_PYTHON x86 bridge, not the game pyd."""
from __future__ import print_function
import imp
import sys

b = imp.load_dynamic('offline_math_batch_native', sys.argv[1])
h = b.destr_open()
try:
    items = ((7, (0., 0., 0.), 1, 1, 0, 1.),
             (8, (1., 0., 0.), 0, 1, 0, 1.))
    assert b.destr_update(h, 2, (22., items, (((0, 0), (7, 8)),), ())) == 1
    pose = ((0., 0., 0.), 0., 0., 0., 0., None, (-2., -1., -3.), (2., 1., 3.))
    sweep = ((0., 0., 0.), ((2., 0., 0.), (0., 1., 0.), (0., 0., 3.)), None)
    original = b.destr_query(h, 1, (22., pose, 2., sweep))
    assert original[0] == (7, 8), original
    partial = b.destr_query(h, 11, (22., pose, 2., sweep, (7,)))
    assert partial[0] == (8,), partial
    empty = b.destr_query(h, 11, (22., pose, 2., sweep, (7, 8)))
    assert empty == ((), 0, 0), empty
    assert b.destr_query(h, 1, (22., pose, 2., sweep)) == original
    assert b.destr_query(h, 11, (22., pose, 2., sweep, ('wrong',))) is None
    print('Native retirement: active, partial, empty, isolation and rejection passed')
finally:
    b.destr_close(h)
