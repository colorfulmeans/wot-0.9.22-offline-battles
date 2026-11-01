"""Explicit sparse lineup slots; shared by launcher, server and client."""
NATIONS = ('china', 'ussr', 'usa', 'germany', 'czech', 'france', 'uk',
           'japan', 'poland', 'sweden')
CLASSES = ('lightTank', 'mediumTank', 'heavyTank', 'AT-SPG', 'SPG')


def explicit(rows):
    return any('enabled' in row for row in (rows or ()))


def active_slots(rows, team, capacity=15):
    if not explicit(rows):
        return list(range(capacity))
    return sorted(row['slot'] for row in rows
                  if row['team'] == team and row.get('enabled', False))


def validate_filters(row):
    if 'enabled' in row and type(row['enabled']) is not bool:
        raise ValueError('Invalid lineup slot state')
    if row.get('nation') not in (None,) + NATIONS:
        raise ValueError('Invalid lineup nation')
    if row.get('vehicle_class') not in (None,) + CLASSES:
        raise ValueError('Invalid lineup vehicle class')


def matches(row, candidate):
    name = candidate.get('name') or candidate.get('type_name') or ''
    nation = candidate.get('nation') or name.split(':')[0]
    tags = candidate.get('tags') or ()
    tag = candidate.get('vehicleClass') or candidate.get('class_tag')
    return ((not row.get('nation') or row['nation'] == nation) and
            (not row.get('vehicle_class') or row['vehicle_class'] == tag or
             row['vehicle_class'] in tags))
