"""October 3 orbit, right-hand wreck exit and stale withdrawal reports."""
import math
import unittest
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from test_port_0922_server_bot_ai import BotPlanner


class EgressTests(unittest.TestCase):
    def drive(self, driver, position, target, goal, dt=.1):
        return driver.drive(25, 9, position, -.66, 0., dt, target, [],
                            lambda *unused: True, progress_target=goal,
                            stop_at_target=False)

    def test_airfield_small_orbit_and_changing_local_targets_do_not_renew_progress(self):
        driver=LocalDriver()
        modes=[]
        origin=(-291.735, -.18, -167.920)
        goal=(-334., 0., -6.)
        for frame in range(100):
            position=(origin[0]+.2*math.sin(frame*.4), origin[1],
                      origin[2]+.2*math.cos(frame*.4))
            target=(position[0]+(3.2 if frame%2 else -3.2), origin[1], position[2]+3.)
            modes.append(self.drive(driver, position, target, goal)['recovery_mode'])
        self.assertIn('reverse_turn', modes)
        self.assertGreater(driver.states[25]['recovery_count'], 0)

    def test_near_local_waypoint_does_not_hide_a_stalled_distant_objective(self):
        driver=LocalDriver()
        modes=[self.drive(driver, (0.,0.,0.), (0.,0.,1.), (0.,0.,100.))['recovery_mode']
               for unused in range(100)]
        self.assertEqual('arrived', modes[0])
        self.assertIn('reverse_turn', modes)

    def test_real_slow_progress_keeps_normal_drive(self):
        driver=LocalDriver()
        for frame in range(120):
            command=self.drive(driver, (0.,0.,frame*.1), (0.,0.,frame*.1+5.), (0.,0.,100.))
            self.assertNotEqual('reverse_turn', command['recovery_mode'])

    def wreck_scene(self):
        adapter=BotAdapter('04_himmelsdorf', 1)
        state=dict(id=17,slot=1,team=2,position=(0.,0.,0.),yaw=0.,speed=0.,dt=.1,
                   half_length=4.,half_width=1.8, pose_clear=lambda yaw: yaw>=0.,
                   neighbours=[dict(id=2,team=1,alive=False,position=(0.,0.,9.),
                                    yaw=0.,half_width=1.8,half_length=4.)])
        order=dict(combat_mode='route',move_position=(0.,0.,100.),route_id='heavy',
                   route_index=2,throttle_override=None)
        return adapter,state,order

    def test_right_hand_exit_is_tried_before_push_and_failed_push_never_returns_to_left(self):
        adapter,state,order=self.wreck_scene()
        def terrain(yaw, distance=None):
            return -.05<=yaw<=1.4
        commands=[adapter.decide_with_order(state,order,terrain) for unused in range(170)]
        self.assertEqual('avoid',commands[0]['recovery_mode'])
        self.assertGreater(commands[0]['turn'],0.)
        self.assertTrue(all(c['recovery_mode']!='wreck_push' for c in commands[:59]))
        self.assertIn('wreck_push',[c['recovery_mode'] for c in commands[60:130]])
        self.assertTrue(all(c['recovery_mode']=='blocked' and c['throttle']==c['turn']==0.
                            for c in commands[145:]))

    def test_successful_wreck_detour_never_switches_to_pushing(self):
        adapter,state,order=self.wreck_scene()
        for frame in range(100):
            state['position']=(frame*.03,0.,frame*.1)
            command=adapter.decide_with_order(state,order,lambda *unused: True)
            self.assertNotEqual('wreck_push',command['recovery_mode'])

    def test_failed_withdrawal_releases_parking_after_threat_disappears(self):
        planner=BotPlanner()
        bot=dict(id=18,state=dict(x=57.455,y=1.1,z=-8.213))
        goal=dict(x=57.412,y=1.1,z=-27.683)
        route=dict(combat_mode='route',target_id=None,move_position=dict(x=182.,y=0.,z=-10.),
                   throttle_override=None)
        def apply(now,target=None):
            order=dict(route,target_id=target)
            return planner._apply_retreat_order(order,bot,goal,goal,now,
                                               'low_health_retreat','low_health_defend')
        self.assertIsNone(apply(1.)['throttle_override'])
        self.assertEqual(0.,apply(12.)['throttle_override'])
        resumed=apply(28.)
        self.assertEqual('route',resumed['combat_mode'])
        self.assertIsNone(resumed['throttle_override'])
        self.assertEqual(route['move_position'],resumed['move_position'])
        self.assertEqual('route',apply(29.)['combat_mode'])
        self.assertEqual('low_health_retreat',apply(30.,2)['combat_mode'])

    def test_defensive_hold_with_current_enemy_remains_intentional(self):
        planner=BotPlanner()
        bot=dict(id=18,state=dict(x=0.,y=0.,z=0.))
        route=dict(combat_mode='route',target_id=2,move_position=dict(x=0.,y=0.,z=100.))
        for now in (1.,30.,60.):
            result=planner._apply_retreat_order(dict(route),bot,dict(x=0.,y=0.,z=0.),
                         dict(x=100.,y=0.,z=0.),now,'low_health_retreat','low_health_defend')
            self.assertEqual(0.,result['throttle_override'])
            self.assertEqual('low_health_defend',result['tactical_phase'])


if __name__=='__main__': unittest.main()
