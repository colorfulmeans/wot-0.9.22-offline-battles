"""Daily missions in the same native Window chrome as stock settings."""
from gui.mods.offline_lan_0922.waiting_room_flash import RoomWindow, _rooms
from gui.mods.offline_lan_0922.ui_i18n import tr


class DailyWindow(RoomWindow):
    def __init__(self, room):
        RoomWindow.__init__(self, room)
        self._tick = None

    def model(self):
        from gui.mods.offline_lan_0922 import offline_services_ui as ui
        daily = ui.policy.daily_state(ui.snapshot())
        labels = dict(note=tr('Standard battles only. Rewards automatic. Resets at 00:00 UTC.'))
        for index, key in enumerate(daily['missions']):
            row = ui.policy.MISSION_BY_ID[key]
            labels['row%d' % index] = tr('%s: %d/%d') % (
                ui.mission_label(row), daily[key], row[3])
            labels['reward%d' % index] = tr('Reward: %s reserve x1%s') % (
                tr(ui.policy.RESERVE_BY_ID[row[4]][1]),
                tr(' (RECEIVED)') if key in daily['claimed'] else '')
        return dict(daily=True, title=tr('DAILY MISSIONS'), labels=labels,
            controls=dict((key, dict(label=tr(caption), enabled=True,
                                    visible=True, selected=False))
                for key, caption in (('reserves', 'PERSONAL RESERVES'), ('close', 'CLOSE'))))

    def refresh(self):
        result = RoomWindow.refresh(self)
        if self.view is not None and self._tick is None:
            import BigWorld
            token, view = self.token, self.view
            def refresh():
                self._tick = None
                if (_rooms.get(token) is self and self.token == token and
                        self.view is view and self.room._open):
                    self.refresh()
            self._tick = BigWorld.callback(1.0, refresh)
        return result

    def close(self):
        if self._tick is not None:
            import BigWorld
            callback, self._tick = self._tick, None
            BigWorld.cancelCallback(callback)
        return RoomWindow.close(self)

    def action(self, role, value):
        if not self.room._open or _rooms.get(self.token) is not self:
            return
        if role == 'diagnostics':
            from gui.mods.offline_lan_0922.native_input_diagnostics import validation_event
            validation_event('daily_window_layout', layout=str(value)[:2048])
        elif role in ('close', 'reserves'):
            self.room.activate(role)
