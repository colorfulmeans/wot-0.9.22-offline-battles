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
        self._contact_attempts = {}
        self._wreck_attempts = {}
        self._withdrawal_attempts = {}

    def register(self, bot_id, team, descriptor, display_name='Bot'):
        return self.director.register(bot_id, team, descriptor, display_name)

    def forget(self, bot_id):
        self.driver.forget(bot_id)
        self.director.agents.pop(int(bot_id), None)
        self._contact_peers.pop(int(bot_id), None)
        self._contact_attempts.pop(int(bot_id), None)
        self._wreck_attempts.pop(int(bot_id), None)
        self._withdrawal_attempts.pop(int(bot_id), None)

    def _hull_contact(self, bot_id, state, position):
        """Return geometry for a real hull contact across small gaps."""
        shape = state.get('collision_shape') or (
            state.get('half_width', 1.7), state.get('half_length', 3.5),
            tank_collision.DEFAULT_SHAPE[2], tank_collision.DEFAULT_SHAPE[3])
        previous = self._contact_peers.get(bot_id)
        for peer in state.get('neighbours', ()):
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
                    'peer_team': peer.get('team'),
                    'peer_alive': peer.get('alive', True),
                    'normal': overlap[:2],
                    'peer_position': where,
                }
        self._contact_peers.pop(bot_id, None)
        self._contact_attempts.pop(bot_id, None)
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
        A centred side contact tries both checked ends in bounded episodes.
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
            bot_id = int(state.get('id', 0))
            attempt = self._contact_attempts.get(bot_id)
            if (attempt is None or attempt['peer'] != contact.get('peer_id') or
                    math.hypot(position[0]-attempt['position'][0],
                               position[2]-attempt['position'][2]) >= 0.5):
                attempt = dict(peer=contact.get('peer_id'), position=position,
                               elapsed=0.0)
                self._contact_attempts[bot_id] = attempt
            attempt['elapsed'] += max(0.0, float(state.get('dt', 0.0)))
            preferred = -1.0 if int(attempt['elapsed']/1.5) % 2 == 0 else 1.0
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
                'throttle': 1.0 * sign,
                'brake': False,
                'turn': 0.0,
                'target_yaw': yaw,
                'recovery_mode': 'contact_escape',
            }
        return None

    def _wreck_push_plan(self, bot_id, state, position, strategic,
                         direction_clear):
        """Try local detours before spending a bounded wreck motor attempt.

        This admits controls only. The normal terrain, hull and contact solver
        still owns every resulting pose and any displacement of the wreck.
        Route changes or real wreck movement renew the attempt; yaw oscillation
        and tiny order changes do not.
        """
        if (strategic.get('combat_mode') not in ('route', 'advance') or
                strategic.get('throttle_override') is not None):
            return None
        yaw = float(state.get('yaw', 0.0))
        length = float(state.get('half_length', 3.5))
        width = float(state.get('half_width', 1.7))
        goal = _position(strategic.get('move_position'), position)
        desired = math.atan2(goal[0]-position[0], goal[2]-position[2])
        neighbours = state.get('neighbours', ())
        wreck = next((peer for peer in neighbours
                      if not peer.get('alive', True) and
                      self.driver._static_hull_ahead(
                          position, desired, [peer], length, width)), None)
        if wreck is None:
            return None
        where = _position(wreck.get('position', wreck))
        forward = math.sin(yaw), math.cos(yaw)
        error = (desired-yaw+math.pi) % (2.0*math.pi)-math.pi
        key = (wreck.get('id'), strategic.get('route_id'),
               strategic.get('route_index'))
        attempt = self._wreck_attempts.get(bot_id)
        if (attempt is None or attempt['key'] != key or
                math.hypot(where[0]-attempt['position'][0],
                           where[2]-attempt['position'][2]) >= 1.0):
            attempt = dict(key=key, position=where, elapsed=0.0,
                           best_distance=math.hypot(goal[0]-position[0], goal[2]-position[2]))
            self._wreck_attempts[bot_id] = attempt
        distance = math.hypot(goal[0]-position[0], goal[2]-position[2])
        if distance + 0.5 <= attempt['best_distance']:
            attempt['best_distance'] = distance
            attempt['elapsed'] = 0.0
        attempt['elapsed'] += max(0.0, float(state.get('dt', 0.0)))
        if attempt['elapsed'] < 6.0:
            return None
        if attempt['elapsed'] >= 14.0:
            return position, dict(throttle=0.0, turn=0.0, target_yaw=yaw,
                                  recovery_mode='blocked')
        if abs(error) > math.pi/3.0:
            return None
        reach = recovery_probe_distance(length)
        if not self.driver._clear(direction_clear, yaw, reach):
            return None
        living = [peer for peer in neighbours if peer.get('alive', True)]
        if self.driver._reverse_blocked_by_vehicle(
                position, yaw+math.pi, living, length, width) is not None:
            return None
        # First push squarely, then spend track torque on alternate small turns.
        # A world wall still vetoes the manoeuvre; wreck contacts spend real
        # motor force even when the realised rotation is clamped by physics.
        turn = 0.0
        if attempt['elapsed'] >= 8.0:
            side = 1.0 if int((attempt['elapsed']-6.0)/2.0) % 2 else -1.0
            sample_yaw = yaw + side*0.25
            pose_clear = state.get('pose_clear')
            if (self.driver._clear(direction_clear, sample_yaw, reach) and
                    (pose_clear is None or pose_clear(sample_yaw))):
                turn = side*0.4
        target = (position[0]+forward[0]*reach, position[1],
                  position[2]+forward[1]*reach)
        return target, dict(throttle=1.0, turn=turn, target_yaw=yaw,
                            recovery_mode='wreck_push')

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

    def _reverse_withdrawal(self, state, strategic, position, target,
                            destination, direction_clear):
        """Back toward a nearby withdrawal point while preserving frontal armour.

        Long withdrawals retain reverse while an in-range contact is tracked;
        after contact is lost the ordinary route driver may turn and travel.
        Native motion still independently proves every realised movement.
        """
        if strategic.get('combat_mode') not in (
                'withdraw', 'low_health_retreat', 'under_fire_withdraw',
                'crossfire_withdraw'):
            return None
        if strategic.get('throttle_override') is not None:
            return None
        dx, dz = target[0] - position[0], target[2] - position[2]
        distance = math.hypot(dx, dz)
        if distance <= WAYPOINT_ARRIVAL_RADIUS:
            return None
        goal_distance = math.hypot(
            destination[0] - position[0], destination[2] - position[2])
        threat = _position(strategic.get('aim_position'), position)
        exposed = (strategic.get('target_id') is not None and
                   math.hypot(threat[0] - position[0],
                              threat[2] - position[2]) <=
                   float(strategic.get('fire_range', 0.0)))
        if goal_distance > 30.0 and not exposed:
            return None
        # Backing bypasses LocalDriver.drive, including its progress clock.
        # Bound this owner independently so a denied rear sweep cannot hold
        # the tank forever or repeatedly steal control from local recovery.
        bot_id = int(state.get('id', 0))
        attempt = self._withdrawal_attempts.get(bot_id)
        if (attempt is None or math.hypot(
                destination[0] - attempt['goal'][0],
                destination[2] - attempt['goal'][2]) > 2.0):
            attempt = {'goal': tuple(destination), 'position': tuple(position),
                       'distance': goal_distance, 'age': 0.0, 'fallback': False}
            self._withdrawal_attempts[bot_id] = attempt
        moved = math.hypot(position[0] - attempt['position'][0],
                           position[2] - attempt['position'][2])
        progressed = (goal_distance + 2.0 <= attempt['distance']
                      if attempt['fallback'] else moved >= 0.08)
        if progressed:
            attempt.update(position=tuple(position), distance=goal_distance,
                           age=0.0, fallback=False)
        attempt['age'] += max(0.0, float(state.get('dt', 0.0)))
        if attempt['age'] >= 8.0:
            attempt['fallback'] = True
        if attempt['fallback']:
            return None
        yaw = float(state.get('yaw', 0.0))
        travel_yaw = math.atan2(dx, dz)
        # atan2 is the rear travel heading; the desired hull faces opposite it.
        face_yaw = travel_yaw + math.pi
        error = (face_yaw - yaw + math.pi) % (2.0 * math.pi) - math.pi
        if abs(error) > math.pi / 3.0:
            return None
        length = float(state.get('half_length', 3.5))
        width = float(state.get('half_width', 1.7))
        reach = min(distance, length * 1.6)
        clear = True
        blocker = None
        pose_clear = state.get('pose_clear')
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            sample_yaw = yaw + error * fraction
            clear = clear and self.driver._clear(
                direction_clear, sample_yaw + math.pi, reach)
            blocker = blocker or self.driver._reverse_blocked_by_vehicle(
                position, sample_yaw, state.get('neighbours', ()), length, width)
            try:
                if pose_clear is not None:
                    clear = clear and bool(pose_clear(sample_yaw))
            except Exception:
                clear = False
        if not clear or blocker is not None:
            result = {'throttle': 0.0, 'turn': 0.0, 'target_yaw': yaw,
                      'recovery_mode': 'blocked'}
            if blocker is not None:
                result['reverse_blocked_by'] = blocker
            return result
        # Reverse steering has the opposite input sign. Align gently before
        # backing rather than turning the chassis around toward the waypoint.
        braking_distance = max(0.0, float(state.get('stopping_distance') or 0.0))
        stopping = (float(state.get('speed', 0.0)) < -0.05 and
                    distance <= max(WAYPOINT_ARRIVAL_RADIUS, braking_distance))
        return {'throttle': 0.0 if stopping else -0.72,
                'turn': 0.0 if stopping else -max(-0.5, min(0.5, error / 0.58)),
                'withdrawal_aim': goal_distance <= 30.0 and exposed,
                'target_yaw': face_yaw, 'recovery_mode': 'reverse_withdraw'}

    @observed('driver.order')
    def _drive_order(self, bot_id, state, position, strategic,
                     direction_clear):
        aim_position = strategic.get('aim_position')
        move_position = strategic.get('move_position')
        face_position = strategic.get('face_position')
        parked = strategic.get('parking_phase') in ('waiting', 'queue')
        if parked and face_position is None and aim_position is None:
            # A parking coordinate is a translation anchor, not a facing
            # order. Losing a target must not turn the hull back toward the
            # sub-metre offset to that anchor and undo fixed-gun laying.
            heading=strategic.get('parking_heading')
            if heading is None:face_position = position
            else:
                angle=math.radians(float(heading))
                face_position=(position[0]+math.sin(angle)*20,position[1],position[2]+math.cos(angle)*20)
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
        if callable(self.navigation_target):
            target = _position(self.navigation_target(
                bot_id, position, target, strategic, state), target)
        contact_plan = (None if parked else self._wreck_push_plan(
            bot_id, state, position, strategic, direction_clear))
        contact = self._hull_contact(bot_id, state, position)
        side_contact = bool(contact is not None and abs(
            math.sin(state.get('yaw', 0.0))*contact['normal'][0] +
            math.cos(state.get('yaw', 0.0))*contact['normal'][1]) < 0.35)
        if (not parked and contact_plan is None and contact is not None and
                (side_contact or (strategic.get('throttle_override') is not None and
                 (not contact['peer_alive'] or contact['peer_team'] != state.get('team'))))):
            contact_plan = self._contact_escape_plan(
                state, position, direction_clear, contact)
        if contact_plan is not None:
            target = contact_plan[0]
        stop_at_target = bool(state.get(
            'navigation_stop_at_target',
            strategic.get('combat_mode') not in ('route', 'advance')))
        throttle_override = strategic.get('throttle_override')
        if contact_plan is not None:
            throttle_override = None
            stop_at_target = False
        movement_intent = not (
            throttle_override is not None and
            float(throttle_override) <= 0.0)
        if (not movement_intent or strategic.get('combat_mode') not in (
                'withdraw', 'low_health_retreat', 'under_fire_withdraw',
                'crossfire_withdraw')):
            self._withdrawal_attempts.pop(bot_id, None)
        requested_dx = float(move_position[0]) - float(position[0])
        requested_dz = float(move_position[2]) - float(position[2])
        target_dx = float(target[0]) - float(position[0])
        target_dz = float(target[2]) - float(position[2])
        navigation_wait = bool(
            movement_intent and
            requested_dx * requested_dx + requested_dz * requested_dz > 225.0 and
            target_dx * target_dx + target_dz * target_dz <=
            WAYPOINT_ARRIVAL_RADIUS * WAYPOINT_ARRIVAL_RADIUS)
        # Runtime supplies the producer status. A close bypass is not an A* wait.
        navigation_wait = navigation_wait and state.get(
            'navigation_status', 'pending') in ('pending', 'blocked')
        # A centreline endpoint never removes the leading half of the hull.
        state['navigation_probe_distance'] = max(
            math.hypot(target_dx, target_dz),
            float(state.get('half_length', 3.5)) + max(0.5,
            abs(float(state.get('speed', 0.0))) *
            max(0.0, float(state.get('decision_horizon', state.get('dt', 0.0))))))
        if not movement_intent:
            state.pop('navigation_probe_distance', None)
        if not navigation_wait:
            self.driver.end_navigation_wait(bot_id)
        if contact_plan is not None:
            local = contact_plan[1]
        elif navigation_wait:
            local = self.driver.wait_for_navigation(
                bot_id, int(state['slot']), position,
                float(state.get('yaw', 0.0)), float(state.get('speed', 0.0)),
                float(state.get('dt', 0.0)), state.get('neighbours', ()),
                direction_clear, half_length=float(state.get('half_length', 3.5)),
                half_width=float(state.get('half_width', 1.7)),
                recovery_allowed=bool(state.get('navigation_recovery_allowed')))
        else:
            local = self._reverse_withdrawal(
                state, strategic, position, target, move_position, direction_clear)
            if local is None:
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
                    progress_target=move_position,
                    turn_speed_limit=state.get('turn_speed_limit'),
                    pose_clear=state.get('pose_clear'),
                    arrival_radius=strategic.get('arrival_radius') if stop_at_target else None)
        # Preserve the mature face-position intent which is separate from the
        # gun target.  At a route/cover stop it gives armoured turreted tanks
        # their stable 12-30 degree hull angle while the turret keeps tracking
        # ``aim_position``.  Local recovery directions still outrank it.
        recovery_mode = local.get('recovery_mode', 'drive')
        target_yaw = float(local['target_yaw'])
        turn = float(local['turn'])
        dx = float(face_position[0]) - float(position[0])
        dz = float(face_position[2]) - float(position[2])
        if (recovery_mode == 'arrived' and
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
            'withdrawal_aim': bool(local.get('withdrawal_aim', False)),
        }
        if strategic.get('parking_phase') is not None:
            result['parking_phase'] = strategic['parking_phase']
        if strategic.get('hull_angle_degrees') is not None:
            result['hull_angle_degrees'] = float(
                strategic.get('hull_angle_degrees'))
        for name in ('forward_blocked_by', 'reverse_blocked_by', 'recovery_probe_distance',
                     'navigation_recovery', 'navigation_replan'):
            if name in local:
                result[name] = local[name]
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
        if throttle_override is not None and float(throttle_override) == 0.0:
            result['throttle'] = 0.0
            result['brake'] = True
        return result
