"""Foreground command lifecycle and physical arrival evidence.

The controller owns one mission. Static map circles describe the objective;
only the observed native vehicle pose can prove arrival. No actor allocations
or server movement state are consumed here.
"""
from __future__ import division
import copy
import math


ACTIONS = ('attack', 'return_base', 'defend_base', 'hold_position', 'capture_base')
TERMINAL = ('completed', 'failed', 'cancelled')
SETTLE_SECONDS = .5
STOP_SPEED = .5
SUPPORT_TOLERANCE = 1.
PROGRESS_TIMEOUT = 30.


def horizontal(point):
    """Accept protocol x/z or the current native x/y/z pose."""
    if isinstance(point, dict):
        return float(point['x']), float(point['z'])
    return float(point[0]), float(point[2] if len(point) == 3 else point[1])


def distance(position, point):
    x, z = horizontal(point)
    return math.hypot(position[0] - x, position[2] - z)


def base_areas(graph, team, active=None):
    """Prefer the circles actually published for this match.

    A radius in the active publication wins over baked metadata. The server's
    _update_capture contract assigns 50 metres to an admitted legacy point
    without a radius; this explicit wire default also applies to edited flags.
    """
    bases, radii = graph.get('objective_bases') or (), graph.get('objective_base_radii') or ()
    result = []
    for index in (team - 1, 2 - team):
        baked_point = horizontal(bases[index]) if len(bases) == 2 else None
        radius = float(radii[index]) if len(radii) == 2 else None
        point, source = baked_point, 'validated_map_graph'
        if active is not None:
            rows = active.get(index + 1, active.get(str(index + 1), ())) if isinstance(active, dict) else ()
            if not isinstance(rows, (list, tuple)) or len(rows) != 1:
                result.append(None)
                continue
            row = rows[0]
            point = horizontal(row)
            if isinstance(row, dict) and row.get('radius') is not None:
                radius = float(row['radius'])
            else:
                radius = 50.
            source = 'active_capture_bases'
        if (point is None or radius is None or not radius > 0. or
                math.isnan(radius) or math.isinf(radius)):
            result.append(None)
        else:
            result.append(dict(point=point, radius=radius, team=index + 1, source=source))
    return result[0], result[1]


def legal_support(state, context, height):
    return bool(context.get('supported', state.get('supported', True)) and
                not context.get('overturned', state.get('overturned', False)) and
                height is not None and abs(state['position'][1] - height) <= SUPPORT_TOLERANCE)


class Mission(object):
    def __init__(self, identity, action, args, state, home, enemy, explicit=True):
        if action not in ACTIONS:
            raise ValueError('Unknown player mission: %s' % action)
        self.identity = identity
        self.action = action
        self.explicit = bool(explicit)
        self.created_at = float(state['now'])
        default_timeout = 600. if action in ('attack', 'capture_base') else 180.
        self.deadline = self.created_at + float(args.get('timeout', default_timeout))
        self.status = 'pending'
        self.phase = 'attacking' if action == 'attack' else 'travelling'
        self.reason = 'accepted'
        self.result = None
        self.progress = 0.
        self.arrival = dict(inside=False, supported=False, stopped=False, settled=False)
        self.settle_at = None
        self.clear_at = None
        self.origin = tuple(state['position'])
        self.progress_position = self.origin
        self.progress_at = self.created_at
        self.best_distance = None
        self.initial_distance = None
        self.goal = None
        self.goal_height = None
        self.radius = max(2., float(args.get('radius', 2.)))
        self.objective = action
        self.area = None
        self.point_attack = action == 'attack' and args.get('position') is not None
        self._last_now = self.created_at
        if action in ('return_base', 'defend_base'):
            self.area = copy.deepcopy(home)
        elif action == 'capture_base':
            self.area = copy.deepcopy(enemy)
        elif action == 'attack' and not self.point_attack:
            self.area = copy.deepcopy(enemy)
        else:
            destination = args.get('position', self.origin)
            self.goal = horizontal(destination)
            if not isinstance(destination, dict) and len(destination) == 3:
                self.goal_height = float(destination[1])
        if self.area is not None:
            self.goal, self.radius = tuple(self.area['point']), float(self.area['radius'])
        elif self.goal is None:
            self.finish('failed', 'base_geometry_unavailable', self.created_at)

    @property
    def protected(self):
        # A completed command still owns its parking anchor until replaced.
        return self.explicit and self.status != 'cancelled'

    @property
    def capturing(self):
        return self.objective == 'capture_base' or (
            self.action == 'attack' and self.phase in ('capture_travel', 'capturing'))

    @property
    def route_attack(self):
        return self.action == 'attack' and self.objective == 'attack' and not self.point_attack

    def finish(self, status, reason, now):
        if self.status in TERMINAL:
            return
        self.status, self.reason = status, reason
        self.result = dict(status=status, reason=reason, at=float(now))
        if status == 'completed':
            self.progress = 1.
        else:
            self.phase = status

    def enter_capture(self, enemy, state, reason):
        if self.status in TERMINAL or self.capturing:
            return
        if enemy is None:
            self.finish('failed', 'base_geometry_unavailable', state['now'])
            return
        # Keep identity/action/deadline: this is a phase of the accepted attack.
        self.objective = 'capture_base'
        self.area = copy.deepcopy(enemy)
        self.goal, self.radius = tuple(enemy['point']), float(enemy['radius'])
        self.goal_height = None
        self.phase, self.reason = 'capture_travel', reason
        self.settle_at = None
        self.best_distance = self.initial_distance = None
        self.progress_position = tuple(state['position'])
        self.progress_at = float(state['now'])

    def observe(self, state, context, height):
        now, position = float(state['now']), state['position']
        self._last_now = now
        if self.goal is None:
            return
        remaining = distance(position, self.goal)
        was_legal = self.arrival.get('inside') and self.arrival.get('supported')
        supported = legal_support(state, context, height)
        height_matches = self.goal_height is None or abs(position[1] - self.goal_height) <= SUPPORT_TOLERANCE
        supported = supported and height_matches
        inside = remaining <= self.radius
        stopped = abs(float(state.get('speed', 0.))) <= STOP_SPEED
        legal = inside and supported
        if legal and stopped:
            if self.settle_at is None:
                self.settle_at = now
        else:
            self.settle_at = None
        settled = self.settle_at is not None and now - self.settle_at >= SETTLE_SECONDS
        self.arrival = dict(inside=inside, supported=supported, stopped=stopped,
                            settled=settled, distance=remaining, radius=self.radius,
                            settled_since=self.settle_at, height_matches=height_matches)
        if self.status in TERMINAL:
            # Arrival facts continue to expose a shove after completed parking.
            return
        self.status = 'running'
        if self.initial_distance is None:
            self.initial_distance = max(remaining, self.radius + .01)
            self.best_distance = remaining
        if was_legal and not legal:
            # A small shove across a flag edge starts a new travel attempt,
            # even after minutes of valid occupancy at that same anchor.
            self.progress_at, self.progress_position = now, tuple(position)
        if remaining < self.best_distance - .5 or distance(position, self.progress_position) >= 2.:
            self.best_distance = min(remaining, self.best_distance)
            self.progress_position, self.progress_at = tuple(position), now
        self.progress = min(.9, max(self.progress,
            .9 * (1. - max(0., remaining - self.radius) /
                  max(.01, self.initial_distance - self.radius))))

        captured = bool(context.get('capture_complete') or
                        (context.get('enemy_base') or {}).get('points', 0) >= 100)
        if self.capturing and captured:
            self.phase = 'captured'
            self.finish('completed', 'base_captured', now)
            return
        if context.get('battle_finished'):
            self.finish('cancelled', 'battle_finished_before_objective', now)
            return
        if now >= self.deadline:
            self.finish('failed', 'mission_timeout', now)
            return

        if self.route_attack:
            # The navigation owner decides when the authored route hands off.
            return
        if not legal:
            self.phase = 'capture_travel' if self.capturing else 'travelling'
            self.clear_at = None
            if now - self.progress_at >= PROGRESS_TIMEOUT:
                self.finish('failed', 'no_navigation_progress', now)
            return
        if not settled:
            self.phase = 'arriving'
            return
        if self.capturing:
            self.phase, self.reason = 'capturing', 'inside_flag_circle'
            self.progress = max(self.progress, .95)
            return
        if self.action == 'defend_base':
            self.phase = 'defending'
            base = context.get('base') or {}
            alarm = bool(base.get('points', 0) > 0 or base.get('invaders', 0) > 0)
            observed = any(distance(enemy['position'], self.goal) <= max(self.radius, 100.)
                           for enemy in context.get('contacts', ()) if enemy.get('position') is not None)
            if alarm or observed:
                self.clear_at = None
            elif self.clear_at is None:
                self.clear_at = now
            elif now - self.clear_at >= 5.:
                self.phase = 'holding'
                self.finish('completed', 'base_clear_and_held', now)
            return
        self.phase = 'holding'
        self.finish('completed', 'arrived_and_held', now)

    def wants_hold(self):
        if self.status in ('failed', 'cancelled'):
            return True
        if self.route_attack:
            return False
        # Brake immediately on legal entry; the settle timer proves arrival.
        return bool(self.arrival.get('inside') and self.arrival.get('supported'))

    def snapshot(self):
        return dict(id=self.identity, action=self.action, objective=self.objective,
                    explicit=self.explicit, status=self.status, phase=self.phase,
                    progress=round(self.progress, 4), reason=self.reason,
                    result=copy.deepcopy(self.result), goal=self.goal, radius=self.radius,
                    goal_height=self.goal_height,
                    arrival=dict(self.arrival), created_at=self.created_at,
                    deadline=self.deadline, holding=self.wants_hold())
