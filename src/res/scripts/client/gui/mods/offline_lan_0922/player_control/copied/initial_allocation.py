"""Round-local priority draws, independent of projectile random state."""
import random


def ordered_pairs(states):
    groups = {}
    for state in sorted(states, key=lambda s: (s.get('slot', 0), s['id'])):
        tag = (state.get('profile') or {}).get('class_tag', '')
        groups.setdefault(tag, {1: [], 2: []})[state['team']].append(state)
    for tag in sorted(groups):
        sides = groups[tag]
        for ordinal in range(max(len(sides[1]), len(sides[2]))):
            yield tag, ordinal, tuple(sides[t][ordinal] if ordinal < len(sides[t]) else None
                                      for t in (1, 2))


def choose(seed, scope, tag, ordinal, candidates, side=0):
    """Candidates are (priority, family, paired, payload); draw families once.

    Multiple geometric candidates must not give a parking zone extra tickets.
    Larger priority wins; callers convert source catalog cost priorities.
    """
    if not candidates:
        return None
    priority = max(c[0] for c in candidates)
    choices = dict((c[1], c) for c in candidates if c[0] == priority)
    keys = sorted(choices)
    generator = random.Random('%s:%s:%s:%s:%s' % (seed, scope, tag, ordinal, side))
    return choices[keys[generator.randrange(len(keys))]]


def allocate(states, candidates, reserve, seed, scope):
    """Pair only explicit symmetric families; standalone intent stays local.

    Re-evaluate capacity before every actor pair. If one side cannot use the
    matched highest-priority family (geometry, footprint or exhausted capacity),
    keep the physical/priority contract and allow independent local choices.
    """
    for tag, ordinal, pair in ordered_pairs(states):
        available = [candidates(s) if s is not None else [] for s in pair]
        tops = [[c for c in rows if c[0] == max(r[0] for r in rows)] if rows else []
                for rows in available]
        shared = set(c[1] for c in tops[0] if c[2]) & set(c[1] for c in tops[1] if c[2])
        coupled = bool(shared and all(c[2] for rows in tops for c in rows))
        selected = choose(seed, scope, tag, ordinal,
                          [c for c in tops[0] if c[1] in shared]) if coupled else None
        local = [choose(seed, scope, tag, ordinal, rows, index+1)
                 for index, rows in enumerate(available)]
        if not coupled:
            requested = set(c[1] for c in local if c is not None and c[2] and c[1] in shared)
            if requested:
                selected = choose(seed, scope, tag, ordinal,
                                  [c for c in tops[0] if c[1] in requested])
                coupled = True
        for index, state in enumerate(pair):
            if state is None:
                continue
            choice = (next(c for c in tops[index] if c[1] == selected[1]) if coupled else
                      local[index])
            reserve(state, choice)
