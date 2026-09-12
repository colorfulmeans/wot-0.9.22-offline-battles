"""Round-local cumulative physical impulses, independent of armour/HP receipts.

Each visible human reports the opposite momentum of its contact impulse.
The worker divides the unseen momentum by its canonical Bot mass.
Cumulative checkpoints survive input/snapshot coalescing; retries are no-ops.
The acknowledgement travels with the Bot velocity it produced, so prediction
subtracts exactly the already-integrated share, never a positional correction.
"""
import math

MAX_ACTORS = 30
MAX_SEQUENCE = 2147483647
MAX_TOTAL = 1000000000000.0


def normalize(rows):
    if not isinstance(rows, (list, tuple)) or len(rows) > MAX_ACTORS:
        raise ValueError('invalid contact checkpoint list')
    result = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            raise ValueError('invalid contact checkpoint')
        actor, seq, x, z = row
        if (isinstance(actor, bool) or isinstance(seq, bool) or
                int(actor) != actor or int(seq) != seq or
                not 1 <= actor <= MAX_SEQUENCE or
                not 1 <= seq <= MAX_SEQUENCE or actor in result):
            raise ValueError('invalid contact identity')
        values = []
        for value in (x, z):
            if isinstance(value, bool):
                raise ValueError('invalid contact total')
            number = float(value)
            if math.isnan(number) or math.isinf(number) or abs(number) > MAX_TOTAL:
                raise ValueError('invalid contact total')
            values.append(number)
        result[int(actor)] = [int(actor), int(seq)] + values
    return result


def record(ledger, actor, delta):
    if not any(delta):
        return
    old = ledger.get(actor, [actor, 0, 0.0, 0.0])
    ledger[actor] = [actor, old[1] + 1,
                     old[2] + delta[0], old[3] + delta[1]]


def unseen(row, previous):
    if previous is None:
        return row[2], row[3]
    if row[1] <= previous[1]:
        return 0.0, 0.0
    return row[2] - previous[2], row[3] - previous[3]


def pending(ledger, actor, acknowledgements, player_id):
    row = ledger.get(actor)
    if row is None:
        return 0.0, 0.0
    acknowledged = next((r for r in acknowledgements or ()
                         if r[0] == player_id), None)
    return unseen(row, acknowledged)
