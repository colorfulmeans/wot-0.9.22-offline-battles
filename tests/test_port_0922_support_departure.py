"""Replay real bridge support contacts without treating them as side walls."""
import json
import math
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import test_port_0922_world_collision as fixtures
from gui.mods.offline_lan_0922 import vehicle_physics, world_collision

Vector = fixtures._Vector
REPORT = json.loads((Path(__file__).parent / 'fixtures' /
    'sacred_valley_20260925_support_contacts.json').read_text())


def departure(contact, dx, dz):
    left, right = contact['lateral_bounds']
    unused_width, back, front = contact['extents']
    return world_collision._translation_departing_contact(
        Vector(*contact['position']), contact['yaw'],
        (left, right, back, front), world_collision._hull_pose_y(
            contact['pitch'], contact['roll']), dx, dz)


def plane_scene(contact, backing=False):
    """Intersect the captured support plane and an optional later wall."""
    origin = Vector(*contact['hit'])
    end = Vector(*contact['ray_end'])
    wall = origin + (end - origin).scale(0.5)
    # The wall is a separate physical face after the reported support hit.
    normal = Vector(origin.x - end.x, 0., origin.z - end.z)
    normal.normalise()
    planes = [(origin, Vector(*contact['normal']))]
    if backing:
        planes.append((wall, normal))

    def collide(space, start, end, mask, *unused):
        delta = end - start
        hits = []
        for point, face in planes:
            denominator = delta.x*face.x + delta.y*face.y + delta.z*face.z
            if abs(denominator) < 1e-12:
                continue
            offset = point - start
            fraction = (offset.x*face.x + offset.y*face.y + offset.z*face.z) / denominator
            if 0. <= fraction <= 1.:
                hits.append((fraction, start + delta.scale(fraction), face))
        if not hits:
            return None
        unused_fraction, point, face = min(hits, key=lambda row: row[0])
        return point, face, 0
    return types.SimpleNamespace(wg_collideSegment=collide)


class SupportDepartureTests(unittest.TestCase):
    def test_native_hull_probe_releases_captured_support_for_roll_and_push(self):
        contact = REPORT['contacts'][2]
        left, right = contact['lateral_bounds']
        unused_width, back, front = contact['extents']
        descriptor = fixtures._Strict1513Component(
            hull=fixtures._Strict1513Component(hitTester=types.SimpleNamespace(
                bbox=((left, -1., -back), (right, 2., front), None))))
        center = Vector(*contact['hit'])

        def collide(space, start, end, mask, *unused):
            dy = end.y - start.y
            if abs(dy) < 1e-12:
                return None
            fraction = (center.y - start.y) / dy
            if not 0. <= fraction <= 1.:
                return None
            point = start + (end - start).scale(fraction)
            # Reconstruct only a local piece of the observed native face;
            # this does not pretend the unrecorded whole bridge is flat.
            if (point.x-center.x)**2 + (point.z-center.z)**2 > 0.4**2:
                return None
            return point, Vector(0., 1., 0.), 0

        scene = types.SimpleNamespace(wg_collideSegment=collide,
            wg_getMatInfoNearPoint=fixtures._miss_mat_info_1513)
        for speed, dt in ((contact['speed'], contact['dt']), (1.0, 0.04)):
            with self.subTest(speed=speed), mock.patch.object(
                    world_collision, '_destroy_and_recast', return_value=False):
                args = (scene, types.SimpleNamespace(Vector3=Vector), 1,
                    Vector(*contact['position']), contact['yaw'], speed,
                    descriptor, False, dt, True)
                keywords = dict(commit_enabled=False, pitch=contact['pitch'],
                    roll=contact['roll'], motion_yaw=contact['motion_yaw'])
                self.assertEqual('clear', world_collision.check_horizontal_collision(
                    *args, **keywords))
                # Disabling departure reproduces the reported support-as-wall
                # verdict with a real intersection and the full native adapter.
                self.assertEqual('hard', world_collision.check_horizontal_collision(
                    *args, departing_contact=lambda hit: False, **keywords))

    def test_captured_bridge_top_does_not_absorb_mass_center_origin_shift(self):
        contact = REPORT['contacts'][2]
        # This is the actual COM correction at log line 879, not drive intent.
        motion = contact['motion_yaw']
        distance = contact['speed'] * contact['dt']
        dx, dz = math.sin(motion)*distance, math.cos(motion)*distance
        yaw = contact['yaw']
        local = (math.cos(yaw)*dx - math.sin(yaw)*dz,
                 math.sin(yaw)*dx + math.cos(yaw)*dz)
        calls = []

        def probe(sx, sz):
            with mock.patch.dict(sys.modules, {'BigWorld': plane_scene(contact)}):
                hit = world_collision._collide_horizontal(
                    1, Vector(*contact['ray_start']), Vector(*contact['ray_end']),
                    collision_filter=None, departing_contact=departure(contact, sx, sz))
            calls.append(hit)
            return hit is None, None if hit is None else (hit[1].x, hit[1].y, hit[1].z)

        after = vehicle_physics.resolve_suspension_origin_shift(yaw, local, probe)
        self.assertAlmostEqual(dx, after[0])
        self.assertAlmostEqual(dz, after[1])
        self.assertEqual([None], calls)

    def test_each_captured_support_recasts_and_keeps_a_later_wall(self):
        for contact in REPORT['contacts']:
            with self.subTest(line=contact['source_line']):
                motion = contact['motion_yaw']
                if motion is None:
                    motion = contact['yaw'] + (math.pi if contact['speed'] < 0 else 0.)
                predicate = departure(contact, math.sin(motion)*0.01, math.cos(motion)*0.01)
                self.assertTrue(predicate((Vector(*contact['hit']), Vector(*contact['normal']))))
                with mock.patch.dict(sys.modules, {'BigWorld': plane_scene(contact, True)}):
                    hit = world_collision._collide_horizontal(
                        1, Vector(*contact['ray_start']), Vector(*contact['ray_end']),
                        collision_filter=None, departing_contact=predicate)
                self.assertIsNotNone(hit)
                self.assertAlmostEqual(0., hit[1].y)

    def test_new_surface_inward_slope_and_downward_face_still_block(self):
        predicate = world_collision._translation_departing_contact(
            Vector(), 0., (-1.5, 1.5, 3., 3.), (0., 1., 0.), 0.1, 0.)
        self.assertFalse(predicate((Vector(1.6, 1., 0.), Vector(0., 1., 0.))))
        self.assertFalse(predicate((Vector(0., 1., 0.), Vector(-0.5, 1., 0.))))
        self.assertFalse(predicate((Vector(0., 1., 0.), Vector(0., -1., 0.))))
        self.assertTrue(predicate((Vector(0., 1., 0.), Vector(0.5, 1., 0.))))

    def test_repeated_native_surface_exhaustion_remains_blocking(self):
        contact = REPORT['contacts'][2]
        repeated = (Vector(*contact['hit']), Vector(*contact['normal']), 0)
        scene = types.SimpleNamespace(wg_collideSegment=mock.Mock(return_value=repeated))
        with mock.patch.dict(sys.modules, {'BigWorld': scene}):
            hit = world_collision._collide_horizontal(
                1, Vector(*contact['ray_start']), Vector(*contact['ray_end']),
                collision_filter=None, departing_contact=departure(contact, 0.01, 0.))
        self.assertIs(repeated, hit)
        self.assertEqual(world_collision._WORLD_SOFT_RECAST_BUDGET + 1,
                         scene.wg_collideSegment.call_count)


if __name__ == '__main__':
    unittest.main()
