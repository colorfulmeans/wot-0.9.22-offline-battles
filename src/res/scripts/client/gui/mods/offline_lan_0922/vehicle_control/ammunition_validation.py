"""Player planning roles for the exact #1513 gun/shell combinations.

These roles do not alter a shell's physical kind, damage or magazine rules.
The five HE exceptions were selected from the pinned client's mounted shots;
shell names alone cannot identify penetration because guns can share a shell.
"""
from __future__ import division


FULL = 'full'
SINGLE_POINT = 'single_point'
HE = 'HIGH_EXPLOSIVE'
FULL_VALIDATION_HE = frozenset((
    ('uk:_183mm_L4', 'uk:_183mm_HESH'),
    ('uk:_183mm_AT_Gun', 'uk:_183mm_HESH'),
    ('uk:_105mm_Gun_L7', 'uk:_105mm_HESH_L7'),
    ('uk:_105mm_AT_Gun_L7', 'uk:_105mm_HESH_L7'),
    ('uk:_5_5inch_AT_Gun', 'uk:_5_5inch_HESH_Mk_1'),
))


def validation_mode(gun_identity, shell_identity, kind):
    """Classify the mounted shot without inferring identity from slot/price."""
    if kind != HE:
        return FULL
    return FULL if (gun_identity, shell_identity) in FULL_VALIDATION_HE else SINGLE_POINT


def shell_mode(shell):
    """Read the observation's role; unlabelled physical HE uses the default."""
    mode = shell.get('validation_mode')
    if mode in (FULL, SINGLE_POINT):
        return mode
    return SINGLE_POINT if shell.get('is_he') else FULL
