"""Foreground-only direct fire, shell comparison and bounded attack search."""
from __future__ import division

import math

from ..gun_mechanics import _field


PENETRATION_FACTOR_65 = 0.9679810530375992
SEARCH_SECONDS = 8.
POSITION_SECONDS = 6.
OWN_RESCAN_SECONDS = .7
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
        self.search_expired = False
        self.exhausted = set()
        self.fallback = False
        self.seek = False
        self.retreat = False
        self.laying_until = None
        self.next_clip_scan = None
        self.checking = False
        self.last_full_at = None
        self.laying_error = None
        self.phase = 'turret'
        self.phase_since = None
        self.receipt = dict(phase='turret')
        self.tried = set()
        self.point_since = None
        self.fallback_due = False
        self.engaged_targets = set()
        self.active_engagement = False
        self.checked_targets = set()
        self.visible_targets = set()
        self.clear_for_cruise = False

    def movement_stage(self, now, stopped, permitted, ready=False, active=False):
        """One encounter clock; changing point, target or destination cannot renew it."""
        previous = self.phase
        self.active_engagement = bool(active)
        if not active:
            self.phase, self.phase_since = 'turret', None
            self.search_expired = self.retreat = self.seek = False
            self.search_since = None
        elif ready:
            self.phase, self.phase_since = 'turret', None
            self.search_expired = self.retreat = self.seek = False
            self.search_since = None
        elif self.target is None:
            self.phase, self.phase_since = 'turret', None
            self.search_since = None
            self.search_expired = self.retreat = self.seek = False
        elif not permitted:
            # Missions own travel. Capture keeps scanning without spending a
            # movement deadline that it cannot exercise.
            self.phase, self.phase_since = 'turret', None
            self.search_since = None
            self.search_expired = self.retreat = self.seek = False
        elif self.phase_since is None and stopped:
            self.phase_since = now
        elif self.phase == 'turret' and self.phase_since is not None and now-self.phase_since >= SEARCH_SECONDS:
            self.phase, self.phase_since = 'position', now
        elif self.phase == 'position' and now-self.phase_since >= POSITION_SECONDS:
            self.phase, self.phase_since = 'retreat', now
        self.seek = self.phase == 'position'
        self.retreat = self.phase == 'retreat'
        self.search_since = self.phase_since
        self.search_expired = self.retreat
        self.receipt.update(phase=self.phase, since=self.phase_since, active=bool(active),
            admitted_targets=sorted(self.engaged_targets), cruise_scan_complete=self.clear_for_cruise,
            elapsed=0. if self.phase_since is None else now-self.phase_since,
            previous=previous, transition=previous != self.phase,
            reason='no_admitted_engagement' if not active else 'ray_ready' if ready else 'movement_prohibited' if not permitted else
                   'turret_timeout' if previous == 'turret' and self.seek else
                   'position_timeout' if previous == 'position' and self.retreat else 'search')
        return self.phase

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
        self.laying_until = self.next_clip_scan = self.last_full_at = self.laying_error = None
        self.checking = False
        self.tried.clear()
        self.point_since = None
        self.fallback_due = False

    def _motion_changes(self, aiming, target):
        try:
            pose = aiming.direct_pose(target)
        except (AttributeError, ValueError, TypeError, RuntimeError):
            return True, False, None
        if self.motion is None:
            return True, False, pose
        def changed(index, angles):
            if sum((pose[index][axis] - self.motion[index][axis])**2 for axis in range(3)) > .04**2:
                return True
            return any(abs((pose[i] - self.motion[i] + math.pi) % (2.*math.pi) - math.pi) > .005
                       for i in angles)
        return changed(2, (3, 4, 5, 6)), changed(0, (1,)), pose

    def _scan(self, control, target, rows, now, mode, sample=None):
        aiming = control.aiming
        indices = tuple(row['index'] for row in rows)
        count = aiming.direct_samples(target)
        identity = (target.id, indices, mode, sample, count)
        if self.scan is None or self.scan['identity'] != identity:
            points = (sample,) if sample is not None else range(count)
            self.scan = dict(identity=identity, pending=[(index, point)
                for point in points for index in indices
                if mode != 'full' or (index, point) not in self.tried], hits=[], armor=False, unknown=False)
        scan = self.scan
        for unused in range(min(2, len(scan['pending']))):
            if not scan['pending']:
                break
            index, point = scan['pending'].pop(0)
            verdict, solution = aiming.compare_direct(target, index, point, now,
                lambda a, b: control.lane_from(target, a, b),
                None if mode == 'splash' else PENETRATION_FACTOR_65,
                current_barrel=mode == 'barrel', nominal=mode == 'splash', prepare=mode == 'full')
            self.receipt.setdefault('candidates', []).append(dict(
                target=target.id, index=index, sample=point, verdict=verdict, mode=mode, at=now,
                reason=(solution or {}).get('reason'),
                geometry_clear=(solution or {}).get('geometry_clear'),
                reachable=(solution or {}).get('reachable')))
            if verdict == 'pending':
                scan['pending'].append((index, point))
                continue
            if verdict == 'ready' and mode == 'full':
                self.engaged_targets.add(target.id)
                self.checked_targets.discard(target.id)
                self.clear_for_cruise = False
                self.scan = None
                return 'ready', (index, point)
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
        return ('unknown' if scan['unknown'] else 'armor' if scan['armor'] else 'unavailable'), None

    def _lay(self, control, target, index, sample, now, fallback):
        gun, aiming = control.owner._gun_state, control.aiming
        self.stage = (index, None if fallback else PENETRATION_FACTOR_65)
        if self.point_since is None:
            self.point_since = now
        if gun.shot_index != index:
            if now-self.point_since >= 5.:
                self.tried.add((index, sample))
                self.sample = self.last_solution = self.point_since = None
                self.receipt['physical'] = dict(target=target.id, index=index,
                                                sample=sample, verdict='shell_timeout', at=now)
            else:
                control.queue_automatic_shell(index)
            return None, None, False
        verdict, solution = aiming.compare_direct(target, index, sample, now,
            lambda a, b: control.lane_from(target, a, b), self.stage[1],
            physical=True, nominal=fallback)
        if (verdict == 'pending' and now-self.point_since >= .5) or (
                verdict == 'laying' and now-self.point_since >= 5.):
            verdict = 'point_timeout'
        self.receipt['physical'] = dict(target=target.id, index=index, sample=sample, verdict=verdict, at=now)
        if verdict in ('ready', 'laying'):
            self.engaged_targets.add(target.id)
            self.clear_for_cruise = False
            self.last_solution = solution
            if verdict == 'laying':
                self.laying_until = self.point_since + 5.
                self.laying_error = solution.get('barrel_error')
                return target, solution, False
            self.laying_until = self.laying_error = None
            if not fallback:
                self.exhausted.clear()
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
        self.checking = verdict == 'pending'
        if verdict != 'pending':
            self.tried.add((index, sample))
            self.point_since = None
            self.laying_until = self.laying_error = None
            self.sample = self.last_solution = None
            self.fallback = False
        if verdict == 'pending' and self.last_solution is not None:
            return target, self.last_solution, False
        return None, None, False

    def update(self, control, candidates, now):
        owner, aiming = control.owner, control.aiming
        gun, policy = owner._gun_state, control.ammo_policy
        rows = self.shells(policy, gun)
        self.checking = False
        self.receipt.update(candidates=[], visible=[item.id for item in candidates], at=now)
        held = bool(getattr(owner, '_local_fire_intent', None) or
                    getattr(owner, '_local_player_burst', None) or
                    getattr(control, 'owned_burst', None))
        by_id = dict((target.id, target) for target in candidates)
        visible = set(by_id)
        if visible != self.visible_targets:
            self.checked_targets.intersection_update(visible)
            self.clear_for_cruise = not visible
            self.visible_targets = visible
        self.engaged_targets.intersection_update(visible)
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
        target_moved, own_moved, pose = self._motion_changes(aiming, target)
        facing = getattr(control, 'last_order', {}).get('combat_facing', {})
        if (own_moved and self.motion is not None and facing.get('target') == target.id
                and facing.get('state') in ('turning', 'settling', 'aligned')
                and sum((pose[0][axis] - self.motion[0][axis])**2 for axis in range(3)) <= .5**2):
            # A controlled pivot already has an admitted point. Recheck it
            # against the live barrel without using hull yaw to restart a scan.
            self.motion = pose[:2] + self.motion[2:]
            own_moved = False
        own_due = own_moved and (self.last_full_at is None or
                                 now - self.last_full_at >= OWN_RESCAN_SECONDS)
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
        if self.scan is not None and self.scan['identity'][2] == 'next':
            mode = 'next'
        elif self.fallback_due and self.search_expired and self.sample is None and self.scan is None:
            mode = 'next' if keep_clip and not he else 'splash' if he else 'full'
        elif self.scan is not None and self.scan['identity'][2] == 'splash':
            mode = 'splash'
        elif self.scan is not None and self.scan['identity'][2] == 'full':
            mode = 'full'
        elif self.sample is not None and not (target_moved or own_due or self.fallback):
            mode = 'barrel'
        elif (self.sample is None and own_moved and not target_moved and not own_due
                and self.last_full_at is not None):
            self.checking = True
            return None, None, False
        else:
            mode = 'full'
        if mode == 'full' and (self.scan is None or self.scan['identity'][2] != 'full'):
            self.motion = pose
            self.last_full_at = now
        compare = he if mode == 'splash' else rows if mode == 'next' else eligible
        verdict, pick = self._scan(control, target, compare,
                                   now, mode, self.sample if mode == 'barrel' else None)
        if verdict == 'pending':
            self.checking = True
            if self.last_solution is not None and now - self.last_solution['created'] <= .5:
                return target, self.last_solution, False
            return None, None, False
        if mode == 'next':
            self.fallback_due = False
            next_index = (pick[0] if pick is not None else
                          next((row['index'] for row in rows if row['kind'] == HE), gun.shot_index))
            if pick is not None and next_index == gun.shot_index:
                self.sample = pick[1]
                self.fallback = False
                return self._lay(control, target, next_index, self.sample, now, False)
            if control.reload_automatic_clip(next_index):
                self.exhausted.clear()
            return None, None, False
        if pick is not None:
            self.fallback_due = False
            index, self.sample = pick
            self.stage = (index, None if mode == 'splash' else PENETRATION_FACTOR_65)
            self.last_solution = None
            self.point_since = now
            self.laying_until = self.laying_error = None
            self.fallback = mode == 'splash'
            return self._lay(control, target, index, self.sample, now, self.fallback)
        if mode == 'barrel':
            self.tried.add((self.stage[0], self.sample))
            self.point_since = None
            self.sample = self.last_solution = None
            self.fallback = False
            return None, None, False
        self.sample = self.last_solution = None
        self.tried.clear()
        self.fallback_due = mode == 'full' and self.search_expired
        self.exhausted.add(target.id)
        if mode == 'full':
            if verdict == 'unavailable':
                self.checked_targets.add(target.id)
            else:
                self.checked_targets.discard(target.id)
            self.clear_for_cruise = self.visible_targets.issubset(self.checked_targets)
        alternate = next((item for item in candidates if item.id not in self.exhausted
                          and item.id != target.id), None)
        if alternate is not None and self.scan is None:
            self.adopt(alternate.id)
        elif self.scan is None:
            self.exhausted.clear()

        return None, None, False
