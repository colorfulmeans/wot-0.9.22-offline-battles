"""Preview combinations follow the pinned client's compatibility and ordering."""
import os
import unittest
from test_vehicle_armor_viewer import packed_element, element_value, string_value
import vehicle_armor_viewer as v


class MountTests(unittest.TestCase):
    def setUp(self):
        self.choices = dict(turrets=(dict(key=('turrets0','top'), guns=('large','small')),
                                    dict(key=('turrets0','stock'), guns=('small','old'))),
                            guns=tuple(dict(name=n) for n in ('large','small','old')))

    def test_default_is_first_native_order_not_xml_or_random(self):
        self.assertEqual(dict(turret=('turrets0','top'),gun='large'),v.resolve_mount(self.choices))

    def test_new_turret_wins_and_invalid_gun_uses_first_compatible(self):
        result=v.resolve_mount(self.choices,dict(turret=('turrets0','top'),gun='large'),
                               'turret',('turrets0','stock'))
        self.assertEqual(dict(turret=('turrets0','stock'),gun='small'),result)

    def test_new_gun_wins_and_selects_first_compatible_turret(self):
        result=v.resolve_mount(self.choices,dict(turret=('turrets0','top'),gun='large'),'gun','old')
        self.assertEqual(dict(turret=('turrets0','stock'),gun='old'),result)

    def test_compatible_partner_is_preserved_even_if_not_first(self):
        result=v.resolve_mount(self.choices,dict(turret=('turrets0','stock'),gun='small'),
                               'turret',('turrets0','top'))
        self.assertEqual('small',result['gun'])
        result=v.resolve_mount(self.choices,dict(turret=('turrets0','stock'),gun='old'),'gun','small')
        self.assertEqual(('turrets0','stock'),result['turret'])

    def test_impossible_choice_is_contained(self):
        with self.assertRaises(v.ArmorViewerError):v.resolve_mount(self.choices,role='gun',value='absent')

    def test_display_sort_matches_reverse_level_price_localized_name(self):
        def turret(level,price):
            return element_value([('level',string_value(str(level))),('price',string_value(str(price))),
                                  ('guns',element_value([('small',element_value([]))]))])
        root=packed_element([('turrets0',element_value([
            ('cheap',turret(6,1)),('expensive',turret(6,2)),('top',turret(7,1))]))])
        choices=v.component_choices(root,{})
        self.assertEqual(['top','expensive','cheap'],[r['name'] for r in choices['turrets']])


@unittest.skipUnless(os.environ.get('WOT_0922_CLIENT'), 'requires exact #1513 resources')
class StockMountTests(unittest.TestCase):
    def test_t29_keeps_real_compatible_105mm_on_both_turrets(self):
        game=os.environ['WOT_0922_CLIENT']
        member='scripts/item_defs/vehicles/usa/A11_T29.xml'
        scene=v.load_vehicle_armor_scene(game,member,[],mounted={})
        choices=scene['componentChoices']
        self.assertEqual(['T136','T123'],[r['name'] for r in choices['turrets']])
        self.assertEqual('_105mm_Gun_T5E1',choices['guns'][0]['name'])
        mounts=[]
        for row in choices['turrets']:
            mount=v.resolve_mount(choices,role='turret',value=row['key'])
            selected=v.load_vehicle_armor_scene(game,member,[],mounted=mount)
            self.assertEqual(row['name'],selected['configuration']['turret'])
            self.assertEqual('_105mm_Gun_T5E1',selected['configuration']['gun'])
            mounts.append(next(p for p in selected['parts'] if p['role']=='turret'))
        self.assertNotEqual(mounts[0]['surfaces'],mounts[1]['surfaces'])


if __name__=='__main__':unittest.main()
