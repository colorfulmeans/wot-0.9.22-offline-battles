"""Unknown async model ownership failures gain bounded opt-in context only."""
import types
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import compat, native_input_diagnostics as logs


class ModelRefreshDiagnosticsTests(unittest.TestCase):
    def test_captured_explosion_supersedes_only_current_dead_destroyed_completion(self):
        for completion_order in (('destroyed', 'exploded'), ('exploded', 'destroyed')):
            with self.subTest(order=completion_order):
                damage=types.SimpleNamespace(modelState='exploded')
                vehicle=types.SimpleNamespace(id=23,health=0)
                appearance=types.SimpleNamespace(_CompoundAppearance__vehicle=vehicle,
                    _CompoundAppearance__currentDamageState=damage)
                vehicle.appearance=appearance
                installed=[]
                def refresh(subject,state,resources):
                    self.assertEqual(damage.modelState,state)
                    installed.append((state,resources))
                    return 'stock-result'
                owner=types.SimpleNamespace(_battle_active=True,
                    _runtime=types.SimpleNamespace(bigworld=types.SimpleNamespace(entity=lambda identity:vehicle)),
                    _original_compound_models_refresh=refresh)
                with mock.patch.object(logs,'detailed_enabled',return_value=True):
                    for state in completion_order:
                        result=compat._run_model_refresh_callback(owner,appearance,state,state+'-resource')
                        self.assertEqual('stock-result' if state=='exploded' else None,result)
                self.assertEqual([('exploded','exploded-resource')],installed)
                self.assertEqual('exploded',damage.modelState)
                self.assertEqual({'returned','superseded'},
                    {r['result'] for r in owner._model_refresh_callbacks})

    def test_unknown_or_rebound_lifecycles_keep_stock_failure(self):
        for mode in ('alive','rebound_appearance','reused_id','not_battle','unknown_state'):
            with self.subTest(mode=mode):
                vehicle=types.SimpleNamespace(id=23,health=0)
                damage=types.SimpleNamespace(modelState='exploded')
                appearance=types.SimpleNamespace(_CompoundAppearance__vehicle=vehicle,
                    _CompoundAppearance__currentDamageState=damage)
                vehicle.appearance=appearance
                current=vehicle
                if mode=='alive':vehicle.health=1
                if mode=='rebound_appearance':vehicle.appearance=object()
                if mode=='reused_id':current=object()
                if mode=='unknown_state':damage.modelState='unknown'
                error=AssertionError('unreviewed lifecycle')
                original=mock.Mock(side_effect=error)
                owner=types.SimpleNamespace(_battle_active=mode!='not_battle',
                    _runtime=types.SimpleNamespace(bigworld=types.SimpleNamespace(entity=lambda identity:current)),
                    _original_compound_models_refresh=original)
                with mock.patch.object(logs,'detailed_enabled',return_value=False):
                    with self.assertRaises(AssertionError) as caught:
                        compat._run_model_refresh_callback(owner,appearance,'destroyed',['resource'])
                self.assertIs(error,caught.exception)
                original.assert_called_once()

    def test_instance_history_survives_unrelated_global_callback_traffic(self):
        owner=types.SimpleNamespace(_battle_active=True,
            _original_compound_models_refresh=lambda *a:42)
        def appearance(vehicle):
            return types.SimpleNamespace(_CompoundAppearance__vehicle=types.SimpleNamespace(id=vehicle),
                _CompoundAppearance__currentDamageState=types.SimpleNamespace(modelState='normal'))
        subject=appearance(23)
        with mock.patch.object(logs,'detailed_enabled',return_value=True):
            compat._observe_model_lifecycle(owner,subject,'state_observed','destroyed','requestModels')
            for i in range(40):
                compat._run_model_refresh_callback(owner,appearance(100+i),'destroyed',[])
            subject._CompoundAppearance__currentDamageState.modelState='exploded'
            owner._original_compound_models_refresh=mock.Mock(side_effect=AssertionError())
            with mock.patch.object(logs,'write_json_record') as writer:
                with self.assertRaises(AssertionError):
                    compat._run_model_refresh_callback(owner,subject,'destroyed',[])
        history=writer.call_args.args[1]['appearance_history']
        self.assertEqual('destroyed',history[0]['state'])
        self.assertEqual('requestModels',history[0]['caller'])
        self.assertEqual('callback_assertion',history[-1]['phase'])
        self.assertTrue(all(row['vehicle']==23 for row in history))
        self.assertLessEqual(len(owner._model_lifecycle_histories),64)

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

