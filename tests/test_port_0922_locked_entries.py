"""Unavailable native entries cannot re-enable themselves or dispatch actions."""
import sys
import types
import unittest
from unittest import mock
import test_port_0922_garage as fixture


class LockedEntryTests(unittest.TestCase):
    def test_entry_guards_survive_repopulation_and_restore_original_owners(self):
        ui = fixture._load_port_module('offline_services_ui')
        calls, callbacks, counters = [], [], []

        class Header:
            def _getHangarMenuItemDataProvider(self):
                return [dict(value=value, enabled=True) for value in ('hangar', 'missions', 'browser', 'academy')]
            def _populate(self): calls.append('header')
            def as_doDisableHeaderButtonS(self, key, enabled): calls.append((key, enabled))
            def menuItemClick(self, key): calls.append(('click', key))
            def onPremShopClick(self): calls.append('shop')

        class Menu:
            def __init__(self):
                self.live = True
                self.flashObject = types.SimpleNamespace(logoffBtn=types.SimpleNamespace(enabled=True))
            def _populate(self): calls.append('menu')
            def _isDAAPIInited(self): return self.live
            def logoffClick(self): calls.append('logoff')

        original = Header.menuItemClick
        modules = {
            'BigWorld': types.SimpleNamespace(callback=lambda delay, callback: callbacks.append(callback)),
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
                    header.as_doDisableHeaderButtonS('premShop', True)
                    header.as_doDisableHeaderButtonS('gold', True)
                    rows = {row['value']: row for row in header._getHangarMenuItemDataProvider()}
                    self.assertFalse(rows['browser']['enabled'])
                    self.assertFalse(rows['academy']['enabled'])
                    self.assertTrue(rows['missions']['enabled'])
                header.menuItemClick('browser'); header.menuItemClick('academy')
                header.menuItemClick('missions'); header.onPremShopClick()
                menu._populate(); callbacks.pop()(); menu.logoffClick()
                self.assertFalse(menu.flashObject.logoffBtn.enabled)
                menu._populate(); menu.live = False; menu.flashObject = None
                callbacks.pop()()  # A retired view cannot receive a stale UI write.
                self.assertNotIn(('premShop', True), calls)
                self.assertIn(('gold', True), calls)
                self.assertIn(('click', 'missions'), calls)
                self.assertNotIn('shop', calls); self.assertNotIn('logoff', calls)
                self.assertEqual([('GameSettings', None, 'gameplay_epicStandard')] * 2, counters)
            finally:
                ui.uninstall()
        self.assertIs(original, Header.menuItemClick)
