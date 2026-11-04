"""Private authored-route parking; no Bot reservations or actor state."""
from __future__ import division
import copy
import math
from .. import bot_tactics
from .artillery import MAX_PARKING_GRADE
from .missions import distance, legal_support, STOP_SPEED, PROGRESS_TIMEOUT


class RouteParking(object):
    def __init__(self, team):
        self.team = int(team)
        self.records = {}
        self.current = None
        self.receipt = dict(phase='idle')
        self.last_completion = None

    def release(self):
        # Completed gates belong to this player's round, including a temporary
        # emergency-defence diversion. No shared slot claim is ever installed.
        self.current = None
        self.receipt = dict(phase='idle')

    def _occupied(self, place, height, state, context):
        radius = math.hypot(state['half_length'], state['half_width'])
        own = state.get('engine_id', state['id'])
        rows = list(context.get('allies') or ()) + list(context.get('contacts') or ())
        rows += [row for row in context.get('neighbours') or ()
                 if row.get('team') == self.team or row.get('visible')]
        for row in rows:
            position = row.get('position')
            if row.get('id') == own or position is None:
                continue
            shape = row.get('collision_shape') or (1., 2.)
            other = math.hypot(float(shape[0]), float(shape[1]))
            if (abs(float(position[1]) - height) <= max(3., radius) and
                    distance(position, place) < radius + other + .5):
                return True
        return False

    def _finish(self, record, reason):
        record['complete'] = True
        record['reason'] = reason
        self.receipt = dict(phase='completed', reason=reason, route=self.current[0],
                            gate=self.current[1], slot=record.get('slot'),
                            arrived_at=record.get('arrived_at'), duration=record.get('duration'))
        self.last_completion = dict(self.receipt)
        return dict(phase='completed', complete=True, holding=False,
                    skipped=reason != 'authored_wait_elapsed')

    @staticmethod
    def _unknown(evidence):
        return evidence is None or evidence().get('status') not in (
            'water', 'disconnected', 'outside_bounds')

    def _candidate(self, place, state, height, evidence, scan):
        centre = height(place[:2], state['position'][1])
        if centre is None:
            return ('unknown' if self._unknown(evidence) else 'rejected'), None
        reach = math.hypot(state['half_length'], state['half_width']) + 2.5
        # A complete footprint can exceed one native decision's query budget.
        # Preserve only this player's short-lived positive planning evidence;
        # the current centre and realised hull support are still rechecked.
        # A moved hull, changed surface or stale sample restarts the scan.
        now, position = float(state['now']), state['position']
        generation = evidence().get('generation') if evidence is not None else None
        if (not scan or not 0. <= now - scan['at'] <= .5 or
                abs(centre - scan['centre']) > .01 or reach != scan['reach'] or
                generation != scan.get('generation') or
                math.sqrt(sum((a-b)**2 for a, b in zip(position, scan['origin']))) > .25):
            scan.clear()
            scan.update(at=now, origin=tuple(position), centre=centre,
                        reach=reach, generation=generation, verified=0)
        for index in range(scan['verified'], 8):
            heading = index * math.pi / 4.
            sample = (place[0] + math.sin(heading) * reach,
                      place[1] + math.cos(heading) * reach)
            supported = height(sample, centre)
            if supported is None:
                return ('unknown' if self._unknown(evidence) else 'rejected'), None
            if abs(supported - centre) > reach * MAX_PARKING_GRADE:
                return 'rejected', None
            scan['verified'] = index + 1
        return 'supported', (place[0], centre, place[1])

    def _defer(self, record, now, reason):
        if record.get('evidence_since') is None:
            record['evidence_since'] = now
        if now - record['evidence_since'] >= PROGRESS_TIMEOUT:
            return self._finish(record, 'parking_evidence_timeout')
        return self._result(record, 'recheck', None, True, now, reason)

    def update(self, route, index, state, context, height, evidence=None):
        places = bot_tactics.waiting_positions(route['waypoints'][index])
        if not places:
            self.release()
            return dict(phase='idle', complete=True, holding=False)
        key = (str(route['id']), int(index))
        self.current = key
        now, position = float(state['now']), state['position']
        record = self.records.setdefault(key, dict(complete=False, slot=None,
            arrived_at=None, arrival=None, duration=None, progress_at=now,
            progress_position=tuple(position), best=None))
        if record['complete']:
            return dict(phase='completed', complete=True, holding=False,
                        skipped=record.get('reason') != 'authored_wait_elapsed')
        if context.get('empty_ammo'):
            return self._finish(record, 'empty_ammo_skip')
        radius = math.hypot(state['half_length'], state['half_width'])
        supported = legal_support(state, context, height((position[0], position[2]), position[1]))
        arrived, arrival = record['arrived_at'], record['arrival']
        if arrived is not None:
            if record['duration'] >= 0. and now - arrived >= record['duration']:
                return self._finish(record, 'authored_wait_elapsed')
            displaced = distance(position, arrival)
            if (supported and displaced <= radius * 2. and
                    abs(position[1] - arrival[1]) <= 1. + displaced * math.tan(math.radians(27.5))):
                record['rechecking'] = False
                record['evidence_since'] = None
                return self._result(record, 'waiting', tuple(position), True, now)
            if not record.get('rechecking'):
                record['rechecking'] = True
                record['progress_at'], record['progress_position'] = now, tuple(position)
        reason = 'parking_candidate'
        if record['slot'] is not None:
            place = places[record['slot']]
            candidate_height = height(place[:2], position[1])
            if candidate_height is None and self._unknown(evidence):
                return self._defer(record, now, 'parking_support_unknown')
            if candidate_height is None or self._occupied(place[:2], candidate_height, state, context):
                record['slot'] = None
                reason = 'parking_recheck'
        if record['slot'] is None:
            unknown = False
            for slot, place in enumerate(places):
                scan = record.setdefault('scans', {}).setdefault(slot, {})
                status, candidate = self._candidate(place, state, height, evidence, scan)
                unknown = unknown or status == 'unknown'
                if candidate is None or self._occupied(place[:2], candidate[1], state, context):
                    continue
                record['slot'] = slot
                record['goal'] = candidate
                record['duration'] = float(place[2])
                record['best'] = distance(position, record['goal'])
                record['progress_at'] = now
                record['progress_position'] = tuple(position)
                break
            if record['slot'] is None:
                if unknown:
                    return self._defer(record, now, 'parking_geometry_unknown')
                return self._finish(record, 'no_supported_unoccupied_parking')
        place = places[record['slot']]
        candidate_height = height(place[:2], position[1])
        if candidate_height is None:
            return self._defer(record, now, 'parking_support_unknown')
        record['evidence_since'] = None
        goal = (place[0], candidate_height, place[1])
        record['goal'] = goal
        remaining = distance(position, goal)
        if (record['best'] is None or remaining < record['best'] - .5 or
                distance(position, record['progress_position']) >= 2.):
            record['best'] = remaining
            record['progress_at'], record['progress_position'] = now, tuple(position)
        if now - record['progress_at'] >= PROGRESS_TIMEOUT:
            return self._finish(record, 'blocked_approach_timeout')
        reached = (supported and remaining <= bot_tactics.ROUTE_ARRIVAL_RADIUS and
                   abs(position[1] - candidate_height) <= 1. + remaining * math.tan(math.radians(27.5)))
        if reached:
            if abs(state['speed']) > STOP_SPEED:
                return self._result(record, 'arriving', goal, True, now)
            if record['arrived_at'] is None:
                record['arrived_at'], record['arrival'] = now, tuple(position)
            if record['duration'] == 0.:
                return self._finish(record, 'authored_wait_elapsed')
            return self._result(record, 'waiting', tuple(position), True, now)
        return self._result(record, 'recheck' if arrived is not None else 'approach',
                            goal, False, now, reason)

    def _result(self, record, phase, goal, holding, now, reason=None):
        self.receipt = dict(phase=phase, route=self.current[0], gate=self.current[1],
            slot=record['slot'], goal=record.get('goal'), arrived_at=record['arrived_at'],
            duration=record['duration'], elapsed=(None if record['arrived_at'] is None else
                now - record['arrived_at']), reason=reason or phase)
        return dict(phase=phase, complete=False, holding=bool(holding), goal=goal)

    def snapshot(self):
        result = copy.deepcopy(self.receipt)
        if self.last_completion is not None:
            result['previous'] = dict(self.last_completion)
        return result
