"""Exact compiled #1513 objectives, with all authored navigation preserved."""
import hashlib
import json
import struct
import unittest
from pathlib import Path
from test_port_0922_navigation_baker import compiled_space
from gui.mods.offline_lan_0922 import capture_circles, bot_tactics
from gui.mods.offline_lan_0922.bot_editor_maps import MAPS

ROOT = Path(__file__).resolve().parents[1]


class CaptureCoordinateTests(unittest.TestCase):
    def test_all_41_maps_match_compiled_circle_receipts_and_fingerprints(self):
        receipts = json.loads((ROOT / 'tests/fixtures/standard_capture_circles_1513.json').read_text())
        manifest = json.loads((ROOT / 'navgraphs/manifest.json').read_text())
        self.assertEqual(set(MAPS), set(receipts))
        self.assertEqual(41, len(receipts))
        hashes = dict((e['map'], e['sha256']) for e in manifest['maps'])
        for name, expected in receipts.items():
            raw = (ROOT / 'navgraphs' / (name + '.json')).read_bytes()
            graph = json.loads(raw)
            self.assertEqual(expected['centres'], graph['objective_bases'], name)
            self.assertEqual(expected['radii'], graph['objective_base_radii'], name)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), hashes[name], name)
            self.assertEqual(hashes[name], MAPS[name]['resource_sha256'], name)

    def test_standard_mode_ignores_other_mode_control_points(self):
        rows = []
        for team, mask, x in ((1, 2, 500), (2, 2, -500), (2, 1, -85), (1, 1, 85)):
            row = bytearray(124)
            struct.pack_into('<3f', row, 48, x, 0.0, 20.0)
            struct.pack_into('<fI', row, 64, 40.0, team)
            struct.pack_into('<I', row, 120, mask)
            rows.append(row)
        space = compiled_space([('WTCP', 2, struct.pack('<II', 124, len(rows)) + b''.join(rows))])
        self.assertEqual([([85.0, 20.0], 40.0), ([-85.0, 20.0], 40.0)],
                         capture_circles.standard_circles_from_space(space))
        duplicate = compiled_space([('WTCP', 2, struct.pack('<II', 124, 5) + b''.join(rows + rows[-1:]))])
        with self.assertRaises(ValueError):
            capture_circles.standard_circles_from_space(duplicate)

    def test_verified_coordinate_only_update_preserves_authored_profile(self):
        profile = bot_tactics.empty()
        name = '01_karelia'
        profile['maps'][name] = dict(mode='regular', resource_sha256=MAPS[name]['capture_coordinate_previous_sha256'],
                                     routes=[], positions=[dict(id='test', label='Authored parking', team=1,
                                         point=[398.0, 402.0], radius=16.0, heading=0.0, priority=5)])
        updated = bot_tactics.canonical(profile)
        self.assertEqual(MAPS[name]['resource_sha256'], updated['maps'][name]['resource_sha256'])
        profile['maps'][name]['resource_sha256'] = '0' * 64
        with self.assertRaises(bot_tactics.TacticsError):
            bot_tactics.canonical(profile)
