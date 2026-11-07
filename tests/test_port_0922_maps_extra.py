"""The shipped and empty-round catalogs derive from the reviewed Default."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import bot_tactics as config, bot_tactics_runtime
from gui.mods.offline_lan_0922.ai import maps
from gui.mods.offline_lan_0922.player_control.copied import (
    bot_tactics as player_config, bot_tactics_runtime as player_routes)


class PackagedDefaultRoutesTests(unittest.TestCase):
    def test_every_runtime_catalog_uses_the_same_reviewed_route_coordinates(self):
        self.assertEqual(set(config.MAPS), set(maps.TACTICAL_MAPS))
        for name in config.MAPS:
            with self.subTest(map=name):
                graph = json.loads((ROOT / 'navgraphs' / (name + '.json')).read_bytes())
                settings = config.default_map(name)
                shared = config.shared_route_points(settings)
                empty = config.effective_round(config.empty(), name)
                self.assertEqual(settings, empty['maps'][name])
                baked = {(int(team), r['id']): r['waypoints']
                         for team, rows in graph['routes'].items() for r in rows}
                static = {(team, r['id']): [list(p) for p in r['waypoints']]
                          for team, rows in maps.TACTICAL_MAPS[name]['routes'].items() for r in rows}
                self.assertEqual(shared, baked)
                self.assertEqual(shared, static)
                bot, outcomes = bot_tactics_runtime.default_routes(empty, name, graph)
                self.assertEqual({'baked_route_connected'}, set(outcomes.values()))
                player, player_outcomes = player_routes.default_routes(
                    player_config.effective_round(player_config.empty(), name), name, graph)
                self.assertEqual(outcomes, player_outcomes)
                self.assertEqual(bot, player)
                self.assertIsNot(bot, player)
                for row in settings['default_routes']:
                    team, route_id = row['team'], config.default_route_id(row)
                    self.assertEqual([p[:3] for p in row['points']],
                                     next(r['waypoints'] for r in bot[str(team)] if r['id'] == route_id))
                    player_row = next(r for r in player[str(team)] if r['id'] == route_id)
                    self.assertEqual([p[:3] for p in row['points']], player_row['waypoints'])
                    self.assertIsNot(next(r for r in bot[str(team)] if r['id'] == route_id),
                                     player_row)

    def test_sparse_profile_and_failed_class_edit_use_packaged_default(self):
        name = '100_thepit'
        baseline = config.default_map(name)
        graph = json.loads((ROOT / 'navgraphs' / (name + '.json')).read_bytes())
        wanted = next(r for r in baseline['default_routes']
                      if r['team'] == 2 and r.get('class_tag') == 'mediumTank')
        edit = dict(wanted, points=[list(p) for p in wanted['points']])
        edit['points'][1] = [350., 300., 0]
        edit.pop('defense', None)
        profile = config.empty('Sparse profile')
        profile['maps'][name] = dict(baseline, default_routes=[edit])
        round_profile = config.effective_round(profile, name)
        self.assertEqual(baseline, config.effective_round(
            dict(profile, name='Default'), name)['maps'][name])
        self.assertEqual(30, len(round_profile['maps'][name]['default_routes']))
        catalog, status = bot_tactics_runtime.default_routes(round_profile, name, graph)
        player, player_status = player_routes.default_routes(
            player_config.effective_round(profile, name), name, graph)
        self.assertEqual(catalog, player)
        self.assertEqual(status, player_status)
        identity = config.default_route_id(wanted)
        self.assertEqual('built_in_default_fallback', status['2:' + identity])
        actual = next(r for r in catalog['2'] if r['id'] == identity)
        self.assertEqual(wanted['points'], actual['waypoints'])
        self.assertEqual(wanted['defense'], config.route_config(
            round_profile, name, identity, 2, actual['waypoints'])['defense'])

    def test_invalid_common_override_restores_displaced_class_routes(self):
        name = '100_thepit'
        baseline = config.default_map(name)
        graph = json.loads((ROOT / 'navgraphs' / (name + '.json')).read_bytes())
        common = next(r for r in baseline['default_routes']
                      if r['team'] == 2 and r.get('class_tag', 'all') == 'all')
        edit = dict(common, points=[list(p) for p in common['points']])
        edit['points'][1] = [350., 300., 0]
        edit.pop('defense', None)
        profile = config.empty('Common override')
        profile['maps'][name] = dict(baseline, default_routes=[edit])
        catalog, status = bot_tactics_runtime.default_routes(
            config.effective_round(profile, name), name, graph)
        player, player_status = player_routes.default_routes(
            player_config.effective_round(profile, name), name, graph)
        self.assertEqual(catalog, player)
        self.assertEqual(status, player_status)
        self.assertEqual('built_in_default_fallback', status['2:' + common['id']])
        for row in baseline['default_routes']:
            if row['team'] == 2 and row['id'] == common['id']:
                route_id = config.default_route_id(row)
                actual = next(r for r in catalog['2'] if r['id'] == route_id)
                self.assertEqual([p[:3] for p in row['points']], actual['waypoints'])
