"""Physical invariants for rigid contact, independent of map coordinates."""
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import collision_geometry as geometry
from gui.mods.offline_lan_0922 import vehicle_physics, tank_collision


class RigidContactTests(unittest.TestCase):
    bbox = ((-1., -.5, -3.), (1., 1.5, 3.))

    def motion(self, delta=.5, end=(0., 0., 0.), dt=.2):
        return {'start': (0., 0., 0.), 'end': end, 'yaw': 0.,
                'yaw_delta': delta, 'bbox': self.bbox, 'dt': dt}

    def test_axes_preserve_lengths_angles_and_volume_on_slopes(self):
        for yaw, pitch, roll in ((.7, .6, -.4), (-2., -.6, .6), (0., 1., 1.)):
            axes = geometry.pose_axes(yaw, pitch, roll)
            for i in range(3):
                for j in range(3):
                    self.assertAlmostEqual(float(i == j), geometry.dot(axes[i], axes[j]))
            self.assertAlmostEqual(1., geometry.dot(axes[0], geometry.cross(axes[1], axes[2])))

    def test_arc_empty_envelope_corner_does_not_block(self):
        motion = self.motion()
        envelope = geometry.motion_envelope(motion)
        maximum = [envelope[0][i]+sum(abs(a[i]) for a in envelope[1]) for i in range(3)]
        obstacle = geometry.body_box((maximum[0]-.02, .5, maximum[2]-.02), 0.,
                                     ((-.01, -.1, -.01), (.01, .1, .01)))
        self.assertGreater(geometry.contact(envelope, obstacle)[0], 0.)
        self.assertIsNone(geometry.sweep_contact(motion, obstacle))

    def test_thin_object_crossed_mid_arc_is_seen_even_with_both_ends_clear(self):
        motion = self.motion()
        x, z = math.cos(.25)+3*math.sin(.25), -math.sin(.25)+3*math.cos(.25)
        obstacle = geometry.body_box((x, .5, z), 0., ((-.015, -.1, -.015), (.015, .1, .015)))
        for yaw in (0., .5):
            self.assertLess(geometry.contact(geometry.body_box((0.,0.,0.), yaw, self.bbox), obstacle)[0], 0.)
        witness = geometry.sweep_contact(motion, obstacle)
        self.assertIsNotNone(witness)
        self.assertGreater(witness['fraction'], 0.)
        self.assertLess(witness['fraction'], 1.)
        self.assertGreater(geometry.contact_speed(motion, witness), 0.)

    def test_arbitrarily_close_parallel_motion_is_not_a_collision_margin(self):
        obstacle = geometry.body_box((2.+1e-10, .5, 0.), 0., self.bbox)
        self.assertIsNone(geometry.sweep_contact(self.motion(delta=0., end=(0.,0.,10.)), obstacle))

    def test_real_translation_first_contact_and_normal_speed(self):
        obstacle = geometry.body_box((0., 0., 8.), 0., self.bbox)
        motion = self.motion(delta=0., end=(0.,0.,4.), dt=2.)
        witness = geometry.sweep_contact(motion, obstacle)
        self.assertAlmostEqual(.5, witness['fraction'], places=6)
        self.assertAlmostEqual(2., geometry.contact_speed(motion, witness))

    def test_moving_contact_speed_uses_velocity_at_the_contact(self):
        motion = self.motion(delta=.2, end=(0.,0.,1.), dt=.5)
        witness = {'point': (1.,0.,3.), 'position': (0.,0.,0.), 'normal': (-1.,0.,0.)}
        self.assertAlmostEqual(1.2, geometry.contact_speed(motion, witness))
        witness['normal'] = (0.,0.,-1.)
        self.assertAlmostEqual(1.6, geometry.contact_speed(motion, witness))

    def test_wall_projection_is_idempotent_and_cannot_create_energy(self):
        velocity = (3., 0., 4.)
        normal = (-1.,0.,0.)
        after = vehicle_physics.world_contact_velocity(velocity, normal)
        self.assertEqual((0.,0.,4.), after)
        for unused in range(200):
            after = vehicle_physics.world_contact_velocity(after, normal)
        self.assertEqual((0.,0.,4.), after)
        self.assertLessEqual(geometry.dot(after, after), geometry.dot(velocity, velocity))

    def test_asymmetric_tank_shape_never_fills_mirrored_empty_space(self):
        shape = (.5, 1., 0., 1., 1.5, 2.)
        body = {'x': 0., 'y': 0., 'z': 0., 'yaw': 0., 'shape': shape}
        self.assertTrue(tank_collision.body_contains_point(body, (1.5,.5,2.), slop=0.))
        self.assertFalse(tank_collision.body_contains_point(body, (-1.5,.5,-2.), slop=0.))
        self.assertLess(tank_collision._obb_overlap(0.,0.,0.,shape, -1.5,-2.,0.,(.5,1.,0.,1.))[2], 0.)
        pitched = dict(body, pitch=.3, roll=.2)
        axes = geometry.pose_axes(0., .3, .2)
        center = tuple(axes[0][i]*1.5+axes[1][i]*.5+axes[2][i]*2. for i in range(3))
        self.assertTrue(tank_collision.body_contains_point(pitched, center, slop=0.))


if __name__ == '__main__':
    unittest.main()
