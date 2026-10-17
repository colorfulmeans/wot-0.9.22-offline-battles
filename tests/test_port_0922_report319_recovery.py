"""Windows319 failures at partial tips, repeated exits and adjacent roofs."""
import unittest
import types
from unittest import mock

from test_port_0922_navigation import TerrainNavigator
from gui.mods.offline_lan_0922 import vehicle_stack
from gui.mods.offline_lan_0922 import tank_collision
import test_port_0922_battle_runtime as battle_fixture
import test_port_0922_vehicle_physics as physics_fixture
from gui.mods.offline_lan_0922 import vehicle_physics


class IncompleteEndpointTests(unittest.TestCase):
    def scene(self):
        nav = TerrainNavigator(lambda *args: -14.73, lambda *args: False)
        nav.grid.segment_clear = lambda *args: True
        nav.grid.segment_penalty = lambda *args: 0.
        return nav

    def test_report_bot10_same_partial_tip_is_blocked_not_arrived(self):
        nav = self.scene()
        current = (-10.28, -14.73, 18.20)
        endpoint = (-10., -14.681, 18.)
        goal = (0., 0., 18.)
        nav._path = lambda key, *args: (key, (endpoint,))
        for now in (1., 1.5):
            target = nav.next_target(10,current,goal,('route',10),now)
            self.assertEqual(goal,target)
            self.assertEqual('blocked',nav.bot_states[10]['navigation_status'])
            self.assertFalse(nav.target_is_terminal(10))
        self.assertEqual(2,nav.bot_states[10]['local_retry_progress']['failures'])
        self.assertEqual('no_onward_leg',nav.bot_states[10]['path_endpoint_refusal']['reason'])

    def test_nearby_incomplete_tip_is_not_an_arrival_either(self):
        nav = self.scene()
        current = (-2.,-14.,18.)
        goal = (0.,0.,18.)
        nav._path = lambda key,*args:(key,(current,))
        self.assertEqual(goal,nav.next_target(10,current,goal,('route',10),1.))
        self.assertEqual('incomplete_endpoint',nav.bot_states[10]['path_endpoint_refusal']['reason'])
        self.assertFalse(nav.target_is_terminal(10))

    def test_actual_arrival_keeps_terminal_output(self):
        nav = self.scene()
        goal = (0.,0.,18.)
        nav._path = lambda key,*args:(key,(goal,))
        nav.next_target(10,goal,goal,('route',10),1.)
        self.assertTrue(nav.target_is_terminal(10))
        self.assertNotIn('path_endpoint_refusal',nav.bot_states[10])

    def test_new_request_and_onward_plan_retire_old_refusal(self):
        for new_goal, new_key in (((-94.896,-14.499,-20.981),('route',10)),
                                  ((0.,0.,18.),('route',11))):
            nav=self.scene()
            current=(-10.28,-14.73,18.20)
            nav._path=lambda key,*args:(key,((-10.,-14.681,18.),))
            nav.next_target(10,current,(0.,0.,18.),('route',10),1.)
            self.assertIn('path_endpoint_refusal',nav.bot_states[10])
            nav._path=lambda key,*args:(key,(new_goal,))
            nav.next_target(10,current,new_goal,new_key,2.)
            self.assertNotIn('path_endpoint_refusal',nav.bot_states[10])

    def test_onward_plan_for_same_request_retires_old_refusal(self):
        nav=self.scene()
        current,goal=(-10.28,-14.73,18.20),(0.,0.,18.)
        nav._path=lambda key,*args:(key,((-10.,-14.681,18.),))
        nav.next_target(10,current,goal,('route',10),1.)
        nav._path=lambda key,*args:(key,(goal,))
        nav.next_target(10,current,goal,('route',10),2.)
        self.assertNotIn('path_endpoint_refusal',nav.bot_states[10])

    def test_report_bot28_repeated_tip_without_search_keeps_bounded_retry(self):
        nav = self.scene()
        current = (-30.4237,1.2487,-168.3943)
        candidate = (-28.34897,.616,-168.2463)
        goal = (0.,0.,-18.)
        state = dict(request_key=(('local',28),(0,0)),temporary_stalled=True,
                     temporary_visited_cells={nav.grid.cell_for(candidate)})
        nav.bot_states[28] = state
        with mock.patch.object(nav.grid,'safe_local_target',return_value=candidate):
            target = nav._pending_target(28,current,goal,50.,state,allow_last_target=False,
                                         immediate_safe_local=True)
        self.assertEqual(current,target)
        self.assertEqual('pending',state['navigation_status'])
        self.assertEqual(1,state['local_retry_progress']['failures'])
        self.assertEqual('temporary_path_repeats',state['local_selection']['outcome'])
        nav._record_local_retry_refusal(state,current,goal,50.5)
        self.assertFalse(nav._local_retry_stalled(state,current,goal,50.5,True))
        self.assertTrue(nav._local_retry_stalled(state,current,goal,63.,True))

    def test_real_pending_search_still_waits_for_its_own_proof(self):
        nav = self.scene()
        current,goal=(0.,0.,0.),(30.,0.,0.)
        key=('search',)
        state=dict(path_key=key,pending_since=0.)
        nav.searches[key]=mock.Mock(done=False,progress={})
        with mock.patch.object(nav,'_pending_search_target',return_value=None), \
                mock.patch.object(nav,'_safe_fallback_target',return_value=None):
            self.assertEqual(current,nav._pending_target(1,current,goal,5.,state))
        self.assertEqual('pending',state['navigation_status'])




if __name__ == '__main__':
    unittest.main()
