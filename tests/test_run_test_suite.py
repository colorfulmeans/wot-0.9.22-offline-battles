"""The isolated runner must expose failures and prevent module fake leakage."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('isolated_test_runner',ROOT/'tools/run_test_suite.py')
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class IsolatedRunnerTests(unittest.TestCase):
    def run_files(self, files):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);tests=root/'tests';tests.mkdir()
            for name, source in files.items():
                (tests/name).write_text(source,encoding='utf-8')
            output=io.StringIO()
            with mock.patch.object(runner,'ROOT',root), mock.patch('sys.argv',[
                    'runner','--jobs','2','--logs',str(root/'logs')]), \
                    contextlib.redirect_stdout(output):
                failed=runner.main()
            logs={path.name:path.read_text(encoding='utf-8') for path in (root/'logs').glob('*.log')}
            return failed,output.getvalue(),logs

    def test_an_assertion_failure_keeps_a_nonzero_result_and_full_log(self):
        failed,output,logs=self.run_files({'test_bad.py':
            "import unittest\nclass Checks(unittest.TestCase):\n def test_bad(self): self.assertEqual(1,2,'visible failure')\n"})
        self.assertTrue(failed)
        self.assertIn('FAIL test_bad.py',output)
        self.assertIn('visible failure',logs['test_bad.log'])

    def test_import_errors_are_not_converted_to_success(self):
        failed,output,logs=self.run_files({'test_bad.py':"raise RuntimeError('fixture import failed')\n"})
        self.assertTrue(failed)
        self.assertIn('fixture import failed',logs['test_bad.log'])

    def test_module_fakes_do_not_escape_into_the_next_test_file(self):
        failed,output,logs=self.run_files({
            'test_first.py':"import sys,types,unittest\nsys.modules['native_fixture_leak']=types.ModuleType('native_fixture_leak')\nclass Checks(unittest.TestCase):\n def test_first(self): self.assertIn('native_fixture_leak',sys.modules)\n",
            'test_second.py':"import sys,unittest\nclass Checks(unittest.TestCase):\n def test_second(self): self.assertNotIn('native_fixture_leak',sys.modules)\n"})
        self.assertFalse(failed)
        self.assertEqual(2,len(logs))
        self.assertIn('2 passed, 0 failed',output)
