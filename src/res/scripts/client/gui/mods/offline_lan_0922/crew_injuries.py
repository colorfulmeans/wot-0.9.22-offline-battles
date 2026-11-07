"""Terminal physical crew injuries, preserved through durable settlement.

WG support article 15085: members still injured at battle end earn 10% less
crew XP. Healing before that boundary removes the penalty. Vehicle destruction
alone does not invent injuries. Legacy receipts without the facts stay neutral.
"""

NAMES = frozenset(('commander', 'driver', 'gunner1', 'gunner2',
                   'loader1', 'loader2', 'radioman1', 'radioman2'))
try:
    TEXT_TYPES = (basestring,)
except NameError:
    TEXT_TYPES = (str,)


def canonical(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != set(('roster', 'wounded')):
        raise ValueError('battle crew injuries are invalid')
    roster, wounded = value['roster'], value['wounded']
    for row in (roster, wounded):
        if (not isinstance(row, (list, tuple)) or len(row) > len(NAMES) or
                any(not isinstance(name, TEXT_TYPES) or name not in NAMES for name in row) or
                len(set(row)) != len(row)):
            raise ValueError('battle crew injury roster is invalid')
    if not roster or not set(wounded).issubset(roster):
        raise ValueError('battle crew injuries are outside their roster')
    return dict(roster=sorted(roster), wounded=sorted(wounded))


def from_critical(critical):
    critical = critical or {}
    roster = critical.get('crew_roster')
    if not roster:
        return None
    return canonical(dict(roster=list(roster),
                          wounded=list(critical.get('crew_ko') or ())))


def physical_roster(roles):
    counts, roster = {}, []
    for row in roles:
        role = str(row[0])
        counts[role] = counts.get(role, 0) + 1
        roster.append(role + str(counts[role]) if role in (
            'gunner', 'loader', 'radioman') else role)
    return tuple(roster)


def injured_seats(roles, facts):
    facts = canonical(facts)
    if facts is None:
        return ()
    roster = physical_roster(roles)
    if set(roster) != set(facts['roster']):
        raise ValueError('battle injury roster does not match the vehicle')
    return tuple(index for index, name in enumerate(roster)
                 if name in facts['wounded'])
