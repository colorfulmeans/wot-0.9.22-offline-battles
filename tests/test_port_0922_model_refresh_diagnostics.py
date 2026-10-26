"""Unknown async model ownership failures gain bounded opt-in context only."""
import types
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import compat, native_input_diagnostics as logs


class ModelRefreshDiagnosticsTests(unittest.TestCase):
    def test_failed_diagnostic_preserves_original_native_exception(self):
        for error in (AssertionError('native assertion'),RuntimeError('native failure')):
            owner=types.SimpleNamespace(_battle_active=True,
                _original_compound_models_refresh=mock.Mock(side_effect=error))
            with mock.patch.object(logs,'detailed_enabled',return_value=True), \
                    mock.patch.object(logs,'write_json_record',side_effect=OSError('closed log')):
                with self.assertRaises(type(error)) as caught:
                    compat._run_model_refresh_callback(owner,types.SimpleNamespace(),'destroyed',[])
            self.assertIs(error,caught.exception)

    def test_callback_history_observes_destroyed_then_exploded_without_hiding_assertion(self):
        damage=types.SimpleNamespace(modelState='normal')
        appearance=types.SimpleNamespace(_CompoundAppearance__vehicle=types.SimpleNamespace(id=23),
            _CompoundAppearance__currentDamageState=damage)
        error=AssertionError('native state changed')
        def refresh(unused, state, resources):
            if state=='destroyed' and damage.modelState=='exploded':raise error
            damage.modelState=state
            return 'native-result'
        owner=types.SimpleNamespace(_battle_active=True,_original_compound_models_refresh=refresh)
        with mock.patch.object(logs,'detailed_enabled',return_value=True), \
                mock.patch.object(logs,'write_json_record') as writer:
            self.assertEqual('native-result',compat._run_model_refresh_callback(owner,appearance,'destroyed',[]))
            compat._run_model_refresh_callback(owner,appearance,'exploded',[])
            with self.assertRaises(AssertionError) as caught:
                compat._run_model_refresh_callback(owner,appearance,'destroyed',['resource'])
        self.assertIs(error,caught.exception)
        row=writer.call_args.args[1]
        history=row['callback_history']
        self.assertEqual(['destroyed','exploded','destroyed'],[r['callback_state'] for r in history])
        self.assertEqual(['returned','returned','assertion'],[r['result'] for r in history])
        self.assertEqual('exploded',history[-1]['before_state'])
        self.assertTrue(row['assertion_frames'])
        self.assertEqual('exploded',damage.modelState)

    def test_history_is_bounded_and_disabled_entry_never_retains_appearance(self):
        owner=types.SimpleNamespace(_original_compound_models_refresh=lambda *a:42)
        appearance=types.SimpleNamespace()
        with mock.patch.object(logs,'detailed_enabled',return_value=False):
            self.assertEqual(42,compat._run_model_refresh_callback(owner,appearance,'normal',[]))
        self.assertFalse(hasattr(owner,'_model_refresh_callbacks'))
        with mock.patch.object(logs,'detailed_enabled',return_value=True):
            for unused in range(40):compat._run_model_refresh_callback(owner,appearance,'normal',[])
        self.assertEqual(16,len(owner._model_refresh_callbacks))
        self.assertEqual(40,owner._model_refresh_callbacks[-1]['sequence'])
        self.assertTrue(all(isinstance(row['appearance_identity'],int) for row in owner._model_refresh_callbacks))
        self.assertEqual({},vars(appearance))

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

