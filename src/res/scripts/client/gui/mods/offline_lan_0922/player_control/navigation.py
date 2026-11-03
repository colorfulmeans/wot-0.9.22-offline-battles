"""Player-owned route entry and travel. No Bot allocator or Bot actor state."""
from __future__ import division
import copy
import math
from .. import prebaked_navigation, bot_tactics
from ..ai.navigation import TerrainNavigator
from .driving import Driver


def authored_routes(profile, name, graph):
    """Copy static geometry only; no director, allocation or Bot actor calls."""
    result = copy.deepcopy(graph.get('routes') or {})
    edits = bot_tactics.map_settings(profile, name).get('default_routes', ())
    for edit in edits:
        rows = result.get(str(edit['team']), [])
        base = next((r for r in rows if r['id'] == edit['id']), None)
        if base is None:
            continue
        tag = edit.get('class_tag', 'all')
        if edit.get('disabled'):
            if tag == 'all':
                rows.remove(base)
            else:
                base.setdefault('_editor_disabled_classes', []).append(tag)
        elif tag == 'all':
            base['waypoints'] = copy.deepcopy(edit['points'])
        else:
            variant = copy.deepcopy(base)
            variant.update(id=bot_tactics.default_route_id(edit),
                           _editor_source=base['id'], _editor_class=tag,
                           waypoints=copy.deepcopy(edit['points']))
            rows.append(variant)
    return result


def route_candidates(catalog, team, tag):
    rows = catalog.get(str(team), catalog.get(team, ())) or ()
    variants = dict((r['_editor_source'], r) for r in rows
                    if r.get('_editor_source') and r.get('_editor_class') == tag)
    result = []
    for base in rows:
        if base.get('_editor_source'):
            continue
        route = variants.get(base['id'], base)
        if tag in base.get('_editor_disabled_classes', ()) and route is base:
            continue
        if (route.get('class_weights') or {}).get(tag, 1) <= 0:
            continue
        # Main and reserve routes are equally eligible for mid-battle entry.
        result.append(copy.deepcopy(route))
    return result


class PlayerNavigation(object):
    def __init__(self, owner, descriptor):
        name = owner._start_message['map']
        graph = copy.deepcopy(prebaked_navigation.load_graph(name))
        prebaked_navigation.clip_graph_to_arena(graph, owner._arena_bounds)
        graph = prebaked_navigation.with_shore_hazards(graph)
        profile = copy.deepcopy(owner._start_message.get('bot_tactics') or bot_tactics.empty())
        catalog = authored_routes(profile, name, graph)
        tags = descriptor.type.tags
        self.tag = next((t for t in bot_tactics.CLASSES if t in tags), 'mediumTank')
        self.routes = route_candidates(catalog, int(owner.client.team), self.tag)
        bases = graph.get('objective_bases') or ()
        self.home = tuple(bases[int(owner.client.team)-1][:2]) if len(bases)==2 else None
        settings = bot_tactics.map_settings(profile, name)
        for route in settings.get('routes', ()):
            if route.get('disabled') or route['team'] != int(owner.client.team):
                continue
            if route.get('purpose') == 'spg_attack':
                if self.tag == 'SPG':
                    self.routes.append(dict(route, id='user_'+route['id'],
                                            waypoints=route['points'], player_spg_attack=True))
            elif bot_tactics.matches(route, dict(team=int(owner.client.team), slot=0,
                                               profile=dict(class_tag=self.tag))):
                self.routes.append(dict(route, id='user_'+route['id'], waypoints=route['points']))
        self.selection = self.routes
        self.navigator = TerrainNavigator(owner._navigation_ground, owner._navigation_obstacle,
            graph.get('bounds'), 18., baked_graph=graph)
        from ..native_navigation_query import Oracle
        self.navigator.grid.native_query_oracle = Oracle.create(owner)
        self.driver = Driver()
        self.route = None
        self.index = None
        self.candidates = None
        self.search = None
        self.pending = None
        self.join_origin = None
        self.retry_at = 0.
        self.receipt = dict(status='not_started')

    def close(self):
        self.navigator.close()

    def _height(self, point, hint):
        return self.navigator.grid._ground(float(point[0]), float(point[1]), hint)

    def retask(self, routes):
        self.selection = list(routes)
        self.route = self.index = self.candidates = self.search = self.pending = None
        self.retry_at = 0.
        self.receipt = dict(status='player_retask')

    def join(self, position, now):
        """Rank all points in 3D, then require an actual connected path.

        Resumable searches stay bounded; an overhead baked layer cannot prove
        an entry from a lower road by snapping the search's first point.
        """
        if self.route is not None:
            return True
        if now < self.retry_at:
            return False
        if self.candidates is None:
            self.join_origin = tuple(position)
            candidates = []
            for route in getattr(self, 'selection', self.routes):
                for index, point in enumerate(route.get('waypoints', ())):
                    height = self._height(point, position[1])
                    if height is None:
                        continue
                    goal = (float(point[0]), height, float(point[1]))
                    distance = math.sqrt(sum((a-b)**2 for a,b in zip(position,goal)))
                    candidates.append((distance, str(route['id']), index, route, goal))
            self.candidates = sorted(candidates, key=lambda r: (not r[3].get('player_spg_attack'),) + r[:3])
        if self.search is None:
            if not self.candidates:
                self.receipt = dict(status='no_connected_entry')
                self.retry_at = now + 2.
                self.candidates = None
                return False
            self.pending = self.candidates.pop(0)
            self.search = self.navigator.grid.begin_plan(self.join_origin, self.pending[4],
                                                        now=now, max_expansions=4096)
        self.search.step(32)
        self.receipt = dict(status='checking_entry', route=self.pending[1], index=self.pending[2],
                            start=self.join_origin, goal=self.pending[4])
        if not self.search.done:
            return False
        path = self.search.result
        self.search = None
        goal = self.pending[4]
        # One metre is an entry support tolerance, not a teleport allowance.
        # Every subsequent edge is still proved by the current navigator.
        connected = (path and abs(path[0][1]-self.join_origin[1]) <= 1. and
                     math.sqrt(sum((a-b)**2 for a,b in zip(path[-1],goal))) <= 13.)
        if not connected:
            self.receipt['status'] = 'rejected_layer_or_path'
            return False
        self.route, self.index = self.pending[3], self.pending[2]
        self.receipt.update(status='joined', path_length=len(path))
        return True

    def decide(self, state, direction_clear, hold=False):
        position, now = state['position'], state['now']
        joined = self.join(position, now)
        target = position
        if joined:
            points = self.route['waypoints']
            while self.index+1 < len(points):
                point = points[self.index]
                height = self._height(point, position[1])
                if height is None or abs(height-position[1]) > 1. or math.hypot(
                        point[0]-position[0], point[1]-position[2]) > 10.:
                    break
                self.index += 1
            point = points[self.index]
            height = self._height(point, position[1])
            goal = (point[0], height if height is not None else position[1], point[1])
            identity = int(state['id'])
            self.navigator.set_boundary_body(identity, position, state['yaw'],
                                             state['half_length'], state['half_width'])
            target = self.navigator.next_target(identity, position, goal,
                ('route', identity, self.route['id'], self.index), now)
        command = self.driver.drive(position, state['yaw'], state['speed'], target,
                                    now, direction_clear, hold=hold or not joined)
        if self.driver.replan:
            self.navigator.bot_states.pop(int(state['id']), None)
        command.update(route_id=self.route['id'] if self.route else None,
                       route_index=self.index, local_target=target,
                       combat_mode='engage' if hold else 'route' if joined else 'joining',
                       driving=self.driver.receipt)
        return command
