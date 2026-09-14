"""Scenes from the September 14 follow-up gameplay report."""
import math
import unittest

import test_port_0922_battle_runtime as fixtures
from gui.mods.offline_lan_0922 import bot_runtime, vehicle_physics
from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime


class RolloverBridgeTests(unittest.TestCase):
    def battle(self):
        runtime = fixtures._runtime()
        battle = BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        battle._local_fall_armed = True
        entity = fixtures._Vehicle(10, fixtures._suspension_descriptor(),
            fixtures._Vector(), (0, 0, 0), {'health': 500})
        return battle, entity

    @staticmethod
    def floor(x, z, minimum, maximum, **kwargs):
        return 0.0 if minimum <= 0.0 <= maximum else None

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
        self.assertAlmostEqual(math.pi, state['roll'], places=3)
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


if __name__ == '__main__':
    unittest.main()
