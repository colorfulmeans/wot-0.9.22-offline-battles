"""Recorded connector handoffs must not renew a stationary recovery lease.

These are driver contract regressions, not native map/physics replays.
"""
import math
import unittest
from unittest import mock
from test_port_0922_driver_arrival import BotAdapter, LocalDriver


class ConnectorProgressMemoryTests(unittest.TestCase):
    cases = (
        ((-16.34449, .26, -26.159964), (-18., .26, -26.),
         (76.484, 0., 28.52)),
        ((-175.53929, .28, 58.158675), (-172.660057, .28, 59.737949),
         (-114.48, 0., 94.58)),
    )

    def drive(self, driver, position, target, dt=.1, intent=True):
        driver._state(11, 0, position)['recovery_count'] = 2
        return driver.drive(11, 0, position, 0., 0., dt, target, (),
                            lambda *unused: False, movement_intent=intent,
                            progress_target=target, recovery_goal=(80., 0., 80.),
                            retain_failed_legs=True)

    def test_recorded_local_global_local_handoff_keeps_previous_best_and_clock(self):
        for position, local, goal in self.cases:
            driver = LocalDriver()
            self.drive(driver, position, local)
            original = driver.states[11]['objective_progress']
            original.update(alignment_yaw=1.2, alignment_best=.1)
            self.drive(driver, position, goal, dt=4.)
            self.drive(driver, position, local, dt=3.)
            restored = driver.states[11]['objective_progress']
            self.assertIs(original, restored)
            self.assertEqual(.1, restored['at'])
            self.assertEqual(.1, restored['alignment_best'])

    def test_wobble_does_not_buy_another_distance_lease(self):
        position, local, goal = self.cases[0]
        driver = LocalDriver()
        self.drive(driver, position, local)
        best = driver.states[11]['objective_progress']['best']
        for tick in range(10):
            p = (position[0] + .3 * (tick % 2), position[1], position[2])
            self.drive(driver, p, goal if tick % 2 else local)
        self.drive(driver, position, local)
        self.assertEqual(best, driver.states[11]['objective_progress']['best'])
        self.assertGreater(driver.states[11]['clock'] -
                           driver.states[11]['objective_progress']['at'], .9)

    def test_real_approach_renews_existing_leg(self):
        position, local, goal = self.cases[0]
        driver = LocalDriver()
        self.drive(driver, position, local)
        self.drive(driver, position, goal)
        nearer = (position[0] - .5, position[1], position[2])
        self.drive(driver, nearer, local)
        self.assertEqual(driver.states[11]['clock'],
                         driver.states[11]['objective_progress']['at'])

    def test_alternating_failed_legs_eventually_take_proved_short_exit(self):
        for position, local, goal in self.cases:
            driver = LocalDriver()
            driver._state(11, 0, position)['recovery_count'] = 2
            commands = []
            for tick in range(150):
                # Net-zero shuffling renews translation samples but makes no
                # new best approach after the first pair of positions.
                p = (position[0]+.3*(tick % 2), position[1], position[2])
                target = local if tick % 20 < 10 else goal
                commands.append(driver.drive(11, 0, p, 0., 0., .1, target, (),
                    lambda yaw, maximum_distance=None:
                        maximum_distance is not None and maximum_distance <= .5
                        and math.cos(yaw) < 0.,
                    progress_target=target, recovery_goal=goal,
                    retain_failed_legs=True,
                    pose_clear=lambda yaw: False))
            self.assertTrue(any(c['recovery_mode'] == 'short_reverse_escape'
                                for c in commands[85:]))

    def test_hull_departure_or_explicit_hold_retires_pocket(self):
        for hold in (False, True):
            position, local, goal = self.cases[0]
            driver = LocalDriver()
            self.drive(driver, position, local)
            original = driver.states[11]['objective_progress']
            if hold:
                self.drive(driver, position, local, intent=False)
                self.assertNotIn('objective_progress_history', driver.states[11])
            else:
                self.drive(driver, (position[0]+20., .26, position[2]), goal)
            self.drive(driver, position, local)
            self.assertIsNot(original, driver.states[11]['objective_progress'])

    def test_history_is_bounded_under_distinct_stationary_orders(self):
        driver = LocalDriver()
        for index in range(100):
            self.drive(driver, (0., 0., 0.), (index * 3. + 10., 0., 20.))
        self.assertEqual(32, len(driver.states[11]['objective_progress_history']['entries']))

    def test_switching_remote_orders_cannot_renew_the_same_unmoved_leg(self):
        driver = LocalDriver()
        position, local = (0.,0.,0.), (0.,0.,100.)
        driver._state(11,0,position)['recovery_count'] = 2
        original = None
        for remote in ((80.,0.,80.), (130.,0.,134.), (-110.,0.,27.), (80.,0.,80.)):
            driver.drive(11,0,position,0.,0.,.1,local,(),lambda *unused:True,
                         progress_target=local, recovery_goal=remote,
                         retain_failed_legs=True)
            if original is None:
                original = driver.states[11]['objective_progress']
            self.assertIs(original, driver.states[11]['objective_progress'])
            self.assertEqual(.1, original['at'])

    def test_admission_preserves_existing_progress_and_arrival_consumes_it(self):
        driver = LocalDriver()
        position, local, goal = self.cases[0]
        driver.drive(11,0,position,0.,0.,.1,local,(),lambda *unused:False,
                     progress_target=local)
        original = driver.states[11]['objective_progress']
        self.drive(driver, position, local)
        self.assertIs(original, driver.states[11]['objective_progress'])
        self.drive(driver, local, local)
        self.drive(driver, local, goal)
        self.drive(driver, position, local)
        self.assertIsNot(original, driver.states[11]['objective_progress'])

    def test_leaving_the_physical_pocket_retires_the_same_leg_history(self):
        driver = LocalDriver()
        for position in ((0.,0.,0.), (20.,0.,0.)):
            driver._state(11,0,position)['recovery_count'] = 2
            driver.drive(11,0,position,0.,0.,.1,(0.,0.,100.),(),lambda *a:True,
                progress_target=(0.,0.,100.),retain_failed_legs=True)
            self.assertEqual(driver.states[11]['clock'],
                             driver.states[11]['objective_progress']['at'])

    def test_actual_order_arrival_completes_the_recovery_owner(self):
        driver = LocalDriver()
        self.drive(driver,(0.,0.,0.),(80.,0.,80.))
        driver.states[11]['recovery_replan_episode'] = dict(issued=True,origin=(0.,0.,0.))
        self.drive(driver,(80.,0.,80.),(80.,0.,80.))
        self.assertNotIn('objective_progress_history',driver.states[11])
        self.assertNotIn('recovery_replan_episode',driver.states[11])

    def test_stopping_short_of_arrival_releases_the_brake_latch(self):
        driver = LocalDriver()
        args = (11,0,(0.,0.,0.),0.)
        goal = (0.,0.,1.8)
        braking = driver.drive(*(args+(2.,.1,goal,(),lambda *a:True)),
            stopping_distance=2.,stop_at_target=True)
        self.assertTrue(braking['brake'])
        approach = driver.drive(*(args+(0.,.1,goal,(),lambda *a:True)),
            stopping_distance=0.,stop_at_target=True)
        self.assertEqual(1.,approach['throttle'])
        stopped = driver.drive(11,0,goal,0.,0.,.1,goal,(),lambda *a:True,
                               stop_at_target=True)
        self.assertTrue(stopped['brake'])
        passing = driver.drive(11,0,goal,0.,0.,.1,goal,(),lambda *a:True,
                               stop_at_target=False)
        self.assertFalse(passing['brake'])

    def test_unobstructed_travel_is_separate_from_admitted_recovery(self):
        for mode, wreck_distance, expected in (
                ('route', None, False), ('withdraw', None, True),
                ('route', 1., True), ('route', 100., False)):
            adapter = BotAdapter('test', 1)
            state = dict(id=11, slot=0, team=1, position=(0.,0.,0.),
                         yaw=0., speed=0., dt=.1, neighbours=[])
            if wreck_distance is not None:
                adapter._wreck_history[11] = {29:dict(exhausted=True,
                    origin=(wreck_distance,0.,0.))}
            with mock.patch.object(adapter, '_wreck_push_plan', return_value=None), \
                 mock.patch.object(adapter, '_reverse_withdrawal', return_value=None), \
                 mock.patch.object(adapter.driver, 'drive', return_value=dict(
                     throttle=1., turn=0., target_yaw=0., recovery_mode='drive')) as drive:
                adapter._drive_order_controls(11, state, state['position'],
                    dict(combat_mode=mode, move_position=(0.,0.,100.)),
                    lambda *unused: True)
            self.assertEqual(expected, drive.call_args.kwargs['retain_failed_legs'])

    def test_proved_route_blockage_keeps_progress_across_mode_handoffs(self):
        adapter = BotAdapter('test', 1)
        state = dict(id=11, half_length=3.5, half_width=1.7)
        position = (0.,0.,0.)
        adapter.driver._state(11,0,position)['recovery_replan_episode'] = dict(
            origin=position, at=0., count=2, cause='local_blocked', issued=False)
        for mode in ('route', 'advance', 'withdraw'):
            self.assertTrue(adapter._retain_recovery_progress(
                11,state,position,dict(combat_mode=mode)))
        departed=(20.,0.,0.)
        self.assertFalse(adapter._retain_recovery_progress(
            11,state,departed,dict(combat_mode='route')))
        adapter.driver.drive(11,0,departed,0.,0.,.1,(0.,0.,100.),(),lambda *a:True)
        self.assertNotIn('recovery_replan_episode',adapter.driver.states[11])
