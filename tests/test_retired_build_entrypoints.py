"""Current builds cannot restore retired Bot strategies or historical routes.

The old source-rewriting jobs and their embedded patch payloads are deleted,
not switched off behind a flag. Historical prose/proof JSON may remain as audit
records; none of those records is an executable build input for these jobs.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RETIRED_TOOLS = (
    'bot077_build.py', 'full_bot080_build.py',
    'apply_bot080_radio_fix.py', 'bot_editor_build.py',
    'bot_editor_localization_build.py', 'exchange_crew_test_build.py',
    'release_v094.py', 'spg_tracking_build.py', 'repair_094_build.py',
    'ram_contact_build.py', 'apply_ram_contact_repair.py',
    'test_094_repairs.py', 'verify_immutable_build.py',
    'verify_v080_bot_build.py', 'test_v080_bot_behavior.py',
    'test_v080_runtime_boundaries.py', 'verify_airfield_test_build.py',
    'test_airfield_review_gate.py',
)
RETIRED_WORKFLOWS = (
    'build-bot077-compare.yml', 'build-full-bot080-test.yml',
    'build-bot080-radio.yml', 'build-bot080-startfix.yml',
    'build-v080-bot-test.yml', 'build-094-mechanics-test.yml',
    'build-094-bot-editor.yml', 'build-094-bot-editor-i18n.yml',
    'build-094-ram-contact-test.yml', 'build-spg-tracking-test.yml',
    'build-exchange-crew-test.yml', 'build-airfield-test.yml',
    'build-no-native-review-test.yml', 'launcher-editor-source.yml',
    'publish-v0.9.4.yml',
)
RETIRED_PATCHES = (
    'bot_editor.patch*.b64', 'repair_094.patch*.b64',
    'spg_tracking.patch*.b64', 'editor_i18n.patch*.b64',
    'exchange_crew_test.patch.b64',
)


class RetiredBuildEntrypointTests(unittest.TestCase):
    def test_historical_source_rewriters_and_pinned_build_helpers_are_deleted(self):
        for name in RETIRED_TOOLS:
            with self.subTest(tool=name):
                self.assertFalse((ROOT / 'tools' / name).exists())

    def test_historical_restore_workflows_are_deleted_not_disabled(self):
        for name in RETIRED_WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertFalse((ROOT / '.github/workflows' / name).exists())

    def test_embedded_old_source_patches_cannot_recreate_retired_logic(self):
        for pattern in RETIRED_PATCHES:
            with self.subTest(pattern=pattern):
                self.assertEqual([], list((ROOT / 'tools').glob(pattern)))

    def test_remaining_tools_and_workflows_do_not_call_retired_helpers(self):
        files = list((ROOT / 'tools').rglob('*.py'))
        files += list((ROOT / 'tools').rglob('*.sh'))
        files += list((ROOT / 'tools').rglob('*.ps1'))
        files += list((ROOT / '.github/workflows').glob('*.yml'))
        tokens = RETIRED_TOOLS + RETIRED_WORKFLOWS
        for path in files:
            source = path.read_text(encoding='utf-8')
            for token in tokens:
                with self.subTest(path=path.relative_to(ROOT), retired=token):
                    self.assertNotIn(token, source)

    def test_current_build_and_current_physical_validation_entrypoints_remain(self):
        paths = (
            'build_wotmod.py', 'build_for_client.sh', 'build_wotmod_docker.sh',
            '.github/workflows/build-launcher.yml', '.github/workflows/tests.yml',
            'launcher/stage_payload.py', 'launcher/build_launcher.ps1',
            'server/build_windows_server.ps1',
            'tools/verify_release0100_code.py',
            'tools/verify_release0100_package.py', 'tools/validate_wotmod.py',
            'tools/build_math_batch_native.sh', 'tools/verify_native_payload.py',
            'tools/check_shared_vehicle_control.py', 'tools/run_test_suite.py',
            'tools/test_bot080_radio_contract.py',
            'tools/test_bot080_startup_contract.py',
            'tools/test_immutable_navigation.py',
            'tests/test_current_default_route_authority.py',
            'tests/test_port_0922_ram_contact_followup.py',
        )
        for relative in paths:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())
                self.assertTrue((ROOT / relative).read_bytes())

    def test_standard_windows_build_uses_current_sources_and_real_payload_gates(self):
        workflow = (ROOT / '.github/workflows/build-launcher.yml').read_text(
            encoding='utf-8')
        for command in (
                'python build_wotmod.py', 'sh tools/build_math_batch_native.sh',
                'tools/verify_release0100_code.py',
                'tools/verify_release0100_package.py'):
            self.assertIn(command, workflow)
        for historical_restore in ('git show', 'git reset', 'git apply',
                                   '.localization-baseline', '.airfield-transfer'):
            self.assertNotIn(historical_restore, workflow)


if __name__ == '__main__':
    unittest.main()
