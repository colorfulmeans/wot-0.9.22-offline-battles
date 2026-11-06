"""Route steering and checked detours preserve the current player's objective.

The opening pose and target are from report 133716, 13:19:52.876. Clear-world
and installed-physics inputs are explicit seams. The Bot driver is used only
as an independent test reference; player runtime never calls it. These tests
do not claim to replay the client's native suspension or steering dynamics.
"""
import json
import math
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.ai.driver import LocalDriver, FIRST_CANDIDATE_OFFSET
from gui.mods.offline_lan_0922.player_control.driving import Driver, angle


POSITION = (-38.782702541859024, .25004818172341164, -106.43755713094941)
TARGET = (-78.8077, .25, -98.9527)
YAW = -.927706572266834
SPEED = 4.012412739670818
SHAPE = (1.5080519914627075, 2.9235379695892334,
         .0026149998884648085, 1.6808550357818604)


def goal(distance, bearing, height=0.):
    return (distance * math.sin(bearing), height, distance * math.cos(bearing))


class PlayerSteeringProgressTests(unittest.TestCase):
    def test_captured_far_clear_point_keeps_forward_like_actual_bot_driver(self):
        reference = LocalDriver()
        bot = reference.drive(1, 0, POSITION, YAW, SPEED, .1, TARGET, (),
            lambda *args: True, half_length=SHAPE[1], turn_speed_limit=.55)
        self.assertEqual([], reference.states[1]['pedal_observation']['gates'])
        self.assertEqual(1., bot['throttle'])
        driver = Driver()
        # Keep this call usable against the old driver as a behavioral
        # countercheck, independently of the newly exposed optional inputs.
        player = driver.drive(POSITION, YAW, SPEED, TARGET, 0., lambda *args: True)
        self.assertAlmostEqual(40.718834803993545, driver.receipt['distance'])
        self.assertAlmostEqual(-.45822045895848396, driver.receipt['delta'])
        self.assertEqual(1., player['throttle'])
        self.assertFalse(player['brake'])
        self.assertAlmostEqual(bot['turn'], player['turn'])

    def test_distant_moderate_correction_drives_from_rest_and_at_speed(self):
        for speed in (0., 4.):
            for bearing in (-.8, -.458, .458, .8):
                with self.subTest(speed=speed, bearing=bearing):
                    command = Driver().drive((0., 0., 0.), 0., speed,
                        goal(40.7, bearing), 0., lambda *args: True,
                        half_length=3., turn_speed_limit=.55)
                    self.assertEqual(1., command['throttle'])
                    self.assertFalse(command['brake'])
                    self.assertGreater(command['turn'] * bearing, 0.)

    def test_near_corner_rear_goal_and_steep_entry_still_align(self):
        for label, target in (('near_corner', goal(6., .5)),
                              ('rear', goal(40., 2.)),
                              ('uphill', goal(40., 1., 20.)),
                              ('downhill', goal(40., -1., -20.))):
            for speed in (0., 4.):
                with self.subTest(label=label, speed=speed):
                    command = Driver().drive((0., 0., 0.), 0., speed,
                        target, 0., lambda *args: True, half_length=3.)
                    self.assertEqual(0., command['throttle'])
                    if speed:
                        self.assertTrue(command['brake'])
                    else:
                        self.assertNotEqual(0., command['turn'])

    def test_long_hull_retains_near_corner_gate_beyond_eight_metres(self):
        short = Driver().drive((0., 0., 0.), 0., 0., goal(10., .5), 0.,
                               lambda *args: True, half_length=3.)
        long = Driver().drive((0., 0., 0.), 0., 0., goal(10., .5), 0.,
                              lambda *args: True, half_length=6.)
        self.assertGreater(short['throttle'], 0.)
        self.assertEqual(0., long['throttle'])

    def test_installed_turn_radius_alignment_survives_braking_to_rest(self):
        driver = Driver()
        target = goal(15., .35)
        # At 4 m/s and .4 rad/s, the 10 m radius admits the near-point
        # alignment. At rest the geometric radius shrinks, but its owner stays.
        first = driver.drive((0., 0., 0.), 0., 4., target, 0.,
                             lambda *args: True, turn_speed_limit=.4)
        self.assertEqual(0., first['throttle'])
        self.assertTrue(first['brake'])
        for now, remaining in ((.1, .35), (.2, .20), (.3, .121)):
            command = driver.drive((0., 0., 0.), .35 - remaining, 0., target, now,
                                   lambda *args: True, turn_speed_limit=.4)
            self.assertEqual(0., command['throttle'])
        aligned = driver.drive((0., 0., 0.), .35 - .119, 0., target, .4,
                               lambda *args: True, turn_speed_limit=.4)
        self.assertGreater(aligned['throttle'], 0.)
        self.assertFalse(aligned['brake'])

    def test_nearby_rebased_tip_cannot_move_the_alignment_heading(self):
        driver = Driver()
        first = goal(7., .6)
        driver.drive((0., 0., 0.), 0., 0., first, 0., lambda *args: True,
                     turn_speed_limit=.5)
        second = (first[0] + 1., first[1], first[2])
        command = driver.drive((0., 0., 0.), .6 - .119, 0., second, .1,
                               lambda *args: True, turn_speed_limit=.5)
        self.assertGreater(command['throttle'], 0.)
        self.assertAlmostEqual(.119 / .58, command['turn'])

    def test_rebased_clear_corner_replaces_a_now_blocked_alignment_target(self):
        from test_player_stationary_waypoint import captured_pit_neighbours
        from gui.mods.offline_lan_0922.player_control.traffic import Traffic, body
        # The ending pose/points come from the captured-geometry opening
        # scenario. The exact recorded hulls prove the old four-metre sweep
        # has become blocked while its nearby replacement remains clear.
        position = (-58.09491024863001, .25, -107.24335894937805)
        yaw = 3.286647294765138
        old = (-59.46679569442907, .302, -103.48060322050814)
        replacement = (-58.35400506706844, .302, -102.83738538527099)
        peers = captured_pit_neighbours()
        request = ('route', 1, 'class_mt_rim_west', 1)
        traverse = .7783950319281508
        old_heading = math.atan2(old[0]-position[0], old[2]-position[2])
        old_distance = math.hypot(old[0]-position[0], old[2]-position[2])
        heading = math.atan2(replacement[0]-position[0], replacement[2]-position[2])
        reach = math.hypot(replacement[0]-position[0], replacement[2]-position[2])
        traffic = Traffic(body(2130706436, position, yaw, SHAPE), peers)
        self.assertFalse(traffic.clear(old_heading, old_distance))
        self.assertEqual([2130706463], traffic.receipt['blockers'])
        self.assertTrue(traffic.clear(heading, reach))
        self.assertLess(math.hypot(replacement[0]-old[0], replacement[2]-old[2]), 2.)

        # Admit the original alignment from a proved approach with the same
        # fourteen hulls. No private Driver state is manufactured for the
        # subsequent same-request handoff, and no native dynamics are implied.
        start = (old[0]-4.*math.sin(.4), .25, old[2]-4.*math.cos(.4))
        approach = Traffic(body(2130706436, start, .9, SHAPE), peers)
        self.assertTrue(approach.clear(.4, 4.))
        driver = Driver()
        first = driver.drive(start, .9, 0., old, 0., approach.clear,
                             request_key=request, turn_speed_limit=traverse)
        self.assertEqual(0., first['throttle'])
        self.assertEqual(old, driver.alignment_target)
        driver.drive(position, yaw, 0., replacement, .1, traffic.clear,
                     request_key=request, turn_speed_limit=traverse)
        # Once the hull faces the new checked corner, it may advance. The old
        # latch instead keeps turning back toward the rejected T110E5 sweep.
        facing = Traffic(body(2130706436, position, heading, SHAPE), peers)
        moving = driver.drive(position, heading, 0., replacement, .2, facing.clear,
                              request_key=request, turn_speed_limit=traverse)
        self.assertGreater(moving['throttle'], 0.)
        self.assertAlmostEqual(0., moving['turn'])
        self.assertFalse(moving['brake'])

    def test_new_far_leg_releases_near_point_alignment(self):
        driver = Driver()
        driver.drive((0., 0., 0.), 0., 0., goal(6., .6), 0., lambda *args: True,
                     turn_speed_limit=.5)
        command = driver.drive((0., 0., 0.), 0., 0., goal(40., .458), .1,
                               lambda *args: True, turn_speed_limit=.5)
        self.assertGreater(command['throttle'], 0.)
        self.assertFalse(command['brake'])

    def test_closed_forward_corridor_cannot_gain_throttle_from_far_point_rule(self):
        queries = []
        def clear(heading, reach):
            queries.append((heading, reach))
            return abs(angle(heading)) > .7
        command = Driver().drive((0., 0., 0.), 0., 0., goal(40., .458), 0., clear)
        self.assertEqual(0., command['throttle'])
        self.assertTrue(any(abs(heading) < 1.e-9 for heading, unused in queries))

    def test_cover_fixed_gears_retain_their_alignment_and_steering_signs(self):
        for direction, base in ((1., 0.), (-1., math.pi)):
            for delta in (.2, .458):
                with self.subTest(direction=direction, delta=delta):
                    command = Driver().drive((0., 0., 0.), 0., 0.,
                        goal(40., base + delta), 0., lambda *args: True,
                        terminal=True, travel_direction=direction,
                        motion_key=('player_cover', direction),
                        half_length=3., turn_speed_limit=.55)
                    if delta > .30:
                        self.assertEqual(0., command['throttle'])
                        self.assertGreater(command['turn'], 0.)
                    else:
                        self.assertGreater(command['throttle'] * direction, 0.)
                        self.assertAlmostEqual(delta * direction, command['turn'])

    def test_cover_reverse_brakes_opposing_motion_before_changing_gear(self):
        command = Driver().drive((0., 0., 0.), 0., 4., goal(8., math.pi), 0.,
            lambda *args: True, terminal=True, travel_direction=-1.,
            motion_key=('player_cover', 'return'), turn_speed_limit=.55)
        self.assertEqual((0., 0., True),
                         (command['throttle'], command['turn'], command['brake']))

    def test_real_control_passes_installed_traverse_and_keeps_clear_route_forward(self):
        from test_player_control import PlayerRegressionTests
        from test_player_navigation_migration import controller
        control, unused = PlayerRegressionTests().aim_controller()
        owner = control.owner
        entity = owner._server_entity(1)
        entity.typeDescriptor.type = types.SimpleNamespace(tags=('mediumTank',))
        control.features = {'drive'}
        control.navigation = controller('mediumTank')
        self.addCleanup(control.navigation.close)
        route = dict(id='captured_clear_route', waypoints=[
            (POSITION[0], POSITION[2]), (TARGET[0], TARGET[2])])
        control.navigation.routes = control.navigation.selection = [route]
        control.navigation.route, control.navigation.index = route, 1
        control.publish_status = mock.Mock()
        owner.local_pose = lambda: (POSITION, YAW)
        owner._clock = lambda: 1.
        owner._local_speed = SPEED
        owner._local_physics = dict(rotSpd=.55)
        owner._collision_shape = lambda unused: SHAPE
        control.direction_clear = mock.Mock(return_value=True)
        # The live ally is well behind the swept driving corridor; merely
        # observing a teammate must not reinstate the old far-angle brake.
        neighbour = dict(id=37, actor_key=('bot', 7), alive=True, team=1,
            position=(-20., .25, -180.), yaw=0., collision_shape=SHAPE,
            health=1000, max_health=1000, class_tag='heavyTank', speed=0.)
        control._contacts = lambda unused: ([], [neighbour], {})
        with mock.patch.object(control.navigation.driver, 'drive',
                               wraps=control.navigation.driver.drive) as drive, \
             mock.patch('gui.mods.offline_lan_0922.player_control.traffic_laws.traffic_stopping_distance',
                        return_value=.9):
            control.update(.1, 1.)
        self.assertAlmostEqual(.55, drive.call_args.kwargs['turn_speed_limit'])
        self.assertAlmostEqual(SHAPE[1], drive.call_args.kwargs['half_length'])
        self.assertEqual('route', control.last_order['combat_mode'])
        self.assertGreater(owner._sender.forward, 0.)
        self.assertLess(owner._sender.turn, 0.)
        self.assertFalse(owner._sender.handbrake)
        control.direction_clear.assert_called()
        owner._sender.send_current.assert_called()


class PlayerProgressFrontierTests(unittest.TestCase):
    def test_captured_pivot_drift_and_returning_angles_cannot_renew_progress(self):
        from test_player_stationary_waypoint import captured_pit_neighbours
        from gui.mods.offline_lan_0922.player_control.traffic import Traffic, body
        # Every third observation from the integrated opening's 39.27-49.39s
        # Driver window. This is a captured-geometry simulation, not a claim
        # that these exact controls were logged by the Windows client. The
        # native report independently confirms the prerequisite: visible
        # lines 2328->2349 and 2349->2368 each move the hull centre ~.99m during
        # ~48 degrees of pivot while both endpoint longitudinal speeds are 0.
        samples = (
            (0., -66.18058253619, -113.03440212557, -.65203156679),
            (.33, -66.32664798379, -112.78452447565, -.40412831702),
            (.66, -66.41032592625, -112.48873512672, -.14725795649),
            (.99, -66.41611166243, -112.18139189473, .10961240405),
            (1.32, -66.34362553018, -111.88266275717, .36648276459),
            (1.65, -66.27212304283, -111.62783135510, .16341506866),
            (1.98, -66.26137249880, -111.32062171528, -.09345529188),
            (2.31, -66.31305686876, -111.06090500071, -.23288141000),
            (2.64, -66.36186303685, -110.84431459310, -.14725795649),
            (2.97, -66.36764877304, -110.53697136110, .10961240405),
            (3.3, -66.29516264078, -110.23824222354, .36648276459),
            (3.63, -66.22366015344, -109.98341082147, .16341506866),
            (3.96, -66.21290960940, -109.67620118165, -.09345529188),
            (4.29, -66.26459397937, -109.41648446709, -.23288141000),
            (4.62, -66.29664216537, -109.11076196093, .02398895054),
            (4.95, -66.24996856031, -108.80692827026, .28085931107),
            (5.28, -66.16683021582, -108.55525399866, .24903852217),
            (5.61, -66.12984683494, -108.25008918002, -.00783183837),
            (5.94, -66.17160548657, -107.94554106886, -.26470219890),
            (6.27, -66.21684581007, -107.68476345804, -.06163450297),
            (6.6, -66.19632670494, -107.37805137266, .19523585756),
            (6.93, -66.09855914397, -107.08661554607, .45210621810),
            (7.26, -65.95899988103, -106.86156608917, .59153233622),
            (7.59, -65.82167882194, -106.58654561043, .33466197568),
            (7.92, -65.75873357767, -106.28566152441, .07779161514),
            (8.25, -65.76540333878, -106.02093608134, -.06163450297),
            (8.58, -65.74488423365, -105.71422399596, .19523585756),
            (8.91, -65.64711667269, -105.42278816937, .45210621810),
            (9.24, -65.47851619970, -105.16575272920, .70897657863),
            (9.57, -65.25014644060, -104.95998443688, .96584693917),
            (9.9, -64.97699310413, -104.81898588449, 1.22271729971),
        )
        driver = Driver()
        target = (-70.26604586852287, .26, -113.85484658042944)
        modes = []
        for now, x, z, yaw in samples:
            position = (x, .25, z)
            traffic = Traffic(body(2130706436, position, yaw, SHAPE),
                              captured_pit_neighbours())
            command = driver.drive(position, yaw, 0., target, now, traffic.clear,
                request_key=('route', 1, 'class_mt_rim_west', 1), half_length=SHAPE[1],
                turn_speed_limit=.7783950319281508)
            modes.append(command['recovery_mode'])
            if command['recovery_mode'] == 'reverse_clearance':
                self.assertTrue(traffic.clear(yaw+math.pi, 4.))
                self.assertLess(command['throttle'], 0.)
                self.assertEqual(0., command['turn'])
                break  # The recorded no-recovery trajectory no longer applies.
        self.assertIn('reverse_clearance', modes)

    def test_real_slow_forward_progress_does_not_trigger_recovery(self):
        driver = Driver()
        for now in range(10):
            command = driver.drive((0., 0., now*.6), 0., .6, (0., 0., 30.),
                                   now, lambda *args: True, request_key='route')
            self.assertEqual('travel', command['recovery_mode'])
            self.assertGreater(command['throttle'], 0.)

    def test_continuous_new_alignment_supports_a_slow_stationary_turn(self):
        driver = Driver()
        target = goal(6., 2.5)
        for step in range(9):
            command = driver.drive((0., 0., 0.), step*.22, 0., target,
                step*2., lambda *args: True, request_key='route', turn_speed_limit=.11)
            self.assertEqual('align', command['recovery_mode'])
            self.assertEqual(0., command['throttle'])
            self.assertGreater(command['turn'], 0.)

    def test_first_checked_detour_can_finish_a_slow_stationary_alignment(self):
        driver = Driver()
        for step in range(21):
            now, yaw = step*.22, step*.022
            def clear(heading, reach):
                # The straight goal is blocked, the +.55 fan is proved, and
                # a rear escape exists if the progress clock truly expires.
                return (abs(angle(heading-.55)) < .12 or
                        reach <= 4. and abs(angle(heading-yaw-math.pi)) < .01)
            command = driver.drive((0., 0., 0.), yaw, 0., (0., 0., 30.), now,
                clear, request_key='route', turn_speed_limit=.1)
            self.assertNotIn(command['recovery_mode'], ('reverse_clearance', 'forward_clearance'))
            self.assertGreater(command['turn'], 0.)
        self.assertGreater(command['throttle'], 0.)

    def test_distance_credit_does_not_grant_the_same_alignment_again(self):
        driver = Driver()
        target = (0., 0., 30.)
        samples = ((0., 0., .2, 0.), (1., 1.2, 1.4, 1.),
                   (2., 1.2, .9, 0.), (3., 1.2, 1.4, 0.), (4.1, 1.2, .9, 0.))
        for now, z, yaw, speed in samples:
            command = driver.drive((0., 0., z), yaw, speed, target, now,
                                   lambda *args: True, request_key='route')
        self.assertEqual('reverse_clearance', command['recovery_mode'])
        self.assertLess(command['throttle'], 0.)

    def test_changing_nearby_connectors_cannot_credit_target_motion(self):
        driver = Driver()
        modes = []
        for step in range(6):
            command = driver.drive((0., 0., 0.), .25 if step % 2 else 0., 0.,
                goal(10., 2.4-step*.4), step*.9, lambda *args: True,
                request_key='route', turn_speed_limit=.55)
            modes.append(command['recovery_mode'])
        self.assertIn('reverse_clearance', modes)

    def test_reached_corner_starts_the_next_legitimate_slow_alignment(self):
        driver = Driver()
        for now, z in ((0., 0.), (1., 2.)):
            driver.drive((0., 0., z), 0., 2., (0., 0., 6.), now,
                         lambda *args: True, request_key='route', turn_speed_limit=.11)
        # The pathfinder consumes the prior corner before calling the driver
        # again. Its new point does not require a fake intermediate hold call.
        for step in range(5):
            command = driver.drive((0., 0., 4.6), step*.22, 0., (5., 0., 6.),
                2.+step*2., lambda *args: True, request_key='route', turn_speed_limit=.11)
            self.assertEqual('align', command['recovery_mode'])
            self.assertGreater(command['turn'], 0.)

    def test_new_request_owns_a_fresh_progress_episode(self):
        driver = Driver()
        driver.drive((0., 0., 0.), 0., 0., (0., 0., 30.), 0.,
                     lambda *args: True, request_key='old_route')
        driver.drive((0., 0., 0.), 0., 0., (0., 0., 30.), 2.9,
                     lambda *args: True, request_key='old_route')
        for now in (3., 3.2, 5.8):
            command = driver.drive((0., 0., 0.), 0., 0., goal(6., 2.5), now,
                lambda *args: True, request_key='new_contact', turn_speed_limit=.55)
            self.assertEqual('align', command['recovery_mode'])
        recovered = driver.drive((0., 0., 0.), 0., 0., goal(6., 2.5), 6.1,
            lambda *args: True, request_key='new_contact', turn_speed_limit=.55)
        self.assertEqual('reverse_clearance', recovered['recovery_mode'])

    def test_nonprogress_signal_is_not_an_active_or_expired_recovery_lease(self):
        driver = Driver()
        target = (0., 0., 30.)
        driver.drive((0., 0., 0.), 0., 0., target, 0., lambda *args: True)
        stalled = driver.drive((0., 0., 0.), 0., 0., target, 3.1, lambda *args: True)
        self.assertEqual('reverse_clearance', stalled['recovery_mode'])
        self.assertTrue(getattr(driver, 'nonprogress_triggered', False))
        driver.drive((0., 0., 0.), 0., 0., target, 3.2, lambda *args: True)
        self.assertFalse(driver.nonprogress_triggered)
        driver.drive((0., 0., 0.), 0., 0., target, 4.2, lambda *args: True)
        self.assertTrue(driver.replan)
        self.assertFalse(driver.nonprogress_triggered)

    def test_completed_external_translation_cancels_both_own_gear_leases(self):
        for direction in (-1., 1.):
            with self.subTest(direction=direction):
                driver = Driver()
                target = (0., 0., 30. if direction < 0. else -30.)
                clear = (lambda *args: True) if direction < 0. else (
                    lambda heading, reach: abs(angle(heading)) < .1)
                driver.drive((0., 0., 0.), 0., 0., target, 0., clear, request_key='route')
                if direction < 0.:
                    # Preserve an earned best and another visited connector.
                    driver.drive((0., 0., 1.2), 0., 1.2, target, 1., clear, request_key='route')
                    driver.drive((0., 0., 1.2), 0., 0., (10., 0., 30.), 1.1,
                                 clear, request_key='route')
                    driver.drive((0., 0., 1.2), 0., 0., target, 1.2, clear, request_key='route')
                position = (0., 0., 1.2 if direction < 0. else 0.)
                now = 4.1 if direction < 0. else 3.1
                command = driver.drive(position, 0., 0., target, now, clear, request_key='route')
                self.assertEqual('reverse_clearance' if direction < 0. else 'forward_clearance',
                                 command['recovery_mode'])
                points = [(row['goal'], row['best']) for row in driver.progress['points']]
                completed = (0., 0., position[2] + direction*2.)
                finish = getattr(driver, 'complete_translation_escape', None)
                self.assertTrue(callable(finish))
                self.assertTrue(finish(completed, 0., now+.4))
                self.assertEqual((0., 0.), (driver.reverse_until, driver.forward_until))
                self.assertIsNone(driver.anchor)
                self.assertIsNone(driver.alignment_target)
                self.assertFalse(driver.nonprogress_triggered)
                self.assertEqual('route', driver.request_key)
                self.assertEqual(points, [(row['goal'], row['best']) for row in driver.progress['points']])
                resumed = driver.drive(completed, 0., 0., target, now+.51,
                                       clear, request_key='route')
                self.assertNotIn(resumed['recovery_mode'], ('reverse_clearance', 'forward_clearance'))
                self.assertGreaterEqual(resumed['throttle'], 0.)
                before = driver.anchor
                self.assertFalse(finish(completed, 0., now+.4))
                self.assertEqual(before, driver.anchor)


class PlayerDetourOwnershipTests(unittest.TestCase):
    # Report 144204, 14:40:43.900: a newly selected northward contact leg
    # inherited a route detour to the southwest. The first call below admits
    # that detour through the real driver; its world proof is an explicit
    # seam, not a replay of the client's unlogged intermediate probe.
    position = (-35.63776755158413, .24998958359965545, -108.64678188285771)
    target = (-34.83267593383789, .2500002384185791, -105.59831237792969)
    yaw = -1.5568264391707969
    old_heading = -1.9308219842405652
    traverse = .7783950319281508

    def admit(self, driver, position=(0., 0., 0.), heading=0., now=0.):
        target = (position[0] + 30. * math.sin(heading), position[1],
                  position[2] + 30. * math.cos(heading))
        proof = lambda yaw, reach: abs(angle(yaw - heading - .55)) < .001
        command = driver.drive(position, heading, 0., target, now, proof)
        self.assertEqual('detour_align', command['recovery_mode'])
        self.assertAlmostEqual(heading + .55, driver.recovery_heading)
        return target

    def test_captured_clear_goal_heading_survives_blocked_forward_and_side_fan(self):
        from test_player_stationary_waypoint import captured_pit_neighbours
        from gui.mods.offline_lan_0922 import tank_collision
        from gui.mods.offline_lan_0922.player_control.pathfinding import PlayerPathfinder
        from gui.mods.offline_lan_0922.player_control.traffic import Traffic, body
        # The closed-loop opening reaches this pose at 26.40 s after the
        # recovery handoff and straight-corner corrections. Its map and peer
        # hulls are from report 144204; the pose is not a new native sample.
        position = (-66.1242419287645, .25, -114.04324171108934)
        yaw = -.7281900981989412
        target = (-70., .25, -94.)
        heading = math.atan2(target[0]-position[0], target[2]-position[2])
        nav = PlayerPathfinder(lambda *unused: .25, lambda *unused: False,
            baked_graph=json.loads((ROOT / 'navgraphs/100_thepit.json').read_text()))
        self.addCleanup(nav.close)
        peers = captured_pit_neighbours()
        traffic = Traffic(body(2130706436, position, yaw, SHAPE), peers)

        def clear(bearing, reach):
            end = (position[0]+math.sin(bearing)*reach, .25,
                   position[2]+math.cos(bearing)*reach)
            return bool(traffic.clear(bearing, reach) and
                        nav.grid.dry_segment_clear(position, end, 0.))

        self.assertFalse(clear(yaw, 8.))
        for offset in (.55, -.55, 1., -1.):
            self.assertFalse(clear(heading+offset, 5.))
        self.assertTrue(clear(heading, 5.))
        self.assertTrue(clear(heading, 8.))
        self.assertEqual(1., tank_collision.rotation_fraction(
            position, yaw, heading, SHAPE, traffic.neighbours))
        driver = Driver()
        command = driver.drive(position, yaw, 0., target, 0., clear,
            half_length=SHAPE[1], turn_speed_limit=self.traverse,
            request_key=('route', 1, 'class_mt_rim_west', 1))
        self.assertEqual('detour_align', command['recovery_mode'])
        self.assertEqual(0., command['throttle'])
        self.assertGreater(command['turn'], 0.)
        self.assertFalse(command['brake'])
        self.assertAlmostEqual(heading, driver.recovery_heading)

        # The full hull can pivot into that heading, then use the same
        # checked five-metre admission without another sideways candidate.
        traffic = Traffic(body(2130706436, position, heading, SHAPE), peers)
        moving = driver.drive(position, heading, 0., target, .1, clear,
            half_length=SHAPE[1], turn_speed_limit=self.traverse,
            request_key=('route', 1, 'class_mt_rim_west', 1))
        self.assertGreater(moving['throttle'], 0.)
        self.assertEqual(0., moving['turn'])
        self.assertFalse(moving['brake'])

    def test_aligned_five_metre_candidate_has_no_spurious_turn_or_unproved_cruise(self):
        from gui.mods.offline_lan_0922.player_control.traffic import Traffic, body
        position, target = (0., 0., 0.), (0., 0., 30.)
        peer = dict(id=37, position=(0., 0., 12.), yaw=0.,
                    collision_shape=SHAPE, alive=True, team=1)
        traffic = Traffic(body(1, position, 0., SHAPE), [peer])
        self.assertTrue(traffic.clear(0., 5.))
        self.assertFalse(traffic.clear(0., 8.))
        driver = Driver()
        selected = driver.drive(position, 0., 0., target, 0., traffic.clear)
        self.assertEqual('detour_align', selected['recovery_mode'])
        self.assertEqual((0., 0.), (selected['throttle'], selected['turn']))
        self.assertEqual(0., driver.recovery_heading)
        moving = driver.drive(position, 0., 0., target, .1, traffic.clear)
        self.assertGreater(moving['throttle'], 0.)
        self.assertEqual(0., moving['turn'])
        self.assertFalse(moving['brake'])
        self.assertLessEqual(traffic.receipt['reach'], 5.)
        self.assertFalse(traffic.clear(0., 8.))

    def test_actual_navigation_contact_owner_discards_captured_route_detour(self):
        from test_player_navigation_migration import controller, state
        nav = controller('mediumTank')
        self.addCleanup(nav.close)
        route_heading = self.old_heading - .55
        route_target = (self.position[0] + 30. * math.sin(route_heading), .25,
                        self.position[2] + 30. * math.cos(route_heading))
        current = state(36.5, self.position, yaw=route_heading)
        current.update(half_length=SHAPE[1], half_width=SHAPE[0],
                       turn_speed_limit=self.traverse)
        route = nav._drive_goal(current, lambda yaw, reach:
            abs(angle(yaw - self.old_heading)) < .001,
            route_target, ('route', 'opening', 1))
        self.assertEqual('detour_align', route['recovery_mode'])
        self.assertAlmostEqual(self.old_heading, nav.driver.recovery_heading)
        # Retain real Navigation/LocalRoutes/Driver consumption. Only the
        # asynchronous native pathfinder's returned corner is replayed.
        nav.navigator.next_target = lambda *args: self.target
        enemy = dict(id=2130706456, position=(6., .32, 94.))
        current.update(now=37.1, yaw=self.yaw, speed=1.9824850468260873)
        command = nav.drive_to_contact(current, lambda *args: True, enemy)
        self.assertEqual('advance_contact', command['combat_mode'])
        self.assertEqual(0., command['throttle'])
        self.assertTrue(command['brake'])
        current.update(now=37.2, speed=0.)
        aligned = nav.drive_to_contact(current, lambda *args: True, enemy)
        self.assertGreater(aligned['turn'], 0.)
        self.assertEqual(0., aligned['throttle'])
        self.assertIsNone(nav.driver.motion_key)

    def test_captured_changed_goal_rejects_old_heading_like_actual_bot(self):
        driver = Driver()
        route_heading = self.old_heading - .55
        self.admit(driver, self.position, route_heading)
        reference = LocalDriver()
        bot_heading = self.old_heading - FIRST_CANDIDATE_OFFSET
        bot_target = (self.position[0] + 30. * math.sin(bot_heading), .25,
                      self.position[2] + 30. * math.cos(bot_heading))
        reference.drive(1, 0, self.position, bot_heading, 0., .1,
            bot_target, (), lambda yaw, *unused:
            abs(angle(yaw - self.old_heading)) < .001)
        self.assertAlmostEqual(self.old_heading, reference.states[1]['steering_yaw'])
        bot = reference.drive(1, 0, self.position, self.yaw, 0., .1,
            self.target, (), lambda *args: True, turn_speed_limit=self.traverse)
        command = driver.drive(self.position, self.yaw, 0., self.target, .1,
            lambda *args: True, turn_speed_limit=self.traverse)
        self.assertGreater(bot['turn'], 0.)
        self.assertEqual(0., bot['throttle'])
        self.assertGreater(command['turn'], 0.)
        self.assertEqual(0., command['throttle'])

    def test_detour_expires_before_three_metres_and_resolves_live_goal(self):
        driver = Driver()
        target = self.admit(driver)
        retained = driver.drive((0., 0., 0.), .55, 0., target, 1.19,
                                lambda *args: True)
        self.assertGreater(retained['throttle'], 0.)
        self.assertEqual(0., retained['turn'])
        expired = driver.drive((0., 0., 0.), .55, 0., target, 1.21,
                               lambda *args: True)
        self.assertGreater(expired['throttle'], 0.)
        self.assertLess(expired['turn'], 0.)
        self.assertIsNone(driver.recovery_heading)

    def test_retained_detour_requires_its_own_fresh_world_proof(self):
        driver = Driver()
        target = self.admit(driver)
        calls = []
        def clear(heading, reach):
            calls.append((heading, reach))
            return abs(angle(heading - .55)) > .001
        command = driver.drive((0., 0., 0.), .4, 0., target, .1, clear)
        self.assertGreater(command['throttle'], 0.)
        self.assertLess(command['turn'], 0.)
        self.assertTrue(any(abs(angle(heading - .55)) < .001
                            for heading, unused in calls))
        self.assertIsNone(driver.recovery_heading)

    def test_rejected_detour_requests_a_path_refresh_without_claiming_a_stall(self):
        driver = Driver()
        target = self.admit(driver)
        command = driver.drive((0., 0., 0.), .4, 0., target, .1,
            lambda heading, reach: abs(angle(heading-.55)) > .001)
        self.assertGreater(command['throttle'], 0.)
        self.assertTrue(driver.replan)
        self.assertFalse(getattr(driver, 'nonprogress_triggered', True))

    def test_expired_detour_can_renew_only_from_a_current_goal_fan(self):
        driver = Driver()
        target = self.admit(driver)
        calls = []
        def proof(heading, reach):
            calls.append((heading, reach))
            return abs(angle(heading - .55)) < .001
        command = driver.drive((0., 0., 0.), .55, 0., target, 1.21, proof)
        self.assertGreater(command['throttle'], 0.)
        self.assertEqual(0., command['turn'])
        self.assertAlmostEqual(.55, driver.recovery_heading)
        self.assertTrue(any(abs(angle(heading)) < .001 for heading, unused in calls))
        self.assertGreater(driver.receipt['recovery_until'], 1.21)
        self.assertEqual(target, driver.receipt['recovery_target'])

    def test_blocked_detour_cannot_accumulate_another_fan_offset(self):
        driver = Driver()
        target = self.admit(driver)
        # The old implementation tries .55 + .55, despite every branch of
        # the current goal's actual fan being blocked.
        command = driver.drive((0., 0., 0.), .55, 0., target, .1,
            lambda heading, reach: abs(angle(heading - 1.1)) < .001)
        self.assertEqual(0., command['throttle'])
        self.assertEqual(0., command['turn'])
        self.assertTrue(command['brake'])
        self.assertIsNone(driver.recovery_heading)

    def test_completed_detour_uses_live_heading_in_the_same_update(self):
        driver = Driver()
        target = self.admit(driver)
        command = driver.drive((3.1, 0., 0.), .55, 0., target, .1,
                               lambda *args: True)
        self.assertGreater(command['throttle'], 0.)
        self.assertLess(command['turn'], 0.)
        self.assertIsNone(driver.recovery_heading)

    def test_stationary_hold_releases_detour_before_movement_resumes(self):
        driver = Driver()
        target = self.admit(driver)
        held = driver.drive((0., 0., 0.), .55, 0., target, .1,
                            lambda *args: True, hold=True)
        self.assertTrue(held['brake'])
        resumed = driver.drive((0., 0., 0.), .55, 0., target, .2,
                               lambda *args: True)
        self.assertGreater(resumed['throttle'], 0.)
        self.assertLess(resumed['turn'], 0.)


if __name__ == '__main__':
    unittest.main()
