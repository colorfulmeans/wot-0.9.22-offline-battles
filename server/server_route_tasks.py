"""Ordered travel tasks. Combat/fire selection remains in BotPlanner."""
import copy
import json
import math
import os
import zipfile

from gui.mods.offline_lan_0922 import bot_tactics, route_network, spg_positions
from server_route_recovery import MIN_ROUTE_AFFINITY


def point(value):
    if isinstance(value, dict):return dict((k, float(value.get(k, 0))) for k in ('x', 'y', 'z'))
    return dict(x=float(value[0]), y=0., z=float(value[1]))


def distance(a, b):
    return math.hypot(a['x']-b['x'], a['z']-b['z'])


class RouteTasksMixin:
    @staticmethod
    def _task_combat(order):
        mode=order.get('combat_mode')
        retreats=('low_health_retreat','low_health_defend','magazine_reload_retreat','magazine_reload_hold',
            'under_fire_withdraw','under_fire_hold','crossfire_withdraw','crossfire_hold','withdraw')
        return bool(mode in retreats or order.get('target_id') is not None and mode in (
            'engage','flank','advance_contact','take_cover','cover_hold','cover_peek','cover_return','support_hold'))

    def _task_init(self):
        self._travel_tasks = {}
        self._previous_combat = set()
        self._previous_player = {}
        self._travel_graph_cache = {}
        self._empty_task_reports = 0

    def _task_route(self, bot):
        return (self._route_assignments.get(bot['id']) or {}).get('route') or bot.get('route') or {}

    def _task_family(self,route,team):
        config=bot_tactics.route_config(self.tactics,self.tactics_map,route.get('id'),team)
        if config:
            return ('user_'+config.get('family',config['id'])) if not config.get('default') else config['source_id']
        return str(route.get('_route_family') or route.get('_editor_source') or route.get('id') or '')

    def _task_class_route(self,route,bot,catalog):
        family=self._task_family(route,bot['team']);tag=bot['profile'].get('class_tag')
        def applicable(candidate):
            config=bot_tactics.route_config(self.tactics,self.tactics_map,candidate.get('id'),bot['team'])
            return (self._task_family(candidate,bot['team'])==family and
                (not config or bot_tactics.matches(config,bot)) and
                (candidate.get('class_weights') or {}).get(tag,1.)>=MIN_ROUTE_AFFINITY)
        choices=[candidate for candidate in catalog.values() if applicable(candidate)]
        if choices:return min(choices,key=lambda r:(r['id']!=route['id'],r['id']))
        settings=bot_tactics.map_settings(self.tactics,self.tactics_map)
        rows=[r for r in settings.get('default_routes',()) if r['team']==bot['team'] and r['id']==family and not r.get('disabled') and r.get('class_tag','all') in (tag,'all')]
        if rows:
            from gui.mods.offline_lan_0922 import bot_tactics_runtime
            graph=self._task_graph()
            rows=[row for row in rows if graph is not None and bot_tactics_runtime.validate_route(graph,row) is None]
        if rows:
            row=min(rows,key=lambda r:r.get('class_tag','all')!=tag)
            return dict(id=bot_tactics.default_route_id(row),capacity=15,
                class_weights={tag:1.},waypoints=[point(p) for p in row['points']])
        return None

    def _task_graph(self):
        name = self.tactics_map
        if name not in self._travel_graph_cache:
            root = os.path.dirname(os.path.dirname(__file__))
            try:
                path = os.path.join(root, 'navgraphs', name+'.json')
                if os.path.isfile(path):
                    with open(path, encoding='utf8') as stream:raw = json.load(stream)
                else:
                    archive = os.path.join(root, '..', '..', 'client', '0.9.22.zip')
                    with zipfile.ZipFile(archive) as packed:
                        raw = json.loads(packed.read('mods/configs/offline_lan_0922/navgraphs/'+name+'.json'))
                self._travel_graph_cache[name] = spg_positions._Graph(raw, bot_tactics.MAPS[name]['bounds'])
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                self._travel_graph_cache[name] = None
        return self._travel_graph_cache[name]

    def _task_rejoin(self, bot):
        """Nearest reachable point by directed graph travel, only on handoff."""
        route = self._task_route(bot)
        points = route.get('waypoints') or []
        graph = self._task_graph()
        if not points or graph is None:return
        pose = point(bot['state'])
        index=route_network.reachable_join(graph,(pose['x'],pose['y'],pose['z']),points)
        if index is not None:
            self._cycle_drop_parking(bot)
            state=self._route_states.setdefault(bot['id'],{})
            state.update(route_id=route['id'],index=index,join_index=index,join_anchor=pose)
            state.pop('arrival_previous_pose',None)

    def _task_position(self, bot, now):
        task = self._travel_tasks[bot['id']]
        goal = task['points'][task['index']]
        return task['route_id'], task['source_index'], goal, point(bot['state']), True

    def _task_begin(self, bot, kind, base=None, target_route=None, now=0.):
        route = self._task_route(bot)
        source = route.get('waypoints') or []
        state = self._route_states.get(bot['id']) or {}
        index = max(0, min(int(state.get('index', 0))-1, len(source)-1))
        config = bot_tactics.route_config(self.tactics, self.tactics_map, route.get('id'), bot['team'],source)
        junction = -1
        if config and config.get('defense'):
            junction = route_network.nodes(config).index(config['defense']['junction'])
        end = junction if kind in ('defense', 'guard') and index >= junction >= 0 else 0
        # Unconfigured artillery legitimately has no ordinary route. It still
        # receives a base target below, using the existing local navigation.
        path = [point(source[i]) for i in range(index, end-1, -1)] if source else []
        if kind in ('defense', 'guard'):
            if end == junction and config:
                path += [point(p) for p in config['defense']['points'][1:]]
            path.append(point(base['point']))
        elif target_route:
            path.append(point(target_route['waypoints'][0]))
        if not path:path = [point(bot['state'])]
        if (not source and os.environ.get('WOT_OFFLINE_DIAGNOSTICS') == '1'
                and self._empty_task_reports < 64):
            self._empty_task_reports += 1
            try:
                print('[Offline LAN 0.9.22] ROUTE TASK EMPTY SOURCE '+json.dumps(dict(
                    round=self._round_id, map=self.tactics_map, bot=bot['id'], team=bot['team'],
                    class_tag=bot['profile'].get('class_tag'), kind=kind,
                    route_id=route.get('id'), source_count=0, points=path,
                    base_id=(base or {}).get('base_id'), policy='existing_target_navigation'),sort_keys=True))
            except Exception:
                pass  # Diagnostic output must not prevent a valid task.
        task = dict(kind=kind, route_id=str(route.get('id') or ''), route=route,
            source_index=index, points=path, index=0, since=now, best=float('inf'),
            target_route=target_route, until=now+180., base=copy.deepcopy(base), root_index=max(0,index-end), last_source=index,
            original_parking=copy.deepcopy(bot.get('spg_initial')))
        self._travel_tasks[bot['id']] = task
        if kind in ('defense', 'guard'):
            self._route_recoveries.pop(bot['id'], None)
            self._wreck_route_progress.pop(bot['id'], None)
        self._cycle_drop_parking(bot)
        return task

    def _task_publish(self, order, bot, task, now):
        base = task.get('base')
        inside = base and self._inside_base(bot,base)
        if inside:
            task['arrived'] = True
        if task['kind'] == 'pressure' and now >= task['until']:
            self._travel_tasks.pop(bot['id'], None)
            state=self._route_states.setdefault(bot['id'],{})
            state.update(route_id=task['route_id'],index=task['last_source'],join_index=task['last_source'],join_anchor=point(bot['state']))
            move=self._route(bot,now)[2]
            order.update(route_id=task['route_id'],route_index=state['index'],move_position=move,combat_mode='route',throttle_override=None)
            return
        if task.get('arrived'):
            order.update(move_position=point(bot['state']) if inside else point(base['point']), throttle_override=0. if inside else None,
                         combat_mode='engage' if inside and order.get('target_id') is not None else 'base_defense' if task['kind']=='defense' else 'team_guard')
            return
        goal = task['points'][task['index']]
        d = distance(point(bot['state']), goal)
        if d < task['best']-.5:
            task.update(best=d, since=now)
        previous_index=task['index']
        reached = d <= bot_tactics.ROUTE_ARRIVAL_RADIUS
        if reached:
            task['failures']=0
            if task['index']<=task['root_index']:task['last_source']=max(0,task['source_index']-task['index'])
            task['index'] += 1
            task.update(best=float('inf'), since=now)
        elif now-task['since'] >= 20.:
            # A return gate gets local motion recovery first, then one skip.
            # Defense owns the explicit direct-base fallback after two failures.
            failures = task.get('failures', 0)+1
            task.update(failures=failures, best=float('inf'), since=now)
            if task['kind'] in ('defense', 'guard') and failures >= 2:
                task['points'] = [point(base['point'])];task['index'] = 0
            elif task['index'] < len(task['points'])-1 and not (task['kind']=='pressure' and task['index']>=task['root_index']):task['index'] += 1
        if task['index'] >= len(task['points']):
            if task['kind'] == 'pressure':
                route = task['target_route']
                self._route_assignments[bot['id']] = dict(route=route, until=0., ordered_task=True)
                self._route_states[bot['id']] = dict(route_id=route['id'], index=0)
                self._route_history.setdefault(bot['id'], {}).pop(route['id'], None)
                self._travel_tasks.pop(bot['id'], None)
                move = self._route(bot, now)[2]
                order.update(route_id=route['id'], route_index=0, move_position=move, combat_mode='route', throttle_override=None)
                return
            task['index'] = len(task['points'])-1
        goal = task['points'][task['index']]
        if task['index']!=previous_index:task['best']=distance(point(bot['state']),goal)
        order.update(move_position=dict(goal), route_anchor=point(bot['state']), route_join=True,
            throttle_override=None, parking_phase=None, parking_slot=None,
            combat_mode='base_defense' if task['kind']=='defense' else
                        'team_back_to_base' if task['kind']=='guard' else 'route_transfer')
        if task['kind']=='defense':order['defense_base_id'] = str(base['base_id'])
        if task['kind']=='pressure':order.update(target_id=None, fire_allowed=False)
        order['travel_task'] = dict(kind=task['kind'], index=task['index'], route_id=task['route_id'])

    def _task_capture_handoff(self,order,bot,target):
        if (target is None or bot['id'] in self._travel_tasks or bot['id'] in self._route_recoveries or
                order.get('team_command') or order.get('target_id') is not None or
                bot['profile'].get('class_tag')=='SPG' or
                order.get('combat_mode') not in ('route','advance','base_screen')):return
        route=self._task_route(bot)
        authored=bot_tactics.route_config(self.tactics,self.tactics_map,route.get('id'),bot['team'],route.get('waypoints'))
        state=self._route_states.get(bot['id']) or {}
        if (authored is None or state.get('holding') or state.get('parking_phase') in ('approach','waiting','queue')):return
        if self._inside_base(bot,target) or state.get('index')==len(route.get('waypoints',()))-1:
            self._apply_base_capture_order(order,bot,target)

    def _task_apply(self, order, bot, now, defense_record=None, player_order=None, defense=None):
        if bot.get('empty_ammo'):return
        actor = bot['id']
        combat = self._task_combat(order)
        previous=self._previous_player.get(actor)
        command_id=(player_order or {}).get('command_id')
        if previous and previous['id']!=command_id:
            self._previous_player.pop(actor,None)
            if not combat and actor not in self._route_recoveries and actor not in self._travel_tasks:
                self._task_rejoin(bot)
                if not player_order:
                    identity,index,move,anchor,join=self._route(bot,now)
                    order.update(route_id=identity,route_index=index,move_position=move,route_anchor=anchor,route_join=join)
        if player_order:
            if not previous or previous['id']!=command_id:
                previous=dict(id=command_id,command=player_order.get('command'),goal=copy.deepcopy(order.get('move_position')))
                self._previous_player[actor]=previous
            if previous['command']=='TURNBACK':
                order['move_position']=previous['goal']
                if distance(point(bot['state']),point(previous['goal']))<=bot_tactics.ROUTE_ARRIVAL_RADIUS:
                    order['player_command_cancelled']=True
                    self._previous_player.pop(actor,None)
                    self._task_rejoin(bot)
                    identity,index,move,anchor,join=self._route(bot,now)
                    order.update(route_id=identity,route_index=index,move_position=move,route_anchor=anchor,route_join=join,combat_mode='route',throttle_override=None)
                    player_order=None
        task = self._travel_tasks.get(actor)
        released=False
        combat = self._task_combat(order)
        if defense_record is not None:
            if task is None or task['kind'] != 'defense':task = self._task_begin(bot, 'defense', defense_record, now=now)
        elif task and task['kind'] == 'defense':
            self._travel_tasks.pop(actor, None);self._task_rejoin(bot);task = None;released=True
        if task is None and player_order and player_order.get('command') == 'BACKTOBASE' and not combat:
            bases = self._defense_points((defense or {}).get('capture_bases'), bot['team'])
            if bases:
                base = min(bases, key=lambda b:distance(point(bot['state']), b['point']))
                task = self._task_begin(bot, 'guard', dict(base_id=base['id'], **base), now=now)
        if task and task['kind']=='guard' and (not player_order or player_order.get('command')!='BACKTOBASE' or combat):
            self._travel_tasks.pop(actor, None);self._task_rejoin(bot);task = None;released=True
        if combat and (not task or task['kind']!='defense'):
            self._previous_combat.add(actor)
            if task:task['paused_at'] = task.get('paused_at', now)
            return
        if actor in self._previous_combat:
            self._previous_combat.discard(actor)
            if not task and actor not in self._route_recoveries:
                self._task_rejoin(bot)
                if not player_order:
                    identity,index,move,anchor,join=self._route(bot,now)
                    order.update(route_id=identity,route_index=index,move_position=move,route_anchor=anchor,route_join=join)
        if released and not task and not player_order and order.get('combat_mode') in ('route','advance','base_screen'):
            identity,index,move,anchor,join=self._route(bot,now)
            order.update(route_id=identity,route_index=index,move_position=move,route_anchor=anchor,route_join=join)
        if task:
            if 'paused_at' in task:
                pause = now-task.pop('paused_at');task['since'] += pause
            self._task_publish(order, bot, task, now)
