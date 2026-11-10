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
        self.he_fallback = False
        self.he_identity = None
        self.covered = set()
        self.checked_lanes = set()
        self.cursor = 0

    def _sync(self, frame, shell):
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
            self.he_sample, self.he_fallback = None, False
            self.he_identity = None
            self.covered.clear()
            self.checked_lanes.clear()
            self.cursor = 0
        if self.target not in live:
            self.target, self.sample, self.he_sample = None, None, None
            self.he_fallback = False

    def next_load(self, frame):
        loaded = frame['loaded']
        shell = next((row for row in frame['shells'] if row['index'] == loaded), None)
        if shell is None:
            return None, 'shell_descriptor_pending'
        penetration = stocked(frame, False)
        if shell['is_he']:
            if penetration:
                return penetration[0]['index'], 'he_finished_lowest_penetration'
        elif frame['ammo'][loaded] <= frame['clip']:
            reserve = [row for row in penetration if row['index'] != loaded]
            reserve = reserve or stocked(frame, True)
            if reserve:
                return reserve[0]['index'], 'mounted_stock_exhausted'
        return None, 'keep_mounted_shell'

    def _switch(self, policy, shell, reason):
        action = 'reload_clip' if policy.frame['clip_size'] > 1 else 'switch_shell'
        return policy._choose(action, reason, shell_index=shell['index'],
                              early_reload=policy.frame['clip'] > 0 and policy.frame['ammo'][self.loaded] > 0)

    def _aim(self, policy, now, row, reason):
        fence = getattr(policy.evaluator, 'fence_next', None)
        if row['observed_at'] == now and callable(fence) and not fence(policy.frame, (row,), False):
            policy.rows.clear()
            policy.selected = None
            policy._frame_invalid = True
            return policy._recover_incomplete(now, 'ordered_point_observation_changed')
        policy.fallback = row['mode'] == 'he_fallback'
        policy.reload_authority = None
        return policy._choose('aim', reason, row)

    def _current_he(self, policy, now, shell, jobs):
        if self.target is None:
            self.target = self.order[0]
        target = next(row for row in policy.frame['targets'] if row['key'] == self.target)
        identity = target.get('sample_identity')
        if identity != self.he_identity:
            self.he_sample, self.he_fallback = None, False
            self.he_identity = identity
        if self.he_sample is None:
            points = [job[3] for job in jobs if job[0][1] == self.target]
            self.he_sample = self.sample if self.sample in points else points[0]
            self.he_fallback = False
        for mode in (('he_fallback',) if self.he_fallback else ('penetration', 'he_fallback')):
            job = next((job for job in policy._jobs(mode, shell['index'])
                        if job[0][1:3] == (self.target, self.he_sample)), None)
            if job is None:
                return policy._choose('wait', 'ordered_he_point_unavailable')
            row = policy._current(job, require_line=True)
            if not policy._plannable(row, mode) and not policy._reviewed(row, mode):
                if policy._used['foreground'] < policy.foreground_budget:
                    row = policy._evaluate(job, now, 'foreground')
            if policy._executable(row, mode):
                reason = 'current_he_fallback_contact' if mode == 'he_fallback' else 'current_shell_verified'
                return self._aim(policy, now, row, reason)
            if self._can_lay(policy, row, mode):
                return policy._choose('firing_position', 'ordered_he_hull_lay', row)
            if self._unproved_hull_lay(row):
                return policy._choose('firing_position', 'unverified_points_obstructed', row)
            if (row is not None and row.get('line') in ('friendly_blocked', 'world_blocked') and
                    isinstance(row.get('solution'), dict)):
                return policy._choose('firing_position', 'he_fallback_obstructed', row)
            if (mode == 'penetration' and row is not None and row.get('line') == 'clear'
                    and row.get('mechanical') == 'reachable' and row.get('armor') == 'failed'):
                self.he_fallback = True
                continue
            return policy._recover_incomplete(now, 'ordered_he_point_wait', (row,) if row else ())
        return policy._choose('wait', 'ordered_he_point_wait')

    @staticmethod
    def _can_lay(policy, row, mode):
        if row is None or row.get('line') in ('enemy_blocked', 'vehicle_blocked',
                                             'friendly_blocked', 'world_blocked'):
            return False
        refusal = row.get('stationary_pending') or ''
        return (policy._executable(policy._planned_evidence(row), mode) or
                'blocked' not in refusal and 'actuator_unavailable' not in refusal and
                row.get('line') == 'clear' and row.get('mechanical') == 'hull_laying' and
                (row.get('armor') == 'passed' or row.get('route_he_damage', 0.) > 0.))

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

    def _inspect(self, policy, now, jobs):
        current = [policy._current(job, require_line=True) for job in jobs]
        for row in current:
            if policy._executable_current(row):
                return 'aim', row
        pending = [index for index, (job, row) in enumerate(zip(jobs, current))
                   if not self._can_lay(policy, row, 'penetration') and
                   not policy._executable(row) and
                   self._negative_evidence(policy, job, row) is None]
        pending.sort(key=lambda index: (jobs[index][0] != policy.selected,
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
        return 'complete', clear or blocked

    def update(self, policy, now):
        frame = policy.frame
        shell = next((row for row in frame['shells'] if row['index'] == frame['loaded']), None)
        if shell is None or shell.get('unavailable'):
            return policy._choose('wait', 'ordered_shell_descriptor_pending')
        self._sync(frame, shell)
        if frame['ammo'][shell['index']] <= 0 or (frame['clip_size'] > 1 and
                frame['clip'] <= 0 and not frame.get('reloading')):
            index, reason = self.next_load(frame)
            index = shell['index'] if index is None and frame['ammo'][shell['index']] > 0 else index
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
                self.covered.clear()
                self.checked_lanes.clear()
                self.order.remove(key)
                self.order.insert(0, key)
                return self._aim(policy, now, row, 'current_shell_verified')
            if action == 'firing_position':
                return policy._choose(action, 'current_penetration_after_stationary_turn', row)
            if action == 'native_lay':
                return policy._choose('firing_position', 'unverified_points_obstructed', row)
            if action == 'navigation_owned':
                navigation_owned = True
                continue
            if action in ('wait', 'stationary_wait'):
                combat = getattr(policy.runtime, 'combat_stop', None)
                if (row is not None and combat is not None and not combat.combat_owned and
                        combat._route_requires_confirmation(combat.task_order)):
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
