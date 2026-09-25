"""A moving overturned roof must keep its real sloping-ground contact."""
import contextlib
import io
import math
import types
import unittest

import test_port_0922_battle_runtime as fixtures
import test_port_0922_world_collision as collision_fixtures
from gui.mods.offline_lan_0922 import vehicle_physics, world_collision
from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime


class RoofSlopeSweepTests(unittest.TestCase):
    def test_overturned_inertia_uses_corner_sweep_on_slope(self):
        for dt in (0.1, 1.0 / 30.0, 1.0 / 120.0):
            with self.subTest(dt=dt), contextlib.redirect_stdout(io.StringIO()):
                runtime = fixtures._runtime()
                battle = BattleRuntime(runtime)
                battle._avatar = runtime.bigworld.avatar
                descriptor = fixtures._suspension_descriptor()
                descriptor.hull.turretPositions = (fixtures._Vector(0, 1.4, 0.8),)
                entity = fixtures._Vehicle(10, descriptor,
                    fixtures._Vector(0, 12, 0), (0, 0, math.pi), {'health': 500})
                runtime.bigworld.entities[10] = entity
                battle._server = types.SimpleNamespace(vehicle_id=10)
                battle._sender = types.SimpleNamespace(
                    forward=0.0, turn=0.0, handbrake=False)
                battle._local_descriptor = descriptor
                battle._local_position = (0.0, 12.0, 0.0)
                battle._attach_local_presentation()
                battle._local_fall_armed = True
                battle._local_airborne = True
                battle._local_roll = math.pi
                battle._local_vertical_speed = -12.0
                battle._local_speed = 4.0
                battle._overturn_level = 2

                def collide(space, start, end, mask, *unused):
                    delta = end - start
                    denominator = delta.y - 0.3 * delta.z
                    if abs(denominator) < 1.0e-12:
                        return None
                    fraction = (0.3 * start.z - start.y) / denominator
                    if not 0.0 <= fraction <= 1.0:
                        return None
                    normal_length = math.sqrt(1.09)
                    return (start + delta.scale(fraction),
                        fixtures._Vector(0, 1.0 / normal_length,
                            -0.3 / normal_length), 0)

                runtime.bigworld.wg_collideSegment = collide
                scene = types.SimpleNamespace(wg_collideSegment=collide,
                    wg_getMatInfoNearPoint=collision_fixtures._miss_mat_info_1513)
                vector = collision_fixtures._Vector

                def sweep(actor, position, motion_yaw, speed, step,
                          hull_yaw=None, **kwargs):
                    trace = {}
                    status = world_collision.check_horizontal_collision(
                        scene, types.SimpleNamespace(Vector3=vector), 1,
                        vector(*position),
                        motion_yaw if hull_yaw is None else hull_yaw,
                        speed, descriptor, battle._local_airborne, step, True,
                        commit_enabled=False,
                        motion_yaw=motion_yaw if hull_yaw is not None else None,
                        pitch=battle._local_pitch, roll=battle._local_roll,
                        trace=trace)
                    battle._local_world_collision_trace = trace
                    return status == 'clear'

                battle._motion_is_clear = sweep
                battle._suspension_ground_y = lambda x, z, low, high, **kwargs: (
                    0.3 * z if low <= 0.3 * z <= high else None)
                battle._resolve_local_tank_contacts = lambda actor, pos, *args: pos
                worst_gap = 0.0
                for unused in range(int(3.0 / dt)):
                    battle._drive_local_step(dt)
                    position = battle._local_position
                    self.assertIsNotNone(battle._local_suspension_params)
                    posed = vehicle_physics.suspension_pose_params(
                        battle._local_suspension_params,
                        battle._local_pitch, battle._local_roll)
                    for point in posed['pseudo_contacts']:
                        offset = vehicle_physics.suspension_point_offset(
                            point, battle._local_pitch, battle._local_roll)
                        gap = position[1] + offset[1] - 0.3 * (position[2] + offset[2])
                        worst_gap = min(worst_gap, gap)
                # Preserve the existing coarse-step landing tolerance. Merely
                # deleting the broad ceiling, without actual corner sweeps,
                # increases penetration to 0.85 m / 0.32 m at 10 / 30 Hz.
                self.assertGreaterEqual(worst_gap, -0.24)
                self.assertFalse(battle._local_airborne)
                self.assertLess(abs(battle._local_speed), 0.01)
                self.assertGreater(battle._local_position[2], 2.0)


if __name__ == '__main__':
    unittest.main()
