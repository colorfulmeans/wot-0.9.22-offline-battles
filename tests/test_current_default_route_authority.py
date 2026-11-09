"""Only the owner-reviewed October Default may seed runtime route geometry."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from gui.mods.offline_lan_0922 import bot_tactics as config
from gui.mods.offline_lan_0922 import bot_tactics_runtime as planning
from gui.mods.offline_lan_0922 import prebaked_navigation
from gui.mods.offline_lan_0922.ai import maps


ROOT = Path(__file__).resolve().parents[1]
OWNER = json.loads((ROOT / 'tests/fixtures/default_tactics_owner_20261025.json').read_text())


def graph(name):
    return json.loads((ROOT / 'navgraphs' / (name + '.json')).read_bytes())


def stale_routes(value):
    for team, rows in value['routes'].items():
        for row in rows:
            row['waypoints'] = [[-80., -270., 1]] if team == '1' else [[45., 270., 1]]
        rows.append(dict(id='august_dead_end', capacity=15, risk=0.,
                         role_weights={}, waypoints=[[0., 0., 0]]))
    return value


class CurrentDefaultAuthorityTests(unittest.TestCase):
    def test_every_catalog_uses_owner_reviewed_points_and_unchanged_allocation_metadata(self):
        profile = config.default_profile()
        self.assertEqual(41, len(profile['maps']))
        self.assertEqual(OWNER['profile_digest'], config.digest(profile))
        negative_z = 0
        for name, entry in profile['maps'].items():
            with self.subTest(map=name):
                self.assertEqual(OWNER['maps'][name]['digest'],
                                 hashlib.sha256(config.dumps(entry).encode('ascii')).hexdigest())
                catalog = maps.default_route_catalog(name)
                self.assertEqual(graph(name)['routes'], catalog)
                self.assertTrue(all(type(point[2]) is bool for rows in catalog.values()
                                    for row in rows for point in row['waypoints']))
                shared = config.shared_route_points(entry)
                self.assertEqual(shared, {(int(team), row['id']): row['waypoints']
                                         for team, rows in catalog.items() for row in rows})
                negative_z += sum(point[1] < 0 for points in shared.values() for point in points)
                # One caller cannot mutate the authority used by another.
                catalog['1'][0]['waypoints'][0][0] += 20
                self.assertEqual(shared, {(int(team), row['id']): row['waypoints']
                                         for team, rows in maps.default_route_catalog(name).items()
                                         for row in rows})
        self.assertGreater(negative_z, 0)

    def test_absent_or_default_profile_never_uses_embedded_old_graph_routes(self):
        for name in ('04_himmelsdorf', '31_airfield', '59_asia_great_wall'):
            with self.subTest(map=name):
                dirty = stale_routes(graph(name))
                before = copy.deepcopy(dirty)
                expected, expected_status = planning.default_routes(config.default_profile(), name, graph(name))
                for profile in (config.empty(), config.empty('User sparse profile'),
                                config.default_profile()):
                    actual, status = planning.default_routes(profile, name, dirty)
                    self.assertEqual(expected, actual)
                    self.assertEqual(expected_status, status)
                    self.assertEqual({'baked_route_connected'}, set(status.values()))
                self.assertEqual(before, dirty)

    def test_failed_custom_override_can_only_restore_reviewed_default(self):
        name = '31_airfield'
        profile = config.empty('Editable test profile')
        entry = config.default_map(name)
        edited = next(row for row in entry['default_routes']
                      if row['team'] == 1 and row.get('class_tag', 'all') == 'all')
        edited['points'] = copy.deepcopy(edited['points'])
        edited['points'][1][0] += 1
        rejected_points = edited['points']
        profile['maps'][name] = dict(entry, default_routes=[edited])
        original_validate = planning.validate_route

        def validation(grid, route):
            if route['points'] == rejected_points:
                return 'waypoints_disconnected'
            return original_validate(grid, route)

        with mock.patch.object(planning, 'validate_route', side_effect=validation):
            actual, status = planning.default_routes(profile, name, stale_routes(graph(name)))
        expected, unused = planning.default_routes(config.default_profile(), name, graph(name))
        # Restored class variants may be appended after unaffected variants.
        # Compare every field by stable identity, not the recovery visit order.
        for team in ('1', '2'):
            self.assertEqual({row['id']: row for row in expected[team]},
                             {row['id']: row for row in actual[team]})
        self.assertEqual('built_in_default_fallback', status['1:' + edited['id']])

    def test_failed_baseline_validation_still_cannot_restore_old_points(self):
        name = '04_himmelsdorf'
        with mock.patch.object(planning, 'validate_route', return_value='waypoints_disconnected'):
            actual, status = planning.default_routes(config.empty(), name, stale_routes(graph(name)))
        expected = maps.default_route_catalog(name)
        for team, rows in actual.items():
            for row in rows:
                row.pop('_allocation_symmetric')
        self.assertEqual(expected, actual)
        self.assertEqual({'waypoints_disconnected'}, set(status.values()))

    def test_installed_legacy_route_list_is_replaced_without_mutating_physical_data(self):
        name = '04_himmelsdorf'
        dirty = stale_routes(graph(name))
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'navgraphs'
            directory.mkdir()
            (directory / (name + '.json')).write_text(json.dumps(dirty))
            actual = prebaked_navigation.load_graph(name, temp)
        self.assertEqual(maps.default_route_catalog(name), actual['routes'])
        for key in ('heights_mm', 'links', 'hazards'):
            self.assertEqual(dirty[key], list(actual[key]))
        for key in ('origin', 'bounds', 'cell_size', 'spawn_anchors', 'spawn_formations',
                    'objective_bases', 'objective_base_radii', 'local_meshes'):
            self.assertEqual(dirty.get(key), actual.get(key), key)

    def test_baker_publishes_reviewed_routes_without_old_geometry_or_metadata(self):
        # Exercise the actual publisher, not just its route catalog helper.
        with mock.patch.object(sys, 'path', [str(ROOT / 'tools')] + sys.path):
            spec = importlib.util.spec_from_file_location(
                'current_default_baker', ROOT / 'tools/bake_navigation_0922.py')
            baker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(baker)
        for name in ('04_himmelsdorf', '31_airfield', '59_asia_great_wall'):
            with self.subTest(map=name):
                dirty = stale_routes(graph(name))
                dirty['routes']['1'][0]['capacity'] = 999
                physical = {key: copy.deepcopy(value) for key, value in dirty.items()
                            if key not in ('routes', 'validation')}
                self.assertIs(dirty, baker.publish_default_routes(dirty))
                self.assertEqual(maps.default_route_catalog(name), dirty['routes'])
                self.assertEqual(physical, {key: value for key, value in dirty.items()
                                            if key not in ('routes', 'validation')})

    def test_route_replacement_does_not_bypass_physical_graph_validation(self):
        name = '31_airfield'
        invalid = stale_routes(graph(name))
        invalid['links'] = []
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'navgraphs'
            directory.mkdir()
            (directory / (name + '.json')).write_text(json.dumps(invalid))
            with self.assertRaisesRegex(ValueError, 'links array is incomplete'):
                prebaked_navigation.load_graph(name, temp)


if __name__ == '__main__':
    unittest.main()
