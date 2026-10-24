"""Planning rotations retain allied safety and fresh sequential poses."""
import copy
import unittest
from unittest import mock
import test_port_0922_bot_runtime as harness


class PlanningRotationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.runtime = self.fixture.runtime
        self.runtime.states = {
            1: dict(id=1, team=1, x=0., y=0., z=0., yaw=0.,
                    collision_shape=(1.5, 3.5, -.8, 2.)),
            2: dict(id=2, team=1, x=5., y=0., z=0., yaw=0.,
                    collision_shape=(1.5, 3.5, -.8, 2.)),
            3: dict(id=3, team=2, x=4., y=0., z=0., yaw=0.,
                    collision_shape=(1.5, 3.5, -.8, 2.)),
            4: dict(id=4, team=2, alive=False, x=4., y=0., z=0., yaw=0.,
                    collision_shape=(1.5, 3.5, -.8, 2.))}
        self.source = self.runtime.states[1]
        self.supplied = [dict(id=1000001, team=1, position=(3., 0., 0.), yaw=0.,
                             shape=(1.5, 3.5, -.8, 2.)),
                         dict(id=1000002, team=2, position=(3., 0., 0.), yaw=0.,
                             shape=(1.5, 3.5, -.8, 2.))]

    def tearDown(self):
        self.fixture.tearDown()

    def test_native_roster_keeps_allies_wreck_policy_and_live_state_identity(self):
        from gui.mods.offline_lan_0922 import native_math as module
        backend = mock.Mock(rotation_current=mock.Mock())
        before = copy.deepcopy((self.runtime.states, self.supplied))
        with mock.patch.object(module, '_load', return_value=backend), mock.patch.object(
                module, 'call', return_value=.75) as call:
            for push, expected in ((False, [2, 4]), (True, [2])):
                value = self.runtime._planning_rotation_fraction_for(
                    self.source, (0., 0., 0.), 0., .4, self.supplied, push)
                self.assertEqual(.75, value)
                args = call.call_args[0]
                self.assertEqual([1000001], [peer['id'] for peer in args[5]])
                self.assertEqual(expected, [key for key, raw in args[6]])
                self.assertIs(self.runtime.states[2], args[6][0][1])
            self.runtime.states[2]['x'] = 9.
            self.runtime._planning_rotation_fraction_for(self.source, (0., 0., 0.),
                                                        0., .4, self.supplied)
            self.assertEqual(9., call.call_args[0][6][0][1]['x'])
        self.runtime.states[2]['x'] = 5.
        self.assertEqual(before, (self.runtime.states, self.supplied))

    def test_reference_and_native_refusal_keep_exact_original_projection(self):
        from gui.mods.offline_lan_0922 import native_math as module
        for native_refusal in (False, True):
            with self.subTest(native_refusal=native_refusal):
                backend = mock.Mock(rotation_current=mock.Mock()) if native_refusal else None
                with mock.patch.object(module, '_load', return_value=backend), mock.patch.object(
                        module, 'call', return_value=None):
                    for push in (False, True):
                        peers = [p for p in self.runtime._neighbours_for(self.source, self.supplied)
                                 if (not p.get('alive', True) and not push) or
                                 (p.get('alive', True) and p.get('team') == 1)]
                        expected = self.fixture.module.tank_collision.rotation_fraction(
                            (0., 0., 0.), 0., .4, self.source['collision_shape'], peers)
                        actual = self.runtime._planning_rotation_fraction_for(
                            self.source, (0., 0., 0.), 0., .4, self.supplied, push)
                        self.assertEqual(expected, actual)

    def test_missing_shape_retains_original_half_dimensions(self):
        self.runtime.states[2].update(collision_shape=None, half_width=3., half_length=6.)
        from gui.mods.offline_lan_0922 import native_math as module
        with mock.patch.object(module, '_load', return_value=mock.Mock()), mock.patch.object(
                module, 'call', return_value=None) as call:
            self.runtime._planning_rotation_fraction_for(
                self.source, (0., 0., 0.), 0., .4, self.supplied)
            self.assertNotIn('rotation_current', [args[0][0] for args in call.call_args_list])

    def test_decision_roster_reuse_keeps_live_poses_and_distinct_push_policy(self):
        from gui.mods.offline_lan_0922 import native_math as module
        cache = {}
        backend = mock.Mock(rotation_current=mock.Mock())
        with mock.patch.object(module, '_load', return_value=backend), mock.patch.object(
                module, 'call', return_value=.75) as call:
            self.runtime._planning_rotation_fraction_for(
                self.source, (0., 0., 0.), 0., .4, self.supplied, False, cache)
            first = call.call_args[0][6]
            self.runtime.states[2]['x'] = 9.
            self.runtime._planning_rotation_fraction_for(
                self.source, (0., 0., 0.), 0., .8, self.supplied, False, cache)
            self.assertIs(first, call.call_args[0][6])
            self.assertEqual(.8, call.call_args[0][3])
            self.assertEqual(9., call.call_args[0][6][0][1]['x'])
            self.runtime._planning_rotation_fraction_for(
                self.source, (0., 0., 0.), 0., .8, self.supplied, True, cache)
            self.assertEqual([2], [key for key, raw in call.call_args[0][6]])
            self.assertEqual(2, len(cache))
            # New decisions rebuild membership, including death/team changes.
            self.runtime.states[3]['team'] = 1
            self.runtime._planning_rotation_fraction_for(
                self.source, (0., 0., 0.), 0., .8, self.supplied, False, {})
            self.assertEqual([2, 3, 4], [key for key, raw in call.call_args[0][6]])
            self.assertEqual(4, call.call_count)
