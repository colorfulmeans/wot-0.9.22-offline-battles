"""Cover return regressions from the 2026-11-06 02:48:47 client report.

These tests exercise the real foreground navigation state machine. The native
path, support, and motion boundaries are explicit seams; they do not establish
Windows-client collision or vehicle physics behavior.
"""
import math
import types
import unittest

from test_player_navigation_migration import controller, state


REPORT_COVER = (118.46879076602637, .602, 58.05706267397922)
REPORT_PEEK = (107.12930852382884, -.25258970260620117, 55.19885858172728)
REPORT_RETURN_POSITION = (108.51408430747809, -.2634448561346828, 54.664766477985474)
REPORT_RETURN_YAW = -1.3823811623707363


def wrapped(value):
    return (value + math.pi) % (2. * math.pi) - math.pi


def bearing(origin, goal):
    return math.atan2(goal[0] - origin[0], goal[2] - origin[2])


class SyntheticMotion(object):
    """A deterministic control seam, not native vehicle physics.

    Braking stops immediately. Pedal and turn map to fixed test rates; a
    pivot also translates the hull slightly, so arriving does not erase the
    lateral error that exposed the report's return-direction bug. No phase
    transition teleports the hull or resets its yaw.
    """
    def __init__(self, position, yaw):
        self.position = list(position)
        self.yaw = yaw
        self.speed = 0.
        self.now = 0.
        self.yaws = [yaw]

    def snapshot(self):
        current = state(self.now, tuple(self.position), self.speed, wrapped(self.yaw))
        current.update(stopping_distance=0., decision_horizon=.1)
        return current

    def advance(self, order):
        if order['brake']:
            self.speed = 0.
        else:
            throttle, turn = order['throttle'], order['turn']
            self.speed = 4. * throttle
            change = turn * (-1. if throttle < 0. else 1.) * .8 * .1
            travel = self.speed if throttle else .9 * abs(turn)
            self.position[0] += math.sin(self.yaw + change / 2.) * travel * .1
            self.position[2] += math.cos(self.yaw + change / 2.) * travel * .1
            self.yaw += change
        self.yaws.append(self.yaw)
        self.now += .1


class CoverReturnMotionTests(unittest.TestCase):
    def setUp(self):
        self.nav = controller()

    def motion(self, current, goal=(0., 0., -12.), clear=lambda *args: True,
               phase='return'):
        return self.nav._cover_motion(current, clear, goal, phase)

    def test_report_return_pose_aligns_rear_instead_of_turning_toward_cover(self):
        # visible-client.log: 02:42:26.314. The actual rear error was -29.61
        # degrees, outside the old 20-degree straight-reverse exception.
        current = state(244.531005859375, REPORT_RETURN_POSITION, yaw=REPORT_RETURN_YAW)
        error = wrapped(bearing(current['position'], REPORT_COVER) -
                        current['yaw'] - math.pi)
        self.assertAlmostEqual(-29.613123086545816, math.degrees(error))
        order = self.motion(current, REPORT_COVER)
        self.assertEqual('cover_return', order['combat_mode'])
        self.assertEqual(0., order['throttle'])
        self.assertLess(order['turn'], 0.)
        self.assertFalse(order['brake'])
        self.assertFalse(order['holding'])

    def test_return_alignment_retains_reverse_intent_on_both_sides(self):
        for error in (-.52, -.36, .36, .52):
            with self.subTest(rear_error=error):
                self.nav = controller()
                current = state(yaw=-error)
                order = self.motion(current)
                self.assertEqual(0., order['throttle'])
                self.assertGreater(order['turn'] * error, 0.)
                self.assertFalse(order['brake'])

    def test_aligned_return_uses_reverse_steering_sign(self):
        for error in (-.12, .12):
            with self.subTest(rear_error=error):
                self.nav = controller()
                current = state(yaw=-error, speed=-1.)
                order = self.motion(current)
                self.assertLess(order['throttle'], 0.)
                self.assertLess(order['turn'] * error, 0.)
                # The existing motion/traffic contract reverses steering
                # while backing. A small step must reduce the rear error.
                next_yaw = current['yaw'] - order['turn'] * .1
                self.assertLess(abs(wrapped(-next_yaw)), abs(error))

    def test_return_rechecks_the_actual_rear_corridor_on_every_decision(self):
        for now, yaw, blocked in ((1., .12, False), (1.1, .08, True), (1.2, .06, False)):
            with self.subTest(now=now, blocked=blocked):
                current = state(now, yaw=yaw, speed=-1.)
                actual_rear = yaw + math.pi
                probes = []

                def clear(heading, reach):
                    probes.append((heading, reach))
                    # The geometric goal ray is clear, but it is not the
                    # trajectory of a hull that has not finished steering.
                    return not (blocked and abs(wrapped(heading - actual_rear)) < 1.e-6)

                order = self.motion(current, clear=clear)
                self.assertTrue(any(abs(wrapped(heading - actual_rear)) < 1.e-6
                                    and reach > 0. for heading, reach in probes), probes)
                if blocked:
                    self.assertEqual(0., order['throttle'])
                    self.assertTrue(order['brake'])
                else:
                    self.assertLess(order['throttle'], 0.)

    def test_return_brakes_forward_momentum_before_backing(self):
        current = state(speed=3.)
        current.update(stopping_distance=2., decision_horizon=.1)
        order = self.motion(current)
        self.assertEqual((0., 0., True),
                         (order['throttle'], order['turn'], order['brake']))

    def test_reverse_arrival_brake_uses_speed_magnitude_and_decision_horizon(self):
        for stopping in (1.4, lambda: 1.4):
            with self.subTest(callable_stopping=callable(stopping)):
                self.nav = controller()
                current = state(speed=-2.)
                current.update(stopping_distance=stopping, decision_horizon=.1)
                # 3m - 1.5m arrival radius exceeds 1.4m braking alone, but
                # lies inside braking plus this decision's 0.2m travel.
                order = self.motion(current, (0., 0., -3.))
                self.assertEqual((0., 0., True),
                                 (order['throttle'], order['turn'], order['brake']))

    def test_cover_phase_change_cannot_inherit_forward_escape_or_detour(self):
        self.nav.driver.forward_until = 100.
        self.nav.driver.forward_origin = (0., 0., 0.)
        self.nav.driver.recovery_heading = .8
        self.nav.driver.recovery_origin = (0., 0., 0.)
        returning = self.motion(state(1.))
        self.assertLess(returning['throttle'], 0.)
        self.assertEqual(0., returning['turn'])
        peeking = self.motion(state(2.), (0., 0., 12.), phase='peek')
        self.assertGreater(peeking['throttle'], 0.)
        self.assertEqual(0., peeking['turn'])

    def test_cover_return_does_not_change_the_default_route_direction(self):
        returning = self.motion(state(1.))
        self.assertLess(returning['throttle'], 0.)
        route = self.nav._drive_goal(state(2.), lambda *args: True, (0., 0., -12.),
                                    ('ordinary_route',), mode='route')
        self.assertEqual(0., route['throttle'])
        self.assertNotEqual(0., route['turn'])

    def test_peek_brakes_actual_reverse_speed_before_applying_forward_throttle(self):
        returning = self.motion(state(1., speed=-3.))
        self.assertLess(returning['throttle'], 0.)
        peeking = self.motion(state(2., speed=-3.), (0., 0., 12.), phase='peek')
        self.assertEqual((0., 0., True),
                         (peeking['throttle'], peeking['turn'], peeking['brake']))
        stopped = self.motion(state(2.1), (0., 0., 12.), phase='peek')
        self.assertGreater(stopped['throttle'], 0.)
        self.assertFalse(stopped['brake'])

    def test_short_terminal_leg_does_not_require_clearance_past_its_goal(self):
        for phase, direction in (('return', -1.), ('peek', 1.)):
            with self.subTest(phase=phase):
                self.nav = controller()
                goal = (0., 0., 2. * direction)
                clear = lambda heading, reach: reach <= 2.
                order = self.motion(state(1.), goal, clear, phase)
                self.assertGreater(order['throttle'] * direction, 0.)
                self.assertFalse(order['brake'])
                # Limiting a terminal probe to its goal does not waive the
                # earlier stopping-envelope decision for a moving vehicle.
                moving = state(1.1, speed=2. * direction)
                moving.update(stopping_distance=3., decision_horizon=.1)
                braking = self.motion(moving, goal, clear, phase)
                self.assertEqual((0., 0., True),
                                 (braking['throttle'], braking['turn'], braking['brake']))


class CoverLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.nav = controller()
        self.goal, self.peek = (0., 0., -12.), (0., 0., 0.)
        self.entity = types.SimpleNamespace(
            typeDescriptor=types.SimpleNamespace(maxHealth=1000), health=200)
        self.target = types.SimpleNamespace(id=5, position=(2., 0., 118.))
        self.gun = types.SimpleNamespace(clip_size=1, clip=1, reload_time=0.)
        self.fire_seq = 0
        # Candidate geometry and observed exposure are the native seams. All
        # phase, arrival, timeout, and driving decisions remain real methods.
        self.nav._cover_candidate = lambda *args: dict(
            target=self.target.id, goal=self.goal, peek=self.peek)
        self.nav.cover_search.current_exposure = lambda *args: 0.
        self.nav.cover_search.peek_clear = lambda *args: True

    def apply(self, current, clear=lambda *args: True):
        self.nav.set_context(dict(gun_ready=True, fire_clear=True,
                                  fire_seq=self.fire_seq, supported=True))
        return self.nav.withdrawal(current, self.target, self.entity, self.gun,
                                   clear, lambda *args: True)

    def enter_return(self, yaw):
        self.apply(state(1., self.goal))
        held = self.apply(state(1.1, self.goal))
        self.assertEqual('cover_hold', held['combat_mode'])
        peeking = self.apply(state(2.2, self.goal))
        self.assertEqual('cover_peek', peeking['combat_mode'])
        ready = self.apply(state(3., self.peek, yaw=yaw))
        self.assertTrue(ready['holding'])
        self.fire_seq += 1
        returning = self.apply(state(3.1, self.peek, yaw=yaw))
        self.assertEqual('cover_return', returning['combat_mode'])
        return returning

    def test_approach_keeps_its_admitted_gear_across_the_nearest_direction_boundary(self):
        heading = math.pi / 2. + .05
        self.goal = (12. * math.sin(heading), 0., 12. * math.cos(heading))
        first = self.apply(state(1., self.peek))
        admitted = self.nav.cover_move
        self.assertEqual('approach', admitted['phase'])
        self.assertEqual(0., first['throttle'])
        self.assertLess(first['turn'], 0.)
        # A small yaw change makes the front momentarily closer. Rechoosing
        # gear here would reverse the pivot and repeatedly cross this border.
        perturbed = self.apply(state(1.1, self.peek, yaw=.1))
        self.assertIs(admitted, self.nav.cover_move)
        self.assertEqual(0., perturbed['throttle'])
        self.assertLess(perturbed['turn'], 0.)

    def test_stationary_return_alignment_does_not_renew_cover_progress(self):
        returning = self.enter_return(.5)
        self.assertLess(returning['turn'], 0.)
        # Rotation without translation is not progress toward the cover.
        for now, yaw in ((5., .2), (7.5, -.2), (11.09, .3)):
            order = self.apply(state(now, self.peek, yaw=yaw))
            self.assertIsNotNone(order)
            self.assertLessEqual(order['throttle'], 0.)
        self.assertIsNone(self.apply(state(11.2, self.peek, yaw=.3)))
        self.assertIsNone(self.nav.cover_move)
        self.assertEqual('cover_movement_timeout', self.nav.receipt['status'])
        # The failed owner must not be recreated on the very next frame.
        self.assertIsNone(self.apply(state(11.3, self.peek, yaw=.3)))

    def test_blocked_return_cannot_use_a_forward_escape_before_its_timeout(self):
        self.assertLess(self.enter_return(0.)['throttle'], 0.)

        def clear(heading, reach):
            return abs(wrapped(heading - math.pi)) > .1

        for now in (3.2, 6.3, 10.9):
            order = self.apply(state(now, self.peek), clear)
            self.assertIsNotNone(order)
            self.assertEqual((0., 0., True),
                             (order['throttle'], order['turn'], order['brake']))
        self.assertIsNone(self.apply(state(11.2, self.peek), clear))
        self.assertIsNone(self.nav.cover_move)
        self.assertEqual('cover_movement_timeout', self.nav.receipt['status'])

    def test_repeated_report_cover_cycles_do_not_accumulate_complete_turns(self):
        self.goal = (REPORT_COVER[0], 0., REPORT_COVER[2])
        self.peek = (REPORT_PEEK[0], 0., REPORT_PEEK[2])
        motion = SyntheticMotion((117.0230209934184, 0., 58.411748438625324),
                                 1.5924508041877266)
        phases, forward_returns = [], []
        previous, fired, completed = None, False, 0
        for unused in range(2000):
            order = self.apply(motion.snapshot())
            self.assertIsNotNone(order, self.nav.receipt)
            self.assertIsNotNone(self.nav.cover_move)
            phase = self.nav.cover_move['phase']
            if phase != previous:
                phases.append(phase)
                if phase == 'peek':
                    fired = False
                if previous == 'return' and phase == 'hold':
                    completed += 1
            if phase == 'return' and order['throttle'] > 0.:
                forward_returns.append((motion.now, order['throttle'], order['turn']))
            if phase == 'peek' and order.get('holding') and not fired:
                # A committed shot, not an aim-progress flag, starts return
                # on the next real withdrawal decision.
                self.fire_seq += 1
                fired = True
            previous = phase
            if completed == 6:
                break
            motion.advance(order)
        self.assertEqual(6, completed)
        self.assertEqual(6, self.fire_seq)
        self.assertEqual(['approach', 'hold'] + ['peek', 'return', 'hold'] * 6, phases)
        yaw_range = max(motion.yaws) - min(motion.yaws)
        self.assertLess(yaw_range, 2. * math.pi,
                        'Hull yaw spanned %.2f degrees across six cover cycles' %
                        math.degrees(yaw_range))
        self.assertFalse(forward_returns, forward_returns[:3])
        self.assertTrue(order['brake'])
        self.assertLessEqual(math.hypot(motion.position[0] - self.goal[0],
                                       motion.position[2] - self.goal[2]), 1.5)


if __name__ == '__main__':
    unittest.main()
