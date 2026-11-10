# -*- coding: utf-8 -*-
"""One task state machine for foreground and worker vehicle bindings.

Bindings supply current actor facts and native input ownership. Automatic
capture, task priority, arrival, retry and terminal decisions live here.
Explicit controller tasks have their existing completion/holding lifecycle.
Server-admitted radio requests keep their server lease and enter the same
BotPlanner; they are not silently converted into a new controller task.
"""
from __future__ import division

import math

from .. import capture_orders
from .combat_control import _point, _distance
from .settling import HaltObservation


class MissionControl(object):
    """Per-actor task decisions, shared without a second physics owner."""

    def _init_mission_state(self):
        self._mission = None
        self._mission_sequence = 0
        self._mission_halt = HaltObservation()
        self._implicit_retry = None
        self._implicit_failures = 0

    def _start_mission_lifecycle(self, mission=None):
        if (mission is None and self._mission is not None and
                self._mission['status'] != 'running' and not self._mission.get('holding')):
            self._mission = None

    def _cancel_mission(self, reason):
        self._implicit_retry = None
        # A cancelled explicit task cannot donate its previous gun-only
        # override to a cached physical slice. A subsequent ordinary
        # decision may independently acquire a fresh live target.
        self._gun_handoff = None
        self._shared_aim_intention = None
        if self._mission is not None and self._mission['status'] == 'running':
            self._mission.update(status='cancelled', phase='cancelled', reason=reason)
        if self._mission is not None:
            self._mission['holding'] = False

    def _advance_mission_retry(self, now):
        if self._implicit_retry is None:
            return True
        if now < self._implicit_retry['at']:
            return True
        self._implicit_retry = None
        self._mission = None
        self.engine._decision_cache.pop(self.actor_id, None)
        return 'fire' not in self.features or self._acquire_mission_inputs()

    def _accept_task_order(self, order, now):
        order = self._mission_order(order, now)
        self._observe_mission(now)
        return self._accept_combat_order(order, now)

    def mission_team_orders(self, rows=()):
        """Project accepted actor tasks into the same strategic command input."""
        result = [dict(row) for row in rows or () if isinstance(row, dict)]
        mission = self._mission
        if mission is not None and mission['status'] == 'running':
            names = dict(attack='ATTACK', return_base='BACKTOBASE', hold_position='STOP')
            command = names.get(mission['action'])
            if command is not None and 'position' not in mission['payload']:
                result.append(dict(command_id=mission['id'], command=command,
                    team=self.state['team'], recipient_bot_ids=[self.actor_id],
                    issued_tick=int(mission['started'] * 1000.),
                    expires_tick=int(mission['deadline'] * 1000.)))
        return result

    def guard_mission_controls(self, command):
        """Apply task stopping ownership before either binding actuates motion."""
        if self._implicit_retry is not None:
            return dict(command, throttle=0., turn=0., brake=False,
                        fire_allowed=False, movement_intent=False)
        if not self._mission_brakes():
            return command
        result = dict(command, throttle=0., turn=0., brake=True,
                      fire_allowed=False, movement_intent=False)
        self.state['hull_aiming'] = False
        self.state.pop('_confirmed_facing', None)
        result.pop('confirmed_facing', None)
        return result

    def mission_preflight(self, kind, payload=None):
        from .commands import MISSIONS
        if kind not in MISSIONS:
            return 'unknown_mission'
        payload = payload or {}
        raw = payload.get('position')
        if raw is None and 'x' in payload and 'z' in payload:
            raw = (payload['x'], payload.get('y', 0.), payload['z'])
        if raw is not None:
            try:
                point = _point(raw)
                if any(math.isnan(value) or math.isinf(value) for value in point):
                    return 'invalid_destination'
            except (ValueError, TypeError, IndexError, KeyError, AttributeError):
                return 'invalid_destination'
            bounds = self._mission_bounds()
            if bounds is not None and (point[0] < bounds[0] or point[0] > bounds[2] or
                                       point[2] < bounds[1] or point[2] > bounds[3]):
                return 'destination_outside_arena'
        try:
            radius = float(payload.get('radius', 2.))
            timeout = float(payload.get('timeout', 600.))
            if any(math.isnan(value) or math.isinf(value) or value <= 0.
                   for value in (radius, timeout)):
                return 'invalid_mission_parameters'
        except (ValueError, TypeError, OverflowError):
            return 'invalid_mission_parameters'
        return None

    def set_mission(self, kind, payload=None):
        reason = self.mission_preflight(kind, payload)
        if reason is not None:
            return dict(status='rejected', reason=reason)
        if not self._mission_ready():
            return dict(status='failed', reason=self._mission_unavailable_reason())
        from .commands import MISSIONS
        if kind not in MISSIONS:
            return dict(status='rejected', reason='unknown_mission')
        payload = dict(payload or {})
        self._mission_sequence += 1
        self._strategic_due = 0.
        self._mission = dict(id=payload.get('command_id', 'player-mission-%d' % self._mission_sequence),
            action=kind, status='running', phase='travelling', reason=None, explicit=True,
            started=float(payload.get('requested_at', self.now)),
            deadline=float(payload.get('requested_at', self.now)) + float(payload.get('timeout', 600.)),
            payload=payload, progress=0., holding=False)
        self._mission_halt = HaltObservation()
        self._implicit_retry = None
        self._implicit_failures = 0
        if (kind in ('return_base', 'defend_base', 'capture_base') or
                'position' in payload or 'x' in payload and 'z' in payload):
            self.combat_stop.mission_handoff(self.now)
        self.combat_stop.reset()
        self._siege_aim_candidate = None
        self.siege_aim.reset()
        self.engine._clear_friendly_reposition(self.actor_id)
        self.state.pop('_gun_angle_adjustment', None)
        if kind == 'hold_position' and not ('position' in payload or 'x' in payload and 'z' in payload):
            self._mission['hold_point'] = tuple(self.state['position'])
        if 'position' in payload:
            self._mission['destination'] = _point(payload['position'])
        self._mission['radius'] = float(payload.get('radius', 2.))
        self.engine._decision_cache.pop(self.actor_id, None)
        return self.mission_status()

    def _mission_order(self, order, now):
        mission = self._mission
        if (mission is None and order.get('combat_mode') == 'base_capture' and
                not order.get('initial_target_hint') and self._implicit_retry is None):
            # A physical circle constraint may label an ordinary route as
            # base_capture while its enemy is only an evaluation hint. That
            # is not a new strategic capture task and must not create one.
            self._mission_sequence += 1
            mission = self._mission = dict(id='auto-capture-%d' % self._mission_sequence,
                action='capture_base', explicit=False, payload={}, status='running',
                phase='capture_travel', reason='copied_route_capture_handoff',
                progress=0., holding=False, started=now, deadline=now + 600.)
        if mission is None or mission['status'] != 'running' and not mission.get('holding'):
            return order
        payload, kind = mission['payload'], mission['action']
        empty = bool(self.gun.ammo) and not any(int(value) > 0 for value in self.gun.ammo)
        if empty and kind == 'attack':
            kind = mission['action'] = 'capture_base'
            mission.update(phase='capture_travel', reason='ammunition_exhausted', holding=False)
            mission.pop('destination', None)
        defense = self._defense_context()
        if kind == 'capture_base':
            target = self.planner._capture_target(defense, self.state['team'])
            if target is None:
                mission.update(status='failed', phase='failed', reason='capture_circle_unavailable')
                self._retire_implicit(now)
                return order
            mission.update(capture_area=target, destination=_point(target['point']))
            inside = capture_orders.inside(self.state, target) and not self.state.get('airborne', False)
            if inside:
                mission['capture_started'] = True
            # Preserve the full copied emergency-defence handoff for an
            # implicit approach until this player actually starts capturing.
            if (not mission['explicit'] and not mission.get('capture_started') and
                    order.get('combat_mode') == 'base_defense'):
                mission['phase'] = 'defending'
                return order
            result = dict(order)
            self.planner._apply_base_capture_order(result, self._planner_bot(), target)
            result['capture_area'] = target
            return capture_orders.constrain(result, self.state)
        destination = None
        if 'position' in payload:
            destination = _point(payload['position'])
        elif 'x' in payload and 'z' in payload:
            destination = (float(payload['x']), self.state['y'], float(payload['z']))
        if kind in ('return_base', 'defend_base'):
            bases = (defense.get('capture_bases') or {}).get(str(self.state['team'])) or ()
            if not bases:
                mission.update(status='failed', phase='failed', reason='home_circle_unavailable')
                return order
            destination = _point(bases[0])
            if kind == 'defend_base':
                mission['radius'] = float(bases[0]['radius'])
        if kind == 'hold_position':
            destination = destination or tuple(mission.setdefault('hold_point', self.state['position']))
        if destination is not None:
            result = dict(order, move_position=destination, face_position=destination,
                          throttle_override=None, combat_mode='team_' + kind,
                          parking_phase=None, route_join=False)
            mission['destination'] = destination
            distance = _distance(self.state['position'], destination)
            radius = mission.get('radius', 2.)
            if distance <= radius:
                result.update(move_position=destination, throttle_override=0.,
                              combat_mode='engage' if result.get('target_id') is not None else 'hold')
            mission.setdefault('initial_distance', distance)
            return result
        if kind == 'attack' and order.get('combat_mode') == 'base_capture':
            mission.update(action='capture_base', phase='capture_travel',
                           reason='copied_route_capture_handoff')
            return self._mission_order(order, now)
        return order

    def _planner_bot(self):
        return next((bot for bot in self.planner._alive_bots(
            self._mission_manifest(), list(self.engine.states.values()), self.planner.tactics)
            if bot['id'] == self.actor_id), None)

    def _mission_guard_order(self, order, now):
        """External mission ownership constrains goals, never drive physics."""
        mission = self._mission
        if mission is None:
            return order
        if mission['status'] in ('failed', 'cancelled'):
            return dict(order, move_position=tuple(self.state['position']),
                        throttle_override=0., fire_allowed=False, combat_mode='hold')
        if mission['action'] == 'capture_base' and mission.get('capture_area'):
            if not mission['explicit'] and mission['phase'] == 'defending' and not mission.get('capture_started'):
                return order
            return capture_orders.constrain(dict(order, capture_area=mission['capture_area']), self.state)
        if mission['action'] in ('attack', 'return_base', 'hold_position', 'defend_base') and mission.get('destination'):
            destination = mission['destination']
            inside = _distance(self.state['position'], destination) <= mission.get('radius', 2.)
            if not inside:
                return dict(order, move_position=destination, throttle_override=None,
                            combat_mode='team_' + mission['action'], parking_phase=None,
                            route_join=False)
            if mission['action'] != 'defend_base' or mission.get('holding'):
                return dict(order, move_position=destination, throttle_override=0.,
                            combat_mode='engage' if order.get('target_id') is not None else 'hold')
        return order

    def _mission_brakes(self):
        mission = self._mission
        return bool(mission is not None and
            (mission.get('status') in ('failed', 'cancelled') or
             mission.get('phase') == 'arriving'))


    def _observe_mission(self, now):
        mission = self._mission
        if mission is None or mission['status'] != 'running':
            return
        if now >= mission['deadline']:
            mission.update(status='failed', phase='failed', reason='deadline')
            self._retire_implicit(now)
            return
        result = self._mission_battle_result()
        if isinstance(result, dict):
            self.finish_battle(result, now)
            return
        destination = mission.get('destination')
        if mission['action'] == 'capture_base' and mission.get('capture_area'):
            inside = (capture_orders.inside(self.state, mission['capture_area']) and
                      not self.state.get('airborne', False))
            if mission['phase'] != 'defending' or mission.get('capture_started'):
                mission['phase'] = 'capturing' if inside else 'capture_travel'
            if inside:
                mission['capture_started'] = True
            native = (self._defense_context().get('states') or {}).get(str(3 - self.state['team'])) or {}
            mission['progress'] = max(0., min(1., float(native.get('points', 0.)) / 100.))
            mission['holding'] = inside
            return
        if destination is None:
            mission['phase'] = 'attacking' if self._last_order.get('target_id') is not None else 'travelling'
            return
        distance = _distance(self.state['position'], destination)
        initial = max(float(mission.get('initial_distance', distance)), mission.get('radius', 2.))
        mission['progress'] = max(0., min(1., 1. - distance / initial))
        if distance > mission.get('radius', 2.):
            self._mission_halt = HaltObservation()
            mission['phase'], mission['holding'] = 'travelling', False
            return
        mission['phase'] = 'arriving'
        if self._mission_halt.observe_motion(self._mission_motion(), now):
            if mission['action'] in ('return_base', 'hold_position', 'attack'):
                mission.update(status='completed', phase='holding',
                    reason='supported_stopped_arrival', holding=True, progress=1.)
            elif mission['action'] == 'defend_base':
                mission.update(phase='defending', holding=True, progress=1.)

    def _retire_implicit(self, now):
        mission = self._mission
        if mission is None or mission['explicit'] or mission['status'] not in ('failed', 'cancelled'):
            return False
        if self._implicit_retry is not None:
            return True
        self._implicit_failures += 1
        self._implicit_retry = dict(at=now + min(30., 5. * self._implicit_failures),
                                   failures=self._implicit_failures)
        self.engine._clear_friendly_reposition(self.actor_id)
        self._release_mission_inputs()
        self.engine._decision_cache.pop(self.actor_id, None)
        return True

    def mission_status(self):
        mission = self._mission
        if mission is None:
            return dict(id=None, action=None, status='idle', phase='idle', progress=0., holding=False)
        result = dict((key, mission[key]) for key in ('id', 'action', 'status', 'phase',
                    'reason', 'explicit', 'progress', 'holding', 'destination') if key in mission)
        if mission.get('destination') is not None:
            point = mission['destination']
            result['goal'] = (point[0], point[2])
        if self._implicit_retry is not None:
            result['retry_at'] = self._implicit_retry['at']
        return result

    def finish_battle(self, result, now):
        mission = self._mission
        if mission is not None and mission['status'] == 'running':
            captured = (mission['action'] == 'capture_base' and mission.get('capture_started') and
                        result.get('reason') == 'base captured' and
                        int(result.get('winner', 0)) == int(self.state['team']) and
                        int(result.get('base_team', 0)) == 3 - int(self.state['team']))
            mission.update(status='completed' if captured else 'cancelled',
                phase='captured' if captured else 'cancelled',
                reason='base_captured' if captured else 'battle_finished_before_objective',
                holding=False)
        return self.mission_status()
