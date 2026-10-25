"""Macro route recovery over immutable, ordered authored points.

The worker still owns path finding, collision proofs and local motor recovery.
This owner only chooses which existing macro point to attempt next.
"""
import math

from gui.mods.offline_lan_0922 import bot_tactics


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else 0.
    except (ValueError, TypeError, OverflowError):
        return 0.


def _point(value):
    return {key: _number(value.get(key)) for key in ('x', 'y', 'z')}


def _distance(a, b):
    return math.hypot(a['x']-b['x'], a['z']-b['z'])


ROUTE_ATTEMPT_SECONDS = 20.
MIN_ROUTE_AFFINITY = .20


class RouteRecoveryMixin:
    def _cycle_route(self, bot):
        return ((self._route_assignments.get(bot['id']) or {}).get('route')
                or bot.get('route') or {})

    def _cycle_drop_parking(self, bot):
        state = self._route_states.get(bot['id'], {})
        for key in ('parking_phase', 'parking_slot', 'holding', 'terminal_hold',
                    'terminal_crossing', 'completed_terminal'):
            state.pop(key, None)
        for key, claim in list(self._wait_claims.items()):
            if claim['bot_id'] == bot['id']:
                self._wait_claims.pop(key, None)

    def _cycle_leg(self, bot, recovery, phase, index, now):
        points = self._cycle_route(bot)['waypoints']
        recovery.update(phase=phase, index=max(0, min(index, len(points)-1)),
                        anchor=_point(bot['state']))
        recovery.pop('last_pose', None)
        recovery.pop('last_at', None)
        self._cycle_drop_parking(bot)
        state = self._route_states.setdefault(bot['id'], {})
        state.update(route_id=recovery['route_id'], index=recovery['index'],
                     join_index=recovery['index'], join_anchor=dict(recovery['anchor']))
        state.pop('blocked_skip_to', None)
        goal = _point(points[recovery['index']])
        self._wreck_route_progress[bot['id']] = dict(
            key=(recovery['route_id'], recovery['index']), goal=goal,
            since=now, origin=_point(bot['state']), best_distance=_distance(goal, _point(bot['state'])),
            physical_block=bool(bot['state'].get('route_wreck_blocked')))

    def _cycle_position(self, bot, now):
        recovery = self._route_recoveries[bot['id']]
        points = self._cycle_route(bot)['waypoints']
        index = recovery['index']
        state = self._route_states.setdefault(bot['id'], {})
        state.update(route_id=recovery['route_id'], index=index)
        state['progress_receipt'] = dict(at=now, route_id=recovery['route_id'],
            selected_index=index, outcome='recovery_'+recovery['phase'])
        return (recovery['route_id'], index, _point(points[index]),
                dict(recovery['anchor']), True)

    def _cycle_publish(self, order, bot, now):
        route_id, index, move, anchor, join = self._route(bot, now)
        order.update(route_id=route_id, route_index=index, combat_mode='route',
            move_position=move, face_position=dict(move), route_anchor=anchor,
            route_join=join, throttle_override=None, arrival_radius=None,
            parking_phase=None, parking_slot=None)
        order.pop('parking_heading', None)
        order.pop('move_area_bounds', None)
        recovery = self._route_recoveries.get(bot['id'])
        if 'route_attempt' in order:
            order['route_attempt'].update(phase=recovery['phase'] if recovery else 'complete',
                next_route=route_id, next_index=index, cycle=recovery['round'] if recovery else None)
        if bot['id'] not in self._route_recoveries:
            self._apply_authored_route_order(order, bot, move, now)

    def _cycle_finish(self, bot):
        recovery = self._route_recoveries.pop(bot['id'], None)
        if recovery is not None:
            self._route_states.setdefault(bot['id'], {}).update(
                route_id=recovery['route_id'], index=recovery['index'],
                join_index=recovery['index'], join_anchor=_point(bot['state']))
        self._wreck_route_progress.pop(bot['id'], None)
        self._cycle_drop_parking(bot)

    def _cycle_restart(self, bot, recovery, now):
        recovery['round'] += 1
        self._cycle_leg(bot, recovery, 'forward', recovery['failed'], now)

    def _cycle_change_route(self, order, bot, manifest, recovery, now):
        """Only enter another lane at its first point, never a nearby middle."""
        previous = recovery['route_id']
        catalog = self._route_catalog([row for row in manifest or () if _number(row.get('team')) == bot['team']])
        visits = self._recovery_route_visits.setdefault(bot['id'], {})
        visits[previous] = visits.get(previous, 0)+1
        tag = bot.get('profile', {}).get('class_tag')
        candidates = []
        for identity, route in sorted(catalog.items()):
            if identity == previous or not route.get('waypoints'):
                continue
            config = bot_tactics.route_config(self.tactics, self.tactics_map, identity, bot['team'])
            if config is not None and not bot_tactics.matches(config, bot):
                continue
            weights = route.get('class_weights') or {}
            affinity = _number(weights.get(tag, .5))
            if affinity < MIN_ROUTE_AFFINITY or tag in route.get('_editor_disabled_classes', ()):
                continue
            candidates.append((visits.get(identity, 0), -affinity, identity, route))
        if not candidates:
            self._cycle_restart(bot, recovery, now)
            return 'retry_no_alternative'
        route = min(candidates, key=lambda row: row[:3])[3]
        identity = str(route['id'])
        self._record_route_assignment(bot, now, previous, identity, 'recovery_at_start')
        self._route_assignment_receipts[bot['id']]['entry_selection'] = dict(
            sampled_at=now, origin=_point(bot['state']),
            policy='least_tried_then_affinity_at_first_point',
            candidates=[dict(route=row[2], outcome='eligible', visits=row[0],
                affinity=-row[1], entry_index=0,
                entry_distance=_distance(_point(bot['state']), _point(row[3]['waypoints'][0])))
                for row in candidates],
            selected_route=identity, selected_index=0,
            selected_point=_point(route['waypoints'][0]))
        self._route_assignments[bot['id']] = dict(route=route, until=0.)
        # Returning to the start completed the old traversal. A new traversal
        # owns fresh wait clocks and cannot restore an old failed route cursor.
        self._route_states[bot['id']] = dict(route_id=identity, index=0)
        self._route_history.setdefault(bot['id'], {}).pop(identity, None)
        recovery.update(route_id=identity, failed=min(1, len(route['waypoints'])-1))
        self._cycle_leg(bot, recovery, 'transfer', 0, now)
        if _distance(_point(bot['state']), _point(route['waypoints'][0])) <= bot_tactics.ROUTE_ARRIVAL_RADIUS:
            self._cycle_finish(bot)
        order.update(previous_route_id=previous, route_switch_reason='recovery_at_start')
        return 'switch_at_start'

    def _reroute_wreck_stall(self, order, bot, manifest, now):
        """Forward C, try D, return via B/A, retry C or start another lane."""
        bot_id = bot['id']
        recovery = self._route_recoveries.get(bot_id)
        route = self._cycle_route(bot)
        points = route.get('waypoints') or []
        progress = self._wreck_route_progress.get(bot_id)
        travel_modes = ('route', 'advance', 'parking_approach', 'base_capture')
        # Distant-contact advance still travels the authored leg. Only actual
        # combat ownership pauses it; retaining/changing aim is not a hold.
        aiming_owns_motion = (order.get('target_id') is not None and
                              bot_tactics.route_motion_identity(order) is None)
        paused = (aiming_owns_motion or order.get('team_command')
                  or order.get('defense_base_id') or order.get('combat_mode') not in travel_modes
                  or not self._route_donor_eligible(bot)
                  or not bot['state'].get('world_pose') or bot['state'].get('airborne')
                  or order.get('throttle_override') is not None and _number(order['throttle_override']) <= 0.)
        if paused:
            if progress is not None:
                progress.setdefault('paused_at', now)
                progress.setdefault('pause_pose', _point(bot['state']))
                order['route_attempt'] = dict(route_id=progress['key'][0],
                    route_index=progress['key'][1], action='pause_'+str(order.get('combat_mode')),
                    elapsed=round(progress['paused_at']-progress['since'], 3),
                    phase=recovery['phase'] if recovery else None)
            return
        # A singleton automatic objective has no ordered return corridor. Keep
        # its existing precise arrival and fallback owner separate from lanes.
        if len(points) <= 1 and recovery is None:
            return self._reroute_automatic_goal(order, bot, manifest, now)
        if not points:
            return
        pose = _point(bot['state'])
        if recovery is not None:
            index = recovery['index']
            goal = _point(points[index])
        else:
            index = max(0, min(int(order.get('route_index') or 0), len(points)-1))
            goal = _point(order.get('move_position') or points[index])
        key = (str(route.get('id') or order.get('route_id') or ''), index)
        distance = _distance(goal, pose)
        physical = bool(bot['state'].get('route_wreck_blocked'))
        trace = dict(route_id=key[0], route_index=index, distance=round(distance, 3),
            arrival=bot_tactics.ROUTE_ARRIVAL_RADIUS, physical_block=physical,
            action='attempt', elapsed=0., phase=recovery['phase'] if recovery else 'normal')
        order['route_attempt'] = trace
        if progress is not None and progress['key'] != key:
            progress = None
        if progress is not None:
            paused_at = progress.pop('paused_at', None)
            if paused_at is not None:
                duration = max(0., now-paused_at)
                progress['since'] += duration
                progress.pop('pause_pose', None)
                progress['origin'] = dict(pose)
                progress['best_distance'] = min(progress.get('best_distance', distance), distance)
                # Combat may have moved the hull. Rejoin the unchanged pending
                # gate from its realised pose, with no stale start/arrival sweep.
                if recovery is not None:
                    recovery['anchor'] = dict(pose)
                    self._route_states.setdefault(bot_id, {}).update(
                        join_index=recovery['index'], join_anchor=dict(pose))
                    recovery.pop('last_pose', None)
                    recovery.pop('last_at', None)
                trace['resumed_after_pause'] = duration
        previous = (recovery.get('last_pose') if recovery and
                    0. < now-recovery.get('last_at',now-3.) <= 2. else None)
        if recovery is not None:
            recovery['last_pose'] = (pose['x'], pose['z'])
            recovery['last_at'] = now
        arrived = bot_tactics.route_disk_reached((pose['x'], pose['z']),
            (goal['x'], goal['z']), None, previous)
        if arrived and order.get('combat_mode') != 'parking_approach':
            if recovery is None:
                self._wreck_route_progress.pop(bot_id, None)
                trace['action'] = 'arrived_or_unowned'
                return
            phase = recovery['phase']
            if phase in ('forward', 'skip', 'transfer'):
                self._cycle_finish(bot)
                self._cycle_publish(order, bot, now)
                trace['action'] = 'recovery_complete'
                return
            if index == 0:
                trace['action'] = self._cycle_change_route(order, bot, manifest, recovery, now)
            else:
                self._cycle_leg(bot, recovery, 'return', index-1, now)
                trace['action'] = 'return_previous_point'
            self._cycle_publish(order, bot, now)
            return
        if progress is None:
            progress = dict(key=key, goal=goal, since=now, origin=dict(pose),
                best_distance=distance, physical_block=physical)
            self._wreck_route_progress[bot_id] = progress
        if (recovery is None and physical and order.get('combat_mode') in ('route', 'advance')):
            recovery = dict(route_id=key[0], phase='forward', index=index,
                failed=index, anchor=_point(order.get('route_anchor') or pose), round=0)
            self._route_recoveries[bot_id] = recovery
            self._cycle_drop_parking(bot)
        elapsed = max(0., now-progress['since'])
        progress_goal = progress['goal']
        progress_distance = _distance(progress_goal, pose)
        best = progress.setdefault('best_distance', _distance(progress_goal, progress['origin']))
        improvement = best-progress_distance
        trace.update(attempt_started_at=progress['since'], elapsed=round(elapsed, 3),
            improvement=round(improvement, 3), best_distance=round(best, 3),
            progress_goal=dict(progress_goal), progress_distance=round(progress_distance, 3))
        if physical and improvement >= .5:
            progress.update(since=now, origin=dict(pose), best_distance=progress_distance)
            trace.update(action='physical_progress_renewed', elapsed=0., attempt_started_at=now)
        elif not physical and (_distance(pose, progress['origin']) >= 6. and
                              _distance(goal, progress['origin'])-distance >= 4.):
            progress.update(since=now, origin=dict(pose), goal=goal,
                            best_distance=min(best, distance))
            trace.update(action='travel_progress_renewed', elapsed=0., attempt_started_at=now)
        elif elapsed >= ROUTE_ATTEMPT_SECONDS:
            if order.get('combat_mode') == 'parking_approach' and recovery is None:
                # Preserve the established small-place refusal before changing
                # a macro point. The legacy helper performs no lane switch here.
                return self._reroute_automatic_goal(order, bot, manifest, now)
            if recovery is None:
                recovery = dict(route_id=key[0], phase='forward', index=index,
                    failed=index, anchor=dict(pose), round=0)
                self._route_recoveries[bot_id] = recovery
            phase = recovery['phase']
            if phase == 'forward' and index+1 < len(points):
                self._cycle_leg(bot, recovery, 'skip', index+1, now)
                order.update(route_point_skip_reason='blocked_timeout', previous_route_index=index)
                trace['action'] = 'skip_gate'
            elif phase in ('forward', 'skip'):
                self._cycle_leg(bot, recovery, 'return', max(0, recovery['failed']-1), now)
                trace['action'] = 'return_to_anchor'
            elif phase == 'transfer':
                recovery['round'] += 1
                self._cycle_leg(bot, recovery, 'transfer', 0, now)
                trace['action'] = 'retry_transfer'
            elif phase == 'return' and index > 0:
                self._cycle_leg(bot, recovery, 'return_skip', index-1, now)
                trace['action'] = 'skip_return_point'
            else:
                self._cycle_restart(bot, recovery, now)
                trace['action'] = 'retry_cycle'
        if bot_id in self._route_recoveries:
            recovery = self._route_recoveries[bot_id]
            trace.update(phase=recovery['phase'], cycle=recovery['round'],
                         next_route=recovery['route_id'], next_index=recovery['index'])
            self._cycle_publish(order, bot, now)
