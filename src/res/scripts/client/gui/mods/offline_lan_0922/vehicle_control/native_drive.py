"""Foreground physical checks, with no navigation or driving decisions."""
from __future__ import division

import math


def capture_pivot_allows(circle, position, end, pivot_offset, angle):
    """Bound the centre's arc by its chord plus the arc's sagitta."""
    (x, z), radius = circle
    farthest_end = max(math.hypot(position[0]-x, position[2]-z),
                       math.hypot(end[0]-x, end[2]-z))
    sagitta = abs(pivot_offset) * (1. - math.cos(angle * .5))
    return farthest_end + sagitta <= radius
