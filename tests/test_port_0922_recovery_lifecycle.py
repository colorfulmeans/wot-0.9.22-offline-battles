"""Recovery ownership across orders, waits and arrivals, not map acceptance.

Report poses identify the three affected hulls. Explicit proof callbacks
describe a synthetic pocket with one short rear exit; no map BSP is faked.
"""
import math
import unittest

from test_port_0922_driver_arrival import LocalDriver, BotAdapter


class RecoveryLifecycleTests(unittest.TestCase):
    cases = (
        ('IS-7', (-16.34449,.26,-26.159964), (-18.,.26,-26.)),
        ('Object 704', (-178.29,.27,29.75), (-175.,.27,30.)),
        ('FV4005', (-170.73,.65,-80.71), (-170.506908,.647,-80.802422)),
    )

    def test_tangent_friend_does_not_steal_route_or_hold_but_penetration_still_escapes(self):
        for side in (-1.,1.):
            for held in (False,True):
                with self.subTest(side=side,held=held):
                    adapter=BotAdapter('04_himmelsdorf',1)
                    peer=dict(id=2,team=1,alive=True,position=(side*3.,0.,0.),
                        yaw=0.,shape=(1.5,3.5,-.8,2.),half_width=1.5,
                        half_length=3.5,velocity=(0.,0.,0.))
                    state=dict(id=1,slot=0,team=1,position=(0.,0.,0.),yaw=0.,
                        speed=0.,dt=.1,half_width=1.5,half_length=3.5,
                        collision_shape=(1.5,3.5,-.8,2.),neighbours=[peer],
                        pose_clear=lambda yaw:True)
                    order=dict(combat_mode='hold' if held else 'route',
                        move_position=(0.,0.,0.) if held else (0.,0.,30.),
                        throttle_override=0. if held else None)
                    command=adapter.decide_with_order(state,order,lambda *a:True)
                    self.assertNotEqual('contact_escape',command['recovery_mode'])
                    self.assertEqual(0. if held else 1.,command['throttle'])
                    self.assertEqual(not held,command['movement_intent'])
                    peer['position']=(side*2.99,0.,0.)
                    escaped=adapter.decide_with_order(state,order,lambda *a:True)
                    self.assertEqual('contact_escape',escaped['recovery_mode'])

    def test_complete_forward_sweep_allows_parallel_contact_but_keeps_other_blockers(self):
        driver=LocalDriver()
        peer=dict(position=(3.,0.,0.),yaw=0.,half_width=1.5,
                  half_length=3.5,alive=True,velocity=(0.,0.,0.))
        self.assertFalse(driver._static_hull_ahead((0.,0.,0.),0.,[peer],3.5,1.5))
        front=dict(peer,position=(0.,0.,7.))
        self.assertTrue(driver._static_hull_ahead((0.,0.,0.),0.,[peer,front],3.5,1.5))

    def test_order_churn_cannot_renew_a_returning_leg_or_enable_an_unsafe_exit(self):
        for name, origin, connector in self.cases:
            for hz in (15,24,60):
                with self.subTest(vehicle=name,hz=hz):
                    driver = LocalDriver()
                    driver._state(11,0,origin)['recovery_count'] = 2
                    commands = []
                    dt = 1.0/hz
                    # A close source corner can legitimately be reached. Use
                    # the unconsumed outgoing connector beyond that corner.
                    outgoing = (connector[0],connector[1],connector[2]+10.)
                    for frame in range(16*hz):
                        point = (origin[0]+.3*((frame//3)%2),origin[1],origin[2])
                        local = outgoing if (frame//hz)%2 else (80.,0.,80.)
                        remote = ((130.,0.,134.),(-110.,0.,27.))[(frame//hz)%2]
                        def proof(yaw,maximum_distance=None):
                            return (maximum_distance is not None and
                                    maximum_distance <= .5 and math.cos(yaw)<0.)
                        command = driver.drive(11,0,point,0.,0.,dt,local,(),proof,
                            progress_target=local,recovery_goal=remote,
                            retain_failed_legs=True,pose_clear=lambda yaw:False)
                        commands.append(command)
                        if command['throttle']:
                            self.assertLess(command['throttle'],0.)
                            self.assertEqual('short_reverse_escape',command['recovery_mode'])
                            self.assertLessEqual(command['recovery_probe_distance'],.5)
                    self.assertTrue(any(c['throttle']<0. for c in commands[8*hz:]))

    def test_no_exit_remains_blocked_despite_expired_progress_and_order_changes(self):
        driver = LocalDriver()
        origin = (0.,0.,0.)
        driver._state(11,0,origin)['recovery_count'] = 2
        for frame in range(240):
            goal = (100.,0.,100.) if frame%2 else (-100.,0.,-100.)
            command = driver.drive(11,0,origin,0.,0.,.1,goal,(),lambda *a:False,
                progress_target=goal,recovery_goal=goal,retain_failed_legs=True,
                pose_clear=lambda yaw:False)
            self.assertEqual(0.,command['throttle'])
            self.assertEqual(0.,command['turn'])

    def test_continuous_slow_approach_is_real_progress_not_a_timed_failure(self):
        driver = LocalDriver()
        driver._state(11,0,(0.,0.,0.))['recovery_count'] = 2
        for frame in range(300):
            point = (0.,0.,frame*.01)
            command = driver.drive(11,0,point,0.,.1,.1,(0.,0.,50.),(),lambda *a:True,
                progress_target=(0.,0.,50.),recovery_goal=(80.,0.,80.),
                retain_failed_legs=True)
            self.assertEqual('drive',command['recovery_mode'])
            self.assertEqual(1.,command['throttle'])
