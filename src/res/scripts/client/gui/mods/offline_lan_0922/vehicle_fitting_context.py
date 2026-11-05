"""Installed descriptor/crew facts shared by local physical consumers.

This registry does not choose equipment, skill tiers, vehicles or tactics.
Those policies publish a completed native fitting; players and replicas can
then read the same physical facts without importing a Bot implementation.
"""
from gui.mods.offline_lan_0922 import siege_mechanics


_CONTEXTS = {}


def context(descriptor):
    entry = _CONTEXTS.get(id(descriptor))
    return entry[1] if entry is not None and entry[0] is descriptor else None


def clear():
    _CONTEXTS.clear()


def register(descriptor, value):
    for member in (descriptor,) + siege_mechanics.descriptor_pair(descriptor):
        if member is not None:
            _CONTEXTS[id(member)] = (member, value)


def native_factors(descriptor, critical=None, equipments=()):
    """Cache native factors by immutable fitting and actual crew/fire state."""
    from gui.mods.offline_lan_0922 import loadout
    value = context(descriptor)
    if value is None:
        raise ValueError('installed vehicle fitting is unavailable')
    critical = critical or {}
    knocked_out = frozenset(critical.get('crew_ko') or ())
    flags = tuple(name not in knocked_out for name in value['crew_roster'])
    fire = bool(critical.get('fire', False))
    consumables = tuple(equipments or ())
    key = (id(descriptor), flags, fire, consumables)
    cache = value.setdefault('factors', {})
    if key not in cache:
        factors = loadout.attribute_factors(
            descriptor, equipments=consumables, activity_flags=flags, is_fire=fire,
            crew_level=value['wire']['crew_level'])
        if factors is None:
            raise RuntimeError('native installed crew factors were rejected')
        cache[key] = factors
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diagnostic
        if diagnostic.detailed_enabled():
            modifiers = loadout.modifiers(
                descriptor, crew_skills=value.get('crew_skills', ()), factors=factors)
            misc = getattr(descriptor, 'miscAttrs', None) or {}
            gun = getattr(descriptor, 'gun', None)
            base_reload = getattr(gun, 'reloadTime', None)
            # Keep the established diagnostic schema for installed replicas.
            diagnostic.validation_event('bot_effective_factors', vehicle=value['wire'].get('vehicle'),
                tier=value['wire'].get('tier'), crew_level=value['wire']['crew_level'],
                devices=value['wire'].get('devices'), directive=value['wire'].get('directive'),
                crew_active=list(flags), fire=fire,
                descriptor_misc=dict((name, misc[name]) for name in (
                    'gunReloadTimeFactor', 'gunAimingTimeFactor',
                    'crewChanceToHitFactor', 'vehicleByChassisDamageFactor',
                    'chassisHealthFactor', 'ammoBayHealthFactor',
                    'engineHealthFactor', 'fuelTankHealthFactor') if name in misc),
                final_modifiers=dict((name, factor) for name, factor in modifiers.items()
                                     if isinstance(factor, (int, float))),
                base_reload_seconds=base_reload,
                effective_reload_seconds=(float(base_reload) * modifiers['reload_factor']
                                          if base_reload is not None else None),
                factors=dict((name, factor) for name, factor in factors.items()
                             if isinstance(factor, (int, float))))
    return cache[key]


def battle_factors(descriptor, critical=None, equipments=()):
    from gui.mods.offline_lan_0922 import crew_battle
    return crew_battle.from_native(native_factors(descriptor, critical, equipments=equipments))


def skill_snapshot(descriptor):
    """Project installed native crew slots through the shared eligibility law."""
    value = context(descriptor)
    if value is None:
        return None
    if 'skill_snapshot' not in value:
        from items import tankmen
        from gui.mods.offline_lan_0922 import effective_params
        members = []
        for index, raw in enumerate(value['crew']):
            member = tankmen.TankmanDescr(raw)
            names = tuple(member.skills)
            roles = list(descriptor.type.crewRoles[index])
            skills = []
            for order, name in enumerate(names):
                name = str(name).lower()
                role = effective_params.skill_required_role(name)
                level = (float(getattr(member, 'lastSkillLevel', 100))
                         if order == len(names) - 1 else 100.0)
                skills.append(dict(name=name, level=level, active=True,
                                   enabled=role is None or role in roles))
            # A directive grants the installed discrete perk even when the
            # member has not trained it; numerical native factors are separate.
            for booster in value.get('directives', ()):
                name = str(getattr(booster, 'skillName', '')).lower()
                if (name not in effective_params.DISCRETE_SKILL_ROLES or
                        effective_params.skill_required_role(name) not in roles):
                    continue
                existing = next((row for row in skills if row['name'] == name), None)
                if existing is None:
                    existing = dict(name=name)
                    skills.append(existing)
                existing.update(level=100.0, active=True, enabled=True)
            members.append(dict(instance=value['crew_roster'][index],
                                roles=roles, skills=skills))
        value['skill_snapshot'] = {'crew': {'members': members}}
    return value['skill_snapshot']


def skill_count(descriptor, name, critical=None):
    from gui.mods.offline_lan_0922 import effective_params
    snapshot = skill_snapshot(descriptor)
    return (effective_params.living_skill_count(
        snapshot, name, (critical or {}).get('crew_ko', ()))
        if snapshot is not None else 0)


def skill_level(descriptor, name, critical=None):
    from gui.mods.offline_lan_0922 import effective_params
    snapshot = skill_snapshot(descriptor)
    return (effective_params.living_skill_level(
        snapshot, name, (critical or {}).get('crew_ko', ()))
        if snapshot is not None else 0.0)


def descriptor_crew_roster(descriptor):
    """Return the exact #1513 health-instance names for one real crew."""
    roles = getattr(getattr(descriptor, 'type', None), 'crewRoles', None)
    if not isinstance(roles, (list, tuple)) or not roles:
        return ()
    counters = {'gunner': 1, 'loader': 1, 'radioman': 1}
    allowed = frozenset(
        ('commander', 'driver', 'gunner', 'loader', 'radioman'))
    roster = []
    for crewman_roles in roles:
        if (not isinstance(crewman_roles, (list, tuple)) or
                not crewman_roles):
            return ()
        main_role = str(crewman_roles[0])
        if main_role not in allowed:
            return ()
        if main_role in counters:
            name = main_role + str(counters[main_role])
            counters[main_role] += 1
        else:
            name = main_role
        if name in roster:
            return ()
        roster.append(name)
    return tuple(roster)
