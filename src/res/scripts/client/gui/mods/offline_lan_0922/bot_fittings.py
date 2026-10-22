"""Immutable native Bot fittings, with per-descriptor crew/directive context."""
import base64
import copy
from gui.mods.offline_lan_0922.bot_fitting_data import PLANS, CLASSES
from gui.mods.offline_lan_0922 import default_crew, siege_mechanics

_CONTEXTS = {}
TIERS = ('rookie', 'regular', 'veteran', 'elite')
try:
    TEXT_TYPES = (basestring,)
except NameError:
    TEXT_TYPES = (str,)


def crew_level(tier):
    return dict(rookie=50, regular=75, veteran=100, elite=100)[tier]


def plan(vehicle, tier):
    if tier not in TIERS or vehicle not in PLANS:
        raise ValueError('unsupported Bot fitting: %s/%s' % (vehicle, tier))
    return copy.deepcopy(PLANS[vehicle][tier])


def context(descriptor):
    entry = _CONTEXTS.get(id(descriptor))
    return entry[1] if entry is not None and entry[0] is descriptor else None


def clear():
    _CONTEXTS.clear()


def native_factors(descriptor, critical=None):
    """Cache native factors by immutable fitting and actual crew/fire state."""
    from gui.mods.offline_lan_0922 import loadout
    value = context(descriptor)
    if value is None:
        raise ValueError('Bot fitting is unavailable')
    critical = critical or {}
    knocked_out = frozenset(critical.get('crew_ko') or ())
    flags = tuple(name not in knocked_out for name in value['crew_roster'])
    fire = bool(critical.get('fire', False))
    key = (id(descriptor), flags, fire)
    cache = value.setdefault('factors', {})
    if key not in cache:
        factors = loadout.attribute_factors(
            descriptor, activity_flags=flags, is_fire=fire,
            crew_level=value['wire']['crew_level'])
        if factors is None:
            raise RuntimeError('native Bot fitting crew factors were rejected')
        cache[key] = factors
    return cache[key]


def battle_factors(descriptor, critical=None):
    from gui.mods.offline_lan_0922 import crew_battle
    return crew_battle.from_native(native_factors(descriptor, critical))


def register(descriptor, value):
    for member in (descriptor,) + siege_mechanics.descriptor_pair(descriptor):
        if member is not None:
            _CONTEXTS[id(member)] = (member, value)


def canonical(value):
    """Validate the immutable fitting envelope before native reconstruction."""
    if not isinstance(value, dict) or value.get('schema') != 1:
        raise ValueError('invalid Bot fitting schema')
    vehicle, tier = value.get('vehicle'), value.get('tier')
    expected = plan(vehicle, tier)
    if value.get('devices') != expected['devices'] or value.get('directive') != expected['directive'] or value.get('style') != expected['style']:
        raise ValueError('Bot fitting equipment policy changed')
    level = value.get('crew_level')
    if isinstance(level, bool) or not isinstance(level, (int, float)) or not 50 <= level <= 100 or int(level) != level:
        raise ValueError('invalid Bot fitting crew level')
    encoded = value.get('descriptor')
    if not isinstance(encoded, TEXT_TYPES) or not 1 <= len(encoded) <= 16384:
        raise ValueError('invalid Bot fitting descriptor')
    try:
        raw = base64.b64decode(encoded)
    except Exception:
        raise ValueError('unreadable Bot fitting descriptor')
    if base64.b64encode(raw).decode('ascii') != encoded:
        raise ValueError('noncanonical Bot fitting descriptor')
    return dict(schema=1, vehicle=vehicle, tier=tier, crew_level=int(level),
                descriptor=encoded, devices=list(expected['devices']),
                directive=expected['directive'], style=expected['style'])


def _named(values, name):
    return next(value for value in values if value.name == name)


def build(vehicles, vehicle, tier, crew_level=None, restored=None):
    """Install exact native modules/devices and retain native install guards."""
    from items import tankmen, customizations
    from gui.mods.offline_lan_0922.vehicle_configuration import _installation_accepted
    selected = plan(vehicle, tier)
    level = selected['crew'] if crew_level is None else crew_level
    if isinstance(level, bool) or not isinstance(level, (int, float)) or int(level) != level:
        raise ValueError('invalid Bot crew level')
    level = int(level)
    if not 50 <= level <= 100:
        raise ValueError('unsupported Bot crew level')
    descriptor = vehicles.VehicleDescr(typeName=vehicle)
    parts = selected['modules']
    for attribute, kind in (('chassis', 'chassis'), ('engines', 'engine')):
        component = _named(getattr(descriptor.type, attribute), parts[kind])
        if not _installation_accepted(descriptor.mayInstallComponent(component.compactDescr, 0)):
            raise ValueError('native Bot module installation refused: %s' % kind)
        descriptor.installComponent(component.compactDescr, 0)
    turret = _named(descriptor.type.turrets[0], parts['turret'])
    gun = _named(turret.guns, parts['gun'])
    if not _installation_accepted(descriptor.mayInstallTurret(turret.compactDescr, gun.compactDescr, 0)):
        raise ValueError('native Bot turret/gun installation refused')
    descriptor.installTurret(turret.compactDescr, gun.compactDescr, 0)
    for attribute, kind in (('radios', 'radio'), ('fuelTanks', 'fuel_tank')):
        component = _named(getattr(descriptor.type, attribute), parts[kind])
        if not _installation_accepted(descriptor.mayInstallComponent(component.compactDescr, 0)):
            raise ValueError('native Bot module installation refused: %s' % kind)
        descriptor.installComponent(component.compactDescr, 0)
    cache = vehicles.g_cache
    devices = cache.optionalDevices()
    ids = cache.optionalDeviceIDs()
    for slot, name in enumerate(selected['devices']):
        device = devices[ids[name]]
        if not _installation_accepted(descriptor.mayInstallOptionalDevice(device.compactDescr, slot)):
            raise ValueError('native Bot device installation refused: %s' % name)
        descriptor.installOptionalDevice(device.compactDescr, slot)
    # Reparse once so all native derived geometry and module properties agree.
    encoded = base64.b64encode(descriptor.makeCompactDescr()).decode('ascii')
    descriptor = vehicles.VehicleDescr(compactDescr=base64.b64decode(encoded))
    actual = dict(chassis=descriptor.chassis.name, engine=descriptor.engine.name,
                  radio=descriptor.radio.name, fuel_tank=descriptor.fuelTank.name,
                  turret=descriptor.turret.name, gun=descriptor.gun.name)
    if actual != parts:
        raise ValueError('native Bot fitting module postcondition failed')
    if [d.name for d in descriptor.optionalDevices if d is not None] != selected['devices']:
        raise ValueError('native Bot fitting device postcondition failed')
    wire = canonical(dict(schema=1, vehicle=vehicle, tier=tier, crew_level=level,
        descriptor=encoded, devices=selected['devices'], directive=selected['directive'], style=selected['style']))
    if restored is not None and canonical(restored) != wire:
        raise ValueError('restored Bot fitting changed')
    skills = (() if tier in ('rookie', 'regular') else ('repair', 'camouflage'))
    mask = default_crew.sandbox_skill_mask() if tier == 'elite' else tankmen.getSkillsMask(skills)
    crew = tuple(tankmen.generateTankmen(descriptor.type.id[0], descriptor.type.id[1],
        descriptor.type.crewRoles, False, level, mask, False))
    if len(crew) != len(descriptor.type.crewRoles):
        raise ValueError('native Bot crew roster changed')
    crew_skills = tuple(tuple(tankmen.TankmanDescr(raw).skills) for raw in crew)
    directives = ()
    if selected['directive']:
        directives = (cache.equipments()[cache.equipmentIDs()[selected['directive']]],)
    outfits, camouflages = {}, {}
    if selected['style'] is not None:
        if 'lockOutfit' in descriptor.type.tags:
            raise ValueError('native Bot outfit is locked')
        style = cache.customization20().styles[selected['style']]
        from items.components.c11n_constants import ApplyArea
        for season, outfit in style.outfits.items():
            outfits[str(season)] = base64.b64encode(customizations.makeCompDescr(outfit)).decode('ascii')
            hull = [item.id for item in outfit.camouflages
                    if item.appliedTo & ApplyArea.HULL]
            if len(hull) != 1:
                raise ValueError('native Bot seasonal hull camouflage is ambiguous')
            camouflages[str(season)] = hull[0]
    value = dict(wire=wire, crew=crew, directives=directives, skills=skills,
                 crew_skills=crew_skills, camouflages=camouflages,
                 outfits=outfits, native_style=selected['style'])
    from gui.mods.offline_lan_0922.bot_runtime import _descriptor_crew_roster
    value['crew_roster'] = _descriptor_crew_roster(descriptor)
    register(descriptor, value)
    return descriptor
