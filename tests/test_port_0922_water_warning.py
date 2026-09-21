"""Water effects cannot supply the server's pre-drowning warning plane."""
import math
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixture


class WaterWarningTests(unittest.TestCase):
    def setUp(self):
        self.battle = fixture.BattleRuntime(fixture._runtime())
        self.entity = fixture._Vehicle(
            10, fixture._Descriptor(), fixture._Vector(), (0, 0, 0),
            {'health': 500})

    def test_splashes_are_not_a_caution_warning(self):
        self.entity.appearance.waterSensor = object()
        self.entity.appearance.isInWater = True
        self.entity.appearance.isUnderwater = False
        self.assertEqual(0, self.battle._native_drowning_level(self.entity))
        self.entity.appearance.isUnderwater = True
        self.assertEqual(2, self.battle._native_drowning_level(self.entity))

    def test_fallback_does_not_read_track_footprint_as_sensor_height(self):
        descriptor = self.entity.typeDescriptor
        descriptor.chassis = types.SimpleNamespace(
            hullPosition=(0.0, 0.6, 0.0),
            topRightCarryingPoint=(1.5, 4.0))
        descriptor.hull = types.SimpleNamespace(
            turretPositions=((0.0, 0.4, 0.0),))
        self.battle._water_depth = mock.Mock(return_value=0.01)
        self.assertEqual(2, self.battle._fallback_drowning_level(
            self.entity, (10.0, 20.0, 30.0), 0.0, 0.0, 0.0))
        self.battle._water_depth.assert_called_once_with((10.0, 21.0, 30.0))

    def test_fallback_probes_transformed_point_including_pitch_roll_and_yaw(self):
        descriptor = self.entity.typeDescriptor
        descriptor.chassis = types.SimpleNamespace(hullPosition=(1.0, 0.6, 0.0))
        descriptor.hull = types.SimpleNamespace(turretPositions=((0.0, 0.4, 2.0),))
        self.battle._water_depth = mock.Mock(return_value=-0.01)
        self.assertEqual(0, self.battle._fallback_drowning_level(
            self.entity, (10.0, 20.0, 30.0),
            math.pi / 2, math.pi / 2, math.pi / 2))
        point = self.battle._water_depth.call_args[0][0]
        for actual, expected in zip(point, (11.0, 18.0, 31.0)):
            self.assertAlmostEqual(expected, actual)

    def test_missing_geometry_does_not_create_a_default_drowning_plane(self):
        self.entity.typeDescriptor.hull = types.SimpleNamespace()
        self.battle._water_depth = mock.Mock()
        self.assertIsNone(self.battle._fallback_drowning_level(
            self.entity, (0.0, 0.0, 0.0), 0.0, 0.0, 0.0))
        self.battle._water_depth.assert_not_called()

    def test_worker_fallback_uses_replicated_pose_instead_of_spawn_pose(self):
        runtime = self.battle._runtime
        runtime.bigworld.entities[10] = self.entity
        sender = mock.Mock(return_value=True)
        self.battle.client = types.SimpleNamespace(
            is_bot_authority=lambda: True, send_player_environment=sender)
        self.battle._worker_mode = True
        self.battle._records = {'player:1': {
            'engine_id': 10, 'network_id': 1, 'kind': 'player', 'local': False,
            'state': {'health': 500, 'alive': True, 'input_seq': 12,
                      'x': 10.0, 'y': 20.0, 'z': 30.0,
                      'yaw': 0.0, 'pitch': math.pi / 2, 'roll': 0.0}}}
        self.battle._water_depth = mock.Mock(return_value=-0.1)
        self.assertTrue(self.battle._publish_player_environment(0.3, 1.0))
        point = self.battle._water_depth.call_args[0][0]
        for actual, expected in zip(point, (10.0, 20.0, 30.6)):
            self.assertAlmostEqual(expected, actual)
        sender.assert_called_once_with([
            {'player_id': 1, 'input_seq': 12, 'level': 0}], 1)


if __name__ == '__main__':
    unittest.main()
