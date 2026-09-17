"""Paid services, reserve timing, daily rewards and native surface ownership."""

import copy
import json
import sys
import types
import unittest
from unittest import mock

import test_port_0922_garage as garage_fixture
import test_port_0922_waiting_room_ui as room_fixture


class OfflineServicesTests(unittest.TestCase):
    def setUp(self):
        self.requests, self.commands, self.garage = garage_fixture._request_modules()
        self.policy = garage_fixture._load_port_module('offline_services')
        # The policy imports this lazily; keep it on the same module graph as
        # the handlers when other suites have loaded independent fixtures.
        module_scope = mock.patch.dict(sys.modules, {
            'gui.mods.offline_lan_0922.account_rpc.garage': self.garage})
        module_scope.start()
        self.addCleanup(module_scope.stop)
        self.state = self.garage.GarageState({
            'wallet': {'gold': 1000, 'credits': 0, 'crystal': 0, 'freeXP': 0}})

    def test_reserve_purchase_activation_limit_and_expiry(self):
        for key, unused, percent, price in self.policy.RESERVES:
            self.policy.transact(self.state, 'buy_reserve', key, 100)
        self.assertEqual(700, self.state.snapshot()['wallet']['gold'])
        for key in ('xp', 'crew_xp', 'free_xp'):
            self.policy.transact(self.state, 'activate_reserve', key, 100)
        before = copy.deepcopy(self.state.snapshot())
        with self.assertRaises(self.garage.GarageError):
            self.policy.transact(self.state, 'activate_reserve', 'credits', 200)
        self.assertEqual(before, self.state.snapshot())
        self.policy.transact(self.state, 'activate_reserve', 'credits', 3700)
        self.assertEqual({'credits': [3700, 7300]},
                         self.policy.reserve_state(self.state.snapshot())['active'])

    def test_reserves_use_battle_start_and_base_earnings(self):
        self.policy.transact(self.state, 'buy_reserve', 'xp', 100)
        self.policy.transact(self.state, 'activate_reserve', 'xp', 100)
        data = self.state.snapshot()
        self.assertEqual(50, self.policy.reserve_bonuses(data, {'xp': 100}, 3699)['xp'])
        self.assertEqual(0, self.policy.reserve_bonuses(data, {'xp': 100}, 3700)['xp'])
        self.assertEqual(0, self.policy.reserve_bonuses(data, {'xp': 100}, 99)['xp'])
        self.policy.transact(self.state, 'buy_reserve', 'xp', 5000)
        self.policy.transact(self.state, 'activate_reserve', 'xp', 5000)
        restored = self.policy.saved_fields(data)
        self.assertEqual(50, self.policy.reserve_bonuses(restored, {'xp': 100}, 3699)['xp'])
        self.assertEqual(0, self.policy.reserve_bonuses(restored, {'xp': 100}, 4000)['xp'])

    def test_daily_rewards_once_each_and_no_rewind_on_late_receipt(self):
        data = self.state.snapshot()
        facts = {'damage': 1500, 'won': True}
        for unused in range(5):
            self.policy.advance_daily(data, facts, now=86401)
        self.assertEqual({'xp': 1, 'credits': 1, 'crew_xp': 1, 'free_xp': 0},
                         self.policy.reserve_state(data)['counts'])
        self.policy.advance_daily(data, facts, now=172801)
        before = copy.deepcopy(data)
        self.assertEqual([], self.policy.advance_daily(data, facts, now=86401))
        self.assertEqual(before, data)
        self.assertEqual(1, self.policy.daily_state(data, 172801)['battles'])

    def test_save_refusal_rolls_back_charge_and_owned_reserve(self):
        state = self.garage.GarageState(copy.deepcopy(garage_fixture.SNAPSHOT))
        before = copy.deepcopy(state.snapshot())
        store = mock.Mock()
        store.flush.return_value = False
        context = {'garage': state, 'garage_store': store}
        result = self.requests._offline_service(context, (json.dumps({
            'action': 'buy_reserve', 'key': 'xp'}),))
        self.assertEqual(self.commands.RES_FAILURE, result.result_id)
        self.assertEqual(before, state.snapshot())

    def test_offer_prices_and_entitlements_use_the_exact_retired_names(self):
        names = sorted(self.policy.BOND_OFFERS)
        types_by_name = dict((name, types.SimpleNamespace(
            id=(1, index), level=7 if 'Auf_Panther' in name else 10,
            userString=name)) for index, name in enumerate(names))
        vehicles = types.SimpleNamespace(
            VehicleDescr=lambda typeName: types.SimpleNamespace(type=types_by_name[typeName]),
            makeIntCompactDescrByID=lambda kind, nation, index: index + 100)
        data = {'notInShopItems': set(range(100, 100 + len(names)))}
        self.policy.publish_offers(data, vehicles)
        self.assertEqual(13, len(data['offlineVehicleOffers']))
        retired = dict((row['name'], row['price']) for row in data['offlineVehicleOffers']
                       if row['retired'])
        self.assertEqual({
            'germany:G85_Auf_Panther': 6000,
            'ussr:R75_SU122_54': 12000,
            'ussr:R96_Object_430B': 15000,
            'ussr:R93_Object263B': 15000,
            'germany:G98_Waffentrager_E100': 15000}, retired)
        for row in data['offlineVehicleOffers']:
            self.assertEqual({'crystal': row['price']}, data['shopItemPrices'][row['cd']])
            self.assertNotIn(row['cd'], data['notInShopItems'])

    def test_panel_close_and_escape_release_every_native_resource(self):
        ui = garage_fixture._load_port_module('offline_services_ui')
        closed = []
        surface = room_fixture._TransactionalSurface()
        # Native SimpleGUIComponent owns delChild as well as addChild.
        with mock.patch.object(room_fixture._Component, 'delChild',
                               lambda owner, child: owner.children.remove(child), create=True), \
                mock.patch.object(ui, 'snapshot', return_value=self.state.snapshot()), \
                mock.patch.dict(sys.modules, {'Keys': types.SimpleNamespace(KEY_ESCAPE=1)}):
            panel = ui.ServicePanel('reserves', lambda: closed.append(True), surface)
            self.assertTrue(panel.open())
            self.assertTrue(surface.cursor_owned)
            panel._panel.script.handleKeyEvent(types.SimpleNamespace(
                key=1, isKeyDown=lambda: True))
            self.assertEqual([True], closed)
            self.assertEqual([], surface.roots)
            self.assertFalse(surface.cursor_owned)
            self.assertFalse(surface.callbacks)
            self.assertTrue(panel.open())
            panel.activate('close')
            self.assertEqual([True, True], closed)
            self.assertFalse(surface.roots)

    def test_lobby_install_accepts_settings_package_class_export(self):
        ui = garage_fixture._load_port_module('offline_services_ui')
        called, notices, selected_tabs = [], [], []

        def native_tab(view, tab):
            called.append(tab)

        def noop(*args, **kwargs):
            return None

        store = type('StoreActions', (object,), dict(
            _StoreActions__update=noop, actionSelect=noop, onActionSeen=noop))
        boosters = type('BoostersWindow', (object,), dict(
            __init__=noop, _populate=noop, _dispose=noop,
            requestBoostersArray=noop, onBoosterActionBtnClick=noop,
            onFiltersChange=noop, onResetFilters=noop))
        missions = type('MissionsPage', (object,), dict(_populate=noop, _dispose=noop))
        premium = type('PremiumWindow', (object,), dict(_PremiumWindow__getDurationStr=noop))
        settings = type('SettingsWindow', (object,), dict(onTabSelected=native_tab))
        voip = type('VOIPSupportSetting', (object,), dict(_VOIPSupportSetting__isSupported=noop))
        exports = {
            'gui.Scaleform.daapi.view.lobby.store.StoreActions': {'StoreActions': store},
            'gui.Scaleform.daapi.view.lobby.boosters.BoostersWindow': {'BoostersWindow': boosters},
            'gui.Scaleform.daapi.view.lobby.missions.regular.missions_page': {'MissionsPage': missions},
            'gui.Scaleform.daapi.view.lobby.PremiumWindow': {'PremiumWindow': premium},
            # settings/__init__.py re-exports the class under the same name as
            # its module. Treating that package attribute as a module prevents
            # the visible client from reaching Account creation.
            'gui.Scaleform.daapi.view.common.settings': {'SettingsWindow': settings},
            'gui.Scaleform.daapi.view.common.settings.SettingsWindow': {
                'SettingsWindow': settings, '_setLastTabIndex': selected_tabs.append,
                '_PAGES_INDICES': {'sound': 2},
                'SETTINGS': types.SimpleNamespace(SOUNDTITLE='sound')},
            'account_helpers.settings_core.options': {'VOIPSupportSetting': voip},
            'gui': {'SystemMessages': types.SimpleNamespace(pushMessage=notices.append)},
        }
        modules = {}
        for name in exports:
            parts = name.split('.')
            for end in range(1, len(parts) + 1):
                full = '.'.join(parts[:end])
                if full not in modules:
                    modules[full] = types.ModuleType(full)
                    modules[full].__path__ = []
        for name, values in exports.items():
            modules[name].__dict__.update(values)
        with mock.patch.dict(sys.modules, modules), mock.patch.object(ui, 'tr', side_effect=lambda text: text):
            try:
                ui.install()
                view = settings()
                view.onTabSelected('graphics')
                view.onTabSelected('sound')
                view.onTabSelected('sound')
                self.assertEqual(['graphics'], called)
                self.assertEqual([2, 2], selected_tabs)
                self.assertEqual(['Voice chat is unavailable in offline mode.'], notices)
            finally:
                ui.uninstall()
        self.assertIs(native_tab, settings.onTabSelected)


if __name__ == '__main__':
    unittest.main()
