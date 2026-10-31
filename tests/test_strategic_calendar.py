"""Calendar, independent quality windows, and unchanged native income factors."""
import calendar
import unittest
from unittest import mock
import test_port_0922_garage as fixture
import test_ordinary_missions as scenes


class StrategicCalendarTests(unittest.TestCase):
    def test_saved_week_and_month_draws_survive_daily_rollover_and_account_rebuild(self):
        policy = fixture._load_port_module('ordinary_missions')
        friday = calendar.timegm((2026,10,30,12,0,0))
        snapshot = dict(missionSeed='save-a')
        before = policy.state(snapshot, friday)
        snapshot.update(dailyMissions=before, missionSeed='rebuilt-account')
        after = policy.state(snapshot, friday+86400)
        for key, seed in before['rewardSeeds'].items():
            if policy.BY_ID[key]['period'] == 'day':
                self.assertNotEqual(seed, after['rewardSeeds'][key])
            else:
                self.assertEqual(seed, after['rewardSeeds'][key])
        sunday = policy.state(dict(snapshot, dailyMissions=after), friday+2*86400)
        self.assertNotEqual(after['rewardSeeds']['vehicle_simple_month'],
                            sunday['rewardSeeds']['vehicle_simple_month'])
        self.assertEqual(after['rewardSeeds']['vehicle_simple_week'],
                         sunday['rewardSeeds']['vehicle_simple_week'])

    def test_beijing_eight_weekend_and_leap_month_boundaries(self):
        clock=fixture._load_port_module('game_calendar')
        friday=calendar.timegm((2026,10,30,23,59,59))
        self.assertEqual(2,clock.first_win_factor(friday))
        self.assertEqual(5,clock.first_win_factor(friday+1))
        monday=calendar.timegm((2026,11,2,0,0,0))
        self.assertEqual(2,clock.first_win_factor(monday))
        self.assertEqual(monday,clock.bounds(monday,'week')[0])
        start,end=clock.bounds(calendar.timegm((2028,2,28,0,0,0)),'month')
        self.assertEqual(29*86400,end-start)

    def test_every_quality_level_advances_all_periods_and_pays_once(self):
        scene=scenes.OrdinaryMissionsTests();scene.setUp()
        self.addCleanup(scene.doCleanups)
        key='vehicle_elite_day'
        # Isolate strategic tasks so native equipment dependencies cannot hide
        # the qualifying win count or the once-only payment contract.
        ids=[r['id'] for r in scene.policy.CATALOGUE if r['pool']=='strategic']
        with mock.patch.object(scene.policy,'assignments',return_value=ids), \
             mock.patch.object(scene.policy,'_pay',return_value=[{'kind':'credits','count':7}]) as pay:
            for i in range(100):
                scene.policy.advance(scene.owner,scene.receipt(receipt_id=str(i),rewards={'xp':2500}),86401)
            daily=scene.owner.snapshot()['dailyMissions']
            self.assertEqual(set(ids),set(daily['claimed']))
            self.assertEqual(12,pay.call_count)
            self.assertEqual(5,daily['progress'][key][key])
            scene.policy.advance(scene.owner,scene.receipt(rewards={'xp':2500}),86401)
            self.assertEqual(12,pay.call_count)

    def test_first_win_five_changes_xp_and_crew_but_not_credit_or_bonds(self):
        economy=fixture._load('economy')
        basis=dict(credits=1000,xp=1000,free_xp=50,bonds=7)
        a,crew,record=economy.battle_income(basis,{},first_win=True,daily_factor=5)
        self.assertEqual((5000,250,1000,7),(a['xp'],a['free_xp'],a['credits'],a['bonds']))
        self.assertEqual(5000,crew)
        self.assertEqual(5,record['daily_factor'])
        b,unused,record=economy.battle_income(basis,{},first_win=False,daily_factor=5)
        self.assertEqual(1000,b['xp'])
        self.assertEqual(1,record['daily_factor'])
