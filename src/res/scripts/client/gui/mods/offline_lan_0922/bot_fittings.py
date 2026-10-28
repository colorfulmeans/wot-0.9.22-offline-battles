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


def plan(vehicle, tier, overrides=None):
    if tier not in TIERS or vehicle not in PLANS:
        raise ValueError('unsupported Bot fitting: %s/%s' % (vehicle, tier))
    result = copy.deepcopy(PLANS[vehicle][tier])
    overrides = overrides or {}
    from gui.mods.offline_lan_0922.bot_tactics import normalize_values
    overrides = normalize_values(overrides)
    development = overrides.get('development')
    if development:
        result['modules'] = copy.deepcopy(PLANS[vehicle][dict(
            stock='rookie', intermediate='regular', full='elite')[development]]['modules'])
    equipment = overrides.get('equipment')
    if equipment:
        donor = PLANS[vehicle][dict(none='rookie', single='regular',
            standard='veteran', improved='elite')[equipment]]
        result['devices'] = list(donor['devices'])
        result['directive'] = donor['directive']
    preset = overrides.get('crew_preset')
    if preset:
        result['crew'] = {'50':50, '75':75, 'repair':100, 'all':100}[preset]
    if 'outfit' in overrides:
        # The reviewed elite plan already excludes vehicles with locked outfits.
        result['style'] = PLANS[vehicle]['elite']['style'] if overrides['outfit'] == 'on' else None
    development = development or {'rookie':'stock','regular':'intermediate','veteran':'full','elite':'full'}[tier]
    equipment = equipment or {'rookie':'none','regular':'single','veteran':'standard','elite':'improved'}[tier]
    if development=='stock' and equipment!='none':
        raise ValueError('Stock development only allows no equipment')
    return result


def validate_profile(profile):
    from gui.mods.offline_lan_0922 import bot_tactics
    if not any(any(k in r['values'] for k in ('development','equipment')) for r in profile.get('behavior',())):
        return
    for team in (1,2):
        for tag in bot_tactics.CLASSES:
            for slot in range(15):
                values=bot_tactics.effective(profile,team,tag,slot)
                if not any(k in values for k in ('development','equipment')):continue
                tiers=(values['skill'],) if 'skill' in values else TIERS
                for tier in tiers:
                    development=values.get('development',{'rookie':'stock','regular':'intermediate','veteran':'full','elite':'full'}[tier])
                    equipment=values.get('equipment',{'rookie':'none','regular':'single','veteran':'standard','elite':'improved'}[tier])
                    if development=='stock' and equipment!='none':
                        raise bot_tactics.TacticsError('Stock development only allows no equipment')


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
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diagnostic
        if diagnostic.detailed_enabled():
            diagnostic.validation_event('bot_effective_factors', vehicle=value['wire'].get('vehicle'),
                tier=value['wire'].get('tier'), crew_level=value['wire']['crew_level'],
                devices=value['wire'].get('devices'), directive=value['wire'].get('directive'),
                crew_active=list(flags), fire=fire,
                factors=dict((name, factor) for name, factor in factors.items()
                             if isinstance(factor, (int, float))))
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
    overrides = value.get('overrides') or {}
    expected = plan(vehicle, tier, overrides)
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
    result = dict(schema=1, vehicle=vehicle, tier=tier, crew_level=int(level),
                descriptor=encoded, devices=list(expected['devices']),
                directive=expected['directive'], style=expected['style'])
    if overrides:
        from gui.mods.offline_lan_0922.bot_tactics import normalize_values
        result['overrides'] = normalize_values(overrides)
    return result


def _named(values, name):
    return next(value for value in values if value.name == name)


def hull_camouflage(outfit, hull_area):
    """Native outfits may have no camouflage (notably rented EVENT outfits)."""
    hull = [item.id for item in outfit.camouflages
            if item.appliedTo & hull_area]
    if len(hull) > 1:
        raise ValueError('native Bot seasonal hull camouflage is ambiguous')
    return hull[0] if hull else None


def build(vehicles, vehicle, tier, crew_level=None, restored=None, overrides=None):
    """Install exact native modules/devices and retain native install guards."""
    from items import tankmen, customizations
    from gui.mods.offline_lan_0922.vehicle_configuration import _installation_accepted
    overrides = overrides or (restored or {}).get('overrides') or {}
    selected = plan(vehicle, tier, overrides)
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
    raw_wire = dict(schema=1, vehicle=vehicle, tier=tier, crew_level=level,
        descriptor=encoded, devices=selected['devices'], directive=selected['directive'], style=selected['style'])
    if overrides:raw_wire['overrides'] = overrides
    wire = canonical(raw_wire)
    if restored is not None and canonical(restored) != wire:
        raise ValueError('restored Bot fitting changed')
    crew_tier = {'50':'rookie','75':'regular','repair':'veteran','all':'elite'}.get(overrides.get('crew_preset'), tier)
    skills = (() if crew_tier in ('rookie', 'regular') else ('repair', 'camouflage'))
    mask = default_crew.sandbox_skill_mask() if crew_tier == 'elite' else tankmen.getSkillsMask(skills)
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
            camouflages[str(season)] = hull_camouflage(outfit, ApplyArea.HULL)
    value = dict(wire=wire, crew=crew, directives=directives, skills=skills,
                 crew_skills=crew_skills, camouflages=camouflages,
                 outfits=outfits, native_style=selected['style'])
    from gui.mods.offline_lan_0922.bot_runtime import _descriptor_crew_roster
    value['crew_roster'] = _descriptor_crew_roster(descriptor)
    register(descriptor, value)
    from gui.mods.offline_lan_0922.native_input_diagnostics import validation_event
    validation_event('bot_fitting_installed', vehicle=vehicle, tier=tier,
        crew_level=level, modules=actual,
        devices=[d.name for d in descriptor.optionalDevices if d is not None],
        directive=selected['directive'],
        native_directives=[d.name for d in directives], style=selected['style'],
        restored=restored is not None, overrides=overrides)
    return descriptor
