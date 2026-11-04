"""Player's local vehicle/wreck clearance, using ordinary collision geometry."""
from __future__ import division
import math
from .. import tank_collision


class TurnClearance(object):
    """Keep an admitted long-way pivot instead of undoing it next update."""
    def __init__(self):
        self.sign = 0.
        self.heading = None
        self.advance_origin = None
        self.advance_sign = 1.
        self.recovery = BlockedMotion()

    def apply(self, order, yaw, traffic, position=None, clear=None):
        def delta(a,b):
            return (a-b+math.pi) % (2*math.pi)-math.pi
        goal=order.get('driving',{}).get('heading',yaw)
        if (order['recovery_mode'] in ('hold','reverse_clearance','forward_clearance') or
                self.heading is not None and abs(delta(goal,self.heading))>.35):
            self.sign,self.heading,self.advance_origin=0.,None,None
        if self.heading is not None and abs(delta(self.heading,yaw))<.25:
            self.sign,self.heading,self.advance_origin=0.,None,None
        if self.advance_origin is not None and position is not None and math.hypot(
                position[0]-self.advance_origin[0],position[2]-self.advance_origin[2])>=3.:
            self.sign,self.heading,self.advance_origin=0.,None,None
        if self.heading is None:
            turn=order['turn']
            if not turn or traffic.can_turn(turn):
                return
            opposite=-1. if turn>0 else 1.
            if traffic.can_turn(opposite):
                self.sign,self.heading=opposite,goal
            else:
                self.sign,self.heading=(1. if turn>0 else -1.),goal
        # Continue the same pivot across the shortest-angle boundary. Normal
        # measured nonprogress recovery can still request a proved rear exit.
        allowed=traffic.can_turn(self.sign)
        if not allowed and traffic.can_turn(-self.sign):
            # A moving neighbour may release the other side first. A latched
            # preference is not authority to ignore newly proved clearance.
            self.sign = -self.sign
            allowed = True
        if not allowed and position is not None and clear is not None:
            # A parked hull can obstruct pivoting even when the forward swept
            # corridor is open. Create at most three metres of turn space,
            # proving ordinary static and dynamic clearance on every update.
            # Keep a proved escape direction across updates, including a rear
            # exit when the captured Type 62's forward corridor is occupied.
            # Recheck both native world and vehicle sweeps every update.
            directions = (self.advance_sign, -self.advance_sign)
            for sign in directions:
                if clear(yaw if sign > 0 else yaw+math.pi, 4.):
                    if self.advance_origin is None or sign != self.advance_sign:
                        self.advance_origin = tuple(position)
                    self.advance_sign = sign
                    order.update(turn=0., throttle=.45*sign, brake=False,
                        recovery_mode=('vehicle_turn_forward_clearance' if sign > 0
                                       else 'vehicle_turn_reverse_clearance'))
                    return
        order.update(turn=self.sign if allowed else 0.,throttle=0.,brake=not allowed,
                     recovery_mode='vehicle_turn_clearance_latched')



class BlockedMotion(object):
    """Own the bounded response after an ordinary motion command is refused."""
    def __init__(self):
        self.action = None
        self.wait_until = 0.
        self.rejected = {}
        self.blocked_target = None

    def apply(self, order, state, probe, report):
        now, position, yaw = state['now'], state['position'], state['yaw']
        mode = order.get('recovery_mode')
        if order.get('holding') or mode == 'hold' and not order.get('travel_intent'):
            self.__init__()
            return False
        command = (order['throttle'], order['turn'])
        refused = any(command) and not probe(*command)
        stuck_pivot = mode == 'vehicle_turn_clearance_latched' and not any(command)
        if not (self.action or self.blocked_target is not None or refused or stuck_pivot):
            return False
        if self.blocked_target is None:
            self.blocked_target = order.get('local_target')
        if self.blocked_target is not None:
            report(self.blocked_target)
        if self.action is not None:
            pedals, start, heading, deadline = self.action
            travelled = math.hypot(position[0]-start[0], position[2]-start[2])
            turned = abs((yaw-heading+math.pi) % (2.*math.pi)-math.pi)
            reached = travelled >= .55 if pedals[0] else turned >= .22
            if not reached and now < deadline and probe(pedals[0], pedals[1], .55):
                order.update(throttle=pedals[0], turn=pedals[1], brake=False,
                             recovery_mode='traffic_escape')
                return True
            if not reached:
                self.rejected[pedals] = now + 1.5
            self.action = None
            self.wait_until = now + .25
            if reached:
                self.blocked_target = None
            order.update(throttle=0., turn=0., brake=True,
                         recovery_mode='traffic_escape_rejoin' if reached else 'traffic_wait')
            return True
        if now >= self.wait_until and abs(state['speed']) < .5:
            if any(command) and not refused:
                self.blocked_target = None
                return False
            # A four-metre corridor can be blocked while a short separating
            # step is safe. Recheck each candidate including its real sweep.
            steer = -1. if command[1] < 0. else 1.
            choices = ((-.35, 0.), (.35, 0.), (-.35, -steer*.35),
                       (-.35, steer*.35), (.35, -steer*.35),
                       (.35, steer*.35), (0., -steer*.35), (0., steer*.35))
            for pedals in choices:
                if now >= self.rejected.get(pedals, 0.) and probe(pedals[0], pedals[1], .55):
                    self.action = (pedals, tuple(position), yaw, now + .9)
                    order.update(throttle=pedals[0], turn=pedals[1], brake=False,
                                 recovery_mode='traffic_escape')
                    return True
            self.wait_until = now + .3
        order.update(throttle=0., turn=0., brake=True, recovery_mode='traffic_wait')
        return True


def body(identity, position, yaw, shape, pitch=0., roll=0.):
    return dict(id=identity, kind='player', x=position[0], y=position[1], z=position[2],
                yaw=yaw, pitch=pitch, roll=roll, shape=tuple(shape))


class Traffic(object):
    def __init__(self, current, neighbours):
        self.current = current
        self.neighbours = [body(r['id'],r['position'],r['yaw'],r['collision_shape'],
                               r.get('pitch',0.),r.get('roll',0.)) for r in neighbours]
        self.receipt = {}
        self.motion_probe = None
        self.blocked_queries = []
        self.peers = dict((r['id'], r) for r in neighbours)

    def sweep(self, heading, reach, living_only=False):
        # A rear translation does not rotate the physical hull by 180 degrees.
        # Preserve front/rear offsets of asymmetric collision footprints.
        hull_heading = heading if math.cos(heading-self.current['yaw']) >= 0 else heading+math.pi
        moving = dict(self.current, yaw=hull_heading)
        hits = []
        peers = [b for b in self.neighbours if not living_only or self.peers[b['id']]['alive']]
        fraction = tank_collision.translation_fraction(moving,
            (math.sin(heading)*reach,math.cos(heading)*reach),peers,contacts=hits)
        return fraction, hits

    def wreck_ahead(self, heading, reach):
        unused, hits = self.sweep(heading, reach)
        if not hits:
            return None
        identity, unused = min(hits, key=lambda item:item[1])
        peer = self.peers[identity]
        return peer if not peer['alive'] else None

    def clear(self, heading, reach):
        fraction, hits = self.sweep(heading, reach)
        self.receipt = dict(fraction=fraction, blockers=[r[0] for r in hits],
                            heading=heading, reach=reach)
        if fraction < .999 and len(self.blocked_queries) < 12:
            self.blocked_queries.append(dict(self.receipt,
                actors=[dict(id=identity, alive=self.peers[identity]['alive'],
                    team=self.peers[identity].get('team'),
                    position=self.peers[identity]['position']) for identity, at in hits]))
        self.receipt['blocked_queries'] = self.blocked_queries
        return fraction >= .999

    def can_turn(self, turn):
        if not turn:
            return True
        if self.motion_probe is not None:
            return self.motion_probe(0., turn)
        b = self.current
        return tank_collision.rotation_fraction((b['x'],b['y'],b['z']),b['yaw'],
            b['yaw']+turn*.15,b['shape'],self.neighbours) >= .999

    def swept_command_clear(self, throttle, turn, speed, pivot_for, world_clear, reach=None):
        """Check live hull geometry along a short turn/translation horizon."""
        from ..vehicle_physics import track_pivot_position
        moving = dict(self.current)
        yaw = moving['yaw']
        step = 0.
        if throttle:
            reach = (max(1., min(5., abs(speed) * .5 + 1.)) if reach is None else
                     max(reach, abs(speed) * .35))
            step = math.copysign(reach / 3., throttle)
        for unused in range(3):
            new_yaw = yaw + turn * .12
            position = (moving['x'], moving['y'], moving['z'])
            pivot = pivot_for(turn, throttle)
            if turn and tank_collision.rotation_fraction(position, yaw, new_yaw,
                    moving['shape'], self.neighbours, pivot_offset=pivot) < .999:
                return False
            rotated = track_pivot_position(position, yaw, new_yaw, pivot)
            moving.update(x=rotated[0], z=rotated[2], yaw=new_yaw)
            translation = (math.sin(new_yaw) * step, math.cos(new_yaw) * step)
            if step and tank_collision.translation_fraction(moving, translation,
                                                            self.neighbours) < .999:
                return False
            if not world_clear(position, yaw, new_yaw, pivot, translation):
                return False
            moving['x'] += translation[0]
            moving['z'] += translation[1]
            yaw = new_yaw
        return True
