# -*- coding: utf-8 -*-
"""Native runtime observations for the one shared strategic implementation.

Published orders and local recovery use the same BotPlanner. Missing orders
never invoke a second director. The recovery planner owns its own round-local
state, consumes only observed contacts, and keeps the existing one-Hz cadence.
"""
from __future__ import division

import copy

STRATEGY_SECONDS = 1.0


def normalized_bases(raw):
    result = {}
    if not isinstance(raw, dict):
        return result
    for team in (1, 2):
        points = raw.get(str(team), raw.get(team, ())) or ()
        if isinstance(points, dict):
            points = [points]
        elif (isinstance(points, (tuple, list)) and len(points) >= 2 and
              not isinstance(points[0], (tuple, list, dict))):
            points = [points]
        values = []
        for index, raw_point in enumerate(points):
            if isinstance(raw_point, dict):
                point = raw_point.get('point', raw_point)
                values.append(dict(id=raw_point.get('id', '%d:%d' % (team, index)),
                    x=float(point['x']), y=float(point.get('y', 0.)),
                    z=float(point['z']), radius=float(raw_point.get('radius', 50.))))
            else:
                values.append(dict(id='%d:%d' % (team, index), x=float(raw_point[0]),
                    y=0., z=float(raw_point[-1]), radius=50.))
        result[str(team)] = values
    return result


class SharedOrderPlanning(object):
    def _reset_control_planning(self, round_id=None):
        # Runtime construction occurs after BotRuntime has finished importing;
        # no Python-2 import cycle through a partially defined physical class.
        from .strategy import BotPlanner
        self.control_planner = BotPlanner()
        self.control_planner.reset(round_id)
        self.control_manifest = ()
        self._control_context = {}
        self._control_observers = {}
        self._control_plan = None
        self._control_plan_due = 0.
        self._control_missions = None

    def _observe_control_context(self, message):
        for key in ('defense', 'capture_bases', 'bases', 'base_capture',
                    'base_captures', 'capture', 'rules', 'battle_result',
                    'team_commands', 'team_orders'):
            if key in message:
                self._control_context[key] = copy.deepcopy(message[key])
        self.control_planner.tactics = self._bot_tactics
        self.control_planner.tactics_map = self._navigation_map_name

    def control_defense_context(self):
        source = self._control_context
        result = copy.deepcopy(source.get('defense') or {})
        for key in ('capture_bases', 'bases', 'base_capture', 'base_captures', 'battle_result'):
            if key in source:
                result[key] = copy.deepcopy(source[key])
        result['arena_bounds'] = self._arena_bounds
        capture = ((source.get('rules') or {}).get('bases') or
                   source.get('capture') or source.get('base_capture'))
        if isinstance(capture, dict) and 'states' not in result:
            result['states'] = copy.deepcopy(capture)
        result['contributors_known'] = isinstance(result.get('contributors'), dict)
        graph = self.baked_graph or {}
        if not result.get('capture_bases'):
            points = graph.get('objective_bases') or ()
            radii = graph.get('objective_base_radii')
            result['capture_bases'] = dict((str(team), [dict(x=float(point[0]),
                z=float(point[1]), radius=float(radii[team - 1]) if radii is not None else 50.)])
                for team, point in enumerate(points, 1))
        if not result.get('bases'):
            result['bases'] = copy.deepcopy(result.get('capture_bases') or
                getattr(getattr(self.adapter, 'roster', None), 'bases', {}))
        for key in ('capture_bases', 'bases'):
            result[key] = normalized_bases(result.get(key))
        return result

    def _shared_control_order(self, source, contacts, players, now):
        """Replan an absent published order in the shared controller only.

        Keep each observer's visibility/radio rights separate. A seen target
        from one actor cannot make a different actor omniscient, and pending
        ray work never becomes a positive lane or negative armour proof.
        """
        from .. import bot_runtime
        self._control_observers[int(source['id'])] = (float(now), tuple(contacts))
        commands = list(self._control_context.get('team_commands') or
                        self._control_context.get('team_orders') or ())
        mission_signature = []
        for actor_id, control in sorted(self._actor_controls.items()):
            commands = control.mission_team_orders(commands)
            mission = getattr(control, '_mission', None) or {}
            mission_signature.append((actor_id, mission.get('id'), mission.get('status')))
        mission_signature = tuple(mission_signature)
        rebuild = (self._control_plan is None or now >= self._control_plan_due or
                   now < self._control_plan_due - STRATEGY_SECONDS or
                   mission_signature != self._control_missions)
        if not rebuild:
            return self._control_order_for(source)
        rows = {}
        for observer_id, sample in list(self._control_observers.items()):
            observed_at, observed = sample
            observer = self.states.get(observer_id)
            if (observer is None or not observer.get('alive', True) or
                    now - observed_at > STRATEGY_SECONDS + self._control_seconds):
                del self._control_observers[observer_id]
                continue
            for contact in observed:
                if not contact.get('visible') or not contact.get('alive', True):
                    continue
                kind = contact.get('kind', 'bot')
                kind = 'human' if kind == 'player' else kind
                identity = contact.get('network_id', contact.get('id'))
                key = (int(observer['team']), kind, identity)
                point = contact.get('position') or (contact['x'], contact['y'], contact['z'])
                row = rows.setdefault(key, dict(observing_team=key[0], target_kind=kind,
                    target_id=identity, target_team=contact['team'], visible=True,
                    fresh=bool(contact.get('fresh_visible', True)), time_left=STRATEGY_SECONDS,
                    x=point[0], y=point[1], z=point[2], health=contact.get('health', 1),
                    max_health=contact.get('max_health', 1), armor=contact.get('armor', 0.),
                    class_tag=contact.get('class_tag', 'unknown'), shootable_by_bot_ids=[],
                    pending_lane_by_bot_ids=[], radio_recipients=[]))
                row['radio_recipients'].append(dict(kind='bot', id=observer_id,
                    time_left=STRATEGY_SECONDS))
                # Identity is already normalized above. Read the existing
                # observation receipt, without a native ray or a second
                # per-pair geometry/key-building pass in the lane service.
                lane = self._shot_los_cache.get((observer_id, kind, int(identity)))
                fresh = lane is not None and 0. <= now - lane[0] <= (
                    bot_runtime.SHOT_LANE_REFRESH_SECONDS + self._control_seconds + 1.e-9)
                if fresh and lane[1]:
                    row['shootable_by_bot_ids'].append(observer_id)
                elif not fresh:
                    row['pending_lane_by_bot_ids'].append(observer_id)
        states = list(self.states.values())
        known = self.control_planner.known_targets(states, players)
        self.control_planner.report_contacts(list(rows.values()), known, now)
        self._control_plan = self.control_planner.build_orders(
            self.control_manifest, states, players, now,
            defense=self.control_defense_context(), team_orders=commands)
        self._control_plan_due = float(now) + STRATEGY_SECONDS
        self._control_missions = mission_signature
        return self._control_order_for(source)

    def _control_order_for(self, source):
        order = next((row for row in self._control_plan.get('orders') or ()
                      if int(row.get('id', 0)) == int(source['id'])), None)
        if order is None:
            # A missing manifest/actor is explicit pending, never a hidden
            # invocation of an earlier controller or an invented fire proof.
            point = (source['x'], source['y'], source['z'])
            return dict(id=source['id'], target_id=None, target_kind=None,
                move_position=point, face_position=point, aim_position=None,
                throttle_override=0., fire_allowed=False, combat_mode='hold',
                control_pending='shared_order_unavailable')
        return dict(order, control_order_source='shared_local_replan')
