"""Real catalog commit and tilted Bot presentation regressions; no native claim."""
import math
import contextlib
import io
import json
import os
import types
import unittest
from unittest import mock

import test_port_0922_bot_destructible_approach as catalog
import test_port_0922_battle_runtime as battle
from gui.mods.offline_lan_0922 import bot_state_codec, snapshot_sync


class PassiveCatalogCommitTests(unittest.TestCase):
    setUp = catalog.BotDestructibleApproachTests.setUp
    scene = catalog.BotDestructibleApproachTests.scene

    def test_passive_realised_contact_uses_physical_speed_without_drive_cap(self):
        for speed, expected in ((.16, 'hard'), (20., 'crushed')):
            with self.subTest(speed=speed), self.scene(house_z=3.2, registered=True) as f:
                state = dict(id=16, alive=False, yaw=0., movement_dir=0,
                             pitch=0., roll=0.)
                f.battle._bots = types.SimpleNamespace(states={16: state}, _turn_speeds={})
                f.battle._turret_motion_is_clear = lambda *args: True
                f.battle._tree_motion_proposal = lambda *args: dict(status='clear')
                f.battle._complete_bot_tree_contact = lambda *args: args[-1]
                with mock.patch.object(battle.battle_runtime_module.world_collision,
                        'check_horizontal_collision', return_value='clear'), \
                        mock.patch.object(f.battle, '_destructible_drive_speed_cap',
                            side_effect=AssertionError('dead engine cannot supply a cap')):
                    result = f.battle._resolve_bot_motion(16, (0.,0.,0.), 0., speed,
                        f.descriptor, .04, 10., True, motion_yaw=0.)
                self.assertEqual(expected, result)
                self.assertEqual(int(speed == 20.), f.authority.destroy_module.call_count)
                f.authority.destroy_module.reset_mock()


class TiltedBotAimTests(unittest.TestCase):
    def test_wreck_playback_interpolates_relative_traverse_across_wrap(self):
        sync = snapshot_sync.SnapshotSync(1, clock=lambda: 0.)
        state = dict(self.state(), name='Bot', vehicle='france:F16_AMX_13_75',
                     team=2, slot=0, max_health=1000, turret_yaw=3.1)
        sync.snapshot(dict(server_tick=1, bots=[state]))
        sync.snapshot(dict(server_tick=2, bots=[dict(state, turret_yaw=-3.1)]))
        sync.advance(.1)
        pose = sync._entities['bot:28']['current']
        self.assertGreater(abs(pose['turret_yaw']), 3.1)
        self.assertLess(abs(pose['turret_yaw']), 3.19)

    def test_diagnostic_reads_actual_matrix_providers_with_round_identity(self):
        runtime = battle.BattleRuntime(battle._runtime())
        runtime.client = types.SimpleNamespace(round_id=7)
        state = self.state()
        runtime._runtime.math.Matrix = lambda value: value
        runtime._remote_factory = types.SimpleNamespace(get=lambda unused:
            types.SimpleNamespace(appearance=types.SimpleNamespace(
                turretMatrix=types.SimpleNamespace(yaw=state['turret_yaw']),
                gunMatrix=types.SimpleNamespace(pitch=state['gun_pitch']))))
        output = io.StringIO()
        with mock.patch.dict(os.environ, {'WOT_OFFLINE_DIAGNOSTICS':'1'}), \
                contextlib.redirect_stdout(output):
            runtime._observe_wreck_aim(dict(engine_id=128, network_id=28,
                projectile_collision_pose=state), 10.)
        row = json.loads(output.getvalue().split('BATTLE REVIEW ', 1)[1])
        self.assertEqual(7, row['round'])
        self.assertIsNone(row['native_aim_error'])
        self.assertEqual(0., row['yaw_error'])
        self.assertEqual(0., row['pitch_error'])

    def state(self):
        return dict(id=28, alive=False, health=0, x=85.3, y=.8077, z=93.377,
            yaw=-.7503210507923185, pitch=.3006862100070991,
            roll=.1801381710585897, aim_yaw=-2.94068,
            turret_yaw=-2.158571441394977, gun_pitch=.0111392140839639,
            reload_time=0., reload_duration=1.)

    def test_authority_presentation_and_projectile_share_relative_traverse(self):
        runtime = battle.BattleRuntime(battle._runtime())
        runtime._binding = mock.Mock()
        runtime._worker_mode = True
        record = dict(engine_id=128, kind='bot', network_id=28, ready=True)
        runtime._records = {'bot:28': record}
        state = self.state()
        self.assertTrue(runtime._apply_authority_bot_poses([state]))
        args = runtime._binding.update_vehicle_aim.call_args.args
        self.assertAlmostEqual(state['turret_yaw'], args[2]-args[1])
        self.assertAlmostEqual(args[2]-args[1], record['projectile_collision_pose']['turret_yaw'])
        # A change in world projection alone does not rotate a fixed corpse.
        runtime._binding.update_vehicle_aim.reset_mock()
        runtime._apply_authority_bot_poses([dict(state, aim_yaw=-2.9)])
        runtime._binding.update_vehicle_aim.assert_not_called()

    def test_wire_server_and_guest_keep_relative_traverse(self):
        from lan_battle_server import BattleState
        state = self.state()
        # Exercise the actual positional wire, not a dictionary-only fixture.
        decoded = bot_state_codec.decode_row(bot_state_codec.encode_row(state), {})
        self.assertAlmostEqual(state['turret_yaw'], decoded['turret_yaw'], places=5)
        identity = dict(id=28, team=2, slot=0, name='AMX 13 75', max_health=1000)
        admitted = BattleState._sanitize_bot_state(decoded, identity, None)
        pose = snapshot_sync._pose(admitted)
        runtime = battle.BattleRuntime(battle._runtime())
        runtime._binding = mock.Mock()
        runtime._worker_mode = True
        record = dict(engine_id=128, state=dict(alive=False, health=0))
        runtime._apply_record_pose(record, pose)
        args = runtime._binding.update_vehicle_aim.call_args.args
        self.assertAlmostEqual(admitted['turret_yaw'], args[2]-args[1])
        self.assertAlmostEqual(args[2]-args[1], record['projectile_collision_pose']['turret_yaw'])


if __name__ == '__main__':
    unittest.main()
