"""Foreground-only direct fire, shell comparison and bounded attack search."""
from __future__ import division

import math

from ..gun_mechanics import _field


PENETRATION_FACTOR_65 = 0.9679810530375992
SEARCH_SECONDS = 8.
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
        self.failed_penetration_shells = None
        self.exhausted = set()
        self.fallback = False
        self.seek = False
        self.retreat = False
        self.laying_until = None
        self.next_shell_scan = None
        self.checking = False
        self.locked_wait = False
        self.confirmed = None
        self.pivot_search = None
        self.next_round = None
        self.next_shell = None
        self.switch_from = None
        self.last_full_at = None
        self.laying_error = None

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
        # The search clock spans targets; a completed armor check does not.
        self.failed_penetration_shells = None
        self.fallback = False
        self.laying_until = self.next_shell_scan = self.last_full_at = self.laying_error = None
        self.checking = False
        self.locked_wait = False
        self.confirmed = None
        self.pivot_search = None
        self.next_round = None
        self.next_shell = None
        self.switch_from = None

    def shot_admitted(self, target):
        if self.target == target and not self.fallback:
            self.search_since = None
            self.failed_penetration_shells = None
            self.exhausted.clear()
            self.retreat = self.seek = False

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

    def _scan(self, control, target, rows, now, mode):
        aiming = control.aiming
        indices = tuple(row['index'] for row in rows)
        count = aiming.direct_samples(target)
        gun = control.owner._gun_state
        protect_current = gun.clip_size <= 1 and mode == 'full' and gun.shot_index in indices
        current = gun.shot_index if protect_current else None
        identity = (target.id, indices, mode, count, current)
        if self.scan is None or self.scan['identity'] != identity:
            rejected = self.pivot_search if mode == 'full' and self.pivot_search is not None else {}
            self.scan = dict(identity=identity, pending=[(index, point)
                for point in range(count) for index in indices if (index, point) not in rejected],
                hits=[], armor='armor' in rejected.values(), unknown='unknown' in rejected.values(),
                current_unknown=any(index == current and verdict == 'unknown'
                    for (index, unused_point), verdict in rejected.items()))
        scan = self.scan
        for unused in range(2):
            if not scan['pending']:
                break
            index, point = scan['pending'][0]
            verdict, solution = aiming.compare_direct(target, index, point, now,
                lambda a, b: control.lane_from(target, a, b),
                None if mode == 'splash' else PENETRATION_FACTOR_65,
                nominal=mode == 'splash')
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
                if index == current:
                    scan['current_unknown'] = True
        if scan['pending']:
            return 'pending', None
        self.scan = None
        if scan['hits']:
            best = min(scan['hits'])
            if protect_current:
                mounted = [hit for hit in scan['hits'] if hit[3] == current]
                if mounted:
                    self.next_round = ((target.id, current, best[3], best[1])
                                       if best[3] != current else None)
                    best = min(mounted)
                elif scan['current_unknown']:
                    # Missing evidence cannot justify unloading the current round.
                    self.next_round = None
                    return 'unavailable', None
                else:
                    self.next_round = None
            unused_score, point, unused_rank, index = best
            return 'ready', (index, point)
        return ('armor' if scan['armor'] and not scan['unknown'] else 'unavailable'), None

    def interrupt_pivot(self, index, sample, verdict):
        already_searching = self.pivot_search is not None
        if not already_searching:
            self.pivot_search = {}
        if verdict in ('armor', 'unavailable') or (already_searching and verdict == 'unknown'):
            self.pivot_search[(index, sample)] = verdict
        self.sample = self.last_solution = self.scan = None
        self.laying_until = self.laying_error = None
        self.fallback = False
        self.checking = True

    def _compare_next_shell(self, control, target, index, sample, now):
        gun, aiming = control.owner._gun_state, control.aiming
        if ((gun.clip_size > 1 and gun.clip != 1) or
                getattr(control.owner, '_local_player_burst', None) or
                getattr(control.owner, '_local_fire_intent', None)):
            return
        rows = self.shells(control.ammo_policy, gun)
        indices = tuple(row['index'] for row in rows)
        planned = self.next_round if (self.next_round is not None and
            self.next_round[:2] == (target.id, index)) else None
        alternatives = tuple((other, planned[3] if planned and planned[2] == other else sample)
                             for other in indices if other != index)
        key = (target.id, index, sample, alternatives)
        scan = self.next_shell_scan
        if scan is None or scan['key'] != key:
            scan = self.next_shell_scan = dict(key=key, cursor=0, ready={})
        if not alternatives or index not in indices:
            return
        cursor = scan['cursor']
        other, point = alternatives[cursor]
        verdict, unused = aiming.compare_direct(target, other, point, now,
            lambda a, b: control.lane_from(target, a, b), PENETRATION_FACTOR_65,
            current_barrel=point == sample)
        if verdict == 'pending':
            scan['ready'].pop(other, None)
        else:
            scan['ready'][other] = now if verdict == 'ready' else None
        # Aiming retains an unfinished path job per shell and point. Give the
        # other alternatives a turn while this one waits for another slice.
        scan['cursor'] = (cursor + 1) % len(alternatives)
        # A round can fire while the alternatives are still being compared.
        # Only a recent proof for a higher-priority shell may queue a change.
        selected = next((other for other in indices[:indices.index(index)]
            if scan['ready'].get(other) is not None and now - scan['ready'][other] <= .35), index)
        if gun.clip_size <= 1:
            self.next_shell = selected if selected != index else None
        elif len(scan['ready']) == len(alternatives):
            control.queue_next_automatic_clip(selected)
        else:
            return True
        return False

    def _lay(self, control, target, index, sample, now, fallback, facing=None, compare_next=True):
        gun, aiming = control.owner._gun_state, control.aiming
        self.stage = (index, None if fallback else PENETRATION_FACTOR_65)
        if gun.shot_index != index:
            if gun.clip_size <= 1 and self.switch_from != gun.shot_index:
                # A completed shot or a manual selection can replace the
                # mounted shell while the old aiming stage is still present.
                self.sample = self.last_solution = self.switch_from = None
                self.checking = True
                return None, None, False
            if gun.clip_size <= 1 and not fallback:
                # Recheck the alternate before committing a full reload. A
                # completed scan may have spanned several vehicle poses.
                verdict, unused_solution = aiming.compare_direct(target, index, sample, now,
                    lambda a, b: control.lane_from(target, a, b), self.stage[1])
                if verdict != 'ready':
                    self.checking = verdict == 'pending'
                    if not self.checking:
                        self.sample = self.last_solution = None
                    return None, None, False
            control.queue_automatic_shell(index)
            return None, None, False
        self.switch_from = None
        turning = facing == 'turning'
        verdict, solution = aiming.compare_direct(target, index, sample, now,
            lambda a, b: control.lane_from(target, a, b), self.stage[1],
            physical=True, nominal=fallback, verify_point=turning)
        if verdict == 'pending' and self.last_solution is not None:
            self.checking = self.locked_wait = True
            return target, self.last_solution, False
        if turning and verdict != 'ready' and not (solution and solution.get('point_viable')):
            # A missing or failed current point proof releases the tracks to
            # stationary point search. Unknown evidence does not reject armor.
            self.interrupt_pivot(index, sample, verdict)
            return None, None, False
        if verdict in ('ready', 'laying'):
            self.last_solution = solution
            if verdict == 'laying':
                if turning:
                    return target, solution, False
                error = solution.get('barrel_error')
                progressing = error is not None and (self.laying_error is None or
                                                      error < self.laying_error - .002)
                if self.laying_until is None or progressing:
                    self.laying_until = now + 5.
                    self.laying_error = error
                elif now >= self.laying_until:
                    aiming.defer_ordered_point(target, index, solution, now)
                    if facing or self.pivot_search is not None:
                        self.interrupt_pivot(index, sample, 'unavailable')
                    else:
                        self.sample = self.last_solution = self.laying_until = self.laying_error = None
                    return None, None, False
                return target, solution, False
            self.laying_until = self.laying_error = None
            self.confirmed = (target.id, sample, index)
            self.pivot_search = None
            if not fallback:
                # Hold the verified point for the trigger. Its final ray
                # proof can still reject the shot, so keep the search clock.
                self.failed_penetration_shells = None
                self.retreat = self.seek = False
            waiting_for_clip = compare_next and self._compare_next_shell(control, target, index, sample, now)
            return target, solution, not waiting_for_clip
        self.checking = verdict == 'pending'
        if verdict != 'pending':
            if facing or self.pivot_search is not None:
                self.interrupt_pivot(index, sample, verdict)
            else:
                if (verdict == 'armor' and solution is not None and gun.clip_size <= 1 and
                        not getattr(control.owner, '_local_player_burst', None) and
                        not getattr(control.owner, '_local_fire_intent', None)):
                    aiming.defer_ordered_point(target, index, solution, now)
                self.laying_until = self.laying_error = None
                self.sample = self.last_solution = self.scan = self.next_shell_scan = None
                self.fallback = False
        return None, None, False

    def update(self, control, candidates, now):
        owner, aiming = control.owner, control.aiming
        gun, policy = owner._gun_state, control.ammo_policy
        rows = self.shells(policy, gun)
        self.checking = False
        self.locked_wait = False
        self.confirmed = None
        self.next_shell = None
        self.seek = self.search_since is not None and not self.retreat
        held = bool(getattr(owner, '_local_fire_intent', None) or
                    getattr(owner, '_local_player_burst', None) or
                    getattr(control, 'owned_burst', None))
        by_id = dict((target.id, target) for target in candidates)
        facing = getattr(control, 'last_order', {}).get('confirmed_facing', {})
        phase = facing.get('state')
        facing_phase = phase if (phase in ('turning', 'settling', 'recheck') and
            facing.get('key') == (self.target, self.sample, gun.shot_index)) else None
        if held:
            target = by_id.get(self.target)
            if target is not None and self.sample is not None and self.stage is not None:
                return self._lay(control, target, self.stage[0], self.sample, now, self.fallback,
                                 facing=facing_phase)
            return None, None, False
        if not rows or not candidates:
            self.adopt(None)
            return None, None, False
        if self.target not in by_id:
            self.adopt(candidates[0].id)
        target = by_id[self.target]
        target_moved, own_moved, pose = self._motion_changes(aiming, target)
        pivoting = facing_phase is not None and self.sample is not None and self.target == target.id
        if pivoting and own_moved and self.motion is not None:
            # Retain the target anchor and existing scan across our pivot.
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
        if self.sample is not None and self.stage is not None:
            if self.stage[0] != gun.shot_index and self.last_solution is None:
                return self._lay(control, target, self.stage[0], self.sample, now, self.fallback)
            if self.stage[0] == gun.shot_index:
                rescan = (not pivoting and self.last_solution is not None and
                    (not magazine or gun.clip != 1) and self.laying_until is None and
                    (self.fallback or target_moved or own_due or
                     self.scan is not None and self.scan['identity'][2] == 'full'))
                result = self._lay(control, target, self.stage[0], self.sample, now, self.fallback,
                                   facing=facing_phase if pivoting else None, compare_next=not rescan)
                if rescan and result[2]:
                    if self.scan is None or self.scan['identity'][2] != 'full':
                        self.motion = pose
                        self.last_full_at = now
                        self.next_shell_scan = None
                    unused_verdict, pick = self._scan(control, target, eligible, now, 'full')
                    if self.fallback and pick is not None:
                        index, self.sample = pick
                        self.stage = (index, PENETRATION_FACTOR_65)
                        self.last_solution = None
                        self.fallback = False
                        self.failed_penetration_shells = None
                        if not magazine and index != gun.shot_index:
                            self.switch_from = gun.shot_index
                        return result[0], result[1], False
                return result
        expired = self.search_since is not None and now - self.search_since >= SEARCH_SECONDS
        eligible_shells = tuple(row['index'] for row in eligible)
        if self.pivot_search is not None and self.sample is None:
            mode = 'full'
        elif self.scan is not None and self.scan['identity'][2] == 'next' and not self.retreat:
            mode = 'next'
        elif (expired and self.failed_penetration_shells == eligible_shells and
              self.sample is None and self.scan is None and not self.retreat):
            mode = 'next' if keep_clip and not he else 'splash' if he else 'full'
        elif self.scan is not None and self.scan['identity'][2] == 'splash':
            mode = 'splash'
        elif self.scan is not None and self.scan['identity'][2] == 'full':
            mode = 'full'
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
        verdict, pick = self._scan(control, target, compare, now, mode)
        if verdict == 'pending':
            self.checking = True
            if self.last_solution is not None and now - self.last_solution['created'] <= .5:
                return target, self.last_solution, False
            return None, None, False
        if mode == 'full':
            self.failed_penetration_shells = eligible_shells if verdict == 'armor' else None
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
            self.laying_until = self.laying_error = None
            self.fallback = mode == 'splash'
            if mode in ('full', 'splash') and gun.clip_size <= 1 and index != gun.shot_index:
                self.switch_from = gun.shot_index
            return self._lay(control, target, index, self.sample, now, self.fallback)
        self.sample = self.last_solution = None
        self.pivot_search = None
        if mode == 'splash':
            # A failed splash sweep also gives penetration another turn.
            self.failed_penetration_shells = None
        if verdict == 'armor' and self.search_since is None:
            self.search_since = now
        if expired and self.failed_penetration_shells == eligible_shells:
            if keep_clip or he:
                # Give the completed target its fallback before rotating again.
                return None, None, False
            self.retreat = True
            self.seek = False
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
