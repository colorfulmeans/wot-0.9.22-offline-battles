# -*- coding: utf-8 -*-
"""Blue, battle-owned outgoing team damage without enemy efficiency credit."""
from gui.mods.offline_lan_0922 import ui_i18n


class FriendlyDamageHUD(object):
    COLOUR = (100, 180, 255, 255)

    def __init__(self, gui=None):
        self.gui = gui
        self.total = 0
        self.rows = []
        self.roots = []

    def record(self, damage, vehicle_name, reason, dead=False):
        damage = max(0, int(damage))
        if not damage:
            return False
        self.total += damage
        self.rows.append(u'%s  -%d  %s%s' % (
            ui_i18n.as_text(vehicle_name), damage,
            {0: u'射击', 1: u'燃烧', 2: u'撞击', 3: u'坠落',
             5: u'淹没', 7: u'翻覆'}.get(reason, u'伤害'),
            u'（击毁）' if dead else u''))
        self.rows = self.rows[-4:]
        self.draw()
        return True

    def draw(self):
        if self.gui is None:
            import GUI
            self.gui = GUI
        lines = [u'友军伤害：%d' % self.total] + list(reversed(self.rows))
        # Use the already-reviewed #1513 GUI.Text surface and shipped CJK font.
        # This extra team-damage column never feeds the stock DAMAGE total.
        while len(self.roots) < len(lines):
            label = self.gui.Text('')
            label.font = ui_i18n.CHINESE_FONT
            label.horizontalPositionMode = 'CLIP'
            label.verticalPositionMode = 'CLIP'
            label.widthMode = 'CLIP'
            label.heightMode = 'CLIP'
            label.width = 0.8
            label.height = 0.05
            label.horizontalAnchor = 'LEFT'
            label.verticalAnchor = 'CENTER'
            label.colour = self.COLOUR
            label.multiline = False
            label.focus = False
            label.mouseButtonFocus = False
            label.crossFocus = False
            label.moveFocus = False
            label.position = (-0.96, 0.38 - len(self.roots)*0.055, 0.01)
            # Register ownership before native calls which may re-enter.
            self.roots.append(label)
            self.gui.addRoot(label)
        for label, text in zip(self.roots, lines):
            label.text = text
            label.visible = True

    def close(self):
        roots, self.roots = self.roots, []
        for label in reversed(roots):
            label.visible = False
            try:
                self.gui.delRoot(label)
            except Exception:
                pass
        self.rows = []
        self.total = 0
