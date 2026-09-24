"""Installed WTCP circles -> graph -> ready packet -> server capture law."""
import copy
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zipfile

from gui.mods.offline_lan_0922 import capture_circles, prebaked_navigation
from gui.mods.offline_lan_0922.spawn_planner import SpawnPlanner
import test_port_0922_server_capture as capture_tests
import lan_battle_server as server


ROOT = Path(__file__).resolve().parents[1]


def _compiled(points, prefix=b''):
    rows = []
    for point in points:
        # The source fixture records only the fields relevant to capture.
        row = bytearray(124)
        struct.pack_into('<16f', row, 0, *point['transform'])
        struct.pack_into('<fII', row, 64, point['radius'],
                         point['team'], point.get('base_id', 1))
        struct.pack_into('<I', row, 120, point.get('visibility_mask', 1))
        rows.append(bytes(row))
    payload = struct.pack('<2I', 124, len(rows)) + b''.join(rows)
    return (struct.pack('<4s5I', b'BWTB', 1, 48, 0, 0, 1) +
            struct.pack('<4s5I', b'WTCP', 2, 48 + len(prefix), 0,
                        len(payload), 0) + prefix + payload)


class CaptureCircleTests(unittest.TestCase):
    def setUp(self):
        self.points = json.loads((ROOT /
            'tests/fixtures/thepit_wtcp_circles.json').read_text())['control_points']
        self.graph = json.loads((ROOT / 'navgraphs/100_thepit.json').read_text())

    def read(self, data, bases=None):
        return capture_circles.read_ctf_radii(
            io.BytesIO(data), len(data), bases or self.graph['objective_bases'])

    def test_pinned_mittengard_points_select_standard_teams_not_encounter(self):
        self.assertEqual([30., 30.], self.read(_compiled(self.points)))
        self.assertEqual([30., 30.], self.read(_compiled(self.points[::-1])))
        duplicate = self.points + [dict(self.points[1])]
        self.assertEqual([30., 30.], self.read(_compiled(duplicate)))

    def test_no_radius_guess_when_circle_is_missing_ambiguous_or_malformed(self):
        cases = [self.points[:1], self.points + [dict(self.points[1], radius=50.)]]
        for bad_radius in (0., -1., float('nan'), float('inf')):
            points = copy.deepcopy(self.points)
            points[1]['radius'] = bad_radius
            cases.append(points)
        for points in cases:
            with self.subTest(points=points):
                with self.assertRaises(ValueError):
                    self.read(_compiled(points))
        data = _compiled(self.points)
        for bad in (data[:20], data[:-1], data.replace(b'WTCP', b'BWST', 1)):
            with self.assertRaises(ValueError):
                self.read(bad)

    def test_section_layout_and_version_must_match_the_pinned_client(self):
        for offset, value in ((28, 1), (32, 0), (40, 7), (48, 120), (52, 4)):
            data = bytearray(_compiled(self.points))
            struct.pack_into('<I', data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.read(bytes(data))

    def test_streaming_never_retains_the_large_geometry_section(self):
        class BoundedStream(io.BytesIO):
            def read(self, size=-1):
                if size < 0 or size > 65536:
                    raise AssertionError('unbounded compiled-space read')
                return super(BoundedStream, self).read(size)
        data = _compiled(self.points, prefix=b'geometry' * 20000)
        self.assertEqual([30., 30.], capture_circles.read_ctf_radii(
            BoundedStream(data), len(data), self.graph['objective_bases']))

    def test_both_reported_maps_take_local_wtcp_values_through_ready_to_capture(self):
        # Synthetic radii deliberately differ from 30/50. This tests data flow;
        # it does not pretend to establish either unavailable map's real value.
        for name in ('63_tundra', '44_north_america'):
            graph = json.loads((ROOT / ('navgraphs/%s.json' % name)).read_text())
            points = copy.deepcopy(self.points[1:])
            for index, point in enumerate(points):
                point['transform'][12] = graph['objective_bases'][index][0]
                point['transform'][14] = graph['objective_bases'][index][1]
                point['radius'] = (27., 42.)[index]
            for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                with self.subTest(map=name, compression=compression), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    package = root / 'res/packages' / (name + '.pkg')
                    package.parent.mkdir(parents=True)
                    with zipfile.ZipFile(str(package), 'w', compression) as archive:
                        archive.writestr('spaces/%s/space.bin' % name, _compiled(points))
                    graphs = root / 'overlay/navgraphs'
                    graphs.mkdir(parents=True)
                    (graphs / (name + '.json')).write_text(json.dumps(graph))
                    original = capture_circles.apply_installed_radii
                    with mock.patch.object(capture_circles, 'apply_installed_radii',
                                           side_effect=lambda data: original(data, folder)):
                        loaded = prebaked_navigation.load_graph(name, str(graphs.parent))
                    planner = SpawnPlanner(navigation_graph=loaded)
                    state = capture_tests.ServerCaptureTests()._state()
                    state.phase = 'loading'
                    state.bot_authority_id = server.SIMULATION_WORKER_AUTHORITY_ID
                    state.simulation_worker = capture_tests._player(
                        server.SIMULATION_WORKER_AUTHORITY_ID, 1, 0., 0.)
                    state.mark_battle_ready(server.SIMULATION_WORKER_AUTHORITY_ID, {
                        'round_id': state.round_id,
                        'bases': json.loads(json.dumps(planner.capture_bases)),
                    })
                    state.phase = 'battle'
                    self.assertEqual([27., 42.], loaded['objective_base_radii'])
                    self.assertEqual(graph['objective_bases'], loaded['objective_bases'])
                    for team in (1, 2):
                        base = state.capture_bases[team][0]
                        for offset, expected in ((base['radius'], 1), (base['radius'] + .01, 0)):
                            state.players.clear()
                            state.players[2] = capture_tests._player(2, 3 - team,
                                base['x'] + offset, base['z'])
                            capture_tests.ServerCaptureTests._capture_tick(state)
                            self.assertEqual(expected, state.rules_state['bases'][str(team)]['invaders'])

    def test_failed_local_read_preserves_proved_baked_radius(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(capture_circles.apply_installed_radii(self.graph, folder))
            self.assertEqual([30., 30.], self.graph['objective_base_radii'])
            path = Path(folder) / 'res/packages/100_thepit.pkg'
            path.parent.mkdir(parents=True)
            with zipfile.ZipFile(str(path), 'w') as archive:
                archive.writestr('spaces/100_thepit/space.bin', _compiled(self.points[:1]))
            with self.assertRaises(ValueError):
                capture_circles.apply_installed_radii(self.graph, folder)
            self.assertEqual([30., 30.], self.graph['objective_base_radii'])


if __name__ == '__main__':
    unittest.main()
