"""Real OpenGL pixel, resident geometry and independent-context contracts."""
import os
import unittest
import numpy as np
from vehicle_gpu_renderer import GpuRenderer


class GpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.renderer=GpuRenderer()
        except Exception as error:
            if os.environ.get('WOT_REQUIRE_GPU')=='1':raise
            raise unittest.SkipTest('OpenGL 3.3 is unavailable: %s'%error)

    @classmethod
    def tearDownClass(cls):cls.renderer.release()

    def render(self, objects, styles=None):
        r=self.renderer
        r.load(objects)
        return np.asarray(r.render(64,64,np.eye(4),np.eye(3),
            styles or [dict(alpha=1.) for _ in objects],lighting=False))

    def triangle(self,z,color,pick):
        return dict(triangles=[(((-1.,-1.,z),(1.,-1.,z),(0.,1.,z)),color,pick)])

    def test_crossing_geometry_uses_per_pixel_depth_independent_of_submission_order(self):
        a=dict(triangles=[(((-1.,-1.,.6),(1.,-1.,-.6),(0.,1.,.6)),(255,0,0),1)])
        b=self.triangle(0,(0,0,255),2)
        first=self.render([a,b]);left=self.renderer.pick(20,45);right=self.renderer.pick(43,45)
        second=self.render([b,a])
        self.assertEqual((2,1),(left,right))
        np.testing.assert_array_equal(first,second)

    def test_transparent_shell_does_not_intercept_pick_but_opaque_shell_does(self):
        shell=self.triangle(-.5,(200,200,200),0)
        module=self.triangle(0,(255,0,0),7)
        image=self.render([shell,module],[dict(alpha=.2),dict(alpha=1.)])
        self.assertEqual(7,self.renderer.pick(32,32))
        np.testing.assert_allclose((244,40,40),image[32,32],atol=1)
        self.renderer.render(64,64,np.eye(4),np.eye(3),[dict(alpha=1.),dict(alpha=1.)],lighting=False)
        self.assertEqual(0,self.renderer.pick(32,32))

    def test_visibility_and_camera_changes_do_not_reupload_geometry(self):
        self.render([self.triangle(0,(255,0,0),7)])
        before=self.renderer.uploads
        for _ in range(4):self.renderer.render(64,64,np.eye(4),np.eye(3),[dict(alpha=0.)])
        self.assertEqual(0,self.renderer.pick(32,32))
        self.assertEqual(before,self.renderer.uploads)

    def test_back_faces_in_same_object_do_not_accumulate_opacity(self):
        obj=self.triangle(-.5,(200,0,0),7)
        obj['triangles']+=self.triangle(.5,(200,0,0),7)['triangles']
        image=self.render([obj],[dict(alpha=.5)])
        np.testing.assert_allclose((111,13,17),image[32,32],atol=1)

    def test_another_context_cannot_break_existing_renderer_or_release(self):
        other=GpuRenderer()
        try:
            self.render([self.triangle(0,(255,0,0),7)])
            other.load([self.triangle(0,(0,0,255),8)])
            other.render(32,32,np.eye(4),np.eye(3),[dict(alpha=1.)])
            self.renderer.render(64,64,np.eye(4),np.eye(3),[dict(alpha=1.)])
            self.assertEqual(7,self.renderer.pick(32,32))
        finally:other.release()


if __name__=='__main__':unittest.main()
