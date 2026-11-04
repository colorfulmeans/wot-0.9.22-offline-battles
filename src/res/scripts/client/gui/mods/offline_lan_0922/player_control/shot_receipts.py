"""Player-owned command/projectile observations, independent of ammo policy.

Only a controller-issued committed shot creates an entry. Native flight and
canonical combat consumers remain authoritative; this ledger only publishes
their observations. A terminal contact may precede its combat effects.
"""
from __future__ import division

import math

try:
    STRING_TYPES = (basestring,)
except NameError:
    STRING_TYPES = (str,)


def text_identity(value):
    # JSON strings are unicode in the embedded Python 2.7 interpreter. A
    # read-only lookup of a non-ASCII ID must be an unknown observation, never
    # an implicit ASCII encoding exception that stops unrelated control.
    return value if isinstance(value, STRING_TYPES) else str(value)


class ShotReceipts(object):
    HISTORY = 256
    RECENT_SECONDS = 5.

    def __init__(self):
        self.rows = {}
        self.order = []
        self.sequence = 0

    def get(self, projectile_id):
        return self.rows.get(text_identity(projectile_id)) if projectile_id is not None else None

    def _event(self, row, status, now, **fields):
        self.sequence += 1
        result = dict(type='shot', projectile_id=row['projectile_id'],
            command_id=row['command_id'], target_id=row['target_id'],
            status=status, flight_status=row['flight_status'], time=float(now),
            event_seq=self.sequence, shell_index=row['shell_index'],
            burst_group=row['burst_group'], burst_count=row['burst_count'],
            damage_total=row['damage_total'], hit_count=row['hit_count'],
            penetrated=row['penetrated'], terminal_observed=row['terminal_at'] is not None,
            combat_observed=row['hit_count'] > 0)
        if row['terminal_at'] is not None:
            result['hit_vehicle'] = row['hit_vehicle']
        if row.get('reason') is not None:
            result['reason'] = row['reason']
        result.update(fields)
        row['latest'] = result
        row['observed_at'] = float(now)
        self._prune(now)
        return dict(result)

    def committed(self, event, pending, context, now, generation):
        identity = event.get('projectile_id')
        if identity is None or self.get(identity) is not None:
            return None
        identity = text_identity(identity)
        row = dict(projectile_id=identity, command_id=context.get('command'),
            target_id=context.get('target'), generation=context.get('generation', generation),
            trigger_sequence=context.get('trigger_sequence', 0),
            shell_index=event.get('shell_index'), burst_group=pending.get('burst_group_seq'),
            burst_count=pending.get('burst_count', 1), flight_status='committed',
            damage_total=0., hit_count=0, penetrated=False, terminal_at=None,
            hit_vehicle=None, finished_at=None, combat_ids=set(), latest=None)
        self.rows[identity] = row
        self.order.append(identity)
        return self._event(row, 'committed', now, stage='local_committed')

    def hit(self, event, now):
        row = self.get(event.get('projectile_id'))
        if row is None or row['flight_status'] == 'rejected' or event.get('cosmetic_only'):
            return None
        event_id = event.get('event_id')
        if event_id is not None:
            event_id = text_identity(event_id)
            if event_id in row['combat_ids']:
                return None
        try:
            damage = float(event.get('damage', 0.))
        except (TypeError, ValueError, OverflowError):
            return None
        if math.isnan(damage) or math.isinf(damage):
            return None
        damage = max(0., damage)
        if event_id is not None:
            row['combat_ids'].add(event_id)
        row['hit_count'] += 1
        row['damage_total'] += damage
        row['penetrated'] |= event.get('shot_result') == 2
        fields = dict(damage=damage, combat_event_id=event_id)
        for key in ('target', 'target_bot', 'shot_result', 'killed'):
            if key in event:
                fields[key] = event[key]
        return self._event(row, 'hit', now, **fields)

    def terminal(self, event, now):
        row = self.get(event.get('projectile_id'))
        if row is None or row['flight_status'] in ('terminal', 'rejected'):
            return None
        row['flight_status'] = 'terminal'
        row['terminal_at'] = row['finished_at'] = float(now)
        row['hit_vehicle'] = event.get('hit_vehicle')
        return self._event(row, 'terminal', now)

    def rejected(self, projectile_id, reason, now):
        row = self.get(projectile_id)
        if row is None or row['flight_status'] == 'rejected':
            return None
        row['flight_status'] = 'rejected'
        row['reason'] = text_identity(reason)
        row['finished_at'] = float(now)
        return self._event(row, 'rejected', now)

    def _prune(self, now):
        # Never discard an admitted live flight. Keep a grace window for combat
        # effects ordered after terminal contact, plus a bounded old history.
        finished = sorted((identity for identity in self.order
                           if self.rows[identity]['finished_at'] is not None),
                          key=lambda identity:self.rows[identity]['latest']['event_seq'])
        excess = len(finished) - self.HISTORY
        for identity in finished:
            if excess <= 0:
                break
            if now - self.rows[identity]['observed_at'] < self.RECENT_SECONDS:
                continue
            self.rows.pop(identity)
            self.order.remove(identity)
            excess -= 1

    def snapshot(self, limit=32):
        # A slow earlier flight can receive an effect after many later launches.
        # Repair snapshots follow observation order, not launch order.
        latest = sorted((row['latest'] for row in self.rows.values()
                         if row['latest'] is not None), key=lambda row:row['event_seq'])
        return [dict(row) for row in latest[-limit:]]
