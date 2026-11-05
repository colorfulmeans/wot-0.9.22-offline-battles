"""Player map projections and runtime decisions cannot enter Bot owners.

The Bot implementation is used only as an offline compatibility oracle for
the existing editor/wire data. A separate fresh process blocks those imports
while exercising actual player navigation and parking.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import bot_tactics
from gui.mods.offline_lan_0922.bot_tactics_default_data import PROFILE_JSON
from gui.mods.offline_lan_0922.player_control import route_catalog
from gui.mods.offline_lan_0922.player_control.navigation import authored_routes, route_candidates
from gui.mods.offline_lan_0922.player_control.observations import public_allies


class PlayerMapDataTests(unittest.TestCase):
    def test_all_packaged_maps_keep_current_default_geometry_without_bot_loader(self):
        maps = json.loads(PROFILE_JSON)['maps']
        self.assertEqual(41, len(maps))
        for name in sorted(maps):
            expected = bot_tactics.default_map(name)
            with self.subTest(map=name):
                self.assertEqual(expected, route_catalog.packaged_map(name))
                self.assertEqual(expected, route_catalog.map_settings(None, name))
                self.assertEqual(expected, route_catalog.map_settings(dict(name='Default'), name))

    def test_sparse_class_and_shared_edits_keep_latest_resolution_semantics(self):
        for name in sorted(json.loads(PROFILE_JSON)['maps']):
            baseline = bot_tactics.default_map(name)
            shared = next(row for row in baseline['default_routes']
                          if row.get('class_tag', 'all') == 'all')
            common = dict(shared, points=[[10., 20., 0], [30., 40., 0]])
            variant = dict(common, class_tag='heavyTank', points=[[30., 40., 0], [50., 60., 0]])
            for rows in ([variant], [common], [common, variant], [dict(common, disabled=True)]):
                profile = dict(name='My edited roads', maps={name: dict(default_routes=rows)})
                before = copy.deepcopy(profile)
                with self.subTest(map=name, rows=len(rows), tag=rows[0].get('class_tag')):
                    self.assertEqual(bot_tactics.effective_map(profile, name),
                                     route_catalog.map_settings(profile, name))
                    self.assertEqual(before, profile)

    def test_default_name_ignores_stale_embedded_edits_but_custom_name_preserves_them(self):
        name = '02_malinovka'
        settings = dict(routes=[], positions=[], default_routes=[])
        stale = dict(name='DEFAULT', maps={name: settings})
        self.assertEqual(route_catalog.packaged_map(name), route_catalog.map_settings(stale, name))
        custom = route_catalog.map_settings(dict(stale, name='My roads'), name)
        self.assertEqual([], custom['positions'])
        self.assertEqual([], custom['routes'])
        self.assertTrue(custom['default_routes'])

    def test_each_player_and_bot_cache_have_separate_mutable_rows(self):
        name = '02_malinovka'
        expected = route_catalog.packaged_map(name)
        first = route_catalog.map_settings(None, name)
        first['default_routes'][0]['points'][0][0] += 100.
        first['positions'].append(dict(id='private', point=[0., 0.]))
        with mock.patch.object(bot_tactics, '_DEFAULT_PROFILE', dict(maps={name: {}})):
            self.assertEqual(expected, route_catalog.map_settings(None, name))
        self.assertNotEqual(first, route_catalog.map_settings(None, name))

    def test_warm_lookup_decodes_only_the_selected_map_without_global_validation(self):
        name = '02_malinovka'
        route_catalog.packaged_map(name)
        loads = json.loads
        decoded = []
        def observe(text):
            value = loads(text)
            decoded.append(value)
            return value
        with mock.patch.object(route_catalog.json, 'loads', side_effect=observe), \
             mock.patch.object(bot_tactics, 'normalize_values', side_effect=AssertionError('Bot normalizer')):
            route_catalog.map_settings(dict(name='Default'), name)
        self.assertEqual(1, len(decoded))
        self.assertIn('default_routes', decoded[0])
        self.assertNotIn('maps', decoded[0])

    def test_player_custom_routes_do_not_fabricate_a_bot_formation_slot(self):
        row = dict(id='human-road', team=1, classes=['heavyTank'], slots=[2, 4],
                   points=[[0., 0., 0], [10., 10., 0]])
        self.assertTrue(route_catalog.accepts_route(row, 1, 'heavyTank'))
        self.assertFalse(route_catalog.accepts_route(row, 2, 'heavyTank'))
        self.assertFalse(route_catalog.accepts_route(row, 1, 'SPG'))
        self.assertFalse(route_catalog.accepts_route(dict(row, disabled=True), 1, 'heavyTank'))
        sortie = dict(row, purpose='spg_attack', classes=['SPG'])
        self.assertTrue(route_catalog.accepts_route(sortie, 1, 'SPG'))
        self.assertFalse(route_catalog.accepts_route(sortie, 1, 'heavyTank'))

    def test_authored_waits_and_whole_route_exclusions_are_private(self):
        points = [[0., 0., 0], [10., 10., 1, 0., [[12., 10., 30.]]], [20., 20., 0]]
        graph = dict(routes={'1': [dict(id='road', waypoints=[[0., 0.], [20., 20.]])]})
        edit = dict(id='road', team=1, class_tag='AT-SPG', points=points)
        profile = dict(maps={'test': dict(default_routes=[edit])})
        catalog = authored_routes(profile, 'test', graph)
        route = route_candidates(catalog, 1, 'AT-SPG')[0]
        self.assertEqual('class_td_road', route['id'])
        self.assertEqual([[12., 10., 30.]], route_catalog.waiting_positions(route['waypoints'][1]))
        route['waypoints'][1][4][0][2] = 99.
        self.assertEqual(30., points[1][4][0][2])
        profile['maps']['test']['default_routes'].append(dict(id='road', team=1,
            disabled=True, points=points))
        self.assertEqual([], route_candidates(authored_routes(profile, 'test', graph), 1, 'AT-SPG'))


class PlayerPublicationTests(unittest.TestCase):
    def test_valid_public_roster_does_not_read_bot_creation_or_runtime(self):
        class Owner(SimpleNamespace):
            def __getattribute__(self, name):
                if name in ('_bots', '_pending_bot_create_order', '_pending_bot_creates', '_bots_ready_reported'):
                    raise AssertionError('player read Bot lifecycle: ' + name)
                return super().__getattribute__(name)
        owner = Owner(client=SimpleNamespace(player_id=7, team=1),
            _start_message=dict(round_id=4, players=[dict(id=7, team=1), dict(id=8, team=1)],
                                bots=[dict(id=3, team=1)]), _records={}, _last_snapshot={})
        rows, complete = public_allies(owner, [])
        self.assertTrue(complete)
        self.assertEqual({'player:8', 'bot:3'}, {row['id'] for row in rows})
        self.assertTrue(all(row['alive'] and row['class_tag'] is None for row in rows))
        self.assertTrue(all('position' not in row for row in rows))

    def test_fresh_player_navigation_and_parking_work_with_bot_imports_blocked(self):
        script = r'''
import importlib.abc
import pathlib
import sys
from types import SimpleNamespace

root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root / 'src/res/scripts/client'))
prefix = 'gui.mods.offline_lan_0922.'
blocked = ('bot_runtime', 'bot_tactics', 'bot_tactics_runtime', 'ammo_policy', 'bot_gunnery', 'ai')
class NoBot(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix + name or fullname.startswith(prefix + name + '.') for name in blocked):
            raise AssertionError('player imported Bot implementation: ' + fullname)
sys.meta_path.insert(0, NoBot())
from gui.mods.offline_lan_0922 import prebaked_navigation
from gui.mods.offline_lan_0922.player_control.navigation import PlayerNavigation
from gui.mods.offline_lan_0922.player_control.observations import public_allies
from gui.mods.offline_lan_0922.player_control.parking import RouteParking

class Owner(SimpleNamespace):
    def __getattribute__(self, name):
        if name in ('_bots', '_pending_bot_create_order', '_pending_bot_creates'):
            raise AssertionError('player read Bot owner: ' + name)
        return super().__getattribute__(name)

prebaked_navigation.CONFIG_PATH = str(root / 'config.json')
graph = prebaked_navigation.load_graph('02_malinovka')
holder = {}
owner = Owner(_start_message=dict(map='02_malinovka', round_id=1,
    bot_tactics=dict(name='Default'), players=[dict(id=7, team=1)], bots=[]),
    client=SimpleNamespace(team=1, player_id=7), _arena_bounds=graph['bounds'],
    _navigation_ground=lambda x,z,h: holder['nav'].navigator.grid._ground(x,z,h),
    _navigation_obstacle=lambda *args: False, _records={}, _last_snapshot={})
nav = PlayerNavigation(owner, SimpleNamespace(type=SimpleNamespace(tags=['AT-SPG'])))
holder['nav'] = nav
assert nav.routes
assert public_allies(owner, [])[1]
state = dict(id=7, engine_id=5007, now=0., position=(0.,0.,0.), speed=0., yaw=0.,
             half_length=2., half_width=1.)
route = dict(id='private-parking', waypoints=[[0.,0.,1,0.,[[0.,0.,1.]]]])
parking = RouteParking(1)
assert parking.update(route,0,state,dict(supported=True),lambda *args:0.)['holding']
owner._bots = object()
state['now'] = 2.
assert parking.update(route,0,state,dict(supported=True),lambda *args:0.)['complete']
assert public_allies(owner, [])[1]
assert nav.navigator.player_states == {}
nav.close()
assert not any(prefix+name in sys.modules for name in blocked)
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class PlayerAuthoredTopologyTests(unittest.TestCase):
    def road(self):
        return dict(id='medium-road', waypoints=[[0., 0., 0], [20., 20., 0],
            [40., 40., 1, 0., [[43., 40., -1.]]], [60., 60., 0]],
            node_ids=['home', 'junction', 'wait', 'enemy'], family='east', tier='reserve',
            defense=dict(junction='junction', points=[[20., 20., 0], [10., -5., 0], [0., -20., 0]]))

    def test_borrowed_spg_uses_reverse_home_connector_then_real_road_tail(self):
        road = self.road()
        before = copy.deepcopy(road)
        route = route_catalog.borrowed_roads([road])[0]
        self.assertEqual([[0., -20., 0], [10., -5., 0], [20., 20., 0],
                          [40., 40., 0], [60., 60., 0]], route['waypoints'])
        self.assertTrue(route['player_borrowed'])
        self.assertEqual(('east', 'reserve'), (route['family'], route['tier']))
        self.assertEqual(before, road)
        route['waypoints'][0][0] = 100.
        self.assertEqual(before, road)

    def test_broken_authored_junction_is_never_replaced_with_a_nearest_node(self):
        for change in (dict(junction='missing'), dict(junction='home'),
                       dict(points=[[25., 20., 0], [0., -20., 0]])):
            road = self.road()
            road['defense'].update(change)
            with self.subTest(change=change):
                self.assertEqual([], route_catalog.borrowed_roads([road]))

    def test_duplicate_geometry_unifies_aliases_without_shared_occupancy_claim(self):
        first = self.road()
        second = dict(first, id='heavy-road', family='heavy-east')
        routes = route_catalog.borrowed_roads([first, second])
        self.assertEqual(1, len(routes))
        self.assertEqual({'medium-road', 'heavy-road', 'east', 'heavy-east'},
                         set(routes[0]['player_road_ids']))
        self.assertNotIn('capacity', routes[0])
        self.assertNotIn('slots', routes[0])

    def test_class_overlay_preserves_its_nodes_and_drops_stale_common_branch(self):
        common = self.road()
        graph = dict(routes={'1': [dict(id='road', waypoints=[[0.,0.,0],[1.,1.,0]])]})
        shared = dict(common, id='road', team=1, points=common['waypoints'])
        variant = dict(id='road', team=1, class_tag='AT-SPG',
                       points=[[20.,10.,0],[30.,20.,0]], node_ids=['td-home', 'td-end'], tier='main')
        profile = dict(maps={'test': dict(default_routes=[variant, shared])})
        routes = authored_routes(profile, 'test', graph)
        selected = route_candidates(routes, 1, 'AT-SPG')[0]
        self.assertEqual(['td-home', 'td-end'], selected['node_ids'])
        self.assertNotIn('defense', selected)
        self.assertEqual('main', selected['tier'])
        ordinary = route_candidates(routes, 1, 'heavyTank')[0]
        self.assertEqual(common['defense'], ordinary['defense'])
        self.assertEqual(common['node_ids'], ordinary['node_ids'])

    def test_player_navigation_borrows_only_effective_ordinary_class_roads(self):
        from gui.mods.offline_lan_0922.player_control import navigation
        from gui.mods.offline_lan_0922 import native_navigation_query
        from test_player_navigation_migration import NativeNavigationSeam
        graph = dict(bounds=(-200.,-200.,200.,200.), objective_bases=[(0.,-100.),(0.,100.)],
            objective_base_radii=[20.,20.], routes={'1':[dict(id='road',
                class_weights={'SPG':0.}, waypoints=[[0.,-100.,0],[0.,0.,0],[0.,100.,0]])]})
        edits = [dict(id='road', team=1, class_tag=tag,
            points=[[float(index),-100.,0],[float(index),0.,0],[0.,100.,0]])
            for index,tag in enumerate(route_catalog.VEHICLE_CLASSES[:-1],1)]
        profile = dict(name='Custom', maps={'test':dict(default_routes=edits)})
        owner = SimpleNamespace(_start_message=dict(map='test',bot_tactics=profile),
            client=SimpleNamespace(team=1),_arena_bounds=graph['bounds'],
            _navigation_ground=None,_navigation_obstacle=None)
        seam = NativeNavigationSeam()
        with mock.patch.object(navigation.prebaked_navigation,'load_graph',return_value=graph), \
             mock.patch.object(navigation.prebaked_navigation,'clip_graph_to_arena'), \
             mock.patch.object(navigation.prebaked_navigation,'with_shore_hazards',side_effect=lambda g:g), \
             mock.patch.object(navigation,'PlayerPathfinder',return_value=seam), \
             mock.patch.object(native_navigation_query.Oracle,'create',return_value=None):
            nav = navigation.PlayerNavigation(owner,SimpleNamespace(type=SimpleNamespace(tags=['SPG'])))
        self.addCleanup(nav.close)
        self.assertEqual(4,len(nav.sortie_routes))
        self.assertTrue(all(route['player_route_source'].startswith('class_') for route in nav.sortie_routes))
        self.assertNotIn('road',[route['player_route_source'] for route in nav.sortie_routes])
        nav.artillery.mode='sortie'
        nav.set_context(dict(allies=[]))
        state=dict(id=7,engine_id=5007,now=0.,position=(0.,0.,-100.),yaw=0.,speed=0.,
                   half_length=2.,half_width=1.)
        nav.decide(state,lambda *args:True)
        self.assertTrue(nav.route['player_borrowed'])
        self.assertTrue(nav.sortie_started)


if __name__ == '__main__':
    unittest.main()
