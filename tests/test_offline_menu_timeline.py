"""The native frame inspectors, not a pre-frame Python assignment, own grey logoff."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_offline_menu_swf as builder


class MenuTimelineTests(unittest.TestCase):
    def test_all_four_initializers_change_without_touching_other_buttons(self):
        source = '\n'.join('function frame%d() { logoffBtn.enabled = true; quitBtn.enabled = true; }' % i
                           for i in range(4))
        changed = builder.transform(source)
        self.assertEqual(4, changed.count('logoffBtn.enabled = false;'))
        self.assertEqual(4, changed.count('quitBtn.enabled = true;'))
        with self.assertRaises(ValueError):
            builder.transform(source.replace('logoffBtn.enabled = true;', '', 1))

    def test_shipping_movie_proof_matches_current_builder_and_pinned_menu(self):
        path = ROOT / 'src/res/gui/flash/LobbyMenu.swf'
        proof = json.loads(path.with_suffix('.swf.json').read_text())
        self.assertEqual(builder.INPUT_SHA256, proof['source_sha256'])
        self.assertEqual(4, proof['disabled_logoff_initializers'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), proof['output_sha256'])
        source = Path(builder.__file__).read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(hashlib.sha256(source).hexdigest(), proof['builder_sha256'])
        spec = importlib.util.spec_from_file_location('package_builder', ROOT / 'build_wotmod.py')
        package = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(package)
        package._validate_offline_menu_ui(str(ROOT))
