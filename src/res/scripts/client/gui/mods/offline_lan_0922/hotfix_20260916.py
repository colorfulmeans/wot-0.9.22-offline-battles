from __future__ import print_function

"""Focused compatibility fixes found by the 2026-09-16 live test.

Keep these adapters small and removable.  They repair server-owned values that
#1513 expects the account to publish, without changing the historical client
resources themselves.
"""

_installed = False


def _install_shop_prices():
    from gui.mods.offline_lan_0922.account_rpc import data
    from gui.mods.offline_lan_0922.account_rpc import economy

    original = data.shop
    if getattr(original, '_offline_0922_20260916', False):
        return

    def shop(revision=0, selected_vehicle=None):
        result = original(revision, selected_vehicle)
        # #1513's Shop expects prices as (credits, gold) Money tuples.  The
        # previous offline stream used scalar zeroes, so both dialogs showed
        # a free operation even though GarageState already charged 300 gold.
        result['slotsPrices'] = (0, [(0, 300)])
        result['berthsPrices'] = (0, 16, [(0, 300)])

        # These are the exact ShopCommonStats fallbacks shipped by the pinned
        # client.  Publishing them explicitly also keeps the role-change
        # window and the command-side wallet check on one price.
        result['changeRoleCost'] = int(economy.CHANGE_ROLE_COST['gold'])
        result['passportChangeCost'] = int(
            economy.PASSPORT_CHANGE_COST['gold'])
        result['femalePassportChangeCost'] = int(
            economy.FEMALE_PASSPORT_CHANGE_COST['gold'])
        return result

    shop._offline_0922_20260916 = True
    data.shop = shop


def _install_crew_cost_fallbacks():
    from gui.mods.offline_lan_0922.account_rpc import economy
    from gui.mods.offline_lan_0922.account_rpc import garage

    original = garage.GarageState._crew_cost
    if getattr(original, '_offline_0922_20260916', False):
        return

    defaults = {
        'crewChangeRoleCost': economy.CHANGE_ROLE_COST,
        'crewPassportCost': economy.PASSPORT_CHANGE_COST,
        'crewFemalePassportCost': economy.FEMALE_PASSPORT_CHANGE_COST,
    }

    def crew_cost(self, key):
        cost = self._snapshot.get(key)
        if isinstance(cost, dict):
            return dict((str(currency), int(amount))
                        for currency, amount in cost.items())
        fallback = defaults.get(key)
        if fallback is None:
            return original(self, key)
        return dict((str(currency), int(amount))
                    for currency, amount in fallback.items())

    crew_cost._offline_0922_20260916 = True
    garage.GarageState._crew_cost = crew_cost


def install():
    global _installed
    if _installed:
        return
    _install_shop_prices()
    _install_crew_cost_fallbacks()
    _installed = True
