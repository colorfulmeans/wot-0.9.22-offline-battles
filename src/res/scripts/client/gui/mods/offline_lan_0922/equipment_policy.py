"""Shared priorities; player and Bot installers remain separate owners."""

PRIORITIES = {
    'lightTank': ('optics', 'rammer', 'stabilizer', 'ventilation', 'aim_drives'),
    'mediumTank': ('rammer', 'stabilizer', 'optics', 'ventilation', 'aim_drives'),
    'heavyTank': ('liner', 'rammer', 'stabilizer', 'ventilation', 'aim_drives'),
    'AT-SPG': ('rammer', 'ventilation', 'aim_drives', 'camouflage', 'binoculars'),
    'SPG': ('rammer', 'ventilation', 'aim_drives', 'camouflage', 'binoculars'),
}

NORMAL = {
    'liner': ('antifragmentationLining_superheavy', 'antifragmentationLining_heavy',
              'antifragmentationLining_medium', 'antifragmentationLining_light'),
    'binoculars': ('stereoscope',),
    'ventilation': ('improvedVentilation_class1', 'improvedVentilation_class2',
                    'improvedVentilation_class3'),
    'optics': ('coatedOptics',),
    'stabilizer': ('aimingStabilizer_Mk1', 'aimingStabilizer_Mk2'),
    'rammer': ('mediumCaliberTankRammer', 'largeCaliberTankRammer',
               'mediumCaliberHowitzerRammer', 'largeCaliberHowitzerRammer'),
    'aim_drives': ('enhancedAimDrives',),
    'camouflage': ('camouflageNet',),
}
IMPROVED = dict(ventilation='deluxImprovedVentilation',
    optics='deluxCoatedOptics', stabilizer='deluxAimingStabilizer',
    rammer='deluxRammer', aim_drives='deluxEnhancedAimDrives')
DIRECTIVES = dict(ventilation='improvedVentilationBattleBooster',
    optics='coatedOpticsBattleBooster', stabilizer='aimingStabilizerBattleBooster',
    rammer='rammerBattleBooster', aim_drives='enhancedAimDrivesBattleBooster')


def class_tag(tags):
    found = [tag for tag in PRIORITIES if tag in tags]
    if len(found) != 1:
        raise ValueError('vehicle must have exactly one equipment class')
    return found[0]


def candidates(tag, improved=False):
    for family in PRIORITIES[tag]:
        names = NORMAL[family]
        if improved and family in IMPROVED:
            names = (IMPROVED[family],) + names
        yield names


def directive_candidates(installed):
    for name in installed:
        for family, normal in NORMAL.items():
            if name in normal or name == IMPROVED.get(family):
                directive = DIRECTIVES.get(family)
                if directive is not None:
                    yield directive
                break
