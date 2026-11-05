"""Player-owned motor attempts; ordinary physics alone moves any wreck."""
from __future__ import division
import math
from .. import tank_collision
from .traffic import protected_hold


class WreckPush(object):
    def __init__(self):
        self.history = {}
        self.active = None
        self.receipt = None

    def _side_wreck(self, traffic):
        current = traffic.current
        candidates = []
        for peer in traffic.neighbours:
            observed = traffic.peers[peer['id']]
            if observed['alive'] or not tank_collision.vertical_overlap(
                    current['y'], current['shape'], peer['y'], peer['shape'], slop=0.,
                    pitch_a=current.get('pitch', 0.), roll_a=current.get('roll', 0.),
                    pitch_b=peer.get('pitch', 0.), roll_b=peer.get('roll', 0.)):
                continue
            contact = tank_collision._obb_overlap(
                current['x'], current['z'], current['yaw'], current['shape'],
                peer['x'], peer['z'], peer['yaw'], peer['shape'])
            forward_normal = (math.sin(current['yaw'])*contact[0]+
                              math.cos(current['yaw'])*contact[1])
            if contact[2] >= -.15 and abs(forward_normal) < .35:
                candidates.append((math.hypot(peer['x']-current['x'], peer['z']-current['z']),
                                   peer['id'], observed))
        return min(candidates, key=lambda row:row[:2])[2] if candidates else None

    def _steering_clear(self, traffic, world_clear, pose_clear, yaw, turn, reach, key, speed):
        if pose_clear is None or not traffic.can_steer(1., turn, speed,
                                                       ignore_ids=(key,), reach=reach):
            return False
        # Direction probes alone do not establish an in-place hull rotation.
        # Each proposed orientation needs the foreground's actual world-pose
        # query; only the selected pushable wreck is excluded from the separate
        # vehicle sweep. Ordinary native physics still resolves every contact.
        for index in range(1, 5):
            heading = yaw+turn*.12*index
            if not pose_clear(heading) or not world_clear(heading, reach):
                return False
        return True

    def apply(self, order, state, traffic, world_clear, pose_clear=None):
        position, yaw, now = state['position'], state['yaw'], state['now']
        radius = 2.*state['half_length'] + 2.*state['half_width']
        for key, row in list(self.history.items()):
            if math.hypot(position[0]-row['origin'][0], position[2]-row['origin'][2]) > radius:
                self.history.pop(key)
        self.receipt = None
        previous, self.active = self.active, None
        if ((order.get('combat_mode') != 'route' and not order.get('travel_intent')) or
                order.get('recovery_mode') == 'hold' or protected_hold(order) or
                order.get('cover_motion') or state.get('burst_active')):
            return False
        goal = order.get('local_target')
        if goal is None:
            return False
        desired = math.atan2(goal[0]-position[0], goal[2]-position[2])
        delta = (desired-yaw+math.pi) % (2.*math.pi)-math.pi
        reach = 2.*state['half_length'] + 2.
        peer = traffic.wreck_ahead(yaw, reach)
        side = False
        if peer is None:
            peer = self._side_wreck(traffic)
            side = peer is not None
        if peer is None or previous is None and (
                not side and abs(delta) > .30 or order.get('recovery_mode') in
                ('reverse_clearance', 'forward_clearance')):
            return False
        key, where = peer['id'], peer['position']
        row = self.history.get(key)
        wreck_moved = row is not None and math.hypot(
            where[0]-row['wreck_origin'][0], where[2]-row['wreck_origin'][2]) >= 1.
        if row is None or row['exhausted'] and wreck_moved:
            row = dict(origin=tuple(position), wreck_origin=tuple(where),
                heading=yaw, elapsed=0., best=0., last=now, exhausted=False)
            self.history[key] = row
        elif wreck_moved:
            # Consume this geometry change now. Movement during the old motor
            # attempt cannot masquerade as a new opportunity after exhaustion.
            row['wreck_origin'] = tuple(where)
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
        if traffic.sweep(yaw, reach, ignore_ids=(key,))[0] < .999:
            self.receipt['phase'] = 'living_hull_blocked'
            return False
        turn = 0.
        bearing = math.atan2(where[0]-position[0], where[2]-position[2])
        offset = (bearing-yaw+math.pi) % (2.*math.pi)-math.pi
        preferred = max(-.8, min(.8, offset/.65)) if side else 0.
        if row['elapsed'] >= 8.:
            # The steering phase belongs to the same fourteen-second motor
            # attempt. Changing yaw, planning or order cannot renew its budget.
            sign = 1. if (int((row['elapsed']-8.)/2.)+int(key)) % 2 else -1.
            preferred = .7*sign
        if preferred:
            for candidate in (preferred, -preferred):
                if self._steering_clear(traffic, world_clear, pose_clear, yaw,
                        candidate, reach, key, state.get('speed', 0.)):
                    turn = candidate
                    break
            if side and not turn:
                self.receipt['phase'] = 'side_rotation_refused'
                return False
        # This only issues pedals. It bypasses no native contact, mass,
        # engine, ground or destructible rule and never edits a remote pose.
        self.active = key
        self.receipt.update(phase='steering' if turn else 'pushing', elapsed=row['elapsed'],
                            best=row['best'], side_contact=side, turn=turn)
        order.update(throttle=1., turn=turn, brake=False, recovery_mode='wreck_push',
                     suppress_fire=True, fire_allowed=False)
        return True
