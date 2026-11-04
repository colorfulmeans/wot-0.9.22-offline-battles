"""Foreground-only direct fire, shell comparison and bounded attack search."""
from __future__ import division

import math

from ..gun_mechanics import _field


PENETRATION_FACTOR_65 = 0.9679810530375992
SEARCH_SECONDS = 8.
HE = 'HIGH_EXPLOSIVE'


class DirectEngagement(object):
    def __init__(self, descriptor):
        self.target = None
        self.stage = None
        self.last_solution = None
        self.sample = None
        self.scan = None
        self.motion = None
        self.search_since = None
        self.exhausted = set()
        self.fallback = False
        self.seek = False
        self.retreat = False
        self.laying_until = None
        self.next_clip_scan = None

    def shells(self, policy, gun):
        main = next((row for row in policy.shells if row['index'] == policy.main), None)
        rows = [row for row in policy.shells if gun.ammo[row['index']] > 0]
        if main is not None and main['kind'] == HE:
            def rank(row):
                index = row['index']
                if row['kind'] == HE:
                    return (0, index != policy.main, index)
                penetration = _field(gun.shots[index], 'piercingPower', (0., 0.))
                return (1, float(penetration[0]), index)
        else:
            def rank(row):
                premium = row.get('role') == 'premium' or row.get('premium', False)
                return (0 if row['kind'] == HE else 2 if premium else 1,
                        row['index'] != policy.main, row['index'])
        return sorted(rows, key=rank)

    def adopt(self, target, stage=None):
        self.target, self.stage = target, stage
        self.sample = self.scan = self.last_solution = self.motion = None
        self.fallback = False
        self.laying_until = self.next_clip_scan = None

    def _stationary(self, aiming, target):
        try:
            pose = aiming.direct_pose(target)
        except (AttributeError, ValueError, TypeError, RuntimeError):
            self.motion = None
            return False
        old, self.motion = self.motion, pose
        if old is None:
            return False
        for index in (0, 2):
            if sum((pose[index][axis] - old[index][axis])**2 for axis in range(3)) > .04**2:
                return False
        return all(abs((pose[i] - old[i] + math.pi) % (2.*math.pi) - math.pi) <= .005
                   for i in (1, 3, 4, 5, 6))

    def _scan(self, control, target, rows, now, mode, sample=None):
        aiming = control.aiming
        indices = tuple(row['index'] for row in rows)
        count = aiming.direct_samples(target)
        identity = (target.id, indices, mode, sample, count)
        if self.scan is None or self.scan['identity'] != identity:
            points = (sample,) if sample is not None else range(count)
            self.scan = dict(identity=identity, pending=[(index, point)
                for point in points for index in indices], hits=[], armor=False, unknown=False)
        scan = self.scan
        for unused in range(2):
            if not scan['pending']:
                break
            index, point = scan['pending'][0]
            verdict, solution = aiming.compare_direct(target, index, point, now,
                lambda a, b: control.lane_from(target, a, b),
                None if mode == 'splash' else PENETRATION_FACTOR_65,
                current_barrel=mode == 'barrel', nominal=mode == 'splash')
            if verdict == 'pending':
                return 'pending', None
            scan['pending'].pop(0)
            if verdict == 'ready':
                score = solution['nominal_armor'] if mode == 'splash' else indices.index(index)
                scan['hits'].append((score, point, indices.index(index), index))
            elif verdict == 'armor':
                scan['armor'] = True
            elif verdict == 'unknown':
                scan['unknown'] = True
        if scan['pending']:
            return 'pending', None
        self.scan = None
        if scan['hits']:
            unused_score, point, unused_rank, index = min(scan['hits'])
            return 'ready', (index, point)
        return ('armor' if scan['armor'] and not scan['unknown'] else 'unavailable'), None

    def _lay(self, control, target, index, sample, now, fallback):
        gun, aiming = control.owner._gun_state, control.aiming
        self.stage = (index, None if fallback else PENETRATION_FACTOR_65)
        if gun.shot_index != index:
            control.queue_automatic_shell(index)
            return None, None, False
        verdict, solution = aiming.compare_direct(target, index, sample, now,
            lambda a, b: control.lane_from(target, a, b), self.stage[1],
            physical=True, nominal=fallback)
        if verdict in ('ready', 'laying'):
            self.last_solution = solution
            if verdict == 'laying':
                if self.laying_until is None:
                    self.laying_until = now + 5.
                elif now >= self.laying_until:
                    aiming.defer_ordered_point(target, index, solution, now)
                    self.sample = self.last_solution = self.laying_until = None
                    return None, None, False
                return target, solution, False
            self.laying_until = None
            if not fallback:
                self.search_since = None
                self.exhausted.clear()
                self.retreat = self.seek = False
            if gun.clip_size > 1 and gun.clip == 1 and not (
                    getattr(control.owner, '_local_player_burst', None) or
                    getattr(control.owner, '_local_fire_intent', None)):
                previous = self.scan
                self.scan = self.next_clip_scan
                verdict, next_pick = self._scan(control, target,
                    self.shells(control.ammo_policy, gun), now, 'barrel', sample)
                self.next_clip_scan, self.scan = self.scan, previous
                if verdict == 'pending':
                    return target, solution, False
                control.queue_next_automatic_clip(next_pick[0] if next_pick else index)
            return target, solution, True
        if verdict != 'pending':
            self.sample = self.last_solution = None
            self.fallback = False
        if verdict == 'pending' and self.last_solution is not None:
            return target, self.last_solution, False
        return None, None, False

    def update(self, control, candidates, now):
        owner, aiming = control.owner, control.aiming
        gun, policy = owner._gun_state, control.ammo_policy
        rows = self.shells(policy, gun)
        self.seek = self.search_since is not None and not self.retreat
        held = bool(getattr(owner, '_local_fire_intent', None) or
                    getattr(owner, '_local_player_burst', None) or
                    getattr(control, 'owned_burst', None))
        by_id = dict((target.id, target) for target in candidates)
        if held:
            target = by_id.get(self.target)
            if target is not None and self.sample is not None and self.stage is not None:
                return self._lay(control, target, self.stage[0], self.sample, now, self.fallback)
            return None, None, False
        if not rows or not candidates:
            self.adopt(None)
            return None, None, False
        if self.target not in by_id:
            self.adopt(candidates[0].id)
        target = by_id[self.target]
        stationary = self._stationary(aiming, target)
        magazine = gun.clip_size > 1
        loaded = next((row for row in rows if row['index'] == gun.shot_index), None)
        keep_clip = magazine and gun.clip > 0 and loaded is not None
        if magazine and gun.clip <= 0 and gun.reload_time > 0.:
            return None, None, False
        eligible = [loaded] if keep_clip else rows
        he = [row for row in eligible if row['kind'] == HE]
        if self.stage is not None and not any(row['index'] == self.stage[0] for row in eligible):
            self.sample = self.last_solution = None
            self.fallback = False
        if self.sample is not None and self.stage is not None and (
                self.last_solution is None or self.laying_until is not None or
                self.next_clip_scan is not None and keep_clip and gun.clip == 1):
            return self._lay(control, target, self.stage[0], self.sample, now, self.fallback)
        expired = self.search_since is not None and now - self.search_since >= SEARCH_SECONDS
        if self.scan is not None and self.scan['identity'][2] == 'next' and not self.retreat:
            mode = 'next'
        elif expired and self.sample is None and self.scan is None and not self.retreat:
            mode = 'next' if keep_clip and not he else 'splash' if he else 'full'
        elif self.scan is not None and self.scan['identity'][2] == 'splash':
            mode = 'splash'
        elif self.sample is not None and stationary and (
                self.scan is None or self.scan['identity'][2] == 'barrel'):
            mode = 'barrel'
        else:
            mode = 'full'
        compare = he if mode == 'splash' else rows if mode == 'next' else eligible
        verdict, pick = self._scan(control, target, compare,
                                   now, mode, self.sample if mode == 'barrel' else None)
        if verdict == 'pending':
            if self.last_solution is not None and now - self.last_solution['created'] <= .5:
                return target, self.last_solution, False
            return None, None, False
        if mode == 'next':
            next_index = (pick[0] if pick is not None else
                          next((row['index'] for row in rows if row['kind'] == HE), gun.shot_index))
            if pick is not None and next_index == gun.shot_index:
                self.sample = pick[1]
                self.fallback = False
                return self._lay(control, target, next_index, self.sample, now, False)
            if control.reload_automatic_clip(next_index):
                self.search_since = None
                self.exhausted.clear()
            elif not he and not any(row['kind'] == HE for row in rows):
                self.retreat = True
            return None, None, False
        if pick is not None:
            index, self.sample = pick
            self.stage = (index, None if mode == 'splash' else PENETRATION_FACTOR_65)
            self.last_solution = None
            self.fallback = mode == 'splash'
            return self._lay(control, target, index, self.sample, now, self.fallback)
        if mode == 'barrel':
            self.sample = self.last_solution = None
            self.fallback = False
            return None, None, False
        self.sample = self.last_solution = None
        if verdict == 'armor' and self.search_since is None:
            self.search_since = now
        if self.search_since is None:
            self.exhausted.add(target.id)
        elif now - self.search_since >= SEARCH_SECONDS and not keep_clip and not he:
            self.retreat = True
        else:
            self.exhausted.add(target.id)
        alternate = next((item for item in candidates if item.id not in self.exhausted
                          and item.id != target.id), None)
        if alternate is not None and self.scan is None:
            self.adopt(alternate.id)
        elif self.scan is None:
            self.exhausted.clear()
            self.seek = not self.retreat
        return None, None, False
