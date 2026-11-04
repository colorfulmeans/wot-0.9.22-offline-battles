"""Foreground-player ammunition decisions and ordered physical-shot receipts.

Only descriptor/loadout facts are shared with other controllers. The player's
phase, firing group and feedback history are owned by this instance.
"""
from __future__ import division


_KINDS = {'ARMOR_PIERCING': 0, 'ARMOR_PIERCING_CR': 1,
          'HOLLOW_CHARGE': 2, 'HIGH_EXPLOSIVE': 3}
_ROLES = ('standard', 'premium', 'he')


def mounted_shell_roles(descriptor, shots):
    """Map reviewed shell roles to actual GunState.shots, after shell_order."""
    from ..default_loadouts import shell_roles, value
    native_gun = value(descriptor, 'gun', {})
    return shell_roles(value(value(descriptor, 'type', {}), 'name', ''),
                       value(native_gun, 'name', ''),
                       [value(value(shot, 'shell', {}), 'name', '')
                        for shot in shots]) or {}


def mounted_shells(descriptor, shots):
    """Return semantic policy order without changing the player's fitting."""
    from ..default_loadouts import GOLD_SHELLS, value
    roles = mounted_shell_roles(descriptor, shots)
    nation = str(value(value(descriptor, 'type', {}), 'name', '')).split(':')[0]
    shells = []
    for index, shot in enumerate(shots):
        shell = value(shot, 'shell', {})
        name = value(shell, 'name', '')
        shells.append(dict(index=index, name=name,
                           kind=str(value(shell, 'kind', '')).upper(),
                           premium=nation + ':' + name in GOLD_SHELLS,
                           role=roles.get(index)))
    shells.sort(key=lambda row: (
        _ROLES.index(row['role']) if row['role'] in _ROLES else
        3 + 4 * int(row['premium']) + _KINDS.get(row['kind'], 4),
        row['index']))
    if shells:
        he = [row for row in shells if row['kind'] == 'HIGH_EXPLOSIVE']
        non_he = [row for row in shells if row['kind'] != 'HIGH_EXPLOSIVE']
        artillery = 'SPG' in value(value(descriptor, 'type', {}), 'tags', ())
        shells = he + non_he if he and (artillery or
            shells[0]['kind'] == 'HIGH_EXPLOSIVE') else non_he + he
    return shells


def policy_from_gun(gun, descriptor):
    """Build a player policy whose indices are exactly those consumed by gun."""
    from ..default_loadouts import value
    shells = mounted_shells(descriptor, gun.shots)
    if not shells:
        return None
    artillery = 'SPG' in value(value(descriptor, 'type', {}), 'tags', ())
    policy = Ammunition(shells, shells[0]['index'], gun.shot_index,
                        gun.clip_size, artillery)
    policy.protected = bool(0 <= gun.shot_index < len(gun.ammo) and
                            gun.ammo[gun.shot_index] > 0)
    return policy


class Ammunition(object):
    def __init__(self, shells, main, loaded, clip_size=1, artillery=False):
        self.shells = list(shells)
        self.main = main
        self.desired = loaded
        self.protected = True
        self.clip_size = max(1, int(clip_size))
        self.artillery = artillery
        self.phase = loaded
        self.fired = self.failures = 0
        self.target = None
        self.pending = []
        self.rows = {}
        self.anchor = None
        self.epoch = self.phase_id = self.magazine = self.used = 0
        self._failures = {}
        self._groups = {}
        self._last_group = None
        self._inventory = None
        self._clip_remaining = None

    @property
    def idle(self):
        """True once every accepted projectile and grouped result is drained."""
        return not self.pending and not self.rows and not self._groups

    def available(self, inventory):
        rows = [s for s in self.shells if 0 <= s['index'] < len(inventory)
                and inventory[s['index']] > 0]
        he = [s for s in rows if s['kind'] == 'HIGH_EXPLOSIVE']
        preferred = max(he, key=lambda s: (bool(s.get('premium')),
                                          -self.shells.index(s))) if he else None
        # Artillery retains its HE stage while any HE stock remains. A
        # manually loaded non-HE round is protected separately; remaining
        # non-HE stock is still usable after HE is exhausted.
        if self.artillery and preferred is not None:
            return [preferred['index']]
        # Both HE stocks occupy one logical stage. Exhaustion may select its
        # other physical stock, without resetting the two-round probe counter.
        return [s['index'] for s in rows
                if s['kind'] != 'HIGH_EXPLOSIVE' or s is preferred]

    def same_phase(self, left, right):
        if left == right:
            return True
        kinds = dict((s['index'], s['kind']) for s in self.shells)
        return kinds.get(left) == kinds.get(right) == 'HIGH_EXPLOSIVE'

    def effective_main(self, available):
        if self.main in available:
            return self.main
        return next((i for i in available if self.same_phase(i, self.main)),
                    available[0] if available else self.main)

    def _clear_failures(self):
        self._failures.clear()
        self.failures = 0

    def context(self, position, target):
        """Invalidate old feedback after a target change or a 3 m move."""
        point = None
        if position is not None:
            if isinstance(position, dict):
                point = (float(position.get('x', 0)),
                         float(position.get('z', 0)))
            else:
                point = (float(position[0]), float(position[2]))
        moved = (point is not None and self.anchor is not None and
                 sum((a-b)**2 for a, b in zip(point, self.anchor)) > 9.)
        if point is not None and (self.anchor is None or moved):
            self.anchor = point
        if moved or target != self.target:
            self.epoch += 1
            self._clear_failures()
        self.target = target

    def _automatic_return(self, available):
        # A failure decision is latched until its new shell is actually fired.
        # In particular the last APCR round of a clip must not overwrite HE.
        if (not available or self.protected or
                not self.same_phase(self.desired, self.phase)):
            return
        main = self.effective_main(available)
        kinds = dict((s['index'], s['kind']) for s in self.shells)
        he_main = kinds.get(main) == 'HIGH_EXPLOSIVE'
        automatic = (not self.same_phase(self.phase, main) and
                     (self.artillery or he_main or self.clip_size > 1 or
                      kinds.get(self.phase) == 'HIGH_EXPLOSIVE'))
        limit = self.clip_size if self.clip_size > 1 else (
            1 if he_main and not self.artillery else 2)
        count = self.used if self.clip_size > 1 else self.fired
        if automatic and count >= limit:
            self.desired = main

    def choose(self, inventory, position=None, target=None, burst=None):
        """Choose only; physical reload and inventory remain owned by GunState.

        Optional burst is the foreground admitted-group receipt, with keys
        active, group and committed. A cancelled tail closes at its real count.
        """
        self._inventory = inventory
        if position is not None:
            self.context(position, target)
        if burst is not None and not burst.get('active', True):
            self.close_group(burst.get('group'), burst.get('committed', 0))
        available = self.available(inventory)
        if self.protected and not (0 <= self.desired < len(inventory) and
                                   inventory[self.desired] > 0):
            self.protected = False
        if available and not self.protected:
            self.desired = next((i for i in available
                                 if self.same_phase(i, self.desired)),
                                available[0])
            self._automatic_return(available)
        return self.desired

    def close_group(self, group, count=None):
        """Close a burst using accepted rounds, including a cancelled tail."""
        entry = self._groups.get(group)
        if entry is None:
            return
        actual = entry['admitted'] if count is None else int(count)
        if actual <= 0:
            return
        entry['expected'] = min(actual, entry['admitted'])
        self._finish_group(group)

    def launch(self, projectile, shell, target, now, position=None,
               group=None, count=1, clip_remaining=None):
        projectile = str(projectile)
        if projectile in self.rows:
            return
        self.context(position, target)
        group = projectile if group is None else group
        if self._last_group is not None and group != self._last_group:
            self.close_group(self._last_group)
        self._last_group = group
        entry = self._groups.setdefault(group, dict(
            admitted=0, expected=max(1, int(count)), results=[]))
        entry['admitted'] += 1
        if shell != self.phase:
            old = self.phase
            self.phase = shell
            if not self.same_phase(old, shell):
                self.phase_id += 1
                self.fired = self.used = 0
                self._clear_failures()
            if self.desired in (old, shell):
                self.desired = shell
        if clip_remaining is None:
            new_magazine = self.used == 0 or self.used >= self.clip_size
            used = 1 if new_magazine else self.used + 1
        else:
            remaining = int(clip_remaining)
            if not 0 <= remaining < self.clip_size:
                raise ValueError('invalid committed native clip count')
            new_magazine = (self.used == 0 or self._clip_remaining is None or
                            remaining >= self._clip_remaining)
            used = self.clip_size - remaining
            self._clip_remaining = remaining
        if new_magazine:
            self.magazine += 1
            self.failures = 0
        self.used = used
        self.fired += 1
        row = dict(id=projectile, shell=shell, target=target, launched=now,
                   terminal=None, hit=None, damage=0., penetrated=False,
                   epoch=self.epoch, phase_id=self.phase_id,
                   magazine=self.magazine, group=group, count=max(1, int(count)))
        self.rows[projectile] = row
        self.pending.append(row)
        if self.protected:
            self.protected = False
            self.desired = self.main

    def hit(self, event):
        row = self.rows.get(str(event.get('projectile_id')))
        if row is not None:
            row['hit'] = True
            row['damage'] += max(0., float(event.get('damage', 0)))
            row['penetrated'] |= int(event.get('shot_result', -1)) == 2

    def terminal(self, event, now):
        row = self.rows.get(str(event.get('projectile_id')))
        if row is not None and row['terminal'] is None:
            row['terminal'] = now
            row['vehicle_contact'] = bool(event.get('hit_vehicle'))

    def _finish_group(self, group):
        entry = self._groups.get(group)
        if entry is None or len(entry['results']) < entry['expected']:
            return
        self._groups.pop(group, None)
        rows = entry['results']
        row = dict(rows[-1])
        row['actual_count'] = entry['expected']
        row['hit'] = any(r['hit'] for r in rows)
        row['damage'] = sum(r['damage'] for r in rows)
        row['penetrated'] = any(r['penetrated'] for r in rows)
        row['known'] = all(r['known'] for r in rows)
        if any((r['epoch'], r['phase_id'], r['shell']) !=
               (row['epoch'], row['phase_id'], row['shell']) for r in rows):
            return
        self._result(row)

    def _result(self, row):
        if (row['epoch'] != self.epoch or row['phase_id'] != self.phase_id or
                not self.same_phase(row['shell'], self.phase)):
            return
        if not row['known']:
            self._clear_failures()
            return
        if not self.same_phase(self.desired, self.phase):
            return
        available = self.available(self._inventory or ())
        if not available:
            return
        kinds = dict((s['index'], s['kind']) for s in self.shells)
        he_main = kinds.get(self.effective_main(available)) == 'HIGH_EXPLOSIVE'
        if self.artillery:
            failure = not row['hit'] and row['damage'] <= 0
            success = bool(row['hit']) or row['damage'] > 0
        elif he_main and kinds.get(row['shell']) != 'HIGH_EXPLOSIVE':
            return
        elif he_main:
            failure = bool(row['hit']) and not row['penetrated']
            success = bool(row['hit']) and row['penetrated']
        else:
            failure = bool(row['hit']) and row['damage'] <= 0
            success = row['damage'] > 0
        key = (row['epoch'], row['magazine'] if self.clip_size > 1 else 0)
        if success:
            self._failures[key] = 0
        elif failure:
            self._failures[key] = self._failures.get(key, 0) + 1
        self.failures = self._failures.get(key, 0)
        threshold = 1 if row['count'] > 1 else 2
        if self.failures >= threshold and len(available) > 1:
            current = next((i for i in available
                            if self.same_phase(i, row['shell'])), None)
            if current is not None:
                self.desired = available[(available.index(current)+1) % len(available)]
                self._clear_failures()

    def settle(self, inventory, now):
        self._inventory = inventory
        results = []
        while self.pending:
            row = self.pending[0]
            if row['terminal'] is None:
                break
            # Impact precedes damage effects in the canonical event stream.
            unknown = row['vehicle_contact'] and row['hit'] is None
            if unknown and now-row['terminal'] < 2.:
                break
            self.pending.pop(0)
            self.rows.pop(row['id'], None)
            row['known'] = not unknown
            results.append(row)
            entry = self._groups.get(row['group'])
            if entry is not None:
                entry['results'].append(row)
                self._finish_group(row['group'])
        self._automatic_return(self.available(inventory))
        return results
