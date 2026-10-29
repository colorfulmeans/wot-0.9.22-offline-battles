"""Independent exterior copies move between free inventory and fitted outfits."""
import copy
import json
import types
import unittest
import test_port_0922_garage as fixture


class Outfit(object):
    def __init__(self, descriptor):
        data = json.loads(descriptor)
        self.styleId = data.get('styleId', 0)
        for name in ('paints', 'camouflages', 'decals'):
            setattr(self, name, [types.SimpleNamespace(**row) for row in data.get(name, [])])
        self.modifications = data.get('modifications', [])
        self.descriptor = descriptor

    def makeCompDescr(self):
        return self.descriptor


def descr(**parts):
    return json.dumps(parts)


def component(identifier, areas):
    return dict(id=identifier, appliedTo=areas)


class OutfitStockTests(unittest.TestCase):
    def setUp(self):
        unused, unused, self.garage = fixture._request_modules()
        vehicles, tankmen = fixture._modules()
        shared = types.SimpleNamespace(isVehicleBound=False)
        bound = types.SimpleNamespace(isVehicleBound=True)
        self.cache = types.SimpleNamespace(paints={137:shared}, camouflages={15125:bound},
            decals={137:shared}, modifications={1:shared}, styles={})
        vehicles.g_cache = types.SimpleNamespace(customization20=lambda:self.cache)
        self.state = self.garage.GarageState(fixture.SNAPSHOT, vehicles_module=vehicles,
            tankmen_module=tankmen, customizations_module=types.SimpleNamespace(parseOutfitDescr=Outfit))
        self.stock = {1:{137:{0:7}}, 2:{15125:{50001:3,50002:9}}, 3:{137:{0:4}}, 5:{1:{0:3}}}
        self.state.snapshot()['customizationItems'] = copy.deepcopy(self.stock)
        self.state.snapshot()['vehicles'][0]['outfits'] = {}

    def inventory(self):
        return self.state.snapshot()['customizationItems']

    def test_three_seasons_consume_exact_units_reapply_is_idempotent_and_remove_returns(self):
        paint = descr(paints=[component(137, 2)])
        for season in (1,2,4):self.state.apply_outfit(9,season,paint)
        self.assertEqual(4,self.inventory()[1][137][0])
        self.state.apply_outfit(9,2,paint)
        self.assertEqual(4,self.inventory()[1][137][0])
        for season in (1,2,4):self.state.apply_outfit(9,season,descr())
        self.assertEqual(self.stock,self.inventory())

    def test_area_masks_and_typed_ids_preserve_bindings_and_wear_is_an_integer_id(self):
        outfit = descr(paints=[component(137,3)], camouflages=[component(15125,7)],
            decals=[component(137,5)], modifications=[1])
        self.state.apply_outfit(9,1,outfit)
        self.assertEqual({0:5},self.inventory()[1][137])
        self.assertEqual({50001:0,50002:9},self.inventory()[2][15125])
        self.assertEqual({0:2},self.inventory()[3][137])
        self.assertEqual({0:2},self.inventory()[5][1])
        self.state.apply_outfit(9,1,descr())
        self.assertEqual(self.stock,self.inventory())

    def test_insufficient_last_item_cannot_partially_consume_an_earlier_item_or_outfit(self):
        before = copy.deepcopy(self.state.snapshot())
        with self.assertRaisesRegex(self.garage.GarageError,'not enough customization'):
            self.state.apply_outfit(9,1,descr(paints=[component(137,1)],camouflages=[component(15125,15)]))
        self.assertEqual(before,self.state.snapshot())
        self.assertEqual(0,self.state.revision)

    def test_unchanged_installed_old_save_does_not_receive_a_stock_migration(self):
        paint = descr(paints=[component(137,2)])
        self.state.snapshot()['vehicles'][0]['outfits'] = {1:(paint,True)}
        self.state.apply_outfit(9,1,paint)
        self.assertEqual(self.stock,self.inventory())

    def test_replacing_custom_outfits_with_preset_returns_components_without_spending_style(self):
        self.state.apply_outfit(9,1,descr(paints=[component(137,3)]))
        style = types.SimpleNamespace(compactDescr=12007,isRent=False,rentCount=1)
        self.cache.styles[7] = style
        self.state._customizations.CustomizationOutfit = lambda styleId:Outfit(descr(styleId=styleId))
        self.state._customizations.parseIntCompactDescr = lambda cd:(12,4,7)
        self.inventory()[4] = {7:{0:1}}
        self.state.apply_style(9,7)
        self.assertEqual(7,self.inventory()[1][137][0])
        self.assertEqual({0:1},self.inventory()[4][7])


if __name__ == '__main__':unittest.main()
