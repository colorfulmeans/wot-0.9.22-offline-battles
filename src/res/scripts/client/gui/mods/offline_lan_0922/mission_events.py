"""Bounded server-admitted mission evidence, shared by receipt readers.

Rows are [kind, combat_elapsed_ms, value, ...]. Damage carries HP and the
pre-hit immobilized state; kills carry reason, pre-hit immobilization and
distance; critical events carry the newly changed native critical mask.
The cap is per actor, across targets, keeping receipts below the wire budget.
An incomplete history stays explicitly unknown to the mission evaluator.
"""
import math

try:
    INTEGER_TYPES = (int, long)
except NameError:
    INTEGER_TYPES = (int,)

MAX_EVENTS = 1024
FIELDS = frozenset(('mission_events', 'mission_events_complete'))


def _integer(value, minimum, maximum):
    return (type(value) in INTEGER_TYPES and minimum <= value <= maximum)


def valid(row):
    if not FIELDS.intersection(row):
        return True
    events = row.get('mission_events')
    if (not FIELDS.issubset(row) or
            not isinstance(row.get('mission_events_complete'), bool) or
            not isinstance(events, list) or len(events) > MAX_EVENTS):
        return False
    previous_time = -1
    for event in events:
        if (not isinstance(event, list) or len(event) < 3 or
                not _integer(event[1], 0, 86400000) or event[1] < previous_time):
            return False
        previous_time = event[1]
        kind = event[0]
        if kind == 'damage':
            if (len(event) != 4 or not _integer(event[2], 1, 65535) or
                    not isinstance(event[3], bool)):
                return False
        elif kind == 'kill':
            if (len(event) != 5 or not _integer(event[2], 0, 10) or
                    not isinstance(event[3], bool)):
                return False
            distance = event[4]
            if distance is not None and (
                    isinstance(distance, bool) or
                    not isinstance(distance, INTEGER_TYPES + (float,)) or
                    not 0 <= distance <= 100000 or
                    math.isnan(distance) or math.isinf(distance)):
                return False
        elif kind == 'critical':
            if len(event) != 3 or not _integer(event[2], 1, 4294967295):
                return False
        else:
            return False
    return True
