"""Plain-data adapter between a battle runtime and the pure bot planner.

The adapter deliberately does not inspect BigWorld entities.  A caller sends
JSON-like dictionaries and receives a JSON-safe order: a route/goal, a local
movement command, and optional fire intent.  The caller remains responsible
for visibility, collision probes, and applying commands to any client entity.
"""

from gui.mods.offline_lan_0922.worker_diagnostics import observed
from gui.mods.offline_lan_0922 import tank_collision

import math

from gui.mods.offline_lan_0922.ai.driver import (
    LocalDriver, WAYPOINT_ARRIVAL_RADIUS, recovery_probe_distance,
)
from gui.mods.offline_lan_0922.ai.planner import BattleDirector


def _position(value, fallback=(0.0, 0.0, 0.0)):
    if isinstance(value, dict):
        value = (value.get('x'), value.get('y'), value.get('z'))
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError, IndexError):
        return fallback


def _contact(value):
    if not isinstance(value, dict):
        return None
    result = dict(value)
    result['position'] = _position(value.get('position'))
    result['visible'] = bool(value.get('visible', False))
    return result


class BotAdapter(object):
    """Owns pure planner/driver state for one map and battle seed."""

    def __init__(self, map_name, battle_seed, bases=None, bounds=None,
                 navigation_target=None, baked_routes=None):
        self.director = BattleDirector(map_name, battle_seed, bases, bounds,
                                      baked_routes=baked_routes)
        self.driver = LocalDriver()
        self.navigation_target = navigation_target
        self._contact_peers = {}

    def register(self, bot_id, team, descriptor, display_name='Bot'):
        return self.director.register(bot_id, team, descriptor, display_name)

    def forget(self, bot_id):
        self.driver.forget(bot_id)
        self.director.agents.pop(int(bot_id), None)
        self._contact_peers.pop(int(bot_id), None)

    def _enemy_contact(self, bot_id, state, position):
        """Return geometry for a real hostile hull contact across small gaps."""
        team = state.get('team')
        if team is None:
            team = self.director.agents.get(bot_id, {}).get('team')
        if team is None:
            return None
        shape = state.get('collision_shape') or (
            state.get('half_width', 1.7), state.get('half_length', 3.5),
            tank_collision.DEFAULT_SHAPE[2], tank_collision.DEFAULT_SHAPE[3])
        previous = self._contact_peers.get(bot_id)
        for peer in state.get('neighbours', ()):
            if peer.get('team', team) == team or not peer.get('alive', True):
                continue
            where = _position(peer.get('position', peer))
            other_shape = tank_collision._tank_shape(peer)
            if not tank_collision.vertical_overlap(position[1], shape, where[1], other_shape):
                continue
            overlap = tank_collision._obb_overlap(
                position[0], position[2], state.get('yaw', 0.0), shape,
                where[0], where[2], peer.get('yaw', 0.0), other_shape)
            margin = (tank_collision.CONTACT_BROADPHASE_PADDING
                      if peer.get('id') == previous else tank_collision.POSITION_SLOP)
            if overlap[2] >= -margin:
                self._contact_peers[bot_id] = peer.get('id')
                return {
                    'peer_id': peer.get('id'),
                    'normal': overlap[:2],
                    'peer_position': where,
                }
        self._contact_peers.pop(bot_id, None)
        return None

    def _contact_escape_plan(self, state, position, direction_clear,
                             contact):
        """Select one separating longitudinal exit and prove its full sweep.

        A side contact does not imply that both longitudinal directions are
        usable.  In particular, driving towards the near end of an offset
        hull makes the final traffic guard brake, leaving a tactical hold with
        ``contact_escape`` intent but zero throttle.  Only choose a direct
        escape when SAT geometry identifies a separating end, and retain the
        same terrain and complete-vehicle-sweep checks as ordinary recovery.
        An exactly centred side contact has no preferred end and deliberately
        falls back to LocalDriver's bounded recovery state machine.
        """
        if not isinstance(contact, dict):
            return None
        yaw = float(state.get('yaw', 0.0))
        forward = math.sin(yaw), math.cos(yaw)
        normal = contact.get('normal') or (0.0, 0.0)
        peer_position = contact.get('peer_position')
        normal_alignment = (forward[0] * float(normal[0]) +
                            forward[1] * float(normal[1]))
        longitudinal_offset = 0.0
        if peer_position is not None:
            longitudinal_offset = (
                forward[0] * (float(position[0]) - float(peer_position[0])) +
                forward[1] * (float(position[2]) - float(peer_position[2])))
        epsilon = tank_collision.POSITION_SLOP
        if abs(normal_alignment) > epsilon:
            preferred = 1.0 if normal_alignment > 0.0 else -1.0
        elif abs(longitudinal_offset) > epsilon:
            # The contact is on a side face. Leave through the nearer
            # longitudinal end instead of compressing the overlap along it.
            preferred = 1.0 if longitudinal_offset > 0.0 else -1.0
        else:
            return None
        shape = state.get('collision_shape') or (
            state.get('half_width', 1.7), state.get('half_length', 3.5),
            tank_collision.DEFAULT_SHAPE[2], tank_collision.DEFAULT_SHAPE[3])
        half_width = float(state.get('half_width', shape[0]))
        half_length = float(state.get('half_length', shape[1]))
        neighbours = state.get('neighbours', ())
        for sign in (preferred, -preferred):
            heading = yaw + (math.pi if sign < 0.0 else 0.0)
            if not self.driver._clear(
                    direction_clear, heading,
                    recovery_probe_distance(half_length)):
                continue
            # ``_reverse_blocked_by_vehicle`` owns the exact longitudinal OBB
            # sweep. Supplying the opposite hull heading makes its reverse
            # axis equal this candidate's direction of travel.
            blocker = self.driver._reverse_blocked_by_vehicle(
                position, heading + math.pi, neighbours,
                half_length, half_width)
            if blocker is not None:
                continue
            distance = 2.0 * half_length + WAYPOINT_ARRIVAL_RADIUS
            target = (
                position[0] + math.sin(heading) * distance,
                position[1],
                position[2] + math.cos(heading) * distance)
            return target, {
                'throttle': 0.72 * sign,
                'brake': False,
                'turn': 0.0,
                'target_yaw': yaw,
                'recovery_mode': 'contact_escape',
            }
        return None

    def decide(self, state, direction_clear):
        """Return a deterministic, serializable command for one bot.

        ``state`` needs ``id``, ``slot``, ``position``, ``yaw``, ``speed``,
        ``dt``, ``now`` and optionally ``health``, ``max_health``, ``contacts``
        and ``neighbours``.  ``direction_clear(yaw)`` is the sole runtime probe.
        """
        state = state if isinstance(state, dict) else {}
        bot_id = int(state.get('id', 0))
        position = _position(state.get('position'))
        speed = float(state['speed'])
        contacts = [_contact(item) for item in state.get('contacts', ())]
        contacts = [item for item in contacts if item is not None]
        team = self.director.agents[bot_id]['team']
        now = float(state.get('now', 0.0))
        for contact in contacts:
            self.director.update_contact(
                team, contact.get('id', 0), contact.get('team', 0),
                contact['position'], contact.get('health', 1.0),
                contact.get('max_health', 1.0), contact.get('class_tag'),
                contact['visible'], now, contact.get('armor', 0.0),
                contact.get('speed', 0.0))
        strategic = self.director.order_for(
            bot_id, position, float(state.get('yaw', 0.0)),
            speed,
            state.get('health', 1.0), state.get('max_health', 1.0), now)
        return self._drive_order(
            bot_id, state, position, strategic, direction_clear)

    def decide_with_order(self, state, strategic, direction_clear):
        """Apply a server macro order through the same local terrain driver."""
        state = state if isinstance(state, dict) else {}
        strategic = strategic if isinstance(strategic, dict) else {}
        bot_id = int(state.get('id', 0))
        position = _position(state.get('position'))
        return self._drive_order(
            bot_id, state, position, strategic, direction_clear)

    @observed('driver.order')
    def _drive_order(self, bot_id, state, position, strategic,
                     direction_clear):
        state.pop('navigation_probe_distance', None)
        aim_position = strategic.get('aim_position')
        move_position = strategic.get('move_position')
        face_position = strategic.get('face_position')
        if aim_position is not None:
            aim_position = _position(aim_position, position)
        if move_position is not None:
            move_position = _position(move_position, position)
        if face_position is not None:
            face_position = _position(face_position, position)
        aim_position, move_position, face_position, unused_stop = (
            self.driver.resolve_order_positions(
                position, aim_position, move_position, face_position))
        target = move_position
        contact_escape = self._enemy_contact(bot_id, state, position)
        contact_plan = None
        if contact_escape:
            # A tactical firing hold is not a decision to surrender when an
            # enemy pins the hull. Keep the target/fire order while selecting
            # a geometrically separating, fully checked longitudinal exit.
            yaw = float(state.get('yaw', 0.0))
            distance = 2.0*float(state.get('half_length', 3.5))+WAYPOINT_ARRIVAL_RADIUS
            target = (position[0]+math.sin(yaw)*distance, position[1],
                      position[2]+math.cos(yaw)*distance)
            contact_plan = self._contact_escape_plan(
                state, position, direction_clear, contact_escape)
            if contact_plan is not None:
                target = contact_plan[0]
        elif callable(self.navigation_target):
            target = _position(self.navigation_target(
                bot_id, position, target, strategic, state), target)
        stop_at_target = bool(state.get(
            'navigation_stop_at_target',
            strategic.get('combat_mode') not in ('route', 'advance')))
        throttle_override = strategic.get('throttle_override')
        if contact_escape:
            throttle_override = None
            stop_at_target = False
        movement_intent = not (
            throttle_override is not None and
            float(throttle_override) <= 0.0)
        requested_dx = float(move_position[0]) - float(position[0])
        requested_dz = float(move_position[2]) - float(position[2])
        target_dx = float(target[0]) - float(position[0])
        target_dz = float(target[2]) - float(position[2])
        if movement_intent and not contact_escape:
            try:
                leading = float(state.get('half_length', 3.5))
                horizon = float(state.get('decision_horizon', 0.0))
                speed = float(state.get('speed', 0.0))
                finite = all(not math.isnan(value) and not math.isinf(value)
                             for value in (leading, horizon, speed))
                reach = abs(speed) * max(0.0, horizon)
                remaining = math.hypot(target_dx, target_dz) - WAYPOINT_ARRIVAL_RADIUS
                distance = leading + max(remaining, reach)
                if (finite and remaining > 0.0 and leading > 0.0 and
                        not math.isnan(distance) and not math.isinf(distance)):
                    # The runtime applies this only to ordinary driver probes,
                    # after checking remembered vehicle blockers. Explicit short
                    # recovery probes retain their own range and traffic rules.
                    # Include the leading hull and this decision's real travel.
                    state['navigation_probe_distance'] = distance
            except (TypeError, ValueError, OverflowError):
                pass
        navigation_wait = bool(
            movement_intent and
            requested_dx * requested_dx + requested_dz * requested_dz > 225.0 and
            target_dx * target_dx + target_dz * target_dz <=
            WAYPOINT_ARRIVAL_RADIUS * WAYPOINT_ARRIVAL_RADIUS)
        if contact_plan is not None:
            local = contact_plan[1]
        elif navigation_wait:
            # TerrainNavigator returned the current pose because a resumable A*
            # job is still pending. This is a planner wait, not route arrival and
            # not physical evidence that should advance LocalDriver recovery.
            local = {
                'throttle': 0.0,
                'brake': True,
                'turn': 0.0,
                'target_yaw': float(state.get('yaw', 0.0)),
                'recovery_mode': 'nav_wait',
            }
        else:
            local = self.driver.drive(
                bot_id, int(state['slot']), position,
                float(state.get('yaw', 0.0)),
                float(state.get('speed', 0.0)), float(state.get('dt', 0.0)),
                target, state.get('neighbours', ()), direction_clear,
                velocity=state.get('velocity'),
                half_length=float(state.get('half_length', 3.5)),
                half_width=float(state.get('half_width', 1.7)),
                movement_intent=movement_intent,
                stopping_distance=state.get('stopping_distance'),
                stop_at_target=stop_at_target,
                decision_horizon=float(state.get('decision_horizon', 0.0)),
                pose_clear=state.get('pose_clear'),
                turn_speed_limit=state.get('turn_speed_limit'))
        # Preserve the mature face-position intent which is separate from the
        # gun target.  At a route/cover stop it gives armoured turreted tanks
        # their stable 12-30 degree hull angle while the turret keeps tracking
        # ``aim_position``.  Local recovery directions still outrank it.
        recovery_mode = local.get('recovery_mode', 'drive')
        if contact_escape and recovery_mode in ('drive', 'arrived', 'avoid'):
            recovery_mode = 'contact_escape'
        target_yaw = float(local['target_yaw'])
        turn = float(local['turn'])
        dx = float(face_position[0]) - float(position[0])
        dz = float(face_position[2]) - float(position[2])
        if (recovery_mode in ('arrived', 'nav_wait') and
                dx * dx + dz * dz > 0.01):
            target_yaw = math.atan2(dx, dz)
            difference = target_yaw - float(state.get('yaw', 0.0))
            while difference > math.pi:
                difference -= 2.0 * math.pi
            while difference < -math.pi:
                difference += 2.0 * math.pi
            turn = max(-1.0, min(1.0, difference / 0.58))
        result = {
            'bot_id': bot_id,
            'target_id': strategic.get('target_id'),
            'aim_position': aim_position,
            'face_position': face_position,
            'fire_range': float(strategic.get('fire_range', 0.0)),
            'move_position': target,
            'combat_mode': strategic.get('combat_mode', 'route'),
            'fire_allowed': bool(strategic.get('fire_allowed', False)),
            'shell_index': int(strategic.get('shell_index', 0)),
            'throttle': float(local['throttle']),
            'brake': bool(local.get('brake', False)),
            'turn': turn,
            'target_yaw': target_yaw,
            'recovery_mode': recovery_mode,
            'movement_intent': movement_intent,
        }
        if local.get('reverse_blocked_by') is not None:
            result['reverse_blocked_by'] = local['reverse_blocked_by']
        if strategic.get('hull_angle_degrees') is not None:
            result['hull_angle_degrees'] = float(
                strategic.get('hull_angle_degrees'))
        difference = target_yaw - float(state.get('yaw', 0.0))
        while difference > math.pi:
            difference -= 2.0 * math.pi
        while difference < -math.pi:
            difference += 2.0 * math.pi
        if (throttle_override is not None and
                recovery_mode in ('drive', 'arrived') and
                abs(difference) < 0.65):
            result['throttle'] = max(
                -1.0, min(1.0, float(throttle_override)))
            result['brake'] = result['throttle'] == 0.0
        return result
