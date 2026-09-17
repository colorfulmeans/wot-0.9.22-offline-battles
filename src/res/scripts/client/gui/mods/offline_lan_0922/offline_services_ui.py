"""Offline lobby adapters; mutations always use the Account command path.

The native store still owns its cards. Reserves and daily missions share the
same reversible native surface as the LAN room, including cursor retirement.
Retail battle-result labels remain owned by the installed client locale.
"""

import json
import time

from gui.mods.offline_lan_0922 import offline_services as policy
from gui.mods.offline_lan_0922.ui_i18n import tr, as_text
from gui.mods.offline_lan_0922.waiting_room_ui import (
    WaitingRoomUI, _ControlScript, CONTROL_Z, CONTROL_TEXT_COLOUR)

TEXT_Z = 0.0

_patches = []
_panels = []


def snapshot():
    from gui.mods.offline_lan_0922.compat import g_compatibility
    state = g_compatibility.garage_state()
    return state.snapshot() if state is not None else {}


def request(action, key, callback):
    import BigWorld
    from gui.mods.offline_lan_0922.account_rpc.commands import CMD_OFFLINE_SERVICE
    account = BigWorld.player()

    def complete(unused_request, result, error, *unused):
        if BigWorld.player() is account:
            message = tr(error) if error else ''
            if error and error.startswith('the account has '):
                message = tr('Insufficient currency for this purchase.')
            callback(result >= 0, message)

    account._doCmdStr(CMD_OFFLINE_SERVICE,
                     json.dumps({'action': action, 'key': key}), complete)


class _ServiceControl(_ControlScript):
    def handleKeyEvent(self, event):
        import Keys
        if event.key == Keys.KEY_ESCAPE and event.isKeyDown():
            self._room.activate('close')
            return True
        return False


class ServicePanel(WaitingRoomUI):
    def __init__(self, page, on_close=None, surface=None):
        WaitingRoomUI.__init__(self, lambda unused: False, lambda: (),
                               on_close=on_close, surface=surface)
        self._page = page
        self._busy = False
        self._last_paint = 0

    def install(self):
        if self._panel is not None:
            return True
        WaitingRoomUI.install(self)
        for component in list(self._controls.values()) + list(self._labels.values()):
            self._panel.delChild(component)
        self._controls, self._labels = {}, {}
        self._panel.script = _ServiceControl(self, None)
        self._make_label('title', '', (-0.89, 0.82, TEXT_Z), 1.8, 0.12)
        self._make_label('wallet', '', (-0.89, 0.65, TEXT_Z), 1.8, 0.10)
        for index in range(4):
            y = 0.38 - index * 0.23
            self._make_label('row%d' % index, '',
                             (-0.89, y, TEXT_Z), 1.15, 0.15)
            for verb, x in (('buy', 0.36), ('use', 0.74)):
                role = '%s%d' % (verb, index)
                self._make_control(role, (x, y, CONTROL_Z), 0.34, 0.16)
                self._make_label(role, '', (x, y, TEXT_Z), 0.34, 0.14,
                                 anchor='CENTER', colour=CONTROL_TEXT_COLOUR)
        self._make_label('note', '', (-0.89, -0.50, TEXT_Z), 1.8, 0.12)
        self._make_label('message', '', (-0.89, -0.65, TEXT_Z), 1.8, 0.12)
        for role, text, x in (('switch', '', -0.45), ('close', tr('CLOSE'), 0.55)):
            self._make_control(role, (x, -0.85, CONTROL_Z), 0.75, 0.16)
            self._make_label(role, text, (x, -0.85, TEXT_Z), 0.75, 0.14,
                             anchor='CENTER', colour=CONTROL_TEXT_COLOUR)
        for role, component in self._controls.items():
            component.script = _ServiceControl(self, role)
        return True

    def _sync_selection(self):
        return ()

    def _move_pointer(self):
        WaitingRoomUI._move_pointer(self)
        stamp = int(time.time())
        if self._open and self._last_paint != stamp:
            self._last_paint = stamp
            self.refresh()

    def _refresh_contents(self):
        self._apply_layout()
        data = snapshot()
        stamp = int(time.time())
        reserves = policy.reserve_state(data)
        active = dict((key, value) for key, value in reserves['active'].items()
                      if value[1] > stamp)
        self._set_text('title', tr('PERSONAL RESERVES') if self._page == 'reserves'
                       else tr('DAILY MISSIONS'))
        self._set_text('wallet', tr('Gold: %d   Active reserves: %d / 3') %
                       ((data.get('wallet') or {}).get('gold', 0), len(active)))
        self._set_text('switch', tr('DAILY MISSIONS') if self._page == 'reserves'
                       else tr('PERSONAL RESERVES'))
        self._set_text('message', self._message)
        for component in list(self._controls.values()) + list(self._labels.values()):
            self._set(component, 'visible', True)
        self._set(self._panel, 'visible', True)
        if self._page == 'reserves':
            self._set_text('note', tr('1 hour each. Up to 3 types. Timer continues offline.'))
            for index, (key, label, percent, price) in enumerate(policy.RESERVES):
                self._set(self._labels['row%d' % index], 'width', 1.15)
                remaining = (active[key][1] - stamp + 59) // 60 if key in active else 0
                self._set_text('row%d' % index,
                    tr('%s +%d%% | Owned: %d | %d min') %
                    (tr(label), percent, reserves['counts'][key], remaining))
                self._set_text('buy%d' % index, tr('%d gold') % price)
                self._set_text('use%d' % index,
                               tr('ACTIVE') if key in active else tr('ACTIVATE'))
        else:
            daily = policy.daily_state(data, stamp)
            self._set_text('note', tr('Standard battles only. Rewards automatic. Resets at 00:00 UTC.'))
            for index in range(4):
                for verb in ('buy', 'use'):
                    role = '%s%d' % (verb, index)
                    self._set(self._controls[role], 'visible', False)
                    self._set(self._labels[role], 'visible', False)
                if index < len(policy.DAILY_MISSIONS):
                    key, label, target, reward = policy.DAILY_MISSIONS[index]
                    text = tr('%s: %d/%d | Reward: %s x1%s') % (
                        tr(label), daily[key], target,
                        tr(policy.RESERVE_BY_ID[reward][1]),
                        tr(' (RECEIVED)') if key in daily['claimed'] else '')
                else:
                    text = ''
                self._set(self._labels['row%d' % index], 'width', 1.8)
                self._set_text('row%d' % index, text)
        self._paint()
        return True

    def activate(self, role):
        if not self._open:
            return False
        if role == 'close':
            if self.close() and callable(self._on_close):
                self._on_close()
            return True
        if role == 'switch':
            self._page = 'daily' if self._page == 'reserves' else 'reserves'
            self._message = ''
            return self.refresh()
        if self._busy or self._page != 'reserves' or not role:
            return False
        if role[:3] not in ('buy', 'use') or role[-1:] not in '0123':
            return False
        key = policy.RESERVES[int(role[-1])][0]
        self._busy = True
        self._message = tr('Processing...')
        self.refresh()

        def done(success, error):
            self._busy = False
            self._message = tr('Completed.') if success else error
            self.refresh()

        try:
            request('buy_reserve' if role.startswith('buy') else 'activate_reserve',
                    key, done)
        except Exception:
            self._busy = False
            self._message = tr('The transaction could not be completed.')
            self.refresh()
            raise
        return True


def show_panel(view, page, on_close):
    panel = ServicePanel(page, on_close)
    view._offlineServicePanel = panel
    _panels.append(panel)
    if not panel.open():
        panel.uninstall()
        _panels.remove(panel)
        view._offlineServicePanel = None
        on_close()
        raise RuntimeError('the offline service panel could not open')


def close_panel(view):
    panel = getattr(view, '_offlineServicePanel', None)
    if panel is not None:
        panel.uninstall()
        if panel in _panels:
            _panels.remove(panel)
        view._offlineServicePanel = None


def offer_cards(data):
    from gui.Scaleform.genConsts.STORE_CONSTANTS import STORE_CONSTANTS
    owned = set(int(row.get('vehicleTypeCompactDescr', 0)) for row in
                data.get('vehicles', ()))
    cards = []
    for row in data.get('offlineVehicleOffers', ()):
        token = 'offline-bond:' + row['name']
        price = tr('%d bonds') % row['price']
        cards.append({
            'id': token, 'title': row['label'], 'header': price,
            'time': {'id': token, 'isTimeOver': False, 'timeLeft': '',
                     'isShowTimeIco': False},
            'isNew': False, 'discount': '', 'battleQuestsInfo': '',
            'picture': {'isWeb': False, 'src': '../maps/icons/vehicle/contour/%s.png' %
                        row['name'].replace(':', '-')},
            'tooltipInfo': row['label'], 'linkBtnLabel': None,
            'actionBtnLabel': tr('OWNED') if row['cd'] in owned else tr('BUY'),
            'triggerChainID': token,
            'storeItemDescr': {'descr': tr('Tier %d | %s') % (row['level'], price),
                              'tableOffers': [], 'ttcDataVO': None},
            'linkage': STORE_CONSTANTS.ACTION_CARD_NORMAL_LINKAGE})
    return {'title': '#menu:storeTab/actions',
            'cards': {'heroCard': None, 'columnLeft': cards[::2],
                      'columnRight': cards[1::2], 'comingSoon': None},
            'empty': {'info': '', 'btnLabel': ''}}


def _patch(owner, name, replacement):
    _patches.append((owner, name, getattr(owner, name)))
    setattr(owner, name, replacement)


def install():
    if _patches:
        return
    from gui.Scaleform.daapi.view.lobby.store.StoreActions import StoreActions
    from gui.Scaleform.daapi.view.lobby.boosters.BoostersWindow import BoostersWindow
    from gui.Scaleform.daapi.view.lobby.missions.regular.missions_page import MissionsPage
    from gui.Scaleform.daapi.view.lobby import PremiumWindow as premium
    from gui.Scaleform.daapi.view.common.settings import SettingsWindow as settings
    from account_helpers.settings_core.options import VOIPSupportSetting

    def update_offers(view):
        view.as_setDataS(offer_cards(snapshot()))

    original_action = StoreActions.actionSelect

    def select_offer(view, token):
        if not token.startswith('offline-bond:'):
            return original_action(view, token)
        if getattr(view, '_offlineBuying', False):
            return
        key = token[len('offline-bond:'):]
        row = next((item for item in snapshot().get('offlineVehicleOffers', ())
                    if item['name'] == key), None)
        if row is None:
            return
        from gui import DialogsInterface, SystemMessages
        from gui.Scaleform.daapi.view.dialogs import SimpleDialogMeta
        view._offlineBuying = True

        class Buttons(object):
            def getLabels(self):
                return [{'id': 'submit', 'label': tr('BUY'), 'focused': False},
                        {'id': 'close', 'label': tr('CANCEL'), 'focused': True}]

        def confirm(accepted):
            if not accepted:
                view._offlineBuying = False
                return

            def done(success, error):
                view._offlineBuying = False
                SystemMessages.pushMessage(tr('Completed.') if success else error)
                if view._isDAAPIInited():
                    update_offers(view)

            try:
                request('vehicle', key, done)
            except Exception:
                view._offlineBuying = False
                raise

        DialogsInterface.showDialog(SimpleDialogMeta(
            title=tr('BUY VEHICLE'),
            message=tr('Buy %s for %d bonds?') % (as_text(row['label']), row['price']),
            buttons=Buttons()), confirm)

    _patch(StoreActions, '_StoreActions__update', update_offers)
    _patch(StoreActions, 'actionSelect', select_offer)
    original_seen = StoreActions.onActionSeen

    def seen(view, token):
        if not token.startswith('offline-bond:'):
            return original_seen(view, token)

    _patch(StoreActions, 'onActionSeen', seen)
    original_init = BoostersWindow.__init__

    def boosters_init(view, ctx=None):
        original_init(view, ctx or {})

    def boosters_populate(view):
        super(BoostersWindow, view)._populate()
        show_panel(view, 'reserves', view.onWindowClose)

    def boosters_dispose(view):
        close_panel(view)
        super(BoostersWindow, view)._dispose()

    _patch(BoostersWindow, '__init__', boosters_init)
    _patch(BoostersWindow, '_populate', boosters_populate)
    _patch(BoostersWindow, '_dispose', boosters_dispose)
    # The backing Flash movie may request a tab while its offline surface is
    # opening. Its retail TabsContainer was deliberately never initialized.
    for name in ('requestBoostersArray', 'onBoosterActionBtnClick',
                 'onFiltersChange', 'onResetFilters'):
        _patch(BoostersWindow, name, lambda view, *args: None)
    original_missions_populate = MissionsPage._populate
    original_missions_dispose = MissionsPage._dispose

    def missions_populate(view):
        original_missions_populate(view)
        show_panel(view, 'daily', lambda: close_panel(view))

    def missions_dispose(view):
        close_panel(view)
        original_missions_dispose(view)

    _patch(MissionsPage, '_populate', missions_populate)
    _patch(MissionsPage, '_dispose', missions_dispose)
    original_duration = premium.PremiumWindow._PremiumWindow__getDurationStr

    def duration(view, period, cost, has_action, enough):
        if int(period) != 90:
            return original_duration(view, period, cost, has_action, enough)
        # #1513 has no days90 locale entry. Keep its native price template.
        price = '' if has_action else premium.makeHtmlString(
            'html_templates:lobby/dialogs/premium', 'gold' if enough else 'goldAlert',
            ctx={'value': premium.BigWorld.wg_getGoldFormat(cost)})
        return premium.makeHtmlString('html_templates:lobby/dialogs/premium',
                                      'duration', ctx={'duration': tr('90 days'),
                                                       'price': price})

    _patch(premium.PremiumWindow, '_PremiumWindow__getDurationStr', duration)
    original_tab = settings.SettingsWindow.onTabSelected

    def tab_selected(view, tab):
        if tab != settings.SETTINGS.SOUNDTITLE:
            return original_tab(view, tab)
        # Offline accounts have no authenticated Vivox domain. Never claim a
        # successful initialization or repeatedly ask an unavailable service.
        settings._setLastTabIndex(settings._PAGES_INDICES[tab])
        if not getattr(view, '_offlineVoiceNotice', False):
            from gui import SystemMessages
            SystemMessages.pushMessage(tr('Voice chat is unavailable in offline mode.'))
            view._offlineVoiceNotice = True

    _patch(settings.SettingsWindow, 'onTabSelected', tab_selected)
    _patch(VOIPSupportSetting, '_VOIPSupportSetting__isSupported', lambda unused: False)


def uninstall():
    for panel in list(_panels):
        panel.uninstall()
    _panels[:] = []
    for owner, name, original in reversed(_patches):
        setattr(owner, name, original)
    _patches[:] = []
