from __future__ import print_function

"""Controller-independent trigger execution for the pinned #1513 gun law.

``gun.burst`` is already decoded by the client as ``(count, interval)``.
Every element in the group is a real shell: it has its own ammunition debit,
dispersion sample, projectile ledger entry and terminal.  ``shot_seq`` remains
a strictly increasing physical-shell sequence for the existing LAN fences;
``group_seq`` plus ``burst_index`` preserves the native trigger grouping used
by presentation and server-side projectile reconstruction. A clock is owned by
the weapon, not the controller that requested its first shot. Losing a target,
alignment or controller never withdraws a committed trigger.

Scheduling and committing are deliberately separate. Asking which rounds are
due does not spend ammunition, advance the committed sequence, or finish the
trigger. Only the physical launch transaction may commit an edge.
"""

import math


MAX_BURST_COUNT = 64
MAX_BURST_INTERVAL_SECONDS = 10.0
_EPSILON = 1.0e-9

TERMINAL_REASONS = frozenset((
    'actor_destroyed', 'battle_ended', 'round_changed', 'gun_unavailable',
    'weapon_replaced', 'ammunition_unavailable', 'launch_unavailable',
    'transport_unavailable', 'native_failure',
))


def _field(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def descriptor_burst(gun):
    """Return the validated ``(count, interval)`` for one installed gun."""
    raw = _field(gun, 'burst', (1, 0.0)) or (1, 0.0)
    try:
        count = int(raw[0])
        interval = float(raw[1]) if len(raw) > 1 else 0.0
    except (TypeError, ValueError, IndexError, OverflowError):
        raise ValueError('installed gun burst is malformed')
    if (isinstance(raw[0], bool) or count < 1 or
            count > MAX_BURST_COUNT or float(raw[0]) != count or
            math.isnan(interval) or math.isinf(interval) or
            interval < 0.0 or interval > MAX_BURST_INTERVAL_SECONDS or
            (count > 1 and interval <= 0.0)):
        raise ValueError('installed gun burst is invalid')
    return count, interval if count > 1 else 0.0


def planned_count(gun, ammunition, loaded_clip):
    """Clamp one trigger to the real carried and currently loaded rounds."""
    count, interval = descriptor_burst(gun)
    try:
        ammunition = int(ammunition)
        loaded_clip = int(loaded_clip)
    except (TypeError, ValueError, OverflowError):
        return 0, interval
    return max(0, min(count, ammunition, loaded_clip)), interval


def after_shot_factor(gun, final_round):
    """Return #1513's bloom term for this physical round in a group."""
    factors = _field(gun, 'shotDispersionFactors', {}) or {}
    name = 'afterShot' if final_round else 'afterShotInBurst'
    fallback = _field(factors, 'afterShot', 1.5)
    try:
        value = float(_field(factors, name, fallback))
    except (TypeError, ValueError, OverflowError):
        raise ValueError('installed gun burst dispersion is malformed')
    if math.isnan(value) or math.isinf(value) or value < 0.0:
        raise ValueError('installed gun burst dispersion is invalid')
    return value


class TriggerClock(object):
    """One admitted trigger, with a physical-shell commit frontier.

    ``next_index`` counts committed shells, never speculative due events.
    ``time_left`` may be negative while overdue edges are being drained in the
    current simulation step. Published snapshots must follow their commits.
    """

    WIRE_FIELDS = (
        'burst_active', 'burst_group_seq', 'burst_count',
        'burst_next_index', 'burst_interval', 'burst_time_left',
        'burst_shell_index',
    )

    def __init__(self):
        self.active = False
        self.group_seq = 0
        self.count = 0
        self.next_index = 0
        self.interval = 0.0
        self.time_left = 0.0
        self.shell_index = 0
        self.terminal_reason = None

    def start(self, first_shot_seq, count, interval, shell_index):
        """Prepare a trigger whose first physical edge is due immediately."""
        if self.active:
            return False
        try:
            first_shot_seq = int(first_shot_seq)
            count = int(count)
            interval = float(interval)
            shell_index = int(shell_index)
        except (TypeError, ValueError, OverflowError):
            return False
        if (first_shot_seq <= 0 or count < 1 or
                count > MAX_BURST_COUNT or shell_index < 0 or
                math.isnan(interval) or math.isinf(interval) or
                interval < 0.0 or interval > MAX_BURST_INTERVAL_SECONDS or
                (count > 1 and interval <= 0.0)):
            return False
        self.active = True
        self.group_seq = first_shot_seq
        self.count = count
        self.next_index = 0
        self.interval = interval if count > 1 else 0.0
        self.time_left = 0.0
        self.shell_index = shell_index
        self.terminal_reason = None
        return True

    def advance(self, dt):
        """Advance weapon time and expose every due, uncommitted shell."""
        if not self.active:
            return ()
        try:
            dt = max(0.0, float(dt))
        except (TypeError, ValueError, OverflowError):
            return ()
        if math.isnan(dt) or math.isinf(dt):
            return ()
        previous_time_left = self.time_left
        self.time_left -= dt
        due = []
        index = self.next_index
        while (index < self.count and
               self.time_left + (index - self.next_index) * self.interval <= _EPSILON):
            offset = previous_time_left + (index - self.next_index) * self.interval
            due.append({
                'shot_seq': self.group_seq + index,
                'burst_group_seq': self.group_seq,
                'burst_index': index,
                'burst_count': self.count,
                'shell_index': self.shell_index,
                'final': index + 1 >= self.count,
                # This is the physical edge inside the caller's elapsed
                # interval, not the render callback receipt time.
                'due_offset': min(dt, max(0.0, offset)),
            })
            index += 1
        return tuple(due)

    def accepts(self, edge):
        """Validate identity/cadence only; tactical approval is not an input."""
        if not self.active or self.time_left > _EPSILON or not isinstance(edge, dict):
            return False
        try:
            return bool(
                edge['shot_seq'] == self.group_seq + self.next_index and
                edge['burst_group_seq'] == self.group_seq and
                edge['burst_index'] == self.next_index and
                edge['burst_count'] == self.count and
                edge['shell_index'] == self.shell_index and
                bool(edge['final']) == (self.next_index + 1 == self.count))
        except (KeyError, TypeError, ValueError, OverflowError):
            return False

    def commit(self, edge):
        """Advance exactly once after the corresponding physical launch."""
        if not self.accepts(edge):
            return False
        self.next_index += 1
        if self.next_index == self.count:
            self.active = False
            self.time_left = 0.0
        else:
            self.time_left += self.interval
        return True

    def abort(self):
        """Withdraw a request only before its first physical shell commits."""
        if self.next_index != 0:
            return False
        changed = self.active or self.count > 0
        self.active = False
        self.group_seq = 0
        self.count = 0
        self.interval = 0.0
        self.shell_index = 0
        self.time_left = 0.0
        return changed

    def terminate(self, reason):
        """End an impossible physical execution, never a tactical decision."""
        if reason not in TERMINAL_REASONS:
            raise ValueError('trigger termination is not a physical lifecycle reason')
        if not self.active:
            return False
        if self.next_index == 0:
            changed = self.abort()
        else:
            changed = True
            self.active = False
            self.time_left = 0.0
        self.terminal_reason = reason
        return changed

    def publish(self, target):
        if self.active and (self.next_index == 0 or self.time_left < -_EPSILON):
            raise ValueError('trigger snapshot precedes due physical commits')
        target.update({
            'burst_active': bool(self.active),
            'burst_group_seq': int(self.group_seq),
            'burst_count': int(self.count),
            'burst_next_index': int(self.next_index),
            'burst_interval': round(float(self.interval), 6),
            'burst_time_left': round(max(0.0, float(self.time_left)), 6),
            'burst_shell_index': int(self.shell_index),
        })

    def restore(self, raw, fire_seq):
        """Validate and load one complete server-sanitized wire snapshot."""
        present = tuple(name in raw for name in self.WIRE_FIELDS)
        if not any(present):
            return False
        if not all(present):
            raise ValueError('burst wire snapshot is incomplete')
        try:
            active = raw['burst_active']
            group_seq = int(raw['burst_group_seq'])
            count = int(raw['burst_count'])
            next_index = int(raw['burst_next_index'])
            interval = float(raw['burst_interval'])
            time_left = float(raw['burst_time_left'])
            shell_index = int(raw['burst_shell_index'])
            fire_seq = int(fire_seq)
        except (TypeError, ValueError, OverflowError):
            raise ValueError('burst wire snapshot is malformed')
        exact_integers = (
            (raw['burst_group_seq'], group_seq),
            (raw['burst_count'], count),
            (raw['burst_next_index'], next_index),
            (raw['burst_shell_index'], shell_index),
        )
        if (not isinstance(active, bool) or
                any(isinstance(raw_value, bool) or
                    float(raw_value) != parsed
                    for raw_value, parsed in exact_integers) or
                group_seq < 0 or count < 0 or count > MAX_BURST_COUNT or
                next_index < 0 or next_index > count or shell_index < 0 or
                math.isnan(interval) or math.isinf(interval) or
                math.isnan(time_left) or math.isinf(time_left) or
                interval < 0.0 or interval > MAX_BURST_INTERVAL_SECONDS or
                time_left < 0.0 or
                (count > 1 and interval <= 0.0) or
                (active and (count < 2 or next_index < 1 or
                             next_index >= count or
                             time_left > interval + _EPSILON)) or
                (not active and time_left != 0.0) or
                (count == 0 and (group_seq != 0 or next_index != 0)) or
                (count > 0 and fire_seq != group_seq + next_index - 1)):
            raise ValueError('burst wire snapshot is invalid')
        self.active = active
        self.group_seq = group_seq
        self.count = count
        self.next_index = next_index
        self.interval = interval
        self.time_left = time_left
        self.shell_index = shell_index
        self.terminal_reason = None
        return True
