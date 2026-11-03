"""Visible human's independent pivot/travel controller; no Bot driver state."""
from __future__ import division
import math


def angle(value):
    return (value + math.pi) % (2 * math.pi) - math.pi


class Driver(object):
    def __init__(self):
        self.anchor = None
        self.reverse_until = 0.
        self.forward_until = 0.
        self.forward_origin = None
        self.clearance_checks = None
        self.recovery_heading = None
        self.recovery_origin = None
        self.replan = False
        self.receipt = {}

    def drive(self, position, yaw, speed, target, now, clear, hold=False):
        dx, dz = target[0]-position[0], target[2]-position[2]
        distance = math.hypot(dx, dz)
        heading = math.atan2(dx, dz) if distance > .1 else yaw
        delta = angle(heading-yaw)
        self.replan = False
        mode, throttle, turn, brake = 'travel', 0., 0., False
        if hold or distance < 2.:
            mode, brake = 'hold', True
            self.anchor = None
            self.reverse_until = 0.
            self.forward_until = 0.
            self.forward_origin = None
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
            # Pivot toward an objective behind the vehicle, never reverse
            # toward it. A nearby steering tip is not a parking endpoint.
            if abs(delta) > .30:
                mode = 'align'
                if abs(speed) > 1.5:
                    brake = True
                else:
                    turn = max(-1., min(1., delta/.5))
            elif clear(yaw, min(4.,max(3.,distance)) if self.recovery_heading is not None
                       else max(3., min(8., distance))):
                # A detour was proved over five metres, not the ordinary
                # eight-metre cruise horizon. Move cautiously within that
                # proof instead of rejecting it and alternating fan headings.
                throttle = .45 if self.recovery_heading is not None else 1. if distance > 5. else .45
                turn = max(-.6, min(.6, delta))
            else:
                mode, brake = 'blocked', True
                # Search a bounded forward fan, not an alternating reverse law.
                choices = [heading+offset for offset in (.55, -.55, 1., -1.)]
                self.recovery_heading = next((h for h in choices if clear(h, 5.)), None)
                if self.recovery_heading is not None:
                    self.recovery_origin = tuple(position)
                    mode, brake = 'detour_align', False
                    turn = 1. if angle(self.recovery_heading-yaw) > 0 else -1.
            if self.anchor is None:
                self.anchor = (tuple(position), yaw, now)
            p, old_yaw, at = self.anchor
            moved = math.hypot(position[0]-p[0], position[2]-p[2])
            rotated = abs(angle(yaw-old_yaw))
            if moved > 1. or rotated > .20:
                self.anchor = (tuple(position), yaw, now)
            elif now-at >= 3.:
                self.replan = True
                self.anchor = (tuple(position), yaw, now)
                # Reverse only after measured nonprogress plus a proved clear
                # rear corridor. It is bounded and cannot steer toward a hill.
                if mode in ('blocked', 'travel', 'align', 'detour_align'):
                    rear = clear(yaw+math.pi, 4.)
                    front = not rear and mode in ('align', 'detour_align') and clear(yaw, 4.)
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
                            yaw=yaw, delta=delta, reverse_until=self.reverse_until,
                            forward_until=self.forward_until,
                            clearance_checks=self.clearance_checks)
        return dict(throttle=throttle, turn=turn, brake=brake, recovery_mode=mode)
