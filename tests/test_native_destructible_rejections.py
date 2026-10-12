"""Prepare rejection observation preserves native ownership and fallback."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest import mock
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import native_input_diagnostics


class PrepareRejectionTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'src/res/scripts/client/gui/mods/offline_lan_0922/native_destructibles.py'
        spec=importlib.util.spec_from_file_location('_prepare_observer_test',path)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.owner=module.Geometry.__new__(module.Geometry)
        self.owner.handle=object()

    def test_rejection_captures_payload_without_retry(self):
        query=mock.Mock(return_value=None)
        self.owner.backend=types.SimpleNamespace(destr_query=query)
        payload=(12.,(),(),(1,2,3,4))
        with mock.patch.object(native_input_diagnostics,'record') as record:
            self.assertIsNone(self.owner.query(8,payload))
        query.assert_called_once_with(self.owner.handle,8,payload)
        record.assert_called_once_with('destr_prepare',(payload,),'unsupported_input',None)

    def test_exception_is_observed_and_preserved(self):
        error=RuntimeError('prepare failed')
        self.owner.backend=types.SimpleNamespace(destr_query=mock.Mock(side_effect=error))
        with mock.patch.object(native_input_diagnostics,'record') as record:
            with self.assertRaises(RuntimeError) as raised:self.owner.query(8,())
        self.assertIs(error,raised.exception)
        record.assert_called_once_with('destr_prepare',((),),'exception',error)

    def test_success_and_other_queries_have_no_observer_work(self):
        self.owner.backend=types.SimpleNamespace(destr_query=mock.Mock(return_value=()))
        with mock.patch.object(native_input_diagnostics,'record') as record:
            self.assertEqual((),self.owner.query(8,()))
            self.owner.backend.destr_query.return_value=None
            self.assertIsNone(self.owner.query(0,()))
        record.assert_not_called()
