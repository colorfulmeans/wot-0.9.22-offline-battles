"""Single-player roster, native loadouts and existing Redshire corridors."""
import os

from .gun_mechanics import _field

ENV = 'WOT_OFFLINE_MOBILE_COMBAT_TEST'
MAP = '34_redshire'

PFM = 'sweden:S09_L_120_TD'
ELC = 'france:F62_ELC_AMX'
UDES = 'sweden:S21_UDES_03'
FV = 'uk:GB48_FV215b_183'
TYPE4 = 'japan:J25_Type_4'
OHO = 'japan:J27_O_I_120'
OBJECT261 = 'ussr:R52_Object_261'
BATCHAT = 'france:F38_Bat_Chatillon155_58'

VEHICLES = (PFM,) * 4 + (ELC,) * 4 + (UDES,) * 2 + (FV, TYPE4, OHO, OBJECT261, BATCHAT)
LOADOUTS = {
    PFM: ('_20mm_pvlvkan_m_40',
          (('_20mm_slpprj_m_40', 80), ('_20mm_slpprj_m_49', 80), ('_20mm_slsgr_m_42', 80))),
    ELC: ('_90mm_D914',
          (('_90mm_Prf1941', 12), ('_90mm_FrtPrf1944', 12), ('_90mm_OE_mle_1924', 12))),
    UDES: ('_105mm_kan_UDES_03',
           (('_105mm_slpprj_m_61', 13), ('_105mm_slpprj_m_ny', 13), ('_105mm_slsgr_m_61A', 14))),
    FV: ('_183mm_L4', (('_183mm_AP_Mk1', 6), ('_183mm_HE_Mk1', 7), ('_183mm_HESH', 7))),
    TYPE4: ('_150mm_45_41st_Year_Type',
            (('_150mm_Common_Type_0_HE', 20), ('_150mm_Common_Type_0_HE_Kai', 20))),
    OHO: ('_150mm_Howitzer_Type96',
          (('_150mm_APHE_Type1', 20), ('_150mm_HEAT_Type3', 20), ('_150mm_HE_Type96', 20))),
    OBJECT261: ('_180mm_B-1-P', (('_180mm_F-600D', 9), ('_180mm_F-600BM', 9))),
    BATCHAT: ('Canon_de_155mm', (('_155mm_OE_M101M4', 18), ('_155mm_OE_M101M6', 18))),
}


def enabled():
    return (os.environ.get('WOT_OFFLINE_DIAGNOSTICS') == '1' and
            os.environ.get(ENV) == '1')


def lineup():
    return [dict(team=team, slot=slot, vehicle=vehicle, skill='veteran', enabled=True)
            for team in (1, 2) for slot, vehicle in enumerate(VEHICLES)]


def ammunition(descriptor, vehicle):
    """Return counts indexed by the mounted gun, or None outside this scene."""
    if not enabled() or vehicle not in LOADOUTS:
        return None
    gun_name, shells = LOADOUTS[vehicle]
    gun = _field(descriptor, 'gun')
    if _field(gun, 'name') != gun_name:
        raise ValueError('Mobile combat test requires %s on %s' % (gun_name, vehicle))
    stock = dict(shells)
    counts = [stock.pop(_field(_field(shot, 'shell'), 'name'), 0)
              for shot in _field(gun, 'shots', ())]
    maximum = _field(descriptor, 'maxAmmo', _field(gun, 'maxAmmo'))
    if stock or sum(counts) != int(maximum):
        raise ValueError('Mobile combat test ammunition does not match the native rack')
    return counts


def tactics():
    from . import bot_tactics
    profile = bot_tactics.empty('Mobile combat test')
    profile['behavior'].append(dict(team=0, class_tag='all', slot=-1,
                                    values=dict(ammo_ratios=[1, 1, 1])))
    settings = profile['maps'][MAP] = bot_tactics.default_map(MAP)
    # The eastern parking spots sit below the ridge along the moving targets.
    settings['deleted_positions'] = ['spg_%d_east_ridge' % team for team in (1, 2)]
    settings['positions'] = [row for row in settings['positions']
                             if row['id'] not in settings['deleted_positions']]
    groups = (
        ('pfm_west', 'west_fields', None, 'AT-SPG', [0, 1]),
        ('pfm_east', 'east_ridge', None, 'AT-SPG', [2, 3]),
        ('elc_centre', 'river_town', 'lightTank', 'lightTank', [4, 5]),
        ('elc_west', 'west_fields', 'lightTank', 'lightTank', [6, 7]),
        ('udes_ridge', 'east_ridge', None, 'AT-SPG', [8, 9]),
        ('heavy_centre', 'river_town', 'heavyTank', 'heavyTank', [11, 12]),
    )
    for team in (1, 2):
        for label, family, source_class, target_class, slots in groups:
            authored = next(row for row in settings['default_routes']
                            if row['team'] == team and row['id'] == family and
                            row.get('class_tag') == source_class)
            settings['routes'].append(dict(id='test_%s_%s' % (team, label),
                label=label, team=team, classes=[target_class], slots=slots,
                policy='fixed', capacity=len(slots), weight=1., points=authored['points']))
    return bot_tactics.canonical(profile)
