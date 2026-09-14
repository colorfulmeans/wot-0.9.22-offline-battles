"""Match native slots to authored placements without assuming WGDE offsets."""
import itertools


def placement_index(baked, trees):
    bins = {}
    for records in (baked, trees):
        for wire, record in records.items():
            signature = record['signature']
            key = (wire[0],) + tuple(value // 4 for value in signature[:3])
            bins.setdefault(key, []).append((wire, record))
    return bins


def match_placement(index, chunk_id, signature, kind):
    """Require a unique 12-component transform and the live native category.

    The one-unit tolerance is the existing float32/millimetre rounding
    allowance; it is not a nearest-object lookup or a guessed slot shift.
    """
    cells = [set(((value - 1) // 4, (value + 1) // 4))
             for value in signature[:3]]
    matches = []
    for cell in itertools.product(*cells):
        for wire, record in index.get((chunk_id,) + cell, ()):
            if kind is not None and record['kind'] != kind:
                continue
            if all(abs(a - b) <= 1 for a, b in
                   zip(signature, record['signature'])):
                matches.append((wire, record))
    return matches[0] if len(matches) == 1 else None
