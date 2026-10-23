"""Unknown async model ownership failures gain bounded opt-in context only."""
import types
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import compat, native_input_diagnostics as logs


class ModelRefreshDiagnosticsTests(unittest.TestCase):
    def test_basic_entry_does_not_log_or_change_appearance(self):
        owner=types.SimpleNamespace(_battle_active=True)
        appearance=types.SimpleNamespace()
        with mock.patch.object(logs,'detailed_enabled',return_value=False), \
             mock.patch.object(logs,'write_json_record') as writer:
            compat._report_model_refresh_failure(owner,appearance,1,[])
        writer.assert_not_called();self.assertEqual({},vars(appearance))
        self.assertFalse(hasattr(owner,'_model_refresh_failure_reports'))

    def test_diagnostic_captures_stale_state_and_stops_at_eight_reports(self):
        owner=types.SimpleNamespace(_battle_active=True)
        appearance=types.SimpleNamespace(_CompoundAppearance__vehicle=types.SimpleNamespace(
            id=1000,typeDescriptor=types.SimpleNamespace(name='uk:GB31_Conqueror_Gun')),
            _CompoundAppearance__currentDamageState=types.SimpleNamespace(modelState=2),
            damageState=types.SimpleNamespace(isCurrentModelDamaged=True))
        with mock.patch.object(logs,'detailed_enabled',return_value=True), \
             mock.patch.object(logs,'write_json_record') as writer:
            for unused in range(20):compat._report_model_refresh_failure(owner,appearance,1,['resource'])
        self.assertEqual(8,writer.call_count)
        data=writer.call_args.args[1]
        self.assertEqual(('1','2',1000),(data['callback_state'],data['current_state'],data['vehicle']))

