"""Player-owned projection of the published route and parking map data.

The room keeps the historical ``bot_tactics`` wire field for editor geometry.
Consuming that immutable publication is not a request to a Bot director: this
module has no Bot policy imports, actor allocations, reservations or Bot cache.
Each projection returns private rows. Only encoded packaged map text is cached
between players, so a Bot restart or either player's edits cannot change the
other player's route choices.
"""
import copy
import json


VEHICLE_CLASSES = ('lightTank', 'mediumTank', 'heavyTank', 'AT-SPG', 'SPG')
CLASS_CODES = dict(zip(VEHICLE_CLASSES, ('lt', 'mt', 'ht', 'td', 'spg')))
PARKING_ARRIVAL_RADIUS = 6.0
_PACKAGED_MAP_TEXT = None


def _packaged_maps():
    global _PACKAGED_MAP_TEXT
    if _PACKAGED_MAP_TEXT is None:
        # This is immutable authored data, not the Bot profile loader. Do not
        # normalize/validate all maps during a battle-start callback: only the
        # selected map needs a player projection of the admitted publication.
        from ..bot_tactics_default_data import PROFILE_JSON
        maps = json.loads(PROFILE_JSON).get('maps', {})
        _PACKAGED_MAP_TEXT = dict((name, json.dumps(settings))
                                  for name, settings in maps.items())
    return _PACKAGED_MAP_TEXT


def packaged_map(name):
    """Decode a private map, including the legacy class-reserve convention."""
    text = _packaged_maps().get(name)
    if text is None:
        return {}
    result = json.loads(text)
    rows = result.get('default_routes', ())
    shared = dict(((row['team'], row['id']), row) for row in rows
                  if row.get('class_tag', 'all') == 'all')
    for row in rows:
        if row.get('class_tag', 'all') == 'all' or not row.get('disabled'):
            continue
        base = shared.get((row['team'], row['id']))
        if base is not None and base.get('disabled'):
            continue
        # Older packaged class exclusions mean reserve travel, not deletion.
        # Whole-route exclusions and user edits keep their explicit meaning.
        if base is not None:
            row['points'] = [point[:2] + [0] for point in base['points']]
            row.pop('node_ids', None)
            row.pop('defense', None)
        row.pop('disabled')
        row['tier'] = 'reserve'
    return result


def map_settings(profile, name):
    """Resolve this player's selected map without Bot policy/slot evaluation."""
    baseline = packaged_map(name)
    profile = profile or {}
    if profile.get('name', '').lower() == 'default':
        return baseline
    settings = copy.deepcopy((profile.get('maps') or {}).get(name) or {})
    if not settings:
        return baseline
    if not baseline:
        return settings
    def identity(row):
        return (row['team'], row['id'], row.get('class_tag', 'all'))
    edits = dict((identity(row), row) for row in settings.get('default_routes', ()))
    replaced = set(key[:2] for key in edits if key[2] == 'all')
    # A shared user edit replaces the entire packaged route family. A
    # class-only edit replaces that variant, preserving the other defaults.
    for row in baseline.get('default_routes', ()):
        key = identity(row)
        if key[:2] not in replaced and key not in edits:
            edits[key] = row
    settings['default_routes'] = [edits[key] for key in sorted(edits)]
    return settings


def class_route_id(row):
    tag = row.get('class_tag', 'all')
    if tag == 'all':
        return row['id']
    return 'class_' + CLASS_CODES[tag] + '_' + row['id']


def apply_geometry(route, authored):
    """Replace a road and its topology together, never retain a stale branch."""
    route['waypoints'] = copy.deepcopy(authored['points'])
    for name in ('node_ids', 'defense', 'tier', 'family', 'priority', 'label'):
        route.pop(name, None)
        if name in authored:
            route[name] = copy.deepcopy(authored[name])


def borrowed_roads(roads):
    """Project effective ordinary roads into this player's SPG sortie choices.

    A defense connection is authored from its junction towards home. Borrowing
    the road goes from home along the reversed connection, then continues past
    that exact junction. Parking waits belong to the ordinary vehicle, not the
    borrowing artillery. No Bot allocations or claims are consulted.
    """
    result, by_geometry = [], {}
    for source in roads:
        points = source.get('waypoints') or ()
        if len(points) < 2 or source.get('disabled') or source.get('player_spg_attack'):
            continue
        travel = [list(point[:2]) + [0] for point in points]
        branch = source.get('defense')
        if branch:
            nodes = source.get('node_ids') or ['node_%d' % index for index in range(len(points))]
            junction = branch.get('junction')
            connection = branch.get('points') or ()
            # A broken reference is not permission to choose another junction.
            if (len(nodes) != len(points) or junction not in nodes or
                    len(connection) < 2):
                continue
            index = nodes.index(junction)
            if (index == 0 or index == len(points)-1 or
                    list(connection[0][:2]) != list(points[index][:2])):
                continue
            travel = [list(point[:2]) + [0] for point in reversed(connection)] + travel[index+1:]
        geometry = tuple(tuple(point[:2]) for point in travel)
        family = source.get('family') or source.get('_editor_source') or source['id']
        previous = by_geometry.get(geometry)
        if previous is not None:
            for identity in (source['id'], family):
                if identity not in previous['player_road_ids']:
                    previous['player_road_ids'].append(identity)
            continue
        route = dict(id='player_spg_borrowed_' + str(source['id']), waypoints=travel,
                     player_borrowed=True, player_route_source=source['id'],
                     player_road_ids=sorted(set((source['id'], family))),
                     player_sortie_priority=1, tier=source.get('tier', 'main'),
                     family=family)
        by_geometry[geometry] = route
        result.append(route)
    return result


def accepts_route(row, team, tag):
    """A human has a team/vehicle class, never a fabricated Bot slot zero.

    ``slots`` belongs to the Bot formation allocator and is deliberately not
    consulted. SPG sortie publications predate the optional class list and
    retain their explicit artillery-only meaning.
    """
    if row.get('disabled') or row.get('team') != team:
        return False
    if row.get('purpose') == 'spg_attack':
        return tag == 'SPG'
    return tag in row.get('classes', ())


def waiting_positions(waypoint):
    """Read the editor's optional parking places, without claiming a slot."""
    return waypoint[4] if len(waypoint) > 4 else []
