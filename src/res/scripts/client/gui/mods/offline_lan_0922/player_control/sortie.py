"""One foreground artillery's route cursor and bounded progress recovery.

This owner proposes another authored node; it never proves a route, moves a
body, reserves a team road or calls Bot recovery. Native support and the
player pathfinder still admit every proposed target.
"""
import math


ATTEMPT_SECONDS = 20.
MAX_AIM_PAUSE_SECONDS = 20.
ARRIVAL_RADIUS = 6.


def geometry(route):
    return tuple((float(point[0]), float(point[1]))
                 for point in route.get('waypoints', ()))


class SortieProgress(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.identity = None
        self.phase = 'forward'
        self.index = 0
        self.failed_index = None
        self.attempt = None
        self.last_at = None
        self.last_sequence = None
        self.aim_pause = 0.
        self.receipt = dict(phase='idle', reason='idle')

    def pause(self, now):
        self.last_at = None

    def resume(self, now):
        self.last_at = float(now)

    def _goal(self, points, home):
        if self.phase == 'home':
            return tuple(home['point']) if home is not None else None
        return points[self.index]

    def _result(self, route, points, home, reason, **fields):
        self.receipt = dict(phase=self.phase, reason=reason, route=route['id'],
            index=self.index, failed_index=self.failed_index,
            elapsed=self.attempt['elapsed'] if self.attempt is not None else 0.,
            aim_pause=self.aim_pause, goal=self._goal(points, home))
        self.receipt.update(fields)
        return dict(self.receipt)

    def update(self, route, index, state, home, reached, aiming=False, sequence=None,
               can_advance=None, arrived_index=None):
        points = geometry(route)
        if not points:
            return dict(phase='exhausted', reason='empty_sortie_route', replace=True,
                        route=route.get('id'), index=0, goal=None)
        now, position = float(state['now']), state['position']
        identity = (route['id'], points)
        if identity != self.identity:
            self.reset()
            self.identity = identity
            self.index = max(0, min(len(points)-1, int(index)))
        dt = max(0., now-self.last_at) if self.last_at is not None else 0.
        self.last_at = now
        if sequence is not None and sequence != self.last_sequence:
            # Only an actual committed round renews the stationary aiming
            # allowance. Cycling targets or changing a goal is not progress.
            self.last_sequence, self.aim_pause = sequence, 0.
        paused = 0.
        if aiming and sequence is not None:
            paused = min(dt, max(0., MAX_AIM_PAUSE_SECONDS-self.aim_pause))
            self.aim_pause += paused
        active_dt = dt-paused
        if (aiming and sequence is not None and paused == dt and
                self.aim_pause < MAX_AIM_PAUSE_SECONDS):
            return self._result(route, points, home, 'aiming_pause', paused=True)
        # The loop can consume at most the authored nodes plus the home handoff.
        # Every advancement still needs the caller's fresh support evidence.
        for unused in range(len(points)+1):
            goal = self._goal(points, home)
            if goal is None:
                return self._result(route, points, home, 'home_unavailable', replace=True)
            if (self.phase != 'home' and can_advance is not None and
                    not can_advance(self.index, self.phase)):
                # The parking owner must inspect each authored wait before a
                # nearby-node burst can consume it. This is an index boundary,
                # not a coordinate match: repeated points may own distinct waits.
                self.attempt = None
                return self._result(route, points, home, 'authored_node_pending',
                                    node_owner_pending=True)
            radius = home['radius'] if self.phase == 'home' else ARRIVAL_RADIUS
            parked = self.phase in ('forward', 'skip') and self.index == arrived_index
            if not parked and not reached(goal, radius):
                break
            self.attempt = None
            self.aim_pause = 0.
            if self.phase == 'home':
                return self._result(route, points, home, 'returned_home', replace=True)
            if self.phase == 'return':
                if self.index > 0:
                    self.index -= 1
                else:
                    self.phase = 'home'
            elif self.index < len(points)-1:
                self.phase = 'forward'
                self.failed_index = None
                self.index += 1
            else:
                return self._result(route, points, home, 'sortie_route_arrived', complete=True)
        goal = self._goal(points, home)
        if goal is None:
            return self._result(route, points, home, 'home_unavailable', replace=True)
        distance = math.hypot(position[0]-goal[0], position[2]-goal[1])
        key = (self.phase, self.index, goal)
        if self.attempt is None or self.attempt['key'] != key:
            self.attempt = dict(key=key, best=distance, elapsed=0.)
        elif distance < self.attempt['best']-.5:
            self.attempt.update(best=distance, elapsed=0.)
            self.aim_pause = 0.
        else:
            self.attempt['elapsed'] += active_dt
        if self.attempt['elapsed'] < ATTEMPT_SECONDS:
            return self._result(route, points, home, 'travelling')
        failed_phase = self.phase
        if self.phase == 'forward':
            self.failed_index = self.index
            if self.index < len(points)-1:
                self.phase, self.index = 'skip', self.index+1
            else:
                self.phase, self.index = 'return', max(0, self.index-1)
        elif self.phase == 'skip':
            self.phase, self.index = 'return', max(0, self.failed_index-1)
        elif self.phase == 'return':
            if self.index > 0:
                self.index -= 1
            else:
                self.phase = 'home'
        else:
            return self._result(route, points, home, 'home_progress_timeout', replace=True)
        self.attempt = None
        return self._result(route, points, home, 'sortie_progress_timeout',
                            previous_phase=failed_phase)
