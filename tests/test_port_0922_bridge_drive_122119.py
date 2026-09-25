"""Coupled drive/suspension replay from the September 25 12:21 report.

The pose, mass, hull envelope and bridge heights are measured witnesses. The
remaining descriptor values retain the existing engine-free fixture: this is
a geometry regression, not a recreation of the entire native KV-5 descriptor.
"""
import contextlib
import io
import json
import math
from pathlib import Path
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixtures
import test_port_0922_world_collision as collision_fixtures
from gui.mods.offline_lan_0922 import vehicle_physics, world_collision


EDGE_NORMAL = (0.5518978238105774, 0.8339117169380188)
EDGE_POINT = (-1.8749666213989258, 116.09586334228516)
TOP = 1.109309196472168
DECK = 0.8602447509765625
COM_HEIGHT = 1.0300680994987488
REPORT = json.loads((Path(__file__).parent / 'fixtures' /
    'sacred_valley_20260925_r3_departure.json').read_text())


def outside(x, z):
    return ((x - EDGE_POINT[0]) * EDGE_NORMAL[0] +
            (z - EDGE_POINT[1]) * EDGE_NORMAL[1])


def descriptor():
    value = fixtures._suspension_descriptor()
    value.physics['weight'] = 100575.
    value.physics['enginePower'] = 1200. * 735.49875
    value.physics['speedLimits'] = (11.1112, 3.05558)
    # The #1513 client has no cell-only detailed xphysics refinements. Use
    # the production spring layout and inertia law, not fake authored wheels.
    value.type.xphysics = {}
    # X/Z use the recorded installed envelope. Chassis Y bounds were not in
    # this capture; retain the existing fixture height and derived inertia.
    value.chassis.hitTester = fixtures._HitTester1513(
        fixtures._Vector(-1.8318450450897217, -.8, -4.095921993255615),
        fixtures._Vector(1.831845998764038, .8, 4.0078959465026855))
    value.hull.hitTester = fixtures._HitTester1513(
        fixtures._Vector(-1.4948019981384277, -.6029239892959595, -4.095921993255615),
        fixtures._Vector(1.4948019981384277, .9544249773025513, 3.960186004638672))
    # The report's low-specific-power COM shift and hull bounds recover this
    # mount exactly; the independent AODECAL diagnostic rounds it to 1.09.
    value.chassis.hullPosition = fixtures._Vector(*REPORT['hull_position'])
    return value


def finite_bridge(mirror=1.):
    """Finite-height raised outer strip, its side, lower deck and a floor.

    The report samples the outer strip and lower deck, not the entire map.
    The inboard extent and lower floor close this local reconstruction only.
    All world and suspension queries use this same mesh-like intersection.
    """
    Vector = collision_fixtures._Vector
    n = Vector(EDGE_NORMAL[0], 0., EDGE_NORMAL[1])
    def collide(space, start, end, mask, *unused):
        start = Vector(mirror * start.x, start.y, start.z)
        end = Vector(mirror * end.x, end.y, end.z)
        delta = end - start
        hits = []
        if abs(delta.y) > 1.e-12:
            for height, low, high in ((TOP, -1.3, 0.), (DECK, -8., -1.3),
                                       (-20., -1000., 1000.)):
                t = (height - start.y) / delta.y
                if 0. <= t <= 1.:
                    hit = start + delta.scale(t)
                    if low <= outside(hit.x, hit.z) <= high:
                        hits.append((t, hit, Vector(0., 1., 0.)))
        normal_travel = delta.x * n.x + delta.z * n.z
        if abs(normal_travel) > 1.e-12:
            for boundary, low, high, sign in ((0., .5, TOP, 1.),
                                             (-1.3, DECK, TOP, -1.)):
                t = (boundary - outside(start.x, start.z)) / normal_travel
                if 0. <= t <= 1.:
                    hit = start + delta.scale(t)
                    if low <= hit.y <= high:
                        hits.append((t, hit, n.scale(sign)))
        if not hits:
            return None
        unused_t, hit, normal = min(hits, key=lambda row: row[0])
        return (Vector(mirror * hit.x, hit.y, hit.z),
                Vector(mirror * normal.x, normal.y, normal.z), 0)
    return types.SimpleNamespace(wg_collideSegment=collide,
        wg_getMatInfoNearPoint=collision_fixtures._miss_mat_info_1513)


def build_battle(scene, mirror=1., witness='914', speed=None):
    pose = REPORT['contacts'][witness]
    runtime = fixtures._runtime()
    battle = fixtures.BattleRuntime(runtime)
    battle._avatar = runtime.bigworld.avatar
    position = pose['position']
    position = (mirror * position[0], position[1], position[2])
    entity = fixtures._Vehicle(10, descriptor(), fixtures._Vector(),
                               (mirror * pose['yaw'], pose['pitch'],
                                mirror * pose['roll']), {'health': 500})
    runtime.bigworld.entities[10] = entity
    runtime.bigworld.wg_collideSegment = scene.wg_collideSegment
    runtime.bigworld.wg_getMatInfoNearPoint = scene.wg_getMatInfoNearPoint
    battle._server = types.SimpleNamespace(vehicle_id=10)
    battle._sender = types.SimpleNamespace(forward=1., turn=0., handbrake=False)
    battle._local_descriptor = entity.typeDescriptor
    battle._local_position = position
    battle._local_yaw = mirror * pose['yaw']
    battle._local_physics = vehicle_physics.derive_params(entity.typeDescriptor)
    battle._local_suspension_params = vehicle_physics.derive_suspension_params(
        entity.typeDescriptor)
    battle._local_pitch, battle._local_roll = pose['pitch'], mirror * pose['roll']
    battle._local_speed = pose['speed'] if speed is None else speed
    battle._local_fall_armed = True
    # Presentation and absent actors have no part in the physics assertion.
    battle._update_local_presentation = lambda entity, dt: battle._vector(
        battle._local_position)
    battle._resolve_local_tank_contacts = lambda entity, pos, yaw, dt: pos
    battle._report_local_motion_stall = lambda *args, **kwargs: None
    return battle, entity


def center_of_mass(battle):
    offset = vehicle_physics.suspension_point_offset(
        dict(x=0., y=COM_HEIGHT, z=0.), battle._local_pitch, battle._local_roll)
    sine, cosine = math.sin(battle._local_yaw), math.cos(battle._local_yaw)
    pos = battle._local_position
    return (pos[0] + cosine * offset[0] + sine * offset[2],
            pos[1] + offset[1],
            pos[2] - sine * offset[0] + cosine * offset[2])


class BridgeDriveDepartureTests(unittest.TestCase):
    def test_powered_hull_leaves_captured_inboard_pose_before_gravity_fall(self):
        for dt in (1. / 30., 1. / 120.):
            for mirror in (1., -1.):
                for witness, speed in (('589', 0.), ('914', None)):
                    with self.subTest(dt=dt, mirror=mirror, witness=witness), \
                            contextlib.redirect_stdout(io.StringIO()):
                        scene = finite_bridge(mirror)
                        battle, unused_entity = build_battle(scene, mirror, witness, speed)
                        self.assertAlmostEqual(COM_HEIGHT,
                            battle._local_suspension_params['center_of_mass_y'])
                        initial = center_of_mass(battle)
                        self.assertLess(outside(mirror * initial[0], initial[2]), -.5)
                        crossed = False
                        with mock.patch.dict('sys.modules', {'BigWorld': scene}):
                            for unused in range(int(8. / dt)):
                                battle._drive_local_step(dt)
                                center = center_of_mass(battle)
                                crossed = crossed or outside(mirror * center[0], center[2]) > 0.
                                if battle._local_position[1] < -5.:
                                    break
                        self.assertTrue(crossed, (dt, battle._local_position,
                                                 battle._local_pitch, battle._local_roll))
                        self.assertLess(battle._local_position[1], -5.)


if __name__ == '__main__':
    unittest.main()
