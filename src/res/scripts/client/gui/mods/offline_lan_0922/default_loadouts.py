from __future__ import division

"""Explicit sandbox/Bot defaults for the pinned #1513 vehicle catalogue.

Shell roles describe loadout order, never physical kind, currency or native
shot indices. Existing saved fittings are not rewritten by this policy.
"""

LOADOUTS = {
    'germany:G99_RhB_Waffentrager': ('_128mm_K44_L55', ()),
    'germany:G97_Waffentrager_IV': ('_128mm_K44_2_L61', ()),
    'ussr:R77_KV2': ('_152mm_M-10', ('_152mm_53-OF-530', '_152mm_MPB_1915')),
    'france:F33_S_35CA': ('Canon_de_105_mle_1930_Schneider_AC', ()),
    'uk:GB80_Charioteer': ('_105mm_AT_Gun_L7', ('_105mm_HESH_L7', '_105mm_APCR_L7')),
    'uk:GB81_FV4004': ('_5_5inch_AT_Gun', ('_5_5inch_HESH_Mk_1', '_5_5inch_AP_Mk_1')),
    'uk:GB83_FV4005': ('_183mm_AT_Gun', ('_183mm_HESH', '_183mm_AP_Mk1')),
    'uk:GB48_FV215b_183': ('_183mm_L4', ('_183mm_HESH', '_183mm_AP_Mk1')),
    'japan:J23_Mi_To': ('_120mm_Short_Barrel_Gun', ('_120mm_HE_Commerce_Raid', '_120mm_HEAT_Type_88')),
    'japan:J24_Mi_To_130_tons': ('_150mm_Howitzer_Type96', ('_150mm_HE_Type96', '_150mm_HEAT_Type3')),
    'japan:J28_O_I_100': ('_150mm_Howitzer_Type96', ('_150mm_HE_Type96', '_150mm_HEAT_Type3')),
    'japan:J27_O_I_120': ('_150mm_Howitzer_Type96', ('_150mm_HE_Type96', '_150mm_HEAT_Type3')),
    'japan:J25_Type_4': ('_150mm_45_41st_Year_Type', ('_150mm_Common_Type_0_HE_Kai',)),
    'japan:J20_Type_2605': ('_150mm_45_41st_Year_Type', ('_150mm_Common_Type_0_HE_Kai',)),
    'usa:A100_T49': ('_152mm_Gun_Launcher_M81', ('_152mm_HE_XM657E3', '_152mm_HEAT_XM409')),
    'usa:A116_XM551': ('_152mm_Gun_Launcher_M81', ('_152mm_HE_XM657E3', '_152mm_HEAT_XM409')),
    'ussr:R18_SU-152': ('_152mm_ML-20_mod_1937', ('_152mm_53-OF-530', '_152mm_53BP540')),
    'ussr:R20_T-44': ('_100mm_LB-1', ()),
    'ussr:R106_KV85': ('_100mm_S34', ()),
    'china:Ch05_T34_2': ('_100mm_59-100T', ()),
    'ussr:R22_T-46': ('_45mm_VT-42', ()),
    'ussr:R12_A-20': ('_45mm_VT-42', ()),
    'ussr:R44_T80': ('_45mm_VT-43', ()),
    'germany:G83_Pz_IV_AusfA': ('_75mm_KwK_37_L24', ('_75mm_Sprg.18', '_Gr_38_HL_A')),
    'germany:G100_Gtraktor_Krupp': ('_75mm_KwK_37_L24A', ('_75mm_Sprg.18', '_Gr_38_HL_A')),
    'germany:G09_Hetzer': ('_105mm_StuH42_L28', ('_105mm_Sprg_K', '_105mmGr39H1A')),
    'germany:G101_StuG_III': ('_105mm_StuH42_L28', ('_105mm_Sprg_K', '_105mmGr39H1A')),
    'sweden:S19_Sav_M43': ('_105mm_kan_m_44_sav', ('_105mm_lt_sgr_m_34', '_105mm_psgr_m_49')),
    'ussr:R49_SU100Y': ('_130mm_B-13-S2', ('_130mm_PB-46A', '_130mm_PB-46', '_130mm_OF-46')),
    'ussr:R111_ISU130': ('_130mm_S-26A', ('_130mm_2-01743', '_130mm_2-02864A', '_130mm_2-02742')),
    'germany:G81_Pz_IV_AusfH': ('_105mm_StuH42_L28Pz', ('_105mm_Sprg_K', '_105mmGr39H1A')),
    'uk:GB72_AT15': ('_32-pounder_AT_Gun_OQF', ()),
}


def value(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def gun_override(vehicle_name):
    return LOADOUTS.get(vehicle_name, (None, ()))[0]


def shell_roles(vehicle_name, gun_name, shell_names):
    """Return native-index -> logical-role, or None for an unmodified gun.

    Excluded native indices have no role. Never relabel an HE round as AP.
    A different gun mounted by the player keeps its original ammunition law.
    """
    selected, names = LOADOUTS.get(vehicle_name, (None, ()))
    if gun_name != selected or not names:
        return None
    shell_names = tuple(shell_names)
    if any(shell_names.count(name) != 1 for name in names):
        raise ValueError('special loadout shell missing or duplicated: %s' % vehicle_name)
    return dict((shell_names.index(name), role)
                for name, role in zip(names, ('standard', 'premium', 'he')))


def descriptor_roles(descriptor):
    gun = value(descriptor, 'gun', {})
    return shell_roles(value(value(descriptor, 'type', {}), 'name'),
                       value(gun, 'name'),
                       [value(value(shot, 'shell', {}), 'name')
                        for shot in value(gun, 'shots', ())])


def profile_roles(profile):
    return shell_roles(profile.get('vehicle_name'), profile.get('gun_name'),
                       [shell.get('name') for shell in profile.get('shells', ())])


def allocate(maximum, roles, shell_count):
    """Largest remainders, full capacity, 3:2:1 over included roles only."""
    weights = {'standard': 3, 'premium': 2, 'he': 1}
    result = [0] * shell_count
    indices = sorted(roles, key=lambda i: -weights[roles[i]])
    total = sum(weights[roles[i]] for i in indices)
    if not total or maximum <= 0:
        return result
    for i in indices:
        result[i] = maximum * weights[roles[i]] // total
    remainder = sorted(indices, key=lambda i: (
        -(maximum * weights[roles[i]] % total), indices.index(i)))
    for i in remainder[:maximum - sum(result)]:
        result[i] += 1
    return result


def garage_ammo(descriptor):
    """Return ordered compact-descriptor/count pairs for an explicit loadout."""
    roles = descriptor_roles(descriptor)
    if roles is None:
        return None
    shots = descriptor.gun.shots
    maximum = int(descriptor.gun.maxAmmo)
    counts = allocate(maximum, roles, len(shots))
    result = []
    for role in ('standard', 'premium', 'he'):
        for index in sorted(roles):
            if roles[index] == role:
                result.extend((int(shots[index].shell.compactDescr), counts[index]))
    return result
