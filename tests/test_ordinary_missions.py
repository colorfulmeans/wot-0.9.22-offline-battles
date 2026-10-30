"""Current ordinary policy, not the retired three-reserve mission fixture."""
import copy
import calendar
import datetime
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

    def test_six_small_tasks_and_twelve_quality_tasks_in_difficulty_order(self):
        self.assertEqual(40,len(self.policy.CATALOGUE))
        daily=self.policy.state(self.owner.snapshot(),86401)
        self.assertEqual(18,len(daily['missions']))
        rows=[self.policy.BY_ID[k] for k in daily['missions']]
        self.assertEqual([2,2,1,1],[sum(r['pool']==p for r in rows) for p in ('basic','advanced','special','challenge')])
        self.assertEqual([(d,p) for d in ('simple','normal','hard','elite') for p in ('day','week','month')],
                         [(r['difficulty'],r['period']) for r in rows[6:]])
        self.assertEqual([1000,1500,2000,2500],[rows[i]['quality_xp'] for i in (6,9,12,15)])

    def test_old_progress_reset_does_not_change_campaign_or_reserves(self):
        snapshot = dict(dailyMissions={'day': 1, 'claimed': ['battles'], 'battles': 99},
                        personalMissionProgress={'42': 2}, personalReserves={'xp': 3})
        before = copy.deepcopy(snapshot)
        daily = self.policy.state(snapshot, 86401)
        self.assertEqual([], daily['claimed'])
        self.assertTrue(all(not any(values.values()) for values in daily['progress'].values()))
        self.assertEqual(before, snapshot)

    def test_week_month_and_day_boundaries_preserve_only_matching_periods(self):
        for y,m,d in ((2026,10,31),(2026,11,1),(2026,12,31),(2028,2,28),(2028,2,29)):
            now=calendar.timegm((y,m,d,12,0,0))
            a=self.policy.state(self.owner.snapshot(),now)
            for k in a['missions']: a['progress'][k]={metric:1 for metric in self.policy.BY_ID[k]['goals']}
            snapshot=dict(self.owner.snapshot(),dailyMissions=a)
            b=self.policy.state(snapshot,now+86400)
            for k in b['missions'][6:]:
                retained=a['periods'][k]==b['periods'][k]
                self.assertEqual(int(retained),b['progress'][k][k],(y,m,d,k))

    def test_same_day_sort_update_preserves_paid_tasks_and_partial_progress(self):
        daily = self.policy.state({}, 86401)
        key = daily['missions'][0]
        daily['claimed'] = [key]
        daily['rewards'][key] = [{'kind': 'credits', 'count': 40000}]
        daily['progress'][key] = dict((metric, goal) for metric, goal in
                                     self.policy.BY_ID[key]['goals'].items())
        daily['missions'].reverse()
        updated = self.policy.state({'dailyMissions': daily}, 86402)
        self.assertIn(key, updated['claimed'])
        self.assertEqual(daily['rewards'], updated['rewards'])
        self.assertEqual(daily['progress'], updated['progress'])

    def test_native_presentation_honors_marked_description_and_keeps_completed_order(self):
        class Formatter:
            def _getDescription(self, condition): return 'stock description'
        groups = types.SimpleNamespace(missionsSortFunc=lambda a, b: -99,
            _MarathonQuestsBlockInfo=type('Marathon',(),{'_findEvents':lambda *args: []}))
        bonus = types.ModuleType('gui.server_events.cond_formatters.bonus')
        bonus.BattlesCountFormatter = Formatter
        formatters = types.ModuleType('gui.server_events.cond_formatters')
        formatters.packDescriptionField = lambda text: ('native field', text)
        regular = types.ModuleType('gui.Scaleform.daapi.view.lobby.missions.regular')
        regular.group_packers = groups
        with mock.patch.dict(sys.modules, {
                bonus.__name__: bonus, formatters.__name__: formatters,
                regular.__name__: regular}):
            self.native.install_presentation(setattr)
        condition = types.SimpleNamespace(_data={'meta': {'offlineOrdinary': 'v2'}},
            getCustomDescription=lambda: 'Cause seven critical events; 6/7')
        self.assertEqual(('native field', 'Cause seven critical events; 6/7'),
                         Formatter()._getDescription(condition))
        condition._data = {}
        self.assertEqual('stock description', Formatter()._getDescription(condition))
        event = lambda key, priority: types.SimpleNamespace(
            getID=lambda: key, getPriority=lambda: priority,
            isCompleted=lambda: True)
        self.assertEqual(1, groups.missionsSortFunc(
            event('offline_daily_v3_1_win1', 100), event('offline_daily_v3_1_vehicle_hard_day', 90)))
        self.assertEqual(-99, groups.missionsSortFunc(event('personal_1', 100), event('other', 90)))

    def test_yesterdays_receipt_cannot_finish_tasks_after_midnight_before_another_battle(self):
        with mock.patch.object(self.policy, 'assignments', return_value=['crit7']):
            self.owner.snapshot()['dailyMissions'] = self.policy.state({}, 86401)
            self.owner.snapshot()['dailyMissions']['progress']['crit7']['crits'] = 6
            before = copy.deepcopy(self.owner.snapshot())
            with mock.patch.object(self.policy.time, 'time', return_value=172801):
                self.assertEqual([], self.policy.advance(self.owner, self.receipt(), 86402))
            self.assertEqual(before['wallet'], self.owner.snapshot()['wallet'])
            self.assertEqual(0,self.owner.snapshot()['dailyMissions']['progress']['crit7']['crits'])

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
        for key in ('hp_survive', 'damage2hp', 'block2hp'):
            self.assertIsNone(values[key])

    def test_quality_requires_one_battle_base_xp_and_victory(self):
        for xp,qualified in ((999,0),(1000,1),(1499,1),(1500,2),(2000,3),(2500,4)):
            for won in (True,False):
                values=self.policy.battle_values(self.receipt(rewards={'xp':xp},winner=1 if won else 2))
                self.assertEqual(qualified*3 if won else 0,sum(values[k] for k in values if k.startswith('vehicle_')))

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
        self.assertIn('<battles><count>7</count>', xml)
        self.assertIn('6/7', xml)
        self.assertIn('Cause 7 module or crew injuries', xml)
        self.assertEqual({'bonusCount': 0, 'battlesCount': 6},
                         self.native.native_progress(daily, 'crit7'))
        daily['progress']['crit7']['crits'] = 7
        self.assertEqual({'bonusCount': 0, 'battlesCount': 7},
                         self.native.native_progress(daily, 'crit7'))

    def test_partial_assistance_and_combined_goals_reach_native_battle_results(self):
        for key, metric, value in [('assist8000', 'assist', 715),
                                   ('win8damage', 'damage', 2671)]:
            with mock.patch.object(self.policy, 'assignments', return_value=[key]):
                self.owner.snapshot().pop('dailyMissions', None)
                receipt = self.receipt(winner=2, stats=dict(self.receipt()['stats'],
                    damage=2671, assist_radio=715))
                changed = self.policy.advance(self.owner, receipt, 86401)
                self.assertEqual(1, len(changed))
                self.assertEqual(0, changed[0]['after']['bonusCount'])
                field = 'battlesCount' if key == 'assist8000' else 'damageDealt'
                self.assertEqual(value, changed[0]['after'][field])
                if key == 'win8damage':
                    self.assertEqual(0, changed[0]['after']['battlesCount'])
                    xml = self.native.xml_definition(self.owner.snapshot()['dailyMissions'])
                    self.assertIn('<damageDealt>20000</damageDealt>', xml)

    def test_rental_preview_uses_payment_selection_without_mutating_inventory(self):
        rentals = fixture._load_port_module('vehicle_rentals')
        snapshot = {'accountDBID': 7, 'vehicles': []}
        daily = dict(day=1, missions=['vehicle_hard_day'], claimed=[], rewards={})
        pool = [dict(cd=17, name='tank', gold=1000)]
        before = copy.deepcopy(snapshot)
        with mock.patch.object(rentals, 'catalogue', return_value=pool):
            assets = self.native.preview(self.policy.BY_ID['vehicle_hard_day'], None,
                                         snapshot, daily, 86401)
            self.assertEqual({17: {'rent': {'time': 3}}}, assets['vehicles'])
            self.assertEqual(before, snapshot)
            snapshot['vehicles'] = [dict(vehicleTypeCompactDescr=17)]
            assets = self.native.preview(self.policy.BY_ID['vehicle_hard_day'], None,
                                         snapshot, daily, 86401)
            self.assertEqual({'credits': 12000}, assets)
            daily['rewards']['vehicle_hard_day'] = [dict(kind='rental', vehicle_type=17, days=1)]
            assets = self.native.preview(self.policy.BY_ID['vehicle_hard_day'], None,
                                         snapshot, daily, 86401)
            self.assertIn('vehicles', assets)


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

    def test_permanent_prize_upgrades_rentals_and_full_owned_pool_pays_full_value(self):
        records=[dict(vehicleTypeCompactDescr=1),
                 dict(vehicleTypeCompactDescr=2,rent=[{},200000,0,0])]
        reward=self.policy.choose(self.pool,records,0,100000,'seed')
        self.assertEqual('vehicle',reward['kind'])
        self.assertEqual(2,reward['vehicle_type'])
        records[1].pop('rent')
        reward=self.policy.choose(self.pool,records,0,100000,'seed')
        self.assertEqual('compensation',reward['kind'])
        price=self.pool[reward['vehicle_type']-1]['gold']
        self.assertEqual(price*400,reward['credits'])

    def test_approved_placeholder_values_do_not_follow_modern_repricing(self):
        self.assertEqual(13,len(self.policy.PRIZE_GOLD))
        self.assertEqual(7700,self.policy.PRIZE_GOLD['germany:G16_PzVIB_Tiger_II_F'])
        self.assertEqual(9000,self.policy.PRIZE_GOLD['ussr:R135_T_103'])
        self.assertNotIn('china:Ch01_Type59_Gold',self.policy.PRIZE_GOLD)

    def test_save_seed_is_independent_and_survives_ledger_and_restart(self):
        garage=fixture._load('garage')
        services=fixture._load_port_module('offline_services')
        first=garage.GarageState({})
        second=garage.GarageState({})
        self.assertNotEqual(first.snapshot()['missionSeed'],second.snapshot()['missionSeed'])
        ledger=services.saved_fields(first.snapshot())
        restored=garage.GarageState(ledger)
        self.assertEqual(first.snapshot()['missionSeed'],restored.snapshot()['missionSeed'])
        selected={self.policy.choose(self.pool,[],3,100000,str(i))['vehicle_type'] for i in range(50)}
        self.assertEqual({1,2},selected)

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
