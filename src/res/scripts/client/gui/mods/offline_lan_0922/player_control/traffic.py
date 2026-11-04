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

    def swept_command_clear(self, throttle, turn, speed, pivot_for, world_clear):
        """Check live hull geometry along a short turn/translation horizon."""
        from ..vehicle_physics import track_pivot_position
        moving = dict(self.current)
        yaw = moving['yaw']
        step = 0.
        if throttle:
            reach = max(1., min(5., abs(speed) * .5 + 1.))
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
