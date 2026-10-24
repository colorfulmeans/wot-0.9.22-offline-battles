"""Sandbox secondary skills copied from the reviewed full-skill save.

Only the active skill IDs are retained. Native generateTankmen filters this
mask by each seat's combined roles and generates fresh passports. Career
recruits and existing saved crews are unchanged.
"""

SKILL_IDS = (6, 7, 8, 9, 16, 17, 18, 19, 20, 28, 29, 30, 31, 32,
             37, 38, 39, 40, 46, 47, 48, 53, 54, 55, 56)


def sandbox_skill_mask():
    result = 0
    for index in SKILL_IDS:
        result |= 1 << index
    return result
