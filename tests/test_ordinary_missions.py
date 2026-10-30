"""Current ordinary policy, not the retired three-reserve mission fixture."""
import copy
import importlib
import sys
import types
import unittest
from unittest import mock
import test_port_0922_garage as fixture


class OrdinaryMissionsTests(unittest.TestCase):
    def setUp(self):
        self.garage = fixture._load('garage')
        self.policy = fixture._load_port_module('ordinary_missions')
        clock = mock.patch.object(self.policy.time, 'time', return_value=86401)
        clock.start()
        self.addCleanup(clock.stop)
        self.native = fixture._load_port_module('ordinary_missions_native')
        self.owner = self.garage.GarageState({'wallet': {'gold': 0, 'credits': 0}})

    def receipt(self, **changes):
        row = dict(receipt_id='battle-1', battle_mode='regular', premature_leave=False,
                   vehicle='ussr:R11_MS-1', player_id=1, team=1, winner=1,
                   max_health=1000, rewards={'xp': 900},
                   stats=dict(damage=2000, kills=3, damaged=4, critical_hits=2,
                              damage_blocked=2500, piercings=7, spotted=3),
                   public_results=[dict(actor_kind='player', actor_id=1, team=1,
                                        xp=900, stats={'damage': 2000}, health=500)])
        row.update(changes)
        return row

    def test_55_candidates_and_approved_cadence_daily_reset(self):
        self.assertEqual(55, len(self.policy.CATALOGUE))
        for day in range(21):
            daily = self.policy.state({}, day * 86400 + 1)
            self.assertEqual(7 + int(day % 3 == 0) + int(day % 7 == 0), len(daily['missions']))
            rows = [self.policy.BY_ID[key] for key in daily['missions']]
            self.assertEqual([2, 2, 1, 1], [sum(r['pool'] == pool for r in rows)
                for pool in ('basic', 'advanced', 'special', 'challenge')])
            daily['claimed'] = list(daily['missions'])
            saved = {'dailyMissions': daily}
            self.assertEqual(daily, self.policy.state(saved, day * 86400 + 5))
            self.assertEqual([], self.policy.state(saved, (day + 1) * 86400 + 1)['claimed'])

    def test_old_progress_reset_does_not_change_campaign_or_reserves(self):
        snapshot = dict(dailyMissions={'day': 1, 'claimed': ['battles'], 'battles': 99},
                        personalMissionProgress={'42': 2}, personalReserves={'xp': 3})
        before = copy.deepcopy(snapshot)
        daily = self.policy.state(snapshot, 86401)
        self.assertEqual([], daily['claimed'])
        self.assertTrue(all(not any(values.values()) for values in daily['progress'].values()))
        self.assertEqual(before, snapshot)

    def test_yesterdays_receipt_cannot_finish_tasks_after_midnight_before_another_battle(self):
        with mock.patch.object(self.policy, 'assignments', return_value=['crit7']):
            self.owner.snapshot()['dailyMissions'] = self.policy.state({}, 86401)
            self.owner.snapshot()['dailyMissions']['progress']['crit7']['crits'] = 6
            before = copy.deepcopy(self.owner.snapshot())
            with mock.patch.object(self.policy.time, 'time', return_value=172801):
                self.assertEqual([], self.policy.advance(self.owner, self.receipt(), 86402))
            self.assertEqual(before, self.owner.snapshot())

    def test_cumulative_seven_critical_events_paid_once_with_durable_notice(self):
        with mock.patch.object(self.policy, 'assignments', return_value=['crit7']), \
                mock.patch.object(self.owner, '_vehicles_module', side_effect=AttributeError):
            for unused in range(3):
                self.policy.advance(self.owner, self.receipt(), 86401)
            self.assertEqual(0, self.owner.snapshot()['wallet']['gold'])
            changed = self.policy.advance(self.owner, self.receipt(), 86401)
            self.assertEqual(100, self.owner.snapshot()['wallet']['gold'])
            self.assertEqual(1, changed[0]['after']['bonusCount'])
            self.assertEqual([], self.policy.advance(self.owner, self.receipt(), 86401))
            notices = self.owner.snapshot()['personalMissionNotifications']
            self.assertEqual(1, len(notices))
            self.assertEqual([{'kind': 'gold', 'count': 100}],
                notices[0]['settlement']['ordinary_missions'][0]['rewards'])

    def test_training_abandonment_and_late_receipt_never_advance(self):
        with mock.patch.object(self.policy, 'assignments', return_value=['crit7']):
            for changes in ({'battle_mode': 'training'}, {'premature_leave': True}):
                self.assertEqual([], self.policy.advance(self.owner, self.receipt(**changes), 86401))
            self.owner.snapshot()['dailyMissions'] = self.policy.state({}, 172801)
            before = copy.deepcopy(self.owner.snapshot())
            self.assertEqual([], self.policy.advance(self.owner, self.receipt(), 86401))
            self.assertEqual(before, self.owner.snapshot())

    def test_failed_payment_rolls_back_assets_and_keeps_completion_unclaimed(self):
        self.owner.snapshot()['wallet']['gold'] = 2 ** 31 - 50
        with mock.patch.object(self.policy, 'assignments', return_value=['crit7']):
            self.owner.snapshot()['dailyMissions'] = self.policy.state({}, 86401)
            self.owner.snapshot()['dailyMissions']['progress']['crit7']['crits'] = 6
            self.policy.advance(self.owner, self.receipt(), 86401)
        saved = self.owner.snapshot()
        self.assertEqual(2 ** 31 - 50, saved['wallet']['gold'])
        self.assertEqual([], saved['dailyMissions']['claimed'])
        self.assertEqual(7, saved['dailyMissions']['progress']['crit7']['crits'])
        self.assertNotIn('personalMissionNotifications', saved)

    def test_missing_hp_cannot_pass_own_hp_conditions(self):
        values = self.policy.battle_values(self.receipt(max_health=0))
        for key in ('hp_survive', 'damage2hp', 'block2hp', 'rental_3_1', 'rental_5_1'):
            self.assertIsNone(values[key])

    def test_base_xp_and_survival_qualify_battles_not_rewarded_xp(self):
        row = self.receipt(rewards={'xp': 749})
        values = self.policy.battle_values(row)
        self.assertFalse(values['rental_6_1'])
        self.assertTrue(values['rental_5_1'])
        self.assertTrue(values['block2hp'])
        self.assertEqual(2, values['crits'])

    def test_native_flat_cumulative_counter_and_ungrouped_progress(self):
        daily = dict(day=1, missions=['damage3000'], claimed=[],
                     progress={'damage3000': {'damage': 1500}})
        self.assertEqual({'bonusCount': 0, 'damageDealt': 1500},
                         self.native.native_progress(daily, 'damage3000'))
        xml = self.native.xml_definition(daily)
        self.assertIn('<damageDealt>3000</damageDealt>', xml)
        self.assertIn('<showCongrats>false</showCongrats>', xml)
        self.assertNotIn('<popup', xml)

    def test_native_parser_receives_memory_section_quest_root_and_utf8(self):
        section = object()
        parse = mock.Mock(return_value={'quests': section})
        read = mock.Mock(return_value={'native': []})
        with mock.patch.dict(sys.modules, {
                'ResMgr': types.SimpleNamespace(DataSection=lambda: types.SimpleNamespace(
                    createSectionFromString=parse)),
                'quest_xml_source': types.SimpleNamespace(Source=lambda: types.SimpleNamespace(
                    _Source__readXML=read))}):
            self.assertEqual({'native': []}, self.native.parse_xml('<root/>', 100, 0, 200))
        parse.assert_called_once_with(b'<root/>')
        read.assert_called_once_with(section, 100, 0, 200)

    def test_composite_card_uses_native_custom_description_and_actual_completion(self):
        daily = dict(day=1, missions=['crit7'], claimed=[],
                     progress={'crit7': {'crits': 6}})
        xml = self.native.xml_definition(daily)
        self.assertIn('<battles><count>1</count><title>', xml)
        self.assertIn('6/7', xml)
        self.assertIn('Cause 7 module or crew injuries', xml)
        self.assertEqual({'bonusCount': 0, 'battlesCount': 0},
                         self.native.native_progress(daily, 'crit7'))
        daily['progress']['crit7']['crits'] = 7
        self.assertEqual({'bonusCount': 0, 'battlesCount': 1},
                         self.native.native_progress(daily, 'crit7'))


class RentalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = fixture._load_port_module('vehicle_rentals')
        self.pool = [dict(cd=1, name='a', gold=100), dict(cd=2, name='b', gold=200)]

    def test_missing_then_existing_rental_extension_then_all_permanent_compensation(self):
        records = [dict(vehicleTypeCompactDescr=1, rent=[{}, 200000, 0, 0])]
        reward = self.policy.choose(self.pool, records, 3, 100000, 'seed')
        self.assertEqual(2, reward['vehicle_type'])
        records.append(dict(vehicleTypeCompactDescr=2))
        reward = self.policy.choose(self.pool, records, 3, 100000, 'seed')
        self.assertEqual(1, reward['vehicle_type'])
        self.assertEqual(200000 + 3 * 86400, reward['expiry'])
        self.assertTrue(reward['extended'])
        records[0].pop('rent')
        reward = self.policy.choose(self.pool, records, 3, 100000, 'seed')
        self.assertEqual('compensation', reward['kind'])
        self.assertEqual(self.policy.compensation(
            self.pool[reward['vehicle_type'] - 1]['gold'], 3), reward['credits'])

    def test_expired_rental_is_available_before_extending_an_active_one(self):
        records = [dict(vehicleTypeCompactDescr=1, rent=[{}, 200000, 0, 0]),
                   dict(vehicleTypeCompactDescr=2, rent=[{}, 99999, 0, 0])]
        reward = self.policy.choose(self.pool, records, 1, 100000, 'seed')
        self.assertEqual(2, reward['vehicle_type'])
        self.assertFalse(reward['extended'])
        self.assertEqual(186400, reward['expiry'])

    def test_fixed_duration_compensation_is_integer_and_rejects_other_durations(self):
        self.assertEqual([1, 3, 7, 14, 30, 90, 180, 360], sorted(self.policy.COMPENSATION_PERCENT))
        self.assertEqual(14400, self.policy.compensation(1200, 3))
        self.assertEqual(480000, self.policy.compensation(1200, 360))
        with self.assertRaises(KeyError):
            self.policy.compensation(1200, 730)

    def test_expiration_notice_is_durable_once_and_keeps_the_same_hull(self):
        record = dict(id=9, vehicleTypeCompactDescr=1, rent=[{}, 100, 0, 0], crew=[101])
        snapshot = dict(vehicles=[record])
        self.assertEqual([], self.policy.expire(snapshot, 99))
        self.assertEqual([dict(vehicle_type=1, expiry=100)], self.policy.expire(snapshot, 100))
        self.assertEqual([], self.policy.expire(snapshot, 101))
        self.assertEqual([101], record['crew'])
        self.assertEqual(1, len(snapshot['personalMissionNotifications']))
