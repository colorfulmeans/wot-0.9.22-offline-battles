"""A local waypoint handoff is not a new native-refusal recovery task."""
import math
import unittest
from unittest import mock
from test_port_0922_driver_arrival import BotAdapter, LocalDriver


class RecoveryGoalIdentityTests(unittest.TestCase):
    goal=(-106.189,0.,-105.493)
    position=(-155.64,.25,-16.38)

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
