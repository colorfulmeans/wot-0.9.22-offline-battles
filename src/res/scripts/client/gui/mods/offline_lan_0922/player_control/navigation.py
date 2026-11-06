"""Player-owned route entry and travel. No Bot allocator or Bot actor state."""
from __future__ import division
import copy
import math
from .. import prebaked_navigation
from . import route_catalog
from .pathfinding import PlayerPathfinder
from .driving import Driver, angle
from .missions import Mission, base_areas, distance, legal_support, PROGRESS_TIMEOUT, TERMINAL
from .artillery import Artillery
from .strategy import CombatPolicy, target_value
from .navigation_support import PlayerHeightSupport
from .local_routes import LocalRoutes
from .cover import PlayerCover
from .parking import RouteParking
from .sortie import SortieProgress, geometry as route_geometry


def authored_routes(profile, name, graph):
    """Copy static geometry only; no director, allocation or Bot actor calls."""
    result = copy.deepcopy(graph.get('routes') or {})
    edits = (profile or {}).get('maps', {}).get(name, {}).get('default_routes', ())
    # Common geometry is the parent of every class projection, even if the
    # wire document happens to put an AT-SPG variant before its common row.
    for edit in sorted(edits, key=lambda row: row.get('class_tag', 'all') != 'all'):
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
            route_catalog.apply_geometry(base, edit)
        else:
            variant = copy.deepcopy(base)
            variant.update(id=route_catalog.class_route_id(edit),
                           _editor_source=base['id'], _editor_class=tag,
                           class_weights=dict((name, 1. if name == tag else 0.)
                                              for name in route_catalog.VEHICLE_CLASSES))
            route_catalog.apply_geometry(variant, edit)
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
        if not isinstance(graph, dict):
            raise ValueError('Player navigation map is unavailable')
        prebaked_navigation.clip_graph_to_arena(graph, owner._arena_bounds)
        graph = prebaked_navigation.with_shore_hazards(graph)
        settings = route_catalog.map_settings(owner._start_message.get('bot_tactics'), name)
        catalog = authored_routes({'maps': {name: settings}}, name, graph)
        tags = descriptor.type.tags
        self.tag = next((t for t in route_catalog.VEHICLE_CLASSES if t in tags), 'mediumTank')
        self.routes = route_candidates(catalog, int(owner.client.team), self.tag)
        self.team = int(owner.client.team)
        self.bounds = graph.get('bounds')
        bases = graph.get('objective_bases') or ()
        self.home = tuple(bases[int(owner.client.team)-1][:2]) if len(bases)==2 else None
        planner = getattr(owner, '_spawn_planner', None)
        active_bases = getattr(planner, 'capture_bases', getattr(planner, 'bases', None))
        self.home_area, self.enemy_area = base_areas(graph, self.team, active_bases)
        if self.home_area is not None:
            self.home = tuple(self.home_area['point'])
        for route in settings.get('routes', ()):
            if not route_catalog.accepts_route(route, self.team, self.tag):
                continue
            if route.get('purpose') == 'spg_attack':
                self.routes.append(dict(route, id='user_'+route['id'],
                                        waypoints=route['points'], player_spg_attack=True))
            else:
                self.routes.append(dict(route, id='user_'+route['id'], waypoints=route['points']))
        self.spg_attack_routes = [route for route in self.routes if route.get('player_spg_attack')]
        self.travel_routes = [route for route in self.routes if not route.get('player_spg_attack')]
        self.sortie_routes = list(self.spg_attack_routes)
        if self.tag == 'SPG':
            roads = []
            for tag in route_catalog.VEHICLE_CLASSES[:-1]:
                roads.extend(route_candidates(catalog, self.team, tag))
            roads.extend(dict(route, id='user_'+route['id'], waypoints=route['points'])
                         for route in settings.get('routes', ())
                         if route.get('purpose') != 'spg_attack' and any(
                             route_catalog.accepts_route(route, self.team, tag)
                             for tag in route_catalog.VEHICLE_CLASSES[:-1]))
            self.sortie_routes.extend(route_catalog.borrowed_roads(roads))
        for route in self.sortie_routes:
            route['player_sortie'] = True
        self.context = {}
        self.policy_cache = None
        self.mission = None
        self.previous_mission = None
        self.mission_sequence = 0
        self.automatic_recovery = None
        self.capture_retry_at = 0.
        self.capture_failures = 0
        self.parking = RouteParking(self.team)
        self.parking_order = None
        self.combat = CombatPolicy(self.tag)
        self.artillery = None
        if self.tag == 'SPG':
            positions = settings.get('positions')
            if positions is None:
                positions = route_catalog.packaged_map(name).get('positions', ())
            deleted = set(settings.get('deleted_positions', ()))
            self.artillery = Artillery([row for row in positions if row['id'] not in deleted],
                                       self.team, self.home_area)
        self.automatic_defence = False
        self.resume_route = None
        self.resume_sortie = None
        self.sortie_progress = SortieProgress()
        self.sortie_rejections = {}
        self.sortie_receipt = None
        self.sortie_terminal = None
        self.sortie_entry_since = None
        self.sortie_started = False
        self.firing_move = None
        self.cover_move = None
        self.cover_search = PlayerCover(owner)
        self.cover_retry_at = 0.
        self.firing_retry_at = 0.
        self.selection = self.travel_routes or self.routes
        self.navigator = PlayerPathfinder(owner._navigation_ground, owner._navigation_obstacle,
            graph.get('bounds'), 18., baked_graph=graph)
        from ..native_navigation_query import Oracle
        self.navigator.grid.native_query_oracle = Oracle.create(owner, watch_bot_owner=False)
        self.support = PlayerHeightSupport(self.navigator.grid,
            getattr(owner, '_navigation_ground', None),
            getattr(owner, '_navigation_height_columns', None))
        self.local_routes = LocalRoutes(self.navigator, self.support, self.team)
        self.route_history = []
        self.reload_route = None
        self.ammo_retreat = None
        self.driver = Driver()
        self.route = None
        self.index = None
        self.candidates = None
        self.search = None
        self.pending = None
        self.join_origin = None
        self.retry_at = 0.
        control = getattr(owner, '_player_control', None)
        self.opening_origin = getattr(control, 'opening_origin', None)
        anchors = graph.get('spawn_anchors') or graph.get('bases') or ()
        self.opening_anchor = anchors[self.team - 1] if len(anchors) == 2 else None
        self.receipt = dict(status='not_started')

    def close(self):
        if self.mission is not None and self.mission.status not in TERMINAL:
            self.mission.finish('cancelled', 'controller_stopped', self.mission._last_now)
        self.support.close()
        self.local_routes.reset()
        self.parking.release()
        self.navigator.close()
        self.cover_search.close()
        self.search = self.pending = self.candidates = None
        self.cover_move = self.firing_move = self.reload_route = None
        self.ammo_retreat = None
        self.route_history = []
        self.context = {}
        self.sortie_progress.reset()
        self.sortie_rejections.clear()
        self.resume_sortie = None
        self.sortie_receipt = None
        self.sortie_terminal = None
        self.sortie_entry_since = None

    def _height(self, point, hint, strict=False):
        return self.support.height(point, hint, strict)

    def _reset_travel(self, routes):
        self.opening_origin = None
        self.policy_cache = None
        self.mission_goal_key = None
        self.selection = list(routes)
        self.route = self.index = self.candidates = self.search = self.pending = None
        self.retry_at = 0.
        self.driver = Driver()
        reset = getattr(self.navigator, 'reset_travel', None)
        if callable(reset):
            reset()
        else:
            self.navigator.player_states.clear()
        self.local_routes.reset()
        self.route_history = []
        self.reload_route = None
        self.cover_search.reset()
        self.parking.release()
        self.parking_order = None
        self.sortie_entry_since = None
        progress = getattr(self, 'sortie_progress', None)
        if progress is not None:
            progress.reset()

    def retask(self, routes, reason=None):
        """Automatic suggestions cannot replace an accepted player command."""
        mission = self.mission
        if (mission is not None and (mission.protected or
                (mission.capturing and mission.status not in ('failed', 'cancelled') and
                 mission.wants_hold()))) or self.context.get('empty_ammo'):
            self.receipt = dict(status='mission_owns_movement',
                                mission=mission.identity if mission is not None else None)
            return False
        routes = list(routes)
        defending = reason == 'defend' or any(
            str(route['id']).startswith('player_base_defence') for route in routes)
        now = self.context.get('now', 0.)
        if self.artillery is not None and self.artillery.mode == 'sortie' and not defending:
            # Strategy proposes ordinary lane identities. Resolve those to
            # this player's own sortie projection (including its home branch)
            # instead of accepting a road that bypasses the sortie cursor.
            identities = set(route['id'] for route in routes)
            geometries = set(route_geometry(route) for route in routes)
            routes = [copy.deepcopy(route) for route in self.sortie_routes
                if (route['id'] in identities or
                    identities.intersection(route.get('player_road_ids', ())) or
                    route_geometry(route) in geometries) and
                route_geometry(route) not in self.sortie_rejections]
            if not routes:
                self.receipt = dict(status='unavailable_sortie_routes_rejected')
                return False
            proposed = set(route_geometry(route) for route in routes)
            unchanged = (self.route is not None and self.route.get('player_sortie') and
                         route_geometry(self.route) in proposed)
            unchanged = unchanged or (self.route is None and self.selection and
                all(route.get('player_sortie') for route in self.selection) and
                proposed == set(route_geometry(route) for route in self.selection))
            if unchanged:
                # A strategy lane and its SPG projection have different ids.
                # Repeated pressure suggestions for that same geometry cannot
                # renew entry/recovery deadlines or discard an existing cursor.
                self.receipt = dict(status='sortie_route_unchanged')
                return False
        if (self.artillery is not None and not defending and not self.automatic_defence and
                self.artillery.mode not in ('sortie', 'fallback')):
            # Validate the replacement owner before retiring a live automatic
            # task; a rejected suggestion must not change mission identity.
            self.receipt = dict(status='artillery_owns_deployment')
            return False
        if mission is not None:
            mission.finish('cancelled', 'automatic_retask_%s' % (reason or 'strategy'), now)
            self.previous_mission = mission.snapshot()
            self.mission = None
        if self.artillery is not None:
            if defending and not self.automatic_defence:
                self.resume_route = (list(self.selection), self.route, self.index)
                self.resume_sortie = copy.deepcopy(self.sortie_progress)
                self.resume_sortie.pause(now)
                self.artillery.suspend(now)
            elif self.automatic_defence and not defending:
                self.artillery.resume(now)
                if self.resume_route is not None:
                    selection, route, index = self.resume_route
                    self._reset_travel(selection)
                    self.route, self.index = route, index
                    if self.resume_sortie is not None:
                        self.sortie_progress = self.resume_sortie
                        self.sortie_progress.resume(now)
                    self.resume_sortie = None
                    self.resume_route = None
                    self.automatic_defence = False
                    self.receipt = dict(status='resumed_after_defence')
                    return True
        self.automatic_defence = defending
        self._reset_travel(routes)
        self.cover_move = self.firing_move = None
        self.combat.reset()
        self.receipt = dict(status='player_retask')
        return True

    def set_context(self, context):
        # Lists may be observation snapshots, but none are mutated by policies.
        self.context = dict(context or {})
        self.policy_cache = None

    def mission_status(self):
        result = self.mission.snapshot() if self.mission is not None else dict(
            id=None, action=None, explicit=False, status='idle', phase='idle',
            progress=0., reason=None, result=None, holding=False)
        if self.automatic_recovery is not None:
            result['automatic_recovery'] = copy.deepcopy(self.automatic_recovery)
        if self.sortie_receipt is not None:
            result['sortie_recovery'] = copy.deepcopy(self.sortie_receipt)
        if self.mission is None and self.sortie_terminal is not None:
            result.update(status='failed', phase='failed', reason=self.sortie_terminal,
                          result=dict(reason=self.sortie_terminal))
        return result

    def _prepare_mission(self, action, args, state):
        args = dict(args or {})
        identity = args.get('command_id', 'player-mission-%d' % (self.mission_sequence + 1))
        mission = Mission(identity, action, args, state, self.home_area, self.enemy_area)
        if mission.goal is not None and self.bounds is not None:
            x, z = mission.goal
            left, bottom, right, top = self.bounds
            if (math.isnan(x) or math.isnan(z) or math.isinf(x) or math.isinf(z) or
                    not left <= x <= right or not bottom <= z <= top):
                mission.finish('failed', 'objective_outside_arena', state['now'])
        return mission

    def validate_mission(self, action, args, state):
        """Allow the caller to validate before releasing another input owner."""
        return self._prepare_mission(action, args, state).snapshot()

    def start_mission(self, action, args, state):
        mission = self._prepare_mission(action, args, state)
        if mission.status == 'failed':
            # Validation precedes cancelling any accepted task or native lease.
            return mission.snapshot()
        self.mission_sequence += 1
        if self.mission is not None:
            if self.mission.status not in TERMINAL:
                self.mission.finish('cancelled', 'replaced_by_command', state['now'])
            self.previous_mission = self.mission.snapshot()
        self.mission = mission
        self.automatic_recovery = None
        self.capture_retry_at = 0.
        self.capture_failures = 0
        self.cover_move = self.firing_move = None
        self.combat.reset()
        self.automatic_defence = False
        self.resume_route = None
        self.resume_sortie = None
        self.sortie_rejections.clear()
        self.sortie_receipt = None
        self.sortie_terminal = None
        routes = self.travel_routes or self.routes
        if self.tag == 'SPG' and action == 'attack':
            routes = self.sortie_routes
        self._reset_travel(routes)
        self.receipt = dict(status='mission_started', mission=mission.identity, action=action)
        return self.mission_status()

    def cancel_mission(self, reason='cancelled', now=None):
        if self.mission is not None:
            self.mission.finish('cancelled', reason,
                                self.mission._last_now if now is None else now)
            self.previous_mission = self.mission.snapshot()
        self.mission = None
        if self.artillery is not None and self.artillery.mode == 'defending':
            self.artillery.resume(self.context.get('now', 0.) if now is None else now)
        self.automatic_defence = False
        self.resume_route = None
        self.resume_sortie = None
        self.sortie_rejections.clear()
        self.sortie_receipt = None
        self.sortie_terminal = None
        self.sortie_started = False
        self.cover_move = self.firing_move = None
        self.combat.reset()
        self._reset_travel(self.travel_routes or self.routes)

    def finish_battle(self, result, now):
        """Settle the accepted objective before native teardown cancels work."""
        mission = self.mission
        if mission is not None and mission.status not in TERMINAL:
            result = result if isinstance(result, dict) else {}
            captured = (result.get('winner') == self.team and
                        result.get('reason') == 'base captured' and
                        result.get('base_team') == 3 - self.team)
            captured = captured or bool(self.context.get('capture_complete') or
                (self.context.get('enemy_base') or {}).get('points', 0) >= 100)
            if mission.capturing and captured:
                mission.phase = 'captured'
                mission.finish('completed', 'base_captured', now)
            else:
                mission.finish('cancelled', 'battle_finished_before_objective', now)
            mission.result['battle'] = dict((key, result.get(key))
                for key in ('winner', 'reason', 'base_team'))
            self.policy_cache = None
        return self.mission_status()

    def _automatic_capture(self, state, reason):
        if state['now'] < self.capture_retry_at:
            return False
        self.mission_sequence += 1
        self.mission = Mission('auto-capture-%d' % self.mission_sequence,
            'capture_base', {}, state, self.home_area, self.enemy_area, explicit=False)
        if self.mission.status not in TERMINAL:
            self.mission.reason = reason
        self.cover_move = self.firing_move = None
        self.combat.reset()
        self._reset_travel(self.travel_routes or self.routes)
        return True

    def _retire_failed_automatic(self, state):
        mission = self.mission
        if mission is None or mission.explicit or mission.status not in ('failed', 'cancelled'):
            return False
        self.previous_mission = mission.snapshot()
        self.capture_failures += 1
        # Retry admission is bounded and does not retain a failed movement or
        # fire owner. An armed hull can defend/fight immediately; an empty hull
        # retains capture intent and retries after this finite backoff.
        self.capture_retry_at = state['now'] + min(30., 5. * self.capture_failures)
        self.automatic_recovery = dict(reason='automatic_mission_retired',
            previous=self.previous_mission, retry_at=self.capture_retry_at,
            failures=self.capture_failures, empty_ammo=bool(self.context.get('empty_ammo')))
        self.mission = None
        self.cover_move = self.firing_move = None
        self.combat.reset()
        routes = self.travel_routes or self.routes
        if self.artillery is not None and self.artillery.mode == 'sortie':
            # Capture timeout is not a new command or actual route progress.
            # Keep the sortie retirement ledger; when exhausted, an empty
            # selection lets the existing capture backoff own the next retry.
            routes = [route for route in self.sortie_routes
                      if route_geometry(route) not in self.sortie_rejections]
        self._reset_travel(routes)
        self.receipt = dict(status='automatic_mission_recovery',
                            recovery=copy.deepcopy(self.automatic_recovery))
        return True

    def _update_parking(self, state):
        mission = self.mission
        if (self.route is None or self.index is None or self.automatic_defence or
                (mission is not None and (not mission.route_attack or mission.status in TERMINAL))):
            self.parking_order = None
        else:
            self.parking_order = self.parking.update(self.route, self.index,
                state, self.context, self._height, self.support.snapshot)
        return self.parking_order

    def movement_policy(self, state):
        """Resolve one movement owner before combat or automatic retasking."""
        sample = (state['now'], tuple(state['position']), state['yaw'], state['speed'])
        if self.policy_cache is not None and self.policy_cache[0] == sample:
            return dict(self.policy_cache[1])
        context = self.context
        context['now'] = state['now']
        self.support.begin(state['position'], state['now'])
        self.local_routes.publish(state, context)
        empty = bool(context.get('empty_ammo'))
        if empty:
            if self.mission is None:
                self._automatic_capture(state, 'empty_ammo_capture')
            elif self.mission.action == 'attack' and self.mission.status not in TERMINAL:
                transitioning = not self.mission.capturing
                self.mission.enter_capture(self.enemy_area, state, 'empty_ammo_capture')
                if transitioning:
                    self.combat.reset()
                    self._reset_travel(self.travel_routes or self.routes)
            self.cover_move = self.firing_move = None
        mission = self.mission
        if mission is not None:
            position = state['position']
            mission.observe(state, context, self._height((position[0], position[2]), position[1]))
            if self._retire_failed_automatic(state):
                mission = None
        parking = self._update_parking(state)
        parked_route = bool(parking is not None and not parking['complete'])
        parked_artillery = False
        if self.artillery is not None and mission is None and not self.automatic_defence:
            self.artillery.update(state, context, self._height, evidence=self.support.snapshot)
            parked_artillery = self.artillery.mode not in ('sortie', 'fallback')
        ordinary_combat = (not empty and not parked_artillery and not parked_route and
                           (mission is None or (mission.route_attack and mission.status not in TERMINAL)))
        combat_hold = self.combat.update(state, context, allowed=ordinary_combat)
        holding = mission.wants_hold() if mission is not None else False
        force_move = False
        if mission is not None and not mission.route_attack:
            force_move = not holding
        if parked_route:
            holding = parking['holding']
            force_move = not holding
            combat_hold = bool(holding and context.get('target') is not None and context.get('fire_clear'))
        if self.artillery is not None and mission is None and not self.automatic_defence:
            if parked_artillery:
                holding = self.artillery.holding(state, context, self._height)
                force_move = not holding
                combat_hold = bool(holding and context.get('target') is not None and context.get('fire_clear'))
        recovering = self.combat.recovery is not None
        force_move = force_move or recovering or (empty and not holding)
        terminal = mission is not None and mission.status in TERMINAL
        fixed_mission = mission is not None and (not mission.route_attack or terminal)
        engage_range = self.combat.fire_range if self.tag == 'SPG' else self.combat.desired_range * 1.15
        policy = dict(force_move=force_move, holding=holding,
                    allow_withdrawal=not (fixed_mission or parked_artillery or parked_route or empty),
                    allow_firing_position=not (fixed_mission or parked_artillery or parked_route or empty or recovering),
                    allow_strategy=not empty and (mission is None or
                        (not mission.explicit and mission.status not in TERMINAL and not mission.wants_hold())),
                    capture_active=bool(mission is not None and mission.capturing),
                    combat_hold=combat_hold, engage_range=engage_range,
                    desired_range=self.combat.desired_range, fire_range=self.combat.fire_range,
                    recovery=recovering, parking=self.parking.snapshot(),
                    automatic_recovery=copy.deepcopy(self.automatic_recovery))
        self.policy_cache = sample, policy
        return dict(policy)

    def join(self, position, now):
        """Rank all points in 3D, then require an actual connected path.

        Resumable searches stay bounded; an overhead baked layer cannot prove
        an entry from a lower road by snapping the search's first point.
        """
        self.support.begin(position, now)
        if self.route is not None:
            return True
        if now < self.retry_at:
            return False
        if self.join_origin is not None and math.sqrt(sum(
                (a-b)**2 for a, b in zip(position, self.join_origin))) > 1.:
            self.candidates = self.search = self.pending = None
        if self.candidates is None:
            self.join_origin = tuple(position)
            candidates = []
            opening_origin = getattr(self, 'opening_origin', None)
            home = getattr(self, 'home_area', None)
            opening = (opening_origin is not None and home is not None and
                       distance(position, opening_origin) <= 3. and
                       math.hypot(position[0] - home['point'][0],
                                  position[2] - home['point'][1]) <= home['radius'])
            for route in getattr(self, 'selection', self.routes):
                points = route.get('waypoints', ())
                second_only = False
                if opening and len(points) > 1 and not route.get('player_start_at_first'):
                    first = points[0]
                    anchor = getattr(self, 'opening_anchor', None)
                    second_only = (math.hypot(first[0] - home['point'][0],
                                              first[1] - home['point'][1]) <= home['radius'] or
                                   anchor is not None and math.hypot(first[0] - anchor[0],
                                                                    first[1] - anchor[1]) <= 6.)
                for index, point in enumerate(route.get('waypoints', ())):
                    if second_only and index != 1 or route.get('player_start_at_first') and index:
                        continue
                    hint = route.get('player_goal_height')
                    height = self._height(point, position[1] if hint is None else hint,
                                          strict=hint is not None)
                    if height is None or (hint is not None and abs(height - hint) > 1.):
                        continue
                    goal = (float(point[0]), height, float(point[1]))
                    entry_distance = math.sqrt(sum((a-b)**2 for a,b in zip(position,goal)))
                    candidates.append((entry_distance, str(route['id']), index, route, goal))
            # Prefer an authored SPG sortie when its entry is actually
            # connected. Borrowed roads remain fallbacks in this same bounded
            # search, not a team-wide reservation or hidden allocation.
            self.candidates = sorted(candidates,
                key=lambda r: (r[3].get('player_sortie_priority', 0),) + r[:3])
        if self.search is None:
            if not self.candidates:
                self.receipt = dict(status='no_connected_entry')
                self.retry_at = now + 2.
                self.candidates = None
                return False
            self.pending = self.candidates.pop(0)
            goal = self.pending[4]
            status, resolved = self.support.inspect(goal, authored=False)
            segment = getattr(self.navigator.grid, 'segment_clear', None)
            if (status == 'connected' and callable(segment) and
                    abs(resolved[1] - goal[1]) <= 1. and segment(position, resolved)):
                self.route, self.index = self.pending[3], self.pending[2]
                self._remember_route_anchor(position)
                self.receipt = dict(status='joined_native_floor', route=self.pending[1],
                    index=self.pending[2], start=tuple(position), goal=resolved, path_length=2)
                return True
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
                     abs(path[-1][1] - goal[1]) <= 1. and
                     math.sqrt(sum((a-b)**2 for a,b in zip(path[-1],goal))) <= 13.)
        if not connected:
            self.receipt['status'] = 'rejected_layer_or_path'
            return False
        self.route, self.index = self.pending[3], self.pending[2]
        self._remember_route_anchor(position)
        self.receipt.update(status='joined', path_length=len(path))
        return True

    def _remember_route_anchor(self, position):
        if not self.route_history or distance(position, self.route_history[-1]) >= 3.:
            self.route_history.append(tuple(position))
            del self.route_history[:-12]

    def _cover_ground(self, x, z, hint):
        return self._height((x, z), hint, strict=True)

    def _cover_candidate(self, state, target, entity, clear, ray):
        search = getattr(self, 'cover_search', None)
        if search is None:
            return None
        owner = search.owner
        grid = self.navigator.grid
        self.support.begin(state['position'], state['now'])
        self.local_routes.publish(state, self.context)
        def scene():
            revision = getattr(getattr(owner, '_destructibles', None), '_spatial_revision_1513', None)
            return (getattr(grid, 'static_hull_revision', 0),
                    revision() if callable(revision) else None,
                    getattr(grid, '_native_proof_revision', 0))
        def segment(start, end):
            if distance(start, end) < .1:
                return True
            proof = getattr(grid, 'dry_segment_clear', None)
            obstacle = getattr(owner, '_navigation_obstacle', None)
            if not callable(proof) or not callable(obstacle):
                return None
            before = scene()
            allowed = proof(start, end, state['now'])
            if getattr(grid, '_proof_deferred', False) or before != scene():
                return None
            if not allowed:
                return False
            footprint = getattr(grid, 'hull_pose_clear', None)
            if callable(footprint) and not footprint(end, state['yaw'], state['half_length'], state['half_width']):
                return False
            if tuple(start) == tuple(state['position']):
                return clear(math.atan2(end[0]-start[0], end[2]-start[2]), distance(start, end))
            return not obstacle(start, end, state['half_width'])
        route_goal = None
        if self.route is not None and self.index is not None:
            points = self.route.get('waypoints', ())
            if self.index < len(points):
                point = points[self.index]
                route_goal = (point[0], state['position'][1], point[1])
        return search.update(state, self.context, target, entity, self._cover_ground,
            getattr(owner, '_water_depth', None), segment, ray, scene=scene, route_goal=route_goal)

    def withdrawal(self, state, target, entity, gun, clear, terrain_ray):
        """Own checked combat cover, clip retreat, and the existing health rule.

        Cover is useful to a healthy hull too. Empty magazines first seek hard
        cover; if none is reachable, only previously travelled route anchors
        may become a retreat objective. None of these policies replace a fixed
        command, a capture owner, or an active native firing group.
        """
        position, now = state['position'], state['now']
        context = getattr(self, 'context', {})
        mission = getattr(self, 'mission', None)
        search = getattr(self, 'cover_search', None)
        if (self.tag == 'SPG' or context.get('empty_ammo') or
                (mission is not None and (not mission.route_attack or mission.status in TERMINAL))):
            self.cover_move = None
            self.reload_route = None
            if search is not None:
                search.reset()
            return None
        maximum = getattr(entity.typeDescriptor, 'maxHealth', 0)
        critical = maximum > 0 and entity.health <= maximum * .25
        reloading = (getattr(gun, 'clip_size', 1) > 1 and
                     getattr(gun, 'clip', 0) <= 0 and getattr(gun, 'reload_time', 0.) > 0.)
        if context.get('stationary_fire_hold') and not (critical or reloading):
            # A usable firing position owns ordinary movement. Do not start
            # or resume healthy cover/peek cycles while the player is already
            # able to fire, including the bounded same-target proof refresh.
            self.cover_move = self.reload_route = None
            if search is not None:
                search.reset()
            return None
        combat = getattr(self, 'combat', None)
        cover_range = (getattr(combat, 'receipt', {}).get('phase', 'engage') == 'engage')
        normal_cover = (target is not None and
            (bool(context.get('fire_clear')) or self.cover_move is not None) and
            (self.cover_move is not None or cover_range) and
            distance(position, target_value(target, 'position')) <=
                getattr(combat, 'fire_range', 250.))
        if not reloading:
            self.reload_route = None
        if getattr(self, 'reload_route', None) is not None:
            return self._reload_route_order(state, clear)
        if not (critical or reloading or normal_cover):
            self.cover_move = None
            if search is not None:
                search.reset()
            return None
        if self.cover_move is not None and search is not None:
            binding = self.cover_move.get('binding')
            if (binding is not None and binding != search.identity(entity) or
                    target is not None and self.cover_move['target'] != target_value(target, 'id')):
                self.cover_move = None
                self.cover_retry_at = now
                search.reset()
        if self.cover_move is not None:
            cover = self.cover_move
            if reloading and cover['phase'] == 'peek':
                self._cover_phase(cover, 'return', now, position)
            goal = cover['peek'] if cover['phase'] == 'peek' else cover['goal']
            remaining = distance(position, goal)
            supported = legal_support(state, context,
                self._height((position[0], position[2]), position[1]))
            arrived = remaining <= 1.5 and supported
            if cover['phase'] in ('approach', 'return') and arrived:
                cover['phase'], cover['held_since'] = 'hold', now
            if cover['phase'] == 'hold':
                # No travel deadline applies once parked. A long clip reload
                # and its final two seconds retain the same cover owner.
                if not arrived:
                    self._cover_phase(cover, 'return', now, position)
                elif target is not None and search is not None and now >= cover.get('review_at', 0.):
                    exposure = search.current_exposure(state, context, target, entity, terrain_ray)
                    cover['review_at'], cover['review_exposure'] = now + .5, exposure
                    if exposure is not None and exposure > .5:
                        self.cover_move = None
                        self.cover_retry_at = now
                        search.reset()
                        return None
                if cover['phase'] == 'hold' and reloading:
                    return self._cover_order('cover_hold', cover['goal'])
                elif (cover['phase'] == 'hold' and target is not None and search is not None and
                      cover.get('review_exposure') is None):
                    return self._cover_order('cover_hold', cover['goal'])
                elif cover['phase'] == 'hold' and target is None:
                    if now - cover['held_since'] < 5.:
                        return self._cover_order('cover_hold', cover['goal'])
                    self.cover_move = None
                    return None
                elif cover['phase'] == 'hold' and now - cover['held_since'] >= 1. and context.get('gun_ready', True):
                    peek = cover['peek']
                    lane = (search.peek_clear(state, context, target, entity, peek,
                            self._cover_ground, terrain_ray) if search is not None else None)
                    if lane is True:
                        self._cover_phase(cover, 'peek', now, position)
                        cover['fire_seq'] = context.get('fire_seq')
                    elif now - cover['held_since'] >= 10.:
                        self.cover_move = None
                        self.cover_retry_at = now + 10.
                        return None
                    else:
                        return self._cover_order('cover_hold', cover['goal'])
                elif cover['phase'] == 'hold':
                    return self._cover_order('cover_hold', cover['goal'])
            if cover['phase'] == 'peek':
                goal = cover['peek']
                remaining = distance(position, goal)
                if remaining <= 1.5 and supported:
                    if cover.get('peek_until') is None:
                        cover['peek_until'] = now + 3.
                    sequence = context.get('fire_seq')
                    fired = sequence is not None and cover.get('fire_seq') is not None and sequence > cover['fire_seq']
                    if fired and getattr(gun, 'clip_size', 1) > 1 and getattr(gun, 'clip', 0) > 0:
                        cover['fire_seq'] = sequence
                        cover['peek_until'] = now + max(3., getattr(gun, 'reload_time', 0.) + 1.)
                    elif not context.get('burst_active') and (fired or now >= cover['peek_until']):
                        self._cover_phase(cover, 'return', now, position)
                        goal = cover['goal']
                    else:
                        return self._cover_order('cover_peek', goal)
            goal = cover['peek'] if cover['phase'] == 'peek' else cover['goal']
            remaining = distance(position, goal)
            if remaining < cover['best_distance'] - .5:
                cover['best_distance'], cover['progress_at'] = remaining, now
            if now - cover['progress_at'] >= 8.:
                self.cover_move = None
                self.cover_retry_at = now + 10.
                self.receipt = dict(status='cover_movement_timeout')
                return None
            return self._cover_motion(state, clear, goal, cover['phase'])
        if context.get('burst_active'):
            if search is not None:
                search.reset()
            return None
        if target is None or now < self.cover_retry_at:
            return None
        threat = tuple(target_value(target, 'position'))
        candidate = self._cover_candidate(state, target, entity, clear, terrain_ray)
        if candidate is not None:
            self.cover_retry_at = now + 10.
            self.cover_move = dict(candidate, phase='approach', progress_at=now,
                best_distance=distance(position, candidate['goal']), held_since=None, peek_until=None,
                reason='magazine_reload' if reloading else 'critical_custom' if critical else 'combat_cover')
            return self._cover_motion(state, clear, candidate['goal'], 'approach')
        if search is not None and search.receipt.get('status') == 'pending':
            return None  # Current mission/traffic remains the movement owner.
        self.cover_retry_at = now + 10.
        if reloading:
            for anchor in reversed(getattr(self, 'route_history', ())):
                reach = distance(position, anchor)
                if not 5. <= reach <= 80. or distance(anchor, threat) < distance(position, threat) + 2.:
                    continue
                height = self._height((anchor[0], anchor[2]), anchor[1], strict=True)
                if height is None or abs(height - anchor[1]) > 1.:
                    continue
                self.reload_route = dict(goal=(anchor[0], height, anchor[2]),
                    origin=tuple(position), progress_at=now, best_distance=reach,
                    reason='empty_magazine_known_route')
                return self._reload_route_order(state, clear)
        return None

    def ammo_withdrawal(self, state, clear, contacts, terrain_ray, reason='no_he'):
        """Reverse only, with a separate clock for loss of travel progress."""
        now, position, yaw = state['now'], state['position'], state['yaw']
        if getattr(self, 'ammo_retreat', None) is None or self.ammo_retreat['reason'] != reason:
            self.ammo_retreat = dict(reason=reason, progress_at=now, goal=None,
                best_distance=None, finished=False)
        retreat = self.ammo_retreat
        rear = yaw + math.pi
        goal = retreat['goal']
        if not retreat['finished'] and goal is None:
            choices = []
            for reach in (12., 8., 5., 3.):
                point = (position[0] + math.sin(rear)*reach, position[2] + math.cos(rear)*reach)
                height = self._height(point, position[1], strict=True)
                if height is None or not clear(rear, reach):
                    continue
                candidate = (point[0], height, point[1])
                visible = sum(bool(terrain_ray((point[0], height + 1., point[1]),
                    (row['position'][0], row['position'][1] + 1., row['position'][2])))
                    for row in contacts[:3])
                choices.append((visible, -reach, candidate))
            if choices:
                unused, reach, goal = min(choices)
                retreat.update(goal=goal, best_distance=-reach)
        if goal is not None and not retreat['finished']:
            remaining = distance(position, goal)
            if remaining < retreat['best_distance'] - .5:
                retreat.update(best_distance=remaining, progress_at=now)
            if remaining <= 1.5:
                retreat['finished'] = True
        if now - retreat['progress_at'] >= 8.:
            retreat['finished'] = True
        order = self._cover_order('ammo_retreat_hold' if retreat['finished'] else
                                  'ammo_retreat', goal)
        order.update(reverse_only=True, suppress_fire=reason == 'magazine_reload',
                     retreat=dict(retreat))
        if goal is not None and not retreat['finished']:
            heading = math.atan2(goal[0] - position[0], goal[2] - position[2])
            stopping = state.get('stopping_distance', 0.)
            if (abs(angle(heading-rear)) <= .25 and remaining > 1.5 + stopping and
                    clear(rear, min(remaining, max(3., stopping + 1.)))):
                order.update(throttle=-.65, brake=False, holding=False)
        return order

    def _reload_route_order(self, state, clear):
        retreat = self.reload_route
        goal, now = retreat['goal'], state['now']
        remaining = distance(state['position'], goal)
        if remaining < retreat['best_distance'] - .5:
            retreat['best_distance'], retreat['progress_at'] = remaining, now
        supported = legal_support(state, self.context, self._height(
            (state['position'][0], state['position'][2]), state['position'][1]))
        held = remaining <= 2. and supported
        if not held and now - retreat['progress_at'] >= 8.:
            self.reload_route = None
            self.cover_retry_at = now + 10.
            self.receipt = dict(status='reload_route_timeout')
            return None
        command = self._drive_goal(state, clear, goal,
            ('player_reload_route', tuple(goal)), hold=held,
            mode='reload_route_hold' if held else 'reload_withdraw', end_point=True)
        command['reload_retreat'] = dict(retreat)
        return command

    @staticmethod
    def _cover_order(mode, goal):
        command = dict(throttle=0., turn=0., brake=True, combat_mode=mode, local_target=goal,
                       holding=True, travel_intent=False)
        phase = dict(cover_hold='hold', cover_peek='peek', cover_return='return',
                     withdraw='approach').get(mode)
        if phase is not None:
            command['cover_motion'] = dict(phase=phase, direction=0., goal=goal)
        return command

    @staticmethod
    def _cover_phase(cover, phase, now, position):
        cover.update(phase=phase, progress_at=now, peek_until=None,
                     drive_direction=1. if phase == 'peek' else -1.,
                     best_distance=distance(position, cover['peek'] if phase == 'peek' else cover['goal']))

    def _cover_motion(self, state, clear, goal, phase):
        position = state['position']
        heading = math.atan2(goal[0] - position[0], goal[2] - position[2])
        mode = 'cover_peek' if phase == 'peek' else 'cover_return' if phase == 'return' else 'withdraw'
        cover = getattr(self, 'cover_move', None)
        if phase == 'peek':
            direction = 1.
        elif phase == 'return':
            direction = -1.
        else:
            # Select the approach gear once. A small bearing change must not
            # cross a per-frame reverse threshold and request a half turn.
            direction = cover.get('drive_direction') if cover is not None else None
            if direction is None:
                direction = -1. if math.cos(heading - state['yaw']) < 0. else 1.
                if cover is not None:
                    cover['drive_direction'] = direction
        driver = getattr(self, 'driver', None)
        if driver is None:
            return self._cover_order(mode, goal)
        key = ('player_cover', phase, tuple(goal))
        if getattr(self, 'navigator', None) is not None:
            command = self._drive_goal(state, clear, goal, key, mode=mode, end_point=True,
                arrival_radius=1.5, travel_direction=direction, motion_key=key)
        else:
            command = driver.drive(position, state['yaw'], state.get('speed', 0.),
                goal, state['now'], clear, terminal=True, arrival_radius=1.5,
                stopping_distance=state.get('stopping_distance'),
                decision_horizon=state.get('decision_horizon', .1),
                travel_direction=direction, motion_key=key)
            command.update(combat_mode=mode, local_target=goal, driving=driver.receipt,
                           holding=False, travel_intent=True)
        command['cover_motion'] = dict(phase=phase, direction=direction, goal=goal)
        return command

    def firing_position(self, state, target, clear, lane_from, muzzle):
        """Find a short clear approach that opens a direct firing lane."""
        position, now = state['position'], state['now']
        mission = getattr(self, 'mission', None)
        if (self.tag == 'SPG' or getattr(self, 'context', {}).get('empty_ammo') or
                (mission is not None and (not mission.route_attack or mission.status in TERMINAL))):
            self.firing_move = None
            return None
        identity, target_position = target_value(target, 'id'), target_value(target, 'position')
        if self.firing_move is not None:
            previous, goal, deadline = self.firing_move
            if previous == identity and now < deadline and math.hypot(
                    goal[0] - position[0], goal[2] - position[2]) > 2.:
                return goal
            self.firing_move = None
        if now < self.firing_retry_at:
            return None
        self.firing_retry_at = now + 8.
        dx = target_position[0] - position[0]
        dz = target_position[2] - position[2]
        fire_range = getattr(getattr(self, 'combat', None), 'fire_range', 150.)
        if not 3. < math.hypot(dx, dz) <= fire_range:
            return None
        bearing = math.atan2(dx, dz)
        for offset in (math.pi / 2., -math.pi / 2., math.pi / 3., -math.pi / 3.):
            heading = bearing + offset
            reach = 6.
            point = (position[0] + math.sin(heading) * reach,
                     position[2] + math.cos(heading) * reach)
            height = self._height(point, position[1])
            if height is None or abs(height - position[1]) > 1. or not clear(heading, reach):
                continue
            goal = (point[0], height, point[1])
            predicted = tuple(muzzle[i] + goal[i] - position[i] for i in range(3))
            if lane_from(target, predicted):
                self.firing_move = (identity, goal, now + 6.)
                return goal
        return None

    def drive_to_firing_position(self, state, clear, goal):
        return self.drive_combat_goal(state, clear, goal, 'firing_position',
                                      ('player_firing_position', tuple(goal)))

    def drive_to_contact(self, state, clear, target):
        """Retain the selected combat objective after a firing lane is lost."""
        point = tuple(target_value(target, 'position'))
        order = self.drive_combat_goal(state, clear, point, 'advance_contact',
                                      ('player_contact', target_value(target, 'id')))
        order['combat_contact'] = dict(target=target_value(target, 'id'),
                                      point=point, reason='firing_lane_unproved')
        return order

    def drive_combat_goal(self, state, clear, goal, mode='flank', key=None):
        """One actual combat endpoint, with the same path/support ownership."""
        return self._drive_goal(state, clear, goal,
            key or ('player_combat', mode, tuple(goal)), mode=mode, end_point=True)

    def report_drive_blockage(self, identity, order, position, heading, now, dt,
                              realised=False):
        target = (order or {}).get('local_target')
        if target is None or order.get('holding'):
            return
        report = (self.navigator.report_hard_contact if realised else
                  self.navigator.report_blocked_corridor)
        return report(identity, position, target, heading, now, dt)

    def _drive_goal(self, state, direction_clear, goal, key, hold=False, mode='route',
                    end_point=False, arrival_radius=2., travel_direction=1., motion_key=None):
        position, now = state['position'], state['now']
        self.support.begin(position, now)
        self.local_routes.publish(state, self.context)
        identity = int(state['id'])
        self.navigator.set_boundary_body(identity, position, state['yaw'],
                                         state['half_length'], state['half_width'])
        target = position if hold or goal is None else self.navigator.next_target(
            identity, position, goal, key, now)
        if target is None:
            target = position
        final_leg = getattr(self.navigator, 'target_is_terminal', None)
        final_leg = (bool(final_leg(identity)) if callable(final_leg) else
                     goal is not None and distance(target, goal) <= 1.5)
        if not hold and goal is not None:
            status, resolved = self.support.inspect(target)
            if status in ('connected', 'other_surface'):
                target = resolved
            elif status in ('disconnected', 'water'):
                fallback = getattr(self.navigator.grid, 'safe_local_target', None)
                penalty = getattr(self.navigator, 'player_segment_penalized', None)
                if callable(fallback) and callable(penalty):
                    target = fallback(position, goal, now, candidate_clear=lambda point:
                        not penalty(identity, position, point, now))
                else:
                    target = fallback(position, goal, now) if callable(fallback) else None
                target = position if target is None else target
            elif status == 'unknown' and abs(target[1] - position[1]) > 1.:
                # An incomplete local column cannot authorize an apparent
                # jump onto a baked overhead layer.
                target = position
            selected = target
            target = self.local_routes.adjust(state, self.context, goal, selected,
                key, direction_clear, allow_lane=mode in ('route', 'joining', 'return_base',
                    'base_capture', 'base_defence', 'attack', 'hold_position'))
            final_leg = final_leg and tuple(target) == tuple(selected) and distance(target, goal) <= 1.5
        else:
            end_narrow = getattr(self.navigator, 'end_narrow_passage', None)
            if callable(end_narrow):
                end_narrow(identity, now, 'tactical_hold')
        terminal = bool(final_leg and (end_point or mode in (
            'return_base', 'base_capture', 'base_defence', 'attack', 'hold_position',
            'artillery_deploy', 'parking_approach')))
        command = self.driver.drive(position, state['yaw'], state['speed'], target,
            now, direction_clear, hold=hold or goal is None,
            stopping_distance=state.get('stopping_distance'),
            decision_horizon=state.get('decision_horizon', .1), terminal=terminal,
            arrival_radius=arrival_radius, travel_direction=travel_direction, motion_key=motion_key,
            half_length=state['half_length'], turn_speed_limit=state.get('turn_speed_limit'))
        if self.driver.replan and distance(position, target) >= 2.:
            # Preserve the path cursor and progress history across local
            # recovery. Retire a cached corridor only on obstruction evidence.
            self.navigator.report_blocked_plan(position, target)
        command.update(route_id=self.route['id'] if self.route else None,
                       route_index=self.index, local_target=target, combat_mode=mode,
                       driving=self.driver.receipt, holding=bool(hold),
                       traffic_hold_protected=bool(hold and (
                           mode in ('parking_hold', 'mission_hold') or
                           (self.mission is not None and (self.mission.explicit or self.mission.capturing)))),
                       travel_intent=bool(not hold and goal is not None))
        if self.mission is not None:
            command['mission'] = self.mission_status()
        if self.artillery is not None:
            command['artillery'] = self.artillery.snapshot()
        command['combat'] = dict(self.combat.receipt)
        command['height_support'] = self.support.snapshot()
        command['local_navigation'] = self.local_routes.snapshot()
        if self.parking.receipt.get('phase') != 'idle' or self.parking.last_completion is not None:
            command['parking'] = self.parking.snapshot()
        if self.automatic_recovery is not None:
            command['automatic_recovery'] = copy.deepcopy(self.automatic_recovery)
        return command

    def _mission_order(self, state, clear):
        mission = self.mission
        held = mission.wants_hold()
        goal = None
        if held:
            goal = state['position']
        elif mission.goal is not None:
            goal_key = (mission.identity, mission.objective, mission.goal, mission.radius, mission.goal_height)
            if getattr(self, 'mission_goal_key', None) != goal_key:
                # Flag centres can be occupied or unsupported. Native path
                # evidence may choose another supported point inside the real
                # circle; that does not change the mission's arrival circle.
                x, z = mission.goal
                points = [(x, z)]
                if mission.radius > 3.:
                    reach = mission.radius * .65
                    points.extend((x + math.sin(i * math.pi / 4.) * reach,
                                   z + math.cos(i * math.pi / 4.) * reach) for i in range(8))
                routes = [dict(id='player_mission_goal_%d' % index, waypoints=[point],
                               player_goal_height=mission.goal_height)
                          for index, point in enumerate(points)]
                self._reset_travel(routes)
                self.mission_goal_key = goal_key
            if self.join(state['position'], state['now']):
                point = self.route['waypoints'][self.index]
                hint = mission.goal_height
                height = self._height(point, state['position'][1] if hint is None else hint,
                                      strict=hint is not None)
                if height is not None:
                    goal = (point[0], height, point[1])
        mode = ('base_capture' if mission.capturing else
                'base_defence' if mission.action == 'defend_base' else
                'mission_hold' if held else mission.action)
        self.receipt = dict(status='mission', mission=mission.snapshot(),
                            entry_route=self.route['id'] if self.route else None)
        return self._drive_goal(state, clear, goal,
            ('player_mission', mission.identity, mission.objective, mission.goal),
            hold=held, mode=mode)

    def _recovery_goal(self, state, clear):
        recovery = self.combat.recovery
        if recovery is None:
            return None
        if recovery.get('goal') is not None:
            return recovery['goal']
        position, point = state['position'], recovery['point']
        bearing = math.atan2(point[0] - position[0], point[2] - position[2])
        for offset in (0., math.pi / 2., -math.pi / 2.):
            heading = bearing + offset
            reach = min(6., max(3., distance(position, point) - 3.))
            point_xz = (position[0] + math.sin(heading) * reach,
                        position[2] + math.cos(heading) * reach)
            height = self._height(point_xz, position[1])
            if height is None or abs(height - position[1]) > 1. or not clear(heading, reach):
                continue
            recovery['goal'] = (point_xz[0], height, point_xz[1])
            return recovery['goal']
        self.receipt = dict(status='firing_recovery_blocked', until=recovery['until'])
        return None

    def _capture_handoff(self, state, reason='route_terminal_capture'):
        if self.automatic_defence or self.enemy_area is None:
            return False
        if self.mission is None:
            if not self._automatic_capture(state, reason):
                return False
        elif self.mission.route_attack:
            self.mission.enter_capture(self.enemy_area, state, reason)
        else:
            return False
        position = state['position']
        self.mission.observe(state, self.context, self._height((position[0], position[2]), position[1]))
        return True

    def _sortie_order(self, state, direction_clear, hold):
        position = state['position']
        supported = legal_support(state, self.context,
            self._height((position[0], position[2]), position[1]))
        finished_parking = False
        if self.sortie_progress.phase not in ('return', 'home'):
            parking = self.parking.update(self.route, self.index, state, self.context,
                                          self._height, self.support.snapshot)
            self.parking_order = parking
            if not parking['complete']:
                # Explicit authored waits own a separate, bounded approach
                # and an intentional wait duration (including wait forever).
                # The route stall clock must not retire that valid owner.
                self.sortie_progress.pause(state['now'])
                receipt = dict(phase='authored_parking', reason=parking['phase'],
                               route=self.route['id'], index=self.index)
                order = self._drive_goal(state, direction_clear, parking.get('goal'),
                    ('player_sortie_parking', self.route['id'], self.index),
                    hold=parking['holding'], mode='parking_hold' if parking['holding'] else 'parking_approach')
                self.sortie_receipt = receipt
                order['sortie_recovery'] = dict(receipt)
                self.receipt['sortie_recovery'] = dict(receipt)
                return order
            finished_parking = bool(not parking.get('skipped') and
                route_catalog.waiting_positions(self.route['waypoints'][self.index]))
        checked_index = self.index
        def reached(point, radius):
            height = self._height(point, position[1])
            return bool(supported and height is not None and
                        abs(height-position[1]) <= 1. and distance(position, point) <= radius)
        def can_advance(index, phase):
            return (phase == 'return' or index == checked_index or
                    not route_catalog.waiting_positions(self.route['waypoints'][index]))
        aiming = bool(hold and self.context.get('target') is not None and
                      self.context.get('fire_clear') and
                      (self.context.get('gun_ready') or self.context.get('aim_progress') or
                       self.context.get('burst_active')))
        receipt = self.sortie_progress.update(self.route, self.index, state,
            self.home_area, reached, aiming=aiming, sequence=self.context.get('fire_seq'),
            can_advance=can_advance,
            arrived_index=checked_index if finished_parking and supported else None)
        self.index = receipt['index']
        self.sortie_receipt = receipt
        inside = self.enemy_area is not None and reached(
            self.enemy_area['point'], self.enemy_area['radius'])
        if receipt.get('node_owner_pending'):
            # A future authored wait was reached during this tick's cursor
            # burst. Stop here; its own approach/wait owner runs next tick.
            self.sortie_progress.pause(state['now'])
            order = self._drive_goal(state, direction_clear, None,
                ('player_sortie_parking_pending', self.route['id'], self.index),
                hold=True, mode='parking_hold')
        elif (receipt.get('complete') or inside) and self._capture_handoff(state):
            order = self._mission_order(state, direction_clear)
        elif receipt.get('complete') and self.enemy_area is None:
            order = self._fail_sortie(state, direction_clear, receipt)
        elif receipt.get('replace'):
            self.sortie_rejections[route_geometry(self.route)] = dict(
                route=self.route['id'], reason=receipt['reason'])
            order = self._replace_sortie(state, direction_clear, receipt)
        else:
            point = receipt['goal']
            height = self._height(point, position[1]) if point is not None else None
            goal = (point[0], height, point[1]) if height is not None else None
            order = self._drive_goal(state, direction_clear, goal,
                ('player_sortie', self.route['id'], receipt['phase'], self.index),
                hold=hold, mode='engage' if hold else 'route',
                end_point=receipt['phase'] == 'home' or self.index == len(self.route['waypoints'])-1)
        self.sortie_receipt = dict(receipt)
        order['sortie_recovery'] = dict(receipt)
        self.receipt['sortie_recovery'] = dict(receipt)
        return order

    def _replace_sortie(self, state, direction_clear, receipt):
        routes = [copy.deepcopy(route) for route in self.sortie_routes
                  if route_geometry(route) not in self.sortie_rejections]
        receipt['failed_routes'] = sorted(row['route'] for row in self.sortie_rejections.values())
        if routes:
            for route in routes:
                route['player_start_at_first'] = receipt['reason'] == 'returned_home'
            self._reset_travel(routes)
            receipt['handoff'] = 'another_player_sortie_route'
            return self._drive_goal(state, direction_clear, None,
                ('player_sortie_reselect',), hold=True, mode='joining')
        if self._capture_handoff(state, 'sortie_routes_exhausted_native_capture'):
            receipt['handoff'] = 'native_capture_after_route_exhaustion'
            return self._mission_order(state, direction_clear)
        if self.enemy_area is not None:
            receipt.update(handoff='capture_retry_backoff', retry_at=self.capture_retry_at)
            return self._drive_goal(state, direction_clear, None,
                ('player_sortie_capture_retry', self.capture_retry_at), hold=True, mode='mission_hold')
        return self._fail_sortie(state, direction_clear, receipt)

    def _fail_sortie(self, state, direction_clear, receipt):
        # Missing objectives cannot establish a successful capture. Publish a
        # terminal failure and release this cursor until an explicit new task.
        receipt['handoff'] = self.sortie_terminal = 'sortie_failed_no_capture_objective'
        if self.mission is not None and self.mission.status not in TERMINAL:
            self.mission.finish('failed', self.sortie_terminal, state['now'])
        self.sortie_progress.reset()
        return self._drive_goal(state, direction_clear, None,
            ('player_sortie_failed',), hold=True, mode='mission_hold')

    def _route_order(self, state, direction_clear, hold=False):
        position, now = state['position'], state['now']
        if self.sortie_terminal is not None:
            return self._drive_goal(state, direction_clear, None,
                ('player_sortie_failed',), hold=True, mode='mission_hold')
        sortie_intent = bool(self.tag == 'SPG' and not self.automatic_defence and
            (self.artillery is not None and self.artillery.mode == 'sortie' or
             self.mission is not None and self.mission.route_attack))
        if sortie_intent and not self.selection:
            receipt = dict(phase='entry_failed', reason='no_sortie_routes')
            order = self._replace_sortie(state, direction_clear, receipt)
            self.sortie_receipt = dict(receipt)
            order['sortie_recovery'] = dict(receipt)
            self.receipt['sortie_recovery'] = dict(receipt)
            return order
        joined = self.join(position, now)
        goal = None
        key = ('player_joining', int(state['id']))
        if (joined and (sortie_intent or self.route.get('player_sortie')) and
                not self.automatic_defence):
            return self._sortie_order(state, direction_clear, hold)
        if (not joined and not self.automatic_defence and (sortie_intent or
                self.selection and all(route.get('player_sortie') for route in self.selection))):
            if self.sortie_entry_since is None:
                self.sortie_entry_since = now
            if now-self.sortie_entry_since >= PROGRESS_TIMEOUT:
                for route in self.selection:
                    self.sortie_rejections[route_geometry(route)] = dict(
                        route=route['id'], reason='sortie_entry_timeout')
                receipt = dict(phase='entry_failed', reason='sortie_entry_timeout')
                order = self._replace_sortie(state, direction_clear, receipt)
                self.sortie_receipt = dict(receipt)
                order['sortie_recovery'] = dict(receipt)
                self.receipt['sortie_recovery'] = dict(receipt)
                return order
        if joined:
            points = self.route['waypoints']
            parking = None
            finished_parking = False
            while True:
                parking = self.parking.update(self.route, self.index, state, self.context,
                                              self._height, self.support.snapshot)
                self.parking_order = parking
                finished_parking = bool(route_catalog.waiting_positions(points[self.index]) and
                    parking['complete'] and not parking.get('skipped'))
                if not parking['complete'] or self.index + 1 >= len(points):
                    break
                point = points[self.index]
                height = self._height(point, position[1])
                if not finished_parking and (height is None or abs(height-position[1]) > 1. or math.hypot(
                        point[0]-position[0], point[1]-position[2]) > 6.):
                    break
                self._remember_route_anchor(position)
                self.index += 1
            if parking is not None and not parking['complete']:
                order = self._drive_goal(state, direction_clear, parking.get('goal'),
                    ('player_parking', self.route['id'], self.index,
                     self.parking.receipt.get('slot')), hold=parking['holding'],
                    mode='parking_hold' if parking['holding'] else 'parking_approach')
                return order
            point = points[self.index]
            height = self._height(point, position[1])
            goal = (point[0], height, point[1]) if height is not None else None
            key = ('route', int(state['id']), self.route['id'], self.index)
            supported = legal_support(state, self.context,
                self._height((position[0], position[2]), position[1]))
            terminal = (self.index == len(points) - 1 and supported and (finished_parking or
                        (goal is not None and distance(position, goal) <= 6. and abs(position[1] - height) <= 1.)))
            inside_flag = (self.enemy_area is not None and supported and
                           distance(position, self.enemy_area['point']) <= self.enemy_area['radius'])
            combat_owner = bool(hold and (self.context.get('stationary_fire_hold') or
                self.context.get('retain_engagement_hold') or self.combat.receipt.get('hold')))
            if (not self.automatic_defence and not combat_owner and (terminal or inside_flag) and
                    self._capture_handoff(state)):
                return self._mission_order(state, direction_clear)
            if terminal and self.automatic_defence:
                hold = True
        combat_phase = self.combat.receipt.get('phase', 'engage')
        if combat_phase not in ('engage', 'support_hold'):
            combat_phase = 'engage'
        mode = 'base_defence' if self.automatic_defence else combat_phase if hold else 'route' if joined else 'joining'
        return self._drive_goal(state, direction_clear, goal, key, hold=hold or not joined, mode=mode,
                                end_point=bool(joined and self.index == len(self.route['waypoints']) - 1))

    def decide(self, state, direction_clear, hold=False):
        policy = self.movement_policy(state)
        if self.mission is not None and (not self.mission.route_attack or self.mission.status in TERMINAL):
            return self._mission_order(state, direction_clear)
        if self.artillery is not None and self.mission is None and not self.automatic_defence:
            mode = self.artillery.mode
            if mode == 'sortie' and not self.sortie_started:
                routes = copy.deepcopy(self.sortie_routes)
                for route in routes:
                    route['player_start_at_first'] = not self.artillery.sortie_home_failed
                    route['player_sortie'] = True
                self.sortie_rejections.clear()
                self.sortie_receipt = None
                self.sortie_terminal = None
                self._reset_travel(routes)
                self.sortie_started = True
            elif mode not in ('sortie', 'fallback'):
                goal = self.artillery.goal(state, self._height)
                return self._drive_goal(state, direction_clear, goal,
                    ('player_artillery', mode, self.artillery.current['id'] if self.artillery.current else None, goal),
                    hold=policy['holding'], mode='artillery_hold' if policy['holding'] else 'artillery_deploy')
        if policy['recovery']:
            goal = self._recovery_goal(state, direction_clear)
            return self._drive_goal(state, direction_clear, goal,
                ('player_combat_recovery', self.combat.recovery['target'], self.combat.recovery['until']),
                hold=goal is None, mode='combat_recovery')
        if policy['force_move']:
            hold = False
        elif self.context.get('target') is not None and not self.context.get('retain_engagement_hold'):
            hold = bool(hold and policy['combat_hold'])
        return self._route_order(state, direction_clear, hold=hold)
