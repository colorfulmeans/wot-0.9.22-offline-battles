"""Sparse suspension diagnostics remain independent of input and physics."""
import copy
import io
import json
import unittest
from unittest import mock

import test_port_0922_rollover_bridge as fixtures
from gui.mods.offline_lan_0922 import battle_runtime, vehicle_physics


class LocalSuspensionDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.battle, self.entity = fixtures.RolloverBridgeTests().battle()
        self.battle._local_support_rise_blocked = False
        self.params = vehicle_physics.derive_suspension_params(
            self.entity.typeDescriptor)
        self.before = dict(height=0.0, pitch=0.0, roll=0.0,
                           vertical_velocity=0.0, pitch_velocity=0.0,
                           roll_velocity=0.0)
        self.solved = dict(self.before, origin_shift=(0.0, 0.0),
                           airborne=False, contact_count=10,
                           rigid_contact_count=0, touched_contact_count=10)
        self.ground = (0.0,) * len(self.params['springs'])
        self.pseudo = (None,) * len(self.params['pseudo_contacts'])

    def report(self, ground=None, **kwargs):
        return self.battle._report_local_suspension_motion(
            self.entity, self.params, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
            0.0, 1.0 / 60.0, self.before, self.solved,
            self.ground if ground is None else ground,
            self.pseudo, 0.0, None, **kwargs)

    @staticmethod
    def rows(stream):
        prefix = '[Offline LAN 0.9.22] LOCAL SUSPENSION '
        return [json.loads(line[len(prefix):])
                for line in stream.getvalue().splitlines()
                if line.startswith(prefix)]

    def test_normal_supported_ground_is_silent_without_clock_or_native_queries(self):
        with mock.patch.object(battle_runtime, '_PROFILE_CLOCK') as clock, \
                mock.patch.object(self.battle, '_clock', side_effect=AssertionError), \
                mock.patch.object(self.battle, '_motion_is_clear',
                                  side_effect=AssertionError), \
                mock.patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertFalse(self.report())
            clock.assert_not_called()
            self.assertEqual('', output.getvalue())

    def test_zero_throttle_edge_records_at_most_five_hz_with_recovery_tail(self):
        edge = (None,) + self.ground[1:]
        with mock.patch.object(battle_runtime, '_PROFILE_CLOCK',
                side_effect=(10.0, 10.05, 10.2, 10.4, 10.6, 11.41)), \
                mock.patch.object(self.battle, '_clock', side_effect=AssertionError), \
                mock.patch.object(self.battle, '_motion_is_clear',
                                  side_effect=AssertionError), \
                mock.patch('sys.stdout', new_callable=io.StringIO) as output:
            results = [self.report(edge) for unused in range(4)]
            results.extend((self.report(), self.report()))
        self.assertEqual([True, False, True, True, True, False], results)
        rows = self.rows(output)
        self.assertEqual(4, len(rows))
        self.assertTrue(all(row['drive'] == [0.0, 0.0] for row in rows))
        self.assertTrue(rows[-1]['recovery_tail'])
        self.assertIsNone(self.battle._local_suspension_motion_tail_until)

    def test_blocked_origin_shift_and_rollback_retain_rejected_solver_pose(self):
        self.solved.update(roll=0.2, roll_velocity=1.2,
                           height=2.0, origin_shift=(0.04, 0.02))
        probe = {'shift': (0.04, 0.02), 'clear': False,
                 'reason': 'hull_probe', 'normal': (-1.0, 0.0, 0.0)}
        before = copy.deepcopy(self.battle._local_suspension_state_snapshot())
        with mock.patch.object(battle_runtime, '_PROFILE_CLOCK', return_value=10), \
                mock.patch.object(self.battle, '_clock', side_effect=AssertionError), \
                mock.patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertTrue(self.report(origin_probes=[probe], invalid_pose=True,
                                        raised_support=True))
        row = self.rows(output)[0]
        self.assertEqual([0.04, 0.02], row['origin_shift_requested'])
        self.assertEqual([0.0, 0.0], row['origin_shift_resolved'])
        self.assertEqual('hull_probe', row['origin_probes'][0]['reason'])
        self.assertEqual(2.0, row['solved']['height'])
        self.assertTrue(row['invalid_pose'])
        self.assertTrue(row['raised_support'])
        self.assertEqual(list(self.ground), row['ground'])
        self.assertEqual(before, self.battle._local_suspension_state_snapshot())

    def test_live_bridge_solve_has_identical_physics_and_probe_count_with_logging(self):
        results = []
        for enabled in (True, False):
            battle, entity = fixtures.RolloverBridgeTests().battle()
            battle._local_suspension_params = self.params
            battle._suspension_ground_y = lambda x, z, low, high, **kwargs: (
                5.0 if x < 0.0 and low <= 5.0 <= high else None)
            calls = []

            def sweep(*args, **kwargs):
                calls.append((args[1:], kwargs))
                return True

            battle._motion_is_clear = sweep
            if not enabled:
                battle._report_local_suspension_motion = lambda *args, **kwargs: False
            with mock.patch.object(battle_runtime, '_PROFILE_CLOCK', return_value=10), \
                    mock.patch('sys.stdout', new_callable=io.StringIO) as output:
                position = battle._update_vertical_motion(
                    entity, (0.8, 5.0, 0.0), 0.0, 1.0 / 30.0)
            results.append((position, battle._local_suspension_state_snapshot(), calls))
            if enabled:
                self.assertEqual(1, len(self.rows(output)))
            else:
                self.assertEqual([], self.rows(output))
        self.assertEqual(results[0], results[1])

    def test_broken_output_is_not_a_physics_exception(self):
        with mock.patch.object(battle_runtime, '_PROFILE_CLOCK', return_value=10), \
                mock.patch('sys.stdout.write', side_effect=IOError('closed log')):
            self.assertFalse(self.report((None,) + self.ground[1:]))
        self.assertFalse(self.battle._local_suspension_disabled)


if __name__ == '__main__':
    unittest.main()
