"""One mounted shell and one target at a time for ordinary player auto fire."""

def stocked(frame, explosive):
    return sorted((shell for shell in frame['shells']
                   if shell['is_he'] == explosive and not shell.get('unavailable')
                   and frame['ammo'][shell['index']] > 0),
                  key=lambda shell: (shell['piercing'], shell['index']))


class OrderedAttack(object):
    def __init__(self):
        self.order = []
        self.target = None
        self.loaded = None
        self.loaded_he = False
        self.sample = None
        self.he_sample = None
        self.he_identity = None
        self.covered = set()
        self.checked_lanes = set()
        self.cursor = 0
        self.committed_shell = None
        self.committed_rounds = 0
        self.he_fallback_rounds = 0
        self.he_clip_return = False

    def load_started(self, shell_index, new_load=False):
        if self.committed_shell != shell_index:
            self.committed_shell, self.committed_rounds = shell_index, 0
            self.he_fallback_rounds = 0
            new_load = True
        if new_load:
            self.he_clip_return = False

    def shot_committed(self, shell_index, mode=None, magazine=False):
        self.load_started(shell_index)
        self.committed_rounds += 1
        self.he_fallback_rounds = self.he_fallback_rounds + 1 if mode == 'he_fallback' else 0
        if magazine and self.he_fallback_rounds >= 2:
            self.he_clip_return = True

    def _sync(self, frame, shell):
        self.load_started(shell['index'])
        live = [row['key'] for row in frame['targets']]
        self.order = [key for key in self.order if key in live]
        self.order.extend(key for key in live if key not in self.order)
        self.covered.intersection_update(live)
        self.checked_lanes.intersection_update(live)
        if self.loaded != shell['index']:
            if self.loaded_he and not shell['is_he'] and self.target in self.order:
                self.order.remove(self.target)
                self.order.insert(0, self.target)
            if not shell['is_he']:
                self.target = None
                self.sample = None
            self.loaded, self.loaded_he = shell['index'], shell['is_he']
            self.he_sample = None
            self.he_identity = None
            self.covered.clear()
            self.checked_lanes.clear()
            self.cursor = 0
        if self.target not in live:
            self.target, self.sample, self.he_sample = None, None, None

    def next_load(self, policy, trigger=None):
        frame = policy.frame
        loaded = frame['loaded']
        shell = next((row for row in frame['shells'] if row['index'] == loaded), None)
        if shell is None:
            return None, 'shell_descriptor_pending'
        penetration = stocked(frame, False)
        if frame['ammo'][loaded] <= frame['clip']:
            reserve = [row for row in penetration if row['index'] != loaded]
            if not reserve and not shell['is_he']:
                reserve = stocked(frame, True)
            if reserve:
                return reserve[0]['index'], 'mounted_stock_exhausted'
        lowest = penetration[0] if penetration else None
        if lowest is None or (not shell['is_he'] and lowest['piercing'] >= shell['piercing']):
            return None, 'keep_mounted_shell'
        # The native gun promotes NEXT at the reload boundary. The final
        # trigger's shot mode is available before its cartridge is consumed.
        magazine = frame['clip_size'] > 1 or frame.get('burst_count', 1) > 1
        same_shell = self.committed_shell == loaded
        if shell['is_he']:
            if not (same_shell and self.he_clip_return):
                if (trigger is None or trigger.get('mode') != 'he_fallback' or
                        trigger.get('shell_index') != loaded):
                    return None, 'keep_mounted_shell'
                rounds = min(frame['clip'], frame['ammo'][loaded], frame.get('burst_count', 1))
                streak = self.he_fallback_rounds if same_shell else 0
                if streak + rounds < 2:
                    return None, 'keep_mounted_shell'
        elif not magazine and (not same_shell or self.committed_rounds < 1):
            return None, 'keep_mounted_shell'
        if self._still_failed(policy, lowest['index']):
            return None, 'ordered_lowest_penetration_still_failed'
        reason = 'he_finished_lowest_penetration' if shell['is_he'] else 'higher_penetration_cycle_finished'
        return lowest['index'], reason

    def _still_failed(self, policy, index):
        clear_failure = False
        for job in policy._jobs(shell_index=index):
            evidence = self._negative_evidence(policy, job, policy._current(job, require_line=True))
            if evidence is None:
                return False
            clear_failure = clear_failure or self._clear_failure(policy, evidence)
        return clear_failure

    def _switch(self, policy, shell, reason):
        action = 'reload_clip' if policy.frame['clip_size'] > 1 else 'switch_shell'
        return policy._choose(action, reason, shell_index=shell['index'],
                              early_reload=policy.frame['clip'] > 0 and policy.frame['ammo'][self.loaded] > 0)

    def _aim(self, policy, now, row, reason, ranking=()):
        fence = getattr(policy.evaluator, 'fence_next', None)
        if ((row['observed_at'] == now or any(proof['observed_at'] == now for proof in ranking)) and
                callable(fence) and not fence(policy.frame, ranking or (row,), False)):
            policy.rows.clear()
            policy.selected = None
            policy._frame_invalid = True
            return policy._recover_incomplete(now, 'ordered_point_observation_changed')
        policy.fallback = row['mode'] == 'he_fallback'
        policy.reload_authority = None
        return policy._choose('aim', reason, row)

    def _retain_target(self, row):
        self.target, self.sample = row['target_key'], row['sample']
        self.covered.clear()
        self.checked_lanes.clear()
        self.order.remove(self.target)
        self.order.insert(0, self.target)

    def _route_opportunity(self, policy, now, jobs, combat):
        # While the route owns the hull, observe an attackable ray across
        # the same mounted shell's targets. A new driving pose must not
        # restart the first enemy's whole point review on every callback.
        def attackable(row):
            return (policy._executable_current(row) or
                    (combat._route_attackable(row) and combat._route_lay_can_retry(row)))

        row = policy._frontier(now, jobs, attackable)
        if row is None:
            return None
        self._retain_target(row)
        if policy._executable_current(row):
            return self._aim(policy, now, row, 'current_shell_verified')
        return policy._choose('firing_position', 'current_penetration_after_stationary_turn', row)

    def _current_he(self, policy, now, shell, jobs):
        policy.he_comparison = dict(total=0, observed=0, pending=0)
        if self.target is None:
            self.target = self.order[0]
        target = next(row for row in policy.frame['targets'] if row['key'] == self.target)
        identity = target.get('sample_identity')
        if identity != self.he_identity:
            self.he_sample = None
            self.he_identity = identity
        target_jobs = [job for job in jobs if job[0][1] == self.target]
        preferred = self.sample if self.he_sample is None else self.he_sample
        target_jobs.sort(key=lambda job: job[3] != preferred)
        combat = getattr(policy.runtime, 'combat_stop', None)
        route_review = combat is not None and combat.can_review_route_attack()
        previous = policy.decision.get('candidate') or {}
        refresh = None
        if (route_review and previous.get('target_key') == self.target and
                combat._route_attackable(previous)):
            refresh = (shell['index'], self.target, previous['sample'], 'penetration')
        action, row = self._inspect(policy, now, target_jobs, refresh)
        if action == 'aim':
            self.he_sample = row['sample']
            return self._aim(policy, now, row, 'current_shell_verified')
        if action == 'firing_position':
            return policy._choose(action, 'ordered_he_hull_lay', row)
        if action == 'native_lay':
            return policy._choose('firing_position', 'unverified_points_obstructed', row)
        impact = None
        if route_review:
            # The same fresh impact can qualify a stop and retain it while
            # the tank settles and the remaining points are reviewed.
            impact = next((current for job in target_jobs
                           for current in (policy._current(job, require_line=True),)
                           if current is not None and current.get('route_he_contact') and
                           combat._route_attackable(current)), None)
            if impact is not None and (action != 'complete' or not combat.combat_owned):
                return policy._choose('preaim', 'ordered_he_route_contact', impact)
        if action != 'complete':
            return policy._recover_incomplete(now, 'ordered_he_penetration_pending', (row,) if row else ())
        samples = set(job[3] for job in target_jobs if self._clear_failure(policy,
            self._negative_evidence(policy, job, policy._current(job, require_line=True))))
        if not samples:
            return self._no_he_contact(policy, (row,), 'ordered_he_no_clear_lane')
        fallback = [job for job in policy._jobs('he_fallback', shell['index'])
                    if job[0][1] == self.target and job[3] in samples]
        fallback.sort(key=lambda job: job[3] != preferred)
        return self._rank_he_fallback(policy, now, fallback, impact)

    def _rank_he_fallback(self, policy, now, jobs, impact):
        mode = 'he_fallback'

        def complete(row):
            return policy._reviewed(row, mode) or policy._he_contact_failed(row)

        def ranking_row(job):
            row = policy._current(job, require_line=True)
            return row if complete(row) else policy._next_row(job)

        def ready(row):
            return policy._executable(row, mode) or self._can_lay(policy, row, mode)

        pending = [job for job in jobs if not complete(ranking_row(job))]
        for job in pending:
            if policy._used['foreground'] >= policy.foreground_budget:
                break
            policy._evaluate(job, now, 'foreground')
        for unused in policy._ordered_point_slice(tuple(job for job in pending
                if not complete(ranking_row(job))), now):
            pass
        rows = [ranking_row(job) for job in jobs]
        options = [(row, job) for row, job in zip(rows, jobs) if ready(row)]
        if options:
            best, job = min(options, key=lambda option: policy._he_order(option[0]))
            current = policy._current(job, require_line=True)
            if current is not best and policy._used['foreground'] < policy.foreground_budget:
                policy._evaluate(job, now, 'foreground')
                rows = [ranking_row(job) for job in jobs]
                options = [(row, job) for row, job in zip(rows, jobs) if ready(row)]
        reopened = next((row for job in jobs for row in (policy._current(job, require_line=True),)
                         if row is not None and row.get('line') == 'clear' and
                         row.get('armor') == 'passed'), None)
        if reopened is not None:
            # A fresh observation can reopen a plate whose failed ranking
            # had survived a small change in geometry.
            key = reopened['key'][:3] + ('penetration',)
            policy._next_rows.pop(key, None)
            policy.rows.pop(key, None)
            return policy._recover_incomplete(now, 'ordered_he_penetration_pending')
        reviewed = sum(complete(row) for row in rows)
        policy.he_comparison = dict(total=len(rows), observed=reviewed,
                                    pending=len(rows) - reviewed)
        best, job = min(options, key=lambda option: policy._he_order(option[0])) if options else (None, None)
        if reviewed < len(rows) or best is not None and best is not policy._current(job, require_line=True):
            # A proved contact can qualify the route stop while the remaining
            # contacts are being compared. Only the completed ranking can fire.
            fresh = [row for row, job in options if row is policy._current(job, require_line=True)
                     and (policy._executable(row, mode) or row.get('he_route_review'))]
            if fresh:
                impact = min(fresh, key=policy._he_order)
            if impact is not None:
                return policy._choose('preaim', 'he_damage_comparison_pending', impact)
            return policy._recover_incomplete(now, 'he_damage_comparison_pending')
        if best is None:
            return self._no_he_contact(policy, rows, 'ordered_he_no_clear_contact')
        self.he_sample = best['sample']
        if policy._executable(best, mode):
            return self._aim(policy, now, best, 'current_he_fallback_contact', tuple(rows))
        return policy._choose('firing_position', 'ordered_he_hull_lay', best)

    @staticmethod
    def _no_he_contact(policy, rows, reason):
        # A known wreck, world or friendly lane can still enter the existing
        # finite recovery. It cannot qualify a fresh route attack. A live
        # front enemy is merely an excluded point.
        blocked = next((row for row in rows if row is not None and
                        row.get('line') in ('friendly_blocked', 'world_blocked') and
                        isinstance(row.get('solution'), dict)), None)
        if blocked is not None:
            return policy._choose('firing_position', 'he_fallback_obstructed', blocked)
        return policy._choose('navigate', reason)

    @staticmethod
    def _can_lay(policy, row, mode):
        if row is None or row.get('line') in ('enemy_blocked', 'vehicle_blocked',
                                             'friendly_blocked', 'world_blocked'):
            return False
        refusal = row.get('stationary_pending') or ''
        return (policy._executable(policy._planned_evidence(row), mode) or
                'blocked' not in refusal and 'actuator_unavailable' not in refusal and
                row.get('line') == 'clear' and row.get('mechanical') == 'hull_laying' and
                policy._attack_result(row, mode))

    @staticmethod
    def _negative_evidence(policy, job, row):
        if policy._reviewed(row, 'penetration') and not policy._plannable(row):
            return row
        previous = policy._next_row(job)
        if (previous is not None and previous.get('line') == 'clear' and
                previous.get('armor') == 'failed' and policy._reviewed(previous, 'penetration')
                and not (row or {}).get('stationary_progress')):
            return previous
        return None

    @staticmethod
    def _clear_failure(policy, row):
        evidence = policy._planned_evidence(row) or row or {}
        return evidence.get('line') == 'clear' and evidence.get('armor') == 'failed'

    @staticmethod
    def _unproved_hull_lay(row):
        return (row is not None and row.get('line') == 'clear' and
                row.get('mechanical') == 'hull_laying' and row.get('armor') == 'unknown' and
                row.get('stationary_pending') == 'stationary_native_projection_unavailable')

    def _inspect(self, policy, now, jobs, refresh=None):
        current = [policy._current(job, require_line=True) for job in jobs]
        for row in current:
            if policy._executable_current(row):
                return 'aim', row
        # A cached armour failure can finish the penetration sweep. The
        # previously clear contact still needs its own fresh lane check.
        priority = refresh or policy.selected
        pending = [index for index, (job, row) in enumerate(zip(jobs, current))
                   if not self._can_lay(policy, row, 'penetration') and
                   not policy._executable(row) and
                   (job[0] == refresh and not policy._reviewed(row, 'penetration') or
                    self._negative_evidence(policy, job, row) is None)]
        pending.sort(key=lambda index: (jobs[index][0] != priority,
                                       (index - self.cursor) % len(jobs)))
        for index in pending:
            if policy._used['foreground'] >= policy.foreground_budget:
                break
            self.cursor = index + 1
            row = policy._evaluate(jobs[index], now, 'foreground')
            current[index] = row
            if policy._executable_current(row):
                return 'aim', row
        unfinished = [jobs[index] for index in pending
                      if not policy._executable(current[index]) and
                      not self._can_lay(policy, current[index], 'penetration') and
                      self._negative_evidence(policy, jobs[index], current[index]) is None]
        if unfinished:
            by_key = dict((job[0], index) for index, job in enumerate(jobs))
            for row in policy._ordered_point_slice(unfinished, now):
                index = by_key[row['key']]
                current[index] = row
                self.cursor = index + 1
                if policy._executable_current(row):
                    return 'aim', row
        for row in current:
            if self._can_lay(policy, row, 'penetration'):
                return 'firing_position', row
        if any(policy._executable(row) for row in current):
            # A protected movement task can withhold this proved shot.
            # Review another target for the same shell without calling it failed.
            return 'navigation_owned', None
        evidence = [self._negative_evidence(policy, job, row)
                    for job, row in zip(jobs, current)]
        clear = next((row for row in evidence if self._clear_failure(policy, row)), None)
        blocked = next((row for row in current if row is not None and
                        row.get('line') in ('friendly_blocked', 'world_blocked') and
                        isinstance(row.get('solution'), dict)), None)
        if not all(evidence):
            if any(row and row.get('stationary_progress') for row in current):
                return 'stationary_wait', None
            lay = next((row for row in current if self._unproved_hull_lay(row)), None)
            if lay is not None:
                return 'native_lay', lay
            return 'wait', blocked
        range_limited = next((row for row in current if row is not None and
            row.get('scope_reason') == 'outside_stationary_horizontal_range'), None)
        return 'complete', clear or blocked or range_limited

    def update(self, policy, now):
        frame = policy.frame
        shell = next((row for row in frame['shells'] if row['index'] == frame['loaded']), None)
        if shell is None or shell.get('unavailable'):
            return policy._choose('wait', 'ordered_shell_descriptor_pending')
        self._sync(frame, shell)
        if frame['ammo'][shell['index']] <= 0 or (frame['clip_size'] > 1 and
                frame['clip'] <= 0 and not frame.get('reloading')):
            index, reason = ((shell['index'], 'keep_mounted_shell') if frame['ammo'][shell['index']] > 0
                             else self.next_load(policy))
            replacement = next((row for row in frame['shells'] if row['index'] == index), None)
            if replacement is not None:
                return self._switch(policy, replacement, reason)
            return policy._choose('navigate', 'ordered_ammunition_exhausted')
        if not self.order:
            return policy._choose('wait', 'no_relevant_enemy')
        jobs = policy._jobs(shell_index=shell['index'])
        if shell['is_he']:
            return self._current_he(policy, now, shell, jobs)
        # Reuse one accepted target for the current shot. A complete sweep
        # rewinds only when the load changes or a later sweep starts.
        groups = dict((key, []) for key in self.order)
        for job in jobs:
            groups[job[0][1]].append(job)
        combat = getattr(policy.runtime, 'combat_stop', None)
        confirming = (combat is not None and not combat.combat_owned and
                      combat._route_requires_confirmation(combat.task_order))
        if confirming:
            result = self._route_opportunity(policy, now,
                tuple(job for key in self.order for job in groups[key]), combat)
            if result is not None:
                return result
        obstructed = None
        navigation_owned = False
        for key in self.order:
            target_jobs = groups[key]
            if key in self.covered and all(self._negative_evidence(
                    policy, job, policy._current(job, require_line=True)) for job in target_jobs):
                continue
            self.covered.discard(key)
            self.checked_lanes.discard(key)
            if self.target != key:
                self.target, self.sample, self.cursor = key, None, 0
            if policy.selected is not None and policy.selected[1] == key:
                target_jobs.sort(key=lambda job: job[0] != policy.selected)
            action, row = self._inspect(policy, now, target_jobs)
            if row is not None and action != 'wait':
                self.sample = row['sample']
            if action == 'aim':
                self._retain_target(row)
                return self._aim(policy, now, row, 'current_shell_verified')
            if action == 'firing_position':
                return policy._choose(action, 'current_penetration_after_stationary_turn', row)
            if action == 'native_lay':
                return policy._choose('firing_position', 'unverified_points_obstructed', row)
            if action == 'navigation_owned':
                navigation_owned = True
                continue
            if action in ('wait', 'stationary_wait'):
                if row is not None and confirming:
                    # The existing route gate can report a checked blocked
                    # point without granting it movement or ending this pass.
                    return policy._choose('firing_position', 'unverified_points_obstructed', row)
                reason = ('stationary_domain_review_pending' if action == 'stationary_wait'
                          else 'ordered_current_target_pending')
                return policy._recover_incomplete(now, reason)
            self.covered.add(key)
            if row is not None:
                if self._clear_failure(policy, row):
                    self.checked_lanes.add(key)
                else:
                    obstructed = obstructed or row
        if navigation_owned:
            return policy._choose('wait', 'current_shot_navigation_owned')
        recovery = next((policy._current(job, require_line=True) for job in jobs
                         if job[0] == policy.selected), None)
        if recovery and recovery.get('line') in ('friendly_blocked', 'world_blocked'):
            reason = ('current_penetration_obstructed' if recovery.get('armor') == 'passed'
                      else 'unverified_points_obstructed')
            return policy._choose('firing_position', reason, recovery,
                                  movement_reason=recovery.get('reason'))
        if not self.checked_lanes:
            self.covered.clear()
            if obstructed is not None:
                return policy._choose('firing_position', 'unverified_points_obstructed', obstructed)
            return policy._choose('navigate', 'ordered_no_clear_lane')
        if not policy._failure_fenced((shell['index'],)):
            self.covered.clear()
            self.checked_lanes.clear()
            return policy._recover_incomplete(now, 'ordered_sweep_observation_changed')
        if any(row.get('unavailable') and frame['ammo'][row['index']] > 0
               for row in frame['shells']):
            return policy._recover_incomplete(now, 'ordered_reserve_descriptor_pending')
        higher = [row for row in stocked(frame, False)
                  if row['piercing'] > shell['piercing']]
        if higher:
            if frame['clip_size'] > 1 and frame['clip'] > 0 and policy.reload_authority is None:
                policy._grant_early_reload(now, 'ordered_penetration_exhausted')
            return self._switch(policy, higher[0], 'ordered_penetration_exhausted')
        explosive = stocked(frame, True)
        if explosive:
            if frame['clip_size'] > 1 and frame['clip'] > 0 and policy.reload_authority is None:
                policy._grant_early_reload(now, 'ordered_he_fallback_load')
            return self._switch(policy, explosive[0], 'ordered_he_fallback_load')
        policy.reload_authority = None
        self.covered.clear()
        self.checked_lanes.clear()
        return policy._choose('navigate', 'ordered_no_he')
