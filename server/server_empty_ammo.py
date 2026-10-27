"""One-way per-round empty-ammunition navigation ownership."""
import copy

from gui.mods.offline_lan_0922 import empty_ammo, capture_orders


class EmptyAmmoMixin:
    def _empty_ammo_update(self, bots):
        live = set(bot['id'] for bot in bots)
        self._empty_ammo_bots.intersection_update(live)
        for bot in bots:
            actor = bot['id']
            if actor not in self._empty_ammo_bots and empty_ammo.active(bot):
                self._empty_ammo_bots.add(actor)
                task = self._travel_tasks.pop(actor, None)
                route = (task or {}).get('route') or self._cycle_route(bot)
                if route:
                    self._route_assignments[actor] = dict(route=copy.deepcopy(route), until=0., ordered_task=True)
                self._cycle_drop_parking(bot)
                for mapping in (self._route_states, self._route_history, self._route_recoveries,
                                self._wreck_route_progress, self._wreck_route_avoid,
                                self._recovery_route_visits, self._previous_player,
                                self._target_assignments, self._combat_states,
                                self._retreat_states, self._engage_anchors,
                                self._cover_states, self._firing_holds, self._artillery_anchors,
                                self._capture_arrivals):
                    mapping.pop(actor, None)
                self._previous_combat.discard(actor)
                for records in self._base_defense.values():
                    records.get('responders', {}).pop(actor, None)
                self._task_rejoin(bot)
            bot['empty_ammo'] = actor in self._empty_ammo_bots

    def _empty_ammo_order(self, order, bot, contacts, target, now):
        order['empty_ammo'] = True
        order['player_command_cancelled'] = True
        order['movement_priority'] = 'empty_ammo_capture'
        if contacts:
            contact = next((row for row in contacts if row.get('visible')), None)
            if contact is not None:
                self._set_target(order, bot, contact, bot['profile'], order['personality'], True)
        order.update(combat_mode='route', throttle_override=None,
                     face_position=dict(order['move_position']))
        route = self._task_route(bot)
        stage = self._route_states.get(bot['id']) or {}
        if target is not None:
            area = dict(id=target['id'], point=dict(target['point']), radius=target['radius'])
            if capture_orders.inside(bot['state'], area) and bot['state'].get('world_pose') and not bot['state'].get('airborne'):
                self._capture_arrivals[bot['id']] = area
                self._route_recoveries.pop(bot['id'], None)
                self._wreck_route_progress.pop(bot['id'], None)
            terminal = (not route.get('waypoints') or
                        stage.get('index') == len(route['waypoints'])-1 and bot['id'] not in self._route_recoveries)
            if terminal or bot['id'] in self._capture_arrivals or bot['profile'].get('class_tag') == 'SPG':
                order.update(combat_mode='base_capture', move_position=dict(target['point']),
                             route_join=False, face_position=dict(target['point']))
            if bot['id'] in self._capture_arrivals:
                order['capture_area'] = area
                order.update(capture_orders.constrain(order, bot['state']))
        order['tactical_evidence']['empty_ammo'] = dict(active=True, inventory=bot['state'].get('ammo_remaining'),
            policy='travel_before_aim', at=now)
        return order
