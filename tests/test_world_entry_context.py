"""A shared callback must retain the exact engine of each synchronous solve."""
import types
import unittest
from gui.mods.offline_lan_0922 import native_world


class WorldEntryContextTests(unittest.TestCase):
    def test_ground_callback_keeps_engine_owner_across_nested_solves(self):
        calls = []
        def vector(x, y, z):
            return types.SimpleNamespace(x=x, y=y, z=z)
        first_engine, second_engine = object(), object()
        def context(engine):
            module = types.SimpleNamespace(
                _UNPREPARED_COLLISION_FILTER=object(),
                ground_collision_filter=lambda x,z: None,
                collide_motion_segment=lambda space,a,b,f,method,label:
                    calls.append((method, space, (a.x,a.y,a.z), label)))
            return native_world._WorldDispatch((module, None,
                [module._UNPREPARED_COLLISION_FILTER, None], vector,
                vector(0.,0.,0.), 0., (-1.,1.,3.,3.), (0.,2.), None,
                7, 5., None, [False], False, None, False, None, {},
                None, module.ground_collision_filter,
                types.SimpleNamespace(wg_collideSegment=engine))).dispatch
        first, second = context(first_engine), context(second_engine)
        rows = (((0.,2.,0.), (0.,-2.,0.), 0),)
        for arm in (first, second, first):
            self.assertIsNone(arm(4, rows)[0][0])
        self.assertEqual([first_engine, second_engine, first_engine],
                         [row[0] for row in calls])
        self.assertEqual([7,7,7], [row[1] for row in calls])


if __name__ == '__main__':
    unittest.main()
