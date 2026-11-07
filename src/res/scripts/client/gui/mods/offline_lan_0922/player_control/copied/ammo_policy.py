from __future__ import division

"""Bot ammunition ordering, whole-magazine allocation and admitted-shot policy.

This module is shared by the Python 2 worker and Python 3 server. No policy
decision consumes ammunition or restarts a reload timer.
"""

from gui.mods.offline_lan_0922.player_control.copied.default_loadouts import (
    GOLD_SHELLS, ELITE_PENETRATION_EXCEPTIONS, profile_roles)


def is_he(shell):
    return str(shell.get('kind', '')).upper() == 'HIGH_EXPLOSIVE'


def _elite_loadout(profile):
    """Upgrade native default rounds without losing HE-primary backups."""
    if profile.get('bot_tier') != 'elite' or 'ammo_ratios' in profile:
        return None
    base = dict(profile)
    base.pop('bot_tier', None)
    shells = stages(base)
    proportions = weights(base, shells)
    nation = str(profile.get('vehicle_name', '')).split(':')[0]
    def premium(shell):
        return nation + ':' + shell.get('name', '') in GOLD_SHELLS
    keep_penetration = (bool(shells and is_he(shells[0])) or
                        (profile.get('vehicle_name'), profile.get('gun_name'))
                        in ELITE_PENETRATION_EXCEPTIONS)
    candidates = [s for s in shells if not is_he(s) and premium(s)]
    if not candidates:
        candidates = [s for s in profile.get('shells', ())
                      if not is_he(s) and premium(s)]
    he_candidates = [s for s in shells if is_he(s) and premium(s)]
    if not he_candidates:
        he_candidates = [s for s in profile.get('shells', ())
                         if is_he(s) and premium(s)]
    replacement = candidates[0] if candidates and not keep_penetration else None
    he_replacement = he_candidates[0] if he_candidates else None
    quotas = {}
    result = []
    changed = False
    for shell, proportion in zip(shells, proportions):
        chosen = shell
        if not premium(shell):
            upgrade = he_replacement if is_he(shell) else replacement
            if upgrade is not None:
                chosen = upgrade
                changed = True
        index = int(chosen['index'])
        if index not in quotas:
            result.append(chosen)
            quotas[index] = 0
        quotas[index] += proportion
    return (result, quotas) if changed else None


def ordered(profile, remaining=None):
    elite = _elite_loadout(profile)
    if elite is not None:
        shells = elite[0]
        if remaining is not None:
            shells = [s for s in shells if int(s['index']) < len(remaining)
                      and remaining[int(s['index'])] > 0]
        return shells
    shells = list(profile.get('shells') or ())
    manual = 'ammo_ratios' in profile
    roles = None if manual else profile_roles(profile)
    if roles is not None:
        shells = [s for s in shells if int(s['index']) in roles]
        shells.sort(key=lambda s: ('standard', 'premium', 'he').index(roles[int(s['index'])]))
    else:
        kinds = {'ARMOR_PIERCING': 0, 'ARMOR_PIERCING_CR': 1,
                 'HOLLOW_CHARGE': 2, 'HIGH_EXPLOSIVE': 3}
        nation = str(profile.get('vehicle_name', '')).split(':')[0]
        shells.sort(key=lambda s: (
            4 * int(nation + ':' + s.get('name', '') in GOLD_SHELLS) +
            kinds.get(str(s.get('kind', '')).upper(), 4), int(s['index'])))
    if manual:
        proportions = profile['ammo_ratios']
        shells = [s for i,s in enumerate(shells) if i < len(proportions) and proportions[i] > 0]
    elif profile.get('class_tag') == 'SPG':
        shells = [s for s in shells if is_he(s)]
    elif shells and is_he(shells[0]):
        # HE-primary guns have one explicit non-HE probe, never two backups.
        shells = shells[:1] + [s for s in shells[1:] if not is_he(s)][:1]
    if remaining is not None:
        shells = [s for s in shells if int(s['index']) < len(remaining)
                  and remaining[int(s['index'])] > 0]
    return shells


def stages(profile, remaining=None):
    shells = ordered(profile)
    if 'ammo_ratios' in profile:
        pass
    elif shells and profile.get('class_tag') != 'SPG' and is_he(shells[0]):
        shells = shells[:1] + [s for s in shells[1:] if not is_he(s)][:1]
    elif profile.get('class_tag') != 'SPG':
        shells = [s for s in shells if not is_he(s)] + [s for s in shells if is_he(s)]
    if remaining is not None:
        shells = [s for s in shells if int(s['index']) < len(remaining)
                  and remaining[int(s['index'])] > 0]
        # Runtime stocks, including explicitly mounted/custom HE, are distinct
        # from default allocation. Do not alter any loadout or quota here.
        nation = str(profile.get('vehicle_name', '')).split(':')[0]
        he = [s for s in profile.get('shells', ()) if is_he(s)
              and int(s['index']) < len(remaining) and remaining[int(s['index'])] > 0]
        if he:
            preferred = max(he, key=lambda s: (
                nation+':'+s.get('name', '') in GOLD_SHELLS, -int(s['index'])))
            he_primary = bool(ordered(profile) and is_he(ordered(profile)[0]))
            shells = [s for s in shells if not is_he(s)]
            shells = [preferred]+shells if he_primary else shells+[preferred]
    return shells


def clip_size(profile):
    return max(1, int(profile.get('clip_size', 1)))


def weights(profile, shells):
    elite = _elite_loadout(profile)
    if elite is not None:
        return tuple(elite[1][int(s['index'])] for s in shells)
    if 'ammo_ratios' in profile:
        raw = dict(profile)
        raw.pop('ammo_ratios')
        # Reconstruct the full native price/kind order without the default
        # gun whitelist. Zero weights never receive a rounding minimum.
        raw['ammo_ratios'] = [1] * len(profile.get('shells', ()))
        indices = [int(s['index']) for s in ordered(raw)]
        return tuple(profile['ammo_ratios'][indices.index(int(s['index']))] for s in shells)
    if len(shells) <= 1:
        return (100,)
    if profile.get('class_tag') == 'SPG':
        return (75, 25) if clip_size(profile) > 1 else (80, 20)
    if is_he(shells[0]):
        return (80, 20)
    if len(shells) == 3:
        return (60, 30, 10)
    return (80, 20) if any(is_he(s) for s in shells) else (60, 40)


def apportion(total, proportions):
    """Nearest integer quotas, at least one unit per available choice, main ties."""
    proportions = tuple(proportions)
    if not proportions:
        return []
    target = [total * p / sum(proportions) for p in proportions]
    result = [1 if i < total else 0 for i in range(len(target))]
    for unused in range(max(0, total - sum(result))):
        index = max(range(len(result)), key=lambda i: (target[i] - result[i], -i))
        result[index] += 1
    return result


def allocation(profile, maximum, shell_count):
    if 'ammo_limit' in profile:maximum = min(int(maximum), int(profile['ammo_limit']))
    shells = stages(profile)
    size = clip_size(profile)
    units, remainder = divmod(int(maximum), size)
    counts = apportion(units, weights(profile, shells)) if shells else []
    result = [0] * shell_count
    for shell, count in zip(shells, counts):
        result[int(shell['index'])] = count * size
    if remainder and shells:
        # Current #1513 clips divide capacity exactly. Preserve capacity for
        # an explicitly supplied non-divisible fitting without enlarging a clip.
        result[int(shells[0]['index'])] += remainder
    return result


class ShotPolicy(object):
    """One round-owned Bot policy; terminal results drain in launch order."""

    def __init__(self, profile):
        self.profile = profile
        self.shells = stages(profile)
        self.inventory = None
        self.phase = int(self.shells[0]['index']) if self.shells else 0
        self.desired = self.phase
        self.anchor = None
        self.target = None
        self.epoch = 0
        self.magazine = 0
        self.used = 0
        self.phase_fired = 0
        self.phase_id = 0
        self.failures = {}
        self.pending = []
        self.by_seq = {}
        self.groups = {}
        self.group_sizes = {}
        self.group_counts = {}
        self.last_group = None

    def context(self, position, target):
        point = (float(position.get('x', 0)), float(position.get('z', 0)))
        moved = self.anchor is not None and sum((a-b)**2 for a, b in zip(point, self.anchor)) > 9.0
        if self.anchor is None or moved:
            self.anchor = point
        if moved or (target is not None and target != self.target):
            self.epoch += 1
            self.failures.clear()
        if target is not None:
            self.target = target

    def _same_phase(self, left, right):
        if left == right:
            return True
        rows = dict((int(s['index']), s) for s in self.profile.get('shells', ()))
        return left in rows and right in rows and is_he(rows[left]) and is_he(rows[right])

    def _close_group(self, group, count):
        if count <= 0:
            return
        self.group_sizes[group] = count
        rows = self.groups.get(group, ())
        if rows and len(rows) == count:
            row = dict(rows[-1], closed_group=True)
            self._result(row)

    def choose(self, state):
        if state.get('burst_active') is False and state.get('burst_group_seq'):
            self._close_group(int(state['burst_group_seq']), int(state.get('burst_next_index', 0)))
        self.inventory = state.get('ammo_remaining')
        available = stages(self.profile, self.inventory)
        if not available:
            return self.phase
        indices = [int(s['index']) for s in available]
        self.desired = next((i for i in indices if self._same_phase(i, self.desired)), indices[0])
        main = indices[0]
        if self.desired != self.phase:
            return self.desired
        loaded = self.phase
        if loaded not in indices:
            return self.desired
        actual = next(s for s in available if int(s['index']) == loaded)
        first_he = is_he(available[0])
        arty = self.profile.get('class_tag') == 'SPG'
        automatic = not self._same_phase(loaded, main) and (arty or first_he or is_he(actual) or clip_size(self.profile) > 1)
        if automatic:
            size = clip_size(self.profile)
            if size > 1:
                returning = self.used >= size
            else:
                limit = 1 if first_he and not arty else 2
                fired = self.phase_fired if loaded == self.phase else 0
                returning = fired >= limit
            if returning:
                return main
        return self.desired

    def launch(self, sequence, shell, group, count, position, target):
        if sequence in self.by_seq:
            return
        self.context(position, target)
        if self.last_group is not None and group != self.last_group:
            self._close_group(self.last_group, self.group_counts.get(self.last_group, 0))
        self.last_group = group
        self.group_counts[group] = self.group_counts.get(group, 0) + 1
        if shell != self.phase:
            old = self.phase
            self.phase = shell
            if not self._same_phase(old, shell):
                self.phase_id += 1
                self.failures.clear()
                self.phase_fired = 0
                self.used = 0
            if self.desired in (old, shell):
                self.desired = shell
        if self.used == 0 or self.used >= clip_size(self.profile):
            self.magazine += 1
            self.used = 0
        self.used += 1
        self.phase_fired += 1
        row = dict(seq=sequence, shell=shell, group=group, count=count,
                   epoch=self.epoch, phase_id=self.phase_id, magazine=self.magazine, result=None)
        self.pending.append(row)
        self.by_seq[sequence] = row

    def resolve(self, sequence, hit, damage, penetrated, known=True):
        row = self.by_seq.get(sequence)
        if row is None or row['result'] is not None:
            return
        row['result'] = (bool(hit), float(damage), bool(penetrated), bool(known))
        while self.pending and self.pending[0]['result'] is not None:
            current = self.pending.pop(0)
            self.by_seq.pop(current['seq'], None)
            self._result(current)

    def _result(self, row):
        hit, damage, penetrated, known = row['result']
        if row['count'] > 1:
            key = row['group']
            group = self.groups.setdefault(key, [])
            if not row.get('closed_group'):
                group.append(row)
            if len(group) < self.group_sizes.get(key, row['count']):
                return
            self.groups.pop(key, None)
            hit = any(r['result'][0] for r in group)
            damage = sum(r['result'][1] for r in group)
            penetrated = any(r['result'][2] for r in group)
            known = all(r['result'][3] for r in group)
            if any(r['epoch'] != row['epoch'] for r in group):
                return
        if not known:
            self.failures.clear()
            return
        if row['epoch'] != self.epoch or not self._same_phase(row['shell'], self.phase) or row['phase_id'] != self.phase_id:
            return
        if self.desired != self.phase:
            return  # An admitted upgrade remains latched.
        if not self.shells:
            return
        shell = next((s for s in self.profile.get('shells', ()) if int(s['index']) == row['shell']), None)
        arty = self.profile.get('class_tag') == 'SPG'
        active = stages(self.profile, self.inventory)
        first_he = bool(active and is_he(active[0])) and not arty
        if first_he and shell is not None and not is_he(shell):
            return
        if arty:
            failure, success = not hit and damage <= 0, hit or damage > 0
        elif first_he and shell is not None and is_he(shell):
            failure, success = hit and not penetrated, hit and penetrated
        else:
            failure, success = hit and damage <= 0, damage > 0
        key = (row['epoch'], row['magazine'] if clip_size(self.profile) > 1 else 0)
        if success:
            self.failures[key] = 0
        elif failure:
            self.failures[key] = self.failures.get(key, 0) + 1
        threshold = 1 if row['count'] > 1 else 2
        if self.failures.get(key, 0) >= threshold:
            indices = [int(s['index']) for s in stages(self.profile, self.inventory)]
            current = next((i for i in indices if self._same_phase(i, row['shell'])), None)
            if current is None or len(indices) < 2:
                return
            offset = indices.index(current)
            self.desired = indices[(offset + 1) % len(indices)]
            self.failures.clear()
