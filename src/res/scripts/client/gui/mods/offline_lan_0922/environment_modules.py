"""Position-based impact and internal-only fire module damage.

The rates and shock reach below are offline trial parameters, not recovered
#1513 server constants. Geometry nominates contacts; this module never creates
a compartment hit from a vehicle class or a random module selection.
"""
from __future__ import print_function
import math
import json

FIRE_DEVICES = frozenset(('engineHealth', 'fuelTankHealth', 'ammoBayHealth',
                          'radioHealth', 'turretRotatorHealth'))
FIRE_MODULE_HP_PER_SECOND = 10.0
IMPACT_MODULE_HP_PER_EXCESS_MS = 30.0
IMPACT_CREW_INJURY_HP = 100.0
IMPACT_REACH_PER_EXCESS_MS = 0.6
IMPACT_DISTANCE_DECAY = 0.25
IMPACT_FAN_TANGENT = math.tan(math.radians(25.0))
MAX_CONTACTS = 32


def normalize_contacts(rows):
    from gui.mods.offline_lan_0922 import device_damage
    if not isinstance(rows, (list, tuple)) or len(rows) > MAX_CONTACTS:
        raise ValueError('invalid environmental module contacts')
    known = set(device_damage._DEVICE_HP_SPEC) | set(device_damage.CREW_HEALTH_NAMES)
    result = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(('name', 'weight')):
            raise ValueError('invalid environmental module contact')
        name, weight = row['name'], row['weight']
        if (name not in known or isinstance(weight, bool) or
                not isinstance(weight, (int, float)) or math.isnan(weight) or
                math.isinf(weight) or not 0.0 < weight <= 1.0):
            raise ValueError('invalid environmental module contact value')
        result[name] = max(result.get(name, 0.0), float(weight))
    return [dict(name=name, weight=result[name]) for name in sorted(result)]


def apply_losses(vehicle, losses, cause, allow_terminal=True):
    from gui.mods.offline_lan_0922 import critical_damage as cd
    from gui.mods.offline_lan_0922 import device_damage as dd
    before = cd._state(vehicle)
    vehicle._crew_ko = set(getattr(vehicle, '_crew_ko', None) or ())
    applied = []
    if float(getattr(vehicle, 'health', 0.) or 0.) <= 0.:
        return 0, None
    for name, loss in losses:
        if name in dd.CREW_HEALTH_NAMES:
            role = name[:-6]
            roles = getattr(getattr(cd._device_td(vehicle), 'type', None), 'crewRoles', ())
            if roles and role in cd._crew_roster(cd._device_td(vehicle)) and loss >= IMPACT_CREW_INJURY_HP:
                vehicle._crew_ko.add(role)
                applied.append(dict(name=name, loss=loss, injured=True))
            continue
        maximum = dd.device_max_hp(cd._device_td(vehicle), name)
        if maximum is None:
            continue
        old = float(vehicle.devices_hp.get(name, maximum))
        cd.damage_device_over_time(vehicle, name, loss, cause=cause)
        new = float(vehicle.devices_hp.get(name, old))
        if new < old:
            applied.append(dict(name=name, before=old, after=new, loss=old-new))
            # Fuel destruction has the same consequence for a physical impact
            # as a projectile. Publish ignition in this operation's payload.
            if (name == 'fuelTankHealth' and new <= 0.0 and
                    not getattr(vehicle, 'is_on_fire', False)):
                cd._offh_ignite(vehicle, False, name + ' destroyed by ' + cause)
            if allow_terminal and name == 'ammoBayHealth' and new <= 0.0:
                vehicle._ammo_rack_death = True
                vehicle._is_killed = True
                break
    cd._refresh_mobility_flags(vehicle)
    roster = (cd._crew_roster(cd._device_td(vehicle)) if
        getattr(getattr(cd._device_td(vehicle), 'type', None), 'crewRoles', ()) else ())
    terminal = bool(allow_terminal and (getattr(vehicle, '_ammo_rack_death', False) or
                    roster and all(role in vehicle._crew_ko for role in roster)))
    payload = cd._payload(before, cd._state(vehicle), cd._device_td(vehicle), cause)
    if applied:
        print('[Offline LAN 0.9.22] ENV MODULE DAMAGE ' + json.dumps(dict(
            actor=getattr(vehicle, 'id', None), actor_kind=getattr(vehicle, 'actor_kind', 'unknown'), cause=cause, trial_rates=True, applied=applied,
            terminal=terminal, fire_before=before['fire'], fire_after=bool(getattr(vehicle,'is_on_fire',False)),
            ignited=bool(not before['fire'] and getattr(vehicle,'is_on_fire',False))), sort_keys=True))
    return int(vehicle.health) if terminal else 0, payload


def apply_impact(vehicle, impact_speed, contacts):
    from gui.mods.offline_lan_0922 import vehicle_physics
    excess = max(0.0, abs(float(impact_speed)) - vehicle_physics.FALL_SAFE_SPEED)
    contacts = normalize_contacts(contacts)
    return apply_losses(vehicle, [(row['name'], excess *
        IMPACT_MODULE_HP_PER_EXCESS_MS * row['weight']) for row in contacts],
        'world_collision')


def ground_witnesses(params, ground, pseudo_ground, position, yaw, pitch, roll):
    """Deepest sampled suspension/body witnesses, never a guessed hull centre."""
    from gui.mods.offline_lan_0922 import vehicle_physics as vp
    rows = []
    for points, heights in ((params.get('springs', ()), ground),
                            (params.get('pseudo_contacts', ()), pseudo_ground)):
        for point, height in zip(points, heights or ()):
            if height is None:
                continue
            x, y, z = vp.suspension_point_offset(point, pitch, roll)
            world = (position[0] + math.cos(yaw)*x + math.sin(yaw)*z,
                     float(height), position[2] - math.sin(yaw)*x + math.cos(yaw)*z)
            rows.append((position[1]+y-float(height), world))
    if not rows:
        return []
    deepest = min(row[0] for row in rows)
    remaining = sorted(set(row[1] for row in rows if row[0] <= deepest + 0.05))
    selected = []
    while remaining and len(selected) < 8:
        point = (remaining[0] if not selected else max(remaining, key=lambda p:
            min((p[0]-q[0])**2+(p[2]-q[2])**2 for q in selected)))
        selected.append(point)
        remaining.remove(point)
    return selected


def _shock_directions(normal):
    # Stable orthogonal tangent basis, including wall and roof landings.
    axis = (0., 1., 0.) if abs(normal[1]) < 0.9 else (1., 0., 0.)
    tangent = (normal[1]*axis[2]-normal[2]*axis[1],
               normal[2]*axis[0]-normal[0]*axis[2],
               normal[0]*axis[1]-normal[1]*axis[0])
    length = math.sqrt(sum(v*v for v in tangent))
    tangent = tuple(v/length for v in tangent)
    other = (normal[1]*tangent[2]-normal[2]*tangent[1],
             normal[2]*tangent[0]-normal[0]*tangent[2],
             normal[0]*tangent[1]-normal[1]*tangent[0])
    directions = [normal]
    for lateral in (tangent, other):
        for sign in (-1., 1.):
            direction = tuple(normal[i]+sign*IMPACT_FAN_TANGENT*lateral[i] for i in range(3))
            length = math.sqrt(sum(v*v for v in direction))
            directions.append(tuple(v/length for v in direction))
    return directions


def collect_contacts(vehicle, witnesses, normal, impact_speed, math_module):
    """Use native external materials and adopted internal/crew geometry.

    Shock is a bounded inward five-segment fan from each witness. Its reach is
    reconstructed and recorded, unlike the existing projectile saving throw.
    """
    from gui.mods.offline_lan_0922 import critical_damage as cd
    from gui.mods.offline_lan_0922.entities.remote_vehicle import collide_vehicle_at_matrix
    contacts = []
    if normal is None:
        print('[Offline LAN 0.9.22] ENV MODULE CONTACT unavailable normal')
        return []
    length = math.sqrt(sum(float(v)**2 for v in normal))
    if math.isnan(length) or math.isinf(length) or length <= 0.0001:
        return contacts
    normal = tuple(float(v)/length for v in normal)
    depth = min(6.0, max(0.25, (abs(float(impact_speed))-10.0)*IMPACT_REACH_PER_EXCESS_MS))
    errors = []
    evidence = []
    directions = _shock_directions(normal)
    for point in witnesses[:8]:
        start = math_module.Vector3(*(point[i]-normal[i]*0.03 for i in range(3)))
        for ray_index, direction in enumerate(directions):
            end = math_module.Vector3(*(point[i]+direction[i]*depth for i in range(3)))
            # A failed external probe cannot suppress a valid interior query.
            queries = (
                ('native.material', lambda: [(hit[0], str(getattr(
                    getattr(hit[2], 'extra', None), 'name', '') or ''))
                    for hit in collide_vehicle_at_matrix(vehicle, vehicle.matrix,
                        start, end, math_module,
                        chassis_matrix=getattr(vehicle, '_chassis_matrix', None))]),
                ('adopted.internal_layout', lambda: cd._offh_internal_ray_hits(
                    vehicle, cd._device_td(vehicle), start, end)))
            for source, query in queries:
                try:
                    hits = query()
                    if hits is None:
                        errors.append(dict(source=source, ray=ray_index, error='geometry_unavailable'))
                    for distance, name in hits or ():
                        distance = float(distance)
                        if (not name or math.isnan(distance) or math.isinf(distance) or
                                distance < 0.0 or distance > depth+0.031):
                            continue
                        weight = 1.0/(1.0+IMPACT_DISTANCE_DECAY*distance)
                        contacts.append(dict(name=name, weight=weight))
                        evidence.append(dict(name=name, distance=distance, source=source,
                            witness=point, ray=ray_index, direction=direction))
                except Exception as error:
                    errors.append(dict(source=source, ray=ray_index, error=str(error)))
    from gui.mods.offline_lan_0922 import device_damage
    known = set(device_damage._DEVICE_HP_SPEC) | set(device_damage.CREW_HEALTH_NAMES)
    merged = {}
    for row in contacts:
        if row['name'] in known:
            merged[row['name']] = max(merged.get(row['name'], 0.), row['weight'])
    contacts = normalize_contacts([dict(name=name, weight=merged[name]) for name in sorted(merged)])
    from gui.mods.offline_lan_0922.native_input_diagnostics import write_json_record
    write_json_record('ENV MODULE CONTACT', dict(
        actor=vehicle.id, actor_kind=getattr(vehicle, 'actor_kind', 'unknown'), witnesses=list(witnesses), normal=normal, depth=depth,
        speed=impact_speed, contacts=contacts, evidence=evidence, errors=errors,
        fan_half_angle_degrees=25., distance_decay=IMPACT_DISTANCE_DECAY, trial_reach=True))
    return contacts
