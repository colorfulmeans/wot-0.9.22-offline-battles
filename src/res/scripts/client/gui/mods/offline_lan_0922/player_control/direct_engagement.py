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
        self.search_elapsed = 0.
        self.search_observation = None
        self.reload_requested = None
        self._reload_plan = None
        self._reload_candidate = None
        self._magazine_state = None
        self._magazine_fallback = None
        self.native_deferred = False

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
        self.reload_requested = self._reload_plan = self._magazine_fallback = None
        self._reload_candidate = None
        self.search_observation = None
        self.native_deferred = False

    def observe_search(self, now, position, yaw, active):
        """Credit only the final owner's actual firing-position attempts.

        ``active`` includes a checked path refusal, so a tank with no safe
        manoeuvre still has a bounded search. Merely waiting for native scan
        evidence, driving a route or having movement disabled is not a search
        attempt. The caller supplies this after the final movement guards.
        After a completed armor failure, an actual attempt can overlap sliced
        native checks; pending checks still cannot authorize a clip reload.
        """
        active = bool(active and self._magazine_state is not None and self.seek
            and self.search_since is not None and self.failed_penetration_shells is not None
            and not (self.locked_wait or self.retreat))
        previous = self.search_observation
        if active:
            if previous is not None and now >= previous[0]:
                self.search_elapsed = min(SEARCH_SECONDS, self.search_elapsed + now - previous[0])
            self.search_observation = (now, tuple(position), yaw)
        else:
            self.search_observation = None

    def _clear_search(self):
        self.search_since = self.search_observation = None
        self.search_elapsed = 0.
        self.failed_penetration_shells = None
        self.reload_requested = None
        self._reload_candidate = None
        self.exhausted.clear()
        self.retreat = self.seek = False

    def _observe_magazine(self, gun):
        if gun.clip_size <= 1:
            self._magazine_state = None
            return
        previous = self._magazine_state
        if previous is not None and (previous[0] is not gun or previous[1] != gun.shot_index
                                     or gun.clip > previous[2]):
            plan = self._reload_plan if previous[0] is gun else None
            target = self.target
            self._clear_search()
            self.adopt(target)
            if (plan is not None and plan[:2] == (target, gun.shot_index)
                    and gun.clip > 0 and plan[3]):
                # The original HE fallback selected a point before reloading.
                # Its physical source and nominal armor are rechecked by _lay;
                # no pre-reload native firing proof is carried into this clip.
                self.sample, self.fallback = plan[2], True
                self.stage = (gun.shot_index, None)
        self._magazine_state = (gun, gun.shot_index, gun.clip)

    def clip_reload_started(self, gun):
        """Consume the same-gun reload accepted by the withdrawal owner."""
        if (self._magazine_state is None or self._magazine_state[0] is not gun
                or gun.clip > 0 or gun.reload_time <= 0.):
            return False
        plan = self._reload_plan
        self._clear_search()
        self.adopt(self.target)
        self._reload_plan = plan
        self._magazine_state = (gun, gun.shot_index, gun.clip)
        self.retreat = True
        return True

    def _request_clip_reload(self, control, target, index, sample, fallback, now, pose):
        self.retreat, self.seek = True, False
        self._reload_candidate = (target.id, id(target), index, sample, fallback)
        # A full comparison can span native slices and vehicle poses. As for
        # the single-shot switch, recheck the chosen alternate before allowing
        # any command to discard currently loaded rounds. Keep the candidate
        # across a budget deferral so the final comparison can get a slot.
        verdict, unused = control.aiming.compare_direct(target, index, sample, now,
            lambda a, b: control.lane_from(target, a, b),
            None if fallback else PENETRATION_FACTOR_65, nominal=fallback)
        self.motion = pose
        if verdict == 'pending':
            self.checking = self.native_deferred = True
            return
        self._reload_candidate = None
        if verdict != 'ready':
            self._reload_plan = self._magazine_fallback = None
            self.failed_penetration_shells = None
            self.retreat, self.seek = False, True
            control.queue_next_automatic_clip(None)
            return
        self.reload_requested = index
        self._reload_plan = (target.id, index, sample, fallback)
        control.queue_next_automatic_clip(index)

    def shot_admitted(self, target):
        if self.target == target and not self.fallback:
            self._clear_search()
            self._reload_plan = self._magazine_fallback = None

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
        protect_current = mode in ('full', 'next') and gun.shot_index in indices
        current = gun.shot_index if protect_current else None
        identity = (target.id, indices, mode, count, current, id(target))
        if self.scan is None or self.scan['identity'] != identity:
            rejected = self.pivot_search if mode == 'full' and self.pivot_search is not None else {}
            pending = [(index, point) for point in range(count) for index in indices
                       if (index, point) not in rejected]
            if gun.clip_size > 1 and protect_current:
                # A deferred alternate cannot consume the budget needed to
                # discover that the current magazine is usable again.
                pending.sort(key=lambda item: item[0] != current)
            self.scan = dict(identity=identity, pending=pending,
                hits=[], hull=[], armor='armor' in rejected.values(), unknown='unknown' in rejected.values(),
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
                self.native_deferred = True
                return 'pending', None
            scan['pending'].pop(0)
            if verdict == 'ready':
                score = solution['nominal_armor'] if mode == 'splash' else indices.index(index)
                scan['hits'].append((score, point, indices.index(index), index))
                if gun.clip_size > 1 and protect_current and index == current:
                    self.scan = None
                    return 'ready', (index, point)
            elif verdict == 'needs_hull':
                # This is a geometric candidate, not an armor comparison or
                # a verified firing source. Keep it for the player's hull
                # owner only after all ready candidates have had their turn.
                scan['hull'].append((index != gun.shot_index, point, indices.index(index), index))
                scan['unknown'] = True
            elif verdict == 'armor':
                scan['armor'] = True
            elif verdict == 'unknown':
                scan['unknown'] = True
                if index == current:
                    scan['current_unknown'] = True
        if gun.clip_size > 1 and protect_current:
            mounted = [hit for hit in scan['hits'] if hit[3] == current]
            if mounted:
                self.scan = None
                unused_score, point, unused_rank, index = min(mounted)
                return 'ready', (index, point)
            if not any(index == current for index, unused_point in scan['pending']):
                hull = [hit for hit in scan['hull'] if hit[3] == current]
                if hull:
                    self.scan = None
                    return 'needs_hull', (current, min(hull)[1])
                if scan['current_unknown']:
                    self.scan = None
                    return 'unavailable', None
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
        if scan['hull']:
            unused_loaded, point, unused_rank, index = min(scan['hull'])
            return 'needs_hull', (index, point)
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
        if (getattr(control.owner, '_local_player_burst', None) or
                getattr(control.owner, '_local_fire_intent', None)):
            return
        if gun.clip_size > 1:
            return self._compare_next_clip(control, target, index, sample, now)
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
        self.next_shell = selected if selected != index else None
        return False

    def _compare_next_clip(self, control, target, index, sample, now):
        gun, aiming = control.owner._gun_state, control.aiming
        indices = tuple(row['index'] for row in self.shells(control.ammo_policy, gun))
        if index not in indices:
            control.queue_next_automatic_clip(None)
            return False
        preferred = tuple(other for other in (indices if self.fallback else
                          indices[:indices.index(index)]) if other != index)
        count = aiming.direct_samples(target)
        points = (sample,) + tuple(point for point in range(count) if point != sample)
        candidates = tuple((other, point) for point in points for other in preferred)
        key = (target.id, id(target), index, sample, candidates)
        scan = self.next_shell_scan
        if scan is None or scan['key'] != key:
            scan = self.next_shell_scan = dict(key=key, cursor=0, ready={}, selected=None, refresh=False)
        if not candidates:
            control.queue_next_automatic_clip(None)
            return False
        selected = scan['selected']
        if selected is not None and scan['refresh']:
            candidate = selected
            scan['refresh'] = False
        else:
            candidate = candidates[scan['cursor']]
            scan['cursor'] = (scan['cursor'] + 1) % len(candidates)
            scan['refresh'] = selected is not None
        other, point = candidate
        verdict, unused = aiming.compare_direct(target, other, point, now,
            lambda a, b: control.lane_from(target, a, b), PENETRATION_FACTOR_65,
            current_barrel=point == sample)
        if verdict == 'ready':
            scan['ready'][candidate] = now
        else:
            scan['ready'].pop(candidate, None)
        ready = [candidate for candidate, completed in scan['ready'].items()
                 if now - completed <= .35]
        selected = min(ready, key=lambda item: (preferred.index(item[0]), item[1])) if ready else None
        if selected != scan['selected']:
            scan['refresh'] = selected is not None
        scan['selected'] = selected
        # This never loads a round. A current-shell physical proof gets the
        # first budget slot, then one next-clip comparison either refreshes
        # the plan or visits another shell/point. Pending work cannot block
        # firing, even on a final trigger that consumes several clip rounds.
        control.queue_next_automatic_clip(selected[0] if selected is not None else None)
        return False

    def _lay(self, control, target, index, sample, now, fallback, facing=None, compare_next=True):
        gun, aiming = control.owner._gun_state, control.aiming
        self.stage = (index, None if fallback else PENETRATION_FACTOR_65)
        if gun.shot_index != index:
            if gun.clip_size > 1 and gun.clip > 0:
                # A candidate for another shell is a next-clip plan only.
                # Even HE cannot discard a live magazine through CURRENT.
                self.sample = self.last_solution = self.switch_from = None
                self.checking = True
                return None, None, False
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
        if verdict == 'pending':
            self.native_deferred = True
        if verdict == 'pending' and self.last_solution is not None:
            self.checking = self.locked_wait = True
            return target, self.last_solution, False
        if verdict == 'needs_hull':
            self.last_solution = solution
            self.laying_until = self.laying_error = None
            self.failed_penetration_shells = None
            self.seek = self.retreat = False
            return target, solution, False
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
                self.reload_requested = self._reload_plan = self._magazine_fallback = None
            waiting_for_clip = compare_next and self._compare_next_shell(control, target, index, sample, now)
            return target, solution, not waiting_for_clip
        self.checking = verdict == 'pending'
        if verdict != 'pending':
            if gun.clip_size > 1:
                control.queue_next_automatic_clip(None)
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
        self._observe_magazine(gun)
        rows = self.shells(policy, gun)
        self.checking = False
        self.locked_wait = False
        self.confirmed = None
        self.next_shell = None
        self.reload_requested = None
        self.native_deferred = False
        self.seek = self.search_since is not None and not self.retreat
        held = bool(getattr(owner, '_local_fire_intent', None) or
                    getattr(owner, '_local_player_burst', None) or
                    getattr(control, 'owned_burst', None))
        by_id = dict((target.id, target) for target in candidates)
        last_order = getattr(control, 'last_order', {})
        facing = last_order.get('confirmed_facing', {})
        facing_states = ('turning', 'settling', 'recheck')
        limited = last_order.get('combat_facing', {})
        if (limited.get('limited_traverse') and
                limited.get('key') == (self.target, self.sample, gun.shot_index)):
            facing = limited
            facing_states = ('braking', 'turning', 'checking', 'aligned')
        phase = facing.get('state')
        facing_phase = phase if (phase in facing_states and
            facing.get('key') == (self.target, self.sample, gun.shot_index)) else None
        if held:
            target = by_id.get(self.target)
            if target is not None and self.sample is not None and self.stage is not None:
                return self._lay(control, target, self.stage[0], self.sample, now, self.fallback,
                                 facing=facing_phase)
            return None, None, False
        if not rows or not candidates:
            if gun.clip_size > 1 and gun.clip > 0:
                control.queue_next_automatic_clip(None)
            self.adopt(None)
            return None, None, False
        if self.target not in by_id:
            if gun.clip_size > 1 and gun.clip > 0:
                control.queue_next_automatic_clip(None)
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
            self.search_observation = None
            return None, None, False
        eligible = [loaded] if keep_clip else rows
        he = [row for row in eligible if row['kind'] == HE]
        if self._reload_candidate is not None:
            candidate = self._reload_candidate
            if (keep_clip and candidate[:2] == (target.id, id(target)) and
                    not (target_moved or own_moved)):
                self._request_clip_reload(control, target, candidate[2], candidate[3], candidate[4], now, pose)
                return None, None, False
            self._reload_candidate = self._reload_plan = self._magazine_fallback = None
            self.failed_penetration_shells = self.scan = None
            self.retreat, self.seek = False, self.search_since is not None
        if self.stage is not None and not any(row['index'] == self.stage[0] for row in eligible):
            self.sample = self.last_solution = None
            self.fallback = False
        if self.sample is not None and self.stage is not None:
            if self.stage[0] != gun.shot_index and self.last_solution is None:
                return self._lay(control, target, self.stage[0], self.sample, now, self.fallback)
            if self.stage[0] == gun.shot_index:
                fallback_due = self.fallback and (not magazine or self.last_full_at is None or
                                                  now - self.last_full_at >= OWN_RESCAN_SECONDS)
                rescan = (not pivoting and self.last_solution is not None and
                    self.laying_until is None and
                    (fallback_due or target_moved or own_due or
                     self.scan is not None and self.scan['identity'][2] == 'full'))
                result = self._lay(control, target, self.stage[0], self.sample, now, self.fallback,
                                   facing=facing_phase if pivoting else None, compare_next=not rescan)
                if rescan and result[2]:
                    if self.scan is None or self.scan['identity'][2] != 'full':
                        self.motion = pose
                        self.last_full_at = now
                        if not self.fallback or target_moved or own_due:
                            self.next_shell_scan = None
                    unused_verdict, pick = self._scan(control, target, eligible, now, 'full')
                    if magazine and self.fallback and unused_verdict != 'pending':
                        self.last_full_at = now
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
        expired = (self.search_elapsed >= SEARCH_SECONDS if magazine else
                   self.search_since is not None and now - self.search_since >= SEARCH_SECONDS)
        eligible_shells = tuple(row['index'] for row in eligible)
        available_shells = tuple(row['index'] for row in rows)
        if self.pivot_search is not None and self.sample is None:
            mode = 'full'
        elif self.scan is not None and self.scan['identity'][2] == 'next':
            mode = 'next'
        elif keep_clip and expired and self._magazine_fallback == available_shells:
            mode = 'splash'
        elif (expired and self.failed_penetration_shells == eligible_shells and
              self.sample is None and self.scan is None and (keep_clip or not self.retreat)):
            mode = 'next' if keep_clip else 'splash' if he else 'full'
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
        if mode == 'splash':
            compare = [row for row in rows if row['kind'] == HE] if keep_clip else he
        else:
            compare = rows if mode == 'next' else eligible
        verdict, pick = self._scan(control, target, compare, now, mode)
        if verdict == 'pending':
            self.checking = True
            if self.last_solution is not None and now - self.last_solution['created'] <= .5:
                return target, self.last_solution, False
            return None, None, False
        if mode == 'full':
            self.failed_penetration_shells = eligible_shells if verdict == 'armor' else None
        if mode == 'next':
            if pick is not None and pick[0] == gun.shot_index:
                self.sample = pick[1]
                self.fallback = False
                return self._lay(control, target, pick[0], self.sample, now, False)
            if verdict == 'ready' and pick is not None:
                self._request_clip_reload(control, target, pick[0], pick[1], False, now, pose)
            elif verdict == 'armor':
                has_he = any(row['kind'] == HE for row in rows)
                self._magazine_fallback = available_shells if has_he else None
                self.retreat = not has_he
                self.seek = not self.retreat
            else:
                # Unknown or a hull-only alternate is not permission to
                # unload the current clip, even after a previous timeout.
                self._magazine_fallback = None
                self.failed_penetration_shells = None
                self._reload_plan = None
                self.retreat, self.seek = False, True
                control.queue_next_automatic_clip(None)
            return None, None, False
        if mode == 'splash' and keep_clip:
            if verdict == 'ready' and pick is not None and pick[0] != gun.shot_index:
                self._request_clip_reload(control, target, pick[0], pick[1], True, now, pose)
                return None, None, False
            if verdict != 'ready':
                self._magazine_fallback = None
                self.failed_penetration_shells = None
                self._reload_plan = None
                control.queue_next_automatic_clip(None)
            elif pick is not None:
                # A loaded HE clip can use the unchanged nominal fallback;
                # reloading the same shell would only discard its ready clip.
                self.retreat = self.seek = False
            if verdict == 'armor' and not he:
                self.retreat = True
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
