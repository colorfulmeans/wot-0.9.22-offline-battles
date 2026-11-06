"""Observed-world route modifiers owned by one foreground player.

These modifiers neither allocate team lanes nor borrow another controller's
orders. They propose a finite, checked target; ordinary driving, traffic and
the native contact solver still decide whether the hull can actually move.
"""
from __future__ import division
import math

from .. import tank_collision
from .pathfinding import BAKED_FATAL_HAZARDS, BAKED_SHALLOW_WATER, WAYPOINT_ARRIVAL_RADIUS


def _finite(value):
    value = float(value)
    return not (math.isnan(value) or math.isinf(value))


def _distance(first, second):
    return math.hypot(first[0] - second[0], first[2] - second[2])


class LocalRoutes(object):
    """Local observation state, deliberately separate from A* search state."""
    def __init__(self, navigator, support, team):
        self.navigator, self.support, self.team = navigator, support, int(team)
        self.leg = None
        self.finished = {}
        self.finished_order = []
        self.lane = None
        self.receipt = dict(status='idle')
        self.static_receipt = dict(count=0, changed=False)
        self.stationary_receipt = dict(count=0, changed=False)

    def reset(self):
        self.leg = self.lane = None
        self.finished.clear()
        self.finished_order[:] = []
        self.receipt = dict(status='idle')

    def publish(self, state, context):
        """Publish only physical wreck/turret poses observed by this client.

        Updating a pose retires affected global corridors. The exact native
        motion sweep remains authoritative; this is not a collision bypass.
        A missing observation channel must not erase a previous publication.
        """
        publish = getattr(self.navigator.grid, 'set_static_hulls', None)
        if not callable(publish) or not ('neighbours' in context or 'turret_hulls' in context):
            return
        hulls, invalid = [], 0
        for body in context.get('neighbours', ()):
            if body.get('alive', True) or body.get('id') == state.get('engine_id'):
                continue
            try:
                shape, point = body['collision_shape'], body['position']
                hull = (int(body['id']), float(point[0]), float(point[2]),
                        float(body.get('yaw', 0.)), float(shape[1]), float(shape[0]))
                if not all(_finite(value) for value in hull[1:]) or min(hull[4:]) <= 0.:
                    raise ValueError('invalid observed hull')
                hulls.append(hull)
            except (KeyError, IndexError, TypeError, ValueError, OverflowError):
                invalid += 1
        for raw in context.get('turret_hulls', ()):
            try:
                hull = (int(raw[0]),) + tuple(float(value) for value in raw[1:])
                if len(hull) != 6 or not all(_finite(value) for value in hull[1:]) or min(hull[4:]) <= 0.:
                    raise ValueError('invalid observed turret')
                hulls.append(hull)
            except (KeyError, IndexError, TypeError, ValueError, OverflowError):
                invalid += 1
        changed = publish(hulls, clearance=state['half_width'])
        self.static_receipt = dict(count=len(hulls), invalid=invalid,
            changed=bool(changed), revision=getattr(self.navigator.grid, 'static_hull_revision', 0))
        stationary = getattr(self.navigator, 'set_stationary_hulls', None)
        if callable(stationary) and 'neighbours' in context:
            living, invalid = [], 0
            for raw, point, unused in self._bodies(state, context):
                if not raw.get('alive', True) or _distance(state['position'], point) > 32.:
                    continue
                try:
                    # Missing motion evidence is not proof that an observed
                    # live hull is parked. Never infer an unseen enemy's pose.
                    velocity = raw.get('velocity')
                    speed = (math.hypot(velocity[0], velocity[2]) if velocity is not None
                             else abs(float(raw['speed'])))
                    shape = tuple(float(value) for value in raw['collision_shape'])
                    yaw = float(raw['yaw'])
                    if (len(shape) < 4 or min(shape[:2]) <= 0. or shape[3] < shape[2] or
                            not all(_finite(value) for value in tuple(point)+shape+(yaw, speed))):
                        raise ValueError('invalid stationary hull')
                    if speed > .5:
                        continue
                    living.append(dict(raw, position=point, collision_shape=shape, yaw=yaw))
                except (KeyError, IndexError, TypeError, ValueError, OverflowError):
                    invalid += 1
            shape = state.get('collision_shape') or (
                state['half_width'], state['half_length'], -.5, 2.)
            self.stationary_receipt = stationary(state['id'], living, shape, state['half_width'])
            self.stationary_receipt.update(invalid=invalid, actors=[body['id'] for body in living])

    def _bodies(self, state, context, stationary=True):
        result = []
        for raw in context.get('neighbours', ()):
            if raw.get('id') == state.get('engine_id'):
                continue
            # A streamed but unspotted enemy is not a tactical observation.
            # Its physical collision is still checked by the native driver.
            if raw.get('alive', True) and raw.get('team') != self.team and not raw.get('visible'):
                continue
            if stationary and raw.get('alive', True):
                velocity = raw.get('velocity')
                measured = (math.hypot(velocity[0], velocity[2]) if velocity is not None
                            else abs(raw['speed']) if raw.get('speed') is not None else None)
                if measured is None or not _finite(measured) or measured > .5:
                    continue
            point, shape = raw.get('position'), raw.get('collision_shape')
            if point is None or shape is None:
                continue
            result.append((raw, tuple(point), math.hypot(shape[0], shape[1])))
        return result

    @staticmethod
    def _same_level(state, height, raw):
        shape = raw['collision_shape']
        own_shape = state.get('collision_shape') or (state['half_width'], state['half_length'], -.5, 2.)
        if len(shape) >= 4:
            return tank_collision.vertical_overlap(height, own_shape,
                raw['position'][1], shape, slop=0., pitch_a=state.get('pitch', 0.),
                roll_a=state.get('roll', 0.), pitch_b=raw.get('pitch', 0.), roll_b=raw.get('roll', 0.))
        return abs(raw['position'][1] - height) <= 3.

    def _occupied(self, point, bodies, radius, state):
        return any(_distance(point, body) < radius + other + .5 and self._same_level(state, point[1], raw)
                   for raw, body, other in bodies)

    def _corridor_free(self, position, target, bodies, radius, state):
        dx, dz = target[0] - position[0], target[2] - position[2]
        length2 = max(.01, dx * dx + dz * dz)
        for raw, point, other in bodies:
            bx, bz = point[0] - position[0], point[2] - position[2]
            projection = bx * dx + bz * dz
            fraction = max(0., min(1., projection / length2))
            if math.hypot(bx - dx * fraction, bz - dz * fraction) < radius + other + .5:
                height = self.support.height((position[0] + dx * fraction, position[2] + dz * fraction),
                    position[1] + (target[1] - position[1]) * fraction)
                if height is not None and not self._same_level(state, height, raw):
                    continue
                # An existing touch may escape outwards, never through the peer.
                if projection > 0.:
                    return False
        return True

    def _admit(self, state, target, clear, bodies):
        grid, position, now = self.navigator.grid, state['position'], state['now']
        reach = _distance(position, target)
        if reach <= 1.5:
            return False
        radius = math.hypot(state['half_length'], state['half_width'])
        if self._occupied(target, bodies, radius, state) or not self._corridor_free(position, target, bodies, radius, state):
            return False
        penalty = getattr(self.navigator, 'player_segment_penalized', None)
        if callable(penalty) and penalty(state['id'], position, target, now):
            return False
        mask = BAKED_FATAL_HAZARDS | BAKED_SHALLOW_WATER
        for name, args in (('point_has_baked_hazard', (target, mask)),
                           ('segment_has_baked_hazard', (position, target, mask))):
            probe = getattr(grid, name, None)
            if callable(probe) and probe(*args):
                return False
        proof = getattr(grid, 'dry_segment_clear', None)
        if not callable(proof):
            return False
        revision = getattr(grid, '_native_proof_revision', 0)
        if getattr(grid, '_proof_deferred', False):
            return False
        previous = getattr(self.navigator, '_boundary_actor', None)
        self.navigator._boundary_actor = int(state['id'])
        try:
            if not proof(position, target, now):
                return False
            if (revision != getattr(grid, '_native_proof_revision', 0) or
                    getattr(grid, '_proof_deferred', False)):
                return False
        finally:
            self.navigator._boundary_actor = previous
        heading = math.atan2(target[0] - position[0], target[2] - position[2])
        footprint = getattr(grid, 'hull_pose_clear', None)
        if callable(footprint) and not footprint(target, heading, state['half_length'], state['half_width']):
            return False
        return bool(clear(heading, reach))

    def _point(self, x, z, hint):
        height = self.support.height((x, z), hint)
        return None if height is None else (x, height, z)

    def _record_finished(self, key, reason):
        if key not in self.finished:
            self.finished_order.append(key)
        self.finished[key] = reason
        if len(self.finished_order) > 16:
            self.finished.pop(self.finished_order.pop(0), None)

    def _finish(self, key, reason, now):
        # History belongs to route intent, not a changing world revision.
        self._record_finished(key, reason)
        self.leg = None
        self.receipt.update(status=reason, finished_at=now)

    def _occupied_target(self, state, context, goal, selected, key, clear):
        position, now = state['position'], state['now']
        if (_distance(position, goal) > 32. or
                _distance(position, goal) <= WAYPOINT_ARRIVAL_RADIUS):
            return None
        nav_state = getattr(self.navigator, 'player_states', {}).get(int(state['id']), {})
        # Only the independent pathfinder's bounded retry starts a new attempt.
        # A corpse pose/global revision never renews a consumed local leg.
        gate = (tuple(key), tuple(goal), nav_state.get('replan_generation', 0))
        retained = self.leg is not None and self.leg['key'] == gate
        if _distance(selected, goal) > WAYPOINT_ARRIVAL_RADIUS and not (retained and
                _distance(selected, self.leg['target']) <= 1.e-4):
            # Enclosing circles reserve space at a destination; they do not
            # prove an intermediate A* corner is physically occupied. Exact
            # private hull admission and the motion sweep own those segments.
            return None
        bodies = self._bodies(state, context)
        radius = math.hypot(state['half_length'], state['half_width'])
        if not self._occupied(goal, bodies, radius, state):
            if self.leg is not None and self.leg['key'] == gate:
                self.leg = None
            return None
        self.receipt = dict(status='occupied_endpoint', goal=tuple(goal), at=now)
        if gate in self.finished:
            self.receipt['status'] = self.finished[gate]
            # Completing this modifier yields to the original checked path.
            # A circle-only reservation is not a permanent physical hold.
            return None
        if self.leg is not None and self.leg['key'] == gate:
            leg = self.leg
            remaining = _distance(position, leg['target'])
            if remaining <= 1.5:
                self._finish(gate, 'bypass_completed', now)
                return None
            if remaining < leg['best'] - .2:
                leg['best'], leg['progress_at'] = remaining, now
            if now - leg['progress_at'] >= 8.:
                self._finish(gate, 'bypass_stalled', now)
                return None
            if self._admit(state, leg['target'], clear, bodies):
                self.receipt.update(status='bypass_retained', target=leg['target'])
                return leg['target']
            self._finish(gate, 'bypass_refused', now)
            return None
        dx, dz = goal[0] - position[0], goal[2] - position[2]
        length = max(.01, math.hypot(dx, dz))
        forward = (dx / length, dz / length)
        for reach in (8., 12.):
            for ox, oz in ((forward[1], -forward[0]), (-forward[1], forward[0]),
                           forward, (-forward[0], -forward[1])):
                target = self._point(goal[0] + ox * reach, goal[2] + oz * reach, goal[1])
                if target is None or not self._admit(state, target, clear, bodies):
                    continue
                self.leg = dict(key=gate, target=target, origin=tuple(position),
                                progress_at=now, best=_distance(position, target))
                self.receipt.update(status='bypass_issued', target=target)
                return target
        self.receipt['status'] = 'no_checked_bypass'
        return None

    def _lane_target(self, state, context, goal, selected, key, clear):
        position = state['position']
        now, lane_key = state['now'], ('observed_lane', tuple(key))
        bodies = self._bodies(state, context, stationary=False)
        if self.lane is not None and self.lane['key'] == lane_key:
            lane = self.lane
            remaining = _distance(position, lane['target'])
            if remaining <= 1.5 and lane['phase'] == 'entry':
                lane.update(target=lane['exit'], phase='passing', progress_at=now,
                            best=_distance(position, lane['exit']))
                remaining = lane['best']
            elif remaining <= 1.5:
                self._record_finished(lane_key, 'lane_completed')
                self.lane = None
                return selected
            if remaining < lane['best'] - .2:
                lane['best'], lane['progress_at'] = remaining, now
            if now - lane['progress_at'] >= 8. or not self._admit(state, lane['target'], clear, bodies):
                self._record_finished(lane_key, 'lane_refused')
                self.lane = None
                return selected
            self.receipt = dict(status='observed_lane', target=lane['target'],
                                phase=lane['phase'], offset=lane['offset'], peers=lane['peers'])
            return lane['target']
        if lane_key in self.finished:
            return selected
        dx, dz = selected[0] - position[0], selected[2] - position[2]
        length = math.hypot(dx, dz)
        if length <= 4. or _distance(position, goal) < 8.:
            self.lane = None
            return selected
        forward, side = (dx / length, dz / length), (dz / length, -dx / length)
        leaders = []
        for raw, point, radius in bodies:
            if not raw.get('alive', True) or raw.get('team') != self.team:
                continue
            if not self._same_level(state, position[1], raw):
                continue
            heading = raw.get('yaw', 0.)
            if math.sin(heading) * forward[0] + math.cos(heading) * forward[1] < .7:
                continue
            px, pz = point[0] - position[0], point[2] - position[2]
            along, across = px * forward[0] + pz * forward[1], px * side[0] + pz * side[1]
            if 0. < along < 24. and abs(across) < radius + state['half_width']:
                leaders.append((raw, point, radius, along))
        if not leaders:
            self.lane = None
            return selected
        # Same observed traffic always prefers its own right-hand side. There
        # is no omniscient route cohort, leased slot, or server-side lane state.
        radius = math.hypot(state['half_length'], state['half_width'])
        peer = min(leaders, key=lambda body: body[3])
        offset = radius + peer[2] + 1.
        advance = min(6., max(2., peer[3] - radius - peer[2] - 1.))
        exit_distance = peer[3] + radius + peer[2] + 3.
        if exit_distance > _distance(position, goal):
            return selected  # No space to pass before the actual objective.
        for scale in (1., 1.3):
            target = self._point(position[0] + forward[0] * advance + side[0] * offset * scale,
                                 position[2] + forward[1] * advance + side[1] * offset * scale, selected[1])
            if target is None or not self._admit(state, target, clear, bodies):
                continue
            exit_point = self._point(position[0] + forward[0] * exit_distance + side[0] * offset * scale,
                                     position[2] + forward[1] * exit_distance + side[1] * offset * scale, selected[1])
            if exit_point is None:
                continue
            self.lane = dict(key=lane_key, offset=offset * scale, target=target, exit=exit_point,
                phase='entry', progress_at=now, best=_distance(position, target),
                peers=[body[0]['id'] for body in leaders])
            self.receipt = dict(status='observed_lane', target=target, phase='entry',
                                offset=offset * scale, peers=list(self.lane['peers']))
            return target
        return selected

    def adjust(self, state, context, goal, selected, key, clear, allow_lane=True):
        """Preserve checked corners and keep the whole body on a narrow axis."""
        self.receipt = dict(status='unchanged')
        identity, now, position = state['id'], state['now'], state['position']
        nav_state = getattr(self.navigator, 'player_states', {}).get(int(identity), {})
        if nav_state.get('controlled_shallow_target') is not None:
            return selected  # Never broaden a scoped ford proof into a lane.
        narrow = getattr(self.navigator, 'narrow_passage_target', None)
        target = selected
        bypass = None
        if callable(narrow):
            target = narrow(identity, position, goal, selected, now, state['yaw'],
                            state['half_length'], state['half_width'])
        if tuple(target) != tuple(selected):
            self.receipt = dict(status='narrow_passage', target=tuple(target))
        else:
            bypass = self._occupied_target(state, context, goal, selected, key, clear)
            if bypass is not None:
                target = bypass
            elif allow_lane and self.receipt['status'] == 'unchanged':
                target = self._lane_target(state, context, goal, selected, key, clear)
        if tuple(target) != tuple(selected):
            if _distance(position, target) <= WAYPOINT_ARRIVAL_RADIUS:
                return target  # A refusal is not a new zero-length local leg.
            remember = getattr(self.navigator, 'remember_runtime_target', None)
            if callable(remember) and not remember(identity, position, goal, target, now):
                self.receipt = dict(status='private_refusal', target=tuple(target))
                # Do not restore the very occupied corner whose bypass was
                # refused. Its original path cursor remains unconsumed.
                return tuple(position) if bypass is not None else selected
        return target

    def snapshot(self):
        return dict(self.receipt, static_hulls=dict(self.static_receipt),
                    stationary_hulls=dict(self.stationary_receipt))
