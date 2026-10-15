# -*- coding: utf-8 -*-
"""Custom environmental ammunition deaths on the exact #1513 panel contract."""


def populate_templates(panel):
    messages = panel._BasePostmortemPanel__messages
    fire = 'DEATH_FROM_DEVICE_EXPLOSION_AT_FIRE'
    collision = 'DEATH_FROM_DEVICE_EXPLOSION_AT_WORLD_COLLISION'
    # #1513 readXML returns (translated template, color tuple) per code.
    # Keep its colors and let the stock panel own killer/name formatting.
    for key in list(messages):
        if key == fire or key.startswith(fire + '_'):
            unused_text, colors = messages[key]
            messages[key] = (u'弹药架因燃烧而爆炸', colors)
    template = messages.get(fire) or messages.get('DEATH_FROM_FIRE')
    if template is not None:
        messages[collision] = (u'弹药架因坠落而损毁', template[1])


def wrap_populate(original):
    def populate(panel, *args, **kwargs):
        result = original(panel, *args, **kwargs)
        populate_templates(panel)
        return result
    return populate
