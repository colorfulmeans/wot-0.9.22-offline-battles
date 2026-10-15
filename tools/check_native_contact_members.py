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
    cold = b.destr_query(h, 13, (0., 0., 0., 0.))
    assert cold == (((22., 7), (22., 8)), 0), cold
    assert b.destr_query(h, 13, (.1, .2, .3, .4)) == (cold[0], 1)
    moved_box = ((1., 0., 0.), box[1], None)
    assert b.destr_update(h, 0, ((22., 7), 0, (moved_box,), ((-1, 0), (0, 0)))) == 1
    assert b.destr_query(h, 13, (0., 0., 0., 0.)) == (cold[0], 1)
    probe = ((-.75, 0., 0.), ((.1, 0., 0.), (0., .1, 0.), (0., 0., .1)), None)
    assert b.destr_query(h, 0, (probe, None))[0] == ()
    assert b.destr_update(h, 0, ((22., 7), 0, (box,), ((-1, 0), (2, 0)))) == 1
    assert b.destr_query(h, 13, (0., 0., 0., 0.)) == (((22., 8),), 0)
    assert b.destr_update(h, 0, ((22., 7), 0, (box,), ((-1, 0), (0, 0)))) == 1
    assert b.destr_query(h, 13, (0., 0., 0., 0.)) == (cold[0], 0)
    assert b.destr_update(h, 1, (22., 7)) == 1
    assert b.destr_query(h, 12, (-.01, -.01, 0., 0.)) == ()
    assert b.destr_query(h, 12, (0., 8., 0., 0.)) == ((22., 8),)
    assert b.destr_update(h, 3, 22.) == 1
    assert b.destr_query(h, 12, (0., 8., 0., 0.)) == ()
    for index in range(257):
        bounds = (10000. + index * 8.,) * 2 + (0., 0.)
        assert b.destr_query(h, 13, bounds) == ((), 0)
    assert b.destr_query(h, 13, bounds) == ((), 1)
    assert b.destr_query(h, 13, (10000., 10000., 0., 0.)) == ((), 0)
    assert cold[0] == ((22., 7), (22., 8))
    other = b.destr_open()
    try:
        assert b.destr_query(other, 13, (0., 0., 0., 0.)) == ((), 0)
    finally:
        b.destr_close(other)
    print('Native contact cache: bins, dedup, live geometry, retirement, bounds and owner isolation passed')
finally:
    b.destr_close(h)
