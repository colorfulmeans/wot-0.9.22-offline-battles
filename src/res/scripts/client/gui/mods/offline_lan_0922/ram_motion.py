"""Bounded, canonical incoming velocities for Bot/player contact episodes."""
import math

MAX_PEERS = 30
ROW_LENGTH = 21
SCALES = (10000, 10000, 10000,
          10000, 10000, 10000, 100000, 100000, 100000,
          10000, 10000, 10000, 100000, 100000, 100000,
          10000, 10000, 10000)
try:
    INTEGER_TYPES = (int, long)
except NameError:
    INTEGER_TYPES = (int,)


def normalize(rows):
    if not isinstance(rows, (list, tuple)) or len(rows) > MAX_PEERS:
        raise ValueError('invalid ram motion collection')
    result = []
    peers = set()
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != ROW_LENGTH:
            raise ValueError('invalid ram motion row')
        peer, seq, stamp = row[:3]
        if (any(isinstance(v, bool) or not isinstance(v, INTEGER_TYPES)
                for v in (peer, seq, stamp)) or
                not 1 <= peer <= 2147483647 or
                not 1 <= seq <= 2147483647 or
                not 0 <= stamp <= 9007199254740991 or peer in peers):
            raise ValueError('invalid ram motion identity')
        values = [float(v) for v in row[3:]]
        limits = (200.,)*3 + (2000.,1000.,2000.,2*math.pi,math.pi,math.pi)*2 + (200.,)*3
        if any(math.isnan(v) or math.isinf(v) or abs(v) > limit
               for v, limit in zip(values, limits)):
            raise ValueError('invalid ram motion values')
        peers.add(peer)
        result.append([peer, seq, stamp] + values)
    return result


def at_time(left, right, stamp):
    """Do not borrow future collision evidence from a later render bracket."""
    if not left and not right:
        return []
    found = {}
    for row in left or ():
        if row[2] <= stamp:
            found[row[0]] = list(row)
    for row in right or ():
        old = found.get(row[0])
        if row[2] <= stamp and (old is None or row[1] > old[1]):
            found[row[0]] = list(row)
    return [found[peer] for peer in sorted(found)]


def for_player(rows, player_id):
    return next((row for row in rows or () if row[0] == player_id), None)
