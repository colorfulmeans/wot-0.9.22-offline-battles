"""Player-owned motor attempts; ordinary physics alone moves any wreck."""
from __future__ import division
import math


class WreckPush(object):
    def __init__(self):
        self.history = {}
        self.active = None
        self.receipt = None

    def apply(self, order, state, traffic, world_clear):
        position, yaw, now = state['position'], state['yaw'], state['now']
        radius = 2.*state['half_length'] + 2.*state['half_width']
        for key, row in list(self.history.items()):
            if math.hypot(position[0]-row['origin'][0], position[2]-row['origin'][2]) > radius:
                self.history.pop(key)
        self.receipt = None
        previous, self.active = self.active, None
        if order.get('combat_mode') != 'route' or order.get('recovery_mode') == 'hold':
            return False
        goal = order.get('local_target')
        if goal is None:
            return False
        desired = math.atan2(goal[0]-position[0], goal[2]-position[2])
        delta = (desired-yaw+math.pi) % (2.*math.pi)-math.pi
        # Align with ordinary checked steering first. An admitted push is a
        # straight motor attempt, never permission to swing through a wall.
        if previous is None and (abs(delta) > .30 or order.get('recovery_mode') in
                ('reverse_clearance', 'forward_clearance')):
            return False
        reach = 2.*state['half_length'] + 2.
        peer = traffic.wreck_ahead(yaw, reach)
        if peer is None:
            return False
        key, where = peer['id'], peer['position']
        row = self.history.get(key)
        wreck_moved = row is not None and math.hypot(
            where[0]-row['wreck_origin'][0], where[2]-row['wreck_origin'][2]) >= 1.
        if row is None or row['exhausted'] and wreck_moved:
            row = dict(origin=tuple(position), wreck_origin=tuple(where),
                heading=yaw, elapsed=0., best=0., last=now, exhausted=False)
            self.history[key] = row
        progress = ((position[0]-row['origin'][0])*math.sin(row['heading']) +
                    (position[2]-row['origin'][2])*math.cos(row['heading']))
        self.receipt = dict(peer=key, phase='exhausted' if row['exhausted'] else 'checking',
            elapsed=row['elapsed'], progress=progress, best=row['best'], origin=row['origin'])
        if row['exhausted']:
            return False
        # A yaw/order change or a corpse sliding by itself is not own progress.
        renewed = progress >= row['best']+.5
        if renewed:
            row['best'], row['elapsed'] = progress, 0.
        if previous == key and not renewed:
            row['elapsed'] += max(0., now-row['last'])
        row['last'] = now
        if row['elapsed'] >= 14.:
            row['exhausted'] = True
            self.receipt.update(phase='own_stalled', elapsed=row['elapsed'])
            return False
        if not world_clear(yaw, reach):
            row['exhausted'] = True
            self.receipt['phase'] = 'world_refused'
            return False
        if traffic.sweep(yaw, reach, living_only=True)[0] < .999:
            self.receipt['phase'] = 'living_hull_blocked'
            return False
        # This only issues pedals. It bypasses no native contact, mass,
        # engine, ground or destructible rule and never edits a remote pose.
        self.active = key
        self.receipt.update(phase='pushing', elapsed=row['elapsed'], best=row['best'])
        order.update(throttle=1., turn=0., brake=False, recovery_mode='wreck_push')
        return True
