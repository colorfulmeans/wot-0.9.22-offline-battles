"""Unavailable native entries cannot re-enable themselves or dispatch actions."""
import sys
import types
import unittest
from unittest import mock
import test_port_0922_garage as fixture


class LockedEntryTests(unittest.TestCase):
    def test_entry_guards_survive_repopulation_and_restore_original_owners(self):
        ui = fixture._load_port_module('offline_services_ui')
        calls, counters = [], []

        class Header:
            TABS = types.SimpleNamespace(BROWSER='browser', ACADEMY='academy', STRONGHOLD='StrongholdView')
            def _isDAAPIInited(self): return True
            def as_setScreenS(self, alias):
                calls.append(('screen', alias))
                self.rows = [dict(value=value, enabled=True) for value in
                             ('hangar', 'missions', 'browser', 'academy', 'StrongholdView')]
            def _updateHangarMenuData(self):
                self.rows = self._getHangarMenuItemDataProvider()
            def _getHangarMenuItemDataProvider(self):
                return [dict(value=value, enabled=True) for value in ('hangar', 'missions', 'browser', 'academy', 'StrongholdView')]
            def _populate(self): calls.append('header')
            def as_doDisableHeaderButtonS(self, key, enabled): calls.append((key, enabled))
            def menuItemClick(self, key): calls.append(('click', key))
            def onPremShopClick(self): calls.append('shop')
            def onPayment(self): calls.append('payment')

        class Menu:
            def __init__(self):
                self.live = True
                self.flashObject = types.SimpleNamespace(logoffBtn=types.SimpleNamespace(enabled=True))
            def _populate(self): calls.append('menu')
            def _isDAAPIInited(self): return self.live
            def logoffClick(self): calls.append('logoff')

        original = Header.menuItemClick
        modules = {
            'gui.Scaleform.daapi.view.lobby.header.LobbyHeader': types.SimpleNamespace(LobbyHeader=Header),
            'gui.Scaleform.daapi.view.lobby.LobbyMenu': types.SimpleNamespace(LobbyMenu=Menu),
            'gui.Scaleform.daapi.view.common.settings.new_settings_counter': types.SimpleNamespace(
                invalidateSettings=lambda *args: counters.append(args))}
        with mock.patch.dict(sys.modules, modules):
            ui._install_unavailable_entries()
            try:
                header, menu = Header(), Menu()
                for unused in range(2):
                    header._populate()
                    header.as_setScreenS('prebattle' if unused else 'hangar')
                    self.assertFalse(next(row for row in header.rows if row['value'] == 'StrongholdView')['enabled'])
                    header.as_doDisableHeaderButtonS('premShop', True)
                    header.as_doDisableHeaderButtonS('gold', True)
                    header.as_doDisableHeaderButtonS('credits', True)
                    rows = {row['value']: row for row in header._getHangarMenuItemDataProvider()}
                    self.assertFalse(rows['browser']['enabled'])
                    self.assertFalse(rows['academy']['enabled'])
                    self.assertTrue(rows['missions']['enabled'])
                header.menuItemClick('browser'); header.menuItemClick('academy')
                header.menuItemClick('StrongholdView'); header.onPayment()
                header.menuItemClick('missions'); header.onPremShopClick()
                menu._populate(); menu.logoffClick()
                self.assertNotIn(('premShop', True), calls)
                self.assertIn(('gold', True), calls)
                self.assertIn(('credits', True), calls)
                self.assertNotIn('payment', calls)
                self.assertIn(('click', 'missions'), calls)
                self.assertNotIn('shop', calls); self.assertNotIn('logoff', calls)
                self.assertEqual([('GameSettings', None, 'gameplay_epicStandard')] * 2, counters)
            finally:
                ui.uninstall()
        self.assertIs(original, Header.menuItemClick)
