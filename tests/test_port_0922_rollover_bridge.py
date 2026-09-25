"""Scenes from the September 14 follow-up gameplay report."""
import math
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixtures
from gui.mods.offline_lan_0922 import bot_runtime, tank_collision, vehicle_physics
from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime


class RolloverBridgeTests(unittest.TestCase):
    def battle(self):
        runtime = fixtures._runtime()
        battle = BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        battle._local_fall_armed = True
        # These scenes define horizontal terrain layers only; static wall
        # sweeps have their own native-ray/normal fixtures.
        battle._motion_is_clear = lambda *args, **kwargs: True
        entity = fixtures._Vehicle(10, fixtures._suspension_descriptor(),
            fixtures._Vector(), (0, 0, 0), {'health': 500})
        return battle, entity

    @staticmethod
    def floor(x, z, minimum, maximum, **kwargs):
        return 0.0 if minimum <= 0.0 <= maximum else None

    def test_bridge_edge_fall_conserves_mass_centre_through_native_hull_sweeps(self):
        from test_port_0922_world_collision import _Vector, _miss_mat_info_1513
        from gui.mods.offline_lan_0922 import world_collision

        for dt in (1.0 / 30.0, 1.0 / 120.0):
            for side in (-1.0, 1.0):
                with self.subTest(dt=dt, side=side):
                    battle, entity = self.battle()

                    def bridge(x, z, low, high, **kwargs):
                        height = 5.0 if side*x < 0.0 else -20.0
                        return height if low <= height <= high else None

                    def collide(space, start, end, mask, *unused):
                        delta = end - start
                        if abs(delta.y) < 1e-12:
                            return None
                        hits = []
                        for height in (5.0, -20.0):
                            fraction = (height-start.y) / delta.y
                            if not 0.0 <= fraction <= 1.0:
                                continue
                            point = start + delta.scale(fraction)
                            if height == -20.0 or side*point.x < 0.0:
                                hits.append((fraction, point))
                        if not hits:
                            return None
                        unused_fraction, point = min(hits, key=lambda row: row[0])
                        return point, _Vector(0.0, 1.0, 0.0), 0

                    scene = types.SimpleNamespace(wg_collideSegment=collide,
                        wg_getMatInfoNearPoint=_miss_mat_info_1513)

                    def sweep(actor, position, motion_yaw, speed, step, hull_yaw=None):
                        trace = {}
                        status = world_collision.check_horizontal_collision(
                            scene, types.SimpleNamespace(Vector3=_Vector), 1,
                            _Vector(*position), motion_yaw if hull_yaw is None else hull_yaw,
                            speed, actor.typeDescriptor, battle._local_airborne,
                            step, True, commit_enabled=False,
                            motion_yaw=motion_yaw if hull_yaw is not None else None,
                            pitch=battle._local_pitch, roll=battle._local_roll, trace=trace)
                        battle._local_world_collision_trace = trace
                        return status == 'clear'

                    battle._suspension_ground_y = bridge
                    battle._motion_is_clear = sweep
                    position = (side*0.8, 5.0, 0.0)
                    crossed_vertical = False
                    # There is only upward contact on this thin deck; no
                    # horizontal force can move the centre of mass. Exercise
                    # the real adapter/solver/sweep loop, not an always-clear
                    # motion stub. The old loop shifted it by about 0.47 m.
                    for unused in range(int(2.5 / dt)):
                        battle._local_support_motion_pose = position
                        position = battle._update_vertical_motion(entity, position, 0.0, dt)
                        params = battle._local_suspension_params
                        centre = vehicle_physics.suspension_point_offset(
                            dict(x=0.0, y=params['center_of_mass_y'], z=0.0),
                            battle._local_pitch, battle._local_roll)
                        self.assertAlmostEqual(side*0.8, position[0]+centre[0], places=7)
                        self.assertAlmostEqual(0.0, position[2]+centre[2], places=7)
                        crossed_vertical |= abs(battle._local_roll) > math.pi/2.0
                        self.assertFalse(battle._local_support_rise_blocked)
                    self.assertTrue(crossed_vertical)
                    self.assertTrue(battle._local_airborne)
                    self.assertLess(position[1], 0.0)

    def test_side_roof_and_tumbling_landings_keep_the_hull_above_ground(self):
        for dt in (1.0 / 30.0, 1.0 / 120.0):
            for pitch, roll, angular in ((0, math.pi, 0), (0, 1.5, 0),
                                         (0.7, 2.1, 1.5)):
                with self.subTest(dt=dt, pitch=pitch, roll=roll):
                    battle, entity = self.battle()
                    entity.typeDescriptor.hull.turretPositions = (
                        fixtures._Vector(0.0, 1.4, 0.8),)
                    battle._suspension_ground_y = self.floor
                    battle._local_pitch, battle._local_roll = pitch, roll
                    battle._local_airborne = True
                    battle._local_vertical_speed = -6.0
                    battle._local_suspension_roll_velocity = angular
                    position = (0.0, 8.0, 0.0)
                    for unused in range(int(4.0 / dt)):
                        position = battle._update_vertical_motion(entity, position, 0.0, dt)
                        base = battle._local_suspension_params
                        self.assertIsNotNone(base)
                        posed = vehicle_physics.suspension_pose_params(
                            base, battle._local_pitch, battle._local_roll)
                        vertices = [p for p in posed['pseudo_contacts']
                                    if p.get('kind') == 'rigid'] or base['rigid_contacts']
                        lowest = position[1] + min(vehicle_physics.suspension_point_offset(
                            p, battle._local_pitch, battle._local_roll)[1] for p in vertices)
                        self.assertGreaterEqual(lowest, -vehicle_physics.ALLOWED_PENETRATION - 0.015)
                        self.assertFalse(battle._local_support_rise_blocked)
                    self.assertFalse(battle._local_airborne)
                    self.assertGreater(position[1], 0.0)

    def test_overturned_bot_uses_roof_support_without_track_spring_propulsion(self):
        descriptor = fixtures._suspension_descriptor()
        descriptor.hull.turretPositions = (fixtures._Vector(0, 1.4, 0),)
        params = vehicle_physics.derive_suspension_params(descriptor)
        runtime = bot_runtime.BotRuntime(1, suspension_ground_probe=
            lambda x, z, low, high, flat=None: self.floor(x, z, low, high))
        state = dict(id=11, x=0.0, y=8.0, z=0.0, yaw=0.0, speed=0.0,
                     terrain_pitch=0.0, roll=math.pi, vertical_speed=-4.0,
                     airborne=True, grounded_once=True, health=500, max_health=500)
        for unused in range(150):
            blocked = runtime._update_suspension_vertical_motion(state, 1.0 / 30, params)
            self.assertFalse(blocked)
            self.assertGreaterEqual(state['y'], 2.8 - vehicle_physics.ALLOWED_PENETRATION - 0.015)
        self.assertFalse(state['airborne'])
        self.assertAlmostEqual(-1.0, math.cos(state['roll']), places=3)
        self.assertLess(abs(state['vertical_speed']), 0.05)

    def test_track_footprint_stays_on_rail_deck_then_releases_at_bridge_end(self):
        for dt in (1.0 / 30.0, 1.0 / 120.0):
            with self.subTest(dt=dt):
                battle, entity = self.battle()
                def bridge(x, z, minimum, maximum, **kwargs):
                    if z >= 20.0:
                        height = -15.0
                    elif z < 0.0 or abs(abs(x) - 1.35) < 0.075 or z % 0.7 < 0.12:
                        height = 12.0
                    else:
                        height = 11.4  # lower beam visible through sleeper gaps
                    return height if minimum <= height <= maximum else None
                battle._suspension_ground_y = bridge
                position = (0.15, 12.0, -5.0)
                for unused in range(int(11.0 / dt)):
                    battle._local_support_motion_pose = position
                    position = battle._update_vertical_motion(entity,
                        (position[0], position[1], position[2] + 2.0 * dt), 0.0, dt)
                    self.assertGreater(position[1], 11.85)
                    self.assertLess(abs(battle._local_roll), 0.08)
                # The footprint must not keep a vanished bridge alive.
                for unused in range(int(5.0 / dt)):
                    battle._local_support_motion_pose = position
                    position = battle._update_vertical_motion(entity,
                        (position[0], position[1], position[2] + 3.0 * dt), 0.0, dt)
                self.assertLess(position[1], 5.0)

    def test_grounded_hull_contact_blocks_without_player_or_bot_hp_damage(self):
        battle, entity = self.battle()
        trace = dict(hit=(0, 1, 3), normal=(0, 0, -1), reason='upper_lane')
        for speed in (12, 20, 30):
            battle._apply_world_contact_impact(entity, trace, speed, 0.0)
        self.assertEqual([], battle._pending_landing_impacts)
        self.assertEqual(500, entity.health)
        runtime = bot_runtime.BotRuntime(1)
        state = dict(id=11, yaw=0.0, airborne=False, vertical_speed=0.0,
                     health=500, max_health=500, alive=True, _world_contact_trace=trace)
        self.assertEqual(0, runtime._apply_world_contact_impact(state, 30, 10))
        self.assertEqual(500, state['health'])
        self.assertNotIn('_world_contact_trace', state)

    def test_attitude_chart_preserves_full_body_axes_and_world_momentum(self):
        # Both end-over-end directions, a side roll, and several revolutions.
        for pitch, roll in ((3.13, -3.13), (-3.14, 3.12), (0.1, 6.4),
                            (9.31, -2.99), (1.58, 0.7), (-1.58, -0.7)):
            battle, unused_entity = self.battle()
            battle._local_pitch, battle._local_roll = pitch, roll
            battle._local_speed = 12.0
            battle._local_suspension_pitch_velocity = 0.4
            old_axes = tank_collision.pose_axes(0.6, pitch, roll)
            yaw = battle._canonicalize_local_attitude(0.6)
            new_axes = tank_collision.pose_axes(yaw, battle._local_pitch, battle._local_roll)
            for a, b in zip(old_axes, new_axes):
                for x, y in zip(a, b):
                    self.assertAlmostEqual(x, y, places=12)
            self.assertAlmostEqual(12.0 * math.sin(0.6), battle._local_speed * math.sin(yaw))
            self.assertAlmostEqual(12.0 * math.cos(0.6), battle._local_speed * math.cos(yaw))
            old_next = tank_collision.pose_axes(0.6, pitch + 0.004, roll)
            new_next = tank_collision.pose_axes(yaw, battle._local_pitch +
                battle._local_suspension_pitch_velocity * 0.01, battle._local_roll)
            for a, b in zip(old_next, new_next):
                for x, y in zip(a, b):
                    self.assertAlmostEqual(x, y, places=12)

    def test_forward_and_reverse_follow_the_nose_after_tumbling_and_righting(self):
        for dt in (1.0 / 30.0, 1.0 / 120.0):
            for pitch, roll in ((2.5, 2.3), (-2.5, -2.3), (0.0, 5.6)):
                battle, entity = self.battle()
                battle._runtime.bigworld.entities[10] = entity
                battle._server = types.SimpleNamespace(vehicle_id=10)
                battle._sender = types.SimpleNamespace(forward=0.0, turn=0.0, handbrake=False)
                battle._local_descriptor = entity.typeDescriptor
                battle._local_position = (0.0, 8.0, 0.0)
                battle._attach_local_presentation()
                battle._local_fall_armed = True
                battle._local_airborne = True
                battle._local_pitch, battle._local_roll = pitch, roll
                battle._suspension_ground_y = self.floor
                battle._motion_is_clear = lambda *args, **kwargs: True
                battle._resolve_local_tank_contacts = lambda entity, pos, *args: pos
                for unused in range(int(5.0 / dt)):
                    battle._drive_local_step(dt)
                self.assertFalse(battle._local_airborne)
                self.assertGreater(math.cos(battle._local_pitch) * math.cos(battle._local_roll), 0.98)
                for direction in (1.0, -1.0):
                    battle._local_speed = 0.0
                    battle._sender.forward = direction
                    before = battle._local_position
                    for unused in range(int(0.5 / dt)):
                        battle._drive_local_step(dt)
                    forward = tank_collision.pose_axes(battle._local_yaw,
                        battle._local_pitch, battle._local_roll)[2]
                    travel = sum((battle._local_position[i] - before[i]) * forward[i]
                                 for i in (0, 2))
                    self.assertGreater(direction * travel, 0.1)

    def test_righted_native_contact_receipt_passes_the_real_server_validator(self):
        from test_port_0922_server_bot_ai import BattleState, Player
        battle, entity = self.battle()
        battle._local_pitch, battle._local_roll = 3.13, -3.13
        battle._local_yaw = 0.0
        remote = fixtures._Vehicle(11, fixtures._Descriptor(),
            fixtures._Vector(0, 0, -6), (0, 0, 0), {'health': 500})
        battle._ram_bot_revision_at = lambda *args: 1
        battle._native_ram_vehicle_armor = mock.Mock(
            return_value={'armor': 80.0, 'screened': False})
        self.assertTrue(battle._queue_ram_contact_proof(
            dict(network_id=11, presentation_time_us=123000), entity, remote,
            (0.0, 0.0, -3.0), (0.0, 0.0, -10.0), (0.0, 0.0, 0.0), 123000,
            player_ram_profile=dict(spall_coefficient=1.0, ramming_bonus=0.0),
            contact_normal=(0.0, 1.0)))
        state = BattleState()
        state.bot_states[11] = {'id': 11}
        state.bot_state_revision, state.bot_state_time_us = 1, 123000
        state.human_collision_profiles[1] = dict(shape=(1.5, 3.5, -0.8, 2.0),
            ram_profile=dict(spall_coefficient=1.0, ramming_bonus=0.0))
        player = Player(1, object(), ('127.0.0.1', 1), team=1, slot=0)
        normalized, reason = state._validate_ram_contact(player, battle._local_ram_receipt)
        self.assertIsNone(reason)
        self.assertIsNotNone(normalized)
        self.assertLess(abs(normalized['pitch']), 0.02)
        self.assertLess(abs(normalized['roll']), 0.02)

    def test_native_layer_probe_acquires_raised_rail_deck_without_prior_deck_contact(self):
        # A rotated sparse deck 24 cm above its approach, over a lower beam.
        # Exercise wg_collideSegment -> layer rejection -> footprint -> solver.
        for dt in (1.0 / 30.0, 1.0 / 120.0):
            for speed in (2.0, 20.0):
                battle, entity = self.battle()
                # Match the reported tank's 3.29 m chassis width. Its carrier
                # centres lie outside the sleeper ends; the inboard track
                # patch must carry it, not a fictitious rail under each wheel.
                entity.typeDescriptor.chassis.hitTester.bbox = (
                    fixtures._Vector(-1.645, -0.8, -3.5),
                    fixtures._Vector(1.645, 0.8, 3.5))
                yaw = -1.95
                sine, cosine = math.sin(yaw), math.cos(yaw)
                def native(unused_space, start, end, mask, *filters):
                    self.assertEqual(0x10 | 0x40, mask)
                    x, z = cosine * start.x - sine * start.z, sine * start.x + cosine * start.z
                    layers = [(30.0, -1.0)]  # overhead underside is never support
                    if z < 0:
                        layers.append((5.0, 1.0))
                    elif z < 25.0 and abs(x) < 2.0:
                        if (abs(abs(x) - 0.72) < 0.045 or
                                (abs(x) < 1.3 and z % 0.65 < 0.16)):
                            layers.append((5.24, 1.0))
                        layers.append((4.6, 1.0))
                    layers.append((-15.0, 1.0))
                    for height, normal in sorted(layers, reverse=True):
                        if end.y <= height <= start.y:
                            return fixtures._Vector(start.x, height, start.z), fixtures._Vector(0, normal, 0)
                    return None
                battle._runtime.bigworld.wg_collideSegment = native
                along = -5.0
                position = (sine * along, 5.0, cosine * along)
                while along < 21.0:
                    battle._local_support_motion_pose = position
                    if 10.0 < along < 11.0:
                        # Reacquire a carrier using fresh geometry even when
                        # that carrier's own deck memory has been lost.
                        battle._local_spring_ground_memory[0] = None
                    along += speed * dt
                    position = battle._update_vertical_motion(entity,
                        (sine * along, position[1], cosine * along), yaw, dt)
                    self.assertGreater(position[1], 4.88)
                    if 5.0 < along < 20.0:
                        self.assertGreater(position[1], 5.05)
                    self.assertLess(abs(battle._local_roll), 0.12)
                # Track-scale recovery must release at the real end of the bridge.
                for unused in range(int(3.0 / dt)):
                    battle._local_support_motion_pose = position
                    along += 10.0 * dt
                    position = battle._update_vertical_motion(entity,
                        (sine * along, position[1], cosine * along), yaw, dt)
                self.assertLess(position[1], 0.0)


if __name__ == '__main__':
    unittest.main()
