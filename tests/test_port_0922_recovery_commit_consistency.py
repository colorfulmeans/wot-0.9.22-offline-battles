"""Recorded Somua minimum-reach refusal must terminate its retained action."""
import contextlib
import io
import json
import math
from pathlib import Path
import types
import unittest
from unittest import mock

import test_port_0922_bot_runtime as harness


class RecoveryCommitTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.module = self.fixture.module

    def tearDown(self):
        self.fixture.tearDown()

    def test_reported_grid_admits_nine_centimetres_but_rejects_commit(self):
        from gui.mods.offline_lan_0922 import prebaked_navigation as pn
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
        graph = pn.with_shore_hazards(json.loads((Path(__file__).resolve().parents[1]/
            'navgraphs/84_winter.json').read_bytes()))
        grid = TerrainGrid(lambda *a: None, baked_graph=graph)
        a = (127.14598450379229, -8.950383186340332, -279.887358742396)
        yaw = 1.4434796963235266
        for distance, blocked in ((.09599760657735601, False), (.5, True)):
            b = (a[0]+math.sin(yaw)*distance, a[1], a[2]+math.cos(yaw)*distance)
            self.assertEqual(blocked, grid.segment_has_motion_hazard(a, b, 13))

    def test_retained_forward_escape_probes_the_same_minimum_as_execution(self):
        from gui.mods.offline_lan_0922.ai.driver import LocalDriver
        driver = LocalDriver()
        for blocked in (False, True):
            state = driver._state(11, 0, (0., 0., 0.))
            state['translation_escape'] = dict(start=(0., 0., 0.),
                distance=1., yaw=0., until=state['clock']+20.)
            checked = []
            def clear(yaw, distance):
                checked.append(distance)
                return not blocked or distance < .5
            result = driver._retained_translation_escape(state, (0., 0., .904),
                0., (), clear, 3.5, 1.7)
            self.assertEqual([.5], checked)
            if blocked:
                self.assertIsNone(result)
                self.assertNotIn('translation_escape', state)
            else:
                self.assertEqual('forward_escape', result['recovery_mode'])

    def test_expired_escape_does_not_renew_or_recast(self):
        from gui.mods.offline_lan_0922.ai.driver import LocalDriver
        driver = LocalDriver(); state = driver._state(11, 0, (0., 0., 0.))
        state['translation_escape'] = dict(start=(0., 0., 0.), distance=1., yaw=0., until=0.)
        clear = mock.Mock(side_effect=AssertionError('expired lease recast'))
        self.assertIsNone(driver._retained_translation_escape(state,
            (0., 0., .904), 0., (), clear, 3.5, 1.7))
        self.assertNotIn('translation_escape', state)

    def _refused_runtime(self, turn=0.):
        runtime = self.fixture._ford_runtime(self.fixture._ford_graph(size=9))
        command = self.fixture._stationary_command()
        command.update(throttle=1., turn=turn, brake=False, movement_intent=True,
            target_yaw=1. if turn else 0., recovery_probe_distance=.096,
            recovery_mode='forward_escape')
        runtime.adapter.decide = lambda *a: dict(command)
        from gui.mods.offline_lan_0922.ai.driver import LocalDriver
        runtime.adapter.driver = LocalDriver()
        runtime.adapter.driver._state(11, 0, (16., 0., 16.))
        state = runtime.states[11]
        state.update(x=16., y=0., z=16., yaw=0., speed=0., grounded_once=True)
        return runtime, state

    def test_aligned_committed_refusal_retires_and_feeds_finite_retry(self):
        runtime, state = self._refused_runtime()
        from gui.mods.offline_lan_0922 import native_input_diagnostics
        memory = runtime.adapter.driver.states[11]
        memory['translation_escape'] = dict(start=(16.,0.,16.),
            yaw=0., distance=4., until=20.)
        with contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(runtime.navigator.grid, 'segment_has_motion_hazard', return_value=True), \
                    mock.patch.object(native_input_diagnostics, 'write_json_record') as write:
                runtime.update(.1, 1.1)
        self.assertEqual(16., state['z'])
        self.assertNotIn(11, runtime._decision_cache)
        self.assertNotIn(11, runtime._motion_probe_cache)
        self.assertTrue(state['_committed_corridor']['retry_feedback'])
        driver = runtime.adapter.driver
        memory = driver.states[11]
        receipt = memory['failure_receipts'][-1]
        self.assertEqual('motion_forecast', receipt['source'])
        self.assertEqual(.5, receipt['distance'])
        self.assertGreater(driver._failure_penalty(memory, 0.), 0.)
        self.assertIsNone(driver._retained_translation_escape(memory,
            (16.,0.,16.), 0., (), lambda *a: True, 3.5, 1.7))
        self.assertNotIn('translation_escape', memory)
        terminal = [call.args[1] for call in write.call_args_list if call.args[0]=='BOT RECOVERY COMMIT']
        self.assertTrue(terminal)
        self.assertEqual('rejected_action_retired', terminal[-1]['outcome'])
        self.assertEqual(11, terminal[-1]['bot'])
        self.assertIn('queries', terminal[-1]['planning'])
        memory['clock'] = receipt['expires_at']+.01
        self.assertEqual(0., driver._failure_penalty(memory, 0.))

    def test_unaligned_command_keeps_its_catchup_turn(self):
        runtime, state = self._refused_runtime(turn=1.)
        with contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(runtime.navigator.grid, 'segment_has_motion_hazard', return_value=True):
                runtime.update(.1, 1.1)
        self.assertIn(11, runtime._decision_cache)
        self.assertFalse(state['_committed_corridor'].get('cache_retired', False))
        self.assertFalse(runtime.adapter.driver.states[11].get('failure_receipts'))

    def test_five_point_batch_reuses_rotation_without_changing_offsets(self):
        physics = self.module.vehicle_physics
        points = [dict(x=x, y=0., z=z) for x, z in ((0,0),(0,3.5),(0,-3.5),(1.7,0),(-1.7,0))]
        for pitch in (-.7, 0., .7):
            for roll in (-.5, 0., .5):
                expected = tuple(physics.suspension_point_offset(p, pitch, roll) for p in points)
                with mock.patch.object(physics, '_suspension_rotation', wraps=physics._suspension_rotation) as prepare:
                    actual = physics.suspension_point_offsets(points, pitch, roll)
                self.assertEqual(expected, actual)
                self.assertEqual(1, prepare.call_count)

    def test_missing_support_preserves_layer_reason_without_extra_cast(self):
        runtime, state = self._refused_runtime()
        calls = []
        def column(x, z, hint, limit):
            calls.append((x,z,hint,limit))
            return dict(height=None, layers=[dict(outcome='ray_miss')])
        runtime._physics_ground_limit_probe = column
        state.pop('_support_mode_sample', None)
        rows = runtime._basic_support_status(state)
        self.assertEqual(5, len(calls))
        self.assertEqual(5, len(rows))
        self.assertTrue(all(not row['valid'] for row in rows))
        self.assertTrue(all(row['column_evidence']['layers'][0]['outcome']=='ray_miss' for row in rows))

    def test_geometry_reads_mutated_mount_instead_of_reusing_a_shape(self):
        from gui.mods.offline_lan_0922 import world_collision as world
        box = ((-2., -.5, -4.), (2., 1., 4.))
        hull = ((-1., 0., -3.), (1., 2., 3.))
        mount = [0., 1., 0.]
        descriptor = types.SimpleNamespace(chassis=types.SimpleNamespace(
            hitTester=types.SimpleNamespace(bbox=box), hullPosition=mount))
        with mock.patch.object(world, '_vehicle_hull_bbox', return_value=hull):
            self.assertEqual(((-2.,2.,4.,4.),(-.5,3.)),world._vehicle_motion_geometry(descriptor))
            mount[1] = 2.
            self.assertEqual(((-2.,2.,4.,4.),(-.5,4.)),world._vehicle_motion_geometry(descriptor))


if __name__ == '__main__':
    unittest.main()
