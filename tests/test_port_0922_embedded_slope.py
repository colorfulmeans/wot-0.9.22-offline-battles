"""Bounded recovery of the T-54 support rollback reported in build 104."""
import math
import unittest
from unittest import mock
import test_port_0922_bot_runtime as harness

class EmbeddedSlopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.module = self.fixture.module
        self.calls = []
        self.runtime = self.module.BotRuntime(1, physics_ground_probe=self.ground)
        self.runtime._suspension_params[22] = None
        self.runtime._detail_tier = lambda state: 2
        self.runtime._turret_motion_probe = mock.Mock(return_value=True)
        self.state = dict(id=22, x=0., y=39.78218460083008, z=0.,
            yaw=0., pitch=.070411488, terrain_pitch=.070411488, roll=.124305645,
            speed=0., half_length=2.952724, half_width=1.622931,
            airborne=False, grounded_once=True, last_drive_pitch=math.atan(.33),
            vertical_speed=0., movement_dir=1, rotation_dir=0)
    def tearDown(self):self.fixture.tearDown()
    def ground(self, x, z, hint):
        self.calls.append((x, z))
        return 40.62900161743164 - .33 * z + .12 * x
    def tick(self, step=.1):
        return self.runtime._update_vertical_motion(self.state, step,
            (self.state['x'], self.state['y'], self.state['z']), self.state['yaw'])
    def test_reported_burial_settles_after_bounded_proof_without_launch_velocity(self):
        for unused in range(9):self.assertTrue(self.tick())
        self.assertFalse(self.tick(.11))
        self.assertAlmostEqual(40.62900161743164, self.state['y'])
        self.assertEqual(0., self.state['vertical_speed'])
        self.assertFalse(self.state['airborne'])
        self.assertEqual(14, len(self.calls))
        count = len(self.calls)
        self.assertTrue(self.runtime._update_slope_pose(self.state))
        self.assertEqual(count, len(self.calls))
        self.assertFalse(self.tick())
    def test_cached_attitude_converges_without_more_ground_columns(self):
        self.state['y'] = 40.62900161743164
        self.assertTrue(self.runtime._update_slope_pose(self.state))
        first = self.state['pitch']
        for unused in range(10):self.runtime._update_slope_pose(self.state)
        self.assertGreater(self.state['pitch'], first)
        self.assertAlmostEqual(math.atan(.33) * .9, self.state['terrain_pitch'], delta=.001)
        self.assertEqual(4, len(self.calls))
    def test_native_pose_denial_cannot_commit_height_repair(self):
        self.runtime._turret_motion_probe.return_value = False
        before = self.state['y']
        self.state['_support_repair_elapsed'] = 1.
        self.assertTrue(self.tick())
        self.assertEqual(before, self.state['y'])
        self.assertEqual(0., self.state['vertical_speed'])
        self.assertNotIn('_slope_pose_target', self.state)
        self.assertNotIn('pose_sample', self.state)

    def test_cached_convergence_does_not_move_ground_sampling_anchor(self):
        self.state['y'] = 40.62900161743164
        self.assertTrue(self.runtime._update_slope_pose(self.state))
        anchor = self.state['pose_sample']
        self.state['x'] = 2.
        self.assertTrue(self.runtime._update_slope_pose(self.state))
        self.assertEqual(anchor, self.state['pose_sample'])
        self.state['x'] = 5.
        self.assertTrue(self.runtime._update_slope_pose(self.state))
        self.assertEqual(8, len(self.calls))
    def test_step_deck_cliff_and_missing_support_still_reject(self):
        for kind in ('step', 'deck', 'cliff', 'missing'):
            with self.subTest(kind=kind):
                self.calls = []
                def probe(x, z, hint):
                    self.calls.append((x, z))
                    if kind == 'step':return 40.629 if z >= 0 else 39.782
                    if kind == 'deck':return 40.629
                    if kind == 'cliff':return 40.629 - z
                    return None if z != 0 else 40.629
                self.runtime._physics_ground_probe = probe
                self.runtime._support_repair_budget = 1
                self.state['_support_repair_elapsed'] = 1.
                self.assertTrue(self.tick())
                self.assertAlmostEqual(39.78218460083008, self.state['y'])
                self.assertLessEqual(len(self.calls), 5)
    def test_failure_cooldown_and_shared_budget_bound_extra_work(self):
        self.runtime._physics_ground_probe = lambda x,z,hint: self.calls.append((x,z)) or 40.629
        self.state['_support_repair_elapsed'] = 1.
        self.assertTrue(self.tick())
        self.assertEqual(5, len(self.calls))
        for unused in range(5):
            self.runtime._support_repair_budget = 1
            self.assertTrue(self.tick())
        self.assertEqual(10, len(self.calls))
        self.state['_support_repair_elapsed'] = 1.
        self.runtime._support_repair_budget = 0
        self.assertTrue(self.tick())
        self.assertEqual(11, len(self.calls))
    def test_ordinary_ground_settle_keeps_one_column(self):
        self.state['y'] = 40.62900161743164
        self.assertFalse(self.tick())
        self.assertEqual(1, len(self.calls))

    def test_rejected_full_roster_pose_samples_still_respect_frame_budget(self):
        calls = []
        runtime = self.module.BotRuntime(1,
            descriptor_resolver=lambda unused: harness._combat_descriptor(),
            adapter_factory=lambda *args, **kwargs: harness._FixedAdapter(
                self.fixture._stationary_command()),
            direction_probe=lambda *args: {'clear': True, 'slope': 0.},
            ground_probe=lambda *args: 0.,
            physics_ground_probe=lambda *args: calls.append(args) or 0.,
            spawn_resolver=harness._spawn_resolver, baked_graph=harness._graph())
        roster = [dict(id=11+i, team=1 if i<15 else 2,
            slot=i if i<15 else i-15, name='Budget-%d'%i) for i in range(29)]
        runtime.battle_start(dict(self.fixture.start, bots=roster))
        for state in runtime.states.values():
            state.update(y=0., grounded_once=True)
            state.pop('pose_sample', None)
            runtime._suspension_params[state['id']] = None
        runtime._turret_motion_probe = mock.Mock(return_value=False)
        calls[:] = []
        runtime.update(.04, 1.)
        self.assertEqual(29 + 4 * self.module.MAX_SLOPE_POSE_SAMPLES_PER_FRAME, len(calls))
        self.assertEqual(self.module.MAX_SLOPE_POSE_SAMPLES_PER_FRAME,
            sum(state.get('_slope_pose_attempt', 0) for state in runtime.states.values()))
        self.assertFalse(any('_slope_pose_target' in state for state in runtime.states.values()))
if __name__ == '__main__':unittest.main()
