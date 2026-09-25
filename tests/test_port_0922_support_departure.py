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
LAYERED_REPORT = json.loads((Path(__file__).parent / 'fixtures' /
    'sacred_valley_20260925_layered_support.json').read_text())


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


def layered_scene(contact, backing=False, lower_gap=False):
    """Reconstruct the recorded lower face and the independently seen rail.

    The report proves these contacts along the centre lane, not the shape of
    the whole bridge. Restrict the planes to that local strip. A gap or wall
    is an explicit negative-control variant rather than recorded geometry.
    """
    origin = Vector(*contact['hit'])
    position = Vector(*contact['position'])
    sine, cosine = math.sin(contact['yaw']), math.cos(contact['yaw'])
    planes = [(origin, Vector(*contact['normal']), 'lower'),
              (Vector(*LAYERED_REPORT['native_replay_contact']['hit']),
               Vector(*LAYERED_REPORT['native_replay_contact']['normal']), 'deck'),
              (Vector(origin.x, contact['profile'][0], origin.z),
               Vector(0., 1., 0.), 'upper')]
    # The two recorded hits are 8.6 cm apart along the ray. Reconstruct a
    # junction between them, rather than pretending they were two answers
    # at the same point or extending one triangle through the other.
    join = (origin + Vector(*LAYERED_REPORT['native_replay_contact']['hit'])).scale(0.5)
    join_z = (join.x-position.x)*sine + (join.z-position.z)*cosine
    if backing:
        end = Vector(*contact['ray_end'])
        normal = origin - end
        normal.y = 0.
        normal.normalise()
        planes.append((origin + (end - origin).scale(0.5), normal, 'wall'))

    def collide(space, start, end, mask, *unused):
        delta = end - start
        hits = []
        for point, normal, kind in planes:
            denominator = delta.x*normal.x + delta.y*normal.y + delta.z*normal.z
            if abs(denominator) < 1e-12:
                continue
            offset = point - start
            fraction = (offset.x*normal.x + offset.y*normal.y + offset.z*normal.z) / denominator
            if not 0. <= fraction <= 1.:
                continue
            hit = start + delta.scale(fraction)
            relative = hit - position
            local_x = relative.x*cosine - relative.z*sine
            local_z = relative.x*sine + relative.z*cosine
            if abs(local_x) >= 0.2:
                continue
            if ((kind == 'deck' and local_z >= join_z) or
                    (kind == 'lower' and local_z < join_z)):
                continue
            if lower_gap and kind in ('lower', 'deck') and local_z < 1.0:
                continue
            hits.append((fraction, hit, normal))
        if not hits:
            return None
        unused_fraction, point, normal = min(hits, key=lambda row: row[0])
        return point, normal, 0
    return types.SimpleNamespace(wg_collideSegment=collide,
        wg_getMatInfoNearPoint=fixtures._miss_mat_info_1513)


class SupportDepartureTests(unittest.TestCase):
    def test_captured_lower_bridge_layer_is_not_a_horizontal_wall(self):
        contact = LAYERED_REPORT['contact']
        left, right = contact['lateral_bounds']
        unused_width, back, front = contact['extents']
        descriptor = fixtures._Strict1513Component(
            hull=fixtures._Strict1513Component(hitTester=types.SimpleNamespace(
                bbox=((left, -1., -back), (right, 2., front), None))))
        # The old occupied-body exception correctly does not accept this new
        # hit just beyond its front edge. Continuity of the actual lower deck
        # must prove support instead of relaxing that boundary or its normal.
        self.assertFalse(departure(contact, 0.01, 0.)(
            (Vector(*contact['hit']), Vector(*contact['normal']))))
        for backing, lower_gap, expected in ((False, False, 'clear'),
                (True, False, 'hard'), (False, True, 'hard')):
            trace = {}
            with self.subTest(backing=backing, lower_gap=lower_gap), mock.patch.object(
                    world_collision, '_destroy_and_recast', return_value=False):
                result = world_collision.check_horizontal_collision(
                    layered_scene(contact, backing, lower_gap),
                    types.SimpleNamespace(Vector3=Vector), 1,
                    Vector(*contact['position']), contact['yaw'], contact['speed'],
                    descriptor, False, contact['dt'], True, commit_enabled=False,
                    pitch=contact['pitch'], roll=contact['roll'], trace=trace)
            self.assertEqual(expected, result, trace)

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

    def test_swept_roll_height_only_releases_tangent_support(self):
        pose = world_collision._hull_pose_y(0.0, -0.55)
        predicate = world_collision._translation_departing_contact(
            Vector(), 0.0, (-1.5, 1.5, 3.0, 3.0), pose, -0.03, 0.0)
        # Inside the previous XZ footprint but only in the destination
        # perimeter's lower height band, the failure in a rolling origin shift.
        point = Vector(-0.3, (-0.3+0.015)*pose[0] + 0.6*pose[1], 0.0)
        self.assertTrue(predicate((point, Vector(0.0, 1.0, 0.0))))
        self.assertFalse(predicate((point, Vector(0.5, 1.0, 0.0))))
        self.assertFalse(predicate((point, Vector(1.0, 0.0, 0.0))))
        self.assertFalse(predicate((point, Vector(0.0, -1.0, 0.0))))

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
