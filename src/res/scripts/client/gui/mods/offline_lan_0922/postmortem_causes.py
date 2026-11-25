# -*- coding: utf-8 -*-
"""Custom environmental ammunition deaths on the exact #1513 panel contract."""

from gui.mods.offline_lan_0922.ui_i18n import tr


def populate_templates(panel):
    messages = panel._BasePostmortemPanel__messages
    fire = 'DEATH_FROM_DEVICE_EXPLOSION_AT_FIRE'
    collision = 'DEATH_FROM_DEVICE_EXPLOSION_AT_WORLD_COLLISION'
    # #1513 readXML returns (translated template, color tuple) per code.
    # Keep its colors and let the stock panel own killer/name formatting.
    for key in list(messages):
        if key == fire or key.startswith(fire + '_'):
            unused_text, colors = messages[key]
            messages[key] = (tr('Ammunition rack exploded due to fire'), colors)
    template = messages.get(fire) or messages.get('DEATH_FROM_FIRE')
    if template is not None:
        messages[collision] = (tr('Ammunition rack destroyed by a fall'), template[1])


def wrap_populate(original):
    def populate(panel, *args, **kwargs):
        result = original(panel, *args, **kwargs)
        populate_templates(panel)
        return result
    return populate
