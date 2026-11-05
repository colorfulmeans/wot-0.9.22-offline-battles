"""Public roster facts used by one visible player's decision state.

An empty Bot roster is a valid match, not an unfinished Bot-create callback.
Unstreamed teammates remain alive/unknown unless public canonical state says
otherwise. Their hidden positions and Bot policy objects are never consulted.
"""


def actor_priority(row):
    """A peer-election key shared by LAN clients, not a local engine handle.

    BigWorld allocates native entity IDs independently on each machine. Keep
    those IDs for collision lookup, but use the public actor namespace/ID for
    tie breaks. The fallback only supports old local fixtures/unknown actors;
    it is not evidence of cross-client agreement.
    """
    key = row.get('actor_key')
    if not isinstance(key, (tuple, list)) or len(key) != 2:
        key = (row.get('kind'), row.get('network_id'))
    try:
        if key[0] in ('player', 'bot') and not isinstance(key[1], bool) and int(key[1]) > 0:
            return (0, key[0], int(key[1]))
    except (TypeError, ValueError, OverflowError):
        pass
    identity = row.get('engine_id', row.get('id'))
    try:
        return (1, 'engine', int(identity))
    except (TypeError, ValueError, OverflowError):
        return (2, 'engine', str(identity))


def public_allies(owner, observed):
    result = [dict(row) for row in observed]
    seen = set(row.get('id') for row in result)
    records = getattr(owner, '_records', {}) or {}
    start = getattr(owner, '_start_message', {}) or {}
    team = int(owner.client.team)
    roster_valid = all(isinstance(start.get(name), (list, tuple)) for name in ('players', 'bots'))
    # Read only public health/alive fields from a same-round snapshot. Native
    # entity observations still own class and physical occupancy information.
    snapshot = getattr(owner, '_last_snapshot', None) or {}
    if snapshot.get('round_id', start.get('round_id')) != start.get('round_id'):
        snapshot = {}
    canonical = {}
    for kind, name in (('player', 'players'), ('bot', 'bots')):
        for row in snapshot.get(name, ()) or ():
            if isinstance(row, dict) and row.get('id') is not None:
                canonical[(kind, row['id'])] = row
        for row in start.get(name, ()) or ():
            if not isinstance(row, dict) or row.get('id') is None:
                roster_valid = False
                continue
            network = row['id']
            if kind == 'player' and network == owner.client.player_id:
                continue
            record = records.get('%s:%s' % (kind, network)) or {}
            current = dict(row)
            current.update(record.get('state') or {})
            current.update(canonical.get((kind, network), {}))
            if int(current.get('team', 0) or 0) != team:
                continue
            identity = record.get('engine_id') or '%s:%s' % (kind, network)
            if identity in seen:
                continue
            result.append(dict(id=identity, actor_key=(kind, network),
                alive=bool(current.get('alive', True) and
                current.get('health', 1) > 0), class_tag=None, source='public_roster'))
            seen.add(identity)
    # Records may precede the start roster's presentation update. Keep them
    # conservatively, without pretending a missing start message is complete.
    for record in records.values():
        public = record.get('state') or {}
        identity = record.get('engine_id')
        if (identity in seen or int(public.get('team', 0) or 0) != team or
                record.get('local')):
            continue
        result.append(dict(id=identity, actor_key=(record.get('kind'), record.get('network_id')),
            alive=bool(public.get('alive', True) and
            public.get('health', 1) > 0), class_tag=None, source='public_record'))
        seen.add(identity)
    # Presentation/creation may lag a valid publication. Unknown teammates
    # above remain alive with an unknown class, so Bot creation queues are
    # neither needed as a safety gate nor a dependency of local decisions.
    return result, bool(roster_valid)
