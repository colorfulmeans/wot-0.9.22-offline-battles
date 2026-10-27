"""Publication contracts for the nineteen explicitly requested assets."""
import importlib.util
from pathlib import Path
import re
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('release_assets', ROOT / 'tools/prepare_release100_assets.py')
ASSETS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASSETS)


class ReleaseAssetsTests(unittest.TestCase):
    def test_bilingual_exports_preserve_every_reviewed_document(self):
        with tempfile.TemporaryDirectory() as directory:
            result = ASSETS.export_guides(directory)
            self.assertEqual(18, len(result))
            self.assertEqual(18, len({p.name for p in result}))
            for language, suffix in (('en', 'English'), ('zh-CN', 'Chinese')):
                sources = sorted((ROOT / 'docs/releases' / ('v1.0.0-guides.' + language)).glob('*.md'))
                for index, source in enumerate(sources, 1):
                    exported = next(p for p in result if p.name.startswith('%02d-' % index)
                                    and p.stem.endswith('-' + suffix))
                    expected = source.read_text(encoding='utf-8-sig')
                    expected = re.sub(r'^#{1,6} ', '', expected, flags=re.M).replace('**', '').replace('`', '')
                    self.assertTrue(exported.read_bytes().startswith(b'\xef\xbb\xbf'))
                    self.assertEqual(expected.replace('\r\n', '\n'), exported.read_text(encoding='utf-8-sig'))

    def test_missing_guides_refuse_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'exactly nine'):
                ASSETS.export_guides(Path(directory) / 'output', directory)

    def test_wrong_architecture_cannot_be_confused_with_game_extension(self):
        data = bytearray(128)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 0x3c, 64)
        data[64:68] = b'PE\0\0'
        struct.pack_into('<H', data, 68, 0x8664)
        self.assertEqual(0x8664, ASSETS.pe_machine(data))
        struct.pack_into('<H', data, 68, 0x14c)
        self.assertEqual(0x14c, ASSETS.pe_machine(data))
        with self.assertRaises(ValueError):
            ASSETS.pe_machine(b'not executable')

    def test_whitelist_and_issue_ids_match_between_languages(self):
        pairs = ((1, 'Vehicle-Fittings-Ammunition-and-Bot-Shell-Switching'),
                 (9, 'Known-Internal-Vehicle-Module-Issues'))
        for index, slug in pairs:
            english = (ROOT / 'docs/releases/v1.0.0-guides.en' / ('%02d-%s.md' % (index, slug))).read_text(encoding='utf-8')
            chinese = next((ROOT / 'docs/releases/v1.0.0-guides.zh-CN').glob('%02d-*.md' % index)).read_text(encoding='utf-8')
            identities = r'\b(?:china|ussr|usa|germany|czech|france|uk|japan|poland|sweden):[A-Za-z0-9_.-]+'
            self.assertEqual(set(re.findall(identities, chinese)), set(re.findall(identities, english)))


if __name__ == '__main__':
    unittest.main()
