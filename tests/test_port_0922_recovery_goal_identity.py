"""A local waypoint handoff is not a new native-refusal recovery task."""
import math
import unittest
from unittest import mock
from test_port_0922_driver_arrival import BotAdapter, LocalDriver


class RecoveryGoalIdentityTests(unittest.TestCase):
    goal=(-106.189,0.,-105.493)
    position=(-155.64,.25,-16.38)

    def stationary_native_refusal(self, clear, actual_goal=None, refused=True):
        driver = LocalDriver()
        commands = []
        # Windows278 Centurion: no vehicle contacts, a nearby local waypoint,
        # alternating route/withdraw goals, and native world rotation refusal.
        position = (77.8351956854, 65.126083374, 179.134907428)
        for tick in range(180):
            goal = actual_goal or ((86.515, 66.49, 181.178) if tick % 30 < 15
                                  else (14.79, 0., 77.037))
            commands.append(driver.drive(20, 4, position, -2.785773322,
                0., .1, position, (), clear, pose_clear=lambda yaw: False,
                progress_target=goal, recovery_goal=goal,
                rotation_refused=refused, turn_speed_limit=.45))
        return driver, commands

    def test_nearby_waypoint_and_changing_goals_do_not_erase_native_stall(self):
        driver, commands = self.stationary_native_refusal(
            lambda yaw, maximum_distance=None: maximum_distance is not None
                and maximum_distance <= .5 and math.cos(yaw + 2.785773322) < 0)
        self.assertTrue(any(c['recovery_mode'] == 'short_reverse_escape'
                            for c in commands[85:]))
        for command in commands[85:]:
            self.assertNotEqual('arrived', command['recovery_mode'])
        self.assertGreater(driver.states[20]['clock'] -
                           driver.states[20]['translation_progress_at'], 8.)

    def test_no_proved_exit_holds_instead_of_bypassing_world_or_vehicle_checks(self):
        unused, commands = self.stationary_native_refusal(lambda *args: False)
        self.assertTrue(any(c['recovery_mode'] == 'blocked' for c in commands[85:]))
        self.assertTrue(all(c['throttle'] == 0. for c in commands))

    def test_real_arrival_and_unproved_native_blockage_do_not_force_recovery(self):
        position = (77.8351956854, 65.126083374, 179.134907428)
        for kwargs in ({'actual_goal': position}, {'refused': False}):
            unused, commands = self.stationary_native_refusal(
                lambda *args: True, **kwargs)
            self.assertTrue(all(c['recovery_mode'] == 'arrived' for c in commands))

    def test_native_world_refusal_can_request_bounded_replan_without_vehicle_contact(self):
        adapter = BotAdapter('test', 1)
        state = dict(id=20, slot=4, team=2, position=(77.835, 65.126, 179.135),
                     yaw=-2.78577, speed=0., dt=.1, neighbours=[],
                     native_rotation_refused=True)
        order = dict(throttle=0., turn=0., target_yaw=-2.78577,
                     recovery_mode='blocked', brake=True)
        with mock.patch.object(adapter.driver, 'drive', return_value=order), \
             mock.patch.object(adapter.driver, 'recovery_replan', return_value=True) as replan:
            result = adapter._drive_order_controls(20, state, state['position'],
                dict(combat_mode='route', move_position=(86.515, 66.49, 181.178)),
                lambda *args: False)
        replan.assert_called_once()
        self.assertTrue(result['navigation_replan'])
        self.assertEqual(0., result['throttle'])

    def driver(self):
        driver=LocalDriver()
        state=driver._state(21,0,self.position)
        state.update(clock=9.,recovery_time=.8,recovery_side=1.,recovery_count=3,
                     recovery_pocket=dict(origin=self.position,at=0.,goal=self.goal))
        return driver,state

    def drive(self,driver,local,recovery_goal=None):
        # A complete reverse sweep is blocked; an actual short rear connector
        # is proved. These replies isolate ownership, not the native map BSP.
        return driver.drive(21,0,self.position,0.,0.,.1,local,(),
            lambda yaw,maximum_distance=None: math.cos(yaw)<0 and
                maximum_distance is not None and maximum_distance<=.5,
            progress_target=local,pose_clear=lambda yaw: True,
            recovery_goal=recovery_goal)

    def test_recorded_local_handoff_preserves_lease_and_uses_proved_translation(self):
        for local in ((-158.,.26,-2.),(-154.,.255,-14.)):
            driver,state=self.driver()
            command=self.drive(driver,local,self.goal)
            self.assertEqual('short_reverse_escape',command['recovery_mode'])
            self.assertEqual(.5,command['recovery_probe_distance'])
            self.assertEqual(0.,command['turn'])
            self.assertEqual(0.,state['recovery_pocket']['at'])
            self.assertEqual(self.goal,state['recovery_pocket']['goal'])

    def test_old_local_identity_reproduces_lease_retirement(self):
        driver,state=self.driver()
        self.drive(driver,(-158.,.26,-2.))
        self.assertNotIn('recovery_pocket',state)

    def test_actual_new_order_and_real_hull_exit_retire_lease(self):
        for changed in (True,False):
            driver,state=self.driver()
            if not changed:state['recovery_pocket']['origin']=(-140.,.25,-16.38)
            self.drive(driver,(-158.,.26,-2.),(0.,0.,0.) if changed else self.goal)
            self.assertNotIn('recovery_pocket',state)

    def test_adapter_passes_strategic_order_separately_from_proved_local_leg(self):
        local=(-158.,.26,-2.)
        adapter=BotAdapter('airfield',11,navigation_target=lambda *args: local)
        state=dict(id=21,team=2,slot=0,position=self.position,yaw=0.,speed=0.,dt=.1)
        with mock.patch.object(adapter.driver,'drive',wraps=adapter.driver.drive) as drive:
            adapter.decide_with_order(state,dict(combat_mode='route',move_position=self.goal),lambda *args: True)
        self.assertEqual(self.goal,drive.call_args.kwargs['recovery_goal'])


if __name__=='__main__':unittest.main()
