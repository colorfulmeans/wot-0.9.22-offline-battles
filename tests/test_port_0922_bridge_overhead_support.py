"""Real bridge-side contact windows and high-speed corner landing coverage."""
import contextlib
import io
import json
import math
from pathlib import Path
import unittest

import test_port_0922_battle_runtime as fixtures
import test_port_0922_bridge_drive_122119 as bridge
from gui.mods.offline_lan_0922 import bot_runtime, vehicle_physics


REPORT = json.loads((Path(__file__).parent / 'fixtures' /
    'sacred_valley_20260925_r4_overhead_support.json').read_text())


def captured_params(frame):
    # Unrecorded spring coefficients retain the established KV-5 fixture.
    # Every contact position, COM and sampled height below is from this log.
    params = vehicle_physics.derive_suspension_params(bridge.descriptor())
    params['center_of_mass_y'] = frame['center_of_mass_y']
    params['springs'] = tuple(dict(spring, x=row[1], y=row[2], z=row[3])
        for spring, row in zip(params['springs'], frame['spring_layout']))
    params['pseudo_contacts'] = tuple(dict(kind=row[0], x=row[1], y=row[2],
        z=row[3], side=('left' if row[1] < 0.0 else 'right')
        if row[0] == 'track' else None,
        penetration=vehicle_physics.ALLOWED_PENETRATION)
        for row in frame['pseudo_layout'])
    pitch, roll = frame['before_pose'][4:]
    params['contact_sweep_pose'] = (
        pitch + frame['before_velocity'][1] * frame['dt'],
        roll + frame['before_velocity'][2] * frame['dt'])
    return params


class BridgeOverheadSupportTests(unittest.TestCase):
    def test_recorded_player_and_bot_corners_cannot_acquire_overhead_deck(self):
        for frame in REPORT['frames']:
            with self.subTest(line=frame['log_line']):
                params = captured_params(frame)
                x, y, z, yaw, pitch, roll = frame['before_pose']
                points = vehicle_physics.suspension_pseudo_world_points(
                    params, (x, y, z), yaw, pitch, roll)

                def column(px, pz, low, high, *unused, **kwargs):
                    # Replay only the exact witnessed columns. There is no
                    # invented surface between them and no forced collision.
                    for point, height in zip(points, frame['pseudo_ground']):
                        if abs(point[0]-px) + abs(point[1]-pz) < 1.e-8:
                            return height if (height is not None and
                                low <= height <= high) else None
                    return None

                runtime = fixtures._runtime()
                battle = fixtures.BattleRuntime(runtime)
                battle._avatar = runtime.bigworld.avatar
                battle._local_suspension_params = params
                battle._local_pitch, battle._local_roll = pitch, roll
                battle._suspension_ground_y = column
                sweep = vehicle_physics.suspension_vertical_sweep_drop(
                    frame['before_velocity'][0], frame['dt'])
                player_samples = battle._local_suspension_pseudo_ground_samples(
                    (x, y, z), yaw, sweep_drop=sweep, params=params)
                bot = bot_runtime.BotRuntime(1, suspension_ground_probe=column)
                state = dict(id=11, x=x, y=y, z=z, yaw=yaw,
                    terrain_pitch=pitch, roll=roll)
                bot_samples = bot._suspension_pseudo_ground_samples(
                    state, params, sweep_drop=sweep)
                self.assertEqual(player_samples, bot_samples)
                for index in frame['invalid_rigid_contacts']:
                    self.assertIsNone(player_samples[index])
                # The recorded old solve injected 1.10 m / 0.66 m of COM
                # height in 9 ms / 11 ms. Keep genuinely reachable contacts,
                # then prove the same solver no longer makes that jump.
                self.assertTrue(any(value is not None for value in player_samples))
                state = dict(height=y, pitch=pitch, roll=roll,
                    vertical_velocity=frame['before_velocity'][0],
                    pitch_velocity=frame['before_velocity'][1],
                    roll_velocity=frame['before_velocity'][2])
                solved = vehicle_physics.damper_suspension_step(
                    params, state, frame['ground'], frame['dt'], player_samples,
                    frame['support_vertical_speed'])
                center = dict(x=0., y=params['center_of_mass_y'], z=0.)
                after_com = solved['height'] + vehicle_physics.suspension_point_offset(
                    center, solved['pitch'], solved['roll'])[1]
                self.assertLess(after_com-frame['before_center'][1], 0.1)

    def test_high_speed_roof_landing_sweeps_below_the_actual_corner(self):
        for dt in (1. / 120., 1. / 30., 0.1):
            with self.subTest(dt=dt), contextlib.redirect_stdout(io.StringIO()):
                runtime = fixtures._runtime()
                battle = fixtures.BattleRuntime(runtime)
                battle._avatar = runtime.bigworld.avatar
                descriptor = fixtures._suspension_descriptor()
                descriptor.hull.turretPositions = (fixtures._Vector(0., 1.4, 0.8),)
                entity = fixtures._Vehicle(10, descriptor, fixtures._Vector(),
                    (0., 0., math.pi), {'health': 500})
                battle._local_fall_armed = True
                battle._local_airborne = True
                battle._local_roll = math.pi
                battle._local_vertical_speed = -45.
                battle._motion_is_clear = lambda *args, **kwargs: True
                battle._suspension_ground_y = lambda x, z, low, high, **kwargs: (
                    0. if low <= 0. <= high else None)
                position = (0., 12., 0.)
                for unused in range(int(1.0 / dt)):
                    position = battle._update_vertical_motion(entity, position, 0., dt)
                    posed = vehicle_physics.suspension_pose_params(
                        battle._local_suspension_params,
                        battle._local_pitch, battle._local_roll)
                    lowest = min(position[1] + vehicle_physics.suspension_point_offset(
                        point, battle._local_pitch, battle._local_roll)[1]
                        for point in posed['pseudo_contacts'])
                    self.assertGreaterEqual(lowest, -vehicle_physics.ALLOWED_PENETRATION-1.e-6)
                self.assertFalse(battle._local_airborne)
                self.assertTrue(battle._pending_landing_impacts)

    def test_multiple_corner_frames_pass_below_finite_bridge_without_acquiring_top(self):
        frame = REPORT['frames'][0]
        params = captured_params(frame)
        runtime = fixtures._runtime()
        battle = fixtures.BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        battle._local_suspension_params = params
        x, y, z, yaw, pitch, roll = frame['before_pose']
        battle._local_pitch, battle._local_roll = pitch, roll
        target = vehicle_physics.suspension_pseudo_world_points(
            params, (x, y, z), yaw, pitch, roll)[22]
        top = frame['pseudo_ground'][22]
        calls = []

        def column(px, pz, low, high, **kwargs):
            return top if abs(pz-target[1]) < 0.1 and low <= top <= high else None

        def collide(space, start, end, mask, *unused):
            calls.append((tuple(start), tuple(end)))
            delta = end-start
            if abs(delta.y) < 1.e-12:
                return None
            fraction = (top-start.y)/delta.y
            if not 0. <= fraction <= 1.:
                return None
            point = start + delta.scale(fraction)
            if abs(point.z-target[1]) >= 0.1:
                return None
            return point, fixtures._Vector(0., 1., 0.), 0

        runtime.bigworld.wg_collideSegment = collide
        battle._suspension_ground_y = column
        for dz in (-0.3, -0.15, 0., 0.15):
            samples = battle._local_suspension_pseudo_ground_samples(
                (x, y, z+dz), yaw, params=params)
            self.assertIsNone(samples[22])
        self.assertGreater(len(calls), 0)
        # The old point retained for the next sweep is the corner at -0.213 m,
        # not the model origin at +3.463 m or the bridge top at +1.109 m.
        self.assertLess(battle._local_pseudo_ground_memory[22][1], 0.)

    def test_crossed_finite_face_does_not_extend_support_beyond_its_edge(self):
        top = 1.
        calls = []

        def collide(start, end):
            fraction = (top-start[1])/(end[1]-start[1])
            point = tuple(start[i]+fraction*(end[i]-start[i]) for i in range(3))
            return (point, (0., 1., 0.)) if 0. <= fraction <= 1. and 0. <= point[2] <= 2. else None

        def column(x, z, low, high):
            calls.append(z)
            return top if 0. <= z <= 2. and low <= top <= high else None

        support = vehicle_physics.swept_rigid_support(
            (0., 2., -1.), (0., 0., 3.), None, collide, column)
        self.assertIsNone(support)
        self.assertEqual([3.], calls)


if __name__ == '__main__':
    unittest.main()
