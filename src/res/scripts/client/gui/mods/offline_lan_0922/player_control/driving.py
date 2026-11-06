"""Visible human's independent pivot/travel controller; no Bot driver state."""
from __future__ import division
import math
from .pathfinding import WAYPOINT_ARRIVAL_RADIUS


DETOUR_HOLD_SECONDS = 1.2
DETOUR_GOAL_LIMIT = 2.15
DETOUR_PROOF_DISTANCE = 5.


def angle(value):
    return (value + math.pi) % (2 * math.pi) - math.pi


class Driver(object):
    def __init__(self):
        self.motion_key = None
        self.request_key = None
        self.travel_direction = 1.
        self._reset_motion()

    def _reset_motion(self):
        self.anchor = None
        self.alignment_best = None
        self.progress = None
        self.reverse_until = 0.
        self.forward_until = 0.
        self.forward_origin = None
        self.clearance_checks = None
        self._clear_detour()
        self.alignment_target = None
        self.replan = False
        self.nonprogress_triggered = False
        self.translation_escape_completed = None
        self.receipt = {}

    def complete_translation_escape(self, position, yaw, now):
        """Return one distance-completed external translation to this driver."""
        previous = self.translation_escape_completed
        if previous is not None and now <= previous['at']:
            return False
        self.translation_escape_completed = dict(at=now, position=tuple(position), yaw=yaw)
        self.reverse_until = self.forward_until = 0.
        self.forward_origin = self.clearance_checks = None
        self.anchor = self.alignment_target = self.alignment_best = None
        self.nonprogress_triggered = False
        # Preserve the request and every fixed-point best. Completing a
        # checked backout starts the next ordinary alignment from its actual
        # endpoint; it does not claim new progress toward the remote goal.
        if self.progress is not None:
            self.progress.update(heading=None, reason='external_translation_completed',
                                 stalled_for=None)
        self.receipt.update(reverse_until=0., forward_until=0., clearance_checks=None,
            alignment_target=None, nonprogress_triggered=False,
            translation_escape_completed=dict(self.translation_escape_completed))
        receipt = self.receipt.get('progress')
        if isinstance(receipt, dict):
            goal = receipt['goal']
            receipt.update(distance=math.hypot(goal[0]-position[0], goal[2]-position[2]),
                heading=None, error=None, best_error=None, at=None, age=None,
                reason='external_translation_completed', stalled_for=None)
        return True

    def _clear_detour(self):
        self.recovery_heading = None
        self.recovery_origin = None
        self.recovery_target = None
        self.recovery_until = 0.

    def _choose_detour(self, position, target, heading, now, clear):
        # Each selection belongs to the live goal. Offsetting an earlier
        # detour repeatedly can turn an ordinary blocked corner into a circle.
        # A blocked hull-forward ray does not reject the goal's own heading.
        # Check that centre candidate before trying the existing side fan.
        choices = [heading + offset for offset in (0., .55, -.55, 1., -1.)]
        selected = next((candidate for candidate in choices
                         if clear(candidate, DETOUR_PROOF_DISTANCE)), None)
        self._clear_detour()
        if selected is not None:
            self.recovery_heading = selected
            self.recovery_origin = tuple(position)
            self.recovery_target = tuple(target)
            self.recovery_until = now + DETOUR_HOLD_SECONDS
            self.alignment_target = None
        return selected is not None

    def _observe_progress(self, position, yaw, speed, target, heading, now,
                          half_length, arrival):
        measured = math.hypot(target[0]-position[0], target[2]-position[2])
        if self.progress is None:
            point = dict(goal=tuple(target), best=measured)
            self.progress = dict(point=point, points=[point], origin=tuple(position),
                                 heading=heading, reason='initial')
        progress = self.progress
        if self.anchor is None:
            self.anchor = (tuple(position), yaw, now)
            progress['origin'], progress['heading'] = tuple(position), heading
            self.alignment_best = abs(angle(heading-yaw))
        previous = progress['point']
        previous_distance = math.hypot(previous['goal'][0]-position[0],
                                       previous['goal'][2]-position[2])
        points = [previous] + [row for row in progress['points'] if row is not previous]
        point = next((row for row in points if
            math.hypot(row['goal'][0]-target[0], row['goal'][2]-target[2]) <= 2. and
            not (measured > arrival and math.hypot(row['goal'][0]-position[0],
                 row['goal'][2]-position[2]) <= arrival)), None)
        progress['reason'] = 'no_new_progress'
        progress['stalled_for'] = None
        if point is None:
            point = dict(goal=tuple(target), best=measured)
            progress['points'].append(point)
            del progress['points'][:-16]
            progress['reason'] = 'new_connector_without_credit'
        elif point is not previous:
            progress['reason'] = 'revisited_connector_without_credit'
        progress['point'] = point
        distance = math.hypot(point['goal'][0]-position[0], point['goal'][2]-position[2])
        arrived = point is not previous and previous_distance <= arrival
        # A consumed corner or actual travel out of the local vehicle-sized
        # pocket permits the next bend's alignment anchor. A zero-speed track
        # pivot can move the hull centre too, so displacement alone cannot.
        departed = abs(speed) > .05 and math.hypot(
            position[0]-progress['origin'][0], position[2]-progress['origin'][2]) >= 2.*half_length+arrival
        if arrived or departed:
            progress['origin'], progress['heading'] = tuple(position), heading
            self.alignment_best = abs(angle(heading-yaw))
            if arrived:
                previous['best'] = min(previous['best'], previous_distance)
        error = abs(angle(progress['heading']-yaw))
        # Both distances refer to one fixed point, including nearby rebases.
        # A new/revisited connector does not renew the clock by itself. Keep
        # the existing metre and angular thresholds, with cumulative credit.
        translation = abs(speed) > .05 and distance < point['best']-1.
        alignment = error < self.alignment_best-.20
        if translation:
            point['best'] = distance
        if alignment:
            self.alignment_best = error
        if arrived or translation or alignment:
            self.anchor = (tuple(position), yaw, now)
            progress['reason'] = ('corner_reached' if arrived else
                                  'new_best_translation_and_alignment' if translation and alignment else
                                  'new_best_translation' if translation else 'new_best_alignment')
        progress['distance'], progress['error'] = distance, error

    def drive(self, position, yaw, speed, target, now, clear, hold=False,
              stopping_distance=None, decision_horizon=.1, terminal=False,
              arrival_radius=2., travel_direction=1., motion_key=None,
              half_length=3.5, turn_speed_limit=None, request_key=None):
        direction = -1. if travel_direction < 0. else 1.
        if (self.request_key != request_key or self.motion_key != motion_key or
                self.travel_direction != direction):
            # A route/contact replacement retires the previous objective's
            # steering and recovery. Ordinary request identity does not impose
            # the fixed gear/alignment policy of a short cover manoeuvre.
            self._reset_motion()
            self.motion_key, self.travel_direction = motion_key, direction
            self.request_key = request_key
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
                # aligned while its whole segment remains clear. The planner
                # may replace a now-obstructed corner by another point within
                # two metres; identity alone cannot preserve the rejected one.
                ax, az = alignment[0]-position[0], alignment[2]-position[2]
                if clear(math.atan2(ax, az), math.hypot(ax, az)):
                    target = alignment
                else:
                    self.alignment_target = None
        dx, dz = target[0]-position[0], target[2]-position[2]
        distance = math.hypot(dx, dz)
        travel_heading = math.atan2(dx, dz) if distance > .1 else yaw
        heading = angle(travel_heading + (math.pi if direction < 0. else 0.))
        live_heading = heading
        delta = angle(heading-yaw)
        self.replan = False
        self.nonprogress_triggered = False
        mode, throttle, turn, brake = 'travel', 0., 0., False
        # A nonterminal corner is consumed by the pathfinder at this same
        # radius. Stopping farther away leaves an unconsumed, unreachable leg.
        alignment_gates = []
        recovery_event = None
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
            self.progress = None
            self.reverse_until = 0.
            self.forward_until = 0.
            self.forward_origin = None
            self.alignment_target = None
            self._clear_detour()
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
            recovery_blocked = False
            if self.recovery_heading is not None:
                # Retention has the current Bot's bounded age and goal-angle
                # contract, implemented with this player's own state/probes.
                # A clear hull-forward ray alone cannot renew an old branch.
                completed = self.recovery_origin is not None and math.hypot(
                    position[0]-self.recovery_origin[0],
                    position[2]-self.recovery_origin[2]) >= 3.
                recovery_event = ('completed' if completed else
                    'expired' if now >= self.recovery_until else
                    'goal_changed' if abs(angle(live_heading-self.recovery_heading)) >= DETOUR_GOAL_LIMIT else
                    'blocked' if not clear(self.recovery_heading, DETOUR_PROOF_DISTANCE) else None)
                if recovery_event is not None:
                    self._clear_detour()
                    self.replan = self.replan or recovery_event in ('completed', 'blocked')
                    # A still-blocked goal may select the same safe side, but
                    # only from a fresh goal-centred proof. If all branches
                    # fail, wait for the ordinary bounded recovery below.
                    if not clear(live_heading, DETOUR_PROOF_DISTANCE):
                        recovery_blocked = not self._choose_detour(
                            position, target, live_heading, now, clear)
                if self.recovery_heading is not None:
                    heading = self.recovery_heading
                    delta = angle(heading-yaw)
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
            if recovery_blocked:
                mode, brake = 'blocked', True
            elif align:
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
                    if self._choose_detour(position, target, live_heading, now, clear):
                        recovery_event = 'selected'
                        heading = self.recovery_heading
                        delta = angle(heading-yaw)
                        mode, brake = 'detour_align', False
                        turn = 1. if delta > 0. else -1. if delta < 0. else 0.
            self._observe_progress(position, yaw, speed, target, heading, now,
                                   float(half_length), radius)
            if now-self.anchor[2] >= 3.:
                self.nonprogress_triggered = True
                self.progress['reason'] = 'stalled_retry'
                self.progress['stalled_for'] = now-self.anchor[2]
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
        progress_receipt = None
        if self.progress is not None:
            progress = self.progress
            goal = progress['point']['goal']
            progress_receipt = dict(goal=goal,
                distance=math.hypot(goal[0]-position[0], goal[2]-position[2]),
                best=progress['point']['best'], heading=progress['heading'],
                error=abs(angle(progress['heading']-yaw)), best_error=self.alignment_best,
                reason=progress['reason'], stalled_for=progress.get('stalled_for'),
                at=self.anchor[2] if self.anchor else None,
                age=now-self.anchor[2] if self.anchor else None)
        self.receipt = dict(mode=mode, distance=distance, heading=heading,
                            travel_heading=travel_heading, direction=direction,
                            yaw=yaw, delta=delta, reverse_until=self.reverse_until,
                            forward_until=self.forward_until,
                            clearance_checks=self.clearance_checks,
                            requested_target=requested_target,
                            request_key=self.request_key,
                            recovery_heading=self.recovery_heading,
                            recovery_origin=self.recovery_origin,
                            recovery_target=self.recovery_target,
                            recovery_until=self.recovery_until,
                            recovery_event=recovery_event,
                            nonprogress_triggered=self.nonprogress_triggered,
                            translation_escape_completed=self.translation_escape_completed,
                            progress=progress_receipt,
                            alignment_target=self.alignment_target,
                            alignment_gates=alignment_gates, turn_speed_limit=traverse,
                            terminal=bool(terminal), arrival_radius=radius,
                            stopping_envelope=stopping,
                            decision_horizon=max(0., float(decision_horizon)))
        return dict(throttle=throttle, turn=turn, brake=brake, recovery_mode=mode)
