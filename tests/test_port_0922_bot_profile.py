"""Tactical profiles and route catalogs come from #1513 data, not a local planner."""
import json
import unittest
from pathlib import Path

from gui.mods.offline_lan_0922 import bot_profile, bot_tactics, bot_tactics_runtime


ROOT = Path(__file__).resolve().parents[1]


class _Strict(object):
    """Expose attributes while rejecting mapping-style access, like #1513."""

    def __init__(self, **values):
        self.__dict__.update(values)

    def _forbidden(self, *unused_args, **unused_kwargs):
        raise AssertionError('mapping access on a native component')

    get = __getitem__ = __contains__ = keys = items = _forbidden


def _descriptor(tag, speed=12.0, hull=0.0, turret=0.0, shots=(), clip=(1, 0.0)):
    return _Strict(
        type=_Strict(name='nation:Vehicle', tags=frozenset((tag,))),
        physics={'speedLimits': (speed, 6.0)},
        hull=_Strict(primaryArmor=hull), turret=_Strict(primaryArmor=turret),
        gun=_Strict(name='Gun', clip=clip, shots=shots))


class VehicleProfileTests(unittest.TestCase):
    def test_reads_native_components_as_attributes(self):
        shots = (
            _Strict(speed=900.0, shell=_Strict(kind='ARMOR_PIERCING', name='AP',
                    piercingPower=(150.0, 170.0), damage=(300.0, 340.0))),
            _Strict(speed=640.0, shell=_Strict(kind='HIGH_EXPLOSIVE', name='HE',
                    piercingPower=(42.0, 58.0), damage=(410.0, 450.0))),
        )
        profile = bot_profile.vehicle_profile(_descriptor(
            'heavyTank', speed=18.0, hull=(110.0, 135.0, 95.0), turret=180.0,
            shots=shots, clip=(3, 2.5)))
        self.assertEqual('heavyTank', profile['class_tag'])
        self.assertEqual('nation:Vehicle', profile['vehicle_name'])
        self.assertEqual(18.0, profile['speed'])
        self.assertEqual(180.0, profile['armor'])
        self.assertEqual(3, profile['clip_size'])
        self.assertEqual('Gun', profile['gun_name'])
        self.assertEqual((
            {'index': 0, 'kind': 'ARMOR_PIERCING', 'name': 'AP',
             'penetration': 160.0, 'damage': 320.0, 'speed': 900.0},
            {'index': 1, 'kind': 'HIGH_EXPLOSIVE', 'name': 'HE',
             'penetration': 50.0, 'damage': 430.0, 'speed': 640.0},
        ), profile['shells'])

    def test_each_class_has_its_role_scores_and_engagement_ranges(self):
        for tag, ranges in bot_profile.ENGAGEMENT_RANGES.items():
            with self.subTest(tag=tag):
                profile = bot_profile.vehicle_profile(_descriptor(tag))
                self.assertEqual(tag, profile['class_tag'])
                self.assertEqual(ranges, (profile['desired_range'], profile['fire_range']))
                self.assertEqual(bot_profile.ROLE_SCORES[tag], profile['roles'])

    def test_speed_and_armour_adjust_the_role_scores(self):
        fast = bot_profile.vehicle_profile(_descriptor('mediumTank', speed=15.0))['roles']
        slow = bot_profile.vehicle_profile(_descriptor('mediumTank', speed=8.0))['roles']
        heavy = bot_profile.vehicle_profile(_descriptor('heavyTank', turret=120.0))['roles']
        armoured_td = bot_profile.vehicle_profile(_descriptor('AT-SPG', hull=200.0))['roles']
        self.assertAlmostEqual(0.98, fast['flanker'])
        self.assertAlmostEqual(0.50, fast['scout'])
        self.assertAlmostEqual(0.70, slow['flanker'])
        self.assertEqual(1.0, heavy['brawler'])
        self.assertAlmostEqual(0.12, heavy['sniper'])
        self.assertEqual(bot_profile.ROLE_SCORES['AT-SPG'], armoured_td)

    def test_only_fields_with_a_reader_are_published(self):
        profile = bot_profile.vehicle_profile(_descriptor('SPG'))
        self.assertEqual({'bot_tier', 'class_tag', 'vehicle_name', 'roles', 'desired_range',
                          'fire_range', 'speed', 'armor', 'clip_size', 'gun_name', 'shells'},
                         set(profile))
        self.assertEqual({'brawler', 'support', 'flanker', 'sniper', 'scout'}, set(profile['roles']))

    def test_untagged_vehicle_is_a_medium_tank_without_inventing_data(self):
        profile = bot_profile.vehicle_profile({})
        self.assertEqual('mediumTank', profile['class_tag'])
        self.assertEqual((0.0, 0.0, 1, ''), (profile['speed'], profile['armor'],
                                            profile['clip_size'], profile['gun_name']))
        self.assertEqual((), profile['shells'])


class RouteCatalogTests(unittest.TestCase):
    def test_catalog_is_the_baked_routes_with_default_edits(self):
        graph = json.loads((ROOT / 'navgraphs' / '01_karelia.json').read_text(encoding='utf-8'))
        profile = bot_tactics.default_profile()
        baked, unused = bot_tactics_runtime.default_routes(profile, '01_karelia', graph)
        catalog, unused = bot_tactics_runtime.route_catalog(profile, '01_karelia', graph)
        for team in (1, 2):
            with self.subTest(team=team):
                self.assertEqual([r['id'] for r in baked[str(team)]],
                                 [r['id'] for r in catalog[team]])
                for source, row in zip(baked[str(team)], catalog[team]):
                    self.assertEqual(tuple((float(p[0]), float(p[1]), bool(p[2]))
                                           for p in source['waypoints']), row['waypoints'])
                    # No legacy tactical map metadata is copied in.
                    self.assertEqual(source.get('class_weights'), row.get('class_weights'))
                    self.assertEqual(source.get('role_weights'), row['role_weights'])

    def test_class_deletion_writes_a_zero_class_weight(self):
        graph = {'map': 'test', 'routes': {'1': [dict(id='lane', waypoints=[[0, 0, 0], [0, 50, 0]],
                                                      _editor_disabled_classes=['heavyTank'])],
                                           '2': []}}
        catalog, unused = bot_tactics_runtime.route_catalog(bot_tactics.empty(), 'test', graph)
        self.assertEqual({'heavyTank': 0.0}, catalog[1][0]['class_weights'])
        self.assertEqual((), catalog[2])


if __name__ == '__main__':
    unittest.main()
