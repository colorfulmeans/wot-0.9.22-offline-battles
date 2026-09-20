"""Replay the support faces that stalled both clients in the 07:58 report."""
import json
from pathlib import Path
import struct
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as local
from test_port_0922_world_collision import _miss_mat_info_1513
from gui.mods.offline_lan_0922 import (
    collision_geometry as geometry, physics_diagnostics, world_collision)


REPORT = json.loads((Path(__file__).parent / 'fixtures' /
                     'rotation_20260920_freeze.json').read_text())


def f32(value):
    return struct.unpack('f', struct.pack('f', value))[0]


class RotationSupportRegressionTests(unittest.TestCase):
    def replay(self, row, with_wall=False):
        motion = row['motion']
        runtime = local._runtime()
        battle = local.BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        battle._destructibles = types.SimpleNamespace(
            _vehicle_body_bbox=lambda descriptor: motion['bbox'])
        point, normal = row['candidates'][0]
        planes = [(point, normal)]
        if with_wall:
            # Place a vertical wall outside the starting body, but
            # inside its real end pose. Ground must not mask this wall.
            entering = []
            for axis in ((1., 0., 0.), (-1., 0., 0.),
                         (0., 0., 1.), (0., 0., -1.)):
                before = geometry.projection_range(dict(motion, yaw_delta=0.), axis)[0]
                after = geometry.projection_range(dict(motion,
                    yaw=motion['yaw']+motion['yaw_delta'], yaw_delta=0.), axis)[0]
                entering.append((before-after, axis, (before+after)*.5))
            change, axis, plane = max(entering)
            self.assertGreater(change, 0.)
            # An axis-aligned native face has float32 vertex coordinates.
            planes.append((tuple(f32(plane*v) for v in axis), axis))
        queries = []

        def native(space, start, end, mask, keep=None):
            # Native points are float32. The intersection plane and
            # body pose are copied from the player's actual report.
            queries.append(1)
            self.assertLess(len(queries), 500,
                            'support face caused repeated yaw refinement')
            start = [f32(getattr(start, c)) for c in 'xyz']
            end = [f32(getattr(end, c)) for c in 'xyz']
            delta = [end[i] - start[i] for i in range(3)]
            hits = []
            for point, normal in planes:
                denominator = sum(delta[i] * normal[i] for i in range(3))
                if abs(denominator) < 1e-15:
                    continue
                fraction = sum((point[i] - start[i]) * normal[i]
                               for i in range(3)) / denominator
                if 0. <= fraction <= 1.:
                    hit = local._Vector(*(f32(start[i] + delta[i] * fraction)
                                          for i in range(3)))
                    hits.append((fraction, hit, local._Vector(*normal)))
            if hits:
                return min(hits, key=lambda hit: hit[0])[1:]

        runtime.bigworld.wg_collideSegment = native
        runtime.bigworld.wg_getMatInfoNearPoint = _miss_mat_info_1513
        with mock.patch.object(physics_diagnostics, 'emit') as emit:
            clear = battle._native_world_rotation_is_clear(
                motion['start'], motion['yaw'],
                motion['yaw'] + motion['yaw_delta'], local._Descriptor(),
                pitch=motion['pitch'], roll=motion['roll'])
        self.assertTrue(queries)
        return clear, emit.call_args_list, len(queries)

    def test_reported_support_planes_complete_without_subdivision(self):
        for row in REPORT['contacts']:
            with self.subTest(role=row['role']):
                clear, events, count = self.replay(row)
                self.assertTrue(clear)
                self.assertFalse(any(c.args[0] == 'rotation_envelope_refine'
                                     for c in events))

    def test_support_does_not_hide_a_wall_entered_by_the_turn(self):
        for row in REPORT['contacts']:
            with self.subTest(role=row['role']):
                clear, events, count = self.replay(row, with_wall=True)
                self.assertFalse(clear)

    def test_grazing_recast_crosses_face_and_keeps_adjacent_wall(self):
        first, second = f32(100.00001), f32(100.00002)
        starts = []

        def native(space, start, end, mask):
            starts.append(f32(start.z))
            self.assertLess(len(starts), 5, 'same native plane was queried again')
            start_z, end_z = f32(start.z), f32(end.z)
            for z in (first, second):
                if start_z <= z <= end_z:
                    fraction = (z-start_z)/(end_z-start_z)
                    return (local._Vector(f32(start.x+(end.x-start.x)*fraction),
                                          1., z), local._Vector(0., 0., -1.))

        with mock.patch.dict('sys.modules', {'BigWorld': types.SimpleNamespace(
                wg_collideSegment=native)}), \
                mock.patch.object(physics_diagnostics, 'emit'):
            result = world_collision._collide_horizontal(
                1, local._Vector(100., 1., 100.),
                local._Vector(103., 1., 100.0001), None,
                lambda hit: hit[0].z == first)
        self.assertEqual(second, result[0].z)
        self.assertEqual(2, len(starts))
        self.assertGreater(starts[1], first)
        self.assertLess(starts[1], second)
