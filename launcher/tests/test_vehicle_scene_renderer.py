"""Pixel-level contracts independent of triangle submission order or Tk."""
import unittest
import numpy as np
from vehicle_scene_renderer import rasterize


def obj(identity, points, color, alpha=1.):
    return dict(id=identity, alpha=alpha, triangles=[(points, color)])


class DepthRendererTests(unittest.TestCase):
    def test_crossing_triangles_use_interpolated_depth_not_centroid_sorting(self):
        a = obj(1, ((0,0,0),(20,0,10),(0,20,0)), (255,0,0))
        b = obj(2, ((0,0,4),(20,0,4),(0,20,4)), (0,0,255))
        first, ids = rasterize(22,22,[a,b])
        second, reversed_ids = rasterize(22,22,[b,a])
        self.assertEqual(2, ids[2,2]); self.assertEqual(1,ids[2,14])
        np.testing.assert_array_equal(ids,reversed_ids)
        np.testing.assert_array_equal(np.asarray(first),np.asarray(second))

    def test_transparent_front_shell_preserves_interior_and_does_not_capture_click(self):
        triangle = ((0,0,5),(20,0,5),(0,20,5))
        shell = obj(0, triangle, (200,200,200), .2)
        module = obj(7,tuple((x,y,z-3) for x,y,z in triangle),(255,0,0))
        image, ids = rasterize(22,22,[shell,module])
        self.assertEqual(7,ids[4,4])
        self.assertEqual((244,40,40),tuple(np.asarray(image)[4,4]))
        # Only original triangles form context: no convex envelope fills this gap.
        self.assertEqual((23,27,34),tuple(np.asarray(image)[18,18]))
        self.assertEqual(0,ids[18,18])
        shell['alpha']=1.
        _, ids=rasterize(22,22,[shell,module])
        self.assertEqual(0, ids[4,4])

    def test_opaque_front_module_occludes_rear_and_zero_opacity_never_picks(self):
        t = ((0,0,2),(20,0,2),(0,20,2))
        back = obj(8,t,(0,200,0))
        front = obj(9,tuple((x,y,z+2) for x,y,z in t),(0,0,255))
        image, ids = rasterize(22,22,[front,back])
        self.assertEqual(9,ids[3,3])
        self.assertEqual((0,0,255),tuple(np.asarray(image)[3,3]))
        front['alpha']=0
        _, ids=rasterize(22,22,[front,back])
        self.assertEqual(8,ids[3,3])

    def test_shared_volume_triangles_do_not_accumulate_alpha_at_seams(self):
        triangles=[(((0,0,2),(20,0,2),(0,20,2)),(200,0,0)),
                   (((0,0,1),(20,0,1),(0,20,1)),(200,0,0))]
        image,_=rasterize(22,22,[dict(id=1,alpha=.5,triangles=triangles)])
        self.assertEqual((111,13,17),tuple(np.asarray(image)[4,4]))
