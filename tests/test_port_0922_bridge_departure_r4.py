"""Replay captured r3 support tops and bridge sides through the full sweep."""
import json
import math
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import test_port_0922_world_collision as fixtures
from gui.mods.offline_lan_0922 import world_collision

Vector = fixtures._Vector
REPORT = json.loads((Path(__file__).parent / 'fixtures' /
    'sacred_valley_20260925_r3_departure.json').read_text())


def descriptor(contact):
    left, right = contact['lateral_bounds']
    unused_width, back, front = contact['extents']
    return fixtures._Strict1513Component(
        hull=fixtures._Strict1513Component(hitTester=types.SimpleNamespace(
            bbox=tuple(REPORT['hull_bbox']) + (None,))),
        chassis=fixtures._Strict1513Component(
            hullPosition=tuple(REPORT['hull_position']),
            hitTester=types.SimpleNamespace(bbox=(
                (left, 0., -back), (right, 1.3, front), None))))


def captured_scene(contact, backing=False):
    """Close only the recorded local support faces into a finite lip.

    The main hit and raw replay are different surfaces along one ray: the
    latter sees the upper support first, before departure recasts it. Preserve
    both that top and the lower/side hit. The remote bottom of the lip is a
    test closure, not a claim about unrecorded native bridge geometry.
    """
    target = Vector(*contact['hit'])
    normal = Vector(0.5518978238105774, 0., 0.8339117169380188)
    upper = 1.1093093156814575
    edge = 95.778902
    if contact is REPORT['contacts']['914']:
        # This capture proves the top but not a side beyond it. Keep that
        # closure beyond the recorded ray rather than inventing an early wall.
        edge = normal.x*target.x + normal.z*target.z + 0.2
    if abs(contact['normal'][1]) > 0.5:
        planes = [(target, Vector(*contact['normal']), 'lower')]
    else:
        planes = [(Vector(target.x, 0.86024475, target.z), Vector(0., 1., 0.), 'lower')]
    planes.extend(((Vector(target.x, upper, target.z), Vector(0., 1., 0.), 'upper'),
                   (normal.scale(edge), normal, 'side')))
    if backing:
        end = Vector(*contact['ray_end'])
        wall = target + (end-target).scale(0.75)
        direction = target-end
        direction.y = 0.
        direction.normalise()
        planes.append((wall, direction, 'wall'))
    calls = []

    def collide(space, start, end, mask, *unused):
        calls.append((start, end))
        delta = end-start
        hits = []
        for origin, face, kind in planes:
            denominator = delta.x*face.x + delta.y*face.y + delta.z*face.z
            if abs(denominator) < 1e-12:
                continue
            offset = origin-start
            fraction = (offset.x*face.x + offset.y*face.y + offset.z*face.z) / denominator
            if not 0. <= fraction <= 1.:
                continue
            point = start + delta.scale(fraction)
            if kind == 'side' and not 0.7 <= point.y <= upper:
                continue
            if kind not in ('side', 'wall') and point.x*normal.x+point.z*normal.z > edge+1e-7:
                continue
            hits.append((fraction, point, face))
        if not hits:
            return None
        unused_fraction, point, face = min(hits, key=lambda row: row[0])
        return point, face, 0
    return types.SimpleNamespace(wg_collideSegment=collide,
        wg_getMatInfoNearPoint=fixtures._miss_mat_info_1513, calls=calls)


class BridgeDepartureR4Tests(unittest.TestCase):
    def test_witnessed_profile_gap_cannot_be_skipped_from_a_farther_anchor(self):
        td = fixtures._Strict1513Component(
            hull=fixtures._Strict1513Component(hitTester=types.SimpleNamespace(
                bbox=((-1., 0., -2.), (1., 1., 2.), None))),
            chassis=fixtures._Strict1513Component(hullPosition=(0., 1., 0.),
                hitTester=types.SimpleNamespace(bbox=((-1., 0., -2.), (1., 1., 2.)))))
        missed_profile = []

        def collide(space, start, end, mask, *unused):
            radius = math.hypot(start.x-0.5, start.z)
            if 0.1 < radius < 0.4:
                missed_profile.append((start.x, start.z))
                return None
            if end.y <= 0.9 <= start.y:
                return Vector(start.x, 0.9, start.z), Vector(0., 1., 0.), 0
            return None

        with mock.patch.dict(sys.modules, {'BigWorld': types.SimpleNamespace(
                wg_collideSegment=collide)}):
            predicate = world_collision._supported_sweep_departure(
                1, types.SimpleNamespace(Vector3=Vector), Vector(), 0.,
                (-1., 1., 2., 2.), 0., 0., td, 0.1, 0., None, lambda hit: False)
            self.assertFalse(predicate((Vector(0.5, 0.8, 0.), Vector(1., 0., 0.))))
        self.assertTrue(missed_profile)

    def test_new_low_wall_inside_destination_only_has_no_old_hull_support(self):
        td = fixtures._Strict1513Component(
            hull=fixtures._Strict1513Component(hitTester=types.SimpleNamespace(
                bbox=((-1., 0., -2.), (1., 1., 2.), None))),
            chassis=fixtures._Strict1513Component(hullPosition=(0., 1., 0.),
                hitTester=types.SimpleNamespace(bbox=((-1., 0., -2.), (1., 1., 2.)))))

        def collide(space, start, end, mask, *unused):
            # Its low roof is inside the destination footprint, but wholly
            # beyond the currently occupied body. No old anchor touches it.
            height = 0.9 if start.x > 1.01 else 0.0
            if end.y <= height <= start.y:
                return Vector(start.x, height, start.z), Vector(0., 1., 0.), 0
            return None

        with mock.patch.dict(sys.modules, {'BigWorld': types.SimpleNamespace(
                wg_collideSegment=collide)}):
            predicate = world_collision._supported_sweep_departure(
                1, types.SimpleNamespace(Vector3=Vector), Vector(), 0.,
                (-1., 1., 2., 2.), 0., 0., td, 0.1, 0., None, lambda hit: False)
            self.assertFalse(predicate((Vector(1.05, 0.8, 0.), Vector(1., 0., 0.))))

    def test_captured_top_and_outward_side_release_but_backing_wall_remains(self):
        for source_line, contact in REPORT['contacts'].items():
            for backing in (False, True):
                trace = {}
                with self.subTest(line=source_line, backing=backing), mock.patch.object(
                        world_collision, '_destroy_and_recast', return_value=False):
                    result = world_collision.check_horizontal_collision(
                        captured_scene(contact, backing), types.SimpleNamespace(Vector3=Vector),
                        1, Vector(*contact['position']), contact['yaw'], contact['speed'],
                        descriptor(contact), False, contact['dt'], True, commit_enabled=False,
                        motion_yaw=contact['motion_yaw'], pitch=contact['pitch'],
                        roll=contact['roll'], trace=trace)
                    self.assertEqual('hard' if backing else 'clear', result, trace)

    def test_support_proof_keeps_inward_side_roof_gap_and_query_bound(self):
        # A box with an exposed upper face is distinguishable from an infinite
        # enclosing backface. Only a low connected roof under the installed
        # hull permits outward departure from the box already straddled.
        td = fixtures._Strict1513Component(
            hull=fixtures._Strict1513Component(hitTester=types.SimpleNamespace(
                bbox=((-1., 0., -2.), (1., 1., 2.), None))),
            chassis=fixtures._Strict1513Component(hullPosition=(0., 1., 0.),
                hitTester=types.SimpleNamespace(bbox=((-1., 0., -2.), (1., 1., 2.)))))
        for height, missing, dx, expected in ((0.9, False, 0.1, True),
                (0.9, False, -0.1, False), (3., False, 0.1, False),
                (0.9, True, 0.1, False)):
            calls = []

            def collide(space, start, end, mask, *unused):
                calls.append((start, end))
                if missing or not end.y <= height <= start.y:
                    return None
                return Vector(start.x, height, start.z), Vector(0., 1., 0.), 0

            with self.subTest(height=height, missing=missing, dx=dx), mock.patch.dict(
                    sys.modules, {'BigWorld': types.SimpleNamespace(wg_collideSegment=collide)}):
                predicate = world_collision._supported_sweep_departure(
                    1, types.SimpleNamespace(Vector3=Vector), Vector(), 0.,
                    (-1., 1., 2., 2.), 0., 0., td, dx, 0., None, lambda hit: False)
                self.assertEqual(expected, predicate((Vector(0.5, 0.8, 0.), Vector(1., 0., 0.))))
                # A distinct face cannot refresh the shared proof budget.
                for index in range(100):
                    predicate((Vector(0.5, 0.8, index*0.001), Vector(1., 0., 0.)))
            self.assertLessEqual(len(calls), world_collision._SUPPORT_PROOF_QUERY_BUDGET)

    def test_support_filter_covers_the_rear_installed_anchor(self):
        contact = REPORT['contacts']['589']
        scene = captured_scene(contact)
        envelopes = []

        def prepare(start, end):
            envelopes.append((start, end))
            return None

        with mock.patch.object(world_collision, 'prepare_horizontal_collision_filter',
                               side_effect=prepare):
            result = world_collision.check_horizontal_collision(
                scene, types.SimpleNamespace(Vector3=Vector), 1,
                Vector(*contact['position']), contact['yaw'], contact['speed'],
                descriptor(contact), False, contact['dt'], True, commit_enabled=False,
                pitch=contact['pitch'], roll=contact['roll'])
        self.assertEqual('clear', result)
        anchors = world_collision._mounted_hull_floor_points(descriptor(contact),
            Vector(*contact['position']), contact['yaw'], contact['pitch'], contact['roll'])
        self.assertGreater(len(envelopes), 1)
        for start, end in envelopes[1:]:
            for x, unused_y, z in anchors:
                self.assertLessEqual(start.x, x)
                self.assertGreaterEqual(end.x, x)
                self.assertLessEqual(start.z, z)
                self.assertGreaterEqual(end.z, z)


if __name__ == '__main__':
    unittest.main()
