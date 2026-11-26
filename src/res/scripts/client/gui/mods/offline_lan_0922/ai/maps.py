# -*- coding: utf-8 -*-
"""Stock arena rectangles for the LAN server and the battle runtime.

Each map's ``bounds`` is the exact stock ``scripts/arena_defs/<map>.xml``
boundingBox rather than an authoring estimate: the LAN server resolves a
minimap attention-cell order through this rectangle, so a wider one would
order Bots at, or past, the red border.

Bot routes come from the built-in Default tactics, never from this registry.
"""


HIMMELSDORF = {
	'name': '04_himmelsdorf',
	'bounds': (-300.0, -300.0, 400.0, 400.0),
}


TACTICAL_MAPS = {
	'04_himmelsdorf': HIMMELSDORF,
}

# The other rectangles live in data-only modules, one per map group.
from gui.mods.offline_lan_0922.ai import maps_group_a
from gui.mods.offline_lan_0922.ai import maps_group_b
from gui.mods.offline_lan_0922.ai import maps_group_c
from gui.mods.offline_lan_0922.ai import maps_extra
from gui.mods.offline_lan_0922.ai import maps_0922_extra

TACTICAL_MAPS.update(maps_group_a.TACTICAL_MAPS_GROUP_A)
TACTICAL_MAPS.update(maps_group_b.TACTICAL_MAPS_GROUP_B)
TACTICAL_MAPS.update(maps_group_c.TACTICAL_MAPS_GROUP_C)
TACTICAL_MAPS.update(maps_extra.TACTICAL_MAPS_EXTRA)
TACTICAL_MAPS.update(maps_0922_extra.TACTICAL_MAPS_0922_EXTRA)


def normalize_map_name(map_name):
	name = str(map_name or '').replace('\\', '/').split('/')[-1]
	if name.endswith('.xml'):
		name = name[:-4]
	return name.lower()


def get_tactical_map(map_name):
	return TACTICAL_MAPS.get(normalize_map_name(map_name))
