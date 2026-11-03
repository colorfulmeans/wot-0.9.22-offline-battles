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

    def apply(self, order, yaw, traffic, position=None, clear=None):
        def delta(a,b):
            return (a-b+math.pi) % (2*math.pi)-math.pi
        goal=order.get('driving',{}).get('heading',yaw)
        if (order['recovery_mode'] in ('hold','reverse_clearance') or
                self.heading is not None and abs(delta(goal,self.heading))>.35):
            self.sign,self.heading,self.advance_origin=0.,None,None
        if self.heading is not None and abs(delta(self.heading,yaw))<.25:
            self.sign,self.heading,self.advance_origin=0.,None,None
        if self.advance_origin is not None and math.hypot(
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
        if not allowed and position is not None and clear is not None and clear(yaw,4.):
            # A parked hull can obstruct pivoting even when the forward swept
            # corridor is open. Create at most three metres of turn space,
            # proving ordinary static and dynamic clearance on every update.
            if self.advance_origin is None:self.advance_origin=tuple(position)
            order.update(turn=0.,throttle=.45,brake=False,
                         recovery_mode='vehicle_turn_forward_clearance')
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
        self.blocked_queries = []
        self.peers = dict((r['id'], r) for r in neighbours)

    def clear(self, heading, reach):
        moving = dict(self.current, yaw=heading)
        hits = []
        fraction = tank_collision.translation_fraction(moving,
            (math.sin(heading)*reach,math.cos(heading)*reach),self.neighbours,contacts=hits)
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
        b = self.current
        return tank_collision.rotation_fraction((b['x'],b['y'],b['z']),b['yaw'],
            b['yaw']+turn*.15,b['shape'],self.neighbours) >= .999
