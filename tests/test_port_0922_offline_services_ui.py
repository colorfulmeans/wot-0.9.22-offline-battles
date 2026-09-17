"""Native service controller contracts and transaction-facing UI regressions."""

import contextlib
import copy
import sys
import types
import unittest
from collections import namedtuple
from unittest import mock

import test_port_0922_garage as fixture


@contextlib.contextmanager
def native_modules(exports):
    modules = {}
    for name in exports:
        bits = name.split('.')
        for end in range(1, len(bits) + 1):
            path = '.'.join(bits[:end])
            if path not in modules:
                module = types.ModuleType(path)
                module.__path__ = []
                modules[path] = module
    for name, values in exports.items():
        modules[name].__dict__.update(values)
    for name, module in modules.items():
        if '.' in name:
            parent, child = name.rsplit('.', 1)
            if child not in modules[parent].__dict__:
                setattr(modules[parent], child, module)
    with mock.patch.dict(sys.modules, modules):
        yield modules


class NativeServiceUITests(unittest.TestCase):
    def setUp(self):
        self.ui = fixture._load_port_module('offline_services_ui')
        self.data = {'vehicles': [{'vehicleTypeCompactDescr': 2}],
                     'offlineVehicleOffers': [
                         {'cd': 2, 'name': 'owned', 'price': 8000, 'label': 'Owned'},
                         {'cd': 3, 'name': 'new', 'price': 8000, 'label': 'New'}]}
        patch = mock.patch.object(self.ui, 'snapshot', side_effect=lambda: self.data)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.ui.uninstall)

    def test_shop_reuses_native_rows_and_groups_owned_vehicles_last(self):
        class Shop(object):
            def __init__(self):
                pass

            def requestTableData(self, *args):
                return args

        class VehicleTab(object):
            def itemWrapper(self, row):
                return {'type': row[0].icon, 'disabled': False,
                        'price': (0, 0, 8000), 'currency': 'crystal'}

        class StoreView(object):
            def as_initS(self, data):
                self.data = data

        Settings = namedtuple('Settings', 'alias clazz')
        Settings.replaceSettings = lambda self, values: self._replace(**values)
        original = Settings('storeActions', object)
        current = {'storeActions': original}

        def add(settings):
            if settings.alias in current:
                raise ValueError('duplicate alias')
            current[settings.alias] = settings

        factory = types.SimpleNamespace(getSettings=current.get,
                                        removeSettings=current.pop, addSettings=add)
        account_settings = mock.Mock()
        account_settings.getFilter.return_value = (-1, 'vehicle', False)
        account_settings.getFilterDefault.return_value = {}
        defaults = {'filters': {}}
        exports = {
            'account_helpers.AccountSettings': {'AccountSettings': account_settings,
                'DEFAULT_VALUES': defaults, 'KEY_FILTERS': 'filters'},
            'gui.Scaleform.daapi.settings.views': {'VIEW_ALIAS': types.SimpleNamespace(LOBBY_STORE_ACTIONS='storeActions')},
            'gui.Scaleform.daapi.view.lobby.store.StoreView': {'StoreView': StoreView},
            'gui.Scaleform.daapi.view.lobby.store.Shop': {'Shop': Shop},
            'gui.Scaleform.daapi.view.lobby.store.tabs.shop': {'ShopVehicleTab': VehicleTab},
            'gui.Scaleform.genConsts.STORE_CONSTANTS': {'STORE_CONSTANTS': types.SimpleNamespace(
                STORE_ACTIONS='storeActions', SHOP_LINKAGE='ShopUI', VEHICLE='vehicle')},
            'gui.shared.gui_items.Vehicle': {'VEHICLE_TYPES_ORDER': ['lightTank', 'heavyTank']},
            'gui.Scaleform.framework': {'g_entitiesFactories': factory},
            'gui.shared.utils': {'flashObject2Dict': dict},
            'gui.Scaleform.Waiting': {'Waiting': mock.Mock()},
        }
        with native_modules(exports):
            self.ui._install_shop()
            page = StoreView()
            tabs = {'buttonBarData': [
                {'id': 'storeActions', 'linkage': 'StoreActionsViewUI'},
                {'id': 'shop', 'linkage': 'ShopUI'}]}
            page.as_initS(tabs)
            self.assertEqual('ShopUI', page.data['buttonBarData'][0]['linkage'])
            self.assertEqual('StoreActionsViewUI', tabs['buttonBarData'][0]['linkage'])
            shop = current['storeActions'].clazz()
            self.assertEqual('offline_bond', shop.getName())
            self.assertFalse(account_settings.setFilter.called)
            tab = shop._getTabClass('vehicle')()
            tab._nation = None
            tab._filterData = {'selectedTypes': [False, False],
                               'selectedLevels': [False] * 10}
            items = {cd: types.SimpleNamespace(intCD=cd, nationID=0,
                     level=8, type='heavyTank', icon='garage-art-%d' % cd)
                     for cd in (2, 3)}
            tab._items = types.SimpleNamespace(getItemByCD=items.get)
            rows = tab.buildItems([])
            self.assertEqual([3, 2], [row[0].intCD for row in rows])
            self.assertEqual('garage-art-3', tab.itemWrapper(rows[0])['type'])
            self.assertEqual('crystal', tab.itemWrapper(rows[0])['currency'])
            self.assertTrue(tab.itemWrapper(rows[1])['disabled'])
            with mock.patch.object(self.ui, 'request') as request:
                self.assertFalse(shop.buyItem('2'))
                request.assert_not_called()
            self.ui.uninstall()
            self.assertIs(original, current['storeActions'])
            self.assertFalse(defaults['filters'])

    def test_purchase_confirmation_rechecks_ownership_before_sending(self):
        dialogs = []
        exports = {
            'gui': {'DialogsInterface': types.SimpleNamespace(
                showDialog=lambda meta, callback: dialogs.append(callback))},
            'gui.Scaleform.daapi.view.dialogs': {'SimpleDialogMeta': lambda **kw: kw},
        }
        with native_modules(exports), mock.patch.object(self.ui, 'request') as request:
            view = types.SimpleNamespace()
            self.assertTrue(self.ui._buy_vehicle(view, 3))
            self.data['vehicles'].append({'vehicleTypeCompactDescr': 3})
            dialogs[0](True)
            request.assert_not_called()
            self.assertFalse(view._offlineBuying)

    def test_boosters_keep_native_lifecycle_filters_and_route_paid_actions(self):
        class Boosters(object):
            def __init__(self, ctx):
                self.tab = 2
                self.ctx = ctx.get('tabID')
                self._BoostersWindow__tabsContainer = types.SimpleNamespace(
                    currentTab=types.SimpleNamespace(getID=lambda: self.tab))

            def _populate(self):
                self.native_populated = True

            def _dispose(self):
                self.native_disposed = True

            def onBoosterActionBtnClick(self, *args):
                raise AssertionError('online purchase')

            def _isDAAPIInited(self):
                return True

            def _BoostersWindow__update(self):
                self.updated = True

        class Quests(object):
            def _processBoostersData(self):
                raise AssertionError('online quests')

        class Controller(object):
            def _BoostersController__notifyBoosterTime(self):
                pass

        exports = {
            'gui.Scaleform.daapi.view.lobby.boosters.BoostersWindow': {'BoostersWindow': Boosters},
            'gui.Scaleform.daapi.view.lobby.boosters.booster_tabs': {
                'QuestsBoostersTab': Quests, 'TABS_IDS': types.SimpleNamespace(QUESTS=1, SHOP=2)},
            'gui.game_control.BoostersController': {'BoostersController': Controller},
        }
        native_populate, native_dispose = Boosters._populate, Boosters._dispose
        with native_modules(exports), mock.patch.object(self.ui, 'request') as request:
            self.ui._install_reserves()
            self.assertIs(native_populate, Boosters._populate)
            self.assertIs(native_dispose, Boosters._dispose)
            window = Boosters(None)
            window._populate()
            uid = self.ui.policy.RESERVE_IDS['xp']
            window.onBoosterActionBtnClick(uid, None)
            window.onBoosterActionBtnClick(uid, None)
            self.assertEqual(1, request.call_count)
            self.assertEqual(('buy_reserve', 'xp'), request.call_args.args[:2])
            request.call_args.args[2](True, '')
            window.tab = 0
            window.onBoosterActionBtnClick(uid, None)
            self.assertEqual(('activate_reserve', 'xp'), request.call_args.args[:2])
            window._dispose()
            self.assertTrue(window.native_disposed)
            self.ui.uninstall()

    def test_account_popover_preserves_hide_event_and_badge_selection_is_deferred(self):
        events = []

        class Base(object):
            def __init__(self, ctx=None):
                self.live = False

            def _populate(self):
                self.live = True  # AbstractPopOverView's HIDE_POPOVER listener.

            def _dispose(self):
                self.live = False
                events.append('popover_destroyed')

            def destroy(self):
                self._dispose()

            def fireEvent(self, event, scope):
                events.append(event)

        class Popover(Base):
            def __init__(self, ctx):
                raise AssertionError('online clan/tutorial constructor')

            def _populate(self):
                raise AssertionError('online clan setup')

            def _dispose(self):
                raise AssertionError('unregistered clan callbacks')

            def _AccountPopover__syncUserInfo(self):
                pass

            def openBoostersWindow(self, idx):
                pass

            def openBadgesWindow(self):
                pass

            def as_setDataS(self, data):
                self.data = data

            def as_setClanDataS(self, data):
                self.clan = data

        class Badges(object):
            def _BadgesPage__updateBadges(self):
                pass

            def onSelectBadge(self, badge):
                pass

            def onDeselectBadge(self):
                pass

            def _isDAAPIInited(self):
                return True

            def as_setReceivedBadgesS(self, data):
                self.rows = data

            def as_setNotReceivedBadgesS(self, data):
                pass

            def as_setSelectedBadgeImgS(self, image):
                self.selected = image

        exports = {
            'BigWorld': {'player': lambda: types.SimpleNamespace(name='offline')},
            'gui.Scaleform.daapi.view.lobby.header.AccountPopover': {'AccountPopover': Popover},
            'gui.Scaleform.daapi.view.lobby.BadgesPage': {
                'BadgesPage': Badges, '_makeBadgeVO': lambda badge: {'id': badge.badgeID}},
            'gui.Scaleform.settings': {'getBadgeIconPath': lambda size, uid: '%d/%d' % (size, uid),
                                      'BADGES_ICONS': types.SimpleNamespace(X48=48)},
            'gui.Scaleform.locale.RES_ICONS': {'RES_ICONS': types.SimpleNamespace(
                MAPS_ICONS_LIBRARY_BADGES_48X48_BADGE_DEFAULT='default')},
            'gui.Scaleform.daapi.settings.views': {'VIEW_ALIAS': types.SimpleNamespace(
                BOOSTERS_WINDOW='reserves', BADGES_PAGE='badges')},
            'gui.shared': {'events': types.SimpleNamespace(LoadViewEvent=lambda alias, ctx: alias),
                           'EVENT_BUS_SCOPE': types.SimpleNamespace(LOBBY='lobby')},
        }
        with native_modules(exports), mock.patch.object(self.ui, 'request') as request:
            self.ui._install_account()
            self.data['selectedBadges'] = [17]
            popover = Popover(None)
            popover._populate()
            self.assertTrue(popover.live)
            self.assertEqual('48/17', popover.data['badgeIcon'])
            popover.openBadgesWindow()
            self.assertFalse(popover.live)
            self.assertEqual(['popover_destroyed', 'badges'], events)
            page = Badges()
            page.itemsCache = types.SimpleNamespace(items=types.SimpleNamespace(
                getBadges=lambda: {17: types.SimpleNamespace(badgeID=17, getWeight=lambda: 1)}))
            page.selected = 'unchanged'
            page.onDeselectBadge()
            self.assertEqual('unchanged', page.selected)
            self.data['selectedBadges'] = []
            request.call_args.args[2](True, '')
            self.assertEqual('', page.selected)
            self.assertTrue(page.rows['badgesData'][0]['enabled'])
            self.ui.uninstall()

    def test_daily_page_does_not_populate_retail_empty_tabs_or_arrows(self):
        calls = []

        class Base(object):
            def _populate(self):
                calls.append('base_populate')

            def _dispose(self):
                calls.append('base_dispose')

        class Page(Base):
            def _populate(self):
                raise AssertionError('would create empty retail tabs')

            def _dispose(self):
                raise AssertionError('would remove unsubscribed builders')

            def _invalidate(self, ctx=None):
                raise AssertionError('would restore empty retail tabs')

            def onClose(self):
                calls.append('hangar')

            def as_setTabsDataProviderS(self, tabs):
                self.tabs = tabs

            def as_showFilterS(self, visible):
                self.filter = visible

        panel = mock.Mock()
        panel.open.return_value = True
        exports = {'gui.Scaleform.daapi.view.lobby.missions.regular.missions_page': {'MissionsPage': Page}}
        with native_modules(exports), mock.patch.object(self.ui, 'ServicePanel', return_value=panel):
            self.ui._install_daily()
            page = Page()
            page._populate()
            self.assertEqual([], page.tabs)
            self.assertFalse(page.filter)
            page._invalidate()
            panel.refresh.assert_called_once()
            page._dispose()
            panel.uninstall.assert_called_once()
            self.assertFalse(self.ui._panels)
            self.ui.uninstall()
        self.assertEqual(['base_populate', 'base_dispose'], calls)

    def test_purchase_notification_and_callback_follow_account_acknowledgement(self):
        callbacks, notices, finished = [], [], []
        account = types.SimpleNamespace(_doCmdStr=lambda cmd, payload, callback: callbacks.append(callback))
        exports = {
            'BigWorld': {'player': lambda: account},
            'gui': {'SystemMessages': types.SimpleNamespace(
                pushMessage=lambda text, **kwargs: notices.append((text, kwargs['type'])),
                SM_TYPE=types.SimpleNamespace(Error='error', PurchaseForGold='gold',
                    Information='info', PurchaseForCrystal='crystal'))},
            'gui.mods.offline_lan_0922.account_rpc.commands': {'CMD_OFFLINE_SERVICE': 19900},
        }
        with native_modules(exports), mock.patch.object(self.ui, 'tr', side_effect=lambda x: x):
            self.ui.request('buy_reserve', 'xp', lambda *result: finished.append(result))
            self.assertFalse(notices)
            callbacks[0](1, 0, '')
            self.assertIn('Spent 50 gold', notices[0][0])
            self.assertEqual('gold', notices[0][1])
            self.assertEqual([(True, '')], finished)
            self.ui.request('buy_reserve', 'xp', lambda *result: finished.append(result))
            callbacks[1](2, -1, 'The transaction could not be saved.')
            self.assertEqual('error', notices[-1][1])
            self.assertFalse(finished[-1][0])


class MissionResultUITests(unittest.TestCase):
    def setUp(self):
        self.ui = fixture._load_port_module('offline_services_ui')
        self.addCleanup(self.ui.uninstall)

    def test_midnight_refresh_waits_for_lobby_then_replaces_account_stats(self):
        callbacks = []
        server = types.SimpleNamespace(publish_postbattle_progress=mock.Mock())
        lobby = [False]
        exports = {
            'BigWorld': {
                'callback': lambda delay, callback: callbacks.append((delay, callback)) or len(callbacks),
                'player': lambda: types.SimpleNamespace(fakeServer=server),
                'cancelCallback': lambda unused: None},
            'helpers': {'isPlayerAccount': lambda: lobby[0]},
        }
        with native_modules(exports), mock.patch.object(self.ui.time, 'time', return_value=172799):
            self.ui._schedule_daily_rollover()
            self.assertAlmostEqual(1.1, callbacks[0][0])
            callbacks.pop(0)[1]()
            server.publish_postbattle_progress.assert_not_called()
            self.assertEqual(5.0, callbacks[0][0])
            lobby[0] = True
            callbacks.pop(0)[1]()
            server.publish_postbattle_progress.assert_called_once_with()
            self.assertEqual(1, len(callbacks))
            self.ui.uninstall()

    def test_completed_daily_rows_use_native_results_and_open_daily_page(self):
        stock, opened = [], []
        class Block(object):
            def setRecord(self, result, reusable):
                stock.append(result)
            def getNextComponentIndex(self):
                return len(self.rows)
            def addComponent(self, index, value):
                self.rows.append(value)
        class Window(object):
            def showEventsWindow(self, key, kind):
                opened.append(key)
            def destroy(self):
                opened.append('closed')
        exports = {
            'constants': {'EVENT_TYPE': types.SimpleNamespace(BATTLE_QUEST=2)},
            'gui.battle_results.components.progress': {'QuestsProgressBlock': Block},
            'gui.battle_results.components.base': {'DirectStatsItem': lambda unused, info: info},
            'gui.server_events.formatters': {'PROGRESS_BAR_TYPE': types.SimpleNamespace(SIMPLE=1)},
            'gui.Scaleform.genConsts.MISSIONS_STATES': {'MISSIONS_STATES': types.SimpleNamespace(COMPLETED='done')},
            'gui.Scaleform.genConsts.QUESTS_ALIASES': {'QUESTS_ALIASES': types.SimpleNamespace(RENDERER_TYPE_QUEST='quest')},
            'gui.Scaleform.daapi.view.battle_results_window': {'BattleResultsWindow': Window},
            'gui.server_events.events_dispatcher': {'showMissions': lambda: opened.append('daily')},
        }
        with native_modules(exports):
            self.ui._install_mission_results()
            block = Block()
            block.rows = []
            block.setRecord('receipt', types.SimpleNamespace(personal=types.SimpleNamespace(
                getQuestsProgress=lambda: {'offline_daily_wins': (), 'retail': ()})))
            self.assertEqual(['receipt'], stock)
            self.assertEqual(1, len(block.rows))
            self.assertEqual('done', block.rows[0]['questInfo']['status'])
            Window().showEventsWindow('offline_daily_wins', 2)
            self.assertEqual(['daily', 'closed'], opened)

    def test_one_native_popup_combines_simultaneous_rewards(self):
        messages, dialogs = [], []
        exports = {
            'gui.SystemMessages': {'pushMessage': lambda message, **kw: messages.append(message),
                'SM_TYPE': types.SimpleNamespace(Information=1)},
            'gui.DialogsInterface': {'showDialog': lambda meta, callback: dialogs.append(meta)},
            'gui.Scaleform.daapi.view.dialogs': {
                'SimpleDialogMeta': lambda *args: args, 'InfoDialogButtons': lambda label: label},
        }
        with native_modules(exports):
            self.ui.notify_missions(['damage', 'wins'])
        self.assertEqual(1, len(messages))
        self.assertEqual(1, len(dialogs))
        self.assertIn('\n', messages[0])


if __name__ == '__main__':
    unittest.main()
