"""Run with CPython 2.7 and the x86 host bridge, never the game pyd."""
from __future__ import print_function
import imp
import sys

b = imp.load_dynamic('offline_math_batch_native', sys.argv[1])
h = b.destr_open()
try:
    box = ((0., 0., 0.), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), None)
    for key, cells in (((22., 7), ((-1, 0), (0, 0))),
                       ((22., 8), ((0, 0), (1, 0))),
                       ((33., 9), ((0, 1),))):
        assert b.destr_update(h, 0, (key, 0, (box,), cells)) == 1
    assert b.destr_query(h, 12, (-.01, -.01, 0., 0.)) == ((22., 7),)
    assert b.destr_query(h, 12, (0., 8., 0., 0.)) == ((22., 7), (22., 8))
    assert b.destr_query(h, 12, (0., 0., 8., 8.)) == ((33., 9),)
    assert b.destr_query(h, 12, (16., 16., 0., 0.)) == ()
    assert b.destr_query(h, 12, (1., 0., 0., 0.)) is None
    assert b.destr_query(h, 12, (0., float('nan'), 0., 0.)) is None
    assert b.destr_query(h, 12, (0., 1.e50, 0., 0.)) is None
    assert b.destr_update(h, 1, (22., 7)) == 1
    assert b.destr_query(h, 12, (-.01, -.01, 0., 0.)) == ()
    assert b.destr_query(h, 12, (0., 8., 0., 0.)) == ((22., 8),)
    assert b.destr_update(h, 3, 22.) == 1
    assert b.destr_query(h, 12, (0., 8., 0., 0.)) == ()
    print('Native contact members: bins, dedup, retirement and rejection passed')
finally:
    b.destr_close(h)
