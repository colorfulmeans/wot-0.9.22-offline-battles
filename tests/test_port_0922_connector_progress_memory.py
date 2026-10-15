"""Recorded connector handoffs must not renew a stationary recovery lease.

These are driver contract regressions, not native map/physics replays.
"""
import math
import unittest
from test_port_0922_driver_arrival import LocalDriver


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
                            progress_target=target, recovery_goal=(80., 0., 80.))

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
