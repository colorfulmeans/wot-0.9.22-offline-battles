"""Visible human's independent pivot/travel controller; no Bot driver state."""
from __future__ import division
import math
from .pathfinding import WAYPOINT_ARRIVAL_RADIUS


def angle(value):
    return (value + math.pi) % (2 * math.pi) - math.pi


class Driver(object):
    def __init__(self):
        self.motion_key = None
        self.travel_direction = 1.
        self._reset_motion()

    def _reset_motion(self):
        self.anchor = None
        self.alignment_best = None
        self.reverse_until = 0.
        self.forward_until = 0.
        self.forward_origin = None
        self.clearance_checks = None
        self.recovery_heading = None
        self.recovery_origin = None
        self.alignment_target = None
        self.replan = False
        self.receipt = {}

    def drive(self, position, yaw, speed, target, now, clear, hold=False,
              stopping_distance=None, decision_horizon=.1, terminal=False,
              arrival_radius=2., travel_direction=1., motion_key=None,
              half_length=3.5, turn_speed_limit=None):
        direction = -1. if travel_direction < 0. else 1.
        if self.motion_key != motion_key or self.travel_direction != direction:
            # A short manoeuvre owns its gear and progress. A route's old
            # detour or escape must not turn a cover return into forward travel.
            self._reset_motion()
            self.motion_key, self.travel_direction = motion_key, direction
        fixed_direction = motion_key is not None
        radius = max(0., float(arrival_radius)) if terminal else WAYPOINT_ARRIVAL_RADIUS
        requested_target = tuple(target)
        try:
            traverse = float(turn_speed_limit)
            if math.isnan(traverse) or math.isinf(traverse) or traverse <= 0.:
                traverse = None
        except (TypeError, ValueError, OverflowError):
            traverse = None
        alignment = self.alignment_target
        if alignment is not None:
            if (hold or fixed_direction or direction < 0. or speed < -.05 or traverse is None or
                    math.hypot(target[0]-position[0], target[2]-position[2]) <= radius or
                    math.hypot(alignment[0]-position[0], alignment[2]-position[2]) <= radius or
                    math.hypot(alignment[0]-target[0], alignment[2]-target[2]) > 2.):
                self.alignment_target = None
            else:
                # The admitted near corner owns both heading and brake until
                # aligned. Rebased nearby tips cannot keep moving that target.
                target = alignment
        dx, dz = target[0]-position[0], target[2]-position[2]
        distance = math.hypot(dx, dz)
        travel_heading = math.atan2(dx, dz) if distance > .1 else yaw
        heading = angle(travel_heading + (math.pi if direction < 0. else 0.))
        delta = angle(heading-yaw)
        self.replan = False
        mode, throttle, turn, brake = 'travel', 0., 0., False
        # A nonterminal corner is consumed by the pathfinder at this same
        # radius. Stopping farther away leaves an unconsumed, unreachable leg.
        alignment_gates = []
        stopping = None
        if stopping_distance is not None:
            value = stopping_distance() if callable(stopping_distance) else stopping_distance
            value = float(value)
            if not math.isnan(value) and value >= 0.:
                stopping = value + abs(speed) * max(0., float(decision_horizon))
        arrival_brake = (terminal and stopping is not None and speed * direction > .05 and
                         abs(delta) < math.pi / 2. and distance - radius <= stopping)
        if hold or distance <= radius or arrival_brake:
            mode, brake = 'hold', True
            if arrival_brake and not hold and distance >= radius:
                mode = 'arrival_brake'
            self.anchor = None
            self.alignment_best = None
            self.reverse_until = 0.
            self.forward_until = 0.
            self.forward_origin = None
            self.alignment_target = None
        elif (direction < 0. or fixed_direction) and speed * direction < -.05:
            mode, brake = 'direction_brake', True
        elif now < self.forward_until:
            # A static wall may block pivoting and the rear corridor while
            # leaving room ahead. Keep this admitted translation straight and
            # bounded; it must never inherit the objective's steering angle.
            mode = 'forward_clearance'
            advanced = math.hypot(position[0]-self.forward_origin[0],
                                  position[2]-self.forward_origin[2])
            if advanced < 3. and clear(yaw, 4.):
                throttle = .45
            else:
                self.forward_until = 0.
                self.anchor = None
                self.replan = True
                brake = True
        elif now < self.reverse_until:
            # A recovery owns one fixed direction until its deadline. Turning
            # or an updated path tip cannot reverse the pedal every frame.
            mode = 'reverse_clearance'
            throttle = -1. if clear(yaw+math.pi, 4.) else 0.
        else:
            if self.forward_until:
                self.forward_until = 0.
                self.forward_origin = None
                self.anchor = None
                self.replan = True
            if self.reverse_until:
                self.reverse_until = 0.
                self.anchor = None
                self.replan = True
            if self.recovery_heading is not None:
                heading = self.recovery_heading
                delta = angle(heading-yaw)
                if self.recovery_origin is not None and math.hypot(
                        position[0]-self.recovery_origin[0],position[2]-self.recovery_origin[2]) >= 3.:
                    self.recovery_heading = None
                    self.replan = True
            reach = (min(4., max(3., distance)) if self.recovery_heading is not None
                     else max(3., min(5. if direction < 0. else 8., distance)))
            if fixed_direction and terminal:
                # A hard cover face may sit just beyond a valid endpoint.
                # Do not demand cruise space beyond this short leg; the
                # stopping envelope above still brakes before that endpoint.
                reach = min(distance, reach)
            if fixed_direction or direction < 0.:
                # Short cover legs retain their checked gear/alignment rule.
                # This is separate from ordinary forward route steering.
                align = abs(delta) > .30
                if align:
                    alignment_gates.append('fixed_gear_alignment')
            else:
                # Independent implementation of the current Bot's pedal
                # gates: a modest angle to a distant clear goal still drives.
                # Only near turning circles, corners, slopes and rear goals
                # require a stationary alignment before forward travel.
                if self.recovery_heading is not None:
                    self.alignment_target = None
                elif traverse is not None and speed >= -.05:
                    turning_radius = max(1., abs(speed)) / traverse
                    if distance <= max(8., 2. * turning_radius) and abs(delta) > .30:
                        self.alignment_target = tuple(target)
                    if self.alignment_target is not None:
                        if abs(delta) > .12:
                            alignment_gates.append('retained_near_point_alignment')
                        else:
                            self.alignment_target = None
                if distance <= max(8., float(half_length) * 2.) and abs(delta) > .45:
                    alignment_gates.append('near_corner_alignment')
                grade = (target[1] - position[1]) / max(.1, distance)
                if abs(grade) > math.tan(math.radians(22.5)) and abs(delta) > math.pi / 4.:
                    alignment_gates.append('slope_entry_alignment')
                if abs(delta) > math.pi / 2.:
                    alignment_gates.append('rear_heading_alignment')
                align = bool(alignment_gates)
            if align:
                mode = 'align'
                if abs(speed) > (.05 if direction < 0. else 1.5):
                    brake = True
                else:
                    turn = max(-1., min(1., delta/.5))
            elif clear(yaw + (math.pi if direction < 0. else 0.), reach):
                # A detour was proved over five metres, not the ordinary
                # eight-metre cruise horizon. Move cautiously within that
                # proof instead of rejecting it and alternating fan headings.
                throttle = direction * (.45 if self.recovery_heading is not None or distance <= 5.
                                        else .65 if direction < 0. else 1.)
                # Native steering reverses its yaw sign with reverse intent;
                # stationary alignment above still uses the physical yaw sign.
                turn = (max(-.6, min(.6, delta * direction)) if fixed_direction or direction < 0.
                        else max(-1., min(1., delta / .58)))
            else:
                mode, brake = 'blocked', True
                if direction > 0. and not fixed_direction:
                    # Short cover legs already have checked geometry and a
                    # movement deadline. Only ordinary routes own this fan.
                    choices = [heading+offset for offset in (.55, -.55, 1., -1.)]
                    self.recovery_heading = next((h for h in choices if clear(h, 5.)), None)
                    if self.recovery_heading is not None:
                        self.recovery_origin = tuple(position)
                        mode, brake = 'detour_align', False
                        turn = 1. if angle(self.recovery_heading-yaw) > 0 else -1.
            if self.anchor is None:
                self.anchor = (tuple(position), yaw, now)
                self.alignment_best = abs(delta)
            p, old_yaw, at = self.anchor
            moved = math.hypot(position[0]-p[0], position[2]-p[2])
            rotated = abs(angle(yaw-old_yaw))
            aligned_better = (rotated > .20 and self.alignment_best is not None and
                              abs(delta) < self.alignment_best-.20)
            if moved > 1. or aligned_better:
                self.anchor = (tuple(position), yaw, now)
                self.alignment_best = abs(delta)
            elif now-at >= 3.:
                self.replan = True
                self.anchor = (tuple(position), yaw, now)
                # Reverse only after measured nonprogress plus a proved clear
                # rear corridor. It is bounded and cannot steer toward a hill.
                if (direction > 0. and not fixed_direction and
                        mode in ('blocked', 'travel', 'align', 'detour_align')):
                    rear = clear(yaw+math.pi, 4.)
                    front = not rear and mode in ('align', 'detour_align', 'blocked') and clear(yaw, 4.)
                    self.clearance_checks = dict(at=now, origin=tuple(position),
                        yaw=yaw, rear=rear, front=front, stalled_mode=mode)
                    if rear:
                        self.reverse_until = now+1.
                        mode, throttle, turn, brake = 'reverse_clearance', -1., 0., False
                    elif front:
                        self.forward_until = now+1.
                        self.forward_origin = tuple(position)
                        mode, throttle, turn, brake = 'forward_clearance', .45, 0., False
        self.receipt = dict(mode=mode, distance=distance, heading=heading,
                            travel_heading=travel_heading, direction=direction,
                            yaw=yaw, delta=delta, reverse_until=self.reverse_until,
                            forward_until=self.forward_until,
                            clearance_checks=self.clearance_checks,
                            requested_target=requested_target,
                            alignment_target=self.alignment_target,
                            alignment_gates=alignment_gates, turn_speed_limit=traverse,
                            terminal=bool(terminal), arrival_radius=radius,
                            stopping_envelope=stopping,
                            decision_horizon=max(0., float(decision_horizon)))
        return dict(throttle=throttle, turn=turn, brake=brake, recovery_mode=mode)
