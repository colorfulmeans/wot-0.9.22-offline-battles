"""Reject stale or extra-entry packages before publishing the 1.1.3 release."""
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
SPEC = importlib.util.spec_from_file_location('release113', ROOT / 'tools/prepare_release113_assets.py')
ASSETS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASSETS)


def executable(machine):
    data = bytearray(128)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<H', data, 68, machine)
    return data


def launcher_folder(directory, version='1.1.3', mod_name='mods/current_1.1.3.wotmod'):
    launcher = Path(directory) / 'app'
    client = launcher / '_internal/client/0.9.22.zip'
    client.parent.mkdir(parents=True)
    (launcher / 'wot-0.9.22-offline-battles.exe').write_bytes(executable(0x8664))
    inner = Path(directory) / 'mod.zip'
    with zipfile.ZipFile(inner, 'w') as archive:
        archive.writestr('meta.xml', '<root><version>%s</version></root>' % version)
    with zipfile.ZipFile(client, 'w') as archive:
        archive.writestr('mods/configs/offline_lan_0922/build_identity.json',
                         json.dumps({'semanticVersion': version}))
        archive.writestr(mod_name, inner.read_bytes())
        archive.writestr('mods/0.9.22.0.1/offline_math_batch_native.pyd', bytes(executable(0x14c)))
    return launcher


class Release113Tests(unittest.TestCase):
    def setUp(self):
        # The reviewed native bytes are checked by verify_native_payload in CI;
        # these fakes exercise the release-specific checks around it.
        native = types.SimpleNamespace(verify_bytes=lambda unused_root, unused_data: None)
        patch = mock.patch.dict(sys.modules, {'verify_native_payload': native})
        patch.start()
        self.addCleanup(patch.stop)

    def test_old_semantic_version_is_not_publishable(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = launcher_folder(directory, version='1.1.2')
            with self.assertRaisesRegex(ValueError, 'version does not match'):
                ASSETS.prepare(launcher, Path(directory) / 'release')

    def test_new_identity_cannot_disguise_old_embedded_mod(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = launcher_folder(directory, mod_name='mods/old_1.1.2.wotmod')
            with self.assertRaisesRegex(ValueError, 'Incorrect embedded mod'):
                ASSETS.prepare(launcher, Path(directory) / 'release')

    def test_x86_launcher_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory)
            (launcher / 'wot-0.9.22-offline-battles.exe').write_bytes(executable(0x14c))
            with self.assertRaisesRegex(ValueError, 'Windows x64'):
                ASSETS.prepare(launcher, launcher / 'release')

    def test_release_archive_has_only_the_launcher_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = launcher_folder(directory)
            with mock.patch('builtins.print'):
                ASSETS.prepare(launcher, Path(directory) / 'release')
            assets = list((Path(directory) / 'release').iterdir())
            self.assertEqual(['wot-0.9.22-offline-battles-1.1.3-Windows-x64.zip'],
                             [path.name for path in assets])

    def test_diagnostic_batch_entry_is_not_publishable(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = launcher_folder(directory)
            (launcher / 'START_DIAGNOSTIC_TEST.bat').write_bytes(b'start "" launcher --diagnostics\r\n')
            with self.assertRaisesRegex(ValueError, 'only the normal launch entry'):
                ASSETS.prepare(launcher, Path(directory) / 'release')

    def test_release_notes_are_english_and_name_only_the_1_1_line(self):
        notes = (ROOT / 'docs/releases/v1.1.3.md').read_text(encoding='utf-8')
        self.assertFalse([ch for ch in notes if 0x3400 <= ord(ch) <= 0x9FFF])
        self.assertTrue(notes.startswith('# v1.1.3 '))
        self.assertIn('Built from `v1.1.2`', notes)
        self.assertEqual({'1.1'}, set(re.findall(r'v(\d+\.\d+)\.\d+', notes)))

    def test_publish_workflow_binds_main_and_the_release_tag(self):
        workflow = (ROOT / '.github/workflows/publish-v1.1.3.yml').read_text(encoding='utf-8')
        notes = (ROOT / 'docs/releases/v1.1.3.md').read_text(encoding='utf-8')
        self.assertIn('tags: [v1.1.3]', workflow)
        self.assertIn("github.ref == 'refs/heads/main' || github.ref == 'refs/tags/v1.1.3'", workflow)
        self.assertIn('git/ref/heads/main', workflow)
        self.assertIn('tools/prepare_release113_assets.py', workflow)
        title = notes.splitlines()[0][2:]
        self.assertIn("--title '%s'" % title, workflow)


if __name__ == '__main__':
    unittest.main()
