"""Player-owned route entry and travel. No Bot allocator or Bot actor state."""
from __future__ import division
import copy
import math
from . import prebaked_navigation, bot_tactics, bot_tactics_runtime
from .ai.navigation import TerrainNavigator
from .ai.driver import LocalDriver


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
        catalog, unused = bot_tactics_runtime.default_routes(profile, name, graph)
        tags = descriptor.type.tags
        self.tag = next((t for t in bot_tactics.CLASSES if t in tags), 'mediumTank')
        self.routes = route_candidates(catalog, int(owner.client.team), self.tag)
        settings = bot_tactics.map_settings(profile, name)
        for route in settings.get('routes', ()):
            if bot_tactics.matches(route, dict(team=int(owner.client.team), slot=0,
                                             profile=dict(class_tag=self.tag))):
                self.routes.append(dict(route, id='user_'+route['id'], waypoints=route['points']))
        self.navigator = TerrainNavigator(owner._navigation_ground, owner._navigation_obstacle,
            graph.get('bounds'), 18., baked_graph=graph)
        from .native_navigation_query import Oracle
        self.navigator.grid.native_query_oracle = Oracle.create(owner)
        self.driver = LocalDriver()
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
            for route in self.routes:
                for index, point in enumerate(route.get('waypoints', ())):
                    height = self._height(point, position[1])
                    if height is None:
                        continue
                    goal = (float(point[0]), height, float(point[1]))
                    distance = math.sqrt(sum((a-b)**2 for a,b in zip(position,goal)))
                    candidates.append((distance, str(route['id']), index, route, goal))
            self.candidates = sorted(candidates, key=lambda r:r[:3])
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
                        point[0]-position[0], point[1]-position[2]) > 13.:
                    break
                self.index += 1
            point = points[self.index]
            height = self._height(point, position[1])
            goal = (point[0], height if height is not None else position[1], point[1])
            identity = int(state['id'])
            self.navigator.set_boundary_body(identity, position, state['yaw'],
                                             state['half_length'], state['half_width'])
            target = self.navigator.next_target(identity, position, goal,
                ('player_route', identity, self.route['id'], self.index), now)
        if hold:
            target = position
        command = self.driver.drive(state['id'], 0, position, state['yaw'], state['speed'],
            state['dt'], target, state['neighbours'], direction_clear,
            half_length=state['half_length'], half_width=state['half_width'],
            movement_intent=joined and not hold, stop_at_target=True,
            turn_speed_limit=state['turn_speed_limit'],
            pose_clear=lambda yaw:self.navigator.grid.hull_pose_clear(position,yaw,
                                            state['half_length'],state['half_width']))
        command.update(route_id=self.route['id'] if self.route else None,
                       route_index=self.index, local_target=target,
                       combat_mode='engage' if hold else 'route' if joined else 'joining')
        return command
