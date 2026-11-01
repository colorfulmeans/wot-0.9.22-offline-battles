"""Reject stale packages before publishing the 1.1.0 release."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
SPEC = importlib.util.spec_from_file_location('release110', ROOT / 'tools/prepare_release110_assets.py')
ASSETS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASSETS)


def executable(machine):
    data = bytearray(128)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<H', data, 68, machine)
    return data


class Release110Tests(unittest.TestCase):
    def test_old_semantic_version_is_not_publishable(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory) / 'app'
            client = launcher / '_internal/client/0.9.22.zip'
            client.parent.mkdir(parents=True)
            (launcher / 'wot-0.9.22-offline-battles.exe').write_bytes(executable(0x8664))
            with zipfile.ZipFile(client, 'w') as archive:
                archive.writestr('mods/configs/offline_lan_0922/build_identity.json',
                                 json.dumps({'semanticVersion': '1.0.0'}))
            with self.assertRaisesRegex(ValueError, 'version does not match'):
                ASSETS.prepare(launcher, Path(directory) / 'release')

    def test_new_identity_cannot_disguise_old_embedded_mod(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory) / 'app'
            client = launcher / '_internal/client/0.9.22.zip'
            client.parent.mkdir(parents=True)
            (launcher / 'wot-0.9.22-offline-battles.exe').write_bytes(executable(0x8664))
            with zipfile.ZipFile(client, 'w') as archive:
                archive.writestr('mods/configs/offline_lan_0922/build_identity.json',
                                 json.dumps({'semanticVersion': '1.1.0'}))
                archive.writestr('mods/old_1.0.0.wotmod', b'old payload')
            with self.assertRaisesRegex(ValueError, 'Incorrect embedded mod'):
                ASSETS.prepare(launcher, Path(directory) / 'release')

    def test_x86_launcher_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory)
            (launcher / 'wot-0.9.22-offline-battles.exe').write_bytes(executable(0x14c))
            with self.assertRaisesRegex(ValueError, 'Windows x64'):
                ASSETS.prepare(launcher, launcher / 'release')

    def test_release_notes_are_english_and_preserve_approved_scope(self):
        notes = (ROOT / 'docs/releases/v1.1.0.md').read_text(encoding='utf-8')
        self.assertNotRegex(notes, '[\u3400-\u9fff]')
        self.assertIn('Add strategic vehicle-reward missions', notes)
        self.assertIn('Rebuild notification delivery', notes)
        self.assertIn('three vehicles of any class', notes)
        self.assertIn('three vehicles of the same class', notes)
        self.assertIn('Personal-campaign progress and rules are not reset', notes)


if __name__ == '__main__':
    unittest.main()
