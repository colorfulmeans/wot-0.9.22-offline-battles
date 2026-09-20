"""Reuse only identical rays within one synchronous read-only rotation."""
import types
import unittest

import test_port_0922_battle_runtime as local
from gui.mods.offline_lan_0922 import world_collision


class RotationQueryReuseTests(unittest.TestCase):
    def test_callback_candidates_are_replayed_and_a_changed_filter_requeries(self):
        calls, observed = [], []
        original, backing = (74, 131, 23, 32636), (111, 0, 99, 32636)
        accepted = set()

        def keep(*surface):
            observed.append(surface)
            return surface not in accepted

        def native(space, start, end, mask, callback):
            calls.append((start.x, end.x))
            for index, surface in enumerate((original, backing)):
                if callback(*surface):
                    return (local._Vector(index + 1., 0., 0.), local._Vector(-1., 0., 0.))

        queries = world_collision.ReadOnlyMotionQueries(types.SimpleNamespace(wg_collideSegment=native))
        args = (1, local._Vector(), local._Vector(4., 0., 0.), 80, keep)
        first = queries.wg_collideSegment(*args)
        observed[:] = []
        second = queries.wg_collideSegment(*args)
        self.assertEqual(first, second)
        self.assertEqual([original], observed)
        self.assertEqual(1, len(calls))
        accepted.add(original)
        after = queries.wg_collideSegment(*args)
        self.assertEqual(2., after[0].x)
        self.assertEqual(2, len(calls))

    def test_different_geometry_masks_and_query_lifetimes_never_share_a_hit(self):
        calls = []
        def native(*args):
            calls.append(args)
            return None
        engine = types.SimpleNamespace(wg_collideSegment=native, sentinel=17)
        queries = world_collision.ReadOnlyMotionQueries(engine)
        start, end = local._Vector(), local._Vector(4., 0., 0.)
        for args in ((1, start, end, 80), (2, start, end, 80),
                     (1, start, end, 16), (1, end, start, 80),
                     (1, start, local._Vector(4.000000001, 0., 0.), 80)):
            queries.wg_collideSegment(*args)
        self.assertEqual(5, len(calls))
        self.assertEqual(17, queries.sentinel)
        world_collision.ReadOnlyMotionQueries(engine).wg_collideSegment(1, start, end, 80)
        self.assertEqual(6, len(calls))


if __name__ == '__main__':
    unittest.main()
