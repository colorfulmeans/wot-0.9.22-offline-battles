"""Automatic artillery quotas depend on each team's complete roster size."""
import random
import types
import unittest

import test_port_0922_bot_lineup_integration as integration
from gui.mods.offline_lan_0922.ai import planner


class SmallTeamArtilleryTests(unittest.TestCase):
    def pool(self):
        return [dict(name='ussr:'+tag, tags=(tag,), level=8)
                for tag in planner.MATCH_CLASSES]

    def roster(self, sizes, round_id=1, worker=False, human_class='heavyTank', lineup=()):
        entries = {i:types.SimpleNamespace(**value) for i,value in enumerate(self.pool())}
        by_name = {value.name:value for value in entries.values()}
        human = by_name['ussr:'+human_class]
        descriptor = types.SimpleNamespace(type=human)
        battle = integration.BattleRuntime.__new__(integration.BattleRuntime)
        battle._runtime = types.SimpleNamespace(
            nations=types.SimpleNamespace(AVAILABLE_NAMES=('all',),INDICES={'all':0}),
            vehicles=types.SimpleNamespace(g_list=types.SimpleNamespace(getList=lambda unused:entries)))
        battle._worker_mode = worker
        battle._config = {'vehicle':human.name}
        battle.client = types.SimpleNamespace(team=1,player_id=1)
        battle._resolve_descriptor = lambda name:types.SimpleNamespace(type=by_name[name])
        battle._start_message = dict(round_id=round_id,map='01_karelia',bot_tier_mode='same',bot_lineup=list(lineup),
            players=[dict(id=1,team=1,slot=0,vehicle=human.name)],
            bots=[dict(id=team*100+slot,team=team,slot=slot)
                  for team in (1,2) for slot in range(1 if team==1 else 0,sizes[team-1])])
        self.assertTrue(battle._prepare_bot_vehicle_assignments(descriptor))
        return battle._bot_vehicle_assignments

    def test_all_fifteen_size_limits(self):
        expected = [0]*6+[1]*3+[2]*3+[3]*3
        self.assertEqual(expected,[planner.team_artillery_limit(n) for n in range(1,16)])

    def test_template_draws_zero_through_size_limit_and_fills_other_classes(self):
        pool=self.pool()
        for size in range(1,16):
            seen=set()
            for seed in range(64):
                rows=planner.build_match_template(pool,size,pool[0],(8,),random.Random(seed))
                self.assertEqual(size,len(rows))
                count=sum(planner.vehicle_match_class(row)=='SPG' for row in rows)
                self.assertLessEqual(count,planner.team_artillery_limit(size))
                seen.add(count)
                self.assertTrue(any(planner.vehicle_match_class(row)!='SPG' for row in rows))
            self.assertEqual(set(range(planner.team_artillery_limit(size)+1)),seen)

    def test_final_automatic_rosters_obey_each_size_and_match_worker(self):
        for size in range(1,16):
            for seed in range(8):
                with self.subTest(size=size,seed=seed):
                    visible=self.roster((size,size),seed)
                    self.assertEqual(visible,self.roster((size,size),seed,True))
                    self.assertEqual(size*2-1,len(visible))
                    for team in (1,2):
                        count=sum(name=='ussr:SPG' for (side,slot),name in visible.items() if side==team)
                        self.assertLessEqual(count,planner.team_artillery_limit(size))

    def test_unequal_teams_do_not_inherit_the_larger_teams_artillery_allowance(self):
        for sizes in ((15,1),(15,6),(6,15),(7,12),(12,7),(9,13),(13,9)):
            for seed in range(16):
                visible=self.roster(sizes,seed)
                self.assertEqual(visible,self.roster(sizes,seed,True))
                self.assertEqual(sum(sizes)-1,len(visible))
                for team in (1,2):
                    spgs=sum(name=='ussr:SPG' for (side,slot),name in visible.items() if side==team)
                    self.assertLessEqual(spgs,planner.team_artillery_limit(sizes[team-1]))

    def test_human_artillery_is_not_removed_or_mirrored_beyond_a_small_team_limit(self):
        for size in (1,2,6,7,9,10,12,13,15):
            for seed in range(8):
                picked=self.roster((size,size),seed,human_class='SPG')
                self.assertEqual(picked,self.roster((size,size),seed,True,'SPG'))
                own=sum(name=='ussr:SPG' for (team,slot),name in picked.items() if team==1)
                enemy=sum(name=='ussr:SPG' for (team,slot),name in picked.items() if team==2)
                self.assertLessEqual(own,max(0,planner.team_artillery_limit(size)-1))
                self.assertLessEqual(enemy,planner.team_artillery_limit(size))

    def test_pinned_artillery_is_preserved_and_uses_automatic_allowance(self):
        for size in (3,6,7,9,10,12,13,15):
            for seed in range(16):
                pinned=[dict(team=2,slot=0,vehicle='ussr:SPG')]
                picked=self.roster((size,size),seed,lineup=pinned)
                self.assertEqual('ussr:SPG',picked[(2,0)])
                self.assertEqual(picked,self.roster((size,size),seed,True,lineup=pinned))
                automatic=sum(name=='ussr:SPG' for (team,slot),name in picked.items() if team==2 and slot!=0)
                self.assertLessEqual(automatic,max(0,planner.team_artillery_limit(size)-1))

    def test_human_and_multiple_fixed_artillery_share_the_same_budget(self):
        for size in (7,10,13,15):
            for seed in range(16):
                pinned=[dict(team=1,slot=1,vehicle='ussr:SPG'),dict(team=1,slot=2,vehicle='ussr:SPG')]
                picked=self.roster((size,size),seed,human_class='SPG',lineup=pinned)
                self.assertEqual('ussr:SPG',picked[(1,1)])
                self.assertEqual('ussr:SPG',picked[(1,2)])
                self.assertFalse(any(name=='ussr:SPG' for (team,slot),name in picked.items() if team==1 and slot not in (1,2)))

    def test_only_artillery_catalogue_cannot_bypass_zero_quota(self):
        spg=self.pool()[-1]
        self.assertEqual([],planner.build_match_template([spg],3,spg,(8,),random.Random(1)))
        self.assertEqual([],planner.select_bot_lineup([spg],3))

    def test_low_count_spg_prefix_is_replaced_with_regular_vehicles(self):
        pool=self.pool()
        picked=planner.select_bot_lineup([pool[-1]]*3,3,fallback_candidates=pool)
        self.assertEqual(3,len(picked))
        self.assertTrue(all(planner.vehicle_match_class(row)!='SPG' for row in picked))
        self.assertIn('AT-SPG',[planner.vehicle_match_class(row) for row in picked])


if __name__=='__main__':
    unittest.main()
