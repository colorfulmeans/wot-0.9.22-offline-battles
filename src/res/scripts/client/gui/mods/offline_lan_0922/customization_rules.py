"""Pinned #1513 style ownership: isRent decides, rentCount is a quantity."""


def is_rental(style):
    return style is not None and bool(getattr(style, 'isRent', False))


def rental_battles(style):
    # Raw StyleItem defaults to isRent=False, rentCount=1. The GUI Style
    # wrapper masks that quantity for permanent styles; garage/cache owners
    # read the raw descriptor and must apply the same classification.
    if not is_rental(style):
        return 0
    return max(0, int(getattr(style, 'rentCount', 0) or 0))
