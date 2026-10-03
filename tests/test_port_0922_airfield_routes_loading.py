"""Directed route admission, reviewed road gates and navigation ownership."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src/res/scripts/client')]
from gui.mods.offline_lan_0922 import bot_tactics_runtime as planning
from gui.mods.offline_lan_0922 import spg_positions
import bake_navigation_0922 as bake
import test_port_0922_battle_runtime as native


def legacy_baker():
    # Git can check out CRLF on Windows; verify the unchanged vendored source.
    raw = Path(bake.NAVIGATION_BAKER).read_bytes().replace(b'\r\n', b'\n')
    assert hashlib.sha256(raw).hexdigest() == bake.NAVIGATION_BAKER_SHA256
    spec = importlib.util.spec_from_file_location('airfield_review_baker', bake.NAVIGATION_BAKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tiny_graph(width=8, height=8):
    directions = ((-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1))
    g = dict(game_version=spg_positions.CATALOG['game_version'], width=width,
             height=height, cell_size=4, origin=[0,0], bounds=[0,0,width*4,height*4],
             directions=directions, heights_mm=[0]*(width*height),
             hazards=[0]*(width*height), links=[0]*(width*height))
    for i in range(width*height):
        x,z=i%width,i//width
        g['links'][i]=sum(1<<bit for bit,(dx,dz) in enumerate(directions)
                          if 0<=x+dx<width and 0<=z+dz<height)
    return g


class RouteAdmissionTests(unittest.TestCase):
    def test_membership_matches_weighted_flood_with_one_way_links_and_holes(self):
        g=tiny_graph(5,4)
        g['heights_mm'][7]=None
        g['hazards'][12]=2
        for i in (1,5,9,16):
            g['links'][i] &= 0b10101010
        grid=spg_positions._Graph(g,g['bounds'])
        saved=copy.deepcopy(g)
        for start in range(grid.size):
            position=(start%grid.width*grid.cell,0,start//grid.width*grid.cell)
            distances=grid.distances(position)
            for target in range(grid.size):
                if grid.usable(target):
                    self.assertEqual(target in distances, planning._route_reachable(
                        grid,position,target),(start,target))
        self.assertEqual(saved,g)

    def test_forward_edge_does_not_admit_reverse_or_teleport_over_a_hole(self):
        g=tiny_graph(3,1);g['links']=[16,0,0]
        grid=spg_positions._Graph(g,g['bounds'])
        self.assertTrue(planning._route_reachable(grid,(0,0,0),1))
        self.assertFalse(planning._route_reachable(grid,(4,0,0),0))
        self.assertFalse(planning._route_reachable(grid,(0,0,0),2))
        g['heights_mm'][0]=None
        self.assertFalse(planning._route_reachable(grid,(0,0,0),1))

    def test_short_connections_do_not_scan_the_whole_map_or_request_distances(self):
        g=tiny_graph(100,100)
        grid=spg_positions._Graph(g,g['bounds'])
        with mock.patch.object(grid,'distances',side_effect=AssertionError('full flood')), \
                mock.patch.object(grid,'usable',wraps=grid.usable) as check:
            self.assertIsNone(planning.validate_route(grid,dict(points=[[0,0,0],[40,0,0]])))
            self.assertLess(check.call_count,100)
            used=check.call_count
            self.assertTrue(planning._route_reachable(grid,(0,0,0),10))
            self.assertEqual(used+1,check.call_count)


class AirfieldDefaultRoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph=json.loads((ROOT/'navgraphs/31_airfield.json').read_text())
        cls.legacy=legacy_baker()

    def test_baker_reproduces_both_teams_without_altering_terrain_or_links(self):
        g=copy.deepcopy(self.graph); saved=copy.deepcopy(g)
        for team,routes in g['routes'].items():
            for route in routes:
                bases=g['bases'] if team=='1' else list(reversed(g['bases']))
                route['waypoints']=[p+[False] for p in bases]
        bake.bake_airfield_road_routes(g,g['routes'],self.legacy)
        bake.canonicalize_reversible_routes(g,g['routes'])
        self.assertEqual(saved,g)

    def test_all_six_routes_are_connected_and_fit_the_existing_wire(self):
        grid=planning.graph_view('31_airfield',self.graph)
        with mock.patch.object(grid,'distances',side_effect=AssertionError('full flood')):
            for team,routes in self.graph['routes'].items():
                for route in routes:
                    self.assertLessEqual(len(route['waypoints']),16)
                    self.assertIsNone(planning.validate_route(grid,dict(points=route['waypoints'])))
                    self.assertIsNone(self.legacy._route_geometry_issue(route['waypoints']))
        for one,two in zip(self.graph['routes']['1'],self.graph['routes']['2']):
            self.assertEqual(list(reversed(one['waypoints'])),two['waypoints'])

    def test_west_south_opening_goes_east_instead_of_to_the_north_gate(self):
        route=next(r for r in self.graph['routes']['2'] if r['id']=='south_towns')
        start,following=route['waypoints'][:2]
        self.assertGreater(following[0]-start[0],30)
        self.assertLess(following[1],start[1])
        a=self.legacy._nearest_node(self.graph,start)[0]
        b=self.legacy._nearest_node(self.graph,following)[0]
        path,distance=self.legacy._graph_path(self.graph,a,b)
        self.assertLess(distance,60)
        self.assertTrue(all(self.legacy._node_point(self.graph,i)[1] <= -178 for i in path))

    def test_small_rock_and_ridge_centres_are_not_default_route_goals(self):
        centres=((-295,-65),(-245,-162),(66,82),(380,-18),(80,-300))
        for route in self.graph['routes']['1']:
            for p in route['waypoints']:
                for x,z in centres:
                    self.assertGreater((p[0]-x)**2+(p[1]-z)**2,20**2)

    def test_corner_links_leave_the_three_closed_side_cells_unchanged(self):
        self.assertEqual(4,self.graph['bake']['local_adapter_directed_links_added'])
        for p in ((-314,-190),(-306,-194),(-302,-190)):
            unused,index=bake._graph_state(self.graph,p)
            self.assertIsNone(self.graph['heights_mm'][index])
            self.assertEqual(0,self.graph['links'][index])
        for contract in bake._REVIEWED_NARROW_CORNER_CONTRACTS['31_airfield']:
            a,b=contract['points']
            cells=[bake._graph_state(self.graph,p)[0] for p in (a,b)]
            indices=[bake._graph_state(self.graph,p)[1] for p in (a,b)]
            delta=(cells[1][0]-cells[0][0],cells[1][1]-cells[0][1])
            self.assertTrue(self.graph['links'][indices[0]] & (1<<self.legacy.DIRECTIONS.index(delta)))
            self.assertTrue(self.graph['links'][indices[1]] & (1<<self.legacy.DIRECTIONS.index((-delta[0],-delta[1]))))


class NavigationOwnershipTests(unittest.TestCase):
    def test_navigation_uses_bounded_destroyed_skin_adapter_and_retains_its_wall_hit(self):
        battle=native.BattleRuntime(native._runtime())
        battle._avatar=types.SimpleNamespace(spaceID=7)
        collision_filter=lambda unused,material: material!=73
        wall=((0,0,5),(0,0,-1),2)
        adapter=mock.Mock(return_value=wall)
        battle._destructibles=types.SimpleNamespace(collide_motion_segment=adapter)
        with mock.patch.object(battle,'_navigation_collision_filter',return_value=collision_filter):
            self.assertIs(wall,battle._collide_navigation((0,0,0),(0,0,10)))
        args=adapter.call_args[0]
        self.assertEqual(7,args[0])
        self.assertIs(args[3],collision_filter)
        self.assertFalse(args[3](None,73))
        self.assertTrue(args[3](None,2))
        self.assertEqual(args[4],battle._runtime.bigworld.wg_collideSegment)
        self.assertEqual('native.navigation.ray',args[5])


if __name__=='__main__':
    unittest.main()
