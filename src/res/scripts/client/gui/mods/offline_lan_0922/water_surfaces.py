"""The unculled geometric part of #1513 wg_collideWater(start, end, False).

The native routine checks render visibility before its segment/rectangle test.
Its False argument skips edge-alpha tests, not those visibility guards. Use the
exact BWWa rectangles for the shared vertical physics ray, so a private worker
camera cannot turn an existing water surface into a safe/dry observation.
"""
from gui.mods.offline_lan_0922.water_surface_data import SURFACES

# #1513 a3055a/a3058a..a305c9: the native local bounding-box tolerance.
BOUNDARY_EPSILON = 0.0010000000474974513


def depth(map_name, point, receipt=None):
    rows = SURFACES.get(map_name)
    if rows is None:
        return None
    x, y, z = map(float, point)
    if receipt is not None:
        receipt.update(source='compiled_water_rectangles', map=map_name,
                       rectangle_count=len(rows), selected_depth=-1.0,
                       reason='no_water_hit', raw_distance=-1.0)
    for index, row in enumerate(rows):
        px, surface, pz, half_x, half_z, cosine, sine = row
        distance = y+20.-surface
        # The native helper tests the forward ray, not a 25 m segment cap.
        if distance <= 0.:
            continue
        dx, dz = x-px, z-pz
        local_x, local_z = dx*cosine+dz*sine, -dx*sine+dz*cosine
        if abs(local_x) > half_x+BOUNDARY_EPSILON or abs(local_z) > half_z+BOUNDARY_EPSILON:
            continue
        value = surface-y
        if receipt is not None:
            receipt.update(reason='water_hit', raw_distance=distance,
                selected_depth=value, surface_height=surface, rectangle=index,
                local_position=(local_x, local_z), half_extents=(half_x, half_z))
        return value
    return -1.0
