"""Independent player entry: all eligible lanes, actual layer and connectivity."""
from pathlib import Path
import sys,types,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_navigation import PlayerNavigation,route_candidates

class EntryTests(unittest.TestCase):
    def test_reserve_and_class_variants_are_candidates_without_bot_capacity(self):
        rows=[dict(id='main',waypoints=[(0,0)]),
              dict(id='reserve',_route_tier='reserve',waypoints=[(1,1)]),
              dict(id='edited',_editor_source='main',_editor_class='heavyTank',waypoints=[(2,2)])]
        result=route_candidates({'1':rows},1,'heavyTank')
        self.assertEqual(['edited','reserve'],[r['id'] for r in result])
        result[0]['waypoints'].append((3,3))
        self.assertEqual(1,len(rows[-1]['waypoints']))

    def planner(self,routes,heights,path):
        plan=PlayerNavigation.__new__(PlayerNavigation)
        plan.routes=routes;plan.route=None;plan.index=None;plan.candidates=None
        plan.search=None;plan.pending=None;plan.retry_at=0.;plan.receipt={}
        def begin(start,goal,**kw):
            return types.SimpleNamespace(step=lambda budget:None,done=True,result=path(start,goal))
        plan.navigator=types.SimpleNamespace(grid=types.SimpleNamespace(begin_plan=begin))
        plan._height=lambda point,hint:heights.get(tuple(point))
        return plan

    def test_nearest_reserve_is_selected_not_first_main(self):
        plan=self.planner([dict(id='main',waypoints=[(100,0)]),
                           dict(id='reserve',waypoints=[(5,0)])],
                          {(100,0):0,(5,0):0},lambda start,goal:(start,goal))
        self.assertTrue(plan.join((0,0,0),1))
        self.assertEqual('reserve',plan.route['id'])

    def test_overhead_snap_is_rejected_and_connected_ground_route_is_selected(self):
        plan=self.planner([dict(id='bridge',waypoints=[(0,0)]),
                           dict(id='ground',waypoints=[(20,0)])],
                          {(0,0):8,(20,0):0},
                          lambda start,goal:((0,8,0),goal) if goal[1] else (start,goal))
        self.assertFalse(plan.join((0,0,0),1))
        self.assertEqual('rejected_layer_or_path',plan.receipt['status'])
        self.assertTrue(plan.join((0,0,0),2))
        self.assertEqual('ground',plan.route['id'])

    def test_disconnected_nearest_point_does_not_win(self):
        plan=self.planner([dict(id='near',waypoints=[(1,0)]),dict(id='far',waypoints=[(20,0)])],
                          {(1,0):0,(20,0):0},lambda start,goal:() if goal[0]==1 else (start,goal))
        self.assertFalse(plan.join((0,0,0),1))
        self.assertTrue(plan.join((0,0,0),2))
        self.assertEqual('far',plan.route['id'])

if __name__=='__main__':unittest.main()
