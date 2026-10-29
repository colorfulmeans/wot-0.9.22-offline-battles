"""Verification survives busy histories without changing model lifecycle calls."""
import ast
import io
import os
from pathlib import Path
import sys
import types
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import native_input_diagnostics as logs


class ReviewEvidenceTests(unittest.TestCase):
    def test_diagnostic_server_persistence_keeps_early_evidence_over_basic_ceiling(self):
        tree = ast.parse((ROOT / 'launcher/wot_launcher.py').read_text(encoding='utf8'))
        selected = {'_open_server_log', '_BoundedLogStream', '_TeeTextStream'}
        constants = {'SERVER_LOG_MAX_BYTES', 'SERVER_LOG_RETAIN_BYTES',
            'DIAGNOSTIC_SERVER_LOG_MAX_BYTES', 'DIAGNOSTIC_SERVER_LOG_RETAIN_BYTES'}
        nodes = [node for node in tree.body if
            isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in selected or
            isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants
                                                for t in node.targets)]
        ns = dict(os=os, sys=types.SimpleNamespace(stdout=None, stderr=None), threading=threading)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<server log>', 'exec'), ns)
        with tempfile.TemporaryDirectory() as directory:
            for mode in ('0', '1'):
                ns['sys'].stdout = ns['sys'].stderr = None
                target = os.path.join(directory, mode + '.log')
                with mock.patch.dict(os.environ, {'WOT_OFFLINE_DIAGNOSTICS': mode}):
                    self.assertEqual(target, ns['_open_server_log'](target))
                tee = ns['sys'].stdout
                tee.write('EARLY VERIFICATION\n')
                for unused in range(300):
                    tee.write('later evidence ' + 'x' * 4096 + '\n')
                tee.flush()
                tee._log_stream.close()
                payload = Path(target).read_bytes()
                self.assertEqual(mode == '1', b'EARLY VERIFICATION' in payload)
                if mode == '0':
                    self.assertLessEqual(len(payload), ns['SERVER_LOG_MAX_BYTES'])

    def test_bulk_exhaustion_does_not_drop_continuous_verification(self):
        owner = types.SimpleNamespace(round_id=1)
        output = io.StringIO()
        with mock.patch.dict(logs.os.environ, {logs.DETAIL_ENV: '1'}), \
                mock.patch.object(logs, '_detail_budget', dict(start=0, window=0,
                    session=logs.DETAIL_SESSION_BYTES, session_closed=True, dropped=0, notice=True)), \
                mock.patch.object(logs.sys, 'stdout', output):
            for tick in range(200):
                logs.battle_review_record(owner, 'worker_human_observation', 1,
                    tick * .5, lambda: dict(duration=10), limit=4096, interval=.25)
        self.assertEqual(200, output.getvalue().count('BATTLE REVIEW {'))

    def test_full_stage_cannot_consume_another_stage_or_priority_event(self):
        owner = types.SimpleNamespace(round_id=1)
        with mock.patch.dict(logs.os.environ, {logs.DETAIL_ENV: '1'}), \
                mock.patch.object(logs, 'write_json_record') as write:
            logs.battle_review_record(owner, 'radio', 1, 1, lambda: {})
            owner._battle_review_records[3]['radio'] = logs.REVIEW_STAGE_BYTES
            build = mock.Mock(side_effect=AssertionError('must remain lazy'))
            logs.battle_review_record(owner, 'radio', 2, 2, build)
            build.assert_not_called()
            logs.battle_review_record(owner, 'model', 1, 2, lambda: {})
            self.assertEqual('model', write.call_args[0][1]['stage'])
            logs.battle_review_record(owner, 'death', 1, 2, lambda: {}, priority=True)
            self.assertEqual('BATTLE REVIEW EVENT', write.call_args[0][0])
            owner.round_id = 2
            logs.battle_review_record(owner, 'radio', 1, 3, lambda: {})
            self.assertEqual(2, write.call_args[0][1]['round'])

    def test_career_evidence_is_disabled_in_normal_entry(self):
        with mock.patch.dict(logs.os.environ, {logs.DETAIL_ENV: '0'}), \
                mock.patch.object(logs.json, 'dumps', side_effect=AssertionError('encoded')), \
                mock.patch.object(logs, 'write_json_record') as write:
            logs.validation_event('career', value=object())
        write.assert_not_called()

    def namespace(self, owner):
        path = ROOT / 'src/res/scripts/client/gui/mods/offline_lan_0922/compat.py'
        tree = ast.parse(path.read_text(encoding='utf8'))
        names = {'_observe_battle_model_pose', '_run_model_pose_step', 'compound_getattribute'}
        nodes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                 and node.name in names]
        namespace = dict(compatibility=owner)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
        return namespace

    def test_actual_lookup_wraps_only_diagnostic_refresh_and_preserves_failure(self):
        owner = types.SimpleNamespace(_battle_active=True, _compound_refreshing_vehicle=None,
            _original_compound_getattribute=object.__getattribute__)
        class Appearance:
            def activate(self):
                return 42
        appearance = Appearance()
        owner._compound_refreshing_models = appearance
        ns = self.namespace(owner)
        observe = mock.Mock()
        ns['_observe_battle_model_pose'] = observe
        with mock.patch.dict(logs.os.environ, {logs.DETAIL_ENV: '0'}):
            self.assertEqual(42, ns['compound_getattribute'](appearance, 'activate')())
        observe.assert_not_called()
        with mock.patch.dict(logs.os.environ, {logs.DETAIL_ENV: '1'}):
            self.assertEqual(42, ns['compound_getattribute'](appearance, 'activate')())
            self.assertEqual(['activate_before', 'activate_after'],
                [call.args[2] for call in observe.call_args_list])
            error = RuntimeError('original error')
            appearance.setupGunMatrixTargets = mock.Mock(side_effect=error)
            with self.assertRaises(RuntimeError) as caught:
                ns['compound_getattribute'](appearance, 'setupGunMatrixTargets')()
            self.assertIs(error, caught.exception)
            self.assertEqual('gun_targets_after', observe.call_args.args[2])

    def test_deactivation_can_record_after_private_vehicle_is_unbound(self):
        matrix = types.SimpleNamespace(yaw=.5, pitch=.1, roll=0., translation=(0., 0., 0.))
        appearance = types.SimpleNamespace(turretMatrix=matrix, gunMatrix=matrix,
            _CompoundAppearance__vehicle=None, _CompoundAppearance__filter=None,
            _CompoundAppearance__currentDamageState=types.SimpleNamespace(modelState='destroyed'))
        vehicle = types.SimpleNamespace(id=123, appearance=appearance, health=0,
            model=types.SimpleNamespace(matrix=matrix, node=lambda name: matrix), filter=None)
        owner = types.SimpleNamespace(_battle_active=True, _runtime=types.SimpleNamespace(
            bigworld=types.SimpleNamespace(time=lambda: 1., player=lambda: None),
            math=types.SimpleNamespace(Matrix=lambda value: value)))
        ns = self.namespace(owner)
        with mock.patch.dict(logs.os.environ, {logs.DETAIL_ENV: '1'}), \
                mock.patch.object(logs, 'write_json_record') as write:
            ns['_observe_battle_model_pose'](owner, appearance, 'deactivate_after', vehicle)
        payload = write.call_args[0][1]
        self.assertEqual('model_deactivate_after', payload['stage'])
        self.assertFalse(payload['appearance_vehicle_bound'])
        self.assertEqual(.5, payload['turret']['yaw'])


if __name__ == '__main__':
    unittest.main()
