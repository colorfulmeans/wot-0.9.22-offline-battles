"""The shared-entrypoint gate must run ownership and receipt regressions.

The loader seam below isolates the entrypoint's fixed group and exit contract;
it is not a replacement for running its real native-fixture integration groups.
"""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'shared_vehicle_control_checker', ROOT / 'tools/check_shared_vehicle_control.py')
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class SharedVehicleControlCheckerTests(unittest.TestCase):
    def setUp(self):
        original_path = list(sys.path)
        self.addCleanup(sys.path.__setitem__, slice(None), original_path)

    def test_fixed_groups_keep_original_contracts_and_add_both_ownership_boundaries(self):
        self.assertEqual((
            'test_shared_vehicle_control',
            'test_shared_mission_control',
            'test_shared_order_planning',
            'test_shared_route_combat_ownership',
            'test_shared_combat_movement_receipts',
        ), checker.CONTRACT_MODULES)

    @staticmethod
    def run_entrypoint(failed_group=None):
        executed = []

        def load(name):
            def check():
                executed.append(name)
                if name == failed_group:
                    print('fixture diagnostic: ' + name)
                    raise AssertionError('supplied checker failure: ' + name)
            return unittest.TestSuite((unittest.FunctionTestCase(check),))

        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(checker.unittest.defaultTestLoader,
                               'loadTestsFromName', side_effect=load) as loader, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = checker.main(['--check'])
        return status, executed, loader.call_args_list, output.getvalue(), errors.getvalue()

    def test_check_executes_every_fixed_group_once(self):
        status, executed, calls, output, unused_errors = self.run_entrypoint()
        self.assertEqual(0, status)
        self.assertEqual(list(checker.CONTRACT_MODULES), executed)
        self.assertEqual([mock.call(name) for name in checker.CONTRACT_MODULES], calls)
        self.assertEqual('', output)

    def test_either_new_group_failure_is_nonzero_and_keeps_its_diagnostic(self):
        for failed_group in ('test_shared_route_combat_ownership',
                             'test_shared_combat_movement_receipts'):
            with self.subTest(group=failed_group):
                status, executed, unused_calls, output, errors = self.run_entrypoint(failed_group)
                self.assertEqual(1, status)
                self.assertEqual(list(checker.CONTRACT_MODULES), executed)
                self.assertIn('fixture diagnostic: ' + failed_group, output)
                self.assertIn('supplied checker failure: ' + failed_group, errors)
                self.assertIn('FAILED (failures=1)', errors)


if __name__ == '__main__':
    unittest.main()
