"""Physical rebakes cannot republish tactical routes from an older input."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'src/res/scripts/client')]
import bake_navigation_0922 as baker
import rebake_navigation_resolution as resolution
import rebake_navigation_water as water


class RebakeDefaultAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # These packaged routes are independently matched to the reviewed
        # owner fixture by test_current_default_route_authority.
        cls.current = json.loads((ROOT / 'navgraphs/31_airfield.json').read_bytes())

    def stale(self):
        graph = copy.deepcopy(self.current)
        for rows in graph['routes'].values():
            for row in rows:
                row['waypoints'] = row['waypoints'][:1]
            rows.append(dict(id='august_dead_end', capacity=15, risk=0.,
                             role_weights={}, waypoints=[[0., 0., False]]))
        return graph

    def test_resolution_replaces_previous_routes_and_keeps_physical_fields(self):
        previous = self.stale()
        previous['terrain_edge_previous_sha256'] = 'retained-physical-identity'
        raw = json.dumps(previous).encode('ascii')
        graph = copy.deepcopy(self.current)
        before = copy.deepcopy(graph)
        result = resolution.retain_gameplay(graph, previous, raw)
        self.assertIs(graph, result)
        self.assertEqual(self.current['routes'], result['routes'])
        self.assertNotIn('routes', resolution.GAMEPLAY_FIELDS)
        for key in resolution.GAMEPLAY_FIELDS:
            self.assertEqual(previous.get(key), result.get(key), key)
        for key in ('heights_mm', 'links', 'hazards', 'directions', 'local_meshes'):
            self.assertEqual(before.get(key), result.get(key), key)
        self.assertEqual('retained-physical-identity', result['terrain_edge_previous_sha256'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), result['navigation_previous_sha256'])
        self.assertGreater(result['validation']['authored_default_route_segments'], 0)
        self.assertEqual(previous['routes'], self.stale()['routes'])

    def test_resolution_does_not_accept_disconnected_or_unknown_physical_input(self):
        for invalid in ('disconnected', 'unknown_map'):
            with self.subTest(invalid=invalid):
                graph = copy.deepcopy(self.current)
                if invalid == 'disconnected':
                    graph['links'] = [0] * len(graph['links'])
                else:
                    graph['map'] = 'unsupported_august_map'
                previous = copy.deepcopy(graph)
                with self.assertRaises(ValueError):
                    resolution.retain_gameplay(graph, previous, b'previous graph')

    @contextlib.contextmanager
    def remeasured(self):
        # Isolate only resource decoding/remeasurement. Route admission uses
        # the real publisher and the real current physical graph, not a stub.
        legacy = baker._legacy_baker()

        def unchanged(layer, *unused):
            return copy.deepcopy(layer), dict(
                cells_measured=layer['width'] * layer['height'], revived_cells=0)

        with mock.patch.object(water, 'geometry', return_value=(None, None, legacy)), \
                mock.patch.object(water, 'rebake_layer', side_effect=unchanged), \
                mock.patch.object(legacy, 'WATER_DEPTH_LIMIT', 1.2), \
                mock.patch.object(legacy, 'SHALLOW_WATER_THRESHOLD', 1.2), \
                contextlib.redirect_stdout(io.StringIO()):
            yield

    def build_water(self, graph):
        raw = (json.dumps(graph, indent=1) + '\n').encode('ascii')
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'previous.json', Path(directory) / 'new.json'
            source.write_bytes(raw)
            with self.remeasured():
                water.build('unused-resource-fixture', source, output)
            result = output.read_bytes()
        return raw, result

    def test_water_unchanged_geometry_does_not_copy_stale_routes_as_raw_bytes(self):
        previous = self.stale()
        raw, result_bytes = self.build_water(previous)
        self.assertNotEqual(raw, result_bytes)
        result = json.loads(result_bytes)
        self.assertEqual(self.current['routes'], result['routes'])
        self.assertEqual({k: v for k, v in previous.items() if k not in ('routes', 'validation')},
                         {k: v for k, v in result.items() if k not in ('routes', 'validation')})

    def test_water_already_current_routes_keep_exact_raw_and_provenance(self):
        raw, result = self.build_water(copy.deepcopy(self.current))
        self.assertEqual(raw, result)

    def test_water_full_publication_also_replaces_stale_routes(self):
        previous = self.stale()
        previous['bake']['water_policy_rebake']['all_cells_measured'] = False
        raw, result_bytes = self.build_water(previous)
        result = json.loads(result_bytes)
        self.assertEqual(self.current['routes'], result['routes'])
        self.assertIn(hashlib.sha256(raw).hexdigest(), result['navigation_previous_sha256s'])
        self.assertTrue(set(previous.get('navigation_previous_sha256s', ())).issubset(
            result['navigation_previous_sha256s']))
        for key in ('heights_mm', 'links', 'hazards', 'directions', 'local_meshes',
                    'spawn_formations', 'spawn_anchors', 'bases', 'objective_bases',
                    'objective_base_radii', 'bounds', 'origin', 'width', 'height', 'cell_size'):
            self.assertEqual(previous.get(key), result.get(key), key)

    def test_water_cannot_publish_unknown_map_or_invalid_default_connections(self):
        for invalid in ('disconnected', 'unknown_map'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                previous = self.stale()
                if invalid == 'disconnected':
                    previous['links'] = [0] * len(previous['links'])
                else:
                    previous['map'] = 'unsupported_august_map'
                source, output = Path(directory) / 'previous.json', Path(directory) / 'new.json'
                source.write_text(json.dumps(previous))
                with self.remeasured(), self.assertRaises(ValueError):
                    water.build('unused-resource-fixture', source, output)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
