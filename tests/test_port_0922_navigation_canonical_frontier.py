"""Canonical-path handoffs retain progress; model recorded 024540 light-tank loops."""
import unittest
from unittest import mock
from test_port_0922_navigation import TerrainNavigator

class CanonicalFrontierTests(unittest.TestCase):
    def scene(self):
        nav=TerrainNavigator(lambda *a: -12.,lambda *a: False)
        state=dict(request_key=('route_join',30,'river_crossing',3),path_key='one',index=1)
        nav.bot_states[30]=state
        return nav,state

    def test_switching_corners_and_private_paths_cannot_refresh_a_stationary_deadline(self):
        nav,s=self.scene();p=(-160.6475,-12.5921,-244.5734);goal=(28.896,0.,45.425)
        for at,target in ((0.,(-162.,-12.398,-242.)),(3.,(-146.,-13.077,-234.)),
                          (6.,(-162.,-12.398,-242.)),(9.,(-146.,-13.077,-234.))):
            s.update(path_key=str(at),index=int(at))
            self.assertFalse(nav._observe_path_frontier(s,p,target,goal,at))
        self.assertTrue(nav._observe_path_frontier(s,p,(-162.,-12.398,-242.),goal,12.))

    def test_returning_to_known_cells_and_known_leg_distances_is_not_new_progress(self):
        nav,s=self.scene();goal=(100.,0.,0.);target=(30.,0.,0.)
        for at,x in ((0.,0.),(3.,5.),(6.,0.),(9.,5.),(12.,0.)):
            nav._observe_path_frontier(s,(x,0.,0.),target,goal,at)
        self.assertTrue(nav._observe_path_frontier(s,(5.,0.,0.),target,goal,15.))

    def test_proved_dogleg_travel_away_from_macro_goal_still_counts(self):
        nav,s=self.scene();goal=(0.,0.,-100.);target=(100.,0.,0.)
        for at in range(40):
            self.assertFalse(nav._observe_path_frontier(s,(at*.5,0.,0.),target,goal,float(at)))

    def test_stall_hands_to_existing_private_replan_without_shared_terrain_edits(self):
        nav,s=self.scene();p=(0.,0.,0.);target=(10.,0.,0.);goal=(100.,0.,0.)
        s.update(last_target=target,macro_progress_kind='path')
        nav._observe_path_frontier(s,p,target,goal,0.)
        with mock.patch.object(nav,'_start_macro_replan',return_value=True) as replan:
            self.assertTrue(nav._observe_macro_progress(30,s,p,goal,12.))
            replan.assert_called_once_with(30,s,p,target,12.)
        self.assertEqual(1,s['path_frontier']['replans'])

    def test_real_cached_path_churn_reaches_existing_macro_retry(self):
        nav,s=self.scene();p=(-160.6475,-12.5921,-244.5734);goal=(28.896,0.,45.425)
        for at in (0.,3.,6.,9.,12.):
            target=((-162.,-12.398,-242.) if int(at)%2==0 else (-146.,-13.077,-234.))
            s.update(last_target=target,path_key=('join',30,int(at)),index=1)
            nav._observe_macro_progress(30,s,p,goal,at)
        self.assertEqual(1,s['replan_generation'])
        self.assertEqual(1,s['path_frontier']['replans'])
        self.assertTrue(s['macro_replan_active'])
        self.assertEqual({},nav.grid._failed_edges)

    def test_changed_request_retires_old_progress(self):
        nav,s=self.scene();p=(0.,0.,0.);target=(10.,0.,0.);goal=(100.,0.,0.)
        nav._observe_path_frontier(s,p,target,goal,0.)
        s['request_key']=('route_join',30,'other_route',1)
        self.assertFalse(nav._observe_path_frontier(s,p,target,goal,30.))
        self.assertEqual(30.,s['path_frontier']['at'])

if __name__=='__main__':unittest.main()
